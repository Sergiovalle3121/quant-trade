"""Benchmark-evidence validation: a quoted SKU has no hashrate until measured.

Rules enforced here:
- A ``hashrate_hs`` typed into a config is NOT evidence for cloud hardware.
- A benchmark is only valid for the EXACT provider+SKU (and accelerator) it was
  measured on — no extrapolation between GPU models, between SKUs, or GPU→ASIC.
- SHA-256 on general CPU/GPU hardware is architecturally incompatible with ASIC
  economics; without a real benchmark of the exact SKU it is
  ``BLOCKED_INCOMPATIBLE_HARDWARE``, and even with one it must still pass
  policy and economics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quant_trade.carry.quality import parse_utc
from quant_trade.cloud_rental.models import (
    BenchmarkEvidence,
    FeasibilityStatus,
    InstanceSpecification,
)

#: Algorithms whose economic hardware is ASICs; a CPU/GPU SKU claiming them is
#: incompatible unless a real measured benchmark of that exact SKU exists.
ASIC_DOMINATED_ALGORITHMS = frozenset({"sha256", "sha-256", "scrypt"})

MAX_BENCHMARK_AGE_DAYS = 90.0
MIN_BENCHMARK_DURATION_SECONDS = 600.0


@dataclass
class BenchmarkGateResult:
    status: FeasibilityStatus | None  # None = benchmark usable; proceed
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.status is None


def validate_benchmark_for_quote(
    benchmark: BenchmarkEvidence | None,
    spec: InstanceSpecification,
    algorithm: str,
    *,
    evaluated_at_utc: str,
    manual_hashrate_declared: bool = False,
) -> BenchmarkGateResult:
    """Fail-closed benchmark gate for a hashing workload on a rented SKU."""
    problems: list[str] = []
    algo = algorithm.casefold()

    if manual_hashrate_declared:
        problems.append(
            "a manually declared hashrate_hs is not evidence for cloud hardware; "
            "remove it and supply a measured benchmark of the exact SKU"
        )
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)

    if benchmark is None:
        if algo in ASIC_DOMINATED_ALGORITHMS and spec.architecture in ("cpu", "gpu"):
            problems.append(
                f"{algorithm} on a general {spec.architecture.upper()} SKU is not an "
                "ASIC; no measured benchmark exists for this exact SKU"
            )
            return BenchmarkGateResult(
                FeasibilityStatus.BLOCKED_INCOMPATIBLE_HARDWARE, problems
            )
        problems.append("no attributable benchmark for this SKU")
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)

    if benchmark.provider is not spec.provider or benchmark.sku != spec.sku:
        problems.append(
            f"benchmark measured on {benchmark.provider}:{benchmark.sku}, quote is for "
            f"{spec.provider}:{spec.sku}; benchmarks are not transferable between SKUs"
        )
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)
    if (
        benchmark.accelerator_model.casefold() != spec.accelerator_model.casefold()
        or benchmark.accelerator_count != spec.accelerator_count
    ):
        problems.append(
            "benchmark accelerator does not match the SKU specification; "
            "no extrapolation between accelerator models or counts"
        )
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)
    if benchmark.algorithm.casefold() != algo:
        problems.append(
            f"benchmark measured {benchmark.algorithm}, evaluation asks for {algorithm}"
        )
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)
    if benchmark.duration_seconds < MIN_BENCHMARK_DURATION_SECONDS:
        problems.append(
            f"benchmark ran {benchmark.duration_seconds:.0f}s; minimum "
            f"{MIN_BENCHMARK_DURATION_SECONDS:.0f}s after warmup"
        )
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)
    try:
        age_days = (
            parse_utc(evaluated_at_utc) - parse_utc(benchmark.captured_at_utc)
        ).total_seconds() / 86400.0
    except ValueError as exc:
        problems.append(f"benchmark timestamps invalid: {exc}")
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)
    if age_days < 0:
        problems.append("benchmark is dated in the future")
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)
    if age_days > MAX_BENCHMARK_AGE_DAYS:
        problems.append(
            f"benchmark is {age_days:.0f} days old (> {MAX_BENCHMARK_AGE_DAYS:.0f}); re-measure"
        )
        return BenchmarkGateResult(FeasibilityStatus.BLOCKED_MISSING_BENCHMARK, problems)

    # ASIC-dominated algorithm on CPU/GPU with a REAL benchmark of this SKU:
    # measured, so not "missing" — but the economics will use the measured (tiny)
    # hashrate honestly rather than an invented ASIC equivalence.
    return BenchmarkGateResult(None, [])
