"""Typed models for the local strategy evidence database."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

EvidenceStatus = Literal["pass", "warning", "fail"]

SCORECARD_CATEGORIES = [
    "research_quality",
    "out_of_sample_performance",
    "robustness",
    "stress_resilience",
    "paper_trial_performance",
    "operational_reliability",
    "execution_quality",
    "risk_control",
    "governance_completeness",
    "human_review_completeness",
]


@dataclass(frozen=True)
class EvidenceArtifact:
    path: str
    artifact_type: str
    sha256: str
    strategy_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceIngestReport:
    run_id: str
    root_path: str
    artifacts_seen: int
    artifacts_ingested: int
    malformed_artifacts: list[str]
    skipped_secret_artifacts: list[str]
    output_path: str


@dataclass(frozen=True)
class StrategyEvidenceProfile:
    strategy_id: str
    artifact_count: int
    artifact_types: dict[str, int]
    latest_artifact_path: str | None


@dataclass(frozen=True)
class ScorecardCategory:
    name: str
    score: float
    status: EvidenceStatus
    evidence_paths: list[str]
    notes: list[str]
    blocking_issues: list[str]


@dataclass(frozen=True)
class StrategyScorecard:
    strategy_id: str
    overall_score: float
    overall_status: EvidenceStatus
    real_money_ready: bool
    categories: list[ScorecardCategory]
    blocking_issues: list[str]


@dataclass(frozen=True)
class ScorecardPolicy:
    weights: dict[str, float]
    minimum_pass_score: float = 70.0
    minimum_category_score: float = 50.0


@dataclass(frozen=True)
class EvidenceLineage:
    strategy_id: str
    artifacts: list[EvidenceArtifact]
    links: list[dict[str, Any]]


def output_run_dir(base_dir: Path, run_id: str) -> Path:
    return base_dir / "evidence" / run_id
