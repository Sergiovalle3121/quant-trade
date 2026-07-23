from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from quant_trade.metrics.statistics import expected_max_sharpe, psr_from_moments
from quant_trade.research.candidate import CandidateStrategy, SelectionCriteria, utc_now_iso
from quant_trade.research.ledger import ledger_path, ledger_stats


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_runs(outputs_dir: Path) -> list[Path]:
    return [p.parent for p in outputs_dir.rglob("results.json") if "selection" not in p.parts]


def _metric(payload: dict[str, Any], *keys: str) -> float | None:
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return float(cur) if cur is not None else None


def _statistical_reasons(
    result: dict[str, Any],
    criteria: SelectionCriteria,
    trial_stats: tuple[int, float] | None,
) -> list[str]:
    """Gates that separate statistical evidence from lucky point estimates."""
    reasons: list[str] = []
    if criteria.min_trade_count > 0:
        trades = _metric(result, "test_metrics", "trade_count")
        if trades is None or trades < criteria.min_trade_count:
            reasons.append("missing or insufficient test trade count")
    if criteria.min_probabilistic_sharpe > 0:
        psr = _metric(result, "test_metrics", "psr")
        if psr is None or psr < criteria.min_probabilistic_sharpe:
            reasons.append("missing or insufficient probabilistic Sharpe ratio")
    if criteria.require_deflated_sharpe:
        sr = _metric(result, "test_metrics", "sharpe_per_period")
        n_obs = _metric(result, "test_metrics", "observations")
        skew = _metric(result, "test_metrics", "skewness")
        kurt = _metric(result, "test_metrics", "kurtosis")
        if trial_stats is None:
            reasons.append("trial ledger missing; cannot compute deflated Sharpe")
        elif sr is None or n_obs is None or skew is None or kurt is None:
            reasons.append("missing return moments; cannot compute deflated Sharpe")
        else:
            n_trials, sharpe_variance = trial_stats
            threshold = expected_max_sharpe(n_trials, sharpe_variance)
            dsr = psr_from_moments(sr, int(n_obs), skew, kurt, benchmark_sharpe=threshold)
            if dsr < criteria.min_deflated_sharpe:
                reasons.append(
                    f"deflated Sharpe {dsr:.3f} below {criteria.min_deflated_sharpe} "
                    f"(after {n_trials} recorded trials)"
                )
    if criteria.require_walk_forward_overfitting_evidence:
        evidence = result.get("overfitting_evidence")
        if not isinstance(evidence, dict):
            reasons.append("walk-forward overfitting evidence is missing")
        else:
            pbo = _metric(evidence, "walk_forward_pbo")
            windows = _metric(evidence, "windows")
            result_binding = result.get("dataset_binding")
            evidence_binding = evidence.get("dataset_binding")
            same_dataset = (
                isinstance(result_binding, dict)
                and isinstance(evidence_binding, dict)
                and result_binding.get("data_sha256") == evidence_binding.get("data_sha256")
            )
            if not same_dataset:
                reasons.append("walk-forward evidence dataset does not match the research run")
            if evidence.get("strategy") != result.get("strategy"):
                reasons.append("walk-forward evidence strategy does not match the research run")
            if evidence.get("decision") != "PASS":
                reasons.append("walk-forward overfitting evidence did not pass")
            if pbo is None or pbo > criteria.max_walk_forward_pbo:
                reasons.append(
                    f"walk-forward PBO is missing or exceeds {criteria.max_walk_forward_pbo:.3f}"
                )
            if windows is None or windows < criteria.min_walk_forward_windows:
                reasons.append(
                    "walk-forward evidence has fewer than "
                    f"{criteria.min_walk_forward_windows} windows"
                )
    return reasons


