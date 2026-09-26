"""The math the engine stores, shown in the report: trade ranges, Lo's Sharpe,
Jensen's alpha and the 2 and 20 fee row, in Spanish, English and Portuguese."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from functools import cache

import pytest
from audit_fixtures import benchmark_lower_drift, csv_bytes, positive_drift, trades_following

from quant_trade.audit import report
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs, measured

LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


@cache
def _with_trades_and_benchmark() -> AuditResult:
    equity = positive_drift(600)
    inputs = build_inputs(
        csv_bytes(equity),
        DeclaredMetadata(cost_bps_per_side=1),
        trades_bytes=csv_bytes(trades_following(equity)),
        benchmark_bytes=csv_bytes(benchmark_lower_drift(600)),
    )
    return run_audit(inputs, now=NOW, audit_id="math", bootstrap_samples=100)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_shows_the_trade_ranges_and_the_alpha(locale: str) -> None:
    result = _with_trades_and_benchmark()
    data = result.model_dump(mode="json")
    assert data["trade_stats"]["intervals"]["status"] == "MEASURED"
    assert data["benchmark"]["jensen"]["status"] == "MEASURED"
    page = render_html(result, watermark=False, locale=locale)
    text = _text(page)
    labels = report.LABELS[locale]
    assert labels["ranges_title"] in text
    assert labels["alpha_line"].split(":")[0] in text
    assert find_claims(page) == []


def test_a_range_across_break_even_says_so() -> None:
    labels = report.LABELS["es"]
    ranges = {
        "status": "MEASURED",
        "trades": 40,
        "win_rate": {"low": measured(0.4), "high": measured(0.6)},
        "expectancy": {"low": measured(-3.0), "high": measured(5.0)},
        "profit_factor": {"low": measured(0.8), "high": measured(1.9)},
    }

    def says() -> bool:
        return labels["ranges_zero"] in html.unescape(report._ranges_html(ranges, labels))

    assert says()
    # The average's range includes zero while the factor's stays above one:
    # the two disagree, and the report never stays silent in the file's favour.
    ranges["profit_factor"]["low"] = measured(1.4)
    assert says()
    # The factor's range includes one while the average's stays above zero.
    ranges["profit_factor"]["low"] = measured(0.8)
    ranges["expectancy"] = {"low": measured(1.0), "high": measured(5.0)}
    assert says()
    # Neither includes break-even.
    ranges["profit_factor"]["low"] = measured(1.2)
    assert not says()
    # An open upper end reads as such, never as "inf".
    ranges["profit_factor"]["high"] = {"evidence": "NOT_MEASURED", "value": None, "note": ""}
    shown = html.unescape(report._ranges_html(ranges, labels))
    assert labels["ranges_open"] in shown and "inf" not in shown


@pytest.mark.parametrize("locale", LOCALES)
def test_a_range_wholly_below_break_even_says_so(locale: str) -> None:
    labels = report.LABELS[locale]
    ranges = {
        "status": "MEASURED",
        "trades": 60,
        "win_rate": {"low": measured(0.2), "high": measured(0.35)},
        "expectancy": {"low": measured(-12.3), "high": measured(-4.1)},
        "profit_factor": {"low": measured(0.4), "high": measured(0.8)},
    }
    shown = html.unescape(report._ranges_html(ranges, labels))
    assert labels["ranges_below"] in shown and labels["ranges_zero"] not in shown
    assert find_claims(shown) == []
    # One range below, the other straddling: the straddle is the cautious reading.
    ranges["profit_factor"]["high"] = measured(1.1)
    shown = html.unescape(report._ranges_html(ranges, labels))
    assert labels["ranges_zero"] in shown and labels["ranges_below"] not in shown


def test_lo_sharpe_is_shown_only_when_it_is_lower() -> None:
    labels = report.LABELS["en"]
    lower = {"autocorrelation_adjusted": {"sharpe": measured(1.2), "lag1": measured(0.41)}}
    shown = html.unescape(report._lo_html(lower, 1.52, labels))
    assert "1.20" in shown and "1.52" in shown and "0.41" in shown
    # A higher corrected figure is never printed: it would flatter the file.
    higher = {"autocorrelation_adjusted": {"sharpe": measured(3.99), "lag1": measured(0.02)}}
    shown = html.unescape(report._lo_html(higher, 2.22, labels))
    assert "3.99" not in shown and "2.22" in shown
    assert report._lo_html({}, 2.22, labels) == ""


@pytest.mark.parametrize(
    ("t_stat", "key"),
    [(2.5, "alpha_clear_up"), (-2.5, "alpha_clear_down"), (1.96, "alpha_unclear")],
)
def test_alpha_reads_its_t_statistic(t_stat: float, key: str) -> None:
    labels = report.LABELS["es"]
    bench = {
        "jensen": {
            "status": "MEASURED",
            "alpha": measured(0.031),
            "alpha_t_stat": measured(t_stat),
            "beta": measured(0.8),
            "periods": 60,
        }
    }
    shown = html.unescape(report._alpha_html(bench, labels))
    assert labels[key] in shown and f"{t_stat:.2f}" in shown


@pytest.mark.parametrize("locale", LOCALES)
def test_the_fee_table_carries_the_two_and_twenty_row(locale: str) -> None:
    labels = report.LABELS[locale]
    fees = {
        "status": "MEASURED",
        "gross_cagr": measured(0.1),
        "gross_growth": measured(0.6),
        "rows": [{"rate": 0.01, "cagr": measured(0.09), "growth": measured(0.54)}],
        "two_and_twenty": {"cagr": measured(0.06), "growth": measured(0.34)},
    }
    shown = html.unescape(report._fund_fees_html(fees, labels))
    assert labels["fund_fees_two_twenty"] in shown
    assert find_claims(shown) == []


def test_a_curve_without_trades_shows_no_ranges() -> None:
    inputs = build_inputs(csv_bytes(positive_drift(300)), DeclaredMetadata())
    result = run_audit(inputs, now=NOW, audit_id="bare", bootstrap_samples=100)
    for locale in LOCALES:
        text = _text(render_html(result, watermark=False, locale=locale))
        assert report.LABELS[locale]["ranges_title"] not in text


def _shuffle(position: str, share: float) -> dict:
    return {
        "status": "MEASURED",
        "observed": measured(-0.08),
        "shuffled": {"p5": measured(-0.12), "p50": measured(-0.2), "p95": measured(-0.34)},
        "share_at_most_as_deep": measured(share),
        "share_at_least_as_deep": measured(share),
        "position": position,
        "method": {"samples": 1000},
    }


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("position", ["TYPICAL", "SHALLOWER", "DEEPER"])
def test_the_worst_fall_is_placed_among_random_orders(locale: str, position: str) -> None:
    labels = report.LABELS[locale]
    shown = html.unescape(report._shuffle_html(_shuffle(position, 0.012), labels))
    assert labels["shuffle_title"] in shown
    assert "8.0%" in shown and "12.0%" in shown and "34.0%" in shown
    assert ("1,000" in shown) == (locale == "en")
    assert labels[f"shuffle_{position}"].split(":")[0] in shown
    assert find_claims(shown) == []


def test_an_unmeasured_shuffle_shows_nothing() -> None:
    labels = report.LABELS["es"]
    assert report._shuffle_html({"status": "NOT_MEASURED", "reason": "x"}, labels) == ""
    assert report._shuffle_html(None, labels) == ""


def test_the_report_shows_the_shuffle_when_the_engine_measures_it() -> None:
    result = _with_trades_and_benchmark()
    shuffle = result.model_dump(mode="json")["risk"]["versus_shuffle"]
    text = _text(render_html(result, watermark=False, locale="es"))
    assert (report.LABELS["es"]["shuffle_title"] in text) == (shuffle["status"] == "MEASURED")
