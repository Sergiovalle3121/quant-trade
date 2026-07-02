from __future__ import annotations

import sys
import types

import pandas as pd
import pytest
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.data.cache import list_cache, write_cache
from quant_trade.data.providers import get_data_provider
from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.schema import normalize_ohlcv
from quant_trade.data.validation import MarketDataValidationError, validate_ohlcv


def test_request_validation() -> None:
    with pytest.raises(ValueError):
        HistoricalDataRequest(
            provider="synthetic", symbols=[], start="2020-01-02", end="2020-01-01", interval="2d"
        )


def test_normalize_and_validate() -> None:
    data = pd.DataFrame(
        {
            "Date": ["2020-01-01"],
            "Open": [1],
            "High": [2],
            "Low": [0.5],
            "Close": [1.5],
            "Volume": [10],
        }
    )
    out = normalize_ohlcv(data, provider="csv", interval="1d", symbol="spy")
    assert str(out["timestamp"].dt.tz) == "UTC"
    assert validate_ohlcv(out).loc[0, "symbol"] == "SPY"


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda d: d.drop(columns=["open"]), "missing"),
        (lambda d: d.assign(high=0.5), "high"),
        (lambda d: d.assign(open=-1), "prices"),
        (lambda d: d.assign(volume=-1), "volume"),
        (lambda d: pd.concat([d, d]), "duplicate"),
        (lambda d: d.iloc[0:0], "empty"),
    ],
)
def test_validation_errors(mutate, message: str) -> None:
    base = normalize_ohlcv(
        pd.DataFrame(
            {
                "timestamp": ["2020-01-01"],
                "open": [1],
                "high": [2],
                "low": [0.5],
                "close": [1],
                "volume": [1],
                "symbol": ["SPY"],
            }
        ),
        provider="x",
        interval="1d",
    )
    with pytest.raises(MarketDataValidationError, match=message):
        validate_ohlcv(mutate(base))


def test_synthetic_provider_deterministic() -> None:
    req = HistoricalDataRequest(
        provider="synthetic",
        symbols=["SPY", "QQQ"],
        start="2020-01-01",
        end="2020-01-10",
        interval="1d",
    )
    first = get_data_provider("synthetic").fetch_ohlcv(req)
    second = get_data_provider("synthetic").fetch_ohlcv(req)
    pd.testing.assert_frame_equal(first, second)
    assert set(first["symbol"]) == {"SPY", "QQQ"}


def test_csv_provider(tmp_path) -> None:
    path = tmp_path / "bars.csv"
    path.write_text("timestamp,open,high,low,close,volume\n2020-01-01,1,2,1,2,100\n")
    req = HistoricalDataRequest(
        provider="csv",
        symbols=["SPY"],
        start="2020-01-01",
        end="2020-01-02",
        interval="1d",
        path=str(path),
    )
    assert len(get_data_provider("csv").fetch_ohlcv(req)) == 1


def test_yfinance_mock_single_and_missing(monkeypatch) -> None:
    req = HistoricalDataRequest(
        provider="yfinance", symbols=["SPY"], start="2020-01-01", end="2020-01-03", interval="1d"
    )
    monkeypatch.setitem(sys.modules, "yfinance", None)
    with pytest.raises(ImportError, match="pip install"):
        get_data_provider("yfinance").fetch_ohlcv(req)
    fake = types.SimpleNamespace(
        download=lambda *a, **k: pd.DataFrame(
            {"Open": [1], "High": [2], "Low": [1], "Close": [2], "Volume": [100]},
            index=pd.DatetimeIndex(["2020-01-01"], name="Date"),
        )
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    assert len(get_data_provider("yfinance").fetch_ohlcv(req)) == 1


def test_yfinance_mock_multi(monkeypatch) -> None:
    cols = pd.MultiIndex.from_product([["SPY", "QQQ"], ["Open", "High", "Low", "Close", "Volume"]])
    raw = pd.DataFrame(
        [[1, 2, 1, 2, 100, 3, 4, 3, 4, 200]],
        columns=cols,
        index=pd.DatetimeIndex(["2020-01-01"], name="Date"),
    )
    monkeypatch.setitem(
        sys.modules, "yfinance", types.SimpleNamespace(download=lambda *a, **k: raw)
    )
    req = HistoricalDataRequest(
        provider="yfinance",
        symbols=["SPY", "QQQ"],
        start="2020-01-01",
        end="2020-01-03",
        interval="1d",
    )
    assert set(get_data_provider("yfinance").fetch_ohlcv(req)["symbol"]) == {"SPY", "QQQ"}


def test_polygon_mock(monkeypatch) -> None:
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    req = HistoricalDataRequest(
        provider="polygon", symbols=["SPY"], start="2020-01-01", end="2020-01-03", interval="1d"
    )
    with pytest.raises(RuntimeError, match="POLYGON_API_KEY"):
        get_data_provider("polygon").fetch_ohlcv(req)
    monkeypatch.setenv("POLYGON_API_KEY", "placeholder")
    response = types.SimpleNamespace(
        json=lambda: {"results": [{"t": 1577836800000, "o": 1, "h": 2, "l": 1, "c": 2, "v": 100}]}
    )
    monkeypatch.setitem(
        sys.modules, "requests", types.SimpleNamespace(get=lambda *a, **k: response)
    )
    assert len(get_data_provider("polygon").fetch_ohlcv(req)) == 1


def test_cache_and_cli(tmp_path) -> None:
    req = HistoricalDataRequest(
        provider="synthetic",
        symbols=["SPY"],
        start="2020-01-01",
        end="2020-01-10",
        interval="1d",
        output_dir=str(tmp_path),
    )
    data = get_data_provider("synthetic").fetch_ohlcv(req)
    path = write_cache(data, req)
    assert path.with_suffix(".manifest.json").exists()
    with pytest.raises(FileExistsError):
        write_cache(data, req)
    assert list_cache(tmp_path, "synthetic") == [path]
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "data",
            "fetch",
            "--provider",
            "synthetic",
            "--symbol",
            "SPY",
            "--start",
            "2020-01-01",
            "--end",
            "2020-01-10",
            "--interval",
            "1d",
            "--output-dir",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output
    csv_path = next((tmp_path / "cli").rglob("*.csv"))
    assert runner.invoke(app, ["data", "validate", "--path", str(csv_path)]).exit_code == 0
    assert runner.invoke(app, ["data", "info", "--path", str(csv_path)]).exit_code == 0
    assert (
        runner.invoke(app, ["data", "list-cache", "--output-dir", str(tmp_path / "cli")]).exit_code
        == 0
    )


def test_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown data provider"):
        get_data_provider("bad")
