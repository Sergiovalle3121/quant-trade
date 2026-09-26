"""Customer accounts: sign up, sign in, "My reports", credits, reset and deletion."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from quant_trade.audit import account_pages  # noqa: E402
from quant_trade.audit.accounts import (  # noqa: E402
    CSRF_COOKIE,
    MAX_FAILED_SIGNINS_PER_EMAIL,
    MAX_FAILED_SIGNINS_PER_HOUR,
    MAX_SIGNUPS_PER_HOUR,
    SESSION_COOKIE,
    hash_password,
    hash_secret,
    password_problem,
    safe_next,
    valid_email,
    verify_password,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.legal import LegalContext, privacy_text, terms_text  # noqa: E402
from quant_trade.audit.payments import fulfil, pack_code  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.cli import app as cli_app  # noqa: E402

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
PASSWORD = "una frase larga y segura"
ADMIN_KEY = "k" * 40
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")


def _settings(tmp_path: Path, **extra: object) -> AuditSettings:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path}/audit.db",
        "bootstrap_samples": 100,
        "free_mode": False,
        "access_codes": True,
        "contact_url": "https://wa.me/000",
        "admin_key": ADMIN_KEY,
    }
    values.update(extra)
    return AuditSettings(**values)  # type: ignore[arg-type]


def _client(tmp_path: Path, **extra: object) -> tuple[TestClient, object, AuditSettings]:
    settings = _settings(tmp_path, **extra)
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store)), store, settings


def _csrf(page: str) -> str:
    match = CSRF_FIELD.search(page)
    assert match, "the form has no CSRF field"
    return match.group(1)


def _signup(
    client: TestClient,
    email: str = "ana@example.com",
    password: str = PASSWORD,
    *,
    welcome: bool = False,
):
    """Sign up; the free full report is spent unless ``welcome`` is true."""
    csrf = _csrf(client.get("/registro").text)
    response = client.post(
        "/registro",
        data={"email": email, "password": password, "csrf": csrf},
        follow_redirects=False,
    )
    account = client.app.state.store.find_account(email)
    if not welcome and account is not None:
        client.app.state.store.spend_welcome(account.id, at=datetime.now(UTC))
    return response


def _signin(client: TestClient, email: str, password: str = PASSWORD, ip: str = ""):
    headers = {"X-Forwarded-For": ip} if ip else {}
    csrf = _csrf(client.get("/entrar").text)
    return client.post(
        "/entrar",
        data={"email": email, "password": password, "csrf": csrf},
        headers=headers,
        follow_redirects=False,
    )


def _upload(client: TestClient, **data: str):
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    payload = {"trials": "3", "cost_bps": "5", "consent": "on", **data}
    return client.post("/audits", files=files, data=payload, follow_redirects=False)


def _audit_id(location: str) -> str:
    return location.split("/audits/")[1].split("?")[0]


# -- pure helpers ------------------------------------------------------------------
def test_passwords_are_hashed_with_scrypt_and_checked() -> None:
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$16384$8$1$") and PASSWORD not in stored
    assert verify_password(stored, PASSWORD)
    assert not verify_password(stored, PASSWORD + "x")
    assert hash_password(PASSWORD) != stored  # a fresh salt each time
    assert not verify_password("garbage", PASSWORD)
    assert not verify_password("bcrypt$1$2$3$4$5", PASSWORD)
    assert password_problem("short") == "password_short"
    assert password_problem("x" * 300) == "password_long"
    assert password_problem(PASSWORD) == ""
    assert password_problem("una frase\x00muy larga") == "password_bad"


def test_emails_and_return_paths_are_checked() -> None:
    assert valid_email(" Ana@Example.com ")
    assert not valid_email("ana@example") and not valid_email("a b@example.com")
    assert safe_next("/audits/abc?token=x&lang=es") == "/audits/abc?token=x&lang=es"
    assert safe_next("/cuenta") == "/cuenta"
    assert safe_next("/#subir") == "/#subir" and safe_next("/en#subir") == "/en#subir"
    for bad in (
        "https://evil.example/",
        "//evil.example/cuenta",
        "/panel",
        "/\\evil",
        "",
        "/?x=1",
        "/enx",
        "///evil.example",
    ):
        assert safe_next(bad) == ""


# -- sign up, sign in, sign out ----------------------------------------------------
def test_sign_up_opens_a_session_and_the_account_page(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    response = _signup(client, "Ana@Example.com")
    assert response.status_code == 303
    assert response.headers["location"] == "/cuenta?done=welcome"
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie  # plain http in tests; https sets it
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "ana@example.com" in page.text and "Cuenta creada" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert find_claims(page.text) == []
    # Only hashes are stored: the password and the session cookie are not in the DB.
    found = store.account_with_hash("ana@example.com")  # type: ignore[attr-defined]
    assert found is not None and PASSWORD not in found[1]
    token = client.cookies.get(SESSION_COOKIE)
    assert store.session_account(hash_secret(token), NOW)  # type: ignore[attr-defined]


def test_the_session_cookie_is_secure_on_https(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path, base_url="https://rigor.example")
    response = _signup(client)
    assert "Secure" in response.headers["set-cookie"]


def test_sign_up_refuses_bad_input_and_forged_forms(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    csrf = _csrf(client.get("/registro").text)
    forged = client.post(
        "/registro", data={"email": "a@example.com", "password": PASSWORD, "csrf": "nope"}
    )
    assert forged.status_code == 400 and "El formulario caducó" in forged.text
    short = client.post(
        "/registro", data={"email": "a@example.com", "password": "corta", "csrf": csrf}
    )
    assert short.status_code == 400 and "al menos 10 caracteres" in short.text
    bad = client.post("/registro", data={"email": "nope", "password": PASSWORD, "csrf": csrf})
    assert bad.status_code == 400
    assert store.count_accounts() == 0  # type: ignore[attr-defined]
    assert _signup(client, "b@example.com").status_code == 303
    client.cookies.clear()
    again = _signup(client, "B@example.com")
    assert again.status_code == 409 and "No se pudo crear" in again.text


def test_sign_in_checks_the_password_and_limits_attempts(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "c@example.com")
    client.cookies.clear()
    wrong = _signin(client, "c@example.com", "otra frase distinta")
    assert wrong.status_code == 401 and "no coinciden" in wrong.text
    unknown = _signin(client, "nadie@example.com")
    assert unknown.status_code == 401 and unknown.text.count("no coinciden") == 1
    ok = _signin(client, "c@example.com")
    assert ok.status_code == 303 and ok.headers["location"] == "/cuenta"
    client.cookies.clear()
    for _ in range(MAX_FAILED_SIGNINS_PER_HOUR):
        _signin(client, "c@example.com", "otra frase distinta")
    assert _signin(client, "c@example.com").status_code == 429


def test_sign_out_ends_the_session(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client)
    page = client.get("/cuenta").text
    # A sign-out without the session's CSRF token does nothing.
    client.post("/salir", data={"csrf": "nope"})
    assert client.get("/cuenta", follow_redirects=False).status_code == 200
    out = client.post("/salir", data={"csrf": _csrf(page)}, follow_redirects=False)
    assert out.headers["location"] == "/entrar?done=signed_out"
    gone = client.get("/cuenta", follow_redirects=False)
    assert gone.status_code == 303 and gone.headers["location"].startswith("/entrar?next=")


def test_account_pages_exist_in_english(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    for path, text in (
        ("/signup", "Create your account"),
        ("/login", "Sign in to your account"),
        ("/forgot", "Recover your password"),
    ):
        page = client.get(path)
        assert page.status_code == 200 and text in page.text and "lang='en'" in page.text
    assert "Crea tu cuenta" in client.get("/registro").text
    assert "Create your account" in client.get("/registro?lang=en").text
    csrf = _csrf(client.get("/signup").text)
    response = client.post(
        "/signup",
        data={"email": "en@example.com", "password": PASSWORD, "csrf": csrf},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/account?done=welcome"
    assert "Account created" in client.get(response.headers["location"]).text


def test_the_navigation_links_to_the_account(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    assert "href='/cuenta'>Mi cuenta" in client.get("/").text
    assert "href='/account'>My account" in client.get("/en").text


# -- reports on the account ----------------------------------------------------------
def test_an_upload_while_signed_in_lands_on_the_account(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "d@example.com")
    location = _upload(client).headers["location"]
    audit_id = _audit_id(location)
    page = client.get("/cuenta").text
    assert f"/audits/{audit_id}?lang=es" in page and "Vista previa" in page
    # The owner opens it without the token; the report says it is saved.
    own = client.get(f"/audits/{audit_id}?lang=es")
    assert own.status_code == 200 and "Guardado en tu cuenta" in own.text
    assert find_claims(own.text) == []
    # Nobody else can: signed out, or signed in to another account.
    other = TestClient(client.app)
    assert other.get(f"/audits/{audit_id}?lang=es").status_code == 404
    _signup(other, "e@example.com")
    assert other.get(f"/audits/{audit_id}?lang=es").status_code == 404
    assert other.get(f"/audits/{audit_id}.json").status_code == 404
    # The token link keeps working without an account.
    assert TestClient(client.app).get(location).status_code == 200
    assert store.account_for_audit(audit_id) is not None  # type: ignore[attr-defined]


def test_a_report_opened_by_link_can_be_saved(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "uploader@example.com")
    location = _upload(client).headers["location"]
    client.cookies.clear()
    # A deletes the account but keeps the report: only its link is left, as
    # for every report uploaded before accounts existed.
    uploader = store.find_account("uploader@example.com")  # type: ignore[attr-defined]
    store.delete_account(uploader.id)  # type: ignore[attr-defined]
    audit_id = _audit_id(location)
    anon = client.get(location).text
    assert "Crea una cuenta gratis para guardar este informe" in anon
    assert "/registro?next=" in anon
    _signup(client, "f@example.com")
    page = client.get(location).text
    assert "Guardar en mi cuenta" in page
    saved = client.post(
        f"/audits/{audit_id}/save{location[location.index('?') :]}",
        data={"csrf": _csrf(page)},
        follow_redirects=False,
    )
    assert saved.status_code == 303 and saved.headers["location"].endswith("&acct=saved")
    assert "Informe guardado en tu cuenta" in client.get(saved.headers["location"]).text
    assert f"/audits/{audit_id}?lang=es" in client.get("/cuenta").text
    # A forged save (no CSRF token) changes nothing for another account.
    other = TestClient(client.app)
    _signup(other, "g@example.com")
    other.post(f"/audits/{audit_id}/save{location[location.index('?') :]}", data={"csrf": "x"})
    assert store.account_for_audit(audit_id) == store.find_account("f@example.com").id  # type: ignore[attr-defined]


# -- codes and credits -------------------------------------------------------------
def test_codes_redeemed_while_signed_in_give_credits_on_the_account(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "h@example.com")
    code, record = store.create_access_code(credits=3, note="nota-privada", at=NOW)  # type: ignore[attr-defined]
    first = _upload(client, access_code=code).headers["location"]
    assert first.endswith("&code=applied")
    account_page = client.get("/cuenta").text
    assert f"n.º {record.id}" in account_page and "nota-privada" not in account_page
    assert "<b>2</b>" in account_page  # credits left
    # A second upload is a preview with a one-click unlock from the account.
    second = _upload(client).headers["location"]
    audit_id = _audit_id(second)
    preview = client.get(second).text
    assert "Desbloquear con 1 crédito de tu cuenta" in preview and "Tienes 2 créditos" in preview
    unlocked = client.post(
        f"/audits/{audit_id}/credit{second[second.index('?') :]}",
        data={"csrf": _csrf(preview)},
        follow_redirects=False,
    )
    assert unlocked.headers["location"].endswith("&acct=credit")
    full = client.get(unlocked.headers["location"]).text
    assert "Crédito usado" in full and "class='lockbox'" not in full
    assert store.get_access_code(code).credits_left == 1  # type: ignore[attr-defined]
    purchases = client.get("/cuenta").text
    assert purchases.count("Completo · código") == 2


def test_a_code_can_be_added_once_and_to_one_account(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "i@example.com")
    code, _ = store.create_access_code(credits=2, note="", at=NOW)  # type: ignore[attr-defined]
    csrf = _csrf(client.get("/cuenta").text)
    added = client.post("/cuenta/codigo", data={"code": code.lower(), "csrf": csrf})
    assert "Código añadido a tu cuenta" in added.text
    again = client.post("/cuenta/codigo", data={"code": code, "csrf": csrf})
    assert "ya está en tu cuenta" in again.text
    unknown = client.post("/cuenta/codigo", data={"code": "AUD-2222-2222-2222", "csrf": csrf})
    assert "No encontramos ese código" in unknown.text
    other = TestClient(client.app)
    _signup(other, "j@example.com")
    taken = other.post(
        "/cuenta/codigo", data={"code": code, "csrf": _csrf(other.get("/cuenta").text)}
    )
    assert "otra cuenta" in taken.text


def test_without_credits_the_unlock_button_is_not_offered(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "k@example.com")
    location = _upload(client).headers["location"]
    page = client.get(location).text
    assert "Desbloquear con 1 crédito" not in page
    audit_id = _audit_id(location)
    tried = client.post(
        f"/audits/{audit_id}/credit{location[location.index('?') :]}",
        data={"csrf": _csrf(client.get("/cuenta").text)},
        follow_redirects=False,
    )
    assert tried.headers["location"].endswith("&acct=nocredit")
    assert not store.get_audit(audit_id).paid  # type: ignore[attr-defined]


def test_the_code_that_expires_first_is_spent_first(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    account = store.create_account(email="l@example.com", password_hash="x", locale="es", at=NOW)
    assert account is not None
    forever, _ = store.create_access_code(credits=1, note="", at=NOW)
    soon, _ = store.create_access_code(credits=1, note="", at=NOW, expires_days=5)
    for code in (forever, soon):
        store.link_code(account.id, store.code_id(code), at=NOW)
    store.create_audit(
        audit_id="a1",
        created_at=NOW,
        token_hash="t" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json="{}",
        report_html="",
        overall_class="C",
        digests={},
        equity_csv=b"x",
    )
    assert store.account_credits(account.id, NOW) == 2
    assert store.redeem_with_account("a1", account.id, at=NOW)
    assert store.get_access_code(soon).credits_left == 0
    assert store.get_access_code(forever).credits_left == 1
    assert not store.redeem_with_account("a1", account.id, at=NOW)  # already paid
    assert store.account_credits(account.id, NOW + timedelta(days=10)) == 1


def test_a_card_pack_bought_from_an_account_report_lands_on_it(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        free_mode=False,
        stripe_secret_key="sk_test_x",
        stripe_webhook_secret="whsec_x",
    )
    account = store.create_account(email="m@example.com", password_hash="x", locale="es", at=NOW)
    assert account is not None
    store.create_audit(
        audit_id="a2",
        created_at=NOW,
        token_hash="t" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json="{}",
        report_html="",
        overall_class="B",
        digests={},
        equity_csv=b"x",
    )
    store.link_audit(account.id, "a2", at=NOW)
    session = {
        "id": "cs_test_1",
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": settings.pack_price_usd_cents,
        "metadata": {"audit_id": "a2", "plan": "pack", "app": "rigor"},
    }
    assert fulfil(store, settings, session, at=NOW) == "a2"
    code_id = store.code_id(pack_code("whsec_x", "cs_test_1"))
    assert [c.code.id for c in store.account_codes_list(account.id)] == [code_id]
    assert store.account_credits(account.id, NOW) == 2
    [item] = store.account_audits_list(account.id)
    assert item.paid and item.paid_with == "card"


# -- password reset ----------------------------------------------------------------
def test_the_owner_panel_issues_a_one_time_reset_link(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "n@example.com")
    unknown = client.post(
        "/panel", data={"key": ADMIN_KEY, "action": "reset", "email": "x@example.com"}
    )
    assert "No hay ninguna cuenta" in unknown.text
    panel = client.post(
        "/panel", data={"key": ADMIN_KEY, "action": "reset", "email": "N@example.com"}
    )
    link = re.search(r"/restablecer\?token=([A-Za-z0-9_-]+)", panel.text)
    assert link, panel.text
    token = link.group(1)
    visitor = TestClient(client.app)
    form = visitor.get(f"/restablecer?token={token}")
    assert form.status_code == 200 and "Pon una contraseña nueva" in form.text
    done = visitor.post(
        "/restablecer",
        data={"token": token, "password": "otra frase nueva y larga", "csrf": _csrf(form.text)},
        follow_redirects=False,
    )
    assert done.headers["location"] == "/entrar?done=reset_done"
    # The old session is signed out and the old password no longer works.
    assert client.get("/cuenta", follow_redirects=False).status_code == 303
    assert _signin(visitor, "n@example.com").status_code == 401
    assert _signin(visitor, "n@example.com", "otra frase nueva y larga").status_code == 303
    # The link works once.
    assert TestClient(client.app).get(f"/restablecer?token={token}").status_code == 410


def test_the_cli_prints_a_reset_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{tmp_path}/audit.db"
    store = make_store(url)
    store.create_account(email="o@example.com", password_hash="x", locale="en", at=NOW)
    monkeypatch.setenv("DATABASE_URL", url)
    result = CliRunner().invoke(cli_app, ["audit", "account-reset", "o@example.com"])
    assert result.exit_code == 0 and "/reset?token=" in result.output


# -- deletion ----------------------------------------------------------------------
def test_deleting_the_account_keeps_or_removes_reports(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "p@example.com")
    location = _upload(client).headers["location"]
    audit_id = _audit_id(location)
    csrf = _csrf(client.get("/cuenta").text)
    wrong = client.post("/cuenta/borrar", data={"current": "mala", "csrf": csrf})
    assert "no coinciden" in wrong.text
    gone = client.post(
        "/cuenta/borrar", data={"current": PASSWORD, "csrf": csrf}, follow_redirects=False
    )
    assert gone.headers["location"] == "/entrar?done=deleted"
    assert store.find_account("p@example.com") is None  # type: ignore[attr-defined]
    assert store.account_for_audit(audit_id) is None  # type: ignore[attr-defined]
    assert store.get_audit(audit_id) is not None  # type: ignore[attr-defined]
    assert TestClient(client.app).get(location).status_code == 200
    # With the box ticked, the reports go too.
    _signup(client, "q@example.com")
    second = _audit_id(_upload(client).headers["location"])
    csrf = _csrf(client.get("/cuenta").text)
    client.post("/cuenta/borrar", data={"current": PASSWORD, "csrf": csrf, "with_reports": "yes"})
    assert store.get_audit(second) is None  # type: ignore[attr-defined]


def test_the_cli_deletes_an_account_only_with_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path}/audit.db"
    store = make_store(url)
    store.create_account(email="r@example.com", password_hash="x", locale="es", at=NOW)
    monkeypatch.setenv("DATABASE_URL", url)
    runner = CliRunner()
    dry = runner.invoke(cli_app, ["audit", "account-delete", "r@example.com"])
    assert dry.exit_code == 0 and "would delete" in dry.output
    assert store.find_account("r@example.com") is not None
    done = runner.invoke(cli_app, ["audit", "account-delete", "r@example.com", "--yes"])
    assert done.exit_code == 0 and store.find_account("r@example.com") is None


def test_changing_the_password_signs_out_other_sessions(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "s@example.com")
    laptop = TestClient(client.app)
    _signin(laptop, "s@example.com")
    csrf = _csrf(client.get("/cuenta").text)
    changed = client.post(
        "/cuenta/contrasena",
        data={"current": PASSWORD, "password": "frase nueva muy larga", "csrf": csrf},
    )
    assert "Contraseña cambiada" in changed.text
    assert laptop.get("/cuenta", follow_redirects=False).status_code == 303
    assert client.get("/cuenta", follow_redirects=False).status_code == 200


def test_deleting_an_audit_removes_it_from_the_account(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "t@example.com")
    audit_id = _audit_id(_upload(client).headers["location"])
    assert store.delete_audit(audit_id)  # type: ignore[attr-defined]
    assert store.account_for_audit(audit_id) is None  # type: ignore[attr-defined]
    assert audit_id not in client.get("/cuenta").text


# -- texts -------------------------------------------------------------------------
def test_account_texts_pass_the_guard_in_both_languages() -> None:
    assert set(account_pages.COPY["es"]) == set(account_pages.COPY["en"])
    for text in account_pages.all_texts():
        assert find_claims(text) == [], text


def test_privacy_and_terms_describe_the_account_and_its_cookies() -> None:
    ctx = LegalContext(
        operator_name="Op",
        operator_contact="op@example.com",
        operator_address="México",
        jurisdiction="Leyes de México",
    )
    for locale, words in (("es", ("cookies", "scrypt", "Tu cuenta")), ("en", ("cookies",))):
        privacy = " ".join(" ".join(p) for _, p in privacy_text(ctx, locale).sections)
        terms = privacy_text(ctx, locale).title + " ".join(
            title for title, _ in terms_text(ctx, locale).sections
        )
        assert "scrypt" in privacy and "cookies" in privacy
        assert "No hay cuentas de usuario" not in privacy
        assert "no user accounts" not in privacy
        assert ("Tu cuenta" if locale == "es" else "Your account") in terms
        assert find_claims(privacy) == []
        del words


def test_forms_before_sign_in_set_a_csrf_cookie(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    page = client.get("/entrar")
    assert CSRF_COOKIE in page.headers["set-cookie"]
    assert client.cookies.get(CSRF_COOKIE) == _csrf(page.text)


# -- security review findings ------------------------------------------------------
def test_a_report_saved_from_a_link_is_never_deleted_with_the_account(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "uploader@example.com")
    location = _upload(client).headers["location"]
    client.cookies.clear()
    # A deletes the account but keeps the report: only its link is left, as
    # for every report uploaded before accounts existed.
    uploader = store.find_account("uploader@example.com")  # type: ignore[attr-defined]
    store.delete_account(uploader.id)  # type: ignore[attr-defined]
    audit_id = _audit_id(location)
    thief = TestClient(client.app)
    _signup(thief, "b@example.com")
    page = thief.get(location).text
    query = location[location.index("?") :]
    thief.post(f"/audits/{audit_id}/save{query}", data={"csrf": _csrf(page)})
    listing = thief.get("/cuenta").text
    assert "Guardado desde un enlace" in listing
    thief.post(
        "/cuenta/borrar",
        data={"current": PASSWORD, "csrf": _csrf(listing), "with_reports": "yes"},
    )
    assert store.get_audit(audit_id) is not None  # type: ignore[attr-defined]
    assert store.account_for_audit(audit_id) is None  # type: ignore[attr-defined]
    assert client.get(location).status_code == 200


def test_paying_for_someone_elses_report_never_allows_deleting_it(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "uploader@example.com")
    location = _upload(client).headers["location"]
    client.cookies.clear()
    # A deletes the account but keeps the report: only its link is left, as
    # for every report uploaded before accounts existed.
    uploader = store.find_account("uploader@example.com")  # type: ignore[attr-defined]
    store.delete_account(uploader.id)  # type: ignore[attr-defined]
    audit_id = _audit_id(location)
    buyer = TestClient(client.app)
    _signup(buyer, "own@example.com")
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    buyer.post("/cuenta/codigo", data={"code": code, "csrf": _csrf(buyer.get("/cuenta").text)})
    page = buyer.get(location).text
    query = location[location.index("?") :]
    buyer.post(f"/audits/{audit_id}/save{query}", data={"csrf": _csrf(page)})
    buyer.post(f"/audits/{audit_id}/credit{query}", data={"csrf": _csrf(page)})
    account = store.find_account("own@example.com")  # type: ignore[attr-defined]
    [item] = store.account_audits_list(account.id)  # type: ignore[attr-defined]
    assert item.paid and not item.own
    listing = buyer.get("/cuenta").text
    buyer.post(
        "/cuenta/borrar",
        data={"current": PASSWORD, "csrf": _csrf(listing), "with_reports": "yes"},
    )
    assert store.get_audit(audit_id) is not None  # type: ignore[attr-defined]
    assert client.get(location).status_code == 200


@pytest.mark.parametrize("path", ["redeem", "credit"])
def test_unlocking_someone_elses_report_without_saving_never_allows_deleting_it(
    tmp_path: Path, path: str
) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "uploader@example.com")
    location = _upload(client).headers["location"]
    client.cookies.clear()
    # A deletes the account but keeps the report: only its link is left, as
    # for every report uploaded before accounts existed.
    uploader = store.find_account("uploader@example.com")  # type: ignore[attr-defined]
    store.delete_account(uploader.id)  # type: ignore[attr-defined]
    audit_id = _audit_id(location)
    buyer = TestClient(client.app)
    _signup(buyer, "w@example.com")
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    query = location[location.index("?") :]
    if path == "redeem":
        buyer.post(f"/audits/{audit_id}/redeem{query}", data={"code": code})
    else:
        buyer.post("/cuenta/codigo", data={"code": code, "csrf": _csrf(buyer.get("/cuenta").text)})
        buyer.post(
            f"/audits/{audit_id}/credit{query}", data={"csrf": _csrf(buyer.get("/cuenta").text)}
        )
    assert store.get_audit(audit_id).paid  # type: ignore[attr-defined]
    listing = buyer.get("/cuenta").text
    assert audit_id in listing
    buyer.post(
        "/cuenta/borrar",
        data={"current": PASSWORD, "csrf": _csrf(listing), "with_reports": "yes"},
    )
    assert store.get_audit(audit_id) is not None  # type: ignore[attr-defined]
    assert client.get(location).status_code == 200


def test_a_promotional_description_is_withheld_on_the_account_page(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "u@example.com")
    _upload(client, description="Ganancias garantizadas cada mes")
    page = client.get("/cuenta")
    assert page.status_code == 200
    assert "Ganancias garantizadas" not in page.text and "withheld" in page.text
    assert find_claims(page.text) == []


def test_failures_from_elsewhere_do_not_lock_the_owner_out(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client, "v@example.com")
    client.cookies.clear()
    for _ in range(MAX_FAILED_SIGNINS_PER_HOUR):
        _signin(client, "v@example.com", "otra frase distinta", ip="203.0.113.9")
    assert _signin(client, "v@example.com", ip="203.0.113.9").status_code == 429
    client.cookies.clear()
    assert _signin(client, "v@example.com", ip="198.51.100.4").status_code == 303


def test_guesses_spread_over_many_addresses_hit_the_per_email_ceiling(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client, "w@example.com")
    client.cookies.clear()
    # A pool of addresses, each staying under the per-address limits.
    for n in range(MAX_FAILED_SIGNINS_PER_EMAIL):
        ip = f"198.18.{n // 5}.{n % 5 + 1}"
        assert _signin(client, "w@example.com", "otra frase distinta", ip=ip).status_code == 401
    # Past the ceiling an address that already failed gets one more try, then waits.
    assert _signin(client, "w@example.com", "otra frase más", ip="198.18.0.1").status_code == 401
    assert _signin(client, "w@example.com", "otra frase más", ip="198.18.0.1").status_code == 429
    # The owner, from an address with no failures on this e-mail, is not locked out.
    assert _signin(client, "w@example.com", ip="192.0.2.77").status_code == 303


def test_sign_ups_stop_at_the_limit_exactly(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    for n in range(MAX_SIGNUPS_PER_HOUR):
        client.cookies.clear()
        assert _signup(client, f"s{n}@example.com").status_code == 303
    client.cookies.clear()
    assert _signup(client, "one-more@example.com").status_code == 429


def test_the_landing_says_the_free_preview_comes_with_an_account(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    es = client.get("/").text
    assert "Tu primer informe completo, gratis al crear tu cuenta" in es
    assert "después, 3 vistas previas gratis al mes. Sin tarjeta." in es
    assert "Primer informe completo gratis con tu cuenta" in es
    assert "el primer informe completo y 3 al mes" in es
    assert "cuenta opcional" not in es and "cuenta es opcional" not in es
    assert "sin crear cuenta" not in es and "Cuenta gratis opcional" not in es
    en = client.get("/en").text
    assert "Your first full report, free when you create your account" in en
    assert "then 3 free previews a month. No card." in en
    assert "account optional" not in en and "account is optional" not in en
    assert "Optional free account" not in en


def test_two_full_reports_on_the_account_compare_without_pasting_links(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    ids = [_audit_id(_upload(client).headers["location"]) for _ in range(3)]
    # Only full reports can be compared: with one unlocked the picker is hidden.
    store.mark_paid(ids[0], stripe_session_id="cs_a", at=NOW)  # type: ignore[attr-defined]
    page = client.get("/cuenta").text
    assert "/cuenta/comparar" not in page
    store.mark_paid(ids[1], stripe_session_id="cs_b", at=NOW)  # type: ignore[attr-defined]
    page = client.get("/cuenta").text
    assert "action='/cuenta/comparar'" in page
    # The strategy filing form lists every report; only the compare picker counts.
    picker = page.split("action='/cuenta/comparar'", 1)[1].split("</form>", 1)[0]
    assert f"value='{ids[0]}'" in picker and f"value='{ids[1]}'" in picker
    assert f"value='{ids[2]}'" not in picker  # still a preview

    shown = client.get(f"/cuenta/comparar?id={ids[0]}&id={ids[1]}")
    assert shown.status_code == 200
    assert f"/audits/{ids[0]}?lang=es" in shown.text and "token=" not in shown.text
    assert "Dos informes de tu cuenta" in shown.text and "Pega los enlaces" not in shown.text
    assert f"/account/comparar?id={ids[0]}&amp;id={ids[1]}" in shown.text or (
        f"/account/comparar?id={ids[0]}&id={ids[1]}" in shown.text
    )
    assert not find_claims(re.sub(r"<[^>]+>", " ", shown.text))
    assert client.get(f"/account/comparar?id={ids[0]}&id={ids[1]}").status_code == 200

    def refused(query: str, prefix: str = "/cuenta") -> bool:
        answer = client.get(f"{prefix}/comparar?{query}", follow_redirects=False)
        return answer.status_code == 303 and "error=compare_pick" in answer.headers["location"]

    assert refused(f"id={ids[0]}")  # one report
    assert refused(f"id={ids[0]}&id={ids[0]}")  # the same report twice
    assert refused(f"id={ids[0]}&id={ids[2]}")  # a locked preview
    assert refused(f"id={ids[0]}&id={ids[1]}&id={ids[2]}")  # three
    assert refused(f"id={ids[0]}&id=nope", "/account")

    # Someone else's reports never compare, even with the right ids.
    other, _, _ = _client(tmp_path)
    _signup(other, "otro@example.com")
    answer = other.get(f"/cuenta/comparar?id={ids[0]}&id={ids[1]}", follow_redirects=False)
    assert "error=compare_pick" in answer.headers["location"]
    # Signed out, it asks to sign in.
    anon, _, _ = _client(tmp_path)
    answer = anon.get(f"/cuenta/comparar?id={ids[0]}&id={ids[1]}", follow_redirects=False)
    assert answer.headers["location"].startswith("/entrar")


def test_my_reports_link_the_pdf_and_public_page_of_each_report(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    full, preview = (_audit_id(_upload(client).headers["location"]) for _ in range(2))
    store.mark_paid(full, stripe_session_id="cs_a", at=NOW)  # type: ignore[attr-defined]
    page = client.get("/cuenta").text
    assert f"/audits/{full}/pdf?lang=es" in page
    assert f"/audits/{preview}/pdf" not in page  # a preview has no PDF
    assert "/v/" not in page
    published = client.post(f"/audits/{full}/publish", follow_redirects=False)
    public_path = published.headers["location"].split("?")[0]
    assert public_path.startswith("/v/")
    page = client.get("/account").text
    assert f"{public_path}?lang=en" in page and "Public page" in page
    # The owner's session opens the PDF without the token.
    assert client.get(f"/audits/{preview}/pdf").status_code == 402


def test_without_credits_my_account_shows_prices_and_a_ready_message_first(
    tmp_path: Path,
) -> None:
    client, _, settings = _client(tmp_path)
    _signup(client)
    _upload(client)
    page = client.get("/cuenta").text
    single = settings.price_usd_cents // 100
    pack = settings.pack_price_usd_cents // 100
    assert f"Un informe completo: USD {single}." in page
    assert f"Paquete de 3 créditos: USD {pack}." in page
    assert "wa.me/000?text=" in page
    # With no credits, buying comes before the list of reports.
    assert page.index("¿Necesitas créditos?") < page.index("Tus informes")
    en = client.get("/account").text
    assert f"Pack of 3 credits: USD {pack}." in en
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))


# -- the free tier: previews need an account, a few a month ------------------------
def test_a_preview_needs_an_account_unless_a_working_code_pays_for_it(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    refused = _upload(client)
    assert refused.status_code == 401
    assert "tu primer informe completo no se paga" in refused.text
    assert "href='/registro?next=" in refused.text and "3 vistas previas gratis" in refused.text
    assert not find_claims(re.sub(r"<[^>]+>", " ", refused.text))
    as_json = client.post(
        "/audits",
        files={"equity": ("e.csv", csv_bytes(positive_drift(500)), "text/csv")},
        data={"consent": "on"},
        headers={"Accept": "application/json"},
    )
    assert as_json.status_code == 401 and as_json.json() == {"error": "free_tier_signin"}
    bad = _upload(client, access_code="AUD-NOPE-NOPE-NOPE")
    assert bad.status_code == 401 and "Ese código no sirve" in bad.text
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    paid = _upload(client, access_code=code)
    assert paid.status_code == 303 and paid.headers["location"].endswith("&code=applied")
    english = client.post(
        "/audits",
        files={"equity": ("e.csv", csv_bytes(positive_drift(500)), "text/csv")},
        data={"consent": "on", "locale": "en"},
    )
    assert "your first full report is on us" in english.text


def test_each_account_gets_three_free_previews_a_month_then_uses_credits(
    tmp_path: Path,
) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    assert "3 de 3" in client.get("/cuenta").text
    for _ in range(3):
        assert _upload(client).status_code == 303
    page = client.get("/cuenta").text
    assert "0 de 3" in page and "Vistas previas gratis este mes" in page
    over = _upload(client)
    assert over.status_code == 402
    assert "Ya usaste tus 3 vistas previas gratis de este mes" in over.text
    assert "href='/cuenta'" in over.text
    # With credits on the account, the next file comes out as a full report.
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    client.post("/cuenta/codigo", data={"code": code, "csrf": _csrf(page)})
    full = _upload(client)
    assert full.status_code == 303 and "acct=upload_credit" in full.headers["location"]
    report = client.get(full.headers["location"]).text
    assert "Usamos 1 crédito de tu cuenta" in report and "class='lockbox'" not in report
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    assert store.account_credits(account.id, datetime.now(UTC)) == 0  # type: ignore[attr-defined]
    assert _upload(client).status_code == 402  # and then it stops again


def test_free_previews_are_also_counted_per_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import accounts

    monkeypatch.setattr(accounts, "FREE_PREVIEWS_PER_IP_PER_MONTH", 2)
    client, _, _ = _client(tmp_path, trusted_proxy_hops=1)
    ip = {"X-Forwarded-For": "203.0.113.50"}
    files = {"equity": ("e.csv", csv_bytes(positive_drift(500)), "text/csv")}

    def upload(who: TestClient) -> int:
        answer = who.post(
            "/audits", files=files, data={"consent": "on"}, headers=ip, follow_redirects=False
        )
        return answer.status_code

    _signup(client, "first@example.com")
    assert [upload(client), upload(client)] == [303, 303]
    second = TestClient(client.app)
    _signup(second, "second@example.com")
    refused = second.post("/audits", files=files, data={"consent": "on"}, headers=ip)
    assert refused.status_code == 402 and "Esta red ya usó" in refused.text
    # Another network is not affected.
    other = second.post(
        "/audits",
        files=files,
        data={"consent": "on"},
        headers={"X-Forwarded-For": "198.51.100.60"},
        follow_redirects=False,
    )
    assert other.status_code == 303


def test_free_previews_renew_each_calendar_month_and_lose_the_address(tmp_path: Path) -> None:
    from quant_trade.audit.accounts import month_start

    _, store, _ = _client(tmp_path)
    april = datetime(2026, 4, 30, 23, 59, tzinfo=UTC)
    may = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    store.record_free_preview("a" * 32, "acc", client_ip="1.2.3.4", at=april)  # type: ignore[attr-defined]
    assert month_start(may) == may and month_start(april) == datetime(2026, 4, 1, tzinfo=UTC)
    count = store.free_previews_since  # type: ignore[attr-defined]
    assert count(month_start(april), account_id="acc") == 1
    assert count(month_start(may), account_id="acc") == 0
    assert count(month_start(april), client_ip="1.2.3.4") == 1
    store.purge_expired(may + timedelta(days=40), retention_days=30)  # type: ignore[attr-defined]
    assert count(month_start(april), client_ip="1.2.3.4") == 0
    assert count(month_start(april), account_id="acc") == 1


# -- the free first full report ----------------------------------------------------
def _other_file() -> dict[str, tuple[str, bytes, str]]:
    return {"equity": ("other.csv", csv_bytes(positive_drift(420, seed=7)), "text/csv")}


def test_a_new_account_gets_its_first_full_report_free_then_previews(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, welcome=True)
    page = client.get("/cuenta").text
    assert "Primer informe completo gratis" in page and "Disponible" in page
    first = _upload(client)
    assert first.status_code == 303 and "acct=welcome" in first.headers["location"]
    report = client.get(first.headers["location"]).text
    assert "Tu primer informe completo es gratis por crear tu cuenta" in report
    assert "class='lockbox'" not in report
    assert not find_claims(re.sub(r"<[^>]+>", " ", report))
    audit = store.get_audit(_audit_id(first.headers["location"]))  # type: ignore[attr-defined]
    assert audit.paid and audit.stripe_session_id.startswith("welcome:")
    # The free full report does not use one of the monthly previews.
    page = client.get("/cuenta").text
    assert "Usado" in page and "3 de 3" in page and "gratis, primer informe" in page
    second = client.post(
        "/audits", files=_other_file(), data={"consent": "on"}, follow_redirects=False
    )
    assert second.status_code == 303 and "acct=" not in second.headers["location"]
    assert "class='lockbox'" in client.get(second.headers["location"]).text


def test_the_free_report_is_once_per_browser_and_once_per_file(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "first@example.com", welcome=True)
    assert "acct=welcome" in _upload(client).headers["location"]
    device = client.cookies.get("rigor_device")
    assert device
    # Another account in the same browser gets a preview, even with a new file.
    client.cookies.clear()
    client.cookies.set("rigor_device", device)
    _signup(client, "second@example.com", welcome=True)
    same_browser = client.post(
        "/audits", files=_other_file(), data={"consent": "on"}, follow_redirects=False
    )
    assert same_browser.status_code == 303
    assert "acct=welcome" not in same_browser.headers["location"]
    # A fresh browser with the same file gets a preview too.
    fresh = TestClient(client.app)
    _signup(fresh, "third@example.com", welcome=True)
    same_file = _upload(fresh)
    assert same_file.status_code == 303 and "acct=welcome" not in same_file.headers["location"]
    # ...while a fresh browser with a new file still gets its free full report.
    other = TestClient(client.app)
    _signup(other, "fourth@example.com", welcome=True)
    new_file = other.post(
        "/audits", files=_other_file(), data={"consent": "on"}, follow_redirects=False
    )
    assert "acct=welcome" in new_file.headers["location"]


def test_free_reports_are_capped_per_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import accounts

    monkeypatch.setattr(accounts, "WELCOME_REPORTS_PER_IP_PER_MONTH", 1)
    client, _, _ = _client(tmp_path, trusted_proxy_hops=1)
    ip = {"X-Forwarded-For": "203.0.113.70"}
    _signup(client, "first@example.com", welcome=True)
    first = client.post(
        "/audits", files=_other_file(), data={"consent": "on"}, headers=ip, follow_redirects=False
    )
    assert "acct=welcome" in first.headers["location"]
    second = TestClient(client.app)
    _signup(second, "second@example.com", welcome=True)
    files = {"equity": ("e.csv", csv_bytes(positive_drift(500)), "text/csv")}
    capped = second.post(
        "/audits", files=files, data={"consent": "on"}, headers=ip, follow_redirects=False
    )
    assert capped.status_code == 303 and "acct=welcome" not in capped.headers["location"]


def test_a_deleted_account_cannot_sign_up_again_for_another_free_report(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, welcome=True)
    assert "acct=welcome" in _upload(client).headers["location"]
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    store.delete_account(account.id)  # type: ignore[attr-defined]
    assert store.welcome_used(account.id)  # type: ignore[attr-defined]


def test_the_free_report_address_is_cleared_by_the_purge(tmp_path: Path) -> None:
    _, store, _ = _client(tmp_path)
    old = datetime(2026, 1, 1, tzinfo=UTC)
    store.spend_welcome("acc", at=old)  # type: ignore[attr-defined]
    store.grant_welcome(  # type: ignore[attr-defined]
        "b" * 32, "acc2", device_sha256="d", file_sha256="f", client_ip="1.2.3.4", at=old
    )
    since = datetime(2025, 12, 1, tzinfo=UTC)
    assert (
        store.welcome_refusal(  # type: ignore[attr-defined]
            "x", device_sha256="", file_sha256="", client_ip="1.2.3.4", since=since, per_ip=1
        )
        == ""  # grant failed: there is no such audit, so nothing was recorded
    )
    with store.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(
            store.welcome_reports.insert().values(  # type: ignore[attr-defined]
                account_id="acc3",
                audit_id="",
                device_sha256="d",
                file_sha256="f",
                client_ip="1.2.3.4",
                created_at=old.isoformat(),
            )
        )
    assert (
        store.welcome_refusal(  # type: ignore[attr-defined]
            "x", device_sha256="", file_sha256="", client_ip="1.2.3.4", since=since, per_ip=1
        )
        == "network"
    )
    store.purge_expired(NOW, retention_days=30)  # type: ignore[attr-defined]
    assert (
        store.welcome_refusal(  # type: ignore[attr-defined]
            "x", device_sha256="", file_sha256="", client_ip="1.2.3.4", since=since, per_ip=1
        )
        == ""
    )
    # The device and the file still count after the purge.
    assert (
        store.welcome_refusal(  # type: ignore[attr-defined]
            "x", device_sha256="d", file_sha256="", client_ip="", since=since, per_ip=1
        )
        == "device"
    )


# -- the limits hold under simultaneous uploads ------------------------------------
def test_claims_are_all_or_nothing_and_never_hand_out_a_slot_twice(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _, store, _ = _client(tmp_path)
    slots = {"account": [f"preview:account:a:2026-09:{n}" for n in range(3)]}

    def claim(i: int) -> str:
        return store.claim_free(f"r{i}", keys=(), slots=slots, at=NOW)  # type: ignore[attr-defined]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))
    assert results.count("") == 3 and results.count("account") == 5
    # A full group rolls back the keys taken in the same call.
    assert store.claim_free("x", keys=("k",), slots=slots, at=NOW) == "account"  # type: ignore[attr-defined]
    assert store.claim_free("y", keys=("k",), slots={}, at=NOW) == ""  # type: ignore[attr-defined]
    assert store.claim_free("z", keys=("k",), slots={}, at=NOW) == "key"  # type: ignore[attr-defined]
    store.release_free("y")  # type: ignore[attr-defined]
    assert store.claim_free("z", keys=("k",), slots={}, at=NOW) == ""  # type: ignore[attr-defined]


def test_the_free_report_holds_when_the_first_look_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simultaneous uploads all pass the first look; the claims stop them."""
    from quant_trade.audit import accounts

    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    monkeypatch.setattr(store, "welcome_refusal", lambda *a, **k: "")
    monkeypatch.setattr(store, "free_previews_since", lambda *a, **k: 0)
    monkeypatch.setattr(accounts, "MAX_SIGNUPS_PER_HOUR", 50)
    outcomes = []
    for n in range(6):
        browser = TestClient(client.app)
        browser.cookies.set("rigor_device", "same-browser-id")
        _signup(browser, f"user{n}@example.com", welcome=True)
        files = {"equity": ("e.csv", csv_bytes(positive_drift(400 + n, seed=n + 20)), "text/csv")}
        answer = browser.post(
            "/audits",
            files=files,
            data={"consent": "on"},
            headers={"X-Forwarded-For": f"198.51.100.{n}"},
            follow_redirects=False,
        )
        outcomes.append(answer.headers["location"])
    assert sum("acct=welcome" in where for where in outcomes) == 1


