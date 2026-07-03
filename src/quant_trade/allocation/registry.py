from __future__ import annotations

from pathlib import Path

from .config import load_registry
from .exceptions import AllocationEvidenceError
from .models import AllocationCandidate


def validate_candidate(candidate: AllocationCandidate) -> list[str]:
    warnings: list[str] = []
    if (
        candidate.status not in {"approved_paper", "active", "completed"}
        or not candidate.approved_for_paper
    ):
        raise AllocationEvidenceError(
            f"candidate not approved for paper allocation: {candidate.strategy_id}"
        )
    if not candidate.evidence_paths:
        raise AllocationEvidenceError(f"missing evidence for candidate: {candidate.strategy_id}")
    missing = [
        p for p in [*candidate.evidence_paths, candidate.daily_returns_path] if not Path(p).exists()
    ]
    if missing:
        raise AllocationEvidenceError(f"missing evidence for {candidate.strategy_id}: {missing}")
    if candidate.expected_volatility is None:
        warnings.append("missing expected_volatility; allocator will infer from returns")
    return warnings


def eligible_candidates(
    registry_path: Path | str,
) -> tuple[list[AllocationCandidate], dict[str, str], dict[str, list[str]]]:
    selected: list[AllocationCandidate] = []
    rejected: dict[str, str] = {}
    warnings: dict[str, list[str]] = {}
    for c in load_registry(registry_path):
        try:
            warnings[c.strategy_id] = validate_candidate(c)
            selected.append(c)
        except AllocationEvidenceError as exc:
            rejected[c.strategy_id] = str(exc)
    return selected, rejected, warnings
