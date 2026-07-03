from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .config import load_yaml, output_dir
from .models import SAFETY_FLAGS, ReadinessDossier

SECTIONS = [
    "executive_summary",
    "safety_status",
    "strategy_inventory",
    "evidence_database_summary",
    "research_results",
    "oos_walk_forward_results",
    "paper_trial_results",
    "ops_reliability",
    "security_controls",
    "stress_tests",
    "tca_execution_quality",
    "allocation_simulation",
    "incident_history",
    "approval_history",
    "open_risks",
    "blocking_issues",
    "human_review_notes",
    "final_status",
]


def build_dossier(config: dict[str, Any]) -> ReadinessDossier:
    required = config.get("required_evidence", [])
    missing = [name for name in required if not config.get(name)]
    blocking = list(config.get("blocking_issues", []))
    blocking += [{"issue": f"missing evidence: {name}", "severity": "blocker"} for name in missing]
    safety = dict(config.get("safety_status", {}))
    safety.update(SAFETY_FLAGS)
    status = config.get("final_status", "paper_capital_ramp_ready")
    if blocking or missing:
        status = "not_ready"
    if config.get("security_controls", {}).get("security_scan_pass") is False:
        status = "needs_security_review"
    return ReadinessDossier(
        run_id=str(config.get("run_id", "sample_run")),
        executive_summary=str(
            config.get("executive_summary", "Paper-only readiness dossier for human review.")
        ),
        safety_status=safety,
        strategy_inventory=list(config.get("strategy_inventory", [])),
        evidence_database_summary=dict(config.get("evidence_database_summary", {})),
        research_results=dict(config.get("research_results", {})),
        oos_walk_forward_results=dict(config.get("oos_walk_forward_results", {})),
        paper_trial_results=dict(config.get("paper_trial_results", {})),
        ops_reliability=dict(config.get("ops_reliability", {})),
        security_controls=dict(config.get("security_controls", {})),
        stress_tests=dict(config.get("stress_tests", {})),
        tca_execution_quality=dict(config.get("tca_execution_quality", {})),
        allocation_simulation=dict(config.get("allocation_simulation", {})),
        incident_history=list(config.get("incident_history", [])),
        approval_history=list(config.get("approval_history", [])),
        open_risks=list(config.get("open_risks", [])),
        blocking_issues=blocking,
        human_review_notes=str(config.get("human_review_notes", "")),
        final_status=status,
    )


def write_dossier(config_path: Path) -> ReadinessDossier:
    config = load_yaml(config_path)
    out = output_dir(config)
    dossier = build_dossier(config)
    data = dossier.to_dict()
    (out / "readiness_dossier.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    lines = [
        "# Readiness Dossier",
        "",
        "**Paper-only governance artifact. real_money_ready=false.**",
        "",
    ]
    for key in SECTIONS:
        lines += [
            f"## {key.replace('_', ' ').title()}",
            "",
            json.dumps(data.get(key), indent=2)
            if not isinstance(data.get(key), str)
            else str(data.get(key)),
            "",
        ]
    (out / "readiness_dossier.md").write_text("\n".join(lines), encoding="utf-8")
    _write_rows(out / "blocking_issues.csv", data["blocking_issues"])
    _write_rows(out / "open_risks.csv", data["open_risks"])
    (out / "readiness_summary.md").write_text(
        f"# Readiness Summary\n\nFinal status: {data['final_status']}\n\nreal_money_ready: false\n",
        encoding="utf-8",
    )
    return dossier


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = sorted({k for row in rows for k in row}) or ["issue"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
