from __future__ import annotations

from pathlib import Path

from quant_trade.approvals.config import ApprovalWorkflowConfig
from quant_trade.approvals.models import ApprovalRequestType, ApprovalStatus
from quant_trade.approvals.policy import evaluate_request
from quant_trade.approvals.requests import create_request, get_request


def require_approval(
    request_type: str, evidence_paths: list[str], policy: ApprovalWorkflowConfig
) -> str:
    req = create_request(
        ApprovalRequestType(request_type),
        f"Approval required: {request_type}",
        evidence_paths,
        policy,
    )
    return req.approval_id


def verify_approval(
    approval_id: str, request_type: str, config: ApprovalWorkflowConfig | None = None
) -> bool:
    cfg = config or ApprovalWorkflowConfig()
    req = evaluate_request(get_request(cfg, approval_id))
    return (
        req.request_type == ApprovalRequestType(request_type)
        and req.status == ApprovalStatus.approved
        and not req.real_money_approved
    )


def evidence_exists(paths: list[str | Path]) -> bool:
    return all(Path(p).exists() for p in paths)