def test_the_free_report_network_cap_and_previews_hold_when_the_first_look_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import accounts

    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    monkeypatch.setattr(store, "welcome_refusal", lambda *a, **k: "")
    monkeypatch.setattr(store, "free_previews_since", lambda *a, **k: 0)
    monkeypatch.setattr(accounts, "MAX_SIGNUPS_PER_HOUR", 50)
    ip = {"X-Forwarded-For": "203.0.113.90"}
    welcomes = 0
    for n in range(5):
        browser = TestClient(client.app)
        _signup(browser, f"net{n}@example.com", welcome=True)
        files = {"equity": ("e.csv", csv_bytes(positive_drift(400 + n, seed=n + 40)), "text/csv")}
        answer = browser.post(
            "/audits", files=files, data={"consent": "on"}, headers=ip, follow_redirects=False
        )
        welcomes += "acct=welcome" in answer.headers["location"]
    assert welcomes == 3  # WELCOME_REPORTS_PER_IP_PER_MONTH
    # One account's previews stop at 3 even when every first look says 0 used.
    solo = TestClient(client.app)
    _signup(solo, "solo@example.com")
    statuses = [
        solo.post(
            "/audits",
            files={"equity": ("e.csv", csv_bytes(positive_drift(500)), "text/csv")},
            data={"consent": "on"},
            headers={"X-Forwarded-For": "192.0.2.10"},
            follow_redirects=False,
        ).status_code
        for _ in range(5)
    ]
    assert statuses == [303, 303, 303, 402, 402]
    account = store.find_account("solo@example.com")  # type: ignore[attr-defined]
    # A refused upload leaves no audit behind on the account.
    assert len(store.account_audits_list(account.id)) == 3  # type: ignore[attr-defined]


