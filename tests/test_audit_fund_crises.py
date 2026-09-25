"""A track record through dated market falls, and its 12-month extremes. Offline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.crises import MARKET, MARKET_AS_OF, WINDOWS, crisis_review, curve_months
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


def test_curve_months_fill_quiet_trade_months_and_drop_partial_edges() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2020-01-05", "2020-01-31", "2020-03-31", "2020-04-10"], utc=True
            ),
            "equity": [100.0, 110.0, 99.0, 120.0],
        }
    )
    # Trades: February closed nothing, so flat. January starts in its first
    # week, so it counts. April ends on the 10th: left out.
    months = curve_months(frame, from_trades=True)
    assert list(months.round(6)) == [0.1, 0.0, -0.1]
    assert [stamp.month for stamp in months.index] == [1, 2, 3]
    # An uploaded curve with no February point: February and March are unknown.
    assert list(curve_months(frame).round(6)) == [0.1]


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
    # The market beside each window: Nasdaq for 2008, with its source and date.
    assert LABELS[locale]["crises_market"] in html
    assert "Nasdaq Composite</small> -51.8%" in html
    assert "fred.stlouisfed.org/series/NASDAQCOM" in html and MARKET_AS_OF in html
    assert "SP500" not in html  # no S&P figure before FRED's series starts


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


def test_a_curve_under_two_months_says_so() -> None:
    from quant_trade.audit.crises import CURVE_NOTE, curve_crises

    short = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2020-03-02", "2020-03-20"], utc=True),
            "equity": [100.0, 101.0],
        }
    )
    assert curve_crises(short)["reason"] == "the curve is shorter than two months"
    stamps = pd.bdate_range("2006-01-02", "2012-12-31", tz="UTC")
    frame = pd.DataFrame({"timestamp": stamps, "equity": np.linspace(100, 200, len(stamps))})
    assert curve_crises(frame)["note"] == CURVE_NOTE


def _frame(stamps: pd.DatetimeIndex, seed: int = 1) -> pd.DataFrame:
    steps = np.random.default_rng(seed).normal(0.0003, 0.01, len(stamps))
    return pd.DataFrame({"timestamp": stamps, "equity": 10_000 * np.cumprod(1 + steps)})


def test_a_hole_in_an_uploaded_curve_never_covers_a_crisis() -> None:
    from quant_trade.audit.crises import curve_crises

    # Nothing from November 2007 to May 2009: the 2008 window was never seen.
    stamps = pd.bdate_range("2005-01-03", "2007-10-31", tz="UTC").append(
        pd.bdate_range("2009-06-01", "2012-12-31", tz="UTC")
    )
    review = curve_crises(_frame(stamps))
    assert [row["key"] for row in review["windows"]] == ["euro"]
    # A curve rebuilt from trades closed nothing in the quiet months: flat.
    rebuilt = curve_crises(_frame(stamps), from_trades=True)
    gfc = next(row for row in rebuilt["windows"] if row["key"] == "gfc")
    assert gfc["fund"]["value"] == 0.0


def test_a_curve_starting_in_the_first_week_counts_that_month() -> None:
    from quant_trade.audit.crises import curve_crises

    covered = curve_crises(_frame(pd.bdate_range("2020-02-03", "2021-06-30", tz="UTC")))
    assert [row["key"] for row in covered["windows"]] == ["covid"]
    late = curve_crises(_frame(pd.bdate_range("2020-02-12", "2021-06-30", tz="UTC")))
    assert late["status"] == "NOT_MEASURED"


def test_a_flat_curve_shows_no_section() -> None:
    from quant_trade.audit.crises import curve_crises

    stamps = pd.bdate_range("2021-06-01", "2023-06-30", tz="UTC")
    wiggle = 10_000 + 0.1 * np.sin(np.arange(len(stamps)))
    review = curve_crises(pd.DataFrame({"timestamp": stamps, "equity": wiggle}))
    assert review == {
        "status": "NOT_MEASURED",
        "reason": "the curve never moves 0.1 % from its start",
    }


def test_a_window_with_no_closed_trades_says_so(locale: str = "es") -> None:
    from quant_trade.audit.crises import curve_crises
    from quant_trade.audit.report import _crises_html

    # Trades every month except through the 2008 window.
    closes = [
        stamp
        for stamp in pd.date_range("2006-01-15", "2012-12-15", freq="MS", tz="UTC")
        if not pd.Timestamp("2007-11-01", tz="UTC") <= stamp <= pd.Timestamp("2009-02-28", tz="UTC")
    ]
    closes = [pd.Timestamp("2006-01-02", tz="UTC"), *[c + pd.Timedelta(days=14) for c in closes]]
    equity = 10_000 * np.cumprod(np.r_[1.0, np.full(len(closes) - 1, 1.004)])
    frame = pd.DataFrame({"timestamp": closes, "equity": equity})
    review = curve_crises(frame, from_trades=True)
    gfc = next(row for row in review["windows"] if row["key"] == "gfc")
    euro = next(row for row in review["windows"] if row["key"] == "euro")
    assert gfc.get("no_trades") is True and "no_trades" not in euro
    html = _crises_html(review, LABELS[locale])
    assert LABELS[locale]["crises_no_trades"] in html


def test_every_window_has_a_sourced_market_move() -> None:
    assert set(MARKET) == {window.key for window in WINDOWS}
    for moves in MARKET.values():
        assert moves
        for move in moves:
            assert move.source_url.startswith("https://fred.stlouisfed.org/series/")
            assert -1.0 < move.change < 0.0
    # Never part of the result: the figures are context, not measured from a file.
    values = np.random.default_rng(2).normal(0.006, 0.03, 180)
    result = run_audit(
        build_inputs(_grid(values, 2010), DeclaredMetadata(locale="es")), bootstrap_samples=200
    )
    assert "Nasdaq" not in str(result.model_dump(mode="json"))


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_market_note_passes_the_guard_and_says_when_it_does_not_fit(locale: str) -> None:
    text = LABELS[locale]["crises_market_note"]
    assert find_claims(text) == [] and find_claims(LABELS[locale]["crises_market"]) == []
    assert ("otro mercado" if locale == "es" else "another market") in text
