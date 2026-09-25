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
#: Used instead when the client declares zero cost but the platform report
#: itemises the commission, swap and fees it charged. Those are already in
#: the ledger, and a tester fills at bid/ask so the spread is in the prices;
#: what is left is slippage, assumed at 0.5 bps per side (about half a pip on
#: EURUSD at 1.10; 10 bps would be 11 pips) and labelled an assumption.
REFERENCE_BPS_OVER_REPORTED_FEES = 0.5
#: The same 0.5 bps is used for an account history (a real or demo account
#: exported from the platform, Myfxbook, an MQL5 signal or FX Blue) even when
#: it itemises no fee: its fills are the broker's, so the spread and any
#: commission folded into the price are already in each result.
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


def reference_bps(
    declared_bps: float, *, fees_reported: bool = False, real_fills: bool = False
) -> tuple[float, bool]:
    """The per-side cost the sensitivity is anchored on, and whether it is
    the client's figure (``False``) or the zero-cost assumption (``True``).

    With ``fees_reported`` the reference is charged on top of the costs the
    report already itemises, so the assumption is slippage only; the same
    holds with ``real_fills``, an account history whose prices are real."""
    if declared_bps > 0:
        return float(declared_bps), False
    if fees_reported or real_fills:
        return REFERENCE_BPS_OVER_REPORTED_FEES, True
    return REFERENCE_BPS_WHEN_ZERO, True


REAL_FILLS_NOTE = (
    "assumed slippage: an account history's prices are the broker's fills, so the spread "
    "is already in each result; charged on top"
)


def reference_note(assumed: bool, fees_reported: bool, real_fills: bool = False) -> str:
    """Where the reference cost comes from, in the audit's own words."""
    if assumed and real_fills and not fees_reported:
        return REAL_FILLS_NOTE
    if assumed and fees_reported:
        return (
            "assumed slippage: the client declared zero cost; charged on top of the fees "
            "the report itemises"
        )
    if assumed:
        return "assumed: client declared zero cost"
    if fees_reported:
        return "declared by the client; charged on top of the fees the report itemises"
    return "declared by the client"


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
    *,
    reported_costs: list[float] | None = None,
) -> list[RecostRow]:
    """The ledger at each multiple of ``bps_per_side`` charged on entry and exit.

    ``reported_costs`` are per-trade costs the platform already charged
    (positive is a cost). They are part of every row, the 0x one included,
    so a multiple only adds cost on top of what the report measured.
    """
    if len(trades) != len(sides):
        raise ValueError("trades and sides must align")
    charged = list(reported_costs) if reported_costs is not None else [0.0] * len(trades)
    if len(charged) != len(trades):
        raise ValueError("reported_costs and trades must align")
    if bps_per_side < 0:
        raise ValueError("bps_per_side must be non-negative")
    gross = gross_pnls(trades, sides)
    rows: list[RecostRow] = []
    for multiplier in multipliers:
        if multiplier < 0:
            raise ValueError("multipliers must be non-negative")
        bps = bps_per_side * multiplier
        costs = [
            round_trip_cost(trade, bps) + fee for trade, fee in zip(trades, charged, strict=True)
        ]
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


def break_even_bps(
    trades: list[Trade], sides: list[str], *, reported_costs: list[float] | None = None
) -> float | None:
    """Cost per side, in bps, at which the ledger's net pnl is exactly zero.

    Closed form: the cost is linear in bps over the traded notional, so
    ``bps = 10_000 * (sum(gross) - sum(reported)) / sum(entry_notional +
    exit_notional)``, the extra cost on top of what the report already
    charged. ``None`` when nothing was traded. Negative when the ledger
    loses money before any extra cost.
    """
    notional = sum(trade.quantity * (trade.entry_price + trade.exit_price) for trade in trades)
    if notional <= 0:
        return None
    charged = sum(reported_costs) if reported_costs is not None else 0.0
    return 10_000.0 * (sum(gross_pnls(trades, sides)) - charged) / notional


__all__ = [
    "DEFAULT_MULTIPLIERS",
    "REAL_FILLS_NOTE",
    "REFERENCE_BPS_OVER_REPORTED_FEES",
    "REFERENCE_BPS_WHEN_ZERO",
    "RecostRow",
    "break_even_bps",
    "gross_pnl",
    "gross_pnls",
    "reference_note",
    "recost_trades",
    "reference_bps",
    "round_trip_cost",
]
