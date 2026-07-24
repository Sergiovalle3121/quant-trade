"""Consolidated, honest verdict scorecard.

One place that states the non-negotiable safety posture and rolls up whatever
verdicts exist (strategy promotions, cash-and-carry, mining) — so an optimistic
simulation is never mistaken for demonstrated profitability. Nothing here trades
or authorizes anything; it only summarises.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Non-negotiable, hard-wired statuses.
FIXED_STATUSES: dict[str, str] = {
    "REAL_MONEY": "NO-GO",
    "MINING_HARDWARE_CONTROL": "DISABLED",
    "AWS_RESOURCES_CREATED": "FALSE",
}


@dataclass
class ScorecardRow:
    name: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionScorecard:
    fixed_statuses: dict[str, str]
    rows: list[ScorecardRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed_statuses": self.fixed_statuses,
            "rows": [r.to_dict() for r in self.rows],
        }


def _promotion_rollup(promotions: list[dict[str, Any]]) -> ScorecardRow:
    total = len(promotions)
    promoted = sum(1 for p in promotions if p.get("status") == "paper_candidate")
    if total == 0:
        return ScorecardRow("STRATEGY_PROMOTION", "NONE-EVALUATED", "no promotion decisions found")
    status = "PAPER-CANDIDATE" if promoted else "NO-GO"
    return ScorecardRow(
        "STRATEGY_PROMOTION", status,
        f"{promoted}/{total} reached paper_candidate (real money never authorized)",
    )


def build_session_scorecard(
    *,
    statistical_integrity: str = "PASS",
    promotions: list[dict[str, Any]] | None = None,
    carry_decision: str | None = None,
    mining_decision: str | None = None,
    mining_telemetry: str = "READY",
    paper_readiness: str | None = None,
) -> SessionScorecard:
    """Assemble the scorecard from whatever verdicts are available."""
    rows: list[ScorecardRow] = [
        ScorecardRow("STATISTICAL_INTEGRITY", statistical_integrity),
        _promotion_rollup(promotions or []),
    ]
    if carry_decision is not None:
        rows.append(ScorecardRow("TRADING_EDGE_CASH_AND_CARRY", carry_decision))
    if mining_decision is not None:
        rows.append(ScorecardRow("MINING_ECONOMICS", mining_decision))
    rows.append(ScorecardRow("MINING_TELEMETRY", mining_telemetry))
    if paper_readiness is not None:
        rows.append(ScorecardRow("PAPER_READINESS", paper_readiness))
    return SessionScorecard(fixed_statuses=dict(FIXED_STATUSES), rows=rows)


def load_promotion_decisions(outputs_dir: str | Path) -> list[dict[str, Any]]:
    """Read any promotion_v2 decision JSONs under a directory (best-effort)."""
    root = Path(outputs_dir)
    decisions: list[dict[str, Any]] = []
    if not root.exists():
        return decisions
    for path in root.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and "status" in payload and "gates" in payload:
            decisions.append(payload)
    return decisions


def render_markdown(scorecard: SessionScorecard) -> str:
    lines = ["# Session Verdict Scorecard", "", "## Non-negotiable safety posture"]
    for name, status in scorecard.fixed_statuses.items():
        lines.append(f"- **{name}: {status}**")
    lines += ["", "## Verdicts", "", "| Signal | Status | Detail |", "| --- | --- | --- |"]
    for row in scorecard.rows:
        lines.append(f"| {row.name} | {row.status} | {row.detail} |")
    lines += [
        "",
        "_This scorecard summarises evidence only. A synthetic result is never a GO, "
        "and no verdict authorizes real money._",
    ]
    return "\n".join(lines) + "\n"
