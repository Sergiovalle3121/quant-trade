"""Purchase notices are durable, private and tied to one frozen charge."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sa = pytest.importorskip("sqlalchemy")

from quant_trade.audit import mail  # noqa: E402
from quant_trade.audit.payments import fulfil  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def _buyer(tmp_path: Path, *, verified: bool = True):
    cfg = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/purchase.db",
        base_url="https://rigor.example",
        free_mode=False,
        stripe_secret_key="sk_live_fake",
        stripe_webhook_secret="whsec_fake",
        email_token_secret="stable fake secret for tests 1234567890123456",
        smtp_host="smtp.example",
        smtp_from="Rigor <hello@rigor.example>",
    )
    store = make_store(cfg.database_url)
    account = store.create_account(
        email="buyer@example.com", password_hash="not-used", locale="en", at=NOW
    )
    assert account is not None
    if verified:
        with store.engine.begin() as conn:
            conn.execute(
                store.verified_emails.insert().values(
                    account_id=account.id, email=account.email, verified_at=NOW.isoformat()
                )
            )
    store.create_audit(
        audit_id="audit-purchase",
        created_at=NOW,
        token_hash="fake-hash",
        client_ip="127.0.0.1",
        declared_json="{}",
        result_json="{}",
        report_html="<p>Private report</p>",
        overall_class="caution",
        digests={},
        equity_csv=None,
    )
    assert store.link_audit(account.id, "audit-purchase", at=NOW) == "linked"
    order = store.reserve_checkout(
        "audit-purchase",
        account_id=account.id,
        plan="single",
        amount_cents=2900,
        currency="usd",
        at=NOW,
    )
    return cfg, store, order


def _paid(order_id: str, sid: str, pi: str) -> dict[str, object]:
    return {
        "id": sid,
        "payment_intent": pi,
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": 2900,
        "metadata": {
            "audit_id": "audit-purchase",
            "plan": "single",
            "order_id": order_id,
            "app": "rigor",
        },
    }


def _outbox(store):
    with store.engine.connect() as conn:
        return conn.execute(store.email_outbox.select()).mappings().all()


def test_paid_replay_queues_one_notice_without_report_token(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    session = _paid(order.id, "cs_live_notice_1", "pi_notice_1")
    session["payment_intent"] = {"id": "pi_notice_1"}  # Stripe may expand this field.
    assert fulfil(store, cfg, session, at=NOW) == "audit-purchase"
    assert fulfil(store, cfg, session, at=NOW) == "audit-purchase"
    rows = _outbox(store)
    assert len(rows) == 1
    assert rows[0]["id"] == order.id and rows[0]["kind"] == "purchase"
    assert rows[0]["email"] == "buyer@example.com"
    messages = []
    assert (
        mail.deliver_pending(store, cfg, sender=lambda msg, _: messages.append(msg), now=NOW) == 1
    )
    assert (
        mail.deliver_pending(store, cfg, sender=lambda msg, _: messages.append(msg), now=NOW) == 0
    )
    body = messages[0].get_content()
    assert "USD 29.00" in body and order.id in body
    assert "Private report" not in body and "token=" not in body
    assert messages[0]["Message-ID"] == f"<rigor-{order.id}@rigor.example>"


def test_second_charge_has_review_notice_and_no_second_entitlement(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_notice_1", "pi_notice_1"), at=NOW)
    second = _paid("", "cs_live_notice_2", "pi_notice_2")
    assert fulfil(store, cfg, second, at=NOW + timedelta(seconds=1)) == "audit-purchase"
    rows = _outbox(store)
    assert len(rows) == 2
    assert {row["kind"] for row in rows} == {"purchase", "charge_review"}
    assert len([o for o in store.list_checkout_orders() if o.status == "delivered"]) == 1
    assert len([o for o in store.list_checkout_orders() if o.status == "duplicate"]) == 1
    messages = []
    assert (
        mail.deliver_pending(
            store, cfg, sender=lambda msg, _: messages.append(msg), now=NOW + timedelta(seconds=1)
        )
        == 2
    )
    assert (
        "does not confirm a refund"
        in next(m for m in messages if "review" in m["Subject"]).get_content()
    )


def test_unverified_buyer_has_no_purchase_mail(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path, verified=False)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_unverified", "pi_unverified"), at=NOW)
    assert _outbox(store) == []


def test_sandbox_unlock_never_sends_a_real_charge_notice(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    sandbox = replace(
        cfg,
        stripe_secret_key="sk_test_fake",
        stripe_test_audits=frozenset({"audit-purchase"}),
    )
    session = {**_paid(order.id, "cs_test_notice", "pi_sandbox_notice"), "livemode": False}
    assert fulfil(store, sandbox, session, at=NOW) == "audit-purchase"
    assert store.get_checkout_order(order.id).status == "delivered"
    assert _outbox(store) == []


def test_purchase_notice_survives_smtp_failure_and_restart(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_retry", "pi_retry"), at=NOW)

    def fail(_msg, _settings):
        raise OSError("fake SMTP outage")

    assert mail.deliver_pending(store, cfg, sender=fail, now=NOW) == 0
    assert _outbox(store)[0]["attempts"] == 1
    reopened = make_store(cfg.database_url)
    sent = []
    assert (
        mail.deliver_pending(
            reopened, cfg, sender=lambda msg, _: sent.append(msg), now=NOW + timedelta(minutes=2)
        )
        == 1
    )
    assert sent[0]["Message-ID"] == f"<rigor-{order.id}@rigor.example>"
    assert _outbox(reopened)[0]["status"] == "sent"


def test_outbox_write_failure_rolls_back_entitlement_and_order(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)

    def fail_outbox(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "INSERT INTO email_outbox" in statement:
            raise RuntimeError("fake database write failure")

    sa.event.listen(store.engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="fake database write failure"):
            fulfil(store, cfg, _paid(order.id, "cs_live_atomic", "pi_atomic"), at=NOW)
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", fail_outbox)
    assert not store.get_audit("audit-purchase").paid
    assert store.get_checkout_order(order.id).status == "creating"
    assert _outbox(store) == []
