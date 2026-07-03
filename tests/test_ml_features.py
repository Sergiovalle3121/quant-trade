import pandas as pd

from quant_trade.ml.features import generate_features


def _data():
    dates = pd.date_range("2020-01-01", periods=30, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "symbol": "AAA",
            "open": range(30),
            "high": range(1, 31),
            "low": range(30),
            "close": [100 + i for i in range(30)],
            "volume": [1000 + i for i in range(30)],
            "provider": "test",
            "interval": "1d",
        }
    )


def test_features_use_only_past_data():
    base = _data()
    changed = base.copy()
    changed.loc[changed.index[-1], "close"] = 10000
    f1 = generate_features(base)
    f2 = generate_features(changed)
    pd.testing.assert_series_equal(
        f1.iloc[:-1]["return_1d_lag1"], f2.iloc[:-1]["return_1d_lag1"]
    )
