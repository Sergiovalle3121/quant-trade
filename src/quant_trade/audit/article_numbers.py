"""Declared figures for the resampling, streak, consistency, trailing and ruin articles.

Every figure here comes from the engine's own functions on inputs fixed in
this module: ``streaks.longest_run_tail`` for the losing-streak table and
``analytics.drawdown_risk`` and ``analytics.shuffled_drawdown`` for the
resampling example. The synthetic series are drawn with NumPy from the seeds
below, and both resampling functions take an explicit seed, so running this
module again gives the same numbers byte for byte (the tests do exactly that).
The best-day and trailing examples use ``challenge_calc.compute`` with declared
inputs; their source-dated rule rows come directly from ``prop_presets.PRESETS``.
The ruin examples use ``ruin_calc.compute`` unchanged, and their sample-size
comparison uses the same ``winrate.read`` as the win-rate calculator.

None of it is a measurement of a client's file: every displayed figure keeps
DECLARED and the assumption it rests on. Nothing here changes the engine, a
threshold, the report or the class.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache
from typing import Any

import numpy as np

from quant_trade.audit import ruin_calc, winrate
from quant_trade.audit.analytics import (
    SHUFFLE_SAMPLES,
    SHUFFLE_SEED,
    drawdown_risk,
    shuffled_drawdown,
)
from quant_trade.audit.challenge_calc import ChallengeInput, compute
from quant_trade.audit.prop_presets import PRESETS, BestDayBasis, TotalLossType
from quant_trade.audit.public_card import PublicClaim
from quant_trade.audit.streaks import RARE, longest_run_tail

# ---------------------------------------------------------------------------
# Losing streaks: independent trades that lose with a fixed probability
# ---------------------------------------------------------------------------

#: Win rates and trade counts of the table; each trade loses with ``1 - win_rate``.
STREAK_WIN_RATES: tuple[float, ...] = (0.45, 0.50, 0.55, 0.60)
STREAK_TRADE_COUNTS: tuple[int, ...] = (100, 200, 500)
#: "Median" streak: the longest run reached with at least this probability,
#: the same cut ``streaks.loss_streak_review`` uses for its typical run.
STREAK_MEDIAN = 0.5
#: "One in twenty": ``streaks.RARE``, the report's own cut.
STREAK_RARE = RARE
#: Longest run the tail is computed for: far past every row's one-in-twenty run.
STREAK_MAX_RUN = 60
#: Declared stakes for the prop-firm paragraph: a fixed loss per trade, as a
#: share of the initial balance (no compounding, no costs).
STREAK_RISKS: tuple[float, ...] = (0.005, 0.01)
#: The row the prose reads aloud.
STREAK_EXAMPLE = (0.50, 200)


@dataclass(frozen=True)
class StreakRow:
    win_rate: float
    trades: int
    #: Longest k with P(longest losing run >= k) >= ``STREAK_MEDIAN``.
    median_run: int
    #: Longest k with P(longest losing run >= k) >= ``STREAK_RARE``.
    rare_run: int
    #: P(longest losing run >= ``rare_run``): at least ``STREAK_RARE``, often more.
    rare_chance: float


def streak_row(win_rate: float, trades: int, max_run: int = STREAK_MAX_RUN) -> StreakRow:
    """The median and one-in-twenty longest losing runs, exactly, for one row."""
    if not 0 < win_rate < 1 or trades < 1:
        raise ValueError("a win rate in (0, 1) and a positive trade count are required")
    tail = longest_run_tail(trades, 1.0 - win_rate, max_run)
    if tail[-1] >= STREAK_RARE:
        raise ValueError("max_run is too short to reach the one-in-twenty run")
    median = int(np.max(np.nonzero(tail >= STREAK_MEDIAN)[0]))
    rare = int(np.max(np.nonzero(tail >= STREAK_RARE)[0]))
    return StreakRow(
        win_rate=win_rate,
        trades=trades,
        median_run=median,
        rare_run=rare,
        rare_chance=float(tail[rare]),
    )


STREAK_ROWS: tuple[StreakRow, ...] = tuple(
    streak_row(win_rate, trades) for win_rate in STREAK_WIN_RATES for trades in STREAK_TRADE_COUNTS
)
_STREAKS_BY_ROW = {(row.win_rate, row.trades): row for row in STREAK_ROWS}


def streak_for(win_rate: float, trades: int) -> StreakRow:
    """The table's row for ``win_rate`` and ``trades``."""
    return _STREAKS_BY_ROW[(win_rate, trades)]


