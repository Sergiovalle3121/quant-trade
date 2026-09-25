"""When the strategy makes and loses money: by weekday and by time of day.

A result that comes almost entirely from one weekday or one session is
fragile in a way the totals hide: a change of broker server time, a holiday
calendar or a news schedule can remove it. This module groups the closed
trades by the weekday and the four-hour block of their entry, as the file
states them (platform or server time), and reports each group's count, net
result after the fees the file itemises per trade, and hit rate. Nothing is resampled or
forecast; every figure is MEASURED from the uploaded trades.

The time-of-day table is left out when every entry carries the same clock
time (daily data), where it would say nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from quant_trade.audit.schema import measured
from quant_trade.core.models import Trade

#: Fewer trades than this make per-group figures noise.
MIN_TRADES = 20
#: Width of a time-of-day block, in hours.
BLOCK_HOURS = 4

NOTE = (
    "Entry times as the file states them (platform or server time); "
    "net result after the fees the file itemises per trade."
)


def _group(keys: list[int], pnl: list[float]) -> list[dict[str, Any]]:
    rows = []
    for key in sorted(set(keys)):
        values = [p for k, p in zip(keys, pnl, strict=True) if k == key]
        wins = sum(1 for p in values if p > 0)
        rows.append(
            {
                "key": key,
                "trades": measured(len(values)),
                "net": measured(float(sum(values))),
                "win_rate": measured(wins / len(values)),
            }
        )
    return rows


def _best_share(rows: list[dict[str, Any]], total: float) -> dict[str, Any] | None:
    """The group with the largest net result and its share of the total."""
    if not rows or total <= 0:
        return None
    best = max(rows, key=lambda row: (row["net"]["value"], -row["key"]))
    return {"key": best["key"], "share": measured(best["net"]["value"] / total)}


def timing_breakdown(
    trades: Sequence[Trade], fees: Sequence[float] | None = None
) -> dict[str, Any]:
    """Closed trades grouped by entry weekday (0 = Monday) and four-hour block."""
    if len(trades) < MIN_TRADES:
        return {"status": "NOT_MEASURED", "reason": f"fewer than {MIN_TRADES} closed trades"}
    entries = [pd.Timestamp(trade.entry_time) for trade in trades]
    costs = list(fees) if fees is not None and len(fees) == len(trades) else [0.0] * len(trades)
    pnl = [float(trade.pnl) - float(fee) for trade, fee in zip(trades, costs, strict=True)]
    total = float(sum(pnl))
    weekdays = _group([entry.weekday() for entry in entries], pnl)
    clock_times = {(entry.hour, entry.minute) for entry in entries}
    blocks = (
        _group([entry.hour // BLOCK_HOURS for entry in entries], pnl)
        if len(clock_times) > 1
        else []
    )
    return {
        "status": "MEASURED",
        "note": NOTE,
        "trades": len(trades),
        "net": measured(total),
        "weekdays": weekdays,
        "blocks": blocks,
        "best_weekday": _best_share(weekdays, total),
        "best_block": _best_share(blocks, total),
    }


__all__ = ["BLOCK_HOURS", "MIN_TRADES", "NOTE", "timing_breakdown"]
