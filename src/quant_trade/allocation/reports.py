from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .models import AllocationCandidate, AllocationDecision, AllocationSimulationResult


def write_run_artifacts(
    out: Path,
    config_raw: dict[str, Any],
    candidates: list[AllocationCandidate],
    rejected: dict[str, str],
    result: AllocationSimulationResult,
    corr: pd.DataFrame,
    decisions: list[AllocationDecision],
) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    safe_cfg = dict(config_raw)
    safe_cfg["policy"] = result.allocation.to_dict()
    (out / "allocation_config_used.yaml").write_text(yaml.safe_dump(safe_cfg), encoding="utf-8")
    _write_csv(out / "candidates.csv", [c.to_dict() for c in candidates])
    _write_csv(
        out / "selected_allocations.csv", [a.to_dict() for a in result.allocation.allocations]
    )
    _write_csv(
        out / "rejected_candidates.csv",
        [{"strategy_id": k, "reason": v} for k, v in rejected.items()],
    )
    _write_csv(out / "portfolio_equity_curve.csv", result.equity_curve)
    (out / "portfolio_metrics.json").write_text(
        json.dumps(result.metrics, indent=2), encoding="utf-8"
    )
    corr.to_csv(out / "correlation_matrix.csv")
    (out / "risk_budget_report.json").write_text(
        json.dumps(result.risk_report.to_dict(), indent=2), encoding="utf-8"
    )
    with (out / "allocation_decisions.jsonl").open("w", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d.to_dict()) + "\n")
    (out / "allocation_summary.md").write_text(_summary(result), encoding="utf-8")
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _summary(result: AllocationSimulationResult) -> str:
    return "\n".join(
        [
            "# Paper Capital Allocation Summary",
            "",
            "Simulation/governance only. real_money_ready=false.",
            f"Run: {result.allocation.run_id}",
            f"Total return: {result.metrics.get('total_return', 0):.2%}",
            f"Max drawdown: {result.metrics.get('max_drawdown', 0):.2%}",
        ]
    )
