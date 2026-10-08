"""Offline arithmetic checks for declared article examples, never audit metrics."""

from __future__ import annotations

import math

import pytest

from quant_trade.audit.prop_presets import get_preset
from quant_trade.audit.retail_numbers import (
    COIN_NORMAL_TAIL,
    COIN_NULL_WIN_RATE,
    COIN_THRESHOLD_WIN_RATE,
    COIN_TRADE_COUNT,
    PROP_ATTEMPT_EXAMPLES,
    PROP_RISKS,
    PROP_RULES,
    PROP_WIN_RATES,
    declared_attempt_example,
    normal_coin_tail_probability,
)


def test_coin_example_matches_continuity_corrected_normal_and_binomial() -> None:
    probability = COIN_NORMAL_TAIL
    assert probability == pytest.approx(0.06680720126885809)
    threshold = math.ceil(COIN_TRADE_COUNT * COIN_THRESHOLD_WIN_RATE - 1e-12)
    exact = sum(
        math.comb(COIN_TRADE_COUNT, wins)
        * COIN_NULL_WIN_RATE**wins
        * (1 - COIN_NULL_WIN_RATE) ** (COIN_TRADE_COUNT - wins)
        for wins in range(threshold, COIN_TRADE_COUNT + 1)
    )
    assert abs(COIN_NORMAL_TAIL - exact) < 0.001
    assert round(COIN_NORMAL_TAIL * 100) == 7


@pytest.mark.parametrize("args", [(0, 0.5, 0.58), (100, 1, 0.58), (100, 0.5, 0)])
def test_coin_example_rejects_invalid_inputs(args: tuple[int, float, float]) -> None:
    with pytest.raises(ValueError):
        normal_coin_tail_probability(*args)


def test_challenge_uses_the_imported_generic_rules_and_all_four_combinations() -> None:
    assert PROP_RULES is get_preset("generic-2step-phase1")
    assert {(case.win_rate, case.risk) for case in PROP_ATTEMPT_EXAMPLES} == {
        (rate, risk) for rate in PROP_WIN_RATES for risk in PROP_RISKS
    }
    assert PROP_RULES.total_loss_type == "static"
    assert PROP_RULES.time_limit_days is None
    assert PROP_RULES.best_day_limit is None


def test_attempt_example_matches_symmetric_barrier_identity_and_fair_walk() -> None:
    # Symmetric barriers give expected attempts 1 + ((1-p)/p)**distance.
    # This identity is independent of the helper's general absorbing-walk formula.
    for case in PROP_ATTEMPT_EXAMPLES:
        distance = PROP_RULES.profit_target / case.risk
        expected = 1 + ((1 - case.win_rate) / case.win_rate) ** distance
        assert case.expected_attempts == pytest.approx(expected)
        assert case.target_probability * case.expected_attempts == pytest.approx(1)
        fair = declared_attempt_example(0.5, case.risk)
        assert fair.target_probability == 0.5
        assert fair.expected_attempts == 2
    adverse = [c.expected_attempts for c in PROP_ATTEMPT_EXAMPLES if c.win_rate < 0.5]
    favorable = [c.expected_attempts for c in PROP_ATTEMPT_EXAMPLES if c.win_rate > 0.5]
    assert min(adverse) > max(favorable)


@pytest.mark.parametrize(
    "args",
    [(0, 0.01), (1, 0.01), (0.55, -0.01), (0.55, 0.05), (0.55, 0.003), (0.55, math.inf)],
)
def test_attempt_example_rejects_unsupported_assumptions(args: tuple[float, float]) -> None:
    with pytest.raises(ValueError):
        declared_attempt_example(*args)
