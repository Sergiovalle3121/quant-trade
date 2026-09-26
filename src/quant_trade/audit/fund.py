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
* **Few small losses.** Far fewer months with a small loss than the two
  neighbouring bins (small gains, and slightly larger losses) predict is the
  discontinuity at zero that Bollen and Pool (2009) tie to reported values
  that avoid a negative month. The bins are half a monthly standard
  deviation wide; given the months in the three bins, the small-loss count
  is tested one-sided against the binomial share a normal curve with the
  record's mean and deviation gives that bin.

When the file carries its benchmark (a column beside the returns, or a
factsheet's benchmark rows) or a benchmark file is uploaded, the section also
answers what an investor asks first about an actively managed fund: did it
beat its index over the months both share, by how much a year, in how many
months, how closely it tracks it (tracking error, information ratio), its
beta and its up and down capture (Morningstar's definition: geometric mean
return in the index's up, or down, months over the index's). Three findings:
it trails the index; it follows it so closely that the fees buy little
(correlation 0.95 or more with tracking error under 3 % a year, the "closet
indexing" mark of Cremers and Petajisto, 2009); or it captures less of the
rises and more of the falls. No index data is bundled: the benchmark is the
one the customer supplies, as they state it.

Every figure is MEASURED from the uploaded series. The section raises no red
flag and never changes the class: each finding is a question to ask.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.alpha import jensen_alpha
from quant_trade.audit.crises import crisis_review
from quant_trade.audit.schema import measured, not_measured

#: Periods per year at or below which a file counts as a monthly track record.
MAX_PERIODS_PER_YEAR = 13.0
#: Monthly returns needed.
MIN_MONTHS = 24
#: Autocorrelation at or above this, and beyond chance, is a finding.
SMOOTHING_RHO = 0.2
#: Width of the "small" bins either side of zero, in monthly standard deviations.
#: Half a deviation: narrower bins made honest index windows (US market,
#: 2000-2024) read as missing small losses.
SMALL_BIN = 0.5
#: Months needed in the two neighbouring bins together, and the one-sided p-value.
MIN_SMALL = 10
SMALL_P_VALUE = 0.01

NOTE = "month-end returns as the file states them"

#: Months the fund and its benchmark must share for the comparison.
MIN_SHARED = 24
#: Up (or down) months of the index needed for its capture ratio.
MIN_SIDE = 6
#: "Follows its index": correlation at or above, annual tracking error below.
INDEX_LIKE_CORRELATION = 0.95
INDEX_LIKE_TRACKING = 0.03
BENCHMARK_NOTE = "the benchmark's returns as supplied; Rigor did not check them against the index"


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    log_p, log_q = math.log(p), math.log1p(-p)
    return min(
        1.0,
        sum(
            math.exp(
                math.lgamma(n + 1)
                - math.lgamma(i + 1)
                - math.lgamma(n - i + 1)
                + i * log_p
                + (n - i) * log_q
            )
            for i in range(k + 1)
        ),
    )


def _bin_share(mean: float, std: float, width: float) -> float:
    """Share of the small-loss bin among the three bins, larger loss, small
    loss and small gain, under a normal curve with this mean and deviation."""

    def mass(low: float, high: float) -> float:
        return _normal_cdf((high - mean) / std) - _normal_cdf((low - mean) / std)

    larger = mass(-2 * width, -width)
    small_loss = mass(-width, 0.0)
    small_gain = mass(0.0, width)
    total = larger + small_loss + small_gain
    return small_loss / total if total > 0 else 1.0 / 3.0


#: A final month whose last point falls more than this many days before the
#: month's end is partial (a daily benchmark that stops on the 10th).
PARTIAL_MONTH_DAYS = 7


def monthly_returns(frame: pd.DataFrame) -> pd.Series:
    """Month-end returns of an equity frame (``timestamp``, ``equity``).

    A return is measured only between two consecutive calendar months that
    both have a level: a month missing from the file leaves a hole, never one
    "month" that spans two or three. On a series with several points a month
    (a daily benchmark), a final month seen only in part is left out, so it
    is never compared with a full month of the fund."""
    equity = frame.set_index("timestamp")["equity"].astype(float).sort_index()
    month_end = equity.resample("ME").last()
    months = len(month_end)
    if months > 1 and len(equity) > 1.5 * months:
        last = pd.Timestamp(equity.index[-1])
        if last < month_end.index[-1] - pd.Timedelta(days=PARTIAL_MONTH_DAYS):
            month_end = month_end.iloc[:-1]
    returns = month_end / month_end.shift(1) - 1.0
    return returns.iloc[1:].dropna()


def months_between_rows(frame: pd.DataFrame) -> float:
    """Median number of calendar months from one row to the next: 1 for a
    monthly record, 3 for a quarterly one."""
    stamps = pd.DatetimeIndex(frame["timestamp"])
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)
    periods = stamps.to_period("M").unique().sort_values()
    if len(periods) < 2:
        return 0.0
    steps = [(later - earlier).n for earlier, later in zip(periods[:-1], periods[1:], strict=True)]
    return float(np.median(steps))


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


def benchmark_months(returns: pd.DataFrame) -> pd.Series:
    """Month-end returns of a benchmark given as returns (``timestamp``, ``ret``),
    compounded within each month."""
    series = returns.set_index("timestamp")["ret"].astype(float)
    return (1.0 + series).resample("ME").prod(min_count=1).dropna() - 1.0


def _by_month(series: pd.Series) -> pd.Series:
    """The series keyed by calendar month, so month-ends a day apart align."""
    stamps = pd.DatetimeIndex(series.index)
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)
    return pd.Series(series.to_numpy(), index=stamps.to_period("M"))


