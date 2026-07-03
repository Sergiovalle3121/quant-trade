"""Local human approval workflow models for paper-only control gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class ApprovalError(ValueError):
    """Raised when an approval request or decision violates policy."""


class ApprovalRequestType(StrEnum):
    strategy_candidate_promotion = "strategy_candidate_promotion"
    paper_trial_continue = "paper_trial_continue"
    paper_trial_pause = "paper_trial_pause"
    paper_trial_complete = "paper_trial_complete"
    simulated_allocation_approval = "simulated_allocation_approval"
    broker_paper_order_submission = "broker_paper_order_submission"
    cloud_paper_submission_enablement = "cloud_paper_submission_enablement"
    kill_switch_clear = "kill_switch_clear"
    incident_resolution = "incident_resolution"
    archive_delete_confirmation = "archive_delete_confirmation"


class ApprovalStatus(StrEnum):
    draft = "draft"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    revoked = "revoked"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class ApprovalDecision(BaseModel):
    reviewer: str
    decision: str
    notes: str
    decided_at_utc: datetime = Field(default_factory=utc_now)


class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: f"appr_{uuid4().hex[:12]}")
    request_type: ApprovalRequestType
    title: str
    description: str = ""
    requested_by: str = "local_user"
    required_reviewers: list[str] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)
    risk_summary: str = ""
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    expires_at_utc: datetime = Field(default_factory=lambda: utc_now() + timedelta(hours=24))
    status: ApprovalStatus = ApprovalStatus.pending_review
    real_money_approval_requested: bool = False
    real_money_approved: bool = False
    explicit_paper_only: bool = False
    explicit_delete_confirmed: bool = False
    approval_note_required: bool = False
    decisions: list[ApprovalDecision] = Field(default_factory=list)
    content_hash: str = ""

    @model_validator(mode="after")
    def enforce_no_real_money(self) -> ApprovalRequest:
        if self.real_money_approval_requested or self.real_money_approved:
            self.real_money_approval_requested = False
            self.real_money_approved = False
            self.status = ApprovalStatus.rejected
            if "real-money approval is prohibited" not in self.blocking_issues:
                self.blocking_issues.append("real-money approval is prohibited")
        return self

    @property
    def is_expired(self) -> bool:
        return utc_now() >= self.expires_at_utc

    def to_json_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["real_money_approved"] = False
        return data

    def missing_evidence(self) -> list[str]:
        return [p for p in self.evidence_paths if not Path(p).exists()]
