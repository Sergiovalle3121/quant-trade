"""Jensen's alpha: what the strategy earned beyond its exposure to the benchmark.

The strategy's period returns are regressed on the benchmark's over the
periods both share, ``r_s = alpha + beta * r_b + e``. ``alpha`` (annualised
by the periods a year) is the part of the return the benchmark's moves do
not explain, and its t-statistic says whether that part is distinguishable
from zero. The standard error is Newey and West's (1987), so returns that
cluster in time or change in size do not make the alpha look surer than it
is. No cash rate is subtracted from either side (the same convention as the
Sharpe ratios in the report), so alpha here is measured against the
benchmark itself, not against its excess over cash.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from quant_trade.audit.schema import measured, not_measured

#: Shared periods needed for the regression.
MIN_PERIODS = 24
NOTE = (
    "return beyond the benchmark's moves (Jensen's alpha), annualised; Newey-West "
    "standard error; no cash rate subtracted"
)
T_NOTE = "alpha over its Newey-West standard error; beyond about 2 it is unlikely to be chance"
TOO_FEW = "fewer than 24 periods shared with the benchmark"
NOT_ALIGNED = "the strategy's and the benchmark's returns are not on the same dates"


def newey_west_lags(n: int) -> int:
    """The usual automatic lag, ``floor(4 (n / 100) ^ (2/9))``."""
    return int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def jensen_alpha(
    strategy: np.ndarray, benchmark: np.ndarray, periods_per_year: float
) -> dict[str, Any]:
    """Alpha (annualised), its Newey-West t-statistic, beta and R squared."""
    y = np.asarray(strategy, dtype=float)
    x = np.asarray(benchmark, dtype=float)
    if len(x) != len(y):
        return {"status": "NOT_MEASURED", "reason": NOT_ALIGNED}
    # A level at zero gives an infinite return: keep only the periods both measure.
    finite = np.isfinite(y) & np.isfinite(x)
    y, x = y[finite], x[finite]
    n = len(y)
    if n < MIN_PERIODS:
        return {"status": "NOT_MEASURED", "reason": TOO_FEW}
    if not float(x.std(ddof=1)) > 0:
        return {"status": "NOT_MEASURED", "reason": "the benchmark's returns do not vary"}
    design = np.column_stack([np.ones(n), x])
    xtx_inv = np.linalg.inv(design.T @ design)
    coef = xtx_inv @ design.T @ y
    resid = y - design @ coef
    lags = newey_west_lags(n)
    scores = design * resid[:, None]
    meat = scores.T @ scores
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        cross = scores[lag:].T @ scores[:-lag]
        meat += weight * (cross + cross.T)
    covariance = xtx_inv @ meat @ xtx_inv * n / (n - 2)
    se_alpha = math.sqrt(max(float(covariance[0, 0]), 0.0))
    total = float(((y - y.mean()) ** 2).sum())
    r_squared = 1.0 - float(resid @ resid) / total if total > 0 else 0.0
    alpha = float(coef[0])
    return {
        "status": "MEASURED",
        "alpha": measured(alpha * periods_per_year, NOTE),
        "alpha_t_stat": (
            measured(alpha / se_alpha, T_NOTE)
            if se_alpha > 0
            else not_measured("the strategy moves exactly with the benchmark")
        ),
        "beta": measured(float(coef[1])),
        "r_squared": measured(r_squared),
        "periods": n,
        "lags": lags,
    }


__all__ = ["jensen_alpha", "newey_west_lags"]
