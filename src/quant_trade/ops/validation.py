from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .reports import utc_now_iso, write_json, write_md

REQUIRED_ARTIFACTS = [
    "paper_summary.md",
    "paper_metrics.json",
    "final_state.json",
    "account_snapshots.csv",
    "orders.csv",
    "fills.csv",
    "positions.csv",
    "events.csv",
]


@dataclass
class OpsCheck:
    name: str
    status: str
    message: str


@dataclass
class OpsValidationReport:
    run_id: str
    session_id: str
    status: str
    checks: list[OpsCheck]
    blocking_issues: list[str]
    warnings: list[str]
    artifact_paths: dict[str, str]
    generated_at_utc: str = field(default_factory=utc_now_iso)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_artifacts(
    run_dir: Path,
    session_id: str,
    run_id: str = "validation",
    max_drawdown_pct: float = 20.0,
    max_rejected: int = 5,
) -> OpsValidationReport:
    checks: list[OpsCheck] = []
    issues: list[str] = []
    warnings: list[str] = []
    paths: dict[str, str] = {}

    for name in REQUIRED_ARTIFACTS:
        path = run_dir / name
        paths[name] = str(path)
        if path.exists():
            checks.append(OpsCheck(name=name, status="pass", message="found"))
        else:
            issues.append(f"Missing required artifact: {name}")
            checks.append(OpsCheck(name=name, status="fail", message="missing"))

    state: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    snapshots: list[dict[str, str]] = []
    orders: list[dict[str, str]] = []
    fills: list[dict[str, str]] = []
    events: list[dict[str, str]] = []

    try:
        if (run_dir / "final_state.json").exists():
            state = _read_json(run_dir / "final_state.json")
        if (run_dir / "paper_metrics.json").exists():
            metrics = _read_json(run_dir / "paper_metrics.json")
        if (run_dir / "account_snapshots.csv").exists():
            snapshots = _read_csv(run_dir / "account_snapshots.csv")
        if (run_dir / "orders.csv").exists():
            orders = _read_csv(run_dir / "orders.csv")
        if (run_dir / "fills.csv").exists():
            fills = _read_csv(run_dir / "fills.csv")
        if (run_dir / "events.csv").exists():
            events = _read_csv(run_dir / "events.csv")
        checks.append(OpsCheck(name="parse_artifacts", status="pass", message="parseable"))
    except (csv.Error, json.JSONDecodeError, OSError) as exc:
        issues.append(f"Malformed artifact: {exc}")
        checks.append(OpsCheck(name="parse_artifacts", status="fail", message=str(exc)))

    if snapshots and state:
        last_snapshot = snapshots[-1]
        if abs(_float(last_snapshot.get("equity")) - _float(state.get("equity"))) > 0.01:
            issues.append("Final equity does not match last account snapshot")
        if abs(_float(last_snapshot.get("cash")) - _float(state.get("cash"))) > 0.01:
            issues.append("Final cash does not match last account snapshot")

    drawdown = _float(metrics.get("max_drawdown", metrics.get("max_drawdown_pct")))
    if drawdown > max_drawdown_pct / 100:
        issues.append("Drawdown exceeds configured limit")

    rejected = sum(1 for order in orders if order.get("status", "").lower() == "rejected")
    if rejected > max_rejected:
        issues.append("Rejected order count exceeds limit")

    kill_times = [
        event.get("timestamp", "")
        for event in events
        if "kill" in event.get("event_type", event.get("type", "")).lower()
    ]
    if kill_times:
        trigger_time = min(kill_times)
        if any(order.get("timestamp", "") > trigger_time for order in orders):
            issues.append("Orders found after kill switch trigger")

    order_ids = [
        order.get("order_id") or order.get("client_order_id")
        for order in orders
        if order.get("order_id") or order.get("client_order_id")
    ]
    if len(order_ids) != len(set(order_ids)):
        issues.append("Duplicate order IDs found")

    fill_ids = [fill.get("fill_id") for fill in fills if fill.get("fill_id")]
    if len(fill_ids) != len(set(fill_ids)):
        issues.append("Duplicate fill IDs found")
    if not fills:
        warnings.append("No fills available; simulated or no-trade run")

    status = "fail" if issues else "warning" if warnings else "pass"
    return OpsValidationReport(run_id, session_id, status, checks, issues, warnings, paths)


def generate_validation_report(report: OpsValidationReport, out: Path) -> None:
    write_json(out / "validation_report.json", report)
    write_md(
        out / "validation_report.md",
        "Ops Validation Report",
        {
            "status": report.status,
            "blocking_issues": report.blocking_issues,
            "warnings": report.warnings,
        },
    )
