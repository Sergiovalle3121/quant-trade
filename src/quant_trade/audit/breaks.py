"""Did the average return change at some point in the history?

The rolling and sub-period views show how the curve moved; they do not say
whether a difference is larger than the noise of the returns. This block
asks one question of the returns in time order, with an honest error band:
is there a point where the average return shifted?

* The test is the CUSUM of the returns' deviations from their overall mean
  (Ploberger and Kramer, 1992): the largest gap between the running sum and
  a straight line, over ``sigma * sqrt(n)``. ``sigma^2`` is the returns'
  long-run variance, cautious as elsewhere in the report: the largest of the
  plain variance, the Newey-West one (Bartlett weights, the lag of
  :func:`alpha.newey_west_lags`) and the plain one widened for first-order
  autocorrelation (Kendall-corrected, clipped to ``[0, MAX_RHO]``). With no
  change the statistic follows the supremum of a Brownian bridge, whose tail
  is Kolmogorov's: ``p = 2 sum_j (-1)^(j+1) exp(-2 j^2 x^2)``.
* The most likely date of the change is where that gap is largest. Its range
  is Bai's (1997) 95 % interval: ``11 sigma^2 / delta^2`` returns on each side,
  ``delta`` the shift in the mean.
* The average return before and after, annualised, each with a 90 % band
  from its own cautious standard error.

It is informational: it never changes the class. A p-value above
``ALPHA_LEVEL`` reads as no clear change, not as proof of none. The date is
where the change shows most, not its cause, and a single shift is assumed:
several smaller ones read as one. It describes the history; it says nothing
about later periods.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.alpha import newey_west_lags
from quant_trade.audit.schema import measured

#: Returns needed for the test to have a fair chance of seeing a shift.
MIN_RETURNS = 250
#: Returns needed on each side of the date before the two averages are shown.
MIN_SIDE = 30
#: Above this p-value the block reads as no clear change.
ALPHA_LEVEL = 0.05
#: Autocorrelation cap, as in the report's other cautious errors.
MAX_RHO = 0.9
#: Bai's 95 % quantile for the break date (symmetric case, ``11.03``).
BAI_95 = 11.03
#: Two-sided 90 % normal quantile for the before and after bands.
Z_90 = 1.6448536269514722

NOTE = (
    "CUSUM of the returns in time order (Ploberger and Kramer); cautious long-run "
    "variance; p-value from the Brownian bridge"
)
DATE_NOTE = "where the running sum strays furthest from its straight line; 95 % range (Bai)"
MEAN_NOTE = "average return per period, annualised; 90 % band from its cautious standard error"
SHORT = "fewer than 250 returns"
FLAT = "the returns never move"
ZERO = "the curve reaches zero"


def long_run_variance(values: np.ndarray) -> float:
    """The largest of the plain, Newey-West and autocorrelation-widened
    variances of ``values`` about their mean."""
    n = len(values)
    misses = values - values.mean()
    plain = float(misses @ misses) / n
    lags = newey_west_lags(n)
    newey_west = plain
    for lag in range(1, lags + 1):
        newey_west += 2.0 * (1.0 - lag / (lags + 1)) * float(misses[lag:] @ misses[:-lag]) / n
    rho = float(misses[1:] @ misses[:-1]) / (plain * n) if plain > 0 else 0.0
    rho = min(max(rho + (1.0 + 3.0 * rho) / n, 0.0), MAX_RHO)
    widened = plain * (1.0 + rho) / (1.0 - rho)
    return max(plain, newey_west, widened)


def bridge_p_value(statistic: float) -> float:
    """``P(sup |B(t)| > statistic)`` for a Brownian bridge ``B``."""
    if statistic <= 0.3:
        return 1.0
    total = 0.0
    for j in range(1, 101):
        term = 2.0 * (-1.0) ** (j + 1) * math.exp(-2.0 * j * j * statistic * statistic)
        total += term
        if abs(term) < 1e-16:
            break
    return min(max(total, 0.0), 1.0)


def _side(values: np.ndarray, ppy: float) -> dict[str, Any]:
    mean = float(values.mean())
    error = math.sqrt(long_run_variance(values) / len(values))
    return {
        "returns": len(values),
        "mean": measured(mean * ppy, MEAN_NOTE),
        "low": measured((mean - Z_90 * error) * ppy, MEAN_NOTE),
        "high": measured((mean + Z_90 * error) * ppy, MEAN_NOTE),
    }


def mean_shift(frame: pd.DataFrame, ppy: float) -> dict[str, Any]:
    """The CUSUM test for a shift in the average return of ``frame``
    (``timestamp``, ``equity``), with the date and the two averages."""
    equity = frame["equity"].to_numpy(dtype=float)
    if len(equity) < MIN_RETURNS + 1:
        return {"status": "NOT_MEASURED", "reason": SHORT}
    if bool((equity <= 0).any()):
        return {"status": "NOT_MEASURED", "reason": ZERO}
    values = equity[1:] / equity[:-1] - 1.0
    stamps = pd.to_datetime(frame["timestamp"], utc=True).iloc[1:].reset_index(drop=True)
    finite = np.isfinite(values)
    values, stamps = values[finite], stamps[finite].reset_index(drop=True)
    n = len(values)
    if n < MIN_RETURNS:
        return {"status": "NOT_MEASURED", "reason": SHORT}
    sigma2 = long_run_variance(values)
    if not sigma2 > 0:
        return {"status": "NOT_MEASURED", "reason": FLAT}
    path = np.cumsum(values - values.mean())
    k = int(np.argmax(np.abs(path[:-1]))) + 1  # returns before the date
    statistic = float(abs(path[k - 1]) / math.sqrt(sigma2 * n))
    p_value = bridge_p_value(statistic)
    out: dict[str, Any] = {
        "status": "MEASURED",
        "returns": n,
        "statistic": measured(statistic, NOTE),
        "p_value": measured(p_value, NOTE),
        "clear": p_value <= ALPHA_LEVEL,
    }
    if not out["clear"]:
        return out
    if min(k, n - k) < MIN_SIDE:
        # A shift in the first or last few returns has too little on one side
        # to show two averages; it is reported as such, not as no change.
        out.update({"clear": False, "edge": True})
        return out
    before, after = values[:k], values[k:]
    delta = float(after.mean() - before.mean())
    reach = int(math.ceil(BAI_95 * sigma2 / (delta * delta))) if delta else n
    first = max(0, k - reach)
    last = min(n - 1, k + reach)
    out.update(
        {
            "date": stamps[k].date().isoformat(),
            "date_low": stamps[first].date().isoformat(),
            "date_high": stamps[last].date().isoformat(),
            "date_note": DATE_NOTE,
            "share_before": measured(k / n, DATE_NOTE),
            "before": _side(before, ppy),
            "after": _side(after, ppy),
        }
    )
    return out


__all__ = ["bridge_p_value", "long_run_variance", "mean_shift"]
