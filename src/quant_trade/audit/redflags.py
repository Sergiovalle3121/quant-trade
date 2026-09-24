"""Red flags: what a return series looks like when something went wrong.

None of these prove misconduct. Each is a pattern that appears far more often
in backtests with a bug, a look-ahead, or a marking problem than in honest
ones, so a hit is a question the client should answer before the number is
trusted. Severity ``FAIL`` means the audit cannot stand behind the headline
numbers; ``WARN`` means the number is reported with the caveat attached.

Thresholds are constants here, recorded in the report, and covered by tests
one code at a time. Changing one is a documented decision, not a tweak.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant_trade.audit.schema import (
    MIN_OBSERVATIONS,
    DeclaredMetadata,
    IngestedSeries,
    ParsedTrades,
)

Severity = Literal["FAIL", "WARN"]

#: Same constants as ``data/quality/report.py``; the fat-finger signature is
#: the same whether the series is a price or an equity curve.
SPIKE_ROBUST_Z = 10.0
SPIKE_MIN_ABS_RETURN = 0.15

OBSERVATIONS_WARN = 100
UNPARSEABLE_FAIL_SHARE = 0.05
STALE_RUN_WARN = 5
STALE_RUN_FAIL = 20
SPIKES_FAIL = 4
#: Annualised Sharpe above which a retail backtest is more likely mis-measured
#: than exceptional. Intraday series legitimately reach higher ratios.
SHARPE_WARN_DAILY = 3.0
SHARPE_FAIL_DAILY = 6.0
SHARPE_WARN_INTRADAY = 6.0
SHARPE_FAIL_INTRADAY = 10.0
INTRADAY_PERIODS_PER_YEAR = 400.0
GAP_MULTIPLE = 10.0
PNL_MISMATCH_SHARE = 0.01


@dataclass(frozen=True)
class RedFlag:
    code: str
    severity: Severity
    detail: str
    value: float | int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_mad_spikes(
    returns: pd.Series,
    *,
    robust_z: float = SPIKE_ROBUST_Z,
    min_abs: float = SPIKE_MIN_ABS_RETURN,
) -> int:
    """Count returns that are extreme outliers against the series' own
    distribution (robust MAD z-score) and large in absolute terms."""
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) < 10:
        return 0
    median = clean.median()
    mad = (clean - median).abs().median()
    if mad <= 0:
        return int((clean.abs() > min_abs).sum())
    z = (clean - median).abs() / (1.4826 * mad)
    return int(((z > robust_z) & (clean.abs() > min_abs)).sum())


def longest_stale_run(returns: pd.Series) -> int:
    """Longest run of identical consecutive non-zero returns.

    Zero returns are excluded: a strategy sitting in cash produces exact
    zeros honestly. Identical non-zero returns repeated for days are a
    forward-fill or a mark-to-model.
    """
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    longest = 0
    run = 0
    for index in range(1, len(values)):
        same = math.isclose(values[index], values[index - 1], rel_tol=1e-9, abs_tol=1e-12)
        if values[index] != 0.0 and same:
            run = run + 1 if run else 2
            longest = max(longest, run)
        else:
            run = 0
    return longest


def annualised_sharpe(returns: pd.Series, periods_per_year: float) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) < 3:
        return 0.0
    std = float(clean.std(ddof=1))
    if std <= 0:
        return 0.0
    return float(clean.mean() / std * np.sqrt(periods_per_year))


def scan(
    series: IngestedSeries,
    *,
    periods_per_year: float,
    declared: DeclaredMetadata,
    trades: ParsedTrades | None = None,
    recomputed_pnl: list[float] | None = None,
    variants_columns: int = 0,
) -> list[RedFlag]:
    flags: list[RedFlag] = []
    frame = series.frame
    returns = series.returns
    n = int(len(returns))

    if n < MIN_OBSERVATIONS:
        flags.append(
            RedFlag(
                "TOO_FEW_OBSERVATIONS",
                "FAIL",
                f"{n} return observations; at least {MIN_OBSERVATIONS} are needed",
                n,
            )
        )
    elif n < OBSERVATIONS_WARN:
        flags.append(
            RedFlag(
                "TOO_FEW_OBSERVATIONS",
                "WARN",
                f"{n} return observations; conclusions below {OBSERVATIONS_WARN} are fragile",
                n,
            )
        )

    non_positive = int((frame["equity"] <= 0).sum())
    if non_positive:
        flags.append(
            RedFlag(
                "NON_POSITIVE_EQUITY",
                "FAIL",
                f"{non_positive} equity value(s) at or below zero; returns are undefined there",
                non_positive,
            )
        )

    if series.duplicate_timestamps:
        flags.append(
            RedFlag(
                "DUPLICATE_TIMESTAMPS",
                "FAIL",
                f"{series.duplicate_timestamps} duplicated timestamp(s); the last value was kept",
                series.duplicate_timestamps,
            )
        )
    if series.non_monotonic:
        flags.append(
            RedFlag(
                "NON_MONOTONIC_TIMESTAMPS",
                "WARN",
                "rows were not in chronological order; sorted before analysis",
            )
        )
    if series.unparseable_rows:
        share = series.unparseable_rows / max(series.raw_rows, 1)
        flags.append(
            RedFlag(
                "UNPARSEABLE_ROWS",
                "FAIL" if share > UNPARSEABLE_FAIL_SHARE else "WARN",
                f"{series.unparseable_rows} of {series.raw_rows} rows could not be read",
                series.unparseable_rows,
            )
        )

    std = float(returns.std(ddof=1)) if n >= 2 else 0.0
    if n >= 2 and std <= 0:
        flags.append(
            RedFlag("ZERO_VARIANCE", "FAIL", "every return is identical; nothing to measure")
        )

    stale = longest_stale_run(returns)
    if stale >= STALE_RUN_FAIL:
        flags.append(
            RedFlag(
                "STALE_MARKS",
                "FAIL",
                f"{stale} consecutive identical non-zero returns; looks forward-filled",
                stale,
            )
        )
    elif stale >= STALE_RUN_WARN:
        flags.append(
            RedFlag(
                "STALE_MARKS",
                "WARN",
                f"{stale} consecutive identical non-zero returns",
                stale,
            )
        )

    spikes = detect_mad_spikes(returns)
    if spikes >= SPIKES_FAIL:
        flags.append(
            RedFlag(
                "MAD_SPIKES",
                "FAIL",
                f"{spikes} single-period moves are extreme outliers (>{SPIKE_MIN_ABS_RETURN:.0%} "
                f"and >{SPIKE_ROBUST_Z:g} robust sigmas)",
                spikes,
            )
        )
    elif spikes >= 1:
        flags.append(
            RedFlag(
                "MAD_SPIKES",
                "WARN",
                f"{spikes} single-period move(s) are extreme outliers; check for bad prints",
                spikes,
            )
        )

    sharpe = annualised_sharpe(returns, periods_per_year)
    intraday = periods_per_year > INTRADAY_PERIODS_PER_YEAR
    warn_at = SHARPE_WARN_INTRADAY if intraday else SHARPE_WARN_DAILY
    fail_at = SHARPE_FAIL_INTRADAY if intraday else SHARPE_FAIL_DAILY
    if sharpe > fail_at:
        flags.append(
            RedFlag(
                "IMPLAUSIBLE_SHARPE",
                "FAIL",
                f"annualised Sharpe {sharpe:.2f} exceeds {fail_at:g}; almost always a look-ahead "
                "or a costless fill assumption",
                sharpe,
            )
        )
    elif sharpe > warn_at:
        flags.append(
            RedFlag(
                "IMPLAUSIBLE_SHARPE",
                "WARN",
                f"annualised Sharpe {sharpe:.2f} exceeds {warn_at:g}; rare outside intraday "
                "market making",
                sharpe,
            )
        )

    spacing = frame["timestamp"].diff().dropna()
    if len(spacing) >= 2:
        median = spacing.median()
        if median > pd.Timedelta(0):
            multiple = float(spacing.max() / median)
            if multiple > GAP_MULTIPLE:
                flags.append(
                    RedFlag(
                        "LARGE_GAPS",
                        "WARN",
                        f"largest gap between rows is {multiple:.0f}x the median spacing",
                        multiple,
                    )
                )

    if declared.cost_bps_per_side == 0:
        flags.append(
            RedFlag(
                "ZERO_DECLARED_COSTS",
                "WARN",
                "no trading cost declared; the cost dimension uses a reference assumption",
            )
        )
    if variants_columns and declared.trials < variants_columns:
        flags.append(
            RedFlag(
                "TRIALS_BELOW_VARIANTS",
                "WARN",
                f"{declared.trials} trial(s) declared but {variants_columns} variants uploaded; "
                "the declared count is too low",
                variants_columns,
            )
        )

    if trades is not None:
        if trades.invalid_rows:
            flags.append(
                RedFlag(
                    "INVALID_TRADE_ROWS",
                    "WARN",
                    f"{trades.invalid_rows} trade row(s) dropped as unreadable",
                    trades.invalid_rows,
                )
            )
        if recomputed_pnl is not None:
            reported = [
                (client, ours)
                for client, ours in zip(trades.client_pnl, recomputed_pnl, strict=True)
                if client is not None
            ]
            if reported:
                gross = sum(abs(ours) for _, ours in reported)
                mismatch = sum(abs(client - ours) for client, ours in reported)
                if gross > 0 and mismatch / gross > PNL_MISMATCH_SHARE:
                    flags.append(
                        RedFlag(
                            "TRADE_PNL_MISMATCH",
                            "WARN",
                            f"client-reported pnl differs from recomputed pnl by "
                            f"{mismatch / gross:.1%} of gross; the trades file may carry "
                            "costs or a different contract size",
                            mismatch / gross,
                        )
                    )
    return flags


__all__ = [
    "RedFlag",
    "Severity",
    "annualised_sharpe",
    "detect_mad_spikes",
    "longest_stale_run",
    "scan",
]
