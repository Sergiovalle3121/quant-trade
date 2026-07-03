from quant_trade.readiness.dossier import build_dossier


def test_dossier_generated_from_fixtures_and_safe():
    d = build_dossier(
        {
            "run_id": "t",
            "research_results": {"ok": True},
            "paper_trial_results": {"ok": True},
            "security_controls": {"security_scan_pass": True},
        }
    )
    assert d.to_dict()["real_money_ready"] is False
    assert d.to_dict()["real_money_approved"] is False
    assert d.to_dict()["live_trading_enabled"] is False


def test_missing_evidence_produces_not_ready():
    d = build_dossier({"run_id": "t", "required_evidence": ["research_results"]})
    assert d.final_status == "not_ready"
    assert d.blocking_issues
