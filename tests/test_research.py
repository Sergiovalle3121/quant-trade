import pandas as pd
import pytest

from quant_trade.backtest import CostModel, calculate_metrics, load_ohlcv, run_backtest
from quant_trade.research.experiment_config import load_experiment_config
from quant_trade.research.grid_search import expand_parameter_grid, run_grid_search, valid_params
from quant_trade.research.runner import run_experiment
from quant_trade.research.splits import (
    chronological_train_test_split,
    date_based_split,
    walk_forward_splits,
)
from quant_trade.research.walk_forward import run_walk_forward
from quant_trade.strategies import get_strategy

DATA = "examples/data/sample_ohlcv.csv"


def test_config_loads_and_validates():
    cfg = load_experiment_config("configs/sma_crossover_sample.yaml")
    assert cfg.strategy == "sma_crossover"
    assert cfg.initial_cash > 0


def test_bad_config(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "experiment_name: x\n"
        "strategy: sma_crossover\n"
        "strategy_params: {}\n"
        "data_path: x\n"
        "initial_cash: -1\n"
    )
    with pytest.raises(ValueError, match="initial_cash"):
        load_experiment_config(p)


def test_splits_no_leakage():
    data = load_ohlcv(DATA)
    train, test = chronological_train_test_split(data, 0.7)
    assert train.timestamp.max() < test.timestamp.min()
    dtrain, dtest = date_based_split(data, "2024-01-01", "2024-01-10", "2024-01-11", "2024-01-20")
    assert dtrain.timestamp.max() < dtest.timestamp.min()
    for tr, te in walk_forward_splits(data, 10, 5, 5):
        assert tr.timestamp.max() < te.timestamp.min()


def test_grid_expansion_invalid_and_ranking(tmp_path):
    combos = list(expand_parameter_grid({"fast_window": [5, 10], "slow_window": [8]}))
    assert len(combos) == 2 and not valid_params("sma_crossover", combos[1])
    cfg = load_experiment_config("configs/sma_grid_search_sample.yaml")
    cfg.output_dir = str(tmp_path)
    res = run_grid_search(cfg)
    assert (res["output_dir"] / "grid_results.csv").exists()
    assert res["results"].iloc[0]["params"]


def test_artifact_and_runner(tmp_path):
    cfg = load_experiment_config("configs/sma_crossover_sample.yaml")
    cfg.output_dir = str(tmp_path)
    res = run_experiment(cfg)
    out = res["output_dir"]
    assert (out / "metrics_train.json").exists() and (out / "metrics_test.json").exists()
    assert "benchmark_total_return" in res["test_metrics"]


def test_cost_model_and_buy_hold():
    assert CostModel().trade_cost(1000) == 0
    assert CostModel(percentage_commission=0.01).trade_cost(1000) == 10
    assert CostModel(fixed_commission=2).trade_cost(1000) == 2
    assert CostModel(slippage_bps=10).trade_cost(1000) == 1
    data = load_ohlcv(DATA)
    strategy = get_strategy("buy_and_hold")
    sig = strategy.generate_signals(data)
    assert sig["signal"].sum() == 1
    res = run_backtest(data, strategy, 10000)
    assert res.metrics["trade_count"] == 0


def test_metrics_empty_edges():
    m = calculate_metrics(pd.DataFrame(), [])
    assert m["sharpe"] == 0.0 and m["trade_count"] == 0


def test_walk_forward(tmp_path):
    cfg = load_experiment_config("configs/sma_walk_forward_sample.yaml")
    cfg.output_dir = str(tmp_path)
    res = run_walk_forward(cfg)
    assert (res["output_dir"] / "walk_forward_windows.csv").exists()
    assert not res["windows"].empty


def test_legacy_signal_dataframe_backtest_compatibility():
    data = load_ohlcv(DATA)
    signals = get_strategy("buy_and_hold")(data)
    result = run_backtest(data, signals, 10000)
    assert result.metrics["trade_count"] == 0
