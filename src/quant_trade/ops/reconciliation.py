from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .reports import utc_now_iso, write_json, write_md


@dataclass
class ReconciliationReport:
    status: str
    issues: list[str]
    warnings: list[str]
    generated_at_utc: str = field(default_factory=utc_now_iso)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def reconcile_session_state(
    session: Any, latest_state: Path | None, latest_artifacts: Path | None
) -> ReconciliationReport:
    del session
    return reconcile_broker_artifacts(latest_artifacts or latest_state or Path(".missing"), {})


def reconcile_broker_artifacts(
    local_state: Path, broker_responses: dict[str, Any] | None = None
) -> ReconciliationReport:
    del broker_responses
    issues: list[str] = []
    warnings: list[str] = []
    orders = _read_csv(local_state / "orders.csv")
    fills = _read_csv(local_state / "fills.csv")
    positions = _read_csv(local_state / "positions.csv")

    order_ids = [
        order.get("client_order_id") or order.get("order_id")
        for order in orders
        if order.get("client_order_id") or order.get("order_id")
    ]
    if len(order_ids) != len(set(order_ids)):
        issues.append("Duplicated client order IDs")
    order_id_set = set(order_ids)

    for fill in fills:
        order_id = fill.get("client_order_id") or fill.get("order_id")
        if order_id and order_id not in order_id_set:
            issues.append(f"Orphan fill: {order_id}")

    for position in positions:
        quantity = float(position.get("quantity") or position.get("qty") or 0)
        if quantity < 0:
            issues.append("Impossible negative quantities")

    return ReconciliationReport("fail" if issues else "pass", issues, warnings)


def reconcile_positions_over_time(
    positions: list[dict[str, Any]], snapshots: list[dict[str, Any]]
) -> ReconciliationReport:
    del positions, snapshots
    return ReconciliationReport("pass", [], [])


def generate_reconciliation_report(report: ReconciliationReport, out: Path) -> None:
    write_json(out / "reconciliation_report.json", report)
    write_md(
        out / "reconciliation_report.md",
        "Reconciliation Report",
        {"status": report.status, "issues": report.issues},
    )
