"""Each currency after its own inflation. Offline: every provider is stubbed."""

from __future__ import annotations

import io
import json
import zipfile
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
    assert {asset.label for asset in LOCAL_CPI} == {"EUR", "GBP", "CAD", "CHF", "BRL", "MXN", "JPY"}
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
    # The peso's prices were not read: its row stays, without one after inflation.
    assert "real" not in by_code["MXN"]
    series["cpi_mxn"] = _monthly(days, 130.0, 136.5)
    peso = {item["code"]: item for item in in_currencies(frame, series, "USD")["currencies"]}
    assert peso["MXN"]["real"]["provider"] == "inegi"
    assert peso["MXN"]["real"]["inflation"]["value"] == pytest.approx(0.05, abs=1e-9)


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
    for other in ("AUD", "NZD"):
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
    words = METHOD_COPY[locale]
    assert words["data_title"] != METHOD_COPY["en"]["data_title"] or locale == "en"
    for line in words["data"]:  # type: ignore[union-attr]
        assert escape(str(line)) in page
        assert find_claims(str(line)) == []
    for name in (
        "FRED",
        "Eurostat",
        "Office for National Statistics",
        "Banco Central do Brasil",
        "INEGI",
        "Statistics Bureau",
        "e-Stat",
    ):
        assert name in page


def test_new_texts_make_no_claims_and_every_series_is_read() -> None:
    for locale in ("es", "en", "pt"):
        for key, text in LABELS[locale].items():
            if key.startswith("currency_"):
                assert find_claims(text) == [], (locale, key)
    assert {asset.key for asset in LOCAL_CPI} <= set(series_keys())


