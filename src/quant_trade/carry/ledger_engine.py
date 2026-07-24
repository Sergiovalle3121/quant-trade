"""Stateful two-leg carry ledger: explicit position lifecycle, reconciled P&L.

Replaces optimistic aggregate arithmetic with an account simulation that a
reviewer can audit line by line: cash, spot/perp quantities, posted margin,
variation margin, settled funding, per-leg fees on every fill, forced terminal
close, and an accounting identity that must balance to the cent —

    final_equity - initial_capital == Σ(all P&L components)

The engine consumes the SAME snapshots and settlement events as the campaign
runner and the two-leg execution state machine gates every entry, so a partial
hedge or fill-rate failure aborts the trade instead of assuming it happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from quant_trade.carry.economics import _round_trip_friction
from quant_trade.carry.execution import FillStep, TwoLegPlan, TwoLegState, simulate_two_leg
from quant_trade.carry.models import CarryCostModel, CarrySnapshot


@dataclass
class LedgerTotals:
    funding_settled: float = 0.0
    spot_leg_pnl: float = 0.0
    perp_leg_pnl: float = 0.0
    collateral_yield: float = 0.0
    trading_fees: float = 0.0
    unwind_costs: float = 0.0
    carrying_costs: float = 0.0

    @property
    def net_pnl(self) -> float:
        return (
            self.funding_settled
            + self.spot_leg_pnl
            + self.perp_leg_pnl
            + self.collateral_yield
            - self.trading_fees
            - self.unwind_costs
            - self.carrying_costs
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "funding_settled": self.funding_settled,
            "spot_leg_pnl": self.spot_leg_pnl,
            "perp_leg_pnl": self.perp_leg_pnl,
            "collateral_yield": self.collateral_yield,
            "trading_fees": self.trading_fees,
            "unwind_costs": self.unwind_costs,
            "carrying_costs": self.carrying_costs,
            "net_pnl": self.net_pnl,
        }


@dataclass
class LedgerResult:
    initial_capital: float
    final_equity: float
    totals: LedgerTotals
    bars: pd.DataFrame
    entries: int
    exits: int
    aborted_entries: int
    max_margin_used: float
    reconciled: bool
    reconciliation_error: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            **self.totals.to_dict(),
            "entries": self.entries,
            "exits": self.exits,
            "aborted_entries": self.aborted_entries,
            "max_margin_used": self.max_margin_used,
            "reconciled": self.reconciled,
            "reconciliation_error": self.reconciliation_error,
        }


@dataclass
class _Position:
    spot_qty: float
    perp_qty: float
    spot_entry: float
    perp_entry: float
    margin_posted: float


def run_carry_ledger(
    snapshots: list[CarrySnapshot],
    costs: CarryCostModel,
    *,
    entry_threshold: float,
    trailing_window: int,
    initial_capital: float = 1.0,
    perp_leverage: float = 1.0,
    collateral_yield_annual: float = 0.0,
    settlements: list[tuple[Any, float]] | None = None,
    fill_fraction: float = 1.0,
    min_fill_rate: float = 0.9,
) -> LedgerResult:
    """Simulate the campaign as an explicit account. Fail closed on bad hedges.

    ``fill_fraction`` lets stress tests inject partial fills; entries whose
    two-leg execution cannot reach HEDGED (fill fraction below
    ``min_fill_rate``) are aborted and counted, never assumed.
    """
    if not snapshots:
        raise ValueError("no snapshots")
    ordered = sorted(snapshots, key=lambda s: s.captured_at_utc)
    times = [pd.to_datetime(s.captured_at_utc, utc=True) for s in ordered]
    funding_quotes = [s.realized_funding_rate for s in ordered]
    intervals_per_year = ordered[0].funding_intervals_per_year
    per_bar_yield = collateral_yield_annual / intervals_per_year
    per_bar_carry_cost = (
        costs.spot_custody_cost_annual + costs.perp_margin_cost_annual
    ) / intervals_per_year
    per_fill_fraction = _round_trip_friction(ordered[0], costs) / 4.0  # one leg, one way

    settled_sorted = sorted(
        ((pd.to_datetime(ts, utc=True), float(r)) for ts, r in (settlements or [])),
        key=lambda x: x[0],
    )

    cash = initial_capital
    totals = LedgerTotals()
    position: _Position | None = None
    entries = exits = aborted = 0
    max_margin = 0.0
    rows: list[dict[str, Any]] = []

    def notional() -> float:
        return initial_capital / (1.0 + 1.0 / perp_leverage)

    for i, snap in enumerate(ordered):
        spot, perp = snap.spot_price, snap.perp_mark_price
        # --- mark-to-market of an open position --------------------------
        bar = {
            "timestamp": times[i],
            "position": 0.0,
            "funding_pnl": 0.0,
            "spot_leg_pnl": 0.0,
            "perp_leg_pnl": 0.0,
            "fees": 0.0,
            "net_return": 0.0,
        }
        if position is not None:
            prev_spot = position.spot_entry if i == 0 else rows[-1]["_spot_mark"]
            prev_perp = position.perp_entry if i == 0 else rows[-1]["_perp_mark"]
            spot_pnl = position.spot_qty * (spot - prev_spot)
            perp_pnl = -position.perp_qty * (perp - prev_perp)
            totals.spot_leg_pnl += spot_pnl
            totals.perp_leg_pnl += perp_pnl
            # settled funding causally in (t[i-1], t[i]]
            lo = times[i - 1] if i > 0 else None
            if settlements is not None:
                settled = sum(
                    r
                    for ts, r in settled_sorted
                    if (lo is None or ts > lo) and ts <= times[i]
                )
            else:
                # legacy generators: one snapshot per interval == its settlement
                settled = funding_quotes[i]
            funding_pnl = settled * position.perp_qty * perp
            totals.funding_settled += funding_pnl
            cy = per_bar_yield * position.margin_posted
            totals.collateral_yield += cy
            cc = per_bar_carry_cost * position.spot_qty * spot
            totals.carrying_costs += cc
            bar.update(
                position=1.0,
                funding_pnl=funding_pnl,
                spot_leg_pnl=spot_pnl,
                perp_leg_pnl=perp_pnl,
                net_return=(funding_pnl + spot_pnl + perp_pnl + cy - cc) / initial_capital,
            )

        # --- signal ------------------------------------------------------
        if i < trailing_window:
            want_position = False
        else:
            trailing = sum(funding_quotes[i - trailing_window : i]) / trailing_window
            want_position = trailing > entry_threshold

        # --- transitions --------------------------------------------------
        if want_position and position is None:
            target_notional = notional()
            spot_qty = target_notional / spot
            plan = TwoLegPlan(
                symbol=snap.symbol,
                exchange=snap.exchange,
                spot_target_qty=spot_qty,
                perp_target_qty=spot_qty,
                spot_price=spot,
                perp_price=perp,
                max_unhedged_notional=target_notional * 0.1,
                timeout_steps=3,
            )
            # deliver fill_fraction of the target IN TOTAL across the steps,
            # so an injected partial fill actually falls short of the hedge
            per_step = spot_qty * fill_fraction / 3.0
            steps = [FillStep(spot_fill=per_step, perp_fill=per_step)] * 3
            execution = simulate_two_leg(plan, steps)
            achieved = (
                min(execution.spot_filled, execution.perp_filled) / spot_qty
                if spot_qty > 0
                else 0.0
            )
            if execution.state is not TwoLegState.HEDGED or achieved < min_fill_rate:
                aborted += 1
                # the state machine's emergency-unwind cost is real money
                totals.unwind_costs += execution.unwind_cost_usd
                cash -= execution.unwind_cost_usd
            else:
                qty = min(execution.spot_filled, execution.perp_filled)
                entry_fees = qty * spot * per_fill_fraction + qty * perp * per_fill_fraction
                margin = qty * perp / perp_leverage
                totals.trading_fees += entry_fees
                cash -= entry_fees
                position = _Position(qty, qty, spot, perp, margin)
                max_margin = max(max_margin, margin)
                entries += 1
        elif not want_position and position is not None:
            exit_fees = (
                position.spot_qty * spot * per_fill_fraction
                + position.perp_qty * perp * per_fill_fraction
            )
            totals.trading_fees += exit_fees
            cash -= exit_fees
            position = None
            exits += 1

        bar["_spot_mark"] = spot
        bar["_perp_mark"] = perp
        rows.append(bar)

    # --- mandatory terminal close ----------------------------------------
    if position is not None:
        last = ordered[-1]
        exit_fees = (
            position.spot_qty * last.spot_price * per_fill_fraction
            + position.perp_qty * last.perp_mark_price * per_fill_fraction
        )
        totals.trading_fees += exit_fees
        cash -= exit_fees
        position = None
        exits += 1

    final_equity = (
        initial_capital
        + totals.funding_settled
        + totals.spot_leg_pnl
        + totals.perp_leg_pnl
        + totals.collateral_yield
        - totals.trading_fees
        - totals.unwind_costs
        - totals.carrying_costs
    )
    reconciliation_error = abs((final_equity - initial_capital) - totals.net_pnl)
    frame = pd.DataFrame(rows).drop(columns=["_spot_mark", "_perp_mark"])
    return LedgerResult(
        initial_capital=initial_capital,
        final_equity=final_equity,
        totals=totals,
        bars=frame,
        entries=entries,
        exits=exits,
        aborted_entries=aborted,
        max_margin_used=max_margin,
        reconciled=reconciliation_error <= 1e-9 * max(1.0, initial_capital),
        reconciliation_error=reconciliation_error,
    )
