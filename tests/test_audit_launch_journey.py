"""Offline customer journey across the three public languages and fake Stripe."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from audit_fixtures import csv_bytes, positive_drift  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, funnel  # noqa: E402
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app, sign_stripe_payload  # noqa: E402

_CSRF = re.compile(r"name='csrf' value='([^']+)'")
_INVITE_URL = re.compile(r"id='invite-link'[^>]*value='([^']+)'")
_PASSWORD = "a long private phrase for this test"


def _signup(client: TestClient, locale: str, email: str, *, invite: str = "") -> None:
    path = account_pages.path("signup", locale)
    page = client.get(path + (f"?invita={invite}" if invite else ""))
    assert page.status_code == 200
    csrf = _CSRF.search(page.text)
    assert csrf is not None
    created = client.post(
        path,
        data={"email": email, "password": _PASSWORD, "csrf": csrf.group(1), "invite": invite},
        follow_redirects=False,
    )
    assert created.status_code == 303


def _upload(client: TestClient, locale: str, seed: int) -> tuple[str, str]:
    response = client.post(
        "/audits",
        files={
            "equity": (f"journey-{seed}.csv", csv_bytes(positive_drift(500, seed=seed)), "text/csv")
        },
        data={"trials": "3", "cost_bps": "5", "consent": "on", "locale": locale},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    return location.path.rsplit("/", 1)[1], parse_qs(location.query)["token"][0]


def _redeem_credit(client: TestClient, audit_id: str, token: str, locale: str) -> None:
    path = f"/audits/{audit_id}?token={token}&lang={locale}"
    page = client.get(path)
    csrf = _CSRF.search(page.text)
    assert csrf is not None
    result = client.post(
        f"/audits/{audit_id}/credit?token={token}&lang={locale}",
        data={"csrf": csrf.group(1)},
        follow_redirects=False,
    )
    assert result.status_code == 303


@pytest.fixture
def confirmed_emails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invites pay only between confirmed addresses; mail is covered elsewhere."""
    from quant_trade.audit.store import Store

    monkeypatch.setattr(Store, "email_verified", lambda self, account_id: True)


@pytest.mark.parametrize("locale,home", [("es", "/"), ("en", "/en"), ("pt", "/pt")])
@pytest.mark.usefixtures("confirmed_emails")
def test_registration_referral_checkout_credit_pdf_and_help(
    tmp_path: Path, locale: str, home: str
) -> None:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://rigor.example",
        free_mode=False,
        access_codes=False,
        stripe_secret_key="sk_live_test",
        stripe_webhook_secret="whsec_journey",
        approved_markets=frozenset({"MX"}),
        contact_url="https://wa.me/5200000000",
    )
    store = make_store(settings.database_url)
    app = create_app(settings, store)
    owner = TestClient(app, base_url="https://rigor.example")
    _signup(owner, locale, f"owner-{locale}@example.com")
    owner_account = store.find_account(f"owner-{locale}@example.com")
    assert owner_account is not None

    welcome_id, welcome_token = _upload(owner, locale, 101)
    assert store.get_audit(welcome_id).paid
    assert store.get_audit(welcome_id).stripe_session_id.startswith("welcome:")
    assert owner.get(f"/audits/{welcome_id}?token={welcome_token}&lang={locale}").status_code == 200

    account_page = owner.get(account_pages.path("account", locale)).text
    invite_match = _INVITE_URL.search(account_page)
    assert invite_match is not None
    invite_url = invite_match.group(1)
    assert "?token=" not in invite_url
    invite = parse_qs(urlsplit(invite_url).query)["invita"][0]
    friend = TestClient(app, base_url="https://rigor.example")
    _signup(friend, locale, f"friend-{locale}@example.com", invite=invite)
    friend_id, _ = _upload(friend, locale, 102)
    assert store.get_audit(friend_id).paid
    assert store.invite_summary(owner_account.id, datetime.now(UTC)).credited == 1
    assert store.account_credits(owner_account.id, datetime.now(UTC)) == 1

    referral_id, referral_token = _upload(owner, locale, 103)
    assert not store.get_audit(referral_id).paid
    _redeem_credit(owner, referral_id, referral_token, locale)
    assert store.get_audit(referral_id).paid
    assert store.get_audit(referral_id).stripe_session_id.startswith("code:")
    assert store.account_credits(owner_account.id, datetime.now(UTC)) == 0

    priced_id, priced_token = _upload(owner, locale, 104)
    assert not store.get_audit(priced_id).paid
    session_id = f"cs_journey_{locale}"
    observed: list[tuple[str, int]] = []

    def fake_checkout(
        cfg: AuditSettings,
        audit_id: str,
        token: str,
        *,
        plan: str,
        locale: str,
        order_id: str,
        amount_cents: int,
    ) -> dict[str, Any]:
        observed.append((order_id, amount_cents))
        assert audit_id == priced_id and token == priced_token and plan == "pack"
        return {"id": session_id, "url": "https://checkout.stripe.test/journey"}

    app.state.checkout_factory = fake_checkout
    checkout = owner.post(
        f"/audits/{priced_id}/checkout?token={priced_token}&lang={locale}",
        data={"plan": "pack", "billing_country": "MX", "final_sale": "yes"},
        follow_redirects=False,
    )
    assert checkout.status_code == 303
    assert checkout.headers["location"] == "https://checkout.stripe.test/journey"
    assert len(observed) == 1 and observed[0][1] == 6900
    paid = {
        "id": session_id,
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": 6900,
        "customer_details": {"address": {"country": "MX"}},
        "metadata": {
            "audit_id": priced_id,
            "plan": "pack",
            "app": "rigor",
            "order_id": observed[0][0],
        },
    }
    event = json.dumps({"type": "checkout.session.completed", "data": {"object": paid}})
    signature = sign_stripe_payload(
        event.encode(), settings.stripe_webhook_secret, timestamp=int(time.time())
    )
    assert (
        owner.post(
            "/webhooks/stripe", content=event, headers={"stripe-signature": signature}
        ).status_code
        == 200
    )
    assert store.get_audit(priced_id).paid
    assert store.account_credits(owner_account.id, datetime.now(UTC)) == 2
    assert (
        "class='lockbox'"
        not in owner.get(f"/audits/{priced_id}?token={priced_token}&lang={locale}").text
    )

    credit_id, credit_token = _upload(owner, locale, 105)
    assert not store.get_audit(credit_id).paid
    _redeem_credit(owner, credit_id, credit_token, locale)
    assert store.get_audit(credit_id).paid
    assert store.account_credits(owner_account.id, datetime.now(UTC)) == 1
    pdf = owner.get(f"/audits/{credit_id}/pdf?token={credit_token}&lang={locale}")
    if pdf_lib.available():
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    else:
        # The local Windows runtime lacks Pango. Exercise the public PDF
        # fallback without claiming that a PDF was rendered here.
        assert pdf.status_code == 503 and "text/html" in pdf.headers["content-type"]
    home_page = owner.get(home)
    assert home_page.status_code == 200 and "id='faq'" in home_page.text
    assert settings.contact_url in home_page.text
    counts = funnel.build(store.funnel_events(datetime.now(UTC).date().isoformat())).total.counts
    assert counts["purchases"] == 1
    assert counts["gift_credits"] == 1
    assert counts["rights_sold"] == 3
