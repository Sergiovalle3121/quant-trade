from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import load_yaml, output_dir
from .models import CapitalRampResult


def simulate_capital_ramp(config: dict[str, Any]) -> list[CapitalRampResult]:
    levels = [float(x) for x in config.get("capital_levels", [10000, 25000, 50000, 100000, 250000])]
    max_pos = float(config.get("max_position_pct", 0.1))
    turnover = float(config.get("expected_turnover", 0.5))
    cost_bps = float(config.get("cost_bps", 5))
    dd = float(config.get("max_drawdown_pct", 0.15))
    daily = float(config.get("daily_loss_pct", 0.02))
    stress = float(config.get("stress_loss_pct", 0.25))
    cap = float(config.get("capacity_limit", 100000))
    out = []
    for level in levels:
        warning = "review liquidity/capacity" if level > cap else "none"
        conc = "high" if max_pos > 0.2 else "moderate" if max_pos > 0.1 else "controlled"
        out.append(
            CapitalRampResult(
                level,
                level * max_pos,
                level * turnover,
                level * turnover * cost_bps / 10000,
                warning,
                level * dd,
                level * daily,
                min(1.0, dd / max(float(config.get("risk_budget_pct", 0.2)), 1e-9)),
                conc,
                level * stress,
                min(level, cap),
                False,
            )
        )
    return out


def write_capital_ramp(config_path: Path) -> list[CapitalRampResult]:
    cfg = load_yaml(config_path)
    outdir = output_dir(cfg)
    rows = simulate_capital_ramp(cfg)
    with (outdir / "capital_ramp_results.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(asdict(rows[0]).keys()))
        w.writeheader()
        w.writerows(asdict(r) for r in rows)
    return rows
