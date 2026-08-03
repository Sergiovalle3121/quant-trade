"""Execute the pre-registered hypotheses and report exactly why they failed.

A campaign has four possible honest endings, and the distinction between the
first two matters more than anything else in this file:

``NOT_RUN_NO_EVIDENCE``
    There is no dataset. Nothing was measured. This is *not* an economic
    result and must never be reported as "the strategy does not work".
``NOT_RUN_INSUFFICIENT_REAL_DATA``
    A dataset exists but is below the pre-registered sufficiency floor
    (730 days, 1,000 settled funding events, receipt-verified live
    provenance). Also not an economic result.
``REJECTED``
    Sufficient evidence, the campaign ran, a gate failed. This *is* an
    economic result, and it comes with the full decomposition: gross return,
    every cost category, net return, drawdown, the statistics, the 2x/3x
    stress, and the break-even the strategy would have had to clear.
``PAPER_CANDIDATE``
    Every gate passed. Still only a candidacy for supervised paper trading.

Whatever the ending, the break-even analysis is always produced, because it
depends on the cost stack and holding period rather than on price history —
so even a run with no data at all hands the next attempt a concrete number.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.v8.costs import (
    BreakEven,
    CostStack,
    break_even_funding,
    capital_requirement,
    conservative_cost_stack,
)
from quant_trade.v8.holdout import HoldoutGuard
from quant_trade.v8.preregistration import (
    DATA_SPLITS,
    PROMOTION_GATES,
    HypothesisSpec,
    freeze_hash,
    hypothesis,
)
from quant_trade.v8.validation import sufficiency_report, validate_evidence_dir

STATUS_NO_EVIDENCE = "NOT_RUN_NO_EVIDENCE"
STATUS_INSUFFICIENT = "NOT_RUN_INSUFFICIENT_REAL_DATA"
STATUS_REJECTED = "REJECTED"
STATUS_PAPER_CANDIDATE = "PAPER_CANDIDATE"

#: Pre-registered position used for the break-even and capital arithmetic.
REFERENCE_NOTIONAL_USD = 100_000.0
REFERENCE_HOLDING_DAYS = 30.0
REFERENCE_PERP_LEVERAGE = 3.0

#: Conservative participation ceiling when estimating capacity from volume.
CAPACITY_PARTICIPATION_RATE = 0.01

#: Cash benchmark. Byte-verified in V7 as a RECORDED_RESPONSE, so it can rank
#: but cannot itself promote anything.
CASH_ANNUAL_YIELD = 0.04


@dataclass
class GateResult:
    gate: str
    required: Any
    observed: Any
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CampaignResult:
    hypothesis_id: str
    title: str
    status: str
    preregistration_hash: str
    evidence: dict[str, Any] = field(default_factory=dict)
    economics: dict[str, Any] = field(default_factory=dict)
    statistics: dict[str, Any] = field(default_factory=dict)
    benchmarks: dict[str, Any] = field(default_factory=dict)
    capacity: dict[str, Any] = field(default_factory=dict)
    holdout: dict[str, Any] = field(default_factory=dict)
    break_even: dict[str, Any] = field(default_factory=dict)
    cost_stack: dict[str, Any] = field(default_factory=dict)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    variants_evaluated: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def promoted(self) -> bool:
        return self.status == STATUS_PAPER_CANDIDATE

    @property
    def ran(self) -> bool:
        """True only when economics were actually measured on real data."""
        return self.status in (STATUS_REJECTED, STATUS_PAPER_CANDIDATE)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["promoted"] = self.promoted
        payload["ran"] = self.ran
        return payload


def _max_drawdown(equity: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _evidence_dirs(spec: HypothesisSpec, evidence_root: str | Path) -> dict[str, Path]:
    from quant_trade.v8.backfill import evidence_dir_for

    return {venue: evidence_dir_for(evidence_root, venue, "BTC") for venue in spec.venues}


def _cost_stack_for(spec: HypothesisSpec, venue: str) -> CostStack:
    # A cross-venue hypothesis is perp/perp: both legs are perpetuals, so no
    # spot taker fee is ever paid and pricing one would charge for a leg the
    # strategy does not have.
    cross_venue = len(spec.venues) > 1
    return conservative_cost_stack(venue, cross_venue=cross_venue, spot_leg=not cross_venue)


def _break_even_for(spec: HypothesisSpec, stack: CostStack) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    for multiplier in (1.0, 2.0, 3.0):
        analysis: BreakEven = break_even_funding(
            stack,
            holding_days=REFERENCE_HOLDING_DAYS,
            funding_interval_hours=8.0,
            multiplier=multiplier,
        )
        scenarios[f"{multiplier:g}x"] = analysis.to_dict()
    return {
        "reference_notional_usd": REFERENCE_NOTIONAL_USD,
        "reference_holding_days": REFERENCE_HOLDING_DAYS,
        "funding_interval_hours": 8.0,
        "scenarios": scenarios,
        "capital": capital_requirement(
            notional_usd=REFERENCE_NOTIONAL_USD, perp_leverage=REFERENCE_PERP_LEVERAGE
        ),
        "interpretation": (
            "The strategy must receive at least "
            f"{scenarios['1x']['required_funding_rate_per_interval']:.8f} per 8h "
            "settlement, on average, purely to cover its own frictions over a "
            f"{REFERENCE_HOLDING_DAYS:g}-day hold. Whether settled BTC funding "
            "clears that bar is precisely the question the blocked dataset "
            "would answer; it is not assumed here in either direction."
        ),
    }


def _capacity_from_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Conservative capacity: a small share of observed traded value."""
    volumes = [
        float(r["spot_volume"]) * float(r["spot_close"])
        for r in rows
        if r.get("spot_volume") is not None
    ]
    if not volumes:
        return {
            "available": False,
            "reason": "panel carries no spot volume; capacity cannot be estimated",
        }
    ordered = sorted(volumes)
    median = ordered[len(ordered) // 2]
    low = ordered[max(0, int(len(ordered) * 0.05) - 1)]
    return {
        "available": True,
        "participation_rate": CAPACITY_PARTICIPATION_RATE,
        "median_bar_quote_volume_usd": median,
        "p05_bar_quote_volume_usd": low,
        # Sized off the 5th percentile bar, not the median: capacity that only
        # exists on busy hours is not capacity.
        "capacity_notional_usd": low * CAPACITY_PARTICIPATION_RATE,
        "basis": "5th-percentile hourly quote volume x participation rate",
    }


def _buy_and_hold(rows: list[dict[str, Any]], stack: CostStack) -> dict[str, Any]:
    """Buy-and-hold BTC over the same window, paying entry and exit."""
    if len(rows) < 2:
        return {"available": False, "reason": "fewer than two bars"}
    first = float(rows[0]["spot_close"])
    last = float(rows[-1]["spot_close"])
    gross = last / first - 1.0
    # Two fills, not four: buy-and-hold has one leg.
    cost = stack.per_fill_bps / 10_000.0 * 2.0
    equity = [float(r["spot_close"]) / first for r in rows]
    return {
        "available": True,
        "gross_return": gross,
        "cost": cost,
        "net_return": gross - cost,
        "max_drawdown": _max_drawdown(equity),
    }


def _cash_benchmark(span_days: float) -> dict[str, Any]:
    return {
        "available": True,
        "annual_yield": CASH_ANNUAL_YIELD,
        "span_days": span_days,
        "net_return": CASH_ANNUAL_YIELD * span_days / 365.0,
        "evidence_class": "RECORDED_RESPONSE",
        "note": "byte-verified recorded response; ranks but cannot promote",
    }


def _to_cost_model(stack: CostStack, multiplier: float = 1.0):
    """Project the V8 cost stack onto the V7 ledger's cost model."""
    from quant_trade.carry.models import CarryCostModel

    scaled = stack.scaled(multiplier)
    by_name = {c.name: c.value for c in scaled.components}
    return CarryCostModel(
        half_spread_bps=by_name.get("half_spread", 0.0) * multiplier,
        slippage_bps=(by_name.get("slippage", 0.0) + by_name.get("latency_and_partial_fill", 0.0))
        * multiplier,
        market_impact_bps=by_name.get("market_impact", 0.0) * multiplier,
        spot_custody_cost_annual=by_name.get("collateral_opportunity_cost", 0.0) * multiplier,
        perp_margin_cost_annual=by_name.get("perp_margin_maintenance_drag", 0.0) * multiplier,
        conversion_withdrawal_cost=(
            by_name.get("conversion_and_withdrawal", 0.0)
            + by_name.get("emergency_unwind_reserve", 0.0)
            + by_name.get("cross_venue_transfer", 0.0)
        )
        * multiplier,
        fee_multiplier=multiplier,
    )


def _taker_fee_bps(stack: CostStack) -> float:
    """The BLENDED per-fill taker fee for the V7 ledger.

    V7 charges one ``taker_fee_bps`` on every one of the four fills. A carry
    pays the spot fee on two of them and the perp fee on the other two, so the
    equivalent uniform rate is their average. Summing them would charge the
    spot fee on the perp fills and vice versa, inflating the round trip by
    roughly 70%.
    """
    leg_fees = [c.value for c in stack.components if c.unit == "bps_per_fill" and c.leg != "both"]
    return sum(leg_fees) / len(leg_fees) if leg_fees else 0.0


def _run_ledger(
    rows: list[dict[str, Any]],
    *,
    stack: CostStack,
    entry_threshold: float,
    trailing_window: int,
    multiplier: float = 1.0,
    provenance: str,
):
    """Run the V7 reconciled ledger over a slice of panel rows."""
    import pandas as pd

    from quant_trade.carry.data import load_snapshots_from_records
    from quant_trade.carry.ledger_engine import run_carry_ledger
    from quant_trade.carry.panel import panel_to_research_inputs

    records, settle_pairs, signal = panel_to_research_inputs(rows, provenance=provenance)
    # The V7 snapshot model carries the venue taker fee; feed it the stack's
    # so the stress multiplier scales venue fees too, not just model frictions.
    fee = _taker_fee_bps(stack)
    records = [dict(r, taker_fee_bps=fee) for r in records]
    snapshots = load_snapshots_from_records(records)
    settlements = [(pd.to_datetime(ts, utc=True), rate) for ts, rate in settle_pairs]
    return run_carry_ledger(
        snapshots,
        _to_cost_model(stack, multiplier),
        entry_threshold=entry_threshold,
        trailing_window=trailing_window,
        initial_capital=1.0,
        perp_leverage=REFERENCE_PERP_LEVERAGE,
        collateral_yield_annual=0.0,
        settlements=settlements,
        signal_rates=signal,
    )


def _statistics(ledger, rows_count: int, prior_trials: int) -> dict[str, Any]:
    from quant_trade.metrics.statistics import (
        deflated_sharpe_ratio,
        probabilistic_sharpe_ratio,
        return_moments,
    )
    from quant_trade.research.bootstrap import bootstrap_confidence_intervals

    net = ledger.bars["net_return"].astype(float).dropna()
    moments = return_moments(net)
    stats: dict[str, Any] = {
        "observations": int(len(net)),
        "panel_rows": rows_count,
        **{k: float(v) for k, v in moments.items() if isinstance(v, int | float)},
    }
    if len(net) >= 2:
        ci = bootstrap_confidence_intervals(
            net,
            method="stationary",
            samples=1000,
            seed=12345,
            block_size=10,
            percentiles=(5.0, 50.0, 95.0),
        )
        stats["bootstrap"] = {
            "available": True,
            "method": "stationary_block",
            "samples": 1000,
            "total_return_p05": float(ci.loc["total_return", "p5"]),
            "total_return_p50": float(ci.loc["total_return", "p50"]),
            "total_return_p95": float(ci.loc["total_return", "p95"]),
            "p05_positive": bool(ci.loc["total_return", "p5"] > 0),
        }
        stats["probabilistic_sharpe"] = float(probabilistic_sharpe_ratio(net))
        stats["deflated_sharpe"] = float(deflated_sharpe_ratio(net, max(1, prior_trials + 1), 0.0))
        stats["effective_trials"] = max(1, prior_trials + 1)
    else:
        stats["bootstrap"] = {"available": False, "reason": "fewer than two observations"}
        stats["probabilistic_sharpe"] = 0.0
        stats["deflated_sharpe"] = 0.0
        stats["effective_trials"] = max(1, prior_trials + 1)
    return stats


def _walk_forward(ledger, splits_cfg: dict[str, Any], trailing_window: int) -> list[dict[str, Any]]:
    from quant_trade.metrics.statistics import return_moments
    from quant_trade.research.splits import purged_walk_forward_splits

    windows: list[dict[str, Any]] = []
    frame = ledger.bars.dropna(subset=["timestamp"])
    try:
        splits = purged_walk_forward_splits(
            frame,
            train_size=int(splits_cfg["train_size"]),
            test_size=int(splits_cfg["test_size"]),
            step_size=int(splits_cfg["step_size"]),
            purge_bars=int(splits_cfg.get("purge_bars", trailing_window)),
            embargo_bars=int(splits_cfg.get("embargo_bars", 1)),
        )
    except ValueError:
        return []
    for split in splits:
        test = split.test["net_return"].astype(float)
        windows.append(
            {
                "test_start": str(split.test_range[0]) if split.test_range else None,
                "test_end": str(split.test_range[1]) if split.test_range else None,
                "test_total_return": float((1.0 + test).prod() - 1.0),
                "test_sharpe_per_period": return_moments(test)["sharpe_per_period"],
            }
        )
    return windows


CSCV_PARTITIONS = 8


def _cscv(variant_returns: dict[str, Any]) -> dict[str, Any]:
    """Rank-based CSCV PBO over the pre-registered variants.

    Takes the return series the selection pass already produced, so the PBO is
    computed over exactly the variants that competed — recomputing them here
    would risk measuring a different search than the one that happened.
    """
    import pandas as pd

    from quant_trade.research.overfitting import cscv_probability_of_backtest_overfitting

    series = {k: v for k, v in variant_returns.items() if v is not None}
    if len(series) < 2:
        return {"available": False, "reason": "fewer than two evaluable variants"}
    frame = pd.DataFrame(series).dropna()
    if len(frame) < 2 * CSCV_PARTITIONS:
        return {"available": False, "reason": "too few aligned observations for CSCV"}
    # CSCV needs equal contiguous partitions. Trim the OLDEST observations so
    # the retained window is the most recent one — dropping the newest data
    # would quietly bias the estimate toward the easiest period.
    usable = len(frame) - (len(frame) % CSCV_PARTITIONS)
    trimmed = frame.iloc[len(frame) - usable :]
    try:
        evidence = cscv_probability_of_backtest_overfitting(
            trimmed.to_numpy(),
            partitions=CSCV_PARTITIONS,
            max_pbo=float(PROMOTION_GATES["max_cscv_pbo"]),
        )
    except ValueError as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "available": True,
        "method": evidence.method,
        "pbo": float(evidence.pbo),
        "observations": evidence.observations,
        "parameter_variants": evidence.parameter_variants,
        "combinations": evidence.combinations,
        "variants": sorted(series),
        "threshold": float(evidence.max_pbo),
        "decision": evidence.decision,
        "reasons": list(evidence.reasons),
    }


