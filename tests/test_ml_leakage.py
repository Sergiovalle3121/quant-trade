import pandas as pd

from quant_trade.ml.leakage import check_leakage


def test_leakage_detector_catches_bad_feature():
    f = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=3, tz="UTC"),
            "symbol": "AAA",
            "future_return": [1, 2, 3],
        }
    )
    labels = pd.DataFrame(
        {
            "timestamp": f["timestamp"],
            "symbol": "AAA",
            "forward_return": [0.1, 0.2, 0.3],
        }
    )
    report = check_leakage(f, labels, f.iloc[:2], f.iloc[2:])
    assert report["status"] == "fail"
