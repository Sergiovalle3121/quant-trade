"""The Sharpe after the account currency's own cash rate. Offline: the rates are stubbed."""

from __future__ import annotations

from dataclasses import replace
from html import escape

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit.cashrate import LOCAL, NOTE_LOCAL, local_excess_sharpe, local_span_cash
from quant_trade.audit.engine import NO_LOCAL_CASH, run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import CASH, LOCAL_CASH, SERIES, MarketData, parse_rates
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import AuditInputs, DeclaredMetadata, build_inputs


def _curve(days: pd.DatetimeIndex, returns: np.ndarray) -> pd.DataFrame:
    stamps = pd.DatetimeIndex(days).tz_localize("UTC") + pd.Timedelta(hours=21)
    return pd.DataFrame({"timestamp": stamps, "equity": 10_000 * np.cumprod(1 + returns)})


def _daily(days: pd.DatetimeIndex, percent: float) -> pd.Series:
    return pd.Series(percent, index=pd.bdate_range(days[0] - pd.Timedelta(days=30), days[-1]))


def _monthly(days: pd.DatetimeIndex, percent: float) -> pd.Series:
    start = (days[0] - pd.Timedelta(days=31)).to_period("M").to_timestamp()
    return pd.Series(percent, index=pd.date_range(start, days[-1], freq="MS"))


def test_each_quote_becomes_an_annual_yield_by_its_own_convention() -> None:
    ten = np.array([10.0])
    # An overnight rate on a 360-day year, rolled over every day for a year.
    assert LOCAL["MXN"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 360) ** 365 - 1)
    assert LOCAL["GBP"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 365) ** 365 - 1)
    # Brazil's rate is already a compounded annual yield.
    assert LOCAL["BRL"].yearly(ten)[0] == pytest.approx(0.10)
    # The franc's policy rate (SARON's convention) on 360 days, the yen's and
    # CORRA on 365; negative rates stay negative.
    two = np.array([2.0, -0.75])
    chf = LOCAL["CHF"].yearly(two)
    assert chf[0] == pytest.approx((1 + 0.02 / 360) ** 365 - 1)
    assert chf[1] < 0
    assert LOCAL["JPY"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 365) ** 365 - 1)
    assert LOCAL["CAD"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 365) ** 365 - 1)
    assert LOCAL["EUR"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 360) ** 365 - 1)
    assert set(LOCAL) == {asset.label for asset in LOCAL_CASH}


def test_a_strategy_that_earned_the_local_rate_has_no_excess() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    spans = np.r_[0.0, np.diff(days.to_numpy()).astype("timedelta64[D]").astype(float)]
    yearly = float(LOCAL["MXN"].yearly(np.array([11.0]))[0])
    noise = np.random.default_rng(1).normal(0, 1e-4, len(days))
    noise -= noise[1:].mean()
    frame = _curve(days, (1 + yearly) ** (spans / 365) - 1 + noise)
    out = local_excess_sharpe(frame, _monthly(days, 11.0), 252.0, "MXN")
    assert out["status"] == "MEASURED" and out["currency"] == "MXN"
    assert out["series"] == "MX" and out["source_name"] == "BIS"
    assert out["source_url"] == "https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.MX"
    assert abs(out["sharpe_excess"]["value"]) < 0.05
    assert out["mean_rate"]["value"] == pytest.approx(yearly)
    assert out["sharpe_excess"]["note"] == NOTE_LOCAL


def test_a_monthly_rate_too_old_or_values_out_of_bounds_are_not_used() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    frame = _curve(days, np.full(len(days), 0.0004))
    early = pd.Series(11.0, index=pd.date_range("2022-01-01", "2023-06-01", freq="MS"))
    assert local_excess_sharpe(frame, early, 252.0, "MXN")["status"] == "NOT_MEASURED"
    broken = pd.Series(["x"] * 20, index=pd.date_range("2022-06-01", periods=20, freq="MS"))
    assert local_excess_sharpe(frame, broken, 252.0, "MXN")["status"] == "NOT_MEASURED"
    huge = _monthly(days, 1e6)
    assert local_excess_sharpe(frame, huge, 252.0, "MXN")["status"] == "NOT_MEASURED"


