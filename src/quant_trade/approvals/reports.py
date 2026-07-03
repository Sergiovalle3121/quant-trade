from __future__ import annotations

from pathlib import Path

from quant_trade.approvals.models import ApprovalRequest


def write_summary(path: Path, requests: list[ApprovalRequest]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Approval Summary", "", "Paper-only governance; real_money_approved=false.", ""]
    for req in requests:
        lines.append(
            f"- {req.approval_id}: {req.request_type} — {req.status}; real_money_approved=false"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
