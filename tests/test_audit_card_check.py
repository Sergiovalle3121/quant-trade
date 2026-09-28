"""The no-charge card check that stands in for a shared browser or network."""

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

from audit_fixtures import csv_bytes, positive_drift, signed_in  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import payments  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app, sign_stripe_payload  # noqa: E402

BASE = "https://rigor.example"
_CSRF = re.compile(r"name='csrf' value='([^']+)'")


def _settings(tmp_path: Path, **extra: Any) -> AuditSettings:
    values: dict[str, Any] = {
        "database_url": f"sqlite:///{tmp_path}/audit.db",
        "bootstrap_samples": 100,
        "base_url": BASE,
        "free_mode": False,
        "access_codes": False,
        "stripe_secret_key": "sk_live_test",
        "stripe_webhook_secret": "whsec_card",
        "approved_markets": frozenset({"MX"}),
    }
    values.update(extra)
    return AuditSettings(**values)


class FakeStripe:
    """Setup sessions and card fingerprints, as Stripe would report them."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.fingerprints: dict[str, str] = {}

    def create(self, cfg: AuditSettings, account_id: str, *, locale: str, back: str) -> dict:
        params = payments.card_check_params(cfg, account_id, locale=locale, back=back)
        self.created.append(params)
        return {"id": f"cs_setup_{len(self.created)}", "url": "https://checkout.stripe.test/s"}

    def finish(self, account_id: str, fingerprint: str, **changes: Any) -> str:
        """The session Stripe returns once the customer verified a card."""
        n = len(self.sessions) + 1
        session_id, intent = f"cs_setup_done_{n}", f"seti_{n}"
        session = {
            "id": session_id,
            "mode": "setup",
            "status": "complete",
            "livemode": True,
            "setup_intent": intent,
            "metadata": {"app": "rigor", "purpose": "welcome_card", "account_id": account_id},
        }
        session.update(changes)
        self.sessions[session_id] = session
        self.fingerprints[intent] = fingerprint
        return session_id

    def lookup(self, cfg: AuditSettings, session_id: str) -> dict[str, Any]:
        return self.sessions[session_id]

    def fingerprint(self, cfg: AuditSettings, intent_id: str) -> str:
        return self.fingerprints.get(intent_id, "")


def _app(tmp_path: Path, **extra: Any) -> tuple[Any, Any, FakeStripe]:
    settings = _settings(tmp_path, **extra)
    store = make_store(settings.database_url)
    app = create_app(settings, store)
    fake = FakeStripe()
    app.state.card_check_factory = fake.create
    app.state.session_lookup = fake.lookup
    app.state.card_fingerprint = fake.fingerprint
    return app, store, fake


def _upload(client: TestClient, seed: int) -> tuple[str, str, str]:
    response = client.post(
        "/audits",
        files={"equity": (f"c{seed}.csv", csv_bytes(positive_drift(500, seed=seed)), "text/csv")},
        data={"consent": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:300]
    location = response.headers["location"]
    parts = urlsplit(location)
    return parts.path.rsplit("/", 1)[1], parse_qs(parts.query)["token"][0], location


def _switch(client: TestClient, email: str) -> None:
    """Sign another person up in the same browser: the browser mark stays."""
    from quant_trade.audit import accounts

    device = client.cookies.get(accounts.DEVICE_COOKIE)
    client.cookies.clear()
    if device:
        client.cookies.set(accounts.DEVICE_COOKIE, device)
    signed_in(client, email, welcome=True)


def _shared_browser(app: Any, store: Any) -> tuple[TestClient, Any]:
    """Ana takes the free report; Bea signs up in the same browser."""
    client = signed_in(TestClient(app, base_url=BASE), "ana@example.com", welcome=True)
    _upload(client, 1)
    _switch(client, "bea@example.com")
    return client, store.find_account("bea@example.com")


def test_the_setup_session_charges_nothing_and_names_the_account() -> None:
    cfg = _settings(Path("/nonexistent"))
    params = payments.card_check_params(cfg, "acc1", locale="pt", back="/audits/a?token=t")
    assert params["mode"] == "setup" and "line_items" not in params
    assert params["payment_method_types"] == ["card"]
    assert params["metadata"] == {"app": "rigor", "purpose": "welcome_card", "account_id": "acc1"}
    assert params["setup_intent_data"]["metadata"] == params["metadata"]
    assert params["success_url"] == (
        f"{BASE}/audits/a?token=t&card=checked&setup_session={{CHECKOUT_SESSION_ID}}"
    )
    assert params["cancel_url"] == f"{BASE}/audits/a?token=t&card=skipped"
    assert params["locale"] == "pt-BR"


def test_a_shared_browser_gets_a_card_offer_and_the_card_unlocks_the_next_upload(
    tmp_path: Path,
) -> None:
    app, store, fake = _app(tmp_path)
    client, bea = _shared_browser(app, store)
    audit_id, token, location = _upload(client, 2)
    assert "acct=preview_device" in location
    page = client.get(location).text
    assert f"action='/audits/{audit_id}/tarjeta?token={token}" in page
    assert "Verificar tarjeta sin cargo" in page
    started = client.post(
        f"/audits/{audit_id}/tarjeta?token={token}&lang=es",
        data={"csrf": _CSRF.findall(page)[-1]},
        follow_redirects=False,
    )
    assert started.status_code == 303
    assert started.headers["location"] == "https://checkout.stripe.test/s"
    assert fake.created[-1]["metadata"]["account_id"] == bea.id
    done = fake.finish(bea.id, "fp_bea")
    back = client.get(f"/audits/{audit_id}?token={token}&lang=es&card=checked&setup_session={done}")
    assert "Tarjeta confirmada, sin cargo" in back.text
    assert store.card_checked(bea.id)
    assert not store.get_audit(audit_id).paid  # nothing unlocks without a new upload
    assert "Verificar tarjeta sin cargo" not in back.text
    again_id, _, again = _upload(client, 2)
    assert "acct=welcome" in again and store.get_audit(again_id).paid


def test_one_card_gives_one_free_report_across_accounts(tmp_path: Path) -> None:
    app, store, fake = _app(tmp_path)
    client, bea = _shared_browser(app, store)
    done = fake.finish(bea.id, "fp_same")
    audit_id, token, _ = _upload(client, 2)
    client.get(f"/audits/{audit_id}?token={token}&card=checked&setup_session={done}")
    assert store.card_checked(bea.id)
    _switch(client, "caro@example.com")
    caro = store.find_account("caro@example.com")
    caro_id, caro_token, _ = _upload(client, 3)
    later = fake.finish(caro.id, "fp_same")
    page = client.get(f"/audits/{caro_id}?token={caro_token}&card=checked&setup_session={later}")
    assert "Esa tarjeta ya se usó" in page.text
    assert not store.card_checked(caro.id)
    _, _, location = _upload(client, 4)
    assert "acct=preview_device" in location
    # Deleting the account that used the card never frees it.
    store.delete_account(bea.id)
    assert (
        store.record_card_check(
            caro.id, payments.card_fingerprint_sha256("fp_same"), at=datetime.now(UTC)
        )
        == "taken"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"livemode": False},  # a test-mode card never counts on a live service
        {"status": "open"},
        {"mode": "payment"},
        {"metadata": {"app": "other", "purpose": "welcome_card"}},
    ],
)
def test_only_rigor_finished_live_setup_sessions_count(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    app, store, fake = _app(tmp_path)
    client, bea = _shared_browser(app, store)
    audit_id, token, _ = _upload(client, 2)
    done = fake.finish(bea.id, "fp_x", **changes)
    page = client.get(f"/audits/{audit_id}?token={token}&card=checked&setup_session={done}")
    assert "No pudimos confirmar la tarjeta" in page.text
    assert not store.card_checked(bea.id)


def test_a_return_url_for_another_account_records_nothing(tmp_path: Path) -> None:
    app, store, fake = _app(tmp_path)
    client, bea = _shared_browser(app, store)
    ana = store.find_account("ana@example.com")
    audit_id, token, _ = _upload(client, 2)
    done = fake.finish(ana.id, "fp_ana")
    client.get(f"/audits/{audit_id}?token={token}&card=checked&setup_session={done}")
    assert not store.card_checked(bea.id) and not store.card_checked(ana.id)


def test_the_webhook_records_a_card_check_and_never_marks_anything_paid(tmp_path: Path) -> None:
    app, store, fake = _app(tmp_path)
    client, bea = _shared_browser(app, store)
    audit_id, _, _ = _upload(client, 2)
    done = fake.finish(bea.id, "fp_hook")
    session = dict(fake.sessions[done], payment_status="no_payment_required")
    session["metadata"] = dict(session["metadata"], audit_id=audit_id, plan="single")
    event = json.dumps({"type": "checkout.session.completed", "data": {"object": session}})
    signature = sign_stripe_payload(event.encode(), "whsec_card", timestamp=int(time.time()))
    answer = client.post("/webhooks/stripe", content=event, headers={"stripe-signature": signature})
    assert answer.status_code == 200
    assert store.card_checked(bea.id)
    assert not store.get_audit(audit_id).paid


def test_no_offer_without_live_card_sales_or_once_checked(tmp_path: Path) -> None:
    app, store, _ = _app(tmp_path, approved_markets=frozenset())
    client, _ = _shared_browser(app, store)
    _, _, location = _upload(client, 2)
    assert "/tarjeta" not in client.get(location).text


def test_a_card_does_not_lift_the_file_limit(tmp_path: Path) -> None:
    app, store, fake = _app(tmp_path)
    client, bea = _shared_browser(app, store)
    done = fake.finish(bea.id, "fp_file")
    audit_id, token, _ = _upload(client, 2)
    client.get(f"/audits/{audit_id}?token={token}&card=checked&setup_session={done}")
    _, _, location = _upload(client, 1)  # Ana's file, already free once
    assert "acct=preview_file" in location


def test_the_card_check_is_in_the_data_download_and_goes_with_the_account(
    tmp_path: Path,
) -> None:
    app, store, fake = _app(tmp_path)
    client, bea = _shared_browser(app, store)
    store.record_card_check(bea.id, payments.card_fingerprint_sha256("fp_d"), at=datetime.now(UTC))
    exported = store.account_export(bea.id)
    assert exported["card_check"]["card_fingerprint_sha256"] == payments.card_fingerprint_sha256(
        "fp_d"
    )
    assert "fp_d" not in json.dumps(exported)
    store.delete_account(bea.id)
    assert not store.card_checked(bea.id)
