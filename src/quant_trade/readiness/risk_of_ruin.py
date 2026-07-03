from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .config import load_yaml, output_dir
from .models import RiskOfRuinResult


def estimate_risk_of_ruin(config: dict[str, Any]) -> RiskOfRuinResult:
    returns = np.array(
        config.get("daily_returns", [0.001, -0.002, 0.003, -0.004, 0.0]), dtype=float
    )
    seed = int(config.get("seed", 7))
    paths = int(config.get("paths", 500))
    horizon = int(config.get("horizon_days", 60))
    dd_thr = float(config.get("ruin_drawdown_threshold", -0.2))
    daily_thr = float(config.get("daily_loss_threshold", -0.03))
    rng = np.random.default_rng(seed)
    worst = []
    dd_hits = 0
    daily_hits = 0
    for _ in range(paths):
        sample = rng.choice(returns, size=horizon, replace=True)
        equity = np.cumprod(1 + sample)
        peak = np.maximum.accumulate(equity)
        dd = equity / peak - 1
        m = float(dd.min())
        worst.append(m)
        dd_hits += m <= dd_thr
        daily_hits += bool((sample <= daily_thr).any())
    arr = np.array(worst)
    warnings = []
    if dd_hits / paths > 0.05:
        warnings.append("drawdown breach probability requires conservative human risk review")
    if daily_hits / paths > 0.05:
        warnings.append("daily loss breach probability requires tighter paper limits")
    return RiskOfRuinResult(
        float(dd_hits / paths),
        float(daily_hits / paths),
        float(arr.mean()),
        (float(np.quantile(arr, 0.05)), float(np.quantile(arr, 0.95))),
        warnings,
        False,
    )


def write_risk_of_ruin(config_path: Path) -> RiskOfRuinResult:
    cfg = load_yaml(config_path)
    out = output_dir(cfg)
    res = estimate_risk_of_ruin(cfg)
    (out / "risk_of_ruin.json").write_text(json.dumps(asdict(res), indent=2), encoding="utf-8")
    return res
