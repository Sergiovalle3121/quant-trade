"""Cash-and-carry research campaign: causal TOTAL-return backtest + honest verdict.

Builds a causal two-leg return series from read-only snapshots — funding P&L,
spot/perp leg P&L (basis convergence), collateral yield, minus the full cost
stack — computes bootstrap, purged walk-forward, cost-stress, and margin-path
evidence, records a trial-ledger entry, and emits one of exactly three
outcomes:

- ``NOT_RUN_INSUFFICIENT_REAL_DATA`` — synthetic data, or real data below the
  minimum funding events / span / walk-forward windows. Insufficiency is never
  presented as an economic verdict.
- ``REJECTED`` — sufficient real data, but an economic or robustness gate failed.
- ``PAPER_CANDIDATE`` — every campaign gate passed. Still only a candidacy:
  advancing requires :func:`evaluate_carry_promotion`, which reopens the
  artifacts and recomputes. Nothing here ever authorizes real money.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.carry.capital import capital_required, simulate_perp_margin_path
from quant_trade.carry.data import (
    load_snapshots_from_json,
    synthetic_funding_snapshots,
)
from quant_trade.carry.economics import _round_trip_friction, evaluate_carry
from quant_trade.carry.models import (
    CarryCostModel,
    CarryPolicy,
    CarryPosition,
    CarrySnapshot,
)
from quant_trade.evidence.canonical_json import atomic_write_json, canonical_dumps
from quant_trade.evidence.manifest import (
    DatasetManifest,
    build_dataset_manifest,
    build_inline_manifest,
)
from quant_trade.metrics.statistics import probabilistic_sharpe_ratio, return_moments
from quant_trade.research.bootstrap import bootstrap_confidence_intervals
from quant_trade.research.ledger import append_trial_record, build_trial_record, sha256_hex
from quant_trade.research.splits import purged_walk_forward_splits


@dataclass
class CarryCampaignResult:
    decision: str  # "GO" | "NO-GO" | "NOT-RUN"
    reasons: list[str]
    data_source: str
    net_return_series: pd.DataFrame
    metrics: dict[str, Any]
    bootstrap: dict[str, Any]
    walk_forward: list[dict[str, Any]]
    per_snapshot_go_fraction: float
    dataset_manifest: dict[str, Any] = field(default_factory=dict)
    # the stateful ledger IS the promotable P&L path (V6-A): its totals,
    # reconciliation verdict and cash-flow journal ride with every campaign
    ledger_summary: dict[str, Any] = field(default_factory=dict)
    ledger_cashflows: list[dict[str, Any]] = field(default_factory=list)


def carry_campaign_returns(
    snapshots: list[CarrySnapshot],
    costs: CarryCostModel,
    *,
    entry_threshold: float,
    trailing_window: int,
    collateral_yield_annual: float = 0.0,
    settlements: list[tuple[Any, float]] | None = None,
) -> pd.DataFrame:
    """DIAGNOSTIC ONLY — NON-PROMOTABLE aggregate return arithmetic.

    The promotable P&L path is :func:`quant_trade.carry.ledger_engine.
    run_carry_ledger` (an explicit reconciled balance sheet); this helper
    survives only as a cross-check and for lightweight diagnostics. Nothing
    downstream may promote a campaign from these numbers.

    Position at ``t`` is decided from the trailing mean of realized funding up
    to ``t`` (never future funding). For every held interval the series books:

    - ``funding_pnl``  — the interval's realized funding on the short perp;
    - ``spot_leg_pnl`` — long-spot mark-to-market;
    - ``perp_leg_pnl`` — short-perp mark-to-market (variation margin);
    - ``basis_pnl``    — their sum: pure basis convergence/divergence P&L,
      which a matched-quantity hedge exposes while directional moves cancel;
    - ``collateral_yield`` — configurable yield on immobilized collateral;
    - minus per-turn transaction cost and per-interval carrying cost.

    ``net_return`` is the sum of all components per unit of hedge notional.

    Funding accrual semantics: when ``settlements`` is given (collector
    datasets), funding P&L accrues ONLY from settled funding events falling
    causally in each bar's interval ``(t[i-1], t[i]]`` — a poll observation
    never pays. When ``settlements`` is ``None`` (legacy synthetic/json
    generators emitting one snapshot per funding interval), each snapshot's
    rate is that interval's settlement, as before. The quoted per-snapshot rate
    always remains available as SIGNAL input.
    """
    ordered = sorted(snapshots, key=lambda s: s.captured_at_utc)
    funding = [s.realized_funding_rate for s in ordered]
    bar_times = [pd.to_datetime(s.captured_at_utc, utc=True, errors="coerce") for s in ordered]
    settled_in_bar: list[float] | None = None
    if settlements is not None:
        settled_sorted = sorted(
            ((pd.to_datetime(ts, utc=True), float(rate)) for ts, rate in settlements),
            key=lambda x: x[0],
        )
        settled_in_bar = []
        for i in range(len(ordered)):
            lo = bar_times[i - 1] if i > 0 else None
            hi = bar_times[i]
            total = 0.0
            for ts, rate in settled_sorted:
                if pd.isna(hi):
                    continue
                if (lo is None or ts > lo) and ts <= hi:
                    total += rate
            settled_in_bar.append(total)
    spot = [s.spot_price for s in ordered]
    perp = [s.perp_mark_price for s in ordered]
    round_trip = _round_trip_friction(ordered[0], costs) if ordered else 0.0
    turn_cost = round_trip / 2.0  # entering or exiting is half a round trip
    intervals_per_year = ordered[0].funding_intervals_per_year if ordered else 1.0
    annual_carry_cost = costs.spot_custody_cost_annual + costs.perp_margin_cost_annual
    per_interval_carry_cost = annual_carry_cost / intervals_per_year
    per_interval_collateral_yield = collateral_yield_annual / intervals_per_year

    rows: list[dict[str, Any]] = []
    prev_position = 0.0
    for i in range(len(ordered)):
        if i < trailing_window:
            position = 0.0  # warm-up: no causal signal yet
        else:
            trailing_mean = sum(funding[i - trailing_window : i]) / trailing_window
            position = 1.0 if trailing_mean > entry_threshold else 0.0
        accrued_rate = settled_in_bar[i] if settled_in_bar is not None else funding[i]
        funding_pnl = prev_position * accrued_rate
        if prev_position > 0 and i > 0:
            spot_leg = prev_position * (spot[i] - spot[i - 1]) / spot[i - 1]
            perp_leg = prev_position * (perp[i - 1] - perp[i]) / spot[i - 1]
        else:
            spot_leg = 0.0
            perp_leg = 0.0
        basis_pnl = spot_leg + perp_leg
        collateral = prev_position * per_interval_collateral_yield
        turn = abs(position - prev_position) * turn_cost
        carry = position * per_interval_carry_cost
        rows.append(
            {
                "timestamp": pd.to_datetime(ordered[i].captured_at_utc, utc=True, errors="coerce"),
                "symbol": ordered[i].symbol,
                "funding": funding[i],
                "position": position,
                "funding_pnl": funding_pnl,
                "spot_leg_pnl": spot_leg,
                "perp_leg_pnl": perp_leg,
                "basis_pnl": basis_pnl,
                "collateral_yield": collateral,
                "turn_cost": turn,
                "carry_cost": carry,
                "net_return": funding_pnl + basis_pnl + collateral - turn - carry,
            }
        )
        prev_position = position
    return pd.DataFrame(rows)


def _load_snapshots(
    config: dict[str, Any],
) -> tuple[list[CarrySnapshot], DatasetManifest, list[tuple[Any, float]] | None]:
    """Load snapshots, bind them by bytes, and surface funding settlements.

    The third element is the settled-funding event list for settlement-causal
    accrual. It is ``None`` for the legacy synthetic/json paths, whose
    generators emit exactly one snapshot per funding interval (each snapshot IS
    that interval's settlement); collector JSONL datasets accrue funding ONLY
    from explicit settlement events.
    """
    data_cfg = config.get("data", {})
    source = str(data_cfg.get("source", "synthetic"))
    if source == "synthetic":
        snapshots = synthetic_funding_snapshots(**data_cfg.get("synthetic", {}))
        manifest = build_inline_manifest(
            [s.to_dict() for s in snapshots],
            data_source="synthetic",
            source_name="synthetic_funding_snapshots",
            provenance_notes="deterministic generator; not market data",
        )
        return snapshots, manifest, None
    if source == "json":
        path = data_cfg["path"]
        snapshots = load_snapshots_from_json(path)
        manifest = build_dataset_manifest(path)
        return snapshots, manifest, None
    if source == "jsonl_observations":
        from quant_trade.carry.data import load_snapshots_from_records
        from quant_trade.carry.instruments import check_clock_skew, require_single_identity
        from quant_trade.carry.store import (
            extract_settlement_events,
            observations_to_snapshot_records,
            read_store,
        )
        from quant_trade.evidence.manifest import build_file_manifest

        path = data_cfg["path"]
        stored = read_store(path)
        if stored.quarantined:
            raise ValueError(
                f"collected dataset {path} has {len(stored.quarantined)} quarantined "
                "line(s); repair or re-collect before running research"
            )
        # One campaign = one full economic identity. Mixed identities fail
        # closed — the opportunity scanner is the explicit allocator.
        require_single_identity(stored.records)
        skewed = [p for r in stored.records if (p := check_clock_skew(r)) is not None]
        if skewed:
            raise ValueError(
                f"{len(skewed)} record(s) with excessive clock skew or bad "
                f"timestamps; first: {skewed[0]}"
            )
        records = observations_to_snapshot_records(stored.records)
        if not records:
            raise ValueError("dataset contains no quote observations")
        snapshots = load_snapshots_from_records(records)
        settlements = [
            (
                pd.to_datetime(str(r["exchange_timestamp_utc"]), utc=True),
                float(r["realized_funding_rate"]),
            )
            for r in extract_settlement_events(stored.records)
        ]
        manifest = build_file_manifest(
            path, records, provenance_notes="point-in-time collector JSONL"
        )
        return snapshots, manifest, settlements
    raise ValueError(
        f"unsupported carry data source {source!r}; "
        "use 'synthetic', 'json', or 'jsonl_observations'"
    )


def run_carry_research(config: dict[str, Any]) -> CarryCampaignResult:
    """Run a pre-registered carry campaign and return the verdict + evidence."""
    snapshots, manifest, settlements = _load_snapshots(config)
    if not snapshots:
        raise ValueError("no snapshots to evaluate")
    # Provenance comes from the FULL dataset via the manifest ("mixed" when
    # sources disagree) — never inferred from the first record alone.
    data_source = manifest.data_source
    costs = CarryCostModel(**config.get("costs", {}))
    policy = CarryPolicy(**config.get("policy", {}))
    position = CarryPosition(
        **config.get("position", {"notional_usd": 100_000, "holding_days": 30})
    )
    signal_cfg = config.get("signal", {})
    entry_threshold = float(signal_cfg.get("entry_threshold", 0.0001))
    trailing_window = int(signal_cfg.get("trailing_window", 6))
    collateral_yield_annual = float(
        config.get("capital", {}).get("collateral_yield_annual", 0.0)
    )

    # THE promotable P&L path: the stateful, reconciled ledger (V6-A). The
    # legacy aggregate arithmetic remains available only as a diagnostic.
    from quant_trade.carry.ledger_engine import run_carry_ledger

    ledger = run_carry_ledger(
        snapshots,
        costs,
        entry_threshold=entry_threshold,
        trailing_window=trailing_window,
        initial_capital=1.0,
        perp_leverage=position.perp_leverage,
        collateral_yield_annual=collateral_yield_annual,
        settlements=settlements,
    )
    if not ledger.reconciled:
        raise ValueError(
            f"ledger failed reconciliation by {ledger.reconciliation_error!r}; "
            "refusing to produce campaign evidence from unbalanced accounts"
        )
    returns = ledger.bars
    net = returns["net_return"].astype(float)
    active = net[returns["position"] > 0]
    moments = return_moments(net)
    total_return = float(ledger.final_equity / ledger.initial_capital - 1.0)

    # per-snapshot economic GO fraction (diagnostic, not the campaign verdict)
    go = [evaluate_carry(s, position, costs, policy).decision == "GO" for s in snapshots]
    go_fraction = float(sum(go) / len(go)) if go else 0.0

    # bootstrap CI on the net return series (fail-closed on thin samples)
    bootstrap: dict[str, Any]
    if len(net.dropna()) >= 2:
        ci = bootstrap_confidence_intervals(
            net.dropna(), method="stationary", samples=1000, seed=12345, block_size=10
        )
        bootstrap = {
            "available": True,
            "method": "stationary",
            "total_return": {
                "lower": float(ci.loc["total_return", "p2.5"]),
                "upper": float(ci.loc["total_return", "p97.5"]),
            },
            "total_return_lower_positive": bool(ci.loc["total_return", "p2.5"] > 0),
        }
    else:
        bootstrap = {"available": False, "reason": "insufficient observations"}

    # purged walk-forward over timestamps
    walk_forward: list[dict[str, Any]] = []
    wf_cfg = config.get("walk_forward", {"train_size": 30, "test_size": 15, "step_size": 15})
    try:
        splits = purged_walk_forward_splits(
            returns.dropna(subset=["timestamp"]),
            train_size=int(wf_cfg["train_size"]),
            test_size=int(wf_cfg["test_size"]),
            step_size=int(wf_cfg["step_size"]),
            purge_bars=int(wf_cfg.get("purge_bars", trailing_window)),
            embargo_bars=int(wf_cfg.get("embargo_bars", 1)),
        )
        for split in splits:
            test_ret = split.test["net_return"].astype(float)
            walk_forward.append(
                {
                    "test_start": str(split.test_range[0]) if split.test_range else None,
                    "test_end": str(split.test_range[1]) if split.test_range else None,
                    "test_total_return": float((1.0 + test_ret).prod() - 1.0),
                    "test_sharpe_per_period": return_moments(test_ret)["sharpe_per_period"],
                }
            )
    except ValueError:
        walk_forward = []

    # cost stress: rerun the SAME ledger — same settlements, same signals,
    # same fills — multiplying the ENTIRE cost stack (V6-C). fee_multiplier
    # scales the venue's taker_fee_bps inside the friction; every model-side
    # component is multiplied explicitly. The multiplier can never change the
    # strategy, only what it costs.
    def _stressed_total(multiple: float) -> float:
        stressed_costs = dataclasses.replace(
            costs,
            half_spread_bps=costs.half_spread_bps * multiple,
            slippage_bps=costs.slippage_bps * multiple,
            market_impact_bps=costs.market_impact_bps * multiple,
            spot_custody_cost_annual=costs.spot_custody_cost_annual * multiple,
            perp_margin_cost_annual=costs.perp_margin_cost_annual * multiple,
            conversion_withdrawal_cost=costs.conversion_withdrawal_cost * multiple,
            fee_multiplier=costs.fee_multiplier * multiple,  # venue taker_fee_bps
        )
        stressed = run_carry_ledger(
            snapshots,
            stressed_costs,
            entry_threshold=entry_threshold,
            trailing_window=trailing_window,
            initial_capital=1.0,
            perp_leverage=position.perp_leverage,
            collateral_yield_annual=collateral_yield_annual,
            settlements=settlements,
        )
        return float(stressed.final_equity / stressed.initial_capital - 1.0)

    total_return_2x = _stressed_total(2.0)
    total_return_3x = _stressed_total(3.0)

    # trajectory-based margin path on the actual perp price series
    perp_path = [s.perp_mark_price for s in sorted(snapshots, key=lambda s: s.captured_at_utc)]
    margin_path = simulate_perp_margin_path(
        perp_path,
        perp_leverage=position.perp_leverage,
        maintenance_margin_rate=snapshots[0].maintenance_margin_rate,
    )
    capital = capital_required(
        position.notional_usd, perp_leverage=position.perp_leverage
    )
    return_on_capital = (
        total_return * position.notional_usd / capital.total_capital_usd
    )

    # subperiod stability: both halves of the series
    halves = [net.iloc[: len(net) // 2], net.iloc[len(net) // 2 :]]
    half_returns = [float((1.0 + h).prod() - 1.0) for h in halves if len(h) > 0]

    span_days = 0.0
    stamps = returns["timestamp"].dropna()
    if len(stamps) >= 2:
        span_days = float((stamps.max() - stamps.min()).total_seconds() / 86400.0)

    # settlement sufficiency (V6-B): polls NEVER count. For collector/backfill
    # datasets the settlement list is the deduped truth; legacy generators
    # emit one snapshot per funding interval, so each bar IS a settlement.
    if settlements is not None:
        settle_times = sorted(pd.to_datetime(ts, utc=True) for ts, _ in settlements)
        unique_settlement_count = len(settle_times)
        settlement_span_days = (
            float((settle_times[-1] - settle_times[0]).total_seconds() / 86400.0)
            if len(settle_times) >= 2
            else 0.0
        )
    else:
        unique_settlement_count = int(len(returns))
        settlement_span_days = span_days
    intervals_per_year = snapshots[0].funding_intervals_per_year
    expected_settlements = (
        settlement_span_days / 365.25 * intervals_per_year if settlement_span_days else 0.0
    )
    settlement_coverage_ratio = (
        unique_settlement_count / expected_settlements if expected_settlements >= 1.0 else 1.0
    )

    metrics = {
        "total_return": total_return,
        "total_return_2x_costs": total_return_2x,
        "total_return_3x_costs": total_return_3x,
        "basis_pnl_total": float(returns["basis_pnl"].sum()),
        "funding_pnl_total": float(returns["funding_pnl"].sum()),
        "collateral_yield_total": float(returns["collateral_yield"].sum()),
        "active_intervals": int(len(active)),
        "funding_events": unique_settlement_count,  # settlements, never polls
        "unique_settlement_count": unique_settlement_count,
        "settlement_span_days": settlement_span_days,
        "settlement_coverage_ratio": settlement_coverage_ratio,
        "span_days": span_days,
        "subperiod_returns": half_returns,
        "min_margin_distance": margin_path.min_margin_distance,
        "margin_breached": margin_path.breached,
        "max_adverse_excursion": margin_path.max_adverse_excursion,
        "capital_required_usd": capital.total_capital_usd,
        "return_on_capital": return_on_capital,
        **moments,
        "go_fraction": go_fraction,
    }

    # --- verdict (fail closed; sufficiency before economics) ---------------
    gate_cfg = config.get("gate", {})
    min_events = int(gate_cfg.get("min_funding_events", 90))
    min_span = float(gate_cfg.get("min_span_days", 30.0))
    min_windows = int(gate_cfg.get("min_walk_forward_windows", 2))
    min_psr = float(gate_cfg.get("min_probabilistic_sharpe", 0.95))

    insufficiency: list[str] = []
    if data_source != "real":
        insufficiency.append(
            f"data_source is {data_source!r}; only genuinely collected real data counts"
        )
    if unique_settlement_count < min_events:
        insufficiency.append(
            f"{unique_settlement_count} unique funding settlement(s) < required "
            f"minimum {min_events} (polls never count as settlements)"
        )
    if span_days < min_span:
        insufficiency.append(f"span {span_days:.1f}d < required minimum {min_span:.0f}d")
    if len(walk_forward) < min_windows:
        insufficiency.append(
            f"{len(walk_forward)} walk-forward window(s) < required minimum {min_windows}"
        )

    if insufficiency:
        decision = "NOT_RUN_INSUFFICIENT_REAL_DATA"
        reasons = insufficiency
    else:
        psr = probabilistic_sharpe_ratio(net.dropna())
        rejection: list[str] = []
        if total_return <= 0:
            rejection.append("campaign net carry is not positive")
        if total_return_2x <= 0:
            rejection.append("net carry does not survive 2x costs")
        if total_return_3x <= 0:
            rejection.append("net carry does not survive 3x costs")
        if not bootstrap.get("total_return_lower_positive"):
            rejection.append("bootstrap lower bound on total return is not positive")
        if go_fraction <= 0:
            rejection.append("no snapshot passed the per-snapshot economic gate")
        if psr < min_psr:
            rejection.append(f"probabilistic Sharpe {psr:.3f} below {min_psr}")
        if margin_path.breached:
            rejection.append("perp margin path breached maintenance along the trajectory")
        if ledger.aborted_entries > 0:
            rejection.append(
                f"{ledger.aborted_entries} two-leg entr(y/ies) aborted on "
                "fill-rate/hedge failure; execution quality below minimum"
            )
        if any(h <= 0 for h in half_returns):
            rejection.append("a subperiod half is not positive; regime stability unproven")
        negative_windows = [
            w for w in walk_forward if float(w.get("test_total_return", 0.0)) <= 0
        ]
        if len(negative_windows) * 2 > len(walk_forward):
            rejection.append("a majority of walk-forward windows are not positive")
        metrics["probabilistic_sharpe"] = psr
        decision = "PAPER_CANDIDATE" if not rejection else "REJECTED"
        reasons = rejection
        if decision == "PAPER_CANDIDATE":
            reasons = [
                "all campaign gates passed; advancing requires the artifact-recomputing "
                "carry promotion review — never real money"
            ]

    return CarryCampaignResult(
        decision=decision,
        reasons=reasons,
        data_source=data_source,
        net_return_series=returns,
        metrics=metrics,
        bootstrap=bootstrap,
        walk_forward=walk_forward,
        per_snapshot_go_fraction=go_fraction,
        dataset_manifest=manifest.to_dict(),
        ledger_summary=ledger.to_dict(),
        ledger_cashflows=ledger.cashflows,
    )


def evaluate_carry_promotion(
    results_path: str | Path, *, ledger_dir: str | Path | None = None
) -> dict[str, Any]:
    """Artifact-recomputing promotion review for a carry campaign.

    The campaign's own PAPER_CANDIDATE is only a candidacy. This review reopens
    the artifacts and fails closed: strict JSON, dataset manifest re-verified
    against the file's current bytes, trial-ledger integrity, recomputed PSR
    from persisted moments, non-empty walk-forward, and real data. It can never
    authorize real money.
    """
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.evidence.manifest import verify_dataset_manifest
    from quant_trade.metrics.statistics import psr_from_moments
    from quant_trade.research.ledger import ledger_integrity_report

    results_path = Path(results_path)
    ledger_dir = Path(ledger_dir) if ledger_dir is not None else results_path.parent
    failures: list[str] = []
    try:
        payload = load_json(results_path)
    except Exception as exc:  # noqa: BLE001 - strict: any parse problem fails closed
        return {
            "status": "REJECTED",
            "failures": [f"results.json unreadable as strict JSON: {exc}"],
            "real_money_authorized": False,
        }
    if payload.get("decision") != "PAPER_CANDIDATE":
        failures.append(
            f"campaign decision is {payload.get('decision')!r}, not PAPER_CANDIDATE"
        )
    if payload.get("data_source") != "real":
        failures.append("data_source is not real")
    manifest = payload.get("dataset_manifest") or {}
    verification = verify_dataset_manifest(manifest)
    if not verification.ok:
        failures.extend(f"dataset manifest: {p}" for p in verification.problems)
    if not payload.get("walk_forward"):
        failures.append("walk-forward evidence is empty")
    integrity = ledger_integrity_report(ledger_dir)
    if not (integrity.exists and integrity.is_intact):
        failures.append("trial ledger missing or corrupt")
    metrics = payload.get("test_metrics") or {}
    sharpe_pp = metrics.get("sharpe_per_period")
    observations = metrics.get("observations")
    skew = metrics.get("skewness")
    kurt = metrics.get("kurtosis")
    if sharpe_pp is None or observations is None or skew is None or kurt is None:
        failures.append("persisted return moments incomplete; PSR cannot be recomputed")
    else:
        psr = psr_from_moments(
            float(sharpe_pp), int(observations), float(skew), float(kurt), 0.0
        )
        if psr < 0.95:
            failures.append(f"recomputed PSR {psr:.3f} below 0.95")
    return {
        "status": "PAPER_CANDIDATE" if not failures else "REJECTED",
        "failures": failures,
        "real_money_authorized": False,
    }


def write_carry_artifacts(
    output_dir: str | Path, config: dict[str, Any], result: CarryCampaignResult
) -> Path:
    """Persist REAL-JSON artifacts byte-bound to the dataset, plus a ledger entry.

    - ``results.json`` is canonical JSON written atomically (defect A fix): any
      consumer using ``json.loads`` — promotion V2 included — can read it.
    - The trial-ledger ``dataset_sha`` is the SHA-256 of the dataset's actual
      bytes from the manifest (defect B fix), never a hash of the config.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = result.dataset_manifest
    dataset_byte_sha = str(manifest.get("byte_sha256", ""))
    if not dataset_byte_sha:
        raise ValueError("campaign result carries no dataset manifest; refusing to write evidence")
    results_payload = {
        "schema_version": 1,
        "experiment_name": config.get("experiment_name", "cash_and_carry"),
        "strategy": "cash_and_carry_funding",
        "data_source": result.data_source,
        "decision": result.decision,
        "reasons": result.reasons,
        "test_metrics": result.metrics,
        "bootstrap": result.bootstrap,
        "walk_forward": result.walk_forward,
        "benchmark": {"type": "flat_cash", "annual_return": 0.0},
        "comparison_test": {"excess_return": result.metrics["total_return"]},
        "dataset_manifest": manifest,
        "dataset_binding": {"data_sha256": dataset_byte_sha},
        "ledger": result.ledger_summary,
    }
    results_path = atomic_write_json(out / "results.json", results_payload)
    atomic_write_json(out / "dataset_manifest.json", manifest)
    result.net_return_series.to_csv(out / "net_returns.csv", index=False)
    # the ledger's evidence rides with every campaign (V6-A): the equity
    # curve, the reconciliation verdict, and the raw cash-flow journal
    atomic_write_json(
        out / "reconciliation.json",
        {
            "ledger": result.ledger_summary,
            "identity": "final_balance_sheet_equity == initial + sum(category totals)",
        },
    )
    if "equity" in result.net_return_series.columns:
        result.net_return_series[["timestamp", "equity"]].to_csv(
            out / "equity_curve.csv", index=False
        )
    with (out / "funding_cashflows.jsonl").open("w", encoding="utf-8") as handle:
        for entry in result.ledger_cashflows:
            handle.write(canonical_dumps(entry) + "\n")
    append_trial_record(
        out,
        build_trial_record(
            source="cash_and_carry_research",
            strategy="cash_and_carry_funding",
            strategy_params=config.get("signal", {}),
            run_id=str(config.get("experiment_name", "carry")),
            status="discarded" if result.decision.startswith("NOT_RUN") else "evaluated",
            dataset_sha=dataset_byte_sha,
            config_sha=sha256_hex(config),
            split_policy="purged_walk_forward",
            feature_version="carry_v1",
            test_sharpe_per_period=result.metrics.get("sharpe_per_period"),
            test_total_return=result.metrics.get("total_return"),
            error=(
                "; ".join(result.reasons)
                if result.decision.startswith("NOT_RUN")
                else None
            ),
        ),
    )
    return results_path
