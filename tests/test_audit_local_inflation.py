"""Each currency after its own inflation. Offline: every provider is stubbed."""

from __future__ import annotations

import json
from dataclasses import replace
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
from quant_trade.audit.market import (
    LOCAL_CPI,
    PROVIDER_AGENT,
    SERIES,
    MarketData,
    parse_provider,
)
from quant_trade.audit.market import _download as real_download
from quant_trade.audit.method import COPY as METHOD_COPY
from quant_trade.audit.pages import method_page
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

EUROSTAT = json.dumps(
    {
        "value": {"0": 99.65, "2": 100.17},
        "dimension": {"time": {"category": {"index": {"2026-01": 0, "2026-02": 1, "2026-03": 2}}}},
    }
)
ONS = (
    '"Title","CPI INDEX 00: ALL ITEMS 2015=100"\n"CDID","D7BT"\n"2025","140.1"\n'
    '"2025 Q4","141.0"\n"2026 JUL","142.9"\n"2026 AUG","143.6"\n'
)
BOC = (
    '"TERMS AND CONDITIONS"\n"https://www.bankofcanada.ca/terms/"\n\n"SERIES"\n'
    '"id","label","description"\n"V41690973","Total CPI","Total CPI"\n\n"OBSERVATIONS"\n'
    '"date","V41690973"\n"2026-07-01","169.9"\n"2026-08-01","169.8"\n'
)
BCB = json.dumps(
    [
        {"data": "01/12/1994", "valor": "1.71"},
        {"data": "01/01/1995", "valor": "1.00"},
        {"data": "01/02/1995", "valor": "-0.50"},
    ]
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


def test_each_provider_reply_becomes_a_monthly_index() -> None:
    swiss = parse_provider(EUROSTAT, "eurostat")
    assert list(swiss.index) == [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01")]
    uk = parse_provider(ONS, "ons")  # yearly and quarterly rows are skipped
    assert list(uk.index) == [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")]
    assert uk.iloc[-1] == pytest.approx(143.6)
    canada = parse_provider(BOC, "boc")
    assert canada.iloc[-1] == pytest.approx(169.8) and len(canada) == 2
    # Brazil's monthly changes are chained from January 1995.
    brazil = parse_provider(BCB, "bcb")
    assert list(brazil.to_numpy()) == pytest.approx([101.0, 101.0 * 0.995])
    assert {asset.label for asset in LOCAL_CPI} == {"EUR", "GBP", "CAD", "CHF", "BRL"}
    assert all(asset.key in SERIES for asset in LOCAL_CPI)
    assert SERIES["cpi_eur"].source_url.endswith("CP0000EZ19M086NEST")
    assert SERIES["cpi_gbp"].source_url.startswith("https://www.ons.gov.uk/")


def test_a_broken_reply_keeps_nothing() -> None:
    def stub(text: str) -> MarketData:
        return MarketData(lambda series: text)

    assert stub(ONS).refresh("cpi_gbp") is True
    assert stub("<html>blocked</html>").refresh("cpi_gbp") is False
    assert stub("<html>blocked</html>").refresh("cpi_chf") is False
    assert stub(BOC.replace("169.8", "0.0001")).refresh("cpi_cad") is False
    wild = json.dumps([{"data": "01/01/1995", "valor": "80"}, {"data": "01/02/1995", "valor": "1"}])
    assert stub(wild).refresh("cpi_brl") is False


def test_providers_are_asked_at_their_fixed_https_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[Any] = []

    class Reply:
        status = 200

        def __init__(self) -> None:
            self.left = [ONS.encode()]

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
    assert real_download("d7bt", "ons") == ONS
    assert real_download("DTB3") == ONS
    ons, fred = asked
    assert ons.full_url.startswith("https://www.ons.gov.uk/generator?format=csv")
    assert ons.get_header("User-agent") == PROVIDER_AGENT
    # FRED keeps Python's default User-Agent (it stalls some custom ones).
    assert fred.full_url.startswith("https://fred.stlouisfed.org/")
    assert fred.get_header("User-agent") is None


def test_a_dollar_account_shows_each_currency_after_its_own_inflation() -> None:
    days = pd.date_range("2023-01-02", periods=400, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    series = {
        "fx_brl": _daily(days, 5.0, 6.0),
        "fx_mxn": _daily(days, 18.0, 18.0),
        "cpi_brl": _monthly(days, 100.0, 105.0),
    }
    out = in_currencies(frame, series, "USD")
    by_code = {item["code"]: item for item in out["currencies"]}
    brl = by_code["BRL"]
    real = brl["real"]
    inflation = real["inflation"]["value"]
    assert inflation == pytest.approx(0.05, abs=1e-9)
    # 20 % more reais, 5 % dearer prices: about 14 % more buying power.
    assert real["total_return"]["value"] == pytest.approx(
        (1 + brl["total_return"]["value"]) / (1 + inflation) - 1, rel=1e-9
    )
    assert real["total_return"]["note"] == LOCAL_REAL_NOTE and real["provider"] == "bcb"
    assert "yearly_inflation" in real
    # The peso has no open official index here: its row stays, without one after inflation.
    assert "real" not in by_code["MXN"]


def test_prices_that_stop_months_before_the_end_are_not_used() -> None:
    days = pd.date_range("2023-01-02", periods=400, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    early = _monthly(days, 100.0, 105.0)[:-4]
    out = in_currencies(frame, {"fx_brl": _daily(days, 5.0, 6.0), "cpi_brl": early}, "USD")
    assert "real" not in out["currencies"][0]
    real = in_currencies(frame, {"cpi_brl": early}, "BRL")
    assert real["status"] == "NOT_MEASURED" and real["reason"] == LOCAL_CPI_NOT_COVERED


def test_an_account_in_reais_shows_its_own_real_result() -> None:
    days = pd.date_range("2023-01-02", periods=400, freq="D")
    levels = np.linspace(10_000.0, 10_400.0, len(days))
    out = in_currencies(_curve(days, levels), {"cpi_brl": _monthly(days, 100.0, 105.0)}, "brl")
    assert out["status"] == "MEASURED" and out["base"] == "BRL" and out["currencies"] == []
    assert out["account"]["total_return"]["value"] == pytest.approx(0.04)
    # Grew 4 % while prices rose 5 %: it lost buying power.
    assert out["real"]["total_return"]["value"] == pytest.approx(1.04 / 1.05 - 1)
    assert "dollars" not in out and "assumption" not in out
    missing = in_currencies(_curve(days, levels), {}, "EUR")
    assert missing["reason"] == LOCAL_CPI_UNAVAILABLE and missing["status"] == "NOT_MEASURED"
    for other in ("MXN", "JPY", "AUD"):
        assert in_currencies(_curve(days, levels), {}, other)["reason"] == OTHER_CURRENCY


def _inputs(locale: str) -> Any:
    days = pd.bdate_range("2023-01-02", periods=320)
    returns = np.random.default_rng(5).normal(0.0004, 0.004, len(days))
    frame = _curve(days, 10_000 * np.cumprod(1 + returns))
    return build_inputs(csv_bytes(frame), DeclaredMetadata(locale=locale)), days


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_report_shows_real_rows_and_credits_each_source(locale: str) -> None:
    inputs, days = _inputs(locale)
    series = {
        "fx_mxn": _daily(days, 18.0, 19.0),
        "fx_gbp": _daily(days, 1.25, 1.30),
        "fx_eur": _daily(days, 1.10, 1.05),
        "cpi_gbp": _monthly(days, 130.0, 136.0),
        "cpi_eur": _monthly(days, 120.0, 123.0),
        "cpi": _monthly(days, 300.0, 310.0),
    }
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    for code in ("GBP", "EUR"):
        name = labels[f"currency_{code}"]
        assert escape(labels["currency_real_local"].format(name=name)) in html
        assert escape(labels[f"currency_attrib_{code}"]) in html
    assert "Open Government Licence v3.0" in html
    assert f"href='{SERIES['cpi_gbp'].source_url}'" in html
    assert escape(labels["currency_real_local"].format(name=labels["currency_MXN"])) not in html
    assert untranslated(result.model_dump(mode="json")) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_report_of_an_account_in_canadian_dollars(locale: str) -> None:
    inputs, days = _inputs(locale)
    inputs = replace(inputs, account_currency="CAD")
    series = {"cpi_cad": _monthly(days, 160.0, 166.0)}
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    section = result.in_currencies
    assert section is not None and section["base"] == "CAD"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    name = labels["currency_CAD"]
    assert escape(labels["currency_account_local"].format(name=name)) in html
    assert escape(labels["currency_inflation_local_yearly"].split("({code})")[0]) in html
    # The Bank of Canada asks paid services to say the data is free on its site.
    assert (
        "bankofcanada.ca" in escape(labels["currency_attrib_CAD"])
        and escape(labels["currency_attrib_CAD"]) in html
    )
    assert labels["currency_dollars"] not in html
    assert untranslated(result.model_dump(mode="json")) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_methodology_page_credits_every_public_source(locale: str) -> None:
    page = method_page(locale=locale)
    for line in METHOD_COPY[locale]["data"]:  # type: ignore[union-attr]
        assert escape(str(line)) in page
        assert find_claims(str(line)) == []
    for name in ("FRED", "Eurostat", "Office for National Statistics", "Banco Central do Brasil"):
        assert name in page


def test_new_texts_make_no_claims_and_every_series_is_read() -> None:
    for locale in ("es", "en", "pt"):
        for key, text in LABELS[locale].items():
            if key.startswith("currency_"):
                assert find_claims(text) == [], (locale, key)
    assert {asset.key for asset in LOCAL_CPI} <= set(series_keys())
