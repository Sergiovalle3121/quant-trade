from __future__ import annotations

from quant_trade.research.signals import FunctionSignalModel
from quant_trade.research.signals.allocation import (
    equal_weight_quarterly,
    inverse_volatility,
    vol_targeted_equal_weight,
)
from quant_trade.research.signals.breakout import donchian_breakout
from quant_trade.research.signals.carry import funding_carry
from quant_trade.research.signals.crypto_lowcap import (
    annual_equal_weight_rebalance,
    capacity_illiquidity,
    death_avoidance,
    survival_duration,
)
from quant_trade.research.signals.ensemble import ensemble_signal
from quant_trade.research.signals.mean_reversion import simple_mean_reversion_etf
from quant_trade.research.signals.momentum import cross_sectional_momentum, time_series_momentum
from quant_trade.research.signals.trend import (
    equal_weight_buy_and_hold,
    moving_average_trend_filter,
)
from quant_trade.research.signals.tsmom import multi_horizon_tsmom
from quant_trade.research.signals.volatility import volatility_scaled_momentum

REGISTRY = {
    "multi_horizon_tsmom": FunctionSignalModel("multi_horizon_tsmom", multi_horizon_tsmom),
    "ensemble": FunctionSignalModel("ensemble", ensemble_signal),
    "donchian_breakout": FunctionSignalModel("donchian_breakout", donchian_breakout),
    "funding_carry": FunctionSignalModel("funding_carry", funding_carry),
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
    "inverse_volatility": FunctionSignalModel("inverse_volatility", inverse_volatility),
    "vol_targeted_equal_weight": FunctionSignalModel(
        "vol_targeted_equal_weight", vol_targeted_equal_weight
    ),
    "equal_weight_quarterly": FunctionSignalModel("equal_weight_quarterly", equal_weight_quarterly),
    # The four sealed low/mid-cap crypto hypotheses. Each needs the extra
    # point-in-time columns of the crypto panel (market cap, rank, venue
    # turnover) and will raise on a plain OHLCV panel that lacks them.
    "crypto_capacity_illiquidity": FunctionSignalModel(
        "crypto_capacity_illiquidity", capacity_illiquidity
    ),
    "crypto_death_avoidance": FunctionSignalModel("crypto_death_avoidance", death_avoidance),
    "crypto_annual_equal_weight_rebalance": FunctionSignalModel(
        "crypto_annual_equal_weight_rebalance", annual_equal_weight_rebalance
    ),
    "crypto_survival_duration": FunctionSignalModel("crypto_survival_duration", survival_duration),
}


def list_research_signal_models() -> list[str]:
    return sorted(REGISTRY)


def get_research_signal_model(name: str, *, allow_sealed_crypto: bool = False):
    if name.startswith("crypto_") and not allow_sealed_crypto:
        raise ValueError("crypto research models can only be resolved by the sealed crypto runner")
    try:
        return REGISTRY[name]
    except KeyError as e:
        raise ValueError(
            "Unknown research strategy "
            f"'{name}'. Available: {', '.join(list_research_signal_models())}"
        ) from e
