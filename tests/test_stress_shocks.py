import pandas as pd

from quant_trade.stress.costs import apply_cost_shock
from quant_trade.stress.models import StressPolicy, StressScenario
from quant_trade.stress.shocks import apply_correlation_spike, apply_price_shock
from quant_trade.stress.simulator import stress_allocation_portfolio


def test_price_shock_persists_from_second_bar_onward():
    data = pd.DataFrame(
        {
            "symbol": ["SPY", "SPY", "SPY"],
            "close": [100.0, 101.0, 102.0],
            "open": [100.0, 101.0, 102.0],
        }
    )
    scenario = StressScenario("drop", "price_shock", {"SPY": -0.1})
    shocked = apply_price_shock(data, scenario)
    assert shocked.loc[0, "close"] == 100.0
    assert shocked.loc[1, "close"] == 101.0 * 0.9
    assert shocked.loc[2, "close"] == 102.0 * 0.9


def test_negative_price_shock_produces_a_loss_not_a_gain():
    dates = [f"2020-01-0{i}" for i in range(1, 6)]
    data = pd.DataFrame(
        {
            "date": dates,
            "symbol": ["SPY"] * 5,
            "close": [100.0, 100.0, 100.0, 100.0, 100.0],
            "open": [100.0] * 5,
        }
    )
    scenario = StressScenario("crash", "price_shock", {"SPY": -0.08})
    policy = StressPolicy()
    result = stress_allocation_portfolio(data, scenario, policy)
    assert result.stressed_total_return < 0.0
    assert result.stressed_max_drawdown <= -0.08 + 1e-9
    assert result.stressed_daily_loss <= -0.08 + 1e-9
    assert not result.scenario_pass


def test_cost_shock_increases_costs():
    scenario = StressScenario(
        "liquidity", "liquidity_shock", liquidity_cost_multiplier=3.0, slippage_bps_add=5.0
    )
    shocked = apply_cost_shock({"spread_bps": 1.0, "slippage_bps": 2.0}, scenario)
    assert shocked["spread_bps"] == 3.0
    assert shocked["slippage_bps"] == 11.0


def test_correlation_spike_expected_direction():
    data = pd.DataFrame(
        {"symbol": ["SPY", "TLT", "SPY", "TLT"], "close": [100.0, 50.0, 100.0, 50.0]}
    )
    scenario = StressScenario(
        "corr", "correlation_spike", {"SPY": -0.05, "TLT": -0.05}, correlation_direction=-1.0
    )
    shocked = apply_correlation_spike(data, scenario)
    # first bar of each symbol is the pre-shock reference and stays unchanged
    assert shocked.loc[0, "close"] == 100.0
    assert shocked.loc[1, "close"] == 50.0
    assert shocked.loc[2, "close"] < 100.0
    assert shocked.loc[3, "close"] < 50.0
