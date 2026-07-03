from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from .reports import utc_now_iso, write_csv, write_json, write_md


@dataclass
class ReliabilityMetrics:
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    warning_runs: int = 0
    success_rate: float = 0.0
    rolling_7d_success_rate: float = 0.0
    rolling_30d_success_rate: float = 0.0
    average_duration_seconds: float = 0.0
    p95_duration_seconds: float = 0.0
    stale_heartbeat_count: int = 0
    lock_failure_count: int = 0
    broker_api_error_count: int = 0
    risk_rejection_count: int = 0
    kill_switch_count: int = 0
    incident_count: int = 0
    missing_artifact_count: int = 0
    data_freshness_warnings: int = 0
    last_success_at: str | None = None
    last_failure_at: str | None = None
    generated_at_utc: str = field(default_factory=utc_now_iso)


def collect_run_summaries(artifact_roots: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in artifact_roots:
        if not root.exists():
            continue
        for path in root.rglob("validation_report.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"status": "fail", "blocking_issues": ["malformed validation report"]}
            if isinstance(payload, list):
                rows.extend(item for item in payload if isinstance(item, dict))
            elif isinstance(payload, dict):
                rows.append(payload)
    return rows


def calculate_reliability_metrics(
    run_summaries: list[dict[str, Any]], policy: dict[str, Any] | None = None
) -> ReliabilityMetrics:
    total = len(run_summaries)
    successful = [row for row in run_summaries if row.get("status") == "pass"]
    failed = [row for row in run_summaries if row.get("status") == "fail"]
    warning = [row for row in run_summaries if row.get("status") == "warning"]

    metrics = ReliabilityMetrics(
        total_runs=total,
        successful_runs=len(successful),
        failed_runs=len(failed),
        warning_runs=len(warning),
    )
    metrics.success_rate = len(successful) / total if total else 0.0
    metrics.rolling_7d_success_rate = metrics.success_rate
    metrics.rolling_30d_success_rate = metrics.success_rate

    durations = [float(row.get("duration_seconds", 0)) for row in run_summaries]
    metrics.average_duration_seconds = mean(durations) if durations else 0.0
    metrics.p95_duration_seconds = (
        sorted(durations)[int(0.95 * (len(durations) - 1))] if durations else 0.0
    )
    metrics.missing_artifact_count = sum(
        1
        for row in run_summaries
        for issue in row.get("blocking_issues", [])
        if "Missing required artifact" in str(issue)
    )
    metrics.stale_heartbeat_count = sum(
        1
        for row in run_summaries
        for warning_text in row.get("warnings", [])
        if "heartbeat" in str(warning_text).lower()
    )
    metrics.last_success_at = max(
        [row.get("generated_at_utc", "") for row in successful], default=None
    )
    metrics.last_failure_at = max([row.get("generated_at_utc", "") for row in failed], default=None)
    return metrics


def reliability_status(
    metrics: ReliabilityMetrics, policy: dict[str, Any] | None = None
) -> tuple[str, list[str]]:
    threshold = (policy or {}).get("min_success_rate_rolling_7d", 0.8)
    issues: list[str] = []
    if metrics.total_runs and metrics.rolling_7d_success_rate < threshold:
        issues.append("Rolling 7d success rate below policy")
    if metrics.failed_runs:
        issues.append("Failed runs present")
    return ("fail" if issues else "pass"), issues


def generate_reliability_report(metrics: ReliabilityMetrics, out: Path) -> None:
    write_json(out / "reliability_metrics.json", metrics)
    write_md(out / "reliability_summary.md", "Reliability Summary", {"metrics": metrics})
    write_csv(out / "reliability_timeseries.csv", [metrics.__dict__])
