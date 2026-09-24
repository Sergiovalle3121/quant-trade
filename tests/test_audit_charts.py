"""Inline SVG charts: shape, accessibility, escaping, no JavaScript, guard."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

import pytest

from quant_trade.audit import charts
from quant_trade.audit.guard import assert_report_clean

SVG_NS = "{http://www.w3.org/2000/svg}"


def _series(n: int = 600, seed: int = 7) -> tuple[list[datetime], list[float]]:
    start = datetime(2021, 1, 4, tzinfo=UTC)
    times = [start + timedelta(days=i) for i in range(n)]
    equity, value, state = [], 10_000.0, seed
    for _ in range(n):
        state = (state * 1103515245 + 12345) % (2**31)
        value *= 1.0 + (state / 2**31 - 0.5) * 0.02
        equity.append(value)
    return times, equity


def _fan(n: int = 120) -> dict[str, list[float]]:
    offsets = {"p5": -0.3, "p25": -0.1, "p50": 0.0, "p75": 0.1, "p95": 0.3}
    return {k: [1.0 + o * i / (n - 1) for i in range(n)] for k, o in offsets.items()}


def _svg_root(figure: str) -> ElementTree.Element:
    match = re.search(r"<svg.*</svg>", figure, flags=re.S)
    assert match, figure
    return ElementTree.fromstring(match.group(0))


def _all_outputs() -> list[str]:
    times, equity = _series()
    out = []
    for locale in ("es", "en"):
        out += [
            charts.equity_chart(times, equity, locale=locale),
            charts.drawdown_chart(times, equity, locale=locale),
            charts.fan_chart(_fan(), locale=locale, horizon_label="1"),
            charts.monthly_heatmap(times, equity, locale=locale),
            charts.equity_chart([], [], locale=locale),
        ]
    return out


# -- downsample ------------------------------------------------------------


def test_downsample_keeps_short_series_whole() -> None:
    assert charts.downsample([1.0, 2.0, 3.0], 10) == [0, 1, 2]


def test_downsample_bounds_size_and_keeps_extremes_and_ends() -> None:
    values = [math.sin(i / 17) * (1 + i / 500) for i in range(5000)]
    values[1234] = -50.0
    values[4321] = 80.0
    kept = charts.downsample(values, 200)
    assert len(kept) <= 200
    assert kept == sorted(set(kept))
    assert {0, 4999, 1234, 4321} <= set(kept)


def test_downsample_skips_non_finite_and_rejects_tiny_budget() -> None:
    assert charts.downsample([1.0, math.nan, 2.0, math.inf], 10) == [0, 2]
    with pytest.raises(ValueError):
        charts.downsample([1.0] * 10, 3)


# -- data helpers ------------------------------------------------------------


def test_drawdown_series_measures_from_running_peak() -> None:
    dd = charts.drawdown_series([100.0, 120.0, 90.0, math.nan, 130.0])
    assert dd[:3] == pytest.approx([0.0, 0.0, -0.25])
    assert math.isnan(dd[3])
    assert dd[4] == 0.0


def test_monthly_returns_chain_month_ends() -> None:
    times = ["2024-01-02", "2024-01-31", "2024-02-29", "2024-04-30"]
    rows = charts.monthly_returns(times, [100.0, 110.0, 99.0, 108.9])
    assert [(r.year, r.month) for r in rows] == [(2024, 1), (2024, 2), (2024, 4)]
    assert [r.value for r in rows] == pytest.approx([0.10, -0.10, 0.10])


def test_monthly_returns_sorts_and_drops_bad_rows() -> None:
    times = ["2024-02-01", "not a date", "2024-01-01", "2024-01-15"]
    rows = charts.monthly_returns(times, [121.0, 5.0, 100.0, math.nan])
    assert [r.value for r in rows] == pytest.approx([0.0, 0.21])


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        charts.equity_chart(["2024-01-01"], [1.0, 2.0])


# -- rendering ---------------------------------------------------------------


@pytest.mark.parametrize("locale", ["es", "en"])
def test_svg_charts_are_accessible_well_formed_and_tagged(locale: str) -> None:
    times, equity = _series()
    for figure in (
        charts.equity_chart(times, equity, locale=locale),
        charts.drawdown_chart(times, equity, locale=locale),
        charts.fan_chart(_fan(), locale=locale),
    ):
        root = _svg_root(figure)
        assert root.get("role") == "img"
        assert root.find(f"{SVG_NS}title") is not None
        assert root.find(f"{SVG_NS}desc") is not None
        assert '<span class="badge MEASURED">MEASURED</span>' in figure


def test_equity_chart_downsamples_long_series() -> None:
    times, equity = _series(5000)
    root = _svg_root(charts.equity_chart(times, equity, max_points=100))
    line = [p for p in root.iter(f"{SVG_NS}path") if p.get("stroke") == charts.SERIES][0]
    assert line.get("d", "").count("L") <= 99


def test_chart_points_stay_inside_the_viewbox() -> None:
    times, equity = _series()
    for figure in (
        charts.equity_chart(times, equity),
        charts.drawdown_chart(times, equity),
        charts.fan_chart(_fan()),
    ):
        for d in re.findall(r' d="([^"]+)"', figure):
            for x, y in re.findall(r"(-?[\d.]+),(-?[\d.]+)", d):
                assert 0 <= float(x) <= charts.WIDTH
                assert 0 <= float(y) <= charts.HEIGHT


def test_no_javascript_or_event_handlers_anywhere() -> None:
    for output in _all_outputs():
        lowered = output.lower()
        assert "<script" not in lowered
        assert "javascript:" not in lowered
        assert not re.search(r"\son[a-z]+\s*=", lowered)


def test_every_output_passes_the_profit_claim_guard() -> None:
    assert_report_clean(*_all_outputs())


def test_notes_are_escaped() -> None:
    times, equity = _series(50)
    figure = charts.equity_chart(times, equity, note="<script>alert(1)</script>")
    assert "<script>" not in figure
    assert "&lt;script&gt;" in figure


def test_insufficient_data_is_not_measured() -> None:
    figure = charts.drawdown_chart(["2024-01-01"], [100.0])
    assert "NOT_MEASURED" in figure and "<svg" not in figure
    assert "NOT_MEASURED" in charts.monthly_heatmap([], [])
    assert "NOT_MEASURED" in charts.fan_chart({"p50": [1.0]})


def test_invalid_evidence_tag_is_refused() -> None:
    times, equity = _series(50)
    with pytest.raises(ValueError):
        charts.equity_chart(times, equity, evidence="VERIFIED")


def test_declared_evidence_is_shown_as_declared() -> None:
    times, equity = _series(50)
    figure = charts.equity_chart(times, equity, evidence="DECLARED")
    assert "badge DECLARED" in figure and "badge MEASURED" not in figure


def test_fan_says_it_is_not_a_forecast_in_both_languages() -> None:
    assert "no es un pronóstico" in charts.fan_chart(_fan(), locale="es")
    assert "not a forecast" in charts.fan_chart(_fan(), locale="en")


def test_fan_validates_its_input() -> None:
    with pytest.raises(ValueError):
        charts.fan_chart({"p50": [1.0, 1.1], "p99": [1.0, 1.2]})
    with pytest.raises(ValueError):
        charts.fan_chart({"p50": [1.0, 1.1], "p95": [1.0, 1.2, 1.3]})


def test_fan_draws_only_complete_bands() -> None:
    root = _svg_root(charts.fan_chart({"p25": [1, 0.9], "p50": [1, 1], "p75": [1, 1.1]}))
    fills = {p.get("fill") for p in root.iter(f"{SVG_NS}path")}
    assert charts.BAND_INNER in fills
    assert charts.BAND_OUTER not in fills


def test_monthly_heatmap_prints_values_and_totals() -> None:
    times = ["2023-12-29", "2024-01-31", "2024-02-29"]
    table = charts.monthly_heatmap(times, [100.0, 110.0, 99.0], locale="en")
    assert "<th>Jan</th>" in table and "<th>Total</th>" in table
    assert "+10.0%" in table and "-10.0%" in table
    assert "-1.0%" in table  # 2024 compounded: 1.1 * 0.9 - 1
    assert 'title="2024-02: -10.0%"' in table
    assert 'class="empty"' in table


def test_charts_are_deterministic() -> None:
    assert _all_outputs() == _all_outputs()


def test_unknown_locale_falls_back_to_spanish() -> None:
    times, equity = _series(50)
    assert "Curva de equity" in charts.equity_chart(times, equity, locale="fr")


def test_zero_percent_tick_has_no_minus_sign() -> None:
    times, equity = _series(200)
    figure = charts.drawdown_chart(times, equity)
    assert ">0%<" in figure and ">-0%<" not in figure
