from quant_trade.execution.audit import append_audit_event


def test_audit_redacts_secrets(tmp_path) -> None:
    append_audit_event(tmp_path, "x", "msg", details={"api_key": "abcdef12345"})
    text = (tmp_path / "broker_events.jsonl").read_text()
    assert "abcdef12345" not in text
