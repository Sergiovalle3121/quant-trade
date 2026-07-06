from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .decisions import recommend_decision
from .drift import analyze_drift, write_drift_report
from .evidence import build_evidence_index, write_evidence_index
from .expectations import load_expectations_from_research_artifacts
from .models import TrialConfig, TrialPolicy, utc_now
from .performance import calculate_trial_performance, compare_trial_to_benchmark
from .tracker import FIELDS, collect_daily_records


@dataclass
class ReviewPack:
    review_id: str
    trial_id: str
    review_type: str
    period_start: str
    period_end: str
    generated_at_utc: str
    performance_summary: dict[str, Any]
    benchmark_comparison: dict[str, Any]
    expectations_comparison: dict[str, Any]
    drift_report: dict[str, Any]
    fill_analysis_summary: dict[str, Any]
    ops_validation_summary: dict[str, Any]
    reliability_summary: dict[str, Any]
    incidents_summary: dict[str, Any]
    alerts_summary: dict[str, Any]
    risk_summary: dict[str, Any]
    decision_recommendation: dict[str, Any]
    required_human_notes: str
    real_money_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["real_money_ready"] = False
        return d


def generate_review_pack(
    trial: TrialConfig,
    review_type: str,
    policy: TrialPolicy | None = None,
    artifact_roots: list[Path] | None = None,
) -> Path:
    policy = policy or TrialPolicy()
    records = collect_daily_records(trial, artifact_roots=artifact_roots)
    perf = calculate_trial_performance(records)
    exp = load_expectations_from_research_artifacts(trial.research_run_dir)
    drift = analyze_drift(trial, perf, exp)
    review_id = f"{review_type}_{trial.trial_id}_{utc_now()[:10]}"
    tmp = {
        "trial_id": trial.trial_id,
        "performance_summary": perf,
        "drift_report": drift.to_dict(),
        "evidence_paths": [],
    }
    dec = recommend_decision(tmp, policy)
    start = records[0].date.isoformat() if records else trial.start_date.isoformat()
    end = records[-1].date.isoformat() if records else trial.start_date.isoformat()
    pack = ReviewPack(
        review_id,
        trial.trial_id,
        review_type,
        start,
        end,
        utc_now(),
        perf,
        compare_trial_to_benchmark(records),
        {"confidence_level": exp.confidence_level, "limitations": exp.limitations},
        drift.to_dict(),
        {
            "average_slippage_bps": perf.get("average_slippage_bps", 0),
            "fill_rate": perf.get("fill_rate", 0),
        },
        {"reconciliation_fail_count": perf.get("reconciliation_fail_count", 0)},
        {"operational_success_rate": perf.get("operational_success_rate", 0)},
        {"critical_incident_count": perf.get("critical_incident_count", 0)},
        {"alerts": "local/offline only"},
        {"max_drawdown": perf.get("max_drawdown", 0)},
        dec.to_dict(),
        "Human reviewer must add notes before advancement.",
        False,
    )
    out = Path("outputs/trials") / trial.trial_id / "reviews" / review_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "review_pack.json").write_text(
        json.dumps(pack.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    md = "\n".join(
        [
            f"# Paper Trial Review Pack: {trial.display_name}",
            "",
            "> SAFETY: PAPER-ONLY REVIEW. No live trading, no real-money approval. ",
            "> real_money_ready=false.",
            "",
            "## Trial overview",
            f"- Trial: {trial.trial_id}",
            f"- Strategy: {trial.strategy_name}",
            f"- Universe: {', '.join(trial.universe)}",
            f"- Benchmark: {trial.benchmark}",
            f"- Period covered: {start} to {end}",
            "",
            "## Actual paper results",
            f"- Total return: {perf.get('total_return', 0):.4f}",
            f"- Benchmark return: {perf.get('benchmark_return', 0):.4f}",
            f"- Max drawdown: {perf.get('max_drawdown', 0):.4f}",
            f"- Slippage bps: {perf.get('average_slippage_bps', 0):.2f}",
            f"- Operational success rate: {perf.get('operational_success_rate', 0):.2f}",
            "",
            "## Drift/degradation warnings",
            f"- Status: {drift.status}",
            f"- Blocking issues: {', '.join(drift.blocking_issues) or 'none'}",
            f"- Warnings: {', '.join(drift.warnings) or 'none'}",
            "",
            "## Decision recommendation",
            f"- {dec.decision}",
            "- real_money_approved=false",
            "",
            "## Human review section",
            "- Notes required: yes",
            "- Reviewer notes: TODO",
            "",
            "## Next actions",
            "- Continue, pause, extend, reject, or retire only within paper trading governance.",
            "",
        ]
    )
    (out / "review_pack.md").write_text(md, encoding="utf-8")
    with (out / "review_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        [writer.writerow([k, v]) for k, v in perf.items() if isinstance(v, (int, float, str, bool))]
    with (out / "daily_records_period.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        [w.writerow(r.to_dict()) for r in records]
    write_drift_report(drift, out / "drift_report.json")
    (out / "decision_recommendation.json").write_text(
        json.dumps(dec.to_dict(), indent=2), encoding="utf-8"
    )
    (out / "charts_data.json").write_text(
        json.dumps({"equity": [r.equity for r in records]}, indent=2), encoding="utf-8"
    )
    write_evidence_index(build_evidence_index(trial), out)
    return out
