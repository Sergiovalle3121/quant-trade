from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import load_yaml, output_dir
from .models import ChecklistResult

CHECKS = [
    "ci_green_evidence",
    "security_scan_pass",
    "no_secrets_finding",
    "approval_records_exist",
    "paper_trial_review_packs_exist",
    "ops_reliability_meets_threshold",
    "stress_tests_completed",
    "tca_reviewed",
    "allocation_governance_completed",
    "kill_switch_tested",
    "incident_response_tested",
    "human_review_notes_exist",
    "real_money_approval_impossible_in_code",
]


def run_checklist(config: dict[str, Any]) -> ChecklistResult:
    raw = dict(config.get("governance_checklist", config))
    checks = {name: bool(raw.get(name, False)) for name in CHECKS}
    checks["real_money_approval_impossible_in_code"] = (
        raw.get("real_money_approval_impossible_in_code", True) is True
    )
    blockers = [name for name, ok in checks.items() if not ok]
    return ChecklistResult(not blockers, checks, blockers, False)


def write_checklist(config_path: Path) -> ChecklistResult:
    cfg = load_yaml(config_path)
    out = output_dir(cfg)
    res = run_checklist(cfg)
    (out / "checklist_results.json").write_text(json.dumps(asdict(res), indent=2), encoding="utf-8")
    return res
