"""Offline account-mail flows: durable outbox and explicit one-use confirmation."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from audit_fixtures import csv_bytes, positive_drift  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, mail  # noqa: E402
from quant_trade.audit.accounts import verify_password  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

CSRF = re.compile(r"name='csrf' value='([^']+)'")
PASSWORD = "a long private phrase for email tests"


def _settings(tmp_path: Path) -> AuditSettings:
    return AuditSettings(
        database_url=f"sqlite:///{tmp_path}/mail.db",
        base_url="https://rigor.example",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=False,
        stripe_secret_key="sk_live_test",
        stripe_webhook_secret="whsec_email",
        approved_markets=frozenset({"MX"}),
        email_verification_required=True,
        email_token_secret="stable secret shared across replicas 1234567890",
        smtp_host="smtp.example",
        smtp_from="Rigor <hello@example.com>",
    )


def _signup(client: TestClient, email: str, invite: str = "") -> None:
    page = client.get("/registro")
    csrf = CSRF.search(page.text)
    assert csrf is not None
    response = client.post(
        "/registro",
        data={"email": email, "password": PASSWORD, "csrf": csrf.group(1), "invite": invite},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _upload(client: TestClient, seed: int) -> tuple[str, str]:
    response = client.post(
        "/audits",
        files={"equity": ("robot.csv", csv_bytes(positive_drift(500, seed=seed)), "text/csv")},
        data={"trials": "3", "cost_bps": "5", "consent": "on", "locale": "es"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    parts = urlsplit(response.headers["location"])
    return parts.path.rsplit("/", 1)[1], parse_qs(parts.query)["token"][0]


def _mail_link(store: object, cfg: AuditSettings, recipient: str) -> str:
    messages = []
    assert mail.deliver_pending(store, cfg, sender=lambda msg, _: messages.append(msg)) >= 1
    selected = [m for m in messages if m["To"] == recipient]
    assert selected
    match = re.search(r"https://rigor\.example/[^\s]+", selected[-1].get_content())
    assert match is not None
    return match.group(0)


def _confirm(client: TestClient, link: str) -> None:
    parts = urlsplit(link)
    token = parse_qs(parts.query)["token"][0]
    page = client.get(parts.path + "?token=" + token)
    assert page.status_code == 200
    csrf = CSRF.search(page.text)
    assert csrf is not None
    posted = client.post(
        parts.path,
        data={"token": token, "csrf": csrf.group(1)},
        follow_redirects=False,
    )
    assert posted.status_code == 303
    assert (
        client.post(
            parts.path,
            data={"token": token, "csrf": csrf.group(1)},
            follow_redirects=False,
        ).status_code
        == 410
    )


def test_signup_outbox_survives_restart_and_checkout_waits_for_post(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    assert cfg.email_delivery_ready
    store = make_store(cfg.database_url)
    app = create_app(cfg, store)
    client = TestClient(app, base_url=cfg.base_url)
    _signup(client, "buyer@example.com")
    account = store.find_account("buyer@example.com")
    assert account is not None and not store.email_verified(account.id)
    first_id, _ = _upload(client, 301)
    assert store.get_audit(first_id).paid  # first full report before verification
    second_id, token = _upload(client, 302)
    denied = client.post(f"/audits/{second_id}/checkout?token={token}", follow_redirects=False)
    assert denied.status_code == 403
    assert store.list_checkout_orders() == []

    # A different process can reconstruct a link from the persisted id and
    # shared HMAC key, while the database itself has no clear token or URL.
    restarted = make_store(cfg.database_url)
    link = _mail_link(restarted, cfg, "buyer@example.com")
    secret_token = parse_qs(urlsplit(link).query)["token"][0]
    assert secret_token.encode() not in (tmp_path / "mail.db").read_bytes()
    fresh = TestClient(create_app(cfg, restarted), base_url=cfg.base_url)
    preview = fresh.get(link)
    assert preview.status_code == 200
    assert "no-store" in preview.headers["cache-control"]
    assert not restarted.email_verified(account.id)  # GET may be prefetched
    _confirm(fresh, link)
    assert restarted.email_verified(account.id)

    observed = []
    app.state.checkout_factory = lambda *_args, **kwargs: (
        observed.append(kwargs),
        "https://checkout.stripe.test/email",
    )[1]
    allowed = client.post(
        f"/audits/{second_id}/checkout?token={token}",
        data={"billing_country": "MX"},
        follow_redirects=False,
    )
    assert allowed.status_code == 303 and len(observed) == 1
    assert observed[0]["amount_cents"] == 2900


def test_verified_owner_must_be_the_signed_in_checkout_buyer(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    app = create_app(cfg, store)
    owner = TestClient(app, base_url=cfg.base_url)
    _signup(owner, "owner@example.com")
    _upload(owner, 701)  # the first full report is free
    audit_id, token = _upload(owner, 702)
    _confirm(owner, _mail_link(store, cfg, "owner@example.com"))

    path = f"/audits/{audit_id}/checkout?token={token}"
    anonymous = TestClient(app, base_url=cfg.base_url)
    assert anonymous.post(path, follow_redirects=False).status_code == 403
    stranger = TestClient(app, base_url=cfg.base_url)
    _signup(stranger, "stranger@example.com")
    _confirm(stranger, _mail_link(store, cfg, "stranger@example.com"))
    assert stranger.post(path, follow_redirects=False).status_code == 403
    assert store.list_checkout_orders() == []

    app.state.checkout_factory = lambda *_args, **_kwargs: "https://checkout.stripe.test/owner"
    assert (
        owner.post(path, data={"billing_country": "MX"}, follow_redirects=False).status_code == 303
    )
    assert len(store.list_checkout_orders()) == 1


def test_email_change_is_pending_and_reset_request_is_generic(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    client = TestClient(create_app(cfg, store), base_url=cfg.base_url)
    _signup(client, "before@example.com")
    account = store.find_account("before@example.com")
    assert account is not None
    _confirm(client, _mail_link(store, cfg, "before@example.com"))
    page = client.get("/cuenta")
    csrf = CSRF.search(page.text)
    assert csrf is not None
    changed = client.post(
        "/cuenta/correo",
        data={
            "email": "after@example.com",
            "email_again": "after@example.com",
            "current": PASSWORD,
            "csrf": csrf.group(1),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert store.find_account("before@example.com") is not None
    assert store.find_account("after@example.com") is None
    assert store.pending_email_change(account.id, datetime.now(UTC)) == "after@example.com"
    _confirm(client, _mail_link(store, cfg, "after@example.com"))
    assert store.find_account("before@example.com") is None
    assert store.find_account("after@example.com") is not None
    assert store.email_verified(account.id)

    forgot = client.get(account_pages.path("forgot", "es"))
    csrf = CSRF.search(forgot.text)
    assert csrf is not None
    unknown = client.post(
        "/olvide/enlace",
        data={"email": "missing@example.com", "csrf": csrf.group(1)},
        follow_redirects=False,
    )
    known = client.post(
        "/olvide/enlace",
        data={"email": "after@example.com", "csrf": csrf.group(1)},
        follow_redirects=False,
    )
    assert unknown.status_code == known.status_code == 303
    assert unknown.headers["location"] == known.headers["location"]
    reset = _mail_link(store, cfg, "after@example.com")
    assert urlsplit(reset).path == "/restablecer"
    reset_page = client.get(reset)
    assert reset_page.status_code == 200
    csrf = CSRF.search(reset_page.text)
    assert csrf is not None
    reset_token = parse_qs(urlsplit(reset).query)["token"][0]
    new_password = "a different long private phrase"
    accepted = client.post(
        "/restablecer",
        data={"token": reset_token, "password": new_password, "csrf": csrf.group(1)},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert verify_password(store.password_hash(account.id) or "", new_password)
    assert client.get(reset).status_code == 410
    assert client.get("/cuenta", follow_redirects=False).status_code == 303


def test_referral_waits_until_both_addresses_are_confirmed(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    app = create_app(cfg, store)
    inviter = TestClient(app, base_url=cfg.base_url)
    _signup(inviter, "inviter@example.com")
    inviter_link = _mail_link(store, cfg, "inviter@example.com")
    account = store.find_account("inviter@example.com")
    assert account is not None
    invite_match = re.search(r"id='invite-link'[^>]*value='([^']+)'", inviter.get("/cuenta").text)
    assert invite_match is not None
    invite = parse_qs(urlsplit(invite_match.group(1)).query)["invita"][0]
    friend = TestClient(app, base_url=cfg.base_url)
    _signup(friend, "friend@example.com", invite)
    friend_link = _mail_link(store, cfg, "friend@example.com")
    first_id, _ = _upload(friend, 411)
    assert store.get_audit(first_id).paid
    assert store.account_credits(account.id, datetime.now(UTC)) == 0
    _confirm(friend, friend_link)
    assert store.account_credits(account.id, datetime.now(UTC)) == 0
    _confirm(inviter, inviter_link)
    assert store.account_credits(account.id, datetime.now(UTC)) == 1
    assert store.invite_summary(account.id, datetime.now(UTC)).credited == 1


def test_failed_smtp_stays_queued_and_retries_without_a_new_token(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    store = make_store(cfg.database_url)
    client = TestClient(create_app(cfg, store), base_url=cfg.base_url)
    _signup(client, "retry@example.com")
    at = datetime.now(UTC)

    def fail(_message: object, _settings: AuditSettings) -> None:
        raise OSError("fake SMTP outage")

    assert mail.deliver_pending(store, cfg, sender=fail, now=at) == 0
    with store.engine.connect() as conn:
        row = conn.execute(store.email_outbox.select()).mappings().one()
    assert row["status"] == "queued" and row["attempts"] == 1
    assert mail.deliver_pending(store, cfg, sender=fail, now=at) == 0
    messages = []
    assert (
        mail.deliver_pending(
            store,
            cfg,
            sender=lambda message, _settings: messages.append(message),
            now=at + timedelta(minutes=2),
        )
        == 1
    )
    assert len(messages) == 1
    token = parse_qs(urlsplit(re.search(r"https://\S+", messages[0].get_content()).group()).query)[
        "token"
    ][0]
    assert mail.challenge_from_token(token, cfg.email_token_secret) == row["id"]