def test_one_extra_byte_does_not_make_a_new_file(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    body = csv_bytes(positive_drift(450, seed=11))
    _signup(client, "a@example.com", welcome=True)
    first = client.post(
        "/audits",
        files={"equity": ("a.csv", body, "text/csv")},
        data={"consent": "on"},
        follow_redirects=False,
    )
    assert "acct=welcome" in first.headers["location"]
    other = TestClient(client.app)
    _signup(other, "b@example.com", welcome=True)
    again = other.post(
        "/audits",
        files={"equity": ("b.csv", body + b"\n", "text/csv")},
        data={"consent": "on"},
        follow_redirects=False,
    )
    assert again.status_code == 303 and "acct=welcome" not in again.headers["location"]


def test_network_claims_hold_only_a_hash_and_the_purge_drops_them(tmp_path: Path) -> None:
    from quant_trade.audit.accounts import network_key

    _, store, _ = _client(tmp_path)
    old = datetime(2026, 1, 5, tzinfo=UTC)
    key = f"preview:ip:{network_key('1.2.3.4')}:2026-01:0"
    assert "1.2.3.4" not in key
    store.claim_free("r", keys=(key, "preview:account:a:2026-01:0"), slots={}, at=old)  # type: ignore[attr-defined]
    store.purge_expired(NOW, retention_days=30)  # type: ignore[attr-defined]
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        left = [row[0] for row in conn.execute(store.free_claims.select())]  # type: ignore[attr-defined]
    assert left == ["preview:account:a:2026-01:0"]


def test_landing_says_before_the_file_that_an_upload_needs_an_account(tmp_path: Path) -> None:
    client, _store, _settings_ = _client(tmp_path)
    for path, words, signup in (
        ("/", "Antes de subir, crea tu cuenta gratis", "/registro"),
        ("/en", "Before you upload, create your free account", "/signup"),
    ):
        page = client.get(path).text
        box = page.split("class='signin-first'")[1].split("</div></div>")[0]
        assert words in box and f"href='{signup}'" in box
        # It sits above the file fields, so nobody fills the form in to be turned away.
        assert page.index("class='signin-first'") < page.index("name='report'")
        assert find_claims(box) == []
    _signup(client)
    assert "class='signin-first'" not in client.get("/").text
    free, _store, _settings_ = _client(tmp_path / "free", free_mode=True)
    assert "class='signin-first'" not in free.get("/").text


# -- small screens after sign-up ---------------------------------------------------
def test_a_new_account_is_invited_to_upload_its_first_file(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client)
    page = client.get("/cuenta").text
    assert "Subir mi primer archivo" in page and "Auditar otro archivo" not in page
    _upload(client)
    assert "Auditar otro archivo" in client.get("/cuenta").text


def test_the_sign_in_gate_says_the_file_was_not_kept_and_returns_to_the_form(
    tmp_path: Path,
) -> None:
    client, _, _ = _client(tmp_path)
    refused = _upload(client)
    assert refused.status_code == 401
    assert "Tu archivo no se guardó" in refused.text
    assert "href='/registro?next=/%23subir'" in refused.text
    assert not find_claims(re.sub(r"<[^>]+>", " ", refused.text))
    signup = client.get("/registro?next=/%23subir").text
    assert "name='next' value='/#subir'" in signup
    answer = client.post(
        "/registro",
        data={
            "email": "back@example.com",
            "password": PASSWORD,
            "csrf": _csrf(signup),
            "next": "/#subir",
        },
        follow_redirects=False,
    )
    assert answer.status_code == 303 and answer.headers["location"] == "/#subir"


def test_the_account_buys_on_whatsapp_with_the_same_three_steps(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client)
    page = client.get("/cuenta").text
    assert "Comprar por WhatsApp" in page and "Pedir un código" not in page
    assert page.count("<li>", page.index("buy-steps")) >= 3
    assert "Responde una persona" in page
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))


