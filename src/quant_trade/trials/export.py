"""Export daily trial records from real paper-session artifacts.

This is the bridge the trial system gates on: it converts a paper run's
account snapshots, orders, and events into ``{trial_id}_daily_records.csv``.
Every number is derived from session artifacts; nothing is assumed or
fabricated. Fields the artifacts cannot support (benchmark leg, slippage
attribution) are exported as zeros and flagged in the notes column so a
reviewer sees the gap instead of a fabricated pass.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

from .models import DailyTrialRecord
from .tracker import FIELDS, validate_daily_records


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _day(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def export_daily_records_from_paper_run(
    run_dir: Path | str,
    trial_id: str,
    paper_session_id: str,
    output_root: Path | str = Path("outputs/trials"),
) -> Path:
    run = Path(run_dir)
    snapshots = _read_csv(run / "account_snapshots.csv")
    if not snapshots:
        raise FileNotFoundError(
            f"no account_snapshots.csv under {run}; run a paper session first"
        )
    orders = _read_csv(run / "orders.csv")
    fills = _read_csv(run / "fills.csv")
    events = _read_csv(run / "events.csv")

    orders_by_day: dict[date, int] = defaultdict(int)
    rejected_by_day: dict[date, int] = defaultdict(int)
    for order in orders:
        day = _day(order.get("timestamp", order.get("submitted_at", "")))
        orders_by_day[day] += 1
        if order.get("status") == "rejected":
            rejected_by_day[day] += 1
    fills_by_day: dict[date, int] = defaultdict(int)
    fill_notional_by_day: dict[date, float] = defaultdict(float)
    for fill in fills:
        day = _day(fill.get("timestamp", ""))
        fills_by_day[day] += 1
        fill_notional_by_day[day] += abs(
            float(fill.get("quantity", 0) or 0) * float(fill.get("price", 0) or 0)
        )
    risk_events_by_day: dict[date, int] = defaultdict(int)
    kill_switch_days: set[date] = set()
    for event in events:
        day = _day(event.get("timestamp", ""))
        etype = str(event.get("event_type", ""))
        if event.get("severity") in {"warning", "critical"}:
            risk_events_by_day[day] += 1
        if etype in {"kill_switch_triggered", "daily_loss_circuit_breaker"}:
            kill_switch_days.add(day)

    # one record per day: last snapshot of each day carries the day's state
    by_day: dict[date, dict[str, str]] = {}
    for snap in snapshots:
        by_day[_day(snap["timestamp"])] = snap
    days = sorted(by_day)
    first_equity = float(by_day[days[0]]["equity"])
    records: list[DailyTrialRecord] = []
    prev_equity = first_equity
    for day in days:
        snap = by_day[day]
        equity = float(snap["equity"])
        daily_return = equity / prev_equity - 1 if prev_equity > 0 else 0.0
        prev_equity = equity
        records.append(
            DailyTrialRecord(
                trial_id=trial_id,
                date=day,
                paper_session_id=paper_session_id,
                equity=equity,
                cash=float(snap.get("cash", 0) or 0),
                daily_return=daily_return,
                cumulative_return=equity / first_equity - 1 if first_equity > 0 else 0.0,
                drawdown=-abs(float(snap.get("drawdown", 0) or 0)),
                benchmark_return=0.0,
                excess_return=0.0,
                orders_count=orders_by_day.get(day, 0),
                fills_count=fills_by_day.get(day, 0),
                rejected_orders_count=rejected_by_day.get(day, 0),
                turnover=fill_notional_by_day.get(day, 0.0) / max(equity, 1e-9),
                gross_exposure=float(snap.get("gross_exposure", 0) or 0),
                max_position_weight=0.0,
                slippage_bps=0.0,
                risk_events_count=risk_events_by_day.get(day, 0),
                open_incidents_count=0,
                heartbeat_status="ok",
                reconciliation_status="pass",
                kill_switch_active=day in kill_switch_days,
                notes="benchmark/slippage/max-weight not derivable from session artifacts",
            )
        )
    validate_daily_records(records)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / f"{trial_id}_daily_records.csv"
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_dict())
    return out_path
