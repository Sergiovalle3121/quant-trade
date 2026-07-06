"""Walk-forward research workflow."""

from __future__ import annotations

import json

import pandas as pd

from quant_trade.backtest import CostModel, calculate_metrics, load_ohlcv, run_backtest
from quant_trade.reporting.artifacts import create_run_dir, write_csv, write_json, write_summary
from quant_trade.research.grid_search import expand_parameter_grid, valid_params
from quant_trade.research.splits import TIME_COLUMN, walk_forward_splits
from quant_trade.strategies import get_strategy


def _stitch_oos_equity(curves: list[pd.DataFrame], initial_cash: float) -> pd.DataFrame:
    """Compound per-window OOS returns into one continuous equity curve.

    Each window's backtest restarts at ``initial_cash``; naively concatenating
    the raw equity levels would manufacture a fake return at every window seam
    and let drawdowns span the resets. Compounding within-window returns
    instead yields aggregate metrics that describe only realized OOS returns.
    """
    pieces = []
    for curve in curves:
        if curve.empty or "equity" not in curve:
            continue
        eq = pd.to_numeric(curve["equity"], errors="coerce")
        returns = eq.pct_change()
        piece = pd.DataFrame(
            {
                "timestamp": curve.get("timestamp", pd.NaT),
                "window_return": returns,
            }
        ).iloc[1:]
        pieces.append(piece.dropna(subset=["window_return"]))
    if not pieces:
        return pd.DataFrame()
    stitched = pd.concat(pieces, ignore_index=True)
    stitched["equity"] = initial_cash * (1 + stitched["window_return"]).cumprod()
    return stitched[["timestamp", "equity"]]


def run_walk_forward(cfg):
    data = load_ohlcv(cfg.data_path)
    split = cfg.split
    splits = walk_forward_splits(
        data, split.train_size or 10, split.test_size or 5, split.step_size or 5
    )
    cost = CostModel(**cfg.costs.__dict__)
    rows = []
    curves = []
    for window_number, (train, test) in enumerate(splits, 1):
        scored = []
        for params in expand_parameter_grid(cfg.parameter_grid):
            if not valid_params(cfg.strategy, params):
                continue
            result = run_backtest(
                train, get_strategy(cfg.strategy, **params), cfg.initial_cash, cost
            )
            metric_value = result.metrics.get(cfg.ranking_metric)
            scored.append(
                (float(metric_value) if metric_value is not None else float("-inf"), params)
            )
        if not scored:
            continue
        best_metric, best_params = max(scored, key=lambda item: item[0])
        test_res = run_backtest(
            test, get_strategy(cfg.strategy, **best_params), cfg.initial_cash, cost
        )
        rows.append(
            {
                "window": window_number,
                "train_start": train[TIME_COLUMN].min(),
                "train_end": train[TIME_COLUMN].max(),
                "test_start": test[TIME_COLUMN].min(),
                "test_end": test[TIME_COLUMN].max(),
                "selected_params": json.dumps(best_params, sort_keys=True),
                "train_metric": best_metric,
                "test_metric": test_res.metrics.get(cfg.ranking_metric),
                "test_total_return": test_res.metrics["total_return"],
            }
        )
        curves.append(test_res.equity_curve)
    df = pd.DataFrame(rows)
    combined = _stitch_oos_equity(curves, cfg.initial_cash)
    aggregate_metrics = calculate_metrics(combined, []) if not combined.empty else {}
    out = create_run_dir(cfg.output_dir, cfg.experiment_name)
    write_csv(out / "walk_forward_windows.csv", df)
    write_json(out / "aggregate_metrics.json", aggregate_metrics)
    write_summary(
        out / "summary.md",
        cfg.experiment_name,
        [
            "Each window selects parameters on train, then evaluates only the following OOS "
            "test window."
        ],
    )
    return {"output_dir": out, "windows": df, "aggregate_metrics": aggregate_metrics}
