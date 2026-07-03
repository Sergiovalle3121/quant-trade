from quant_trade.readiness.checklist import run_checklist


def test_checklist_blocks_missing_security_scan():
    r = run_checklist({"governance_checklist": {"security_scan_pass": False}})
    assert not r.passed
    assert "security_scan_pass" in r.blocking_issues
    assert r.real_money_ready is False
