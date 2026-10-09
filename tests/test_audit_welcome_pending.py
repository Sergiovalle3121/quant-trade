"""A file uploaded before the e-mail is confirmed becomes the free full report
when the address is confirmed, from any device, under the same limits.

Mail is queued and never sent (no lifespan, so no mail worker), and the
confirmation link is built from the queued row as a reader of the e-mail
would follow it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_email_routes_ui import _outbox_id  # noqa: E402

from quant_trade.audit import account_pages, mail  # noqa: E402
from quant_trade.audit.accounts import (  # noqa: E402
    WELCOME_REPORTS_PER_IP_PER_MONTH,
    month_start,
    network_address,
    network_key,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import WELCOME_REFERENCE_PREFIX, Store, make_store  # noqa: E402
from quant_trade.audit.web import WELCOME_PENDING_DAYS, create_app  # noqa: E402

BASE = "https://rigor.example"
SECRET = "stable secret shared across replicas 1234567890"
PASSWORD = "una frase larga y segura"
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")


def _app(tmp_path: Path) -> tuple[Any, Store]:
    """The settings of ``test_unconfirmed_email_waits_for_the_free_report``."""
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        contact_url="https://wa.me/000",
        admin_key="k" * 40,
        base_url=BASE,
        email_verification_required=True,
        email_token_secret=SECRET,
        resend_api_key="re_test_0123456789abcdefghij",
        smtp_from="Rigor <hola@example.com>",
    )
    store = make_store(settings.database_url)
    return create_app(settings, store), store


def _browser(app: Any) -> TestClient:
    return TestClient(app, base_url=BASE)


def _csrf(page: str) -> str:
    match = CSRF_FIELD.search(page)
    assert match is not None
    return match.group(1)


def _signup(client: TestClient, store: Store, email: str) -> str:
    page = client.get("/registro").text
    made = client.post(
        "/registro",
        data={"email": email, "password": PASSWORD, "csrf": _csrf(page)},
        follow_redirects=False,
    )
    assert made.status_code == 303
    account = store.find_account(email)
    assert account is not None and not store.email_verified(account.id)
    return account.id


def _upload(client: TestClient, seed: int) -> str:
    sent = client.post(
        "/audits",
        files={"equity": ("e.csv", csv_bytes(positive_drift(500, seed=seed)), "text/csv")},
        data={"consent": "on"},
        follow_redirects=False,
    )
    assert sent.status_code == 303, sent.text[:500]
    return sent.headers["location"]


def _audit_id(location: str) -> str:
    return location.split("/audits/")[1].split("?")[0]


def _confirm(app: Any, store: Store, account_id: str, kind: str = "verify") -> tuple[Any, Any]:
    """Open the e-mailed link on another device (a phone with no session)."""
    phone = _browser(app)
    token = mail.token_for(_outbox_id(store, account_id, kind), SECRET)
    path = mail.PATHS["es"][kind]
    page = phone.get(path, params={"token": token})
    assert page.status_code == 200
    answer = phone.post(
        path, data={"token": token, "csrf": _csrf(page.text)}, follow_redirects=False
    )
    assert answer.status_code == 303
    return phone, answer


def _pending(store: Store, account_id: str) -> list[Any]:
    return store.welcome_pending_for(account_id, since=datetime.now(UTC) - timedelta(days=60))


PROMISE = account_pages._e(account_pages.COPY["es"]["welcome_refused_unverified"])
OTHER = account_pages._e(account_pages.COPY["es"]["welcome_pending_other"])
CONFIRMED = account_pages._e(account_pages.COPY["es"]["welcome_pending_confirmed"])


def _notice(client: TestClient, location: str) -> str:
    """Which of the three notices the preview's page shows."""
    page = client.get(location).text
    shown = [
        name
        for name, text in (("promise", PROMISE), ("other", OTHER), ("confirmed", CONFIRMED))
        if text in page
    ]
    assert len(shown) <= 1, shown
    return shown[0] if shown else ""


