"""The owner's sales funnel in /panel: visits, accounts and payments per tag."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.legal import LegalContext, privacy_text  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

KEY = "k" * 40
PASSWORD = "una frase larga y segura"
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")
PLAYBOOK = Path(__file__).resolve().parents[1] / "docs" / "AUDIT_LAUNCH_PLAYBOOK.md"


def _client(tmp_path: Path) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        admin_key=KEY,
    )
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store), headers=BROWSER), store


def _today() -> str:
    return funnel.day_of(datetime.now(UTC))


def _visits(client: TestClient) -> dict[tuple[str, str], int]:
    client.app.state.visits.flush()  # type: ignore[attr-defined]
    rows = client.app.state.store.funnel_events(_today())["visits"]  # type: ignore[attr-defined]
    return {(locale, ref): count for _, locale, ref, count in rows}


def _signup(client: TestClient, email: str) -> None:
    match = CSRF_FIELD.search(client.get("/registro").text)
    assert match
    response = client.post(
        "/registro",
        data={"email": email, "password": PASSWORD, "csrf": match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _upload(client: TestClient) -> str:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"].split("/audits/")[1].split("?")[0]


def test_only_listed_tags_count() -> None:
    assert funnel.clean_ref("f4") == "f4"
    assert funnel.clean_ref(" F4 ") == "f4"
    for bad in ("", None, "zzz", "f4'", "../x", "f" * 40, "<b>", "f4 x"):
        assert funnel.clean_ref(bad) == ""
    assert all(funnel.REF_PATTERN.fullmatch(tag) for tag in funnel.REF_TAGS)


def test_robots_and_link_previews_are_not_people() -> None:
    assert funnel.is_person(BROWSER["User-Agent"])
    for agent in ("", None, "WhatsApp/2.23", "Googlebot/2.1", "curl/8.0", "TelegramBot"):
        assert not funnel.is_person(agent)


def _browser(client: TestClient) -> TestClient:
    """A new browser (no cookies) on the same app."""
    return TestClient(client.app, headers=BROWSER)


def test_visits_are_bare_counters_per_day_language_and_tag(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    assert client.get("/").status_code == 200
    tagged = _browser(client)
    first = tagged.get("/para/retos-prop-firm?ref=f6")
    assert first.cookies.get(funnel.REF_COOKIE) == "f6"
    assert first.cookies.get(funnel.SEEN_COOKIE) == _today()
    # The first tag stays, and the same browser counts once a day.
    for _ in range(5):
        assert tagged.get("/pt?ref=f4").status_code == 200
    later = _browser(client)
    later.cookies.set(funnel.REF_COOKIE, "f6")
    assert later.get("/pt?ref=f4").status_code == 200
    assert _browser(client).get("/en").status_code == 200
    assert _browser(client).get("/?lang=en").status_code == 200
    assert _browser(client).get("/?lang=pt").status_code == 200
    # "/" shows Spanish whatever ``lang`` says, unless it asks for English.
    assert _visits(client) == {
        ("es", ""): 2,
        ("es", "f6"): 1,
        ("pt", "f6"): 1,
        ("en", ""): 2,
    }
    columns = {column.name for column in store.funnel_visits.columns}  # type: ignore[attr-defined]
    assert columns == {"day", "locale", "ref", "visits"}


def test_unknown_tags_robots_and_other_pages_do_not_count(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    unknown = client.get("/?ref=spam-tag")
    assert funnel.REF_COOKIE not in unknown.cookies
    _browser(client).get("/", headers={"User-Agent": "WhatsApp/2.23"})
    _browser(client).get("/", headers={"Sec-Purpose": "prefetch"})
    _browser(client).head("/")
    _browser(client).get("/guias")
    _browser(client).get("/metodologia")
    assert _visits(client) == {("es", ""): 1}


def test_a_slow_or_failing_database_never_touches_a_page(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    calls: list[int] = []

    def broken(**kwargs: object) -> None:
        calls.append(1)
        raise RuntimeError("database away")

    store.count_visit = broken  # type: ignore[attr-defined]
    for _ in range(3):
        assert _browser(client).get("/").status_code == 200
    assert calls == []  # nothing is written during a request
    client.app.state.visits.flush()  # type: ignore[attr-defined]
    assert calls == [1]  # one batched write, which failed and is kept
    del store.count_visit  # type: ignore[attr-defined]
    assert _visits(client) == {("es", ""): 3}


def test_accounts_reports_and_payments_follow_their_tag(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    client.get("/para/retos-prop-firm?ref=f6")
    _signup(client, "ana@example.com")
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    _upload(client)  # the free first full report
    preview_id = _upload(client)  # a free preview
    code, _ = store.create_access_code(  # type: ignore[attr-defined]
        credits=1, note="", at=datetime.now(UTC)
    )
    assert store.redeem_for_audit(preview_id, code, at=datetime.now(UTC))  # type: ignore[attr-defined]

    other = _browser(client)
    _signup(other, "bea@example.com")

    client.app.state.visits.flush()  # type: ignore[attr-defined]
    built = funnel.build(store.funnel_events(_today()))  # type: ignore[attr-defined]
    f6 = built.by_ref["f6"].counts
    assert f6 == {
        "visits": 1,
        "signups": 1,
        "welcome": 1,
        "previews": 1,
        "paid_code": 1,
        "paid_card": 0,
    }
    assert built.by_ref[funnel.DIRECT].counts["signups"] == 1
    assert built.by_day[(_today(), "es")].counts["signups"] == 2

    # The tag goes with the account.
    store.delete_account(account.id)  # type: ignore[attr-defined]
    left = store.funnel_events(_today())["signups"]  # type: ignore[attr-defined]
    assert all(ref != "f6" for _, _, ref, _ in left)


def test_the_panel_shows_the_funnel_behind_the_key(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.get("/?ref=f4")
    _signup(client, "ana@example.com")
    assert "Embudo de ventas" not in client.get("/panel").text
    page = client.post("/panel", data={"key": KEY}).text
    assert "Embudo de ventas: últimos 30 días" in page
    assert "<td>f4</td><td>F4 · Sharpe por pura suerte</td><td>1</td><td>1</td>" in page
    assert "?ref=f6" in page
    assert "ana@example.com" not in page
    assert find_claims(page) == []


def test_an_empty_funnel_says_so(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    page = client.post("/panel", data={"key": KEY}).text
    assert "Todavía no hay nada que contar" in page


def test_privacy_page_names_the_tag_cookie_in_both_languages() -> None:
    for locale in ("es", "en"):
        text = str(privacy_text(LegalContext(), locale=locale))
        assert funnel.REF_COOKIE in text
        assert "?ref=f4" in text


def test_every_template_that_is_posted_has_its_tag() -> None:
    """Posts, forum texts and first messages; the WhatsApp replies are answers."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    ids = set(re.findall(r"^#### ([PFDV]\d+) · ES", text, re.M)) - {"V2"}
    assert {"P1", "F1", "F4", "F7", "D1", "V1"} <= ids
    assert {i.lower() for i in ids} <= set(funnel.REF_TAGS)


