"""Accounts and e-mail before launch: plain addresses, resends that arrive, honest
notices, report keys out of ``next`` and the extra boxes kept through sign-up."""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_user_accounts import (  # noqa: E402
    KEY_SHAPE,
    NEW_PASSWORD,
    PASSWORD,
    _audit_id,
    _client,
    _code,
    _csrf,
    _make_recovery_key,
    _recover,
    _signin,
    _signup,
    _turn_on_two_step,
    _upload,
)

from quant_trade.audit import account_pages, mail  # noqa: E402
from quant_trade.audit.accounts import (  # noqa: E402
    REPORT_KEY_COOKIE,
    REPORT_KEY_MINUTES,
    hash_password,
    join_report_key,
    safe_next,
    simple_email,
    split_report_key,
    valid_email,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import upload_page  # noqa: E402
from quant_trade.audit.prop_presets import DEFAULT_PRESET  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
SITE = "https://rigor.example"
MAIL = {
    "base_url": SITE,
    "email_verification_required": True,
    "email_token_secret": "stable secret shared across replicas 1234567890",
    "smtp_host": "smtp.example",
    "smtp_from": "Rigor <hello@example.com>",
}
SIGNUP = {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}
SIGNIN = {"es": "/entrar", "en": "/login", "pt": "/pt/entrar"}
UPLOAD = {"es": "/auditar", "en": "/en/audit", "pt": "/pt/auditar"}
SIMPLE_WORDS = {
    "es": "Usa un correo simple",
    "en": "Use a plain e-mail address",
    "pt": "Use um e-mail simples",
}
ODD = "ana,luz@example.com"


# -- A1: plain addresses for new accounts ----------------------------------------
@pytest.mark.parametrize(
    "email",
    [
        "ana@example.com",
        "Ana.Perez@Example.COM",
        "a@b.co",
        "first.last+tag@mail.example.org",
        "user_name%x-y@sub-domain.example.mx",
        "x" * 64 + "@example.com",
        "ana@" + "a" * 63 + ".com",
        "ana@123.example.com",
        "  ana@example.com  ",
    ],
)
def test_a_plain_address_is_accepted(email: str) -> None:
    assert simple_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "",
        "ana",
        "ana@",
        "@example.com",
        "ana@example",
        "ana@@example.com",
        "ana@b@example.com",
        "ana,luz@example.com",
        "ana;luz@example.com",
        "ana:luz@example.com",
        '"ana"@example.com',
        "ana'luz@example.com",
        "ana`luz@example.com",
        "<ana@example.com>",
        "Ana <ana@example.com>",
        "ana(nota)@example.com",
        "ana[1]@example.com",
        "ana\\luz@example.com",
        "ana/luz@example.com",
        "ana luz@example.com",
        "ana\tluz@example.com",
        "ana\r\nBcc:x@example.com",
        "ana\x00@example.com",
        "josé@example.com",
        "ana@exämple.com",
        "ana＠example.com",
        ".ana@example.com",
        "ana.@example.com",
        "ana..luz@example.com",
        "x" * 65 + "@example.com",
        "ana@gmail..com",
        "ana@.example.com",
        "ana@example.com.",
        "ana@-gmail.com",
        "ana@gmail-.com",
        "ana@exa_mple.com",
        "ana@" + "a" * 64 + ".com",
        "ana@example.c",
        "ana@example.c0m",
        "ana@example.123",
        "ana@192.168.1.10",
        "ana@[192.168.1.10]",
        "ana@[IPv6:2001:db8::1]",
        "ana@" + ".".join(["a" * 60] * 5) + ".com",
    ],
)
def test_anything_else_is_not_a_plain_address(email: str) -> None:
    assert not simple_email(email)


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_sign_up_refuses_an_address_that_is_not_plain(tmp_path: Path, locale: str) -> None:
    client, store, _ = _client(tmp_path)
    for email in (ODD, "<ana@example.com>", "ana@gmail..com", "ana@192.168.1.10"):
        csrf = _csrf(client.get(SIGNUP[locale]).text)
        refused = client.post(
            SIGNUP[locale],
            data={"email": email, "password": PASSWORD, "csrf": csrf},
            follow_redirects=False,
        )
        assert refused.status_code == 400, email
        assert SIMPLE_WORDS[locale] in refused.text
        assert not find_claims(re.sub(r"<[^>]+>", " ", refused.text))
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        assert conn.execute(store.accounts.select()).all() == []  # type: ignore[attr-defined]


def test_the_checks_after_the_plain_address_rule_still_answer(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)

    def post(email: str, **more: str):
        csrf = _csrf(client.get("/registro").text)
        return client.post(
            "/registro",
            data={"email": email, "password": PASSWORD, "csrf": csrf, **more},
            follow_redirects=False,
        )

    assert "buzones temporales" in post("ana@mailinator.com").text
    typo = post("ana@gmial.com")
    assert typo.status_code == 200 and "ana@gmail.com" in typo.text
    # "My address is the one I typed" is held to the same rule.
    kept = post("ana@gmail.com", email_as_typed="ana,luz@gmial.com")
    assert kept.status_code == 400 and SIMPLE_WORDS["es"] in kept.text
    assert post("ana@example.com").status_code == 303
    assert store.find_account("ana@example.com") is not None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("prefix", "locale"), [("/cuenta", "es"), ("/account", "en"), ("/pt/conta", "pt")]
)
def test_an_email_change_refuses_an_address_that_is_not_plain(
    tmp_path: Path, prefix: str, locale: str
) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    csrf = _csrf(client.get(prefix).text)
    refused = client.post(
        f"{prefix}/correo",
        data={"email": ODD, "email_again": ODD, "current": PASSWORD, "csrf": csrf},
        follow_redirects=False,
    )
    assert refused.status_code == 303
    assert refused.headers["location"] == f"{prefix}?error=email_simple"
    assert SIMPLE_WORDS[locale] in client.get(refused.headers["location"]).text
    assert store.find_account("ana@example.com") is not None  # type: ignore[attr-defined]
    assert store.find_account(ODD) is None  # type: ignore[attr-defined]


