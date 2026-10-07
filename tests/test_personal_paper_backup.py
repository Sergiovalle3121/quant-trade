from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from quant_trade.personal_paper import engine
from quant_trade.personal_paper.backup import create_backup
from quant_trade.personal_paper.config import PersonalPaperError
from quant_trade.personal_paper.demo import create_demo
from quant_trade.personal_paper.store import PaperStore


def test_backup_restores_committed_wal_pause_positions_and_restart(tmp_path):
    fixture = create_demo(tmp_path / "data", sessions=100)
    config = Path(__file__).resolve().parents[1] / "configs/personal/synthetic_demo.yaml"
    source, restored = tmp_path / "source.sqlite", tmp_path / "restored.sqlite"
    engine.run(config, fixture["data"], fixture["fx"], source)
    # Keep a connection open, with an uncheckpointed committed WAL modification.
    store = PaperStore(source)
    try:
        store.db.execute("PRAGMA wal_autocheckpoint=0")
        with store.writing():
            books = store.books()
            for key, book in books.items():
                book["paused"], book["pause_reason"] = True, "backup recovery test"
                store.seal_book(key, book)
            store.event("manual_pause", {"reason": "backup recovery test"})
        assert source.with_name(source.name + "-wal").stat().st_size > 0
        receipt = create_backup(source, restored)
        before = engine.status(source)
        after = engine.status(restored)
        assert before["books"] == after["books"]
        assert before["manifest"] == after["manifest"]
        assert receipt["journal_tip_sha256"]
        assert receipt["real_money_approved"] is False
        assert all(book["paused"] for book in after["books"].values())
        with sqlite3.connect(restored) as db:
            previous = db.execute("SELECT COUNT(*) FROM events WHERE kind='fill'").fetchone()[0]
        again = engine.run(config, fixture["data"], fixture["fx"], restored)
        assert again["books"] == after["books"]
        with sqlite3.connect(restored) as db:
            assert (
                db.execute("SELECT COUNT(*) FROM events WHERE kind='fill'").fetchone()[0]
                == previous
            )
        with pytest.raises(PersonalPaperError, match="new"):
            create_backup(source, restored)
    finally:
        store.close()


def test_corrupt_backup_is_refused_and_never_published(tmp_path):
    fixture = create_demo(tmp_path / "data", sessions=100)
    config = Path(__file__).resolve().parents[1] / "configs/personal/synthetic_demo.yaml"
    source, restored = tmp_path / "source.sqlite", tmp_path / "restored.sqlite"
    engine.run(config, fixture["data"], fixture["fx"], source)
    with sqlite3.connect(source) as db:
        key, text = db.execute("SELECT id,value FROM books LIMIT 1").fetchone()
        book = json.loads(text)
        book["cash_usd"] += 10
        db.execute("UPDATE books SET value=? WHERE id=?", (json.dumps(book), key))
    with pytest.raises(PersonalPaperError, match="reconciliation"):
        create_backup(source, restored)
    assert not restored.exists()
    assert not list(tmp_path.glob("*.creating-*"))
