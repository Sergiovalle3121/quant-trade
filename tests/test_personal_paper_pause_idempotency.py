"""Repeated operational requests preserve the first pause cause and journal."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from quant_trade.personal_paper import engine, worker
from quant_trade.personal_paper.store import PaperStore


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-pause.sqlite"
    store = PaperStore(path)
    try:
        with store.writing():
            store.seal_manifest(
                {
                    "prospective_started_at": None,
                    "clock_source": "INJECTED_TEST_CLOCK",
                    "closed_sessions": 0,
                    "risk_limits": {"max_drawdown": 0.05},
                    "real_money_approved": False,
                }
            )
            for portfolio in engine.PORTFOLIOS:
                for multiplier in engine.COST_MULTIPLIERS:
                    store.seal_book(
                        f"{portfolio}:{multiplier}",
                        {
                            "portfolio": portfolio,
                            "initial_cash_usd": 1000.0,
                            "cash_usd": 1000.0,
                            "positions": {},
                            "paused": False,
                            "pause_reason": None,
                            "drawdown": 0.0,
                            "pending": None,
                        },
                    )
            store.verify()
    finally:
        store.close()
    return path


def _snapshot(database: Path):
    books = engine.status(database)["books"]
    with closing(sqlite3.connect(database)) as connection:
        events = connection.execute("SELECT * FROM events ORDER BY sequence").fetchall()
    return books, events


def _events(database: Path, kind: str) -> list[dict]:
    with closing(sqlite3.connect(database)) as connection:
        return [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT value FROM events WHERE kind=? ORDER BY sequence", (kind,)
            )
        ]


def test_identical_pause_after_restart_preserves_books_and_all_events(database: Path):
    engine.pause(database, "observed monthly budget exceeded", now_utc="2026-10-06T00:00:00Z")
    before = _snapshot(database)
    assert all(book["paused"] for book in before[0].values())
    assert len(_events(database, "manual_pause")) == 1
    assert len(_events(database, "book_state")) == 18

    # Every call reopens SQLite, as a restarted worker does; a new wall time
    # must not create another state transition for the identical request.
    engine.pause(database, "observed monthly budget exceeded", now_utc="2026-10-06T00:01:00Z")
    assert _snapshot(database) == before
    assert engine.status(database)["real_money_approved"] is False


@pytest.mark.parametrize("risk_reason", ["daily_loss_limit", "drawdown_limit_5pct"])
def test_budget_pause_keeps_prior_risk_cause_and_changes_only_active_books(
    database: Path, risk_reason: str
):
    store = PaperStore(database)
    try:
        with store.writing():
            key, book = next(iter(store.books().items()))
            book["paused"], book["pause_reason"] = True, risk_reason
            store.event("pause", {"book": key, "reason": risk_reason})
            store.seal_book(key, book)
    finally:
        store.close()
    original_risk_book = engine.status(database)["books"][key]
    original_states = len(_events(database, "book_state"))

    engine.pause(database, "observed monthly budget exceeded")
    paused = engine.status(database)["books"]
    assert paused[key] == original_risk_book
    assert all(book["paused"] for book in paused.values())
    assert all(
        book["pause_reason"] == "observed monthly budget exceeded"
        for other_key, book in paused.items()
        if other_key != key
    )
    assert len(_events(database, "book_state")) - original_states == 8
    assert _events(database, "manual_pause")[-1]["reason"] == "observed monthly budget exceeded"
    before_repeat = _snapshot(database)
    engine.pause(database, "observed monthly budget exceeded")
    assert _snapshot(database) == before_repeat


def test_different_manual_request_is_recorded_without_replacing_first_cause(database: Path):
    engine.pause(database, "original data-quality inspection")
    original_books = engine.status(database)["books"]
    original_states = len(_events(database, "book_state"))
    engine.pause(database, "observed monthly budget exceeded")
    assert engine.status(database)["books"] == original_books
    assert len(_events(database, "book_state")) == original_states
    assert [event["reason"] for event in _events(database, "manual_pause")] == [
        "original data-quality inspection",
        "observed monthly budget exceeded",
    ]
    before_repeat = _snapshot(database)
    engine.pause(database, "observed monthly budget exceeded")
    assert _snapshot(database) == before_repeat


def test_reviewed_resume_allows_the_same_reason_to_pause_again(database: Path):
    reason = "observed monthly budget exceeded"
    engine.pause(database, reason)
    engine.resume(database, "Reviewed data, budget and risk; continue simulated observations.")
    assert not any(book["paused"] for book in engine.status(database)["books"].values())
    states_before = len(_events(database, "book_state"))
    engine.pause(database, reason)
    assert all(book["paused"] for book in engine.status(database)["books"].values())
    assert len(_events(database, "book_state")) - states_before == 9
    assert len(_events(database, "manual_pause")) == 2
    assert len(_events(database, "reviewed_resume")) == 1


def test_unrelated_journal_checkpoint_does_not_repeat_last_control_request(database: Path):
    reason = "observed monthly budget exceeded"
    engine.pause(database, reason)
    store = PaperStore(database)
    try:
        with store.writing():
            store.seal_manifest(store.get("manifest"))
    finally:
        store.close()
    before = _snapshot(database)
    engine.pause(database, reason)
    assert _snapshot(database) == before


def test_repeated_over_budget_worker_does_not_grow_the_pause_journal(
    database: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        worker, "budget_review", lambda *args: {"status": "OVER_BUDGET", "observed_mxn": 501}
    )

    def forbidden(*args, **kwargs):
        pytest.fail("over-budget worker must not fetch or run the engine")

    monkeypatch.setattr(worker.fetch, "fetch_snapshot", forbidden)
    monkeypatch.setattr(worker.fetch, "fetch_open_quotes", forbidden)
    monkeypatch.setattr(worker.engine, "run", forbidden)
    config = Path("configs/personal/etf_private_v1.yaml")
    cache = tmp_path / "cache"
    first = worker.run_once(config, database, cache)
    before = _snapshot(database)
    second = worker.run_once(config, database, cache)
    assert (
        first
        == second
        == {
            "status": "BUDGET_PAUSED",
            "budget": {"status": "OVER_BUDGET", "observed_mxn": 501},
            "real_money_approved": False,
        }
    )
    assert _snapshot(database) == before
    assert json.loads((cache / "worker_status.json").read_text())["status"] == "BUDGET_PAUSED"


@pytest.mark.parametrize("failure_kind", ["book_state", "manual_pause"])
def test_interrupted_pause_rolls_back_all_transitions_and_request(
    database: Path, monkeypatch, failure_kind: str
):
    before = _snapshot(database)
    original_event = PaperStore.event
    written_states = 0

    def interrupted_event(store, kind, value):
        nonlocal written_states
        original_event(store, kind, value)
        if kind == "book_state":
            written_states += 1
        if kind == failure_kind and (kind == "manual_pause" or written_states == 2):
            raise OSError("synthetic interrupted pause transaction")

    monkeypatch.setattr(PaperStore, "event", interrupted_event)
    with pytest.raises(OSError, match="synthetic interrupted pause"):
        engine.pause(database, "observed monthly budget exceeded")
    assert _snapshot(database) == before
