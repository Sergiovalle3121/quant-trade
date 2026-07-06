import pandas as pd

from quant_trade.data.panel import attach_funding_rates, load_canonical_dataset
from quant_trade.research.strategy_registry import (
    get_research_signal_model,
    list_research_signal_models,
)

DATA = "examples/data/sample_multi_asset_ohlcv.csv"


def test_all_signals_generate_weights():
    data = load_canonical_dataset(DATA)
    # funding_carry requires per-bar funding; attach a flat synthetic rate so
    # every registered signal is exercised against the same panel
    funding = pd.DataFrame(
        {
            "timestamp": data["timestamp"],
            "symbol": data["symbol"],
            "funding_rate": 0.0001,
        }
    )
    panel = attach_funding_rates(data, funding)
    for name in list_research_signal_models():
        w = get_research_signal_model(name).generate(
            panel,
            {
                "lookback_days": 20,
                "lookbacks": [10, 20],
                "sma_window": 20,
                "volatility_window": 10,
                "trend_window": 20,
                "funding_window": 10,
                "entry_window": 20,
                "atr_window": 10,
                "max_weight_per_asset": 0.5,
                "rebalance_frequency": "monthly",
                "top_n": 2,
                "components": [
                    {"name": "time_series_momentum", "params": {"lookback_days": 20}},
                    {"name": "moving_average_trend_filter", "params": {"sma_window": 20}},
                ],
            },
        )
        assert set(w.columns) == {"timestamp", "symbol", "target_weight"}
        assert (w["target_weight"] <= 0.5 + 1e-12).all() if not w.empty else True
        assert (w["target_weight"] >= -1e-12).all() if not w.empty else True  # long-only default
