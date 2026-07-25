"""Perp-perp cross-venue funding dispersion (H3) — a REAL two-venue engine.

Long the perp with the LOWER settled funding, short the perp with the HIGHER:
the position collects the settled-funding spread while matched delta cancels
direction. Prices are never concatenated across venues — each leg keeps its
own mark series, margin account and collateral pool, and the divergence
between the two marks is real P&L (cross-venue basis risk), not noise.

Costs booked: taker fees on all four fills per round trip (two legs × two
venues), a transfer/rebalancing cost whenever collateral moves between
venues (entries, direction switches), and per-leg emergency close-out at the
end. Reconciliation follows the ledger discipline: cash mutated flow-by-flow
versus independently accumulated category totals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class CrossVenueTotals:
    funding_spread: float = 0.0
    mark_divergence_pnl: float = 0.0
    trading_fees: float = 0.0
    transfer_costs: float = 0.0

    @property
    def net_pnl(self) -> float:
        return (
            self.funding_spread
            + self.mark_divergence_pnl
            - self.trading_fees
            - self.transfer_costs
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "funding_spread": self.funding_spread,
            "mark_divergence_pnl": self.mark_divergence_pnl,
            "trading_fees": self.trading_fees,
            "transfer_costs": self.transfer_costs,
            "net_pnl": self.net_pnl,
        }


@dataclass
class CrossVenueResult:
    initial_capital: float
    final_equity: float
    totals: CrossVenueTotals
    bars: pd.DataFrame
    entries: int
    switches: int
    reconciled: bool
    reconciliation_error: float
    venue_a: str = ""
    venue_b: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            **self.totals.to_dict(),
            "entries": self.entries,
            "switches": self.switches,
            "reconciled": self.reconciled,
            "reconciliation_error": self.reconciliation_error,
            "venue_a": self.venue_a,
            "venue_b": self.venue_b,
        }


def run_perp_perp_dispersion(
    bars_a: list[dict[str, Any]],
    bars_b: list[dict[str, Any]],
    *,
    venue_a: str,
    venue_b: str,
    entry_threshold: float,
    trailing_window: int = 3,
    initial_capital: float = 1.0,
    taker_fee_bps: float = 5.0,
    transfer_cost_bps: float = 5.0,
) -> CrossVenueResult:
    """Simulate the dispersion account over the INNER JOIN of both venues.

    ``bars_x`` rows: ``{"start_ms": int, "mark": float, "settled_in_bar":
    float}`` — per-venue settled funding inside each bar interval. Signals
    come from the trailing mean of the SETTLED spread, never from quotes.
    """
    a_by_ts = {int(b["start_ms"]): b for b in bars_a}
    b_by_ts = {int(b["start_ms"]): b for b in bars_b}
    common = sorted(set(a_by_ts) & set(b_by_ts))
    if len(common) < trailing_window + 2:
        raise ValueError(
            f"only {len(common)} overlapping bars between {venue_a} and {venue_b}; "
            "cross-venue dispersion needs aligned history on BOTH venues"
        )

    per_leg_fee = taker_fee_bps / 1e4
    transfer = transfer_cost_bps / 1e4
    notional = initial_capital / 2.0  # one leg's notional per venue collateral pool

    cash = initial_capital
    totals = CrossVenueTotals()
    direction = 0  # +1: long A / short B (collect B-A); -1: reverse; 0: flat
    entries = switches = 0
    spreads: list[float] = []
    rows: list[dict[str, Any]] = []
    prev_a = prev_b = None

    for ts in common:
        bar_a, bar_b = a_by_ts[ts], b_by_ts[ts]
        settled_spread = float(bar_b["settled_in_bar"]) - float(bar_a["settled_in_bar"])
        funding_pnl = divergence_pnl = 0.0
        if direction != 0 and prev_a is not None and prev_b is not None:
            # short leg RECEIVES its venue's settled funding, long leg PAYS
            funding_pnl = direction * settled_spread * notional
            cash += funding_pnl
            totals.funding_spread += funding_pnl
            ret_a = (float(bar_a["mark"]) - prev_a) / prev_a
            ret_b = (float(bar_b["mark"]) - prev_b) / prev_b
            divergence_pnl = direction * (ret_a - ret_b) * notional
            cash += divergence_pnl
            totals.mark_divergence_pnl += divergence_pnl

        spreads.append(settled_spread)
        if len(spreads) >= trailing_window:
            trailing = sum(spreads[-trailing_window:]) / trailing_window
            want = 1 if trailing > entry_threshold else (
                -1 if trailing < -entry_threshold else 0
            )
        else:
            want = 0

        if want != direction:
            legs_to_trade = (2 if direction != 0 else 0) + (2 if want != 0 else 0)
            fees = legs_to_trade * notional * per_leg_fee
            cash -= fees
            totals.trading_fees += fees
            if want != 0:
                move = notional * transfer
                cash -= move
                totals.transfer_costs += move
                if direction == 0:
                    entries += 1
                else:
                    switches += 1
            direction = want

        rows.append(
            {
                "timestamp": pd.to_datetime(ts, unit="ms", utc=True),
                "direction": direction,
                "settled_spread": settled_spread,
                "funding_pnl": funding_pnl,
                "divergence_pnl": divergence_pnl,
                "net_return": (funding_pnl + divergence_pnl) / initial_capital,
            }
        )
        prev_a, prev_b = float(bar_a["mark"]), float(bar_b["mark"])

    if direction != 0:  # mandatory terminal close of both legs
        fees = 2 * notional * per_leg_fee
        cash -= fees
        totals.trading_fees += fees
        direction = 0

    final_equity = cash
    error = abs((final_equity - initial_capital) - totals.net_pnl)
    return CrossVenueResult(
        initial_capital=initial_capital,
        final_equity=final_equity,
        totals=totals,
        bars=pd.DataFrame(rows),
        entries=entries,
        switches=switches,
        reconciled=error <= 1e-9 * max(1.0, initial_capital),
        reconciliation_error=error,
        venue_a=venue_a,
        venue_b=venue_b,
    )


def panel_to_dispersion_bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """HistoricalCarryPanel rows → per-bar dispersion inputs for ONE venue."""
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "start_ms": int(row["start_ms"]),
                "mark": float(row["mark_close"]),
                "settled_in_bar": float(
                    sum(s["rate"] for s in row.get("funding_settlements", []))
                ),
            }
        )
    return out
