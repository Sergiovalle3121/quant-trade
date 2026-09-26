"""Each currency after its own inflation. Offline: the IMF and FRED are stubbed."""

from __future__ import annotations

from html import escape
from typing import Any

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit import market as market_lib
from quant_trade.audit.currency import (
    LOCAL_CPI_NOT_COVERED,
    LOCAL_CPI_UNAVAILABLE,
    LOCAL_REAL_NOTE,
    OTHER_CURRENCY,
    in_currencies,
    series_keys,
)
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import IMF_ACCEPT, IMF_PAGE, LOCAL_CPI, SERIES, MarketData
from quant_trade.audit.market import _download as real_download
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

IMF_REPLY = (
    "DATAFLOW,COUNTRY,INDEX_TYPE,COICOP_1999,TYPE_OF_TRANSFORMATION,FREQUENCY,TIME_PERIOD,"
    "OBS_VALUE,SCALE\n"
    "IMF.STA:CPI(5.0.0),MEX,CPI,_T,IX,M,2026-M06,145.131,\n"
    "IMF.STA:CPI(5.0.0),MEX,CPI,_T,IX,M,2026-M07,145.169,\n"
    "IMF.STA:CPI(5.0.0),MEX,CPI,_T,IX,M,2026-M08,,\n"
    "IMF.STA:CPI(5.0.0),MEX,CPI,_T,IX,M,2026-M05,145.527,\n"
)


def _curve(days: pd.DatetimeIndex, levels: np.ndarray) -> pd.DataFrame:
    stamps = pd.DatetimeIndex(days).tz_localize("UTC") + pd.Timedelta(hours=21)
    return pd.DataFrame({"timestamp": stamps, "equity": levels})


def _daily(days: pd.DatetimeIndex, start: float, end: float) -> pd.Series:
    index = pd.date_range(days[0].normalize() - pd.Timedelta(days=7), days[-1], freq="D")
    return pd.Series(np.linspace(start, end, len(index)), index=index)


def _monthly(days: pd.DatetimeIndex, start: float, end: float) -> pd.Series:
    index = pd.date_range(days[0].to_period("M").to_timestamp(), days[-1], freq="MS")
    return pd.Series(np.linspace(start, end, len(index)), index=index)


def test_the_imf_reply_becomes_a_monthly_series() -> None:
    series = market_lib.parse_imf_csv(IMF_REPLY)
    assert list(series.index) == list(pd.date_range("2026-05-01", periods=3, freq="MS"))
    assert series.iloc[-1] == pytest.approx(145.169)  # the blank August is dropped
    assert {asset.label for asset in LOCAL_CPI} == {"MXN", "BRL", "EUR", "GBP", "JPY", "CAD", "CHF"}
    assert all(asset.key in SERIES for asset in LOCAL_CPI)
    assert SERIES["cpi_mxn"].source_url == IMF_PAGE
    assert SERIES["cpi_eur"].source_url.endswith("CP0000EZ19M086NEST")


def test_a_broken_imf_reply_keeps_nothing() -> None:
    assert MarketData(lambda series: IMF_REPLY).refresh("cpi_mxn") is True
    assert MarketData(lambda series: "<html>blocked</html>").refresh("cpi_mxn") is False
    absurd = IMF_REPLY.replace("145.131", "99999999")
    assert MarketData(lambda series: absurd).refresh("cpi_mxn") is False


def test_the_imf_is_asked_for_csv_at_its_fixed_address(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Any] = []

    class Reply:
        status = 200

        def __init__(self) -> None:
            self.left = [IMF_REPLY.encode()]

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read1(self, _size: int) -> bytes:
            return self.left.pop() if self.left else b""

    class Opener:
        def open(self, request: Any, timeout: float) -> Reply:
            asked.append(request)
            return Reply()

    monkeypatch.setattr(market_lib, "_OPENER", Opener())
    assert real_download("MEX.CPI._T.IX.M", "imf") == IMF_REPLY
    request = asked[0]
    assert request.full_url.startswith("https://api.imf.org/external/sdmx/2.1/data/IMF.STA,CPI/")
    assert "MEX.CPI._T.IX.M" in request.full_url
    assert request.get_header("Accept") == IMF_ACCEPT


