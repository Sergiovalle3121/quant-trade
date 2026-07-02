from quant_trade.data.panel import load_canonical_dataset
from quant_trade.research.strategy_registry import (
    get_research_signal_model,
    list_research_signal_models,
)

DATA = "examples/data/sample_multi_asset_ohlcv.csv"


def test_all_signals_generate_weights():
    data = load_canonical_dataset(DATA)
    for name in list_research_signal_models():
        w = get_research_signal_model(name).generate(
            data,
            {
                "lookback_days": 20,
                "sma_window": 20,
                "volatility_window": 10,
                "trend_window": 20,
                "max_weight_per_asset": 0.5,
                "rebalance_frequency": "monthly",
                "top_n": 2,
            },
        )
        assert set(w.columns) == {"timestamp", "symbol", "target_weight"}
        assert (w["target_weight"] <= 0.5 + 1e-12).all() if not w.empty else True
