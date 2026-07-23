from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.panel import validate_panel_schema
from quant_trade.execution.bar_model import BarExecutionPolicy
from quant_trade.metrics.performance import periods_per_year
from quant_trade.research.signals.trend import equal_weight_buy_and_hold


def run_benchmark(
    data: pd.DataFrame,
    benchmark_config: dict[str, Any],
    initial_cash: float,
    cost_model: CostModel,
    execution_policy: BarExecutionPolicy | None = None,
):
    kind = benchmark_config.get("type", "equal_weight_universe")
    f = validate_panel_schema(data)
    if kind == "cash":
        eq = pd.DataFrame(
            {
                "timestamp": sorted(f["timestamp"].unique()),
                "equity": initial_cash,
                "cash": initial_cash,
                "gross_exposure": 0.0,
                "net_exposure": 0.0,
                "turnover": 0.0,
                "number_of_positions": 0,
            }
        )
        from quant_trade.backtest.multi_asset import MultiAssetBacktestResult, _metrics

        return MultiAssetBacktestResult(eq, pd.DataFrame(), pd.DataFrame(), _metrics(eq))
    if kind == "buy_and_hold_symbol":
        sym = str(benchmark_config.get("symbol", "SPY")).upper()
        if sym not in set(f["symbol"]):
            raise ValueError(f"Benchmark symbol {sym} is not present in dataset")
        weights = pd.DataFrame(
            [
                {
                    "timestamp": f[f.symbol == sym]["timestamp"].min(),
                    "symbol": sym,
                    "target_weight": 1.0,
                }
            ]
        )
    elif kind == "equal_weight_universe":
        weights = equal_weight_buy_and_hold(f, {})
    else:
        raise ValueError(f"Unknown benchmark type: {kind}")
    return run_multi_asset_backtest(
        f,
        weights,
        initial_cash,
        cost_model,
        execution_policy=execution_policy,
    )


def compare_to_benchmark(
    strategy_metrics: dict[str, Any],
    benchmark_metrics: dict[str, Any],
    strategy_equity: pd.DataFrame | None = None,
    benchmark_equity: pd.DataFrame | None = None,
) -> dict[str, float]:
    comp = {
        "strategy_total_return": float(strategy_metrics.get("total_return", 0.0)),
        "benchmark_total_return": float(benchmark_metrics.get("total_return", 0.0)),
        "excess_return": float(
            strategy_metrics.get("total_return", 0.0) - benchmark_metrics.get("total_return", 0.0)
        ),
        "strategy_sharpe": float(strategy_metrics.get("sharpe", 0.0)),
        "benchmark_sharpe": float(benchmark_metrics.get("sharpe", 0.0)),
        "strategy_max_drawdown": float(strategy_metrics.get("max_drawdown", 0.0)),
        "benchmark_max_drawdown": float(benchmark_metrics.get("max_drawdown", 0.0)),
        "alpha_approximation": float(
            strategy_metrics.get("total_return", 0.0) - benchmark_metrics.get("total_return", 0.0)
        ),
        "tracking_error": 0.0,
        "information_ratio": 0.0,
    }
    if (
        strategy_equity is not None
        and benchmark_equity is not None
        and not strategy_equity.empty
        and not benchmark_equity.empty
    ):
        s = strategy_equity.set_index("timestamp")["equity"].pct_change()
        b = benchmark_equity.set_index("timestamp")["equity"].pct_change()
        diff = (s - b).dropna()
        ppy = periods_per_year(diff.index)
        te = float(diff.std(ddof=0) * np.sqrt(ppy)) if len(diff) > 1 else 0.0
        comp["tracking_error"] = te
        comp["information_ratio"] = float(diff.mean() * ppy / te) if te else 0.0
    return comp

