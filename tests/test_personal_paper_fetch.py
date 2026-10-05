from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.personal_paper import fetch
from quant_trade.personal_paper.fetch import normalize_fx, normalize_history, normalize_open_quote


def _history():
    index = pd.to_datetime(["2024-01-02", "2024-01-03"]).tz_localize("America/New_York")
    return pd.DataFrame(
        {
            "Open": [100.0, 100.0],
            "High": [101.0, 101.0],
            "Low": [99.0, 99.0],
            "Close": [100.0, 100.0],
            "Volume": [1000, 1000],
            "Dividends": [0.0, 0.5],
            "Stock Splits": [0.0, 0.0],
        },
        index=index,
    )


def _calendar():
    return pd.DataFrame(
        {
            "session_date": ["2024-01-02", "2024-01-03"],
            "session_open_utc": ["2024-01-02T14:30:00Z", "2024-01-03T14:30:00Z"],
            "session_close_utc": ["2024-01-02T21:00:00Z", "2024-01-03T21:00:00Z"],
        }
    )


def test_closed_bar_cutoff_uses_exchange_close_not_midnight():
    frame = normalize_history(_history(), "SPY", _calendar(), pd.Timestamp("2024-01-03T20:59:59Z"))
    assert len(frame) == 1
    assert frame.bar_end_utc.iloc[0] == pd.Timestamp("2024-01-02T21:00:00Z")


def test_explicit_split_restores_pre_event_price_units():
    raw = _history()
    raw.loc[raw.index[1], "Stock Splits"] = 2.0
    frame = normalize_history(raw, "SPY", _calendar(), pd.Timestamp("2024-01-04T00:00:00Z"))
    assert frame.close.tolist() == [200.0, 100.0]
    assert frame.split_ratio.tolist() == [1.0, 2.0]
    # Old position's wealth is unchanged by a 2:1 split, not doubled.
    assert frame.close.iloc[0] == frame.close.iloc[1] * frame.split_ratio.iloc[1]


@pytest.mark.parametrize("value", [np.nan, np.inf, -1.0])
def test_invalid_provider_prices_fail_closed(value):
    raw = _history()
    raw.loc[raw.index[0], "Close"] = value
    with pytest.raises(ValueError):
        normalize_history(raw, "SPY", _calendar(), pd.Timestamp("2024-01-04T00:00:00Z"))


