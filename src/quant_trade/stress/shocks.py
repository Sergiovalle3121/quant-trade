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
    """Apply a persistent price shock from each symbol's second bar onward.

    The shock must start after the first bar and persist so that it shows up
    once in the return series with its true sign: shocking only the first bar
    made every subsequent return rebound, reporting crashes as gains.
    """
    shocked = data.copy()
    if shocked.empty:
        return shocked
    for symbol, pct in scenario.shocks.items():
        symbol_index = shocked.index[_symbol_mask(shocked, symbol)]
        if len(symbol_index) < 2:
            continue
        shock_rows = symbol_index[1:]
        for column in PRICE_COLUMNS:
            if column in shocked.columns:
                shocked.loc[shock_rows, column] = shocked.loc[shock_rows, column].astype(
                    float
                ) * (1.0 + pct)
    return shocked


def apply_correlation_spike(data: pd.DataFrame, scenario: StressScenario) -> pd.DataFrame:
    """Move every affected symbol the same way, persistently, from bar two on."""
    shocked = data.copy()
    if shocked.empty or "close" not in shocked.columns:
        return shocked
    direction = -1.0 if scenario.correlation_direction < 0 else 1.0
    for symbol in scenario.shocks or {"ALL": direction * 0.05}:
        magnitude = 1.0 + abs(scenario.shocks.get(symbol, 0.05)) * direction
        if symbol == "ALL" and "symbol" in shocked.columns:
            for group_index in shocked.groupby("symbol").groups.values():
                if len(group_index) >= 2:
                    shocked.loc[group_index[1:], "close"] *= magnitude
            continue
        symbol_index = shocked.index[
            _symbol_mask(shocked, symbol)
            if symbol != "ALL"
            else pd.Series(True, index=shocked.index)
        ]
        if len(symbol_index) < 2:
            continue
        shocked.loc[symbol_index[1:], "close"] *= magnitude
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
