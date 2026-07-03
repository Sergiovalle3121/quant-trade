from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from quant_trade.approvals.audit import append_jsonl
from quant_trade.approvals.config import ApprovalWorkflowConfig
from quant_trade.approvals.models import (
    ApprovalRequest,
    ApprovalRequestType,
    ApprovalStatus,
    utc_now,
)
from quant_trade.approvals.signatures import approval_hash


def approvals_path(cfg: ApprovalWorkflowConfig) -> Path:
    return cfg.artifact_dir / "approvals.jsonl"


def audit_path(cfg: ApprovalWorkflowConfig) -> Path:
    return cfg.artifact_dir / "approval_audit.jsonl"


def save_request(req: ApprovalRequest, cfg: ApprovalWorkflowConfig, event: str = "saved") -> None:
    req.real_money_approved = False
    req.content_hash = approval_hash(req.to_json_dict())
    append_jsonl(approvals_path(cfg), req.to_json_dict())
    append_jsonl(
        audit_path(cfg), {"event": event, "approval_id": req.approval_id, "status": req.status}
    )


def create_request(
    request_type: ApprovalRequestType,
    title: str,
    evidence_paths: list[str],
    cfg: ApprovalWorkflowConfig,
    description: str = "",
    requested_by: str = "local_user",
) -> ApprovalRequest:
    req = ApprovalRequest(
        request_type=request_type,
        title=title,
        description=description,
        requested_by=requested_by,
        required_reviewers=cfg.required_reviewers,
        evidence_paths=evidence_paths,
        expires_at_utc=utc_now() + timedelta(hours=cfg.default_ttl_hours),
    )
    save_request(req, cfg, "created")
    return req


def load_requests(cfg: ApprovalWorkflowConfig) -> list[ApprovalRequest]:
    path = approvals_path(cfg)
    if not path.exists():
        return []
    latest: dict[str, ApprovalRequest] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            req = ApprovalRequest(**json.loads(line))
            latest[req.approval_id] = req
    return list(latest.values())


def get_request(cfg: ApprovalWorkflowConfig, approval_id: str) -> ApprovalRequest:
    for req in load_requests(cfg):
        if req.approval_id == approval_id:
            return req
    raise KeyError(f"approval not found: {approval_id}")


def set_status(
    cfg: ApprovalWorkflowConfig, req: ApprovalRequest, status: ApprovalStatus, event: str
) -> ApprovalRequest:
    req.status = status
    req.real_money_approved = False
    save_request(req, cfg, event)
    return req
