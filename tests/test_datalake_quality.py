import pandas as pd

from quant_trade.datalake.quality import (
    flag_corporate_action_risk,
    flag_survivorship_bias_risk,
    generate_dataset_quality_report,
)


def test_quality_flags_duplicates_and_bias() -> None:
    df = pd.DataFrame(
        {
            "timestamp": ["2020-01-01", "2020-01-01", "2020-01-02"],
            "symbol": ["SPY", "SPY", "SPY"],
            "open": [1, 1, 1],
            "high": [1, 1, 1],
            "low": [1, 1, 1],
            "close": [1, 1, 2],
            "volume": [1, 1, 1],
        }
    )
    report = generate_dataset_quality_report("d1", df)
    assert report.status == "fail"
    assert flag_corporate_action_risk(df, 0.25)
    assert flag_survivorship_bias_risk("d1", ["SPY"], "etf")
