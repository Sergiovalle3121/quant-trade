"""Reproducible resampling for backtest confidence intervals.

Three explicit APIs replace the old ``simple_bootstrap_or_block_bootstrap``,
which silently ignored ``block_size`` and always did IID sampling:

- :func:`iid_bootstrap` — independent resampling with replacement. Destroys
  serial dependence; the right tool only when returns are (near) independent.
- :func:`moving_block_bootstrap` — contiguous fixed-length blocks (Kunsch), so
  within-block autocorrelation survives the resample.
- :func:`stationary_bootstrap` — Politis & Romano geometric block lengths, so
  the resampled series is stationary and no single block length is imposed.

:func:`bootstrap_confidence_intervals` wraps any of them into percentile bands.

**Everything here is per period.** Sharpe and volatility are NOT annualized:
scaling by ``sqrt(252)`` would be wrong for weekly, 4-hour, or funding-interval
data. Annualize downstream with the dataset's real frequency if needed.

Every function takes an explicit integer ``seed`` (no hidden global RNG) so a
confidence interval can be reproduced byte-for-byte from persisted metadata.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

#: Statistics computed on each resampled path (all per-period).
STATISTICS: tuple[str, ...] = (
    "total_return",
    "mean",
    "volatility",
    "sharpe",
    "max_drawdown",
)

NanPolicy = Literal["raise", "drop"]
BootstrapMethod = Literal["iid", "moving_block", "stationary"]

_MIN_OBSERVATIONS = 2


def _clean_returns(returns: pd.Series | np.ndarray, nan_policy: NanPolicy) -> np.ndarray:
    """Validate and materialise a 1-D float array of returns.

    ``nan_policy`` is explicit on purpose: the old helper silently dropped NaNs,
    which quietly changed the sample size feeding the statistics. Here NaNs
    ``raise`` by default; pass ``"drop"`` to opt in to dropping them.
    """
    values = np.asarray(returns, dtype=float).ravel()
    if nan_policy not in ("raise", "drop"):
        raise ValueError("nan_policy must be 'raise' or 'drop'")
    nan_mask = np.isnan(values)
    if nan_mask.any():
        if nan_policy == "raise":
            raise ValueError(
                f"returns contain {int(nan_mask.sum())} NaN value(s); "
                "pass nan_policy='drop' to remove them explicitly"
            )
        values = values[~nan_mask]
    if np.isinf(values).any():
        raise ValueError("returns contain non-finite (inf) values")
    if values.size < _MIN_OBSERVATIONS:
        raise ValueError(
            f"need at least {_MIN_OBSERVATIONS} observations for a bootstrap, "
            f"got {values.size}"
        )
    return values


def _validate_samples(samples: int) -> int:
    if int(samples) != samples or samples < 1:
        raise ValueError("samples must be a positive integer")
    return int(samples)


def _summary_matrix(paths: np.ndarray) -> pd.DataFrame:
    """Per-path summary statistics for a ``(samples, n)`` return matrix."""
    mean = paths.mean(axis=1)
    std = paths.std(axis=1, ddof=1)
    sharpe = np.divide(mean, std, out=np.zeros_like(mean), where=std > 0)
    equity = np.cumprod(1.0 + paths, axis=1)
    total_return = equity[:, -1] - 1.0
    peak = np.maximum.accumulate(equity, axis=1)
    drawdown = equity / peak - 1.0
    max_drawdown = drawdown.min(axis=1)
    return pd.DataFrame(
        {
            "sample": np.arange(paths.shape[0]),
            "total_return": total_return,
            "mean": mean,
            "volatility": std,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
        }
    )


def observed_statistics(
    returns: pd.Series | np.ndarray, nan_policy: NanPolicy = "raise"
) -> dict[str, float]:
    """The point estimate of each statistic on the observed series itself."""
    values = _clean_returns(returns, nan_policy)
    row = _summary_matrix(values.reshape(1, -1)).iloc[0]
    return {stat: float(row[stat]) for stat in STATISTICS}


def _iid_indices(n: int, samples: int, rng: np.random.Generator) -> np.ndarray:
    return rng.integers(0, n, size=(samples, n))


def _moving_block_indices(
    n: int, samples: int, block_size: int, wrap: bool, rng: np.random.Generator
) -> np.ndarray:
    n_blocks = int(np.ceil(n / block_size))
    if wrap:
        starts = rng.integers(0, n, size=(samples, n_blocks))
    else:
        starts = rng.integers(0, n - block_size + 1, size=(samples, n_blocks))
    offsets = np.arange(block_size)
    idx = starts[:, :, None] + offsets[None, None, :]
    if wrap:
        idx = idx % n
    return idx.reshape(samples, n_blocks * block_size)[:, :n]


def _stationary_indices(
    n: int, samples: int, p: float, rng: np.random.Generator
) -> np.ndarray:
    idx = np.empty((samples, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, size=samples)
    restart = rng.random((samples, n)) < p
    fresh = rng.integers(0, n, size=(samples, n))
    for j in range(1, n):
        contiguous = (idx[:, j - 1] + 1) % n
        idx[:, j] = np.where(restart[:, j], fresh[:, j], contiguous)
    return idx


def iid_bootstrap(
    returns: pd.Series | np.ndarray,
    *,
    samples: int = 1000,
    seed: int,
    nan_policy: NanPolicy = "raise",
) -> pd.DataFrame:
    """IID resample-with-replacement. Preserves length, destroys autocorrelation."""
    values = _clean_returns(returns, nan_policy)
    samples = _validate_samples(samples)
    rng = np.random.default_rng(seed)
    idx = _iid_indices(values.size, samples, rng)
    return _summary_matrix(values[idx])


def moving_block_bootstrap(
    returns: pd.Series | np.ndarray,
    *,
    samples: int = 1000,
    block_size: int = 20,
    seed: int,
    wrap: bool = True,
    nan_policy: NanPolicy = "raise",
) -> pd.DataFrame:
    """Contiguous fixed-length block resample (Kunsch, 1989).

    Blocks of exactly ``block_size`` consecutive observations are laid end to
    end and truncated to the original length, so within-block serial
    dependence survives. ``wrap`` (circular blocks, Politis & Romano) lets a
    block run off the end and continue from the start, which removes the
    end-of-sample bias of non-circular blocks; with ``wrap=False`` block starts
    are confined to ``[0, n - block_size]`` and ``block_size`` may not exceed
    the sample length.
    """
    values = _clean_returns(returns, nan_policy)
    samples = _validate_samples(samples)
    n = values.size
    if int(block_size) != block_size or block_size < 1:
        raise ValueError("block_size must be a positive integer")
    block_size = int(block_size)
    if not wrap and block_size > n:
        raise ValueError(
            f"block_size {block_size} exceeds sample length {n}; use wrap=True "
            "or a smaller block_size"
        )
    rng = np.random.default_rng(seed)
    idx = _moving_block_indices(n, samples, block_size, wrap, rng)
    return _summary_matrix(values[idx])


def stationary_bootstrap(
    returns: pd.Series | np.ndarray,
    *,
    samples: int = 1000,
    expected_block_size: float = 20.0,
    seed: int,
    nan_policy: NanPolicy = "raise",
) -> pd.DataFrame:
    """Stationary bootstrap (Politis & Romano, 1994).

    Block lengths are geometric with mean ``expected_block_size`` (restart
    probability ``p = 1 / expected_block_size``), so the resampled series is
    strictly stationary and robust to a mis-specified fixed block length. Blocks
    wrap circularly.
    """
    values = _clean_returns(returns, nan_policy)
    samples = _validate_samples(samples)
    n = values.size
    if not np.isfinite(expected_block_size) or expected_block_size < 1:
        raise ValueError("expected_block_size must be finite and >= 1")
    p = 1.0 / float(expected_block_size)
    rng = np.random.default_rng(seed)
    idx = _stationary_indices(n, samples, p, rng)
    return _summary_matrix(values[idx])


_METHODS = {
    "iid": iid_bootstrap,
    "moving_block": moving_block_bootstrap,
    "stationary": stationary_bootstrap,
}


def bootstrap_confidence_intervals(
    returns: pd.Series | np.ndarray,
    *,
    method: BootstrapMethod = "stationary",
    samples: int = 1000,
    seed: int,
    block_size: float = 20.0,
    percentiles: tuple[float, ...] = (2.5, 50.0, 97.5),
    wrap: bool = True,
    nan_policy: NanPolicy = "raise",
) -> pd.DataFrame:
    """Percentile confidence bands for each statistic under ``method``.

    Returns a DataFrame indexed by statistic name with a ``point_estimate``
    column (the statistic on the observed series), a ``bootstrap_mean`` column,
    and one ``p{pct}`` column per requested percentile. All values are
    per-period.
    """
    if method not in _METHODS:
        raise ValueError(f"unknown bootstrap method {method!r}; choose from {sorted(_METHODS)}")
    for pct in percentiles:
        if not 0.0 <= pct <= 100.0:
            raise ValueError("percentiles must lie in [0, 100]")
    if method == "iid":
        draws = iid_bootstrap(returns, samples=samples, seed=seed, nan_policy=nan_policy)
    elif method == "moving_block":
        draws = moving_block_bootstrap(
            returns, samples=samples, block_size=int(block_size), seed=seed,
            wrap=wrap, nan_policy=nan_policy,
        )
    else:
        draws = stationary_bootstrap(
            returns, samples=samples, expected_block_size=block_size, seed=seed,
            nan_policy=nan_policy,
        )
    point = observed_statistics(returns, nan_policy=nan_policy)
    rows = {}
    for stat in STATISTICS:
        col = draws[stat].to_numpy()
        entry = {
            "point_estimate": point[stat],
            "bootstrap_mean": float(col.mean()),
        }
        for pct, value in zip(percentiles, np.percentile(col, percentiles), strict=True):
            entry[f"p{pct:g}"] = float(value)
        rows[stat] = entry
    return pd.DataFrame.from_dict(rows, orient="index")
