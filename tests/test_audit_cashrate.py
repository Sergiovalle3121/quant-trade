"""The Sharpe after what a US Treasury bill paid. Offline: the rates are stubbed."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit.cashrate import NOT_COVERED, UNAVAILABLE, annual_yield, excess_sharpe
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import MarketData, parse_fred_csv
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs


def _curve(days: pd.DatetimeIndex, returns: np.ndarray) -> pd.DataFrame:
    stamps = pd.DatetimeIndex(days).tz_localize("UTC") + pd.Timedelta(hours=21)
    return pd.DataFrame({"timestamp": stamps, "equity": 10_000 * np.cumprod(1 + returns)})


def _rates(days: pd.DatetimeIndex, percent: float) -> pd.Series:
    return pd.Series(percent, index=pd.bdate_range(days[0] - pd.Timedelta(days=30), days[-1]))


def test_a_strategy_that_earned_the_bill_rate_has_no_excess() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    frame = _curve(days, np.zeros(len(days)))
    spans = np.r_[0.0, np.diff(days.to_numpy()).astype("timedelta64[D]").astype(float)]
    # Exactly the bill's 5 % a year over each stretch, plus a little noise.
    noise = np.random.default_rng(1).normal(0, 1e-4, len(days))
    noise -= noise[1:].mean()  # the returns after the first carry no edge over the bill
    bill = float(annual_yield(np.array([0.05]))[0])
    frame["equity"] = 10_000 * np.cumprod(1 + ((1 + bill) ** (spans / 365) - 1) + noise)
    out = excess_sharpe(frame, _rates(days, 5.0), 252.0)
    assert out["status"] == "MEASURED"
    assert abs(out["sharpe_excess"]["value"]) < 0.05
    assert out["mean_rate"]["value"] == pytest.approx(0.05234, abs=1e-4)


def test_the_bill_rate_lowers_the_sharpe_and_zero_rates_change_nothing() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    returns = np.random.default_rng(2).normal(0.0006, 0.005, len(days))
    frame = _curve(days, returns)
    plain = returns[1:].mean() / returns[1:].std(ddof=1) * np.sqrt(252)
    at_zero = excess_sharpe(frame, _rates(days, 0.0), 252.0)
    assert at_zero["sharpe_excess"]["value"] == pytest.approx(plain)
    at_five = excess_sharpe(frame, _rates(days, 5.0), 252.0)
    assert at_five["sharpe_excess"]["value"] < plain - 0.4


def test_rates_that_do_not_cover_the_history_are_not_measured() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    frame = _curve(days, np.full(len(days), 0.001))
    late = pd.Series(4.0, index=pd.bdate_range("2023-06-01", periods=200))
    assert excess_sharpe(frame, late, 252.0)["reason"] == NOT_COVERED


def test_a_rate_series_keeps_its_zeros() -> None:
    text = "DATE,DTB3\n2014-01-02,0.00\n2014-01-03,0.01\n2014-01-06,.\n"
    assert list(parse_fred_csv(text, rate=True)) == [0.0, 0.01]
    assert list(parse_fred_csv(text)) == [0.01]


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_report_shows_it_under_the_tiles(locale: str) -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    frame = _curve(days, np.random.default_rng(3).normal(0.0008, 0.006, len(days)))
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale=locale))

    def market(key: str) -> pd.Series | None:
        return _rates(days, 5.2) if key == "tbill3m" else None

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
    assert result.cash_rate is not None and result.cash_rate["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert "href='https://fred.stlouisfed.org/series/DTB3'" in html
    assert LABELS[locale]["cash_sharpe"].split("(")[0] in html
    assert LABELS[locale]["cash_note"].split(".")[0] in html
    for key in ("cash_sharpe", "cash_below", "cash_note"):
        assert find_claims(LABELS[locale][key]) == [], key
    assert f"{float(annual_yield(np.array([0.052]))[0]):.2%}" in html  # 5.45 %, the yield
    assert find_claims(LABELS[locale]["cash_sharpe"]) == []
    assert untranslated(result.model_dump(mode="json")) == []
    # Without public data, nothing is asked and nothing is shown.
    plain = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert plain.cash_rate is None
    assert LABELS[locale]["cash_sharpe"].split("(")[0] not in render(plain, watermark=False)[0]


def test_bill_rates_down_is_not_measured_and_hidden() -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    frame = _curve(days, np.random.default_rng(4).normal(0.0008, 0.006, len(days)))
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale="es"))

    def broken(key: str) -> pd.Series:
        raise OSError("down")

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=broken)
    assert result.cash_rate is not None and result.cash_rate["status"] == "NOT_MEASURED"
    assert untranslated(result.model_dump(mode="json")) == []
    assert LABELS["es"]["cash_sharpe"].split("(")[0] not in render(result, watermark=False)[0]


def test_the_discount_rate_becomes_the_bills_annual_yield() -> None:
    """A constant 5 % DTB3 compounds to 1.05234 over 365 daily spans."""
    days = pd.date_range("2023-01-01", periods=366, freq="D")
    rates = pd.Series(5.0, index=days)
    growth = 1.0
    bill = float(annual_yield(np.array([0.05]))[0])
    for _ in range(365):
        growth *= (1.0 + bill) ** (1.0 / 365.0)
    assert growth == pytest.approx(1.05234, abs=1e-4)
    frame = _curve(days, np.zeros(len(days)))
    frame["equity"] = 10_000 * np.cumprod(np.r_[1.0, np.full(365, (1 + bill) ** (1 / 365))])
    out = excess_sharpe(frame, rates, 365.0)
    assert out["mean_rate"]["value"] == pytest.approx(0.05234, abs=1e-4)


def test_a_rate_reply_out_of_range_counts_as_unavailable() -> None:
    for bad in ("99999", "1e300"):
        text = f"DATE,DTB3\n2024-01-02,5.1\n2024-01-03,{bad}\n2024-01-04,5.2\n"
        data = MarketData(lambda series, text=text: text)
        assert data.refresh("tbill3m") is False and data.closes("tbill3m") is None
    good = MarketData(lambda series: "DATE,DTB3\n2024-01-02,5.1\n2024-01-03,5.2\n")
    assert good.refresh("tbill3m") is True


@pytest.mark.parametrize("locale", ["es", "en"])
def test_a_curve_that_earned_less_than_cash_says_so_in_words(locale: str) -> None:
    """A low-volatility curve below the bill rate: no -50 Sharpe, a plain sentence."""
    days = pd.bdate_range("2023-01-02", periods=300)
    rng = np.random.default_rng(5)
    frame = _curve(days, rng.normal(0.00005, 0.0003, len(days)))
    out = excess_sharpe(frame, _rates(days, 5.0), 252.0)
    assert out["below_cash"] is True
    assert out["sharpe_excess"]["value"] < -3
    assert out["strategy_yearly"]["value"] < out["mean_rate"]["value"]
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale=locale))
    result = run_audit(
        inputs,
        bootstrap_samples=200,
        risk_samples=300,
        market=lambda k: _rates(days, 5.0) if k == "tbill3m" else None,
    )
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    assert labels["cash_below"].split("(")[0] in html
    assert labels["cash_sharpe"].split("(")[0] not in html
    assert f"{result.cash_rate['sharpe_excess']['value']:.2f}" not in html  # type: ignore[index]
    assert untranslated(result.model_dump(mode="json")) == []


def _bad_series(days: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Replies a broken download or cache could give instead of rates."""
    index = pd.bdate_range(days[0] - pd.Timedelta(days=30), days[-1])
    mixed: list[object] = [5.0 if i % 2 == 0 else "n/a" for i in range(len(index))]
    return {
        "text": pd.Series("n/a", index=index),
        "text_index": pd.Series(5.0, index=[str(day.date()) + "x" for day in index]),
        "mixed": pd.Series(mixed, index=index),
        "infinite": pd.Series(np.inf, index=index),
        "huge": pd.Series(1e300, index=index),
    }


