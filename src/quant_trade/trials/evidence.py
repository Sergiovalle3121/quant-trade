from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import TrialConfig, TrialPolicy

TYPES = [
    "research_artifacts",
    "paper_daily_records",
    "paper_reports",
    "ops_validation",
    "dashboard",
    "alerts",
    "incidents",
    "reconciliation",
    "fill_analysis",
    "kill_switch_drill",
    "cloud_heartbeat",
    "broker_plan",
    "human_notes",
]


def _safe(p: Path) -> str:
    return str(p).replace("..", "")


def build_evidence_index(trial_config: TrialConfig) -> dict[str, Any]:
    root = Path("outputs/trials") / trial_config.trial_id
    items = []
    candidates = [
        Path(trial_config.research_run_dir or ""),
        root / "daily_records.csv",
        root / "trial_state.json",
        root / "reviews",
        root / "decision_history.jsonl",
    ]
    for p in candidates:
        if str(p) != "." and p.exists():
            items.append(
                {
                    "type": "paper_daily_records" if p.suffix == ".csv" else "research_artifacts",
                    "path": _safe(p),
                    "exists": True,
                }
            )
    return {"trial_id": trial_config.trial_id, "evidence": items, "real_money_ready": False}


def verify_required_evidence(evidence_index: dict[str, Any], policy: TrialPolicy) -> dict[str, Any]:
    paths = evidence_index.get("evidence", [])
    missing = []
    if not any("daily_records" in x.get("path", "") for x in paths):
        missing.append("paper_daily_records")
    if policy.require_manual_review_notes and not any("human" in x.get("type", "") for x in paths):
        missing.append("human_notes")
    return {"ok": not missing, "missing": missing, "real_money_ready": False}


def write_evidence_index(evidence_index: dict[str, Any], output_dir: Path | str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    jp = out / "evidence_index.json"
    jp.write_text(json.dumps(evidence_index, indent=2), encoding="utf-8")
    (out / "evidence_index.md").write_text(
        "# Evidence Index\n\n"
        + "\n".join(f"- {x['type']}: `{x['path']}`" for x in evidence_index.get("evidence", [])),
        encoding="utf-8",
    )
    return jp
