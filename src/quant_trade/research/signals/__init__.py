from quant_trade.research.signals.base import FunctionSignalModel, SignalModel
from quant_trade.research.signals.mean_reversion import simple_mean_reversion_etf
from quant_trade.research.signals.momentum import cross_sectional_momentum, time_series_momentum
from quant_trade.research.signals.trend import (
    equal_weight_buy_and_hold,
    moving_average_trend_filter,
)
from quant_trade.research.signals.volatility import volatility_scaled_momentum

__all__ = [
    "SignalModel",
    "FunctionSignalModel",
    "equal_weight_buy_and_hold",
    "moving_average_trend_filter",
    "time_series_momentum",
    "cross_sectional_momentum",
    "volatility_scaled_momentum",
    "simple_mean_reversion_etf",
]
