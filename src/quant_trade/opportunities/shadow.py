"""Crash-recoverable, hash-chained shadow portfolio (local simulation only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from quant_trade.carry.quality import parse_utc
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)
from quant_trade.evidence.safety_posture import SAFETY_POSTURE

DEFAULT_MAX_DRAWDOWN = 0.15
DEFAULT_STALE_HOURS = 48.0
GENESIS_HASH = "0" * 64


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"torn JSONL record at {path}:{line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"non-object JSONL record at {path}:{line_number}")
        records.append(record)
    return records


def _hash_record(payload: dict[str, Any]) -> str:
    return sha256_of_text(canonical_dumps(payload))


def _chained_record(record: dict[str, Any], previous_hash: str) -> dict[str, Any]:
    payload = {**record, "previous_hash": previous_hash}
    return {**payload, "record_hash": _hash_record(payload)}


def _verify_chain(records: list[dict[str, Any]], *, journal: str) -> None:
    previous_hash = GENESIS_HASH
    for index, record in enumerate(records):
        claimed = str(record.get("record_hash", ""))
        payload = {k: v for k, v in record.items() if k != "record_hash"}
        if payload.get("previous_hash") != previous_hash:
            raise ValueError(f"{journal} hash chain broken at record {index}")
        if not claimed or claimed != _hash_record(payload):
            raise ValueError(f"{journal} record hash mismatch at record {index}")
        previous_hash = claimed


def _append_fsynced(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _append_chained(path: Path, record: dict[str, Any], previous_hash: str) -> dict[str, Any]:
    chained = _chained_record(record, previous_hash)
    _append_fsynced(path, chained)
    return chained


def _last_hash(records: list[dict[str, Any]]) -> str:
    return str(records[-1]["record_hash"]) if records else GENESIS_HASH


def _snapshot_record(
    *,
    seq: int,
    timestamp_utc: str,
    equity: float,
    peak: float,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "timestamp_utc": timestamp_utc,
        "equity_usd": equity,
        "cash_usd": equity,
        "peak_equity_usd": peak,
        "drawdown": (peak - equity) / peak if peak > 0 else 0.0,
    }


def _verify_frozen_allocation(state: dict[str, Any]) -> None:
    allocation = state.get("frozen_allocation")
    claimed = str(state.get("frozen_allocation_sha256", ""))
    actual = sha256_of_text(canonical_dumps(allocation))
    if not claimed or actual != claimed:
        raise ValueError("frozen allocation hash mismatch; refusing shadow state")


def _load_state(state_dir: Path) -> dict[str, Any]:
    state_path = state_dir / "state.json"
    if not state_path.exists():
        raise ValueError(f"no shadow session at {state_path}")
    state = load_json(state_path)
    _verify_frozen_allocation(state)
    return state


def _write_checkpoint(
    out: Path,
    *,
    events: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> None:
    last_snapshot = snapshots[-1]
    atomic_write_json(
        out / "checkpoint.json",
        {
            "schema_version": 1,
            "last_event_hash": _last_hash(events),
            "last_snapshot_hash": _last_hash(snapshots),
            "last_seq": int(last_snapshot["seq"]),
            "equity_usd": float(last_snapshot["equity_usd"]),
        },
    )


def _recover_checkpoint(
    out: Path, state: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rebuild a missing snapshot after a crash from the fsynced event WAL."""
    events_path = out / "events.jsonl"
    snapshots_path = out / "snapshots.jsonl"
    events = _read_jsonl(events_path)
    snapshots = _read_jsonl(snapshots_path)
    _verify_chain(events, journal="events")
    _verify_chain(snapshots, journal="snapshots")

    initial = float(state["initial_capital_usd"])
    started = str(state["started_at_utc"])
    expected_payloads = [
        _snapshot_record(
            seq=0,
            timestamp_utc=started,
            equity=initial,
            peak=initial,
        )
    ]
    equity = peak = initial
    previous_seq = 0
    previous_timestamp = parse_utc(started)
    for event in events:
        seq = int(event["seq"])
        timestamp = parse_utc(str(event["timestamp_utc"]))
        if seq <= previous_seq or timestamp <= previous_timestamp:
            raise ValueError("event WAL sequence and timestamps must be strictly monotonic")
        expected_accrual = equity * float(event["cash_yield_daily"])
        if abs(expected_accrual - float(event["accrual_usd"])) > 1e-9 * max(1.0, abs(equity)):
            raise ValueError("event WAL accrual does not reconcile")
        equity += expected_accrual
        peak = max(peak, equity)
        expected_payloads.append(
            _snapshot_record(
                seq=seq,
                timestamp_utc=str(event["timestamp_utc"]),
                equity=equity,
                peak=peak,
            )
        )
        previous_seq = seq
        previous_timestamp = timestamp

    if len(snapshots) > len(expected_payloads):
        raise ValueError("snapshot journal is ahead of the event WAL")
    fields = tuple(expected_payloads[0])
    for index, actual in enumerate(snapshots):
        expected = expected_payloads[index]
        if any(actual.get(field) != expected[field] for field in fields):
            raise ValueError(f"snapshot does not match event WAL at record {index}")

    for payload in expected_payloads[len(snapshots) :]:
        appended = _append_chained(
            snapshots_path,
            payload,
            _last_hash(snapshots),
        )
        snapshots.append(appended)
    _write_checkpoint(out, events=events, snapshots=snapshots)
    return events, snapshots