def _capture(fund: np.ndarray, index: np.ndarray) -> float | None:
    if len(index) < MIN_SIDE:
        return None
    k = len(index)
    index_mean = float(np.prod(1.0 + index) ** (1.0 / k) - 1.0)
    if index_mean == 0:
        return None
    return float(np.prod(1.0 + fund) ** (1.0 / k) - 1.0) / index_mean


def compare_with_benchmark(fund: pd.Series, index: pd.Series, source: str) -> dict[str, Any]:
    """The fund against its benchmark over the months both share."""
    left = _by_month(fund)
    right = _by_month(index)
    shared = pd.concat({"fund": left, "index": right}, axis=1, join="inner").dropna()
    if len(shared) < MIN_SHARED:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs at least {MIN_SHARED} months shared with the benchmark",
        }
    f = shared["fund"].to_numpy(dtype=float)
    b = shared["index"].to_numpy(dtype=float)
    n = len(f)
    if not float(b.std(ddof=1)) > 0:
        return {"status": "NOT_MEASURED", "reason": "the benchmark's monthly returns do not vary"}
    active = f - b
    fund_cagr = float(np.prod(1.0 + f) ** (12.0 / n) - 1.0)
    index_cagr = float(np.prod(1.0 + b) ** (12.0 / n) - 1.0)
    tracking = float(active.std(ddof=1)) * math.sqrt(12.0)
    correlation = float(np.corrcoef(f, b)[0, 1])
    beta = float(np.cov(f, b, ddof=1)[0, 1] / b.var(ddof=1))
    up = _capture(f[b > 0], b[b > 0])
    down = _capture(f[b < 0], b[b < 0])
    review: dict[str, Any] = {
        "status": "MEASURED",
        "note": BENCHMARK_NOTE,
        "source": source,
        "months": measured(n),
        "first": str(shared.index[0]),
        "last": str(shared.index[-1]),
        "fund_cagr": measured(fund_cagr),
        "index_cagr": measured(index_cagr),
        "excess": measured(
            fund_cagr - index_cagr, "fund's compound annual return minus the benchmark's"
        ),
        "beat_share": measured(float((f > b).mean())),
        "tracking_error": measured(
            tracking, "annualised standard deviation of the monthly differences"
        ),
        "correlation": measured(correlation),
        "beta": measured(beta),
        "findings": [],
    }
    review["jensen"] = jensen_alpha(f, b, 12.0)
    if tracking > 0:
        review["information_ratio"] = measured(float(active.mean()) * 12.0 / tracking)
    for key, value in (("up_capture", up), ("down_capture", down)):
        review[key] = (
            measured(value)
            if value is not None
            else not_measured(f"needs at least {MIN_SIDE} months with the benchmark {key[:-8]}")
        )
    if fund_cagr < index_cagr:
        review["findings"].append("trails")
    if correlation >= INDEX_LIKE_CORRELATION and tracking < INDEX_LIKE_TRACKING:
        review["findings"].append("index_like")
    if up is not None and down is not None and up < 1.0 < down:
        review["findings"].append("worse_both_ways")
    return review


