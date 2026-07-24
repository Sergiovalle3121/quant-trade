"""Evidence-bundle validation: quote ↔ spec ↔ benchmark ↔ policy must be ONE cell.

A rental decision is only as good as the weakest link between its artifacts.
This validator rejects any bundle whose pieces describe different things — a
quote for one SKU with a benchmark from another, evidence crossing providers
or regions, an accelerator swap, an algorithm swap — and byte-verifies every
claimed SHA against the actual artifact bytes on disk. Quotes whose source is
a fixture make the whole bundle TEST_ONLY: valid for exercising the pipeline,
never rankable as a real opportunity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.cloud_rental.models import (
    BenchmarkEvidence,
    ComputeQuote,
    InstanceSpecification,
    ProviderPolicyEvidence,
    WorkloadPurpose,
)
from quant_trade.evidence.canonical_json import sha256_of_file


@dataclass
class BundleValidation:
    status: str
    identity: str = ""
    test_only: bool = False
    identity_problems: list[str] = field(default_factory=list)
    sha_problems: list[str] = field(default_factory=list)
    missing_problems: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        return self.identity_problems + self.sha_problems + self.missing_problems

    @property
    def usable(self) -> bool:
        return self.status in ("VALID", "VALID_TEST_ONLY")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["problems"] = self.problems
        d["usable"] = self.usable
        return d


class EvidenceBundleValidator:
    """Validate one bundle. Collects every problem; the verdict fails closed.

    Verdict precedence (worst first): identity mismatch, unverifiable or
    mismatching SHA, missing evidence. Only a clean bundle is VALID, and only
    a clean bundle with no fixture-sourced quote escapes TEST_ONLY.
    """

    def validate(
        self,
        *,
        spec: InstanceSpecification,
        quote: ComputeQuote,
        benchmark: BenchmarkEvidence | None = None,
        policy_evidence: ProviderPolicyEvidence | None = None,
        workload: WorkloadPurpose = WorkloadPurpose.HASHING_WORKER,
        algorithm: str = "",
        benchmark_artifact_path: str | Path | None = None,
        policy_snapshot_path: str | Path | None = None,
        require_benchmark: bool = True,
    ) -> BundleValidation:
        result = BundleValidation(status="VALID")
        result.identity = "|".join(
            [
                str(spec.provider),
                spec.region,
                spec.sku,
                spec.accelerator_model or "-",
                algorithm or "-",
            ]
        )

        def identity(check: bool, message: str) -> None:
            if not check:
                result.identity_problems.append(message)

        # --- exact four-way identity ------------------------------------
        identity(
            quote.provider == spec.provider,
            f"quote provider {quote.provider} != spec provider {spec.provider}",
        )
        identity(quote.sku == spec.sku, f"quote sku {quote.sku!r} != spec sku {spec.sku!r}")
        identity(
            quote.region == spec.region,
            f"quote region {quote.region!r} != spec region {spec.region!r}",
        )
        if benchmark is not None:
            identity(
                benchmark.provider == spec.provider,
                f"benchmark provider {benchmark.provider} != spec provider {spec.provider}",
            )
            identity(
                benchmark.sku == spec.sku,
                f"benchmark sku {benchmark.sku!r} != spec sku {spec.sku!r} "
                "(cross-SKU extrapolation is forbidden)",
            )
            identity(
                benchmark.accelerator_model == spec.accelerator_model,
                f"benchmark accelerator {benchmark.accelerator_model!r} != "
                f"spec accelerator {spec.accelerator_model!r}",
            )
            identity(
                benchmark.accelerator_count == spec.accelerator_count,
                f"benchmark accelerator count {benchmark.accelerator_count} != "
                f"spec count {spec.accelerator_count}",
            )
            if algorithm:
                identity(
                    benchmark.algorithm == algorithm,
                    f"benchmark algorithm {benchmark.algorithm!r} != requested "
                    f"{algorithm!r}",
                )
        if policy_evidence is not None:
            identity(
                policy_evidence.provider == spec.provider,
                f"policy provider {policy_evidence.provider} != spec provider "
                f"{spec.provider}",
            )
            identity(
                policy_evidence.workload == workload,
                f"policy evidence covers workload {policy_evidence.workload}, "
                f"bundle is for {workload}",
            )

        # --- byte-verified SHAs ------------------------------------------
        if benchmark is not None:
            if benchmark_artifact_path is None:
                result.missing_problems.append(
                    "benchmark artifact bytes unavailable; artifact_sha256 cannot "
                    "be byte-verified"
                )
            elif not Path(benchmark_artifact_path).exists():
                result.missing_problems.append(
                    f"benchmark artifact missing on disk: {benchmark_artifact_path}"
                )
            elif sha256_of_file(benchmark_artifact_path) != benchmark.artifact_sha256:
                result.sha_problems.append(
                    "benchmark artifact bytes do NOT hash to the claimed "
                    "artifact_sha256 — evidence chain broken"
                )
        if policy_evidence is not None:
            if policy_snapshot_path is None:
                result.missing_problems.append(
                    "policy snapshot bytes unavailable; snapshot_sha256 cannot "
                    "be byte-verified"
                )
            elif not Path(policy_snapshot_path).exists():
                result.missing_problems.append(
                    f"policy snapshot missing on disk: {policy_snapshot_path}"
                )
            elif sha256_of_file(policy_snapshot_path) != policy_evidence.snapshot_sha256:
                result.sha_problems.append(
                    "policy snapshot bytes do NOT hash to the claimed "
                    "snapshot_sha256 — evidence chain broken"
                )

        # --- completeness -------------------------------------------------
        if benchmark is None and require_benchmark:
            result.missing_problems.append(
                "no benchmark evidence for this exact SKU (a typed-in hashrate "
                "is not evidence)"
            )

        # --- provenance ---------------------------------------------------
        result.test_only = quote.source_kind == "fixture" or (
            benchmark is not None and benchmark.source.startswith("fixture")
        )

        if result.identity_problems:
            result.status = "REJECTED_IDENTITY_MISMATCH"
        elif result.sha_problems:
            result.status = "REJECTED_SHA_MISMATCH"
        elif result.missing_problems:
            result.status = "REJECTED_MISSING_EVIDENCE"
        elif result.test_only:
            result.status = "VALID_TEST_ONLY"
        return result
