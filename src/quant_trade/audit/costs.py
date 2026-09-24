"""Re-cost a client's closed trades under the declared cost, and its multiples.

A backtest that survives its own declared costs is the weakest claim a
strategy can make: the declared cost is the client's guess, and real fills
are worse more often than better. So the audit reports the trade ledger at
0x, 1x, 2x and 3x the reference cost per side, and the exact cost per side at
which the ledger breaks even. The break-even figure is what a client can
compare with a broker's fee schedule without trusting anyone's model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from quant_trade.backtest.costs import CostModel
from quant_trade.core.models import Trade

#: Used when the client declares zero cost. Every retail venue charges
#: something; ``CONSERVATIVE_COST_MODEL`` in ``backtest/costs.py`` totals
#: 12 bps per side, so 10 bps is a mild assumption, and it is labelled one.
REFERENCE_BPS_WHEN_ZERO = 10.0
DEFAULT_MULTIPLIERS: tuple[float, ...] = (0.0, 1.0, 2.0, 3.0)


@dataclass(frozen=True)
class RecostRow:
    multiplier: float
    cost_bps_per_side: float
    gross_pnl: float
    total_cost: float
    net_pnl: float
    win_rate: float
    mean_net_pnl_per_trade: float
    trades: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reference_bps(declared_bps: float) -> tuple[float, bool]:
    """The per-side cost the sensitivity is anchored on, and whether it is
    the client's figure (``False``) or the zero-cost assumption (``True``)."""
    if declared_bps > 0:
        return float(declared_bps), False
    return REFERENCE_BPS_WHEN_ZERO, True


def gross_pnl(trade: Trade, side: str) -> float:
    sign = -1.0 if side == "short" else 1.0
    return sign * (trade.exit_price - trade.entry_price) * trade.quantity


def gross_pnls(trades: list[Trade], sides: list[str]) -> list[float]:
    return [gross_pnl(trade, side) for trade, side in zip(trades, sides, strict=True)]


def round_trip_cost(trade: Trade, bps_per_side: float) -> float:
    model = CostModel(percentage_commission=bps_per_side / 10_000.0)
    entry_notional = trade.entry_price * trade.quantity
    exit_notional = trade.exit_price * trade.quantity
    return model.trade_cost(entry_notional) + model.trade_cost(exit_notional)


def recost_trades(
    trades: list[Trade],
    sides: list[str],
    bps_per_side: float,
    multipliers: tuple[float, ...] = DEFAULT_MULTIPLIERS,
) -> list[RecostRow]:
    """The ledger at each multiple of ``bps_per_side`` charged on entry and exit."""
    if len(trades) != len(sides):
        raise ValueError("trades and sides must align")
    if bps_per_side < 0:
        raise ValueError("bps_per_side must be non-negative")
    gross = gross_pnls(trades, sides)
    rows: list[RecostRow] = []
    for multiplier in multipliers:
        if multiplier < 0:
            raise ValueError("multipliers must be non-negative")
        bps = bps_per_side * multiplier
        costs = [round_trip_cost(trade, bps) for trade in trades]
        nets = [g - c for g, c in zip(gross, costs, strict=True)]
        rows.append(
            RecostRow(
                multiplier=float(multiplier),
                cost_bps_per_side=float(bps),
                gross_pnl=float(sum(gross)),
                total_cost=float(sum(costs)),
                net_pnl=float(sum(nets)),
                win_rate=float(sum(1 for net in nets if net > 0) / len(nets)) if nets else 0.0,
                mean_net_pnl_per_trade=float(sum(nets) / len(nets)) if nets else 0.0,
                trades=len(nets),
            )
        )
    return rows


def break_even_bps(trades: list[Trade], sides: list[str]) -> float | None:
    """Cost per side, in bps, at which the ledger's net pnl is exactly zero.

    Closed form: the cost is linear in bps over the traded notional, so
    ``bps = 10_000 * sum(gross) / sum(entry_notional + exit_notional)``.
    ``None`` when nothing was traded. Negative when the ledger loses money
    before costs.
    """
    notional = sum(trade.quantity * (trade.entry_price + trade.exit_price) for trade in trades)
    if notional <= 0:
        return None
    return 10_000.0 * sum(gross_pnls(trades, sides)) / notional


__all__ = [
    "DEFAULT_MULTIPLIERS",
    "REFERENCE_BPS_WHEN_ZERO",
    "RecostRow",
    "break_even_bps",
    "gross_pnl",
    "gross_pnls",
    "recost_trades",
    "reference_bps",
    "round_trip_cost",
]
