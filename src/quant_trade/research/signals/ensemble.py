"""Ensemble of registered signal models.

Combining genuinely different return sources (trend, breakout, carry) is the
cheapest known Sharpe improvement — IF the components are actually different.
`signal_correlation_report` measures that: components whose backtest P&L
correlates above ~0.9 are one factor wearing two names, and averaging them
buys nothing.

Between a component's rebalance dates its last emitted target is its standing
target (exactly how the engine holds positions), so components with different
calendars combine without look-ahead.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import validate_panel_schema
from quant_trade.research.signals.base import weights_to_long


def _component_wide(data: pd.DataFrame, name: str, params: dict[str, Any]) -> pd.DataFrame:
    from quant_trade.research.strategy_registry import get_research_signal_model

    long_form = get_research_signal_model(name).generate(data, params)
    if long_form.empty:
        return pd.DataFrame()
    return long_form.pivot(index="timestamp", columns="symbol", values="target_weight")


def ensemble_signal(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    components = params.get("components")
    if not components:
        raise ValueError(
            "ensemble requires components: [{name, params, weight}, ...] "
            "with at least two entries"
        )
    if len(components) < 2:
        raise ValueError("an ensemble of one component is just that component")
    allow_short = bool(params.get("allow_short", False))
    max_gross = float(params.get("max_gross_exposure", 1.0))
    f = validate_panel_schema(data)
    timestamps = pd.DatetimeIndex(sorted(f["timestamp"].unique()))
    symbols = sorted(f["symbol"].unique())
    total_weight = sum(float(c.get("weight", 1.0)) for c in components)
    if total_weight <= 0:
        raise ValueError("component weights must sum to a positive number")
    combined = pd.DataFrame(0.0, index=timestamps, columns=symbols)
    for component in components:
        weight = float(component.get("weight", 1.0)) / total_weight
        wide = _component_wide(f, str(component["name"]), dict(component.get("params", {})))
        if wide.empty:
            continue
        # A component's last emitted target stands until its next rebalance.
        aligned = wide.reindex(index=timestamps, columns=symbols).ffill().fillna(0.0)
        combined = combined.add(aligned * weight, fill_value=0.0)
    if not allow_short:
        combined = combined.clip(lower=0.0)
    gross = combined.abs().sum(axis=1)
    over = gross > max_gross
    if over.any():
        combined.loc[over] = combined.loc[over].mul(max_gross / gross[over], axis=0)
    return weights_to_long(combined, allow_short=allow_short)


def signal_correlation_report(
    data: pd.DataFrame,
    components: list[dict[str, Any]],
    initial_cash: float = 100_000.0,
) -> pd.DataFrame:
    """Pairwise correlation of component backtest daily returns.

    High correlation (> ~0.9) means the components are the same factor and
    the ensemble adds turnover, not diversification.
    """
    from quant_trade.backtest.costs import CONSERVATIVE_COST_MODEL
    from quant_trade.backtest.multi_asset import run_multi_asset_backtest

    returns = {}
    for i, component in enumerate(components):
        name = str(component["name"])
        label = str(component.get("label") or f"{name}[{i}]")
        weights = _component_wide(data, name, dict(component.get("params", {})))
        if weights.empty:
            continue
        long_form = weights_to_long(weights, allow_short=True)
        result = run_multi_asset_backtest(
            data, long_form, initial_cash, CONSERVATIVE_COST_MODEL, allow_short=True
        )
        eq = result.equity_curve.set_index("timestamp")["equity"].astype(float)
        returns[label] = eq.pct_change()
    frame = pd.DataFrame(returns).dropna(how="all")
    return frame.corr()