# ---------------------------------------------------------------------------
# Monte Carlo: one synthetic backtest, and the best of a search without edge
# ---------------------------------------------------------------------------

#: The synthetic backtest: normal daily returns, drawn once from this seed.
MC_SERIES_SEED = 20261008
MC_SERIES_DAYS = 500
MC_SERIES_MEAN = 0.0005
MC_SERIES_SD = 0.01
MC_PERIODS_PER_YEAR = 252.0
#: The report's own settings: ``engine.RISK_SAMPLES`` one-year paths and
#: ``run_audit``'s default seed (kept in step by a test).
MC_RISK_SAMPLES = 2000
MC_RISK_SEED = 12345
#: The order comparison runs with its own defaults, as in the report.
MC_SHUFFLE_SAMPLES = SHUFFLE_SAMPLES
MC_SHUFFLE_SEED = SHUFFLE_SEED
#: The search: zero-mean series (no edge by construction); the one with the
#: highest final result is kept, as an optimiser keeps its best pass.
MC_SEARCH_SEED = 20261009
MC_SEARCH_SERIES = 100
MC_SEARCH_DAYS = 250
#: The same zero-mean generator observed for much longer, as the reference.
MC_REFERENCE_SEED = 20261010
MC_REFERENCE_DAYS = 5000
#: The drawdown the example reads (one of ``analytics.DRAWDOWN_THRESHOLDS``).
MC_THRESHOLD = 0.10
MC_DEEP_THRESHOLD = 0.20


def synthetic_series() -> np.ndarray:
    """The example backtest's daily returns."""
    rng = np.random.default_rng(MC_SERIES_SEED)
    return rng.normal(MC_SERIES_MEAN, MC_SERIES_SD, MC_SERIES_DAYS)


def search_best_series() -> np.ndarray:
    """The best final result among ``MC_SEARCH_SERIES`` zero-mean series."""
    rng = np.random.default_rng(MC_SEARCH_SEED)
    series = rng.normal(0.0, MC_SERIES_SD, (MC_SEARCH_SERIES, MC_SEARCH_DAYS))
    final = np.prod(1.0 + series, axis=1) - 1.0
    return series[int(np.argmax(final))]


def reference_series() -> np.ndarray:
    """A long stretch of the same zero-mean generator."""
    rng = np.random.default_rng(MC_REFERENCE_SEED)
    return rng.normal(0.0, MC_SERIES_SD, MC_REFERENCE_DAYS)


def resampled_risk(returns: np.ndarray) -> dict[str, Any]:
    """``analytics.drawdown_risk`` with the report's samples and seed, one year ahead."""
    return drawdown_risk(
        returns,
        periods_per_year=MC_PERIODS_PER_YEAR,
        samples=MC_RISK_SAMPLES,
        seed=MC_RISK_SEED,
    )


@dataclass(frozen=True)
class RiskSummary:
    """The figures the article prints from one ``drawdown_risk`` result."""

    median: float
    p95: float
    at_least: float
    at_least_deep: float
    block: float
    samples: int
    horizon: int


