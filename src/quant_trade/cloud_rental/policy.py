"""Fail-closed provider-policy gates for rented compute.

V7 separates permission to run an ordinary control plane from permission to
hash. AWS Service Terms §1.25 (current 2026-07-09) prohibit cryptocurrency
mining, and Alibaba documents mining as grounds for a security lock.

A boolean, review flag, generic ticket, historical blog post, or declarative
``written_approval`` record cannot unlock hashing. A future implementation may
validate an exact-scope contractual amendment, but V7 still will not execute a
mining workload. This module is not legal advice.
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
                "https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html"
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
            "establishes": ("cryptocurrency mining listed as a security-violation lock example"),
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
    control_plane_allowed: bool = False
    hashing_allowed: bool = False


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
            return PolicyGateResult(
                FeasibilityStatus.BLOCKED_PROVIDER_POLICY,
                reason,
                control_plane_allowed=False,
                hashing_allowed=False,
            )
        return PolicyGateResult(
            FeasibilityStatus.ELIGIBLE_FOR_OFFLINE_EVALUATION,
            "ordinary compute workload; offline evaluation only — no resources are created",
            control_plane_allowed=True,
            hashing_allowed=False,
        )

    # HASHING_WORKER from here on.
    if uses_free_tier_or_credits:
        return PolicyGateResult(
            (
                FeasibilityStatus.BLOCKED_PROVIDER_TERMS
                if provider is CloudProvider.AWS
                else FeasibilityStatus.BLOCKED_PROVIDER_POLICY
            ),
            "mining on Free Tier or promotional credits is prohibited; "
            "no credit-funded evaluation is permitted",
            control_plane_allowed=True,
            hashing_allowed=False,
        )

    if provider is CloudProvider.AWS:
        evidence_note = ""
        if evidence is not None:
            usable, why = _evidence_is_usable(evidence, evaluated_at_utc)
            evidence_note = (
                " The supplied record is current but cannot override the terms."
                if usable
                else f" The supplied record is unusable ({why})."
            )
        return PolicyGateResult(
            FeasibilityStatus.BLOCKED_PROVIDER_TERMS,
            "AWS Service Terms §1.25 effective 2026-07-09 prohibit cryptocurrency "
            "mining; an older blog, generic approval, YAML flag, or human_reviewed "
            f"boolean does not prevail.{evidence_note}",
            evidence.to_dict() if evidence is not None else None,
            control_plane_allowed=True,
            hashing_allowed=False,
        )

    if provider is CloudProvider.ALIBABA:
        evidence_note = ""
        if evidence is not None:
            usable, why = _evidence_is_usable(evidence, evaluated_at_utc)
            evidence_note = (
                " The supplied record is current but cannot enable hashing in V7."
                if usable
                else f" The supplied record is unusable ({why})."
            )
        return PolicyGateResult(
            FeasibilityStatus.BLOCKED_PROVIDER_POLICY,
            "Alibaba Cloud documents cryptocurrency mining as a security-lock "
            f"condition; tickets, flags, and human review do not unlock hashing.{evidence_note}",
            evidence.to_dict() if evidence is not None else None,
            control_plane_allowed=True,
            hashing_allowed=False,
        )

    return PolicyGateResult(
        FeasibilityStatus.BLOCKED_POLICY_UNKNOWN,
        f"no policy model for provider {provider!r}; failing closed",
        control_plane_allowed=False,
        hashing_allowed=False,
    )