# -- comparing from the account ----------------------------------------------------
def test_signing_in_from_a_comparison_returns_to_it(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    ids = "id=" + "a" * 32 + "&id=" + "b" * 32
    answer = client.get(f"/cuenta/comparar?{ids}", follow_redirects=False)
    assert answer.status_code == 303
    where = answer.headers["location"]
    assert where.startswith("/entrar?next=") and "%2Fcuenta%2Fcomparar%3Fid%3D" in where
    page = client.get(where).text
    assert f"name='next' value='/cuenta/comparar?{ids.replace('&', '&amp;')}'" in page


def test_the_public_compare_page_points_a_signed_in_visitor_to_their_list(
    tmp_path: Path,
) -> None:
    client, _, _ = _client(tmp_path)
    assert "class='cmp-mine'" not in client.get("/comparar").text
    _signup(client)
    for path, words, href in (
        ("/comparar", "Elegir en mis informes", "/cuenta#informes"),
        ("/compare", "Pick from my reports", "/account#informes"),
    ):
        page = client.get(path).text
        assert words in page and f"href='{href}'" in page
        assert not find_claims(re.sub(r"<[^>]+>", " ", page))
    assert "id='informes'" in client.get("/cuenta").text


# -- hardening before launch -------------------------------------------------------
def test_a_stranger_who_knows_the_email_cannot_lock_the_owner_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import accounts

    monkeypatch.setattr(accounts, "MAX_FAILED_SIGNINS_PER_EMAIL", 3)
    client, _, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client, "owner@example.com")
    client.cookies.clear()
    for n in range(4):
        _signin(client, "owner@example.com", "wrong password here", ip=f"203.0.113.{n}")
    # The attacker's address that already failed gets one more try past the
    # ceiling, then is stopped...
    assert (
        _signin(client, "owner@example.com", "wrong again!!", ip="203.0.113.1").status_code == 401
    )
    blocked = _signin(client, "owner@example.com", "wrong password again", ip="203.0.113.1")
    assert blocked.status_code == 429
    # ...but the owner, from a network with no failures, still signs in.
    owner = _signin(client, "owner@example.com", ip="198.51.100.9")
    assert owner.status_code == 303


