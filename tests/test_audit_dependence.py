"""The probability of a true Sharpe above zero when returns depend on each
other: never higher than the plain one, right-sized on simulated returns, and
one informational line in the report in Spanish, English and Portuguese."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import business_days, csv_bytes

from quant_trade.audit import report
from quant_trade.audit.engine import dependence_adjusted_psr, run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs, measured
from quant_trade.metrics.statistics import (
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
)

LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
KEYS = (
    "dependence_line",
    "dependence_track",
    "dependence_track_long",
    "dependence_track_reached",
    "dependence_pass_rests",
    "dependence_none",
    "dependence_info",
)


def _ar1(n: int, phi: float, *, mean: float, seed: int) -> pd.Series:
    """AR(1) returns with fat-tailed shocks around ``mean``, after a burn-in."""
    rng = np.random.default_rng(seed)
    shocks = rng.standard_t(5, n + 50) * 0.01
    values = np.zeros(n + 50)
    for i in range(1, n + 50):
        values[i] = shocks[i] + phi * values[i - 1]
    return pd.Series(mean + values[50:])


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def test_without_dependence_it_equals_the_plain_figures() -> None:
    # Returns that alternate have negative autocorrelation: the factor is
    # floored at 1, so nothing moves and nothing is flattered.
    rng = np.random.default_rng(4)
    signs = np.where(np.arange(400) % 2 == 0, 1.0, -1.0)
    returns = pd.Series(0.0008 + signs * 0.01 + rng.normal(0.0, 0.002, 400))
    block = dependence_adjusted_psr(returns)
    assert block["ratio"]["value"] == 1.0
    assert block["psr"]["value"] == pytest.approx(probabilistic_sharpe_ratio(returns), rel=1e-9)
    assert block["min_track_record_length"]["value"] == pytest.approx(
        minimum_track_record_length(returns), rel=1e-6
    )


def test_smoothed_returns_lower_the_probability() -> None:
    returns = _ar1(600, 0.5, mean=0.001, seed=11)
    block = dependence_adjusted_psr(returns)
    assert block["ratio"]["evidence"] == "MEASURED"
    assert block["ratio"]["value"] > 2.0
    assert block["psr"]["value"] < probabilistic_sharpe_ratio(returns)
    assert block["min_track_record_length"]["value"] > minimum_track_record_length(returns)


@pytest.mark.parametrize("phi", [0.0, 0.2, 0.4, 0.6])
def test_it_is_never_above_the_plain_probability(phi: float) -> None:
    for seed in range(20):
        returns = _ar1(300, phi, mean=0.0006, seed=seed)
        block = dependence_adjusted_psr(returns)
        if block["psr"]["evidence"] != "MEASURED":
            continue
        assert block["psr"]["value"] <= probabilistic_sharpe_ratio(returns) + 1e-12


def test_on_returns_with_no_edge_it_keeps_the_false_alarm_rate_near_five_percent() -> None:
    # 400 histories of 200 returns with zero mean and autocorrelation 0.4: the
    # plain probability passes 95 % about 12 % of the time; this one about 5 %.
    plain = adjusted = 0
    runs = 400
    for seed in range(runs):
        returns = _ar1(200, 0.4, mean=0.0, seed=1000 + seed)
        plain += probabilistic_sharpe_ratio(returns) > 0.95
        block = dependence_adjusted_psr(returns)["psr"]
        adjusted += block["evidence"] == "MEASURED" and block["value"] > 0.95
    assert plain / runs > 0.09
    assert adjusted / runs < 0.075
    # Nor is it needlessly strict when the returns are independent.
    independent = sum(
        (block := dependence_adjusted_psr(_ar1(200, 0.0, mean=0.0, seed=5000 + seed))["psr"])[
            "evidence"
        ]
        == "MEASURED"
        and block["value"] > 0.95
        for seed in range(runs)
    )
    assert independent / runs > 0.025


@pytest.mark.parametrize(
    ("returns", "reason"),
    [
        (pd.Series(np.full(49, 0.001) + np.linspace(-0.01, 0.01, 49)), "fewer than fifty"),
        (pd.Series(np.linspace(-0.01, 0.009, 200)), "Sharpe <= 0"),
    ],
)
def test_short_or_losing_histories_are_not_measured(returns: pd.Series, reason: str) -> None:
    block = dependence_adjusted_psr(returns)
    for key in ("ratio", "psr", "min_track_record_length"):
        assert block[key]["evidence"] == "NOT_MEASURED"
        assert reason in block[key]["note"]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_line_reads_the_block(locale: str) -> None:
    labels = report.LABELS[locale]
    significance = {
        "observations": measured(500),
        "psr": measured(0.97),
        "min_track_record_length": measured(420.2),
        "dependence": {
            "ratio": measured(2.34),
            "psr": measured(0.88),
            "min_track_record_length": measured(981.1),
        },
    }
    shown = html.unescape(report._dependence_html(significance, labels))
    assert "2.3" in shown and "97.00%" in shown and "88.00%" in shown
    assert "982" in shown and "421" in shown and "500" in shown
    assert labels["dependence_track_long"].split("{")[0] not in shown
    assert labels["dependence_pass_rests"] in shown and labels["dependence_info"] in shown
    # A count beyond ten times the history is not printed: it only reads as noise.
    significance["dependence"]["min_track_record_length"] = measured(5001.0)
    shown = html.unescape(report._dependence_html(significance, labels))
    assert labels["dependence_track_long"].format(n="500") in shown and "5,001" not in shown
    # A count already within the history says the history reaches it.
    significance["dependence"]["min_track_record_length"] = measured(310.4)
    shown = html.unescape(report._dependence_html(significance, labels))
    assert labels["dependence_track_reached"].format(n="500", track="311") in shown
    significance["dependence"]["min_track_record_length"] = measured(981.1)
    # A probability that stays above 95 % has nothing resting on independence.
    significance["dependence"]["psr"] = measured(0.96)
    shown = html.unescape(report._dependence_html(significance, labels))
    assert labels["dependence_pass_rests"] not in shown
    significance["dependence"]["ratio"] = measured(1.04)
    shown = html.unescape(report._dependence_html(significance, labels))
    assert labels["dependence_none"] in shown and "96.00%" not in shown
    assert report._dependence_html({"psr": measured(0.97)}, labels) == ""


@pytest.mark.parametrize("locale", LOCALES)
def test_the_wording_passes_the_guard(locale: str) -> None:
    labels = report.LABELS[locale]
    for key in KEYS:
        assert find_claims(labels[key]) == [], key


def test_the_notes_have_spanish_and_portuguese_rules() -> None:
    returns = _ar1(300, 0.5, mean=0.001, seed=3)
    for value in dependence_adjusted_psr(returns).values():
        note = value["note"]
        for locale in ("es", "pt"):
            assert localize(note, locale) != note, (locale, note)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_smoothed_curve_shows_the_line_in_the_report(locale: str) -> None:
    returns = _ar1(600, 0.5, mean=0.0012, seed=21).to_numpy()
    equity = pd.DataFrame(
        {"timestamp": business_days(600), "equity": 10_000.0 * np.cumprod(1.0 + returns)}
    )
    result = run_audit(
        build_inputs(csv_bytes(equity), DeclaredMetadata()),
        now=NOW,
        audit_id="dependence",
        bootstrap_samples=100,
    )
    block = result.model_dump(mode="json")["significance"]["dependence"]
    assert block["ratio"]["value"] > 1.1
    page = render_html(result, watermark=False, locale=locale)
    labels = report.LABELS[locale]
    assert labels["dependence_info"] in _text(page)
    assert find_claims(page) == []
