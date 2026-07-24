"""Persistent shadow portfolio: frozen config, event-driven, reconciled daily.

A shadow session freezes the paper allocation the moment it starts — the
champion configuration can never be edited retroactively — and then advances
over market events locally, recording snapshots, cash flows, and daily
reconciliation. No orders are sent anywhere, ever.

State layout (append-only, canonical JSON):

    state.json        session identity, frozen allocation, hashes, status
    events.jsonl      every processed event (idempotent resume by sequence)
    snapshots.jsonl   equity/cash/drawdown after each event
    reconcile.json    latest reconciliation + kill-switch verdicts

Kill switches (stale data, drawdown, exposure) are EVALUATED from state,
never written by an operator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_trade.cloud_rental.models import SAFETY_POSTURE
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)

DEFAULT_MAX_DRAWDOWN = 0.15
DEFAULT_STALE_HOURS = 48.0


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def shadow_start(
    state_dir: str | Path,
    allocation: dict[str, Any],
    *,
    started_at_utc: str,
    commit_sha: str = "",
    max_drawdown: float = DEFAULT_MAX_DRAWDOWN,
    stale_hours: float = DEFAULT_STALE_HOURS,
) -> dict[str, Any]:
    """Freeze the allocation into a new shadow session. Refuses to overwrite."""
    out = Path(state_dir)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    if state_path.exists():
        raise ValueError(
            f"shadow session already exists at {state_path}; stop it first — "
            "configurations are never replaced in place"
        )
    if not allocation.get("paper_only"):
        raise ValueError("only a PAPER allocation can seed a shadow session")
    frozen_sha = sha256_of_text(canonical_dumps(allocation))
    capital = float(allocation.get("total_capital_usd", 0.0))
    if capital <= 0:
        raise ValueError("allocation carries no capital")
    state = {
        "schema_version": 1,
        "session_id": f"shadow-{frozen_sha[:16]}",
        "status": "RUNNING",
        "started_at_utc": started_at_utc,
        "commit_sha": commit_sha,
        "frozen_allocation": allocation,
        "frozen_allocation_sha256": frozen_sha,
        "initial_capital_usd": capital,
        "max_drawdown": max_drawdown,
        "stale_hours": stale_hours,
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
    }
    atomic_write_json(state_path, state)
    _append(
        out / "snapshots.jsonl",
        {
            "seq": 0,
            "timestamp_utc": started_at_utc,
            "equity_usd": capital,
            "cash_usd": capital,
            "peak_equity_usd": capital,
            "drawdown": 0.0,
        },
    )
    return state


def _load_state(state_dir: Path) -> dict[str, Any]:
    state_path = state_dir / "state.json"
    if not state_path.exists():
        raise ValueError(f"no shadow session at {state_path}")
    return load_json(state_path)


def shadow_advance(
    state_dir: str | Path, events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Advance over events; idempotent — already-processed sequences skip.

    Event shape: ``{"seq": int, "timestamp_utc": str, "cash_yield_daily":
    float}`` (plus optional mark data for future candidate legs). With the
    current all-cash allocation, equity accrues the cash yield; every event
    and snapshot is journaled so reconciliation can rebuild equity from
    flows alone.
    """
    out = Path(state_dir)
    state = _load_state(out)
    if state.get("status") != "RUNNING":
        raise ValueError(f"shadow session is {state.get('status')}; not advancing")
    processed = {int(e["seq"]) for e in _read_jsonl(out / "events.jsonl")}
    snapshots = _read_jsonl(out / "snapshots.jsonl")
    last = snapshots[-1]
    equity = float(last["equity_usd"])
    peak = float(last["peak_equity_usd"])
    applied = skipped = 0
    for event in sorted(events, key=lambda e: int(e["seq"])):
        seq = int(event["seq"])
        if seq in processed or seq <= 0:
            skipped += 1
            continue
        accrual = equity * float(event.get("cash_yield_daily", 0.0))
        equity += accrual
        peak = max(peak, equity)
        _append(
            out / "events.jsonl",
            {
                "seq": seq,
                "timestamp_utc": str(event["timestamp_utc"]),
                "cash_yield_daily": float(event.get("cash_yield_daily", 0.0)),
                "accrual_usd": accrual,
            },
        )
        _append(
            out / "snapshots.jsonl",
            {
                "seq": seq,
                "timestamp_utc": str(event["timestamp_utc"]),
                "equity_usd": equity,
                "cash_usd": equity,  # all-cash allocation: equity IS cash
                "peak_equity_usd": peak,
                "drawdown": (peak - equity) / peak if peak > 0 else 0.0,
            },
        )
        applied += 1
    return {"applied": applied, "skipped": skipped, "equity_usd": equity}


