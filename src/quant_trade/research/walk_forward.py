import json
import pandas as pd
from quant_trade.backtest import CostModel, load_ohlcv, run_backtest, calculate_metrics
from quant_trade.research.grid_search import expand_parameter_grid, valid_params
from quant_trade.research.splits import walk_forward_splits
from quant_trade.reporting.artifacts import create_run_dir, write_csv, write_json, write_summary
from quant_trade.strategies import get_strategy


def run_walk_forward(cfg):
    data = load_ohlcv(cfg.data_path)
    s = cfg.split
    splits = walk_forward_splits(data, s.train_size or 10, s.test_size or 5, s.step_size or 5)
    strat = get_strategy(cfg.strategy)
    cost = CostModel(**cfg.costs.__dict__)
    rows = []
    curves = []
    for n, (train, test) in enumerate(splits, 1):
        scored = []
        for params in expand_parameter_grid(cfg.parameter_grid):
            if not valid_params(cfg.strategy, params):
                continue
            r = run_backtest(train, strat(train, **params), cfg.initial_cash, cost)
            scored.append((r.metrics.get(cfg.ranking_metric) or -1e99, params, r))
        if not scored:
            continue
        best_metric, best_params, best_train = max(scored, key=lambda x: x[0])
        test_res = run_backtest(test, strat(test, **best_params), cfg.initial_cash, cost)
        rows.append(
            {
                "window": n,
                "train_start": train.date.min(),
                "train_end": train.date.max(),
                "test_start": test.date.min(),
                "test_end": test.date.max(),
                "selected_params": json.dumps(best_params, sort_keys=True),
                "train_metric": best_metric,
                "test_metric": test_res.metrics.get(cfg.ranking_metric),
                "test_total_return": test_res.metrics["total_return"],
            }
        )
        curves.append(test_res.equity_curve)
    df = pd.DataFrame(rows)
    combined = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    agg = (
        calculate_metrics(combined, pd.DataFrame(), cfg.initial_cash) if not combined.empty else {}
    )
    out = create_run_dir(cfg.output_dir, cfg.experiment_name)
    write_csv(out / "walk_forward_windows.csv", df)
    write_json(out / "aggregate_metrics.json", agg)
    write_summary(
        out / "summary.md",
        cfg.experiment_name,
        [
            "Each window selects parameters on train, then evaluates only the following OOS test window."
        ],
    )
    return {"output_dir": out, "windows": df, "aggregate_metrics": agg}
