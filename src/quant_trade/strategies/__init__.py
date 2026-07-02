from collections.abc import Callable
import pandas as pd
from quant_trade.strategies import buy_and_hold, mean_reversion, sma_crossover

StrategyFn = Callable[..., pd.Series]
STRATEGIES: dict[str, StrategyFn] = {
    "sma_crossover": sma_crossover.generate_signals,
    "mean_reversion": mean_reversion.generate_signals,
    "buy_and_hold": buy_and_hold.generate_signals,
}


def get_strategy(name: str) -> StrategyFn:
    try:
        return STRATEGIES[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown strategy '{name}'. Available: {', '.join(sorted(STRATEGIES))}"
        ) from exc
