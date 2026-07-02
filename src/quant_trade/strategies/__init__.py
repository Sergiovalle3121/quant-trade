"""Educational baseline strategies and registry."""

from __future__ import annotations

from typing import Any

from quant_trade.strategies.base import Strategy
from quant_trade.strategies.buy_and_hold import BuyAndHoldStrategy
from quant_trade.strategies.mean_reversion import MeanReversionStrategy
from quant_trade.strategies.sma_crossover import SmaCrossoverStrategy

STRATEGY_REGISTRY = {
    "sma_crossover": SmaCrossoverStrategy,
    "mean_reversion": MeanReversionStrategy,
    "buy_and_hold": BuyAndHoldStrategy,
}


def get_strategy_class(name: str):
    """Return the strategy class for a registered strategy name."""
    try:
        return STRATEGY_REGISTRY[name]
    except KeyError as exc:
        valid = ", ".join(sorted(STRATEGY_REGISTRY))
        raise ValueError(f"unknown strategy '{name}'. Valid strategies: {valid}") from exc


def get_strategy(name: str, **params: Any) -> Strategy:
    """Build a registered strategy instance."""
    return get_strategy_class(name)(**params)


__all__ = [
    "BuyAndHoldStrategy",
    "MeanReversionStrategy",
    "SmaCrossoverStrategy",
    "Strategy",
    "get_strategy",
    "get_strategy_class",
]
