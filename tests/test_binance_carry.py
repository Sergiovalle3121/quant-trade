"""Binance archive venue and the H1-BIN pre-registration (offline, no network)."""

from __future__ import annotations

import io
import zipfile

import pytest

from quant_trade.evidence.canonical_json import sha256_of_bytes
from quant_trade.v8.backfill import ChecksumMismatch, binance_archive_get
from quant_trade.v8.venues import (
    IdentityMismatch,
    VenueErrorResponse,
    instruments_url,
    parse_binance_funding,
    parse_binance_kline,
    series_spec,
    server_time_url,
)
from quant_trade.v9 import binance_carry_registration as reg

JAN_2024_MS = 1_704_067_200_000


def _zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


KLINE_ROW = "{ts},100.0,110.0,90.0,105.0,12.5,{end},1312.5,40,6.0,630.0,0\n"


def test_kline_parser_reads_headerless_millisecond_files() -> None:
    text = KLINE_ROW.format(ts=JAN_2024_MS, end=JAN_2024_MS + 3_599_999)
    rows = parse_binance_kline(_zip("BTCUSDT-1h-2024-01.csv", text), symbol="BTC", kind="perp")
    assert rows == [
        {
            "start_ms": JAN_2024_MS,
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 12.5,
            "quote_volume": 1312.5,
        }
    ]


def test_kline_parser_skips_header_and_converts_microseconds() -> None:
    header = "open_time,open,high,low,close,volume,close_time,quote_volume,count,a,b,ignore\n"
    text = header + KLINE_ROW.format(ts=JAN_2024_MS * 1000, end=(JAN_2024_MS + 3_599_999) * 1000)
    rows = parse_binance_kline(_zip("BTCUSDT-1h-2025-01.csv", text), symbol="BTC", kind="spot")
    assert rows[0]["start_ms"] == JAN_2024_MS


def test_mark_and_index_klines_carry_no_volume() -> None:
    text = KLINE_ROW.format(ts=JAN_2024_MS, end=JAN_2024_MS + 3_599_999)
    rows = parse_binance_kline(_zip("BTCUSDT-1h-2024-01.csv", text), symbol="BTC", kind="mark")
    assert "volume" not in rows[0]


def test_parser_refuses_another_symbols_file() -> None:
    text = KLINE_ROW.format(ts=JAN_2024_MS, end=JAN_2024_MS + 3_599_999)
    with pytest.raises(IdentityMismatch):
        parse_binance_kline(_zip("ETHUSDT-1h-2024-01.csv", text), symbol="BTC", kind="perp")


def test_parser_refuses_a_non_zip_payload() -> None:
    with pytest.raises(VenueErrorResponse):
        parse_binance_kline(b"<html>not found</html>", symbol="BTC", kind="perp")


def test_funding_parser_snaps_calc_latency_and_keeps_the_raw_stamp() -> None:
    text = (
        "calc_time,funding_interval_hours,last_funding_rate\n"
        f"{JAN_2024_MS + 1},8,0.0001\n"
        f"{JAN_2024_MS + 8 * 3_600_000},8,-0.00002\n"
    )
    rows = parse_binance_funding(_zip("BTCUSDT-fundingRate-2024-01.csv", text), symbol="BTC")
    assert [r["settled_at_ms"] for r in rows] == [JAN_2024_MS, JAN_2024_MS + 8 * 3_600_000]
    assert rows[0]["calc_time_ms"] == JAN_2024_MS + 1
    assert rows[1]["rate"] == -0.00002
    assert {r["rate_field"] for r in rows} == {"last_funding_rate"}


def test_funding_parser_refuses_a_kline_file() -> None:
    with pytest.raises(IdentityMismatch):
        parse_binance_funding(_zip("BTCUSDT-1h-2024-01.csv", "1,8,0.1\n"), symbol="BTC")


def test_archive_urls_walk_one_month_per_file() -> None:
    spec = series_spec("binance", "mark")
    url = spec.build_url(symbol="BTC", kind="mark", cursor_ms=JAN_2024_MS, interval_minutes=60)
    assert url == (
        "https://data.binance.vision/data/futures/um/monthly/markPriceKlines/"
        "BTCUSDT/1h/BTCUSDT-1h-2024-01.zip"
    )
    previous = spec.build_url(
        symbol="BTC", kind="mark", cursor_ms=JAN_2024_MS - 1, interval_minutes=60
    )
    assert previous.endswith("BTCUSDT-1h-2023-12.zip")
    funding = series_spec("binance", "funding").build_url(
        symbol="BTC", kind="funding", cursor_ms=JAN_2024_MS, interval_minutes=60
    )
    assert funding.endswith("/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-01.zip")


def test_archive_has_no_clock_or_instrument_endpoint() -> None:
    assert server_time_url("binance") is None
    assert instruments_url("binance", "BTC") is None


def test_archive_fetch_requires_the_venue_checksum(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"zip-bytes"
    published = {"value": sha256_of_bytes(payload)}

    def fake_http_get(url: str, *, timeout_seconds: float = 20.0):
        if url.endswith(".CHECKSUM"):
            return 200, f"{published['value']}  file.zip\n".encode(), {}
        return 200, payload, {}

    monkeypatch.setattr("quant_trade.v8.backfill.http_get", fake_http_get)
    assert binance_archive_get("https://data.binance.vision/x.zip")[1] == payload
    published["value"] = "0" * 64
    with pytest.raises(ChecksumMismatch):
        binance_archive_get("https://data.binance.vision/x.zip")


def test_registration_is_pinned() -> None:
    assert reg.freeze_hash() == reg.FROZEN_HASH


def test_registration_reuses_h1_variants_and_gates_unchanged() -> None:
    from quant_trade.v8.preregistration import H1, PROMOTION_GATES

    payload = reg.registration()
    assert [v["parameters"] for v in payload["variants"]] == [v.parameters for v in H1.variants]
    for name, value in PROMOTION_GATES.items():
        assert payload["gates"][name] == value
    assert payload["gates"]["require_positive_holdout"] is True
