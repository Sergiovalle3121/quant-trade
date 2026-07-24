"""Tests for cash-and-carry stress scenarios."""

from __future__ import annotations

from quant_trade.carry.models import CarryCostModel, CarryPolicy, CarryPosition, CarrySnapshot
from quant_trade.carry.scenarios import (
    CarryScenario,
    default_carry_scenarios,
    evaluate_carry_scenario,
    evaluate_carry_scenarios,
)


def _snap(**overrides) -> CarrySnapshot:
    base = dict(
        symbol="BTC",
        exchange="venue",
        captured_at_utc="2024-01-01T00:00:00Z",
        spot_price=30000.0,
        perp_mark_price=30030.0,
        perp_index_price=30000.0,
        realized_funding_rate=0.0005,
        taker_fee_bps=5.0,
        borrow_available=True,
        borrow_rate_annual=0.02,
        data_source="real",
    )
    base.update(overrides)
    return CarrySnapshot(**base)


POS = CarryPosition(notional_usd=100_000.0, holding_days=30.0)
COSTS = CarryCostModel()
POLICY = CarryPolicy()


def test_base_scenario_matches_direct_evaluation():
    evals = evaluate_carry_scenarios(_snap(), POS, COSTS, POLICY)
    base = next(e for e in evals if e.scenario == "base")
    assert base.decision == "GO"
    assert len(evals) == len(default_carry_scenarios())


def test_funding_sign_flip_becomes_no_go():
    flip = next(s for s in default_carry_scenarios() if s.name == "funding_sign_flip")
    result = evaluate_carry_scenario(_snap(), POS, COSTS, POLICY, flip)
    assert result.decision == "NO-GO"
    assert any("funding sign" in r for r in result.reasons)


def test_depeg_widens_basis_to_no_go():
    depeg = next(s for s in default_carry_scenarios() if s.name == "depeg")
    result = evaluate_carry_scenario(_snap(), POS, COSTS, POLICY, depeg)
    assert result.decision == "NO-GO"
    assert any("basis" in r for r in result.reasons)


def test_exchange_outage_makes_snapshot_stale():
    outage = next(s for s in default_carry_scenarios() if s.name == "exchange_outage")
    result = evaluate_carry_scenario(_snap(), POS, COSTS, POLICY, outage)
    assert result.decision == "NO-GO"
    assert any("stale" in r for r in result.reasons)


def test_extreme_spread_kills_carry():
    spread = next(s for s in default_carry_scenarios() if s.name == "extreme_spread")
    result = evaluate_carry_scenario(_snap(), POS, COSTS, POLICY, spread)
    assert result.decision == "NO-GO"


def test_custom_scenario_validation():
    import pytest

    with pytest.raises(ValueError, match="name"):
        CarryScenario("")
    with pytest.raises(ValueError, match="spread_multiplier"):
        CarryScenario("x", spread_multiplier=-1.0)
