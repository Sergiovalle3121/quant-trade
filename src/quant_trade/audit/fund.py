"""What a fund investor checks in a monthly track record.

Allocators read a fund's monthly returns the same way: the calendar table,
the compound annual return and volatility, the share of positive months, the
worst month and the deepest fall with how long it took to recover. Two tests
from the fund-due-diligence literature go further:

* **Smoothed returns.** Month after month too alike (positive first-order
  autocorrelation) is the mark of illiquid or stale-priced holdings, and it
  makes volatility look lower than it is (Getmansky, Lo and Makarov, 2004).
  The volatility is recomputed on the unsmoothed series
  ``(r_t - rho * r_{t-1}) / (1 - rho)`` (Geltner, 1993).
* **Few small losses.** Many small gains and very few small losses,
  compared with what the fund's own mean and volatility predict, is the
  discontinuity at zero that Bollen and Pool (2009) tie to reported values
  that avoid a negative month.

Every figure is MEASURED from the uploaded series. The section raises no red
flag and never changes the class: each finding is a question to ask.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.schema import measured

#: Periods per year at or below which a file counts as a monthly track record.
MAX_PERIODS_PER_YEAR = 13.0
#: Monthly returns needed.
MIN_MONTHS = 24
#: Autocorrelation at or above this, and beyond chance, is a finding.
SMOOTHING_RHO = 0.2
#: Width of the "small" bins either side of zero, in monthly standard deviations.
SMALL_BIN = 0.25
#: Months needed in the two small bins together, and the one-sided p-value.
MIN_SMALL = 10
SMALL_P_VALUE = 0.01

NOTE = "month-end returns as the file states them"


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p**i * (1.0 - p) ** (n - i) for i in range(k + 1))


def monthly_returns(frame: pd.DataFrame) -> pd.Series:
    """Month-end returns of an equity frame (``timestamp``, ``equity``)."""
    equity = frame.set_index("timestamp")["equity"].astype(float)
    month_end = equity.resample("ME").last().dropna()
    return month_end.pct_change().dropna()


def _drawdown(returns: np.ndarray) -> tuple[float, int, bool]:
    """Deepest fall, longest months under a previous high, and whether the
    last fall was recovered."""
    wealth = np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    peak = np.maximum.accumulate(wealth)
    depth = float((wealth / peak - 1.0).min())
    longest = run = 0
    for value, high in zip(wealth, peak, strict=True):
        run = run + 1 if value < high else 0
        longest = max(longest, run)
    return depth, longest, bool(wealth[-1] >= peak[-1])


def _longest_losing(returns: np.ndarray) -> int:
    longest = run = 0
    for value in returns:
        run = run + 1 if value < 0 else 0
        longest = max(longest, run)
    return longest


def fund_review(frame: pd.DataFrame, periods_per_year: float) -> dict[str, Any]:
    """Calendar table, allocator figures and the two fund tests."""
    if periods_per_year > MAX_PERIODS_PER_YEAR:
        return {"status": "NOT_MEASURED", "reason": "the file is not a monthly track record"}
    series = monthly_returns(frame)
    if len(series) < MIN_MONTHS:
        return {"status": "NOT_MEASURED", "reason": f"needs at least {MIN_MONTHS} monthly returns"}
    r = series.to_numpy(dtype=float)
    n = len(r)
    mean, std = float(r.mean()), float(r.std(ddof=1))
    if not std > 0:
        return {"status": "NOT_MEASURED", "reason": "the monthly returns do not vary"}

    years: list[dict[str, Any]] = []
    for year, group in series.groupby(series.index.year):
        months = {int(stamp.month): measured(float(value)) for stamp, value in group.items()}
        years.append(
            {
                "key": int(year),
                "months": months,
                "total": measured(float(np.prod(1.0 + group.to_numpy()) - 1.0)),
            }
        )
    depth, under, recovered = _drawdown(r)
    review: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        "months": measured(n),
        "years": years,
        "cagr": measured(float(np.prod(1.0 + r) ** (12.0 / n) - 1.0)),
        "volatility": measured(std * math.sqrt(12.0), "annualised standard deviation"),
        "positive_share": measured(float((r > 0).mean())),
        "best_month": measured(float(r.max())),
        "worst_month": measured(float(r.min())),
        "longest_losing": measured(_longest_losing(r)),
        "max_drawdown": measured(depth),
        "longest_under_water": measured(under),
        "recovered": measured(recovered),
        "findings": [],
    }

    # 1. Smoothing: first-order autocorrelation and the unsmoothed volatility.
    rho = float(np.corrcoef(r[1:], r[:-1])[0, 1])
    review["autocorrelation"] = measured(rho, "first-order autocorrelation of monthly returns")
    if SMOOTHING_RHO <= rho < 1.0:
        unsmoothed = (r[1:] - rho * r[:-1]) / (1.0 - rho)
        review["volatility_unsmoothed"] = measured(
            float(unsmoothed.std(ddof=1)) * math.sqrt(12.0),
            "annualised volatility of the unsmoothed returns",
        )
        if rho > 1.96 / math.sqrt(n):
            review["findings"].append("smoothed")

    # 2. Small gains against small losses, against what a normal with the
    # fund's own mean and volatility predicts for the two bins.
    width = SMALL_BIN * std
    small_gains = int(((r > 0) & (r <= width)).sum())
    small_losses = int(((r < 0) & (r >= -width)).sum())
    review["small_gains"] = measured(small_gains)
    review["small_losses"] = measured(small_losses)
    total_small = small_gains + small_losses
    if total_small >= MIN_SMALL:
        gain_mass = _normal_cdf((width - mean) / std) - _normal_cdf(-mean / std)
        loss_mass = _normal_cdf(-mean / std) - _normal_cdf((-width - mean) / std)
        p_loss = loss_mass / (gain_mass + loss_mass)
        p_value = _binomial_cdf(small_losses, total_small, p_loss)
        review["small_losses_p_value"] = measured(p_value)
        if p_value < SMALL_P_VALUE:
            review["findings"].append("few_small_losses")
    return review


__all__ = ["MIN_MONTHS", "fund_review", "monthly_returns"]