def test_fx_does_not_label_todays_evolving_value_as_completed():
    raw = pd.DataFrame({"Close": [17.0, 18.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    fx = normalize_fx(raw, pd.Timestamp("2024-01-03T15:00:00Z"))
    assert fx.usd_mxn.tolist() == [17.0]
    assert fx.timestamp.tolist() == ["2024-01-03T00:00:00+00:00"]
    assert "Yahoo" in fx.source.iloc[0]


def test_market_holiday_cannot_be_accepted_as_exchange_session():
    with pytest.raises(ValueError, match="outside the exchange calendar"):
        normalize_history(
            _history(), "SPY", _calendar().iloc[1:], pd.Timestamp("2024-01-04T00:00:00Z")
        )


def test_quote_keeps_price_time_and_rejects_missed_open():
    raw = pd.DataFrame(
        {"Close": [100.0], "Volume": [1000], "Dividends": [0.0], "Stock Splits": [0.0]},
        index=pd.to_datetime(["2024-01-03T14:30:00Z"]),
    )
    quote = normalize_open_quote(raw, "SPY", _calendar(), pd.Timestamp("2024-01-03T14:32:00Z"))
    assert quote["observed_at_utc"] == "2024-01-03T14:31:00+00:00"
    assert quote["previous_session_date"] == "2024-01-02"
    assert quote["available_volume"] == 1000
    assert quote["dividend"] == 0.0 and quote["split_ratio"] == 1.0
    assert (
        normalize_open_quote(raw, "SPY", _calendar(), pd.Timestamp("2024-01-03T14:36:00Z")) is None
    )


def test_delayed_quote_does_not_become_fresh_on_retrieval():
    raw = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2024-01-02T20:59:00Z"]))
    assert (
        normalize_open_quote(raw, "SPY", _calendar(), pd.Timestamp("2024-01-03T14:32:00Z")) is None
    )


def test_missing_actions_or_liquidity_is_not_assumed_zero():
    raw = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2024-01-03T14:30:00Z"]))
    assert (
        normalize_open_quote(raw, "SPY", _calendar(), pd.Timestamp("2024-01-03T14:32:00Z")) is None
    )


@pytest.mark.parametrize("column", ["Dividends", "Stock Splits", "Volume"])
def test_daily_history_does_not_invent_missing_actions_or_liquidity(column):
    with pytest.raises(ValueError, match="explicit OHLCV"):
        normalize_history(
            _history().drop(columns=column),
            "SPY",
            _calendar(),
            pd.Timestamp("2024-01-04T00:00:00Z"),
        )


def test_daily_cutoff_and_actual_receipt_are_distinct():
    cutoff = pd.Timestamp("2024-01-03T20:59:59Z")
    received = pd.Timestamp("2024-01-03T21:02:00Z")
    frame = normalize_history(_history(), "SPY", _calendar(), cutoff, received_at=received)
    assert len(frame) == 1  # the new close was outside the requested cutoff
    assert (frame.observed_at_utc == received).all()


def test_quote_arriving_after_open_window_cannot_be_backdated():
    raw = pd.DataFrame(
        {"Close": [100.0], "Volume": [1000], "Dividends": [0.0], "Stock Splits": [0.0]},
        index=pd.to_datetime(["2024-01-03T14:30:00Z"]),
    )
    assert (
        normalize_open_quote(
            raw,
            "SPY",
            _calendar(),
            pd.Timestamp("2024-01-03T14:32:00Z"),
            received_at=pd.Timestamp("2024-01-03T14:36:00Z"),
        )
        is None
    )


def test_snapshot_records_receipt_after_network_response(tmp_path, monkeypatch):
    import json

    import yfinance as yf

    current = [pd.Timestamp("2024-01-04T00:00:00Z")]

    class FakeClock:
        @staticmethod
        def now(tz):
            return current[0].to_pydatetime()

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            current[0] += pd.Timedelta(minutes=1)
            if self.symbol == "MXN=X":
                return pd.DataFrame(
                    {"Close": [17.0, 18.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])
                )
            return _history()

    monkeypatch.setattr(fetch, "datetime", FakeClock)
    monkeypatch.setattr(fetch, "_calendar", lambda start, end: _calendar())
    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    snapshot = fetch.fetch_snapshot("2024-01-02", tmp_path)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    panel = pd.read_csv(snapshot / "panel.csv")
    assert pd.Timestamp(manifest["retrieved_at_utc"]) == pd.Timestamp("2024-01-04T00:06:00Z")
    assert pd.to_datetime(panel.observed_at_utc, utc=True).min() > pd.Timestamp(
        manifest["as_of_utc"]
    )


def test_incomplete_provider_reply_does_not_publish_or_replace_snapshot(tmp_path, monkeypatch):
    import yfinance as yf

    pointer = tmp_path / "latest.txt"
    pointer.write_text("existing-verified-snapshot", encoding="utf-8")

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            return _history().drop(columns="Dividends") if self.symbol == "IWM" else _history()

    monkeypatch.setattr(fetch, "_calendar", lambda start, end: _calendar())
    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    with pytest.raises(ValueError, match="explicit OHLCV"):
        fetch.fetch_snapshot("2024-01-02", tmp_path, as_of="2024-01-04T00:00:00Z")
    assert pointer.read_text(encoding="utf-8") == "existing-verified-snapshot"
    assert list(tmp_path.iterdir()) == [pointer]
