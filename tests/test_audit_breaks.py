"""Whether the average return shifted at some point: the CUSUM test keeps its
false alarms near five percent on dependent returns, finds a real shift with
a date range that covers it, and reads as one informational section in
Spanish, English and Portuguese."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit import report
from quant_trade.audit.breaks import (
    DATE_NOTE,
    MEAN_NOTE,
    NOTE,
    SHORT,
    bridge_p_value,
    mean_shift,
)
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

NOW = datetime(2026, 1, 1, tzinfo=UTC)
KEYS = (
    "shift",
    "shift_intro",
    "shift_badge_changed",
    "shift_badge_steady",
    "shift_changed",
    "shift_steady",
    "shift_edge",
    "shift_before",
    "shift_after",
    "shift_band",
)


def _returns(n: int, phi: float, seed: int, *, shift: float = 0.0, at: float = 0.5) -> np.ndarray:
    """AR(1) returns with fat-tailed shocks, the mean moved by ``shift`` from ``at``."""
    rng = np.random.default_rng(seed)
    shocks = rng.standard_t(5, n + 50) * 0.01
    values = np.zeros(n + 50)
    for i in range(1, n + 50):
        values[i] = shocks[i] + phi * values[i - 1]
    out = 0.0005 + values[50:]
    out[int(n * at) :] += shift
    return out


def _frame(returns: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2018-01-01", periods=len(returns) + 1, tz="UTC"),
            "equity": 10_000.0 * np.concatenate([[1.0], np.cumprod(1.0 + returns)]),
        }
    )


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


@pytest.mark.parametrize(("statistic", "p_value"), [(1.3581, 0.05), (1.2238, 0.10), (1.6276, 0.01)])
def test_the_bridge_tail_matches_kolmogorovs_table(statistic: float, p_value: float) -> None:
    assert bridge_p_value(statistic) == pytest.approx(p_value, abs=5e-4)
    assert bridge_p_value(0.1) == 1.0


@pytest.mark.parametrize("phi", [0.0, 0.3, 0.6])
def test_with_no_shift_it_rarely_finds_one(phi: float) -> None:
    # Dependent returns inflate a plain CUSUM's false alarms; the cautious
    # long-run variance keeps them at or under about five percent.
    runs = 200
    alarms = sum(mean_shift(_frame(_returns(400, phi, seed)), 252)["clear"] for seed in range(runs))
    assert alarms / runs < 0.075


def test_a_real_shift_is_found_and_its_range_covers_the_date() -> None:
    hits = covered = 0
    for seed in range(60):
        frame = _frame(_returns(1000, 0.0, seed, shift=-0.004, at=0.6))
        block = mean_shift(frame, 252)
        if not block["clear"]:
            continue
        hits += 1
        true = frame["timestamp"].iloc[601].date().isoformat()
        covered += block["date_low"] <= true <= block["date_high"]
        assert block["after"]["mean"]["value"] < block["before"]["mean"]["value"]
        assert block["before"]["low"]["value"] < block["before"]["mean"]["value"]
        assert block["before"]["mean"]["value"] < block["before"]["high"]["value"]
    assert hits >= 55
    assert covered / hits > 0.85


def test_short_histories_and_edge_shifts() -> None:
    short = mean_shift(_frame(_returns(200, 0.0, 1)), 252)
    assert short == {"status": "NOT_MEASURED", "reason": SHORT}
    # A slide over the last 24 returns: too little after it for two averages.
    edge = mean_shift(_frame(_returns(400, 0.0, 2, shift=-0.03, at=0.94)), 252)
    assert edge["status"] == "MEASURED" and edge["p_value"]["value"] <= 0.05
    assert edge["clear"] is False and edge["edge"] is True and "date" not in edge


def test_the_notes_have_spanish_and_portuguese_rules() -> None:
    for note in (NOTE, DATE_NOTE, MEAN_NOTE, SHORT):
        for locale in ("es", "pt"):
            assert localize(note, locale) != note, (locale, note)


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_wording_passes_the_guard(locale: str) -> None:
    labels = report.LABELS[locale]
    for key in KEYS:
        assert find_claims(labels[key]) == [], key
    assert find_claims(report.LOCKED_GAINS[locale]["shift"]) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("shift", [0.0, -0.004])
def test_the_report_shows_the_section(locale: str, shift: float) -> None:
    frame = _frame(_returns(800, 0.0, 7, shift=shift, at=0.6))
    result = run_audit(
        build_inputs(csv_bytes(frame), DeclaredMetadata(locale=locale)),
        now=NOW,
        audit_id="shift",
        bootstrap_samples=100,
    )
    block = result.model_dump(mode="json")["mean_shift"]
    assert block["clear"] is (shift != 0.0)
    assert untranslated(result.model_dump(mode="json")) == []
    page = render_html(result, watermark=False, locale=locale)
    labels = report.LABELS[locale]
    text = _text(page)
    assert labels["shift"] in text
    key = "shift_badge_changed" if shift else "shift_badge_steady"
    assert labels[key] in text
    assert find_claims(page) == []
