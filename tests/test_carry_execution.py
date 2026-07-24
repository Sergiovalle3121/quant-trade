"""Tests for the simulated two-leg execution state machine."""

from __future__ import annotations

from quant_trade.carry.execution import (
    FillStep,
    TwoLegPlan,
    TwoLegState,
    simulate_two_leg,
)


def _plan(**overrides) -> TwoLegPlan:
    base = dict(
        symbol="BTC",
        exchange="venue",
        spot_target_qty=1.0,
        perp_target_qty=1.0,
        spot_price=30000.0,
        perp_price=30000.0,
        max_unhedged_notional=5000.0,
        timeout_steps=5,
        max_retries=3,
        unwind_cost_bps=10.0,
    )
    base.update(overrides)
    return TwoLegPlan(**base)


def test_successful_hedge_reaches_hedged_and_reconciles():
    steps = [FillStep(spot_fill=1.0, perp_fill=1.0)]
    res = simulate_two_leg(_plan(), steps)
    assert res.state == TwoLegState.HEDGED
    assert res.reconciled
    assert res.delta_notional == 0.0
    assert res.unwind_cost_usd == 0.0
    assert res.spot_filled == 1.0 and res.perp_filled == 1.0


def test_no_phantom_fills_overfill_is_clamped():
    steps = [FillStep(spot_fill=5.0, perp_fill=5.0)]  # request far more than target
    res = simulate_two_leg(_plan(), steps)
    assert res.spot_filled == 1.0  # clamped to target
    assert res.perp_filled == 1.0
    assert res.state == TwoLegState.HEDGED


def test_one_leg_only_triggers_unhedged_risk_then_emergency_unwind():
    # spot fills, perp never available -> unhedged risk -> timeout -> unwind
    steps = [FillStep(spot_fill=1.0, perp_fill=0.0)] * 6
    res = simulate_two_leg(_plan(max_unhedged_notional=1000.0), steps)
    seen_states = {e.get("state") for e in res.events}
    assert TwoLegState.UNHEDGED_RISK.value in seen_states
    assert res.state == TwoLegState.CLOSED  # emergency-unwound
    assert res.unwind_cost_usd > 0
    assert res.delta_notional == 0.0  # flat after unwind
    assert res.reconciled


def test_leg_permanently_unavailable_fails_closed():
    steps = [FillStep(spot_fill=1.0, perp_fill=1.0, perp_available=False)] * 6
    res = simulate_two_leg(_plan(), steps)
    # spot filled, perp could never fill -> unwind back to flat
    assert res.state in (TwoLegState.CLOSED, TwoLegState.REJECTED)
    assert res.delta_notional == 0.0
    assert res.reconciled


def test_no_fills_at_all_is_rejected():
    steps = [FillStep(spot_fill=1.0, perp_fill=1.0, spot_available=False, perp_available=False)] * 3
    res = simulate_two_leg(_plan(), steps)
    assert res.state == TwoLegState.REJECTED
    assert res.spot_filled == 0.0 and res.perp_filled == 0.0
    assert res.unwind_cost_usd == 0.0
    assert res.reconciled


def test_gradual_fills_complete_within_timeout():
    steps = [
        FillStep(spot_fill=0.5, perp_fill=0.5),
        FillStep(spot_fill=0.5, perp_fill=0.5),
    ]
    res = simulate_two_leg(_plan(max_unhedged_notional=20000.0), steps)
    assert res.state == TwoLegState.HEDGED
    assert res.reconciled


def test_audit_trail_is_recorded():
    res = simulate_two_leg(_plan(), [FillStep(spot_fill=1.0, perp_fill=1.0)])
    assert len(res.events) >= 2
    assert res.events[0]["state"] == TwoLegState.PLANNED.value
    assert any(e.get("detail") for e in res.events)


def test_result_serializes():
    res = simulate_two_leg(_plan(), [FillStep(spot_fill=1.0, perp_fill=1.0)])
    d = res.to_dict()
    assert d["state"] == "HEDGED"
    assert isinstance(d["events"], list)
