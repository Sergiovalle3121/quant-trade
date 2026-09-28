"""Card payments through Stripe Checkout, single audit and pack; Stripe is mocked."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastapi")
sa = pytest.importorskip("sqlalchemy")

from audit_fixtures import csv_bytes, positive_drift, signed_in  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import accounts, funnel  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.payments import (  # noqa: E402
    PLAN_PACK,
    PLAN_SINGLE,
    card_mode,
    checkout_params,
    fulfil,
    pack_code,
    payment_link_urls,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import (  # noqa: E402
    CODE_ALPHABET,
    hash_access_code,
    make_store,
)
from quant_trade.audit.web import create_app, sign_stripe_payload  # noqa: E402

WEBHOOK_SECRET = "whsec_test"
SELLING = {
    "stripe_secret_key": "sk_live_x",
    "stripe_webhook_secret": WEBHOOK_SECRET,
    "free_mode": False,
    "access_codes": True,
    "price_usd_cents": 2900,
    "pack_price_usd_cents": 6900,
    "contact_url": "https://wa.me/5200000000",
    "base_url": "https://rigor.example",
    "approved_markets": frozenset({"MX"}),
}
NOW = datetime(2026, 9, 25, tzinfo=UTC)


def _settings(tmp_path: Path, **overrides: Any) -> AuditSettings:
    values = {**SELLING, **overrides}
    return AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **values
    )


def _client(tmp_path: Path, **overrides: Any) -> TestClient:
    settings = _settings(tmp_path, **overrides)
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def _upload(client: TestClient) -> tuple[str, str]:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    location = client.post("/audits", files=files, data=data, follow_redirects=False).headers[
        "location"
    ]
    path, _, query = location.partition("?")
    return path.rsplit("/", 1)[1], query.split("token=")[1].split("&")[0]


PAID = {PLAN_SINGLE: 2900, PLAN_PACK: 6900}


def _session(audit_id: str, *, plan: str = PLAN_SINGLE, sid: str = "cs_test_1", **extra: Any):
    return {
        "id": sid,
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": PAID[plan],
        "customer_details": {"address": {"country": "MX"}},
        "metadata": {"audit_id": audit_id, "plan": plan, "app": "rigor"},
        **extra,
    }


def _webhook(client: TestClient, session: dict[str, Any]) -> int:
    event = json.dumps({"type": "checkout.session.completed", "data": {"object": session}})
    header = sign_stripe_payload(event.encode(), WEBHOOK_SECRET, timestamp=int(time.time()))
    return client.post(
        "/webhooks/stripe", content=event, headers={"stripe-signature": header}
    ).status_code


# -- settings -----------------------------------------------------------------
def test_card_payments_need_a_secret_key_and_a_webhook_secret_but_no_price_id() -> None:
    env = {
        "STRIPE_SECRET_KEY": "sk_test_x",
        "STRIPE_WEBHOOK_SECRET": "whsec_x",
        "AUDIT_FREE_MODE": "false",
    }
    settings = AuditSettings.from_env(env)
    assert settings.stripe_enabled and card_mode(settings) == "test"
    live = AuditSettings.from_env({**env, "STRIPE_SECRET_KEY": "sk_live_x"})
    assert card_mode(live) == "live"
    # A publishable key pasted by mistake leaves card payments off (and free mode on).
    wrong = AuditSettings.from_env({**env, "STRIPE_SECRET_KEY": "pk_test_x"})
    assert not wrong.stripe_enabled and wrong.free_mode and card_mode(wrong) == "off"
    no_hook = AuditSettings.from_env({**env, "STRIPE_WEBHOOK_SECRET": "sk_test_y"})
    assert not no_hook.stripe_enabled


def test_the_pack_is_on_sale_with_card_payments_alone(tmp_path: Path) -> None:
    card_only = _settings(tmp_path, access_codes=False)
    assert card_only.pack_price_usd == 69.0
    assert _settings(tmp_path, pack_price_usd_cents=0).pack_price_usd == 0.0
    assert _settings(tmp_path, pack_price_usd_cents=9000).pack_price_usd == 0.0


# -- checkout parameters --------------------------------------------------------
def test_checkout_params_price_each_plan_and_come_back_to_the_report(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    single = checkout_params(settings, "a1", "tok", plan=PLAN_SINGLE, locale="es")
    (line,) = single["line_items"]
    assert line["price_data"]["unit_amount"] == 2900
    assert line["price_data"]["currency"] == "usd"
    assert single["metadata"] == {"audit_id": "a1", "plan": PLAN_SINGLE, "app": "rigor"}
    assert single["success_url"] == (
        "https://rigor.example/audits/a1?token=tok&lang=es&session_id={CHECKOUT_SESSION_ID}"
    )
    assert single["cancel_url"].endswith("&pay=cancelled")
    assert single["mode"] == "payment" and single["locale"] == "es"

    pack = checkout_params(settings, "a1", "tok", plan=PLAN_PACK, locale="en")
    (line,) = pack["line_items"]
    assert line["price_data"]["unit_amount"] == 6900
    assert "3" in line["price_data"]["product_data"]["name"]
    assert pack["metadata"]["plan"] == PLAN_PACK and pack["locale"] == "en"

    priced = _settings(tmp_path, stripe_price_id="price_123")
    assert checkout_params(priced, "a1", "t", plan=PLAN_SINGLE, locale="es")["line_items"] == [
        {"price": "price_123", "quantity": 1}
    ]
    # The price id is for the single audit only; the pack is always priced inline.
    assert (
        "price_data"
        in checkout_params(priced, "a", "t", plan=PLAN_PACK, locale="es")["line_items"][0]
    )
    with pytest.raises(ValueError):
        checkout_params(settings, "a1", "t", plan="gift", locale="es")


@pytest.mark.parametrize(
    ("plan", "amount", "product"),
    [
        (PLAN_SINGLE, 2900, "Rigor · relatório completo"),
        (PLAN_PACK, 6900, "Rigor · pacote de 3 relatórios"),
    ],
)
def test_pt_checkout_uses_portuguese_product_and_returns_to_pt_report(
    tmp_path: Path, plan: str, amount: int, product: str
) -> None:
    params = checkout_params(
        _settings(tmp_path), "report123", "private-token", plan=plan, locale="pt"
    )
    assert params["locale"] == "pt-BR"
    assert params["line_items"] == [
        {
            "price_data": {
                "currency": "usd",
                "unit_amount": amount,
                "product_data": {"name": product},
            },
            "quantity": 1,
        }
    ]
    assert params["success_url"] == (
        "https://rigor.example/audits/report123?token=private-token"
        "&lang=pt&session_id={CHECKOUT_SESSION_ID}"
    )
    assert params["cancel_url"] == (
        "https://rigor.example/audits/report123?token=private-token&lang=pt&pay=cancelled"
    )


def test_pack_code_is_stable_secret_bound_and_well_formed() -> None:
    code = pack_code("whsec_a", "cs_test_1")
    assert code == pack_code("whsec_a", "cs_test_1")
    assert code != pack_code("whsec_a", "cs_test_2")
    assert code != pack_code("whsec_b", "cs_test_1")
    prefix, *groups = code.split("-")
    assert prefix == "AUD" and [len(g) for g in groups] == [4, 4, 4]
    assert all(ch in CODE_ALPHABET for g in groups for ch in g)


# -- fulfilment ------------------------------------------------------------------
def test_fulfil_is_idempotent_and_needs_a_paid_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    audit_id, _ = _upload(client)
    store = client.app.state.store

    assert (
        fulfil(store, settings, {**_session(audit_id), "payment_status": "unpaid"}, at=NOW) is None
    )
    assert fulfil(store, settings, _session("missing"), at=NOW) is None
    assert fulfil(store, settings, _session(audit_id, sid="code:x"), at=NOW) is None
    assert not store.get_audit(audit_id).paid

    pack = _session(audit_id, plan=PLAN_PACK)
    assert fulfil(store, settings, pack, at=NOW) == audit_id
    assert fulfil(store, settings, pack, at=NOW) == audit_id
    record = store.get_audit(audit_id)
    assert record.paid and record.stripe_session_id == "cs_test_1"
    (code,) = store.list_access_codes()
    assert (code.credits_total, code.credits_used) == (2, 0)


def test_store_keeps_only_the_hash_of_an_outside_code(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    assert store.ensure_access_code("AUD-2222-3333-4444", credits=2, note="n", at=NOW)
    assert not store.ensure_access_code("aud 2222 3333 4444", credits=2, note="n", at=NOW)
    record = store.get_access_code("AUD-2222-3333-4444")
    assert record is not None and record.credits_left == 2
    assert store.get_access_code("AUD-9999-9999-9999") is None
    with store.engine.connect() as conn:
        rows = conn.execute(store.access_codes.select()).mappings().all()
    assert [row["code_sha256"] for row in rows] == [hash_access_code("AUD-2222-3333-4444")]
    assert "2222" not in json.dumps([dict(row) for row in rows])


# -- web -------------------------------------------------------------------------
def test_locked_report_puts_card_payment_first_with_the_pack_and_keeps_codes(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    assert client.get("/health").json()["card_mode"] == "live"
    for lang, pay, pack, alt in (
        ("es", "Pagar con tarjeta", "Comprar el paquete de 3 (USD 69)", "Prefieres pagar por"),
        ("en", "Pay by card", "Buy the pack of 3 (USD 69)", "Prefer a bank transfer"),
    ):
        page = client.get(f"/audits/{audit_id}?token={token}&lang={lang}").text
        assert pay in page and pack in page and alt in page
        assert page.index(pay) < page.index("name='code'")
        assert "name='plan' value='pack'" in page
        # Both buttons share one height; the card button and the secure note carry icons.
        assert "class='btn btn-ghost btn-lg' type='submit' name='plan' value='pack'" in page
        assert "class='muted pay-secure'><svg" in page and "class='paybox pay-alt'" in page
        assert find_claims(page) == []
    landing = client.get("/").text
    assert "procesado por Stripe" in landing and find_claims(landing) == []


def test_checkout_route_sends_the_chosen_plan(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    seen: list[tuple[str, str, str, int]] = []

    def fake(
        settings: AuditSettings,
        aid: str,
        tok: str,
        *,
        plan: str,
        locale: str,
        order_id: str,
        amount_cents: int,
    ) -> str:
        seen.append((plan, locale, order_id, amount_cents))
        return "https://checkout.stripe.test/s"

    client.app.state.checkout_factory = fake
    url = f"/audits/{audit_id}/checkout?token={token}&lang=en"
    for plan in ("pack", "single", "gift"):
        response = client.post(
            url, data={"plan": plan, "billing_country": "MX"}, follow_redirects=False
        )
        assert response.headers["location"] == "https://checkout.stripe.test/s"
    assert [(plan, locale, amount) for plan, locale, _, amount in seen] == [
        ("pack", "en", 6900),
        ("single", "en", 2900),
    ]
    orders = client.app.state.store.list_checkout_orders()
    assert len(orders) == 2 and len({order.id for order in orders}) == 2

    no_pack = _client(tmp_path / "b", pack_price_usd_cents=0)
    aid, tok = _upload(no_pack)
    no_pack.app.state.checkout_factory = fake
    no_pack.post(
        f"/audits/{aid}/checkout?token={tok}",
        data={"plan": "pack", "billing_country": "MX"},
    )
    assert seen[-1][0:2] == ("single", "es")
    assert "name='plan' value='pack'" not in no_pack.get(f"/audits/{aid}?token={tok}").text


def test_checkout_retry_after_restart_reuses_frozen_order(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    calls: list[str] = []

    def fake(
        settings: AuditSettings,
        aid: str,
        tok: str,
        *,
        plan: str,
        locale: str,
        order_id: str,
        amount_cents: int,
    ) -> dict[str, Any]:
        calls.append(order_id)
        return {"id": "cs_frozen", "url": "https://checkout.stripe.test/frozen"}

    client.app.state.checkout_factory = fake
    path = f"/audits/{audit_id}/checkout?token={token}"
    first = client.post(path, data={"billing_country": "MX"}, follow_redirects=False)
    assert first.headers["location"] == "https://checkout.stripe.test/frozen"
    restarted = _client(tmp_path, price_usd_cents=4900)
    restarted.app.state.checkout_factory = fake
    second = restarted.post(path, data={"billing_country": "MX"}, follow_redirects=False)
    assert second.headers["location"] == first.headers["location"]
    assert len(calls) == 1
    (order,) = restarted.app.state.store.list_checkout_orders()
    assert order.amount_cents == 2900 and order.session_id == "cs_frozen"


def test_live_checkout_needs_approved_country_and_freezes_it(tmp_path: Path) -> None:
    client = _client(tmp_path, approved_markets=frozenset({"MX", "US"}))
    audit_id, token = _upload(client)
    path = f"/audits/{audit_id}/checkout?token={token}"
    page = client.get(f"/audits/{audit_id}?token={token}").text
    assert "name='billing_country'" in page and "País de facturación" in page
    for value in ("", "BR", "ZZ"):
        denied = client.post(path, data={"billing_country": value}, follow_redirects=False)
        assert denied.status_code == 403
    assert client.app.state.store.list_checkout_orders() == []

    client.app.state.checkout_factory = lambda *_args, **_kwargs: {
        "id": "cs_market_1",
        "url": "https://checkout.stripe.test/market",
    }
    allowed = client.post(path, data={"billing_country": "MX"}, follow_redirects=False)
    assert allowed.status_code == 303
    order = client.app.state.store.list_checkout_orders()[0]
    assert client.app.state.store.checkout_market(order.id) == ("MX", "")
    changed = client.post(path, data={"billing_country": "US"}, follow_redirects=False)
    assert changed.status_code == 409
    assert len(client.app.state.store.list_checkout_orders()) == 1


def test_live_checkout_is_closed_without_approved_markets(tmp_path: Path) -> None:
    settings = _settings(tmp_path, approved_markets=frozenset())
    assert not settings.card_public
    client = _client(tmp_path, approved_markets=frozenset())
    audit_id, token = _upload(client)
    page = client.get(f"/audits/{audit_id}?token={token}").text
    assert "name='billing_country'" not in page
    assert client.post(f"/audits/{audit_id}/checkout?token={token}").status_code == 503
    assert client.app.state.store.list_checkout_orders() == []


def test_market_mismatch_records_charge_without_delivery(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    client.app.state.checkout_factory = lambda *_args, **_kwargs: {
        "id": "cs_market_bad",
        "url": "https://checkout.stripe.test/market-bad",
    }
    path = f"/audits/{audit_id}/checkout?token={token}"
    assert (
        client.post(path, data={"billing_country": "MX"}, follow_redirects=False).status_code == 303
    )
    store = client.app.state.store
    order = store.list_checkout_orders()[0]
    refund = {
        "id": "re_market_bad",
        "object": "refund",
        "payment_intent": "pi_market_bad",
        "charge": "ch_market_bad",
        "amount": 1000,
        "currency": "usd",
        "status": "succeeded",
    }
    refund_event = json.dumps(
        {
            "id": "evt_market_bad_refund",
            "type": "refund.created",
            "livemode": True,
            "data": {"object": refund},
        }
    ).encode()
    signature = sign_stripe_payload(refund_event, WEBHOOK_SECRET, timestamp=int(time.time()))
    assert (
        client.post(
            "/webhooks/stripe", content=refund_event, headers={"stripe-signature": signature}
        ).status_code
        == 200
    )
    assert store.list_stripe_refunds()[0].order_id == ""
    bad = _session(
        audit_id,
        sid="cs_market_bad",
        metadata={"audit_id": audit_id, "plan": PLAN_SINGLE, "app": "rigor", "order_id": order.id},
        customer_details={"address": {"country": "US"}},
        currency="mxn",
        amount_total=52900,
        currency_conversion={"source_currency": "usd", "amount_total": 2900},
        payment_intent="pi_market_bad",
    )
    assert _webhook(client, bad) == 200
    assert not store.get_audit(audit_id).paid
    assert store.get_checkout_order(order.id).status == "paid_review"
    assert store.get_checkout_order(order.id).paid_amount_cents == 2900
    assert store.checkout_market(order.id) == ("MX", "US")
    assert store.funnel_country_events("2000-01-01") == [("US", 1, 0, 2900)]
    assert store.list_stripe_refunds()[0].order_id == order.id
    counts = funnel.build(store.funnel_events("2000-01-01")).total.counts
    assert counts["gross_usd_cents"] == 2900
    assert counts["refund_usd_cents"] == 1000
    blocked = client.post(path, data={"billing_country": "MX"}, follow_redirects=False)
    assert blocked.status_code == 409
    assert len(store.list_checkout_orders()) == 1
    assert "No vuelvas a pagar" in client.get(f"/audits/{audit_id}?token={token}").text
    with pytest.raises(ValueError, match="checkout market review"):
        store.reserve_checkout(
            audit_id,
            account_id=store.account_for_audit(audit_id) or "",
            plan=PLAN_SINGLE,
            amount_cents=2900,
            currency="usd",
            at=NOW,
            declared_country="MX",
        )
    assert len(store.list_refused_payments()) == 1
    assert _webhook(client, bad) == 200
    assert len(store.list_refused_payments()) == 1


def test_matching_stripe_billing_country_delivers_and_is_recorded(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    client.app.state.checkout_factory = lambda *_args, **_kwargs: {
        "id": "cs_market_good",
        "url": "https://checkout.stripe.test/market-good",
    }
    path = f"/audits/{audit_id}/checkout?token={token}"
    assert (
        client.post(path, data={"billing_country": "MX"}, follow_redirects=False).status_code == 303
    )
    store = client.app.state.store
    order = store.list_checkout_orders()[0]
    paid = _session(
        audit_id,
        sid="cs_market_good",
        metadata={"audit_id": audit_id, "plan": PLAN_SINGLE, "app": "rigor", "order_id": order.id},
    )
    assert _webhook(client, paid) == 200
    assert store.get_audit(audit_id).paid
    assert store.checkout_market(order.id) == ("MX", "MX")
    assert store.funnel_country_events("2000-01-01") == [("MX", 1, 1, 2900)]


@pytest.mark.parametrize(("first_country", "second_country"), [("MX", "US"), ("US", "MX")])
def test_two_paid_sessions_with_one_order_metadata_keep_separate_charges(
    tmp_path: Path, first_country: str, second_country: str
) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    client.app.state.checkout_factory = lambda *_args, **_kwargs: {
        "id": "cs_market_first",
        "url": "https://checkout.stripe.test/market-first",
    }
    assert (
        client.post(
            f"/audits/{audit_id}/checkout?token={token}",
            data={"billing_country": "MX"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    store = client.app.state.store
    original = store.list_checkout_orders()[0]
    metadata = {
        "audit_id": audit_id,
        "plan": PLAN_SINGLE,
        "app": "rigor",
        "order_id": original.id,
    }
    first = _session(
        audit_id,
        sid="cs_market_first",
        metadata=metadata,
        customer_details={"address": {"country": first_country}},
        payment_intent="pi_market_first",
    )
    second = _session(
        audit_id,
        sid="cs_market_second",
        metadata=metadata,
        customer_details={"address": {"country": second_country}},
        payment_intent="pi_market_second",
    )
    assert _webhook(client, first) == 200
    assert _webhook(client, second) == 200
    assert _webhook(client, first) == 200
    assert _webhook(client, second) == 200

    orders = {order.session_id: order for order in store.list_checkout_orders()}
    assert set(orders) == {"cs_market_first", "cs_market_second"}
    expected_status = {"MX": "delivered", "US": "paid_review"}
    assert orders["cs_market_first"].status == expected_status[first_country]
    assert orders["cs_market_second"].status == expected_status[second_country]
    assert store.checkout_market(original.id) == ("MX", first_country)
    assert store.checkout_market(orders["cs_market_second"].id) == ("MX", second_country)
    with store.engine.connect() as conn:
        links = dict(
            conn.execute(
                sa.select(
                    store.stripe_payment_intents.c.payment_intent_id,
                    store.stripe_payment_intents.c.order_id,
                )
            ).all()
        )
    assert links == {
        "pi_market_first": original.id,
        "pi_market_second": orders["cs_market_second"].id,
    }
    counts = funnel.build(store.funnel_events("2000-01-01")).total.counts
    assert counts["purchases"] == 2
    assert counts["deliveries"] == 1
    assert counts["gross_usd_cents"] == 5800
    refund = store.record_stripe_refund(
        refund_id="re_market_second",
        payment_intent_id="pi_market_second",
        charge_id="ch_market_second",
        amount_minor=1000,
        currency="usd",
        status="succeeded",
        livemode=True,
        event_id="evt_market_second",
        at=NOW,
    )
    assert refund.order_id == orders["cs_market_second"].id
    counts = funnel.build(store.funnel_events("2000-01-01")).total.counts
    assert counts["refund_usd_cents"] == 1000


def test_webhook_replay_queues_review_notice_for_its_own_order(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        smtp_host="smtp.example",
        smtp_from="Rigor <hello@rigor.example>",
        email_token_secret="stable fake secret for tests 1234567890123456",
    )
    store = client.app.state.store
    account = store.find_account("tester@example.com")
    assert account is not None
    with store.engine.begin() as conn:
        conn.execute(
            store.verified_emails.insert().values(
                account_id=account.id, email=account.email, verified_at=NOW.isoformat()
            )
        )
    audit_id, token = _upload(client)
    client.app.state.checkout_factory = lambda *_args, **_kwargs: {
        "id": "cs_market_mail_first",
        "url": "https://checkout.stripe.test/market-mail",
    }
    assert (
        client.post(
            f"/audits/{audit_id}/checkout?token={token}",
            data={"billing_country": "MX"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    original = store.list_checkout_orders()[0]
    metadata = {
        "audit_id": audit_id,
        "plan": PLAN_SINGLE,
        "app": "rigor",
        "order_id": original.id,
    }
    good = _session(
        audit_id,
        sid="cs_market_mail_first",
        metadata=metadata,
        payment_intent="pi_market_mail_first",
    )
    held = _session(
        audit_id,
        sid="cs_market_mail_second",
        metadata=metadata,
        customer_details={"address": {"country": "US"}},
        payment_intent="pi_market_mail_second",
    )
    for session in (good, held, good, held):
        assert _webhook(client, session) == 200
    orders = {order.session_id: order for order in store.list_checkout_orders()}
    assert orders["cs_market_mail_first"].status == "delivered"
    assert orders["cs_market_mail_second"].status == "paid_review"
    with store.engine.connect() as conn:
        notices = conn.execute(store.email_outbox.select()).mappings().all()
    assert {(row["id"], row["kind"]) for row in notices} == {
        (original.id, "purchase"),
        (orders["cs_market_mail_second"].id, "market_review"),
    }
    assert all(row["email"] == account.email for row in notices)


def test_a_timeout_retries_with_the_same_persisted_idempotency_key(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    order_ids: list[str] = []

    def timeout(
        settings: AuditSettings,
        aid: str,
        tok: str,
        *,
        plan: str,
        locale: str,
        order_id: str,
        amount_cents: int,
    ) -> str:
        order_ids.append(order_id)
        if len(order_ids) == 1:
            raise TimeoutError("simulated Stripe timeout")
        return "https://checkout.stripe.test/recovered"

    client.app.state.checkout_factory = timeout
    path = f"/audits/{audit_id}/checkout?token={token}"
    with pytest.raises(TimeoutError):
        client.post(path, data={"billing_country": "MX"}, follow_redirects=False)
    retry = client.post(path, data={"billing_country": "MX"}, follow_redirects=False)
    assert retry.headers["location"] == "https://checkout.stripe.test/recovered"
    assert len(set(order_ids)) == 1


def test_checkout_pause_blocks_new_orders_but_paid_sessions_still_settle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIT_PAUSE_NEW_CHECKOUT", "true")
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    path = f"/audits/{audit_id}/checkout?token={token}"
    paused = client.post(path, follow_redirects=False)
    assert paused.status_code == 503
    assert not client.app.state.store.list_checkout_orders()
    assert _webhook(client, _session(audit_id, sid="cs_paid_during_pause")) == 200
    assert client.app.state.store.get_audit(audit_id).paid
    assert "class='lockbox'" not in client.get(f"/audits/{audit_id}?token={token}").text
    assert client.post(path, follow_redirects=False).status_code == 303


def test_paid_order_uses_frozen_price_after_a_setting_change(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    order = store.reserve_checkout(
        audit_id,
        account_id=store.account_for_audit(audit_id) or "",
        plan=PLAN_SINGLE,
        amount_cents=2900,
        currency="usd",
        at=NOW,
    )
    paid = _session(audit_id, sid="cs_price_frozen")
    paid["metadata"]["order_id"] = order.id
    more_expensive_setting = _settings(tmp_path, price_usd_cents=4900)
    assert fulfil(store, more_expensive_setting, paid, at=NOW) == audit_id
    assert "class='lockbox'" not in client.get(f"/audits/{audit_id}?token={token}").text


def test_pack_delivery_rolls_back_if_credit_grant_fails_then_recovers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    session = _session(audit_id, plan=PLAN_PACK, sid="cs_retry_after_db_failure")

    def fail_grant(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        if "INSERT INTO credit_grants" in statement:
            raise RuntimeError("simulated database failure")

    sa.event.listen(store.engine, "before_cursor_execute", fail_grant)
    try:
        with pytest.raises(RuntimeError, match="simulated database failure"):
            fulfil(store, _settings(tmp_path), session, at=NOW)
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", fail_grant)
    assert not store.get_audit(audit_id).paid
    assert store.list_checkout_orders() == []
    assert store.list_access_codes() == []
    assert fulfil(store, _settings(tmp_path), session, at=NOW) == audit_id
    assert "class='lockbox'" not in client.get(f"/audits/{audit_id}?token={token}").text


def test_two_paid_sessions_are_two_charges_but_one_delivery(tmp_path: Path) -> None:
    key = "k" * 40
    client = _client(tmp_path, admin_key=key)
    audit_id, token = _upload(client)
    first = _session(audit_id, plan=PLAN_PACK, sid="cs_first_pack")
    second = _session(audit_id, plan=PLAN_PACK, sid="cs_second_pack")
    assert _webhook(client, first) == 200
    assert _webhook(client, second) == 200
    assert _webhook(client, second) == 200
    store = client.app.state.store
    record = store.get_audit(audit_id)
    assert record.paid and record.stripe_session_id == "cs_first_pack"
    assert len(store.list_access_codes()) == 1
    orders = {order.session_id: order for order in store.list_checkout_orders()}
    assert set(orders) == {"cs_first_pack", "cs_second_pack"}
    assert orders["cs_first_pack"].status == "delivered"
    assert orders["cs_second_pack"].status == "duplicate"
    assert orders["cs_second_pack"].resolution == "manual_refund_review"
    returned = client.get(f"/audits/{audit_id}?token={token}&session_id=cs_second_pack")
    assert "segundo cobro" in returned.text
    panel = client.post("/panel", data={"key": key}).text
    assert "cs_first_pack" in panel and "cs_second_pack" in panel
    assert "cargo duplicado" in panel and "revisar reembolso manualmente" in panel
    counts = funnel.build(store.funnel_events(NOW.date().isoformat())).total.counts
    assert counts["purchases"] == 2
    assert counts["rights_sold"] == 3
    assert counts["gross_usd_cents"] == 13800


def test_two_paid_sessions_with_one_order_id_still_record_both_charges(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, _ = _upload(client)
    store = client.app.state.store
    order = store.reserve_checkout(
        audit_id,
        account_id=store.account_for_audit(audit_id) or "",
        plan=PLAN_PACK,
        amount_cents=6900,
        currency="usd",
        at=NOW,
    )
    first = _session(audit_id, plan=PLAN_PACK, sid="cs_same_order_first")
    second = _session(audit_id, plan=PLAN_PACK, sid="cs_same_order_second")
    first["metadata"]["order_id"] = order.id
    second["metadata"]["order_id"] = order.id
    store.attach_checkout_session(
        order.id,
        session_id=first["id"],
        checkout_url="https://checkout.stripe.test/same-order",
        expires_at=None,
    )
    assert _webhook(client, first) == 200
    assert _webhook(client, second) == 200
    assert _webhook(client, second) == 200
    orders = {item.session_id: item for item in store.list_checkout_orders()}
    assert len(orders) == 2
    assert orders[second["id"]].status == "duplicate"
    assert orders[second["id"]].resolution == "manual_refund_review"
    assert len(store.list_access_codes()) == 1


def test_a_preledger_paid_session_replay_is_reconciled_without_duplicate_charge(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    audit_id, _ = _upload(client)
    store = client.app.state.store
    assert store.mark_paid(audit_id, stripe_session_id="cs_legacy_paid", at=NOW)
    replay = _session(audit_id, plan=PLAN_PACK, sid="cs_legacy_paid")
    assert _webhook(client, replay) == 200
    assert _webhook(client, replay) == 200
    (order,) = store.list_checkout_orders()
    assert order.session_id == "cs_legacy_paid"
    assert order.status == "delivered"
    assert order.resolution == "legacy_reconciled"
    assert len(store.list_access_codes()) == 1
    assert store.get_access_code(pack_code(WEBHOOK_SECRET, "cs_legacy_paid")).credits_left == 2
    assert funnel.build(store.funnel_events(NOW.date().isoformat())).total.counts["purchases"] == 1


def test_preledger_pack_with_existing_code_is_backfilled_without_extra_credits(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    audit_id, _ = _upload(client)
    store = client.app.state.store
    session_id = "cs_legacy_existing_code"
    assert store.mark_paid(audit_id, stripe_session_id=session_id, at=NOW)
    code = pack_code(WEBHOOK_SECRET, session_id)
    assert store.ensure_access_code(code, credits=2, note="old pack", at=NOW)
    assert _webhook(client, _session(audit_id, plan=PLAN_PACK, sid=session_id)) == 200
    assert _webhook(client, _session(audit_id, plan=PLAN_PACK, sid=session_id)) == 200
    assert len(store.list_access_codes()) == 1
    assert store.get_access_code(code).credits_left == 2
    assert store.account_credits(store.account_for_audit(audit_id), datetime.now(UTC)) == 2


def test_historical_paid_session_survives_a_price_increase(tmp_path: Path) -> None:
    client = _client(tmp_path, price_usd_cents=4900, pack_price_usd_cents=9900)
    audit_id, _ = _upload(client)
    old_price = _session(audit_id, sid="cs_old_price", amount_total=2900)
    assert _webhook(client, old_price) == 200
    assert client.app.state.store.get_audit(audit_id).paid
    (order,) = client.app.state.store.list_checkout_orders()
    assert order.amount_cents == order.paid_amount_cents == 2900
    assert order.status == "delivered"


def test_pack_credits_can_unlock_when_manual_code_sales_are_off(tmp_path: Path) -> None:
    client = _client(tmp_path, access_codes=False)
    bought_id, bought_token = _upload(client)
    assert _webhook(client, _session(bought_id, plan=PLAN_PACK, sid="cs_credit_pack")) == 200
    assert client.get(f"/audits/{bought_id}?token={bought_token}").status_code == 200
    preview_id, preview_token = _upload(client)
    page = client.get(f"/audits/{preview_id}?token={preview_token}").text
    assert "crédito" in page.lower()
    csrf = re.search(r"name='csrf' value='([^']+)'", page)
    assert csrf is not None
    response = client.post(
        f"/audits/{preview_id}/credit?token={preview_token}",
        data={"csrf": csrf.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.app.state.store.get_audit(preview_id).paid
    owner = client.app.state.store.account_for_audit(preview_id)
    assert owner is not None
    assert client.app.state.store.account_credits(owner, datetime.now(UTC)) == 1


def test_return_from_stripe_unlocks_only_a_paid_session_for_this_audit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    other_id, _ = _upload(client)
    sessions: dict[str, dict[str, Any]] = {
        "cs_other": _session(other_id, sid="cs_other"),
        "cs_unpaid": {**_session(audit_id, sid="cs_unpaid"), "payment_status": "unpaid"},
        "cs_good": _session(audit_id, sid="cs_good"),
    }

    def lookup(settings: AuditSettings, session_id: str) -> dict[str, Any]:
        if session_id not in sessions:
            raise RuntimeError("stripe down")
        return sessions[session_id]

    client.app.state.session_lookup = lookup
    base = f"/audits/{audit_id}?token={token}"
    for sid in ("cs_other", "cs_unpaid", "cs_missing", "not_a_session"):
        page = client.get(f"{base}&session_id={sid}").text
        assert "Estamos confirmando tu pago" in page and "class='lockbox'" in page
    store = client.app.state.store
    assert not store.get_audit(audit_id).paid and not store.get_audit(other_id).paid

    paid = client.get(f"{base}&session_id=cs_good").text
    assert "Pago recibido" in paid and "class='lockbox'" not in paid
    assert find_claims(paid) == []
    assert client.get(f"/audits/{audit_id}.json?token={token}").status_code == 200


def test_cancelled_checkout_says_nothing_was_charged(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    page = client.get(f"/audits/{audit_id}?token={token}&pay=cancelled&lang=en").text
    assert "nothing was charged" in page and "class='lockbox'" in page


def test_pack_paid_by_card_shows_a_code_that_unlocks_two_more_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Four uploads: more than a month's free previews, which is not what this checks.
    monkeypatch.setattr(accounts, "FREE_PREVIEWS_PER_MONTH", 10)
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    session = _session(audit_id, plan=PLAN_PACK, sid="cs_pack_1")
    assert _webhook(client, session) == 200
    assert _webhook(client, session) == 200  # Stripe retries: still one code
    store = client.app.state.store
    assert len(store.list_access_codes()) == 1

    code = pack_code(WEBHOOK_SECRET, "cs_pack_1")
    report = f"/audits/{audit_id}?token={token}"
    page = client.get(report).text
    assert "class='lockbox'" not in page
    assert code in page and "Te quedan 2 informes" in page
    assert find_claims(page) == []

    for expected_left in (1, 0):
        next_id, next_token = _upload(client)
        redeemed = client.post(f"/audits/{next_id}/redeem?token={next_token}", data={"code": code})
        assert redeemed.status_code == 200 and "class='lockbox'" not in redeemed.text
        assert store.get_access_code(code).credits_left == expected_left
    assert "Ya usaste los informes de tu paquete" in client.get(report).text
    # A code never shows on a report bought one at a time.
    single_id, single_token = _upload(client)
    assert _webhook(client, _session(single_id, sid="cs_single")) == 200
    single = client.get(f"/audits/{single_id}?token={single_token}").text
    assert "AUD-" not in single


def test_legal_pages_name_stripe_and_explain_the_card_pack(tmp_path: Path) -> None:
    client = _client(tmp_path)
    terms = client.get("/terminos").text
    assert "Stripe" in terms and "código con 2 créditos" in terms
    assert "lee mal tu archivo" in terms
    card_only = _client(tmp_path / "c", access_codes=False)
    terms_en = card_only.get("/terms").text
    assert "code with 2 credits" in terms_en and "misreads your file" in terms_en
    for page in (terms, terms_en, client.get("/privacidad").text):
        assert find_claims(page) == []


# -- test mode never unlocks a real report ---------------------------------------
def test_a_test_mode_key_offers_no_card_and_a_test_payment_unlocks_nothing(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, stripe_secret_key="sk_test_x")
    audit_id, token = _upload(client)
    health = client.get("/health").json()
    assert health["card_mode"] == "test" and health["card_via"] == "checkout"
    page = client.get(f"/audits/{audit_id}?token={token}").text
    assert "name='plan'" not in page and "wa.me" in page  # codes and WhatsApp still work
    assert client.post(f"/audits/{audit_id}/checkout?token={token}").status_code == 503
    assert "Stripe" not in client.get("/terminos").text  # not offered to the public
    # Stripe's public test card pays a test checkout: that alone unlocks nothing.
    assert _webhook(client, _session(audit_id, livemode=False)) == 200
    assert not client.app.state.store.get_audit(audit_id).paid


def test_a_listed_test_audit_can_be_paid_in_test_mode(tmp_path: Path) -> None:
    settings = _settings(tmp_path, stripe_secret_key="sk_test_x")
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    audit_id, _ = _upload(client)
    other_id, _ = _upload(client)
    listed = _settings(tmp_path, stripe_secret_key="sk_test_x", stripe_test_audits={audit_id})
    listed_client = signed_in(TestClient(create_app(listed, make_store(listed.database_url))))
    assert listed.card_for(audit_id) and not listed.card_for(other_id)
    assert _webhook(listed_client, _session(audit_id, livemode=False)) == 200
    assert _webhook(listed_client, _session(other_id, sid="cs_2", livemode=False)) == 200
    store = listed_client.app.state.store
    assert store.get_audit(audit_id).paid and not store.get_audit(other_id).paid


# -- Payment Links: no secret key on the service ------------------------------------
LINKS = {
    "stripe_secret_key": "",
    "stripe_link_single": "https://buy.stripe.com/abc123",
    "stripe_link_pack": "https://buy.stripe.com/pack456",
    "allow_legacy_payment_links": True,
}


def test_payment_links_from_env_need_the_webhook_secret() -> None:
    env = {
        "STRIPE_WEBHOOK_SECRET": "whsec_x",
        "STRIPE_PAYMENT_LINK_SINGLE": "https://buy.stripe.com/abc",
        "STRIPE_PAYMENT_LINK_PACK": "https://buy.stripe.com/def",
        "AUDIT_FREE_MODE": "false",
        "AUDIT_STRIPE_TEST_AUDITS": "a1, a2",
        "AUDIT_LEGACY_PAYMENT_LINKS_ENABLED": "true",
    }
    settings = AuditSettings.from_env(env)
    assert settings.links_enabled and not settings.stripe_enabled
    assert card_mode(settings) == "live" and not settings.card_public
    assert settings.stripe_test_audits == frozenset({"a1", "a2"})
    no_secret = AuditSettings.from_env({**env, "STRIPE_WEBHOOK_SECRET": ""})
    assert not no_secret.links_enabled and no_secret.free_mode
    not_stripe = AuditSettings.from_env({**env, "STRIPE_PAYMENT_LINK_SINGLE": "https://x.io/a"})
    assert not not_stripe.links_enabled
    test_links = AuditSettings.from_env(
        {**env, "STRIPE_PAYMENT_LINK_SINGLE": "https://buy.stripe.com/test_abc"}
    )
    assert card_mode(test_links) == "test" and not test_links.card_public


def test_payment_links_are_off_by_default_but_historical_webhooks_still_work(
    tmp_path: Path,
) -> None:
    disabled = AuditSettings.from_env(
        {
            "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET,
            "STRIPE_PAYMENT_LINK_SINGLE": "https://buy.stripe.com/abc",
            "AUDIT_FREE_MODE": "false",
        }
    )
    assert disabled.links_configured and not disabled.links_enabled
    client = _client(tmp_path, stripe_secret_key="", stripe_link_single="", access_codes=True)
    audit_id, _ = _upload(client)
    assert _webhook(client, _session(audit_id, sid="cs_old_link")) == 200
    assert client.app.state.store.get_audit(audit_id).paid


def test_payment_link_tags_append_to_an_existing_query() -> None:
    settings = AuditSettings(
        stripe_link_single=(
            "https://buy.stripe.com/abc?prefilled_email=a%40b"
            "&client_reference_id=stale&locale=pt#old-fragment"
        ),
        stripe_link_pack="https://buy.stripe.com/pack?promo=1",
        access_codes=True,
        free_mode=False,
    )
    single, pack = payment_link_urls(settings, "report123", "es")
    assert parse_qs(urlsplit(single).query) == {
        "prefilled_email": ["a@b"],
        "client_reference_id": ["report123"],
        "locale": ["es"],
    }
    assert parse_qs(urlsplit(pack).query)["client_reference_id"] == ["report123"]
    assert urlsplit(single).fragment == ""
    pt_single, pt_pack = payment_link_urls(settings, "report123", "pt")
    assert pt_single == (
        "https://buy.stripe.com/abc?prefilled_email=a%40b&client_reference_id=report123"
        "&locale=pt-BR"
    )
    assert pt_pack == (
        "https://buy.stripe.com/pack?promo=1&client_reference_id=report123&locale=pt-BR"
    )


def test_historical_links_are_hidden_but_the_webhook_still_unlocks_them(tmp_path: Path) -> None:
    client = _client(tmp_path, **LINKS)
    audit_id, token = _upload(client)
    assert client.get("/health").json()["card_via"] == "links"
    page = client.get(f"/audits/{audit_id}?token={token}").text
    single = f"https://buy.stripe.com/abc123?client_reference_id={audit_id}&amp;locale=es"
    pack = f"https://buy.stripe.com/pack456?client_reference_id={audit_id}&amp;locale=es"
    assert single not in page and pack not in page
    assert "Ya pagué: ver mi informe" not in page
    assert "wa.me" in page and "name='code'" in page
    assert find_claims(page) == []
    # No Checkout session is ever created in this mode.
    assert client.post(f"/audits/{audit_id}/checkout?token={token}").status_code == 503

    waiting = client.get(f"/audits/{audit_id}?token={token}&pay=done").text
    assert "Estamos confirmando tu pago" in waiting
    link_session = {
        "id": "cs_live_link",
        "payment_status": "paid",
        "livemode": True,
        "client_reference_id": audit_id,
        "currency": "usd",
        "amount_total": 6900,
        "metadata": {"plan": PLAN_PACK, "app": "rigor"},
    }
    assert _webhook(client, link_session) == 200
    done = client.get(f"/audits/{audit_id}?token={token}&pay=done").text
    assert "Pago recibido" in done and "class='lockbox'" not in done
    assert pack_code(WEBHOOK_SECRET, "cs_live_link") in done


def test_test_mode_links_are_shown_only_on_listed_audits(tmp_path: Path) -> None:
    test_links = {**LINKS, "stripe_link_single": "https://buy.stripe.com/test_abc"}
    client = _client(tmp_path, **test_links)
    audit_id, token = _upload(client)
    assert "buy.stripe.com" not in client.get(f"/audits/{audit_id}?token={token}").text
    assert "Stripe" not in client.get("/").text.split("id='pricing'")[-1]
    listed = _client(tmp_path, **test_links, stripe_test_audits={audit_id})
    assert "buy.stripe.com/test_abc" in listed.get(f"/audits/{audit_id}?token={token}").text


# -- only a full-price payment from Rigor's own links unlocks -------------------
@pytest.mark.parametrize(
    "change",
    [
        {"amount_total": 100},  # a USD 1 link
        {"amount_total": 0, "payment_status": "no_payment_required"},  # 100% off
        {"currency": "mxn"},  # 2900 of another currency
        {"amount_total": None},
        {"amount_total": "2900"},
        {"metadata": {"plan": PLAN_SINGLE}},  # another link or app on the account
        {"metadata": {"plan": PLAN_SINGLE, "app": "other"}},
    ],
)
def test_a_session_that_is_not_a_full_rigor_payment_unlocks_nothing(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    session = {**_session(audit_id), "client_reference_id": audit_id, **change}
    assert _webhook(client, session) == 200
    assert "class='lockbox'" in client.get(f"/audits/{audit_id}?token={token}").text


def test_a_single_report_price_never_grants_a_pack(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    audit_id, _ = _upload(client)
    store = client.app.state.store
    cheap_pack = _session(audit_id, plan=PLAN_PACK, amount_total=PAID[PLAN_SINGLE])
    assert fulfil(store, settings, cheap_pack, at=NOW) is None
    assert not store.get_audit(audit_id).paid and store.list_access_codes() == []
    assert fulfil(store, settings, _session(audit_id, plan=PLAN_PACK), at=NOW) == audit_id
    assert len(store.list_access_codes()) == 1


def test_a_payment_in_the_buyers_currency_unlocks_by_its_usd_amount(tmp_path: Path) -> None:
    """Adaptive Pricing: a buyer in Mexico pays in MXN for a USD price."""
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    presented = {"presentment_amount": 52900, "presentment_currency": "mxn"}
    assert _webhook(client, _session(audit_id, presentment_details=presented)) == 200
    assert "class='lockbox'" not in client.get(f"/audits/{audit_id}?token={token}").text

    legacy_id, legacy_token = _upload(client)
    converted = {"source_currency": "usd", "amount_total": 2900}
    legacy = _session(
        legacy_id,
        sid="cs_legacy",
        currency="mxn",
        amount_total=52900,
        currency_conversion=converted,
    )
    assert _webhook(client, legacy) == 200
    assert "class='lockbox'" not in client.get(f"/audits/{legacy_id}?token={legacy_token}").text

    short_id, short_token = _upload(client)
    short = {**converted, "amount_total": 100}
    cheap = _session(
        short_id, sid="cs_short", currency="mxn", amount_total=52900, currency_conversion=short
    )
    assert _webhook(client, cheap) == 200
    assert "class='lockbox'" in client.get(f"/audits/{short_id}?token={short_token}").text


def test_a_refused_paid_session_leaves_a_log_line_without_amounts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = _client(tmp_path)
    audit_id, _ = _upload(client)
    with caplog.at_level("WARNING", logger="quant_trade.audit.payments"):
        assert _webhook(client, _session(audit_id, amount_total=100)) == 200
        assert _webhook(client, _session("x\ny", sid="cs_2")) == 200
    lines = [r.getMessage() for r in caplog.records]
    assert any("cs_test_1" in line and audit_id in line and "below" in line for line in lines)
    assert any("xy" in line and "unknown audit" in line for line in lines)
    assert not any("\n" in line for line in lines)


# -- refused live payments show on /panel --------------------------------------
def test_a_charged_live_payment_that_unlocks_nothing_shows_on_the_panel(tmp_path: Path) -> None:
    key = "k" * 40
    client = _client(tmp_path, admin_key=key, stripe_test_audits=frozenset({"listed"}))
    audit_id, _ = _upload(client)
    assert _webhook(client, _session(audit_id, amount_total=100)) == 200
    assert _webhook(client, _session(audit_id, amount_total=100)) == 200  # a retry, once
    assert _webhook(client, _session("gone", sid="cs_gone")) == 200
    # Test payments stay in the log only: anyone can pay a test link.
    assert _webhook(client, _session("x", sid="cs_test_x", livemode=False)) == 200
    store = client.app.state.store
    refused = store.list_refused_payments()
    assert {(r.session_id, r.audit_id, r.reason) for r in refused} == {
        ("cs_test_1", audit_id, "below the plan price"),
        ("cs_gone", "gone", "unknown audit"),
    }
    page = client.post("/panel", data={"key": key}).text
    assert "Pagos con tarjeta que no abrieron un informe" in page
    assert "cs_gone" in page and "pagó menos que el precio" in page
    assert "cs_test_x" not in page
    assert store.list_checkout_orders() == []
    assert find_claims(page) == []

    later = datetime.now(UTC) + timedelta(days=400)
    store.purge_expired(later, retention_days=30)
    assert store.list_refused_payments() == []


def test_every_refusal_reason_has_a_spanish_panel_label() -> None:
    import inspect
    import re

    from quant_trade.audit import payments
    from quant_trade.audit.owner import REFUSAL_REASONS

    source = inspect.getsource(payments.refusal) + inspect.getsource(payments.fulfil)
    reasons = set(re.findall(r'(?:reason = |return )"([a-zA-Z ]+)"', source))
    assert reasons and reasons <= set(REFUSAL_REASONS)


def test_the_return_page_cannot_be_looped_to_use_up_stripe_lookups(tmp_path: Path) -> None:
    from quant_trade.audit.payments import CARD_LOOKUPS_PER_HOUR

    client = _client(tmp_path)
    audit_id, token = _upload(client)
    calls: list[str] = []

    def lookup(settings: AuditSettings, session_id: str) -> dict[str, Any]:
        calls.append(session_id)
        if session_id == "cs_good":
            return _session(audit_id, sid="cs_good")
        return {**_session(audit_id, sid=session_id), "payment_status": "unpaid"}

    client.app.state.session_lookup = lookup
    base = f"/audits/{audit_id}?token={token}"
    for _ in range(5):  # the same session that did not unlock is asked once
        client.get(f"{base}&session_id=cs_unpaid")
    assert calls == ["cs_unpaid"]
    for n in range(30):  # new ids stop at the hourly limit for this audit
        client.get(f"{base}&session_id=cs_loop_{n}")
    assert len(calls) == CARD_LOOKUPS_PER_HOUR
    # The webhook still unlocks the report without any lookup.
    assert _webhook(client, _session(audit_id, sid="cs_good")) == 200
    assert "class='lockbox'" not in client.get(base).text
    assert len(calls) == CARD_LOOKUPS_PER_HOUR


def test_a_sale_from_another_app_is_not_listed_on_the_panel(tmp_path: Path) -> None:
    client = _client(tmp_path)
    other_sale = {
        "id": "cs_other_app",
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": 5000,
        "metadata": {},
    }
    assert _webhook(client, other_sale) == 200
    marked = {**other_sale, "id": "cs_marked", "metadata": {"app": "rigor"}}
    assert _webhook(client, marked) == 200
    listed = [r.session_id for r in client.app.state.store.list_refused_payments()]
    assert listed == ["cs_marked"]
