from pathlib import Path

from quant_trade.security.audit_review import review_audit_logs


def test_audit_log_with_secret_fails(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"
    payload = (
        '{"event_id":"e1","timestamp":"2026-01-01T00:00:00Z",'
        '"event_type":"x","token":"abcdefghijklmnopqrstuvwxyz1234567890"}\n'
    )
    p.write_text(payload, encoding="utf-8")
    report = review_audit_logs([p])
    assert report.status == "fail"


def test_audit_log_required_fields_pass(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"
    payload = '{"event_id":"e1","timestamp":"2026-01-01T00:00:00Z","event_type":"x"}\n'
    p.write_text(payload, encoding="utf-8")
    report = review_audit_logs([p])
    assert report.status == "pass"
