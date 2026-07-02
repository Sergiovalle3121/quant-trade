import argparse
from quant_trade.backtest import CostModel, load_ohlcv, run_backtest
from quant_trade.research.experiment_config import load_experiment_config
from quant_trade.research.grid_search import run_grid_search
from quant_trade.research.runner import run_experiment
from quant_trade.research.walk_forward import run_walk_forward
from quant_trade.reporting.console import print_metrics
from quant_trade.strategies import get_strategy


def main(argv=None):
    p = argparse.ArgumentParser(prog="quant-trade")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest")
    b.add_argument("--strategy", required=True)
    b.add_argument("--data", required=True)
    b.add_argument("--initial-cash", type=float, default=10000)
    for name in ["run-experiment", "grid-search", "walk-forward"]:
        sp = sub.add_parser(name)
        sp.add_argument("--config", required=True)
    args = p.parse_args(argv)
    if args.cmd == "backtest":
        data = load_ohlcv(args.data)
        strat = get_strategy(args.strategy)
        res = run_backtest(data, strat(data), args.initial_cash, CostModel())
        print_metrics("Backtest", res.metrics)
        return 0
    cfg = load_experiment_config(args.config)
    if args.cmd == "run-experiment":
        result = run_experiment(cfg)
        print(f"Wrote experiment artifacts to {result['output_dir']}")
    elif args.cmd == "grid-search":
        result = run_grid_search(cfg)
        print(result["results"].to_string(index=False))
        print(f"Wrote grid-search artifacts to {result['output_dir']}")
    elif args.cmd == "walk-forward":
        result = run_walk_forward(cfg)
        print(result["windows"].to_string(index=False))
        print(f"Wrote walk-forward artifacts to {result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
