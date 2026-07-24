"""Contracts for rented-infrastructure evaluation (AWS / Alibaba Cloud).

The owner buys no mining hardware: only rented capacity is ever considered, and
only on paper. Nothing in this package creates instances, deploys templates, or
spends money — it evaluates quotes, benchmarks, provider policy, and economics
offline, and fails closed whenever evidence is missing, stale, or ambiguous.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class CloudProvider(StrEnum):
    AWS = "aws"
    ALIBABA = "alibaba"


class WorkloadPurpose(StrEnum):
    CONTROL_PLANE = "control_plane"
    RESEARCH_BATCH = "research_batch"
    PAPER_RUNTIME = "paper_runtime"
    HASHING_WORKER = "hashing_worker"


class PurchaseModel(StrEnum):
    ON_DEMAND = "on_demand"
    SPOT = "spot"                      # AWS Spot (DescribeSpotPriceHistory)
    PREEMPTIBLE = "preemptible"        # Alibaba preemptible (DescribePrice SpotStrategy)
    RESERVED_COMPARISON_ONLY = "reserved_comparison_only"


class FeasibilityStatus(StrEnum):
    ELIGIBLE_FOR_OFFLINE_EVALUATION = "ELIGIBLE_FOR_OFFLINE_EVALUATION"
    BLOCKED_PENDING_WRITTEN_APPROVAL = "BLOCKED_PENDING_WRITTEN_APPROVAL"
    BLOCKED_PROVIDER_POLICY = "BLOCKED_PROVIDER_POLICY"
    BLOCKED_POLICY_UNKNOWN = "BLOCKED_POLICY_UNKNOWN"
    BLOCKED_MISSING_BENCHMARK = "BLOCKED_MISSING_BENCHMARK"
    BLOCKED_INCOMPATIBLE_HARDWARE = "BLOCKED_INCOMPATIBLE_HARDWARE"
    ECONOMIC_NO_GO = "ECONOMIC_NO_GO"
    PAPER_CONTROL_PLANE_CANDIDATE = "PAPER_CONTROL_PLANE_CANDIDATE"
    ECONOMIC_CANDIDATE_PAPER_ONLY = "ECONOMIC_CANDIDATE_PAPER_ONLY"


def _non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and >= 0")


@dataclass(frozen=True)
class InstanceSpecification:
    """What the rented SKU physically is (from provider documentation)."""

    provider: CloudProvider
    sku: str  # e.g. "p5.48xlarge", "ecs.gn7i-c32g1.8xlarge"
    region: str
    architecture: str  # "cpu" | "gpu" | "fpga" | "asic"
    vcpus: int
    memory_gb: float
    accelerator_model: str = ""  # e.g. "NVIDIA H100"
    accelerator_count: int = 0
    source_url: str = ""

    def __post_init__(self) -> None:
        if not self.sku.strip():
            raise ValueError("sku is required")
        if self.architecture not in ("cpu", "gpu", "fpga", "asic"):
            raise ValueError("architecture must be cpu|gpu|fpga|asic")
        if self.vcpus <= 0:
            raise ValueError("vcpus must be > 0")
        if self.accelerator_count < 0:
            raise ValueError("accelerator_count must be >= 0")


@dataclass(frozen=True)
class ComputeQuote:
    """One priced offer, captured read-only from the provider's price source.

    ``source_kind`` must match the purchase model: AWS on-demand prices come
    from the Price List API, Spot prices ONLY from DescribeSpotPriceHistory,
    Alibaba prices from DescribePrice — the two families are never mixed.
    """

    provider: CloudProvider
    sku: str
    region: str
    purchase_model: PurchaseModel
    price_per_hour: float
    currency: str
    source_kind: str  # "price_list" | "spot_price_history" | "describe_price" | "fixture"
    source_name: str
    captured_at_utc: str
    source_url: str = ""
    zone: str = ""
    operating_system: str = "Linux"
    tenancy: str = "shared"
    fx_rate_to_usd: float = 1.0
    vat_rate: float = 0.0
    max_age_hours: float = 24.0
    extras_per_hour_usd: dict[str, float] | None = None  # disk, ip, egress, logging
    uses_free_tier_or_credits: bool = False

    def __post_init__(self) -> None:
        if not self.sku.strip() or not self.source_name.strip():
            raise ValueError("sku and source_name are required")
        if not self.captured_at_utc.strip():
            raise ValueError("captured_at_utc is required")
        _non_negative("price_per_hour", self.price_per_hour)
        if self.fx_rate_to_usd <= 0 or not math.isfinite(self.fx_rate_to_usd):
            raise ValueError("fx_rate_to_usd must be finite and > 0")
        if not 0 <= self.vat_rate < 1:
            raise ValueError("vat_rate must be in [0, 1)")
        if self.max_age_hours <= 0:
            raise ValueError("max_age_hours must be > 0")
        valid_kinds = {"price_list", "spot_price_history", "describe_price", "fixture"}
        if self.source_kind not in valid_kinds:
            raise ValueError(f"source_kind must be one of {sorted(valid_kinds)}")
        # Never mix price families: AWS Spot only from spot history; AWS
        # on-demand only from the price list. (Fixtures declare themselves.)
        if self.provider is CloudProvider.AWS and self.source_kind != "fixture":
            if self.purchase_model is PurchaseModel.SPOT and self.source_kind != (
                "spot_price_history"
            ):
                raise ValueError("AWS Spot quotes must come from DescribeSpotPriceHistory")
            if (
                self.purchase_model is PurchaseModel.ON_DEMAND
                and self.source_kind != "price_list"
            ):
                raise ValueError("AWS on-demand quotes must come from the Price List API")
        if self.provider is CloudProvider.ALIBABA and self.source_kind not in (
            "describe_price",
            "fixture",
        ):
            raise ValueError("Alibaba quotes must come from DescribePrice")

    @property
    def all_extras_per_hour_usd(self) -> float:
        return float(sum((self.extras_per_hour_usd or {}).values()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkEvidence:
    """A real, attributable measurement of THIS SKU running THIS algorithm.

    A number typed into YAML is not evidence. Extrapolating between GPU models,
    between SKUs, or from GPU to ASIC is forbidden — the validator enforces an
    exact SKU/accelerator match.
    """

    provider: CloudProvider
    sku: str
    accelerator_model: str
    accelerator_count: int
    algorithm: str
    hashrate_hs: float
    duration_seconds: float
    warmup_seconds: float
    shares_accepted: int
    shares_rejected: int
    captured_at_utc: str
    source: str
    artifact_sha256: str
    image_digest: str = ""
    miner_name: str = ""      # metadata of the offline benchmark artifact only
    miner_version: str = ""   # never an instruction to run anything
    reproducibility_notes: str = ""

    def __post_init__(self) -> None:
        if not self.sku.strip() or not self.source.strip():
            raise ValueError("sku and source are required")
        if not self.artifact_sha256.strip():
            raise ValueError("artifact_sha256 is required for attribution")
        if self.hashrate_hs <= 0 or not math.isfinite(self.hashrate_hs):
            raise ValueError("hashrate_hs must be finite and > 0")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be > 0")
        if self.warmup_seconds < 0:
            raise ValueError("warmup_seconds must be >= 0")
        if self.shares_accepted < 0 or self.shares_rejected < 0:
            raise ValueError("share counts must be >= 0")

    @property
    def reject_rate(self) -> float:
        total = self.shares_accepted + self.shares_rejected
        return self.shares_rejected / total if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderPolicyEvidence:
    """A human-reviewed snapshot of what the provider's terms actually say.

    ``policy_status`` values:
    - ``written_approval``    — an explicit written approval/contractual
      exception exists for THIS account and THIS workload;
    - ``prohibited_default``  — the provider's public terms prohibit or
      security-flag the workload;
    - ``allowed``             — the workload is an ordinary permitted use;
    - ``unknown``             — terms were not reviewed or are ambiguous.

    Registering a URL is not a legal opinion: `human_reviewed` must be set by a
    person, and expiry forces re-review. This module never interprets law.
    """

    provider: CloudProvider
    workload: WorkloadPurpose
    policy_status: str
    source_url: str
    reviewed_at_utc: str
    snapshot_sha256: str
    expires_at_utc: str
    human_reviewed: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        valid = {"written_approval", "prohibited_default", "allowed", "unknown"}
        if self.policy_status not in valid:
            raise ValueError(f"policy_status must be one of {sorted(valid)}")
        if not self.source_url.strip():
            raise ValueError("source_url is required for attribution")
        if not self.snapshot_sha256.strip():
            raise ValueError("snapshot_sha256 is required for attribution")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeasibilityDecision:
    provider: str
    purpose: str
    status: str
    policy_reason: str = ""
    benchmark_reason: str = ""
    economic_reason: str = ""
    details: dict[str, Any] | None = None
    safety: dict[str, bool] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SAFETY_POSTURE: dict[str, bool] = {
    "aws_resources_created": False,
    "alibaba_resources_created": False,
    "external_spend_authorized": False,
    "miner_execution": False,
    "hardware_control_enabled": False,
}
