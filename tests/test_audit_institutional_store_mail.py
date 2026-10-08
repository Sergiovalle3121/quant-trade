"""Offline institutional intake storage and bounded operator notifications."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

sa = pytest.importorskip("sqlalchemy")

from quant_trade.audit import mail  # noqa: E402
from quant_trade.audit.guard import find_claims, scan_client_text  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import Store, make_store  # noqa: E402

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
PRIVATE_TEXT = "Descripción privada: resultados garantizados.\nConservar este texto tal cual."


def _settings(tmp_path: Path) -> AuditSettings:
    return AuditSettings(
        database_url=f"sqlite:///{tmp_path}/institutional.db",
        base_url="https://rigor.example",
        smtp_host="smtp.example",
        smtp_from="Rigor <hello@example.com>",
        operator_contact="owner@example.com",
        # Institutional composition does not derive a challenge token.
        email_token_secret="",
    )


def _request(store: Store, **overrides: Any) -> str:
    fields = {
        "name": "Ana Ejemplo",
        "organization": "Ejemplo Capital",
        "email": "prospect@example.com",
        "strategy_type": "fund",
        "frequency": "weekly",
        "history_years": "7.5",
        "has_benchmark": True,
        "variants": 314,
        "description": PRIVATE_TEXT,
        "claim_findings": scan_client_text(PRIVATE_TEXT),
        "locale": "es",
        "ref": "institutional-campaign",
        "at": NOW,
        "notification_email": "owner@example.com",
    }
    return store.add_institutional_request(**(fields | overrides))


def _outbox(store: Store) -> list[dict[str, Any]]:
    with store.engine.connect() as conn:
        return [dict(row) for row in conn.execute(store.email_outbox.select()).mappings()]


def test_private_request_survives_restart_and_contact_mark_is_idempotent(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    request_id = _request(store)
    restarted = make_store(cfg.database_url)
    rows = restarted.list_institutional_requests()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == request_id
    assert row.created_at == "2026-10-07T12:00:00Z"
    assert row.history_years == "7.5" and row.has_benchmark is True and row.variants == 314
    assert row.description == PRIVATE_TEXT
    assert row.claim_findings == scan_client_text(PRIVATE_TEXT)
    assert row.claim_findings
    assert row.ref == "institutional-campaign" and row.contacted_at == ""
    assert restarted.mark_institutional_contacted(request_id, at=NOW + timedelta(hours=1))
    assert restarted.mark_institutional_contacted(request_id, at=NOW + timedelta(hours=2))
    assert not restarted.mark_institutional_contacted("missing", at=NOW)
    assert not restarted.mark_institutional_contacted("a" * 31 + "\x00", at=NOW)
    assert (
        make_store(cfg.database_url).list_institutional_requests()[0].contacted_at
        == "2026-10-07T13:00:00Z"
    )


def test_request_list_is_newest_first_and_bounded(tmp_path: Path) -> None:
    store = make_store(_settings(tmp_path).database_url)
    _request(store)
    newest = _request(store, at=NOW + timedelta(minutes=1))
    assert [row.id for row in store.list_institutional_requests(limit=1)] == [newest]
    assert store.list_institutional_requests(limit=0) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_notice_allows_only_contact_fields_and_passes_guard(tmp_path: Path, locale: str) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    request_id = _request(store, locale=locale)
    row = _outbox(store)[0]
    assert row["id"] == request_id and row["kind"] == "institutional"
    assert row["email"] == cfg.operator_contact and row["account_id"] == ""
    assert row["status"] == "queued"
    assert "prospect@example.com" not in str(row)
    assert PRIVATE_TEXT not in str(row)

    # The worker's projection itself excludes the free text and other declarations.
    claimed = store.claim_email_delivery(NOW)
    assert claimed is not None
    prepared = store.prepare_email_delivery(claimed, at=NOW)
    assert prepared is not None
    assert set(prepared["institutional_contact"]) == {
        "name",
        "organization",
        "email",
        "strategy_type",
    }
    assert PRIVATE_TEXT not in str(prepared)
    message = mail.compose(prepared, cfg)
    assert message["To"] == cfg.operator_contact
    assert message.get_content_type() == "text/plain"
    content = message.get_content()
    assert "Ana Ejemplo" in content and "Ejemplo Capital" in content
    assert "prospect@example.com" in content and "Tipo: fund" in content
    for excluded in (PRIVATE_TEXT, "weekly", "7.5", "314", "institutional-campaign", "token="):
        assert excluded not in content
    assert find_claims(str(message["Subject"]) + "\n" + content) == []


def test_notice_retries_with_same_message_id_and_no_private_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    request_id = _request(store)
    attempted: list[EmailMessage] = []

    def fail(message: EmailMessage, _settings: AuditSettings) -> None:
        attempted.append(message)
        raise OSError("fake failure containing prospect@example.com " + PRIVATE_TEXT)

    assert mail.deliver_pending(store, cfg, sender=fail, now=NOW) == 0
    row = _outbox(store)[0]
    assert row["status"] == "queued" and row["attempts"] == 1
    assert row["next_attempt_at"] == "2026-10-07T12:01:00Z"
    assert request_id in caplog.text
    assert "prospect@example.com" not in caplog.text and PRIVATE_TEXT not in caplog.text
    restarted = make_store(cfg.database_url)
    delivered: list[EmailMessage] = []
    sender = lambda message, _settings: delivered.append(message)  # noqa: E731
    assert mail.deliver_pending(restarted, cfg, sender=sender, now=NOW) == 0
    assert mail.deliver_pending(restarted, cfg, sender=sender, now=NOW + timedelta(minutes=1)) == 1
    assert attempted[0]["Message-ID"] == delivered[0]["Message-ID"]
    assert _outbox(restarted)[0]["status"] == "sent"
    assert mail.deliver_pending(restarted, cfg, sender=sender, now=NOW + timedelta(hours=1)) == 0
    assert len(delivered) == 1


def test_notice_uses_existing_eight_attempt_limit(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    _request(store)
    attempted: list[str] = []

    def fail(message: EmailMessage, _settings: AuditSettings) -> None:
        attempted.append(str(message["Message-ID"]))
        raise OSError("fake outage")

    for attempt in range(9):
        assert (
            mail.deliver_pending(store, cfg, sender=fail, now=NOW + timedelta(hours=attempt)) == 0
        )
    assert len(attempted) == 8 and len(set(attempted)) == 1
    assert _outbox(store)[0]["status"] == "dead"
    assert _outbox(store)[0]["attempts"] == 8


def test_missing_mail_configuration_keeps_request_without_outbox(tmp_path: Path) -> None:
    store = make_store(_settings(tmp_path).database_url)
    request_id = _request(store, notification_email="")
    assert store.list_institutional_requests()[0].id == request_id
    assert _outbox(store) == []


def test_request_and_notice_are_atomic(tmp_path: Path) -> None:
    store = make_store(_settings(tmp_path).database_url)

    def fail_outbox(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.startswith("INSERT INTO email_outbox"):
            raise RuntimeError("simulated outbox insert failure")

    sa.event.listen(store.engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="simulated outbox"):
            _request(store)
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", fail_outbox)
    assert store.list_institutional_requests() == []
    assert _outbox(store) == []


def test_deleted_request_cannot_send_an_orphaned_notice(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    _request(store)
    with store.engine.begin() as conn:
        conn.execute(store.institutional_requests.delete())
    delivered: list[EmailMessage] = []
    assert (
        mail.deliver_pending(store, cfg, sender=lambda msg, _: delivered.append(msg), now=NOW) == 0
    )
    assert delivered == []
    assert _outbox(store)[0]["status"] == "dead"