def test_local_series_keep_negative_rates_and_refuse_absurd_ones() -> None:
    assert all(asset.key in SERIES for asset in LOCAL_CASH)
    negative = MarketData(lambda series: _bis("CH", [("2016-01", "-0.75"), ("2016-02", "-0.75")]))
    assert negative.refresh("cash_chf") is True
    closes = negative.closes("cash_chf")
    assert closes is not None and float(closes.iloc[0]) == -0.75
    absurd = MarketData(lambda series: _bis("MX", [("2016-01", "1.2"), ("2016-02", "900")]))
    assert absurd.refresh("cash_mxn") is False
    # The US bill keeps dropping values below zero, as before.
    bill = MarketData(
        lambda series: "DATE,DTB3\n2016-01-04,-0.01\n2016-01-05,0.2\n2016-01-06,0.3\n"
    )
    assert bill.refresh(CASH.key) is True
    kept = bill.closes(CASH.key)
    assert kept is not None and bool((kept >= 0).all())


def _inputs(days: pd.DatetimeIndex, locale: str, currency: str | None) -> AuditInputs:
    returns = np.random.default_rng(3).normal(0.0006, 0.005, len(days))
    inputs = build_inputs(csv_bytes(_curve(days, returns)), DeclaredMetadata(locale=locale))
    return replace(inputs, account_currency=currency)


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_a_euro_account_subtracts_the_euro_rate(locale: str) -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    inputs = _inputs(days, locale, "EUR")

    def market(key: str) -> pd.Series | None:
        return {"cash_eur": _daily(days, -0.4), CASH.key: _daily(days, 5.0)}.get(key)

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
    cash = result.cash_rate
    assert cash is not None and cash["status"] == "MEASURED" and cash["currency"] == "EUR"
    assert cash["mean_rate"]["value"] < 0
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    assert escape(labels["cash_rate_EUR"]) in html
    assert labels["cash_note_local"].split("{code}")[0] in html
    for key, text in labels.items():
        if key.startswith(
            ("cash_rate_", "cash_sharpe_local", "cash_below_local", "cash_note_local")
        ):
            assert find_claims(text) == [], key
    assert untranslated(result.model_dump(mode="json")) == []


def test_without_a_usable_local_rate_only_a_dollar_account_gets_the_bill_line() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    bill = _daily(days, 5.0)
    late = pd.Series(3.0, index=pd.bdate_range("2023-06-01", periods=200))
    for currency, local in (("USD", None), ("USC", None), ("usdt", None), (None, None)):
        inputs = _inputs(days, "es", currency)

        def market(key: str, local: pd.Series | None = local) -> pd.Series | None:
            return {"cash_eur": local, CASH.key: bill}.get(key)

        result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
        cash = result.cash_rate
        assert cash is not None and cash["status"] == "MEASURED", currency
        assert cash["series"] == "DTB3" and "currency" not in cash, currency
    # A euro account whose euro rates start after the history, or none, and a
    # currency with no rate here: the bill is not what their cash paid.
    for currency, local in (("EUR", late), ("EUR", None), ("AUD", None), ("ars", None)):
        inputs = _inputs(days, "es", currency)

        def other(key: str, local: pd.Series | None = local) -> pd.Series | None:
            return {"cash_eur": local, CASH.key: bill}.get(key)

        result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=other)
        cash = result.cash_rate
        assert cash is not None and cash["status"] == "NOT_MEASURED", currency
        assert cash["reason"] == NO_LOCAL_CASH and cash["currency"] == currency.upper()
        assert untranslated(result.model_dump(mode="json")) == []
        page, _ = render(result, watermark=False)
        assert LABELS["es"]["cash_sharpe"].split("{")[0] not in page


def test_a_broken_local_series_never_stops_the_audit() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    inputs = _inputs(days, "es", "GBP")

    def market(key: str) -> pd.Series | None:
        if key == "cash_gbp":
            raise OSError("down")
        return None

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
    assert result.cash_rate is not None and result.cash_rate["status"] == "NOT_MEASURED"
    assert untranslated(result.model_dump(mode="json")) == []


def _ecb(instrument: str, rows: list[tuple[str, str]]) -> str:
    """An ECB FM daily series (``csvdata``, ``detail=dataonly``), as its API sends it."""
    key = f"FM.D.U2.EUR.4F.KR.{instrument}.LEV"
    head = (
        "KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,"
        "TIME_PERIOD,OBS_VALUE\n"
    )
    body = "".join(f"{key},D,U2,EUR,4F,KR,{instrument},LEV,{day},{v}\n" for day, v in rows)
    return head + body


def _each_day(first: str, last: str, value: str) -> list[tuple[str, str]]:
    return [(day.strftime("%Y-%m-%d"), value) for day in pd.date_range(first, last)]


