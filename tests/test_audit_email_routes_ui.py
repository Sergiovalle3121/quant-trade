"""Browser-facing email flows with SMTP queued but no network delivery."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, accounts, mail  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import Store, make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")
SECRET = "s" * 40
PASSWORD = "a long, distinct account password"


def _csrf(page: str) -> str:
    match = CSRF_FIELD.search(page)
    assert match is not None
    return match.group(1)


def _outbox_id(store: Store, account_id: str, kind: str) -> str:
    with store.engine.connect() as conn:
        row = conn.execute(
            store._sa.select(store.email_outbox.c.id)
            .where(store.email_outbox.c.account_id == account_id)
            .where(store.email_outbox.c.kind == kind)
            .order_by(store.email_outbox.c.created_at.desc())
        ).first()
    assert row is not None
    return str(row[0])


def _client(tmp_path: Path) -> tuple[TestClient, Store]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/email.db",
        base_url="https://rigor.example",
        email_verification_required=True,
        email_token_secret=SECRET,
        smtp_host="smtp.example",
        smtp_from="hello@rigor.example",
        free_mode=False,
    )
    store = make_store(settings.database_url)
    client = TestClient(create_app(settings, store), base_url="https://rigor.example")
    return client, store


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_confirmation_requires_a_post_and_recovery_keeps_language(
    tmp_path: Path, locale: str
) -> None:
    client, store = _client(tmp_path)
    paths = account_pages.PATHS[locale]
    email = f"synthetic-{locale}@example.com"

    signup = client.get(paths["signup"])
    made = client.post(
        paths["signup"],
        data={"email": email, "password": PASSWORD, "csrf": _csrf(signup.text)},
        follow_redirects=False,
    )
    assert made.status_code == 303, re.findall(r"<div class='error'[^>]*>(.*?)</div>", made.text)
    account = store.find_account(email)
    assert account is not None and not store.email_verified(account.id)
    account_html = client.get(paths["account"]).text
    assert f"action='{paths['account']}/verificar-correo'" in account_html

    confirm_path = mail.PATHS[locale]["verify"]
    token = mail.token_for(_outbox_id(store, account.id, "verify"), SECRET)
    confirm = client.get(confirm_path, params={"token": token})
    assert confirm.status_code == 200
    assert "no-store" in confirm.headers["cache-control"]
    assert confirm.headers["referrer-policy"] == "no-referrer"
    assert not store.email_verified(account.id)
    assert f"<form method='post' action='{confirm_path}'>" in confirm.text
    assert f"name='token' value='{token}'" in confirm.text
    refused = client.post(
        confirm_path,
        data={"token": token, "csrf": "wrong"},
        follow_redirects=False,
    )
    assert refused.status_code == 400
    assert not store.email_verified(account.id)
    submitted = client.post(
        confirm_path,
        data={"token": token, "csrf": _csrf(confirm.text)},
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    assert store.email_verified(account.id)
    confirmed = client.get(submitted.headers["location"])
    assert account_pages.COPY[locale]["email_verified"] in confirmed.text
    assert account_pages.COPY[locale]["email_verified_signin"] not in confirmed.text
    assert client.get(confirm_path, params={"token": token}).status_code == 410

    new_email = f"changed-{locale}@example.com"
    account_html = client.get(paths["account"]).text
    change = client.post(
        paths["account"] + "/correo",
        data={
            "email": new_email,
            "email_again": new_email,
            "current": PASSWORD,
            "csrf": _csrf(account_html),
        },
        follow_redirects=False,
    )
    assert change.status_code == 303
    assert store.find_account(email) is not None
    assert store.find_account(new_email) is None
    assert new_email in client.get(paths["account"]).text
    change_token = mail.token_for(_outbox_id(store, account.id, "change"), SECRET)
    change_page = client.get(confirm_path, params={"token": change_token})
    assert change_page.status_code == 200
    assert store.find_account(new_email) is None
    changed = client.post(
        confirm_path,
        data={"token": change_token, "csrf": _csrf(change_page.text)},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert store.find_account(email) is None
    assert store.find_account(new_email) is not None

    forgot = client.get(paths["forgot"])
    requested = client.post(
        paths["forgot"] + "/enlace",
        data={"email": new_email, "csrf": _csrf(forgot.text)},
        follow_redirects=False,
    )
    assert requested.status_code == 303
    assert requested.headers["location"] == paths["forgot"] + "?done=email_reset_requested"
    reset_token = mail.token_for(_outbox_id(store, account.id, "reset"), SECRET)
    reset = client.get(paths["reset"], params={"token": reset_token})
    assert reset.status_code == 200
    assert account_pages.COPY[locale]["reset_email_lead"] in reset.text
    for other in account_pages.LANGUAGES:
        if other != locale:
            assert f"{account_pages.path('reset', other)}?token={reset_token}" in reset.text

    unknown = client.post(
        paths["forgot"] + "/enlace",
        data={"email": f"unknown-{locale}@example.com", "csrf": _csrf(forgot.text)},
        follow_redirects=False,
    )
    assert unknown.status_code == 303
    assert unknown.headers["location"] == requested.headers["location"]


@pytest.mark.parametrize(
    ("locale", "notice"),
    [
        (
            "es",
            "Correo confirmado. Inicia sesión para usar tu primer informe completo gratis.",
        ),
        ("en", "E-mail confirmed. Sign in to use your first full report, free."),
        (
            "pt",
            "E-mail confirmado. Entre para usar seu primeiro relatório completo grátis.",
        ),
    ],
)
def test_confirmation_without_a_session_keeps_the_notice_on_signin(
    tmp_path: Path, locale: str, notice: str
) -> None:
    client, store = _client(tmp_path)
    paths = account_pages.PATHS[locale]
    signup = client.get(paths["signup"])
    email = f"separate-browser-{locale}@example.com"
    created = client.post(
        paths["signup"],
        data={"email": email, "password": PASSWORD, "csrf": _csrf(signup.text)},
        follow_redirects=False,
    )
    assert created.status_code == 303
    account = store.find_account(email)
    assert account is not None
    token = mail.token_for(_outbox_id(store, account.id, "verify"), SECRET)
    confirm_path = mail.PATHS[locale]["verify"]

    browser = TestClient(client.app, base_url="https://rigor.example")
    assert accounts.SESSION_COOKIE not in browser.cookies
    confirm = browser.get(confirm_path, params={"token": token})
    submitted = browser.post(
        confirm_path,
        data={"token": token, "csrf": _csrf(confirm.text)},
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    assert store.email_verified(account.id)
    account_redirect = browser.get(submitted.headers["location"], follow_redirects=False)
    assert account_redirect.status_code == 303
    signin_url = urlsplit(account_redirect.headers["location"])
    assert signin_url.path == paths["signin"]
    assert parse_qs(signin_url.query) == {
        "done": ["email_verified"],
        "next": [paths["account"]],
    }
    signin = browser.get(account_redirect.headers["location"])
    assert signin.status_code == 200
    assert f"<div class='flash' role='status'>{notice}</div>" in signin.text
    assert account_pages.COPY[locale]["email_verified"] not in signin.text
    assert find_claims(html.unescape(signin.text)) == []
    assert accounts.SESSION_COOKIE not in browser.cookies


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_signin_only_shows_allowed_flashes_and_account_only_forwards_confirmation(
    tmp_path: Path, locale: str
) -> None:
    client, _ = _client(tmp_path)
    paths = account_pages.PATHS[locale]
    for done in ("email_pending", "email_verified_signin", "unknown", "<script>"):
        signin = client.get(paths["signin"], params={"done": done})
        assert signin.status_code == 200
        assert "<div class='flash'" not in signin.text
        account_redirect = client.get(
            paths["account"], params={"done": done}, follow_redirects=False
        )
        assert account_redirect.status_code == 303
        assert parse_qs(urlsplit(account_redirect.headers["location"]).query) == {
            "next": [paths["account"]]
        }
    signed_out = client.get(paths["signin"], params={"done": "signed_out"})
    assert html.escape(account_pages.COPY[locale]["signed_out"]) in signed_out.text
    assert "<div class='flash'" in signed_out.text
