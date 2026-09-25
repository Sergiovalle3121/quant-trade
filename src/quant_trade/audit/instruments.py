"""Does it work on each instrument, or does one carry the rest?

Robots and signals often trade several pairs or markets. A total that comes
from one of them, while the others lose, is a result fitted to that one
market: the buyer pays for a portfolio and gets one bet. This module groups
the closed trades by the instrument the file names and reports, for each,
the count, the net result after the fees the file itemises and the hit rate.

Three findings, only when the total is a gain and at least two instruments
carry enough trades to read:

* ``one_carries``: without the best instrument, the others together net
  zero or a loss;
* ``mostly_one``: otherwise, the best instrument still brings two thirds
  or more of the net result;
* ``most_lose``: more than half of those instruments net zero or a loss.

The section raises no red flag and never changes the class: a finding is a
question to ask, not a verdict. Every figure is MEASURED from the upload.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from quant_trade.audit.schema import measured
from quant_trade.core.models import Trade

#: Closed trades needed in the file.
MIN_TRADES = 30
#: Trades an instrument needs for its own row; smaller ones share one row.
MIN_EACH = 10
#: Rows shown before the rest are grouped with the small ones.
MAX_ROWS = 12
#: Share of the net result from the best instrument that makes it "most of it".
CONCENTRATED = 2 / 3
#: The key of the row that groups small instruments.
OTHER = "__other__"

NOTE = "closed trades by the instrument the file names; net result after the fees the file itemises"


def _row(key: str, values: list[float]) -> dict[str, Any]:
    return {
        "key": key,
        "trades": measured(len(values)),
        "net": measured(float(sum(values))),
        "win_rate": measured(sum(1 for v in values if v > 0) / len(values)),
    }


def instrument_review(
    trades: Sequence[Trade],
    symbols: Sequence[str] | None,
    fees: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Each instrument's count, net result and hit rate, and two findings."""
    if not symbols or len(symbols) != len(trades):
        return {
            "status": "NOT_MEASURED",
            "reason": "the file does not name each trade's instrument",
        }
    names = [str(name).strip() for name in symbols]
    if any(not name for name in names):
        return {
            "status": "NOT_MEASURED",
            "reason": "the file does not name each trade's instrument",
        }
    if len(set(names)) < 2:
        return {"status": "NOT_MEASURED", "reason": "every trade is on one instrument"}
    if len(trades) < MIN_TRADES:
        return {"status": "NOT_MEASURED", "reason": f"needs at least {MIN_TRADES} closed trades"}
    costs = list(fees) if fees is not None and len(fees) == len(trades) else [0.0] * len(trades)
    nets = [float(t.pnl) - float(f) for t, f in zip(trades, costs, strict=True)]
    if not all(math.isfinite(net) for net in nets):
        return {"status": "NOT_MEASURED", "reason": "a trade result is not a finite number"}

    groups: dict[str, list[float]] = {}
    for name, net in zip(names, nets, strict=True):
        groups.setdefault(name, []).append(net)
    ordered = sorted(groups, key=lambda name: (-len(groups[name]), name))
    readable = [name for name in ordered if len(groups[name]) >= MIN_EACH]
    shown = readable[:MAX_ROWS]
    rest = [name for name in ordered if name not in shown]
    rows = [_row(name, groups[name]) for name in shown]
    if rest:
        other = _row(OTHER, [net for name in rest for net in groups[name]])
        other["instruments"] = measured(len(rest))
        rows.append(other)

    total = float(sum(nets))
    review: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        "instruments": measured(len(groups)),
        "readable": measured(len(readable)),
        "rows": rows,
        "findings": [],
    }
    if len(readable) >= 2 and total > 0:
        net_of = {name: float(sum(groups[name])) for name in readable}
        best = max(readable, key=lambda name: (net_of[name], name))
        review["best"] = {"key": best, "share": measured(net_of[best] / total)}
        if total - net_of[best] <= 0:
            review["findings"].append("one_carries")
        elif net_of[best] / total >= CONCENTRATED:
            review["findings"].append("mostly_one")
        losing = sum(1 for name in readable if net_of[name] <= 0)
        review["losing"] = measured(losing)
        if losing * 2 > len(readable):
            review["findings"].append("most_lose")
    return review


__all__ = ["MIN_EACH", "MIN_TRADES", "OTHER", "instrument_review"]
