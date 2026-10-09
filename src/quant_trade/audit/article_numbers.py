"""Declared teaching figures for the Monte Carlo and losing-streak articles.

Every figure here comes from the engine's own functions on inputs fixed in
this module: ``streaks.longest_run_tail`` for the losing-streak table and
``analytics.drawdown_risk`` and ``analytics.shuffled_drawdown`` for the
resampling example. The synthetic series are drawn with NumPy from the seeds
below, and both resampling functions take an explicit seed, so running this
module again gives the same numbers byte for byte (the tests do exactly that).

None of it is a measurement of a client's file: every displayed figure keeps
DECLARED and the assumption it rests on. Nothing here changes the engine, a
threshold, the report or the class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from quant_trade.audit.analytics import (
    SHUFFLE_SAMPLES,
    SHUFFLE_SEED,
    drawdown_risk,
    shuffled_drawdown,
)
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


__all__ = [
    "MC_REFERENCE_RISK",
    "MC_RISK",
    "MC_SEARCH_RISK",
    "MC_SHUFFLE",
    "STREAK_ROWS",
    "RiskSummary",
    "ShuffleSummary",
    "StreakRow",
    "reference_series",
    "resampled_risk",
    "risk_summary",
    "search_best_series",
    "shuffle_summary",
    "streak_for",
    "streak_row",
    "synthetic_series",
]
