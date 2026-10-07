from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from quant_trade.personal_paper.config import PersonalPaperError, canonical, digest

_READ_SCHEMA = {
    "meta": {"key", "value"},
    "books": {"id", "value"},
    "bars": {"timestamp", "sha"},
    "events": {"sequence", "kind", "value", "previous_sha", "sha"},
    "curves": {"timestamp", "book", "value"},
}
_WRITE_COLUMNS = {
    "meta": (("key", "TEXT", 0, None, 1), ("value", "TEXT", 1, None, 0)),
    "books": (("id", "TEXT", 0, None, 1), ("value", "TEXT", 1, None, 0)),
    "bars": (("timestamp", "TEXT", 0, None, 1), ("sha", "TEXT", 1, None, 0)),
    "events": (
        ("sequence", "INTEGER", 0, None, 1),
        ("kind", "TEXT", 1, None, 0),
        ("value", "TEXT", 1, None, 0),
        ("previous_sha", "TEXT", 1, None, 0),
        ("sha", "TEXT", 1, None, 0),
    ),
    "curves": (
        ("timestamp", "TEXT", 1, None, 1),
        ("book", "TEXT", 1, None, 2),
        ("value", "TEXT", 1, None, 0),
    ),
}
_CREATE_SCHEMA = (
    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE books(id TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE bars(timestamp TEXT PRIMARY KEY, sha TEXT NOT NULL)",
    "CREATE TABLE events(sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
    "value TEXT NOT NULL, previous_sha TEXT NOT NULL, sha TEXT NOT NULL UNIQUE)",
    "CREATE TABLE curves(timestamp TEXT NOT NULL, book TEXT NOT NULL, value TEXT NOT NULL, "
    "PRIMARY KEY(timestamp,book))",
)


class PaperStore:
    """SQLite WAL + FULL fsync; the write transaction is the single-writer lease."""

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.read_only = read_only
        if read_only:
            connection = None
            try:
                # Preserve source data while including committed WAL. SQLite may
                # maintain WAL sidecars; immutable mode would hide new WAL rows.
                connection = sqlite3.connect(
                    path.resolve().as_uri() + "?mode=ro",
                    uri=True,
                    timeout=0,
                    isolation_level=None,
                )
                self.db = connection
                self.db.row_factory = sqlite3.Row
                self._validate_read_schema()
            except (sqlite3.DatabaseError, PersonalPaperError) as exc:
                if connection is not None:
                    connection.close()
                if isinstance(exc, PersonalPaperError):
                    raise
                raise PersonalPaperError(
                    "paper database cannot be read or its schema is invalid"
                ) from exc
            return
        connection = None
        try:
            existed = path.exists()
            if existed:
                preflight = sqlite3.connect(
                    path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0, isolation_level=None
                )
                try:
                    self._validate_write_schema(preflight)
                finally:
                    preflight.close()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                path.resolve().as_uri() + ("?mode=rw" if existed else "?mode=rwc"),
                uri=True,
                timeout=0,
                isolation_level=None,
            )
            self.db = connection
            self.db.row_factory = sqlite3.Row
            self.db.execute("BEGIN IMMEDIATE")
            try:
                # Revalidate under SQLite's writer lease: a preflight alone
                # cannot protect a database changed before the writer opens.
                if not self._validate_write_schema(self.db):
                    for statement in _CREATE_SCHEMA:
                        self.db.execute(statement)
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
        except BaseException as exc:
            if connection is not None:
                connection.close()
            if isinstance(exc, sqlite3.DatabaseError):
                if getattr(exc, "sqlite_errorcode", None) in (
                    sqlite3.SQLITE_BUSY,
                    sqlite3.SQLITE_LOCKED,
                ):
                    raise PersonalPaperError("another writer owns the paper database") from exc
                raise PersonalPaperError(
                    "paper writer cannot open or initialize this database"
                ) from exc
            raise

    @staticmethod
    def _validate_write_schema(connection: sqlite3.Connection) -> bool:
        objects = [
            row
            for row in connection.execute("SELECT type,name,tbl_name FROM sqlite_master")
            if not row[1].startswith("sqlite_")
        ]
        if not objects:
            return False
        tables = {row[1] for row in objects if row[0] == "table"}
        if tables != _WRITE_COLUMNS.keys() or any(
            row[0] not in {"table", "index"} or row[2] not in _WRITE_COLUMNS for row in objects
        ):
            raise PersonalPaperError("paper writer refuses an unrelated or incompatible schema")
        for table, expected in _WRITE_COLUMNS.items():
            rows = connection.execute(f"PRAGMA table_xinfo({table})").fetchall()
            columns = tuple((row[1], row[2].upper(), row[3], row[4], row[5]) for row in rows)
            if columns != expected or any(row[6] != 0 for row in rows):
                raise PersonalPaperError("paper writer refuses an unrelated or incompatible schema")
        unique_hash = any(
            index[2]
            and not index[4]
            and [
                row[2]
                for row in connection.execute("SELECT * FROM pragma_index_info(?)", (index[1],))
            ]
            == ["sha"]
            for index in connection.execute("PRAGMA index_list(events)")
        )
        if not unique_hash:
            raise PersonalPaperError("paper writer refuses an unrelated or incompatible schema")
        return True

    def _validate_read_schema(self) -> None:
        tables = {
            row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not _READ_SCHEMA.keys() <= tables:
            raise PersonalPaperError("paper database schema is absent or incompatible")
        for table, expected in _READ_SCHEMA.items():
            columns = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
            if not expected <= columns:
                raise PersonalPaperError("paper database schema is absent or incompatible")

    @contextmanager
    def reading(self):
        if self.db.in_transaction:
            yield self
            return
        self.db.execute("BEGIN")
        try:
            yield self
        finally:
            self.db.execute("ROLLBACK")

    @contextmanager
    def writing(self):
        if self.read_only:
            raise PersonalPaperError("paper database is read-only; writing is forbidden")
        try:
            self.db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise PersonalPaperError("another writer owns the paper database") from exc
        try:
            yield self
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def get(self, key: str) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, canonical(value)))

    def books(self) -> dict[str, dict[str, Any]]:
        return {r["id"]: json.loads(r["value"]) for r in self.db.execute("SELECT * FROM books")}

    def save_book(self, key: str, value: dict[str, Any]) -> None:
        self.db.execute("INSERT OR REPLACE INTO books VALUES (?,?)", (key, canonical(value)))

    def event(self, kind: str, value: dict[str, Any]) -> None:
        last = self.db.execute("SELECT sequence,sha FROM events ORDER BY sequence DESC LIMIT 1")
        previous = last.fetchone()
        seq, prev = (previous[0] + 1, previous[1]) if previous else (1, "GENESIS")
        sha = digest({"sequence": seq, "kind": kind, "value": value, "previous_sha": prev})
        self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)", (seq, kind, canonical(value), prev, sha)
        )

    def verify(self) -> None:
        with self.reading():
            self._verify_snapshot()

    def _verify_snapshot(self) -> None:
        prev = "GENESIS"
        seq = 0
        anchors: dict[str, str] = {}
        curves: dict[tuple[str, str], str] = {}
        manifest_sha = None
        bars: dict[str, str] = {}
        for r in self.db.execute("SELECT * FROM events ORDER BY sequence"):
            value = json.loads(r["value"])
            expected = digest(
                {"sequence": r["sequence"], "kind": r["kind"], "value": value, "previous_sha": prev}
            )
            if r["sequence"] != seq + 1 or r["previous_sha"] != prev or r["sha"] != expected:
                raise PersonalPaperError("paper journal hash chain is broken")
            prev, seq = r["sha"], r["sequence"]
            if r["kind"] == "book_state":
                anchors[value["book"]] = value["sha"]
            elif r["kind"] == "curve":
                curves[(value["timestamp"], value["book"])] = value["sha"]
            elif r["kind"] == "manifest":
                manifest_sha = value["sha"]
            elif r["kind"] == "bar":
                bars[value["timestamp"]] = value["sha"]
        # Rebuild cash and quantities from fills, never trust a caller-supplied equity.
        registration = self.get("manifest")
        if registration is None:
            return
        if digest(registration) != manifest_sha:
            raise PersonalPaperError("frozen paper manifest was edited")
        actual_bars = {r[0]: r[1] for r in self.db.execute("SELECT timestamp,sha FROM bars")}
        if bars != actual_bars:
            raise PersonalPaperError("paper input anchors were edited or removed")
        actual_curves = {
            (r["timestamp"], r["book"]): digest(json.loads(r["value"]))
            for r in self.db.execute("SELECT * FROM curves")
        }
        if actual_curves != curves:
            raise PersonalPaperError("paper curve observations were edited or removed")
        books = self.books()
        if set(books) != set(anchors):
            raise PersonalPaperError("paper books were removed or added outside the journal")
        for key, book in books.items():
            cash = float(book["initial_cash_usd"])
            positions: dict[str, float] = {}
            for r in self.db.execute(
                "SELECT kind,value FROM events WHERE kind IN ('fill','corporate_action') "
                "ORDER BY sequence"
            ):
                fill = json.loads(r[1])
                if fill["book"] != key:
                    continue
                if r[0] == "corporate_action":
                    positions[fill["symbol"]] = (
                        positions.get(fill["symbol"], 0.0) * fill["split_ratio"]
                    )
                    cash += fill["cash_credit_usd"]
                    continue
                signed = fill["quantity"] * (1 if fill["side"] == "buy" else -1)
                positions[fill["symbol"]] = positions.get(fill["symbol"], 0.0) + signed
                cash -= signed * fill["price"] + fill["fee_usd"]
            tolerance = max(1.0, book["initial_cash_usd"]) * 1e-9
            if abs(cash - book["cash_usd"]) > tolerance:
                raise PersonalPaperError(f"cash reconciliation failed: {key}")
            for sym in set(positions) | set(book["positions"]):
                if abs(positions.get(sym, 0.0) - book["positions"].get(sym, 0.0)) > 1e-8:
                    raise PersonalPaperError(f"position reconciliation failed: {key}/{sym}")
            if digest(book) != anchors.get(key):
                raise PersonalPaperError(f"persisted book was edited: {key}")

    def seal_book(self, key: str, value: dict[str, Any]) -> None:
        self.save_book(key, value)
        self.event("book_state", {"book": key, "sha": digest(value)})

    def seal_manifest(self, value: dict[str, Any]) -> None:
        self.put("manifest", value)
        self.event("manifest", {"sha": digest(value)})

    def close(self) -> None:
        self.db.close()
