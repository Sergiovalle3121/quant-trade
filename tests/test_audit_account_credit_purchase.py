"""Buying credits by card from "My account"; Stripe is simulated by the HMAC helper."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from audit_fixtures import signed_in  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, account_pt  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.payments import (  # noqa: E402
    ACCOUNT_PATHS,
    PLAN_PACK,
    PLAN_SINGLE,
    account_checkout_params,
    credit_code,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import account_order_ref, make_store  # noqa: E402
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
    "approved_markets": frozenset({"MX", "US"}),
}
PAID = {PLAN_SINGLE: 2900, PLAN_PACK: 6900}


def _settings(tmp_path: Path, **overrides: Any) -> AuditSettings:
    return AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        **{**SELLING, **overrides},
    )


def _client(tmp_path: Path, **overrides: Any) -> tuple[TestClient, list[dict[str, Any]]]:
    settings = _settings(tmp_path, **overrides)
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    calls: list[dict[str, Any]] = []

    def fake(cfg: AuditSettings, account_id: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"account_id": account_id, **kwargs})
        return {
            "id": f"cs_live_{len(calls)}",
            "url": f"https://checkout.stripe.test/{len(calls)}",
            "expires_at": int(time.time()) + 3600,
        }

    client.app.state.account_checkout_factory = fake
    return client, calls


def _account_id(client: TestClient, email: str = "tester@example.com") -> str:
    account = client.app.state.store.find_account(email)
    assert account is not None
    return account.id


def _csrf(client: TestClient) -> str:
    match = re.search(r"name='csrf' value='([^']+)'", client.get("/cuenta").text)
    assert match
    return match.group(1)


def _buy(client: TestClient, **fields: str) -> Any:
    data = {"csrf": _csrf(client), "billing_country": "MX", "final_sale": "yes", **fields}
    return client.post("/cuenta/comprar", data=data, follow_redirects=False)


def _session(
    account_id: str, order_id: str, *, plan: str = PLAN_SINGLE, sid: str = "cs_live_1", **extra: Any
) -> dict[str, Any]:
    return {
        "id": sid,
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": PAID[plan],
        "customer_details": {"address": {"country": "MX"}},
        "metadata": {
            "account_id": account_id,
            "plan": plan,
            "order_id": order_id,
            "app": "rigor",
        },
        **extra,
    }


def _webhook(client: TestClient, session: dict[str, Any]) -> int:
    event = json.dumps({"type": "checkout.session.completed", "data": {"object": session}})
    header = sign_stripe_payload(event.encode(), WEBHOOK_SECRET, timestamp=int(time.time()))
    return client.post(
        "/webhooks/stripe", content=event, headers={"stripe-signature": header}
    ).status_code


def _order_id(client: TestClient) -> str:
    orders = client.app.state.store.list_checkout_orders()
    assert orders
    return orders[0].id


def _credits(client: TestClient, account_id: str) -> int:
    return client.app.state.store.account_credits(account_id, datetime.now(UTC))


def test_my_account_offers_card_buttons_with_the_final_sale_box(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    for url, words in (
        ("/cuenta", ("Comprar 1 informe · USD 29", "Comprar paquete de 3 · USD 69")),
        ("/account", ("Buy 1 report · USD 29", "Buy the pack of 3 · USD 69")),
        ("/pt/conta", ("Comprar 1 relatório · USD 29", "Comprar pacote de 3 · USD 69")),
    ):
        page = client.get(url).text
        assert "/comprar'" in page
        assert "name='final_sale' value='yes' required" in page
        assert "name='billing_country' required" in page
        for word in words:
            assert word in page
        assert find_claims(page) == []
    page = client.get("/cuenta").text
    assert "<option value='MX'>México</option>" in page
    assert "<option value='US'>Estados Unidos</option>" in page
    # WhatsApp stays, as the alternative.
    assert "¿Prefieres pagar por WhatsApp?" in page


def test_no_card_buttons_in_test_mode_or_without_markets(tmp_path: Path) -> None:
    client, calls = _client(tmp_path, stripe_secret_key="sk_test_x")
    assert "/cuenta/comprar" not in client.get("/cuenta").text
    response = _buy(client)
    assert response.status_code == 303 and "error=buy_off" in response.headers["location"]
    assert calls == []

    other, _ = _client(tmp_path / "b", approved_markets=frozenset())
    assert "/cuenta/comprar" not in other.get("/cuenta").text


def test_buying_needs_the_box_a_country_and_a_session(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)
    no_box = _buy(client, final_sale="")
    assert "error=buy_final_sale_needed" in no_box.headers["location"]
    no_country = _buy(client, billing_country="BR")
    assert "error=buy_market" in no_country.headers["location"]
    assert calls == []
    assert (
        "Marca la casilla de compra no reembolsable"
        in client.get("/cuenta?error=buy_final_sale_needed").text
    )
    # A stranger's form without the session's CSRF token buys nothing.
    forged = client.post(
        "/cuenta/comprar",
        data={"csrf": "x", "billing_country": "MX", "final_sale": "yes"},
        follow_redirects=False,
    )
    assert "error=csrf" in forged.headers["location"] and calls == []
    anonymous = TestClient(client.app).post(
        "/cuenta/comprar", data={"billing_country": "MX"}, follow_redirects=False
    )
    assert anonymous.status_code == 303
    assert anonymous.headers["location"].startswith("/entrar")


def test_a_paid_single_puts_one_credit_on_the_account_once(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)
    account_id = _account_id(client)
    before = _credits(client, account_id)
    response = _buy(client)
    assert response.headers["location"] == "https://checkout.stripe.test/1"
    (call,) = calls
    assert call["account_id"] == account_id and call["plan"] == PLAN_SINGLE
    assert call["amount_cents"] == 2900
    order_id = call["order_id"]
    store = client.app.state.store
    order = store.get_checkout_order(order_id)
    assert order.audit_id == account_order_ref(account_id)
    assert store.final_sale_acceptance(order_id) is not None
    # A second click reuses the open Checkout session.
    assert _buy(client).headers["location"] == "https://checkout.stripe.test/1"
    assert len(calls) == 1

    session = _session(account_id, order_id)
    assert _webhook(client, session) == 200
    assert _credits(client, account_id) == before + 1
    # Stripe retries the event: still one credit.
    assert _webhook(client, session) == 200
    assert _credits(client, account_id) == before + 1
    assert store.get_checkout_order(order_id).status == "delivered"
    # The code is linked to the account; nobody has to type it.
    assert store.code_id(credit_code(WEBHOOK_SECRET, "cs_live_1")) is not None


def test_a_paid_pack_puts_three_credits_on_the_account(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)
    account_id = _account_id(client)
    before = _credits(client, account_id)
    _buy(client, plan=PLAN_PACK)
    assert calls[0]["plan"] == PLAN_PACK and calls[0]["amount_cents"] == 6900
    session = _session(account_id, calls[0]["order_id"], plan=PLAN_PACK)
    assert _webhook(client, session) == 200
    assert _credits(client, account_id) == before + 3


def test_refused_credit_payments_grant_nothing(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)
    account_id = _account_id(client)
    before = _credits(client, account_id)
    _buy(client)
    order_id = calls[0]["order_id"]
    store = client.app.state.store
    # Test mode, a cheaper amount, another account, a missing marker, an
    # unknown order and another billing country: none of them grant a credit.
    for session in (
        _session(account_id, order_id, livemode=False),
        _session(account_id, order_id, amount_total=100),
        _session("0" * 32, order_id),
        {**_session(account_id, order_id), "metadata": {"account_id": account_id}},
        _session(account_id, "f" * 32),
        _session(account_id, order_id, customer_details={"address": {"country": "US"}}),
    ):
        assert _webhook(client, session) == 200
        assert _credits(client, account_id) == before
    assert store.get_checkout_order(order_id).status == "paid_review"
    # The held order blocks a second purchase until the owner resolves it.
    assert "error=buy_review" in _buy(client).headers["location"]


def test_a_credit_order_never_unlocks_a_report(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)
    account_id = _account_id(client)
    _buy(client)
    order_id = calls[0]["order_id"]
    # The same order presented as a report purchase is refused.
    session = _session(account_id, order_id)
    session["metadata"] = {
        "audit_id": "a" * 32,
        "plan": PLAN_SINGLE,
        "order_id": order_id,
        "app": "rigor",
    }
    assert _webhook(client, session) == 200
    assert client.app.state.store.get_checkout_order(order_id).status != "delivered"


def test_the_card_paid_flash_and_the_checkout_params(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert "Pago recibido." in client.get("/cuenta?done=card_paid").text
    settings = _settings(tmp_path)
    params = account_checkout_params(
        settings, "ab" * 16, plan=PLAN_PACK, locale="pt", order_id="o1", amount_cents=6900
    )
    assert params["metadata"] == {
        "account_id": "ab" * 16,
        "plan": PLAN_PACK,
        "order_id": "o1",
        "app": "rigor",
    }
    assert "audit_id" not in params["metadata"]
    assert params["success_url"] == "https://rigor.example/pt/conta?done=card_paid"
    assert params["billing_address_collection"] == "required"
    (line,) = params["line_items"]
    assert line["price_data"]["unit_amount"] == 6900
    assert {
        "es": account_pages.PATHS["es"]["account"],
        "en": account_pages.PATHS["en"]["account"],
        "pt": account_pt.PATHS_PT["account"],
    } == ACCOUNT_PATHS


def test_the_credit_texts_exist_in_every_language() -> None:
    keys = ("buy_card_single", "buy_card_pack", "buy_final_sale", "card_paid", "buy_review")
    for copy in (account_pages.COPY["es"], account_pages.COPY["en"], account_pt.COPY_PT):
        for key in keys:
            assert copy[key] and find_claims(copy[key]) == []


def test_an_account_deleted_before_the_webhook_gets_no_credits(tmp_path: Path) -> None:
    client, calls = _client(tmp_path)
    account_id = _account_id(client)
    _buy(client)
    order_id = calls[0]["order_id"]
    store = client.app.state.store
    store.delete_account(account_id)
    assert _webhook(client, _session(account_id, order_id)) == 200
    assert store.get_checkout_order(order_id).status != "delivered"
    assert store.account_codes_list(account_id) == []