def test_an_older_account_with_an_odd_address_still_signs_in_and_recovers(
    tmp_path: Path,
) -> None:
    client, store, _ = _client(tmp_path)
    assert valid_email(ODD) and not simple_email(ODD)
    account = store.create_account(  # type: ignore[attr-defined]
        email=ODD, password_hash=hash_password(PASSWORD), locale="es", at=NOW
    )
    assert account is not None
    signed = _signin(client, ODD)
    assert signed.status_code == 303 and signed.headers["location"] == "/cuenta"
    assert client.get("/cuenta").status_code == 200
    match = KEY_SHAPE.search(_make_recovery_key(client).text)
    assert match is not None
    other = TestClient(client.app)
    recovered = _recover(other, ODD, match.group(1))
    assert recovered.status_code == 303 and "done=recovered" in recovered.headers["location"]
    assert _signin(other, ODD, NEW_PASSWORD).status_code == 303


def test_a_reset_link_is_still_queued_for_an_older_odd_address(tmp_path: Path) -> None:
    client, store, cfg = _client(tmp_path, **MAIL)
    client = TestClient(client.app, base_url=SITE)
    account = store.create_account(  # type: ignore[attr-defined]
        email=ODD, password_hash=hash_password(PASSWORD), locale="es", at=NOW
    )
    assert account is not None and cfg.email_delivery_ready
    _verify(store, account.id, ODD)
    csrf = _csrf(client.get("/olvide").text)
    asked = client.post("/olvide/enlace", data={"email": ODD, "csrf": csrf}, follow_redirects=False)
    assert asked.status_code == 303
    rows = _outbox(store)
    assert [(row["kind"], row["email"]) for row in rows] == [("reset", ODD)]


# -- A2: a resend the customer asks for is a new message ----------------------------
def _mail_settings(tmp_path: Path, **extra: Any) -> AuditSettings:
    values: dict[str, Any] = {
        "database_url": f"sqlite:///{tmp_path}/mail.db",
        "bootstrap_samples": 100,
        "free_mode": False,
        **MAIL,
    }
    values.update(extra)
    return AuditSettings(**values)


def _verify(store: Any, account_id: str, email: str) -> None:
    with store.engine.begin() as conn:
        conn.execute(
            store.verified_emails.insert().values(
                account_id=account_id, email=email, verified_at=NOW.isoformat()
            )
        )


def _outbox(store: Any) -> list[dict[str, Any]]:
    with store.engine.connect() as conn:
        rows = conn.execute(
            store.email_outbox.select().order_by(store.email_outbox.c.created_at)
        ).mappings()
        return [dict(row) for row in rows]


def _ask(store: Any, kind: str, account_id: str, at: datetime) -> None:
    """What the customer's button does for each kind of message."""
    if kind == "verify":
        store.request_email_verification(account_id, at=at)
    elif kind == "reset":
        store.request_email_reset("ana@example.com", locale="es", at=at)
    else:
        outcome = store.request_email_change(account_id, "nueva@example.com", locale="es", at=at)
        assert outcome == "pending"


def _account_for(store: Any, kind: str) -> str:
    account = store.create_account(
        email="ana@example.com", password_hash="unused", locale="es", at=NOW
    )
    assert account is not None
    if kind != "verify":
        _verify(store, account.id, "ana@example.com")
    return str(account.id)


def _deliver(store: Any, cfg: AuditSettings, at: datetime) -> list[EmailMessage]:
    sent: list[EmailMessage] = []
    mail.deliver_pending(store, cfg, sender=lambda message, _: sent.append(message), now=at)
    return sent


def _link(message: EmailMessage) -> str:
    match = re.search(r"https://\S+", message.get_content())
    assert match is not None
    return match.group(0)


def _idempotency_key(message: EmailMessage, cfg: AuditSettings) -> str:
    """The key Resend would get, with the network call replaced by a fake."""
    seen: list[Any] = []

    class _Answer:
        status = 200

        def __enter__(self) -> _Answer:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def opener(request: Any, **_: Any) -> _Answer:
        seen.append(request)
        return _Answer()

    ready = dataclasses.replace(cfg, resend_api_key="re_test_0123456789abcdefghij")
    mail.send_resend(message, ready, opener=opener)
    return str(seen[0].get_header("Idempotency-key"))


@pytest.mark.parametrize("kind", ["verify", "change", "reset"])
def test_a_resend_the_customer_asks_for_is_a_new_message_with_the_same_link(
    tmp_path: Path, kind: str
) -> None:
    cfg = _mail_settings(tmp_path)
    store = make_store(cfg.database_url)
    account_id = _account_for(store, kind)
    _ask(store, kind, account_id, NOW)
    first = _deliver(store, cfg, NOW)
    assert len(first) == 1
    row = _outbox(store)[0]
    assert first[0]["Message-ID"] == f"<rigor-{row['id']}@example.com>"

    # Asked again too soon: the ten-minute spacing stays, nothing is sent.
    soon = NOW + timedelta(minutes=9)
    _ask(store, kind, account_id, soon)
    assert _deliver(store, cfg, soon) == []

    later = NOW + timedelta(minutes=11)
    _ask(store, kind, account_id, later)
    second = _deliver(store, cfg, later)
    assert len(second) == 1
    assert second[0]["Message-ID"] != first[0]["Message-ID"]
    assert _idempotency_key(second[0], cfg) != _idempotency_key(first[0], cfg)
    # The same challenge and link: nothing new to guess, the same expiry.
    assert _link(second[0]) == _link(first[0])
    after = _outbox(store)
    assert len(after) == 1 and after[0]["id"] == row["id"]
    assert after[0]["expires_at"] == row["expires_at"]

    # A third message differs from both.
    again = later + timedelta(minutes=11)
    _ask(store, kind, account_id, again)
    third = _deliver(store, cfg, again)
    assert len(third) == 1
    ids = {str(message["Message-ID"]) for message in (*first, *second, *third)}
    assert len(ids) == 3