def test_sign_in_limits_survive_a_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from quant_trade.audit import accounts

    monkeypatch.setattr(accounts, "MAX_FAILED_SIGNINS_PER_HOUR", 2)
    settings = _settings(tmp_path, trusted_proxy_hops=1)
    store = make_store(settings.database_url)
    first = TestClient(create_app(settings, store))
    _signup(first, "kept@example.com")
    first.cookies.clear()
    for _ in range(2):
        _signin(first, "kept@example.com", "wrong password here", ip="203.0.113.7")
    # A deploy: a new app on the same database keeps the count.
    again = TestClient(create_app(settings, make_store(settings.database_url)))
    assert _signin(again, "kept@example.com", ip="203.0.113.7").status_code == 429
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        keys = [
            row[0]
            for row in conn.execute(
                store.attempts.select().with_only_columns(store.attempts.c.key_sha256)
            )
        ]  # type: ignore[attr-defined]
    assert keys and all("@" not in key and "203.0" not in key for key in keys)


def test_an_upload_posted_from_another_site_is_refused(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    files = {"equity": ("e.csv", csv_bytes(positive_drift(300)), "text/csv")}

    def post(headers: dict[str, str]) -> int:
        return client.post(
            "/audits", files=files, data={"consent": "on"}, headers=headers, follow_redirects=False
        ).status_code

    for header in (
        {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
        # Another app under the same parent domain counts as same-site.
        {"Sec-Fetch-Site": "same-site", "Origin": "https://evil.up.railway.app"},
        # An attacker page with its own no-referrer policy: the fetch header still tells.
        {"Sec-Fetch-Site": "cross-site", "Origin": "null"},
        # An old browser without Sec-Fetch-Site: Origin, else Referer, decides.
        {"Origin": "https://evil.up.railway.app"},
        {"Referer": "https://evil.example/page"},
    ):
        assert post(header) == 403, header
    refused = client.post(
        "/audits", files=files, data={"consent": "on"}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert "no viene del formulario de este sitio" in refused.text
    # What a real browser sends from our own form (our pages say no-referrer):
    # Origin null, no Referer, Sec-Fetch-Site same-origin. It reaches the gate.
    assert post({"Sec-Fetch-Site": "same-origin", "Origin": "null"}) == 401
    assert post({"Sec-Fetch-Site": "none"}) == 401
    # An old browser from our own page, and a script with no headers, go through too.
    assert post({"Origin": "null"}) == 401
    assert post({"Origin": "http://testserver"}) == 401
    assert post({}) == 401


def test_common_passwords_are_refused_offline() -> None:
    from quant_trade.audit.accounts import common_password, password_problem

    for weak in (
        "1234567890",
        "qwertyuiop",
        "password123",
        "Password2024!",
        "contraseña123",
        "aaaaaaaaaaaa",
        "abcabcabcabc",
        "iloveyou2020",
        "1qaz2wsx3edc",
        "trader12345",
        "20240521198801",
        "P@ssw0rd2024",
        "p4ssw0rd!2025",
        "1q2w3e4r5t6y",
        "zaq12wsxcde3",
    ):
        assert common_password(weak), weak
        assert password_problem(weak) == "password_common", weak
    assert password_problem("anapaula1990", email="anapaula@example.com") == "password_common"
    for fine in (
        PASSWORD,
        "long safe phrase",
        "correct horse battery",
        "MiPerroSeLlamaTobi",
        "Tr0mb0n-azul-83",
    ):
        assert not common_password(fine), fine


def test_sign_up_and_password_change_refuse_a_common_password(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    csrf = _csrf(client.get("/registro").text)
    refused = client.post(
        "/registro",
        data={"email": "weak@example.com", "password": "password123", "csrf": csrf},
        follow_redirects=False,
    )
    assert refused.status_code == 400 and "primeras que prueba cualquier lista" in refused.text
    _signup(client, "strong@example.com")
    page = client.get("/cuenta").text
    answer = client.post(
        "/cuenta/contrasena",
        data={"current": PASSWORD, "password": "qwertyuiop123", "csrf": _csrf(page)},
        follow_redirects=False,
    )
    assert answer.headers["location"].endswith("?error=password_common")
    assert "primeras que prueba cualquier lista" in client.get(answer.headers["location"]).text


def test_sign_up_and_the_account_say_what_is_kept_and_how_to_delete_it(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path, retention_days=21)
    for path, words in (
        ("/registro", "Qué guardamos y cómo borrarlo"),
        ("/signup", "What we keep and how to delete it"),
    ):
        page = client.get(path).text
        assert words in page and "21" in page and "Stripe" in page
        assert not find_claims(re.sub(r"<[^>]+>", " ", page))
    _signup(client)
    upload = _upload(client)
    audit_id = _audit_id(upload.headers["location"])
    store.mark_paid(audit_id, stripe_session_id="cs_x", at=NOW)  # type: ignore[attr-defined]
    page = client.get("/cuenta").text
    assert "Qué guardamos y cómo borrarlo" in page and "Borrar mi cuenta" in page
    # Each purchase names its report.
    purchases = page.split("Tus compras", 1)[1]
    assert f"<code title='{audit_id}'>{audit_id[:8]}</code>" in purchases
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))


def test_what_we_keep_matches_the_purge_for_the_free_report(tmp_path: Path) -> None:
    """The free report stays past the retention days and its upload IP goes, as promised."""
    client, store, _ = _client(tmp_path, retention_days=21)
    _signup(client, welcome=True)
    audit_id = _audit_id(_upload(client).headers["location"])
    store.purge_expired(NOW + timedelta(days=400), retention_days=21)  # type: ignore[attr-defined]
    record = store.get_audit(audit_id)  # type: ignore[attr-defined]
    assert record is not None and record.result_json and record.client_ip == ""
    for path, kept, ip, stays in (
        (
            "/cuenta",
            "los pagados y tu informe gratis quedan",
            "La dirección IP de cada subida",
            "Se conservan aunque borres la cuenta, sin tu correo",
        ),
        (
            "/account",
            "paid ones and your free report stay",
            "The IP address of each upload",
            "They stay even if you delete the account, without your e-mail",
        ),
    ):
        page = re.sub(r"\s+", " ", client.get(path).text)
        assert kept in page and ip in page and stays in page and "21" in page
    ctx = LegalContext(retention_days=21)
    es = " ".join(" ".join(p) for _, p in privacy_text(ctx, "es").sections)
    en = " ".join(" ".join(p) for _, p in privacy_text(ctx, "en").sections)
    assert "tu primer informe completo gratis: se conservan" in es
    assert "aunque borres tu cuenta y sin tu correo" in es
    assert "your free first full report: kept" in en
    assert "even if you delete your account and without your e-mail" in en


def test_the_account_screens_exist_in_portuguese(tmp_path: Path) -> None:
    from quant_trade.audit import account_pages

    assert set(account_pages.COPY["pt"]) == set(account_pages.COPY["en"])
    client, store, _ = _client(tmp_path)
    page = client.get("/pt/cadastro").text
    assert "<html lang='pt'" in page and "Crie sua conta" in page
    assert "O que guardamos e como apagar" in page
    assert "href='/registro'" in page and "href='/signup'" in page  # language switch
    assert "/terms?lang=en" in page  # the terms are not in Portuguese yet
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))
    # ?lang=pt on a Spanish path reads in Portuguese too.
    assert "Crie sua conta" in client.get("/registro?lang=pt").text
    # The Portuguese landing sends its visitors to the Portuguese sign-up.
    assert "/pt/cadastro" in client.get("/pt").text
    csrf = _csrf(page)
    answer = client.post(
        "/pt/cadastro",
        data={"email": "ana@example.com", "password": PASSWORD, "csrf": csrf},
        follow_redirects=False,
    )
    assert answer.headers["location"].startswith("/pt/conta")
    audit_id = _audit_id(_upload(client).headers["location"])
    store.mark_paid(audit_id, stripe_session_id="cs_pt", at=NOW)  # type: ignore[attr-defined]
    page = client.get("/pt/conta").text
    assert "Meus relatórios" in page and "Minhas estratégias" in page
    assert f"/audits/{audit_id}?lang=en" in page  # the report itself reads in English
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))
    where = client.post(
        "/pt/conta/estrategias/guardar",
        data={"audit_id": audit_id, "strategy": "new", "name": "EA Ouro", "csrf": _csrf(page)},
        follow_redirects=False,
    ).headers["location"]
    assert where.startswith("/pt/conta/estrategias/")
    view = client.get(where).text
    assert "<html lang='pt'" in view and "Versão" in view and "EA Ouro" in view
    assert not find_claims(re.sub(r"<[^>]+>", " ", view))
    # A wrong password on the Portuguese sign-in stays in Portuguese.
    client.post("/pt/sair", data={"csrf": _csrf(page)})
    csrf = _csrf(client.get("/pt/entrar").text)
    wrong = client.post(
        "/pt/entrar",
        data={"email": "ana@example.com", "password": "not the password", "csrf": csrf},
    )
    assert "O e-mail ou a senha não conferem" in wrong.text


# -- "Mis estrategias" -------------------------------------------------------------
def test_strategy_changes_are_called_better_or_worse_only_beyond_the_noise() -> None:
    from quant_trade.audit.strategies import class_change, sharpe_change, what_changed

    def result(overall: str, low: float, high: float, dims: dict[str, str]) -> dict:
        band = {
            "p5": {"value": low, "evidence": "MEASURED"},
            "p95": {"value": high, "evidence": "MEASURED"},
        }
        return {
            "inputs": {"periods_per_year": 252},
            "verdict": {
                "overall": overall,
                "dimensions": [{"name": k, "status": v} for k, v in dims.items()],
            },
            "bootstrap": {"sharpe_per_period": band},
            "performance": {"sharpe": {"value": (low + high) * 8, "evidence": "MEASURED"}},
        }

    assert class_change("C", "B") == "better" and class_change("A", "B") == "worse"
    old = result("C", 0.02, 0.06, {"statistical_significance": "WEAK", "costs": "NOT_MEASURED"})
    overlap = result("B", 0.05, 0.09, {"statistical_significance": "PASS", "costs": "PASS"})
    apart = result("B", 0.07, 0.11, {"statistical_significance": "PASS"})
    assert sharpe_change(old, overlap) == "unclear"
    assert sharpe_change(old, apart) == "better" and sharpe_change(apart, old) == "worse"
    daily_vs_hourly = dict(apart, inputs={"periods_per_year": 6048})
    assert sharpe_change(old, daily_vs_hourly) == "different_frequency"
    lines = dict(what_changed(old, overlap, "es"))
    assert lines["Clase: C → B"] == "mejor"
    assert any(word == "sin cambio claro" for word in lines.values())
    # A dimension that was not measured before is not called better.
    assert not any(k.startswith("Costes") for k in lines)
    pt = dict(what_changed(old, overlap, "pt"))
    assert pt["Classe: C → B"] == "melhor" and "sem mudança clara" in pt.values()
    assert "Significância estatística: Fraca → Passa" in pt
    # Dimension lines say "changed": each report carries its own declarations.
    assert lines["Significación estadística: Débil → Supera"] == "cambió"
    # Dates that barely overlap: the market of those dates could explain it.
    dated = {"periods_per_year": 252, "first_timestamp": "2020-01-01T00:00:00Z"}
    early = dict(old, inputs=dict(dated, last_timestamp="2021-01-01T00:00:00Z"))
    late = dict(
        apart,
        inputs=dict(
            dated, first_timestamp="2020-11-01T00:00:00Z", last_timestamp="2022-01-01T00:00:00Z"
        ),
    )
    assert sharpe_change(early, late) == "different_periods"
    same_dates = dict(apart, inputs=dict(dated, last_timestamp="2021-01-01T00:00:00Z"))
    assert sharpe_change(early, same_dates) == "better"


