"""A visitor without an account sees the class and red flags of a file first,
and creating the account opens that same report in full (AUDIT_ANON_PREVIEW).

Paid mode, e-mail confirmation required and fake mail keys, as in
``test_unconfirmed_email_waits_for_the_free_report``. Mail is queued and never
sent (no lifespan, so no mail worker); a confirmation link is built from the
queued row as a reader of the e-mail would follow it. Everything is offline.
With the switch off, every page and route answers as before.
"""

from __future__ import annotations

import html
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

from quant_trade.audit import account_pages, funnel, mail  # noqa: E402
from quant_trade.audit.accounts import (  # noqa: E402
    ANON_PREVIEWS_PER_IPV4_PER_DAY,
    ANON_PREVIEWS_PER_NETWORK_PER_DAY,
    DEVICE_COOKIE,
    FREE_PREVIEWS_PER_MONTH,
    REPORT_KEY_COOKIE,
    claim_day,
    month_start,
    network_cap,
    network_key,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.owner import TEXT as OWNER_TEXT  # noqa: E402
from quant_trade.audit.pages import _COPY  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import WELCOME_REFERENCE_PREFIX, Store, make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://rigor.example"
SECRET = "stable secret shared across replicas 1234567890"
PASSWORD = "una frase larga y segura"
ADMIN_KEY = "k" * 40
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")
LOCATION = re.compile(r"^/audits/([A-Za-z0-9_-]+)\?token=([A-Za-z0-9_-]+)&acct=anon_preview$")
FORMS = {"es": "/auditar", "en": "/en/audit", "pt": "/pt/auditar"}
SIGNUP = {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}
#: The texts the brief fixes, word for word.
NOTE = {
    "es": (
        "Sin cuenta ves la clase de A a D y las banderas rojas de tu archivo. Con tu correo, el "
        "primer informe completo es gratis."
    ),
    "en": (
        "Without an account you see your file's A to D class and red flags. With your email, "
        "the first full report is free."
    ),
    "pt": (
        "Sem conta você vê a classe de A a D e os alertas do seu arquivo. Com o seu e-mail, o "
        "primeiro relatório completo é grátis."
    ),
}
BOX = {
    "es": "Crea tu cuenta con tu correo y este mismo informe se abre completo, gratis, con PDF.",
    "en": (
        "Create your account with your email and this same report opens in full, free, with "
        "the PDF."
    ),
    "pt": (
        "Crie sua conta com o seu e-mail e este mesmo relatório abre completo, grátis, com o PDF."
    ),
}
BUTTON = {
    "es": "Abrir mi informe completo gratis",
    "en": "Open my full report free",
    "pt": "Abrir meu relatório completo grátis",
}
NEW_KEYS = (
    "anon_preview",
    "anon_preview_link",
    "anon_preview_box",
    "anon_preview_signup",
    "anon_preview_signin",
)


def _settings(tmp_path: Path, **extra: object) -> AuditSettings:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path}/audit.db",
        "bootstrap_samples": 100,
        "free_mode": False,
        "access_codes": True,
        "contact_url": "https://wa.me/000",
        "admin_key": ADMIN_KEY,
        "base_url": BASE,
        "email_verification_required": True,
        "email_token_secret": SECRET,
        "resend_api_key": "re_test_0123456789abcdefghij",
        "smtp_from": "Rigor <hola@example.com>",
        # One proxy in front, as on Railway: X-Forwarded-For names the visitor.
        "trusted_proxy_hops": 1,
        "anon_preview": True,
    }
    values.update(extra)
    return AuditSettings(**values)  # type: ignore[arg-type]


def _app(tmp_path: Path, **extra: object) -> tuple[Any, Store]:
    settings = _settings(tmp_path, **extra)
    store = make_store(settings.database_url)
    return create_app(settings, store), store


def _browser(app: Any, ip: str = "203.0.113.7") -> TestClient:
    return TestClient(app, base_url=BASE, headers={"X-Forwarded-For": ip})


def _seeded_file(seed: int) -> dict[str, tuple[str, bytes, str]]:
    return {"equity": ("e.csv", csv_bytes(positive_drift(500, seed=seed)), "text/csv")}


def _csrf(page: str) -> str:
    match = CSRF_FIELD.search(page)
    assert match is not None
    return match.group(1)


def _upload(client: TestClient, seed: int, **extra: Any) -> Any:
    return client.post(
        "/audits",
        files=_seeded_file(seed),
        data={"consent": "on"},
        follow_redirects=False,
        **extra,
    )


def _anon_upload(client: TestClient, seed: int) -> tuple[str, str]:
    """An upload without an account: the report's id and its key."""
    sent = _upload(client, seed)
    assert sent.status_code == 303, sent.text[:300]
    match = LOCATION.match(sent.headers["location"])
    assert match is not None, sent.headers["location"]
    return match.group(1), match.group(2)


def _audits(store: Store) -> int:
    with store.engine.connect() as conn:
        return int(
            conn.execute(
                store._sa.select(store._sa.func.count()).select_from(store.audits)
            ).scalar()
            or 0
        )


