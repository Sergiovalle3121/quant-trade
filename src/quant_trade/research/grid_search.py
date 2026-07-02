from itertools import product
import json
import pandas as pd
from quant_trade.backtest import CostModel, load_ohlcv, run_backtest
from quant_trade.research.runner import _split
from quant_trade.reporting.artifacts import create_run_dir, write_csv, write_json, write_summary
from quant_trade.strategies import get_strategy


def expand_parameter_grid(grid: dict):
    keys = list(grid)
    for vals in product(*[grid[k] for k in keys]):
        yield dict(zip(keys, vals))


def valid_params(strategy: str, params: dict) -> bool:
    return not (
        strategy == "sma_crossover"
        and params.get("short_window", 0) >= params.get("long_window", 10**9)
    )


def run_grid_search(cfg):
    data = load_ohlcv(cfg.data_path)
    train, test = _split(data, cfg)
    rows = []
    skipped = []
    strat = get_strategy(cfg.strategy)
    cost = CostModel(**cfg.costs.__dict__)
    for params in expand_parameter_grid(cfg.parameter_grid):
        if not valid_params(cfg.strategy, params):
            skipped.append(params)
            continue
        tr = run_backtest(train, strat(train, **params), cfg.initial_cash, cost)
        te = run_backtest(test, strat(test, **params), cfg.initial_cash, cost)
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
