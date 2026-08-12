"""Evaluate an annual-rebalance crypto strategy under the measured cost model.

The multi-asset engine applies one flat cost model to every asset. That is the
wrong instrument here: the measured model prices by market-cap tier and order
size, and it *refuses* sizes the visible book cannot fill. Since these
strategies trade on roughly nine dates in nine years, applying the measured
cost exactly at each rebalance is both simpler and more faithful than
approximating it inside the engine.

Between rebalances the portfolio is held and weights drift with prices, which
is what "annual rebalancing" means and is also where the H3 rebalancing premium
would come from if it exists.

## Delisting is the decision that matters

A coin's series ends. Sometimes the token is still withdrawable and worth
something; sometimes it is worth nothing. The panel cannot tell which, and this
is the single most consequential assumption in the study, so it is a declared
parameter rather than a default buried in code:

``delisting_recovery = 1.0`` exits at the last observed close, paying the
measured exit cost. Defensible because a real price existed on that bar.

``delisting_recovery = 0.0`` writes the position to zero. The stress case.

Neither is "the truth", so both are reported for every result. A verdict quoted
under only one of them is quoting a choice, not a measurement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from quant_trade.costs.crypto_lowcap import DEFAULT_TIER_PROFILES, TierCostProfile
from quant_trade.costs.rebalance import QUANTILE_P75, rebalance_cost

#: What a position is worth when its series ends. ASSUMPTION, declared, and
#: reported at both extremes for every result.
DEFAULT_DELISTING_RECOVERY = 1.0


@dataclass
class RebalanceRecord:
    timestamp: str
    portfolio_value_usd: float
    turnover: float
    cost_usd: float
    names_targeted: int
    names_held: int
    refused_legs: int
    capped_legs: int
    unpriceable_legs: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationResult:
    equity: Any  # pd.Series indexed by timestamp
    rebalances: list[RebalanceRecord] = field(default_factory=list)
    total_turnover: float = 0.0
    total_cost_usd: float = 0.0
    delisting_losses_usd: float = 0.0
    delisted_positions: int = 0
    delisting_recovery: float = DEFAULT_DELISTING_RECOVERY
    initial_capital_usd: float = 0.0

    @property
    def annual_turnover(self) -> float:
        if self.equity is None or len(self.equity) < 2:
            return 0.0
        years = (self.equity.index[-1] - self.equity.index[0]).days / 365.25
        return self.total_turnover / years if years > 0 else 0.0

    def summary(self) -> dict[str, Any]:
        equity = self.equity
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) else 0.0
        years = (
            (equity.index[-1] - equity.index[0]).days / 365.25 if len(equity) > 1 else 0.0
        )
        return {
            "initial_capital_usd": self.initial_capital_usd,
            "final_value_usd": float(equity.iloc[-1]) if len(equity) else 0.0,
            "total_return": total_return,
            "cagr": (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0,
            "years": years,
            "total_turnover": self.total_turnover,
            "annual_turnover": self.annual_turnover,
            "total_cost_usd": self.total_cost_usd,
            "cost_drag_bps_per_year": (
                self.total_cost_usd / self.initial_capital_usd * 10_000 / years
                if years > 0 and self.initial_capital_usd > 0
                else 0.0
            ),
            "rebalances": len(self.rebalances),
            "delisted_positions": self.delisted_positions,
            "delisting_losses_usd": self.delisting_losses_usd,
            "delisting_recovery": self.delisting_recovery,
            "refused_legs": sum(r.refused_legs for r in self.rebalances),
            "capped_legs": sum(r.capped_legs for r in self.rebalances),
            "unpriceable_legs": sum(r.unpriceable_legs for r in self.rebalances),
        }


def evaluate(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    *,
    initial_capital_usd: float = 1_000.0,
    delisting_recovery: float = DEFAULT_DELISTING_RECOVERY,
    quantile: str = QUANTILE_P75,
    profiles: tuple[TierCostProfile, ...] = DEFAULT_TIER_PROFILES,
    min_executable_fraction: float = 1.0,
) -> EvaluationResult:
    """Run long-format ``weights`` over ``panel`` under the measured cost model.

    ``weights`` carries one row per (timestamp, symbol, target_weight) on
    rebalance dates only, as produced by the registered signals.
    """
    if not 0.0 <= delisting_recovery <= 1.0:
        raise ValueError("delisting_recovery must be in [0, 1]")
    if initial_capital_usd <= 0:
        raise ValueError("initial_capital_usd must be positive")

    close = panel.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    caps = panel.pivot(index="timestamp", columns="symbol", values="market_cap_usd")
    caps = caps.sort_index()
    dates = close.index
    targets = {
        ts: dict(zip(group["symbol"], group["target_weight"], strict=True))
        for ts, group in weights.groupby("timestamp")
    }

    cash = initial_capital_usd
    units: dict[str, float] = {}  # symbol -> units held
    result = EvaluationResult(
        equity=None,
        delisting_recovery=delisting_recovery,
        initial_capital_usd=initial_capital_usd,
    )
    equity_points: list[float] = []
    last_price: dict[str, float] = {}

    for day in dates:
        prices = close.loc[day]
        # --- resolve positions whose series ended -------------------------
        for symbol in list(units):
            price = prices.get(symbol)
            if pd.isna(price):
                recovered = last_price.get(symbol, 0.0) * units[symbol] * delisting_recovery
                lost = last_price.get(symbol, 0.0) * units[symbol] - recovered
                cash += recovered
                result.delisting_losses_usd += lost
                result.delisted_positions += 1
                del units[symbol]
        for symbol, price in prices.items():
            if not pd.isna(price):
                last_price[symbol] = float(price)

        held_value = sum(units[s] * float(prices[s]) for s in units)
        value = cash + held_value

        # --- rebalance ----------------------------------------------------
        target = targets.get(day)
        if target is not None and value > 0:
            before = {s: units[s] * float(prices[s]) / value for s in units}
            wanted = {
                s: w
                for s, w in target.items()
                if w > 0 and s in prices.index and not pd.isna(prices[s])
            }
            day_caps = caps.loc[day]
            market_caps = {
                s: float(day_caps.get(s, 0.0) or 0.0)
                for s in set(before) | set(wanted)
            }
            cost = rebalance_cost(
                before,
                wanted,
                market_caps,
                portfolio_value_usd=value,
                quantile=quantile,
                profiles=profiles,
                min_executable_fraction=min_executable_fraction,
            )
            achieved = cost.achieved_weights
            value -= cost.cost_usd
            units = {
                s: (w * value) / float(prices[s])
                for s, w in achieved.items()
                if w > 0 and not pd.isna(prices.get(s))
            }
            cash = value - sum(units[s] * float(prices[s]) for s in units)
            result.total_turnover += cost.turnover
            result.total_cost_usd += cost.cost_usd
            result.rebalances.append(
                RebalanceRecord(
                    timestamp=str(day),
                    portfolio_value_usd=value,
                    turnover=cost.turnover,
                    cost_usd=cost.cost_usd,
                    names_targeted=len(wanted),
                    names_held=len(units),
                    refused_legs=cost.refused_legs,
                    capped_legs=cost.capped_legs,
                    unpriceable_legs=cost.unpriceable_legs,
                )
            )
        equity_points.append(value)

    result.equity = pd.Series(equity_points, index=dates, name="equity")
    return result


def equal_weight_benchmark(
    panel: pd.DataFrame, *, rebalance_frequency: str = "annual", top_n: int = 20
) -> pd.DataFrame:
    """Buy-and-hold equal weight of the point-in-time universe.

    The benchmark every result is measured against. It is built from the same
    panel with the same membership rule, so beating it means beating the
    universe rather than beating a different universe.
    """
    from quant_trade.research.signals.crypto_lowcap import annual_equal_weight_rebalance

    return annual_equal_weight_rebalance(
        panel, {"top_n": top_n, "rebalance_frequency": rebalance_frequency}
    )


__all__ = [
    "DEFAULT_DELISTING_RECOVERY",
    "EvaluationResult",
    "RebalanceRecord",
    "equal_weight_benchmark",
    "evaluate",
]
