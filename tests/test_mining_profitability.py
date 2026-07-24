from datetime import UTC, datetime

import pytest

from quant_trade.mining.models import MiningMarketSnapshot, MiningPolicy, MiningRig
from quant_trade.mining.profitability import evaluate_all, evaluate_mining
from quant_trade.mining.scenarios import (
    MiningStressScenario,
    default_scenarios,
    evaluate_scenario,
)

_AS_OF = datetime(2026, 7, 23, 1, tzinfo=UTC)


def _market() -> MiningMarketSnapshot:
    return MiningMarketSnapshot(
        coin="TEST",
        algorithm="sha256",
        coin_price_usd=100.0,
        network_hashrate_hs=1_000_000_000,
        block_reward_coin=1.0,
        blocks_per_day=100.0,
        pool_fee_rate=0.01,
        source="unit-test-snapshot",
        captured_at_utc="2026-07-23T00:00:00Z",
    )


def _policy(**overrides) -> MiningPolicy:
    values = {
        "electricity_usd_per_kwh": 0.10,
        "min_daily_profit_usd": 1.0,
        "min_margin_rate": 0.10,
        "price_haircut_rate": 0.20,
        "monthly_difficulty_growth_rate": 0.05,
        "max_temperature_c": 80.0,
    }
    values.update(overrides)
    return MiningPolicy(**values)


def test_profitable_owned_rig_passes_base_and_stress_gates():
    rig = MiningRig(
        name="owned",
        algorithm="sha256",
        hashrate_hs=1_000_000,
        power_watts=1000,
        hardware_cost_usd=1000,
        useful_life_days=1000,
        temperature_c=65,
    )
    result = evaluate_mining(rig, _market(), _policy(), _AS_OF)
    assert result.decision == "GO"
    assert result.net_profit_usd > result.stressed_net_profit_usd > 0
    assert result.break_even_electricity_usd_per_kwh is not None
    assert result.authorized_to_start_miner is False


def test_aws_worker_counts_instance_price_and_not_electricity_twice():
    rig = MiningRig(
        name="aws-worker",
        algorithm="sha256",
        hashrate_hs=1_000_000,
        power_watts=1000,
        infrastructure_hourly_cost_usd=0.20,
        electricity_included=True,
        temperature_c=65,
    )
    result = evaluate_mining(
        rig,
        _market(),
        _policy(electricity_usd_per_kwh=1.0),
        _AS_OF,
    )
    assert result.electricity_cost_usd == 0
    assert result.infrastructure_cost_usd == pytest.approx(4.56)


def test_stress_and_temperature_fail_closed():
    rig = MiningRig(
        name="hot",
        algorithm="sha256",
        hashrate_hs=1_000_000,
        power_watts=2500,
        temperature_c=90,
    )
    result = evaluate_mining(
        rig,
        _market(),
        _policy(price_haircut_rate=0.90, monthly_difficulty_growth_rate=0.50),
        _AS_OF,
    )
    assert result.decision == "NO-GO"
    assert any("stressed" in reason for reason in result.reasons)
    assert any("temperature" in reason for reason in result.reasons)


def test_evaluate_all_ranks_by_stressed_profit_and_rejects_no_matches():
    fast = MiningRig("fast", "sha256", 2_000_000, 1000, temperature_c=60)
    slow = MiningRig("slow", "sha256", 1_000_000, 1000, temperature_c=60)
    ranked = evaluate_all((slow, fast), (_market(),), _policy(), _AS_OF)
    assert [item.rig for item in ranked] == ["fast", "slow"]
    with pytest.raises(ValueError, match="no compatible"):
        evaluate_all(
            (MiningRig("gpu", "ethash", 1, 1, temperature_c=60),),
            (_market(),),
            _policy(),
            _AS_OF,
        )


def test_invalid_rig_is_rejected():
    with pytest.raises(ValueError, match="power_watts"):
        MiningRig("bad", "sha256", 1, -1)


def test_facility_losses_rejects_and_complete_fixed_costs_reduce_profit():
    plain = MiningRig(
        "plain",
        "sha256",
        1_000_000,
        1000,
        temperature_c=60,
    )
    burdened = MiningRig(
        "burdened",
        "sha256",
        1_000_000,
        1000,
        temperature_c=60,
        pue=1.20,
        stale_reject_rate=0.05,
        monthly_demand_charge_usd=30,
        daily_maintenance_cost_usd=1,
    )
    plain_result = evaluate_mining(plain, _market(), _policy(), _AS_OF)
    result = evaluate_mining(burdened, _market(), _policy(), _AS_OF)
    assert result.realized_coin_per_day < result.expected_coin_per_day
    assert result.electricity_cost_usd == pytest.approx(plain_result.electricity_cost_usd * 1.20)
    assert result.demand_charge_usd == 1
    assert result.maintenance_cost_usd == 1
    assert result.net_profit_usd < plain_result.net_profit_usd


