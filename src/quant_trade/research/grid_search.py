"""Grid-search research workflow."""

from __future__ import annotations

import json
import time
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.backtest import CostModel, load_ohlcv, run_backtest
from quant_trade.data.manifest import file_sha256
from quant_trade.metrics.statistics import return_moments
from quant_trade.reporting.artifacts import create_run_dir, write_csv, write_json, write_summary
from quant_trade.research.ledger import append_trial_record, build_trial_record, sha256_hex
from quant_trade.research.runner import _split
from quant_trade.strategies import get_strategy


def expand_parameter_grid(grid: dict[str, list[Any]]):
    keys = list(grid)
    for vals in product(*[grid[k] for k in keys]):
        yield dict(zip(keys, vals, strict=True))


def valid_params(strategy: str, params: dict[str, Any]) -> bool:
    return not (
        strategy == "sma_crossover"
        and params.get("fast_window", 0) >= params.get("slow_window", 10**9)
    )


def run_grid_search(cfg):
    data = load_ohlcv(cfg.data_path)
    train, test = _split(data, cfg)
    rows = []
    skipped = []
    cost = CostModel(**cfg.costs.__dict__)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    dataset_sha = file_sha256(Path(cfg.data_path))
    config_sha = sha256_hex({"strategy": cfg.strategy, "grid": cfg.parameter_grid,
                             "initial_cash": cfg.initial_cash})
    split_policy = f"chronological:train_fraction={getattr(cfg, 'train_fraction', 'na')}"

    def _record(params: dict[str, Any], status: str, te=None, error: str | None = None) -> None:
        sharpe_pp: float | None = None
        if te is not None:
            sharpe_pp = return_moments(
                te.equity_curve["equity"].astype(float).pct_change()
            )["sharpe_per_period"]
        append_trial_record(
            cfg.output_dir,
            build_trial_record(
                source="grid_search",
                strategy=cfg.strategy,
                strategy_params=params,
                run_id=run_id,
                status=status,
                dataset_sha=dataset_sha,
                config_sha=config_sha,
                split_policy=split_policy,
                feature_version="v1",
                costs=dict(cfg.costs.__dict__),
                test_sharpe_per_period=sharpe_pp,
                test_sharpe=float(te.metrics.get("sharpe", 0.0)) if te is not None else None,
                test_total_return=(
                    float(te.metrics.get("total_return", 0.0)) if te is not None else None
                ),
                trade_count=int(te.metrics.get("trade_count", 0)) if te is not None else None,
                error=error,
            ),
        )

    for params in expand_parameter_grid(cfg.parameter_grid):
        if not valid_params(cfg.strategy, params):
            skipped.append(params)
            # Discarded candidates are still part of the search breadth.
            _record(params, "discarded", error="invalid parameter combination")
            continue
        try:
            tr = run_backtest(train, get_strategy(cfg.strategy, **params), cfg.initial_cash, cost)
            te = run_backtest(test, get_strategy(cfg.strategy, **params), cfg.initial_cash, cost)
        except Exception as exc:  # noqa: BLE001 - record the failure, keep searching
            _record(params, "failed", error=str(exc))
            continue
        # Every evaluated combination is a trial; the deflated Sharpe of any
        # eventual winner must account for the full breadth of this search.
        _record(params, "evaluated", te=te)
        row = {
            "params": json.dumps(params, sort_keys=True),
            "train_total_return": tr.metrics["total_return"],
            "test_total_return": te.metrics["total_return"],
            "train_sharpe": tr.metrics["sharpe"],
            "test_sharpe": te.metrics["sharpe"],
        }
        if (tr.metrics.get("sharpe") or 0) > 1 and (te.metrics.get("sharpe") or 0) < 0:
            row["warning"] = "strong train / weak test: possible overfitting"
        rows.append(row)
    df = pd.DataFrame(rows)
    metric = "train_" + cfg.ranking_metric
    if not df.empty:
        df = df.sort_values(metric, ascending=False, na_position="last").reset_index(drop=True)
    out = create_run_dir(cfg.output_dir, cfg.experiment_name)
    write_csv(out / "grid_results.csv", df)
    best = json.loads(df.iloc[0]["params"]) if not df.empty else {}
    write_json(out / "best_params.json", {"best_params": best, "skipped": skipped})
    write_summary(
        out / "summary.md",
        cfg.experiment_name,
        [
            "Grid search is a research diagnostic, not an auto-money tool.",
            f"Skipped invalid combinations: {len(skipped)}",
        ],
    )
    return {"output_dir": out, "results": df, "best_params": best, "skipped": skipped}
