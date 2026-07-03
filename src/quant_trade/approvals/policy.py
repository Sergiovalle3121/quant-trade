from __future__ import annotations

from quant_trade.approvals.models import ApprovalRequest, ApprovalRequestType, ApprovalStatus


def evaluate_request(req: ApprovalRequest) -> ApprovalRequest:
    req.real_money_approval_requested = False
    req.real_money_approved = False
    req.blocking_issues = [x for x in req.blocking_issues if x != "approval expired"]
    if req.is_expired and req.status not in {ApprovalStatus.rejected, ApprovalStatus.revoked}:
        req.status = ApprovalStatus.expired
        req.blocking_issues.append("approval expired")
    missing = req.missing_evidence()
    if missing:
        req.blocking_issues.extend(
            [
                f"missing evidence: {p}"
                for p in missing
                if f"missing evidence: {p}" not in req.blocking_issues
            ]
        )
    if (
        req.request_type == ApprovalRequestType.broker_paper_order_submission
        and not req.explicit_paper_only
    ):
        req.blocking_issues.append("broker paper submission requires explicit paper-only approval")
    if req.request_type == ApprovalRequestType.kill_switch_clear:
        req.approval_note_required = True
    if (
        req.request_type == ApprovalRequestType.archive_delete_confirmation
        and not req.explicit_delete_confirmed
    ):
        req.blocking_issues.append("archive deletion requires explicit confirmation")
    return req


def can_approve(req: ApprovalRequest, notes: str) -> tuple[bool, list[str]]:
    req = evaluate_request(req)
    issues = list(dict.fromkeys(req.blocking_issues))
    if req.status in {ApprovalStatus.rejected, ApprovalStatus.revoked, ApprovalStatus.expired}:
        issues.append(f"approval status blocks approval: {req.status}")
    if req.approval_note_required and not notes.strip():
        issues.append("approval note is required")
    return not issues, issues