def risk_summary(risk: dict[str, Any]) -> RiskSummary:
    if risk.get("method") is None:
        raise ValueError("the example series must be long enough to resample")
    chances = risk["probability_drawdown_at_least"]
    return RiskSummary(
        median=float(risk["max_drawdown"]["p50"]["value"]),
        p95=float(risk["max_drawdown"]["p95"]["value"]),
        at_least=float(chances[f"{MC_THRESHOLD:.2f}"]["value"]),
        at_least_deep=float(chances[f"{MC_DEEP_THRESHOLD:.2f}"]["value"]),
        block=float(risk["method"]["expected_block_size"]),
        samples=int(risk["method"]["samples"]),
        horizon=int(risk["method"]["horizon_periods"]),
    )


@dataclass(frozen=True)
class ShuffleSummary:
    """The uploaded order's deepest fall against random orders, as positive sizes."""

    observed: float
    low: float
    median: float
    high: float
    samples: int
    position: str


def shuffle_summary(returns: np.ndarray) -> ShuffleSummary:
    result = shuffled_drawdown(returns, samples=MC_SHUFFLE_SAMPLES, seed=MC_SHUFFLE_SEED)
    if result["status"] != "MEASURED":
        raise ValueError(result.get("reason", "the order comparison was not measured"))
    spread = result["shuffled"]
    # Drawdowns come back as negative fractions; the article prints fall sizes.
    return ShuffleSummary(
        observed=-float(result["observed"]["value"]),
        low=-float(spread["p5"]["value"]),
        median=-float(spread["p50"]["value"]),
        high=-float(spread["p95"]["value"]),
        samples=int(result["method"]["samples"]),
        position=str(result["position"]),
    )


MC_SHUFFLE = shuffle_summary(synthetic_series())
MC_RISK = risk_summary(resampled_risk(synthetic_series()))
MC_SEARCH_RISK = risk_summary(resampled_risk(search_best_series()))
MC_REFERENCE_RISK = risk_summary(resampled_risk(reference_series()))


# ---------------------------------------------------------------------------
# Best-day consistency: the calculator's declared single-phase examples
# ---------------------------------------------------------------------------

CONSISTENCY_INPUTS: tuple[ChallengeInput, ...] = (
    ChallengeInput(
        win_rate_pct=50.0,
        unit="r",
        avg_win=1.5,
        avg_loss=1.0,
        risk=0.5,
        per_day=3.0,
        program="myfundedfutures-rapid-eod-50k",
    ),
    ChallengeInput(
        win_rate_pct=50.0,
        unit="r",
        avg_win=1.5,
        avg_loss=1.0,
        risk=0.5,
        per_day=3.0,
        program="myfundedfutures-builder-50k",
    ),
)
CONSISTENCY_VARIATION_INPUTS: tuple[ChallengeInput, ...] = (
    CONSISTENCY_INPUTS[0],
    replace(CONSISTENCY_INPUTS[0], per_day=1.0),
    replace(CONSISTENCY_INPUTS[0], risk=0.25),
)


@dataclass(frozen=True)
class ConsistencyRuleRow:
    """A published preset's best-day rule, with the page it was read from and the date.

    ``source_url`` is the preset's ``best_day_source_url`` when the firm states the
    rule on a page other than the program's general source.
    """

    key: str
    firm: str
    program: str
    limit: float
    basis: BestDayBasis
    source_url: str
    as_of: str


def consistency_rules() -> tuple[ConsistencyRuleRow, ...]:
    """Every published preset with a best-day rule, in preset order."""
    return tuple(
        ConsistencyRuleRow(
            key=key,
            firm=rules.firm,
            program=rules.program,
            limit=rules.best_day_limit,
            basis=rules.best_day_basis,
            source_url=rules.best_day_source_url or rules.source_url,
            as_of=rules.as_of,
        )
        for key, rules in PRESETS.items()
        if rules.source_url.startswith("https://")
        and rules.best_day_limit is not None
        and rules.best_day_basis is not None
    )