def _reasons(
    result: dict[str, Any],
    criteria: SelectionCriteria,
    trial_stats: tuple[int, float] | None = None,
) -> list[str]:
    reasons: list[str] = _statistical_reasons(result, criteria, trial_stats)
    strategy = str(result.get("strategy", result.get("strategy_name", "")))
    symbols = [str(s) for s in result.get("symbols", result.get("universe", []))]
    if criteria.allowed_strategies and strategy not in criteria.allowed_strategies:
        reasons.append("strategy is not in allowed_strategies")
    if criteria.allowed_symbols and any(s not in criteria.allowed_symbols for s in symbols):
        reasons.append("universe contains symbols outside allowed_symbols")
    test_sharpe = _metric(result, "test_metrics", "sharpe")
    if test_sharpe is None or test_sharpe < criteria.min_test_sharpe:
        reasons.append("missing or insufficient test Sharpe")
    train_sharpe = _metric(result, "train_metrics", "sharpe")
    if (
        train_sharpe is None
        or test_sharpe is None
        or train_sharpe - test_sharpe > criteria.max_train_test_sharpe_gap
    ):
        reasons.append("missing or excessive train/test Sharpe gap")
    drawdown = abs(_metric(result, "test_metrics", "max_drawdown") or 999.0)
    if drawdown > criteria.max_test_drawdown:
        reasons.append("missing or excessive test drawdown")
    turnover = _metric(result, "test_metrics", "turnover") or _metric(result, "turnover")
    if turnover is None or turnover > criteria.max_turnover:
        reasons.append("missing or excessive turnover")
    excess = _metric(result, "comparison_test", "excess_return")
    if excess is None or excess < criteria.min_excess_return:
        reasons.append("missing or insufficient excess return")
    if criteria.require_beats_benchmark and (excess is None or excess <= 0):
        reasons.append("strategy does not beat benchmark")
    months = _metric(result, "test_months")
    if months is None:
        tr = result.get("test_range")
        if isinstance(tr, list | tuple) and len(tr) == 2:
            try:
                start = datetime.fromisoformat(str(tr[0]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(tr[1]).replace("Z", "+00:00"))
                months = max(0.0, (end - start).days / 30.0)
            except ValueError:
                months = None
    if months is None or months < criteria.min_test_months:
        reasons.append("missing or insufficient out-of-sample test months")
    robust = result.get("robustness", {}) if isinstance(result.get("robustness", {}), dict) else {}
    if criteria.require_cost_sensitivity_pass and robust.get("cost_sensitivity_pass") is not True:
        reasons.append("cost sensitivity check missing or failed")
    if criteria.require_subperiod_pass and robust.get("subperiod_pass") is not True:
        reasons.append("subperiod check missing or failed")
    if criteria.require_no_red_flags and result.get("red_flags"):
        reasons.append("red flags present")
    return reasons


def _candidate_from_result(
    run_dir: Path, result: dict[str, Any], reasons: list[str]
) -> CandidateStrategy:
    strategy = str(result.get("strategy", result.get("strategy_name", "unknown")))
    symbols = [str(s) for s in result.get("symbols", result.get("universe", []))]
    params = (
        result.get("strategy_params", {})
        if isinstance(result.get("strategy_params", {}), dict)
        else {}
    )
    return CandidateStrategy(
        candidate_id=f"{strategy}-{run_dir.name}",
        name=str(result.get("experiment_name", run_dir.name)),
        strategy_name=strategy,
        strategy_params=params,
        universe=symbols,
        benchmark=str(result.get("benchmark", "equal_weight_universe")),
        data_start=str((result.get("test_range") or result.get("data_range") or ["", ""])[0]),
        data_end=str((result.get("test_range") or result.get("data_range") or ["", ""])[1]),
        research_run_dir=str(run_dir),
        selected_at_utc=utc_now_iso(),
        selected_by="quant-trade selection",
        status="candidate" if not reasons else "rejected",
        approval_notes="",
        risk_notes="Simulated paper trading only; no broker connectivity.",
        known_limitations=(
            "Selected from historical research artifacts; not evidence of future profitability."
        ),
        required_capital=float(result.get("initial_cash", 0.0) or 0.0),
        expected_rebalance_frequency=str(params.get("rebalance_frequency", "unknown")),
        max_weight_per_asset=float(params.get("max_weight_per_asset", 1.0)),
        max_gross_exposure=float(result.get("max_gross_exposure", 1.0) or 1.0),
        estimated_turnover=float(
            (_metric(result, "test_metrics", "turnover") or result.get("turnover", 0.0)) or 0.0
        ),
        expected_cost_sensitivity="pass"
        if result.get("robustness", {}).get("cost_sensitivity_pass")
        else "unknown_or_fail",
        tags=["phase5", "simulated-paper-only"],
        rejection_reasons=reasons,
    )


def _trial_stats(outputs_dir: Path) -> tuple[int, float] | None:
    if not ledger_path(outputs_dir).exists():
        return None
    return ledger_stats(outputs_dir)


def select_candidates_from_outputs(
    outputs_dir: Path, criteria: SelectionCriteria
) -> list[CandidateStrategy]:
    candidates: list[CandidateStrategy] = []
    stats = _trial_stats(outputs_dir)
    for run_dir in _find_runs(outputs_dir):
        result = _load_json(run_dir / "results.json")
        reasons = _reasons(result, criteria, stats)
        candidate = _candidate_from_result(run_dir, result, reasons)
        if candidate.status == "candidate":
            candidates.append(candidate)
    return candidates


def run_selection(outputs_dir: Path, criteria: SelectionCriteria) -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = outputs_dir / "selection" / run_id
    out.mkdir(parents=True, exist_ok=True)
    all_items = []
    stats = _trial_stats(outputs_dir)
    for run_dir in _find_runs(outputs_dir):
        result = _load_json(run_dir / "results.json")
        all_items.append(_candidate_from_result(run_dir, result, _reasons(result, criteria, stats)))
    candidates = [c for c in all_items if c.status == "candidate"]
    rejected = [c for c in all_items if c.status == "rejected"]
    (out / "selection_criteria.yaml").write_text(
        yaml.safe_dump(criteria.to_dict()), encoding="utf-8"
    )
    (out / "candidates.json").write_text(
        json.dumps([c.to_dict() for c in candidates], indent=2), encoding="utf-8"
    )
    for name, rows in {"candidates.csv": candidates, "rejected.csv": rejected}.items():
        with (out / name).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=list(asdict(all_items[0]).keys()) if all_items else ["candidate_id"]
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row.to_dict())
    (out / "selection_summary.md").write_text(
        (
            f"# Strategy selection summary\n\nSelected: {len(candidates)}\n\n"
            f"Rejected: {len(rejected)}\n\n"
            "Conservative selection requires complete metrics and robustness evidence. "
            "This is not a profitability claim.\n"
        ),
        encoding="utf-8",
    )
    return out
