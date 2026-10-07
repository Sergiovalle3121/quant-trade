"""The owner panel: codes created from a browser behind AUDIT_ADMIN_KEY."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.owner import MAX_FAILED_LOGINS_PER_HOUR, TEXT, _orders_table  # noqa: E402
from quant_trade.audit.settings import (  # noqa: E402
    DEFAULT_PANEL_PATH,
    AuditSettings,
    panel_path_valid,
    resolve_panel_path,
)
from quant_trade.audit.store import CheckoutOrder, hash_access_code, make_store  # noqa: E402
from quant_trade.audit.web import create_app, redact_secrets  # noqa: E402

KEY = "k" * 40
CODE = re.compile(r"AUD-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}")


def _client(
    tmp_path: Path, admin_key: str = KEY, panel_path: str = DEFAULT_PANEL_PATH
) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        admin_key=admin_key,
        panel_path=panel_path,
    )
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store)), store


@pytest.mark.parametrize("admin_key", ["", "short-key"])
def test_the_panel_is_off_without_a_long_key(tmp_path: Path, admin_key: str) -> None:
    client, _ = _client(tmp_path, admin_key)
    assert client.get("/panel").status_code == 404
    assert client.post("/panel", data={"key": admin_key or "x"}).status_code == 404


def test_the_key_is_never_in_the_repr() -> None:
    assert KEY not in repr(AuditSettings(admin_key=KEY))


def test_login_page_is_private(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    page = client.get("/panel")
    assert page.status_code == 200
    assert "type='password' name='key'" in page.text
    assert "noindex" in page.text
    assert page.headers["Cache-Control"] == "no-store"


def test_wrong_keys_are_refused_then_limited(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    for _ in range(MAX_FAILED_LOGINS_PER_HOUR):
        wrong = client.post("/panel", data={"key": "x" * 40, "action": "create"})
        assert wrong.status_code == 403
        assert TEXT["wrong_key"] in wrong.text
    blocked = client.post("/panel", data={"key": KEY})
    assert blocked.status_code == 429
    assert store.list_access_codes() == []  # type: ignore[attr-defined]


def test_create_shows_the_code_once_and_stores_only_its_hash(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    created = client.post(
        "/panel", data={"key": KEY, "action": "create", "credits": "3", "note": "Juan, OXXO"}
    )
    assert created.status_code == 200
    codes = CODE.findall(created.text)
    assert len(codes) == 1
    records = store.list_access_codes()  # type: ignore[attr-defined]
    assert [(r.credits_total, r.note) for r in records] == [(3, "Juan, OXXO")]
    listed = client.post("/panel", data={"key": KEY})
    assert CODE.findall(listed.text) == []
    assert "Juan, OXXO" in listed.text
    assert hash_access_code(codes[0]) not in listed.text


def test_invalid_input_creates_nothing(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    for data in ({"credits": "0"}, {"credits": "abc"}, {"expires_days": "0"}, {"note": "n" * 121}):
        page = client.post("/panel", data={"key": KEY, "action": "create", **data})
        assert TEXT["invalid"] in page.text
    assert store.list_access_codes() == []  # type: ignore[attr-defined]


def test_disable_stops_a_code(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    client.post("/panel", data={"key": KEY, "action": "create"})
    record = store.list_access_codes()[0]  # type: ignore[attr-defined]
    page = client.post("/panel", data={"key": KEY, "action": "disable", "code_id": record.id})
    assert TEXT["disabled"] in page.text
    assert store.list_access_codes()[0].disabled  # type: ignore[attr-defined]
    again = client.post("/panel", data={"key": KEY, "action": "disable", "code_id": record.id})
    assert TEXT["not_found"] in again.text


def test_panel_texts_pass_the_guard() -> None:
    for text in TEXT.values():
        assert find_claims(text) == [], text


def test_paid_review_charge_is_visible_with_held_delivery_and_refund_review() -> None:
    charged = CheckoutOrder(
        id="order-review",
        audit_id="audit-review",
        account_id="account-review",
        plan="single",
        amount_cents=2900,
        currency="usd",
        status="paid_review",
        session_id="cs_live_review",
        checkout_url="https://checkout.stripe.test/review",
        expires_at="2026-09-28T00:00:00Z",
        paid_amount_cents=2900,
        confirmed_at="2026-09-27T12:00:00Z",
        resolution="manual_refund_review",
        livemode=True,
    )
    html = _orders_table([replace(charged, status="open"), charged])
    assert html.count("cs_live_review") == 1
    assert "<td>29.00</td><td>cobrado; entrega retenida</td>" in html
    assert "<td>revisar reembolso manualmente</td>" in html
    assert "registrar la revisión no ejecuta el reembolso" in html


# -- AUDIT_PANEL_PATH: the panel at a path the owner chooses -----------------------
CUSTOM = "/oficina-x9_k/puerta"
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


def _answer(client: TestClient, method: str, path: str, **kwargs: object) -> tuple[object, ...]:
    response = client.request(method, path, **kwargs)  # type: ignore[arg-type]
    return response.status_code, response.content, sorted(response.headers.items())


def test_the_panel_path_comes_from_the_environment() -> None:
    assert AuditSettings.from_env({}).panel_path == DEFAULT_PANEL_PATH
    assert AuditSettings.from_env({"AUDIT_PANEL_PATH": "  "}).panel_path == DEFAULT_PANEL_PATH
    assert AuditSettings.from_env({"AUDIT_PANEL_PATH": f" {CUSTOM} "}).panel_path == CUSTOM
    assert CUSTOM not in repr(AuditSettings(panel_path=CUSTOM))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/",
        "panel",
        "oficina/x",
        "/oficina/",
        "//oficina",
        "/oficina//x",
        "/oficina x",
        "/oficina?x=1",
        "/oficina#x",
        "/oficina.x",
        "/oficiña",
        "/oficina\n",
        "/../oficina",
        "/" + "a" * 64,
        "https://example.test/oficina",
    ],
)
def test_an_invalid_panel_path_falls_back_to_the_default(value: str) -> None:
    assert not panel_path_valid(value)
    assert resolve_panel_path(value) == DEFAULT_PANEL_PATH


def test_valid_panel_paths_and_public_prefixes() -> None:
    for value in ("/x", "/" + "a" * 63, CUSTOM, "/Oficina_9-b"):
        assert panel_path_valid(value)
        assert resolve_panel_path(value, taken={"cuenta", "pt"}) == value
    for value in ("/cuenta", "/cuenta/oficina", "/PT/oficina", "/Cuenta"):
        assert resolve_panel_path(value, taken={"cuenta", "pt"}) == DEFAULT_PANEL_PATH


@pytest.mark.parametrize(
    "value",
    [
        "/cuenta/oficina",
        "/account",
        "/pt/oficina",
        "/audits/oficina",
        "/static/oficina",
        "/v/oficina",
        "/webhooks/oficina",
        "/health",
        "/historial/oficina",
        "/robots.txt",
        "/oficina/",
        "not-a-path",
    ],
)
def test_a_colliding_or_invalid_path_keeps_the_default_and_is_not_logged(
    tmp_path: Path, value: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="quant_trade.audit.web"):
        client, _ = _client(tmp_path, panel_path=value)
    warnings = [r.getMessage() for r in caplog.records if "AUDIT_PANEL_PATH" in r.getMessage()]
    assert len(warnings) == 1
    assert value not in warnings[0]
    assert client.get(DEFAULT_PANEL_PATH).status_code == 200
    assert client.post(DEFAULT_PANEL_PATH, data={"key": KEY}).status_code == 200


def test_the_default_path_logs_no_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="quant_trade.audit.web"):
        _client(tmp_path)
        _client(tmp_path / "custom", panel_path=CUSTOM)
    assert not [r for r in caplog.records if "AUDIT_PANEL_PATH" in r.getMessage()]


def test_a_custom_path_serves_the_panel_and_every_form_posts_to_it(tmp_path: Path) -> None:
    client, store = _client(tmp_path, panel_path=CUSTOM)
    login = client.get(CUSTOM)
    assert login.status_code == 200
    assert f"<form method='post' action='{CUSTOM}'>" in login.text
    created = client.post(CUSTOM, data={"key": KEY, "action": "create", "credits": "2"})
    assert created.status_code == 200
    assert len(CODE.findall(created.text)) == 1
    assert [r.credits_total for r in store.list_access_codes()] == [2]  # type: ignore[attr-defined]
    actions = set(re.findall(r"<form method='post' action='([^']*)'", created.text))
    assert actions == {CUSTOM}
    assert "'/panel'" not in created.text and '"/panel"' not in created.text
    wrong = client.post(CUSTOM, data={"key": "x" * 40})
    assert wrong.status_code == 403
    assert f"<form method='post' action='{CUSTOM}'>" in wrong.text
    for response in (login, created, wrong):
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
        assert response.headers["Cache-Control"] == "no-store"


def test_with_a_custom_path_the_old_one_is_an_unknown_page(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, panel_path=CUSTOM)
    for method in METHODS:
        for body in ({}, {"data": {"key": KEY}}):
            assert _answer(client, method, "/panel", **body) == _answer(
                client, method, "/pagina-que-no-existe", **body
            ), method
    assert client.get("/panel").status_code == 404
    assert client.get(CUSTOM + "/otra").status_code == 404


@pytest.mark.parametrize("admin_key", ["", "short-key", "k" * 31])
@pytest.mark.parametrize("panel_path", [DEFAULT_PANEL_PATH, CUSTOM])
def test_without_a_key_the_panel_path_is_an_unknown_page_for_every_method(
    tmp_path: Path, admin_key: str, panel_path: str
) -> None:
    client, _ = _client(tmp_path, admin_key, panel_path)
    for method in METHODS:
        for body in ({}, {"data": {"key": admin_key or "x"}}, {"data": {"action": "create"}}):
            for headers in ({}, {"accept": "application/json"}):
                assert _answer(client, method, panel_path, headers=headers, **body) == _answer(
                    client, method, "/pagina-que-no-existe", headers=headers, **body
                ), (method, body, headers)
    missing = client.get(panel_path)
    assert missing.status_code == 404
    assert "Esta página no existe" in missing.text
    assert "name='key'" not in missing.text


def test_wrong_keys_are_limited_on_a_custom_path(tmp_path: Path) -> None:
    client, store = _client(tmp_path, panel_path=CUSTOM)
    for _ in range(MAX_FAILED_LOGINS_PER_HOUR):
        wrong = client.post(CUSTOM, data={"key": "x" * 40, "action": "create"})
        assert wrong.status_code == 403
    blocked = client.post(CUSTOM, data={"key": KEY, "action": "create"})
    assert blocked.status_code == 429
    assert TEXT["too_many"] in blocked.text
    assert blocked.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert store.list_access_codes() == []  # type: ignore[attr-defined]


def test_an_overlong_key_is_refused_before_it_is_compared(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    too_long = client.post("/panel", data={"key": "k" * 257, "action": "create"})
    assert too_long.status_code == 400
    assert store.list_access_codes() == []  # type: ignore[attr-defined]
    assert client.post("/panel", data={"key": "x" * 256}).status_code == 403


def test_with_a_key_the_recorded_limits_are_the_only_tells(tmp_path: Path) -> None:
    # docs/AUDIT_SECURITY_REVIEW.md lists these as what still tells the path
    # from an unknown page once a key is set; a new one belongs in that list.
    client, store = _client(tmp_path, panel_path=CUSTOM)
    answers = [client.request(method, CUSTOM) for method in ("PUT", "PATCH", "DELETE", "OPTIONS")]
    assert {response.status_code for response in answers} == {405}
    no_field = client.post(CUSTOM, data={"action": "create"})
    assert no_field.status_code == 400
    slash = client.get(CUSTOM + "/", follow_redirects=False)
    assert slash.status_code == 307
    for response in (*answers, no_field, slash):
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
        assert response.headers["Cache-Control"] == "no-store"
        assert KEY not in response.text
    assert store.list_access_codes() == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("panel_path", [DEFAULT_PANEL_PATH, CUSTOM])
def test_only_the_panel_uses_the_first_segment_of_its_path(tmp_path: Path, panel_path: str) -> None:
    client, _ = _client(tmp_path, panel_path=panel_path)
    first = panel_path.split("/")[1].lower()
    paths = [str(getattr(route, "path", "")) for route in client.app.routes]  # type: ignore[attr-defined]
    shared = {path for path in paths if path.lower().split("/")[1:2] == [first]}
    assert shared == {panel_path, panel_path + "/public-card"}


@pytest.mark.parametrize("panel_path", [DEFAULT_PANEL_PATH, CUSTOM])
def test_robots_and_the_sitemap_never_name_the_panel(tmp_path: Path, panel_path: str) -> None:
    client, _ = _client(tmp_path, panel_path=panel_path)
    robots = client.get("/robots.txt").text
    sitemap = client.get("/sitemap.xml").text
    first = "/" + panel_path.split("/")[1]
    for text in (robots, sitemap):
        assert panel_path not in text
        assert first not in text
    home = client.get("/").text
    assert panel_path not in home


def test_the_access_log_hides_a_key_in_a_query_string() -> None:
    line = f'"GET /panel?key={KEY}&action=list HTTP/1.1" 404'
    assert KEY not in redact_secrets(line)
    assert redact_secrets(f"/panel?action=list&KEY={KEY}") == "/panel?action=list&KEY=[redacted]"
    assert KEY not in redact_secrets(f"/entrar?next=%2Fpanel%3Fkey%3D{KEY}")
    assert redact_secrets("/guias?monkey=1") == "/guias?monkey=1"
