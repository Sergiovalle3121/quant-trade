"""Re-costing is arithmetic; the tests check it against hand-computed numbers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_trade.audit.costs import (
    REFERENCE_BPS_OVER_REPORTED_FEES,
    REFERENCE_BPS_WHEN_ZERO,
    break_even_bps,
    recost_trades,
    reference_bps,
    round_trip_cost,
)
from quant_trade.core.models import Trade

T0 = datetime(2020, 1, 1, tzinfo=UTC)
T1 = datetime(2020, 1, 2, tzinfo=UTC)


def _trade(entry: float, exit_: float, qty: float = 10.0) -> Trade:
    return Trade(
        entry_time=T0,
        exit_time=T1,
        quantity=qty,
        entry_price=entry,
        exit_price=exit_,
        pnl=(exit_ - entry) * qty,
        return_pct=(exit_ - entry) / entry,
    )


def test_round_trip_cost_is_charged_on_both_notionals() -> None:
    # 10 bps per side on 1,000 in and 1,010 out
    assert round_trip_cost(_trade(100.0, 101.0), 10.0) == pytest.approx(1.0 + 1.01)


def test_recost_rows_long_and_short_by_hand() -> None:
    trades = [_trade(100.0, 101.0), _trade(100.0, 99.0)]
    rows = recost_trades(trades, ["long", "short"], 10.0)
    by_multiplier = {row.multiplier: row for row in rows}
    # both trades gain 10 gross (long up 1, short down 1)
    assert by_multiplier[0.0].gross_pnl == pytest.approx(20.0)
    assert by_multiplier[0.0].net_pnl == pytest.approx(20.0)
    # 1x: 10 bps on (1000 + 1010) and on (1000 + 990) = 2.01 + 1.99
    assert by_multiplier[1.0].total_cost == pytest.approx(4.0)
    assert by_multiplier[1.0].net_pnl == pytest.approx(16.0)
    assert by_multiplier[3.0].total_cost == pytest.approx(12.0)
    assert by_multiplier[1.0].win_rate == 1.0
    assert by_multiplier[1.0].trades == 2


def test_break_even_is_exact() -> None:
    trades = [_trade(100.0, 101.0), _trade(100.0, 99.0), _trade(50.0, 52.0, qty=4.0)]
    sides = ["long", "short", "long"]
    be = break_even_bps(trades, sides)
    assert be is not None
    rows = recost_trades(trades, sides, be, multipliers=(1.0,))
    assert rows[0].net_pnl == pytest.approx(0.0, abs=1e-9)
    losing = [_trade(100.0, 99.0)]
    assert break_even_bps(losing, ["long"]) < 0
    assert break_even_bps([], []) is None


def test_reference_bps_assumption_when_zero_declared() -> None:
    assert reference_bps(5.0) == (5.0, False)
    assert reference_bps(0.0) == (REFERENCE_BPS_WHEN_ZERO, True)


def test_recost_refuses_misaligned_or_negative_inputs() -> None:
    with pytest.raises(ValueError):
        recost_trades([_trade(1.0, 2.0)], [], 1.0)
    with pytest.raises(ValueError):
        recost_trades([_trade(1.0, 2.0)], ["long"], -1.0)


def test_reported_costs_sit_in_every_row_and_the_break_even() -> None:
    # Gross +10 and -10; the platform charged 1.5 and 0.5 in commission.
    trades = [_trade(100.0, 101.0), _trade(100.0, 99.0)]
    sides = ["long", "long"]
    rows = recost_trades(trades, sides, 10.0, reported_costs=[1.5, 0.5])
    zero = rows[0]
    assert zero.gross_pnl == pytest.approx(0.0)
    assert zero.total_cost == pytest.approx(2.0)
    assert zero.net_pnl == pytest.approx(-2.0)
    one = rows[1]
    assert one.total_cost == pytest.approx(2.0 + 2.01 + 1.99)
    # Extra bps on top of the reported fees at which the ledger nets zero.
    trades = [_trade(100.0, 102.0)]
    be = break_even_bps(trades, ["long"], reported_costs=[5.0])
    assert be == pytest.approx(10_000.0 * (20.0 - 5.0) / (1_000.0 + 1_020.0))
    at_be = recost_trades(trades, ["long"], be, multipliers=(1.0,), reported_costs=[5.0])
    assert at_be[0].net_pnl == pytest.approx(0.0, abs=1e-9)
    with pytest.raises(ValueError):
        recost_trades(trades, ["long"], 1.0, reported_costs=[])


def test_reference_is_slippage_only_when_the_report_itemises_fees() -> None:
    assert reference_bps(0.0, fees_reported=True) == (REFERENCE_BPS_OVER_REPORTED_FEES, True)
    assert reference_bps(3.0, fees_reported=True) == (3.0, False)
    assert REFERENCE_BPS_OVER_REPORTED_FEES < REFERENCE_BPS_WHEN_ZERO
