import pandas as pd

from quant_trade.stress.models import StressPolicy, StressScenario
from quant_trade.stress.simulator import run_scenario_suite, stress_allocation_portfolio


def test_breach_detection_works():
    data = pd.DataFrame({"date": ["d1", "d2"], "symbol": ["SPY", "SPY"], "close": [100.0, 80.0]})
    policy = StressPolicy(max_daily_loss_pct=0.03, required_symbols=("SPY",))
    result = stress_allocation_portfolio(data, StressScenario("base", "price_shock"), policy)
    assert result.breach_count > 0
    assert result.scenario_pass is False


def test_empty_data_handled_safely():
    result = stress_allocation_portfolio(
        pd.DataFrame(),
        StressScenario("empty", "price_shock"),
        StressPolicy(required_symbols=("SPY",)),
    )
    assert result.scenario_pass is False
    assert result.warnings


def test_run_scenario_suite():
    data = pd.DataFrame({"date": ["d1", "d2"], "symbol": ["SPY", "SPY"], "close": [100.0, 101.0]})
    results = run_scenario_suite(
        data, (StressScenario("one", "price_shock", {"SPY": -0.01}),), StressPolicy()
    )
    assert len(results) == 1