def _euro_history(first: str = "1999-01-01", last: str = "2021-06-30") -> dict[str, pd.Series]:
    """The three ECB series before €STR, parsed from replies in the ECB's shape:
    the MRO fixed rate at 4.25 (it has no values in the variable-rate tender
    years), the minimum bid rate at 3.25 only in those years, the deposit rate
    at 2.0 throughout."""
    fixed = _each_day(first, "2000-06-27", "4.25") + _each_day("2008-10-15", last, "4.25")
    replies = {
        "cash_eur_mro": ("MRR_FR", fixed),
        "cash_eur_mro_bid": ("MRR_MBR", _each_day("2000-06-28", "2008-10-14", "3.25")),
        "cash_eur_deposit": ("DFR", _each_day(first, last, "2.0")),
    }
    return {
        key: parse_rates(_ecb(code, rows), "ecb", f"D.U2.EUR.4F.KR.{code}.LEV")
        for key, (code, rows) in replies.items()
    }


def _yearly(percent: float) -> float:
    return float(LOCAL["EUR"].yearly(np.array([percent]))[0])


def test_older_euro_dates_take_the_mro_until_october_2008_then_the_deposit_rate() -> None:
    history = _euro_history()
    estr = pd.Series(-0.5, index=pd.bdate_range("2019-10-01", "2021-06-30"))
    # Each era alone takes its own ECB rate (the curve's returns are flat, so the
    # mean rate is the rate of the span starts).
    for first, last, percent, used in (
        ("1999-02-01", "2000-06-26", 4.25, ["MRR_FR"]),
        ("2000-06-28", "2008-10-10", 3.25, ["MRR_MBR"]),
        ("2008-10-15", "2019-09-27", 2.0, ["DFR"]),
    ):
        days = pd.bdate_range(first, last)
        out = local_excess_sharpe(
            _curve(days, np.full(len(days), 0.0001)), estr, 252.0, "EUR", history
        )
        assert out["status"] == "MEASURED", first
        assert out["mean_rate"]["value"] == pytest.approx(_yearly(percent)), first
        assert [item["series"].split(".")[-2] for item in out["history_sources"]] == used
    # The cut-overs: 27 June 2000 is the fixed rate, 28 June the minimum bid;
    # 14 October 2008 the minimum bid, 15 October the deposit rate; 30 September
    # 2019 the deposit rate, 1 October €STR.
    for day, percent in (
        ("2000-06-27", 4.25),
        ("2000-06-28", 3.25),
        ("2008-10-14", 3.25),
        ("2008-10-15", 2.0),
        ("2019-09-30", 2.0),
        ("2019-10-01", -0.5),
    ):
        stamps = pd.Series(pd.date_range(day, periods=2, freq="D", tz="UTC"))
        cash = local_span_cash(stamps, estr, "EUR", history)
        assert cash is not None and cash[0] == pytest.approx(
            (1 + _yearly(percent)) ** (1 / 365) - 1
        ), day
    # A span from 1999 to 2021 names all three, oldest first, and links each.
    days = pd.bdate_range("1999-02-01", "2021-06-30", freq="W-FRI")
    whole = local_excess_sharpe(_curve(days, np.full(len(days), 0.001)), estr, 52.0, "EUR", history)
    assert whole["status"] == "MEASURED"
    assert [item["source_url"] for item in whole["history_sources"]] == [
        f"https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.{code}.LEV"
        for code in ("MRR_FR", "MRR_MBR", "DFR")
    ]
    assert {item["source_name"] for item in whole["history_sources"]} == {"ECB"}
    assert _yearly(-0.5) < whole["mean_rate"]["value"] < _yearly(4.25)


