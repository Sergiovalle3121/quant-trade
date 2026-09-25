"""Fund track records: the factsheet grid and the fund investor's checks. Offline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import run_audit
from quant_trade.audit.factsheet import monthly_grid
from quant_trade.audit.fund import fund_review
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.report import LABELS, _fund_html, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs, parse_equity_csv

MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _grid_csv(
    returns: np.ndarray,
    *,
    start_year: int = 2016,
    months: list[str] = MONTHS_EN,
    year: str = "Year",
    total: str | None = "YTD",
    sep: str = ",",
    decimal: str = ".",
    skip: int = 0,
) -> bytes:
    """A year-by-month table of ``returns`` (fractions) written as percentages."""
    values = [None] * skip + [float(v) for v in returns]
    lines = [sep.join([year, *months] + ([total] if total else []))]
    for row in range(0, len(values), 12):
        chunk = values[row : row + 12] + [None] * (12 - len(values[row : row + 12]))
        cells = ["" if v is None else f"{v * 100:.2f}%".replace(".", decimal) for v in chunk]
        line = [str(start_year + row // 12), *cells]
        if total:
            done = [v for v in chunk if v is not None]
            ytd = float(np.prod([1 + v for v in done]) - 1)
            line.append(f"{ytd * 100:.2f}%".replace(".", decimal))
        lines.append(sep.join(line))
    return ("\n".join(lines) + "\n").encode()


def _returns(n: int = 96, seed: int = 1, mean: float = 0.008, vol: float = 0.03) -> np.ndarray:
    return np.random.default_rng(seed).normal(mean, vol, n)


def test_an_english_grid_reads_as_month_end_returns() -> None:
    r = _returns(36)
    series = parse_equity_csv(_grid_csv(r))
    assert series.source == "returns" and series.observations == 37
    assert series.frame["ret"].dropna().to_numpy() == pytest.approx(r, abs=5e-5)
    assert str(series.frame["timestamp"].iloc[1].date()) == "2016-01-31"
    assert any("monthly returns table" in w for w in series.warnings)


def test_a_spanish_grid_with_decimal_commas_and_a_late_start() -> None:
    r = _returns(30)
    data = _grid_csv(r, months=MONTHS_ES, year="Año", total="Total", sep=";", decimal=",", skip=4)
    series = parse_equity_csv(data)
    assert series.frame["ret"].dropna().to_numpy() == pytest.approx(r, abs=5e-5)
    assert str(series.frame["timestamp"].iloc[1].date()) == "2016-05-31"


def test_an_edited_month_leaves_its_year_total_behind() -> None:
    r = _returns(36)
    text = _grid_csv(r).decode().splitlines()
    cells = text[2].split(",")
    cells[3] = "9.99%"  # an edited March 2017, the year total left as it was
    text[2] = ",".join(cells)
    grid = monthly_grid(
        pd.read_csv(pd.io.common.StringIO("\n".join(text))).rename(columns=str.lower)
    )
    assert grid is not None and grid.mismatched_years == [2017]
    assert "does not match its months for 2017" in grid.warnings[-1]


def test_a_table_that_is_not_a_grid_is_left_alone() -> None:
    frame = pd.DataFrame({"name": ["a", "b"], "jan": [1, 2]})
    assert monthly_grid(frame) is None


def _frame(r: np.ndarray) -> pd.DataFrame:
    stamps = pd.date_range("2015-12-31", periods=len(r) + 1, freq="ME", tz="UTC")
    equity = np.concatenate([[1.0], np.cumprod(1 + r)])
    return pd.DataFrame({"timestamp": stamps, "equity": equity})


def test_a_plain_track_record_has_the_figures_and_no_findings() -> None:
    review = fund_review(_frame(_returns()), 12.0)
    assert review["status"] == "MEASURED" and review["findings"] == []
    assert review["months"]["value"] == 96 and len(review["years"]) == 8
    assert -1 < review["max_drawdown"]["value"] < 0


def test_smoothed_returns_are_found_and_unsmoothed() -> None:
    noise = _returns(120, seed=2, mean=0.0, vol=0.02)
    r = np.empty_like(noise)
    r[0] = noise[0]
    for i in range(1, len(r)):
        r[i] = 0.6 * r[i - 1] + 0.4 * noise[i] + 0.003
    review = fund_review(_frame(r), 12.0)
    assert "smoothed" in review["findings"]
    assert review["volatility_unsmoothed"]["value"] > review["volatility"]["value"]


def test_missing_small_losses_are_found() -> None:
    r = _returns(120, seed=3, mean=0.006, vol=0.02)
    # Every small loss reported as a small gain instead.
    r = np.where((r < 0) & (r > -0.012), np.abs(r), r)
    review = fund_review(_frame(r), 12.0)
    assert "few_small_losses" in review["findings"]
    assert review["small_losses"]["value"] == 0


@pytest.mark.parametrize(
    ("r", "ppy", "reason"),
    [
        (_returns(96), 252.0, "not a monthly track record"),
        (_returns(20), 12.0, "needs at least 24"),
    ],
)
def test_daily_and_short_files_are_not_measured(r: np.ndarray, ppy: float, reason: str) -> None:
    review = fund_review(_frame(r), ppy)
    assert review["status"] == "NOT_MEASURED" and reason in review["reason"]


def test_every_label_passes_the_guard() -> None:
    for labels in LABELS.values():
        for key, text in labels.items():
            if key.startswith("fund"):
                assert find_claims(text) == [], text


@pytest.mark.parametrize("locale", ["es", "en"])
def test_engine_reads_a_factsheet_and_renders_the_section(locale: str) -> None:
    noise = _returns(96, seed=2, mean=0.0, vol=0.02)
    r = noise.copy()
    for i in range(1, len(r)):
        r[i] = 0.6 * r[i - 1] + 0.4 * noise[i] + 0.004
    inputs = build_inputs(_grid_csv(r), DeclaredMetadata(locale=locale))
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.fund is not None and result.fund["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert LABELS[locale]["fund"] in html and "fund-cal" in html
    assert ("Pregunta cómo" if locale == "es" else "Ask how") in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_the_calendar_shows_each_month_and_the_year() -> None:
    review = fund_review(_frame(_returns(24)), 12.0)
    html = _fund_html(review, "es", LABELS["es"])
    assert html.count("<tr><th scope='row'>") == 2 and "<th>Dic</th>" in html
    assert "-0.0%" not in html
    # A volatility is a size, never signed.
    assert f"<b>{review['volatility']['value']:.1%}</b>" in html


@pytest.mark.parametrize("seed", range(6))
def test_fat_tailed_honest_returns_do_not_read_as_missing_losses(seed: int) -> None:
    # Peaked, fat-tailed months like a stock index's: no losses were hidden.
    r = 0.008 + 0.03 * np.random.default_rng(seed).standard_t(4, 300) / np.sqrt(2)
    assert "few_small_losses" not in fund_review(_frame(r), 12.0)["findings"]
