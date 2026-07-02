from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quant_trade.paper.models import PaperRiskLimits, PaperTradingConfig


def load_paper_config(path: Path) -> PaperTradingConfig:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("mode") != "simulated":
        raise ValueError("paper trading mode must be simulated")
    if "broker" in raw:
        raise ValueError("broker config is not allowed in Phase 5")
    data_path = Path(str(raw.get("data_path", "")))
    if not data_path.exists():
        raise FileNotFoundError(f"data_path does not exist: {data_path}")
    limits = PaperRiskLimits(**(raw.get("risk_limits") or {}))
    if limits.allow_short or limits.allow_leverage:
        raise ValueError("shorting and leverage are disabled in Phase 5")
    if not limits.kill_switch_enabled:
        raise ValueError("kill switch must be enabled")
    return PaperTradingConfig(
        risk_limits=limits, **{k: v for k, v in raw.items() if k != "risk_limits"}
    )


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
