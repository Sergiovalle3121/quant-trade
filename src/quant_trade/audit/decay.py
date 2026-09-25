"""Does it still work in the recent period?

The commonest complaint of robot buyers and signal copiers is a history
that looks strong over many years while its last stretch is flat or losing:
the market changed, the broker changed, or the settings were fitted to the
early years. The totals hide it, because the early years carry them.

From the closed trades, ordered by exit:

* the history's span is cut in three equal stretches of time; the last one
  is the recent period, the first two the earlier one;
* each period's trade count, net result after the fees the file itemises,
  average net per trade and hit rate;
* how far the recent average per trade sits from the earlier one, in
  standard errors (Welch), so a dip that noise explains is told apart from
  a real drop;
* the net result, trade count and hit rate of each calendar year.

``EDGE_FADING`` (WARN) is raised when the earlier trades average a profit,
the recent ones average zero or a loss, and the recent average sits at least
``DROP_Z`` standard errors below the earlier one. Every figure is MEASURED
from the uploaded trades. It describes the history; it says nothing about
later periods.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from quant_trade.audit.redflags import RedFlag
from quant_trade.audit.schema import measured
from quant_trade.core.models import Trade

#: Closed trades needed in all, and in each of the two periods.
MIN_TRADES = 60
MIN_EACH = 20
#: The history must span at least this many days (two years).
MIN_SPAN_DAYS = 730
#: The recent period is the last third of the span.
RECENT_SHARE = 1 / 3
#: Standard errors the recent average must fall below the earlier one.
DROP_Z = 2.0

NOTE = "closed trades by exit date; net result after the fees the file itemises"


def _period(pnl: Sequence[float]) -> dict[str, Any]:
    wins = sum(1 for value in pnl if value > 0)
    return {
        "trades": measured(len(pnl)),
        "net": measured(float(sum(pnl))),
        "mean": measured(float(statistics.fmean(pnl)), "average net result per trade"),
        "win_rate": measured(wins / len(pnl)),
    }


def _drop_z(early: Sequence[float], recent: Sequence[float]) -> float | None:
    """Welch statistic of the recent mean against the earlier one."""
    spread = statistics.variance(early) / len(early) + statistics.variance(recent) / len(recent)
    if spread <= 0:
        return None
    return (statistics.fmean(recent) - statistics.fmean(early)) / math.sqrt(spread)


def recent_review(
    trades: Sequence[Trade], fees: Sequence[float] | None = None
) -> tuple[dict[str, Any], list[RedFlag]]:
    """The recent third of the history against the earlier two thirds."""
    if len(trades) < MIN_TRADES:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs at least {MIN_TRADES} closed trades",
        }, []
    costs = list(fees) if fees is not None and len(fees) == len(trades) else [0.0] * len(trades)
    rows = sorted(
        (
            (trade.exit_time, float(trade.pnl) - float(fee))
            for trade, fee in zip(trades, costs, strict=True)
        ),
        key=lambda row: row[0],
    )
    if not all(math.isfinite(value) for _, value in rows):
        return {"status": "NOT_MEASURED", "reason": "a trade result is not a finite number"}, []
    start = min(trade.entry_time for trade in trades)
    end = rows[-1][0]
    span = end - start
    if span.days < MIN_SPAN_DAYS:
        return {
            "status": "NOT_MEASURED",
            "reason": "the trades span less than two years, too short to compare periods",
        }, []
    cut: datetime = end - span * RECENT_SHARE
    early = [value for at, value in rows if at < cut]
    recent = [value for at, value in rows if at >= cut]
    if len(early) < MIN_EACH or len(recent) < MIN_EACH:
        return {
            "status": "NOT_MEASURED",
            "reason": (
                f"needs at least {MIN_EACH} closed trades in the recent third of the history "
                "and in the earlier two thirds"
            ),
        }, []

    years: dict[int, list[float]] = {}
    for at, value in rows:
        years.setdefault(at.year, []).append(value)
    z = _drop_z(early, recent)
    review: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        "recent_from": cut.date().isoformat(),
        "early": _period(early),
        "recent": _period(recent),
        "drop_z": (
            measured(z, "distance of the recent average from the earlier one, in standard errors")
            if z is not None
            else None
        ),
        "years": [
            {
                "key": year,
                "trades": measured(len(values)),
                "net": measured(float(sum(values))),
                "win_rate": measured(sum(1 for v in values if v > 0) / len(values)),
            }
            for year, values in sorted(years.items())
        ],
    }
    early_mean = statistics.fmean(early)
    recent_mean = statistics.fmean(recent)
    flags: list[RedFlag] = []
    if early_mean > 0 and recent_mean <= 0 and z is not None and z <= -DROP_Z:
        flags.append(
            RedFlag(
                "EDGE_FADING",
                "WARN",
                f"the {len(recent)} trades since {cut.date().isoformat()} (the last third of "
                f"the history) average {recent_mean:+,.2f} per trade, against "
                f"{early_mean:+,.2f} for the {len(early)} earlier ones; the drop is "
                f"{abs(z):.1f} standard errors",
                z,
            )
        )
    review["clean"] = not flags
    return review, flags


__all__ = ["DROP_Z", "MIN_EACH", "MIN_SPAN_DAYS", "MIN_TRADES", "recent_review"]
