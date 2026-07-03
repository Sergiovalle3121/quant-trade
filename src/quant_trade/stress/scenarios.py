"""Scenario ranking and validation helpers."""

from __future__ import annotations

import pandas as pd

from quant_trade.stress.models import StressResult, StressScenario


def missing_required_symbols(data: pd.DataFrame, scenario: StressScenario) -> tuple[str, ...]:
    if not scenario.required_symbols:
        return ()
    available = set(data["symbol"].astype(str)) if "symbol" in data.columns else set()
    return tuple(symbol for symbol in scenario.required_symbols if symbol not in available)


def rank_scenarios_by_loss(
    results: list[StressResult] | tuple[StressResult, ...],
) -> list[StressResult]:
    return sorted(results, key=lambda item: (item.stressed_total_return, -item.breach_count))