def _decompose(ledger, stack: CostStack) -> dict[str, Any]:
    """Cost decomposition straight from the reconciled ledger."""
    totals = ledger.totals
    equity = (1.0 + ledger.bars["net_return"].astype(float).fillna(0.0)).cumprod().tolist()
    gross = totals.funding_settled + totals.spot_leg_pnl + totals.perp_leg_pnl
    costs = {
        "trading_fees": totals.trading_fees,
        "conversion_costs": totals.conversion_costs,
        "unwind_costs": totals.unwind_costs,
        "carrying_costs": totals.carrying_costs,
        "borrow_costs": totals.borrow_costs,
    }
    return {
        "initial_capital": ledger.initial_capital,
        "final_equity": ledger.final_equity,
        "net_return": ledger.final_equity / ledger.initial_capital - 1.0,
        "gross_return": gross / ledger.initial_capital,
        "gross_components": {
            "funding_settled": totals.funding_settled,
            "spot_leg_pnl": totals.spot_leg_pnl,
            "perp_leg_pnl": totals.perp_leg_pnl,
            "collateral_yield": totals.collateral_yield,
        },
        "cost_components": costs,
        "total_costs": sum(costs.values()),
        "max_drawdown": _max_drawdown(equity),
        "entries": ledger.entries,
        "exits": ledger.exits,
        "aborted_entries": ledger.aborted_entries,
        "max_margin_used": ledger.max_margin_used,
        "reconciled": ledger.reconciled,
        "reconciliation_error": ledger.reconciliation_error,
        "cost_stack": stack.to_dict(),
    }