def test_a_one_month_jump_in_a_price_index_is_a_broken_reply() -> None:
    spike = ONS.replace('"2026 JUL","142.9"', '"2026 JUL","9000000"')
    assert MarketData(lambda series: spike).refresh("cpi_gbp") is False
    us = "DATE,CPIAUCNS\n2024-01-01,300\n2024-02-01,901\n2024-03-01,302\n"
    assert MarketData(lambda series: us).refresh("cpi") is False


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_prices_that_end_weeks_before_the_last_point_say_through_which_month(
    locale: str,
) -> None:
    days = pd.date_range("2023-01-02", "2024-03-10", freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    prices = _monthly(days, 100.0, 105.0)[:-2]  # through January 2024
    out = in_currencies(frame, {"cpi_gbp": prices, "cpi": prices}, "GBP")
    assert out["real"]["prices_through"] == "2024-01"
    usd = in_currencies(frame, {"cpi": prices}, "USD")
    assert usd["real"]["prices_through"] == "2024-01"
    fresh = in_currencies(frame, {"cpi": _monthly(days, 100.0, 105.0)}, "USD")
    assert "prices_through" not in fresh["real"]

    inputs, _ = _inputs(locale)
    inputs = replace(inputs, account_currency="GBP")
    stamps = pd.DatetimeIndex(inputs.equity.frame["timestamp"]).tz_localize(None)
    late = _monthly(pd.DatetimeIndex(stamps), 130.0, 136.0)[:-1]
    result = run_audit(
        inputs, bootstrap_samples=200, risk_samples=300, market={"cpi_gbp": late}.get
    )
    html, _ = render(result, watermark=False)
    month = late.index[-1].strftime("%Y-%m")
    assert escape(LABELS[locale]["currency_prices_through"].format(month=month)) in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_a_brazilian_chain_with_a_missing_repeated_or_unreadable_month_is_refused() -> None:
    months = [{"data": f"01/{month:02d}/1995", "valor": "1.0"} for month in range(1, 7)]
    assert len(parse_provider(json.dumps(months), "bcb")) == 6
    missing = months[:2] + months[3:]
    repeated = months[:3] + [months[2]] + months[3:]
    unreadable = months[:2] + [{"data": "01/03/1995", "valor": "1,5"}] + months[3:]
    for broken in (json.dumps(rows) for rows in (missing, repeated, unreadable)):
        with pytest.raises(ValueError):
            parse_provider(broken, "bcb")
        assert MarketData(lambda series, text=broken: text).refresh("cpi_brl") is False


INPC = "Índice nacional de precios al consumidor (mensual), Resumen, Precios al Consumidor (INPC)"
CORE = "Índice nacional de precios al consumidor (mensual), Resumen, Subyacente"


def _inegi_zip(rows: list[tuple[str, str, str]], name: str = "conjunto_de_datos") -> str:
    """INEGI's open-data zip as the downloader hands it over: bytes as Latin-1."""
    table = "COBERTURA,PERIODICIDAD,FECHA,CONCEPTO,VALOR,UNIDAD_MEDIDA,ESTATUS\n" + "".join(
        f'Nacional,Mensual,{date},"{concept}",{value},Índice,Cifras definitivas\n'
        for date, concept, value in rows
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{name}/{name}_inpc_mensual.csv", "\ufeff" + table)
        archive.writestr("metadatos/metadatos_inpc.txt", "INPC")
    return buffer.getvalue().decode("latin-1")


ESTAT = (
    "類・品目,総合,生鮮食品を除く総合\n"
    'Group/Item,All items,"All items, less fresh food"\n'
    "類・品目符号(Group/Item code),0001,0161\n"
    "含類総連番(Serial number),001,740\n"
    "ウエイト(Weight),3543757090,3409504328\n"
    "ウエイト１万分比(Weight per 10000),10000,9621\n"
    "202607,102.0,102.1\n"
    "202608,102.2,102.0\n"
)


def test_mexico_and_japan_prices_are_read_from_their_open_files() -> None:
    rows = [
        ("2026-08-01", INPC, "145.462"),
        ("2026-07-01", INPC, "144.9"),
        ("2026-07-01", CORE, "150.1"),
    ]
    mexico = parse_provider(_inegi_zip(rows), "inegi")
    assert list(mexico.index) == [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")]
    assert list(mexico.to_numpy()) == pytest.approx([144.9, 145.462])  # headline only
    japan = parse_provider(ESTAT, "estat")
    assert list(japan.to_numpy()) == pytest.approx([102.0, 102.2])  # the all-items column
    assert japan.index[-1] == pd.Timestamp("2026-08-01")
    assert MarketData(lambda series: ESTAT).refresh("cpi_jpy") is True
    assert SERIES["cpi_mxn"].source_url == "https://www.inegi.org.mx/programas/inpc/2018a/"
    assert SERIES["cpi_jpy"].source_url.startswith("https://www.e-stat.go.jp/")


def test_a_broken_mexican_or_japanese_file_keeps_nothing() -> None:
    good = [("2026-07-01", INPC, "144.9"), ("2026-08-01", INPC, "145.4")]
    broken = [
        _inegi_zip(good + [("2026-08-01", INPC, "145.5")]),  # a month twice
        _inegi_zip(good, name="otra_tabla"),  # no monthly table
        _inegi_zip([("2026-07-01", CORE, "150.1")]),  # no headline rows
        "not a zip",
        ESTAT.replace("202607,102.0", "202608,102.0"),  # a month twice
        ESTAT.replace("類・品目符号(Group/Item code),0001", "Code,9999"),  # no item codes
        ESTAT.replace(",0001,", ",0002,"),  # no all-items column
    ]
    for reply in broken:
        key = "cpi_mxn" if "zip" in reply or "PK" in reply[:2] else "cpi_jpy"
        assert MarketData(lambda series, text=reply: text).refresh(key) is False, reply[:30]


def test_an_inegi_table_too_large_to_open_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = _inegi_zip([("2026-07-01", INPC, "144.9"), ("2026-08-01", INPC, "145.4")])
    monkeypatch.setattr(market_lib, "MAX_BYTES", 100)
    with pytest.raises(ValueError, match="too large"):
        parse_provider(reply, "inegi")


def test_zip_and_shift_jis_replies_arrive_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = {
        "inegi": _inegi_zip([("2026-08-01", INPC, "145.4")]).encode("latin-1"),
        "estat": ESTAT.encode("cp932"),
    }
    asked: list[Any] = []

    class Reply:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.left = [body]

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read1(self, _size: int) -> bytes:
            return self.left.pop() if self.left else b""

    class Opener:
        def open(self, request: Any, timeout: float) -> Reply:
            asked.append(request)
            provider = "inegi" if "inegi.org.mx" in request.full_url else "estat"
            return Reply(replies[provider])

    monkeypatch.setattr(market_lib, "_OPENER", Opener())
    mexico = parse_provider(real_download("INPC", "inegi"), "inegi")
    assert mexico.iloc[-1] == pytest.approx(145.4)
    japan = parse_provider(real_download("000040482943", "estat"), "estat")
    assert japan.iloc[-1] == pytest.approx(102.2)
    inegi, estat = asked
    assert inegi.full_url.startswith("https://www.inegi.org.mx/contenidos/programas/inpc/2018a/")
    assert estat.full_url == (
        "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040482943&fileKind=1"
    )
    assert inegi.get_header("User-agent") == estat.get_header("User-agent") == PROVIDER_AGENT


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_an_account_in_pesos_and_the_yen_row_credit_their_sources(locale: str) -> None:
    inputs, days = _inputs(locale)
    inputs = replace(inputs, account_currency="MXN")
    series = {"cpi_mxn": _monthly(days, 130.0, 136.0)}
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    section = result.in_currencies
    assert section is not None and section["base"] == "MXN" and section["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    assert escape(labels["currency_attrib_MXN"]) in html
    assert "INEGI" in labels["currency_attrib_MXN"]
    assert untranslated(result.model_dump(mode="json")) == []

    dollars, _ = _inputs(locale)
    yen = {
        "fx_jpy": _daily(days, 140.0, 150.0),
        "cpi_jpy": _monthly(days, 100.0, 102.0),
        "cpi": _monthly(days, 300.0, 310.0),
    }
    result = run_audit(dollars, bootstrap_samples=200, risk_samples=300, market=yen.get)
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    name = labels["currency_JPY"]
    assert escape(labels["currency_real_local"].format(name=name)) in html
    assert escape(labels["currency_attrib_JPY"]) in html
    assert "Statistics Bureau" in labels["currency_attrib_JPY"]
    assert untranslated(result.model_dump(mode="json")) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_an_account_in_another_currency_reads_one_period(locale: str) -> None:
    inputs, _ = _inputs(locale)
    inputs = replace(inputs, account_currency="AUD")
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market={}.get)
    assert result.in_currencies is not None
    assert result.in_currencies["reason"] == OTHER_CURRENCY
    html, _ = render(result, watermark=False)
    prefix = LABELS[locale]["currency_not_measured"].split("{reason}")[0]
    line = html.split(escape(prefix), 1)[1].split("<", 1)[0].strip()
    assert line.endswith(".") and not line.endswith(".."), line


def _boc(months: list[str]) -> str:
    rows = "".join(f'"{month}-01","{169.0 + i / 10:.1f}"\n' for i, month in enumerate(months))
    return BOC.split('"date","V41690973"\n')[0] + '"date","V41690973"\n' + rows


YEAR = [f"2025-{m:02d}" for m in range(9, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]


def _kept(first: str) -> tuple[MarketData, list[str], pd.Series]:
    """A service that already holds a good copy of Canada's CPI, then gets ``first``."""
    replies = [first, _boc(YEAR)]
    data = MarketData(lambda series: replies.pop())
    assert data.refresh("cpi_cad") is True
    kept = data.closes("cpi_cad")
    assert kept is not None and len(kept) == len(YEAR)
    return data, replies, kept


def test_a_short_boc_reply_leaves_the_kept_series_in_place() -> None:
    data, _, kept = _kept(_boc(YEAR[:-3]))  # three months short of the kept copy
    assert data.refresh("cpi_cad") is False
    assert data.closes("cpi_cad") is kept


def test_a_boc_reply_with_a_missing_month_is_refused_and_the_kept_copy_stays() -> None:
    holed = [month for month in YEAR if month != "2026-03"]
    assert MarketData(lambda series: _boc(holed)).refresh("cpi_cad") is False
    data, _, kept = _kept(_boc(holed))
    assert data.refresh("cpi_cad") is False
    assert data.closes("cpi_cad") is kept


def test_a_truncated_reply_leaves_the_kept_series_in_place() -> None:
    whole = _boc(YEAR)
    data, _, kept = _kept(whole[: whole.index('"2026-06-01"')])  # the connection cut
    assert data.refresh("cpi_cad") is False
    assert data.closes("cpi_cad") is kept
    # A reply that covers the kept copy and a month more replaces it.
    data, replies, kept = _kept(_boc([*YEAR, "2026-09"]))
    assert data.refresh("cpi_cad") is True
    fresh = data.closes("cpi_cad")
    assert fresh is not None and fresh is not kept and len(fresh) == len(YEAR) + 1


def test_every_monthly_series_must_have_consecutive_months() -> None:
    monthly = [asset for asset in SERIES.values() if asset.monthly]
    assert {asset.key for asset in LOCAL_CPI} <= {asset.key for asset in monthly}
    assert {"cpi", "cash_mxn", "cash_jpy", "cash_chf", "cash_brl"} <= {a.key for a in monthly}
    gap = "DATE,CPIAUCNS\n2024-01-01,300\n2024-03-01,301\n2024-04-01,302\n"
    assert MarketData(lambda series: gap).refresh("cpi") is False
    # October 2025 is the one month BLS never published.
    shutdown = "DATE,CPIAUCNS\n2025-09-01,324\n2025-11-01,325\n2025-12-01,326\n"
    assert MarketData(lambda series: shutdown).refresh("cpi") is True
    assert (
        MarketData(lambda series: ONS.replace('"2026 JUL"', '"2026 JUN"')).refresh("cpi_gbp")
        is False
    )


def test_only_the_publishers_own_gaps_are_allowed_in_a_policy_rate() -> None:
    months = [str(p) for p in pd.period_range("2012-01", "2017-12", freq="M")]
    kept = [m for m in months if not "2013-05" <= m <= "2016-08"]

    def bis(area: str) -> str:
        rows = "".join(f"M,{area},{month},0.05\n" for month in kept)
        return "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n" + rows

    assert MarketData(lambda series: bis("JP")).refresh("cash_jpy") is True
    assert MarketData(lambda series: bis("MX")).refresh("cash_mxn") is False
