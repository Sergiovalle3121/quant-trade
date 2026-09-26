"""Returns split by calm and turbulent markets (the VIX). Offline: the VIX is stubbed."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import SERIES, MarketData
from quant_trade.audit.regime import (
    CLEAR_GAP,
    FEW_TURBULENT,
    MONTH_DAYS,
    NOT_COVERED,
    SHORT,
    TURBULENT_AT,
    by_vix,
)
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

KEYS = (
    "regime",
    "regime_intro",
    "regime_not_measured",
    "regime_better_calm",
    "regime_better_turbulent",
    "regime_no_clear_gap",
    "regime_source",
)


def _curve(days: pd.DatetimeIndex, returns: np.ndarray) -> pd.DataFrame:
    stamps = pd.DatetimeIndex(days).tz_localize("UTC") + pd.Timedelta(hours=21)
    return pd.DataFrame({"timestamp": stamps, "equity": 10_000 * np.cumprod(1 + returns)})


def _vix(days: pd.DatetimeIndex, levels: np.ndarray) -> pd.Series:
    """VIX closes on the curve's days, plus a calm month before it starts."""
    before = pd.bdate_range(days[0] - pd.Timedelta(days=30), days[0] - pd.Timedelta(days=1))
    return pd.concat([pd.Series(15.0, index=before), pd.Series(levels, index=days)])