def _from_report(client: TestClient, audit_id: str, token: str, go: str) -> str:
    """The report box's button: to sign-up or sign-in, with the key in its cookie."""
    answer = client.post(
        f"/audits/{audit_id}/account",
        params={"token": token, "lang": "es"},
        data={"go": go},
        follow_redirects=False,
    )
    assert answer.status_code == 303
    target = answer.headers["location"]
    if go == "signin":
        # The sign-in address keeps the key out of ``next`` (its cookie holds it).
        assert "token" not in target
    assert client.cookies.get(REPORT_KEY_COOKIE)
    return f"/audits/{audit_id}?lang=es"


def _signup_from(client: TestClient, next_path: str, email: str) -> Any:
    page = client.get("/registro", params={"next": next_path}).text
    return client.post(
        "/registro",
        data={"email": email, "password": PASSWORD, "csrf": _csrf(page), "next": next_path},
        follow_redirects=False,
    )


def _signin_from(client: TestClient, next_path: str, email: str) -> Any:
    page = client.get("/entrar", params={"next": next_path}).text
    return client.post(
        "/entrar",
        data={"email": email, "password": PASSWORD, "csrf": _csrf(page), "next": next_path},
        follow_redirects=False,
    )


def _confirm(app: Any, store: Store, account_id: str) -> Any:
    """Open the e-mailed link on another device (a phone with no session)."""
    phone = TestClient(app, base_url=BASE)
    token = mail.token_for(_outbox_id(store, account_id, "verify"), SECRET)
    path = mail.PATHS["es"]["verify"]
    page = phone.get(path, params={"token": token})
    assert page.status_code == 200
    answer = phone.post(
        path, data={"token": token, "csrf": _csrf(page.text)}, follow_redirects=False
    )
    assert answer.status_code == 303
    return answer


def _escaped(text: str) -> str:
    return account_pages._e(text)


# -- the form ---------------------------------------------------------------------
@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_form_opens_without_an_account(tmp_path: Path, locale: str) -> None:
    app, _ = _app(tmp_path)
    page = _browser(app).get(FORMS[locale], follow_redirects=False)
    assert page.status_code == 200
    assert _COPY[locale]["anon_preview_note"] == NOTE[locale]
    assert html.escape(NOTE[locale], quote=True) in page.text
    assert html.escape(_COPY[locale]["signin_first"], quote=True) not in page.text
    assert "action='/audits'" in page.text


