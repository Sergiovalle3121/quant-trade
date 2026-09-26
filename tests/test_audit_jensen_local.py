"""Jensen's alpha over each side's own cash: a non-dollar account loses its own
currency's cash rate, the dollar benchmark the bill's. Offline: rates are stubbed."""

from __future__ import annotations

from dataclasses import replace
from html import unescape

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit import report
from quant_trade.audit.alpha import CASH_NOTE, LOCAL_CASH_NOTE, NOTE, jensen_alpha
from quant_trade.audit.cashrate import LOCAL, local_span_cash, span_cash
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.market import CASH
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import AuditInputs, DeclaredMetadata, build_inputs, measured

DAYS = pd.bdate_range("2023-01-02", periods=400)
BRL_PERCENT = 12.0
BILL_PERCENT = 5.0


def _stamps(days: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(pd.DatetimeIndex(days).tz_localize("UTC") + pd.Timedelta(hours=21))


def _monthly(days: pd.DatetimeIndex, percent: float) -> pd.Series:
    start = (days[0] - pd.Timedelta(days=31)).to_period("M").to_timestamp()
    return pd.Series(percent, index=pd.date_range(start, days[-1], freq="MS"))


def _daily(days: pd.DatetimeIndex, percent: float) -> pd.Series:
    return pd.Series(percent, index=pd.bdate_range(days[0] - pd.Timedelta(days=30), days[-1]))


def _brl_account(beta: float = 0.2, locale: str = "es") -> tuple[AuditInputs, dict[str, pd.Series]]:
    """A BRL account that holds Brazilian cash plus ``beta`` of a dollar index
    over the bill: no skill at all, in its own currency."""
    stamps = _stamps(DAYS)
    rates = {
        LOCAL["BRL"].asset.key: _monthly(DAYS, BRL_PERCENT),
        CASH.key: _daily(DAYS, BILL_PERCENT),
    }
    own = local_span_cash(stamps, rates[LOCAL["BRL"].asset.key], "BRL")
    bill = span_cash(stamps, rates[CASH.key])
    assert own is not None and bill is not None
    rng = np.random.default_rng(8)
    index = rng.normal(0.0004, 0.01, len(own))
    account = own + beta * (index - bill) + rng.normal(0.0, 0.002, len(own))
    curve = pd.DataFrame(
        {"timestamp": stamps, "equity": 10_000 * np.cumprod(np.r_[1.0, 1.0 + account])}
    )
    benchmark = pd.DataFrame(
        {"timestamp": stamps, "equity": 100 * np.cumprod(np.r_[1.0, 1.0 + index])}
    )
    inputs = build_inputs(
        csv_bytes(curve), DeclaredMetadata(locale=locale), benchmark_bytes=csv_bytes(benchmark)
    )
    return replace(inputs, account_currency="BRL"), rates


def test_the_local_span_cash_reads_the_quote_like_the_local_sharpe() -> None:
    stamps = _stamps(DAYS)
    cash = local_span_cash(stamps, _monthly(DAYS, BRL_PERCENT), "BRL")
    assert cash is not None and len(cash) == len(DAYS) - 1
    spans = np.diff(DAYS.to_numpy()).astype("timedelta64[D]").astype(float)
    assert cash == pytest.approx((1 + BRL_PERCENT / 100) ** (spans / 365) - 1, rel=1e-12)
    # An overnight rate on a 360-day year is rolled over to an annual yield first.
    mxn = local_span_cash(stamps, _monthly(DAYS, 11.0), "MXN")
    yearly = float(LOCAL["MXN"].yearly(np.array([11.0]))[0])
    assert mxn == pytest.approx((1 + yearly) ** (spans / 365) - 1, rel=1e-12)


def test_the_local_span_cash_is_none_when_it_cannot_cover_every_span() -> None:
    stamps = _stamps(DAYS)
    late = pd.Series(BRL_PERCENT, index=pd.date_range("2023-09-01", periods=20, freq="MS"))
    assert local_span_cash(stamps, late, "BRL") is None
    assert local_span_cash(stamps, None, "BRL") is None
    assert local_span_cash(stamps, _monthly(DAYS, 4.0), "AUD") is None
    broken = pd.Series(["x"] * 30, index=pd.date_range("2022-06-01", periods=30, freq="MS"))
    assert local_span_cash(stamps, broken, "BRL") is None


def test_the_euro_history_fills_only_the_days_before_estr() -> None:
    days = pd.bdate_range("2018-01-02", "2021-06-30")
    stamps = _stamps(days)
    estr = pd.Series(-0.5, index=pd.bdate_range("2019-10-01", days[-1]))
    dfr = pd.Series(-0.36, index=pd.date_range("2017-01-01", "2021-06-30", freq="D"))
    assert local_span_cash(stamps, estr, "EUR") is None
    # The ECB's rates are daily: month-start values are too stale for the history.
    monthly = dfr[dfr.index.day == 1]
    assert local_span_cash(stamps, estr, "EUR", {"cash_eur_deposit": monthly}) is None
    cash = local_span_cash(stamps, estr, "EUR", {"cash_eur_deposit": dfr})
    assert cash is not None
    before = np.asarray(stamps.iloc[:-1].dt.tz_localize(None) < pd.Timestamp("2019-10-01"))
    per_day = np.log1p(cash) / np.diff(days.to_numpy()).astype("timedelta64[D]").astype(float)
    older, newer = (float(np.log1p(LOCAL["EUR"].yearly(np.array([v]))[0])) for v in (-0.36, -0.5))
    assert per_day[before] * 365 == pytest.approx(older, rel=1e-9)
    assert per_day[~before] * 365 == pytest.approx(newer, rel=1e-9)


def test_each_side_loses_its_own_cash() -> None:
    rng = np.random.default_rng(2)
    n = 500
    own = np.full(n, 0.12 / 252)
    bill = np.full(n, 0.05 / 252)
    index = rng.normal(0.0004, 0.01, n)
    account = own + 0.2 * (index - bill) + rng.normal(0.0, 0.002, n)
    fair = jensen_alpha(account, index, 252.0, own, bill, "BRL")
    assert fair["alpha"]["note"] == LOCAL_CASH_NOTE and fair["cash_currency"] == "BRL"
    assert abs(fair["alpha"]["value"]) < 0.02
    # The bill on both sides books Brazil's cash premium over the bill as alpha.
    dollar = jensen_alpha(account, index, 252.0, bill)
    assert dollar["alpha"]["note"] == CASH_NOTE and "cash_currency" not in dollar
    assert dollar["alpha"]["value"] > 0.06
    assert jensen_alpha(account, index, 252.0, own, bill[:-1])["status"] == "NOT_MEASURED"


def test_a_brl_account_with_no_skill_shows_no_alpha() -> None:
    inputs, rates = _brl_account()
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, market=rates.get)
    jensen = result.benchmark["jensen"]
    assert jensen["cash_currency"] == "BRL" and jensen["alpha"]["note"] == LOCAL_CASH_NOTE
    assert abs(jensen["alpha"]["value"]) < 0.03
    # The same account read as dollars keeps the bill on both sides, as before.
    dollar = run_audit(
        replace(inputs, account_currency="USD"),
        bootstrap_samples=100,
        risk_samples=200,
        market=rates.get,
    )
    assert dollar.benchmark["jensen"]["alpha"]["note"] == CASH_NOTE
    assert dollar.benchmark["jensen"]["alpha"]["value"] > 0.05


