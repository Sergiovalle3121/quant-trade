from pathlib import Path

from quant_trade.approvals.config import ApprovalWorkflowConfig
from quant_trade.approvals.gates import require_approval, verify_approval
from quant_trade.approvals.models import ApprovalRequestType
from quant_trade.approvals.requests import get_request, save_request
from quant_trade.approvals.reviewers import approve_request, reject_request


def test_rejected_approval_blocks(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.md"
    evidence.write_text("paper evidence", encoding="utf-8")
    cfg = ApprovalWorkflowConfig(output_dir=str(tmp_path), run_id="run")
    approval_id = require_approval(
        ApprovalRequestType.paper_trial_continue.value, [str(evidence)], cfg
    )
    req = reject_request(get_request(cfg, approval_id), "Sergio", "Risk too high")
    save_request(req, cfg, "rejected")
    assert (
        verify_approval(approval_id, ApprovalRequestType.paper_trial_continue.value, cfg) is False
    )


def test_approved_approval_valid_and_false_real_money(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.md"
    evidence.write_text("paper evidence", encoding="utf-8")
    cfg = ApprovalWorkflowConfig(output_dir=str(tmp_path), run_id="run")
    approval_id = require_approval(
        ApprovalRequestType.paper_trial_continue.value, [str(evidence)], cfg
    )
    req = approve_request(get_request(cfg, approval_id), "Sergio", "paper only")
    save_request(req, cfg, "approved")
    saved = get_request(cfg, approval_id)
    assert saved.real_money_approved is False
    assert verify_approval(approval_id, ApprovalRequestType.paper_trial_continue.value, cfg) is True
