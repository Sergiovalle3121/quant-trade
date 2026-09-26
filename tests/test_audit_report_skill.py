"""The fund's split into cash, exposure to the benchmark and alpha, shown in
Spanish, English and Portuguese without claiming more than the numbers."""

from __future__ import annotations

import html
import re

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit import report
from quant_trade.audit.fund import compare_with_benchmark
from quant_trade.audit.guard import find_claims

LOCALES = ("es", "en", "pt")
ENGLISH_ONLY = re.compile(r"\b(the|benchmark's|months shared|cash rate was)\b")


def _index(seed: int, n: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.008, 0.045, n)


def _bench(fund: np.ndarray, index: np.ndarray, *, cash: bool = True) -> dict:
    months = pd.date_range("2014-01-31", periods=len(index), freq="ME")
    rates = (
        pd.Series(2.0, index=pd.date_range("2013-12-01", "2025-12-31", freq="B")) if cash else None
    )
    return compare_with_benchmark(
        pd.Series(fund, index=months), pd.Series(index, index=months), "upload", rates
    )


def _shown(bench: dict, locale: str) -> str:
    page = report._fund_benchmark_html(
        {"benchmark": bench, "net_of_fees": True}, locale, report.LABELS[locale]
    )
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


@pytest.mark.parametrize("locale", LOCALES)
def test_the_split_adds_up_and_speaks_the_readers_language(locale: str) -> None:
    index = _index(17, 60)
    bench = _bench(0.9 * index + 0.002 + np.random.default_rng(3).normal(0, 0.01, 60), index)
    assert bench["skill"]["status"] == "MEASURED"
    labels = report.LABELS[locale]
    shown = _shown(bench, locale)
    for key in ("skill_title", "skill_cash", "skill_alpha", "skill_total"):
        assert labels[key].split("(")[0].strip() in shown
    parts = bench["skill"]["attribution"]
    total = parts["cash"]["value"] + parts["exposure"]["value"] + parts["alpha"]["value"]
    assert total == pytest.approx(parts["total"]["value"])
    # The plain alpha (no cash) gives way to the split's alpha after cash.
    assert labels["alpha_line"].split(":")[0] not in shown
    assert find_claims(shown) == []
    if locale != "en":
        assert not ENGLISH_ONLY.search(shown), shown


def test_months_needed_says_it_is_no_promise() -> None:
    index = _index(20, 48)
    fund = 0.8 * index + 0.002 + np.random.default_rng(120).normal(0, 0.02, 48)
    bench = _bench(fund, index)
    needed = bench["skill"]["months_needed"]
    assert needed["evidence"] == "MEASURED"
    shown = _shown(bench, "es")
    assert f"unos {needed['value']} meses" in shown and "no una promesa" in shown


def test_a_record_that_would_need_decades_says_so_in_years() -> None:
    rng = np.random.default_rng(9)
    index = _index(10, 121)
    true = index + rng.normal(0, 0.01, 121)
    bench = _bench(0.5 * true[1:] + 0.5 * true[:-1], index[1:])
    assert bench["skill"]["months_needed"]["value"] > report.NEEDED_MONTHS_SHOWN
    for locale in LOCALES:
        shown = _shown(bench, locale)
        assert report.LABELS[locale]["skill_needed_long"][:30] in shown


def test_a_smoothed_fund_shows_the_late_exposure() -> None:
    rng = np.random.default_rng(9)
    index = _index(10, 121)
    true = index + rng.normal(0, 0.01, 121)
    reported = 0.5 * true[1:] + 0.5 * true[:-1]
    shown = _shown(_bench(reported, index[1:]), "es")
    assert "Dimson" in shown and "un mes de retraso" in shown


def test_timing_shows_only_when_it_clears_two_errors() -> None:
    index = _index(11, 120)
    timed = np.where(index > 0, 1.3, 0.7) * index + np.random.default_rng(12).normal(0, 0.005, 120)
    assert "Treynor" in _shown(_bench(timed, index), "es")
    plain = 0.9 * index + np.random.default_rng(13).normal(0, 0.01, 120)
    bench = _bench(plain, index)
    if abs(bench["skill"]["timing"]["gamma_t_stat"]["value"]) < 2:
        assert "Treynor" not in _shown(bench, "es")


@pytest.mark.parametrize("locale", LOCALES)
def test_without_cash_the_intro_says_zero_was_used(locale: str) -> None:
    index = _index(17, 48)
    bench = _bench(0.9 * index, index, cash=False)
    shown = _shown(bench, locale)
    assert report.LABELS[locale]["skill_intro_no_cash"].format(n=48)[:40] in shown


@pytest.mark.parametrize("locale", LOCALES)
def test_a_short_record_says_why_there_is_no_split(locale: str) -> None:
    index = _index(17, 30)
    bench = _bench(0.9 * index + np.random.default_rng(5).normal(0, 0.01, 30), index)
    assert bench["skill"]["status"] == "NOT_MEASURED"
    shown = _shown(bench, locale)
    assert report.LABELS[locale]["skill_nm"].split(":")[0] in shown
    # The plain alpha still shows when the split is not measured.
    assert report.LABELS[locale]["alpha_line"].split(":")[0] in shown
    if locale != "en":
        assert "fewer than" not in shown
