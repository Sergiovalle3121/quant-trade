"""Which prop firm's rules a history fits, and the best-day rule at the pass. Offline."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.analytics import simulate_challenge
from quant_trade.audit.engine import run_audit
from quant_trade.audit.firmfit import REPEATS, firm_fit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.prop_presets import PRESETS
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs


def _daily(seed: int = 3, n: int = 400) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.001, 0.008, n)


def test_best_day_rule_counts_passes_carried_by_one_big_day() -> None:
    rules = PRESETS["ftmo-1step"]
    assert rules.best_day_limit == 0.5 and rules.best_day_basis == "positive_days"
    calm = simulate_challenge(_daily(), rules, samples=500, seed=1)
    assert calm["best_day"]["breach_share_of_passes"]["value"] < 0.05
    # Mostly flat days and a rare jump of 8 %: a pass rests on one day.
    spiky = np.where(np.arange(400) % 50 == 0, 0.08, 0.0002)
    result = simulate_challenge(spiky, rules, samples=500, seed=1)
    assert result["probability"]["pass"]["value"] > 0.5
    assert result["best_day"]["breach_share_of_passes"]["value"] > 0.4
    within = result["best_day"]["pass_within"]["value"]
    assert within <= result["probability"]["pass"]["value"]


def test_topstep_limit_is_a_share_of_the_profit_target() -> None:
    rules = PRESETS["topstep-50k-combine"]
    assert rules.best_day_basis == "profit_target"
    # Every day +3.4 %: above 55 % of the 6 % target, so no pass keeps the rule.
    result = simulate_challenge(
        np.full(100, 0.034) + np.linspace(0, 1e-4, 100), rules, samples=200, seed=0
    )
    assert result["probability"]["pass"]["value"] == 1.0
    assert result["best_day"]["pass_within"]["value"] == 0.0


def test_presets_without_a_rule_report_none() -> None:
    result = simulate_challenge(_daily(), PRESETS["ftmo-2step-phase1"], samples=200, seed=0)
    assert "best_day" not in result


def test_a_limit_needs_its_basis() -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(PRESETS["ftmo-2step-phase1"], best_day_limit=0.5)


def test_programs_multiply_their_phases_and_rank_by_pass_odds() -> None:
    daily = _daily()
    fit = firm_fit(daily, samples=400, seed=7)
    assert fit["status"] == "MEASURED"
    rows = fit["firms"]
    passes = [row["pass"]["value"] for row in rows]
    assert passes == sorted(passes, reverse=True)
    assert all(row["firm"] != "Generic" for row in rows)
    ftmo = next(row for row in rows if row["program"] == "FTMO Challenge 2-Step")
    assert ftmo["phases"] == 2 and ftmo["keys"] == ["ftmo-2step-phase1", "ftmo-2step-phase2"]
    p1, p2 = (
        simulate_challenge(daily, PRESETS[key], samples=400, seed=7)["probability"]["pass"]["value"]
        for key in ftmo["keys"]
    )
    assert ftmo["pass"]["value"] == pytest.approx(p1 * p2)
    bootcamp = next(row for row in rows if row["program"] == "Bootcamp")
    assert bootcamp["phases"] == REPEATS["the5ers-bootcamp-step"] == 3
    one_step = next(row for row in rows if row["program"] == "FTMO Challenge 1-Step")
    assert one_step["pass_within_best_day"]["value"] <= one_step["pass"]["value"]
    assert "pass_within_best_day" not in ftmo


def test_too_few_days_is_not_measured() -> None:
    assert firm_fit(_daily(n=5), samples=100)["status"] == "NOT_MEASURED"


def _daily_csv() -> bytes:
    stamps = pd.bdate_range("2022-01-03", periods=500)
    equity = 10_000 * np.cumprod(1 + _daily(n=500))
    rows = [f"{s.date()},{v:.4f}" for s, v in zip(stamps, equity, strict=True)]
    return ("timestamp,equity\n" + "\n".join(rows) + "\n").encode()


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_report_shows_the_firm_table(locale: str) -> None:
    result = run_audit(
        build_inputs(_daily_csv(), DeclaredMetadata(locale=locale, challenge="ftmo-1step")),
        bootstrap_samples=200,
    )
    assert result.challenge is not None
    assert result.challenge["firm_fit"]["status"] == "MEASURED"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    assert labels["ff_clean"] in html and "Topstep · Trading Combine 50K" in html
    assert labels["best_day_line"].split("{")[0].replace("'", "&#x27;") in html
    assert untranslated(result.model_dump(mode="json")) == []
    for key in ("ff_title", "ff_intro", "ff_clean", "best_day_line"):
        assert find_claims(labels[key]) == [], key


def test_one_huge_day_carries_every_pass_past_the_best_day_rule() -> None:
    # Flat drift and a single +50 % day: any pass rests on that day.
    daily = np.r_[np.full(100, 0.0001), 0.5, np.full(100, 0.0001)]
    fit = firm_fit(daily, samples=300, seed=1)
    assert fit["status"] == "MEASURED"
    for row in fit["firms"]:
        assert 0.0 <= row["pass"]["value"] <= 1.0
        if "pass_within_best_day" in row:
            assert row["pass_within_best_day"]["value"] == 0.0
    result = simulate_challenge(daily, PRESETS["ftmo-1step"], samples=300, seed=1)
    if result["probability"]["pass"]["value"] > 0:
        assert result["best_day"]["breach_share_of_passes"]["value"] == 1.0


@pytest.mark.parametrize("daily", [np.zeros(200), np.full(5, 0.01)], ids=["flat", "short"])
def test_flat_or_short_histories_give_no_table_and_no_best_day(daily: np.ndarray) -> None:
    assert firm_fit(daily, samples=100)["status"] == "NOT_MEASURED"
    assert "best_day" not in simulate_challenge(daily, PRESETS["ftmo-1step"], samples=100)