@dataclass(frozen=True)
class ConsistencyExample:
    """Calculator outputs on synthetic inputs, never measured client evidence.

    ``within_best_day`` is a subset of ``target``, assessed when a path first
    reaches the target after its required minimum days. The engine does not
    continue those paths to try to dilute a best-day excess. ``median_days``
    includes every target-reaching path, not only the subset inside the rule.
    """

    inputs: ChallengeInput
    target: float
    within_best_day: float | None
    daily_limit: float
    total_limit: float
    unfinished: float
    median_days: float | None
    horizon: int
    samples: int
    synthetic_days: int
    seed: int
    block_size: float
    #: Best-day cap in initial-balance units, only for a target-based rule.
    target_rule_cap: float | None
    #: Largest synthetic day's gain when the day starts at the initial balance.
    maximum_initial_day_gain: float
    #: Worst synthetic day's loss, as a positive share of the initial balance.
    maximum_initial_day_loss: float
    evidence: str = "DECLARED"


@lru_cache(maxsize=8)
def consistency_example(inputs: ChallengeInput) -> ConsistencyExample:
    """Read a single-phase example from ``challenge_calc.compute`` unchanged.

    Trading days compound the balance. Synthetic trades use a fixed win rate
    and fixed win/loss sizes, without separately modelled fees or slippage.
    The selected programs have other rule differences, so their comparison
    is descriptive; it does not isolate the effect of removing one rule.
    """
    reading = compute(inputs)
    run = reading.declared
    if len(run.phases) != 1 or not run.measured:
        raise ValueError("the consistency example needs one simulated phase")
    _, phase = run.phases[0]
    method = phase["method"]
    outcome = run.outcome
    within = outcome.get("pass_within_best_day")
    median = phase["days_to_target"]["p50"].get("value")
    rules = PRESETS[inputs.program]
    cap = (
        rules.profit_target * rules.best_day_limit
        if rules.best_day_basis == "profit_target" and rules.best_day_limit is not None
        else None
    )
    return ConsistencyExample(
        inputs=inputs,
        target=float(outcome["pass"]["value"]),
        within_best_day=None if within is None else float(within["value"]),
        daily_limit=float(outcome["fail_daily_loss"]["value"]),
        total_limit=float(outcome["fail_total_loss"]["value"]),
        unfinished=float(outcome["unfinished"]["value"]),
        median_days=None if median is None else float(median),
        horizon=int(method["horizon_business_days"]),
        samples=int(method["samples"]),
        synthetic_days=int(method["observations"]),
        seed=int(method["seed"]),
        block_size=float(method["expected_block_size"]),
        target_rule_cap=cap,
        maximum_initial_day_gain=float(np.max(run.daily)),
        maximum_initial_day_loss=float(-np.min(run.daily)),
    )


def consistency_examples() -> tuple[ConsistencyExample, ...]:
    return tuple(consistency_example(inputs) for inputs in CONSISTENCY_INPUTS)


def consistency_variations() -> tuple[ConsistencyExample, ...]:
    return tuple(consistency_example(inputs) for inputs in CONSISTENCY_VARIATION_INPUTS)


# ---------------------------------------------------------------------------
# Maximum loss: the same declared history under three existing program types
# ---------------------------------------------------------------------------

#: One single-phase program per supported loss type. Targets, loss allowances,
#: minimum days and best-day rules also differ: this is not a controlled test
#: of the loss type alone. No intraday-high program is represented as an EOD one.
TRAILING_INPUTS: tuple[ChallengeInput, ...] = tuple(
    ChallengeInput(
        win_rate_pct=50.0,
        unit="r",
        avg_win=1.5,
        avg_loss=1.0,
        risk=0.5,
        per_day=3.0,
        program=key,
    )
    for key in ("fundednext-stellar-1step", "ftmo-1step", "topstep-50k-combine")
)

#: An editorial selection only; every amount, type, source and date is read
#: from PRESETS. There are no intraday-high evaluation presets in that catalog.
TRAILING_RULE_KEYS: tuple[str, ...] = (
    "ftmo-2step-phase1",
    "fundednext-stellar-1step",
    "fundingpips-1step-flex",
    "ftmo-1step",
    "e8-zero-100k",
    "myfundedfutures-rapid-50k",
    "topstep-50k-combine",
    "e8-signature-100k",
    "take-profit-trader-test-50k",
)


