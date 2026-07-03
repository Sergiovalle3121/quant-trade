from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from uuid import uuid4

from .models import AllocationDecision, AllocationDecisionStatus, PortfolioAllocation


def recommend_decisions(
    allocation: PortfolioAllocation, evidence: dict[str, list[str]], warnings: list[str]
) -> list[AllocationDecision]:
    decisions: list[AllocationDecision] = []
    for a in allocation.allocations:
        decision = (
            "approve_simulated" if not warnings and not a.warnings else "require_human_review"
        )
        reason = (
            "passes simulation governance checks"
            if decision == "approve_simulated"
            else "warnings require human review"
        )
        decisions.append(
            AllocationDecision(
                str(uuid4()),
                allocation.run_id,
                a.strategy_id,
                cast(AllocationDecisionStatus, decision),
                reason,
                evidence.get(a.strategy_id, []),
            )
        )
    return decisions


def record_decision(
    allocation_run_id: str,
    strategy_id: str,
    decision: str,
    evidence_paths: list[str],
    human_notes: str = "",
    output_root: Path | str = "outputs/allocation",
) -> Path:
    allowed = {
        "approve_simulated",
        "reduce_allocation",
        "pause_allocation",
        "reject_allocation",
        "require_human_review",
    }
    if decision not in allowed:
        raise ValueError(f"unknown allocation decision: {decision}")
    dec = AllocationDecision(
        str(uuid4()),
        allocation_run_id,
        strategy_id,
        cast(AllocationDecisionStatus, decision),
        "manual paper-only governance record",
        evidence_paths,
        human_notes,
    )
    out = Path(output_root) / allocation_run_id / "allocation_decisions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dec.to_dict()) + "\n")
    return out