def _blocks(n: int) -> np.ndarray:
    """Alternating 20-day stretches of calm (15) and turbulent (30) closes."""
    return np.where((np.arange(n) // 20) % 2 == 0, 15.0, 30.0)


def test_a_strategy_that_loses_when_fear_rises_is_split_that_way() -> None:
    days = pd.bdate_range("2022-01-03", periods=400)
    levels = _blocks(len(days))
    rng = np.random.default_rng(1)
    # The return on day i starts at day i - 1, placed by the close of day i - 2.
    known = np.r_[15.0, 15.0, levels[:-2]]
    returns = np.where(known >= TURBULENT_AT, -0.002, 0.002) + rng.normal(0, 0.004, len(days))
    returns[0] = 0.0
    out = by_vix(_curve(days, returns), _vix(days, levels), 252.0)
    assert out["status"] == "MEASURED"
    calm, turbulent = out["calm"], out["turbulent"]
    assert calm["returns"]["value"] + turbulent["returns"]["value"] == len(days) - 1
    assert calm["time_share"]["value"] + turbulent["time_share"]["value"] == pytest.approx(1.0)
    assert 0.4 < turbulent["time_share"]["value"] < 0.6
    assert calm["monthly_return"]["value"] > 0 > turbulent["monthly_return"]["value"]
    assert calm["sharpe"]["value"] > 0 > turbulent["sharpe"]["value"]
    assert out["gap_in_se"]["value"] > CLEAR_GAP


def test_the_regime_is_the_one_known_before_the_return_started() -> None:
    """A turbulent close on one day places only the return that starts after it."""
    days = pd.bdate_range("2022-01-03", periods=200)
    levels = np.full(len(days), 15.0)
    levels[100:130] = 40.0  # 30 turbulent closes
    returns = np.full(len(days), 0.001)
    returns[0] = 0.0
    out = by_vix(_curve(days, returns), _vix(days, levels), 252.0)
    assert out["turbulent"]["returns"]["value"] == 30
    # Mark the returns that start on a turbulent close's day: none of them is counted
    # as turbulent, because that close was not known when they started.
    returns[101] = 0.05  # starts on day 100, the first turbulent close
    first = by_vix(_curve(days, returns), _vix(days, levels), 252.0)
    assert first["calm"]["monthly_return"]["value"] > out["calm"]["monthly_return"]["value"]


def test_the_monthly_return_compounds_over_each_regimes_days() -> None:
    days = pd.date_range("2023-01-01", periods=240, freq="D")
    levels = _blocks(len(days))
    returns = np.full(len(days), 0.001)
    returns[0] = 0.0
    out = by_vix(_curve(days, returns), _vix(days, levels), 365.0)
    expected = 1.001**MONTH_DAYS - 1
    assert out["calm"]["monthly_return"]["value"] == pytest.approx(expected)
    assert out["turbulent"]["monthly_return"]["value"] == pytest.approx(expected)
    assert "sharpe" not in out["calm"]  # a flat series has no Sharpe
    assert "gap_in_se" not in out


def test_equal_regimes_rarely_read_as_different() -> None:
    days = pd.bdate_range("2022-01-03", periods=300)
    levels = _blocks(len(days))
    vix = _vix(days, levels)
    rng = np.random.default_rng(7)
    hits = 0
    for _ in range(200):
        returns = rng.normal(0.0005, 0.01, len(days))
        returns[0] = 0.0
        out = by_vix(_curve(days, returns), vix, 252.0)
        hits += abs(out["gap_in_se"]["value"]) >= CLEAR_GAP
    assert hits / 200 < 0.1


def test_too_few_turbulent_returns_uncovered_or_short_histories_are_not_measured() -> None:
    days = pd.bdate_range("2022-01-03", periods=300)
    returns = np.random.default_rng(2).normal(0.0005, 0.01, len(days))
    frame = _curve(days, returns)
    calm_only = np.full(len(days), 15.0)
    calm_only[:10] = 30.0
    assert by_vix(frame, _vix(days, calm_only), 252.0)["reason"] == FEW_TURBULENT
    late = pd.Series(15.0, index=pd.bdate_range("2022-06-01", periods=200))
    assert by_vix(frame, late, 252.0)["reason"] == NOT_COVERED
    short = _curve(days[:50], returns[:50])
    assert by_vix(short, _vix(days, _blocks(len(days))), 252.0)["reason"] == SHORT


def test_a_vix_reply_out_of_range_counts_as_unavailable() -> None:
    assert "vix" in SERIES
    bad = MarketData(lambda series: "DATE,VIXCLS\n2024-01-02,13.2\n2024-01-03,99999\n")
    assert bad.refresh("vix") is False and bad.closes("vix") is None
    good = MarketData(lambda series: "DATE,VIXCLS\n2020-03-16,82.69\n2020-03-17,75.91\n")
    assert good.refresh("vix") is True


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_report_shows_the_split(locale: str) -> None:
    days = pd.bdate_range("2022-01-03", periods=400)
    levels = _blocks(len(days))
    known = np.r_[15.0, 15.0, levels[:-2]]
    rng = np.random.default_rng(3)
    returns = np.where(known >= TURBULENT_AT, 0.003, 0.0) + rng.normal(0, 0.004, len(days))
    frame = _curve(days, returns)
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale=locale))

    def market(key: str) -> pd.Series | None:
        return _vix(days, levels) if key == "vix" else None

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
    assert result.vix_regime is not None and result.vix_regime["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    assert "href='https://fred.stlouisfed.org/series/VIXCLS'" in html
    assert labels["regime"] in html
    assert labels["regime_better_turbulent"].split(":")[0] in html
    for key in KEYS:
        assert find_claims(labels[key]) == [], key
    assert untranslated(result.model_dump(mode="json")) == []
    # Without public data, nothing is asked and nothing is shown.
    plain = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert plain.vix_regime is None
    assert labels["regime"] not in render(plain, watermark=False)[0]


def test_vix_down_is_not_measured_in_words() -> None:
    days = pd.bdate_range("2022-01-03", periods=300)
    frame = _curve(days, np.random.default_rng(4).normal(0.0008, 0.006, len(days)))
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale="es"))

    def broken(key: str) -> pd.Series:
        raise OSError("down")

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=broken)
    assert result.vix_regime is not None and result.vix_regime["status"] == "NOT_MEASURED"
    assert untranslated(result.model_dump(mode="json")) == []
    html = render(result, watermark=False)[0]
    assert_report_clean(html)
    assert "no se pudieron leer los cierres del VIX" in html
