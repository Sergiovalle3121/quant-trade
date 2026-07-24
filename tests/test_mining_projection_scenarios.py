"""Tests for the deterministic mining projection scenario matrix."""

from __future__ import annotations

from quant_trade.mining.cashflow import ProjectionAssumptions
from quant_trade.mining.market import MiningMarketData
from quant_trade.mining.models import MiningRig
from quant_trade.mining.projection_scenarios import (
    ProjectionScenario,
    default_projection_scenarios,
    npv_band,
    project_scenarios,
    scenario_projection_rows,
)


def _rig() -> MiningRig:
    return MiningRig(
        name="s21", algorithm="sha256", hashrate_hs=2.0e14, power_watts=3500.0,
        hardware_cost_usd=5000.0, useful_life_days=1095.0, uptime_rate=0.95,
        residual_value_usd=200.0,
    )


def _market() -> MiningMarketData:
    return MiningMarketData(
        coin="BTC", algorithm="sha256", coin_price_usd=60000.0, network_hashrate_hs=6.0e20,
        difficulty=8.0e13, block_subsidy_coin=3.125, tx_fee_revenue_coin_per_block=0.15,
        blocks_per_day=144.0, captured_at_utc="2024-05-01T00:00:00Z", source_name="test",
        pool_fee_rate=0.01,
    )


def test_scenario_matrix_runs_all():
    base = ProjectionAssumptions(horizon_days=365)
    results = project_scenarios(_rig(), _market(), base)
    assert len(results) == len(default_projection_scenarios())
    rows = scenario_projection_rows(results)
    assert {r.scenario for r in rows} == {s.name for s in default_projection_scenarios()}


def test_bull_beats_bear_npv():
    base = ProjectionAssumptions(horizon_days=730)
    results = dict(
        (s.name, p) for s, p in project_scenarios(_rig(), _market(), base)
    )
    assert results["bull"].npv_usd > results["bear"].npv_usd
    assert results["price_crash"].npv_usd < results["base"].npv_usd


def test_npv_band_orders_min_median_max():
    base = ProjectionAssumptions(horizon_days=365)
    band = npv_band(project_scenarios(_rig(), _market(), base))
    assert band["min_npv_usd"] <= band["median_npv_usd"] <= band["max_npv_usd"]
    assert band["scenarios"] == float(len(default_projection_scenarios()))


def test_price_multiplier_stacks_on_base():
    base = ProjectionAssumptions(horizon_days=200, price_multiplier=1.0)
    scenario = ProjectionScenario("double", price_multiplier=2.0)
    applied = scenario.apply(base)
    assert applied.price_multiplier == 2.0