@dataclass(frozen=True)
class TrailingRuleRow:
    """A preset's modelled maximum-loss rule, with its original caveats.

    ``limit`` is a share of the initial balance. ``loss_type`` describes the
    simulator's rule; notes preserve any difference from the firm's wording.
    """

    key: str
    firm: str
    program: str
    limit: float
    loss_type: TotalLossType
    source_url: str
    as_of: str
    notes: tuple[str, ...]


def trailing_rules() -> tuple[TrailingRuleRow, ...]:
    """Three source-dated examples per supported loss type, without new rules."""
    return tuple(
        TrailingRuleRow(
            key=key,
            firm=rules.firm,
            program=rules.program,
            limit=rules.max_total_loss,
            loss_type=rules.total_loss_type,
            source_url=rules.source_url,
            as_of=rules.as_of,
            notes=rules.notes,
        )
        for key in TRAILING_RULE_KEYS
        for rules in (PRESETS[key],)
    )


@dataclass(frozen=True)
class TrailingCaveatRow:
    """An unchanged preset note on approximation, monitoring or another stage."""

    key: str
    firm: str
    program: str
    note: str
    source_url: str
    as_of: str


#: Prefixes select complete existing notes; they do not recreate their copy.
#: A changed note fails visibly instead of silently removing a limitation.
_TRAILING_CAVEATS: tuple[tuple[str, str], ...] = (
    ("ftmo-1step", "Maximum loss is an end-of-day trailing limit;"),
    ("e8-zero-100k", "The maximum loss trails the highest end-of-day balance;"),
    (
        "myfundedfutures-rapid-50k",
        "The maximum loss trails the highest end-of-day balance and locks",
    ),
    ("myfundedfutures-rapid-50k", "Only the evaluation is simulated;"),
    ("topstep-50k-combine", "Maximum loss trails the highest end-of-day balance"),
    ("take-profit-trader-test-50k", "The maximum-loss floor moves only at the day's close,"),
    ("earn2trade-tcp-25k", "The maximum-loss floor moves only at the day's close,"),
)


def trailing_caveats() -> tuple[TrailingCaveatRow, ...]:
    """Quote the catalog without confusing an EOD floor with EOD-only monitoring.

    The Rapid note names intraday trailing in the Sim Funded stage, which the
    evaluation preset does not simulate. Its evaluation amount must not be
    presented as the amount of that other stage.
    """
    return tuple(
        TrailingCaveatRow(
            key=key,
            firm=rules.firm,
            program=rules.program,
            note=next(note for note in rules.notes if note.startswith(prefix)),
            source_url=rules.source_url,
            as_of=rules.as_of,
        )
        for key, prefix in _TRAILING_CAVEATS
        for rules in (PRESETS[key],)
    )


@lru_cache(maxsize=3)
def trailing_example(inputs: ChallengeInput) -> ConsistencyExample:
    """Use the same calculator reader, including raw target and total-loss outcomes.

    Target-reaching frequency is distinct from the best-day-rule subset. All
    inputs and outputs are declared model examples, not client measurements.
    The simulator checks closes and a strict breach below the loss floor; it
    cannot reconstruct an intraday touch or a high between daily observations.
    """
    return consistency_example(inputs)


def trailing_examples() -> tuple[ConsistencyExample, ...]:
    return tuple(trailing_example(inputs) for inputs in TRAILING_INPUTS)


# ---------------------------------------------------------------------------
# Ruin: declared rates versus their Wilson lower bounds on identical paths
# ---------------------------------------------------------------------------