def test_the_euro_history_is_held_to_the_daily_staleness_limit() -> None:
    history = _euro_history()
    estr = pd.Series(-0.5, index=pd.bdate_range("2019-10-01", "2021-06-30"))
    days = pd.bdate_range("2004-01-02", "2004-12-31")
    frame = _curve(days, np.full(len(days), 0.0001))
    assert local_excess_sharpe(frame, estr, 252.0, "EUR", history)["status"] == "MEASURED"
    # Without the minimum bid rate, the tender years are not covered: the fixed
    # rate's last value (June 2000) is far older than ten days.
    no_bid = {**history, "cash_eur_mro_bid": None}
    assert local_excess_sharpe(frame, estr, 252.0, "EUR", no_bid)["status"] == "NOT_MEASURED"
    # Nor are they filled by the deposit rate, which is only used from October 2008.
    only_dfr = {"cash_eur_deposit": history["cash_eur_deposit"]}
    assert local_excess_sharpe(frame, estr, 252.0, "EUR", only_dfr)["status"] == "NOT_MEASURED"
    # A three-week hole in the minimum bid rate is past the daily limit (the
    # monthly 75 days no longer applies to the euro's history).
    bid = history["cash_eur_mro_bid"]
    holed = {
        **history,
        "cash_eur_mro_bid": bid[(bid.index < "2004-05-01") | (bid.index > "2004-05-21")],
    }
    assert local_excess_sharpe(frame, estr, 252.0, "EUR", holed)["status"] == "NOT_MEASURED"
    # Ten days old is still covered.
    short = {
        **history,
        "cash_eur_mro_bid": bid[(bid.index < "2004-05-01") | (bid.index > "2004-05-09")],
    }
    assert local_excess_sharpe(frame, estr, 252.0, "EUR", short)["status"] == "MEASURED"
    # A history that starts after €STR does not name the older series, and
    # €STR still has to be fresh after it starts.
    recent = pd.bdate_range("2020-01-02", "2021-06-30")
    later = _curve(recent, np.full(len(recent), 0.0001))
    assert "history_sources" not in local_excess_sharpe(later, estr, 252.0, "EUR", history)
    gap = estr[(estr.index < "2020-03-01") | (estr.index > "2020-04-01")]
    assert local_excess_sharpe(later, gap, 252.0, "EUR", history)["status"] == "NOT_MEASURED"


def test_the_engine_reads_the_euro_history_for_an_old_euro_account() -> None:
    days = pd.bdate_range("2007-01-02", "2021-06-30")
    inputs = _inputs(days, "es", "EUR")
    series = {
        "cash_eur": pd.Series(-0.5, index=pd.bdate_range("2019-10-01", days[-1])),
        **_euro_history("2006-01-01"),
    }
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    assert result.cash_rate is not None and result.cash_rate["currency"] == "EUR"
    assert result.cash_rate["label"] == "EUR cash rate (FRED ECBESTRVOLWGTTRMDMNRT)"
    html = render(result, watermark=False)[0]
    for code in ("MRR_MBR", "DFR"):
        ecb = f"https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.{code}.LEV"
        assert f"href='{ecb}' rel='noopener'>ECB {code}</a>" in html
    assert "MRR_FR.LEV" not in html
    assert "IRSTCI01" not in html
    assert_report_clean(html)


def _bis(area: str, rows: list[tuple[str, str]]) -> str:
    """The BIS's policy-rate CSV (``detail=dataonly``), as its API sends it."""
    body = "".join(f"M,{area},{month},{value}\n" for month, value in rows)
    return "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n" + body


#: A few rows of each source, in the shape each one sends (read 2026-09-26).
BCB_4189 = (
    '[{"data":"01/06/1994","valor":"13532.65"},{"data":"01/01/1995","valor":"46.25"},'
    '{"data":"01/02/1995","valor":"56.54"},{"data":"01/08/2026","valor":"13.94"},'
    '{"data":"01/09/2026","valor":"13.80"}]'
)
BOC_CORRA = (
    '\ufeff"TERMS AND CONDITIONS"\n"https://www.bankofcanada.ca/terms/"\n\n"SERIES"\n'
    '"id","label","description"\n"AVG.INTWO","Canadian Overnight Repo Rate Average (CORRA) (%)",'
    '"Canadian Overnight Repo Rate Average (CORRA) (%)"\n\n"OBSERVATIONS"\n'
    '"date","AVG.INTWO"\n"2026-09-22","2.2900"\n"2026-09-23","2.2900"\n"2026-09-24","2.3000"\n'
)
ECB_DFR = _ecb("DFR", [("2019-09-17", "-0.4"), ("2019-09-18", "-0.5"), ("2019-09-19", "-0.5")])
#: The MRO fixed rate stops on 27 June 2000 and resumes on 15 October 2008;
#: the minimum bid rate covers only the days between.
ECB_MRR_FR = _ecb(
    "MRR_FR",
    [
        ("2000-06-26", "4.25"),
        ("2000-06-27", "4.25"),
        ("2008-10-15", "3.75"),
        ("2008-10-16", "3.75"),
    ],
)
ECB_MRR_MBR = _ecb(
    "MRR_MBR",
    [
        ("2000-06-28", "4.25"),
        ("2000-06-29", "4.25"),
        ("2008-10-13", "4.25"),
        ("2008-10-14", "4.25"),
    ],
)