def test_two_daily_files_of_different_length_are_comparable(tmp_path: Path) -> None:
    """Periods per year are inferred, so two daily files never match exactly."""
    import json

    from quant_trade.audit.strategies import sharpe_change

    client, store, _ = _client(tmp_path)
    _signup(client)
    results = []
    for rows in (750, 760):
        files = {"equity": ("e.csv", csv_bytes(positive_drift(rows)), "text/csv")}
        answer = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
        record = store.get_audit(_audit_id(answer.headers["location"]))  # type: ignore[attr-defined]
        results.append(json.loads(record.result_json))
    ppy = [r["inputs"]["periods_per_year"]["value"] for r in results]
    assert ppy[0] != ppy[1]
    assert sharpe_change(results[0], results[1]) in ("better", "worse", "unclear")


def test_a_strategy_groups_versions_and_says_what_changed(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    ids = []
    for seed in (1, 2, 3):
        files = {"equity": ("e.csv", csv_bytes(positive_drift(500, seed=seed)), "text/csv")}
        answer = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
        ids.append(_audit_id(answer.headers["location"]))
    for audit_id in ids[:2]:
        store.mark_paid(audit_id, stripe_session_id=f"cs_{audit_id}", at=NOW)  # type: ignore[attr-defined]
    page = client.get("/cuenta").text
    assert "Mis estrategias" in page and "Guardar un informe en una estrategia" in page
    csrf = _csrf(page)
    first = client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": ids[0], "strategy": "new", "name": "EA Oro", "csrf": csrf},
        follow_redirects=False,
    )
    where = first.headers["location"]
    assert where.startswith("/cuenta/estrategias/")
    strategy_id = where.rsplit("/", 1)[1]
    for audit_id in ids[1:]:
        client.post(
            "/cuenta/estrategias/guardar",
            data={"audit_id": audit_id, "strategy": strategy_id, "csrf": csrf},
            follow_redirects=False,
        )
    view = client.get(where).text
    assert "EA Oro" in view and "<td>v1</td>" in view and "<td>v3</td>" in view
    assert "Qué cambió frente a la versión 1" in view
    assert f"/cuenta/comparar?id={ids[0]}&amp;id={ids[1]}" in view
    # v3 is a locked preview: only its class change, no per-test detail.
    assert "las dos versiones tienen que ser informes completos" in view
    assert not find_claims(re.sub(r"<[^>]+>", " ", view))
    assert "EA Oro" in client.get("/cuenta").text
    # English page and rename.
    assert "My strategies" in client.get("/account").text
    assert "What changed against version 1" in client.get(f"/account/strategies/{strategy_id}").text
    client.post(f"{where}/nombre", data={"name": "EA Oro v2", "csrf": csrf})
    assert "EA Oro v2" in client.get(where).text
    # Removing a version keeps the report on the list.
    client.post(f"{where}/quitar", data={"audit_id": ids[2], "csrf": csrf})
    assert "<td>v3</td>" not in client.get(where).text
    # Deleting the strategy keeps every report.
    client.post(f"{where}/borrar", data={"csrf": csrf}, follow_redirects=False)
    assert client.get(where).status_code == 404
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    assert len(store.account_audits_list(account.id)) == 3  # type: ignore[attr-defined]


def test_strategies_stay_inside_their_account(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client, "one@example.com")
    mine = _audit_id(_upload(client).headers["location"])
    csrf = _csrf(client.get("/cuenta").text)
    where = client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": mine, "strategy": "new", "name": "Mía", "csrf": csrf},
        follow_redirects=False,
    ).headers["location"]
    other = TestClient(client.app)
    _signup(other, "two@example.com")
    assert other.get(where).status_code == 404
    other_csrf = _csrf(other.get("/cuenta").text)
    # Someone else's report cannot be filed, and someone else's strategy cannot be touched.
    bad = other.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": mine, "strategy": "new", "name": "Robo", "csrf": other_csrf},
        follow_redirects=False,
    )
    assert "error=file_bad" in bad.headers["location"]
    # The refused filing left no empty strategy behind.
    other_account = store.find_account("two@example.com")  # type: ignore[attr-defined]
    assert store.list_strategies(other_account.id) == []  # type: ignore[attr-defined]
    assert other.post(f"{where}/borrar", data={"csrf": other_csrf}).status_code == 404
    assert client.get(where).status_code == 200
    # Deleting the account removes its strategies.
    account = store.find_account("one@example.com")  # type: ignore[attr-defined]
    store.delete_account(account.id)  # type: ignore[attr-defined]
    assert store.list_strategies(account.id) == []  # type: ignore[attr-defined]


def test_strategy_names_drop_invisible_and_control_characters(tmp_path: Path) -> None:
    from quant_trade.audit.store import strategy_name

    assert strategy_name("EA\x00Oro") == "EAOro"
    assert strategy_name("EA \u202eOro\u200b\x07") == "EA Oro"
    assert strategy_name("\u202e\u200b") == "" and strategy_name(" \u0301 ") == ""
    assert strategy_name("  EA   Oro  ") == "EA Oro" and len(strategy_name("x" * 300)) == 80
    client, store, _ = _client(tmp_path)
    _signup(client)
    mine = _audit_id(_upload(client).headers["location"])
    csrf = _csrf(client.get("/cuenta").text)
    invisible = client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": mine, "strategy": "new", "name": "\u202e\u200b", "csrf": csrf},
        follow_redirects=False,
    )
    assert "error=file_bad" in invisible.headers["location"]
    where = client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": mine, "strategy": "new", "name": "EA\x00Oro\u202e", "csrf": csrf},
        follow_redirects=False,
    ).headers["location"]
    assert "EAOro" in client.get(where).text
    # An invisible rename keeps the old name.
    client.post(f"{where}/nombre", data={"name": "\u200b\u202e", "csrf": csrf})
    assert "EAOro" in client.get(where).text


def test_account_forms_refuse_a_cross_site_post(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    mine = _audit_id(_upload(client).headers["location"])
    csrf = _csrf(client.get("/cuenta").text)
    data = {"audit_id": mine, "strategy": "new", "name": "EA", "csrf": csrf}
    refused = client.post(
        "/cuenta/estrategias/guardar",
        data=data,
        headers={"Sec-Fetch-Site": "cross-site"},
        follow_redirects=False,
    )
    assert "error=csrf" in refused.headers["location"]
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    assert store.list_strategies(account.id) == []  # type: ignore[attr-defined]
    # A real browser form: same-origin, or Origin: null under no-referrer.
    for headers in ({"Sec-Fetch-Site": "same-origin"}, {"Origin": "null"}):
        answer = client.post(
            "/cuenta/estrategias/guardar", data=data, headers=headers, follow_redirects=False
        )
        assert answer.headers["location"].startswith("/cuenta/estrategias/")


# -- "Descargar mis datos" -----------------------------------------------------------
def test_download_my_data_returns_only_the_owners_rows(tmp_path: Path) -> None:
    import json

    client, store, _ = _client(tmp_path)
    assert client.get("/cuenta/datos", follow_redirects=False).status_code == 303
    _signup(client, "ana@example.com", welcome=True)
    code, record = store.create_access_code(credits=3, note="nota-privada", at=NOW)  # type: ignore[attr-defined]
    first = _audit_id(_upload(client).headers["location"])
    second_url = _upload(client, access_code=code).headers["location"]
    second = _audit_id(second_url)
    csrf = _csrf(client.get("/cuenta").text)
    client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": first, "strategy": "new", "name": "EA Oro", "csrf": csrf},
    )
    other = TestClient(client.app)
    _signup(other, "bea@example.com")
    theirs = _audit_id(_upload(other).headers["location"])

    answer = client.get("/cuenta/datos")
    assert answer.status_code == 200
    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["content-disposition"].startswith("attachment;")
    data = json.loads(answer.text)
    assert data["account"]["email"] == "ana@example.com"
    ids = {item["audit_id"] for item in data["reports"]}
    assert ids == {first, second} and theirs not in answer.text
    assert all(item["upload_ip"] for item in data["reports"])  # kept until the purge
    assert data["strategies"][0]["name"] == "EA Oro"
    assert data["strategies"][0]["reports"] == [first]
    assert data["access_codes"][0]["id"] == record.id
    assert data["free_first_report"]["audit_id"] == first
    assert "bea@example.com" not in answer.text
    # Never a secret: no password hash, no token, no code, no owner's note.
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    for secret in ("scrypt$", code, "nota-privada", second_url.split("token=")[1][:20]):
        assert secret not in answer.text
    sessions = store.account_sessions  # type: ignore[attr-defined]
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        tokens = [row[0] for row in conn.execute(sessions.select()).all()]
    assert tokens and not any(token in answer.text for token in tokens)
    assert account is not None
    # The other account downloads only its own.
    mine = json.loads(other.get("/account/datos").text)
    assert [item["audit_id"] for item in mine["reports"]] == [theirs]
    # The button on the account page, in every language, and the promise in /privacidad.
    for path, words in (
        ("/cuenta", "Descargar mis datos"),
        ("/account", "Download my data"),
        ("/pt/conta", "Baixar meus dados"),
    ):
        page = client.get(path).text
        assert words in page and "/datos'" in page
        assert not find_claims(re.sub(r"<[^>]+>", " ", page))
    ctx = LegalContext()
    es = " ".join(" ".join(p) for _, p in privacy_text(ctx, "es").sections)
    en = " ".join(" ".join(p) for _, p in privacy_text(ctx, "en").sections)
    assert "«Descargar mis datos»" in es and "'Download my data'" in en


def test_download_my_data_refuses_cross_site_and_hides_others_descriptions(
    tmp_path: Path,
) -> None:
    import json

    client, store, _ = _client(tmp_path)
    _signup(client, "ana@example.com")
    # An anonymous upload paid with a code, later saved by Ana from its link.
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    stranger = TestClient(client.app)
    theirs = _audit_id(
        _upload(stranger, description="mi robot secreto", access_code=code).headers["location"]
    )
    with store.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(store.audits.update().values(paid=False, paid_at=None))  # type: ignore[attr-defined]
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    store.link_audit(account.id, theirs, at=NOW)  # type: ignore[attr-defined]  # saved from a link
    refused = client.get(
        "/cuenta/datos", headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False
    )
    assert refused.status_code == 303 and refused.headers["location"] == "/cuenta"
    data = json.loads(client.get("/cuenta/datos", headers={"Sec-Fetch-Site": "none"}).text)
    saved = next(item for item in data["reports"] if item["audit_id"] == theirs)
    assert saved["description"] == "" and saved["upload_ip"] == ""
    assert "mi robot secreto" not in json.dumps(data)
    # Once this account pays for it, the description is part of what it bought.
    store.mark_paid(theirs, stripe_session_id="cs_saved", at=NOW)  # type: ignore[attr-defined]
    data = json.loads(client.get("/cuenta/datos").text)
    assert "mi robot secreto" in json.dumps(data, ensure_ascii=False)


def test_a_strategy_summary_prints_without_forms_and_only_for_its_owner(tmp_path: Path) -> None:
    from quant_trade.audit import pdf as pdf_lib

    client, store, _ = _client(tmp_path)
    _signup(client)
    ids = [_audit_id(_upload(client).headers["location"]) for _ in range(2)]
    for audit_id in ids:
        store.mark_paid(audit_id, stripe_session_id=f"cs_{audit_id}", at=NOW)  # type: ignore[attr-defined]
    csrf = _csrf(client.get("/cuenta").text)
    where = client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": ids[0], "strategy": "new", "name": "EA Oro", "csrf": csrf},
        follow_redirects=False,
    ).headers["location"]
    client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": ids[1], "strategy": where.rsplit("/", 1)[1], "csrf": csrf},
    )
    view = client.get(where).text
    assert f"href='{where}/pdf'" in view and "Descargar resumen en PDF" in view
    # The printable page: same content, no forms or buttons, the date and the notice.
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    strategy = store.list_strategies(account.id)[0]  # type: ignore[attr-defined]
    listed = {a.audit_id: a for a in store.account_audits_list(account.id)}  # type: ignore[attr-defined]
    versions = [
        (listed[i], json.loads(store.get_audit(i).result_json))  # type: ignore[attr-defined]
        for i in ids
    ]
    printable = account_pages.strategy_page(
        locale="es",
        csrf="x" * 30,
        strategy=strategy,
        versions=versions,
        printable=True,
        generated_at="2026-09-26T01:00:00Z",
    )
    assert "<form" not in printable and "x" * 30 not in printable
    assert "generado el 2026-09-26" in printable and "No es asesoría de inversión" in printable
    assert "Qué cambió frente a la versión 1" in printable
    assert "href='/audits/" not in printable  # a PDF carries no links to reports
    assert not find_claims(re.sub(r"<[^>]+>", " ", printable))
    # Only the owner, signed in.
    other = TestClient(client.app)
    _signup(other, "bea@example.com")
    assert other.get(f"{where}/pdf").status_code == 404
    assert TestClient(client.app).get(f"{where}/pdf", follow_redirects=False).status_code == 303
    if pdf_lib.available():
        answer = client.get(f"{where}/pdf")
        assert answer.status_code == 200 and answer.content.startswith(b"%PDF")
        assert "no-store" in answer.headers["cache-control"]
        assert "attachment;" in answer.headers["content-disposition"]


