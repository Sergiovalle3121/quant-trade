"""Conservative strategy evidence scorecards."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from quant_trade.evidence.config import EvidenceConfig, load_scorecard_policy
from quant_trade.evidence.database import connect, fetch_artifacts
from quant_trade.evidence.models import (
    SCORECARD_CATEGORIES,
    EvidenceStatus,
    ScorecardCategory,
    StrategyScorecard,
)

CATEGORY_TYPES = {
    "research_quality": ["research"],
    "out_of_sample_performance": ["research"],
    "robustness": ["research"],
    "stress_resilience": ["stress"],
    "paper_trial_performance": ["paper_trial"],
    "operational_reliability": ["ops", "incident", "alert"],
    "execution_quality": ["paper_trial", "ops"],
    "risk_control": ["stress", "allocation", "decision"],
    "governance_completeness": ["decision", "trial_review"],
    "human_review_completeness": ["trial_review"],
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_artifacts(rows: list[Any]) -> tuple[list[Any], dict[str, str]]:
    """Revalidate indexed artifact bytes before they can support a scorecard."""
    verified: list[Any] = []
    problems: dict[str, str] = {}
    for row in rows:
        raw_path = str(row["path"])
        path = Path(raw_path)
        if not path.is_file():
            problems[raw_path] = f"Evidence artifact is missing: {raw_path}"
            continue
        try:
            actual_sha = _sha256(path)
        except OSError as exc:
            problems[raw_path] = f"Evidence artifact is unreadable: {raw_path} ({exc})"
            continue
        if actual_sha != str(row["sha256"]):
            problems[raw_path] = f"Evidence artifact digest mismatch: {raw_path}"
            continue
        verified.append(row)
    return verified, problems


def build_scorecard(config: EvidenceConfig, strategy_id: str) -> StrategyScorecard:
    policy = load_scorecard_policy(config.scorecard_policy_path)
    with connect(config.database_path) as conn:
        rows = fetch_artifacts(conn, strategy_id)
    verified_rows, integrity_problems = _verified_artifacts(rows)
    categories: list[ScorecardCategory] = []
    blocking: list[str] = list(integrity_problems.values())
    for name in SCORECARD_CATEGORIES:
        wanted = CATEGORY_TYPES[name]
        paths = [
            str(row["path"])
            for row in verified_rows
            if str(row["artifact_type"]) in wanted
        ]
        issues: list[str] = [] if paths else [f"Missing evidence for {name}"]
        issues.extend(
            problem
            for path, problem in integrity_problems.items()
            if any(
                str(row["path"]) == path and str(row["artifact_type"]) in wanted for row in rows
            )
        )
        score = 75.0 if paths else 0.0
        status: EvidenceStatus = (
            "pass" if score >= policy.minimum_pass_score else ("warning" if paths else "fail")
        )
        if issues:
            blocking.extend(issue for issue in issues if issue not in blocking)
        categories.append(
            ScorecardCategory(
                name, score, status, paths, ["Conservative offline evidence score."], issues
            )
        )
    total_weight = sum(policy.weights.values()) or 1.0
    overall = sum(c.score * policy.weights.get(c.name, 1.0) for c in categories) / total_weight
    overall_status: EvidenceStatus = (
        "pass"
        if overall >= policy.minimum_pass_score and not blocking
        else ("warning" if overall > 0 else "fail")
    )
    return StrategyScorecard(strategy_id, overall, overall_status, False, categories, blocking)


def persist_scorecard(config: EvidenceConfig, scorecard: StrategyScorecard, run_id: str) -> Path:
    out_dir = config.output_dir / "evidence" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"strategy_scorecard_{scorecard.strategy_id}.md"
    lines = [
        f"# Strategy Scorecard: {scorecard.strategy_id}",
        "",
        f"Overall score: {scorecard.overall_score:.1f}",
        f"Status: {scorecard.overall_status}",
        "real_money_ready: false",
        "",
    ]
    for cat in scorecard.categories:
        lines += [f"## {cat.name}", f"Score: {cat.score:.1f}", f"Status: {cat.status}", "Evidence:"]
        lines += [f"- {p}" for p in cat.evidence_paths] or ["- Missing"]
        lines += [f"Blocking: {issue}" for issue in cat.blocking_issues]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    csv_path = out_dir / "scorecards.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy_id", "category", "score", "status", "real_money_ready"])
        for cat in scorecard.categories:
            writer.writerow([scorecard.strategy_id, cat.name, cat.score, cat.status, "false"])
    with connect(config.database_path) as conn:
        conn.execute(
            "INSERT INTO scorecards("
            "strategy_id, overall_score, overall_status, "
            "real_money_ready, scorecard_json"
            ") VALUES (?, ?, ?, 0, ?)",
            (
                scorecard.strategy_id,
                scorecard.overall_score,
                scorecard.overall_status,
                json.dumps(scorecard, default=lambda o: o.__dict__, sort_keys=True),
            ),
        )
        conn.commit()
    return md_path
