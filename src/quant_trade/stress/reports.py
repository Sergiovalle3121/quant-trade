"""Stress report artifact generation."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from quant_trade.stress.models import StressDecision, StressPortfolioReport, StressResult
from quant_trade.stress.scenarios import rank_scenarios_by_loss


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate_stress_report(
    results: list[StressResult],
    config_payload: dict[str, Any],
    output_root: Path = Path("outputs/stress"),
) -> StressPortfolioReport:
    run_id = _run_id()
    out = output_root / run_id
    out.mkdir(parents=True, exist_ok=True)
    rows = [result.to_dict() for result in results]
    worst = rank_scenarios_by_loss(results)
    breaches = [row for row in rows if int(row["breach_count"]) > 0]
    decision = StressDecision(
        "pass" if not breaches else "fail", "conservative stress gates evaluated", False
    )
    metrics = {
        "run_id": run_id,
        "worst_scenario": worst[0].scenario_name if worst else "none",
        "breach_count": len(breaches),
        "scenario_count": len(results),
        "real_money_ready": False,
    }
    (out / "stress_config_used.yaml").write_text(
        yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8"
    )
    _write_csv(out / "scenario_results.csv", rows)
    (out / "stress_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    _write_csv(out / "worst_scenarios.csv", [item.to_dict() for item in worst[:5]])
    _write_csv(out / "breaches.csv", breaches)
    (out / "stress_summary.md").write_text(
        "# Stress Summary\n\n"
        "Simulation-only stress test. No live trading, no broker calls, "
        "and no real-money readiness.\n\n"
        f"- Run ID: {run_id}\n- Decision: {decision.status}\n- Real money ready: false\n"
        f"- Worst scenario: {metrics['worst_scenario']}\n- Breaches: {len(breaches)}\n",
        encoding="utf-8",
    )
    dashboard = out / "dashboard"
    dashboard.mkdir(exist_ok=True)
    (dashboard / "index.html").write_text(
        "<html><body><h1>Stress Dashboard</h1>"
        "<p>Simulation-only; real_money_ready=false.</p></body></html>",
        encoding="utf-8",
    )
    return StressPortfolioReport(run_id, tuple(results), decision)
