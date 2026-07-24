"""The feasibility pipeline: policy → benchmark → freshness → economics.

Order matters and is fail-closed at every step. A BLOCKED policy status ends
the evaluation with the legal/operational reason intact — it is never converted
into an economic NO-GO, and an economic win can never override a block.
"""

from __future__ import annotations

from typing import Any

from quant_trade.cloud_rental.benchmarks import validate_benchmark_for_quote
from quant_trade.cloud_rental.catalog import check_quote_freshness
from quant_trade.cloud_rental.economics import RevenueAssumptions, compute_rental_economics
from quant_trade.cloud_rental.models import (
    SAFETY_POSTURE,
    BenchmarkEvidence,
    CloudProvider,
    ComputeQuote,
    FeasibilityDecision,
    FeasibilityStatus,
    InstanceSpecification,
    ProviderPolicyEvidence,
    WorkloadPurpose,
)
from quant_trade.cloud_rental.policy import evaluate_provider_policy


def evaluate_feasibility(
    *,
    purpose: WorkloadPurpose,
    quote: ComputeQuote,
    spec: InstanceSpecification,
    benchmark: BenchmarkEvidence | None,
    policy_evidence: ProviderPolicyEvidence | None,
    algorithm: str = "sha256",
    manual_hashrate_declared: bool = False,
    revenue: RevenueAssumptions | None = None,
    horizon_hours: float = 24.0 * 30,
    budget_ceiling_usd: float = 1000.0,
    evaluated_at_utc: str,
) -> FeasibilityDecision:
    """Evaluate one provider/purpose/SKU combination, offline, fail-closed."""
    provider = quote.provider

    # 1. Provider policy (legal/operational) — decisive and preserved.
    policy = evaluate_provider_policy(
        provider,
        purpose,
        policy_evidence,
        evaluated_at_utc=evaluated_at_utc,
        uses_free_tier_or_credits=quote.uses_free_tier_or_credits,
    )
    if policy.status is not FeasibilityStatus.ELIGIBLE_FOR_OFFLINE_EVALUATION:
        return FeasibilityDecision(
            provider=str(provider),
            purpose=str(purpose),
            status=str(policy.status),
            policy_reason=policy.reason,
            safety=dict(SAFETY_POSTURE),
        )

    # 2. Quote freshness (recomputed, never trusted).
    freshness_problems = check_quote_freshness(quote, evaluated_at_utc=evaluated_at_utc)
    if freshness_problems:
        return FeasibilityDecision(
            provider=str(provider),
            purpose=str(purpose),
            status=str(FeasibilityStatus.ECONOMIC_NO_GO),
            policy_reason=policy.reason,
            economic_reason="; ".join(freshness_problems),
            safety=dict(SAFETY_POSTURE),
        )

    # 3. Control-plane style workloads: cost summary against budget only.
    if purpose is not WorkloadPurpose.HASHING_WORKER:
        base_price = quote.price_per_hour * quote.fx_rate_to_usd * (1.0 + quote.vat_rate)
        hourly = base_price + quote.all_extras_per_hour_usd
        horizon_cost = hourly * horizon_hours
        within = horizon_cost <= budget_ceiling_usd
        return FeasibilityDecision(
            provider=str(provider),
            purpose=str(purpose),
            status=str(
                FeasibilityStatus.PAPER_CONTROL_PLANE_CANDIDATE
                if within
                else FeasibilityStatus.ECONOMIC_NO_GO
            ),
            policy_reason=policy.reason,
            economic_reason=(
                f"all-in ${hourly:.4f}/h, {horizon_hours:.0f}h horizon "
                f"${horizon_cost:.2f} vs budget ${budget_ceiling_usd:.2f}"
            ),
            details={"all_in_cost_per_hour_usd": hourly, "horizon_cost_usd": horizon_cost},
            safety=dict(SAFETY_POSTURE),
        )

    # 4. Hashing worker: measured benchmark of THIS SKU is mandatory.
    gate = validate_benchmark_for_quote(
        benchmark,
        spec,
        algorithm,
        evaluated_at_utc=evaluated_at_utc,
        manual_hashrate_declared=manual_hashrate_declared,
    )
    if not gate.usable:
        assert gate.status is not None
        return FeasibilityDecision(
            provider=str(provider),
            purpose=str(purpose),
            status=str(gate.status),
            policy_reason=policy.reason,
            benchmark_reason="; ".join(gate.problems),
            safety=dict(SAFETY_POSTURE),
        )
    assert benchmark is not None

    # 5. Economics over cancelable rental flows.
    econ = compute_rental_economics(
        quote,
        benchmark,
        revenue or RevenueAssumptions(hashprice_usd_per_th_day=0.0),
        horizon_hours=horizon_hours,
        budget_ceiling_usd=budget_ceiling_usd,
    )
    positive = econ.economically_positive and econ.within_budget
    return FeasibilityDecision(
        provider=str(provider),
        purpose=str(purpose),
        status=str(
            FeasibilityStatus.ECONOMIC_CANDIDATE_PAPER_ONLY
            if positive
            else FeasibilityStatus.ECONOMIC_NO_GO
        ),
        policy_reason=policy.reason,
        economic_reason=(
            f"margin ${econ.margin_per_hour_usd:.4f}/h at 1x costs, "
            f"${econ.margin_per_hour_2x_costs_usd:.4f}/h at 2x; "
            f"break-even hourly price ${econ.break_even_hourly_price_usd:.4f}"
        ),
        details=econ.to_dict(),
        safety=dict(SAFETY_POSTURE),
    )


def feasibility_matrix(
    evaluations: list[dict[str, Any]], *, evaluated_at_utc: str
) -> list[FeasibilityDecision]:
    """Evaluate a list of loaded rental configs into matrix rows."""
    rows: list[FeasibilityDecision] = []
    for cfg in evaluations:
        revenue_cfg = cfg.get("revenue") or {}
        revenue = (
            RevenueAssumptions(**revenue_cfg) if revenue_cfg else None
        )
        rows.append(
            evaluate_feasibility(
                purpose=cfg["purpose"],
                quote=cfg["quote"],
                spec=cfg["spec"],
                benchmark=cfg.get("benchmark"),
                policy_evidence=cfg.get("policy_evidence"),
                algorithm=str(cfg.get("algorithm", "sha256")),
                manual_hashrate_declared=bool(cfg.get("manual_hashrate_declared")),
                revenue=revenue,
                horizon_hours=float(cfg.get("horizon_hours", 24.0 * 30)),
                budget_ceiling_usd=float(cfg.get("budget_ceiling_usd", 1000.0)),
                evaluated_at_utc=evaluated_at_utc,
            )
        )
    return rows


def matrix_markdown(rows: list[FeasibilityDecision]) -> str:
    lines = [
        "| Provider | Purpose | Status | Policy | Benchmark | Economics |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.provider} | {row.purpose} | **{row.status}** | "
            f"{row.policy_reason or '—'} | {row.benchmark_reason or '—'} | "
            f"{row.economic_reason or '—'} |"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "CloudProvider",
    "evaluate_feasibility",
    "feasibility_matrix",
    "matrix_markdown",
]
