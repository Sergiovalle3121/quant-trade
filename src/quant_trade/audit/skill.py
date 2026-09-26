"""Skill or market exposure: where a fund's return came from.

An investor comparing a fund with its index asks one question before any
other: did the manager add anything, or did the fund simply hold the market?
This module answers it from the months the fund and its benchmark share,
with three regressions of the fund's return over cash on the index's:

* **Attribution.** ``r_f - c = alpha + beta (r_b - c) + e`` splits the fund's
  average yearly return into cash, exposure (``beta`` times the index's
  return over cash) and skill (``alpha``). With ordinary least squares the
  three add up exactly to the fund's average, so the report can say how much
  of it following the market explains (cash is its own line); that share is
  given only when beta is at least two standard errors from zero and the
  share lies between 0 and 1.
* **Lagged exposure** (Dimson, 1979). Funds whose holdings are priced late or
  smoothed react to the market a month later; the plain ``beta`` misses that
  part and the missing exposure shows up as alpha. Adding last month's index
  return, ``beta_0 + beta_1`` is the exposure with the lag counted, and the
  alpha beside it is the one left after it.
* **Timing** (Treynor and Mazuy, 1966). A squared excess index term: a positive
  ``gamma`` means the fund gained more in months of big index moves than its
  beta explains (convexity): good timing does that, and so do option-like
  positions; selling options gives a negative one. The alpha of that
  regression is the part left for choosing holdings.

Standard errors are cautious on purpose: each is the largest of three
estimates. HC3 (MacKinnon and White, 1985) holds when the size of the misses
changes; Newey and West's (1987) holds when they cluster in time; and, for
the alpha, the plain error scaled by ``(1 + rho) / (1 - rho)`` for the
misses' first-order autocorrelation (with Kendall's small-sample correction)
holds for smoothed funds, where Newey-West alone reads a chance alpha as
real about twice as often as it should. On simulated funds with no skill,
``|t| > 2`` then comes up about 4 % of the time with independent misses and
5 % to 8 % with strongly smoothed ones (36 to 120 months). Alpha carries a 95 %
range (Student's t) and, when positive, the months a record this noisy
would need before the alpha is about two standard errors from zero.

Cash is the 3-month US Treasury bill (FRED DTB3, converted to an annual
yield) when public data is on and covers every shared month; otherwise it is
zero and the note says so, because then the alpha also holds
``(1 - beta)`` times the cash rate. Informational: nothing here raises a
flag or changes the class.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.alpha import cautious_fit, newey_west_lags
from quant_trade.audit.analytics import _t_quantile
from quant_trade.audit.cashrate import annual_yield
from quant_trade.audit.schema import measured, not_measured

#: Shared months needed for the regressions.
MIN_MONTHS = 36
#: Standard errors an alpha needs to be told apart from zero ("months needed").
SIGNIFICANT_T = 2.0
CONFIDENCE = 0.95

ATTRIBUTION_NOTE = (
    "average yearly return split into cash, exposure to the benchmark (beta times its "
    "return over cash) and what is left (alpha); the three add up to the fund's average"
)
CASH_NOTE = "cash is the 3-month US Treasury bill (FRED DTB3, converted to an annual yield)"
NO_CASH_NOTE = (
    "no cash rate was available, so cash is taken as zero and the alpha also holds "
    "(1 - beta) times what cash paid"
)
DIMSON_NOTE = (
    "exposure with last month's benchmark return added (Dimson, 1979); late or smoothed "
    "prices hide part of the exposure from the plain beta"
)
TIMING_NOTE = (
    "squared benchmark term (Treynor and Mazuy, 1966); above zero, the fund gained more in "
    "months of big market moves than its beta explains (good timing or option-like "
    "positions), below zero less (poor timing or selling options)"
)
T_NOTE = (
    "alpha over its cautious standard error (the largest of HC3, Newey-West and one "
    "widened for autocorrelated misses); beyond about 2 it is unlikely to be chance"
)
RANGE_NOTE = "95 % range of the yearly alpha, cautious standard error and Student's t"
MONTHS_NOTE = (
    "months a record with this alpha and this noise would need before the alpha is two "
    "standard errors from zero"
)
TOO_FEW = "fewer than 36 months shared with the benchmark"
NOT_POSITIVE = "the alpha is not above zero"
FLAT = "the benchmark's monthly returns do not vary"
ALREADY = "already two standard errors from zero"
NO_CLEAR_EXPOSURE = (
    "the exposure to the benchmark is not two standard errors from zero, so the split is "
    "not shown as a share"
)
NOT_POSITIVE_TOTAL = "the fund's average return is not above zero"
EXPOSURE_ABOVE_TOTAL = "the exposure alone is larger than the fund's whole return"
EXPOSURE_NEGATIVE = "the exposure took away from the fund's return rather than adding to it"
BETA_T_NOTE = "beta over its cautious standard error"
SINGULAR = "the benchmark's returns take too few distinct values for the regressions"


def _exposure_share(
    exposure: float, total: float, beta_t: float | None, note: str
) -> dict[str, Any]:
    """The share of the fund's return that exposure to the benchmark explains
    (cash is its own line), only when it is a share at all."""
    if beta_t is None or beta_t < SIGNIFICANT_T:
        return not_measured(NO_CLEAR_EXPOSURE)
    if total <= 0:
        return not_measured(NOT_POSITIVE_TOTAL)
    share = exposure / total
    if share > 1.0:
        return not_measured(EXPOSURE_ABOVE_TOTAL)
    if share < 0.0:
        return not_measured(EXPOSURE_NEGATIVE)
    return measured(share, note)


def _t(value: float, variance: float) -> float | None:
    se = math.sqrt(max(variance, 0.0))
    return value / se if se > 0 else None


def monthly_cash(rates: pd.Series | None, months: pd.PeriodIndex) -> np.ndarray | None:
    """Each month's return on a 3-month bill from FRED DTB3 rates (percent,
    discount basis); ``None`` unless every month has at least one rate."""
    if rates is None or rates.empty:
        return None
    index = pd.DatetimeIndex(rates.index)
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    values = pd.to_numeric(pd.Series(rates.to_numpy(), index=index), errors="coerce").dropna()
    if values.empty:
        return None
    by_month = values.groupby(values.index.to_period("M")).mean()
    found = by_month.reindex(months)
    if bool(found.isna().any()):
        return None
    yearly = annual_yield(found.to_numpy(dtype=float) / 100.0)
    days = np.asarray([period.days_in_month for period in months], dtype=float)
    return np.asarray((1.0 + yearly) ** (days / 365.0) - 1.0, dtype=float)


def skill_review(
    fund: np.ndarray, index: np.ndarray, cash: np.ndarray | None = None
) -> dict[str, Any]:
    """Attribution, lagged exposure, timing and the alpha's uncertainty over
    aligned monthly returns (``cash`` per month, or ``None`` for zero)."""
    f = np.asarray(fund, dtype=float)
    b = np.asarray(index, dtype=float)
    c = np.zeros_like(f) if cash is None else np.asarray(cash, dtype=float)
    if not len(f) == len(b) == len(c):
        return {"status": "NOT_MEASURED", "reason": "the series are not on the same months"}
    keep = np.isfinite(f) & np.isfinite(b) & np.isfinite(c)
    f, b, c = f[keep], b[keep], c[keep]
    n = len(f)
    if n < MIN_MONTHS:
        return {"status": "NOT_MEASURED", "reason": TOO_FEW}
    if not float(b.std(ddof=1)) > 0:
        return {"status": "NOT_MEASURED", "reason": FLAT}
    try:
        return _review(f - c, b - c, c, n, cash_given=cash is not None, fund=f)
    except np.linalg.LinAlgError:
        # A benchmark with two distinct values makes the timing term collinear.
        return {"status": "NOT_MEASURED", "reason": SINGULAR}


def _review(
    y: np.ndarray,
    x: np.ndarray,
    c: np.ndarray,
    n: int,
    *,
    cash_given: bool,
    fund: np.ndarray,
) -> dict[str, Any]:
    f = fund

    coef, var = cautious_fit(y, [x])
    alpha, beta = float(coef[0]), float(coef[1])
    alpha_t = _t(alpha, float(var[0]))
    beta_t = _t(beta, float(var[1]))
    margin = _t_quantile(0.5 + CONFIDENCE / 2, n - 2) * math.sqrt(max(float(var[0]), 0.0))
    cash_year = float(c.mean()) * 12.0
    exposure_year = beta * float(x.mean()) * 12.0
    alpha_year = alpha * 12.0
    total_year = float(f.mean()) * 12.0
    note = ATTRIBUTION_NOTE
    attribution: dict[str, Any] = {
        "total": measured(total_year, note),
        "cash": measured(cash_year, note),
        "exposure": measured(exposure_year, note),
        "alpha": measured(alpha_year, note),
        "exposure_share": _exposure_share(exposure_year, total_year, beta_t, note),
    }
    if alpha_t is None:
        needed: dict[str, Any] = not_measured("the fund moves exactly with the benchmark")
    elif alpha <= 0:
        needed = not_measured(NOT_POSITIVE)
    elif alpha_t >= SIGNIFICANT_T:
        needed = not_measured(ALREADY)
    else:
        needed = measured(int(math.ceil(n * (SIGNIFICANT_T / alpha_t) ** 2)), MONTHS_NOTE)

    lag_coef, lag_var = cautious_fit(y[1:], [x[1:], x[:-1]])
    dimson_beta = float(lag_coef[1] + lag_coef[2])
    lag_t = _t(float(lag_coef[2]), float(lag_var[2]))
    dimson_alpha_t = _t(float(lag_coef[0]), float(lag_var[0]))

    tm_coef, tm_var = cautious_fit(y, [x, x**2])
    gamma_t = _t(float(tm_coef[2]), float(tm_var[2]))
    tm_alpha_t = _t(float(tm_coef[0]), float(tm_var[0]))

    def _stat(value: float | None, text: str) -> dict[str, Any]:
        return measured(value, text) if value is not None else not_measured(text)

    return {
        "status": "MEASURED",
        "months": n,
        "lags": newey_west_lags(n),
        "cash_basis": {
            "source": "DTB3" if cash_given else None,
            "note": CASH_NOTE if cash_given else NO_CASH_NOTE,
        },
        "attribution": attribution,
        "beta": measured(beta),
        "beta_t_stat": _stat(beta_t, BETA_T_NOTE),
        "alpha": measured(alpha_year, note),
        "alpha_t_stat": _stat(alpha_t, T_NOTE),
        "alpha_range": {
            "low": measured((alpha - margin) * 12.0, RANGE_NOTE),
            "high": measured((alpha + margin) * 12.0, RANGE_NOTE),
        },
        "months_needed": needed,
        "lagged": {
            "beta": measured(dimson_beta, DIMSON_NOTE),
            "lag_beta": measured(float(lag_coef[2]), DIMSON_NOTE),
            "lag_t_stat": _stat(lag_t, DIMSON_NOTE),
            "alpha": measured(float(lag_coef[0]) * 12.0, DIMSON_NOTE),
            "alpha_t_stat": _stat(dimson_alpha_t, DIMSON_NOTE),
        },
        "timing": {
            "gamma": measured(float(tm_coef[2]), TIMING_NOTE),
            "gamma_t_stat": _stat(gamma_t, TIMING_NOTE),
            "selection_alpha": measured(float(tm_coef[0]) * 12.0, TIMING_NOTE),
            "selection_alpha_t_stat": _stat(tm_alpha_t, TIMING_NOTE),
        },
    }


__all__ = ["MIN_MONTHS", "monthly_cash", "skill_review"]