#: Illustration only: one R is a fixed share of the INITIAL balance, not a
#: position-sizing recommendation. The threshold means a fall, not balance left.
RUIN_RISK_PCT = 1.0
RUIN_THRESHOLD_PCT = 30.0
RUIN_HORIZON = 500
RUIN_INPUTS: tuple[ruin_calc.RuinInput, ...] = tuple(
    ruin_calc.RuinInput(
        win_rate_pct=rate,
        unit="r",
        avg_win=win,
        avg_loss=1.0,
        risk=RUIN_RISK_PCT,
        ruin_pct=RUIN_THRESHOLD_PCT,
        horizon=RUIN_HORIZON,
        trades=trades,
    )
    for rate, win, trades in ((55.0, 1.0, 60), (55.0, 1.0, 300), (45.0, 2.0, 100))
)
RUIN_READINGS: tuple[ruin_calc.RuinReading, ...] = tuple(
    ruin_calc.compute(value) for value in RUIN_INPUTS
)
#: Paths of the third case that touched the threshold at its declared rate.
#: The table rounds that share to one decimal, like the calculator, so the
#: prose states the count itself instead of reading a zero into it.
RUIN_THIRD_CASE_RUINED_PATHS = round(RUIN_READINGS[2].declared.ruin * ruin_calc.SAMPLES)


def _ruin_winrate_reading(trades: int | None) -> winrate.WinRateReading:
    """Read the first example's rate and payoffs at the given sample size."""
    value = RUIN_INPUTS[0]
    return winrate.read(
        PublicClaim(
            trades=trades,
            win_rate=value.win_rate,
            target_r=value.avg_win,
            stop_r=value.avg_loss,
        )
    )


#: The calculator reports the first qualifying size in its discrete TRADE_GRID.
RUIN_WINRATE_READING = _ruin_winrate_reading(RUIN_INPUTS[0].trades)
#: Check every integer as well: the declared rate is treated as a proportion,
#: exactly as in winrate.read, without reconstructing an integer count of wins.
RUIN_MIN_TRADES = next(
    trades
    for trades in range(1, max(winrate.TRADE_GRID) + 1)
    if _ruin_winrate_reading(trades).position == "above"
)
#: An observed rate of exactly 55 % needs a multiple of 20 trades. This distinct
#: result keeps the proportion calculation separate from integer observations.
_RUIN_RATE_DENOMINATOR = Fraction(str(RUIN_INPUTS[0].win_rate)).denominator
RUIN_EXACT_RATE_TRADES = next(
    trades
    for trades in range(_RUIN_RATE_DENOMINATOR, max(winrate.TRADE_GRID) + 1, _RUIN_RATE_DENOMINATOR)
    if _ruin_winrate_reading(trades).position == "above"
)


__all__ = [
    "CONSISTENCY_INPUTS",
    "CONSISTENCY_VARIATION_INPUTS",
    "MC_REFERENCE_RISK",
    "MC_RISK",
    "MC_SEARCH_RISK",
    "MC_SHUFFLE",
    "RUIN_EXACT_RATE_TRADES",
    "RUIN_HORIZON",
    "RUIN_INPUTS",
    "RUIN_MIN_TRADES",
    "RUIN_READINGS",
    "RUIN_RISK_PCT",
    "RUIN_THIRD_CASE_RUINED_PATHS",
    "RUIN_THRESHOLD_PCT",
    "RUIN_WINRATE_READING",
    "STREAK_ROWS",
    "TRAILING_INPUTS",
    "TRAILING_RULE_KEYS",
    "ConsistencyExample",
    "ConsistencyRuleRow",
    "RiskSummary",
    "ShuffleSummary",
    "StreakRow",
    "TrailingCaveatRow",
    "TrailingRuleRow",
    "consistency_example",
    "consistency_examples",
    "consistency_rules",
    "consistency_variations",
    "reference_series",
    "resampled_risk",
    "risk_summary",
    "search_best_series",
    "shuffle_summary",
    "streak_for",
    "streak_row",
    "synthetic_series",
    "trailing_caveats",
    "trailing_example",
    "trailing_examples",
    "trailing_rules",
]
