from pathlib import Path

import pytest

from quant_trade.data.csv_loader import CsvValidationError, load_ohlcv_csv


def test_load_ohlcv_csv_sorts_and_validates() -> None:
    data = load_ohlcv_csv("examples/data/sample_ohlcv.csv")
    assert list(data.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert data["timestamp"].is_monotonic_increasing


def test_load_ohlcv_csv_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,open\n2024-01-01,1\n")
    with pytest.raises(CsvValidationError, match="Missing required"):
        load_ohlcv_csv(path)
