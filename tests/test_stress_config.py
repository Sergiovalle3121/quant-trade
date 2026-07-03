from pathlib import Path

from quant_trade.stress.config import load_stress_policy, load_suite_config


def test_load_stress_config_forces_real_money_false():
    policy = load_stress_policy(Path("configs/stress/stress_policy_conservative.yaml"))
    assert policy.real_money_ready is False
    assert policy.required_symbols == ("SPY",)


def test_load_suite_config():
    policy, scenarios, payload = load_suite_config(
        Path("configs/stress/allocation_stress_test.yaml")
    )
    assert policy.name == "conservative_phase11"
    assert len(scenarios) == 10
    assert payload["real_money_ready"] is False
