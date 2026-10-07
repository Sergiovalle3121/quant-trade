"""Private diagnostics never initialize or change the source SQLite database."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_trade.personal_paper import engine
from quant_trade.personal_paper.cli import app
from quant_trade.personal_paper.config import PersonalPaperError
from quant_trade.personal_paper.store import PaperStore


def _database_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _foreign_snapshot(path: Path) -> tuple[str, str, list[tuple], list[tuple]]:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
        schema = connection.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        rows = connection.execute("SELECT * FROM unrelated").fetchall()
    return _database_digest(path), journal, schema, rows


def _sealed_writer(path: Path) -> PaperStore:
    store = PaperStore(path)
    manifest = {
        "prospective_started_at": None,
        "clock_source": "SYSTEM_UTC",
        "closed_sessions": 0,
        "evidence_kind": "SYNTHETIC",
        "calendar_checked": False,
        "historical_trials": [],
        "historical_trial_ids": [],
        "real_money_approved": False,
    }
    book = {
        "portfolio": "inverse_volatility",
        "initial_cash_usd": 1000.0,
        "cash_usd": 1000.0,
        "positions": {},
        "drawdown": 0.0,
        "paused": True,
        "pause_reason": "synthetic reviewed pause",
        "rebalance_count": 0,
    }
    with store.writing():
        store.seal_book("synthetic@1x", book)
        store.seal_manifest(manifest)
    return store


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
@pytest.mark.parametrize("command", ["store", "status", "export", "economic-review"])
def test_foreign_sqlite_is_rejected_without_changing_source_or_creating_export(
    tmp_path: Path, journal: str, command: str
) -> None:
    source, output = tmp_path / "unrelated.sqlite", tmp_path / "unused-export"
    with sqlite3.connect(source) as connection:
        connection.execute(f"PRAGMA journal_mode={journal}")
        connection.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES (1,'synthetic preserved value')")
    before = _foreign_snapshot(source)
    if command == "economic-review":
        result = CliRunner().invoke(
            app, [command, "--database", str(source), "--output", str(output)]
        )
        assert result.exit_code != 0
        assert isinstance(result.exception, PersonalPaperError)
        assert "schema" in str(result.exception)
    else:
        with pytest.raises(PersonalPaperError, match="schema"):
            if command == "store":
                PaperStore(source, read_only=True)
            elif command == "status":
                engine.status(source)
            else:
                engine.export(source, output)
    assert _foreign_snapshot(source) == before
    assert not output.exists()


def test_missing_reader_path_never_creates_file_or_parent(tmp_path: Path) -> None:
    source = tmp_path / "absent-parent" / "absent.sqlite"
    with pytest.raises(PersonalPaperError, match="cannot be read"):
        PaperStore(source, read_only=True)
    assert not source.exists() and not source.parent.exists()
    with pytest.raises(PersonalPaperError, match="does not exist"):
        engine.status(source)
    with pytest.raises(PersonalPaperError, match="does not exist"):
        engine.export(source, tmp_path / "unused-export")
    assert not source.parent.exists() and not (tmp_path / "unused-export").exists()


def test_empty_paper_schema_without_registration_cannot_create_export(tmp_path: Path) -> None:
    source, output = tmp_path / "unregistered.sqlite", tmp_path / "unused-export"
    PaperStore(source).close()
    before = _database_digest(source)
    for diagnostic in (engine.status, lambda path: engine.export(path, output)):
        with pytest.raises(PersonalPaperError, match="registration is absent"):
            diagnostic(source)
    result = CliRunner().invoke(
        app, ["economic-review", "--database", str(source), "--output", str(output)]
    )
    assert isinstance(result.exception, PersonalPaperError)
    assert "registration is absent" in str(result.exception)
    assert _database_digest(source) == before and not output.exists()


@pytest.mark.parametrize("missing", ["table", "column"])
def test_missing_schema_components_fail_as_domain_errors(tmp_path: Path, missing: str) -> None:
    source = tmp_path / "incompatible.sqlite"
    PaperStore(source).close()
    with sqlite3.connect(source) as connection:
        if missing == "table":
            connection.execute("DROP TABLE bars")
        else:
            connection.execute("ALTER TABLE bars RENAME COLUMN sha TO wrong_column")
    before = _database_digest(source)
    with pytest.raises(PersonalPaperError, match="schema is absent or incompatible"):
        PaperStore(source, read_only=True)
    assert _database_digest(source) == before


def test_non_sqlite_file_is_rejected_without_changes_or_raw_sql(tmp_path: Path) -> None:
    source = tmp_path / "not-sqlite.sqlite"
    source.write_bytes(b"synthetic non-SQLite content")
    before = source.read_bytes()
    with pytest.raises(PersonalPaperError, match="cannot be read") as raised:
        PaperStore(source, read_only=True)
    assert "SELECT" not in str(raised.value)
    assert source.read_bytes() == before


def test_reader_matches_writer_and_uri_escapes_filename(tmp_path: Path) -> None:
    source = tmp_path / "paper spaces %23 # á.sqlite"
    writer = _sealed_writer(source)
    try:
        writer.verify()
        expected = deepcopy((writer.get("manifest"), writer.books()))
        reader = PaperStore(source, read_only=True)
        try:
            with reader.reading():
                reader.verify()
                assert (reader.get("manifest"), reader.books()) == expected
            with (
                pytest.raises(PersonalPaperError, match="read-only; writing is forbidden"),
                reader.writing(),
            ):
                pytest.fail("a read-only store entered a write transaction")
            assert not reader.db.in_transaction
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                reader.db.execute("DELETE FROM books")
            assert (reader.get("manifest"), reader.books()) == expected
        finally:
            reader.close()
        assert (writer.get("manifest"), writer.books()) == expected
        assert len(list(tmp_path.glob("*.sqlite"))) == 1
    finally:
        writer.close()


def test_reader_initialization_uses_only_schema_queries(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "readable.sqlite"
    _sealed_writer(source).close()
    commands: list[str] = []
    actual_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        assert kwargs["uri"] is True and str(args[0]).endswith("?mode=ro")
        connection = actual_connect(*args, **kwargs)
        connection.set_trace_callback(commands.append)
        return connection

    monkeypatch.setattr("quant_trade.personal_paper.store.sqlite3.connect", traced_connect)
    PaperStore(source, read_only=True).close()
    assert commands
    assert all(sql.startswith(("SELECT ", "PRAGMA table_info(")) for sql in commands)


def test_reader_preserves_snapshot_and_sees_committed_wal_after_transaction(tmp_path: Path) -> None:
    source = tmp_path / "wal.sqlite"
    writer = _sealed_writer(source)
    writer.db.execute("PRAGMA wal_autocheckpoint=0")
    reader = PaperStore(source, read_only=True)
    try:
        with reader.reading():
            reader.verify()
            original = reader.books()
            with writer.writing():
                updated = writer.books()["synthetic@1x"]
                updated["pause_reason"] = "synthetic later committed pause"
                writer.seal_book("synthetic@1x", updated)
            assert reader.books() == original
            reader.verify()
        assert source.with_name(source.name + "-wal").stat().st_size > 0
        with reader.reading():
            reader.verify()
            assert reader.books() == writer.books()
            assert (
                reader.books()["synthetic@1x"]["pause_reason"]
                != original["synthetic@1x"]["pause_reason"]
            )
    finally:
        reader.close()
        writer.close()


def test_status_export_and_economic_review_preserve_sealed_source(tmp_path: Path) -> None:
    source, output = tmp_path / "paper.sqlite", tmp_path / "export"
    _sealed_writer(source).close()
    before = _database_digest(source)
    status = engine.status(source)
    assert status["status"] == "PAUSED"
    assert status["books"]["synthetic@1x"]["pause_reason"] == "synthetic reviewed pause"
    assert status["real_money_approved"] is False
    paths = engine.export(source, output)
    assert json.loads(Path(paths["manifest"]).read_text(encoding="utf-8")) == status["manifest"]
    result = CliRunner().invoke(
        app, ["economic-review", "--database", str(source), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    review = json.loads(result.stdout)
    assert review["status"] == "INCONCLUSIVE" and review["real_money_approved"] is False
    assert _database_digest(source) == before