def shadow_reconcile(state_dir: str | Path, *, now_utc: str) -> dict[str, Any]:
    """Rebuild equity from the flow journal and evaluate every kill switch."""
    from quant_trade.carry.quality import parse_utc

    out = Path(state_dir)
    state = _load_state(out)
    events = _read_jsonl(out / "events.jsonl")
    snapshots = _read_jsonl(out / "snapshots.jsonl")
    initial = float(state["initial_capital_usd"])
    rebuilt = initial + sum(float(e["accrual_usd"]) for e in events)
    reported = float(snapshots[-1]["equity_usd"]) if snapshots else initial
    error = abs(rebuilt - reported)
    reconciled = error <= 1e-9 * max(1.0, initial)

    drawdown = float(snapshots[-1]["drawdown"]) if snapshots else 0.0
    last_ts = str(snapshots[-1]["timestamp_utc"]) if snapshots else str(
        state["started_at_utc"]
    )
    age_hours = (parse_utc(now_utc) - parse_utc(last_ts)).total_seconds() / 3600.0
    kill = {
        "stale_data": age_hours > float(state["stale_hours"]),
        "drawdown": drawdown > float(state["max_drawdown"]),
        "exposure": False,  # all-cash: no exposure; candidate legs add checks here
        "reconciliation": not reconciled,
    }
    report = {
        "session_id": state["session_id"],
        "reconciled": reconciled,
        "reconciliation_error_usd": error,
        "equity_rebuilt_usd": rebuilt,
        "equity_reported_usd": reported,
        "drawdown": drawdown,
        "data_age_hours": age_hours,
        "kill_switches": kill,
        "kill_switch_engaged": any(kill.values()),
        "evaluated_at_utc": now_utc,
    }
    atomic_write_json(out / "reconcile.json", report)
    if report["kill_switch_engaged"] and state.get("status") == "RUNNING":
        state["status"] = "HALTED_KILL_SWITCH"
        atomic_write_json(out / "state.json", state)
    return report


def shadow_status(state_dir: str | Path) -> dict[str, Any]:
    out = Path(state_dir)
    state = _load_state(out)
    snapshots = _read_jsonl(out / "snapshots.jsonl")
    last = snapshots[-1] if snapshots else {}
    initial = float(state["initial_capital_usd"])
    equity = float(last.get("equity_usd", initial))
    reconcile = (
        load_json(out / "reconcile.json") if (out / "reconcile.json").exists() else {}
    )
    return {
        "artifact": "SHADOW_PORTFOLIO_STATUS",
        "schema_version": 1,
        "session_id": state["session_id"],
        "status": state["status"],
        "started_at_utc": state["started_at_utc"],
        "frozen_allocation_sha256": state["frozen_allocation_sha256"],
        "commit_sha": state.get("commit_sha", ""),
        "initial_capital_usd": initial,
        "equity_usd": equity,
        "total_return": equity / initial - 1.0 if initial else 0.0,
        "drawdown": float(last.get("drawdown", 0.0)),
        "events_processed": len(_read_jsonl(out / "events.jsonl")),
        "scoreboard": {
            "shadow_equity_usd": equity,
            "cash_benchmark_usd": equity,  # all-cash champion: identical by design
            "active_return": 0.0,
        },
        "last_reconcile": reconcile,
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
    }


def shadow_stop(state_dir: str | Path, *, stopped_at_utc: str) -> dict[str, Any]:
    out = Path(state_dir)
    state = _load_state(out)
    state["status"] = "STOPPED"
    state["stopped_at_utc"] = stopped_at_utc
    atomic_write_json(out / "state.json", state)
    return state
