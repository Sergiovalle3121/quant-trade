"""How much capital a strategy needs, at which size, for a given loss limit.

The question a robot buyer or a copier asks before switching it on: "with my
account, at what size can I run this so that a bad year does not take more
than X % of it?". A backtest answers it only in the currency and lot sizes
it was run with. This section turns the closed trades into that answer.

Method: the net result of each closed trade (after the costs the report
itemises), in money and at the backtest's own sizes. One year of trades is
drawn at random with replacement ``samples`` times, and the deepest fall in
money of each drawn year is recorded. The reference fall is the larger of
the 95th percentile of those falls and the deepest fall the history itself
shows, so a history with one long losing streak is not understated by the
resampling, which breaks streaks.

Two readings follow from the reference fall:

* the capital that keeps it within 10, 20, 30 or 50 % of the account at the
  backtest's own size;
* the share of the backtest's size that keeps it within those limits on the
  backtest's own starting balance.

Assumptions, printed with the section: fixed sizes (no compounding, no size
change after wins or losses), trades independent of one another, the
uploaded costs. It measures the history's losses; it does not say how the
strategy will do.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from quant_trade.audit.schema import declared, measured, not_measured
from quant_trade.core.models import Trade

#: Loss limits, as a share of the account, the section answers for.
LOSS_LIMITS: tuple[float, ...] = (0.10, 0.20, 0.30, 0.50)
MIN_TRADES = 30
MIN_SPAN_DAYS = 30
#: Trades in a drawn year are kept within these bounds.
MIN_YEAR_TRADES = 20
MAX_YEAR_TRADES = 20_000
MAX_CELLS = 4_000_000
QUANTILE = 95

RESAMPLED_NOTE = (
    "deepest fall in money over one year of trades drawn at random from the history, "
    "at the backtest's sizes"
)
HISTORY_NOTE = "deepest fall in money of the closed trades in their own order"
REFERENCE_NOTE = "the larger of the resampled 95th percentile and the history's own fall"
CAPITAL_NOTE = "reference fall / loss limit, at the backtest's sizes"
SCALE_NOTE = "loss limit x starting balance / reference fall"
ASSUMPTIONS: dict[str, list[str]] = {
    "es": [
        "Tamaños fijos: sin interés compuesto ni cambios de tamaño tras ganar o perder.",
        "Las operaciones se sortean de forma independiente; la caída del propio historial "
        "cubre las rachas.",
        "Los costes son los que detalla el archivo subido.",
        "Mide las pérdidas del historial; no es una predicción.",
    ],
    "en": [
        "Fixed sizes: no compounding and no size change after wins or losses.",
        "Trades are drawn independently of one another; the history's own fall covers streaks.",
        "Costs are those the uploaded file itemises.",
        "It measures the history's losses; it is not a forecast.",
    ],
}


def _deepest_fall(pnl: np.ndarray) -> np.ndarray:
    """Deepest peak-to-trough fall in money of each row of cumulative results."""
    path = np.cumsum(pnl, axis=-1)
    start = np.zeros((*path.shape[:-1], 1))
    path = np.concatenate([start, path], axis=-1)
    return np.max(np.maximum.accumulate(path, axis=-1) - path, axis=-1)


def capital_review(
    trades: Sequence[Trade],
    *,
    fees: Sequence[float] | None,
    starting_balance: float | None,
    samples: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    """Capital and size for each loss limit, from the closed trades."""
    if len(trades) < MIN_TRADES:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs at least {MIN_TRADES} closed trades; {len(trades)} supplied",
        }
    ordered = sorted(range(len(trades)), key=lambda i: trades[i].exit_time)
    costs = list(fees) if fees is not None else [0.0] * len(trades)
    pnl = np.array([trades[i].pnl - costs[i] for i in ordered], dtype=float)
    first = min(trade.entry_time for trade in trades)
    last = max(trade.exit_time for trade in trades)
    span_days = (last - first).total_seconds() / 86_400
    if span_days < MIN_SPAN_DAYS:
        return {
            "status": "NOT_MEASURED",
            "reason": f"needs trades spread over at least {MIN_SPAN_DAYS} days",
        }
    per_year = int(round(len(pnl) * 365.25 / span_days))
    per_year = min(max(per_year, MIN_YEAR_TRADES), MAX_YEAR_TRADES)
    used = int(max(100, min(samples, MAX_CELLS // per_year)))
    rng = np.random.default_rng(seed)
    drawn = pnl[rng.integers(0, len(pnl), size=(used, per_year))]
    falls = _deepest_fall(drawn)
    history = float(_deepest_fall(pnl))
    resampled = float(np.percentile(falls, QUANTILE))
    reference = max(resampled, history)
    if reference <= 0:
        return {"status": "NOT_MEASURED", "reason": "the trades show no fall to size against"}

    balance = starting_balance if starting_balance and starting_balance > 0 else None
    rows = []
    for limit in LOSS_LIMITS:
        rows.append(
            {
                "limit": limit,
                "capital": measured(reference / limit, CAPITAL_NOTE),
                "size_share": (
                    measured(limit * balance / reference, SCALE_NOTE)
                    if balance
                    else not_measured("the file states no starting balance")
                ),
            }
        )
    return {
        "status": "MEASURED",
        "trades_per_year": measured(
            per_year,
            "closed trades per year in the history"
            if span_days >= 365
            else "closed trades per year at the history's pace; the history is shorter than a year",
        ),
        "fall_p50": measured(float(np.percentile(falls, 50)), RESAMPLED_NOTE),
        "fall_p95": measured(resampled, RESAMPLED_NOTE),
        "fall_history": measured(history, HISTORY_NOTE),
        "fall_reference": measured(reference, REFERENCE_NOTE),
        "starting_balance": (
            declared(balance, "starting balance of the uploaded file")
            if balance
            else not_measured("the file states no starting balance")
        ),
        "rows": rows,
        "method": {"samples": used, "seed": int(seed), "quantile": QUANTILE},
        "assumptions": ASSUMPTIONS,
    }


def scale_text(share: float) -> str:
    """A size share as a reader says it: ``0.35x`` or ``2.0x``."""
    if not math.isfinite(share):
        return "—"
    return f"{share:.2f}x" if share < 1 else f"{share:.1f}x"


__all__ = ["ASSUMPTIONS", "LOSS_LIMITS", "MIN_TRADES", "capital_review", "scale_text"]
