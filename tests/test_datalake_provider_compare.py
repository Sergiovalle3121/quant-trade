import pandas as pd

from quant_trade.datalake.provider_compare import compare_providers


def test_provider_comparison_detects_differences() -> None:
    a = pd.DataFrame(
        {
            "timestamp": ["2020-01-01", "2020-01-02"],
            "symbol": ["SPY", "SPY"],
            "close": [100.0, 101.0],
        }
    )
    b = pd.DataFrame(
        {
            "timestamp": ["2020-01-01", "2020-01-03"],
            "symbol": ["SPY", "SPY"],
            "close": [110.0, 102.0],
        }
    )
    report = compare_providers(a, b, "SPY", "1d", "a", "b", 1.0)
    assert report.status in {"warn", "fail"}
    assert report.missing_bars_a == 1
    assert report.missing_bars_b == 1
