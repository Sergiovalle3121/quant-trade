"""Deterministic synthetic OHLCV provider for tests and demos."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.schema import normalize_ohlcv
from quant_trade.data.validation import validate_ohlcv


class SyntheticProvider:
    name = "synthetic"

    def supports_interval(self, interval: str) -> bool:
        return interval == "1d"

    def fetch_ohlcv(self, request: HistoricalDataRequest) -> pd.DataFrame:
        if not self.supports_interval(request.interval):
            raise ValueError("synthetic provider currently supports daily interval '1d' only")
        frames = []
        dates = pd.date_range(request.start, request.end, freq="B", inclusive="left", tz="UTC")
        for offset, symbol in enumerate(request.symbols):
            rng = np.random.default_rng(request.seed + offset)
            returns = rng.normal(0.0003, 0.01, len(dates))
            close = 100.0 * np.cumprod(1.0 + returns)
            open_ = close * (1.0 + rng.normal(0.0, 0.002, len(dates)))
            high = np.maximum(open_, close) * (1.0 + rng.uniform(0.0, 0.01, len(dates)))
            low = np.minimum(open_, close) * (1.0 - rng.uniform(0.0, 0.01, len(dates)))
            volume = rng.integers(100_000, 2_000_000, len(dates)).astype(float)
            frames.append(
                pd.DataFrame(
                    {
                        "timestamp": dates,
                        "symbol": symbol,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                        "adjusted_close": close,
                    }
                )
            )
        return validate_ohlcv(
            normalize_ohlcv(
                pd.concat(frames, ignore_index=True), provider=self.name, interval=request.interval
            )
        )
