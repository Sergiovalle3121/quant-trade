"""The Sharpe after the account currency's own cash rate. Offline: the rates are stubbed."""

from __future__ import annotations

from dataclasses import replace
from html import escape

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit.cashrate import LOCAL, NOTE_LOCAL, local_excess_sharpe
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import CASH, LOCAL_CASH, SERIES, MarketData
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
    # A 3-month rate rolled over four times a year; negative rates stay negative.
    two = np.array([2.0, -0.75])
    chf = LOCAL["CHF"].yearly(two)
    assert chf[0] == pytest.approx((1 + 0.02 * 91 / 360) ** (365 / 91) - 1)
    assert chf[1] < 0
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
    assert out["series"] == "IRSTCI01MXM156N"
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
    negative = MarketData(lambda series: "DATE,X\n2016-01-01,-0.75\n2016-02-01,-0.73\n")
    assert negative.refresh("cash_chf") is True
    closes = negative.closes("cash_chf")
    assert closes is not None and float(closes.iloc[0]) == -0.75
    absurd = MarketData(lambda series: "DATE,X\n2016-01-01,1.2\n2016-02-01,900\n")
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


def test_without_a_usable_local_rate_the_dollar_line_stays() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    bill = _daily(days, 5.0)
    # A euro account whose euro rates start after the history: the bill line.
    late = pd.Series(3.0, index=pd.bdate_range("2023-06-01", periods=200))
    for currency, local in (("EUR", late), ("EUR", None), ("AUD", None), ("USD", None)):
        inputs = _inputs(days, "es", currency)

        def market(key: str, local: pd.Series | None = local) -> pd.Series | None:
            return {"cash_eur": local, CASH.key: bill}.get(key)

        result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
        cash = result.cash_rate
        assert cash is not None and cash["status"] == "MEASURED", currency
        assert cash["series"] == "DTB3" and "currency" not in cash, currency


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


def test_older_euro_dates_take_the_oecd_monthly_rate_and_only_those() -> None:
    days = pd.bdate_range("2018-01-02", "2021-06-30")
    frame = _curve(days, np.full(len(days), 0.0001))
    estr = pd.Series(-0.5, index=pd.bdate_range("2019-10-01", days[-1]))
    oecd = pd.Series(-0.36, index=pd.date_range("2017-01-01", "2021-06-01", freq="MS"))
    assert local_excess_sharpe(frame, estr, 252.0, "EUR")["status"] == "NOT_MEASURED"
    out = local_excess_sharpe(frame, estr, 252.0, "EUR", oecd)
    assert out["status"] == "MEASURED" and out["history_series"] == "IRSTCI01EZM156N"
    assert out["history_source_url"].endswith("IRSTCI01EZM156N")
    # A history that starts after €STR does not name the older series.
    recent = frame[frame["timestamp"] >= pd.Timestamp("2020-01-01", tz="UTC")]
    assert "history_series" not in local_excess_sharpe(recent, estr, 252.0, "EUR", oecd)
    # The mean mixes -0.36 % before October 2019 and -0.5 % after.
    low, high = (float(LOCAL["EUR"].yearly(np.array([v]))[0]) for v in (-0.5, -0.36))
    assert low < out["mean_rate"]["value"] < high
    # €STR still has to be fresh after it starts: a month-long hole is not covered.
    holed = estr[(estr.index < "2020-03-01") | (estr.index > "2020-04-01")]
    assert local_excess_sharpe(frame, holed, 252.0, "EUR", oecd)["status"] == "NOT_MEASURED"


def test_the_engine_reads_the_euro_history_for_an_old_euro_account() -> None:
    days = pd.bdate_range("2018-01-02", "2021-06-30")
    inputs = _inputs(days, "es", "EUR")
    series = {
        "cash_eur": pd.Series(-0.5, index=pd.bdate_range("2019-10-01", days[-1])),
        "cash_eur_history": pd.Series(
            -0.36, index=pd.date_range("2017-01-01", "2021-06-01", freq="MS")
        ),
    }
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    assert result.cash_rate is not None and result.cash_rate["currency"] == "EUR"
    assert result.cash_rate["label"] == "EUR cash rate (FRED ECBESTRVOLWGTTRMDMNRT)"
    html = render(result, watermark=False)[0]
    assert "href='https://fred.stlouisfed.org/series/IRSTCI01EZM156N'" in html
