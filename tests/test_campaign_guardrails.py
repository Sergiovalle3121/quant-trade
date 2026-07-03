from quant_trade.campaigns.guardrails import rejection_reason
from quant_trade.campaigns.models import CampaignResult, GuardrailPolicy


def test_missing_oos_metrics_fail():
    r = CampaignResult(
        "r", "s", {"benchmark_return": 0.1, "cost_sensitivity": 0, "trade_count": 10}
    )
    assert rejection_reason(r, GuardrailPolicy()) == "missing OOS metrics"
