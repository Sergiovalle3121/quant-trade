"""Browser-facing email flows with SMTP queued but no network delivery."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, mail  # noqa: E402
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


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_confirmation_requires_a_post_and_recovery_keeps_language(
    tmp_path: Path, locale: str
) -> None:
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
