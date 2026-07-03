import pandas as pd

from quant_trade.ml.labels import generate_labels


def test_labels_are_forward_shifted():
    dates = pd.date_range("2020-01-01", periods=10, freq="B", tz="UTC")
    data = pd.DataFrame(
        {
            "timestamp": dates,
            "symbol": "AAA",
            "close": range(100, 110),
            "open": 1,
            "high": 1,
            "low": 1,
            "volume": 1,
        }
    )
    labels = generate_labels(data, horizon_days=2)
    assert labels.loc[0, "forward_return"] == 102 / 100 - 1
    assert pd.isna(labels.loc[8, "forward_return"])
