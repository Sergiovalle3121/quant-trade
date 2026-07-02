from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.strategies import get_strategy, get_strategy_class
from quant_trade.strategies.buy_and_hold import BuyAndHoldStrategy
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


def test_buy_and_hold_signal_generation() -> None:
    data = load_ohlcv_csv("examples/data/sample_ohlcv.csv")
    signals = BuyAndHoldStrategy().generate_signals(data)
    assert list(signals.columns) == ["timestamp", "signal"]
    assert signals["signal"].sum() == 1
    assert signals["signal"].iloc[0] == 1


def test_strategy_registry() -> None:
    assert get_strategy("buy_and_hold").name == "buy_and_hold"
    assert get_strategy_class("sma_crossover") is SmaCrossoverStrategy
