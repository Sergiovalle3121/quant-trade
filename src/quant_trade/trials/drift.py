from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .expectations import ExpectedPerformance, compare_actual_to_expectations
from .models import TrialConfig, utc_now


@dataclass
class DriftReport:
    trial_id: str
    status: str
    drift_checks: dict[str, str]
    blocking_issues: list[str]
    warnings: list[str]
    recommended_action: str
    generated_at_utc: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_drift(
    trial: TrialConfig, metrics: dict[str, Any], exp: ExpectedPerformance | None = None
) -> DriftReport:
    checks = {}
    blocks = []
    warns = []
    if exp is None:
        warns.append("missing expectation data")
        exp = None
    else:
        cmp = compare_actual_to_expectations(metrics, exp)
        blocks += cmp["breaches"]
        warns += cmp["warnings"]
    if float(metrics.get("max_drawdown", 0)) < -0.10:
        blocks.append("severe drawdown drift")
    if float(metrics.get("excess_return", 0)) < -0.03:
        warns.append("benchmark underperformance")
    if float(metrics.get("average_daily_turnover", 0)) > trial.expected_turnover_range[1] * 2:
        warns.append("turnover drift")
    if float(metrics.get("average_slippage_bps", 0)) > 10:
        warns.append("slippage drift")
    if int(metrics.get("stale_heartbeat_count", 0)) or int(
        metrics.get("critical_incident_count", 0)
    ):
        blocks.append("operational drift")
    status = "severe" if blocks else ("warning" if warns else "no_drift")
    action = "pause" if blocks else ("monitor" if warns else "continue")
    for x in [
        "performance_drift",
        "volatility_drift",
        "drawdown_drift",
        "turnover_drift",
        "slippage_drift",
        "benchmark_drift",
        "operational_drift",
        "regime_warning",
    ]:
        checks[x] = status if x in " ".join(blocks + warns).replace(" ", "_") else "pass"
    return DriftReport(trial.trial_id, status, checks, blocks, warns, action)


def write_drift_report(report: DriftReport, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return p