def test_strategy_pdfs_are_cached_and_limited_per_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import pdf as pdf_lib
    from quant_trade.audit import web

    pages: list[str] = []

    def fake_pdf(page: str, **_: object) -> bytes:
        pages.append(page)
        return b"%PDF-fake"

    monkeypatch.setattr(pdf_lib, "report_pdf", fake_pdf)
    client, store, _ = _client(tmp_path)
    _signup(client)
    audit_id = _audit_id(_upload(client).headers["location"])
    csrf = _csrf(client.get("/cuenta").text)
    where = client.post(
        "/cuenta/estrategias/guardar",
        data={"audit_id": audit_id, "strategy": "new", "name": "EA Oro", "csrf": csrf},
        follow_redirects=False,
    ).headers["location"]
    for _ in range(3):
        assert client.get(f"{where}/pdf").content == b"%PDF-fake"
    assert len(pages) == 1  # the same summary renders once
    assert "class='skip'" not in pages[0] and "href='/audits/" not in pages[0]
    # A change (a rename) renders again; past the window's limit, a 429.
    for n in range(web.STRATEGY_PDFS_PER_WINDOW):
        client.post(f"{where}/nombre", data={"name": f"EA {n}", "csrf": csrf})
        client.get(f"{where}/pdf")
    refused = client.get(f"{where}/pdf")
    assert refused.status_code == 429 and "PDF" in refused.text
    assert len(pages) == web.STRATEGY_PDFS_PER_WINDOW
    # The cached one still downloads.
    client.post(f"{where}/nombre", data={"name": "EA 0", "csrf": csrf})
    assert client.get(f"{where}/pdf").status_code == 200


# -- "Invita a un colega" -----------------------------------------------------------
def _invite_token(client: TestClient) -> str:
    match = re.search(r"invita=([\w-]+)", client.get("/cuenta").text)
    assert match, "no invite link on the account page"
    return match.group(1)


def _join(client: TestClient, email: str, token: str, headers: dict[str, str] | None = None):
    page = client.get(f"/registro?invita={token}").text
    return client.post(
        "/registro",
        data={"email": email, "password": PASSWORD, "csrf": _csrf(page), "invite": token},
        headers=headers or {},
        follow_redirects=False,
    )


def _seeded_file(seed: int) -> dict[str, tuple[str, bytes, str]]:
    return {"equity": ("e.csv", csv_bytes(positive_drift(430, seed=seed)), "text/csv")}


def test_an_invite_credits_the_inviter_once_the_new_account_gets_its_free_report(
    tmp_path: Path,
) -> None:
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    ana_ip = {"X-Forwarded-For": "203.0.113.10"}
    _signup(client, welcome=True)
    assert (
        "acct=welcome"
        in client.post(
            "/audits",
            files=_seeded_file(21),
            data={"consent": "on"},
            headers=ana_ip,
            follow_redirects=False,
        ).headers["location"]
    )
    page = client.get("/cuenta").text
    assert "Invita a un colega" in page and "hasta 5 al mes" in page and "wa.me" in page
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))
    token = _invite_token(client)
    assert token == _invite_token(client)  # the same link every time
    ana = store.find_account("ana@example.com")  # type: ignore[attr-defined]

    # A colleague in another browser and network: invited, then credited.
    bea = TestClient(client.app)
    assert "Un colega te invitó" in bea.get(f"/registro?invita={token}").text
    assert _join(bea, "bea@example.com", token).status_code == 303
    assert "Esperan su primer informe" in client.get("/cuenta").text
    assert store.account_credits(ana.id, datetime.now(UTC)) == 0  # type: ignore[attr-defined]
    bea_ip = {"X-Forwarded-For": "198.51.100.20"}
    upload = bea.post(
        "/audits",
        files=_seeded_file(22),
        data={"consent": "on"},
        headers=bea_ip,
        follow_redirects=False,
    )
    assert "acct=welcome" in upload.headers["location"]
    assert store.account_credits(ana.id, datetime.now(UTC)) == 1  # type: ignore[attr-defined]
    summary = store.invite_summary(ana.id, datetime.now(UTC))  # type: ignore[attr-defined]
    assert (summary.joined, summary.waiting, summary.credited) == (1, 0, 1)
    assert "bea@example.com" not in client.get("/cuenta").text  # never who joined
    # A second upload of the new account credits nothing more.
    bea.post("/audits", files=_seeded_file(23), data={"consent": "on"}, headers=bea_ip)
    assert store.account_credits(ana.id, datetime.now(UTC)) == 1  # type: ignore[attr-defined]

    # Someone on Ana's own network is taken as Ana: joined, no credit.
    carl = TestClient(client.app)
    _join(carl, "carl@example.com", token)
    carl.post("/audits", files=_seeded_file(24), data={"consent": "on"}, headers=ana_ip)
    assert store.account_credits(ana.id, datetime.now(UTC)) == 1  # type: ignore[attr-defined]
    summary = store.invite_summary(ana.id, datetime.now(UTC))  # type: ignore[attr-defined]
    assert (summary.joined, summary.credited) == (2, 1)

    # Ana's own browser (her free report's mark) is never noted as an invite.
    device = client.cookies.get("rigor_device")
    mine = TestClient(client.app)
    mine.cookies.set("rigor_device", device)
    _join(mine, "dan@example.com", token)
    assert store.invite_summary(ana.id, datetime.now(UTC)).joined == 2  # type: ignore[attr-defined]

    # The data download carries dates and outcomes, never the other account.
    data = json.loads(client.get("/cuenta/datos").text)
    assert data["invites"]["link_token"] == token
    assert [item["outcome"] for item in data["invites"]["joined"]] == ["credited", "self"]
    assert "bea@example.com" not in json.dumps(data)
    assert json.loads(bea.get("/cuenta/datos").text)["invites"]["joined_through_an_invite"]


def test_invites_ignore_bad_tokens_the_signed_in_inviter_and_the_monthly_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import accounts

    monkeypatch.setattr(accounts, "REFERRAL_MONTHLY_CAP", 1)
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client)
    token = _invite_token(client)
    ana = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    # An unknown or malformed token: a normal sign-up, no banner, nothing noted.
    stranger = TestClient(client.app)
    assert "Un colega te invitó" not in stranger.get("/registro?invita=nope<script>").text
    assert _join(stranger, "eve@example.com", "x" * 20).status_code == 303
    assert store.invite_summary(ana.id, datetime.now(UTC)).joined == 0  # type: ignore[attr-defined]
    # The inviter, still signed in, posting a sign-up with its own link.
    _join(client, "fake@example.com", token)
    assert store.invite_summary(ana.id, datetime.now(UTC)).joined == 0  # type: ignore[attr-defined]
    # Past the month's cap an invite still joins, with no credit.
    for n, email in enumerate(("bea@example.com", "carl@example.com")):
        friend = TestClient(client.app)
        _join(friend, email, token)
        friend.post(
            "/audits",
            files=_seeded_file(30 + n),
            data={"consent": "on"},
            headers={"X-Forwarded-For": f"198.51.100.{40 + n}"},
        )
    summary = store.invite_summary(ana.id, datetime.now(UTC))  # type: ignore[attr-defined]
    assert (summary.joined, summary.credited, summary.credited_this_month) == (2, 1, 1)
    assert store.account_credits(ana.id, datetime.now(UTC)) == 1  # type: ignore[attr-defined]


def test_deleting_either_account_removes_its_invite_rows(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    token = _invite_token(client)
    friend = TestClient(client.app)
    _join(friend, "bea@example.com", token)
    ana = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    bea = store.find_account("bea@example.com")  # type: ignore[attr-defined]
    assert store.invite_summary(ana.id, datetime.now(UTC)).joined == 1  # type: ignore[attr-defined]
    store.delete_account(bea.id)  # type: ignore[attr-defined]
    assert store.invite_summary(ana.id, datetime.now(UTC)).joined == 0  # type: ignore[attr-defined]
    store.delete_account(ana.id)  # type: ignore[attr-defined]
    assert store.inviter_for_token(token) is None  # type: ignore[attr-defined]
    for gone in (ana.id, bea.id):
        assert store.account_export(gone) is None  # type: ignore[attr-defined]
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        assert not conn.execute(store.referrals.select()).all()  # type: ignore[attr-defined]
        assert not conn.execute(store.invite_links.select()).all()  # type: ignore[attr-defined]


def test_invite_screens_exist_in_every_language_and_pass_the_guard() -> None:
    from quant_trade.audit.store import InviteSummary

    for locale in account_pages.LANGUAGES:
        html = account_pages.invite_section(
            locale,
            account_pages.InviteView(
                link="https://example.test/registro?invita=abc12345",
                summary=InviteSummary(joined=3, waiting=1, credited=2, credited_this_month=1),
                credits=1,
                monthly_cap=5,
            ),
        )
        text = re.sub(r"<[^>]+>", " ", html)
        assert "abc12345" in html and not find_claims(text)
        assert "{" not in text
        signup = account_pages.signup_page(locale=locale, csrf="c" * 30, invite="abc12345")
        assert "name='invite' value='abc12345'" in signup
        assert account_pages.COPY[locale]["invited_banner"] in signup


def test_deleting_credited_invitees_never_frees_the_monthly_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import accounts

    monkeypatch.setattr(accounts, "REFERRAL_MONTHLY_CAP", 2)
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client)
    token = _invite_token(client)
    ana = store.find_account("ana@example.com")  # type: ignore[attr-defined]

    def invite(n: int) -> TestClient:
        friend = TestClient(client.app)
        _join(friend, f"friend{n}@example.com", token)
        friend.get("/cuenta")  # the invitee's own invite link exists too
        friend.post(
            "/audits",
            files=_seeded_file(50 + n),
            data={"consent": "on"},
            headers={"X-Forwarded-For": f"198.51.100.{60 + n}"},
        )
        return friend

    for n in range(2):
        invite(n)
    assert store.account_credits(ana.id, datetime.now(UTC)) == 2  # type: ignore[attr-defined]
    for n in range(2):
        friend = store.find_account(f"friend{n}@example.com")  # type: ignore[attr-defined]
        store.delete_account(friend.id)  # type: ignore[attr-defined]
    invite(2)
    assert store.account_credits(ana.id, datetime.now(UTC)) == 2  # type: ignore[attr-defined]
    summary = store.invite_summary(ana.id, datetime.now(UTC))  # type: ignore[attr-defined]
    assert (summary.joined, summary.credited, summary.credited_this_month) == (3, 2, 2)
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        kept = conn.execute(store.referrals.select()).mappings().all()  # type: ignore[attr-defined]
        # The deleted invitees keep only an outcome under a random id.
        assert all(
            row["device_sha256"] == "" for row in kept if row["invitee_id"].startswith("gone")
        )
        tokens = conn.execute(store.invite_links.select()).mappings().all()  # type: ignore[attr-defined]
    assert {row["account_id"] for row in tokens} == {
        ana.id,
        store.find_account("friend2@example.com").id,  # type: ignore[attr-defined]
    }


def test_the_upload_gate_and_a_missing_strategy_speak_the_visitors_language(
    tmp_path: Path,
) -> None:
    client, _, _ = _client(tmp_path)
    gate = _upload(client, locale="pt")
    assert gate.status_code == 401
    assert "<html lang='pt'" in gate.text and "/pt/cadastro" in gate.text
    assert account_pages.COPY["pt"]["gate_signin_title"] in gate.text
    assert "Create your free account" not in gate.text
    _signup(client)
    for where, title in (
        ("/pt/conta/estrategias/999999", "Não encontramos essa estratégia"),
        ("/cuenta/estrategias/999999", "No encontramos esa estrategia"),
        ("/account/strategies/999999", "We could not find that strategy"),
    ):
        missing = client.get(where)
        assert missing.status_code == 404 and title in missing.text
        assert "encontramos esa audit" not in missing.text and "find that audit" not in missing.text


