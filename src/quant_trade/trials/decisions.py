from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import TrialPolicy, utc_now


@dataclass
class DecisionRecord:
    decision_id: str
    trial_id: str
    decision: str
    reason: str
    blocking_issues: list[str]
    warnings: list[str]
    evidence_paths: list[str]
    human_reviewer: str | None = None
    human_notes: str | None = None
    created_at_utc: str = field(default_factory=utc_now)
    real_money_approved: bool = False

    def __post_init__(self) -> None:
        self.real_money_approved = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["real_money_approved"] = False
        return d


def recommend_decision(review_pack: dict[str, Any], policy: TrialPolicy) -> DecisionRecord:
    """Apply every enforceable TrialPolicy dimension to the performance summary.

    Policy fields that exist but are never checked are worse than absent —
    operators configure them believing they gate something.
    """
    trial_id = str(review_pack.get("trial_id", "unknown"))
    drift = review_pack.get("drift_report", {}) or {}
    perf = review_pack.get("performance_summary", {}) or {}
    blocks = list(drift.get("blocking_issues", []))
    warns = list(drift.get("warnings", []))
    if int(perf.get("critical_incident_count", 0)) > policy.max_open_critical_incidents:
        blocks.append("critical incidents exceed policy")
    if float(perf.get("max_drawdown", 0)) < -policy.max_total_drawdown_pct:
        blocks.append("drawdown exceeds policy")
    if float(perf.get("worst_day", 0)) < -policy.max_daily_loss_pct:
        blocks.append("single-day loss exceeds policy")
    if float(perf.get("rejected_order_rate", 0)) > policy.max_rejected_order_rate:
        blocks.append("rejected-order rate exceeds policy")
    if float(perf.get("average_slippage_bps", 0)) > policy.max_slippage_bps:
        blocks.append("average slippage exceeds policy")
    if float(perf.get("operational_success_rate", 1.0)) < policy.min_success_rate:
        blocks.append("operational success rate below policy")
    if int(perf.get("stale_heartbeat_count", 0)) > policy.max_stale_heartbeats:
        blocks.append("stale heartbeats exceed policy")
    if policy.require_reconciliation_pass and int(perf.get("reconciliation_fail_count", 0)) > 0:
        blocks.append("reconciliation failures present")
    if float(perf.get("excess_return", 0)) < policy.min_excess_return_vs_benchmark:
        blocks.append("excess return below policy floor")
    if int(perf.get("days_observed", 0)) < policy.min_observation_days:
        warns.append(
            f"only {perf.get('days_observed', 0)} observation days "
            f"(policy requires {policy.min_observation_days}); evidence is thin"
        )
    psr = perf.get("psr")
    if psr is not None and float(psr) < 0.5:
        warns.append(
            "probabilistic Sharpe below 0.5: trial performance is statistically "
            "indistinguishable from zero so far"
        )
    if policy.require_manual_review_notes and not review_pack.get("human_notes"):
        warns.append("human review notes required before advancement")
    decision = "pause_trial" if blocks else ("needs_human_review" if warns else "continue_trial")
    return DecisionRecord(
        f"decision_{trial_id}_{utc_now().replace(':', '').replace('+', 'Z')}",
        trial_id,
        decision,
        "Conservative paper-only policy recommendation.",
        blocks,
        warns,
        review_pack.get("evidence_paths", []),
    )


def require_human_review_if_needed(
    decision_record: DecisionRecord, policy: TrialPolicy
) -> DecisionRecord:
    if (
        policy.require_manual_review_notes
        and not decision_record.human_notes
        and decision_record.decision in {"paper_ops_ready", "complete_trial"}
    ):
        decision_record.decision = "needs_human_review"
        decision_record.warnings.append("human notes missing")
    decision_record.real_money_approved = False
    return decision_record


def record_decision(
    decision_record: DecisionRecord, output_root: Path | str = Path("outputs/trials")
) -> Path:
    p = Path(output_root) / decision_record.trial_id / "decision_history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision_record.to_dict()) + "\n")
    (p.parent / "decision_recommendation.json").write_text(
        json.dumps(decision_record.to_dict(), indent=2), encoding="utf-8"
    )
    return p


def load_decision_history(
    trial_id: str, output_root: Path | str = Path("outputs/trials")
) -> list[DecisionRecord]:
    p = Path(output_root) / trial_id / "decision_history.jsonl"
    if not p.exists():
        return []
    return [
        DecisionRecord(**json.loads(line))
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
