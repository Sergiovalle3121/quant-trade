"""Configuration for the research-only ML alpha lab."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MLConfig:
    run_id: str = "synthetic_ml_baseline"
    output_root: str = "outputs/ml"
    provider: str = "synthetic"
    symbols: list[str] = field(default_factory=lambda: ["AAA", "BBB", "CCC"])
    start: str = "2020-01-01"
    end: str = "2021-01-01"
    interval: str = "1d"
    data_path: str | None = None
    seed: int = 42
    horizon_days: int = 5
    train_fraction: float = 0.7
    embargo_days: int = 0
    model: str = "simple_rank_model"
    prediction_bucket_count: int = 5
    top_fraction: float = 0.34
    initial_cash: float = 100000.0
    real_money_ready: bool = False

    @property
    def output_dir(self) -> Path:
        return Path(self.output_root) / self.run_id


def load_ml_config(path: Path) -> MLConfig:
    payload: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    payload["real_money_ready"] = False
    return MLConfig(**payload)


def dump_ml_config(config: MLConfig, path: Path) -> None:
    path.write_text(yaml.safe_dump(config.__dict__, sort_keys=True), encoding="utf-8")
