"""A private writer never adopts an unrelated or partly compatible SQLite."""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from quant_trade.personal_paper import engine
from quant_trade.personal_paper.config import PersonalPaperError
from quant_trade.personal_paper.demo import create_demo
from quant_trade.personal_paper.store import PaperStore

_CRASHED_WAL = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA wal_autocheckpoint=0')
db.execute('CREATE TABLE unrelated(id INTEGER PRIMARY KEY, value TEXT)')
db.execute("INSERT INTO unrelated VALUES (1,'synthetic committed WAL')")
db.commit()
os._exit(0)
"""


def _snapshot(path: Path, *, unrelated: bool = False):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        journal = db.execute("PRAGMA journal_mode").fetchone()[0]
        schema = db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name"
        ).fetchall()
        rows = db.execute("SELECT * FROM unrelated").fetchall() if unrelated else []
    wal = path.with_name(path.name + "-wal")
    return (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        journal,
        schema,
        rows,
        hashlib.sha256(wal.read_bytes()).hexdigest() if wal.exists() else None,
    )


@pytest.mark.parametrize("source_kind", ["delete", "live_wal", "crashed_wal"])
@pytest.mark.parametrize("command", ["store", "pause", "run"])
def test_foreign_writer_paths_preserve_main_wal_schema_journal_and_rows(
    tmp_path: Path, source_kind: str, command: str
):
    source = tmp_path / "unrelated.sqlite"
    writer = None
    if source_kind == "crashed_wal":
        subprocess.run([sys.executable, "-B", "-c", _CRASHED_WAL, str(source)], check=True)
    else:
        writer = sqlite3.connect(source)
        if source_kind == "live_wal":
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY,value TEXT)")
        writer.execute("INSERT INTO unrelated VALUES (1,'synthetic preserved value')")
        writer.commit()
        if source_kind == "delete":
            writer.close()
            writer = None
    try:
        if source_kind != "delete":
            assert source.with_name(source.name + "-wal").stat().st_size > 0
        before = _snapshot(source, unrelated=True)
        with pytest.raises(PersonalPaperError, match="unrelated or incompatible schema"):
            if command == "store":
                PaperStore(source)
            elif command == "pause":
                engine.pause(source, "synthetic mistaken database path")
            else:
                data = create_demo(tmp_path / "synthetic-inputs", sessions=65)
                engine.run(
                    Path("configs/personal/synthetic_demo.yaml"), data["data"], data["fx"], source
                )
        assert _snapshot(source, unrelated=True) == before
    finally:
        if writer is not None:
            writer.close()


@pytest.mark.parametrize("kind", ["absent", "zero_bytes", "empty_sqlite", "empty_paper"])
def test_new_and_empty_destinations_keep_the_current_schema(tmp_path: Path, kind: str):
    source = tmp_path / "new-parent" / "paper spaces %23 # á.sqlite"
    if kind != "absent":
        source.parent.mkdir()
        if kind == "zero_bytes":
            source.touch()
        elif kind == "empty_sqlite":
            with closing(sqlite3.connect(source)) as db:
                db.execute("PRAGMA user_version=0")
        else:
            PaperStore(source).close()
    store = PaperStore(source)
    try:
        store.verify()
        assert store.get("manifest") is None
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert {
            row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } == {"meta", "books", "bars", "events", "curves"}
        assert len(list(store.db.execute("SELECT * FROM sqlite_master WHERE type='index'"))) == 5
    finally:
        store.close()


@pytest.mark.parametrize(
    "alteration",
    [
        "DROP TABLE bars",
        "ALTER TABLE bars RENAME COLUMN sha TO wrong_column",
        "ALTER TABLE bars ADD COLUMN extra TEXT",
        "ALTER TABLE bars ADD COLUMN extra TEXT GENERATED ALWAYS AS (sha) VIRTUAL",
        "DROP TABLE bars; CREATE TABLE bars(timestamp TEXT PRIMARY KEY,"
        "sha TEXT NOT NULL GENERATED ALWAYS AS ('synthetic') VIRTUAL)",
        "DROP TABLE books; CREATE TABLE books(id TEXT PRIMARY KEY,value INTEGER NOT NULL)",
        "DROP TABLE meta; CREATE TABLE meta(key TEXT,value TEXT NOT NULL)",
        "DROP TABLE bars; CREATE TABLE bars(timestamp TEXT PRIMARY KEY,sha TEXT)",
        "DROP TABLE events; CREATE TABLE events(sequence INTEGER PRIMARY KEY,kind TEXT NOT NULL,"
        "value TEXT NOT NULL,previous_sha TEXT NOT NULL,sha TEXT NOT NULL)",
        "CREATE VIEW unrelated_view AS SELECT * FROM books",
        "CREATE TRIGGER unrelated_trigger AFTER INSERT ON books BEGIN SELECT 1; END",
    ],
)
def test_partial_or_incompatible_paper_is_refused_without_repair(tmp_path: Path, alteration: str):
    source = tmp_path / "incompatible.sqlite"
    PaperStore(source).close()
    with closing(sqlite3.connect(source)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.executescript(alteration)
    before = _snapshot(source)
    with pytest.raises(PersonalPaperError, match="unrelated or incompatible schema"):
        engine.pause(source, "synthetic incompatible database path")
    assert _snapshot(source) == before


def test_non_sqlite_input_is_rejected_without_modification(tmp_path: Path):
    source = tmp_path / "non-sqlite.sqlite"
    contents = b"synthetic unrelated binary file"
    source.write_bytes(contents)
    with pytest.raises(PersonalPaperError, match="cannot open or initialize"):
        PaperStore(source)
    assert source.read_bytes() == contents


def test_indexes_and_sqlite_statistics_on_paper_tables_remain_compatible(tmp_path: Path):
    source = tmp_path / "indexed.sqlite"
    PaperStore(source).close()
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE INDEX private_bars_sha ON bars(sha)")
        db.execute("ANALYZE")
    store = PaperStore(source)
    try:
        store.verify()
        assert (
            store.db.execute(
                "SELECT name FROM sqlite_master WHERE name='private_bars_sha'"
            ).fetchone()[0]
            == "private_bars_sha"
        )
        assert (
            store.db.execute("SELECT name FROM sqlite_master WHERE name='sqlite_stat1'").fetchone()[
                0
            ]
            == "sqlite_stat1"
        )
    finally:
        store.close()


def test_schema_changed_after_preflight_is_rejected_before_wal_or_ddl(tmp_path: Path, monkeypatch):
    source = tmp_path / "raced.sqlite"
    source.touch()
    actual_connect = sqlite3.connect
    baseline = None

    def replace_empty_schema(*args, **kwargs):
        nonlocal baseline
        if str(args[0]).endswith("?mode=rw"):
            with closing(actual_connect(source)) as changed:
                changed.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY,value TEXT)")
                changed.execute("INSERT INTO unrelated VALUES (1,'synthetic raced value')")
                changed.commit()
            baseline = _snapshot(source, unrelated=True)
        return actual_connect(*args, **kwargs)

    monkeypatch.setattr("quant_trade.personal_paper.store.sqlite3.connect", replace_empty_schema)
    with pytest.raises(PersonalPaperError, match="unrelated or incompatible schema"):
        PaperStore(source)
    assert baseline is not None and _snapshot(source, unrelated=True) == baseline


def test_interrupted_schema_creation_is_atomic_and_can_retry(tmp_path: Path, monkeypatch):
    source = tmp_path / "interrupted.sqlite"
    actual_connect = sqlite3.connect

    class InterruptedCreation(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            result = super().execute(sql, *args, **kwargs)
            if sql.startswith("CREATE TABLE books("):
                raise sqlite3.OperationalError("synthetic interrupted initialization")
            return result

    monkeypatch.setattr(
        "quant_trade.personal_paper.store.sqlite3.connect",
        lambda *args, **kwargs: actual_connect(*args, **kwargs, factory=InterruptedCreation),
    )
    with pytest.raises(PersonalPaperError, match="cannot open or initialize"):
        PaperStore(source)
    assert _snapshot(source)[1:3] == ("delete", [])
    monkeypatch.setattr("quant_trade.personal_paper.store.sqlite3.connect", actual_connect)
    PaperStore(source).close()
    assert len(_snapshot(source)[2]) == 10


def test_other_initializer_is_blocked_until_the_complete_schema_commits(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "concurrent.sqlite"
    actual_connect = sqlite3.connect
    blocked = []

    class ObservedCreation(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("CREATE TABLE meta("):
                with pytest.raises(PersonalPaperError, match="another writer owns"):
                    PaperStore(source)
                blocked.append(True)
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(
        "quant_trade.personal_paper.store.sqlite3.connect",
        lambda *args, **kwargs: actual_connect(*args, **kwargs, factory=ObservedCreation),
    )
    PaperStore(source).close()
    assert blocked == [True]
    PaperStore(source).close()
