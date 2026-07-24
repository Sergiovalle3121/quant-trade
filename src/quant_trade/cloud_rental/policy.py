"""Fail-closed provider-policy gates for rented compute.

Facts this module encodes (sources below; every decision demands a
human-reviewed, attributable, unexpired snapshot — a URL alone proves nothing):

- **AWS**: mining is not categorically banned, but AWS Service Terms §1.25 and
  AWS's own guidance require written approval for crypto-mining workloads, and
  mining on Free Tier / promotional credits is prohibited. Without a verifiable
  written-approval artifact: ``BLOCKED_PENDING_WRITTEN_APPROVAL``.
- **Alibaba Cloud**: cryptocurrency mining is listed as a security-violation
  example that gets ECS instances locked. Default: ``BLOCKED_PROVIDER_POLICY``.
  Only an explicit, current, human-reviewed contractual exception could lift it.
- Control-plane / research / paper workloads are ordinary compute and can be
  evaluated offline — evaluation still creates no resources.

Absent, ambiguous, expired, or unattributable policy evidence is always
``BLOCKED_POLICY_UNKNOWN`` (or the provider's stricter default). BLOCKED is a
legal/operational state and is never collapsed into an economic NO-GO.
This module is not legal advice; human review of the terms is mandatory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quant_trade.carry.quality import parse_utc
from quant_trade.cloud_rental.models import (
    CloudProvider,
    FeasibilityStatus,
    ProviderPolicyEvidence,
    WorkloadPurpose,
)

#: Official sources to snapshot (URL, what it establishes). Capture the page,
#: hash the text, record the date, and have a human review it.
OFFICIAL_POLICY_SOURCES: dict[str, list[dict[str, str]]] = {
    "aws": [
        {
            "url": "https://aws.amazon.com/service-terms/",
            "establishes": "Service Terms including §1.25 obligations",
        },
        {
            "url": (
                "https://aws.amazon.com/blogs/security/detecting-and-preventing-"
                "crypto-mining-in-your-aws-environment/"
            ),
            "establishes": "AWS treats unapproved mining as abuse; written approval path",
        },
        {
            "url": (
                "https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/"
                "price-changes.html"
            ),
            "establishes": "Price List as the on-demand price source",
        },
        {
            "url": (
                "https://docs.aws.amazon.com/AWSEC2/latest/APIReference/"
                "API_DescribeSpotPriceHistory.html"
            ),
            "establishes": "DescribeSpotPriceHistory as the ONLY Spot price source",
        },
        {
            "url": "https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html",
            "establishes": "accelerated instance specifications",
        },
    ],
    "alibaba": [
        {
            "url": (
                "https://www.alibabacloud.com/help/en/ecs/developer-reference/"
                "api-behavior-when-an-instance-is-locked-for-security-reasons"
            ),
            "establishes": (
                "cryptocurrency mining listed as a security-violation lock example"
            ),
        },
        {
            "url": (
                "https://www.alibabacloud.com/help/en/ecs/developer-reference/"
                "api-ecs-2014-05-26-describeprice"
            ),
            "establishes": "DescribePrice as the price source",
        },
        {
            "url": (
                "https://www.alibabacloud.com/help/en/ecs/user-guide/gpu-accelerated-"
                "compute-optimized-and-vgpu-accelerated-instance-families-1"
            ),
            "establishes": "GPU ECS instance families",
        },
    ],
}


@dataclass
class PolicyGateResult:
    status: FeasibilityStatus
    reason: str
    evidence_summary: dict[str, Any] | None = None


def _evidence_is_usable(
    evidence: ProviderPolicyEvidence, evaluated_at_utc: str
) -> tuple[bool, str]:
    if not evidence.human_reviewed:
        return False, "policy snapshot exists but has not been human-reviewed"
    try:
        expires = parse_utc(evidence.expires_at_utc)
        now = parse_utc(evaluated_at_utc)
    except ValueError as exc:
        return False, f"policy evidence timestamps invalid: {exc}"
    if now >= expires:
        return False, f"policy evidence expired at {evidence.expires_at_utc}"
    return True, ""


def evaluate_provider_policy(
    provider: CloudProvider,
    purpose: WorkloadPurpose,
    evidence: ProviderPolicyEvidence | None,
    *,
    evaluated_at_utc: str,
    uses_free_tier_or_credits: bool = False,
) -> PolicyGateResult:
    """Fail-closed policy gate. BLOCKED reasons stay legal, never economic."""
    # Non-hashing workloads: ordinary compute; evaluable offline. An explicit
    # prohibition in reviewed evidence still blocks.
    if purpose is not WorkloadPurpose.HASHING_WORKER:
        if evidence is not None and evidence.policy_status == "prohibited_default":
            usable, why = _evidence_is_usable(evidence, evaluated_at_utc)
            reason = (
                "reviewed policy evidence prohibits this workload"
                if usable
                else f"prohibitive evidence on file but unusable ({why}); failing closed"
            )
            return PolicyGateResult(FeasibilityStatus.BLOCKED_PROVIDER_POLICY, reason)
        return PolicyGateResult(
            FeasibilityStatus.ELIGIBLE_FOR_OFFLINE_EVALUATION,
            "ordinary compute workload; offline evaluation only — no resources are created",
        )

    # HASHING_WORKER from here on.
    if uses_free_tier_or_credits:
        return PolicyGateResult(
            FeasibilityStatus.BLOCKED_PROVIDER_POLICY,
            "mining on Free Tier or promotional credits is prohibited; "
            "no credit-funded evaluation is permitted",
        )

    if provider is CloudProvider.AWS:
        if evidence is None:
            return PolicyGateResult(
                FeasibilityStatus.BLOCKED_PENDING_WRITTEN_APPROVAL,
                "no verifiable AWS Trust & Safety written-approval artifact on file "
                "(AWS Service Terms §1.25); human review of terms is mandatory",
            )
        usable, why = _evidence_is_usable(evidence, evaluated_at_utc)
        if not usable:
            return PolicyGateResult(
                FeasibilityStatus.BLOCKED_PENDING_WRITTEN_APPROVAL,
                f"written-approval artifact unusable: {why}",
            )
        if evidence.policy_status == "written_approval":
            return PolicyGateResult(
                FeasibilityStatus.ELIGIBLE_FOR_OFFLINE_EVALUATION,
                "written approval on file and reviewed; offline evaluation only — "
                "no instance is created and no spend is authorized",
                evidence.to_dict(),
            )
        if evidence.policy_status == "prohibited_default":
            return PolicyGateResult(
                FeasibilityStatus.BLOCKED_PROVIDER_POLICY,
                "reviewed AWS evidence records a prohibition for this account/workload",
            )
        return PolicyGateResult(
            FeasibilityStatus.BLOCKED_POLICY_UNKNOWN,
            f"AWS policy evidence status {evidence.policy_status!r} is not a written approval",
        )

    if provider is CloudProvider.ALIBABA:
        if evidence is None:
            return PolicyGateResult(
                FeasibilityStatus.BLOCKED_PROVIDER_POLICY,
                "Alibaba Cloud lists cryptocurrency mining as a security-violation "
                "lock example; blocked by default absent a written contractual "
                "exception (a ticket or assumption is not enough)",
            )
        usable, why = _evidence_is_usable(evidence, evaluated_at_utc)
        if not usable:
            return PolicyGateResult(
                FeasibilityStatus.BLOCKED_PROVIDER_POLICY,
                f"contractual-exception artifact unusable: {why}; provider default stands",
            )
        if evidence.policy_status == "written_approval":
            return PolicyGateResult(
                FeasibilityStatus.ELIGIBLE_FOR_OFFLINE_EVALUATION,
                "explicit written contractual exception on file and reviewed; offline "
                "evaluation only — no instance is created and no spend is authorized",
                evidence.to_dict(),
            )
        if evidence.policy_status == "unknown":
            return PolicyGateResult(
                FeasibilityStatus.BLOCKED_POLICY_UNKNOWN,
                "Alibaba policy evidence is ambiguous; failing closed",
            )
        return PolicyGateResult(
            FeasibilityStatus.BLOCKED_PROVIDER_POLICY,
            "reviewed Alibaba evidence confirms the default prohibition",
        )

    return PolicyGateResult(
        FeasibilityStatus.BLOCKED_POLICY_UNKNOWN,
        f"no policy model for provider {provider!r}; failing closed",
    )