def test_without_the_local_rate_no_cash_comes_off_either_side() -> None:
    # The bill is what dollars paid: taking it off an account in reais would
    # leave Brazil's cash premium over it in the alpha.
    inputs, rates = _brl_account()
    only_bill = {CASH.key: rates[CASH.key]}
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, market=only_bill.get)
    assert result.benchmark["jensen"]["alpha"]["note"] == NOTE
    assert result.benchmark["jensen"]["cash_subtracted"] is False
    assert "cash_currency" not in result.benchmark["jensen"]

    def broken(key: str) -> pd.Series | None:
        if key == LOCAL["BRL"].asset.key:
            raise OSError("down")
        return rates.get(key)

    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, market=broken)
    assert result.benchmark["jensen"]["alpha"]["note"] == NOTE
    # Without the bill neither side loses cash, even with the local rate.
    only_local = {LOCAL["BRL"].asset.key: rates[LOCAL["BRL"].asset.key]}
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, market=only_local.get)
    assert result.benchmark["jensen"]["cash_subtracted"] is False


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_report_names_the_accounts_rate(locale: str) -> None:
    inputs, rates = _brl_account(locale=locale)
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, market=rates.get)
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    text = unescape(html)
    assert labels["alpha_line_local"].split("{alpha}")[0] in text
    assert labels["alpha_line_local"].split("{beta}")[0].split("{name}")[1] in text
    assert labels["cash_rate_BRL"] in text
    assert find_claims(labels["alpha_line_local"]) == []
    assert untranslated(result.model_dump(mode="json")) == []


def test_the_line_falls_back_when_the_currency_has_no_name() -> None:
    labels = report.LABELS["en"]
    block = {
        "status": "MEASURED",
        "alpha": measured(0.01),
        "beta": measured(0.2),
        "alpha_t_stat": measured(0.5),
        "cash_subtracted": True,
        "cash_currency": "XYZ",
        "periods": 300,
    }
    shown = report._alpha_html({"jensen": block}, labels)
    assert "subtracting from both what the 3-month US Treasury bill paid" in shown


def test_the_note_has_spanish_and_portuguese_rules() -> None:
    for locale in ("es", "pt"):
        assert localize(LOCAL_CASH_NOTE, locale) != LOCAL_CASH_NOTE


@pytest.mark.parametrize("currency", ["AUD", "ARS", " ars "])
def test_another_currency_without_a_rate_here_never_loses_the_bill(currency: str) -> None:
    inputs, rates = _brl_account()
    inputs = replace(inputs, account_currency=currency)
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, market=rates.get)
    assert result.benchmark["jensen"]["cash_subtracted"] is False
    assert result.benchmark["jensen"]["alpha"]["note"] == NOTE


@pytest.mark.parametrize("currency", ["USD", "USC", "USDT", "usdc", None])
def test_a_dollar_account_loses_the_bill_on_both_sides(currency: str | None) -> None:
    inputs, rates = _brl_account()
    inputs = replace(inputs, account_currency=currency)
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, market=rates.get)
    assert result.benchmark["jensen"]["alpha"]["note"] == CASH_NOTE
