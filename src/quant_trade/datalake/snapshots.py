"""Dataset snapshot creation and diffing."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import DataLakeConfig
from .models import DatasetSnapshot
from .registry import latest_record
from .versioning import compute_data_hash, compute_schema_hash, read_dataset


def create_snapshot(cfg: DataLakeConfig, dataset_id: str) -> DatasetSnapshot:
    rec = latest_record(cfg, dataset_id)
    source = Path(rec.data_path)
    snapshot_id = f"{dataset_id}_{rec.version}"
    dest = cfg.snapshots_dir / dataset_id / f"{rec.version}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    df = read_dataset(dest)
    snap = DatasetSnapshot(
        dataset_id=dataset_id,
        version=rec.version,
        snapshot_id=snapshot_id,
        source_data_path=str(source),
        snapshot_path=str(dest),
        schema_hash=compute_schema_hash(df),
        data_hash=compute_data_hash(dest),
        row_count=len(df),
    )
    meta = dest.with_suffix(".json")
    meta.write_text(json.dumps(snap.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
    return snap


def diff_snapshots(
    cfg: DataLakeConfig, dataset_id: str, from_version: str, to_version: str
) -> dict:
    a = cfg.snapshots_dir / dataset_id / f"{from_version}.json"
    b = cfg.snapshots_dir / dataset_id / f"{to_version}.json"
    old = json.loads(a.read_text(encoding="utf-8"))
    new = json.loads(b.read_text(encoding="utf-8"))
    return {
        "dataset_id": dataset_id,
        "from_version": from_version,
        "to_version": to_version,
        "schema_changed": old["schema_hash"] != new["schema_hash"],
        "data_changed": old["data_hash"] != new["data_hash"],
        "row_count_delta": new["row_count"] - old["row_count"],
    }
