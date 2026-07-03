"""Dataset registry persistence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import DataLakeConfig
from .models import DatasetDefinition, DatasetRegistryRecord, DatasetVersion, utc_now_iso
from .quality import generate_dataset_quality_report
from .versioning import compute_data_hash, compute_schema_hash, next_version, read_dataset

REGISTRY_FILE = "datasets.json"


def registry_path(cfg: DataLakeConfig) -> Path:
    return cfg.registry_dir / REGISTRY_FILE


def load_registry(cfg: DataLakeConfig) -> dict[str, list[dict]]:
    path = registry_path(cfg)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_registry(cfg: DataLakeConfig, registry: dict[str, list[dict]]) -> None:
    registry_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    registry_path(cfg).write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")


def latest_record(cfg: DataLakeConfig, dataset_id: str) -> DatasetRegistryRecord:
    records = load_registry(cfg).get(dataset_id, [])
    if not records:
        from .exceptions import DatasetNotFoundError

        raise DatasetNotFoundError(dataset_id)
    return DatasetRegistryRecord(**records[-1])


def register_dataset(
    cfg: DataLakeConfig, definition: DatasetDefinition, data_path: Path
) -> DatasetRegistryRecord:
    df = read_dataset(data_path)
    registry = load_registry(cfg)
    version = next_version([r["version"] for r in registry.get(definition.dataset_id, [])])
    schema_hash = compute_schema_hash(df)
    data_hash = compute_data_hash(data_path)
    manifest_path = cfg.manifests_dir / definition.dataset_id / f"{version}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stored_data = cfg.datasets_dir / definition.dataset_id / f"{version}.csv"
    stored_data.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data_path, stored_data)
    q = generate_dataset_quality_report(definition.dataset_id, df, version)
    manifest = {
        "dataset_id": definition.dataset_id,
        "version": version,
        "created_at_utc": utc_now_iso(),
        "source_path": str(data_path),
        "stored_data_path": str(stored_data),
        "schema_hash": schema_hash,
        "data_hash": data_hash,
        "row_count": len(df),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    rec = DatasetRegistryRecord(
        **definition.model_dump(),
        version=version,
        schema_hash=schema_hash,
        data_hash=data_hash,
        source_manifest=str(manifest_path),
        quality_status=q.status,
        data_path=str(stored_data),
        row_count=len(df),
    )
    registry.setdefault(definition.dataset_id, []).append(rec.model_dump())
    save_registry(cfg, registry)
    return rec


def list_versions(cfg: DataLakeConfig, dataset_id: str) -> list[DatasetVersion]:
    return [DatasetVersion(**r) for r in load_registry(cfg).get(dataset_id, [])]
