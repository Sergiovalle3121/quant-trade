"""Customer accounts: sign up, sign in, "My reports", credits, reset and deletion."""

from __future__ import annotations

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
    MAX_FAILED_SIGNINS_PER_HOUR,
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


def _signup(client: TestClient, email: str = "ana@example.com", password: str = PASSWORD):
    csrf = _csrf(client.get("/registro").text)
    return client.post(
        "/registro",
        data={"email": email, "password": password, "csrf": csrf},
        follow_redirects=False,
    )


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
    for bad in ("https://evil.example/", "//evil.example/cuenta", "/panel", "/\\evil", ""):
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
    location = _upload(client).headers["location"]
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
    location = _upload(client).headers["location"]  # A uploads, never signs up
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
    location = _upload(client).headers["location"]  # A uploads, never signs up
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
    location = _upload(client).headers["location"]  # A uploads, never signs up
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


def test_the_landing_says_the_preview_needs_no_card_and_an_account_is_optional(
    tmp_path: Path,
) -> None:
    client, _, _ = _client(tmp_path)
    es = client.get("/").text
    assert "cuenta opcional" in es and "sin crear cuenta" not in es
    assert "Vista previa sin tarjeta" in es
    en = client.get("/en").text
    assert "account optional" in en and "no account needed" not in en
    assert "No card for the preview" in en
