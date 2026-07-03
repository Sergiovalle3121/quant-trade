from datetime import UTC, datetime, timedelta

from quant_trade.approvals.models import ApprovalRequest, ApprovalRequestType, ApprovalStatus
from quant_trade.approvals.policy import can_approve, evaluate_request


def test_missing_evidence_blocks() -> None:
    req = ApprovalRequest(
        request_type=ApprovalRequestType.paper_trial_continue,
        title="continue",
        evidence_paths=["/tmp/does-not-exist-approval-evidence"],
    )
    ok, issues = can_approve(req, "notes")
    assert not ok
    assert any("missing evidence" in issue for issue in issues)


def test_expired_approval_invalid() -> None:
    req = ApprovalRequest(
        request_type=ApprovalRequestType.paper_trial_continue,
        title="old",
        expires_at_utc=datetime.now(UTC) - timedelta(hours=1),
    )
    evaluated = evaluate_request(req)
    assert evaluated.status == ApprovalStatus.expired
    assert "approval expired" in evaluated.blocking_issues


def test_broker_requires_explicit_paper_only() -> None:
    req = ApprovalRequest(
        request_type=ApprovalRequestType.broker_paper_order_submission,
        title="broker",
    )
    ok, issues = can_approve(req, "Approved for Alpaca Paper only.")
    assert not ok
    assert any("paper-only" in issue for issue in issues)