def shadow_start(
    state_dir: str | Path,
    allocation: dict[str, Any],
    *,
    started_at_utc: str,
    commit_sha: str = "",
    max_drawdown: float = DEFAULT_MAX_DRAWDOWN,
    stale_hours: float = DEFAULT_STALE_HOURS,
) -> dict[str, Any]:
    """Freeze an allocation into a new shadow session."""
    parse_utc(started_at_utc)
    out = Path(state_dir)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    if state_path.exists():
        raise ValueError(f"shadow session already exists at {state_path}; stop it first")
    if not allocation.get("paper_only"):
        raise ValueError("only a PAPER allocation can seed a shadow session")
    frozen_sha = sha256_of_text(canonical_dumps(allocation))
    capital = float(allocation.get("total_capital_usd", 0.0))
    if capital <= 0:
        raise ValueError("allocation carries no capital")
    state = {
        "schema_version": 2,
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
    _recover_checkpoint(out, state)
    return state


def shadow_advance(state_dir: str | Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply a strictly ordered batch exactly once and checkpoint it."""
    out = Path(state_dir)
    state = _load_state(out)
    if state.get("status") != "RUNNING":
        raise ValueError(f"shadow session is {state.get('status')}; not advancing")
    existing_events, snapshots = _recover_checkpoint(out, state)

    sequences = [int(event["seq"]) for event in events]
    if len(sequences) != len(set(sequences)):
        raise ValueError("duplicate sequence within shadow event batch")
    batch_timestamps = [parse_utc(str(event["timestamp_utc"])) for event in events]
    if any(left >= right for left, right in zip(sequences, sequences[1:], strict=False)):
        raise ValueError("batch sequences must be strictly increasing")
    if any(
        left >= right for left, right in zip(batch_timestamps, batch_timestamps[1:], strict=False)
    ):
        raise ValueError("batch timestamps must be strictly increasing")

    processed = {int(event["seq"]): event for event in existing_events}
    last_seq = int(existing_events[-1]["seq"]) if existing_events else 0
    last_timestamp = (
        parse_utc(str(existing_events[-1]["timestamp_utc"]))
        if existing_events
        else parse_utc(str(state["started_at_utc"]))
    )
    equity = float(snapshots[-1]["equity_usd"])
    peak = float(snapshots[-1]["peak_equity_usd"])
    applied = skipped = 0

    for event in events:
        seq = int(event["seq"])
        timestamp_text = str(event["timestamp_utc"])
        timestamp = parse_utc(timestamp_text)
        cash_yield = float(event.get("cash_yield_daily", 0.0))
        if seq in processed:
            prior = processed[seq]
            if (
                str(prior["timestamp_utc"]) != timestamp_text
                or float(prior["cash_yield_daily"]) != cash_yield
            ):
                raise ValueError(f"sequence {seq} conflicts with the event WAL")
            skipped += 1
            continue
        if seq <= last_seq or timestamp <= last_timestamp:
            raise ValueError("event sequence and timestamp must be strictly monotonic")

        accrual = equity * cash_yield
        wal_record = _append_chained(
            out / "events.jsonl",
            {
                "seq": seq,
                "timestamp_utc": timestamp_text,
                "cash_yield_daily": cash_yield,
                "accrual_usd": accrual,
            },
            _last_hash(existing_events),
        )
        existing_events.append(wal_record)
        equity += accrual
        peak = max(peak, equity)
        snapshot = _append_chained(
            out / "snapshots.jsonl",
            _snapshot_record(
                seq=seq,
                timestamp_utc=timestamp_text,
                equity=equity,
                peak=peak,
            ),
            _last_hash(snapshots),
        )
        snapshots.append(snapshot)
        _write_checkpoint(out, events=existing_events, snapshots=snapshots)
        processed[seq] = wal_record
        last_seq = seq
        last_timestamp = timestamp
        applied += 1
    return {"applied": applied, "skipped": skipped, "equity_usd": equity}


def shadow_reconcile(state_dir: str | Path, *, now_utc: str) -> dict[str, Any]:
    """Rebuild equity from the flow journal and evaluate kill switches."""
    out = Path(state_dir)
    state = _load_state(out)
    try:
        events, snapshots = _recover_checkpoint(out, state)
    except ValueError as exc:
        report = {
            "session_id": state["session_id"],
            "reconciled": False,
            "reconciliation_error_usd": None,
            "equity_rebuilt_usd": None,
            "equity_reported_usd": None,
            "drawdown": None,
            "data_age_hours": None,
            "kill_switches": {
                "stale_data": False,
                "drawdown": False,
                "exposure": False,
                "reconciliation": True,
            },
            "kill_switch_engaged": True,
            "integrity_error": str(exc),
            "evaluated_at_utc": now_utc,
        }
        atomic_write_json(out / "reconcile.json", report)
        state["status"] = "HALTED_KILL_SWITCH"
        atomic_write_json(out / "state.json", state)
        return report
    initial = float(state["initial_capital_usd"])
    rebuilt = initial + sum(float(event["accrual_usd"]) for event in events)
    reported = float(snapshots[-1]["equity_usd"])
    error = abs(rebuilt - reported)
    reconciled = error <= 1e-9 * max(1.0, initial)

    drawdown = float(snapshots[-1]["drawdown"])
    last_ts = str(snapshots[-1]["timestamp_utc"])
    age_hours = (parse_utc(now_utc) - parse_utc(last_ts)).total_seconds() / 3600.0
    kill = {
        "stale_data": age_hours > float(state["stale_hours"]),
        "drawdown": drawdown > float(state["max_drawdown"]),
        "exposure": False,
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
    initial = float(state["initial_capital_usd"])
    integrity_error = ""
    try:
        events, snapshots = _recover_checkpoint(out, state)
        last = snapshots[-1]
        equity = float(last["equity_usd"])
        drawdown = float(last["drawdown"])
        checkpoint_hash = _last_hash(snapshots)
    except ValueError as exc:
        integrity_error = str(exc)
        events = _read_jsonl(out / "events.jsonl")
        equity = initial
        drawdown = 0.0
        checkpoint_hash = ""
        if state.get("status") == "RUNNING":
            state["status"] = "HALTED_KILL_SWITCH"
            atomic_write_json(out / "state.json", state)
    reconcile = load_json(out / "reconcile.json") if (out / "reconcile.json").exists() else {}
    return {
        "artifact": "SHADOW_PORTFOLIO_STATUS",
        "schema_version": 2,
        "session_id": state["session_id"],
        "status": state["status"],
        "started_at_utc": state["started_at_utc"],
        "frozen_allocation_sha256": state["frozen_allocation_sha256"],
        "commit_sha": state.get("commit_sha", ""),
        "initial_capital_usd": initial,
        "equity_usd": equity,
        "total_return": equity / initial - 1.0 if initial else 0.0,
        "drawdown": drawdown,
        "events_processed": len(events),
        "checkpoint_hash": checkpoint_hash,
        "integrity_error": integrity_error,
        "scoreboard": {
            "shadow_equity_usd": equity,
            "cash_benchmark_usd": equity,
            "active_return": 0.0,
        },
        "last_reconcile": reconcile,
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
    }


def shadow_stop(state_dir: str | Path, *, stopped_at_utc: str) -> dict[str, Any]:
    out = Path(state_dir)
    state = _load_state(out)
    _recover_checkpoint(out, state)
    state["status"] = "STOPPED"
    state["stopped_at_utc"] = stopped_at_utc
    atomic_write_json(out / "state.json", state)
    return state
