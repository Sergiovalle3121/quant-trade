import pandas as pd
import pytest

from quant_trade.data.panel import (
    calculate_returns,
    load_canonical_dataset,
    pivot_close,
    pivot_open,
    validate_panel_schema,
)


def df():
    return pd.DataFrame(
        {
            "timestamp": ["2020-01-01Z", "2020-01-01Z", "2020-01-02Z"],
            "symbol": ["SPY", "QQQ", "SPY"],
            "open": [1, 2, 2],
            "high": [1.1, 2.1, 2.1],
            "low": [0.9, 1.9, 1.9],
            "close": [1, 2, 2],
            "volume": [1, 1, 1],
        }
    )


def test_panel_pivots(tmp_path):
    f = validate_panel_schema(df())
    assert list(f.columns)[:2] == ["timestamp", "symbol"]
    assert pivot_close(f).shape == (2, 2)
    assert pivot_open(f).shape == (2, 2)
    assert calculate_returns(pivot_close(f)).loc[
        pd.Timestamp("2020-01-02", tz="UTC"), "SPY"
    ] == pytest.approx(1.0)
    p = tmp_path / "d.csv"
    f.to_csv(p, index=False)
    assert load_canonical_dataset(p).shape[0] == 3


def test_panel_rejects_duplicate_missing():
    d = df()
    d.loc[2, "symbol"] = "QQQ"
    d.loc[2, "timestamp"] = "2020-01-01Z"
    with pytest.raises(ValueError):
        validate_panel_schema(d)
    with pytest.raises(ValueError):
        validate_panel_schema(df().drop(columns=["close"]))
