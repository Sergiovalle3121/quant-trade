"""Verified SQLite snapshot copies, including committed rows still in WAL."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_trade.personal_paper.config import PersonalPaperError, file_hash
from quant_trade.personal_paper.store import PaperStore


def create_backup(database: Path, destination: Path) -> dict[str, Any]:
    """Publish a new verified copy; never replace a live or existing database.

    SQLite's backup API takes a transactionally consistent snapshot rather than
    copying a file without its WAL. Restoring means using the verified copy as
    a NEW database path, retaining the original, with its exact frozen code.
    """
    source_path, target_path = database.resolve(), destination.resolve()
    if not source_path.is_file():
        raise PersonalPaperError("backup requires an existing paper database")
    if target_path.exists() or source_path == target_path:
        raise PersonalPaperError("backup destination must be new; no overwrite is permitted")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.creating-{uuid.uuid4().hex}")
    temporary.touch(exist_ok=False)
    try:
        source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=5)
        copy = sqlite3.connect(temporary, timeout=5)
        try:
            copy.execute("PRAGMA synchronous=FULL")
            source.backup(copy, pages=256)
        finally:
            copy.close()
            source.close()
        restored = PaperStore(temporary)
        try:
            with restored.reading():
                integrity = [row[0] for row in restored.db.execute("PRAGMA integrity_check")]
                if integrity != ["ok"]:
                    raise PersonalPaperError("SQLite backup integrity check failed")
                restored.verify()
                manifest = restored.get("manifest")
                if manifest is None:
                    raise PersonalPaperError("backup has no sealed paper registration")
                tip = restored.db.execute(
                    "SELECT sha FROM events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()[0]
                events = restored.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            restored.close()
        # Same-directory hard link is atomic and fails if a racing caller creates
        # destination. Unlike replace(), it cannot erase somebody else's file.
        os.link(temporary, target_path)
        return {
            "backup": str(target_path),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "sha256": file_hash(target_path),
            "journal_tip_sha256": str(tip),
            "journal_events": int(events),
            "restore_verification": "SQLITE_INTEGRITY_AND_PAPER_RECONCILIATION_PASSED",
            "real_money_approved": False,
        }
    finally:
        # Only files made by this invocation are removed, never source/destination.
        for suffix in ("", "-wal", "-shm"):
            temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
