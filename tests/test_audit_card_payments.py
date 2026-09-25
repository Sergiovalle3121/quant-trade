"""Card payments through Stripe Checkout, single audit and pack; Stripe is mocked."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from audit_fixtures import csv_bytes, positive_drift  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.payments import (  # noqa: E402
    PLAN_PACK,
    PLAN_SINGLE,
    card_mode,
    checkout_params,
    fulfil,
    pack_code,
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
}
NOW = datetime(2026, 9, 25, tzinfo=UTC)


def _settings(tmp_path: Path, **overrides: Any) -> AuditSettings:
    values = {**SELLING, **overrides}
    return AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **values
    )


def _client(tmp_path: Path, **overrides: Any) -> TestClient:
    settings = _settings(tmp_path, **overrides)
    return TestClient(create_app(settings, make_store(settings.database_url)))


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
    client = TestClient(create_app(settings, make_store(settings.database_url)))
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
    seen: list[tuple[str, str]] = []

    def fake(settings: AuditSettings, aid: str, tok: str, *, plan: str, locale: str) -> str:
        seen.append((plan, locale))
        return "https://checkout.stripe.test/s"

    client.app.state.checkout_factory = fake
    url = f"/audits/{audit_id}/checkout?token={token}&lang=en"
    for plan in ("pack", "single", "gift"):
        response = client.post(url, data={"plan": plan}, follow_redirects=False)
        assert response.headers["location"] == "https://checkout.stripe.test/s"
    assert seen == [("pack", "en"), ("single", "en"), ("single", "en")]

    no_pack = _client(tmp_path / "b", pack_price_usd_cents=0)
    aid, tok = _upload(no_pack)
    no_pack.app.state.checkout_factory = fake
    no_pack.post(f"/audits/{aid}/checkout?token={tok}", data={"plan": "pack"})
    assert seen[-1] == ("single", "es")
    assert "name='plan' value='pack'" not in no_pack.get(f"/audits/{aid}?token={tok}").text


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


def test_pack_paid_by_card_shows_a_code_that_unlocks_two_more_reports(tmp_path: Path) -> None:
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
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    audit_id, _ = _upload(client)
    other_id, _ = _upload(client)
    listed = _settings(tmp_path, stripe_secret_key="sk_test_x", stripe_test_audits={audit_id})
    listed_client = TestClient(create_app(listed, make_store(listed.database_url)))
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
}


def test_payment_links_from_env_need_the_webhook_secret() -> None:
    env = {
        "STRIPE_WEBHOOK_SECRET": "whsec_x",
        "STRIPE_PAYMENT_LINK_SINGLE": "https://buy.stripe.com/abc",
        "STRIPE_PAYMENT_LINK_PACK": "https://buy.stripe.com/def",
        "AUDIT_FREE_MODE": "false",
        "AUDIT_STRIPE_TEST_AUDITS": "a1, a2",
    }
    settings = AuditSettings.from_env(env)
    assert settings.links_enabled and not settings.stripe_enabled
    assert card_mode(settings) == "live" and settings.card_public
    assert settings.stripe_test_audits == frozenset({"a1", "a2"})
    no_secret = AuditSettings.from_env({**env, "STRIPE_WEBHOOK_SECRET": ""})
    assert not no_secret.links_enabled and no_secret.free_mode
    not_stripe = AuditSettings.from_env({**env, "STRIPE_PAYMENT_LINK_SINGLE": "https://x.io/a"})
    assert not not_stripe.links_enabled
    test_links = AuditSettings.from_env(
        {**env, "STRIPE_PAYMENT_LINK_SINGLE": "https://buy.stripe.com/test_abc"}
    )
    assert card_mode(test_links) == "test" and not test_links.card_public


def test_report_links_carry_the_audit_and_the_webhook_unlocks_it(tmp_path: Path) -> None:
    client = _client(tmp_path, **LINKS)
    audit_id, token = _upload(client)
    assert client.get("/health").json()["card_via"] == "links"
    page = client.get(f"/audits/{audit_id}?token={token}").text
    single = f"https://buy.stripe.com/abc123?client_reference_id={audit_id}&amp;locale=es"
    pack = f"https://buy.stripe.com/pack456?client_reference_id={audit_id}&amp;locale=es"
    assert single in page and pack in page
    assert "Ya pagué: ver mi informe" in page and "&amp;pay=done" in page
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
    client = TestClient(create_app(settings, make_store(settings.database_url)))
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
    assert "cs_test_x" not in page and "2900" not in page
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
