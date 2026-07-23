from __future__ import annotations

from itertools import product
from typing import Any

import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.execution.bar_model import BarExecutionPolicy
from quant_trade.research.strategy_registry import get_research_signal_model


def parameter_sensitivity_grid(
    data: pd.DataFrame,
    strategy_name: str,
    param_grid: dict[str, list[Any]],
    initial_cash: float,
    cost_model: CostModel,
    execution_policy: BarExecutionPolicy | None = None,
) -> pd.DataFrame:
    rows = []
    keys = list(param_grid)
    for vals in product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, vals, strict=True))
        try:
            w = get_research_signal_model(strategy_name).generate(data, params)
            res = run_multi_asset_backtest(
                data,
                w,
                initial_cash,
                cost_model,
                execution_policy=execution_policy,
            )
            rows.append({**params, **res.metrics, "error": ""})
        except Exception as exc:
            rows.append({**params, "error": str(exc)})
    return pd.DataFrame(rows)


def cost_sensitivity(
    data: pd.DataFrame,
    strategy_name: str,
    params: dict[str, Any],
    initial_cash: float,
    execution_policy: BarExecutionPolicy | None = None,
) -> pd.DataFrame:
    levels = {
        "zero": CostModel(),
        "low": CostModel(percentage_commission=0.0001, slippage_bps=1),
        "medium": CostModel(percentage_commission=0.0005, slippage_bps=2, spread_bps=1),
        "high": CostModel(percentage_commission=0.001, slippage_bps=5, spread_bps=3),
    }
    rows = []
    w = get_research_signal_model(strategy_name).generate(data, params)
    for name, cost in levels.items():
        rows.append(
            {
                "cost_level": name,
                **run_multi_asset_backtest(
                    data,
                    w,
                    initial_cash,
                    cost,
                    execution_policy=execution_policy,
                ).metrics,
            }
        )
    return pd.DataFrame(rows)


def subperiod_analysis(equity_curve: pd.DataFrame) -> pd.DataFrame:
    if equity_curve.empty:
        return pd.DataFrame(columns=["year", "return", "max_drawdown"])
    e = equity_curve.copy()
    e["year"] = pd.to_datetime(e["timestamp"], utc=True).dt.year
    rows = []
    for y, g in e.groupby("year"):
        eq = g["equity"].astype(float)
        rows.append(
            {
                "year": int(y),
                "return": float(eq.iloc[-1] / eq.iloc[0] - 1),
                "max_drawdown": float((eq / eq.cummax() - 1).min()),
            }
        )
    return pd.DataFrame(rows)


def rolling_metrics(
    equity_curve: pd.DataFrame, windows: tuple[int, ...] = (63, 126, 252)
) -> pd.DataFrame:
    if equity_curve.empty:
        return pd.DataFrame()
    e = equity_curve[["timestamp", "equity"]].copy()
    ret = e["equity"].pct_change()
    for w in windows:
        e[f"rolling_{w}_return"] = e["equity"].pct_change(w)
        e[f"rolling_{w}_volatility"] = ret.rolling(w).std() * (252**0.5)
        e[f"rolling_{w}_drawdown"] = e["equity"] / e["equity"].rolling(w).max() - 1
    return e


def simple_bootstrap_or_block_bootstrap(
    returns: pd.Series, samples: int = 100, block_size: int = 20
) -> pd.DataFrame:
    rows = []
    clean = returns.dropna().reset_index(drop=True)
    if clean.empty:
        return pd.DataFrame(columns=["sample", "total_return"])
    for i in range(samples):
        draws = clean.sample(n=len(clean), replace=True, random_state=i).to_numpy()
        rows.append({"sample": i, "total_return": float((1 + draws).prod() - 1)})
    return pd.DataFrame(rows)

