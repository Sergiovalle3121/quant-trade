"""Data lake artifact reports."""

from __future__ import annotations

import json
from pathlib import Path

from .models import DatasetRegistryRecord


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def produce_lineage_report(record: DatasetRegistryRecord) -> dict:
    return {
        "dataset_id": record.dataset_id,
        "version": record.version,
        "provider": record.provider,
        "source_manifest": record.source_manifest,
        "data_hash": record.data_hash,
        "schema_hash": record.schema_hash,
        "paper_only_warning": (
            "Research/backtesting data lake only; not approved for live trading or order routing."
        ),
    }


def write_summary(path: Path, title: str, payload: dict) -> None:
    lines = [
        f"# {title}",
        "",
        "Research/backtesting only. No live trading or broker execution approval is implied.",
        "",
        "```json",
        json.dumps(payload, indent=2, sort_keys=True),
        "```",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
