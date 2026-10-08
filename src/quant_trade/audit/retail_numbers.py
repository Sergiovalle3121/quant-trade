"""Declared teaching examples for articles, separate from audit measurements.

The calculator and luck modules concern Sharpe, not binary wins or challenge
attempts. These small textbook examples cannot be presented as their output.
They do not change the engine, report, challenge simulator, or any criterion.
Every displayed result must retain DECLARED and the article's assumptions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from quant_trade.audit.prop_presets import get_preset

SIGNAL_DECLARED_WIN_RATE = 0.60
COIN_TRADE_COUNT = 100
COIN_NULL_WIN_RATE = 0.50
COIN_THRESHOLD_WIN_RATE = 0.58


def normal_coin_tail_probability(
    trades: int, null_win_rate: float, threshold_win_rate: float
) -> float:
    """Normal approximation to P(X >= ceil(n * threshold)), corrected by 0.5.

    Assumes independent Bernoulli outcomes; ignores payoffs, dependence, costs,
    selection and model error. It is not a probability of skill or a power test.
    """
    if trades < 1 or not 0 < null_win_rate < 1 or not 0 < threshold_win_rate <= 1:
        raise ValueError("positive count and valid win rates required")
    wins = math.ceil(trades * threshold_win_rate - 1e-12)
    mean = trades * null_win_rate
    deviation = math.sqrt(trades * null_win_rate * (1 - null_win_rate))
    z_score = (wins - 0.5 - mean) / deviation
    return 0.5 * math.erfc(z_score / math.sqrt(2))


COIN_NORMAL_TAIL = normal_coin_tail_probability(
    COIN_TRADE_COUNT, COIN_NULL_WIN_RATE, COIN_THRESHOLD_WIN_RATE
)

PROP_RULES = get_preset("generic-2step-phase1")
PROP_WIN_RATES = (0.45, 0.55)
PROP_RISKS = (0.005, 0.01)
PROP_STREAK_LENGTH = 5


@dataclass(frozen=True)
class DeclaredAttemptExample:
    win_rate: float
    risk: float
    target_probability: float
    expected_attempts: float


def declared_attempt_example(win_rate: float, risk: float) -> DeclaredAttemptExample:
    """A fixed-stake absorbing walk using the generic preset's static limits.

    Independent steps are +risk or -risk of initial balance, one per day, with
    equal win/loss magnitude, no costs and unlimited time. Touching the loss
    limit ends a path (conservative relative to the simulator's strict breach).
    The target and loss barriers must be integer multiples of the stake. The
    earliest possible target must also satisfy the preset's minimum-day rule.
    An expected count of independent identical restarts is 1 / target_probability;
    this is not a quantile, budget, forecast, or the full multi-phase evaluation.
    """
    if not 0 < win_rate < 1 or not math.isfinite(risk) or risk <= 0:
        raise ValueError("win rate in (0, 1) and positive finite risk required")
    if PROP_RULES.max_daily_loss is None or risk >= PROP_RULES.max_daily_loss:
        raise ValueError("daily stake must stay below the generic daily limit")
    loss_steps = PROP_RULES.max_total_loss / risk
    target_steps = PROP_RULES.profit_target / risk
    if not all(math.isclose(value, round(value)) for value in (loss_steps, target_steps)):
        raise ValueError("barriers must be integer multiples of risk")
    if target_steps < PROP_RULES.min_trading_days:
        raise ValueError("earliest target would precede minimum trading days")
    start = round(loss_steps)
    width = start + round(target_steps)
    if math.isclose(win_rate, 0.5, abs_tol=1e-12):
        probability = start / width
    else:
        log_ratio = math.log((1 - win_rate) / win_rate)
        # A bounded expression also works when adverse drift makes the odds tiny.
        if log_ratio > 0:
            probability = (
                math.exp(-(width - start) * log_ratio)
                * -math.expm1(-start * log_ratio)
                / -math.expm1(-width * log_ratio)
            )
        else:
            probability = math.expm1(start * log_ratio) / math.expm1(width * log_ratio)
    attempts = 1 / probability if probability else math.inf
    return DeclaredAttemptExample(win_rate, risk, probability, attempts)


PROP_ATTEMPT_EXAMPLES = tuple(
    declared_attempt_example(win_rate, risk) for win_rate in PROP_WIN_RATES for risk in PROP_RISKS
)
