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


def _held(store, cfg, order, *, sid: str = "cs_live_market_notice"):
    if store.checkout_market(order.id) is None:
        store.record_checkout_market(order.id, "", declared_country="MX", at=NOW)
    session = {
        **_paid(order.id, sid, "pi_market_notice"),
        "customer_details": {"address": {"country": "US"}},
    }
    return fulfil(store, replace(cfg, approved_markets=frozenset({"MX"})), session, at=NOW)


@pytest.mark.parametrize(
    ("locale", "subject", "message", "refund_copy"),
    [
        (
            "es",
            "Pago de Rigor retenido para revisión",
            "este cargo no habilitó una compra",
            "te escribiremos con la solución",
        ),
        (
            "en",
            "Rigor payment held for review",
            "this charge did not unlock a purchase",
            "write to you with the solution",
        ),
        (
            "pt",
            "Pagamento do Rigor retido para análise",
            "esta cobrança não liberou uma compra",
            "escreveremos com a solução",
        ),
    ],
)
def test_market_review_notice_is_durable_once_and_honest_in_each_language(
    tmp_path: Path, locale: str, subject: str, message: str, refund_copy: str
) -> None:
    cfg, store, order = _buyer(tmp_path)
    with store.engine.begin() as conn:
        conn.execute(
            store.accounts.update()
            .where(store.accounts.c.id == order.account_id)
            .values(locale=locale)
        )
    assert _held(store, cfg, order) is None
    assert _held(store, cfg, order) is None
    assert store.get_checkout_order(order.id).status == "paid_review"
    assert not store.get_audit(order.audit_id).paid
    rows = _outbox(store)
    assert len(rows) == 1
    assert rows[0]["id"] == order.id
    assert rows[0]["kind"] == "market_review"
    assert rows[0]["locale"] == locale
    sent = []
    assert mail.deliver_pending(store, cfg, sender=lambda msg, _: sent.append(msg), now=NOW) == 1
    assert sent[0]["Subject"] == subject
    body = sent[0].get_content()
    assert message in body
    assert order.id in body and "USD 29.00" in body
    assert refund_copy in body
    assert "Private report" not in body and "token=" not in body
    assert sent[0]["Message-ID"] == f"<rigor-{order.id}@rigor.example>"
    assert _outbox(store)[0]["status"] == "sent"


@pytest.mark.parametrize(("verified", "smtp_ready"), [(False, True), (True, False)])
def test_market_review_without_verified_configured_mail_still_keeps_charge(
    tmp_path: Path, verified: bool, smtp_ready: bool
) -> None:
    cfg, store, order = _buyer(tmp_path, verified=verified)
    if not smtp_ready:
        cfg = replace(cfg, smtp_host="")
    assert _held(store, cfg, order) is None
    assert store.get_checkout_order(order.id).status == "paid_review"
    assert _outbox(store) == []


def test_market_review_outbox_failure_rolls_back_charge(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)

    def fail_outbox(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "INSERT INTO email_outbox" in statement:
            raise RuntimeError("fake outbox write failure")

    sa.event.listen(store.engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="fake outbox write failure"):
            _held(store, cfg, order)
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", fail_outbox)
    assert store.get_checkout_order(order.id).status == "creating"
    assert store.checkout_market(order.id) == ("MX", "")
    assert _outbox(store) == []


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
        "write to you with the solution"
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


def test_queued_purchase_notice_follows_newly_verified_email_without_new_id(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_changed", "pi_changed"), at=NOW)

    def fail(_msg, _settings):
        raise OSError("fake SMTP outage")

    assert mail.deliver_pending(store, cfg, sender=fail, now=NOW) == 0
    original = _outbox(store)[0]
    assert original["id"] == order.id and original["attempts"] == 1
    assert (
        store.request_email_change(
            order.account_id,
            "new@example.com",
            locale="en",
            at=NOW + timedelta(seconds=1),
        )
        == "pending"
    )
    challenge = next(row for row in _outbox(store) if row["kind"] == "change")
    assert store.confirm_email_challenge(challenge["id"], at=NOW + timedelta(seconds=2)) == (
        "change",
        order.account_id,
    )
    sent = []
    assert (
        mail.deliver_pending(
            store,
            cfg,
            sender=lambda msg, _: sent.append(msg),
            now=NOW + timedelta(minutes=2),
        )
        == 1
    )
    assert len(sent) == 1 and sent[0]["To"] == "new@example.com"
    assert sent[0]["Message-ID"] == f"<rigor-{order.id}@rigor.example>"
    assert "USD 29.00" in sent[0].get_content()
    assert "Private report" not in sent[0].get_content()
    purchase = next(row for row in _outbox(store) if row["kind"] == "purchase")
    assert purchase["id"] == order.id and purchase["email"] == "new@example.com"
    assert purchase["status"] == "sent"
    assert mail.deliver_pending(store, cfg, sender=lambda msg, _: sent.append(msg)) == 0


def test_unverified_new_address_can_requeue_same_purchase_notice_after_verification(
    tmp_path: Path,
) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(
        store, cfg, _paid(order.id, "cs_live_unverified_move", "pi_unverified_move"), at=NOW
    )
    assert store.set_email(order.account_id, "unverified@example.com")
    sent = []
    assert mail.deliver_pending(store, cfg, sender=lambda msg, _: sent.append(msg), now=NOW) == 0
    assert sent == []
    row = _outbox(store)[0]
    assert row["status"] == "dead" and row["used_at"] is None
    assert row["email"] == "unverified@example.com" and row["id"] == order.id
    assert not store.requeue_purchase_email(order.id, at=NOW + timedelta(minutes=1))
    with store.engine.begin() as conn:
        conn.execute(
            store.verified_emails.update()
            .where(store.verified_emails.c.account_id == order.account_id)
            .values(
                email="unverified@example.com", verified_at=(NOW + timedelta(minutes=2)).isoformat()
            )
        )
    assert store.requeue_purchase_email(order.id, at=NOW + timedelta(minutes=2))
    assert not store.requeue_purchase_email(order.id, at=NOW + timedelta(minutes=2))
    assert (
        mail.deliver_pending(
            store,
            cfg,
            sender=lambda msg, _: sent.append(msg),
            now=NOW + timedelta(minutes=2),
        )
        == 1
    )
    assert len(sent) == 1 and sent[0]["To"] == "unverified@example.com"
    assert sent[0]["Message-ID"] == f"<rigor-{order.id}@rigor.example>"
    assert _outbox(store)[0]["status"] == "sent"


def test_account_deletion_removes_queued_purchase_notice(tmp_path: Path) -> None:
    cfg, store, order = _buyer(tmp_path)
    assert fulfil(store, cfg, _paid(order.id, "cs_live_deleted", "pi_deleted"), at=NOW)
    assert _outbox(store)[0]["email"] == "buyer@example.com"
    store.delete_account(order.account_id)
    assert _outbox(store) == []
    sent = []
    assert mail.deliver_pending(store, cfg, sender=lambda msg, _: sent.append(msg), now=NOW) == 0
    assert sent == []


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
