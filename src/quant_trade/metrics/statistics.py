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

_EULER_GAMMA = 0.5772156649015329


def _phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _phi_inv(p: float) -> float:
    """Standard normal inverse CDF (Acklam's rational approximation)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > p_high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
    )


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


def deflated_sharpe_ratio(
    returns: pd.Series, n_trials: int, sharpe_variance: float
) -> float:
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
