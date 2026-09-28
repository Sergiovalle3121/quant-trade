"""Operators can see and safely recover failed purchase mail without recipients."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_purchase_mail import NOW, _buyer, _held, _outbox, _paid  # noqa: E402

from quant_trade.audit import mail, pdf  # noqa: E402
from quant_trade.audit.payments import fulfil  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402


def _exhaust_smtp(store, cfg, *, start: datetime) -> None:
    def fail(_message, _settings) -> None:
        raise OSError("fake SMTP outage")

    for attempt in range(8):
        assert (
            mail.deliver_pending(store, cfg, sender=fail, now=start + timedelta(hours=2 * attempt))
            == 0
        )


def test_dead_purchase_notice_visible_and_admin_requeues_without_recipient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_recover", "pi_recover"), at=NOW)
    _exhaust_smtp(store, cfg, start=NOW)
    row = _outbox(store)[0]
    assert row["status"] == "dead" and row["attempts"] == 8

    issues = store.list_purchase_email_issues(at=NOW + timedelta(days=1))
    assert len(issues) == 1
    assert asdict(issues[0]) == {
        "id": order.id,
        "kind": "purchase",
        "status": "dead",
        "attempts": 8,
        "created_at": row["created_at"],
        "next_attempt_at": row["next_attempt_at"],
    }
    assert store.purchase_email_warning_counts(at=NOW + timedelta(days=1)) == {
        "dead": 1,
        "overdue": 0,
    }

    monkeypatch.setattr(pdf, "available", lambda: True)
    key = "operator-key-long-enough-for-admin"
    app = create_app(replace(cfg, admin_key=key), store)
    client = TestClient(app)  # No lifespan: the fake SMTP sender is the only transport.
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["warnings"] == {
        "purchase_mail_dead": 1,
        "purchase_mail_overdue": 0,
        "purchase_mail_probe_failed": 0,
    }
    refused = client.post(
        "/panel", data={"key": "wrong", "action": "mail_requeue", "mail_id": order.id}
    )
    assert refused.status_code == 403
    listed = client.post("/panel", data={"key": key})
    assert listed.status_code == 200
    assert order.id in listed.text and "Reintentar aviso" in listed.text
    assert "buyer@example.com" not in listed.text
    assert "Private report" not in listed.text

    requeued = client.post(
        "/panel", data={"key": key, "action": "mail_requeue", "mail_id": order.id}
    )
    assert requeued.status_code == 200
    assert "Aviso reencolado" in requeued.text
    assert _outbox(store)[0]["status"] == "queued"
    assert _outbox(store)[0]["attempts"] == 0
    sent = []
    assert mail.deliver_pending(store, cfg, sender=lambda msg, _: sent.append(msg)) == 1
    assert len(sent) == 1
    assert _outbox(store)[0]["status"] == "sent"
    again = client.post("/panel", data={"key": key, "action": "mail_requeue", "mail_id": order.id})
    assert "No se reencoló" in again.text
    assert store.requeue_purchase_email(order.id, at=datetime.now(UTC)) is False


def test_requeue_renews_expiry_but_rejects_changed_or_unverified_address(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_stale", "pi_stale"), at=NOW)
    _exhaust_smtp(store, cfg, start=NOW)
    late = NOW + timedelta(days=8)
    with store.engine.begin() as conn:
        conn.execute(
            store.accounts.update()
            .where(store.accounts.c.id == order.account_id)
            .values(email="changed@example.com")
        )
    assert not store.requeue_purchase_email(order.id, at=late)
    with store.engine.begin() as conn:
        conn.execute(
            store.accounts.update()
            .where(store.accounts.c.id == order.account_id)
            .values(email="buyer@example.com")
        )
        conn.execute(
            store.verified_emails.delete().where(
                store.verified_emails.c.account_id == order.account_id
            )
        )
    assert not store.requeue_purchase_email(order.id, at=late)
    with store.engine.begin() as conn:
        conn.execute(
            store.verified_emails.insert().values(
                account_id=order.account_id,
                email="buyer@example.com",
                verified_at=late.isoformat(),
            )
        )
    assert store.requeue_purchase_email(order.id, at=late)
    assert _outbox(store)[0]["expires_at"] > late.isoformat()
    sent = []
    assert mail.deliver_pending(store, cfg, sender=lambda msg, _: sent.append(msg), now=late) == 1
    assert sent[0]["Message-ID"] == f"<rigor-{order.id}@rigor.example>"


def test_charge_review_requeue_requires_duplicate_live_order(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_first", "pi_first"), at=NOW)
    second = _paid("", "cs_live_second", "pi_second")
    assert fulfil(store, cfg, second, at=NOW + timedelta(seconds=1))
    review = next(row for row in _outbox(store) if row["kind"] == "charge_review")
    with store.engine.begin() as conn:
        conn.execute(
            store.email_outbox.update()
            .where(store.email_outbox.c.id == review["id"])
            .values(status="dead", attempts=8)
        )
        conn.execute(
            store.checkout_orders.update()
            .where(store.checkout_orders.c.id == review["id"])
            .values(status="delivered")
        )
    assert not store.requeue_purchase_email(review["id"], at=NOW + timedelta(days=1))
    with store.engine.begin() as conn:
        conn.execute(
            store.checkout_orders.update()
            .where(store.checkout_orders.c.id == review["id"])
            .values(status="duplicate")
        )
    assert store.requeue_purchase_email(review["id"], at=NOW + timedelta(days=1))
    assert not store.requeue_purchase_email(review["id"], at=NOW + timedelta(days=1))


def test_market_review_mail_is_visible_and_requeued_only_while_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert _held(store, cfg, order) is None
    _exhaust_smtp(store, cfg, start=NOW)
    row = _outbox(store)[0]
    assert row["kind"] == "market_review" and row["status"] == "dead"
    assert store.purchase_email_warning_counts(at=NOW + timedelta(days=1)) == {
        "dead": 1,
        "overdue": 0,
    }
    assert [
        issue.kind for issue in store.list_purchase_email_issues(at=NOW + timedelta(days=1))
    ] == ["market_review"]
    monkeypatch.setattr(pdf, "available", lambda: True)
    key = "operator-key-long-enough-for-admin"
    client = TestClient(create_app(replace(cfg, admin_key=key), store))
    assert client.get("/ready").json()["warnings"]["purchase_mail_dead"] == 1
    panel = client.post("/panel", data={"key": key})
    assert panel.status_code == 200
    assert order.id in panel.text and "market_review" in panel.text
    assert "buyer@example.com" not in panel.text
    with store.engine.begin() as conn:
        conn.execute(
            store.checkout_orders.update()
            .where(store.checkout_orders.c.id == order.id)
            .values(status="delivered")
        )
    assert not store.requeue_purchase_email(order.id, at=NOW + timedelta(days=1))
    with store.engine.begin() as conn:
        conn.execute(
            store.checkout_orders.update()
            .where(store.checkout_orders.c.id == order.id)
            .values(status="paid_review")
        )
    assert store.requeue_purchase_email(order.id, at=NOW + timedelta(days=1))
    assert not store.requeue_purchase_email(order.id, at=NOW + timedelta(days=1))
    sent = []
    assert (
        mail.deliver_pending(
            store, cfg, sender=lambda msg, _: sent.append(msg), now=NOW + timedelta(days=1)
        )
        == 1
    )
    assert sent[0]["Subject"] == "Rigor payment held for review"


def test_overdue_warning_does_not_change_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_overdue", "pi_overdue"), at=NOW)
    assert store.purchase_email_warning_counts(at=NOW + timedelta(minutes=16)) == {
        "dead": 0,
        "overdue": 1,
    }
    monkeypatch.setattr(pdf, "available", lambda: True)
    client = TestClient(create_app(cfg, store))
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["warnings"]["purchase_mail_overdue"] == 1


def test_warning_probe_failure_does_not_change_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, store, _ = _buyer(tmp_path)
    monkeypatch.setattr(pdf, "available", lambda: True)
    client = TestClient(create_app(cfg, store))
    with patch.object(store, "purchase_email_warning_counts", side_effect=OSError("private")):
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["warnings"] == {
        "purchase_mail_dead": 0,
        "purchase_mail_overdue": 0,
        "purchase_mail_probe_failed": 1,
    }
    assert "private" not in response.text


def test_existing_outbox_gets_warning_indexes_on_reopen(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    from quant_trade.audit.store import make_store

    cfg, store, _ = _buyer(tmp_path)
    with store.engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX ix_email_outbox_kind_status_due")
        conn.exec_driver_sql("DROP INDEX ix_email_outbox_kind_status_lease")
    reopened = make_store(cfg.database_url)
    index_names = {item["name"] for item in inspect(reopened.engine).get_indexes("email_outbox")}
    assert "ix_email_outbox_kind_status_due" in index_names
    assert "ix_email_outbox_kind_status_lease" in index_names
