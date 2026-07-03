"""Configuration loading for the offline TCA lab."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from quant_trade.tca.models import ExecutionAssumption, TcaPolicy


def load_tca_policy(path: Path) -> TcaPolicy:
    payload: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    execution_payload = payload.get("execution", {}) or {}
    assumption = ExecutionAssumption(**execution_payload)
    policy = TcaPolicy(
        name=payload.get("name", "conservative_offline_tca"),
        real_money_ready=False,
        default_equity=float(payload.get("default_equity", 100000.0)),
        research_assumed_cost_bps=float(payload.get("research_assumed_cost_bps", 10.0)),
        execution=assumption,
    )
    return replace(policy, real_money_ready=False)
