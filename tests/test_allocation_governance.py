import json

from quant_trade.allocation.governance import record_decision
from quant_trade.allocation.registry import eligible_candidates


def test_missing_evidence_rejects_candidate():
    _, rejected, _ = eligible_candidates("configs/allocation/allocation_registry.yaml")
    assert "missing_evidence" in rejected


def test_governance_decision_never_real_money(tmp_path):
    p = record_decision(
        "run", "trend_paper", "approve_simulated", ["evidence"], output_root=tmp_path
    )
    row = json.loads(p.read_text().splitlines()[0])
    assert row["real_money_approved"] is False
