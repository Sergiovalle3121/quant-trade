"""Data lake configuration loading."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class DataLakeConfig(BaseModel):
    lake_root: Path = Path("data/lake")
    outputs_root: Path = Path("outputs/datalake")
    registry_dir: Path = Path("data/lake/registry")
    manifests_dir: Path = Path("data/lake/manifests")
    snapshots_dir: Path = Path("data/lake/snapshots")
    datasets_dir: Path = Path("data/lake/datasets")
    quality_reports_dir: Path = Path("data/lake/quality_reports")


def load_datalake_config(path: Path | None = None) -> DataLakeConfig:
    payload: dict[str, object] = {}
    if path is not None and path.exists():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = DataLakeConfig(**payload)
    for directory in (
        cfg.registry_dir,
        cfg.manifests_dir,
        cfg.snapshots_dir,
        cfg.datasets_dir,
        cfg.quality_reports_dir,
        cfg.outputs_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return cfg
