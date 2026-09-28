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
  longest run of losing months;
* the five deepest falls, each from its high to its low and back (or still
  open at the file's end), the way a fund fact sheet lists them;
* the Calmar ratio: the compound annual return over the depth of the
  deepest fall, from a year of history on;
* the average of the worst 5 % of days and of months (expected shortfall),
  once there are enough of them for the 5 % to hold more than one.

Every figure is MEASURED from the file and describes the history only.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.schema import measured, not_measured
from quant_trade.metrics.performance import elapsed_years

#: Points needed to say anything.
MIN_POINTS = 20
#: Calendar months needed for the monthly figures.
MIN_MONTHS = 3
#: The worst day needs points on at least this many days a week, on median.
MAX_DAY_GAP = 4
#: Falls listed in the table of the deepest ones.
WORST_FALLS = 5
#: Calendar days of history before the Calmar ratio (it divides an annual return).
MIN_CALMAR_DAYS = 365
#: A deepest fall shallower than this leaves the Calmar ratio dividing by
#: almost nothing: a too-smooth curve would print it in the tens of thousands.
MIN_CALMAR_FALL = 0.01
#: Share of the worst days or months the tail average covers.
TAIL_SHARE = 0.05
#: Days needed so the worst 5 % holds at least five of them, and months so it
#: holds at least two (fewer would leave most fund records without the figure;
#: the report prints how many it averages).
MIN_TAIL_DAYS = 81
MIN_TAIL_MONTHS = 40

NOTE = "calendar days from the uploaded equity curve; months from each month's last point"


def _day(stamp: pd.Timestamp) -> str:
    return stamp.strftime("%Y-%m-%d")


def _longest_losing(returns: pd.Series) -> int:
    best = run = 0
    for value in returns:
        run = run + 1 if value < 0 else 0
        best = max(best, run)
    return best


def _falls(stamps: pd.Series, equity: pd.Series) -> list[dict[str, Any]]:
    """Every stretch below a previous high, deepest first, at most ``WORST_FALLS``.

    A fall starts at the last point at the high and ends at the first point
    back at or above it; one still below the high at the file's end is open.
    """
    values = equity.to_numpy(dtype=float)
    falls: list[dict[str, Any]] = []
    high = 0
    low = -1
    for i in range(1, len(values)):
        if values[i] >= values[high]:
            if low >= 0:
                falls.append({"high": high, "low": low, "back": i})
            high, low = i, -1
        elif low < 0 or values[i] < values[low]:
            low = i
    if low >= 0:
        falls.append({"high": high, "low": low, "back": None})
    for fall in falls:
        fall["depth"] = values[fall["low"]] / values[fall["high"]] - 1.0
    # Deepest first; equal depths in date order, so the table never reshuffles.
    falls.sort(key=lambda fall: (fall["depth"], fall["high"]))
    out = []
    for fall in falls[:WORST_FALLS]:
        start, bottom = stamps.iloc[fall["high"]], stamps.iloc[fall["low"]]
        back = fall["back"]
        out.append(
            {
                "depth": measured(float(fall["depth"]), "high to low"),
                "from": _day(start),
                "low": _day(bottom),
                "to": _day(stamps.iloc[back]) if back is not None else None,
                "fall_days": (bottom - start).days,
                "recovery_days": (stamps.iloc[back] - bottom).days if back is not None else None,
                "until": _day(stamps.iloc[back] if back is not None else stamps.iloc[-1]),
                "days": ((stamps.iloc[back] if back is not None else stamps.iloc[-1]) - start).days,
            }
        )
    return out


def _tail(returns: pd.Series, least: int, what: str) -> dict[str, Any]:
    """The average of the worst ``TAIL_SHARE`` of ``returns`` (expected shortfall)."""
    if len(returns) < least:
        few = int(np.ceil(TAIL_SHARE * least))
        return not_measured(f"fewer than {least} {what}; the worst 5 % would hold fewer than {few}")
    count = int(np.ceil(TAIL_SHARE * len(returns)))
    worst = np.sort(returns.to_numpy(dtype=float))[:count]
    return {
        **measured(float(worst.mean()), f"average of the worst 5 % of the {what}"),
        "count": count,
        "of": len(returns),
    }


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
    # Only a stretch that dipped below the high counts: the days between two
    # rising points (a weekend, a week between rows) are not time under water.
    dipped = False
    for value, stamp in zip(equity.iloc[1:], stamps.iloc[1:], strict=True):
        if value >= peak_value:
            days = (stamp - peak_at).days
            if dipped and days > longest[0]:
                longest = (days, peak_at, stamp, True)
            peak_value, peak_at, dipped = float(value), stamp, False
        else:
            dipped = True
    open_days = (last - peak_at).days
    if equity.iloc[-1] < peak_value and open_days > longest[0]:
        longest = (open_days, peak_at, last, False)

    # The deepest fall: high, low and the way back.
    running = equity.cummax()
    depth = equity / running - 1.0
    low = int(depth.idxmin())
    # The last time the high was reached: a flat stretch at the high (a balance
    # curve with no closed trade) is not part of the fall.
    before = equity.iloc[: low + 1].to_numpy()
    high = low - int(np.argmax(before[::-1]))
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
        review["tail_day"] = _tail(day_returns, MIN_TAIL_DAYS, "days")
    else:
        review["worst_day"] = not_measured("the curve has no point on most days")
        review["tail_day"] = not_measured("the curve has no point on most days")

    by_month = series.groupby(series.index.tz_localize(None).to_period("M"))
    monthly = by_month.last()
    if int(by_month.size().iloc[0]) == 1 and len(monthly) > 1:
        # A first month holding only the starting point (a fund record's
        # opening value at the end of the month before its first return) is
        # the base, not a month with a return of zero.
        monthly = monthly.iloc[1:]
    periods = monthly.index
    # The first month is measured from the first point of the file.
    monthly = pd.concat([pd.Series([float(equity.iloc[0])]), monthly.reset_index(drop=True)])
    month_returns = monthly.pct_change().dropna().reset_index(drop=True)
    if len(month_returns) >= MIN_MONTHS:
        worst = int(month_returns.idxmin())
        review["months"] = measured(len(month_returns))
        review["positive_months"] = measured(float((month_returns > 0).mean()))
        review["worst_month"] = measured(float(month_returns.min()))
        review["worst_month_in"] = str(periods[worst])
        review["losing_months_run"] = measured(_longest_losing(month_returns))
        review["tail_month"] = _tail(month_returns, MIN_TAIL_MONTHS, "months")
    else:
        review["months"] = not_measured("fewer than three calendar months")
        review["tail_month"] = not_measured("fewer than three calendar months")

    review["worst_falls"] = _falls(stamps, equity) if fell else []
    span = (last - stamps.iloc[0]).days
    if not fell:
        review["calmar"] = not_measured("the curve never falls below a previous high")
    elif float(depth.iloc[low]) > -MIN_CALMAR_FALL:
        review["calmar"] = not_measured("the deepest fall is under 1 %, too shallow to divide by")
    elif span < MIN_CALMAR_DAYS:
        review["calmar"] = not_measured("under a year of history; it divides an annual return")
    else:
        years = elapsed_years(stamps, len(equity))
        cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)
        # Over the whole file, not the usual trailing 36 months: the deepest
        # fall grows with the length of a history, so the report prints the
        # span beside it and nothing ranks or compares by it.
        review["calmar"] = {
            **measured(
                cagr / abs(float(depth.iloc[low])),
                "compound annual return over the depth of the deepest fall",
            ),
            "years": round(years, 1),
        }
    return review