def test_a_failing_tag_store_never_breaks_a_sign_up(tmp_path: Path) -> None:
    client, store = _client(tmp_path)

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database away")

    store.set_account_ref = broken  # type: ignore[attr-defined]
    client.get("/?ref=f4")
    _signup(client, "ana@example.com")
    assert client.get("/cuenta", follow_redirects=False).status_code == 200


def test_what_we_keep_names_the_tag_in_every_language(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    for path in ("/registro", "/signup", "/pt/cadastro"):
        assert "?ref=f4" in client.get(path).text, path


def test_my_data_download_carries_the_tag(tmp_path: Path) -> None:
    import json

    client, _ = _client(tmp_path)
    client.get("/para/retos-prop-firm?ref=f6")
    _signup(client, "ana@example.com")
    data = json.loads(client.get("/cuenta/datos").text)
    assert data["arrived_through_link_tag"] == "f6"

    other = TestClient(client.app, headers=BROWSER)
    _signup(other, "bea@example.com")
    assert json.loads(other.get("/cuenta/datos").text)["arrived_through_link_tag"] == ""


def test_the_background_writer_flushes_on_shutdown(tmp_path: Path) -> None:
    _, store = _client(tmp_path)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", admin_key=KEY)
    with TestClient(create_app(settings, store), headers=BROWSER) as client:
        assert client.get("/").status_code == 200
    rows = store.funnel_events(_today())["visits"]  # type: ignore[attr-defined]
    assert [(locale, ref, count) for _, locale, ref, count in rows] == [("es", "", 1)]
