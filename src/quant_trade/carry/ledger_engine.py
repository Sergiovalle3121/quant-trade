"""Stateful two-leg carry ledger: explicit balance sheet, reconciled P&L.

This is the ONLY promotable P&L path for carry (V6-A). The account is a real
balance sheet, not aggregate arithmetic:

- ``cash`` is mutated flow-by-flow: spot purchases and sales, posted and
  released margin, per-fill fees, one-time conversion/withdrawal costs,
  cash-settled funding, per-bar variation margin on the linear perp,
  collateral yield, carrying costs, and emergency-unwind costs;
- ``spot_qty``/``margin_posted`` are the non-cash accounts; per-bar equity is
  ``cash + spot_qty·spot + margin_posted`` (the perp needs no unrealized term
  because variation margin cash-settles each bar);
- category totals (funding, legs, fees, …) are accumulated in SEPARATE
  variables from the cash mutations, so reconciliation compares two
  independent accounting paths:

      final balance-sheet equity  vs  initial equity + Σ category totals

  and a category bookkeeping error cannot silently match the cash path.

Entries are gated through the two-leg execution state machine: a partial
hedge below ``min_fill_rate`` aborts and books the emergency-unwind cost as
real money. Funding accrues ONLY from settlement events causally inside each
bar. A mandatory terminal close realizes everything back to cash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    conversion_costs: float = 0.0
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
            - self.conversion_costs
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
            "conversion_costs": self.conversion_costs,
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
    cashflows: list[dict[str, Any]] = field(default_factory=list)

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
    signal_rates: list[float] | None = None,
    fill_fraction: float = 1.0,
    min_fill_rate: float = 0.9,
) -> LedgerResult:
    """Simulate the campaign as an explicit account. Fail closed on bad hedges.

    ``signal_rates`` decouples the SIGNAL series from the quoted per-snapshot
    rates (e.g. a settlement-derived series); when ``None`` the quoted rates
    are used. ``fill_fraction`` lets stress tests inject partial fills;
    entries whose two-leg execution cannot reach HEDGED are aborted, never
    assumed.
    """
    if not snapshots:
        raise ValueError("no snapshots")
    ordered = sorted(snapshots, key=lambda s: s.captured_at_utc)
    times = [pd.to_datetime(s.captured_at_utc, utc=True) for s in ordered]
    funding_quotes = [s.realized_funding_rate for s in ordered]
    signals = signal_rates if signal_rates is not None else funding_quotes
    if len(signals) != len(ordered):
        raise ValueError("signal_rates length must match snapshots")
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

    # --- the balance sheet: cash is mutated flow-by-flow --------------------
    cash = initial_capital
    journal: list[dict[str, Any]] = []

    def flow(ts: Any, kind: str, amount: float) -> None:
        nonlocal cash
        cash += amount
        journal.append({"timestamp": str(ts), "type": kind, "amount": amount})

    totals = LedgerTotals()
    position: _Position | None = None
    entries = exits = aborted = 0
    max_margin = 0.0
    rows: list[dict[str, Any]] = []

    def notional() -> float:
        return initial_capital / (1.0 + 1.0 / perp_leverage)

    def close_position(ts: Any, spot: float, perp: float) -> float:
        nonlocal position, exits
        assert position is not None
        exit_fees = (
            position.spot_qty * spot * per_fill_fraction
            + position.perp_qty * perp * per_fill_fraction
        )
        flow(ts, "spot_sale", position.spot_qty * spot)
        flow(ts, "margin_release", position.margin_posted)
        flow(ts, "exit_fees", -exit_fees)
        totals.trading_fees += exit_fees
        position = None
        exits += 1
        return exit_fees

    for i, snap in enumerate(ordered):
        spot, perp = snap.spot_price, snap.perp_mark_price
        bar = {
            "timestamp": times[i],
            "symbol": snap.symbol,
            "funding": funding_quotes[i],
            "signal_rate": signals[i],
            "position": 0.0,
            "funding_pnl": 0.0,
            "spot_leg_pnl": 0.0,
            "perp_leg_pnl": 0.0,
            "basis_pnl": 0.0,
            "collateral_yield": 0.0,
            "carry_cost": 0.0,
            "fees": 0.0,
            "net_return": 0.0,
        }
        # --- mark-to-market + cash flows of an open position --------------
        if position is not None:
            prev_spot = position.spot_entry if i == 0 else rows[-1]["_spot_mark"]
            prev_perp = position.perp_entry if i == 0 else rows[-1]["_perp_mark"]
            spot_pnl = position.spot_qty * (spot - prev_spot)  # unrealized (asset)
            perp_pnl = -position.perp_qty * (perp - prev_perp)  # variation margin
            totals.spot_leg_pnl += spot_pnl
            totals.perp_leg_pnl += perp_pnl
            flow(times[i], "variation_margin", perp_pnl)
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
            flow(times[i], "funding_settlement", funding_pnl)
            cy = per_bar_yield * position.margin_posted
            totals.collateral_yield += cy
            flow(times[i], "collateral_yield", cy)
            cc = per_bar_carry_cost * position.spot_qty * spot
            totals.carrying_costs += cc
            flow(times[i], "carrying_cost", -cc)
            bar.update(
                position=1.0,
                funding_pnl=funding_pnl,
                spot_leg_pnl=spot_pnl,
                perp_leg_pnl=perp_pnl,
                basis_pnl=spot_pnl + perp_pnl,
                collateral_yield=cy,
                carry_cost=cc,
                net_return=(funding_pnl + spot_pnl + perp_pnl + cy - cc)
                / initial_capital,
            )

        # --- signal (decoupled from quoted rates when settlements drive it)
        if i < trailing_window:
            want_position = False
        else:
            trailing = sum(signals[i - trailing_window : i]) / trailing_window
            want_position = trailing > entry_threshold

        # --- transitions ---------------------------------------------------
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
                totals.unwind_costs += execution.unwind_cost_usd
                flow(times[i], "emergency_unwind", -execution.unwind_cost_usd)
            else:
                qty = min(execution.spot_filled, execution.perp_filled)
                entry_fees = qty * spot * per_fill_fraction + qty * perp * per_fill_fraction
                conv = costs.conversion_withdrawal_cost * qty * spot
                margin = qty * perp / perp_leverage
                flow(times[i], "spot_purchase", -qty * spot)
                flow(times[i], "margin_posted", -margin)
                flow(times[i], "entry_fees", -entry_fees)
                if conv > 0:
                    flow(times[i], "conversion_withdrawal", -conv)
                totals.trading_fees += entry_fees
                totals.conversion_costs += conv
                position = _Position(qty, qty, spot, perp, margin)
                max_margin = max(max_margin, margin)
                entries += 1
                bar["fees"] = entry_fees + conv
        elif not want_position and position is not None:
            bar["fees"] = close_position(times[i], spot, perp)

        # --- balance-sheet equity at end of bar ---------------------------
        equity = cash
        if position is not None:
            equity += position.spot_qty * spot + position.margin_posted
        bar["equity"] = equity
        bar["_spot_mark"] = spot
        bar["_perp_mark"] = perp
        rows.append(bar)

    # --- mandatory terminal close -----------------------------------------
    if position is not None:
        close_position(times[-1], ordered[-1].spot_price, ordered[-1].perp_mark_price)
        rows[-1]["equity"] = cash

    # --- reconciliation: two independent accounting paths ------------------
    # LEFT: the balance sheet (cash mutated flow-by-flow; positions closed).
    # RIGHT: initial equity + independently accumulated category totals.
    # NOTE: spot MTM is not a cash flow while held, but the terminal/exit
    # sale realizes exactly the accumulated MTM, so both paths must agree.
    final_equity = cash
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
        cashflows=journal,
    )
