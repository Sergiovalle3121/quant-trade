from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.reporting.artifacts import create_run_dir, write_csv, write_json, write_yaml
from quant_trade.reporting.research_report import generate_research_summary
from quant_trade.research.benchmarks import compare_to_benchmark, run_benchmark
from quant_trade.research.robustness import cost_sensitivity, rolling_metrics, subperiod_analysis
from quant_trade.research.strategy_registry import get_research_signal_model


def load_multi_asset_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    cfg = yaml.safe_load(p.read_text()) or {}
    cfg.setdefault("experiment_name", p.stem)
    return cfg


def _cost(cfg: dict[str, Any]) -> CostModel:
    return CostModel(**{k: float(v) for k, v in cfg.get("costs", {}).items()})


def _split(data: pd.DataFrame, frac: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(data["timestamp"].unique())
    cut = max(1, min(len(dates) - 1, int(len(dates) * frac)))
    return data[data.timestamp.isin(dates[:cut])].copy(), data[
        data.timestamp.isin(dates[cut:])
    ].copy()


def run_multi_asset_research_experiment(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("mode") != "multi_asset_research":
        raise ValueError("config mode must be multi_asset_research")
    data_path = Path(config["data_path"])
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} not found. Run quant-trade data fetch ... first.")
    data = load_canonical_dataset(data_path)
    train, test = _split(data, float(config.get("split", {}).get("train_fraction", 0.7)))
    strategy = str(config["strategy"])
    params = dict(config.get("strategy_params", {}))
    initial = float(config.get("initial_cash", 100000))
    cost = _cost(config)
    model = get_research_signal_model(strategy)
    w_train = model.generate(train, params)
    w_test = model.generate(test, params)
    port = config.get("portfolio", {})
    max_weight = float(port.get("max_weight_per_asset", params.get("max_weight_per_asset", 1.0)))
    allow_leverage = bool(port.get("allow_leverage", False))
    allow_short = bool(port.get("allow_short", False))
    r_train = run_multi_asset_backtest(
        train,
        w_train,
        initial,
        cost,
        max_weight_per_asset=max_weight,
        allow_leverage=allow_leverage,
        allow_short=allow_short,
    )
    r_test = run_multi_asset_backtest(
        test,
        w_test,
        initial,
        cost,
        max_weight_per_asset=max_weight,
        allow_leverage=allow_leverage,
        allow_short=allow_short,
    )
    bcfg = dict(config.get("benchmark", {"type": "equal_weight_universe"}))
    b_train = run_benchmark(train, bcfg, initial, cost)
    b_test = run_benchmark(test, bcfg, initial, cost)
    c_train = compare_to_benchmark(
        r_train.metrics, b_train.metrics, r_train.equity_curve, b_train.equity_curve
    )
    c_test = compare_to_benchmark(
        r_test.metrics, b_test.metrics, r_test.equity_curve, b_test.equity_curve
    )
    run_id = time.strftime("%Y%m%d_%H%M%S")
    out = create_run_dir(
        config.get("output_dir", "outputs"), f"{config['experiment_name']}_{run_id}"
    )
    write_yaml(out / "config_used.yaml", config)
    write_json(out / "metrics_train.json", r_train.metrics)
    write_json(out / "metrics_test.json", r_test.metrics)
    write_json(out / "benchmark_train.json", b_train.metrics)
    write_json(out / "benchmark_test.json", b_test.metrics)
    write_json(out / "comparison_train.json", c_train)
    write_json(out / "comparison_test.json", c_test)
    write_csv(out / "equity_curve_train.csv", r_train.equity_curve)
    write_csv(out / "equity_curve_test.csv", r_test.equity_curve)
    write_csv(out / "positions_test.csv", r_test.positions)
    write_csv(out / "trades_test.csv", r_test.trades)
    write_csv(out / "target_weights_test.csv", w_test)
    rob = config.get("robustness", {})
    files = []
    if rob.get("run_cost_sensitivity", False):
        cs = cost_sensitivity(test, strategy, params, initial)
        write_csv(out / "cost_sensitivity.csv", cs)
        files.append("cost_sensitivity.csv")
    if rob.get("run_subperiod_analysis", False):
        sp = subperiod_analysis(r_test.equity_curve)
        write_csv(out / "subperiod_analysis.csv", sp)
        files.append("subperiod_analysis.csv")
    if rob.get("run_rolling_metrics", False):
        rm = rolling_metrics(r_test.equity_curve)
        write_csv(out / "rolling_metrics.csv", rm)
        files.append("rolling_metrics.csv")
    generate_research_summary(
        out / "summary.md",
        experiment_name=config["experiment_name"],
        dataset_info={
            "symbols": sorted(data.symbol.unique()),
            "rows": len(data),
            "start": str(data.timestamp.min()),
            "end": str(data.timestamp.max()),
        },
        strategy=strategy,
        strategy_params=params,
        benchmark=bcfg,
        train_metrics=r_train.metrics,
        test_metrics=r_test.metrics,
        comparison=c_test,
        robustness_files=files,
    )
    return {
        "output_dir": str(out),
        "train_metrics": r_train.metrics,
        "test_metrics": r_test.metrics,
        "comparison_test": c_test,
        "symbols": sorted(data.symbol.unique()),
        "train_range": [str(train.timestamp.min()), str(train.timestamp.max())],
        "test_range": [str(test.timestamp.min()), str(test.timestamp.max())],
    }