def test_total_capex_depreciation_unit_economics_and_cash_flow_are_explicit():
    rig = MiningRig(
        "complete-capex",
        "sha256",
        1_000_000,
        1000,
        hardware_cost_usd=1000,
        shipping_cost_usd=100,
        import_cost_usd=50,
        installation_cost_usd=50,
        residual_value_usd=100,
        useful_life_days=1000,
        temperature_c=60,
    )
    result = evaluate_mining(rig, _market(), _policy(), _AS_OF)
    assert result.total_capex_usd == 1200
    assert result.depreciation_usd == pytest.approx(1.1)
    assert result.net_cash_profit_usd == pytest.approx(
        result.net_profit_usd + result.depreciation_usd
    )
    assert result.efficiency_j_per_th == pytest.approx(1_000_000_000)
    assert result.break_even_coin_price_usd is not None
    assert result.break_even_hashprice_usd_per_th_day is not None
    assert result.production_cost_usd_per_coin is not None
    assert result.npv_usd > 0
    assert result.irr_annual_rate is not None
    assert result.payback_days is not None


def test_tax_and_reporting_fx_are_configured_not_hardcoded():
    rig = MiningRig(
        "taxed",
        "sha256",
        1_000_000,
        1000,
        temperature_c=60,
    )
    untaxed = evaluate_mining(rig, _market(), _policy(tax_rate=0), _AS_OF)
    taxed = evaluate_mining(
        rig,
        _market(),
        _policy(tax_rate=0.30, usd_mxn_rate=20),
        _AS_OF,
    )
    assert taxed.tax_cost_usd > 0
    assert taxed.net_profit_usd < untaxed.net_profit_usd
    assert taxed.net_profit_mxn == pytest.approx(taxed.net_profit_usd * 20)


def test_negative_project_has_no_irr_and_is_no_go():
    rig = MiningRig(
        "uneconomic",
        "sha256",
        1,
        3000,
        hardware_cost_usd=10_000,
        temperature_c=60,
    )
    result = evaluate_mining(rig, _market(), _policy(), _AS_OF)
    assert result.decision == "NO-GO"
    assert result.npv_usd < 0
    assert result.irr_annual_rate is None
    assert any("NPV" in reason for reason in result.reasons)


def test_scenarios_are_deterministic_and_extreme_case_fails_closed():
    rig = MiningRig(
        "scenario-rig",
        "sha256",
        1_000_000,
        1000,
        temperature_c=60,
    )
    scenarios = {item.name: item for item in default_scenarios()}
    base = evaluate_scenario(rig, _market(), _policy(), scenarios["base"], _AS_OF)
    optimistic = evaluate_scenario(rig, _market(), _policy(), scenarios["optimistic"], _AS_OF)
    extreme = evaluate_scenario(rig, _market(), _policy(), scenarios["extreme"], _AS_OF)
    assert optimistic.evaluation.gross_revenue_usd > base.evaluation.gross_revenue_usd
    assert extreme.evaluation.decision == "NO-GO"
    assert any("temperature" in reason for reason in extreme.evaluation.reasons)
    assert evaluate_scenario(rig, _market(), _policy(), scenarios["extreme"], _AS_OF) == extreme
    with pytest.raises(ValueError, match="price_multiplier"):
        MiningStressScenario("bad", price_multiplier=0)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pue": 0.99}, "pue"),
        ({"stale_reject_rate": 1.0}, "stale_reject_rate"),
        (
            {"hardware_cost_usd": 1, "residual_value_usd": 2},
            "residual_value_usd",
        ),
    ],
)
def test_extended_rig_inputs_fail_closed(kwargs, message):
    with pytest.raises(ValueError, match=message):
        MiningRig("bad", "sha256", 1, 1, **kwargs)


def test_market_snapshot_provenance_and_freshness_fail_closed():
    rig = MiningRig(
        "freshness",
        "sha256",
        1_000_000,
        1000,
        temperature_c=60,
    )
    missing = MiningMarketSnapshot(
        coin="TEST",
        algorithm="sha256",
        coin_price_usd=100,
        network_hashrate_hs=1_000_000_000,
        block_reward_coin=1,
        blocks_per_day=100,
    )
    missing_result = evaluate_mining(rig, missing, _policy(), _AS_OF)
    assert missing_result.decision == "NO-GO"
    assert any("source" in reason for reason in missing_result.reasons)
    assert any("capture time" in reason for reason in missing_result.reasons)

    stale = MiningMarketSnapshot(
        **{
            **_market().__dict__,
            "captured_at_utc": "2026-07-20T00:00:00Z",
        }
    )
    stale_result = evaluate_mining(rig, stale, _policy(), _AS_OF)
    assert stale_result.decision == "NO-GO"
    assert any("stale" in reason for reason in stale_result.reasons)
    assert stale_result.market_snapshot_age_hours == pytest.approx(73)
    assert len(stale_result.market_snapshot_sha256) == 64


def test_market_snapshot_future_clock_skew_is_rejected():
    future = MiningMarketSnapshot(
        **{
            **_market().__dict__,
            "captured_at_utc": "2026-07-23T02:00:00Z",
        }
    )
    rig = MiningRig("future", "sha256", 1_000_000, 1000, temperature_c=60)
    result = evaluate_mining(rig, future, _policy(), _AS_OF)
    assert result.decision == "NO-GO"
    assert any("future" in reason for reason in result.reasons)
