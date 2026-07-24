from __future__ import annotations

import warnings
from itertools import product
from typing import Any

import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.execution.bar_model import BarExecutionPolicy
from quant_trade.research.bootstrap import (
    bootstrap_confidence_intervals,
    moving_block_bootstrap,
)
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


def bootstrap_summary(
    returns: pd.Series,
    *,
    method: str = "stationary",
    samples: int = 1000,
    block_size: int = 20,
    seed: int = 12345,
    percentiles: tuple[float, ...] = (2.5, 50.0, 97.5),
) -> dict[str, Any]:
    """A JSON-serialisable block-bootstrap confidence interval for evidence.

    Emits the per-period total-return and Sharpe percentile bands plus the
    metadata needed to reproduce them (method, seed, samples, block size,
    observations). Insufficient data yields ``available: False`` instead of a
    misleading interval, so promotion gates can fail closed.
    """
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    meta = {
        "method": method,
        "samples": int(samples),
        "block_size": int(block_size),
        "seed": int(seed),
        "observations": int(len(clean)),
        "annualized": False,
    }
    if len(clean) < 2:
        return {**meta, "available": False, "reason": "insufficient observations"}
    ci = bootstrap_confidence_intervals(
        clean,
        method=method,  # type: ignore[arg-type]
        samples=samples,
        seed=seed,
        block_size=block_size,
        percentiles=percentiles,
        nan_policy="drop",
    )
    lo, hi = f"p{percentiles[0]:g}", f"p{percentiles[-1]:g}"
    return {
        **meta,
        "available": True,
        "total_return": {
            "point_estimate": float(ci.loc["total_return", "point_estimate"]),
            "lower": float(ci.loc["total_return", lo]),
            "upper": float(ci.loc["total_return", hi]),
        },
        "sharpe_per_period": {
            "point_estimate": float(ci.loc["sharpe", "point_estimate"]),
            "lower": float(ci.loc["sharpe", lo]),
            "upper": float(ci.loc["sharpe", hi]),
        },
        # Positive lower bound on total return = the resampled paths stay
        # profitable across the confidence level, not just at the point estimate.
        "total_return_lower_positive": bool(ci.loc["total_return", lo] > 0.0),
    }


def simple_bootstrap_or_block_bootstrap(
    returns: pd.Series, samples: int = 100, block_size: int = 20, seed: int = 0
) -> pd.DataFrame:
    """Deprecated. Use :mod:`quant_trade.research.bootstrap` instead.

    The original implementation ignored ``block_size`` and did IID sampling.
    This shim now delegates to the real moving-block bootstrap so historical
    callers get correct behaviour, but new code should call the explicit APIs.
    """
    warnings.warn(
        "simple_bootstrap_or_block_bootstrap is deprecated; use "
        "quant_trade.research.bootstrap.moving_block_bootstrap or "
        "bootstrap_confidence_intervals",
        DeprecationWarning,
        stacklevel=2,
    )
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) < 2:
        return pd.DataFrame(columns=["sample", "total_return"])
    draws = moving_block_bootstrap(
        clean, samples=samples, block_size=block_size, seed=seed, nan_policy="drop"
    )
    return draws[["sample", "total_return"]].copy()