def fund_review(
    frame: pd.DataFrame,
    periods_per_year: float,
    benchmark: pd.Series | None = None,
    benchmark_source: str = "file",
) -> dict[str, Any]:
    """Calendar table, allocator figures and the two fund tests; with a
    benchmark's month-end returns, the comparison with it."""
    if periods_per_year > MAX_PERIODS_PER_YEAR or months_between_rows(frame) > 1.0:
        # A quarterly or yearly record read month by month would compound each
        # quarter as one month: its annual return and volatility would be wrong.
        return {"status": "NOT_MEASURED", "reason": "the file is not a monthly track record"}
    series = monthly_returns(frame)
    stamps = pd.DatetimeIndex(frame["timestamp"])
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)
    periods = stamps.to_period("M")
    span = int((periods.max() - periods.min()).n)
    if len(series) < MIN_MONTHS:
        return {"status": "NOT_MEASURED", "reason": f"needs at least {MIN_MONTHS} monthly returns"}
    r = series.to_numpy(dtype=float)
    n = len(r)
    std = float(r.std(ddof=1))
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
        # Calendar months with no return because the file skips a month.
        "missing_months": measured(max(span - n, 0)),
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

    # 2. Months with a small loss against their two neighbouring bins: a
    # histogram of returns is smooth across zero unless losses were avoided.
    width = SMALL_BIN * std
    small_gains = int(((r > 0) & (r <= width)).sum())
    small_losses = int(((r < 0) & (r >= -width)).sum())
    larger_losses = int(((r < -width) & (r >= -2 * width)).sum())
    review["small_gains"] = measured(small_gains)
    review["small_losses"] = measured(small_losses)
    if small_gains + larger_losses >= MIN_SMALL:
        # Conditional on the months in the three bins, the small-loss bin's
        # share is what a normal curve with the record's mean and deviation
        # gives it. The neighbours' plain average ignored its own noise and the
        # curve's slope and flagged steady honest funds several times too often.
        mean = float(r.mean())
        share = _bin_share(mean, std, width)
        total = small_gains + small_losses + larger_losses
        expected = total * share
        p_value = _binomial_cdf(small_losses, total, share)
        review["small_losses_expected"] = measured(expected)
        review["small_losses_p_value"] = measured(p_value)
        if p_value < SMALL_P_VALUE:
            review["findings"].append("few_small_losses")
    if benchmark is not None:
        review["benchmark"] = compare_with_benchmark(series, benchmark, benchmark_source)
    review["crises"] = crisis_review(series, benchmark)
    return review


#: Yearly fees an active fund commonly charges, for the fee table.
FEE_RATES: tuple[float, ...] = (0.01, 0.015, 0.02, 0.025)
FEE_NOTE = (
    "the monthly returns with each yearly fee taken out month by month; shown because the "
    "figures were not declared net of fees"
)


#: The classic hedge-fund charge: 2 % a year on assets, 20 % of the gains
#: above the high-water mark, taken at the end of each year of the record
#: (and at its last month, as for an investor who leaves then).
MANAGEMENT_FEE = 0.02
PERFORMANCE_FEE = 0.20
TWO_AND_TWENTY_NOTE = (
    "the monthly returns with 2 % a year taken month by month and 20 % of each year's gain "
    "above the previous high taken at the year's end (high-water mark)"
)


def _two_and_twenty(returns: np.ndarray) -> float:
    """Growth of 1 after 2 % a year and 20 % of the gains over the high-water mark."""
    monthly = (1.0 + MANAGEMENT_FEE) ** (1.0 / 12.0) - 1.0
    value = high_water = 1.0
    for month, r in enumerate(returns, start=1):
        value *= (1.0 + r) / (1.0 + monthly)
        year_end = month % 12 == 0 or month == len(returns)
        if year_end and value > high_water:
            value -= PERFORMANCE_FEE * (value - high_water)
            high_water = value
    return float(value)


def fee_drag(series: pd.Series, comparison: dict[str, Any] | None = None) -> dict[str, Any]:
    """What common yearly fees would leave of a record not declared net of
    fees, and, with an index comparison, the fee at which the fund would only
    match its index."""
    r = series.to_numpy(dtype=float)
    n = len(r)
    if n < MIN_MONTHS:
        return {"status": "NOT_MEASURED", "reason": f"needs at least {MIN_MONTHS} monthly returns"}
    years = n / 12.0
    rows = []
    for rate in FEE_RATES:
        monthly = (1.0 + rate) ** (1.0 / 12.0) - 1.0
        net = (1.0 + r) / (1.0 + monthly) - 1.0
        growth = float(np.prod(1.0 + net))
        rows.append(
            {
                "rate": rate,
                "cagr": measured(growth ** (1.0 / years) - 1.0, FEE_NOTE),
                "growth": measured(growth - 1.0, FEE_NOTE),
            }
        )
    out: dict[str, Any] = {
        "status": "MEASURED",
        "note": FEE_NOTE,
        "gross_cagr": measured(float(np.prod(1.0 + r) ** (1.0 / years) - 1.0)),
        "gross_growth": measured(float(np.prod(1.0 + r) - 1.0)),
        "rows": rows,
    }
    growth = _two_and_twenty(r)
    out["two_and_twenty"] = {
        "management": MANAGEMENT_FEE,
        "performance": PERFORMANCE_FEE,
        "cagr": measured(growth ** (1.0 / years) - 1.0, TWO_AND_TWENTY_NOTE),
        "growth": measured(growth - 1.0, TWO_AND_TWENTY_NOTE),
    }
    if comparison and comparison.get("status") == "MEASURED":
        fund_cagr = float(comparison["fund_cagr"]["value"])
        index_cagr = float(comparison["index_cagr"]["value"])
        out["break_even"] = measured(
            (1.0 + fund_cagr) / (1.0 + index_cagr) - 1.0,
            "the yearly fee that would leave the fund's months level with the benchmark's "
            "over the months they share",
        )
    return out


__all__ = [
    "FEE_RATES",
    "MIN_MONTHS",
    "benchmark_months",
    "compare_with_benchmark",
    "fee_drag",
    "fund_review",
    "monthly_returns",
]
