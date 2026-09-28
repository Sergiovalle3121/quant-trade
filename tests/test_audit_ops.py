"""Operator probes and incident admission controls, without outside services."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.responses import PlainTextResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import pdf as pdf_lib  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import (  # noqa: E402
    WEBHOOK_BODY_LIMIT,
    AuditAdmissionMiddleware,
    create_app,
    message,
)


def _app(tmp_path: Path) -> Any:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    return create_app(settings, make_store(settings.database_url))


def test_live_and_ready_have_distinct_dependencies(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    app = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/live").json() == {"status": "alive"}
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"] == {"database": True, "pdf": True}
        with patch.object(app.state.store.engine, "connect", side_effect=OSError("private url")):
            assert client.get("/live").status_code == 200
            failed = client.get("/ready")
        assert failed.status_code == 503
        assert failed.json()["checks"] == {"database": False, "pdf": True}
        assert "private url" not in failed.text


def test_readiness_reports_missing_pdf_dependency(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: False)
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": True, "pdf": False}


def test_readiness_requires_audit_schema(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    app = _app(tmp_path)
    with app.state.store.engine.begin() as connection:
        app.state.store.audits.drop(connection)
    with TestClient(app) as client:
        assert client.get("/live").status_code == 200
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": False, "pdf": True}


def test_required_email_configuration_blocks_readiness(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    base = AuditSettings(database_url=f"sqlite:///{tmp_path}/email.db")
    required = replace(base, email_verification_required=True)
    with TestClient(create_app(required, make_store(required.database_url))) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {
        "database": True,
        "pdf": True,
        "email_delivery": False,
    }

    configured = replace(
        required,
        base_url="https://rigor.example",
        smtp_host="smtp.example",
        smtp_from="no-reply@rigor.example",
        email_token_secret="x" * 32,
    )
    with TestClient(create_app(configured, make_store(configured.database_url))) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["email_delivery"] is True


def test_webhook_body_is_bounded_before_signature_work(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/webhooks/stripe",
            content=b"x" * (WEBHOOK_BODY_LIMIT + 1),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.text == "Payload too large"


def test_incident_pause_refuses_before_reading_body() -> None:
    slots = threading.BoundedSemaphore(1)
    messages: list[dict[str, Any]] = []

    async def fail_receive() -> Any:
        raise AssertionError("paused upload body was read")

    async def fail_app(scope: Any, receive: Any, send: Any) -> None:
        raise AssertionError("paused upload reached the parser")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    middleware = AuditAdmissionMiddleware(
        fail_app,
        slots=slots,
        paused=True,
        reject=lambda scope, reason: PlainTextResponse(reason, status_code=503),
    )
    asyncio.run(
        middleware(
            {"type": "http", "method": "POST", "path": "/audits", "headers": []},
            fail_receive,
            send,
        )
    )
    assert messages[0]["status"] == 503
    assert messages[1]["body"] == b"incident_paused"


def test_paused_upload_keeps_existing_report_access(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.delenv("AUDIT_PAUSE_NEW_AUDITS", raising=False)
    app = _app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/audits",
            files={"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")},
            data={"consent": "on"},
            follow_redirects=False,
        )
    assert created.status_code == 303
    report_url = created.headers["location"]
    audit_id = report_url.split("?", 1)[0].rsplit("/", 1)[1]
    assert app.state.store.mark_paid(
        audit_id, stripe_session_id="cs_test_prior", at=datetime.now(UTC)
    )
    count = app.state.store.count_audits()
    monkeypatch.setenv("AUDIT_PAUSE_NEW_AUDITS", "true")
    paused = _app(tmp_path)
    with TestClient(paused) as client:
        rejected = client.post(
            "/audits?lang=en",
            data={"consent": "on"},
            headers={"accept": "application/json"},
        )
        assert rejected.status_code == 503
        assert message("incident_paused", "en") in rejected.json()["error"]
        assert client.get(report_url).status_code == 200
        assert client.get("/live").status_code == 200
        assert client.get("/ready").json()["pause_new_audits"] is True
    assert paused.state.store.count_audits() == count


def _hold_all(slots: threading.BoundedSemaphore) -> int:
    held = 0
    while slots.acquire(blocking=False):
        held += 1
    return held


def test_full_admission_limit_rejects_before_form_parse(tmp_path: Path) -> None:
    app = _app(tmp_path)
    slots = app.state.upload_admission_slots
    held = _hold_all(slots)
    try:
        with TestClient(app) as client:
            response = client.post("/audits?lang=en", data={"consent": "on"})
    finally:
        for _ in range(held):
            slots.release()
    assert response.status_code == 503
    assert message("busy", "en") in response.text
    assert app.state.store.count_audits() == 0


def test_slow_uploads_holding_admission_do_not_block_another_upload(tmp_path: Path) -> None:
    """Three clients still sending their bodies (more than the audit slots)
    leave room for another upload, which queues for the CPU work as usual."""
    app = _app(tmp_path)
    slots = app.state.upload_admission_slots
    slow_clients = app.state.audit_slots.total_tokens + 1
    for _ in range(slow_clients):
        assert slots.acquire(blocking=False)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/audits",
                files={"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")},
                data={"consent": "on"},
                follow_redirects=False,
            )
            ready = client.get("/ready").json()
    finally:
        for _ in range(slow_clients):
            slots.release()
    assert response.status_code == 303, response.text
    assert ready["max_inflight_uploads_per_process"] > slow_clients


def test_stalled_upload_body_is_cut_off_and_frees_admission() -> None:
    slots = threading.BoundedSemaphore(2)
    stalled_forever = asyncio.Event()

    async def read_body_app(scope: Any, receive: Any, send: Any) -> None:
        body = b""
        while True:
            chunk = await receive()
            body += chunk.get("body", b"")
            if not chunk.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    middleware = AuditAdmissionMiddleware(
        read_body_app,
        slots=slots,
        paused=False,
        reject=lambda scope, reason: PlainTextResponse(reason, status_code=408),
        body_seconds=0.2,
    )
    scope = {"type": "http", "method": "POST", "path": "/audits", "headers": []}

    async def stalled_receive() -> Any:
        await stalled_forever.wait()
        return {"type": "http.request", "body": b"", "more_body": False}

    async def whole_receive() -> Any:
        return {"type": "http.request", "body": b"file", "more_body": False}

    async def call(receive: Any) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await middleware(scope, receive, send)
        return messages

    async def scenario() -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        stalled = asyncio.create_task(call(stalled_receive))
        await asyncio.sleep(0)
        normal = await call(whole_receive)
        finished_first = not stalled.done()
        return await stalled, normal, finished_first

    stalled, normal, normal_finished_first = asyncio.run(scenario())
    assert normal_finished_first
    assert normal[0]["status"] == 200 and normal[1]["body"] == b"file"
    assert stalled[0]["status"] == 408
    assert stalled[1]["body"] == b"upload_timeout"
    assert _hold_all(slots) == 2  # both requests gave their slot back
    assert message("upload_timeout", "pt") != message("upload_timeout", "es")


def test_sqlite_backup_restores_account_credit_payment_and_report(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    source = tmp_path / "source.db"
    restored_path = tmp_path / "restored.db"
    store = make_store(f"sqlite:///{source}")
    account = store.create_account(
        email="synthetic@example.invalid", password_hash="synthetic-hash", locale="es", at=now
    )
    assert account is not None
    _, code = store.create_access_code(credits=3, note="synthetic", at=now)
    assert store.link_code(account.id, code.id, at=now) == "linked"
    audit_id = "a" * 24
    assert not store.create_audit(
        audit_id=audit_id,
        created_at=now,
        token_hash="b" * 64,
        client_ip="192.0.2.0",
        declared_json="{}",
        result_json="{}",
        report_html="<html>synthetic</html>",
        overall_class="B",
        digests={},
        equity_csv=b"synthetic equity",
    )
    order = store.reserve_checkout(
        audit_id, account_id=account.id, plan="single", amount_cents=2900, currency="usd", at=now
    )
    store.attach_checkout_session(
        order.id,
        session_id="cs_test_synthetic",
        checkout_url="https://checkout.stripe.com/synthetic",
        expires_at=None,
    )
    paid = store.settle_card_payment(
        order_id=order.id,
        session_id="cs_test_synthetic",
        audit_id=audit_id,
        plan="single",
        expected_cents=2900,
        paid_cents=2900,
        currency="usd",
        pack_code="",
        at=now,
    )
    assert paid.status == "delivered"
    with sqlite3.connect(source) as existing, sqlite3.connect(restored_path) as replacement:
        existing.backup(replacement)
    restored = make_store(f"sqlite:///{restored_path}")
    assert restored.count_accounts() == store.count_accounts() == 1
    assert restored.account_credits(account.id, now) == store.account_credits(account.id, now) == 3
    assert restored.get_checkout_order(order.id) == store.get_checkout_order(order.id)
    assert restored.get_audit(audit_id, with_blobs=True) == store.get_audit(
        audit_id, with_blobs=True
    )
