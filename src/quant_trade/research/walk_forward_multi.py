"""Multi-asset walk-forward validation.

The flagship anti-overfitting protocol, for the panel engine the crypto plan
actually uses: roll a train window forward, (optionally) pick parameters on
train only, evaluate strictly out-of-sample on the following test window with
an embargo between them, and aggregate OOS evidence by compounding per-window
returns. Every parameter evaluation is recorded in the trial ledger so the
deflated Sharpe of any eventual winner accounts for the full search.

Signals are generated once per parameter set on the FULL panel and sliced per
window â€” registered signals are causal (enforced by the truncation-invariance
tests), so this is leak-free and gives every test window full signal coverage
instead of burning the lookback inside it.
"""

from __future__ import annotations

import time
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.manifest import file_sha256
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.metrics.statistics import probabilistic_sharpe_ratio, return_moments
from quant_trade.reporting.artifacts import create_run_dir, write_csv, write_json, write_summary
from quant_trade.research.ledger import append_trial
from quant_trade.research.multi_asset_runner import _cost, _execution_policy
from quant_trade.research.strategy_registry import get_research_signal_model
from quant_trade.research.walk_forward import _stitch_oos_equity


def _expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, values, strict=True)) for values in product(*[grid[k] for k in keys])]


def _window_result(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    window_ts: list,
    config: dict[str, Any],
) -> Any:
    ts_set = set(window_ts)
    window_panel = panel[panel["timestamp"].isin(ts_set)]
    window_weights = weights[weights["timestamp"].isin(ts_set)]
    port = config.get("portfolio", {})
    return run_multi_asset_backtest(
        window_panel,
        window_weights,
        float(config.get("initial_cash", 100_000)),
        _cost(config),
        max_weight_per_asset=float(port.get("max_weight_per_asset", 1.0)),
        allow_leverage=bool(port.get("allow_leverage", False)),
        allow_short=bool(port.get("allow_short", False)),
        rebalance_band=float(port.get("rebalance_band", 0.0)),
        execution_policy=_execution_policy(config),
    )


def run_multi_asset_walk_forward(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("mode") != "multi_asset_walk_forward":
        raise ValueError("config mode must be multi_asset_walk_forward")
    data_path = Path(config["data_path"])
    data = load_canonical_dataset(data_path)
    dataset_binding = {
        "data_path": str(data_path),
        "data_sha256": file_sha256(data_path),
        "rows": int(len(data)),
    }
    dates = sorted(data["timestamp"].unique())
    split = config.get("split", {})
    train_size = int(split.get("train_size", 252))
    test_size = int(split.get("test_size", 63))
    step_size = int(split.get("step_size", 63))
    embargo = int(split.get("embargo_bars", 0))
    if min(train_size, test_size, step_size) <= 0 or embargo < 0:
        raise ValueError("window sizes must be positive and embargo_bars >= 0")
    strategy = str(config["strategy"])
    base_params = dict(config.get("strategy_params", {}))
    grid = config.get("parameter_grid", {}) or {}
    ranking_metric = str(config.get("ranking_metric", "sharpe"))
    model = get_research_signal_model(strategy)

    # One generation per parameter set over the full panel (causal), reused
    # across every window.
    combos = _expand_grid(grid)
    weights_by_combo = {
        i: model.generate(data, {**base_params, **combo}) for i, combo in enumerate(combos)
    }

    rows = []
    curves = []
    start = 0
    window_number = 0
    initial_cash = float(config.get("initial_cash", 100_000))
    while start + train_size + embargo + test_size <= len(dates):
        window_number += 1
        train_ts = dates[start : start + train_size]
        test_from = start + train_size + embargo
        test_ts = dates[test_from : test_from + test_size]
        scored = []
        for i, combo in enumerate(combos):
            train_res = _window_result(data, weights_by_combo[i], train_ts, config)
            metric = train_res.metrics.get(ranking_metric)
            scored.append((float(metric) if metric is not None else float("-inf"), i, combo))
        best_metric, best_index, best_combo = max(scored, key=lambda item: item[0])
        test_res = _window_result(data, weights_by_combo[best_index], test_ts, config)
        moments = return_moments(
            test_res.equity_curve["equity"].astype(float).pct_change()
        )
        append_trial(
            config.get("output_dir", "outputs"),
            {
                "source": "multi_asset_walk_forward",
                "experiment_name": config.get("experiment_name", "walk_forward_multi"),
                "strategy": strategy,
                "strategy_params": {**base_params, **best_combo},
                "window": window_number,
                "trials_in_window": len(scored),
                "data_sha256": dataset_binding["data_sha256"],
                "test_sharpe": float(test_res.metrics.get("sharpe", 0.0)),
                "test_sharpe_per_period": moments["sharpe_per_period"],
                "test_total_return": float(test_res.metrics.get("total_return", 0.0)),
                "trade_count": int(len(test_res.trades)),
            },
        )
        rows.append(
            {
                "window": window_number,
                "train_start": str(train_ts[0]),
                "train_end": str(train_ts[-1]),
                "test_start": str(test_ts[0]),
                "test_end": str(test_ts[-1]),
                "selected_params": str(best_combo),
                "train_metric": best_metric,
                "test_sharpe": test_res.metrics.get("sharpe"),
                "test_total_return": test_res.metrics.get("total_return"),
                "test_max_drawdown": test_res.metrics.get("max_drawdown"),
                "test_trades": int(len(test_res.trades)),
            }
        )
        curves.append(test_res.equity_curve)
        start += step_size
    if not rows:
        raise ValueError("insufficient data for any walk-forward window")

    frame = pd.DataFrame(rows)
    stitched = _stitch_oos_equity(curves, initial_cash)
    from quant_trade.backtest import calculate_metrics

    aggregate = calculate_metrics(stitched, []) if not stitched.empty else {}
    oos_returns = stitched["equity"].astype(float).pct_change().dropna()
    aggregate["psr"] = probabilistic_sharpe_ratio(oos_returns)
    aggregate["windows"] = len(rows)
    aggregate["positive_window_rate"] = float((frame["test_total_return"] > 0).mean())

    run_id = time.strftime("%Y%m%d_%H%M%S")
    out = create_run_dir(
        config.get("output_dir", "outputs"),
        f"{config.get('experiment_name', 'walk_forward_multi')}_{run_id}",
    )
    write_csv(out / "walk_forward_windows.csv", frame)
    write_json(out / "aggregate_metrics.json", aggregate)
    write_json(out / "dataset_binding.json", dataset_binding)
    write_csv(out / "oos_equity_curve.csv", stitched)
    write_summary(
        out / "summary.md",
        str(config.get("experiment_name", "walk_forward_multi")),
        [
            f"Windows: {len(rows)} (train {train_size} / embargo {embargo} / test {test_size})",
            f"Aggregate OOS Sharpe: {aggregate.get('sharpe')}",
            f"Aggregate OOS PSR: {aggregate.get('psr')}",
            f"Positive window rate: {aggregate.get('positive_window_rate')}",
            "Every parameter evaluation is recorded in the trial ledger.",
        ],
    )
    return {
        "output_dir": str(out),
        "windows": frame,
        "aggregate_metrics": aggregate,
        "dataset_binding": dataset_binding,
    }

