"""Run the pre-registered H1-BIN carry campaign and write its result.

Everything tunable is fixed in :mod:`quant_trade.v9.binance_carry_registration`;
this module only executes it, in this order:

1. validate the Binance evidence directory and rebuild its panel byte-for-byte
   from the archived raw files (fails closed, like every V8/V9 panel);
2. register the four variants in the global hash-chained trial ledger
   *before* any of them is run;
3. run each variant as one continuous, causal, reconciled ledger at 1x, 2x
   and 3x costs;
4. anchored walk-forward over the walk-forward section: each window selects on
   bars strictly before ``test_start - purge - embargo``, is scored on its own
   test block only, and pays a round trip whenever the selected variant
   changes;
5. freeze the final variant on everything before the holdout, reveal the
   holdout exactly once, and score it — the holdout is decisive;
6. compare against holding BTC and holding cash over the same bars.

Nothing here places an order, reads a key or reaches a venue. It reads files
the backfill already verified.
"""

from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.evidence.canonical_json import atomic_write_json, load_json
from quant_trade.v9 import binance_carry_registration as reg

STATE_MEASURED_REJECTED = "MEASURED_REJECTED"
STATE_BACKTEST_CANDIDATE = "BACKTEST_CANDIDATE"
STATE_NOT_MEASURED = "NOT_MEASURED"

COST_MULTIPLIERS = (1.0, 2.0, 3.0)
HOURS_PER_YEAR = 24.0 * 365.25


