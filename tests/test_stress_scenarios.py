from quant_trade.stress.models import StressResult
from quant_trade.stress.scenarios import rank_scenarios_by_loss


def test_worst_scenario_is_ranked():
    good = StressResult("good", "price_shock", -0.01, -0.01, -0.01, 1.0, 1.0, 1.0, 0, True)
    bad = StressResult("bad", "price_shock", -0.20, -0.20, -0.10, 1.0, 1.0, 1.0, 2, False)
    assert rank_scenarios_by_loss([good, bad])[0].scenario_name == "bad"
