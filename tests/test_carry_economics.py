"""Tests for cash-and-carry economics and fail-closed risk gates."""

from __future__ import annotations

import pytest

from quant_trade.carry.economics import evaluate_carry
from quant_trade.carry.models import (
    CarryCostModel,
    CarryPolicy,
    CarryPosition,
    CarrySnapshot,
)


def _snap(**overrides) -> CarrySnapshot:
    base = dict(
        symbol="BTC",
        exchange="venue",
        captured_at_utc="2024-01-01T00:00:00Z",
        spot_price=30000.0,
        perp_mark_price=30030.0,  # basis ~ +0.001
        perp_index_price=30000.0,
        realized_funding_rate=0.0005,  # 5 bp / 8h
        funding_interval_hours=8.0,
        taker_fee_bps=5.0,
        maintenance_margin_rate=0.005,
        borrow_available=True,
        borrow_rate_annual=0.02,
        data_source="real",
    )
    base.update(overrides)
    return CarrySnapshot(**base)


def _pos(**overrides) -> CarryPosition:
    base = dict(notional_usd=100_000.0, holding_days=30.0, perp_leverage=1.0, daily_volatility=0.02)
    base.update(overrides)
    return CarryPosition(**base)


COSTS = CarryCostModel(half_spread_bps=2.0, slippage_bps=1.0, market_impact_bps=1.0)
POLICY = CarryPolicy()


def test_strong_positive_funding_is_go():
    ev = evaluate_carry(_snap(), _pos(), COSTS, POLICY)
    assert ev.decision == "GO", ev.reasons
    assert ev.gross_annual_carry > ev.expected_annual_carry  # reversion haircut applied
    assert ev.net_annual_carry_3x_costs < ev.net_annual_carry  # more cost -> less carry


def test_negative_funding_is_no_go():
    ev = evaluate_carry(_snap(realized_funding_rate=-0.0003), _pos(), COSTS, POLICY)
    assert ev.decision == "NO-GO"
    assert any("funding sign" in r for r in ev.reasons)


def test_high_costs_fail_stress_gates():
    costs = CarryCostModel(half_spread_bps=40.0, slippage_bps=40.0, market_impact_bps=40.0)
    ev = evaluate_carry(_snap(), _pos(holding_days=5.0), costs, POLICY)
    assert ev.decision == "NO-GO"
    assert any("cost stress" in r or "net annualized carry" in r for r in ev.reasons)


def test_stale_snapshot_is_no_go():
    ev = evaluate_carry(_snap(staleness_seconds=9999.0), _pos(), COSTS, POLICY)
    assert ev.decision == "NO-GO"
    assert any("stale" in r for r in ev.reasons)


def test_wide_basis_is_no_go():
    ev = evaluate_carry(_snap(perp_mark_price=33000.0), _pos(), COSTS, POLICY)  # basis 0.10
    assert ev.decision == "NO-GO"
    assert any("basis" in r for r in ev.reasons)


def test_high_leverage_low_liquidation_distance_is_no_go():
    ev = evaluate_carry(_snap(), _pos(perp_leverage=20.0), COSTS, POLICY)
    assert ev.liquidation_distance < POLICY.min_liquidation_distance
    assert ev.decision == "NO-GO"
    assert any("liquidation" in r for r in ev.reasons)


def test_decision_uses_only_realized_funding_not_predicted():
    # Changing the (separate) predicted funding must not change the decision.
    a = evaluate_carry(_snap(predicted_funding_rate=0.5), _pos(), COSTS, POLICY)
    b = evaluate_carry(_snap(predicted_funding_rate=-0.5), _pos(), COSTS, POLICY)
    assert a.decision == b.decision == "GO"
    assert a.net_annual_carry == pytest.approx(b.net_annual_carry)
    assert any("predicted" in n for n in a.field_notes)


def test_break_even_funding_rate_zeroes_net_carry():
    ev = evaluate_carry(_snap(), _pos(), COSTS, POLICY)
    assert ev.break_even_funding_rate is not None
    # At the break-even funding rate, expected carry equals total cost.
    snap_be = _snap(realized_funding_rate=ev.break_even_funding_rate)
    ev_be = evaluate_carry(snap_be, _pos(), COSTS, POLICY)
    assert ev_be.net_annual_carry == pytest.approx(0.0, abs=1e-6)


def test_delta_is_hedged_at_model_level():
    ev = evaluate_carry(_snap(), _pos(), COSTS, POLICY)
    assert ev.delta_after_hedge == 0.0