def _iso_to_ms(value: str) -> int:
    import calendar

    return int(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")) * 1000)


def _total(returns: list[float]) -> float:
    total = 1.0
    for value in returns:
        total *= 1.0 + value
    return total - 1.0


def _annualised(total_return: float, bars: int) -> float | None:
    if bars <= 0 or total_return <= -1.0:
        return None
    return (1.0 + total_return) ** (HOURS_PER_YEAR / bars) - 1.0


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def _summary(returns: list[float]) -> dict[str, Any]:
    from quant_trade.metrics.statistics import return_moments

    total = _total(returns)
    moments = return_moments(pd.Series(returns, dtype=float))
    sharpe = float(moments["sharpe_per_period"])
    return {
        "bars": len(returns),
        "total_return": total,
        "annualised_return": _annualised(total, len(returns)),
        "max_drawdown": _max_drawdown(returns),
        "sharpe_per_period": sharpe,
        "sharpe_annualised": sharpe * math.sqrt(HOURS_PER_YEAR),
    }


def _hold_btc(rows: list[dict[str, Any]], start: int, end: int, per_fill: float) -> dict[str, Any]:
    """Buy at the close before ``start``, sell at the close of ``end - 1``.

    Two fills at the same per-fill cost the carry pays, so the comparison is
    like for like.
    """
    first = float(rows[max(0, start - 1)]["spot_close"])
    closes = [float(r["spot_close"]) for r in rows[start:end]]
    returns = [closes[0] / first - 1.0] + [
        b / a - 1.0 for a, b in zip(closes[:-1], closes[1:], strict=True)
    ]
    returns[0] = (1.0 + returns[0]) * (1.0 - per_fill) - 1.0
    returns[-1] = (1.0 + returns[-1]) * (1.0 - per_fill) - 1.0
    return _summary(returns)


def _hold_cash(bars: int) -> dict[str, Any]:
    annual = float(reg.BENCHMARKS["cash"]["annual_yield"])
    total = (1.0 + annual) ** (bars / HOURS_PER_YEAR) - 1.0
    return {"bars": bars, "total_return": total, "annualised_return": annual}


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _per_year(
    rows: list[dict[str, Any]], returns: list[float], per_fill: float
) -> list[dict[str, Any]]:
    """Calendar-year carry vs BTC. In-sample for the selection: context only."""
    years: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        years.setdefault(str(row["timestamp_utc"])[:4], []).append(index)
    out: list[dict[str, Any]] = []
    for year, indices in sorted(years.items()):
        start, end = indices[0], indices[-1] + 1
        out.append(
            {
                "year": year,
                "carry_total_return": _total(returns[start:end]),
                "btc_hold_total_return": _hold_btc(rows, start, end, per_fill)["total_return"],
            }
        )
    return out


def run_h1_bin(
    *,
    evidence_root: str | Path = "data/v8_evidence",
    ledger_path: str | Path = reg.TRIAL_LEDGER_PATH,
    evaluated_at_utc: str | None = None,
    hypothesis_id: str = reg.HYPOTHESIS_ID,
) -> dict[str, Any]:
    """Execute H1-BIN end to end and return the result payload."""
    from quant_trade.carry.panel import load_panel
    from quant_trade.v8.backfill import evidence_dir_for
    from quant_trade.v8.campaigns import _run_ledger
    from quant_trade.v8.costs import conservative_cost_stack
    from quant_trade.v8.preregistration import PROMOTION_GATES
    from quant_trade.v8.validation import sufficiency_report, validate_evidence_dir
    from quant_trade.v9.oos import HoldoutSeal, plan_splits, run_walk_forward
    from quant_trade.v9.trial_ledger import (
        GlobalTrialLedger,
        TrialRecord,
        deflated_sharpe,
        require_promotable_ledger,
    )

    spec = reg.campaign_spec(hypothesis_id)
    if spec.current_hash != spec.frozen_hash:
        raise RuntimeError(
            f"{spec.hypothesis_id} registration moved after it was pinned; refusing to run"
        )

    payload: dict[str, Any] = {
        "artifact": "BINANCE_CARRY_RESULTS",
        "schema_version": 1,
        "hypothesis_id": spec.hypothesis_id,
        "preregistration_hash": spec.frozen_hash,
        "evaluated_at_utc": evaluated_at_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "research_only": True,
        "real_money_approved": False,
    }

    directory = evidence_dir_for(evidence_root, reg.VENUE, reg.SYMBOL)
    since_ms, until_ms = _iso_to_ms(reg.SINCE_UTC), _iso_to_ms(reg.UNTIL_UTC)
    validation = validate_evidence_dir(
        directory,
        since_ms=since_ms,
        until_ms=until_ms,
        interval_minutes=reg.INTERVAL_MINUTES,
        venue=reg.VENUE,
        symbol=reg.SYMBOL,
    )
    sufficiency = sufficiency_report(
        validation,
        min_days=float(PROMOTION_GATES["min_span_days"]),
        min_settlements=int(PROMOTION_GATES["min_unique_settlements"]),
    )
    payload["evidence"] = {
        "directory": directory.as_posix(),
        "provenance": validation.provenance,
        "receipts": validation.receipts,
        "raw_files": validation.raw_pages,
        "validation_clean": validation.is_clean,
        "validation_problems": validation.problems[:20],
        "sufficiency": sufficiency,
        "settlements": {
            k: validation.settlements.get(k)
            for k in ("unique_settlements", "span_days", "first_utc", "last_utc")
        },
    }
    if not (validation.is_clean and sufficiency["sufficient"]):
        payload["state"] = STATE_NOT_MEASURED
        payload["reason"] = "evidence is missing, unclean or below the registered floor"
        return payload

    rows = load_panel(directory)  # byte-identical rebuild from raw, or raises
    manifest = load_json(directory / "panel_manifest.json")
    dataset_sha = str(manifest["byte_sha256"]) if isinstance(manifest, dict) else ""
    payload["panel"] = {
        "rows": len(rows),
        "first_utc": rows[0]["timestamp_utc"],
        "last_utc": rows[-1]["timestamp_utc"],
        "byte_sha256": dataset_sha,
    }
    provenance = validation.provenance

    # --- trials are registered before any variant runs ---------------------
    ledger = GlobalTrialLedger(ledger_path)
    code_sha = _git_head()
    records = {
        v["variant_id"]: TrialRecord(
            trial_id=f"{spec.hypothesis_id}:{v['variant_id']}",
            hypothesis_id=spec.hypothesis_id,
            variant_id=str(v["variant_id"]),
            code_sha=code_sha,
            config_sha=spec.frozen_hash,
            dataset_sha=dataset_sha,
            seed=None,
            registered_at_utc=payload["evaluated_at_utc"],
        )
        for v in spec.variants
    }
    for record in records.values():
        ledger.register(record)

    # --- every variant, as one continuous causal ledger per cost level -----
    stack = conservative_cost_stack(reg.VENUE)
    per_fill = stack.per_fill_bps / 10_000.0
    returns: dict[float, dict[str, list[float]]] = {m: {} for m in COST_MULTIPLIERS}
    positions: dict[str, list[float]] = {}
    ledgers: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for variant in spec.variants:
        vid = str(variant["variant_id"])
        params = variant["parameters"]
        for multiplier in COST_MULTIPLIERS:
            try:
                result = _run_ledger(
                    rows,
                    stack=stack,
                    entry_threshold=float(params["entry_threshold"]),
                    trailing_window=int(params["trailing_window"]),
                    multiplier=multiplier,
                    provenance=provenance,
                    **spec.ledger_options,
                )
            except (ValueError, KeyError) as exc:
                failures[f"{vid}@{multiplier:g}x"] = f"{type(exc).__name__}: {exc}"
                continue
            returns[multiplier][vid] = result.bars["net_return"].astype(float).tolist()
            if multiplier == 1.0:
                positions[vid] = result.bars["position"].astype(float).tolist()
                ledgers[vid] = {
                    **result.to_dict(),
                    "rehedges": result.rehedges,
                    "time_in_market": sum(positions[vid]) / len(positions[vid]),
                    "full_sample": _summary(returns[1.0][vid]),
                }
    payload["variants"] = ledgers
    payload["ledger_failures"] = failures
    usable = [str(v["variant_id"]) for v in spec.variants if str(v["variant_id"]) in returns[1.0]]
    if not usable:
        payload["state"] = STATE_MEASURED_REJECTED
        payload["reason"] = "no pre-registered variant produced a ledger"
        return payload

    # --- anchored walk-forward, per-window out-of-sample selection ---------
    wf_cfg = reg.SPLITS["walk_forward"]
    plan = plan_splits(
        len(rows),
        train_fraction=float(reg.SPLITS["train_fraction"]),
        walk_forward_fraction=float(reg.SPLITS["walk_forward_fraction"]),
    )
    purge, embargo = int(wf_cfg["purge_bars"]), int(wf_cfg["embargo_bars"])
    walk = run_walk_forward(
        len(rows),
        usable,
        lambda vid, start, end: returns[1.0][vid][start:end],
        plan=plan,
        test_size=int(wf_cfg["test_size"]),
        step_size=int(wf_cfg["step_size"]),
        min_selection_rows=int(wf_cfg["min_selection_rows"]),
        purge_bars=purge,
        embargo_bars=embargo,
    )
    switch_charge = 4.0 * per_fill
    oos: dict[str, list[float]] = {}
    switches = 0
    for multiplier in COST_MULTIPLIERS:
        series: list[float] = []
        previous = ""
        for window in walk.windows:
            source = returns[multiplier].get(window.selected_variant)
            if source is None:
                source = [0.0] * len(rows)
                failures.setdefault(
                    f"{window.selected_variant}@{multiplier:g}x", "missing at this cost level"
                )
            block = list(source[window.test_start_index : window.test_end_index])
            if previous and window.selected_variant != previous:
                block[0] = (1.0 + block[0]) * (1.0 - switch_charge * multiplier) - 1.0
                if multiplier == 1.0:
                    switches += 1
            previous = window.selected_variant
            series.extend(block)
        oos[f"{multiplier:g}x"] = series
    wf_start = walk.windows[0].test_start_index if walk.windows else plan.train_end
    wf_end = walk.windows[-1].test_end_index if walk.windows else plan.walk_forward_end
    payload["walk_forward"] = {
        **walk.to_dict(),
        "variant_switches": switches,
        "switch_charge_fraction": switch_charge,
        "oos_start_utc": rows[wf_start]["timestamp_utc"],
        "oos_end_utc": rows[wf_end - 1]["timestamp_utc"],
        "oos": {k: _summary(v) for k, v in oos.items()},
        "btc_hold_same_bars": _hold_btc(rows, wf_start, wf_end, per_fill),
        "cash_same_bars": _hold_cash(wf_end - wf_start),
    }
    for window in payload["walk_forward"]["windows"]:
        window["test_start_utc"] = rows[window["test_start_index"]]["timestamp_utc"]

    # --- trial outcomes: each variant's walk-forward-section Sharpe ---------
    from quant_trade.metrics.statistics import return_moments

    for vid, record in records.items():
        section = returns[1.0].get(vid)
        if section is None:
            ledger.complete(record, oos_sharpe=None, oos_total_return=None, status="failed")
            continue
        piece = section[plan.train_end : plan.walk_forward_end]
        moments = return_moments(pd.Series(piece, dtype=float))
        ledger.complete(
            record,
            oos_sharpe=float(moments["sharpe_per_period"]),
            oos_total_return=_total(piece),
        )
    ledger_stats = require_promotable_ledger(ledger)

    # --- final selection, sealed holdout, revealed once ---------------------
    seal = HoldoutSeal(plan)
    selection_end = plan.holdout_start - purge - embargo
    scores = {vid: _total(returns[1.0][vid][:selection_end]) for vid in usable}
    chosen = max(usable, key=lambda vid: (scores[vid], vid))
    seal.freeze(variant=chosen, config={"registration": spec.frozen_hash, "scores": scores})
    start, end = seal.reveal(reason="final out-of-sample scoring of the frozen H1-BIN variant")
    carried_in = bool(positions[chosen][start - 1]) if start > 0 else False
    holdout: dict[str, list[float]] = {}
    for multiplier in COST_MULTIPLIERS:
        block = list(returns[multiplier].get(chosen, [0.0] * len(rows))[start:end])
        if carried_in:
            # The position opened before the holdout paid its entry outside
            # it; charge that entry (two fills) inside so the holdout carries
            # its own costs.
            block[0] = (1.0 + block[0]) * (1.0 - 2.0 * per_fill * multiplier) - 1.0
        holdout[f"{multiplier:g}x"] = block
    hold_1x = pd.Series(holdout["1x"], dtype=float)

    from quant_trade.metrics.statistics import probabilistic_sharpe_ratio
    from quant_trade.research.bootstrap import bootstrap_confidence_intervals

    moments = return_moments(hold_1x)
    bootstrap: dict[str, Any] = {}
    for block_size in (10, 168):
        ci = bootstrap_confidence_intervals(
            hold_1x,
            method="stationary",
            samples=1000,
            seed=12345,
            block_size=block_size,
            percentiles=(5.0, 50.0, 95.0),
        )
        bootstrap[f"block_{block_size}h"] = {
            "total_return_p05": float(ci.loc["total_return", "p5"]),
            "total_return_p50": float(ci.loc["total_return", "p50"]),
            "total_return_p95": float(ci.loc["total_return", "p95"]),
        }
    psr = float(probabilistic_sharpe_ratio(hold_1x))
    dsr = float(
        deflated_sharpe(
            float(moments["sharpe_per_period"]),
            observations=int(moments["observations"]),
            trials=ledger_stats.distinct_trials,
            sharpe_variance=ledger_stats.sharpe_variance,
            skew=float(moments["skewness"]),
            kurtosis=float(moments["kurtosis"]),
        )
    )
    btc_holdout = _hold_btc(rows, start, end, per_fill)
    cash_holdout = _hold_cash(end - start)
    holdout_summary = {k: _summary(v) for k, v in holdout.items()}
    payload["holdout"] = {
        "seal": seal.to_dict(),
        "selection_scores_before_holdout": scores,
        "frozen_variant": chosen,
        "start_utc": rows[start]["timestamp_utc"],
        "end_utc": rows[end - 1]["timestamp_utc"],
        "position_carried_in": carried_in,
        "carry": holdout_summary,
        "btc_hold_same_bars": btc_holdout,
        "cash_same_bars": cash_holdout,
        "bootstrap_stationary_1000": bootstrap,
        "probabilistic_sharpe": psr,
        "deflated_sharpe": dsr,
        "trial_ledger": ledger_stats.to_dict(),
    }
    payload["full_sample_frozen_variant"] = {
        "in_sample_warning": "the variant was chosen on this data; context only",
        "carry": _summary(returns[1.0][chosen]),
        "btc_hold": _hold_btc(rows, 0, len(rows), per_fill),
        "cash": _hold_cash(len(rows)),
        "per_year": _per_year(rows, returns[1.0][chosen], per_fill),
    }
    payload["cost_stack"] = stack.to_dict()

    # --- gates ---------------------------------------------------------------
    net = holdout_summary["1x"]["total_return"]
    wf = payload["walk_forward"]
    checks = [
        ("holdout_net_positive", "> 0", net, net > 0),
        (
            "holdout_positive_at_2x_costs",
            "> 0",
            holdout_summary["2x"]["total_return"],
            holdout_summary["2x"]["total_return"] > 0,
        ),
        (
            "bootstrap_p05_positive",
            "> 0",
            bootstrap["block_10h"]["total_return_p05"],
            bootstrap["block_10h"]["total_return_p05"] > 0,
        ),
        ("probabilistic_sharpe", ">= 0.95", psr, psr >= 0.95),
        ("deflated_sharpe", ">= 0.95", dsr, dsr >= 0.95),
        (
            "walk_forward_windows",
            f">= {PROMOTION_GATES['min_walk_forward_windows']}",
            wf["window_count"],
            wf["window_count"] >= int(PROMOTION_GATES["min_walk_forward_windows"]),
        ),
        (
            "walk_forward_majority_positive",
            "> half",
            f"{wf['positive_windows']}/{wf['window_count']}",
            wf["positive_windows"] * 2 > wf["window_count"],
        ),
        (
            "zero_ledger_failures",
            0,
            len(failures),
            not failures,
        ),
        (
            "ledgers_reconciled",
            True,
            all(v["reconciled"] for v in ledgers.values()),
            all(v["reconciled"] for v in ledgers.values()),
        ),
        (
            "beats_cash_on_holdout",
            f"> {cash_holdout['total_return']}",
            net,
            net > cash_holdout["total_return"],
        ),
        (
            "beats_buy_and_hold_btc_on_holdout",
            f"> {btc_holdout['total_return']}",
            net,
            net > btc_holdout["total_return"],
        ),
        (
            "cost_evidence_promotable",
            "REAL",
            stack.weakest_evidence_class,
            stack.promotable,
        ),
    ]
    payload["gate_results"] = [
        {"gate": g, "required": r, "observed": o, "passed": bool(p)} for g, r, o, p in checks
    ]
    failed = [g["gate"] for g in payload["gate_results"] if not g["passed"]]
    payload["failed_gates"] = failed
    payload["state"] = STATE_MEASURED_REJECTED if failed else STATE_BACKTEST_CANDIDATE
    payload["note"] = (
        "Research backtest only. BACKTEST_CANDIDATE would at most justify a "
        "supervised paper trial; it never authorises real money."
    )
    return payload


def write_h1_bin(payload: dict[str, Any], path: str | Path) -> Path:
    return atomic_write_json(Path(path), payload)


__all__ = [
    "STATE_BACKTEST_CANDIDATE",
    "STATE_MEASURED_REJECTED",
    "STATE_NOT_MEASURED",
    "run_h1_bin",
    "write_h1_bin",
]