def test_the_report_uploaded_before_confirming_opens_in_full(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    laptop = _browser(app)
    account_id = _signup(laptop, store, "nueva@example.com")
    location = _upload(laptop, 21)
    assert "acct=preview_unverified" in location
    audit_id = _audit_id(location)
    (row,) = _pending(store, account_id)
    assert row.audit_id == audit_id and row.file_sha256 and row.device_sha256
    month = month_start(datetime.now(UTC))
    assert store.free_previews_since(month, account_id=account_id) == 1
    preview = laptop.get(location).text
    assert account_pages.COPY["es"]["welcome_refused_unverified"] in preview

    phone, confirmed = _confirm(app, store, account_id)
    assert "done=email_verified_report" in confirmed.headers["location"]
    record = store.get_audit(audit_id)
    assert record is not None and record.paid
    assert str(record.stripe_session_id).startswith(WELCOME_REFERENCE_PREFIX)
    assert store.welcome_used(account_id)
    # The month's preview is given back, and nothing stays pending.
    assert store.free_previews_since(month, account_id=account_id) == 0
    assert _pending(store, account_id) == []
    # The phone has no session: it is asked to sign in, with the news.
    signin = phone.get(confirmed.headers["location"])
    assert account_pages.COPY["es"]["email_verified_report"] in signin.text
    # The laptop, signed in, reads it on the account page.
    page = laptop.get("/cuenta?done=email_verified_report").text
    assert account_pages.COPY["es"]["email_verified_report"] in page


def test_only_the_most_recent_pending_upload_opens(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    laptop = _browser(app)
    account_id = _signup(laptop, store, "dos@example.com")
    first_location = _upload(laptop, 21)
    second_location = _upload(laptop, 22)
    first, second = _audit_id(first_location), _audit_id(second_location)
    assert [row.audit_id for row in _pending(store, account_id)] == [second, first]
    # Only the upload that confirming would open says so; the other one says
    # which one opens.
    assert _notice(laptop, second_location) == "promise"
    assert _notice(laptop, first_location) == "other"
    _, confirmed = _confirm(app, store, account_id)
    assert "done=email_verified_report" in confirmed.headers["location"]
    opened, kept = store.get_audit(second), store.get_audit(first)
    assert opened is not None and opened.paid
    assert kept is not None and not kept.paid
    # Confirmed, the preview that stayed one no longer asks to confirm.
    assert _notice(laptop, first_location) == "confirmed"
    month = month_start(datetime.now(UTC))
    assert store.free_previews_since(month, account_id=account_id) == 1
    assert _pending(store, account_id) == []


def test_a_file_that_already_had_its_free_report_is_not_opened(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    ana = _browser(app)
    ana_id = _signup(ana, store, "ana@example.com")
    location = _upload(ana, 31)
    waiting = _audit_id(location)
    (row,) = _pending(store, ana_id)
    assert _notice(ana, location) == "promise"
    # Someone else, confirmed first, gets the free report with the same file.
    beto = _browser(app)
    beto_id = _signup(beto, store, "beto@example.com")
    _confirm(app, store, beto_id)
    assert "acct=welcome" in _upload(beto, 31)
    # The same page no longer promises what confirming cannot give.
    assert _notice(ana, location) == "other"

    _, confirmed = _confirm(app, store, ana_id)
    assert "done=email_verified_report" not in confirmed.headers["location"]
    record = store.get_audit(waiting)
    assert record is not None and not record.paid
    assert not store.welcome_used(ana_id)
    assert _pending(store, ana_id) == []
    # The file's own claim decided it, not the network or the browser.
    refusal = store.welcome_refusal(
        ana_id,
        device_sha256=row.device_sha256,
        file_sha256=row.file_sha256,
        client_ip=row.client_ip,
        since=month_start(datetime.now(UTC)),
        per_ip=WELCOME_REPORTS_PER_IP_PER_MONTH,
    )
    assert refusal == "file"
    assert _notice(ana, location) == "confirmed"


def test_a_file_that_had_its_free_report_before_the_upload_is_not_noted(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    beto = _browser(app)
    beto_id = _signup(beto, store, "beto@example.com")
    _confirm(app, store, beto_id)
    assert "acct=welcome" in _upload(beto, 33)
    ana = _browser(app)
    ana_id = _signup(ana, store, "ana@example.com")
    location = _upload(ana, 33)
    assert "acct=preview_unverified" in location
    # The file is checked at upload: nothing waits, and nothing is promised.
    assert _pending(store, ana_id) == []
    assert _notice(ana, location) == "other"
    _, confirmed = _confirm(app, store, ana_id)
    assert "done=email_verified_report" not in confirmed.headers["location"]
    record = store.get_audit(_audit_id(location))
    assert record is not None and not record.paid
    assert _notice(ana, location) == "confirmed"


def test_the_most_recent_upload_that_can_still_open_is_the_one(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    laptop = _browser(app)
    account_id = _signup(laptop, store, "tres@example.com")
    first_location = _upload(laptop, 71)
    second_location = _upload(laptop, 72)
    assert _notice(laptop, second_location) == "promise"
    # Another account has its free report with the second file meanwhile.
    beto = _browser(app)
    beto_id = _signup(beto, store, "beto3@example.com")
    _confirm(app, store, beto_id)
    assert "acct=welcome" in _upload(beto, 72)
    # The first upload is now the one confirming would open, and says so.
    assert _notice(laptop, second_location) == "other"
    assert _notice(laptop, first_location) == "promise"
    _, confirmed = _confirm(app, store, account_id)
    assert "done=email_verified_report" in confirmed.headers["location"]
    opened = store.get_audit(_audit_id(first_location))
    kept = store.get_audit(_audit_id(second_location))
    assert opened is not None and opened.paid
    assert kept is not None and not kept.paid


def test_a_pending_upload_older_than_a_week_is_ignored(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    laptop = _browser(app)
    account_id = _signup(laptop, store, "tarde@example.com")
    location = _upload(laptop, 41)
    audit_id = _audit_id(location)
    old = datetime.now(UTC) - timedelta(days=WELCOME_PENDING_DAYS + 1)
    with store.engine.begin() as conn:
        conn.execute(
            store.welcome_pending.update().values(created_at=old.isoformat().replace("+00:00", "Z"))
        )
    # Past the window the page no longer promises it.
    assert _notice(laptop, location) == "other"
    _, confirmed = _confirm(app, store, account_id)
    assert "done=email_verified_report" not in confirmed.headers["location"]
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    assert not store.welcome_used(account_id)
    assert _pending(store, account_id) == []


def test_confirming_a_new_address_grants_nothing(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    laptop = _browser(app)
    account_id = _signup(laptop, store, "cambio@example.com")
    location = _upload(laptop, 51)
    audit_id = _audit_id(location)
    account_page = laptop.get("/cuenta").text
    asked = laptop.post(
        "/cuenta/correo",
        data={
            "email": "cambio.nuevo@example.com",
            "email_again": "cambio.nuevo@example.com",
            "current": PASSWORD,
            "csrf": _csrf(account_page),
        },
        follow_redirects=False,
    )
    assert asked.status_code == 303 and "done=email_pending" in asked.headers["location"]
    _, confirmed = _confirm(app, store, account_id, kind="change")
    assert "done=email_changed" in confirmed.headers["location"]
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    assert not store.welcome_used(account_id)
    assert [row.audit_id for row in _pending(store, account_id)] == [audit_id]
    # The address is confirmed by the change: the page stops asking for it.
    assert store.email_verified(account_id)
    assert _notice(laptop, location) == "confirmed"


def test_pending_rows_go_with_the_report_and_the_retention_purge(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    laptop = _browser(app)
    account_id = _signup(laptop, store, "borra@example.com")
    deleted = _audit_id(_upload(laptop, 61))
    kept = _audit_id(_upload(laptop, 62))
    assert store.delete_audit(deleted)
    assert [row.audit_id for row in _pending(store, account_id)] == [kept]
    store.purge_expired(datetime.now(UTC) + timedelta(days=60), retention_days=30)
    assert _pending(store, account_id) == []
    exported = store.welcome_pending_for(account_id, since=datetime(2000, 1, 1, tzinfo=UTC))
    assert exported == []


def test_the_network_key_is_the_same_from_the_address_or_its_network() -> None:
    for raw in ("203.0.113.7", "2001:db8:1:2:3:4:5:6", "::ffff:198.51.100.9", "testclient"):
        ip = network_address(raw)
        net = network_address(ip)
        assert net == ip
        assert network_key(net) == network_key(ip)
