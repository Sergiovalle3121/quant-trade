"""Rented-infrastructure feasibility (AWS / Alibaba Cloud), research-only.

Evaluates provider policy, quotes, benchmarks, and rental economics offline.
Creates no resources, runs no miners, authorizes no spend.
"""

from quant_trade.cloud_rental.economics import RevenueAssumptions, compute_rental_economics
from quant_trade.cloud_rental.feasibility import (
    evaluate_feasibility,
    feasibility_matrix,
    matrix_markdown,
)
from quant_trade.cloud_rental.models import (
    SAFETY_POSTURE,
    BenchmarkEvidence,
    CloudProvider,
    ComputeQuote,
    FeasibilityDecision,
    FeasibilityStatus,
    InstanceSpecification,
    ProviderPolicyEvidence,
    PurchaseModel,
    WorkloadPurpose,
)
from quant_trade.cloud_rental.policy import OFFICIAL_POLICY_SOURCES, evaluate_provider_policy

__all__ = [
    "SAFETY_POSTURE",
    "OFFICIAL_POLICY_SOURCES",
    "BenchmarkEvidence",
    "CloudProvider",
    "ComputeQuote",
    "FeasibilityDecision",
    "FeasibilityStatus",
    "InstanceSpecification",
    "ProviderPolicyEvidence",
    "PurchaseModel",
    "RevenueAssumptions",
    "WorkloadPurpose",
    "compute_rental_economics",
    "evaluate_feasibility",
    "evaluate_provider_policy",
    "feasibility_matrix",
    "matrix_markdown",
]
