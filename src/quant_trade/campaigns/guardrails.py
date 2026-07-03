from __future__ import annotations

from quant_trade.campaigns.models import CampaignResult, GuardrailPolicy


def rejection_reason(result: CampaignResult, policy: GuardrailPolicy) -> str:
    m = result.metrics
    if not result.artifacts_complete:
        return "missing artifacts"
    if policy.require_oos_metrics and "oos_return" not in m:
        return "missing OOS metrics"
    if policy.require_benchmark_comparison and "benchmark_return" not in m:
        return "missing benchmark comparison"
    if policy.require_cost_sensitivity and "cost_sensitivity" not in m:
        return "missing cost sensitivity"
    if m.get("trade_count", 0) < policy.min_trades:
        return "too few trades"
    if abs(m.get("max_drawdown", 0)) > policy.max_drawdown:
        return "drawdown too high"
    if abs(m.get("train_return", 0) - m.get("oos_return", 0)) > policy.max_train_test_gap:
        return "train/test gap too high"
    return ""
