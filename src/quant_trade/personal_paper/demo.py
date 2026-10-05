"""Deterministic invented bars/FX for plumbing; never market evidence."""

from pathlib import Path

import numpy as np
import pandas as pd

from quant_trade.personal_paper.config import UNIVERSE


def create_demo(output: Path, sessions: int = 180) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2020-01-02", periods=sessions, tz="UTC")
    rows = []
    for index, timestamp in enumerate(dates):
        for asset, symbol in enumerate(UNIVERSE):
            price = (50 + asset * 20) * (1 + index * 0.0002 + 0.01 * np.sin(index / 7 + asset))
            rows.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "symbol": symbol,
                    "open": price * 0.999,
                    "high": price * 1.005,
                    "low": price * 0.995,
                    "close": price,
                    "volume": 1_000_000,
                    "bar_end_utc": (timestamp + pd.Timedelta(hours=21)).isoformat(),
                    "observed_at_utc": (timestamp + pd.Timedelta(hours=21, minutes=1)).isoformat(),
                }
            )
    data_path, fx_path = output / "synthetic_ohlcv.csv", output / "synthetic_fx.csv"
    pd.DataFrame(rows).to_csv(data_path, index=False)
    pd.DataFrame(
        {
            "timestamp": [t.isoformat() for t in dates],
            "usd_mxn": 20.0,
            "source": "SYNTHETIC_FIXTURE_ASSUMPTION_NOT_MARKET_DATA",
        }
    ).to_csv(fx_path, index=False)
    return {"data": data_path, "fx": fx_path}
