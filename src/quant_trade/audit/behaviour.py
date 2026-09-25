"""How the trades behave around losses.

Traders pay trading journals to be told three things about themselves, and
buyers of a robot want the same three about its logic:

* whether losing trades are held much longer than winning ones (cutting
  winners short and letting losers run: a stop that is far away, moved, or
  missing);
* whether a new trade follows a loss much faster than it follows a win
  (re-entering to win the money back);
* whether the trades that follow a run of losses do worse than the rest.

Each is MEASURED from the entry and exit times of the closed trades and
their net result after the fees the file itemises. The section raises no
red flag and never changes the class: it describes the history, and a
finding is a question to ask, not a verdict.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pandas as pd

from quant_trade.audit.schema import measured
from quant_trade.core.models import Trade

#: Closed trades needed, and winners and losers each.
MIN_TRADES = 30
MIN_EACH = 10
#: Losers held this many times longer than winners, beyond chance, is a finding.
HOLD_RATIO = 1.5
#: A new entry within this time of the previous exit counts as a quick re-entry.
QUICK = timedelta(minutes=15)
#: Quick re-entries after losses at least this often, and twice as often as after wins.
QUICK_SHARE = 0.20
#: Consecutive losses that make a streak, trades needed after one, and the drop
#: in hit rate (percentage points) that makes a finding.
STREAK = 2
MIN_AFTER_STREAK = 15
STREAK_DROP = 0.15
#: Two-sided p-value below which a hold-time difference is beyond chance.
P_VALUE = 0.05

NOTE = "closed trades by entry and exit time; net result after the fees the file itemises"


def _hours(value: timedelta) -> float:
    return value.total_seconds() / 3600


def _mann_whitney_p(first: Sequence[float], second: Sequence[float]) -> float:
    """Two-sided p-value of the Mann-Whitney U test (normal approximation,
    tie-corrected); 1.0 when every value is equal."""
    n1, n2 = len(first), len(second)
    ranks = pd.Series([*first, *second], dtype=float).rank()
    u = float(ranks.iloc[:n1].sum()) - n1 * (n1 + 1) / 2
    counts = pd.Series([*first, *second]).value_counts()
    n = n1 + n2
    ties = float(((counts**3) - counts).sum())
    variance = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
    if variance <= 0:
        return 1.0
    z = (u - n1 * n2 / 2) / math.sqrt(variance)
    return math.erfc(abs(z) / math.sqrt(2))


def behaviour_review(
    trades: Sequence[Trade], fees: Sequence[float] | None = None
) -> dict[str, Any]:
    """Hold times, re-entries and results after losing streaks."""
    if len(trades) < MIN_TRADES:
        return {"status": "NOT_MEASURED", "reason": f"needs at least {MIN_TRADES} closed trades"}
    costs = list(fees) if fees is not None and len(fees) == len(trades) else [0.0] * len(trades)
    rows = sorted(
        (
            (trade.entry_time, trade.exit_time, float(trade.pnl) - float(fee))
            for trade, fee in zip(trades, costs, strict=True)
        ),
        key=lambda row: (row[0], row[1]),
    )
    if not all(math.isfinite(net) for _, _, net in rows):
        return {"status": "NOT_MEASURED", "reason": "a trade result is not a finite number"}
    wins = [_hours(exit_ - entry) for entry, exit_, net in rows if net > 0]
    losses = [_hours(exit_ - entry) for entry, exit_, net in rows if net < 0]
    if len(wins) < MIN_EACH or len(losses) < MIN_EACH:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs at least {MIN_EACH} winning and {MIN_EACH} losing trades",
        }
    review: dict[str, Any] = {"status": "MEASURED", "note": NOTE, "findings": []}

    # 1. Hold times. Daily data (every trade lasting whole days at the same
    # clock time) still compares; zero-length trades carry no duration.
    win_hold = statistics.median(wins)
    loss_hold = statistics.median(losses)
    if win_hold > 0 and loss_hold > 0:
        ratio = loss_hold / win_hold
        p_value = _mann_whitney_p(losses, wins)
        review["hold_win_hours"] = measured(win_hold, "median hours a winning trade stays open")
        review["hold_loss_hours"] = measured(loss_hold, "median hours a losing trade stays open")
        review["hold_ratio"] = measured(ratio, "median losing hold over median winning hold")
        if ratio >= HOLD_RATIO and p_value < P_VALUE:
            review["findings"].append("losers_held_longer")

    # 2. Time from one exit to the next entry, after a loss and after a win.
    after_loss: list[timedelta] = []
    after_win: list[timedelta] = []
    for (_, exit_, net), (entry_next, _, _) in zip(rows, rows[1:], strict=False):
        gap = entry_next - exit_
        if gap < timedelta(0):  # overlapping trades: no pause to measure
            continue
        if net < 0:
            after_loss.append(gap)
        elif net > 0:
            after_win.append(gap)
    if len(after_loss) >= MIN_EACH and len(after_win) >= MIN_EACH:
        quick_loss = sum(gap <= QUICK for gap in after_loss) / len(after_loss)
        quick_win = sum(gap <= QUICK for gap in after_win) / len(after_win)
        review["quick_after_loss"] = measured(
            quick_loss, "share of trades after a loss opened within 15 minutes of it"
        )
        review["quick_after_win"] = measured(
            quick_win, "share of trades after a win opened within 15 minutes of it"
        )
        if quick_loss >= QUICK_SHARE and quick_loss >= 2 * quick_win:
            review["findings"].append("quick_after_loss")

    # 3. The trade after a run of losses, against every trade.
    results = [net for _, _, net in rows]
    after_streak = [
        results[i]
        for i in range(STREAK, len(results))
        if all(results[j] < 0 for j in range(i - STREAK, i))
    ]
    overall = sum(net > 0 for net in results) / len(results)
    review["hit_rate"] = measured(overall, "share of trades with a net profit")
    if len(after_streak) >= MIN_AFTER_STREAK:
        after = sum(net > 0 for net in after_streak) / len(after_streak)
        review["after_streak_trades"] = measured(len(after_streak))
        review["hit_rate_after_streak"] = measured(
            after, f"share with a net profit among trades that follow {STREAK} losses in a row"
        )
        if after <= overall - STREAK_DROP:
            review["findings"].append("worse_after_streak")
    return review


__all__ = ["MIN_EACH", "MIN_TRADES", "behaviour_review"]
