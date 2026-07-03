"""Evidence search helpers."""

from __future__ import annotations

from pathlib import Path

from quant_trade.evidence.database import connect


def search(database_path: Path, query: str) -> list[dict[str, str]]:
    needle = f"%{query.lower()}%"
    with connect(database_path) as conn:
        rows = conn.execute(
            "SELECT strategy_id, artifact_type, path FROM artifacts "
            "WHERE lower(path) LIKE ? OR lower(metadata_json) LIKE ? "
            "ORDER BY path",
            (needle, needle),
        )
        return [dict(row) for row in rows]
