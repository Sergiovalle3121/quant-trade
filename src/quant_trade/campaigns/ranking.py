from __future__ import annotations

from quant_trade.campaigns.guardrails import rejection_reason
from quant_trade.campaigns.models import CampaignResult, GuardrailPolicy, RankedCandidate


def rank_candidates(
    results: list[CampaignResult], policy: GuardrailPolicy
) -> list[RankedCandidate]:
    ranked = [_rank_one(r, policy) for r in results]
    return sorted(ranked, key=lambda r: (r.rejected, -r.composite_score, r.run_id))


def _rank_one(result: CampaignResult, policy: GuardrailPolicy) -> RankedCandidate:
    m = result.metrics
    reason = rejection_reason(result, policy)
    oos_score = m.get("oos_return", 0.0) - m.get("benchmark_return", 0.0)
    robustness_score = m.get("cost_sensitivity", 0.0) + m.get("stress_return", 0.0)
    risk_score = max(0.0, 1.0 - abs(m.get("max_drawdown", 0.0)))
    operational_score = m.get("operational_score", 0.5)
    overfitting_penalty = max(0.0, m.get("train_return", 0.0) - m.get("oos_return", 0.0))
    turnover_penalty = max(0.0, m.get("turnover", 0.0) - policy.max_turnover) * 0.05
    drawdown_penalty = max(0.0, abs(m.get("max_drawdown", 0.0)) - policy.max_drawdown)
    composite = (
        0.35 * oos_score
        + 0.2 * robustness_score
        + 0.25 * risk_score
        + 0.2 * operational_score
        - overfitting_penalty
        - turnover_penalty
        - drawdown_penalty
    )
    return RankedCandidate(
        result.run_id,
        result.strategy,
        composite,
        oos_score,
        robustness_score,
        risk_score,
        operational_score,
        overfitting_penalty,
        turnover_penalty,
        drawdown_penalty,
        bool(reason),
        reason,
    )
