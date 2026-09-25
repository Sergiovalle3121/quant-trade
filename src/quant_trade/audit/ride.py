"""What would it have felt like to run this history?

A total return and a maximum drawdown hide how the history was lived: how
long the account went without a new high, how long the deepest fall took to
come back, the worst single day and month, and how many months ended up.
These are the numbers that make people switch a system off, so a buyer
should see them before paying for one.

From the uploaded equity curve, in calendar time:

* the longest stretch below a previous high, from the high to the day the
  curve first gets back to it (or to the last date when it never does);
* the deepest fall: its depth, the days from the high to the low, and the
  days from the low back to the high;
* the worst day, from the last point of each calendar day, when the curve
  has points on most days;
* the calendar months: the share that end up, the worst one, and the
  longest run of losing months.

Every figure is MEASURED from the file and describes the history only.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.audit.schema import measured, not_measured

#: Points needed to say anything.
MIN_POINTS = 20
#: Calendar months needed for the monthly figures.
MIN_MONTHS = 3
#: The worst day needs points on at least this many days a week, on median.
MAX_DAY_GAP = 4

NOTE = "calendar days from the uploaded equity curve; months from each month's last point"


def _day(stamp: pd.Timestamp) -> str:
    return stamp.strftime("%Y-%m-%d")


def _longest_losing(returns: pd.Series) -> int:
    best = run = 0
    for value in returns:
        run = run + 1 if value < 0 else 0
        best = max(best, run)
    return best


def ride_review(frame: pd.DataFrame) -> dict[str, Any]:
    """Stretches under water, worst day and month, and the monthly hit rate."""
    data = frame[["timestamp", "equity"]].dropna()
    if len(data) < MIN_POINTS:
        return {"status": "NOT_MEASURED", "reason": "fewer than twenty points on the curve"}
    stamps = pd.to_datetime(data["timestamp"], utc=True).reset_index(drop=True)
    equity = data["equity"].astype(float).reset_index(drop=True)
    if (equity <= 0).any():
        return {"status": "NOT_MEASURED", "reason": "the curve reaches zero or below"}
    last = stamps.iloc[-1]

    # Longest stretch below a previous high, in calendar days.
    peak_value = float(equity.iloc[0])
    peak_at = stamps.iloc[0]
    longest = (0, peak_at, peak_at, True)
    for value, stamp in zip(equity.iloc[1:], stamps.iloc[1:], strict=True):
        if value >= peak_value:
            days = (stamp - peak_at).days
            if days > longest[0]:
                longest = (days, peak_at, stamp, True)
            peak_value, peak_at = float(value), stamp
    open_days = (last - peak_at).days
    if equity.iloc[-1] < peak_value and open_days > longest[0]:
        longest = (open_days, peak_at, last, False)

    # The deepest fall: high, low and the way back.
    running = equity.cummax()
    depth = equity / running - 1.0
    low = int(depth.idxmin())
    high = int(equity.iloc[: low + 1].idxmax())
    back = equity.iloc[low:][equity.iloc[low:] >= equity.iloc[high]]
    recovered = not back.empty
    fell = float(depth.iloc[low]) < 0
    review: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        "longest_under": measured(longest[0], "calendar days from a high until it is regained"),
        "longest_under_from": _day(longest[1]),
        "longest_under_to": _day(longest[2]),
        "longest_under_recovered": longest[3],
        "deepest": measured(float(depth.iloc[low]), "deepest fall from a previous high"),
        "deepest_from": _day(stamps.iloc[high]),
        "deepest_low": _day(stamps.iloc[low]),
        "fall_days": (
            measured((stamps.iloc[low] - stamps.iloc[high]).days, "high to low")
            if fell
            else not_measured("the curve never falls below a previous high")
        ),
        "recovery_days": (
            measured((stamps.iloc[int(back.index[0])] - stamps.iloc[low]).days, "low to high")
            if fell and recovered
            else not_measured(
                "not regained by the last date of the file"
                if fell
                else "the curve never falls below a previous high"
            )
        ),
        "recovered": recovered,
    }

    series = pd.Series(equity.to_numpy(), index=stamps)
    daily = series.groupby(series.index.normalize()).last()
    gap = daily.index.to_series().diff().dt.days.median() if len(daily) > 1 else None
    if gap is not None and gap <= MAX_DAY_GAP and len(daily) >= MIN_POINTS:
        day_returns = daily.pct_change().dropna()
        worst_day = day_returns.idxmin()
        review["worst_day"] = measured(float(day_returns.min()), "from each day's last point")
        review["worst_day_on"] = _day(worst_day)
    else:
        review["worst_day"] = not_measured("the curve has no point on most days")

    monthly = series.groupby(series.index.tz_localize(None).to_period("M")).last()
    # The first month is measured from the first point of the file.
    monthly = pd.concat([pd.Series([float(equity.iloc[0])]), monthly.reset_index(drop=True)])
    month_returns = monthly.pct_change().dropna().reset_index(drop=True)
    periods = series.index.tz_localize(None).to_period("M").unique()
    if len(month_returns) >= MIN_MONTHS:
        worst = int(month_returns.idxmin())
        review["months"] = measured(len(month_returns))
        review["positive_months"] = measured(float((month_returns > 0).mean()))
        review["worst_month"] = measured(float(month_returns.min()))
        review["worst_month_in"] = str(periods[worst])
        review["losing_months_run"] = measured(_longest_losing(month_returns))
    else:
        review["months"] = not_measured("fewer than three calendar months")
    return review
