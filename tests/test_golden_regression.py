"""Golden-file backtest regression.

A refactor or dependency bump that silently shifts strategy P&L must fail CI.
The golden values were produced by the engines at a known-good state on the
committed sample datasets with explicit cost models. If a change is meant to
alter results (an engine semantics fix), regenerate the goldens in the same
commit and explain the shift in the commit message.
"""

from __future__ import annotations

import json
from pathlib import Path

from quant_trade.backtest import CostModel, load_ohlcv, run_backtest
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.research.signals.momentum import time_series_momentum
from quant_trade.strategies import get_strategy

GOLDEN_DIR = Path(__file__).parent / "golden"
RELATIVE_TOLERANCE = 1e-9


def _assert_matches_golden(metrics: dict, golden_name: str) -> None:
    golden = json.loads((GOLDEN_DIR / golden_name).read_text())
    assert set(metrics) == set(golden), (
        f"metric keys changed vs {golden_name}: "
        f"added={set(metrics) - set(golden)}, removed={set(golden) - set(metrics)}"
    )
    for key, expected in golden.items():
        actual = metrics[key]
        tolerance = max(abs(expected), 1.0) * RELATIVE_TOLERANCE
        assert abs(actual - expected) <= tolerance, (
            f"{golden_name}:{key} drifted: expected {expected!r}, got {actual!r}"
        )


def test_single_asset_sma_crossover_matches_golden():
    data = load_ohlcv("examples/data/sample_ohlcv.csv")
    result = run_backtest(
        data,
        get_strategy("sma_crossover"),
        10_000.0,
        CostModel(percentage_commission=0.0005, slippage_bps=5.0, spread_bps=2.0),
    )
    _assert_matches_golden(result.metrics, "sma_crossover_sample_metrics.json")


def test_multi_asset_ts_momentum_matches_golden():
    panel = load_canonical_dataset("examples/data/sample_multi_asset_ohlcv.csv")
    params = {"lookback_days": 63, "rebalance_frequency": "monthly", "max_weight_per_asset": 0.4}
    weights = time_series_momentum(panel, params)
    result = run_multi_asset_backtest(
        panel,
        weights,
        100_000.0,
        CostModel(percentage_commission=0.0005, slippage_bps=2.0, spread_bps=1.0),
        max_weight_per_asset=0.4,
    )
    _assert_matches_golden(result.metrics, "ts_momentum_sample_metrics.json")
