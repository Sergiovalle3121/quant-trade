"""The Sharpe after what a US Treasury bill paid. Offline: the rates are stubbed."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit.cashrate import NOT_COVERED, excess_sharpe
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import parse_fred_csv
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
    frame["equity"] = 10_000 * np.cumprod(1 + (1.05 ** (spans / 365) - 1) + noise)
    out = excess_sharpe(frame, _rates(days, 5.0), 252.0)
    assert out["status"] == "MEASURED"
    assert abs(out["sharpe_excess"]["value"]) < 0.05
    assert out["mean_rate"]["value"] == pytest.approx(0.05)


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
    assert "5.20%" in html
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
