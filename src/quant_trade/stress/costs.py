"""Cost stress helpers."""

from __future__ import annotations

from typing import Any

from quant_trade.stress.models import StressScenario


def apply_cost_shock(cost_model: dict[str, float], scenario: StressScenario) -> dict[str, float]:
    multiplier = max(scenario.liquidity_cost_multiplier, 1.0)
    shocked = dict(cost_model)
    for key in ("commission", "spread_bps", "slippage_bps", "transaction_cost_bps"):
        if key in shocked:
            shocked[key] = float(shocked[key]) * multiplier
    shocked["slippage_bps"] = float(shocked.get("slippage_bps", 0.0)) + scenario.slippage_bps_add
    return shocked


def estimate_liquidity_cost(notional: float, cost_model: dict[str, Any]) -> float:
    bps = float(cost_model.get("spread_bps", 0.0)) + float(cost_model.get("slippage_bps", 0.0))
    return abs(notional) * bps / 10_000.0 + float(cost_model.get("commission", 0.0))