def test_automatic_retries_of_one_message_keep_its_key(tmp_path: Path) -> None:
    cfg = _mail_settings(tmp_path)
    store = make_store(cfg.database_url)
    account_id = _account_for(store, "verify")
    _ask(store, "verify", account_id, NOW)
    tried: list[str] = []

    def fail(message: EmailMessage, _settings: AuditSettings) -> None:
        tried.append(str(message["Message-ID"]))
        raise OSError("fake outage")

    at = NOW
    for _ in range(3):
        assert mail.deliver_pending(store, cfg, sender=fail, now=at) == 0
        at += timedelta(hours=2)
    first = _deliver(store, cfg, at)
    assert len(first) == 1 and len(tried) == 3
    assert set(tried) == {str(first[0]["Message-ID"])}

    # The same holds for the retries of a resend: one key, not the first one.
    at += timedelta(minutes=11)
    _ask(store, "verify", account_id, at)
    tried.clear()
    for _ in range(2):
        assert mail.deliver_pending(store, cfg, sender=fail, now=at) == 0
        at += timedelta(hours=2)
    second = _deliver(store, cfg, at)
    assert len(second) == 1 and len(tried) == 2
    assert set(tried) == {str(second[0]["Message-ID"])}
    assert second[0]["Message-ID"] != first[0]["Message-ID"]


def test_a_resend_works_after_the_tries_of_the_first_message_were_used(tmp_path: Path) -> None:
    cfg = _mail_settings(tmp_path)
    store = make_store(cfg.database_url)
    account_id = _account_for(store, "verify")
    _ask(store, "verify", account_id, NOW)

    def fail(_message: EmailMessage, _settings: AuditSettings) -> None:
        raise OSError("fake outage")

    at = NOW
    for _ in range(7):
        assert mail.deliver_pending(store, cfg, sender=fail, now=at) == 0
        at += timedelta(hours=2)
    # The eighth and last try gets through.
    assert len(_deliver(store, cfg, at)) == 1
    row = _outbox(store)[0]
    assert row["status"] == "sent" and row["attempts"] == 8
    at += timedelta(minutes=11)
    _ask(store, "verify", account_id, at)
    assert _outbox(store)[0]["attempts"] == 0
    assert len(_deliver(store, cfg, at)) == 1


def test_a_message_left_waiting_by_an_older_resend_is_sent(tmp_path: Path) -> None:
    cfg = _mail_settings(tmp_path)
    store = make_store(cfg.database_url)
    account_id = _account_for(store, "verify")
    _ask(store, "verify", account_id, NOW)
    assert len(_deliver(store, cfg, NOW)) == 1
    # As the earlier code left it: queued again with every try already counted.
    with store.engine.begin() as conn:
        conn.execute(store.email_outbox.update().values(status="queued", attempts=8))
    at = NOW + timedelta(minutes=1)
    assert _deliver(store, cfg, at) == []
    _ask(store, "verify", account_id, at)
    assert len(_deliver(store, cfg, at)) == 1


def test_asking_again_after_a_message_died_makes_a_new_challenge(tmp_path: Path) -> None:
    cfg = _mail_settings(tmp_path)
    store = make_store(cfg.database_url)
    account_id = _account_for(store, "verify")
    _ask(store, "verify", account_id, NOW)

    def fail(_message: EmailMessage, _settings: AuditSettings) -> None:
        raise OSError("fake outage")

    at = NOW
    for _ in range(8):
        assert mail.deliver_pending(store, cfg, sender=fail, now=at) == 0
        at += timedelta(hours=2)
    dead = _outbox(store)[0]
    assert dead["status"] == "dead"
    assert _deliver(store, cfg, at) == []
    _ask(store, "verify", account_id, at)
    sent = _deliver(store, cfg, at)
    assert len(sent) == 1
    rows = _outbox(store)
    assert len(rows) == 2 and rows[1]["id"] != dead["id"]
    token = parse_qs(urlsplit(_link(sent[0])).query)["token"][0]
    assert mail.challenge_from_token(token, cfg.email_token_secret) == rows[1]["id"]


def test_the_resend_button_sends_a_second_message(tmp_path: Path) -> None:
    client, store, cfg = _client(tmp_path, **MAIL)
    client = TestClient(client.app, base_url=SITE)
    _signup(client)
    first = _deliver(store, cfg, datetime.now(UTC))
    assert len(first) == 1
    with store.engine.begin() as conn:  # type: ignore[attr-defined]
        # The first message left eleven minutes ago.
        sent_at = (datetime.now(UTC) - timedelta(minutes=11)).isoformat().replace("+00:00", "Z")
        conn.execute(store.email_outbox.update().values(sent_at=sent_at))  # type: ignore[attr-defined]
    csrf = _csrf(client.get("/cuenta").text)
    asked = client.post("/cuenta/verificar-correo", data={"csrf": csrf}, follow_redirects=False)
    assert asked.status_code == 303 and "done=email_verification_sent" in asked.headers["location"]
    second = _deliver(store, cfg, datetime.now(UTC))
    assert len(second) == 1
    assert second[0]["Message-ID"] != first[0]["Message-ID"]
    assert _link(second[0]) == _link(first[0])


