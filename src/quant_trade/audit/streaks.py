"""How long a losing streak does chance alone give these trades?

A buyer who sees "most consecutive losses: 9" cannot tell whether nine is a
warning or ordinary bad luck. With the history's own share of losing trades,
chance alone gives a known distribution of the longest losing run: if each
of ``n`` trades loses with probability ``q``, independently, the chance of no
run of ``k`` losses satisfies the exact recurrence (Feller, 1968, XIII.7)::

    a(m) = 1                          for m < k
    a(k) = 1 - q^k
    a(m) = a(m-1) - p q^k a(m-k-1)    for m > k,  p = 1 - q

so ``P(longest run >= k) = 1 - a(n)``. From it the report shows the median
longest losing run chance gives, the run it reaches one time in twenty, and
how often chance reaches the observed run. A low figure says the losses came
closer together than a random order of the same trades would put them.

Every figure describes the uploaded trades in random order; nothing here
predicts a future streak, and none of it changes the class.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from quant_trade.audit.schema import measured, not_measured

#: Fewer closed trades than this, and the streak says little.
MIN_TRADES = 20
#: "One time in twenty": the run chance reaches with at least this probability.
RARE = 0.05
#: Below this, the losses clustered more than chance would put them.
CLUSTERED = 0.05
#: More trades than this take too long to count exactly.
MAX_TRADES = 100_000

KEYS = ("losing_run_chance", "losing_run_rare", "losing_run_odds")


def longest_run_tail(n: int, q: float, max_k: int) -> np.ndarray:
    """``P(longest run of losses >= k)`` for ``k = 0 .. max_k``, exactly."""
    ks = np.arange(1, max_k + 1)
    columns = np.arange(max_k)
    p = 1.0 - q
    qk = q**ks
    # recent[m % size, j]: probability of no run of ks[j] losses in m trades,
    # kept for the last max_k + 2 values of m, all the recurrence reaches back.
    size = max_k + 2
    recent = np.ones((size, max_k))
    for m in range(1, n + 1):
        row = recent[(m - 1) % size].copy()
        row[ks == m] = 1.0 - qk[ks == m]
        longer = ks < m
        lag = (m - ks[longer] - 1) % size
        row[longer] -= p * qk[longer] * recent[lag, columns[longer]]
        recent[m % size] = row
    tail = np.concatenate(([1.0], 1.0 - recent[n % size]))
    return np.clip(tail, 0.0, 1.0)


def loss_streak_review(pnl: Sequence[float]) -> dict[str, Any]:
    """The observed longest losing run next to the one chance gives."""
    values = np.asarray(pnl, dtype=float)
    n = int(len(values))
    losing = values < 0
    q = float(losing.mean()) if n else 0.0
    if n < MIN_TRADES or n > MAX_TRADES:
        reason = (
            f"fewer than {MIN_TRADES} closed trades"
            if n < MIN_TRADES
            else "too many trades to count the streak exactly"
        )
        return {key: not_measured(reason) for key in KEYS}
    if q <= 0.0 or q >= 1.0:
        return {key: not_measured("needs both losing and other trades") for key in KEYS}
    observed = 0
    run = 0
    for flag in losing:
        run = run + 1 if flag else 0
        observed = max(observed, run)
    # Long enough to hold the observed run and the chance tail beyond it.
    max_k = min(n, max(observed, 1) + 1)
    tail = longest_run_tail(n, q, max_k)
    while max_k < n and tail[-1] >= RARE / 10:
        max_k = min(n, max_k * 2)
        tail = longest_run_tail(n, q, max_k)
    median = int(np.max(np.nonzero(tail >= 0.5)[0]))
    rare = int(np.max(np.nonzero(tail >= RARE)[0]))
    return {
        "losing_run_chance": measured(
            median,
            "median longest losing run when trades lose as often as these, in random order",
        ),
        "losing_run_rare": measured(
            rare, "longest losing run chance reaches once in twenty, at the same loss rate"
        ),
        "losing_run_odds": measured(
            float(tail[observed]),
            "chance of a losing run at least this long, at the same loss rate",
        ),
    }
