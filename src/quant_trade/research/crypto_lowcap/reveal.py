"""The single holdout reveal.

Everything before this point was allowed to look at the selection window and
nothing else. This module is the one place the holdout is read, and it reads
it once: ``record_reveal`` writes the append-only reveal record *before* the
panel is loaded, naming the already-frozen selection, and a second call raises.

Without a frozen candidate there is nothing to judge, so the verdict says
``NOT_REVEALED_NO_CANDIDATE`` and the holdout stays sealed. That is a real
outcome, and it is the one every campaign in this repository has produced so
far; writing it plainly is the point.

The verdict is a range. The seal itself declares that 2.69 years cannot
separate a true annualised Sharpe of 1.0 from zero (standard error ~0.75), so
the primary candidate's holdout Sharpe is reported with its Lo (2002) standard
error and classified as RANGE_ABOVE_ZERO, RANGE_INCLUDES_ZERO or
RANGE_BELOW_ZERO. A point estimate alone would claim a precision the data does
not have.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import atomic_write_json, load_json, sha256_of_file
from quant_trade.research.crypto_lowcap.campaign import (
    RECOVERIES,
    RESULTS_FILENAME,
    SELECTION_DIRNAME,
    STRESS_RECOVERY,
    TRIALS_DIRNAME,
    CampaignError,
    benchmark_weights,
    bootstrap,
    comparison,
    deflated_sharpes,
    evaluate_span,
    gate_turnover,
    generate_weights,
    load_frozen,
    load_gates,
    load_panel,
    performance,
    require_verified_panel,
    score,
    sharpe_range,
)
from quant_trade.research.crypto_lowcap.config import load_trials_config
from quant_trade.research.holdout_seal import load_seal, read_reveals, record_reveal

HOLDOUT_DIRNAME = "holdout"
VERDICT_FILENAME = "HOLDOUT_VERDICT.json"

STATE_REVEALED = "REVEALED"
STATE_NO_CANDIDATE = "NOT_REVEALED_NO_CANDIDATE"

DECLARED_POWER_LIMIT = (
    "a 2.69-year holdout has a standard error of roughly 0.75 on an annualised Sharpe, so it "
    "cannot separate a true Sharpe of 1.0 from 0; the verdict is a range, not a point"
)


def verdict_path(experiment_dir: str | Path) -> Path:
    return Path(experiment_dir) / HOLDOUT_DIRNAME / VERDICT_FILENAME


def _no_candidate(exp: Path, seal_id: str, reason: str, at_utc: str) -> dict[str, Any]:
    payload = {
        "artifact": "HOLDOUT_VERDICT",
        "schema_version": 1,
        "state": STATE_NO_CANDIDATE,
        "seal_id": seal_id,
        "evaluated_at_utc": at_utc,
        "evidence_class": "DECLARED",
        "reason": reason,
        "revealed": False,
        "reveals_used": len(read_reveals(exp)),
        "declared_power_limit": DECLARED_POWER_LIMIT,
        "note": (
            "The holdout was not read. No selection-window number is out-of-sample evidence, "
            "and nothing in this experiment supports a claim about future returns."
        ),
    }
    atomic_write_json(verdict_path(exp), payload)
    return payload


def run_reveal(
    experiment_dir: str | Path,
    panel_path: str | Path,
    *,
    reason: str,
    evaluated_at_utc: str,
    code_sha: str,
) -> dict[str, Any]:
    exp = Path(experiment_dir)
    seal = load_seal(exp)
    existing = verdict_path(exp)
    if existing.is_file() and load_json(existing).get("state") == STATE_REVEALED:
        raise CampaignError(f"{existing} already records a reveal; the holdout is read once")

    frozen = load_frozen(exp)
    if frozen is None:
        return _no_candidate(
            exp, seal.seal_id, "selection has not run; nothing is frozen", evaluated_at_utc
        )
    if frozen.get("primary") is None:
        return _no_candidate(
            exp,
            seal.seal_id,
            str(frozen.get("no_candidate_reason") or "no candidate"),
            evaluated_at_utc,
        )

    results_path = exp / SELECTION_DIRNAME / RESULTS_FILENAME
    if not results_path.is_file():
        raise CampaignError(f"{results_path} is missing; the frozen selection has no provenance")
    if sha256_of_file(results_path) != frozen["selection_results_sha256"]:
        raise CampaignError("SELECTION_RESULTS.json changed after the candidate was frozen")
    results = load_json(results_path)
    config = load_trials_config(results["trials_config"]["path"])
    if config.sha256 != results["trials_config"]["sha256"]:
        raise CampaignError("the trials config changed after selection; the reveal refuses it")
    criteria, gate_shas = load_gates(config)
    if gate_shas != results["gate_shas"]:
        raise CampaignError("a gate file changed after selection; the reveal refuses it")
    require_verified_panel(exp, panel_path, seal)

    # The reveal is recorded BEFORE the panel is read. Order is the guarantee.
    reveal = record_reveal(exp, reason=reason, at_utc=evaluated_at_utc, frozen_selection=frozen)

    common = config.common
    panel = load_panel(panel_path)  # full history: causal signals need it; only holdout P&L is read
    start, end = seal.holdout_start, seal.holdout_end
    deflation = results["deflated_sharpe"]
    n_declared = int(deflation["n_trials_declared"])
    floor = float(deflation["sharpe_variance_floor"])
    sealed_sharpes = [float(t[f"recovery_{STRESS_RECOVERY}"]["sharpe"]) for t in results["trials"]]
    primary_bench = str(config.deflated_sharpe.get("primary_benchmark", "ew_universe_buy_and_hold"))

    bench_metrics: dict[str, dict[str, dict[str, Any] | None]] = {}
    bench_equity: dict[str, dict[str, dict[str, Any] | None]] = {}
    for name, weights in benchmark_weights(panel, config, start).items():
        bench_metrics[name] = {}
        bench_equity[name] = {}
        for rec in RECOVERIES:
            if weights is None:
                bench_metrics[name][rec] = None
                bench_equity[name][rec] = None
                continue
            ev = evaluate_span(panel, weights, start, end, common=common, recovery=float(rec))
            bench_metrics[name][rec] = performance(ev)
            # Kept so downstream tools (the capital horizon) never need to read
            # the holdout panel again: the reveal is the one read.
            bench_equity[name][rec] = {
                "dates": [t.strftime("%Y-%m-%d") for t in ev.equity_frame["timestamp"]],
                "values": [float(v) for v in ev.equity_frame["equity"]],
            }

    summary_by_id = {t["trial_id"]: t for t in results["trials"]}
    entries = [("primary", frozen["primary"]), *(("secondary", s) for s in frozen["secondaries"])]
    candidates: list[dict[str, Any]] = []
    for role, entry in entries:
        tid = entry["trial_id"]
        selection_row = summary_by_id[tid]
        trial_file = exp / SELECTION_DIRNAME / TRIALS_DIRNAME / f"{tid.replace(':', '__')}.json"
        trial_detail = load_json(trial_file) if trial_file.is_file() else {}
        weights = generate_weights(panel, entry["strategy"], entry["strategy_params"])
        control_weights = generate_weights(
            panel, entry["control_strategy"], entry["control_params"]
        )
        by_recovery: dict[str, Any] = {}
        for rec in RECOVERIES:
            evals = {
                mult: evaluate_span(
                    panel,
                    weights,
                    start,
                    end,
                    common=common,
                    recovery=float(rec),
                    cost_multiplier=mult,
                )
                for mult in common.cost_multipliers
            }
            base = evals[1.0]
            metrics = performance(base)
            control_metrics = performance(
                evaluate_span(
                    panel, control_weights, start, end, common=common, recovery=float(rec)
                )
            )
            highest = max(common.cost_multipliers)
            sensitivity = {
                f"{mult:g}x": {"total_return": performance(ev)["total_return"]}
                for mult, ev in evals.items()
            }
            cost_pass = float(sensitivity[f"{highest:g}x"]["total_return"]) > 0.0
            test_metrics = {
                **metrics,
                "turnover": gate_turnover(metrics, config.turnover),
                "trade_count": metrics["executed_legs"],
            }
            evidence = trial_detail.get("by_recovery", {}).get(rec, {}).get(
                "overfitting_evidence"
            ) or {"decision": "NO-GO", "walk_forward_pbo": None, "windows": 0}
            result = {
                "strategy": entry["strategy"],
                "strategy_params": entry["strategy_params"],
                "experiment_name": tid,
                "universe": [],
                "test_metrics": test_metrics,
                "train_metrics": {"sharpe": float(selection_row[f"recovery_{rec}"]["sharpe"])},
                "comparison_test": comparison(
                    metrics, bench_metrics.get(primary_bench, {}).get(rec)
                ),
                "test_range": [start, end],
                "robustness": {"cost_sensitivity_pass": cost_pass},
                "overfitting_evidence": {
                    **evidence,
                    "strategy": entry["strategy"],
                    "dataset_binding": {"data_sha256": seal.dataset_digest},
                },
                "dataset_binding": {"data_sha256": seal.dataset_digest},
            }
            comparisons = {
                name: comparison(metrics, bench_metrics[name].get(rec)) for name in bench_metrics
            }
            btc = comparisons.get("btc_buy_and_hold", {})
            refutation = {
                "beats_control": bool(metrics["total_return"] > control_metrics["total_return"]),
                "beats_ew_bh": bool((result["comparison_test"].get("excess_return") or 0.0) > 0.0)
                if result["comparison_test"].get("status") == "MEASURED"
                else None,
                "beats_btc": (
                    bool(btc["excess_return"] > 0.0) if btc.get("status") == "MEASURED" else None
                ),
            }
            by_recovery[rec] = {
                "test_metrics": test_metrics,
                "selection_window_sharpe": float(selection_row[f"recovery_{rec}"]["sharpe"]),
                "comparison_test": result["comparison_test"],
                "comparisons": comparisons,
                "control": {
                    "strategy": entry["control_strategy"],
                    "params": entry["control_params"],
                    "metrics": control_metrics,
                },
                "cost_sensitivity": sensitivity,
                "robustness": {"cost_sensitivity_pass": cost_pass},
                "bootstrap": bootstrap(base.returns, common),
                "sharpe_range": sharpe_range(base, metrics),
                "dsr": deflated_sharpes(
                    metrics,
                    n_declared=n_declared,
                    n_spent=len(sealed_sharpes),
                    own_sharpes=sealed_sharpes,
                    floor=floor,
                    etf_sharpes=None,
                ),
                "refutation": refutation,
                "gates": {
                    name: score(result, crit, n_declared, float(deflation["sharpe_variance_used"]))
                    for name, crit in criteria.items()
                    if name == entry["gate"] or not name.startswith("primary:")
                },
                "equity": {
                    "dates": [t.strftime("%Y-%m-%d") for t in base.equity_frame["timestamp"]],
                    "values": [float(v) for v in base.equity_frame["equity"]],
                },
            }
        candidates.append({"role": role, **entry, "by_recovery": by_recovery})

    primary = candidates[0]["by_recovery"][STRESS_RECOVERY]
    program = {
        "primary_trial_id": candidates[0]["trial_id"],
        "verdict_class_at_recovery_0": primary["sharpe_range"].get("verdict_class", "NOT_MEASURED"),
        "verdict_class_at_recovery_1": candidates[0]["by_recovery"]["1.0"]["sharpe_range"].get(
            "verdict_class", "NOT_MEASURED"
        ),
        "primary_gate_pass_at_recovery_0": primary["gates"][candidates[0]["gate"]]["pass"],
        "primary_gate_pass_at_recovery_1": candidates[0]["by_recovery"]["1.0"]["gates"][
            candidates[0]["gate"]
        ]["pass"],
        "refutation_at_recovery_0": primary["refutation"],
    }
    payload = {
        "artifact": "HOLDOUT_VERDICT",
        "schema_version": 2,
        "state": STATE_REVEALED,
        "seal_id": seal.seal_id,
        "seal": seal.seal(),
        "panel_digest": seal.dataset_digest,
        "evaluated_at_utc": evaluated_at_utc,
        "code_sha": code_sha,
        "evidence_class": "MEASURED",
        "revealed": True,
        "reveals_used": len(read_reveals(exp)),
        "reveal": reveal,
        "frozen_selection_sha256": frozen["sha256"],
        "holdout_window": [start, end],
        "declared_power_limit": DECLARED_POWER_LIMIT,
        "deflated_sharpe": {
            "n_trials_declared": n_declared,
            "sharpe_variance_used": deflation["sharpe_variance_used"],
        },
        "benchmarks": {
            name: {rec: bench_metrics[name][rec] for rec in RECOVERIES} for name in bench_metrics
        },
        "benchmark_equity": {
            name: {rec: bench_equity[name][rec] for rec in RECOVERIES} for name in bench_equity
        },
        "program": program,
        "candidates": candidates,
        "note": (
            "Holdout evidence is one draw over one window that the seal declares flatters "
            "long-only strategies (2024-2025 upswing). It supports at most a paper trial, never a "
            "claim about realised money."
        ),
    }
    atomic_write_json(verdict_path(exp), payload)
    return payload


__all__ = [
    "DECLARED_POWER_LIMIT",
    "HOLDOUT_DIRNAME",
    "STATE_NO_CANDIDATE",
    "STATE_REVEALED",
    "VERDICT_FILENAME",
    "run_reveal",
    "verdict_path",
]
