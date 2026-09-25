"""A track record through dated market falls, and its 12-month extremes. Offline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.crises import WINDOWS, crisis_review, curve_months
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _series(first: str, values: np.ndarray) -> pd.Series:
    stamps = pd.date_range(first, periods=len(values), freq="ME", tz="UTC")
    return pd.Series(values, index=stamps)


def test_only_windows_covered_in_full_are_reported() -> None:
    # From March 2008: the 2008 window (from Nov 2007) is not covered in full.
    values = np.full(200, 0.01)
    review = crisis_review(_series("2008-03-31", values))
    keys = [row["key"] for row in review["windows"]]
    assert "gfc" not in keys and "dotcom" not in keys
    assert keys[:2] == ["euro", "china_oil"]
    covid = next(row for row in review["windows"] if row["key"] == "covid")
    assert covid["fund"]["value"] == pytest.approx(1.01**2 - 1)
    assert covid["first"] == "2020-02" and covid["last"] == "2020-03"


def test_rolling_twelve_months() -> None:
    values = np.array([0.02] * 12 + [-0.03] * 12 + [0.01] * 12)
    review = crisis_review(_series("2010-01-31", values))
    assert review["worst_12m"]["value"] == pytest.approx(0.97**12 - 1)
    assert review["best_12m"]["value"] == pytest.approx(1.02**12 - 1)
    # 25 windows: the first and the last ones positive, the middle ones mixed.
    wealth = np.cumprod(1 + values)
    rolling = wealth[11:] / np.concatenate([[1.0], wealth[:-12]]) - 1
    assert review["positive_12m"]["value"] == pytest.approx(float((rolling > 0).mean()))


def test_falling_more_than_the_benchmark_in_crises_is_a_finding() -> None:
    rng = np.random.default_rng(4)
    index = rng.normal(0.006, 0.04, 300)
    fund = index.copy()
    stamps = pd.date_range("2000-01-31", periods=300, freq="ME", tz="UTC")
    for window in WINDOWS:
        span = (stamps.to_period("M") >= window.first) & (stamps.to_period("M") <= window.last)
        fund[span] = index[span] * 1.5 - 0.01
    review = crisis_review(pd.Series(fund, index=stamps), pd.Series(index, index=stamps))
    assert "fell_more_in_crises" in review["findings"]
    assert review["compared"]["value"] == len(review["windows"]) >= 2
    calm = crisis_review(pd.Series(index, index=stamps), pd.Series(index, index=stamps))
    assert calm["findings"] == []


def test_every_crisis_label_passes_the_guard_and_names_each_window() -> None:
    for labels in LABELS.values():
        for window in WINDOWS:
            assert labels[f"fund_stress_{window.key}"]
        for key, text in labels.items():
            if key.startswith("fund_stress"):
                assert find_claims(text) == [], text


def _grid(values: np.ndarray, first_year: int) -> bytes:
    lines = ["Year," + ",".join(MONTHS)]
    for y in range(len(values) // 12):
        cells = [f"{v * 100:.2f}%" for v in values[12 * y : 12 * y + 12]]
        lines.append(",".join([str(first_year + y), *cells]))
    return ("\n".join(lines) + "\n").encode()


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_section_shows_the_crises(locale: str) -> None:
    values = np.random.default_rng(2).normal(0.006, 0.03, 180)
    result = run_audit(
        build_inputs(_grid(values, 2010), DeclaredMetadata(locale=locale)), bootstrap_samples=200
    )
    assert result.fund is not None and result.fund["crises"]["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert LABELS[locale]["fund_stress"] in html and LABELS[locale]["fund_stress_covid"] in html
    assert untranslated(result.model_dump(mode="json")) == []


@pytest.mark.parametrize("locale", ["es", "en"])
def test_a_record_that_covers_no_crisis_says_so(locale: str) -> None:
    # 2023 onwards: after every dated window, so none is estimated from part of it.
    values = np.random.default_rng(3).normal(0.006, 0.03, 36)
    result = run_audit(
        build_inputs(_grid(values, 2023), DeclaredMetadata(locale=locale)), bootstrap_samples=200
    )
    assert result.fund is not None
    crises = result.fund["crises"]
    assert crises["windows"] == [] and crises["findings"] == []
    assert "worst_12m" in crises
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert LABELS[locale]["fund_stress_none"].replace("'", "&#x27;") in html


def _daily_csv(first: str, last: str, seed: int = 5) -> bytes:
    stamps = pd.bdate_range(first, last)
    steps = np.random.default_rng(seed).normal(0.0003, 0.01, len(stamps))
    equity = 10_000 * np.cumprod(1 + steps)
    rows = [f"{stamp.date()},{value:.4f}" for stamp, value in zip(stamps, equity, strict=True)]
    return ("timestamp,equity\n" + "\n".join(rows) + "\n").encode()


def test_curve_months_carry_quiet_months_and_drop_a_partial_last_month() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2020-01-05", "2020-01-31", "2020-03-31", "2020-04-10"], utc=True
            ),
            "equity": [100.0, 110.0, 99.0, 120.0],
        }
    )
    months = curve_months(frame)
    # February had no point: flat. April ends on the 10th: left out.
    assert list(months.round(6)) == [0.0, -0.1]
    assert [stamp.month for stamp in months.index] == [2, 3]


@pytest.mark.parametrize("locale", ["es", "en"])
def test_a_daily_backtest_shows_the_crises_it_covers(locale: str) -> None:
    result = run_audit(
        build_inputs(_daily_csv("2006-01-02", "2012-12-31"), DeclaredMetadata(locale=locale)),
        bootstrap_samples=200,
    )
    assert result.fund is not None and result.fund["status"] == "NOT_MEASURED"
    assert result.crises is not None and result.crises["status"] == "MEASURED"
    assert [row["key"] for row in result.crises["windows"]] == ["gfc", "euro"]
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert LABELS[locale]["crises_subject"] in html
    assert LABELS[locale]["fund_stress_gfc"] in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_a_curve_that_covers_no_crisis_shows_no_section() -> None:
    result = run_audit(
        build_inputs(_daily_csv("2023-01-02", "2024-12-31"), DeclaredMetadata(locale="es")),
        bootstrap_samples=200,
    )
    assert result.crises is not None and result.crises["status"] == "NOT_MEASURED"
    html, _ = render(result, watermark=False)
    assert LABELS["es"]["crises_intro"] not in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_a_fund_record_keeps_the_crises_in_its_own_section() -> None:
    values = np.random.default_rng(2).normal(0.006, 0.03, 180)
    result = run_audit(
        build_inputs(_grid(values, 2010), DeclaredMetadata(locale="es")), bootstrap_samples=200
    )
    assert result.crises is None
    html, _ = render(result, watermark=False)
    assert html.count(LABELS["es"]["fund_stress"]) == 1
