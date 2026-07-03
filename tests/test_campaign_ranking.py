from quant_trade.campaigns.models import CampaignResult, GuardrailPolicy
from quant_trade.campaigns.ranking import rank_candidates


def test_ranking_penalizes_overfitting():
    base = {
        "benchmark_return": 0.05,
        "cost_sensitivity": 0,
        "stress_return": 0.02,
        "max_drawdown": 0.1,
        "turnover": 1,
        "trade_count": 20,
    }
    stable = CampaignResult("stable", "s", {**base, "train_return": 0.08, "oos_return": 0.07})
    overfit = CampaignResult("overfit", "s", {**base, "train_return": 0.30, "oos_return": 0.07})
    ranked = rank_candidates([overfit, stable], GuardrailPolicy(max_train_test_gap=1.0))
    assert ranked[0].run_id == "stable"
    assert ranked[1].overfitting_penalty > ranked[0].overfitting_penalty