@pytest.mark.parametrize("kind", ["text", "text_index", "mixed", "infinite", "huge"])
def test_a_malformed_rate_series_skips_the_cash_line_never_the_audit(kind: str) -> None:
    days = pd.bdate_range("2023-01-02", periods=300)
    frame = _curve(days, np.random.default_rng(5).normal(0.0008, 0.006, len(days)))
    bench = _curve(days, np.random.default_rng(6).normal(0.0005, 0.008, len(days)))
    inputs = build_inputs(
        csv_bytes(frame), DeclaredMetadata(locale="es"), benchmark_bytes=csv_bytes(bench)
    )
    bad = _bad_series(days)[kind]

    def market(key: str) -> pd.Series | None:
        return bad if key == "tbill3m" else None

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
    assert result.cash_rate is not None
    if kind == "mixed":
        # Every other day still has a rate: the readable ones are used.
        assert result.cash_rate["status"] == "MEASURED"
    else:
        assert result.cash_rate["status"] == "NOT_MEASURED"
        assert result.cash_rate["reason"] == UNAVAILABLE
    assert result.benchmark is not None
    assert result.benchmark["jensen"]["status"] == "MEASURED"
    assert result.benchmark["jensen"]["cash_subtracted"] is (kind == "mixed")
    assert untranslated(result.model_dump(mode="json")) == []