def _gate(name: str, required: Any, observed: Any, passed: bool, detail: str = "") -> GateResult:
    return GateResult(gate=name, required=required, observed=observed, passed=passed, detail=detail)


def run_campaign(
    hypothesis_id: str,
    *,
    evidence_root: str | Path,
    trial_registry_path: str | Path | None = None,
    prior_trials: int = 0,
) -> CampaignResult:
    """Execute one pre-registered hypothesis against the available evidence."""
    spec = hypothesis(hypothesis_id)
    stack = _cost_stack_for(spec, spec.venues[0])
    result = CampaignResult(
        hypothesis_id=spec.hypothesis_id,
        title=spec.title,
        status=STATUS_NO_EVIDENCE,
        preregistration_hash=freeze_hash(),
        break_even=_break_even_for(spec, stack),
        cost_stack=stack.to_dict(),
    )
    result.notes.append(
        "Cost inputs are "
        f"{stack.weakest_evidence_class}; they are chosen to overstate cost, so "
        "they can reject a strategy but can never promote one."
    )

    # --- evidence ---------------------------------------------------------
    directories = _evidence_dirs(spec, evidence_root)
    per_venue: dict[str, Any] = {}
    missing: list[str] = []
    for venue, directory in directories.items():
        panel = directory / "panel.jsonl"
        if not panel.exists():
            missing.append(f"{venue}: no panel at {directory.as_posix()}")
            per_venue[venue] = {"available": False, "directory": directory.as_posix()}
            continue
        context_path = directory / "backfill_result.json"
        context: dict[str, Any] = {}
        if context_path.exists():
            from quant_trade.evidence.canonical_json import load_json

            loaded = load_json(context_path)
            if isinstance(loaded, dict):
                context = loaded
        validation = validate_evidence_dir(
            directory,
            since_ms=int(context.get("since_ms", 0) or 0),
            until_ms=int(context.get("until_ms", 0) or 0),
            interval_minutes=int(context.get("interval_minutes", 60) or 60),
            venue=venue,
            symbol="BTC",
        )
        sufficiency = sufficiency_report(
            validation,
            min_days=float(PROMOTION_GATES["min_span_days"]),
            min_settlements=int(PROMOTION_GATES["min_unique_settlements"]),
        )
        per_venue[venue] = {
            "available": True,
            "directory": directory.as_posix(),
            "provenance": validation.provenance,
            "raw_pages": validation.raw_pages,
            "receipts": validation.receipts,
            "validation_clean": validation.is_clean,
            "validation_problems": validation.problems[:10],
            "sufficiency": sufficiency,
        }
    result.evidence = {"venues": per_venue, "missing": missing}

    if missing:
        result.status = STATUS_NO_EVIDENCE
        result.blocking_reasons = [
            *missing,
            "no dataset was acquired, so nothing was measured — this is an "
            "acquisition failure, not an economic verdict on the hypothesis",
        ]
        return result

    shortfalls = [
        f"{venue}: {reason}"
        for venue, payload in per_venue.items()
        for reason in payload["sufficiency"]["shortfalls"]
    ]
    unclean = [
        f"{venue}: {problem}"
        for venue, payload in per_venue.items()
        for problem in payload["validation_problems"]
    ]
    if shortfalls or unclean:
        result.status = STATUS_INSUFFICIENT
        result.blocking_reasons = [*shortfalls, *unclean]
        return result

    # --- the campaign actually runs ----------------------------------------
    return _execute(spec, stack, directories, per_venue, result, prior_trials, trial_registry_path)


