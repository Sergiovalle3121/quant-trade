from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .reports import utc_now_iso, write_json, write_md


@dataclass
class ReadinessPolicy:
    min_calendar_days_observed: int = 1
    min_success_rate: float = 0.8
    max_critical_incidents: int = 0
    max_open_incidents: int = 0
    max_drawdown_pct: float = 20.0
    max_rejected_order_rate: float = 0.1
    require_kill_switch_drill_passed: bool = True
    require_reconciliation_passed: bool = True
    require_fill_analysis: bool = True
    require_no_stale_heartbeats: bool = True
    require_dashboard_generated: bool = True
    require_manual_review_notes: bool = False


@dataclass
class ReadinessReport:
    readiness_status: str
    real_money_ready: bool
    blocking_issues: list[str]
    warnings: list[str]
    evidence: dict[str, Any]
    generated_at_utc: str = field(default_factory=utc_now_iso)


def _item_value(item: object, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def evaluate_ops_readiness(
    session: object,
    validation_reports: list[dict[str, Any]],
    reliability_metrics: object,
    incidents: Sequence[object],
    drills: Sequence[object],
    policy: ReadinessPolicy,
    manual_review_notes: str = "",
) -> ReadinessReport:
    issues: list[str] = []
    warnings: list[str] = []
    success_rate = float(getattr(reliability_metrics, "success_rate", 0.0))

    if success_rate < policy.min_success_rate:
        issues.append("Reliability success rate below policy")
    if not validation_reports:
        issues.append("Missing validation evidence")
    if any(report.get("status") == "fail" for report in validation_reports):
        issues.append("Validation failure present")
    if policy.require_manual_review_notes and not manual_review_notes:
        issues.append("Manual review notes required")

    kill_switch_passed = any(
        _item_value(drill, "name") == "kill_switch_drill" and _item_value(drill, "status") == "pass"
        for drill in drills
    )
    if policy.require_kill_switch_drill_passed and not kill_switch_passed:
        issues.append("Kill switch drill evidence missing")

    open_incidents = sum(
        1 for incident in incidents if _item_value(incident, "status") in {"open", "investigating"}
    )
    if open_incidents > policy.max_open_incidents:
        issues.append("Too many open incidents")

    return ReadinessReport(
        readiness_status="not_ready" if issues else "paper_ops_ready",
        real_money_ready=False,
        blocking_issues=issues,
        warnings=warnings,
        evidence={
            "session_id": getattr(session, "session_id", str(session)),
            "success_rate": success_rate,
        },
    )


def generate_readiness_report(report: ReadinessReport, out: Path) -> None:
    write_json(out / "readiness_report.json", report)
    write_md(out / "readiness_report.md", "Operational Readiness", {"report": asdict(report)})
