from dataclasses import asdict
from quant_trade.backtest import CostModel, load_ohlcv, run_backtest
from quant_trade.research.experiment_config import ExperimentConfig
from quant_trade.research.splits import chronological_train_test_split, date_based_split
from quant_trade.reporting.artifacts import (
    create_run_dir,
    write_csv,
    write_json,
    write_summary,
    write_yaml,
)
from quant_trade.strategies import get_strategy


def _cost(c):
    return CostModel(**asdict(c))


def _split(data, cfg):
    s = cfg.split
    if s.method == "date":
        return date_based_split(data, s.train_start, s.train_end, s.test_start, s.test_end)
    return chronological_train_test_split(data, s.train_fraction)


def _run(data, cfg, params):
    signals = get_strategy(cfg.strategy)(data, **params)
    return run_backtest(data, signals, cfg.initial_cash, _cost(cfg.costs))


def run_experiment(cfg: ExperimentConfig):
    data = load_ohlcv(cfg.data_path)
    train, test = _split(data, cfg)
    train_res = _run(train, cfg, cfg.strategy_params)
    test_res = _run(test, cfg, cfg.strategy_params)
    bench_train = run_backtest(
        train, get_strategy("buy_and_hold")(train), cfg.initial_cash, _cost(cfg.costs)
    )
    bench_test = run_backtest(
        test, get_strategy("buy_and_hold")(test), cfg.initial_cash, _cost(cfg.costs)
    )
    for m, b in [(train_res.metrics, bench_train.metrics), (test_res.metrics, bench_test.metrics)]:
        m["benchmark_total_return"] = b["total_return"]
        m["benchmark_max_drawdown"] = b["max_drawdown"]
        m["benchmark_sharpe"] = b["sharpe"]
        m["alpha_approximation"] = m["total_return"] - b["total_return"]
    out = create_run_dir(cfg.output_dir, cfg.experiment_name)
    write_yaml(out / "config_used.yaml", asdict(cfg))
    write_json(out / "metrics_train.json", train_res.metrics)
    write_json(out / "metrics_test.json", test_res.metrics)
    write_csv(out / "trades.csv", test_res.trades)
    write_csv(out / "equity_curve.csv", test_res.equity_curve)
    write_summary(
        out / "summary.md",
        cfg.experiment_name,
        [
            "In-sample and out-of-sample metrics are stored separately.",
            f"Train total_return: {train_res.metrics['total_return']}",
            f"Test total_return: {test_res.metrics['total_return']}",
        ],
    )
    return {"output_dir": out, "train_metrics": train_res.metrics, "test_metrics": test_res.metrics}
