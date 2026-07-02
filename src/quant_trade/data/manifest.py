"""Dataset manifest helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.data.requests import HistoricalDataRequest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    path: Path, data: pd.DataFrame, request: HistoricalDataRequest, warnings: list[str]
) -> dict[str, Any]:
    return {
        "dataset_id": path.stem,
        "provider": request.provider,
        "symbols": request.symbols,
        "interval": request.interval,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "adjusted": request.adjusted,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "row_count": int(len(data)),
        "min_timestamp": str(data["timestamp"].min()),
        "max_timestamp": str(data["timestamp"].max()),
        "columns": list(data.columns),
        "sha256": file_sha256(path),
        "data_file": str(path),
        "validation_status": "passed",
        "quality_warnings": warnings,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    manifest_path = path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path