def test_a_preview_says_why_it_was_not_the_free_full_report(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    _signup(client, "first@example.com", welcome=True)
    assert "acct=welcome" in _upload(client).headers["location"]
    # The same file from a fresh browser on another account: a preview, told why.
    fresh = TestClient(client.app)
    _signup(fresh, "second@example.com", welcome=True)
    same_file = _upload(fresh).headers["location"]
    assert "acct=preview_file" in same_file
    assert account_pages.COPY["es"]["welcome_refused_file"] in fresh.get(same_file).text
    # The same browser with a new file on a third account, in Portuguese.
    device = client.cookies.get("rigor_device")
    again = TestClient(client.app)
    again.cookies.set("rigor_device", device)
    _signup(again, "third@example.com", welcome=True)
    same_browser = again.post(
        "/audits",
        files=_other_file(),
        data={"consent": "on", "locale": "pt"},
        follow_redirects=False,
    ).headers["location"]
    assert "acct=preview_device" in same_browser
    page = again.get(same_browser).text
    assert account_pages.COPY["pt"]["welcome_refused_device"] in page
    assert not find_claims(
        re.sub(r"<[^>]+>", " ", account_pages.COPY["pt"]["welcome_refused_device"])
    )
    # An unknown value shows nothing.
    assert (
        "welcome_refused" not in again.get(same_browser.replace("preview_device", "preview_x")).text
    )


def test_ipv6_counts_by_its_64_in_the_free_tier_and_invites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_trade.audit import accounts

    assert accounts.network_address("2001:db8:1:2::abcd") == "2001:db8:1:2::/64"
    assert accounts.network_address("2001:db8:1:2:ffff::1") == "2001:db8:1:2::/64"
    assert accounts.network_address("::ffff:203.0.113.9") == "203.0.113.9"
    assert accounts.network_address("203.0.113.9") == "203.0.113.9"
    assert accounts.network_address("not an ip") == "not an ip"
    assert accounts.network_key("2001:db8:1:2::1") == accounts.network_key("2001:db8:1:2::2")
    assert accounts.network_key("2001:db8:1:3::1") != accounts.network_key("2001:db8:1:2::1")

    # Rotating addresses inside one /64 does not pass the free reports' network cap.
    monkeypatch.setattr(accounts, "WELCOME_REPORTS_PER_IP_PER_MONTH", 1)
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client, welcome=True)
    first = client.post(
        "/audits",
        files=_seeded_file(71),
        data={"consent": "on"},
        headers={"X-Forwarded-For": "2001:db8:1:2::10"},
        follow_redirects=False,
    )
    assert "acct=welcome" in first.headers["location"]
    token = _invite_token(client)
    other = TestClient(client.app)
    _join(other, "bea@example.com", token)
    rotated = other.post(
        "/audits",
        files=_seeded_file(72),
        data={"consent": "on"},
        headers={"X-Forwarded-For": "2001:db8:1:2::99"},
        follow_redirects=False,
    )
    assert "acct=welcome" not in rotated.headers["location"]
    assert "acct=preview_network" in rotated.headers["location"]
    # ...and with the cap raised, the same /64 is the inviter's own network: no credit.
    monkeypatch.setattr(accounts, "WELCOME_REPORTS_PER_IP_PER_MONTH", 3)
    carl = TestClient(client.app)
    _join(carl, "carl@example.com", token)
    carl.post(
        "/audits",
        files=_seeded_file(73),
        data={"consent": "on"},
        headers={"X-Forwarded-For": "2001:db8:1:2:aaaa::5"},
    )
    ana = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    assert store.account_credits(ana.id, datetime.now(UTC)) == 0  # type: ignore[attr-defined]
    data = json.loads(client.get("/cuenta/datos").text)
    assert "self" in [item["outcome"] for item in data["invites"]["joined"]]


def test_sign_up_and_upload_limits_count_an_ipv6_64_as_one_network(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path, trusted_proxy_hops=1, max_uploads_per_hour_per_ip=2)
    # Rotating addresses inside one /64 share the hourly sign-up limit.
    for n in range(MAX_SIGNUPS_PER_HOUR + 1):
        client.cookies.clear()
        csrf = _csrf(client.get("/registro").text)
        response = client.post(
            "/registro",
            data={"email": f"r{n}@example.com", "password": PASSWORD, "csrf": csrf},
            headers={"X-Forwarded-For": f"2001:db8:5:6::{n + 1:x}"},
            follow_redirects=False,
        )
        expected = 303 if n < MAX_SIGNUPS_PER_HOUR else 429
        assert response.status_code == expected, n
    # Another /64 still signs up.
    client.cookies.clear()
    csrf = _csrf(client.get("/registro").text)
    assert (
        client.post(
            "/registro",
            data={"email": "other@example.com", "password": PASSWORD, "csrf": csrf},
            headers={"X-Forwarded-For": "2001:db8:5:7::1"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    # Rotating addresses inside one /64 share the hourly upload limit, and the
    # upload stores the network, not the exact address.
    statuses = [
        client.post(
            "/audits",
            files=_seeded_file(80 + n),
            data={"consent": "on"},
            headers={"X-Forwarded-For": f"2001:db8:9:9::{n + 1:x}"},
            follow_redirects=False,
        ).status_code
        for n in range(3)
    ]
    assert statuses == [303, 303, 429]
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        column = store.audits.c.client_ip  # type: ignore[attr-defined]
        stored = {row[0] for row in conn.execute(column.table.select().with_only_columns(column))}
    assert stored == {"2001:db8:9:9::/64"}


KEY_SHAPE = re.compile(r"<code>([A-HJ-NP-Z2-9]{5}(?:-[A-HJ-NP-Z2-9]{5}){3})</code>")
NEW_PASSWORD = "otra frase larga distinta"


def _make_recovery_key(client: TestClient, password: str = PASSWORD, prefix: str = "/cuenta"):
    csrf = _csrf(client.get(prefix).text)
    return client.post(
        f"{prefix}/recuperacion",
        data={"current": password, "csrf": csrf},
        follow_redirects=False,
    )


def _recover(client: TestClient, email: str, key: str, password: str = NEW_PASSWORD, ip: str = ""):
    headers = {"X-Forwarded-For": ip} if ip else {}
    csrf = _csrf(client.get("/olvide").text)
    return client.post(
        "/olvide",
        data={"email": email, "key": key, "password": password, "csrf": csrf},
        headers=headers,
        follow_redirects=False,
    )


def test_a_recovery_key_sets_a_new_password_once_without_email(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    page = client.get("/cuenta").text
    assert "Crea tu clave de recuperación" in page and "Aún no tienes clave" in page
    # The current password is required, and a wrong one makes no key.
    wrong = _make_recovery_key(client, password="no es la contraseña")
    assert wrong.status_code == 303 and "error=wrong" in wrong.headers["location"]
    ana = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    assert store.recovery_key_created(ana.id) is None  # type: ignore[attr-defined]
    shown = _make_recovery_key(client)
    assert shown.status_code == 200 and shown.headers["cache-control"] == "no-store"
    match = KEY_SHAPE.search(shown.text)
    assert match, "the key is shown once"
    key = match.group(1)
    assert not find_claims(re.sub(r"<[^>]+>", " ", shown.text))
    # Only its hash is stored; the account page shows the date, never the key.
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        rows = conn.execute(store.recovery_keys.select()).all()  # type: ignore[attr-defined]
    assert len(rows) == 1 and key not in str(tuple(rows[0]))
    page = client.get("/cuenta").text
    assert "Creada el" in page and key not in page and "Crea tu clave" not in page
    data = json.loads(client.get("/cuenta/datos").text)
    assert data["recovery_key_created_at"] and key not in json.dumps(data)

    other = TestClient(client.app)
    assert "Con tu clave de recuperación" in other.get("/olvide").text
    assert _recover(other, "ana@example.com", "AAAAA-BBBBB-CCCCC-DDDDD").status_code == 400
    assert _recover(other, "nadie@example.com", key).status_code == 400
    # A weak new password is refused before the key is spent.
    weak = _recover(other, "ana@example.com", key, password="corta")
    assert weak.status_code == 400 and "al menos" in weak.text
    # Typed in lower case without dashes, the key still works: once.
    done = _recover(other, "ana@example.com", key.lower().replace("-", " "))
    assert done.status_code == 303 and "done=recovered" in done.headers["location"]
    assert "Contraseña guardada y sesiones cerradas" in other.get(done.headers["location"]).text
    again = _recover(other, "ana@example.com", key, password="una tercera frase larga")
    assert again.status_code == 400 and "ya se usó" in again.text
    # Every session was signed out; the new password signs in, the old one no longer.
    assert client.get("/cuenta", follow_redirects=False).status_code == 303
    assert _signin(other, "ana@example.com").status_code == 401
    assert _signin(other, "ana@example.com", NEW_PASSWORD).status_code == 303
    assert store.recovery_key_created(ana.id) is None  # type: ignore[attr-defined]
    assert "Crea tu clave de recuperación" in other.get("/cuenta").text


def test_a_new_recovery_key_replaces_the_old_and_goes_with_the_account(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    _signup(client)
    first = KEY_SHAPE.search(_make_recovery_key(client).text).group(1)  # type: ignore[union-attr]
    second = KEY_SHAPE.search(_make_recovery_key(client).text).group(1)  # type: ignore[union-attr]
    assert first != second
    other = TestClient(client.app)
    assert _recover(other, "ana@example.com", first).status_code == 400
    assert _recover(other, "ana@example.com", second).status_code == 303
    _signin(client, "ana@example.com", NEW_PASSWORD)
    _make_recovery_key(client, password=NEW_PASSWORD)
    csrf = _csrf(client.get("/cuenta").text)
    client.post("/cuenta/borrar", data={"current": NEW_PASSWORD, "csrf": csrf})
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        assert conn.execute(store.recovery_keys.select()).all() == []  # type: ignore[attr-defined]


def test_recovery_tries_are_limited_per_network_and_per_email(tmp_path: Path) -> None:
    from quant_trade.audit import accounts

    client, _, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client)
    key = KEY_SHAPE.search(_make_recovery_key(client).text).group(1)  # type: ignore[union-attr]
    other = TestClient(client.app)
    limit = accounts.MAX_RECOVERY_TRIES_PER_HOUR
    # Rotating addresses in one /64, each guessing a different e-mail.
    for n in range(limit):
        answer = _recover(other, f"x{n}@example.com", key, ip=f"2001:db8:4:4::{n + 1:x}")
        assert answer.status_code == 400
    blocked = _recover(other, "ana@example.com", key, ip="2001:db8:4:4::ff")
    assert blocked.status_code == 429 and "Demasiados intentos" in blocked.text
    # One e-mail guessed from many networks stops too (the blocked try above
    # counted for it), and the key survives it.
    for n in range(limit - 1):
        wrong = _recover(other, "ana@example.com", "AAAAA-BBBBB-CCCCC-DDDDD", ip=f"198.51.100.{n}")
        assert wrong.status_code == 400
    assert _recover(other, "ana@example.com", key, ip="203.0.113.200").status_code == 429
    # A cross-site post is refused.
    csrf = _csrf(other.get("/olvide").text)
    cross = other.post(
        "/olvide",
        data={"email": "ana@example.com", "key": key, "password": NEW_PASSWORD, "csrf": csrf},
        headers={"Sec-Fetch-Site": "cross-site", "X-Forwarded-For": "192.0.2.9"},
        follow_redirects=False,
    )
    assert cross.status_code == 400


def test_the_recovery_key_screens_exist_in_every_language(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    for lang, forgot, words in (
        ("es", "/olvide", "Con tu clave de recuperación"),
        ("en", "/forgot", "With your recovery key"),
        ("pt", account_pages.path("forgot", "pt"), "Com sua chave de recuperação"),
    ):
        page = client.get(forgot).text
        assert words in page, lang
        assert not find_claims(re.sub(r"<[^>]+>", " ", page))
    _signup(client)
    for prefix, words in (
        ("/account", "Your recovery key"),
        (account_pages.path("account", "pt"), "Sua chave de recuperação"),
    ):
        shown = _make_recovery_key(client, prefix=prefix)
        assert words in shown.text and KEY_SHAPE.search(shown.text)
        assert not find_claims(re.sub(r"<[^>]+>", " ", shown.text))
    ctx = LegalContext(
        operator_name="Op",
        operator_contact="op@example.com",
        operator_address="México",
        jurisdiction="Leyes de México",
    )
    for locale, words in (("es", "clave de recuperación"), ("en", "recovery key")):
        privacy = " ".join(" ".join(p) for _, p in privacy_text(ctx, locale).sections)
        assert words in privacy and not find_claims(privacy)


def test_password_guesses_on_account_forms_count_a_64_and_the_account(tmp_path: Path) -> None:
    from quant_trade.audit import accounts

    client, store, _ = _client(tmp_path, trusted_proxy_hops=1)
    _signup(client)
    csrf = _csrf(client.get("/cuenta").text)

    def guess(ip: str) -> str:
        answer = client.post(
            "/cuenta/recuperacion",
            data={"current": "adivinando una frase", "csrf": csrf},
            headers={"X-Forwarded-For": ip},
            follow_redirects=False,
        )
        return answer.headers["location"]

    limit = accounts.MAX_ACCOUNT_ACTIONS_PER_HOUR
    # Rotating addresses inside one /64 share the limit...
    for n in range(limit):
        assert "error=wrong" in guess(f"2001:db8:7:7::{n + 1:x}")
    assert "error=too_many" in guess("2001:db8:7:7::ffff")
    # ...and so does the account from any other network.
    assert "error=too_many" in guess("203.0.113.77")
    ana = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    assert store.recovery_key_created(ana.id) is None  # type: ignore[attr-defined]
