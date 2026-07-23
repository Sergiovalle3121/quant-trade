import pytest

from quant_trade.mining.models import MiningMarketSnapshot, MiningPolicy, MiningRig
from quant_trade.mining.profitability import evaluate_all, evaluate_mining


def _market() -> MiningMarketSnapshot:
    return MiningMarketSnapshot(
        coin="TEST",
        algorithm="sha256",
        coin_price_usd=100.0,
        network_hashrate_hs=1_000_000_000,
        block_reward_coin=1.0,
        blocks_per_day=100.0,
        pool_fee_rate=0.01,
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
    result = evaluate_mining(rig, _market(), _policy())
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
    result = evaluate_mining(rig, _market(), _policy(electricity_usd_per_kwh=1.0))
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
    )
    assert result.decision == "NO-GO"
    assert any("stressed" in reason for reason in result.reasons)
    assert any("temperature" in reason for reason in result.reasons)


def test_evaluate_all_ranks_by_stressed_profit_and_rejects_no_matches():
    fast = MiningRig("fast", "sha256", 2_000_000, 1000, temperature_c=60)
    slow = MiningRig("slow", "sha256", 1_000_000, 1000, temperature_c=60)
    ranked = evaluate_all((slow, fast), (_market(),), _policy())
    assert [item.rig for item in ranked] == ["fast", "slow"]
    with pytest.raises(ValueError, match="no compatible"):
        evaluate_all(
            (MiningRig("gpu", "ethash", 1, 1, temperature_c=60),),
            (_market(),),
            _policy(),
        )


def test_invalid_rig_is_rejected():
    with pytest.raises(ValueError, match="power_watts"):
        MiningRig("bad", "sha256", 1, -1)

