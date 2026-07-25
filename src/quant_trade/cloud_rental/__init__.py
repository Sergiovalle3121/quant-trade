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
from quant_trade.cloud_rental.hashpower_marketplace import (
    MarketplaceDeliveryEvidence,
    MarketplaceOrderbookEvidence,
    evaluate_marketplace_evidence,
    load_marketplace_delivery,
    load_marketplace_orderbook,
)
from quant_trade.cloud_rental.market import (
    ALGORITHM_UNIT_REGISTRY_VERSION,
    AlgorithmUnitDefinition,
    MarketSnapshot,
    algorithm_unit,
    native_hashrate_units,
    verify_market_snapshot_bytes,
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
    RentalType,
    WorkloadPurpose,
)
from quant_trade.cloud_rental.policy import OFFICIAL_POLICY_SOURCES, evaluate_provider_policy

__all__ = [
    "SAFETY_POSTURE",
    "OFFICIAL_POLICY_SOURCES",
    "ALGORITHM_UNIT_REGISTRY_VERSION",
    "AlgorithmUnitDefinition",
    "MarketSnapshot",
    "MarketplaceDeliveryEvidence",
    "MarketplaceOrderbookEvidence",
    "BenchmarkEvidence",
    "CloudProvider",
    "ComputeQuote",
    "FeasibilityDecision",
    "FeasibilityStatus",
    "InstanceSpecification",
    "ProviderPolicyEvidence",
    "PurchaseModel",
    "RentalType",
    "RevenueAssumptions",
    "WorkloadPurpose",
    "compute_rental_economics",
    "algorithm_unit",
    "evaluate_feasibility",
    "evaluate_provider_policy",
    "evaluate_marketplace_evidence",
    "feasibility_matrix",
    "matrix_markdown",
    "native_hashrate_units",
    "load_marketplace_delivery",
    "load_marketplace_orderbook",
    "verify_market_snapshot_bytes",
]
