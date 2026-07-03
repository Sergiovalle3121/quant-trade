from datetime import UTC, datetime, timedelta

from quant_trade.approvals.models import ApprovalRequest, ApprovalRequestType, ApprovalStatus


def test_real_money_request_forced_rejected() -> None:
    req = ApprovalRequest(
        request_type=ApprovalRequestType.strategy_candidate_promotion,
        title="bad",
        real_money_approval_requested=True,
        real_money_approved=True,
    )
    assert req.status == ApprovalStatus.rejected
    assert req.real_money_approved is False
    assert "real-money approval is prohibited" in req.blocking_issues


def test_expiry_property() -> None:
    req = ApprovalRequest(
        request_type=ApprovalRequestType.paper_trial_continue,
        title="expired",
        expires_at_utc=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert req.is_expired
