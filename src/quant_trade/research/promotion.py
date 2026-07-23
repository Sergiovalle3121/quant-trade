from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quant_trade.research.candidate import CandidateStrategy

PromotionStatus = Literal["fail", "warning", "pass"]


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


@dataclass
class PromotionCheck:
    name: str
    status: PromotionStatus
    message: str
    blocking: bool = True


@dataclass
class PromotionReport:
    candidate_id: str
    overall_status: PromotionStatus
    checks: list[PromotionCheck]
    blocking_issues: list[str]
    warnings: list[str]
    generated_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def evaluate_promotion(
    candidate: CandidateStrategy, artifacts: Path, risk_config: dict[str, Any]
) -> PromotionReport:
    checks: list[PromotionCheck] = []

    def add(name: str, ok: bool, msg: str, blocking: bool = True):
        checks.append(
            PromotionCheck(
                name, "pass" if ok else ("fail" if blocking else "warning"), msg, blocking
            )
        )

    add("research_artifacts_exist", artifacts.is_dir(), "research artifact directory is required")
    add(
        "approval_notes_present",
        bool(candidate.approval_notes.strip()),
        "human approval notes are required",
    )
    add("risk_limits_defined", bool(risk_config), "paper trading risk limits are defined")
    add(
        "kill_switch_enabled",
        bool(risk_config.get("kill_switch_enabled", False)),
        "kill switch must be enabled",
    )
    add(
        "no_live_broker_config",
        "broker" not in risk_config,
        "no live broker integration is configured",
    )
    add(
        "candidate_not_rejected",
        candidate.status in {"candidate", "paper_ready"},
        "candidate status must be candidate or paper_ready",
    )
    add(
        "selection_rejections_empty",
        not candidate.rejection_reasons,
        "candidate contains selection rejection reasons",
    )

    results: dict[str, Any] | None = None
    results_path = artifacts / "results.json"
    try:
        loaded = json.loads(results_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            results = loaded
    except (OSError, json.JSONDecodeError):
        results = None
    add("results_json_readable", results is not None, "valid results.json is required")

    if results is not None:
        comparison = results.get("comparison_test", {})
        test_metrics = results.get("test_metrics", {})
        robustness = results.get("robustness", {})
        execution = results.get("execution_test", {})
        test_range = results.get("test_range")
        excess = (
            _optional_float(comparison.get("excess_return"))
            if isinstance(comparison, dict)
            else None
        )
        raw_drawdown = (
            _optional_float(test_metrics.get("max_drawdown"))
            if isinstance(test_metrics, dict)
            else None
        )
        drawdown = abs(raw_drawdown) if raw_drawdown is not None else None
        min_excess = float(risk_config.get("min_net_excess_return", 0.0))
        max_drawdown = float(risk_config.get("max_drawdown", 0.20))
        max_turnover = float(risk_config.get("max_turnover", 3.0))
        min_fill_rate = float(risk_config.get("min_quantity_fill_rate", 0.90))
        max_incomplete_rate = float(risk_config.get("max_partial_or_expired_order_rate", 0.10))
        fill_rate = (
            _optional_float(execution.get("quantity_fill_rate"))
            if isinstance(execution, dict)
            else None
        )
        incomplete_rate = (
            _optional_float(execution.get("partial_or_expired_order_rate"))
            if isinstance(execution, dict)
            else None
        )
        overfitting = results.get("overfitting_evidence")
        add(
            "beats_benchmark_after_costs",
            excess is not None and excess > min_excess,
            f"net OOS excess return must exceed {min_excess:.4f}",
        )
        add(
            "drawdown_within_limit",
            drawdown is not None and drawdown <= max_drawdown,
            f"OOS drawdown must not exceed {max_drawdown:.2%}",
        )
        add(
            "turnover_within_limit",
            candidate.estimated_turnover <= max_turnover,
            f"estimated turnover must not exceed {max_turnover:.4f}",
        )
        add(
            "cost_sensitivity_ok",
            isinstance(robustness, dict) and robustness.get("cost_sensitivity_pass") is True,
            "cost sensitivity evidence is missing or failed",
        )
        add(
            "execution_fill_rate_ok",
            fill_rate is not None and fill_rate >= min_fill_rate,
            f"OOS quantity fill rate must be at least {min_fill_rate:.2%}",
        )
        add(
            "execution_completion_rate_ok",
            incomplete_rate is not None and incomplete_rate <= max_incomplete_rate,
            f"partial/expired/cancelled OOS order rate must not exceed {max_incomplete_rate:.2%}",
        )
        add(
            "walk_forward_or_oos_exists",
            isinstance(test_range, list | tuple)
            and len(test_range) == 2
            and bool(test_range[0])
            and bool(test_range[1]),
            "an explicit out-of-sample test range is required",
        )
        if bool(risk_config.get("require_overfitting_evidence", False)):
            pbo = (
                _optional_float(overfitting.get("walk_forward_pbo"))
                if isinstance(overfitting, dict)
                else None
            )
            windows = (
                _optional_float(overfitting.get("windows"))
                if isinstance(overfitting, dict)
                else None
            )
            max_pbo = float(risk_config.get("max_walk_forward_pbo", 0.50))
            min_windows = int(risk_config.get("min_walk_forward_windows", 4))
            add(
                "walk_forward_overfitting_evidence_ok",
                isinstance(overfitting, dict)
                and overfitting.get("decision") == "PASS"
                and pbo is not None
                and pbo <= max_pbo
                and windows is not None
                and windows >= min_windows,
                "matching walk-forward overfitting evidence must pass with "
                f"PBO <= {max_pbo:.3f} across at least {min_windows} windows",
            )
    blocking = [c.message for c in checks if c.status == "fail" and c.blocking]
    warnings = [c.message for c in checks if c.status == "warning"]
    return PromotionReport(
        candidate.candidate_id,
        "fail" if blocking else ("warning" if warnings else "pass"),
        checks,
        blocking,
        warnings,
        datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def save_promotion_report(path: Path, report: PromotionReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