# -- A3: honest notices while confirmation is required ----------------------------
STALE = ("sigue disponible", "still available", "continua disponível")
UNLOCKS = {
    "es": "Confírmalo para desbloquear tu primer informe completo gratis",
    "en": "Confirm it to unlock your first free full report",
    "pt": "Confirme-o para liberar seu primeiro relatório completo gratuito",
}
SENT = {
    "es": ("Te enviamos un enlace de confirmación a tu correo", "spam"),
    "en": ("We sent a confirmation link to your e-mail", "spam"),
    "pt": ("Enviamos um link de confirmação para o seu e-mail", "spam"),
}


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_sign_up_says_a_confirmation_link_was_sent(tmp_path: Path, locale: str) -> None:
    client, _store, _ = _client(tmp_path, **MAIL)
    client = TestClient(client.app, base_url=SITE)
    csrf = _csrf(client.get(SIGNUP[locale]).text)
    done = client.post(
        SIGNUP[locale],
        data={"email": "ana@example.com", "password": PASSWORD, "csrf": csrf},
        follow_redirects=False,
    )
    assert done.status_code == 303 and done.headers["location"].endswith("?done=welcome_confirm")
    page = client.get(done.headers["location"]).text
    for words in SENT[locale]:
        assert words in page
    # The account card no longer offers the free report to an unconfirmed address.
    assert UNLOCKS[locale] in page
    assert not any(words in page for words in STALE)
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))


def test_sign_up_keeps_its_notice_without_confirmation_or_without_mail(tmp_path: Path) -> None:
    plain, _, _ = _client(tmp_path / "a")
    done = _signup(plain)
    assert done.headers["location"] == "/cuenta?done=welcome"
    page = plain.get(done.headers["location"]).text
    assert "Cuenta creada. Ya puedes subir un archivo" in page
    assert SENT["es"][0] not in page
    # Confirmation required but no way to send: no link is promised.
    no_mail = {**MAIL, "smtp_host": ""}
    silent, _, cfg = _client(tmp_path / "b", **no_mail)
    assert cfg.email_verification_required and not cfg.email_delivery_ready
    silent = TestClient(silent.app, base_url=SITE)
    done = _signup(silent)
    assert done.headers["location"] == "/cuenta?done=welcome"
    page = silent.get(done.headers["location"]).text
    assert SENT["es"][0] not in page and not any(words in page for words in STALE)
    assert "requieren confirmar el correo" in page


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_checkout_refusal_does_not_offer_the_free_report(locale: str) -> None:
    text = account_pages.COPY[locale]["email_checkout_required"]
    assert not any(words in text for words in STALE)
    assert not find_claims(text)
    for key in ("email_unverified_status", "email_delivery_unavailable", "welcome_confirm"):
        assert not any(words in account_pages.COPY[locale][key] for words in STALE)
        assert not find_claims(account_pages.COPY[locale][key])


# -- A4: a report's key never travels inside next -----------------------------------
def test_the_report_key_moves_between_next_and_its_cookie() -> None:
    token = "t" * 43
    with_key = f"/audits/abc123?token={token}&lang=es"
    assert split_report_key(with_key) == ("/audits/abc123?lang=es", f"abc123.{token}")
    assert join_report_key("/audits/abc123?lang=es", f"abc123.{token}") == with_key
    assert split_report_key(f"/audits/abc123/pdf?lang=en&TOKEN={token}") == (
        "/audits/abc123/pdf?lang=en",
        f"abc123.{token}",
    )
    # Nothing to take out, nothing to keep.
    for path in ("", "/cuenta", "/auditar?extras=1", "/audits/abc123?lang=es"):
        assert split_report_key(path) == (path, "")
    # A token no report has is dropped, not kept.
    assert split_report_key("/audits/abc123?token=x&lang=es") == ("/audits/abc123?lang=es", "")
    # The cookie adds the key to its own report and changes nothing else.
    kept = f"abc123.{token}"
    assert join_report_key("/audits/other?lang=es", kept) == "/audits/other?lang=es"
    assert join_report_key("/cuenta", kept) == "/cuenta"
    assert join_report_key("", kept) == ""
    assert join_report_key(with_key, f"abc123.{'z' * 43}") == with_key
    for bad in (None, "", "abc123", f"abc123.{token}.x", "abc123.short", f"//evil.example.{token}"):
        assert join_report_key("/audits/abc123?lang=es", bad) == "/audits/abc123?lang=es"
    # Whatever the cookie says, the address stays a path on this service.
    for cookie in (f"abc123.{token}", f"evil.example.{token}", "https://evil.example/x"):
        target = join_report_key(safe_next("/audits/abc123?lang=es"), cookie)
        assert safe_next(target) == target and target.startswith("/audits/abc123?")


def _shared_report(tmp_path: Path, **extra: object) -> tuple[TestClient, Any, str, str]:
    """A report someone uploaded, and a visitor who only has its link."""
    client, store, _ = _client(tmp_path, **extra)
    _signup(client, "uploader@example.com")
    location = _upload(client).headers["location"]
    token = parse_qs(urlsplit(location).query)["token"][0]
    return client, store, _audit_id(location), token


def _set_cookies(response: Any) -> list[str]:
    return [value for name, value in response.headers.multi_items() if name == "set-cookie"]


