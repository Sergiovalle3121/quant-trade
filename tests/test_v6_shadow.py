"""Persistent shadow portfolio: frozen config, idempotent replay, kill switches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.opportunities.shadow import (
    shadow_advance,
    shadow_reconcile,
    shadow_start,
    shadow_status,
    shadow_stop,
)

START = "2026-07-25T00:00:00Z"


def _allocation(capital=100_000.0):
    return {
        "artifact": "PAPER_CAPITAL_ALLOCATION",
        "paper_only": True,
        "total_capital_usd": capital,
        "allocations": [
            {"entry_id": "cash_usd", "kind": "cash", "fraction": 1.0,
             "capital_usd": capital}
        ],
    }


def _events(n, daily_yield=0.0001, start_day=25):
    return [
        {
            "seq": i + 1,
            "timestamp_utc": f"2026-07-{start_day + (i + 1) // 24:02d}T{(i + 1) % 24:02d}:00:00Z",
            "cash_yield_daily": daily_yield,
        }
        for i in range(n)
    ]


def test_start_freezes_the_allocation_and_refuses_overwrite(tmp_path):
    state = shadow_start(tmp_path, _allocation(), started_at_utc=START, commit_sha="abc")
    assert state["status"] == "RUNNING"
    assert state["frozen_allocation_sha256"]
    with pytest.raises(ValueError, match="already exists"):
        shadow_start(tmp_path, _allocation(), started_at_utc=START)
    # non-paper allocations can never seed a shadow session
    with pytest.raises(ValueError, match="PAPER"):
        shadow_start(tmp_path / "other", {"paper_only": False}, started_at_utc=START)


def test_advance_is_idempotent_on_resume(tmp_path):
    shadow_start(tmp_path, _allocation(), started_at_utc=START)
    events = _events(10)
    first = shadow_advance(tmp_path, events)
    assert first["applied"] == 10
    second = shadow_advance(tmp_path, events)  # resume: nothing double-applied
    assert second["applied"] == 0
    assert second["skipped"] == 10
    assert second["equity_usd"] == pytest.approx(first["equity_usd"])
    status = shadow_status(tmp_path)
    assert status["events_processed"] == 10
    assert status["equity_usd"] > 100_000.0


def test_reconcile_rebuilds_equity_from_flows(tmp_path):
    shadow_start(tmp_path, _allocation(), started_at_utc=START)
    shadow_advance(tmp_path, _events(5))
    report = shadow_reconcile(tmp_path, now_utc="2026-07-25T06:00:00Z")
    assert report["reconciled"] is True
    assert report["kill_switch_engaged"] is False


def test_tampered_snapshot_engages_the_reconciliation_kill_switch(tmp_path):
    shadow_start(tmp_path, _allocation(), started_at_utc=START)
    shadow_advance(tmp_path, _events(5))
    snaps = tmp_path / "snapshots.jsonl"
    lines = snaps.read_text().splitlines()
    last = json.loads(lines[-1])
    last["equity_usd"] += 1_000.0  # someone edits the books
    snaps.write_text("\n".join(lines[:-1] + [json.dumps(last)]) + "\n")
    report = shadow_reconcile(tmp_path, now_utc="2026-07-25T06:00:00Z")
    assert report["reconciled"] is False
    assert report["kill_switches"]["reconciliation"] is True
    assert shadow_status(tmp_path)["status"] == "HALTED_KILL_SWITCH"


def test_stale_data_kill_switch(tmp_path):
    shadow_start(tmp_path, _allocation(), started_at_utc=START, stale_hours=24.0)
    shadow_advance(tmp_path, _events(2))
    report = shadow_reconcile(tmp_path, now_utc="2026-07-30T00:00:00Z")
    assert report["kill_switches"]["stale_data"] is True
    assert report["kill_switch_engaged"] is True


def test_drawdown_kill_switch(tmp_path):
    shadow_start(tmp_path, _allocation(), started_at_utc=START, max_drawdown=0.01)
    # negative cash yield (a real possibility) drags equity down 2%+
    shadow_advance(tmp_path, _events(20, daily_yield=-0.002))
    report = shadow_reconcile(tmp_path, now_utc="2026-07-25T21:00:00Z")
    assert report["kill_switches"]["drawdown"] is True
    # a halted session refuses to advance
    with pytest.raises(ValueError, match="HALTED"):
        shadow_advance(tmp_path, _events(1, start_day=27))


def test_stop_preserves_state(tmp_path):
    shadow_start(tmp_path, _allocation(), started_at_utc=START)
    shadow_advance(tmp_path, _events(3))
    state = shadow_stop(tmp_path, stopped_at_utc="2026-07-25T12:00:00Z")
    assert state["status"] == "STOPPED"
    assert Path(tmp_path / "snapshots.jsonl").exists()
    with pytest.raises(ValueError, match="STOPPED"):
        shadow_advance(tmp_path, _events(1, start_day=27))


def test_cli_shadow_lifecycle(tmp_path):
    from typer.testing import CliRunner

    from quant_trade.cli import app

    runner = CliRunner()
    allocation_path = tmp_path / "PAPER_CAPITAL_ALLOCATION.json"
    allocation_path.write_text(json.dumps(_allocation()))
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in _events(4)) + "\n")
    state_dir = tmp_path / "shadow"

    started = runner.invoke(
        app,
        [
            "opportunities", "shadow-start",
            "--allocation", str(allocation_path),
            "--state-dir", str(state_dir),
            "--started-at-utc", START,
        ],
    )
    assert started.exit_code == 0, started.output
    advanced = runner.invoke(
        app,
        [
            "opportunities", "shadow-advance",
            "--state-dir", str(state_dir),
            "--events", str(events_path),
        ],
    )
    assert advanced.exit_code == 0, advanced.output
    assert "applied=4" in advanced.output
    reconciled = runner.invoke(
        app,
        [
            "opportunities", "shadow-reconcile",
            "--state-dir", str(state_dir),
            "--now-utc", "2026-07-25T05:00:00Z",
        ],
    )
    assert reconciled.exit_code == 0, reconciled.output
    status_path = tmp_path / "SHADOW_PORTFOLIO_STATUS.json"
    status = runner.invoke(
        app,
        [
            "opportunities", "shadow-status",
            "--state-dir", str(state_dir),
            "--output", str(status_path),
        ],
    )
    assert status.exit_code == 0, status.output
    payload = json.loads(status_path.read_text())
    assert payload["artifact"] == "SHADOW_PORTFOLIO_STATUS"
    assert payload["real_money_authorized"] is False
