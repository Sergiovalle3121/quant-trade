"""Robustness stress tests: how much of the result rests on a few trades or days.

A backtest whose total disappears once its five best trades are removed
depends on rare events that may not repeat. These tests remove the best
outcomes from what was uploaded and report what is left; nothing is
resampled or forecast. Two families:

- on the equity curve (always, from the uploaded returns): total return
  without the best 5 and 10 periods, without the best 1 % of periods, and
  without the best calendar month;
- on closed trades (when uploaded): net result without the best 1 and 5
  trades, without the best 10 % of trades, and without the best exit month,
  after the fees the report itemises.

Every row is MEASURED and says whether what is left stays above zero. A row
that cannot be computed (fewer periods or trades than it removes) is left
out, and the section is NOT_MEASURED when nothing can be computed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.schema import measured
from quant_trade.core.models import Trade

#: The removals, in order. Share rows remove ceil(share x N), at least one.
PERIOD_COUNTS = (5, 10)
PERIOD_SHARE = 0.01
TRADE_COUNTS = (1, 5)
TRADE_SHARE = 0.10

NOTE = "the uploaded history with its best outcomes removed; not a forecast"


def _row(scenario: str, removed: int, value: float, original: float) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "removed": removed,
        "result": measured(value),
        "change": measured(value - original),
        "stays_positive": bool(value > 0),
    }


def _compound(returns: np.ndarray) -> float:
    return float(np.prod(1.0 + returns) - 1.0)


def returns_stress(frame: pd.DataFrame) -> dict[str, Any]:
    """Compounded total return of the curve without its best periods and month."""
    ordered = frame.sort_values("timestamp")
    equity = ordered["equity"].astype(float).to_numpy()
    times = pd.to_datetime(ordered["timestamp"], utc=True).to_numpy()
    if len(equity) < 3 or np.any(equity[:-1] <= 0):
        return {"status": "NOT_MEASURED", "reason": "the curve is too short or not positive"}
    returns = equity[1:] / equity[:-1] - 1.0
    ends = times[1:]
    original = _compound(returns)
    ranked = np.argsort(-returns, kind="stable")
    rows = []
    share = max(1, math.ceil(PERIOD_SHARE * len(returns)))
    if len(returns) > share and share not in PERIOD_COUNTS:
        kept = _compound(np.delete(returns, ranked[:share]))
        rows.append(_row("best_1pct_periods", share, kept, original))
    for count in PERIOD_COUNTS:
        if len(returns) > count:
            kept = _compound(np.delete(returns, ranked[:count]))
            rows.append(_row(f"best_{count}_periods", count, kept, original))
    months = pd.PeriodIndex(pd.DatetimeIndex(ends).tz_localize(None), freq="M")
    unique = months.unique()
    if len(unique) >= 2:
        by_month = {m: _compound(returns[months == m]) for m in unique}
        best = max(by_month, key=lambda m: (by_month[m], str(m)))
        keep = returns[months != best]
        row = _row("best_month", int((months == best).sum()), _compound(keep), original)
        row["month"] = str(best)
        rows.append(row)
    return {
        "status": "MEASURED",
        "original": measured(original, "compounded total return of the uploaded curve"),
        "rows": rows,
        "note": NOTE,
    }


def trades_stress(trades: Sequence[Trade], *, fees_total: float = 0.0) -> dict[str, Any]:
    """Net result of the closed trades without the best trades and exit month.

    ``fees_total`` (a positive cost) is not attributable to single trades,
    so every row keeps it whole: removing trades never removes their fees,
    which errs on the strict side.
    """
    if len(trades) < 2:
        return {"status": "NOT_MEASURED", "reason": "fewer than two closed trades"}
    pnl = np.array([trade.pnl for trade in trades], dtype=float)
    fees = float(fees_total)
    original = float(pnl.sum()) - fees
    ranked = np.argsort(-pnl, kind="stable")
    rows = []
    for count in TRADE_COUNTS:
        if len(pnl) > count:
            rest = float(np.delete(pnl, ranked[:count]).sum()) - fees
            rows.append(_row(f"best_{count}_trades", count, rest, original))
    share = max(1, math.ceil(TRADE_SHARE * len(pnl)))
    if len(pnl) > share and share not in TRADE_COUNTS:
        rest = float(np.delete(pnl, ranked[:share]).sum()) - fees
        rows.append(_row("best_10pct_trades", share, rest, original))
    months = [pd.Timestamp(trade.exit_time).strftime("%Y-%m") for trade in trades]
    unique = sorted(set(months))
    if len(unique) >= 2:
        by_month = {
            m: float(sum(p for p, mm in zip(pnl, months, strict=True) if mm == m)) for m in unique
        }
        best = max(unique, key=lambda m: (by_month[m], m))
        rest = float(sum(p for p, mm in zip(pnl, months, strict=True) if mm != best)) - fees
        row = _row("best_month", months.count(best), rest, original)
        row["month"] = best
        rows.append(row)
    top = float(pnl[ranked[: min(5, len(pnl))]].sum())
    out: dict[str, Any] = {
        "status": "MEASURED",
        "original": measured(original, "net result of the closed trades after reported fees"),
        "rows": rows,
        "note": NOTE,
    }
    if original > 0:
        out["top5_share"] = measured(top / original, "best five trades / net result")
    return out


__all__ = [
    "NOTE",
    "PERIOD_COUNTS",
    "PERIOD_SHARE",
    "TRADE_COUNTS",
    "TRADE_SHARE",
    "returns_stress",
    "trades_stress",
]