def test_each_new_source_is_read_in_its_own_shape() -> None:
    selic = parse_rates(BCB_4189, "bcb_rate", "4189")
    # Before the Real plan (1995) the monthly Selic ran in the thousands a year.
    assert list(selic) == [46.25, 56.54, 13.94, 13.80]
    assert selic.index[0] == pd.Timestamp("1995-01-01")
    corra = parse_rates(BOC_CORRA, "boc_rate", "AVG.INTWO")
    assert list(corra) == [2.29, 2.29, 2.30] and corra.index[-1] == pd.Timestamp("2026-09-24")
    dfr = parse_rates(ECB_DFR, "ecb", "D.U2.EUR.4F.KR.DFR.LEV")
    assert list(dfr) == [-0.4, -0.5, -0.5]
    fixed = parse_rates(ECB_MRR_FR, "ecb", "D.U2.EUR.4F.KR.MRR_FR.LEV")
    assert list(fixed.index.strftime("%Y-%m-%d")) == [
        "2000-06-26",
        "2000-06-27",
        "2008-10-15",
        "2008-10-16",
    ]
    bid = parse_rates(ECB_MRR_MBR, "ecb", "D.U2.EUR.4F.KR.MRR_MBR.LEV")
    assert list(bid) == [4.25] * 4 and bid.index[-1] == pd.Timestamp("2008-10-14")
    # A BIS month's value stands at its last day, not at the start of the month.
    jpy = parse_rates(_bis("JP", [("2016-08", "-0.1"), ("2016-09", "-0.1")]), "bis", "JP")
    assert list(jpy.index) == [pd.Timestamp("2016-08-31"), pd.Timestamp("2016-09-30")]
    for key, text in (
        (
            "cash_brl",
            BCB_4189.replace(',{"data":"01/08/2026","valor":"13.94"}', "").replace(
                ',{"data":"01/09/2026","valor":"13.80"}', ""
            ),
        ),
        ("cash_cad", BOC_CORRA),
        ("cash_eur_deposit", ECB_DFR),
        ("cash_eur_mro", ECB_MRR_FR),
        ("cash_eur_mro_bid", ECB_MRR_MBR),
        ("cash_jpy", _bis("JP", [("2026-07", "1"), ("2026-08", "1")])),
    ):
        data = MarketData(lambda series, text=text: text)
        assert data.refresh(key) is True, key


def test_a_broken_reply_from_a_new_source_is_refused() -> None:
    twice = _bis("MX", [("2026-07", "6.5"), ("2026-07", "6.75")])
    other = _bis("BR", [("2026-07", "14.25"), ("2026-08", "14")])
    blank = _bis("CH", [("2026-07", "0"), ("2026-08", "NaN")])
    for text in (twice, other, blank, "<html>busy</html>"):
        assert MarketData(lambda series, text=text: text).refresh("cash_mxn") is False
    # Each ECB series refuses a reply for another one (the fixed rate for the
    # deposit rate, the minimum bid for the fixed rate), a repeated day and a blank.
    for key, text in (
        ("cash_eur_deposit", ECB_MRR_FR),
        ("cash_eur_mro", ECB_MRR_MBR),
        ("cash_eur_mro_bid", ECB_MRR_MBR.replace("2008-10-13", "2008-10-14")),
        ("cash_eur_mro", ECB_MRR_FR.replace("2008-10-16,3.75", "2008-10-16,")),
    ):
        assert MarketData(lambda series, text=text: text).refresh(key) is False, key
    unreadable = BOC_CORRA.replace('"2026-09-23","2.2900"', '"2026-09-23","n/a"')
    assert MarketData(lambda series: unreadable).refresh("cash_cad") is False
    with pytest.raises(ValueError):
        parse_rates("[]", "bcb_rate", "4189")
    with pytest.raises(ValueError):
        parse_rates(BOC_CORRA, "boc_rate", "V39079")


def test_japan_has_no_policy_rate_from_2013_to_2016_so_those_dates_are_not_covered() -> None:
    months = [f"{y}-{m:02d}" for y in range(2012, 2018) for m in range(1, 13)]
    kept = [m for m in months if not ("2013-05" <= m <= "2016-08")]
    rates = parse_rates(_bis("JP", [(m, "0.05") for m in kept]), "bis", "JP")
    inside = pd.bdate_range("2014-01-02", periods=300)
    out = local_excess_sharpe(_curve(inside, np.full(300, 0.0002)), rates, 252.0, "JPY")
    assert out["status"] == "NOT_MEASURED"
    after = pd.bdate_range("2016-10-03", periods=250)
    out = local_excess_sharpe(_curve(after, np.full(250, 0.0002)), rates, 252.0, "JPY")
    assert out["status"] == "MEASURED" and out["source_name"] == "BIS"
