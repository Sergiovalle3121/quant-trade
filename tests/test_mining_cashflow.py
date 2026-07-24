"""Tests for the dynamic per-period mining cash-flow projection."""

from __future__ import annotations

import pytest

from quant_trade.mining.cashflow import ProjectionAssumptions, project_mining_cashflow
from quant_trade.mining.market import MiningMarketData
from quant_trade.mining.models import MiningRig


def _rig(**overrides) -> MiningRig:
    base = dict(
        name="S21-like",
        algorithm="sha256",
        hashrate_hs=2.0e14,  # 200 TH/s
        power_watts=3500.0,
        hardware_cost_usd=5000.0,
        useful_life_days=1095.0,
        uptime_rate=0.95,
        residual_value_usd=200.0,
    )
    base.update(overrides)
    return MiningRig(**base)


def _market(**overrides) -> MiningMarketData:
    base = dict(
        coin="BTC",
        algorithm="sha256",
        coin_price_usd=60000.0,
        network_hashrate_hs=6.0e20,
        difficulty=8.0e13,
        block_subsidy_coin=3.125,
        tx_fee_revenue_coin_per_block=0.15,
        blocks_per_day=144.0,
        captured_at_utc="2024-05-01T00:00:00Z",
        source_name="unit_test",
        pool_fee_rate=0.01,
    )
    base.update(overrides)
    return MiningMarketData(**base)


def test_projection_runs_and_has_horizon_length():
    proj = project_mining_cashflow(_rig(), _market(), ProjectionAssumptions(horizon_days=365))
    assert len(proj.daily_series) == 365
    assert len(proj.monthly_series) >= 12
    assert proj.total_coin_mined > 0


def test_difficulty_growth_makes_npv_below_constant_flow():
    # The core defect fix: with positive difficulty growth, the honest NPV must
    # be BELOW the constant-flow NPV the V1 method produced.
    assumptions = ProjectionAssumptions(
        horizon_days=1095, monthly_difficulty_growth_rate=0.03, electricity_usd_per_kwh=0.05
    )
    proj = project_mining_cashflow(_rig(), _market(), assumptions)
    assert proj.npv_usd < proj.constant_flow_npv_usd
    assert proj.npv_overstatement_vs_constant > 0


def test_zero_growth_converges_to_constant_flow():
    assumptions = ProjectionAssumptions(
        horizon_days=730,
        monthly_difficulty_growth_rate=0.0,
        annual_price_drift=0.0,
        annual_uptime_degradation=0.0,
        annual_hashrate_degradation=0.0,
        annual_energy_inflation=0.0,
        electricity_usd_per_kwh=0.05,
    )
    proj = project_mining_cashflow(_rig(), _market(), assumptions)
    # with no time variation, honest NPV == constant-flow NPV
    assert proj.npv_usd == pytest.approx(proj.constant_flow_npv_usd, rel=1e-9)


def test_halving_reduces_coin_mined():
    assumptions = ProjectionAssumptions(
        horizon_days=400, monthly_difficulty_growth_rate=0.0, halving_day_indices=(200,)
    )
    proj = project_mining_cashflow(_rig(), _market(), assumptions)
    before = proj.daily_series[199]["coin_mined"]
    after = proj.daily_series[200]["coin_mined"]
    # only the subsidy halves; tx fees do not, so the coin-per-block ratio is
    # (3.125/2 + 0.15) / (3.125 + 0.15)
    expected_ratio = (3.125 / 2 + 0.15) / (3.125 + 0.15)
    assert after == pytest.approx(before * expected_ratio, rel=1e-6)
    assert after < before


def test_capex_event_lowers_that_days_cashflow():
    base = project_mining_cashflow(
        _rig(), _market(), ProjectionAssumptions(horizon_days=200)
    )
    with_repair = project_mining_cashflow(
        _rig(), _market(), ProjectionAssumptions(horizon_days=200, capex_events=((100, 1500.0),))
    )
    assert with_repair.daily_series[100]["net_cash_usd"] < base.daily_series[100]["net_cash_usd"]
    assert with_repair.cash_profit_usd == pytest.approx(base.cash_profit_usd - 1500.0, abs=1e-6)


def test_break_evens_and_production_cost_present():
    proj = project_mining_cashflow(_rig(), _market(), ProjectionAssumptions(horizon_days=365))
    assert proj.production_cost_usd_per_coin is not None
    assert proj.break_even_electricity_usd_per_kwh is not None
    assert proj.break_even_coin_price_usd is not None


def test_incompatible_algorithm_raises():
    with pytest.raises(ValueError, match="incompatible"):
        project_mining_cashflow(
            _rig(algorithm="scrypt"), _market(), ProjectionAssumptions(horizon_days=30)
        )


def test_capex_event_out_of_horizon_rejected():
    with pytest.raises(ValueError, match="capex_events"):
        ProjectionAssumptions(horizon_days=100, capex_events=((150, 100.0),))
