import pandas as pd

from quant_trade.ml.splits import chronological_split


def test_chronological_split_with_embargo():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=10, tz="UTC"),
            "symbol": "AAA",
        }
    )
    train, test = chronological_split(frame, 0.6, embargo_days=1)
    assert train["timestamp"].max() < test["timestamp"].min()
    assert len(train) == 6