# -- the upload ---------------------------------------------------------------------
def test_an_upload_without_an_account_is_a_locked_preview(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    visitor = _browser(app)
    sent = _upload(visitor, 11)
    assert sent.status_code == 303
    match = LOCATION.match(sent.headers["location"])
    assert match is not None, sent.headers["location"]
    audit_id = match.group(1)
    # The browser gets its random id, as with any upload.
    assert visitor.cookies.get(DEVICE_COOKIE)
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    assert record.overall_class in ("A", "B", "C", "D")
    assert store.account_for_audit(audit_id) is None
    row = store.anon_pending(audit_id)
    assert row is not None and row.account_id == ""
    assert row.file_sha256 and row.device_sha256 and row.client_ip == "203.0.113.7"

    page = visitor.get(sent.headers["location"])
    assert page.status_code == 200
    assert "noindex" in page.headers.get("x-robots-tag", "")
    text = page.text
    assert f"Clase {record.overall_class}" in html.unescape(text)
    assert _escaped(account_pages.COPY["es"]["anon_preview"]) in text
    assert _escaped(BOX["es"]) in text and _escaped(BUTTON["es"]) in text
    assert _escaped(account_pages.COPY["es"]["anon_preview_signin"]) in text
    # The main button goes to sign-up through the report's own form.
    assert re.search(r"name='go' value='signup'>\s*" + re.escape(BUTTON["es"]), text)
    # A locked preview: no PDF link.
    assert f"/audits/{audit_id}/pdf" not in text


@pytest.mark.parametrize("locale", ["en", "pt"])
def test_the_preview_speaks_the_report_language(tmp_path: Path, locale: str) -> None:
    app, _ = _app(tmp_path)
    visitor = _browser(app)
    sent = visitor.post(
        "/audits",
        files=_seeded_file(12),
        data={"consent": "on", "locale": locale},
        follow_redirects=False,
    )
    assert sent.status_code == 303 and "acct=anon_preview" in sent.headers["location"]
    text = visitor.get(sent.headers["location"]).text
    assert _escaped(account_pages.COPY[locale]["anon_preview"]) in text
    assert _escaped(BOX[locale]) in text and _escaped(BUTTON[locale]) in text


def test_the_upload_in_place_follows_the_same_way(tmp_path: Path) -> None:
    """With JavaScript the form posts for JSON and opens ``location``."""
    app, store = _app(tmp_path)
    visitor = _browser(app)
    sent = _upload(visitor, 13, headers={"Accept": "application/json"})
    assert sent.status_code == 201
    body = sent.json()
    assert LOCATION.match(body["location"])
    assert body["location"] == f"/audits/{body['audit_id']}?token={body['token']}&acct=anon_preview"
    assert visitor.cookies.get(DEVICE_COOKIE)
    record = store.get_audit(body["audit_id"])
    assert record is not None and not record.paid


def test_past_the_days_cap_the_upload_asks_for_the_account(tmp_path: Path) -> None:
    assert ANON_PREVIEWS_PER_NETWORK_PER_DAY == 2 and ANON_PREVIEWS_PER_IPV4_PER_DAY == 6
    assert network_cap("203.0.113.7", per_ip=2, per_ipv4=6) == 6
    assert network_cap("2001:db8:1:2::/64", per_ip=2, per_ipv4=6) == 2
    app, store = _app(tmp_path)
    visitor = _browser(app)
    # Five of the IPv4 address's six previews of the day are already used.
    now = datetime.now(UTC)
    slots = [
        f"anon:ip:{network_key('203.0.113.7')}:{claim_day(now)}:{n}"
        for n in range(ANON_PREVIEWS_PER_IPV4_PER_DAY)
    ]
    for n in range(ANON_PREVIEWS_PER_IPV4_PER_DAY - 1):
        assert store.claim_free(f"earlier-{n}", keys=(), slots={"network": slots}, at=now) == ""
    _anon_upload(visitor, 14)  # the sixth
    stored = _audits(store)
    refused = _upload(visitor, 15)
    assert refused.status_code == 401
    assert html.escape(account_pages.COPY["es"]["gate_signin_title"], quote=True) in refused.text
    assert f"{SIGNUP['es']}?next=" in refused.text
    assert _audits(store) == stored
    as_json = _upload(visitor, 15, headers={"Accept": "application/json"})
    assert as_json.status_code == 401 and as_json.json() == {"error": "free_tier_signin"}
    # Another network still has its own.
    _anon_upload(_browser(app, "198.51.100.20"), 15)


def test_an_ipv6_network_gets_two_a_day(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    phone = _browser(app, "2001:db8:1:2::5")
    _anon_upload(phone, 16)
    # Another address of the same /64 is the same network.
    _anon_upload(_browser(app, "2001:db8:1:2::99"), 17)
    assert _upload(phone, 18).status_code == 401
    assert _audits(store) == 2


def test_uploads_arriving_together_cannot_pass_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first look passes, the claim after parsing refuses: nothing is kept."""
    app, store = _app(tmp_path)
    now = datetime.now(UTC)
    slots = [
        f"anon:ip:{network_key('203.0.113.7')}:{claim_day(now)}:{n}"
        for n in range(ANON_PREVIEWS_PER_IPV4_PER_DAY)
    ]
    for n in range(ANON_PREVIEWS_PER_IPV4_PER_DAY):
        assert store.claim_free(f"other-{n}", keys=(), slots={"network": slots}, at=now) == ""
    monkeypatch.setattr(store, "free_claim_taken", lambda key: False)
    refused = _upload(_browser(app), 19)
    assert refused.status_code == 401
    assert _audits(store) == 0
    with store.engine.connect() as conn:
        held = conn.execute(store._sa.select(store.free_claims.c.reservation)).scalars().all()
    assert sorted(held) == sorted(f"other-{n}" for n in range(ANON_PREVIEWS_PER_IPV4_PER_DAY))


def test_cross_site_and_consent_still_hold(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    visitor = _browser(app)
    cross = _upload(visitor, 20, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    unconsented = visitor.post("/audits", files=_seeded_file(20), follow_redirects=False)
    assert unconsented.status_code == 400
    assert _audits(store) == 0


def test_a_working_code_still_asks_for_the_account(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    code, _ = store.create_access_code(credits=1, note="test", at=datetime.now(UTC))
    sent = _browser(app).post(
        "/audits",
        files=_seeded_file(21),
        data={"consent": "on", "access_code": code},
        follow_redirects=False,
    )
    assert sent.status_code == 401
    assert "no necesitas cuenta" not in sent.text
    assert _audits(store) == 0


# -- creating the account from the preview ---------------------------------------------
def test_signing_up_links_the_preview_and_confirming_opens_it(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    visitor = _browser(app)
    audit_id, token = _anon_upload(visitor, 31)
    next_path = _from_report(visitor, audit_id, token, "signup")
    made = _signup_from(visitor, next_path, "nueva@example.com")
    assert made.status_code == 303
    location = made.headers["location"]
    assert location.startswith(f"/audits/{audit_id}?token={token}&")
    assert "acct=welcome_confirm" in location
    account = store.find_account("nueva@example.com")
    assert account is not None and not store.email_verified(account.id)
    assert store.account_for_audit(audit_id) == account.id
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    # The pending row now belongs to the account, with the upload's own marks.
    (row,) = store.welcome_pending_for(account.id, since=datetime.now(UTC) - timedelta(days=8))
    assert row.audit_id == audit_id and store.anon_pending(audit_id) is None
    # Back on the report: what confirming opens, not an empty upload page's notice.
    page = visitor.get(location).text
    assert _escaped(account_pages.COPY["es"]["welcome_refused_unverified"]) in page
    assert _escaped(BOX["es"]) not in page

    confirmed = _confirm(app, store, account.id)
    assert "done=email_verified_report" in confirmed.headers["location"]
    record = store.get_audit(audit_id)
    assert record is not None and record.paid
    assert str(record.stripe_session_id).startswith(WELCOME_REFERENCE_PREFIX)
    assert store.welcome_used(account.id)
    counts = funnel.build(store.funnel_events(funnel.day_of(datetime.now(UTC)))).total.counts
    assert counts["anon_previews"] == 1 and counts["anon_linked"] == 1
    # The uploading browser made it the account's own report.
    assert [report.audit_id for report in store.account_audits_list(account.id) if report.own] == [
        audit_id
    ]


def test_without_confirmation_required_it_opens_at_sign_up(tmp_path: Path) -> None:
    app, store = _app(tmp_path, email_verification_required=False)
    visitor = _browser(app)
    audit_id, token = _anon_upload(visitor, 32)
    made = _signup_from(visitor, _from_report(visitor, audit_id, token, "signup"), "a@example.com")
    assert made.status_code == 303
    assert made.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es&acct=welcome"
    record = store.get_audit(audit_id)
    assert record is not None and record.paid
    assert str(record.stripe_session_id).startswith(WELCOME_REFERENCE_PREFIX)
    page = visitor.get(made.headers["location"]).text
    assert "Tu primer informe completo es gratis" in page


def test_the_same_file_or_browser_never_gets_a_second_free_report(tmp_path: Path) -> None:
    app, store = _app(tmp_path, email_verification_required=False)
    # The same file from two browsers on two networks: only the first account opens it.
    ana, beto = _browser(app, "203.0.113.10"), _browser(app, "198.51.100.11")
    ana_id, ana_token = _anon_upload(ana, 41)
    beto_id, beto_token = _anon_upload(beto, 41)
    first = _signup_from(ana, _from_report(ana, ana_id, ana_token, "signup"), "ana@example.com")
    assert first.headers["location"].endswith("&acct=welcome")
    second = _signup_from(
        beto, _from_report(beto, beto_id, beto_token, "signup"), "beto@example.com"
    )
    assert second.headers["location"].endswith("&acct=preview_file")
    opened, kept = store.get_audit(ana_id), store.get_audit(beto_id)
    assert opened is not None and opened.paid
    assert kept is not None and not kept.paid
    beto_account = store.find_account("beto@example.com")
    assert beto_account is not None and store.account_for_audit(beto_id) == beto_account.id
    assert not store.welcome_used(beto_account.id)

    # The same browser, another file and another account: the browser had its report.
    carla = _browser(app, "192.0.2.12")
    carla_id, carla_token = _anon_upload(carla, 42)
    made = _signup_from(
        carla, _from_report(carla, carla_id, carla_token, "signup"), "carla@example.com"
    )
    assert made.headers["location"].endswith("&acct=welcome")
    again = _browser(app, "192.0.2.13")
    again.cookies.set(DEVICE_COOKIE, str(carla.cookies.get(DEVICE_COOKIE)), domain="rigor.example")
    other_id, other_token = _anon_upload(again, 43)
    # The box no longer promises what signing up cannot give.
    page = again.get(f"/audits/{other_id}?token={other_token}&acct=anon_preview").text
    assert _escaped(BOX["es"]) not in page
    assert _escaped(account_pages.COPY["es"]["anon_box"]) in page
    refused = _signup_from(
        again, _from_report(again, other_id, other_token, "signup"), "carla2@example.com"
    )
    assert refused.headers["location"].endswith("&acct=preview_device")
    record = store.get_audit(other_id)
    assert record is not None and not record.paid


def test_signing_in_with_a_used_free_report_keeps_it_locked(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    owner = _browser(app, "198.51.100.30")
    page = owner.get("/registro").text
    owner.post(
        "/registro",
        data={"email": "usada@example.com", "password": PASSWORD, "csrf": _csrf(page)},
        follow_redirects=False,
    )
    account = store.find_account("usada@example.com")
    assert account is not None
    now = datetime.now(UTC)
    store.spend_welcome(account.id, at=now)
    _confirm(app, store, account.id)
    _, code = store.create_access_code(credits=1, note="test", at=now)
    store.link_code(account.id, code.id, at=now)

    visitor = _browser(app, "203.0.113.31")
    audit_id, token = _anon_upload(visitor, 51)
    entered = _signin_from(
        visitor, _from_report(visitor, audit_id, token, "signin"), "usada@example.com"
    )
    assert entered.status_code == 303
    assert entered.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"
    assert store.account_for_audit(audit_id) == account.id
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    report = visitor.get(entered.headers["location"]).text
    # As today: the credit on the account unlocks it, and a code can be typed.
    assert _escaped(account_pages.COPY["es"]["credit_button"]) in report
    assert f"/audits/{audit_id}/redeem" in report


def test_an_unconfirmed_account_that_signs_in_gets_it_on_confirming(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    first = _browser(app, "198.51.100.40")
    page = first.get("/registro").text
    first.post(
        "/registro",
        data={"email": "luego@example.com", "password": PASSWORD, "csrf": _csrf(page)},
        follow_redirects=False,
    )
    account = store.find_account("luego@example.com")
    assert account is not None
    visitor = _browser(app, "203.0.113.41")
    audit_id, token = _anon_upload(visitor, 52)
    entered = _signin_from(
        visitor, _from_report(visitor, audit_id, token, "signin"), "luego@example.com"
    )
    assert entered.headers["location"].endswith("&acct=preview_unverified")
    report = visitor.get(entered.headers["location"]).text
    assert _escaped(account_pages.COPY["es"]["welcome_refused_unverified"]) in report
    assert "done=email_verified_report" in _confirm(app, store, account.id).headers["location"]
    record = store.get_audit(audit_id)
    assert record is not None and record.paid


def test_a_report_with_an_owner_is_never_taken(tmp_path: Path) -> None:
    app, store = _app(tmp_path, email_verification_required=False)
    visitor = _browser(app, "203.0.113.50")
    audit_id, token = _anon_upload(visitor, 53)
    next_path = _from_report(visitor, audit_id, token, "signup")
    assert _signup_from(visitor, next_path, "uno@example.com").status_code == 303
    holder = store.account_for_audit(audit_id)
    # Someone else with the same link and key cookie signs up afterwards.
    other = _browser(app, "198.51.100.51")
    _from_report(other, audit_id, token, "signup")
    made = _signup_from(other, next_path, "dos@example.com")
    assert made.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"
    assert store.account_for_audit(audit_id) == holder


def test_a_wrong_key_links_nothing(tmp_path: Path) -> None:
    app, store = _app(tmp_path, email_verification_required=False)
    visitor = _browser(app, "203.0.113.52")
    audit_id, _ = _anon_upload(visitor, 54)
    visitor.cookies.set(REPORT_KEY_COOKIE, f"{audit_id}.{'x' * 43}", domain="rigor.example")
    _signup_from(visitor, f"/audits/{audit_id}?lang=es", "nadie@example.com")
    assert store.account_for_audit(audit_id) is None
    assert store.anon_pending(audit_id) is not None


# -- only the uploading browser takes it -----------------------------------------------
def _same_browser(app: Any, ip: str, device: str) -> TestClient:
    """A new tab without a session in the browser that holds ``device``."""
    client = _browser(app, ip)
    client.cookies.set(DEVICE_COOKIE, device, domain="rigor.example")
    return client


def _own(store: Store, account_id: str) -> list[str]:
    return [report.audit_id for report in store.account_audits_list(account_id) if report.own]


def _saved(store: Store, account_id: str) -> list[str]:
    return [report.audit_id for report in store.account_audits_list(account_id) if not report.own]


@pytest.mark.parametrize("confirmation", [False, True])
def test_another_browser_with_the_link_never_takes_the_free_report(
    tmp_path: Path, confirmation: bool
) -> None:
    app, store = _app(tmp_path, email_verification_required=confirmation)
    uploader = _browser(app, "203.0.113.7")
    audit_id, token = _anon_upload(uploader, 91)
    row = store.anon_pending(audit_id)
    assert row is not None
    reader = _browser(app, "198.51.100.50")
    # The reader is offered no free report: the usual box, and no promise.
    page = reader.get(f"/audits/{audit_id}?token={token}&acct=anon_preview").text
    assert _escaped(BOX["es"]) not in page and _escaped(BUTTON["es"]) not in page
    assert _escaped(account_pages.COPY["es"]["anon_box"]) in page
    assert _escaped(account_pages.COPY["es"]["anon_preview"]) not in page
    assert _escaped(account_pages.COPY["es"]["anon_preview_link"]) in page

    made = _signup_from(reader, _from_report(reader, audit_id, token, "signup"), "lee@example.com")
    assert made.status_code == 303
    location = made.headers["location"]
    assert location.startswith(f"/audits/{audit_id}?token={token}&lang=es")
    assert "acct=welcome&" not in location + "&" and "preview_" not in location
    reader_account = store.find_account("lee@example.com")
    assert reader_account is not None
    if confirmation:
        _confirm(app, store, reader_account.id)
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    assert store.account_for_audit(audit_id) is None
    assert not store.welcome_used(reader_account.id)
    # The pending row still waits for the uploader, with no account.
    still = store.anon_pending(audit_id)
    assert still is not None and still.account_id == ""
    # Nothing of the uploader's upload reaches the reader's data.
    data = reader.get("/cuenta/datos")
    assert data.status_code == 200
    assert "203.0.113.7" not in data.text and row.device_sha256 not in data.text
    assert row.file_sha256 not in data.text
    assert data.json()["free_first_report"] is None
    assert data.json()["free_first_report_pending"] == []

    # The uploader still opens it by creating the account from the report.
    opened = _signup_from(
        uploader, _from_report(uploader, audit_id, token, "signup"), "sube@example.com"
    )
    owner = store.find_account("sube@example.com")
    assert owner is not None and store.account_for_audit(audit_id) == owner.id
    if confirmation:
        assert "acct=welcome_confirm" in opened.headers["location"]
        _confirm(app, store, owner.id)
    else:
        assert opened.headers["location"].endswith("&acct=welcome")
    record = store.get_audit(audit_id)
    assert record is not None and record.paid
    assert _own(store, owner.id) == [audit_id]


def test_another_browser_saving_the_link_keeps_a_saved_preview(tmp_path: Path) -> None:
    app, store = _app(tmp_path, email_verification_required=False)
    uploader = _browser(app, "203.0.113.8")
    audit_id, token = _anon_upload(uploader, 92)
    reader = _browser(app, "198.51.100.52")
    page = reader.get("/registro").text
    reader.post(
        "/registro",
        data={"email": "guarda@example.com", "password": PASSWORD, "csrf": _csrf(page)},
        follow_redirects=False,
    )
    account = store.find_account("guarda@example.com")
    assert account is not None
    report = reader.get(f"/audits/{audit_id}?token={token}&lang=es").text
    saved = reader.post(
        f"/audits/{audit_id}/save",
        params={"token": token, "lang": "es"},
        data={"csrf": _csrf(report)},
        follow_redirects=False,
    )
    assert saved.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es&acct=saved"
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    assert _saved(store, account.id) == [audit_id] and _own(store, account.id) == []
    assert not store.welcome_used(account.id)
    still = store.anon_pending(audit_id)
    assert still is not None and still.account_id == ""
    assert "203.0.113.8" not in reader.get("/cuenta/datos").text


# -- an account's own uploads keep the month's previews ------------------------------
def test_an_account_past_its_previews_takes_previews_without_an_account_as_saved(
    tmp_path: Path,
) -> None:
    """The free report used, the previews linked from uploads without an account
    count as the month's: past the 3, a preview goes on the account as saved."""
    app, store = _app(tmp_path, email_verification_required=False)
    ip = "198.51.100.60"
    first = _browser(app, ip)
    page = first.get("/registro").text
    first.post(
        "/registro",
        data={"email": "tope@example.com", "password": PASSWORD, "csrf": _csrf(page)},
        follow_redirects=False,
    )
    account = store.find_account("tope@example.com")
    assert account is not None
    now = datetime.now(UTC)
    store.spend_welcome(account.id, at=now)
    device = str(first.cookies.get(DEVICE_COOKIE) or "")
    ids: list[str] = []
    for seed in range(101, 101 + FREE_PREVIEWS_PER_MONTH + 1):
        tab = _same_browser(app, ip, device) if device else _browser(app, ip)
        audit_id, token = _anon_upload(tab, seed)
        device = str(tab.cookies.get(DEVICE_COOKIE))
        entered = _signin_from(tab, _from_report(tab, audit_id, token, "signin"), account.email)
        assert entered.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"
        assert store.account_for_audit(audit_id) == account.id
        ids.append(audit_id)
    # The first three are its own uploads and its three previews of the month.
    assert set(_own(store, account.id)) == set(ids[:3])
    assert _saved(store, account.id) == [ids[3]]
    assert store.free_previews_since(month_start(now), account_id=account.id) == 3
    # And an upload signed in finds the month's previews used.
    signed_in = _same_browser(app, ip, device)
    _signin_from(signed_in, "/auditar", account.email)
    assert _upload(signed_in, 120).status_code == 402


# -- what the notice promises ----------------------------------------------------------
def _no_promise(page: str) -> None:
    assert _escaped(account_pages.COPY["es"]["anon_preview"]) not in page
    assert _escaped(account_pages.COPY["es"]["anon_preview_link"]) in page
    assert "se abren con una cuenta" not in page
    assert _escaped(BOX["es"]) not in page


def test_the_notice_promises_the_account_only_when_it_would_open_it(tmp_path: Path) -> None:
    app, store = _app(tmp_path, email_verification_required=False)
    # The same file already had its free report on another account.
    ana = _browser(app, "203.0.113.70")
    ana_id, ana_token = _anon_upload(ana, 121)
    page = ana.get(f"/audits/{ana_id}?token={ana_token}&acct=anon_preview").text
    assert _escaped(account_pages.COPY["es"]["anon_preview"]) in page
    assert "se abren con una cuenta" in html.unescape(page)
    _signup_from(ana, _from_report(ana, ana_id, ana_token, "signup"), "ana@example.com")
    beto = _browser(app, "198.51.100.71")
    beto_id, beto_token = _anon_upload(beto, 121)
    _no_promise(beto.get(f"/audits/{beto_id}?token={beto_token}&acct=anon_preview").text)

    # The network already had the month's free reports.
    now = datetime.now(UTC)
    with store.engine.begin() as conn:
        for n in range(10):
            conn.execute(
                store.welcome_reports.insert().values(
                    account_id=f"used{n}",
                    client_ip="192.0.2.77",
                    created_at=now.isoformat().replace("+00:00", "Z"),
                )
            )
    carla = _browser(app, "192.0.2.77")
    carla_id, carla_token = _anon_upload(carla, 122)
    _no_promise(carla.get(f"/audits/{carla_id}?token={carla_token}&acct=anon_preview").text)


def test_without_mail_the_preview_promises_nothing(tmp_path: Path) -> None:
    """Confirmation required and no way to send it: the box and the notice stay plain."""
    app, store = _app(tmp_path, resend_api_key="")
    visitor = _browser(app)
    audit_id, token = _anon_upload(visitor, 123)
    page = visitor.get(f"/audits/{audit_id}?token={token}&acct=anon_preview").text
    _no_promise(page)
    assert _escaped(account_pages.COPY["es"]["anon_box"]) in page


# -- an account made another way, then "save" --------------------------------------
@pytest.mark.parametrize("confirmation", [False, True])
def test_an_account_made_from_the_menu_takes_the_preview_on_saving(
    tmp_path: Path, confirmation: bool
) -> None:
    app, store = _app(tmp_path, email_verification_required=confirmation)
    visitor = _browser(app, "203.0.113.80")
    audit_id, token = _anon_upload(visitor, 124)
    page = visitor.get("/registro").text
    made = visitor.post(
        "/registro",
        data={"email": "menu@example.com", "password": PASSWORD, "csrf": _csrf(page)},
        follow_redirects=False,
    )
    assert made.status_code == 303 and "/audits/" not in made.headers["location"]
    account = store.find_account("menu@example.com")
    assert account is not None and store.account_for_audit(audit_id) is None
    # Signed in, the notice makes no promise: the box offers "save".
    report = visitor.get(f"/audits/{audit_id}?token={token}&lang=es&acct=anon_preview").text
    _no_promise(report)
    assert _escaped(account_pages.COPY["es"]["save_button"]) in report
    saved = visitor.post(
        f"/audits/{audit_id}/save",
        params={"token": token, "lang": "es"},
        data={"csrf": _csrf(report)},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    back = f"/audits/{audit_id}?token={token}&lang=es"
    assert store.account_for_audit(audit_id) == account.id
    assert _own(store, account.id) == [audit_id]
    if confirmation:
        assert saved.headers["location"] == f"{back}&acct=preview_unverified"
        shown = visitor.get(saved.headers["location"]).text
        assert _escaped(account_pages.COPY["es"]["welcome_refused_unverified"]) in shown
        record = store.get_audit(audit_id)
        assert record is not None and not record.paid
        _confirm(app, store, account.id)
    else:
        assert saved.headers["location"] == f"{back}&acct=welcome"
    record = store.get_audit(audit_id)
    assert record is not None and record.paid
    assert str(record.stripe_session_id).startswith(WELCOME_REFERENCE_PREFIX)
    assert store.welcome_used(account.id)


# -- the sign-up page and a code ---------------------------------------------------
def test_the_sign_up_page_asks_for_the_account_for_a_code_too() -> None:
    told = {
        "es": "código de acceso, entra en tu cuenta y escríbelo en el formulario.",
        "en": "access code, sign in to your account and type it in the form.",
        "pt": "código de acesso, entre na sua conta e digite-o no formulário.",
    }
    for locale, words in told.items():
        lead = account_pages.COPY[locale]["gate_signin_lead"]
        assert lead.endswith(words), lead
        for wrong in ("no necesitas cuenta", "you need no account", "não precisa de conta"):
            assert wrong not in lead
        assert find_claims(lead) == []
        page = account_pages.gate_page(
            locale=locale, reason="signin", limit=FREE_PREVIEWS_PER_MONTH
        )
        assert html.escape(words, quote=True) in page


# -- retention and the panel ---------------------------------------------------------
def test_the_preview_and_its_rows_follow_the_purge(tmp_path: Path) -> None:
    app, store = _app(tmp_path)
    visitor = _browser(app)
    purged_id, _ = _anon_upload(visitor, 61)
    deleted_id, _ = _anon_upload(visitor, 62)
    assert store.delete_audit(deleted_id)
    assert store.anon_pending(deleted_id) is None
    later = datetime.now(UTC) + timedelta(days=60)
    store.purge_expired(later, retention_days=30)
    record = store.get_audit(purged_id)
    assert record is not None and record.purged_at
    assert store.anon_pending(purged_id) is None
    with store.engine.connect() as conn:
        rows = conn.execute(store._sa.select(store.anon_previews)).all()
        claims = conn.execute(
            store._sa.select(store.free_claims.c.claim_key).where(
                store.free_claims.c.claim_key.like("anon:%")
            )
        ).all()
    assert rows == [] and claims == []


def test_the_panel_counts_previews_without_an_account(tmp_path: Path) -> None:
    app, store = _app(tmp_path, email_verification_required=False)
    visitor = _browser(app)
    visitor.cookies.set(funnel.REF_COOKIE, "f4", domain="rigor.example")
    audit_id, token = _anon_upload(visitor, 71)
    _anon_upload(_browser(app, "198.51.100.70"), 72)
    _signup_from(visitor, _from_report(visitor, audit_id, token, "signup"), "panel@example.com")
    built = funnel.build(store.funnel_events(funnel.day_of(datetime.now(UTC))))
    assert built.total.counts["anon_previews"] == 2
    assert built.total.counts["anon_linked"] == 1
    assert built.by_ref["f4"].counts["anon_previews"] == 1
    assert built.by_ref["f4"].counts["anon_linked"] == 1
    page = TestClient(app, base_url=BASE).post("/panel", data={"key": ADMIN_KEY}).text
    assert html.escape(OWNER_TEXT["funnel_anon"], quote=True) in page

    off, _ = _app(tmp_path / "off", anon_preview=False)
    page = TestClient(off, base_url=BASE).post("/panel", data={"key": ADMIN_KEY}).text
    assert html.escape(OWNER_TEXT["funnel_anon"], quote=True) not in page


# -- the texts -----------------------------------------------------------------------
def test_the_new_texts_say_the_same_in_three_languages_and_pass_the_guard() -> None:
    forbidden = re.compile(
        r"verificad|certificad|aprobad|garantiz|rentab|verified|certified|approved|guarantee"
        r"|profitable|lucrativ|aprovad",
        re.IGNORECASE,
    )
    texts: list[str] = []
    for locale in ("es", "en", "pt"):
        copy = account_pages.COPY[locale]
        assert copy["anon_preview_box"] == BOX[locale]
        assert copy["anon_preview_signup"] == BUTTON[locale]
        assert _COPY[locale]["anon_preview_note"] == NOTE[locale]
        texts += [copy[key] for key in NEW_KEYS] + [_COPY[locale]["anon_preview_note"]]
    texts += [OWNER_TEXT[key] for key in ("funnel_anon", "funnel_anon_cols", "funnel_anon_note")]
    texts += [funnel.STAGE_LABELS["anon_previews"], funnel.STAGE_LABELS["anon_linked"]]
    for text in texts:
        assert find_claims(text) == [], text
        assert not forbidden.search(text), text


# -- the switch off --------------------------------------------------------------------
def _forbidden(*_: Any, **__: Any) -> Any:
    raise AssertionError("a path of the switch was reached with the switch off")


def test_with_the_switch_off_everything_answers_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AUDIT_ANON_PREVIEW`` off: /auditar, POST /audits without a session,
    /registro, /entrar and the report answer byte for byte as on main, and no
    store path of the switch is reached."""
    assert AuditSettings().anon_preview is False
    assert AuditSettings.from_env({}).anon_preview is False
    assert AuditSettings.from_env({"AUDIT_ANON_PREVIEW": "true"}).anon_preview is True
    app, store = _app(tmp_path, anon_preview=False)
    for name in (
        "anon_pending",
        "welcome_pending_attach",
        "record_anon_preview",
        "note_anon_linked",
    ):
        monkeypatch.setattr(store, name, _forbidden)
    visitor = _browser(app)
    # The upload form sends a visitor without an account to sign-up first.
    for locale, form in FORMS.items():
        answer = visitor.get(form, follow_redirects=False)
        assert answer.status_code == 303 and answer.content == b""
        assert answer.headers["location"] == f"{SIGNUP[locale]}?next={form}"
    # An upload without a session gets the sign-in page, and nothing is stored.
    refused = _upload(visitor, 81)
    assert refused.status_code == 401
    assert refused.text == account_pages.gate_page(
        locale="es", reason="signin", limit=FREE_PREVIEWS_PER_MONTH
    )
    assert "set-cookie" not in refused.headers
    as_json = _upload(visitor, 81, headers={"Accept": "application/json"})
    assert as_json.status_code == 401 and as_json.json() == {"error": "free_tier_signin"}
    assert _audits(store) == 0
    # Sign-up and sign-in are the pages of always.
    signup = visitor.get("/registro")
    assert signup.text == account_pages.signup_page(
        retention_days=30,
        locale="es",
        csrf=_csrf(signup.text),
        next_path="",
        invite="",
        email_verification=True,
        offer="welcome",
    )
    signin = visitor.get("/entrar")
    assert signin.text == account_pages.signin_page(
        locale="es", csrf=_csrf(signin.text), flash="", next_path="", passkeys=True
    )
    # A report opened by its link: the usual box, and ``acct=anon_preview`` means nothing.
    made = visitor.post(
        "/registro",
        data={"email": "antes@example.com", "password": PASSWORD, "csrf": _csrf(signup.text)},
        follow_redirects=False,
    )
    assert made.status_code == 303
    sent = _upload(visitor, 82)
    assert sent.status_code == 303 and "acct=preview_unverified" in sent.headers["location"]
    audit_id = sent.headers["location"].split("/audits/")[1].split("?")[0]
    token = sent.headers["location"].split("token=")[1].split("&")[0]
    reader = _browser(app, "198.51.100.80")
    plain = reader.get(f"/audits/{audit_id}?token={token}")
    flagged = reader.get(f"/audits/{audit_id}?token={token}&acct=anon_preview")
    assert plain.status_code == flagged.status_code == 200
    assert plain.content == flagged.content
    box = account_pages.report_box(
        locale="es", state="anon", audit_id=audit_id, query=f"?token={token}&lang=es"
    )
    assert box in plain.text
    for key in NEW_KEYS:
        assert _escaped(account_pages.COPY["es"][key]) not in plain.text
    # Signing up from that report does not put it on the new account.
    next_path = _from_report(reader, audit_id, token, "signup")
    back = _signup_from(reader, next_path, "lector@example.com")
    assert back.headers["location"] == (
        f"/audits/{audit_id}?token={token}&lang=es&acct=welcome_confirm"
    )
    holder = store.find_account("antes@example.com")
    assert holder is not None and store.account_for_audit(audit_id) == holder.id


def test_the_off_switch_report_box_is_the_old_one() -> None:
    for locale in ("es", "en", "pt"):
        old = account_pages.report_box(locale=locale, state="anon", audit_id="a1", query="?t=1")
        assert "btn btn-dark btn-sm" in old
        assert _escaped(account_pages.COPY[locale]["anon_box"]) in old
        assert _escaped(account_pages.COPY[locale]["anon_signup"]) in old
        new = account_pages.report_box(
            locale=locale, state="anon", audit_id="a1", query="?t=1", anon_preview=True
        )
        assert _escaped(BOX[locale]) in new and _escaped(BUTTON[locale]) in new