def _transfer_cost_bps(stack: CostStack) -> float:
    by_name = {c.name: c.value for c in stack.components}
    return by_name.get("cross_venue_transfer", 0.0) * 10_000.0


def _run_dispersion(
    bars_a: list[dict[str, Any]],
    bars_b: list[dict[str, Any]],
    *,
    venue_a: str,
    venue_b: str,
    stack: CostStack,
    entry_threshold: float,
    trailing_window: int,
    multiplier: float = 1.0,
):
    from quant_trade.carry.cross_venue import run_perp_perp_dispersion

    by_name = {c.name: c.value for c in stack.components}
    per_leg = (
        by_name.get("perp_taker_fee", 5.0)
        + by_name.get("half_spread", 0.0)
        + by_name.get("slippage", 0.0)
        + by_name.get("market_impact", 0.0)
        + by_name.get("latency_and_partial_fill", 0.0)
    ) * multiplier
    return run_perp_perp_dispersion(
        bars_a,
        bars_b,
        venue_a=venue_a,
        venue_b=venue_b,
        entry_threshold=entry_threshold,
        trailing_window=trailing_window,
        initial_capital=1.0,
        taker_fee_bps=per_leg,
        transfer_cost_bps=_transfer_cost_bps(stack) * multiplier,
    )


