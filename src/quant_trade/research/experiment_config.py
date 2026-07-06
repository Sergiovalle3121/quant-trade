import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CostConfig:
    """Trading-cost settings for experiments.

    Defaults are deliberately conservative (5 bps commission, 5 bps slippage,
    2 bps spread): omitting the ``costs`` block must never produce a
    frictionless backtest. Zero costs require explicitly setting every field
    to 0 in the experiment config.
    """

    fixed_commission: float = 0.0
    percentage_commission: float = 0.0005
    slippage_bps: float = 5.0
    min_commission: float = 0.0
    spread_bps: float = 2.0


@dataclass
class SplitConfig:
    method: str = "chronological"
    train_fraction: float = 0.7
    train_start: str | None = None
    train_end: str | None = None
    test_start: str | None = None
    test_end: str | None = None
    train_size: int | None = None
    test_size: int | None = None
    step_size: int | None = None
    # Bars dropped at the train/test boundary so lookback features cannot
    # leak train information into out-of-sample evidence.
    embargo_bars: int = 0


@dataclass
class ExperimentConfig:
    experiment_name: str
    strategy: str
    strategy_params: dict[str, Any]
    data_path: str
    initial_cash: float = 10000
    costs: CostConfig = field(default_factory=CostConfig)
    risk_settings: dict[str, Any] = field(default_factory=dict)
    split: SplitConfig = field(default_factory=SplitConfig)
    output_dir: str = "outputs"
    parameter_grid: dict[str, list[Any]] = field(default_factory=dict)
    ranking_metric: str = "sharpe"

    def __post_init__(self):
        if not self.experiment_name:
            raise ValueError("experiment_name is required")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.split.method not in {"chronological", "date", "walk_forward"}:
            raise ValueError("split.method must be chronological, date, or walk_forward")


def _build(raw: dict[str, Any]) -> ExperimentConfig:
    raw = dict(raw)
    raw["costs"] = CostConfig(**raw.get("costs", {}))
    raw["split"] = SplitConfig(**raw.get("split", {}))
    return ExperimentConfig(**raw)


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    p = Path(path)
    text = p.read_text()
    raw = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("config must contain a mapping/object")
    try:
        return _build(raw)
    except TypeError as exc:
        raise ValueError(f"invalid config fields: {exc}") from exc