def test_a_dollar_account_shows_each_currency_after_its_own_inflation() -> None:
    days = pd.date_range("2023-01-02", periods=400, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    series = {
        "fx_mxn": _daily(days, 20.0, 25.0),
        "fx_jpy": _daily(days, 140.0, 140.0),
        "cpi_mxn": _monthly(days, 100.0, 105.0),
    }
    out = in_currencies(frame, series, "USD")
    by_code = {item["code"]: item for item in out["currencies"]}
    mxn = by_code["MXN"]
    real = mxn["real"]
    inflation = real["inflation"]["value"]
    assert inflation == pytest.approx(0.05, abs=1e-9)
    # 25 % more pesos, 5 % dearer prices: about 19 % more buying power.
    assert real["total_return"]["value"] == pytest.approx(
        (1 + mxn["total_return"]["value"]) / (1 + inflation) - 1, rel=1e-9
    )
    assert real["total_return"]["note"] == LOCAL_REAL_NOTE and real["provider"] == "imf"
    assert "yearly_inflation" in real
    # Yen prices were not read: its row stays, without one after inflation.
    assert "real" not in by_code["JPY"]


def test_prices_that_stop_months_before_the_end_are_not_used() -> None:
    days = pd.date_range("2023-01-02", periods=400, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    early = _monthly(days, 100.0, 105.0)[:-6]
    out = in_currencies(frame, {"fx_mxn": _daily(days, 20.0, 25.0), "cpi_mxn": early}, "USD")
    assert "real" not in out["currencies"][0]
    peso = in_currencies(frame, {"cpi_mxn": early}, "MXN")
    assert peso["status"] == "NOT_MEASURED" and peso["reason"] == LOCAL_CPI_NOT_COVERED


def test_an_account_in_pesos_shows_its_own_real_result() -> None:
    days = pd.date_range("2023-01-02", periods=400, freq="D")
    levels = np.linspace(10_000.0, 10_400.0, len(days))
    out = in_currencies(_curve(days, levels), {"cpi_mxn": _monthly(days, 100.0, 105.0)}, "mxn")
    assert out["status"] == "MEASURED" and out["base"] == "MXN" and out["currencies"] == []
    assert out["account"]["total_return"]["value"] == pytest.approx(0.04)
    # Grew 4 % while prices rose 5 %: it lost buying power.
    assert out["real"]["total_return"]["value"] == pytest.approx(1.04 / 1.05 - 1)
    assert "dollars" not in out and "assumption" not in out
    missing = in_currencies(_curve(days, levels), {}, "EUR")
    assert missing["reason"] == LOCAL_CPI_UNAVAILABLE and missing["status"] == "NOT_MEASURED"
    assert in_currencies(_curve(days, levels), {}, "AUD")["reason"] == OTHER_CURRENCY


def _inputs(locale: str) -> Any:
    days = pd.bdate_range("2023-01-02", periods=320)
    returns = np.random.default_rng(5).normal(0.0004, 0.004, len(days))
    frame = _curve(days, 10_000 * np.cumprod(1 + returns))
    return build_inputs(csv_bytes(frame), DeclaredMetadata(locale=locale)), days


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_report_shows_real_rows_in_every_language(locale: str) -> None:
    inputs, days = _inputs(locale)
    series = {
        "fx_mxn": _daily(days, 18.0, 19.0),
        "fx_eur": _daily(days, 1.10, 1.05),
        "cpi_mxn": _monthly(days, 130.0, 136.0),
        "cpi_eur": _monthly(days, 120.0, 123.0),
        "cpi": _monthly(days, 300.0, 310.0),
    }
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    name = labels["currency_MXN"]
    assert escape(labels["currency_real_local"].format(name=name)) in html
    assert f"href='{IMF_PAGE}'" in html
    assert escape(labels["currency_note_mixed"].split("{source}")[-1].strip()) in html
    assert untranslated(result.model_dump(mode="json")) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_report_of_a_peso_account(locale: str) -> None:
    from dataclasses import replace

    inputs, days = _inputs(locale)
    inputs = replace(inputs, account_currency="MXN")
    series = {"cpi_mxn": _monthly(days, 130.0, 136.0)}
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    section = result.in_currencies
    assert section is not None and section["base"] == "MXN"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    name = labels["currency_MXN"]
    assert escape(labels["currency_account_local"].format(name=name)) in html
    assert escape(labels["currency_inflation_local_yearly"].split("({code})")[0]) in html
    assert labels["currency_dollars"] not in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_new_texts_make_no_claims_and_every_series_is_read() -> None:
    for locale in ("es", "en", "pt"):
        for key, text in LABELS[locale].items():
            if key.startswith("currency_"):
                assert find_claims(text) == [], (locale, key)
    assert {asset.key for asset in LOCAL_CPI} <= set(series_keys())
