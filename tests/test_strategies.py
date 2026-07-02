from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.strategies.mean_reversion import MeanReversionStrategy
from quant_trade.strategies.sma_crossover import SmaCrossoverStrategy


def test_sma_crossover_signal_generation() -> None:
    data = load_ohlcv_csv("examples/data/sample_ohlcv.csv")
    signals = SmaCrossoverStrategy(fast_window=3, slow_window=5).generate_signals(data)
    assert "signal" in signals
    assert set(signals["signal"].unique()).issubset({-1.0, 0.0, 1.0})
    assert (signals["signal"] == 1).any()


def test_mean_reversion_signal_generation() -> None:
    data = load_ohlcv_csv("examples/data/sample_ohlcv.csv")
    signals = MeanReversionStrategy(window=5, entry_z=-1.0, exit_z=0.0).generate_signals(data)
    assert "z_score" in signals
    assert set(signals["signal"].unique()).issubset({-1, 0, 1})
    assert (signals["signal"] != 0).any()