def _kept(response: Any) -> str:
    found = [item for item in _set_cookies(response) if item.startswith(REPORT_KEY_COOKIE + "=")]
    assert len(found) == 1, "the report key goes into its own cookie"
    return found[0]


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("go", ["signup", "signin"])
def test_a_visitor_with_a_report_link_signs_up_or_in_and_comes_back(
    tmp_path: Path, locale: str, go: str
) -> None:
    client, store, audit_id, token = _shared_report(tmp_path)
    visitor = TestClient(client.app)
    if go == "signin":
        _signup(visitor, "visita@example.com")
        visitor.cookies.clear()
    report = visitor.get(f"/audits/{audit_id}?token={token}&lang={locale}")
    assert report.status_code == 200
    assert "next=" not in report.text and "set-cookie" not in report.headers
    action = f"/audits/{audit_id}/account?token={token}&amp;lang={locale}"
    assert f"<form method='post' action='{action}'>" in report.text
    assert "name='go' value='signup'" in report.text
    assert "name='go' value='signin'" in report.text

    start = visitor.post(
        f"/audits/{audit_id}/account?token={token}&lang={locale}",
        data={"go": go},
        follow_redirects=False,
    )
    assert start.status_code == 303
    where = start.headers["location"]
    pages = SIGNUP if go == "signup" else SIGNIN
    assert urlsplit(where).path == pages[locale]
    assert parse_qs(urlsplit(where).query)["next"] == [f"/audits/{audit_id}?lang={locale}"]
    assert token not in where and token not in unquote(unquote(where))
    cookie = _kept(start)
    assert f"{REPORT_KEY_COOKIE}={audit_id}.{token};" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert f"Max-Age={REPORT_KEY_MINUTES * 60}" in cookie

    form = visitor.get(where)
    assert form.status_code == 200 and token not in form.text
    assert f"name='next' value='/audits/{audit_id}?lang={locale}'" in form.text
    email = "nueva@example.com" if go == "signup" else "visita@example.com"
    done = visitor.post(
        pages[locale],
        data={
            "email": email,
            "password": PASSWORD,
            "csrf": _csrf(form.text),
            "next": f"/audits/{audit_id}?lang={locale}",
        },
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert done.headers["location"] == f"/audits/{audit_id}?token={token}&lang={locale}"
    # Used once: the cookie is cleared with the sign-in.
    assert 'rigor_report="";' in _kept(done) or "rigor_report=;" in _kept(done)
    assert "Max-Age=0" in _kept(done)
    assert visitor.cookies.get(REPORT_KEY_COOKIE) is None
    assert visitor.get(done.headers["location"]).status_code == 200
    assert store.find_account(email) is not None


def test_report_forms_send_a_visitor_to_sign_in_without_the_key(tmp_path: Path) -> None:
    client, _store, audit_id, token = _shared_report(tmp_path)
    for path, data in (
        ("save", {"csrf": "x"}),
        ("credit", {"csrf": "x"}),
        ("redeem", {"code": "AUD-XXXX-XXXX-XXXX"}),
    ):
        visitor = TestClient(client.app)
        sent = visitor.post(
            f"/audits/{audit_id}/{path}?token={token}&lang=es", data=data, follow_redirects=False
        )
        assert sent.status_code == 303, path
        where = sent.headers["location"]
        assert where == f"/entrar?next=%2Faudits%2F{audit_id}%3Flang%3Des", path
        assert f"{REPORT_KEY_COOKIE}={audit_id}.{token};" in _kept(sent)
        _signup(visitor, f"{path}@example.com")
        visitor.cookies.delete("rigor_session")
        visitor.cookies.set(REPORT_KEY_COOKIE, f"{audit_id}.{token}")
        back = _signin_with_next(visitor, f"{path}@example.com", f"/audits/{audit_id}?lang=es")
        assert back.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"


def _signin_with_next(client: TestClient, email: str, next_path: str):
    csrf = _csrf(client.get("/entrar").text)
    return client.post(
        "/entrar",
        data={"email": email, "password": PASSWORD, "csrf": csrf, "next": next_path},
        follow_redirects=False,
    )


def test_the_key_survives_the_second_step(tmp_path: Path) -> None:
    client, _store, audit_id, token = _shared_report(tmp_path)
    owner = TestClient(client.app)
    _signup(owner, "ana@example.com")
    secret = _turn_on_two_step(owner)
    visitor = TestClient(client.app)
    start = visitor.post(
        f"/audits/{audit_id}/account?token={token}&lang=es",
        data={"go": "signin"},
        follow_redirects=False,
    )
    assert start.status_code == 303
    step = _signin_with_next(visitor, "ana@example.com", f"/audits/{audit_id}?lang=es")
    assert step.headers["location"] == f"/entrar/codigo?next=%2Faudits%2F{audit_id}%3Flang%3Des"
    page = visitor.get(step.headers["location"])
    assert page.status_code == 200 and token not in page.text
    done = visitor.post(
        "/entrar/codigo",
        data={
            "code": _code(secret, 1),
            "csrf": _csrf(page.text),
            "next": f"/audits/{audit_id}?lang=es",
        },
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert done.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"
    assert visitor.cookies.get(REPORT_KEY_COOKIE) is None


def test_the_key_survives_a_passkey_sign_in(tmp_path: Path) -> None:
    pytest.importorskip("webauthn")
    pytest.importorskip("cbor2")
    from test_audit_passkeys import ORIGIN, Device, _add_passkey, _options

    client, _store, audit_id, token = _shared_report(tmp_path, base_url=ORIGIN)
    owner = TestClient(client.app)
    _signup(owner, "ana@example.com")
    device = Device()
    assert "done=passkey_added" in _add_passkey(owner, device)
    visitor = TestClient(client.app)
    start = visitor.post(
        f"/audits/{audit_id}/account?token={token}&lang=es",
        data={"go": "signin"},
        follow_redirects=False,
    )
    form = visitor.get(start.headers["location"])
    next_path = f"/audits/{audit_id}?lang=es"
    page = visitor.post(
        "/entrar/llave",
        data={"csrf": _csrf(form.text), "next": next_path},
        follow_redirects=False,
    )
    assert page.status_code == 200 and token not in page.text
    options, action = _options(page.text)
    done = visitor.post(
        action,
        data={"credential": device.get(options), "csrf": _csrf(page.text), "next": next_path},
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert done.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"
    assert visitor.cookies.get(REPORT_KEY_COOKIE) is None


@pytest.mark.parametrize("page", ["/entrar", "/registro", "/login", "/pt/cadastro"])
def test_an_older_link_with_the_key_inside_next_is_cleaned(tmp_path: Path, page: str) -> None:
    client, _store, audit_id, token = _shared_report(tmp_path)
    visitor = TestClient(client.app)
    old = f"{page}?next=%2Faudits%2F{audit_id}%3Ftoken%3D{token}%26lang%3Des"
    moved = visitor.get(old, follow_redirects=False)
    assert moved.status_code == 303
    assert moved.headers["location"] == f"{page}?next=%2Faudits%2F{audit_id}%3Flang%3Des"
    assert f"{REPORT_KEY_COOKIE}={audit_id}.{token};" in _kept(moved)
    shown = visitor.get(moved.headers["location"], follow_redirects=False)
    assert shown.status_code == 200 and token not in shown.text


def test_the_cookie_cannot_send_a_sign_in_anywhere_else(tmp_path: Path) -> None:
    client, _store, audit_id, token = _shared_report(tmp_path)
    for cookie, next_path, target in (
        (f"{audit_id}.{token}", "/cuenta/datos", "/cuenta/datos"),
        (f"{audit_id}.{token}", "/audits/another?lang=es", "/audits/another?lang=es"),
        ("https://evil.example/x", f"/audits/{audit_id}?lang=es", f"/audits/{audit_id}?lang=es"),
        (f"//evil.example.{token}", f"/audits/{audit_id}?lang=es", f"/audits/{audit_id}?lang=es"),
        (f"{audit_id}.{token}", "https://evil.example/", "/cuenta"),
    ):
        visitor = TestClient(client.app)
        _signup(visitor, "ana@example.com")
        visitor.cookies.delete("rigor_session")
        visitor.cookies.set(REPORT_KEY_COOKIE, cookie)
        done = _signin_with_next(visitor, "ana@example.com", next_path)
        assert done.status_code == 303 and done.headers["location"] == target
        # Whatever it held, it does not outlive the sign-in.
        assert "Max-Age=0" in _kept(done)


# -- A5: the extra boxes stay chosen through sign-up ----------------------------------
def test_next_accepts_the_upload_pages_with_extras_and_nothing_wider() -> None:
    for page in UPLOAD.values():
        assert safe_next(page) == page
        assert safe_next(f"{page}?extras=1") == f"{page}?extras=1"
        for bad in (
            f"{page}?extras=2",
            f"{page}?extras=1&x=1",
            f"{page}?x=1&extras=1",
            f"{page}?extras=1&extras=1",
            f"{page}?extras=1#subir",
            f"{page}?EXTRAS=1",
            f"{page}?extras=1%26x",
            f"{page}?next=https://evil.example",
            f"{page}/?extras=1",
            f"/{page}?extras=1",
            f"https://evil.example{page}?extras=1",
        ):
            assert safe_next(bad) == "", bad
    assert safe_next("/?extras=1") == "" and safe_next("/en?extras=1") == ""


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("go", ["signup", "signin"])
def test_a_visitor_who_chose_extras_finds_them_open_after_the_account(
    tmp_path: Path, locale: str, go: str
) -> None:
    client, _store, _ = _client(tmp_path)
    if go == "signin":
        _signup(client, "ana@example.com")
        client.cookies.clear()
    landing = {"es": "/?extras=1", "en": "/en?extras=1", "pt": "/pt?extras=1"}[locale]
    first = client.get(landing, follow_redirects=False)
    assert first.headers["location"] == f"{UPLOAD[locale]}?extras=1"
    sent = client.get(first.headers["location"], follow_redirects=False)
    assert sent.status_code == 303
    assert sent.headers["location"] == f"{SIGNUP[locale]}?next={UPLOAD[locale]}%3Fextras%3D1"
    form = client.get(sent.headers["location"])
    kept = f"?next={UPLOAD[locale]}%3Fextras%3D1"
    # The other tab and the language switch keep the choice too.
    assert f"href='{SIGNIN[locale]}{kept}'" in form.text
    assert f"name='next' value='{UPLOAD[locale]}?extras=1'" in form.text
    pages = SIGNUP if go == "signup" else SIGNIN
    form = client.get(f"{pages[locale]}{kept}")
    done = client.post(
        pages[locale],
        data={
            "email": "ana@example.com",
            "password": PASSWORD,
            "csrf": _csrf(form.text),
            "next": f"{UPLOAD[locale]}?extras=1",
        },
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert done.headers["location"] == f"{UPLOAD[locale]}?extras=1"
    page = client.get(done.headers["location"])
    assert page.status_code == 200 and "<details class='adv extras' open>" in page.text


def test_without_extras_the_upload_page_asks_for_the_account_as_before(tmp_path: Path) -> None:
    client, _store, _ = _client(tmp_path)
    for locale, page in UPLOAD.items():
        sent = client.get(page, follow_redirects=False)
        assert sent.headers["location"] == f"{SIGNUP[locale]}?next={page}"
        assert client.get(f"{page}?extras=0", follow_redirects=False).headers["location"] == (
            f"{SIGNUP[locale]}?next={page}"
        )


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_gate_and_the_language_switch_keep_the_extras(locale: str) -> None:
    chosen = account_pages.gate_page(locale=locale, reason="signin", limit=3, extras=True)
    kept = f"?next={UPLOAD[locale]}%3Fextras%3D1"
    assert f"href='{SIGNUP[locale]}{kept}'" in chosen
    assert f"href='{SIGNIN[locale]}{kept}'" in chosen
    plain = account_pages.gate_page(locale=locale, reason="signin", limit=3)
    assert f"href='{SIGNUP[locale]}?next={UPLOAD[locale]}'" in plain and "extras" not in plain

    opened = upload_page(locale=locale, free_mode=True, extras_open=True)
    closed = upload_page(locale=locale, free_mode=True)
    for other, page in UPLOAD.items():
        if other != locale:
            assert f"href='{page}?extras=1'" in opened
            assert f"href='{page}'" in closed and f"href='{page}?extras=1'" not in closed


def test_an_upload_without_account_that_used_an_extra_box_comes_back_to_them(
    tmp_path: Path,
) -> None:
    client, _store, _ = _client(tmp_path)
    refused = _upload(client, challenge="ftmo-2step-100k")
    assert refused.status_code == 401
    assert "href='/registro?next=/auditar%3Fextras%3D1'" in refused.text
    # A browser always sends the list's first choice: that alone opens nothing.
    for data in ({}, {"challenge": DEFAULT_PRESET}, {"challenge": " "}):
        plain = _upload(client, **data)
        assert plain.status_code == 401
        assert "href='/registro?next=/auditar'" in plain.text and "extras" not in plain.text


def test_a_signed_in_visitor_sent_to_sign_in_goes_straight_back(tmp_path: Path) -> None:
    client, _store, audit_id, token = _shared_report(tmp_path)
    visitor = TestClient(client.app)
    _signup(visitor, "ana@example.com")
    visitor.cookies.set(REPORT_KEY_COOKIE, f"{audit_id}.{token}")
    back = visitor.get(f"/entrar?next=%2Faudits%2F{audit_id}%3Flang%3Des", follow_redirects=False)
    assert back.status_code == 303
    assert back.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"
    assert "Max-Age=0" in _kept(back)
    # With a session the report's own form goes back to the report.
    again = visitor.post(
        f"/audits/{audit_id}/account?token={token}&lang=es",
        data={"go": "signup"},
        follow_redirects=False,
    )
    assert again.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"
    # Without the key there is no report to go to, and no cookie.
    stranger = TestClient(client.app)
    refused = stranger.post(
        f"/audits/{audit_id}/account?token=wrong", data={"go": "signup"}, follow_redirects=False
    )
    assert refused.status_code == 404 and "set-cookie" not in refused.headers


# -- After review: the cases the first pass left open ---------------------------------
def test_a_last_try_left_by_a_stopped_worker_is_sent_on_request(tmp_path: Path) -> None:
    cfg = _mail_settings(tmp_path)
    store = make_store(cfg.database_url)
    account_id = _account_for(store, "verify")
    _ask(store, "verify", account_id, NOW)
    # The eighth try was claimed and its worker stopped before answering.
    lease = (NOW + timedelta(seconds=90)).isoformat().replace("+00:00", "Z")
    with store.engine.begin() as conn:
        conn.execute(
            store.email_outbox.update().values(status="sending", attempts=8, lease_until=lease)
        )
    # While the lease runs the message belongs to that worker.
    soon = NOW + timedelta(seconds=60)
    _ask(store, "verify", account_id, soon)
    row = _outbox(store)[0]
    assert row["status"] == "sending" and row["attempts"] == 8
    later = NOW + timedelta(minutes=5)
    assert _deliver(store, cfg, later) == []
    _ask(store, "verify", account_id, later)
    row = _outbox(store)[0]
    assert row["status"] == "queued" and row["attempts"] == 0 and row["lease_until"] == ""
    sent = _deliver(store, cfg, later)
    assert len(sent) == 1
    # The name of the try that stopped: had the provider taken it, this is no second one.
    assert sent[0]["Message-ID"] == f"<rigor-{row['id']}@example.com>"
    assert len(_outbox(store)) == 1


def test_the_second_step_page_cleans_an_older_next(tmp_path: Path) -> None:
    client, _store, audit_id, token = _shared_report(tmp_path)
    owner = TestClient(client.app)
    _signup(owner, "ana@example.com")
    _turn_on_two_step(owner)
    visitor = TestClient(client.app)
    step = _signin_with_next(visitor, "ana@example.com", f"/audits/{audit_id}?lang=es")
    assert step.headers["location"].startswith("/entrar/codigo?next=")
    old = f"/entrar/codigo?next=%2Faudits%2F{audit_id}%3Ftoken%3D{token}%26lang%3Des"
    moved = visitor.get(old, follow_redirects=False)
    assert moved.status_code == 303
    assert moved.headers["location"] == f"/entrar/codigo?next=%2Faudits%2F{audit_id}%3Flang%3Des"
    assert f"{REPORT_KEY_COOKIE}={audit_id}.{token};" in _kept(moved)
    shown = visitor.get(moved.headers["location"], follow_redirects=False)
    assert shown.status_code == 200 and token not in shown.text


def test_the_passkey_page_takes_the_key_out_of_an_older_next(tmp_path: Path) -> None:
    pytest.importorskip("webauthn")
    pytest.importorskip("cbor2")
    from test_audit_passkeys import ORIGIN, Device, _add_passkey, _options

    client, _store, audit_id, token = _shared_report(tmp_path, base_url=ORIGIN)
    owner = TestClient(client.app)
    _signup(owner, "ana@example.com")
    device = Device()
    assert "done=passkey_added" in _add_passkey(owner, device)
    visitor = TestClient(client.app)
    form = visitor.get("/entrar")
    # As a form rendered before the change would post it.
    page = visitor.post(
        "/entrar/llave",
        data={"csrf": _csrf(form.text), "next": f"/audits/{audit_id}?token={token}&lang=es"},
        follow_redirects=False,
    )
    assert page.status_code == 200 and token not in page.text
    assert f"{REPORT_KEY_COOKIE}={audit_id}.{token};" in _kept(page)
    options, action = _options(page.text)
    done = visitor.post(
        action,
        data={
            "credential": device.get(options),
            "csrf": _csrf(page.text),
            "next": f"/audits/{audit_id}?lang=es",
        },
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert done.headers["location"] == f"/audits/{audit_id}?token={token}&lang=es"


def test_another_site_cannot_plant_the_report_key(tmp_path: Path) -> None:
    client, _store, audit_id, token = _shared_report(tmp_path)
    visitor = TestClient(client.app)
    address = f"/audits/{audit_id}/account?token={token}&lang=es"
    for headers in (
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": "https://evil.example"},
    ):
        refused = visitor.post(
            address, data={"go": "signup"}, headers=headers, follow_redirects=False
        )
        assert refused.status_code == 403, headers
        assert "set-cookie" not in refused.headers
    # The report's own form: same origin, or no origin under no-referrer.
    for headers in ({"Sec-Fetch-Site": "same-origin"}, {"Origin": "null"}):
        taken = visitor.post(
            address, data={"go": "signup"}, headers=headers, follow_redirects=False
        )
        assert taken.status_code == 303, headers
        assert f"{REPORT_KEY_COOKIE}={audit_id}.{token};" in _kept(taken)


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("extras", ["", "?extras=1"])
def test_sign_up_on_the_way_to_the_form_says_a_confirmation_link_was_sent(
    tmp_path: Path, locale: str, extras: str
) -> None:
    client, store, _ = _client(tmp_path, **MAIL)
    client = TestClient(client.app, base_url=SITE)
    next_path = UPLOAD[locale] + extras
    form = client.get(SIGNUP[locale], params={"next": next_path})
    assert form.status_code == 200
    done = client.post(
        SIGNUP[locale],
        data={
            "email": "ana@example.com",
            "password": PASSWORD,
            "csrf": _csrf(form.text),
            "next": next_path,
        },
        follow_redirects=False,
    )
    assert done.status_code == 303
    where = done.headers["location"]
    assert where == f"{next_path}{'&' if extras else '?'}done=welcome_confirm"
    page = client.get(where)
    assert page.status_code == 200
    for words in SENT[locale]:
        assert words in page.text
    assert ("<details class='adv extras' open>" in page.text) == bool(extras)
    assert not any(words in page.text for words in STALE)

    # Signing in later goes to the form as before, with no notice asked for.
    client.cookies.delete("rigor_session")
    form = client.get(SIGNIN[locale], params={"next": next_path})
    back = client.post(
        SIGNIN[locale],
        data={
            "email": "ana@example.com",
            "password": PASSWORD,
            "csrf": _csrf(form.text),
            "next": next_path,
        },
        follow_redirects=False,
    )
    assert back.status_code == 303 and back.headers["location"] == next_path
    assert SENT[locale][0] not in client.get(next_path).text

    # Once the address is confirmed the same link says nothing.
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    _verify(store, account.id, "ana@example.com")
    assert SENT[locale][0] not in client.get(where).text


def test_the_confirmation_notice_is_not_shown_without_confirmation_or_mail(
    tmp_path: Path,
) -> None:
    settings: tuple[tuple[str, dict[str, Any]], ...] = (
        ("a", {}),
        ("b", {**MAIL, "smtp_host": ""}),
    )
    for name, extra in settings:
        client, _store, _ = _client(tmp_path / name, **extra)
        client = TestClient(client.app, base_url=SITE)
        form = client.get("/registro?next=/auditar")
        done = client.post(
            "/registro",
            data={
                "email": "ana@example.com",
                "password": PASSWORD,
                "csrf": _csrf(form.text),
                "next": "/auditar",
            },
            follow_redirects=False,
        )
        assert done.headers["location"] == "/auditar", name
        # A hand-made link shows nothing either.
        page = client.get("/auditar?done=welcome_confirm")
        assert page.status_code == 200 and SENT["es"][0] not in page.text, name


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_sign_up_from_a_report_says_a_confirmation_link_was_sent(
    tmp_path: Path, locale: str
) -> None:
    client, store, _ = _client(tmp_path, **MAIL)
    uploader = TestClient(client.app, base_url=SITE)
    _signup(uploader, "uploader@example.com")
    location = _upload(uploader).headers["location"]
    token = parse_qs(urlsplit(location).query)["token"][0]
    audit_id = _audit_id(location)

    visitor = TestClient(client.app, base_url=SITE)
    start = visitor.post(
        f"/audits/{audit_id}/account?token={token}&lang={locale}",
        data={"go": "signup"},
        follow_redirects=False,
    )
    assert "Secure" in _kept(start)
    form = visitor.get(start.headers["location"])
    done = visitor.post(
        SIGNUP[locale],
        data={
            "email": "nueva@example.com",
            "password": PASSWORD,
            "csrf": _csrf(form.text),
            "next": f"/audits/{audit_id}?lang={locale}",
        },
        follow_redirects=False,
    )
    assert done.status_code == 303
    where = done.headers["location"]
    assert where == f"/audits/{audit_id}?token={token}&lang={locale}&acct=welcome_confirm"
    page = visitor.get(where)
    assert page.status_code == 200
    for words in SENT[locale]:
        assert words in page.text
    # Whoever only has the link, or confirmed already, reads no such notice.
    reader = TestClient(client.app, base_url=SITE)
    assert SENT[locale][0] not in reader.get(where).text
    account = store.find_account("nueva@example.com")  # type: ignore[attr-defined]
    _verify(store, account.id, "nueva@example.com")
    assert SENT[locale][0] not in visitor.get(where).text


def test_sign_up_on_the_way_elsewhere_keeps_its_address(tmp_path: Path) -> None:
    client, _store, _ = _client(tmp_path, **MAIL)
    client = TestClient(client.app, base_url=SITE)
    form = client.get("/registro?next=/cuenta/datos")
    done = client.post(
        "/registro",
        data={
            "email": "ana@example.com",
            "password": PASSWORD,
            "csrf": _csrf(form.text),
            "next": "/cuenta/datos",
        },
        follow_redirects=False,
    )
    assert done.headers["location"] == "/cuenta/datos"
