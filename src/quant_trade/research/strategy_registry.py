from __future__ import annotations

from quant_trade.research.signals import FunctionSignalModel
from quant_trade.research.signals.mean_reversion import simple_mean_reversion_etf
from quant_trade.research.signals.momentum import cross_sectional_momentum, time_series_momentum
from quant_trade.research.signals.trend import (
    equal_weight_buy_and_hold,
    moving_average_trend_filter,
)
from quant_trade.research.signals.volatility import volatility_scaled_momentum

REGISTRY = {
    "equal_weight_buy_and_hold": FunctionSignalModel(
        "equal_weight_buy_and_hold", equal_weight_buy_and_hold
    ),
    "time_series_momentum": FunctionSignalModel("time_series_momentum", time_series_momentum),
    "moving_average_trend_filter": FunctionSignalModel(
        "moving_average_trend_filter", moving_average_trend_filter
    ),
    "cross_sectional_momentum": FunctionSignalModel(
        "cross_sectional_momentum", cross_sectional_momentum
    ),
    "volatility_scaled_momentum": FunctionSignalModel(
        "volatility_scaled_momentum", volatility_scaled_momentum
    ),
    "simple_mean_reversion_etf": FunctionSignalModel(
        "simple_mean_reversion_etf", simple_mean_reversion_etf
    ),
}


def list_research_signal_models() -> list[str]:
    return sorted(REGISTRY)


def get_research_signal_model(name: str):
    try:
        return REGISTRY[name]
    except KeyError as e:
        raise ValueError(
            "Unknown research strategy "
            f"'{name}'. Available: {', '.join(list_research_signal_models())}"
        ) from e
