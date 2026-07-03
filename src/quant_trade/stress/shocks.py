"""Deterministic scenario shock transformations."""

from __future__ import annotations

import pandas as pd

from quant_trade.stress.models import StressScenario

PRICE_COLUMNS = ("open", "high", "low", "close")


def _symbol_mask(data: pd.DataFrame, symbol: str) -> pd.Series:
    if "symbol" not in data.columns:
        return pd.Series(True, index=data.index)
    return data["symbol"].astype(str) == symbol


def apply_price_shock(data: pd.DataFrame, scenario: StressScenario) -> pd.DataFrame:
    shocked = data.copy()
    if shocked.empty:
        return shocked
    for symbol, pct in scenario.shocks.items():
        mask = _symbol_mask(shocked, symbol)
        if not bool(mask.any()):
            continue
        first_index = shocked.index[mask][0]
        row_mask = mask & (shocked.index == first_index)
        for column in PRICE_COLUMNS:
            if column in shocked.columns:
                shocked.loc[row_mask, column] = shocked.loc[row_mask, column].astype(float) * (
                    1.0 + pct
                )
    return shocked


def apply_correlation_spike(data: pd.DataFrame, scenario: StressScenario) -> pd.DataFrame:
    shocked = data.copy()
    if shocked.empty or "close" not in shocked.columns:
        return shocked
    direction = -1.0 if scenario.correlation_direction < 0 else 1.0
    for symbol in scenario.shocks or {"ALL": direction * 0.05}:
        mask = (
            _symbol_mask(shocked, symbol)
            if symbol != "ALL"
            else pd.Series(True, index=shocked.index)
        )
        if bool(mask.any()):
            first_index = shocked.index[mask][0]
            shocked.loc[mask & (shocked.index == first_index), "close"] *= (
                1.0 + abs(scenario.shocks.get(symbol, 0.05)) * direction
            )
    return shocked


def apply_volatility_spike(data: pd.DataFrame, scenario: StressScenario) -> pd.DataFrame:
    shocked = data.copy()
    if shocked.empty or "close" not in shocked.columns:
        return shocked
    multiplier = max(scenario.volatility_multiplier, 1.0)
    group_key = (
        shocked["symbol"] if "symbol" in shocked.columns else pd.Series("ALL", index=shocked.index)
    )
    means = shocked.groupby(group_key)["close"].transform("mean")
    shocked["close"] = means + (shocked["close"] - means) * multiplier
    return shocked


def apply_scenario_shock(data: pd.DataFrame, scenario: StressScenario) -> pd.DataFrame:
    if scenario.scenario_type in {"price_shock", "gap_risk", "benchmark_crash", "rate_shock_proxy"}:
        return apply_price_shock(data, scenario)
    if scenario.scenario_type == "correlation_spike":
        return apply_correlation_spike(data, scenario)
    if scenario.scenario_type == "volatility_spike":
        return apply_volatility_spike(data, scenario)
    return data.copy()
