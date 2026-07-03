"""Evidence lineage export."""

from __future__ import annotations

import json
from pathlib import Path

from quant_trade.evidence.config import EvidenceConfig
from quant_trade.evidence.database import connect, fetch_artifacts


def export_lineage(config: EvidenceConfig, strategy_id: str, run_id: str) -> Path:
    with connect(config.database_path) as conn:
        rows = [dict(row) for row in fetch_artifacts(conn, strategy_id)]
    out_dir = config.output_dir / "evidence" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"evidence_lineage_{strategy_id}.json"
    path.write_text(
        json.dumps({"strategy_id": strategy_id, "artifacts": rows, "links": []}, indent=2),
        encoding="utf-8",
    )
    return path
