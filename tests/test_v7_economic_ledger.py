from __future__ import annotations

import dataclasses
import math

import pandas as pd
import pytest

from quant_trade.carry.data import synthetic_funding_snapshots
from quant_trade.carry.ledger_engine import run_carry_ledger
from quant_trade.carry.models import CarryCostModel, CarrySnapshot


def _snapshots(periods: int = 30) -> list[CarrySnapshot]:
    return [
        dataclasses.replace(snapshot, realized_funding_rate=0.001)
        for snapshot in synthetic_funding_snapshots(periods=periods, seed=11)
    ]


def _costs() -> CarryCostModel:
    return CarryCostModel(
        half_spread_bps=2.0,
        slippage_bps=2.0,
        market_impact_bps=1.0,
        conversion_withdrawal_cost=0.001,
    )


def test_compounded_authoritative_returns_equal_final_equity():
    result = run_carry_ledger(
        _snapshots(),
        _costs(),
        entry_threshold=0.0,
        trailing_window=2,
        initial_capital=100_000.0,
    )
    compounded = math.prod(1.0 + result.bars["net_return"].astype(float)) - 1.0
    balance_sheet = result.final_equity / result.initial_capital - 1.0
    assert compounded == pytest.approx(balance_sheet, abs=1e-12)
    assert result.bars.iloc[-1]["net_return"] != 0  # terminal exit fees are included


def test_entry_sizing_reserves_margin_and_all_round_trip_costs():
    result = run_carry_ledger(
        _snapshots(),
        _costs(),
        entry_threshold=0.0,
        trailing_window=2,
        initial_capital=100_000.0,
    )
    running_cash = result.initial_capital
    minimum = running_cash
    for cashflow in result.cashflows:
        running_cash += float(cashflow["amount"])
        minimum = min(minimum, running_cash)
    assert minimum >= -1e-9


def test_higher_borrow_cost_cannot_improve_equity():
    base = _snapshots()
    expensive = [dataclasses.replace(row, borrow_rate_annual=0.50) for row in base]
    low = run_carry_ledger(
        base, _costs(), entry_threshold=0.0, trailing_window=2, initial_capital=100_000
    )
    high = run_carry_ledger(
        expensive,
        _costs(),
        entry_threshold=0.0,
        trailing_window=2,
        initial_capital=100_000,
    )
    assert high.totals.borrow_costs > 0
    assert high.final_equity < low.final_equity


def _flat_panel(freq: str) -> list[CarrySnapshot]:
    times = pd.date_range("2026-01-01", "2026-01-03", freq=freq, tz="UTC")
    return [
        CarrySnapshot(
            symbol="BTC",
            exchange="bybit",
            captured_at_utc=timestamp.isoformat(),
            spot_price=100.0,
            perp_mark_price=100.0,
            perp_index_price=100.0,
            realized_funding_rate=0.0,
            taker_fee_bps=0.0,
            data_source="test_only",
        )
        for timestamp in times
    ]


def test_settlement_signal_and_pnl_are_resampling_invariant():
    settlements = [
        (pd.Timestamp("2026-01-01T08:00:00Z"), 0.001),
        (pd.Timestamp("2026-01-01T16:00:00Z"), 0.001),
        (pd.Timestamp("2026-01-02T00:00:00Z"), 0.001),
        (pd.Timestamp("2026-01-02T08:00:00Z"), 0.001),
    ]
    costs = CarryCostModel(
        half_spread_bps=0,
        slippage_bps=0,
        market_impact_bps=0,
    )
    hourly = run_carry_ledger(
        _flat_panel("1h"),
        costs,
        entry_threshold=0,
        trailing_window=2,
        settlements=settlements,
    )
    four_hour = run_carry_ledger(
        _flat_panel("4h"),
        costs,
        entry_threshold=0,
        trailing_window=2,
        settlements=settlements,
    )
    assert hourly.entries == four_hour.entries == 1
    assert hourly.final_equity == pytest.approx(four_hour.final_equity, abs=1e-12)


def test_out_of_order_or_duplicate_events_fail_closed():
    snapshots = _snapshots(5)
    with pytest.raises(ValueError, match="snapshots must be strictly ordered"):
        run_carry_ledger(
            [snapshots[1], snapshots[0]],
            _costs(),
            entry_threshold=0,
            trailing_window=2,
        )
    timestamp = pd.to_datetime(snapshots[2].captured_at_utc, utc=True)
    with pytest.raises(ValueError, match="settlements must be strictly ordered"):
        run_carry_ledger(
            snapshots,
            _costs(),
            entry_threshold=0,
            trailing_window=2,
            settlements=[(timestamp, 0.001), (timestamp, 0.002)],
        )
