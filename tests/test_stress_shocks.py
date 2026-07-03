import pandas as pd

from quant_trade.stress.costs import apply_cost_shock
from quant_trade.stress.models import StressScenario
from quant_trade.stress.shocks import apply_correlation_spike, apply_price_shock


def test_price_shock_applies_to_first_symbol_row():
    data = pd.DataFrame({"symbol": ["SPY", "SPY"], "close": [100.0, 101.0], "open": [100.0, 101.0]})
    scenario = StressScenario("drop", "price_shock", {"SPY": -0.1})
    shocked = apply_price_shock(data, scenario)
    assert shocked.loc[0, "close"] == 90.0
    assert shocked.loc[1, "close"] == 101.0


def test_cost_shock_increases_costs():
    scenario = StressScenario(
        "liquidity", "liquidity_shock", liquidity_cost_multiplier=3.0, slippage_bps_add=5.0
    )
    shocked = apply_cost_shock({"spread_bps": 1.0, "slippage_bps": 2.0}, scenario)
    assert shocked["spread_bps"] == 3.0
    assert shocked["slippage_bps"] == 11.0


def test_correlation_spike_expected_direction():
    data = pd.DataFrame({"symbol": ["SPY", "TLT"], "close": [100.0, 50.0]})
    scenario = StressScenario(
        "corr", "correlation_spike", {"SPY": -0.05, "TLT": -0.05}, correlation_direction=-1.0
    )
    shocked = apply_correlation_spike(data, scenario)
    assert shocked.loc[0, "close"] < 100.0
    assert shocked.loc[1, "close"] < 50.0
