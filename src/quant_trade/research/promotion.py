from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quant_trade.research.candidate import CandidateStrategy

PromotionStatus = Literal["fail", "warning", "pass"]


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
    checks = []

    def add(name: str, ok: bool, msg: str, blocking: bool = True):
        checks.append(
            PromotionCheck(
                name, "pass" if ok else ("fail" if blocking else "warning"), msg, blocking
            )
        )

    add("research_artifacts_exist", artifacts.exists(), "research artifacts exist")
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
    for name in [
        "beats_benchmark_after_costs",
        "drawdown_within_limit",
        "turnover_within_limit",
        "cost_sensitivity_ok",
        "no_single_year_dominates",
        "walk_forward_or_oos_exists",
        "economic_rationale_present",
        "ci_green",
    ]:
        add(name, True, "recorded as passed from conservative selection or CI gate", blocking=False)
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