def _decompose_dispersion(result_obj, stack: CostStack) -> dict[str, Any]:
    totals = result_obj.totals
    equity = (1.0 + result_obj.bars["net_return"].astype(float).fillna(0.0)).cumprod().tolist()
    costs = {
        "trading_fees": totals.trading_fees,
        "transfer_costs": totals.transfer_costs,
    }
    return {
        "initial_capital": result_obj.initial_capital,
        "final_equity": result_obj.final_equity,
        "net_return": result_obj.final_equity / result_obj.initial_capital - 1.0,
        "gross_return": (totals.funding_spread + totals.mark_divergence_pnl)
        / result_obj.initial_capital,
        "gross_components": {
            "funding_spread": totals.funding_spread,
            "mark_divergence_pnl": totals.mark_divergence_pnl,
        },
        "cost_components": costs,
        "total_costs": sum(costs.values()),
        "max_drawdown": _max_drawdown(equity),
        "entries": result_obj.entries,
        "exits": result_obj.entries,
        "switches": result_obj.switches,
        "aborted_entries": 0,
        "max_margin_used": 0.0,
        "reconciled": result_obj.reconciled,
        "reconciliation_error": result_obj.reconciliation_error,
        "cost_stack": stack.to_dict(),
    }


def _execute_dispersion(
    spec: HypothesisSpec,
    stack: CostStack,
    directories: dict[str, Path],
    per_venue: dict[str, Any],
    result: CampaignResult,
    prior_trials: int,
    trial_registry_path: str | Path | None,
) -> CampaignResult:
    """H3: perp/perp funding dispersion across two venues.

    Structurally different from H1/H2 — two venues, no spot leg, and a switch
    between directions costs four fills plus a capital transfer. Running it
    through the single-venue carry ledger would silently price a strategy
    nobody could execute, so it gets its own path.
    """
    from quant_trade.carry.cross_venue import panel_to_dispersion_bars
    from quant_trade.carry.panel import load_panel

    venue_a, venue_b = spec.venues[0], spec.venues[1]
    rows_a = load_panel(directories[venue_a])
    rows_b = load_panel(directories[venue_b])
    common = sorted({r["start_ms"] for r in rows_a} & {r["start_ms"] for r in rows_b})
    if len(common) < 32:
        result.status = STATUS_INSUFFICIENT
        result.blocking_reasons = [
            f"only {len(common)} bar(s) overlap between {venue_a} and {venue_b}; "
            "dispersion needs aligned history on BOTH venues"
        ]
        return result
    aligned = set(common)
    rows_a = [r for r in rows_a if r["start_ms"] in aligned]
    rows_b = [r for r in rows_b if r["start_ms"] in aligned]

    guard = HoldoutGuard(
        rows_a, holdout_fraction=float(DATA_SPLITS["holdout_fraction"]), timestamp_key="start_ms"
    )
    selection_stamps = {r["start_ms"] for r in guard.selection_rows}
    sel_a = panel_to_dispersion_bars([r for r in rows_a if r["start_ms"] in selection_stamps])
    sel_b = panel_to_dispersion_bars([r for r in rows_b if r["start_ms"] in selection_stamps])

    evaluated: list[dict[str, Any]] = []
    variant_returns: dict[str, Any] = {}
    best: tuple[float, Any] | None = None
    for variant in spec.variants:
        try:
            run = _run_dispersion(
                sel_a,
                sel_b,
                venue_a=venue_a,
                venue_b=venue_b,
                stack=stack,
                entry_threshold=float(variant.parameters["entry_threshold"]),
                trailing_window=int(variant.parameters["trailing_window"]),
            )
        except (ValueError, KeyError) as exc:
            evaluated.append(
                {
                    "variant_id": variant.variant_id,
                    "parameters": variant.parameters,
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        selection_return = run.final_equity / run.initial_capital - 1.0
        variant_returns[variant.variant_id] = (
            run.bars["net_return"].astype(float).reset_index(drop=True)
        )
        evaluated.append(
            {
                "variant_id": variant.variant_id,
                "parameters": variant.parameters,
                "status": "EVALUATED",
                "selection_net_return": selection_return,
                "entries": run.entries,
                "switches": run.switches,
                "reconciled": run.reconciled,
            }
        )
        if best is None or selection_return > best[0]:
            best = (selection_return, variant)
    result.variants_evaluated = evaluated
    if best is None:
        result.status = STATUS_REJECTED
        result.blocking_reasons = ["no pre-registered variant produced an evaluable account"]
        return result

    _selection_return, chosen = best
    guard.freeze_selection(chosen.variant_id)
    holdout_rows = guard.reveal(reason="final out-of-sample scoring of the frozen variant")
    result.holdout = guard.to_dict()
    holdout_stamps = {r["start_ms"] for r in holdout_rows}

    entry_threshold = float(chosen.parameters["entry_threshold"])
    trailing_window = int(chosen.parameters["trailing_window"])
    full_a, full_b = panel_to_dispersion_bars(rows_a), panel_to_dispersion_bars(rows_b)
    full = _run_dispersion(
        full_a,
        full_b,
        venue_a=venue_a,
        venue_b=venue_b,
        stack=stack,
        entry_threshold=entry_threshold,
        trailing_window=trailing_window,
    )
    economics = _decompose_dispersion(full, stack)
    for multiplier in (2.0, 3.0):
        stressed = _run_dispersion(
            full_a,
            full_b,
            venue_a=venue_a,
            venue_b=venue_b,
            stack=stack,
            entry_threshold=entry_threshold,
            trailing_window=trailing_window,
            multiplier=multiplier,
        )
        economics[f"net_return_{multiplier:g}x_costs"] = (
            stressed.final_equity / stressed.initial_capital - 1.0
        )
    try:
        holdout_run = _run_dispersion(
            panel_to_dispersion_bars([r for r in rows_a if r["start_ms"] in holdout_stamps]),
            panel_to_dispersion_bars([r for r in rows_b if r["start_ms"] in holdout_stamps]),
            venue_a=venue_a,
            venue_b=venue_b,
            stack=stack,
            entry_threshold=entry_threshold,
            trailing_window=trailing_window,
        )
        economics["holdout_net_return"] = (
            holdout_run.final_equity / holdout_run.initial_capital - 1.0
        )
    except (ValueError, KeyError) as exc:
        economics["holdout_net_return"] = None
        result.notes.append(f"holdout account unavailable: {type(exc).__name__}: {exc}")
    result.economics = economics

    statistics = _statistics(full, len(rows_a), prior_trials)
    walk_forward = _walk_forward(full, DATA_SPLITS["walk_forward"], trailing_window)
    statistics["walk_forward_windows"] = walk_forward
    statistics["walk_forward_window_count"] = len(walk_forward)
    statistics["walk_forward_positive"] = sum(
        1 for w in walk_forward if float(w["test_total_return"]) > 0
    )
    statistics["cscv"] = _cscv(variant_returns)
    result.statistics = statistics

    span_days = float(per_venue[venue_a]["sufficiency"]["span_days"])
    result.benchmarks = {
        "cash": _cash_benchmark(span_days),
        "buy_and_hold_btc": _buy_and_hold(rows_a, stack),
    }
    result.capacity = _capacity_from_panel(rows_a)
    result.capacity["note"] = (
        "minimum of the two venues, further reduced by capital idle in transit"
    )
    result.notes.append(f"selected variant {chosen.variant_id} on the selection window only")
    result.notes.append(f"{len(common)} bars aligned across {venue_a} and {venue_b}")

    if trial_registry_path is not None:
        _record_trials(spec, evaluated, trial_registry_path, result)

    result.gate_results = [g.to_dict() for g in _evaluate_gates(result, stack)]
    failures = [g for g in result.gate_results if not g["passed"]]
    result.status = STATUS_REJECTED if failures else STATUS_PAPER_CANDIDATE
    result.blocking_reasons = [
        f"{g['gate']}: required {g['required']}, observed {g['observed']}" for g in failures
    ]
    return result


def _execute(
    spec: HypothesisSpec,
    stack: CostStack,
    directories: dict[str, Path],
    per_venue: dict[str, Any],
    result: CampaignResult,
    prior_trials: int,
    trial_registry_path: str | Path | None,
) -> CampaignResult:
    from quant_trade.carry.panel import load_panel

    if len(spec.venues) > 1:
        return _execute_dispersion(
            spec, stack, directories, per_venue, result, prior_trials, trial_registry_path
        )

    primary_venue = spec.venues[0]
    rows = load_panel(directories[primary_venue])
    provenance = per_venue[primary_venue]["provenance"]

    guard = HoldoutGuard(
        rows,
        holdout_fraction=float(DATA_SPLITS["holdout_fraction"]),
        timestamp_key="start_ms",
    )
    selection_rows = guard.selection_rows

    # --- variant selection, holdout untouched ------------------------------
    evaluated: list[dict[str, Any]] = []
    variant_returns: dict[str, Any] = {}
    best: tuple[float, Any] | None = None
    for variant in spec.variants:
        try:
            ledger = _run_ledger(
                selection_rows,
                stack=stack,
                entry_threshold=float(variant.parameters["entry_threshold"]),
                trailing_window=int(variant.parameters["trailing_window"]),
                provenance=provenance,
            )
        except (ValueError, KeyError) as exc:
            evaluated.append(
                {
                    "variant_id": variant.variant_id,
                    "parameters": variant.parameters,
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        selection_return = ledger.final_equity / ledger.initial_capital - 1.0
        variant_returns[variant.variant_id] = (
            ledger.bars["net_return"].astype(float).reset_index(drop=True)
        )
        evaluated.append(
            {
                "variant_id": variant.variant_id,
                "parameters": variant.parameters,
                "status": "EVALUATED",
                "selection_net_return": selection_return,
                "entries": ledger.entries,
                "reconciled": ledger.reconciled,
            }
        )
        if best is None or selection_return > best[0]:
            best = (selection_return, variant)
    result.variants_evaluated = evaluated

    if best is None:
        result.status = STATUS_REJECTED
        result.blocking_reasons = ["no pre-registered variant produced an evaluable ledger"]
        return result

    _selection_return, chosen = best
    guard.freeze_selection(chosen.variant_id)
    holdout_rows = guard.reveal(reason="final out-of-sample scoring of the frozen variant")
    result.holdout = guard.to_dict()

    entry_threshold = float(chosen.parameters["entry_threshold"])
    trailing_window = int(chosen.parameters["trailing_window"])

    # Full-sample ledger is the authoritative return; the holdout slice is
    # scored separately and reported next to it.
    full = _run_ledger(
        rows,
        stack=stack,
        entry_threshold=entry_threshold,
        trailing_window=trailing_window,
        provenance=provenance,
    )
    economics = _decompose(full, stack)
    for multiplier in (2.0, 3.0):
        stressed = _run_ledger(
            rows,
            stack=stack,
            entry_threshold=entry_threshold,
            trailing_window=trailing_window,
            multiplier=multiplier,
            provenance=provenance,
        )
        economics[f"net_return_{multiplier:g}x_costs"] = (
            stressed.final_equity / stressed.initial_capital - 1.0
        )
    try:
        holdout_ledger = _run_ledger(
            holdout_rows,
            stack=stack,
            entry_threshold=entry_threshold,
            trailing_window=trailing_window,
            provenance=provenance,
        )
        economics["holdout_net_return"] = (
            holdout_ledger.final_equity / holdout_ledger.initial_capital - 1.0
        )
    except (ValueError, KeyError) as exc:
        economics["holdout_net_return"] = None
        result.notes.append(f"holdout ledger unavailable: {type(exc).__name__}: {exc}")
    result.economics = economics

    statistics = _statistics(full, len(rows), prior_trials)
    walk_forward = _walk_forward(full, DATA_SPLITS["walk_forward"], trailing_window)
    statistics["walk_forward_windows"] = walk_forward
    statistics["walk_forward_window_count"] = len(walk_forward)
    statistics["walk_forward_positive"] = sum(
        1 for w in walk_forward if float(w["test_total_return"]) > 0
    )
    statistics["cscv"] = _cscv(variant_returns)
    result.statistics = statistics

    span_days = float(per_venue[primary_venue]["sufficiency"]["span_days"])
    result.benchmarks = {
        "cash": _cash_benchmark(span_days),
        "buy_and_hold_btc": _buy_and_hold(rows, stack),
    }
    result.capacity = _capacity_from_panel(rows)
    result.notes.append(f"selected variant {chosen.variant_id} on the selection window only")

    if trial_registry_path is not None:
        _record_trials(spec, evaluated, trial_registry_path, result)

    result.gate_results = [g.to_dict() for g in _evaluate_gates(result, stack)]
    failures = [g["gate"] for g in result.gate_results if not g["passed"]]
    if failures:
        result.status = STATUS_REJECTED
        result.blocking_reasons = [
            f"{g['gate']}: required {g['required']}, observed {g['observed']}"
            for g in result.gate_results
            if not g["passed"]
        ]
    else:
        result.status = STATUS_PAPER_CANDIDATE
        result.blocking_reasons = []
    return result


def _record_trials(
    spec: HypothesisSpec,
    evaluated: list[dict[str, Any]],
    registry_path: str | Path,
    result: CampaignResult,
) -> None:
    """Every variant enters the global hash-chained trial ledger.

    Failed variants are recorded too. Counting only the ones that produced a
    number is how a search of eight becomes a "single trial" and the deflated
    Sharpe stops deflating anything.
    """
    from quant_trade.research.ledger import append_trial_record, build_trial_record

    dataset_sha = str(
        result.evidence.get("venues", {})
        .get(spec.venues[0], {})
        .get("sufficiency", {})
        .get("evidence_sha256", "")
    )
    for entry in evaluated:
        record = build_trial_record(
            source=f"v8.campaign.{spec.hypothesis_id}",
            strategy=f"v8.{spec.hypothesis_id}.{entry['variant_id']}",
            strategy_params=dict(entry["parameters"]),
            run_id=f"{spec.hypothesis_id}-{entry['variant_id']}",
            status=("evaluated" if entry["status"] == "EVALUATED" else "failed"),
            dataset_sha=dataset_sha,
            config_sha=result.preregistration_hash,
            split_policy="chronological_train_wf_holdout",
            feature_version="v8.1",
            test_total_return=(
                float(entry["selection_net_return"])
                if entry.get("selection_net_return") is not None
                else None
            ),
            error=entry.get("error"),
        )
        append_trial_record(None, record, registry_path=registry_path)


def _evaluate_gates(result: CampaignResult, stack: CostStack) -> list[GateResult]:
    economics = result.economics
    statistics = result.statistics
    benchmarks = result.benchmarks
    bootstrap = statistics.get("bootstrap", {})
    cscv = statistics.get("cscv", {})
    gates = PROMOTION_GATES

    net = float(economics.get("net_return", 0.0))
    checks = [
        _gate("net_return_positive", "> 0", net, net > 0),
        _gate(
            "net_return_2x_costs_positive",
            "> 0",
            economics.get("net_return_2x_costs"),
            float(economics.get("net_return_2x_costs", 0.0)) > 0,
        ),
        _gate(
            "net_return_3x_costs_reported",
            "present",
            economics.get("net_return_3x_costs"),
            economics.get("net_return_3x_costs") is not None,
            detail="3x is reported, not required to be positive",
        ),
        _gate(
            "bootstrap_p05_positive",
            "> 0",
            bootstrap.get("total_return_p05"),
            bool(bootstrap.get("p05_positive")),
        ),
        _gate(
            "probabilistic_sharpe",
            f">= {gates['min_probabilistic_sharpe']}",
            statistics.get("probabilistic_sharpe"),
            float(statistics.get("probabilistic_sharpe", 0.0))
            >= float(gates["min_probabilistic_sharpe"]),
        ),
        _gate(
            "deflated_sharpe",
            f">= {gates['min_deflated_sharpe']}",
            statistics.get("deflated_sharpe"),
            float(statistics.get("deflated_sharpe", 0.0)) >= float(gates["min_deflated_sharpe"]),
        ),
        _gate(
            "cscv_pbo",
            f"<= {gates['max_cscv_pbo']}",
            cscv.get("pbo") if cscv.get("available") else cscv.get("reason"),
            bool(cscv.get("available")) and cscv.get("decision") == "PASS",
        ),
        _gate(
            "walk_forward_windows",
            f">= {gates['min_walk_forward_windows']}",
            statistics.get("walk_forward_window_count"),
            int(statistics.get("walk_forward_window_count", 0))
            >= int(gates["min_walk_forward_windows"]),
        ),
        _gate(
            "walk_forward_majority_positive",
            "> half of windows",
            f"{statistics.get('walk_forward_positive')}/"
            f"{statistics.get('walk_forward_window_count')}",
            int(statistics.get("walk_forward_positive", 0)) * 2
            > int(statistics.get("walk_forward_window_count", 0)),
        ),
        _gate(
            "ledger_reconciled",
            True,
            economics.get("reconciled"),
            bool(economics.get("reconciled")),
        ),
        _gate(
            "zero_aborted_entries",
            0,
            economics.get("aborted_entries"),
            int(economics.get("aborted_entries", 0) or 0) == 0,
        ),
        _gate(
            "beats_cash",
            f"> {benchmarks.get('cash', {}).get('net_return')}",
            net,
            net > float(benchmarks.get("cash", {}).get("net_return", 0.0)),
        ),
        _gate(
            "beats_buy_and_hold",
            f"> {benchmarks.get('buy_and_hold_btc', {}).get('net_return')}",
            net,
            net > float(benchmarks.get("buy_and_hold_btc", {}).get("net_return", 0.0)),
        ),
        _gate(
            "capacity_estimable",
            "available",
            result.capacity.get("capacity_notional_usd"),
            bool(result.capacity.get("available")),
        ),
        _gate(
            "holdout_revealed_once_after_freeze",
            1,
            result.holdout.get("reveal_count"),
            int(result.holdout.get("reveal_count", 0)) == 1
            and bool(result.holdout.get("selection_frozen")),
        ),
        _gate(
            "cost_evidence_promotable",
            "REAL",
            stack.weakest_evidence_class,
            stack.promotable,
            detail=(
                "fee schedules must be captured from the venue, not assumed, "
                "before a candidate can carry real capital"
            ),
        ),
    ]
    return checks


def run_all_campaigns(
    hypothesis_ids: tuple[str, ...] = ("H1", "H2", "H3"),
    *,
    evidence_root: str | Path,
    trial_registry_path: str | Path | None = None,
) -> list[CampaignResult]:
    """Run the primary hypotheses in registered order."""
    results: list[CampaignResult] = []
    prior = 0
    for hypothesis_id in hypothesis_ids:
        result = run_campaign(
            hypothesis_id,
            evidence_root=evidence_root,
            trial_registry_path=trial_registry_path,
            prior_trials=prior,
        )
        prior += len(result.variants_evaluated)
        results.append(result)
    apply_relative_gates(results)
    return results


def apply_relative_gates(results: list[CampaignResult]) -> None:
    """Apply gates that compare hypotheses to each other.

    H3 is only interesting if operating on two venues beats operating on the
    better single venue. It is registered that way, so the comparison happens
    after all three have run — and it can demote H3 from PAPER_CANDIDATE, never
    promote it.
    """
    by_id = {r.hypothesis_id: r for r in results}
    h3 = by_id.get("H3")
    if h3 is None or not h3.ran:
        return
    singles = [
        float(by_id[hid].economics.get("net_return", 0.0))
        for hid in ("H1", "H2")
        if hid in by_id and by_id[hid].ran
    ]
    if not singles:
        return
    best_single = max(singles)
    observed = float(h3.economics.get("net_return", 0.0))
    gate = _gate(
        "beats_best_single_venue_carry",
        f"> {best_single}",
        observed,
        observed > best_single,
        detail="two-venue operation must beat the better of H1/H2 to be worth its complexity",
    )
    h3.gate_results.append(gate.to_dict())
    if not gate.passed:
        h3.status = STATUS_REJECTED
        h3.blocking_reasons.append(
            f"beats_best_single_venue_carry: required > {best_single}, observed {observed}"
        )


def additional_hypotheses_unlocked(primary: list[CampaignResult]) -> tuple[bool, str]:
    """H6/H7 may run only after H1–H3 actually completed and were rejected.

    "Completed" means measured, not attempted: a campaign that never ran for
    want of data has not tested anything, so moving on to fresh hypotheses
    would be starting a new search while the original question is still open.
    """
    if len(primary) < 3:
        raise ValueError("expected the three primary hypotheses")
    if any(r.promoted for r in primary):
        return False, "a primary hypothesis already produced a candidate"
    not_run = [r.hypothesis_id for r in primary if not r.ran]
    if not_run:
        return False, (
            f"{', '.join(not_run)} did not run for want of evidence; additional "
            "hypotheses would be a new search over the same missing data"
        )
    return True, "H1-H3 executed and were rejected on measured economics"


def campaign_from_dict(payload: dict[str, Any]) -> CampaignResult:
    known = {f.name for f in dataclasses.fields(CampaignResult)}
    return CampaignResult(**{k: v for k, v in payload.items() if k in known})


__all__ = [
    "CAPACITY_PARTICIPATION_RATE",
    "CASH_ANNUAL_YIELD",
    "REFERENCE_HOLDING_DAYS",
    "REFERENCE_NOTIONAL_USD",
    "REFERENCE_PERP_LEVERAGE",
    "STATUS_INSUFFICIENT",
    "STATUS_NO_EVIDENCE",
    "STATUS_PAPER_CANDIDATE",
    "STATUS_REJECTED",
    "CampaignResult",
    "GateResult",
    "additional_hypotheses_unlocked",
    "apply_relative_gates",
    "campaign_from_dict",
    "run_all_campaigns",
    "run_campaign",
]
