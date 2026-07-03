from quant_trade.security.redaction import (
    sanitize_dict,
    sanitize_jsonl,
    sanitize_report,
    sanitize_text,
)


def test_redaction_removes_values() -> None:
    secret = "abcdefghijklmnopqrstuvwxyz1234567890"
    clean = sanitize_dict({"api_key": secret, "nested": {"message": f"Bearer {secret}"}})
    blob = (
        str(clean)
        + sanitize_text(f"token={secret}")
        + sanitize_jsonl(f'{{"token":"{secret}"}}')
        + sanitize_report(secret)
    )
    assert secret not in blob
    assert "[REDACTED]" in blob
