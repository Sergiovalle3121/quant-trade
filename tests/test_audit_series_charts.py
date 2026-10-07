"""Periodic-return charts retain the first return without inventing an opening date."""

from __future__ import annotations

import html
import re

import pytest

from quant_trade.audit.charts import MonthlyReturn, drawdown_chart, monthly_heatmap
from quant_trade.audit.guard import find_claims


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_periodic_drawdown_keeps_first_loss_with_original_dates(locale: str) -> None:
    times = ["2024-01-31", "2024-02-29"]
    figure = drawdown_chart(times, [0.9, 0.99], opening_equity=1, locale=locale)
    assert "-10.0%" in figure
    assert "2024-01-31" in figure and "2024-02-29" in figure
    assert "2024-01-30" not in figure
    assert "MEASURED" in figure
    assert find_claims(html.unescape(re.sub(r"<[^>]+>", " ", figure))) == []


def test_drawdown_without_opening_equity_keeps_existing_equity_semantics() -> None:
    figure = drawdown_chart(["2024-01-31", "2024-02-29"], [0.9, 0.99], locale="en")
    caption = re.search(r"<figcaption>(.*?)</figcaption>", figure)
    assert caption is not None
    assert "max 0.0%" in caption.group(1)


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_monthly_heatmap_uses_actual_first_period_return(locale: str) -> None:
    rows = [MonthlyReturn(2024, 1, -0.1), MonthlyReturn(2024, 2, 0.1)]
    figure = monthly_heatmap(
        ["2024-01-31", "2024-02-29"], [0.9, 0.99], period_months=rows, locale=locale
    )
    assert 'title="2024-01: -10.0%"' in figure
    assert 'title="2024-02: +10.0%"' in figure
    assert 'title="2024: -1.0%"' in figure
    assert "MEASURED" in figure
    assert find_claims(html.unescape(re.sub(r"<[^>]+>", " ", figure))) == []


def test_monthly_heatmap_does_not_fill_absent_periods_or_fall_back_from_empty_rows() -> None:
    rows = [MonthlyReturn(2024, 1, -0.1), MonthlyReturn(2024, 3, 0.02)]
    figure = monthly_heatmap([], [], period_months=rows)
    assert 'title="2024-01: -10.0%"' in figure
    assert 'title="2024-03: +2.0%"' in figure
    assert 'title="2024-02:' not in figure
    assert 'class="empty"' in figure
    assert "NOT_MEASURED" in monthly_heatmap(
        ["2024-01-31", "2024-02-29"], [0.9, 0.99], period_months=[]
    )


@pytest.mark.parametrize("opening", [0, -1, float("nan"), float("inf")])
def test_drawdown_rejects_invalid_opening_equity(opening: float) -> None:
    with pytest.raises(ValueError, match="opening_equity"):
        drawdown_chart(["2024-01-31", "2024-02-29"], [0.9, 0.99], opening_equity=opening)


@pytest.mark.parametrize(
    "rows",
    [
        [MonthlyReturn(2024, 0, 0.01)],
        [MonthlyReturn(2024, 13, 0.01)],
        [MonthlyReturn(2024, 1, float("nan"))],
        [MonthlyReturn(2024, 1, float("inf"))],
        [MonthlyReturn(2024, 1, 0.01), MonthlyReturn(2024, 1, 0.02)],
    ],
)
def test_heatmap_rejects_invalid_precomputed_period_months(rows: list[MonthlyReturn]) -> None:
    with pytest.raises(ValueError, match="period_months"):
        monthly_heatmap([], [], period_months=rows)
