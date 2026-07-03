"""Configuration loading for the local evidence database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from quant_trade.evidence.exceptions import EvidenceConfigError
from quant_trade.evidence.models import SCORECARD_CATEGORIES, ScorecardPolicy


@dataclass(frozen=True)
class EvidenceConfig:
    database_path: Path
    output_dir: Path
    scorecard_policy_path: Path
    max_artifact_bytes: int = 1_000_000


def load_evidence_config(path: Path) -> EvidenceConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return EvidenceConfig(
            database_path=Path(
                payload.get("database_path", "data/evidence/quant_trade_evidence.sqlite")
            ),
            output_dir=Path(payload.get("output_dir", "outputs")),
            scorecard_policy_path=Path(
                payload.get(
                    "scorecard_policy_path", "configs/evidence/scorecard_policy_conservative.yaml"
                )
            ),
            max_artifact_bytes=int(payload.get("max_artifact_bytes", 1_000_000)),
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceConfigError(f"Invalid evidence config: {path}") from exc


def load_scorecard_policy(path: Path) -> ScorecardPolicy:
    payload: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    weights = {
        name: float(payload.get("weights", {}).get(name, 1.0)) for name in SCORECARD_CATEGORIES
    }
    return ScorecardPolicy(
        weights=weights,
        minimum_pass_score=float(payload.get("minimum_pass_score", 70.0)),
        minimum_category_score=float(payload.get("minimum_category_score", 50.0)),
    )
