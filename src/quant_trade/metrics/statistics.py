"""Statistical validation of backtest performance.

Implements the Bailey & López de Prado estimators that defend against
selection bias and non-normal returns:

- probabilistic_sharpe_ratio (PSR): probability that the true Sharpe exceeds a
  benchmark, adjusting for track-record length, skewness, and kurtosis.
- deflated_sharpe_ratio (DSR): PSR against the Sharpe one would expect from
  the best of N unskilled trials — the multiple-testing correction.
- minimum_track_record_length: observations needed before a Sharpe estimate
  is statistically distinguishable from a benchmark.

All Sharpe inputs here are PER-PERIOD (non-annualized); helpers accept raw
return series and derive moments internally.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quant_trade.metrics.normal import normal_cdf, normal_inverse_cdf

_EULER_GAMMA = 0.5772156649015329

# Single implementation, shared with the dependency-free arithmetic modules.
_phi = normal_cdf
_phi_inv = normal_inverse_cdf


def _moments(returns: pd.Series) -> tuple[int, float, float, float, float]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    n = len(clean)
    if n < 3:
        return n, 0.0, 0.0, 0.0, 3.0
    values = clean.to_numpy(dtype=float)
    mean = float(values.mean())
    std = float(values.std(ddof=1))
    if std <= 0:
        return n, mean, 0.0, 0.0, 3.0
    z = (values - mean) / std
    skew = float((z**3).mean())
    kurt = float((z**4).mean())  # Pearson kurtosis; normal = 3
    return n, mean, std, skew, kurt


def sharpe_per_period(returns: pd.Series) -> float:
    n, mean, std, _, _ = _moments(returns)
    if n < 3 or std <= 0:
        return 0.0
    return mean / std


def psr_from_moments(
    sharpe: float, n_observations: int, skew: float, kurtosis: float, benchmark_sharpe: float = 0.0
) -> float:
    """PSR from stored moments (all per-period). Enables recomputing PSR/DSR
    from persisted run artifacts without the raw return series."""
    if n_observations < 3:
        return 0.0
    denominator = 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe**2
    if denominator <= 0:
        return 0.0
    z = ((sharpe - benchmark_sharpe) * math.sqrt(n_observations - 1)) / math.sqrt(denominator)
    return _phi(z)


def return_moments(returns: pd.Series) -> dict[str, float]:
    """Per-period moments needed to recompute PSR/DSR later: sharpe, n, skew,
    kurtosis (Pearson)."""
    n, _, std, skew, kurt = _moments(returns)
    sr = sharpe_per_period(returns) if n >= 3 and std > 0 else 0.0
    return {
        "sharpe_per_period": sr,
        "observations": float(n),
        "skewness": skew,
        "kurtosis": kurt,
    }


def probabilistic_sharpe_ratio(returns: pd.Series, benchmark_sharpe: float = 0.0) -> float:
    """P[true Sharpe > benchmark_sharpe] given the observed track record.

    ``benchmark_sharpe`` is per-period (non-annualized). Returns 0.0 when the
    track record is too short to say anything.
    """
    n, _, std, skew, kurt = _moments(returns)
    if n < 3 or std <= 0:
        return 0.0
    return psr_from_moments(sharpe_per_period(returns), n, skew, kurt, benchmark_sharpe)


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """E[max Sharpe] across n unskilled trials with the given cross-trial
    variance of Sharpe estimates (per-period units)."""
    if n_trials <= 1 or sharpe_variance <= 0:
        return 0.0
    e = math.e
    return math.sqrt(sharpe_variance) * (
        (1 - _EULER_GAMMA) * _phi_inv(1 - 1 / n_trials)
        + _EULER_GAMMA * _phi_inv(1 - 1 / (n_trials * e))
    )


def deflated_sharpe_ratio(returns: pd.Series, n_trials: int, sharpe_variance: float) -> float:
    """PSR against the best-of-N-unskilled-trials Sharpe threshold.

    ``sharpe_variance`` is the variance of PER-PERIOD Sharpe estimates across
    the trials that were actually run (from the trial ledger). With one trial
    or unknown variance this degrades to the plain PSR against zero.
    """
    threshold = expected_max_sharpe(n_trials, sharpe_variance)
    return probabilistic_sharpe_ratio(returns, benchmark_sharpe=threshold)


def minimum_track_record_length(
    returns: pd.Series, benchmark_sharpe: float = 0.0, confidence: float = 0.95
) -> float:
    """Observations required for PSR(benchmark) to reach ``confidence``.

    Returns +inf when the observed Sharpe does not exceed the benchmark.
    """
    n, _, std, skew, kurt = _moments(returns)
    if n < 3 or std <= 0:
        return float("inf")
    sr = sharpe_per_period(returns)
    if sr <= benchmark_sharpe:
        return float("inf")
    z_alpha = _phi_inv(confidence)
    variance_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2
    if variance_term <= 0:
        return float("inf")
    return 1.0 + variance_term * (z_alpha / (sr - benchmark_sharpe)) ** 2


def sharpe_variance_across_trials(per_period_sharpes: list[float]) -> float:
    values = np.asarray([s for s in per_period_sharpes if np.isfinite(s)], dtype=float)
    if len(values) < 2:
        return 0.0
    return float(values.var(ddof=1))
