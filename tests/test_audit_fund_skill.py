"""Skill or market exposure: attribution, lagged beta, timing and the alpha's range."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit import skill
from quant_trade.audit.cashrate import annual_yield
from quant_trade.audit.fund import compare_with_benchmark
from quant_trade.audit.i18n import spanish
from quant_trade.audit.skill import monthly_cash, skill_review


def _index(seed: int, n: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.008, 0.045, n)


def test_the_three_parts_add_up_to_the_funds_average() -> None:
    index = _index(1, 72)
    fund = 0.002 + 0.8 * index + np.random.default_rng(2).normal(0, 0.01, 72)
    cash = np.full(72, 0.003)
    out = skill_review(fund, index, cash)
    parts = out["attribution"]
    total = parts["cash"]["value"] + parts["exposure"]["value"] + parts["alpha"]["value"]
    assert total == pytest.approx(parts["total"]["value"])
    assert parts["total"]["value"] == pytest.approx(float(fund.mean()) * 12.0)


def test_the_fit_matches_least_squares_on_excess_returns() -> None:
    index = _index(3, 60)
    fund = 0.001 + 1.1 * index + np.random.default_rng(4).normal(0, 0.01, 60)
    cash = np.linspace(0.001, 0.004, 60)
    out = skill_review(fund, index, cash)
    y, x = fund - cash, index - cash
    design = np.column_stack([np.ones(60), x])
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    assert out["alpha"]["value"] == pytest.approx(coef[0] * 12.0)
    assert out["beta"]["value"] == pytest.approx(coef[1])
    square = np.linalg.lstsq(np.column_stack([design, x**2]), y, rcond=None)[0]
    assert out["timing"]["gamma"]["value"] == pytest.approx(square[2])


def test_leaving_cash_out_moves_the_alpha_by_one_minus_beta_times_cash() -> None:
    index = _index(5, 60)
    fund = 0.5 * index + np.random.default_rng(6).normal(0, 0.005, 60)
    cash = np.full(60, 0.004)
    with_cash = skill_review(fund, index, cash)["alpha"]["value"]
    without = skill_review(fund, index, None)["alpha"]["value"]
    beta = skill_review(fund, index, cash)["beta"]["value"]
    assert without - with_cash == pytest.approx((1.0 - beta) * 0.004 * 12.0, rel=1e-6)


def test_without_cash_the_note_says_zero_was_used() -> None:
    out = skill_review(_index(7, 48), _index(8, 48), None)
    assert out["cash_basis"]["source"] is None
    assert out["cash_basis"]["note"] == skill.NO_CASH_NOTE


def test_a_smoothed_fund_shows_its_exposure_only_with_the_lag() -> None:
    rng = np.random.default_rng(9)
    index = _index(10, 121)
    true = index + rng.normal(0, 0.01, 121)
    reported = 0.5 * true[1:] + 0.5 * true[:-1]
    out = skill_review(reported, index[1:])
    assert out["beta"]["value"] < 0.65
    assert out["lagged"]["beta"]["value"] == pytest.approx(1.0, abs=0.1)
    assert out["lagged"]["lag_t_stat"]["value"] > 2


def test_a_fund_that_adds_exposure_before_rises_shows_positive_timing() -> None:
    index = _index(11, 120)
    fund = np.where(index > 0, 1.3, 0.7) * index + np.random.default_rng(12).normal(0, 0.005, 120)
    out = skill_review(fund, index)
    assert out["timing"]["gamma"]["value"] > 0
    assert out["timing"]["gamma_t_stat"]["value"] > 2


@pytest.mark.parametrize("smoothing", [0.0, 0.4])
def test_funds_with_no_skill_seldom_show_an_alpha_two_errors_from_zero(smoothing: float) -> None:
    runs = 300
    hits = 0
    for seed in range(runs):
        rng = np.random.default_rng(seed)
        index = rng.normal(0.008, 0.045, 60)
        misses = rng.normal(0, 0.02, 60)
        for i in range(1, 60):
            misses[i] += smoothing * misses[i - 1]
        out = skill_review(0.9 * index + misses, index)
        hits += abs(out["alpha_t_stat"]["value"]) > 2
    # Nominal 5 %; Newey-West alone gave about 7 % and 12 % here.
    assert hits / runs < 0.09


def test_the_alpha_range_contains_the_alpha_and_months_needed_grows_with_noise() -> None:
    index = _index(13, 60)
    rng = np.random.default_rng(14)
    quiet = skill_review(0.002 + index + rng.normal(0, 0.01, 60), index)
    noisy = skill_review(0.002 + index + rng.normal(0, 0.04, 60), index)
    for out in (quiet, noisy):
        assert out["alpha_range"]["low"]["value"] < out["alpha"]["value"]
        assert out["alpha"]["value"] < out["alpha_range"]["high"]["value"]
    needed = [
        out["months_needed"].get("value") for out in (quiet, noisy) if out["alpha"]["value"] > 0
    ]
    if len(needed) == 2 and None not in needed:
        assert needed[0] <= needed[1]


def test_a_beta_that_is_only_noise_gets_no_confident_share() -> None:
    index = _index(15, 48)
    fund = 0.01 + np.random.default_rng(16).normal(0, 0.03, 48)
    out = skill_review(fund, index)
    assert abs(out["beta_t_stat"]["value"]) < 2
    share = out["attribution"]["exposure_share"]
    assert share["evidence"] == "NOT_MEASURED"
    assert share["note"] == skill.NO_CLEAR_EXPOSURE


@pytest.mark.parametrize(
    ("fund", "index", "reason"),
    [
        (np.zeros(20), np.linspace(-0.01, 0.01, 20), skill.TOO_FEW),
        (np.linspace(0, 0.01, 40), np.full(40, 0.01), skill.FLAT),
        (np.linspace(0, 0.01, 40), np.tile([0.01, -0.01], 20), skill.SINGULAR),
    ],
)
def test_short_flat_or_two_valued_benchmarks_are_not_measured(
    fund: np.ndarray, index: np.ndarray, reason: str
) -> None:
    out = skill_review(fund, index)
    assert out == {"status": "NOT_MEASURED", "reason": reason}


def test_monthly_cash_uses_the_months_mean_yield_over_its_real_days() -> None:
    days = pd.date_range("2023-01-02", "2023-03-31", freq="B")
    rates = pd.Series(5.0, index=days)
    months = pd.period_range("2023-01", "2023-03", freq="M")
    cash = monthly_cash(rates, months)
    assert cash is not None
    yearly = float(annual_yield(np.array([0.05]))[0])
    expected = [(1 + yearly) ** (d / 365) - 1 for d in (31, 28, 31)]
    assert cash == pytest.approx(expected)


def test_monthly_cash_is_none_when_a_month_has_no_rate() -> None:
    rates = pd.Series(5.0, index=pd.date_range("2023-01-02", "2023-01-31", freq="B"))
    months = pd.period_range("2023-01", "2023-02", freq="M")
    assert monthly_cash(rates, months) is None
    assert monthly_cash(None, months) is None


def test_the_fund_comparison_carries_the_skill_block() -> None:
    months = pd.date_range("2018-01-31", periods=48, freq="ME")
    index = pd.Series(_index(17, 48), index=months)
    fund = pd.Series(0.9 * index.to_numpy() + 0.001, index=months)
    rates = pd.Series(2.0, index=pd.date_range("2017-12-01", "2022-01-31", freq="B"))
    review = compare_with_benchmark(fund, index, "upload", rates)
    assert review["skill"]["status"] == "MEASURED"
    assert review["skill"]["cash_basis"]["source"] == "DTB3"


def test_every_skill_sentence_has_a_spanish_rule() -> None:
    texts = [
        value
        for name, value in vars(skill).items()
        if name.isupper() and isinstance(value, str) and " " in value
    ]
    assert texts
    assert [text for text in texts if spanish(text) is None] == []
