"""Resend HTTPS transport: offline, with the network call replaced by a fake."""

from __future__ import annotations

import json
from email.message import EmailMessage
from typing import Any

import pytest

from quant_trade.audit import mail
from quant_trade.audit.settings import AuditSettings, resend_key_valid

KEY = "re_test_0123456789abcdefghij"


def _settings(**changes: Any) -> AuditSettings:
    values: dict[str, Any] = {
        "base_url": "https://rigor.example",
        "email_token_secret": "stable secret shared across replicas 1234567890",
        "smtp_from": "Rigor <hola@example.com>",
        "resend_api_key": KEY,
    }
    values.update(changes)
    return AuditSettings(**values)


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "Rigor <hola@example.com>"
    message["To"] = "cliente@example.org"
    message["Subject"] = "Confirma tu correo en Rigor"
    message["Message-ID"] = "<rigor-abc123@example.com>"
    message.set_content("Abre el enlace:\n\nhttps://rigor.example/confirmar-correo?token=x\n")
    return message


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_resend_key_alone_is_a_ready_transport() -> None:
    cfg = _settings()
    assert cfg.resend_ready and not cfg.smtp_ready
    assert cfg.email_delivery_ready
    assert KEY not in repr(cfg)


@pytest.mark.parametrize(
    "key", ["", "sk_live_nope_123456789", "re_short", "re_with space 12345678"]
)
def test_malformed_resend_key_is_not_ready(key: str) -> None:
    assert not resend_key_valid(key)
    assert not _settings(resend_api_key=key).email_delivery_ready


def test_resend_still_needs_https_sender_and_token_secret() -> None:
    assert not _settings(base_url="http://rigor.example").email_delivery_ready
    assert not _settings(smtp_from="").email_delivery_ready
    assert not _settings(email_token_secret="short").email_delivery_ready


def test_send_resend_posts_the_message_with_idempotency_key() -> None:
    seen: list[Any] = []

    def opener(request: Any, **kwargs: Any) -> _Response:
        seen.append((request, kwargs))
        return _Response(200)

    mail.send_resend(_message(), _settings(), opener=opener)
    request, kwargs = seen[0]
    assert request.full_url == mail.RESEND_URL
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert request.get_header("Idempotency-key") == "rigor-abc123@example.com"
    assert kwargs["timeout"] == 15
    body = json.loads(request.data)
    assert body["to"] == ["cliente@example.org"]
    assert body["from"] == "Rigor <hola@example.com>"
    assert "confirmar-correo?token=x" in body["text"]
    assert body["headers"]["Message-ID"] == "<rigor-abc123@example.com>"


def test_send_resend_refuses_a_non_success_answer() -> None:
    with pytest.raises(RuntimeError):
        mail.send_resend(_message(), _settings(), opener=lambda *_, **__: _Response(500))


def test_send_resend_refuses_without_configuration() -> None:
    with pytest.raises(RuntimeError):
        mail.send_resend(_message(), _settings(resend_api_key=""), opener=lambda *_, **__: None)


def test_send_email_prefers_resend_over_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[str] = []
    monkeypatch.setattr(mail, "send_resend", lambda *_: used.append("resend"))
    monkeypatch.setattr(mail, "send_smtp", lambda *_: used.append("smtp"))
    mail.send_email(_message(), _settings(smtp_host="smtp.example"))
    mail.send_email(_message(), _settings(resend_api_key="", smtp_host="smtp.example"))
    assert used == ["resend", "smtp"]


def test_token_secret_is_derived_from_the_resend_key_when_unset() -> None:
    env = {
        "AUDIT_BASE_URL": "https://rigor.example",
        "AUDIT_RESEND_API_KEY": KEY,
        "AUDIT_EMAIL_FROM": "Rigor <hola@example.com>",
    }
    cfg = AuditSettings.from_env(env)
    assert cfg.email_delivery_ready
    assert len(cfg.email_token_secret) == 64
    assert KEY not in cfg.email_token_secret
    # Stable across restarts and replicas.
    assert AuditSettings.from_env(env).email_token_secret == cfg.email_token_secret
    explicit = AuditSettings.from_env({**env, "AUDIT_EMAIL_TOKEN_SECRET": "x" * 40})
    assert explicit.email_token_secret == "x" * 40


def test_no_resend_key_means_no_derived_secret() -> None:
    cfg = AuditSettings.from_env({"AUDIT_BASE_URL": "https://rigor.example"})
    assert cfg.email_token_secret == ""
    assert not cfg.email_delivery_ready
