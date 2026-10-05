from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from quant_trade.personal_paper.config import PersonalPaperError, canonical, digest


class PaperStore:
    """SQLite WAL + FULL fsync; the write transaction is the single-writer lease."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=0, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bars(timestamp TEXT PRIMARY KEY, sha TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL,
                    previous_sha TEXT NOT NULL, sha TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS curves(
                    timestamp TEXT NOT NULL, book TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY(timestamp,book));
            """)
        except sqlite3.OperationalError as exc:
            self.db.close()
            raise PersonalPaperError("another writer owns the paper database") from exc

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
