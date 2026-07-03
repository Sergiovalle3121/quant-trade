from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import load_yaml, output_dir


def calculate_loss_limits(config: dict[str, Any]) -> dict[str, Any]:
    capital = float(config.get("paper_capital", config.get("capital_levels", [10000])[0]))
    limits = dict(config.get("loss_limits", {}))
    result = {
        "portfolio_max_daily_loss": capital * float(limits.get("portfolio_daily_loss_pct", 0.02)),
        "strategy_max_daily_loss": capital * float(limits.get("strategy_daily_loss_pct", 0.01)),
        "max_total_drawdown": capital * float(limits.get("max_drawdown_pct", 0.15)),
        "per_symbol_notional_cap": capital * float(limits.get("per_symbol_notional_pct", 0.1)),
        "paper_kill_switch_threshold": capital * float(limits.get("kill_switch_pct", 0.05)),
        "pause_threshold": capital * float(limits.get("pause_pct", 0.03)),
        "review_threshold": capital * float(limits.get("review_pct", 0.02)),
        "real_money_ready": False,
    }
    return result


def write_loss_limits(config_path: Path) -> dict[str, Any]:
    cfg = load_yaml(config_path)
    out = output_dir(cfg)
    res = calculate_loss_limits(cfg)
    (out / "loss_limits.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res
