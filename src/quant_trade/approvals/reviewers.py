from __future__ import annotations

from quant_trade.approvals.models import ApprovalDecision, ApprovalRequest, ApprovalStatus
from quant_trade.approvals.policy import can_approve


def approve_request(req: ApprovalRequest, reviewer: str, notes: str) -> ApprovalRequest:
    ok, issues = can_approve(req, notes)
    if not ok:
        req.blocking_issues = list(dict.fromkeys(req.blocking_issues + issues))
        req.status = ApprovalStatus.rejected
    else:
        req.status = ApprovalStatus.approved
    req.real_money_approved = False
    req.decisions.append(
        ApprovalDecision(reviewer=reviewer, decision=req.status.value, notes=notes)
    )
    return req


def reject_request(req: ApprovalRequest, reviewer: str, notes: str) -> ApprovalRequest:
    req.status = ApprovalStatus.rejected
    req.real_money_approved = False
    req.decisions.append(ApprovalDecision(reviewer=reviewer, decision="rejected", notes=notes))
    return req
