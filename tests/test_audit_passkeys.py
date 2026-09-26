"""Passkeys: add one on "Mi cuenta", sign in with it, use it as the second step.

A software authenticator made here (P-256, "none" attestation) plays the
phone, so nothing leaves the machine and nothing needs a browser.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("webauthn")

import cbor2  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from test_audit_user_accounts import (  # noqa: E402
    PASSWORD,
    _client,
    _code,
    _csrf,
    _signin,
    _signup,
    _turn_on_two_step,
)

from quant_trade.audit import passkeys as pk  # noqa: E402
from quant_trade.audit.accounts import SESSION_COOKIE  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.theme import SCRIPT_SRC  # noqa: E402

ORIGIN = "http://testserver"
OPTIONS = re.compile(r"data-options='([^']+)'")
ACTION = re.compile(r"<form method='post' action='([^']+)' data-passkey=")
CARD = "id='llaves'"


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class Device:
    """A phone that keeps one passkey: it signs what the page asks for."""

    def __init__(self, rp_id: str = "testserver", *, counter: bool = True) -> None:
        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential = os.urandom(32)
        self.count = 0
        self.counter = counter
        self.user_handle = b""

    def _cose(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}
        ).encode()

    def create(self, options: dict, *, origin: str = ORIGIN, verified: bool = True) -> str:
        self.user_handle = pk.decode(options["user"]["id"])
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        flags = 0x01 | 0x40 | (0x04 if verified else 0)
        auth = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + self.count.to_bytes(4, "big")
            + bytes(16)
            + len(self.credential).to_bytes(2, "big")
            + self.credential
            + self._cose()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return json.dumps(
            {
                "id": _b64(self.credential),
                "rawId": _b64(self.credential),
                "type": "public-key",
                "response": {
                    "clientDataJSON": _b64(client_data),
                    "attestationObject": _b64(attestation),
                    "transports": ["internal", "hybrid"],
                },
                "clientExtensionResults": {},
                "authenticatorAttachment": "platform",
            }
        )

    def get(
        self,
        options: dict,
        *,
        origin: str = ORIGIN,
        verified: bool = True,
        count: int | None = None,
    ) -> str:
        if count is not None:
            self.count = count
        elif self.counter:
            self.count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        flags = 0x01 | (0x04 if verified else 0)
        auth = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + self.count.to_bytes(4, "big")
        )
        signature = self.key.sign(
            auth + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return json.dumps(
            {
                "id": _b64(self.credential),
                "rawId": _b64(self.credential),
                "type": "public-key",
                "response": {
                    "clientDataJSON": _b64(client_data),
                    "authenticatorData": _b64(auth),
                    "signature": _b64(signature),
                    "userHandle": _b64(self.user_handle),
                },
                "clientExtensionResults": {},
            }
        )


def _passkey_client(tmp_path: Path, **extra: object) -> TestClient:
    client, _, _ = _client(tmp_path, base_url=ORIGIN, **extra)
    return client


def _options(page: str) -> tuple[dict, str]:
    match = OPTIONS.search(page)
    action = ACTION.search(page)
    assert match and action, "the passkey page carries its options and where to post"
    return json.loads(html.unescape(match.group(1))), html.unescape(action.group(1))


def _add_passkey(
    client: TestClient, device: Device, *, prefix: str = "/cuenta", label: str = "iPhone"
) -> str:
    """Add ``device``'s passkey from "Mi cuenta"; the redirect's location."""
    csrf = _csrf(client.get(prefix).text)
    page = client.post(
        f"{prefix}/llaves",
        data={"current": PASSWORD, "label": label, "csrf": csrf},
        follow_redirects=False,
    )
    assert page.status_code == 200, page.headers.get("location")
    options, action = _options(page.text)
    done = client.post(
        action,
        data={"credential": device.create(options), "csrf": _csrf(page.text)},
        follow_redirects=False,
    )
    return str(done.headers["location"])


def _passkey_signin(
    client: TestClient,
    device: Device,
    *,
    start: str = "/entrar/llave",
    from_page: str = "/entrar",
    **answer: object,
):
    csrf = _csrf(client.get(from_page).text)
    page = client.post(start, data={"csrf": csrf}, follow_redirects=False)
    assert page.status_code == 200, page.headers.get("location")
    options, action = _options(page.text)
    return client.post(
        action,
        data={"credential": device.get(options, **answer), "csrf": _csrf(page.text)},  # type: ignore[arg-type]
        follow_redirects=False,
    )


def _signed_out(client: TestClient) -> None:
    client.cookies.delete(SESSION_COOKIE)


def test_add_a_passkey_then_sign_in_with_it_and_no_password(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    device = Device()
    assert "done=passkey_added" in _add_passkey(client, device)
    page = client.get("/cuenta").text
    card = page.split(CARD)[1].split("</div>")[0]
    assert "iPhone" in card and "sin usar aún" in card
    assert "Llave de acceso añadida" in page.split("id='actividad'")[1]
    assert find_claims(page) == []

    _signed_out(client)
    assert "Entrar con una llave de acceso" in client.get("/entrar").text
    done = _passkey_signin(client, device)
    assert done.status_code == 303 and done.headers["location"].startswith("/cuenta")
    assert client.cookies.get(SESSION_COOKIE)
    after = client.get("/cuenta").text
    assert "Entrada con llave de acceso" in after.split("id='actividad'")[1]
    assert "último uso el" in after.split(CARD)[1]


def test_the_device_is_asked_to_check_its_owner(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    csrf = _csrf(client.get("/cuenta").text)
    page = client.post(
        "/cuenta/llaves", data={"current": PASSWORD, "csrf": csrf}, follow_redirects=False
    )
    options, _ = _options(page.text)
    assert options["rp"]["id"] == "testserver"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    # The account id, never the e-mail, is the handle the device keeps.
    account = client.app.state.store.find_account("ana@example.com")
    assert pk.decode(options["user"]["id"]) == account.id.encode()
    assert page.headers["Cache-Control"] == "no-store"
    # Without the device's own check (no fingerprint, face or PIN) nothing is added.
    done = client.post(
        "/cuenta/llaves/guardar",
        data={"credential": Device().create(options, verified=False), "csrf": csrf},
        follow_redirects=False,
    )
    assert "error=passkey_failed" in done.headers["location"]
    assert client.app.state.store.list_passkeys(account.id) == []


def test_adding_a_passkey_needs_the_password(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    csrf = _csrf(client.get("/cuenta").text)
    wrong = client.post(
        "/cuenta/llaves",
        data={"current": "no es la contraseña", "csrf": csrf},
        follow_redirects=False,
    )
    assert "error=wrong" in wrong.headers["location"]
    bad_csrf = client.post(
        "/cuenta/llaves", data={"current": PASSWORD, "csrf": "x" * 30}, follow_redirects=False
    )
    assert "error=csrf" in bad_csrf.headers["location"]
    # Signed out, the form sends you to sign in.
    _signed_out(client)
    out = client.post(
        "/cuenta/llaves", data={"current": PASSWORD, "csrf": csrf}, follow_redirects=False
    )
    assert out.headers["location"].startswith("/entrar")


def test_a_stolen_answer_a_wrong_site_or_a_cloned_key_never_signs_in(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    device = Device()
    _add_passkey(client, device)
    _signed_out(client)

    # The same answer twice: the page's challenge is used up.
    csrf = _csrf(client.get("/entrar").text)
    page = client.post("/entrar/llave", data={"csrf": csrf}, follow_redirects=False)
    options, action = _options(page.text)
    answer = device.get(options)
    first = client.post(
        action, data={"credential": answer, "csrf": _csrf(page.text)}, follow_redirects=False
    )
    assert first.status_code == 303
    _signed_out(client)
    replay = client.post(
        action, data={"credential": answer, "csrf": _csrf(page.text)}, follow_redirects=False
    )
    assert replay.status_code == 400 and not client.cookies.get(SESSION_COOKIE)

    # Signed on another site's page (a phishing copy): refused.
    phished = _passkey_signin(client, device, origin="https://rigor-login.example")
    assert phished.status_code == 400 and "No pudimos comprobar la llave" in phished.text
    # A counter that goes backwards means a copied key: refused.
    cloned = _passkey_signin(client, device, count=1)
    assert cloned.status_code == 400
    # Without the owner's check on the device: refused.
    unverified = _passkey_signin(client, device, verified=False)
    assert unverified.status_code == 400
    # A passkey this site never stored: refused.
    stranger = _passkey_signin(client, Device())
    assert stranger.status_code == 400
    assert not client.cookies.get(SESSION_COOKIE)
    # Garbage in the field is only a failed try.
    csrf = _csrf(client.get("/entrar").text)
    page = client.post("/entrar/llave", data={"csrf": csrf}, follow_redirects=False)
    _, action = _options(page.text)
    for junk in ("", "{", "[]", json.dumps({"id": "!!"})):
        junk_try = client.post(
            action, data={"credential": junk, "csrf": _csrf(page.text)}, follow_redirects=False
        )
        assert junk_try.status_code == 400
    # A synced passkey (its counter stays at zero) keeps working.
    synced_client = _passkey_client(tmp_path / "synced")
    _signup(synced_client, "bea@example.com")
    synced = Device(counter=False)
    _add_passkey(synced_client, synced)
    _signed_out(synced_client)
    for _ in range(2):
        assert _passkey_signin(synced_client, synced).status_code == 303
        _signed_out(synced_client)


def test_a_passkey_replaces_the_code_on_a_two_step_account(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    secret = _turn_on_two_step(client)
    device = Device()
    assert "done=passkey_added" in _add_passkey(client, device)

    # From the sign-in page the passkey is enough: device plus fingerprint.
    _signed_out(client)
    assert _passkey_signin(client, device).status_code == 303
    assert client.cookies.get(SESSION_COOKIE)

    # After the password, the code page offers the passkey instead of the code.
    _signed_out(client)
    assert _signin(client, "ana@example.com").headers["location"].startswith("/entrar/codigo")
    code_page = client.get("/entrar/codigo").text
    assert "Usar una llave de acceso" in code_page
    done = _passkey_signin(client, device, start="/entrar/codigo/llave", from_page="/entrar/codigo")
    assert done.status_code == 303 and client.cookies.get(SESSION_COOKIE)
    assert "Entrada con llave de acceso" in client.get("/cuenta").text
    # The code keeps working too.
    _signed_out(client)
    _signin(client, "ana@example.com")
    csrf = _csrf(client.get("/entrar/codigo").text)
    by_code = client.post(
        "/entrar/codigo",
        data={"code": _code(secret, 1), "csrf": csrf},
        follow_redirects=False,
    )
    assert by_code.status_code == 303


def test_another_accounts_passkey_never_finishes_the_second_step(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    _turn_on_two_step(client)
    _add_passkey(client, Device())
    other = TestClient(client.app)
    _signup(other, "bea@example.com")
    bea_device = Device()
    _add_passkey(other, bea_device)

    _signed_out(client)
    _signin(client, "ana@example.com")
    csrf = _csrf(client.get("/entrar/codigo").text)
    page = client.post("/entrar/codigo/llave", data={"csrf": csrf}, follow_redirects=False)
    options, action = _options(page.text)
    # Only Ana's passkey is offered, and Bea's is refused.
    assert len(options["allowCredentials"]) == 1
    wrong = client.post(
        action,
        data={"credential": bea_device.get(options), "csrf": _csrf(page.text)},
        follow_redirects=False,
    )
    assert wrong.status_code == 400 and not client.cookies.get(SESSION_COOKIE)
    # The second-step page needs a correct password first.
    fresh = TestClient(client.app)
    csrf = _csrf(fresh.get("/entrar").text)
    alone = fresh.post("/entrar/codigo/llave", data={"csrf": csrf}, follow_redirects=False)
    assert "two_step_expired" in alone.headers["location"]


def test_removing_a_passkey_stops_it(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    device = Device()
    _add_passkey(client, device)
    store = client.app.state.store
    account = store.find_account("ana@example.com")
    [item] = store.list_passkeys(account.id)
    csrf = _csrf(client.get("/cuenta").text)
    # The session alone is not enough: the password is asked, as when adding.
    no_password = client.post(
        "/cuenta/llaves/quitar",
        data={"credential": item.credential_id, "csrf": csrf},
        follow_redirects=False,
    )
    assert "error=wrong" in no_password.headers["location"]
    assert len(store.list_passkeys(account.id)) == 1
    done = client.post(
        "/cuenta/llaves/quitar",
        data={"credential": item.credential_id, "current": PASSWORD, "csrf": csrf},
        follow_redirects=False,
    )
    assert "done=passkey_removed" in done.headers["location"]
    page = client.get("/cuenta").text
    assert "Aún no tienes llaves de acceso." in page
    assert "Llave de acceso quitada" in page.split("id='actividad'")[1]
    _signed_out(client)
    assert _passkey_signin(client, device).status_code == 400
    # Someone else's form cannot remove Ana's passkey.
    _signin(client, "ana@example.com")
    _add_passkey(client, device)
    [item] = store.list_passkeys(account.id)
    other = TestClient(client.app)
    _signup(other, "bea@example.com")
    csrf = _csrf(other.get("/cuenta").text)
    other.post(
        "/cuenta/llaves/quitar",
        data={"credential": item.credential_id, "current": PASSWORD, "csrf": csrf},
        follow_redirects=False,
    )
    assert len(store.list_passkeys(account.id)) == 1


def test_passkeys_are_in_the_export_and_go_with_the_account(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    _add_passkey(client, Device(), label="Portátil <b>")
    store = client.app.state.store
    account = store.find_account("ana@example.com")
    data = client.get("/cuenta/datos").json()
    [row] = data["passkeys"]
    assert row["name"] == "Portátil <b>" and row["site"] == "testserver"
    assert set(row) == {"name", "site", "created_at", "last_used_at"}
    assert "<b>" not in client.get("/cuenta").text.split(CARD)[1].split("</ul>")[0]
    csrf = _csrf(client.get("/cuenta").text)
    client.post("/cuenta/borrar", data={"current": PASSWORD, "csrf": csrf})
    assert store.list_passkeys(account.id) == []


def test_passkeys_exist_in_every_language(tmp_path: Path) -> None:
    for locale, account_path, signin, start, texts in (
        ("en", "/account", "/login", "/login/passkey", ("Passkeys", "Sign in with a passkey")),
        (
            "pt",
            "/pt/conta",
            "/pt/entrar",
            "/pt/entrar/chave",
            ("Chaves de acesso", "Entrar com uma chave de acesso"),
        ),
    ):
        client = _passkey_client(tmp_path / locale)
        _signup(client, f"{locale}@example.com")
        page = client.get(account_path).text
        assert CARD in page and texts[0] in page
        device = Device()
        location = _add_passkey(client, device, prefix=account_path)
        assert "done=passkey_added" in location and location.startswith(account_path)
        _signed_out(client)
        assert texts[1] in client.get(signin).text
        done = _passkey_signin(client, device, start=start, from_page=signin)
        assert done.status_code == 303
        assert find_claims(client.get(account_path).text) == []


def test_no_passkey_buttons_where_the_browser_would_refuse_them(tmp_path: Path) -> None:
    # AUDIT_BASE_URL names another host: a passkey made here would not work there.
    client, _, _ = _client(tmp_path, base_url="http://rigor.example")
    _signup(client)
    assert CARD not in client.get("/cuenta").text
    csrf = _csrf(client.get("/cuenta").text)
    refused = client.post(
        "/cuenta/llaves", data={"current": PASSWORD, "csrf": csrf}, follow_redirects=False
    )
    assert "error=passkey_unavailable" in refused.headers["location"]
    _signed_out(client)
    assert "llave de acceso" not in client.get("/entrar").text.lower()


def test_a_passkey_from_an_old_domain_is_listed_and_the_card_says_what_still_works(
    tmp_path: Path,
) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    store = client.app.state.store
    account = store.find_account("ana@example.com")
    store.add_passkey(
        account.id,
        credential_id=_b64(b"old-credential"),
        public_key=_b64(b"k"),
        sign_count=0,
        label="Teléfono",
        rp_id="rigor.up.railway.app",
        transports="",
        at=datetime.now(UTC),
        limit=pk.MAX_PER_ACCOUNT,
    )
    card = client.get("/cuenta").text.split(CARD)[1]
    assert "Solo funciona en rigor.up.railway.app" in card
    assert "la clave de recuperación siguen funcionando" in card
    # The second step offers only passkeys made for this address.
    assert store.passkey_ids(account.id, "testserver") == []


def test_an_account_holds_at_most_ten_passkeys(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    _signup(client)
    for n in range(pk.MAX_PER_ACCOUNT):
        assert "done=passkey_added" in _add_passkey(client, Device(), label=f"llave {n}")
    page = client.get("/cuenta").text
    assert "Añadir una llave de acceso" not in page.split(CARD)[1]
    csrf = _csrf(page)
    full = client.post(
        "/cuenta/llaves", data={"current": PASSWORD, "csrf": csrf}, follow_redirects=False
    )
    assert "error=passkey_full" in full.headers["location"]
    # The same device twice is refused as well.
    fresh = _passkey_client(tmp_path / "twice")
    _signup(fresh)
    device = Device()
    _add_passkey(fresh, device)
    assert "error=passkey_full" in _add_passkey(fresh, device)


def test_passkey_pages_are_limited_per_network(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    csrf = _csrf(client.get("/entrar").text)
    codes = [
        client.post("/entrar/llave", data={"csrf": csrf}, follow_redirects=False).status_code
        for _ in range(pk.MAX_STARTS_PER_HOUR + 2)
    ]
    assert codes[: pk.MAX_STARTS_PER_HOUR] == [200] * pk.MAX_STARTS_PER_HOUR
    assert codes[-1] == 303


def test_the_script_address_changes_with_its_content(tmp_path: Path) -> None:
    client = _passkey_client(tmp_path)
    assert re.fullmatch(r"/static/app\.js\?v=[0-9a-f]{12}", SCRIPT_SRC)
    assert SCRIPT_SRC in client.get("/entrar").text
    script = client.get(SCRIPT_SRC)
    assert script.status_code == 200 and "data-passkey" in script.text
    assert "navigator.credentials.get" in script.text
