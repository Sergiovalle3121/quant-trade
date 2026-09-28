"""The continuous track record's pages through the web app, offline.

Reports are uploaded through ``POST /audits`` as the account and marked
paid with the store; statements are the MT4 fixture and its cuts made with
``forensics.edit``. The switches are monkeypatched before ``create_app``.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from audit_fixtures import signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import track_seal_pages as pages  # noqa: E402
from quant_trade.audit import track_seal_service as service  # noqa: E402
from quant_trade.audit.forensics import edit, rows  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.importers import MT4_STATEMENT_HTML  # noqa: E402
from quant_trade.audit.pages import BADGE_NOTICE  # noqa: E402
from quant_trade.audit.seo import BRAND  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.track_seal_copy import COPY, LANGUAGES, PATHS  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = (FIXTURES / "mt4_statement.htm").read_bytes()
D1 = datetime(2024, 3, 4, 23, 59, 59)
KEY = "k" * 40
#: Text of the fixture and of the account that must never reach a public page.
PRIVATE_TEXT = (
    "12345678",
    "Demo Trader",
    "FixtureEA",
    "Synthetic Broker",
    "SyntheticBroker",
    "eurusd",
    "xauusd",
    "1000002",
    "1000003",
    "1000005",
    "tester@example.com",
    ".htm",
)
ES, EN, PT = (PATHS[lang]["records"] for lang in LANGUAGES)


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    public: bool = True,
    pt: bool = False,
    admin_key: str = KEY,
    sign_in: bool = True,
) -> TestClient:
    monkeypatch.setattr(pages, "TRACK_SEAL_ENABLED", enabled)
    monkeypatch.setattr(pages, "TRACK_SEAL_PUBLIC_ENABLED", public)
    monkeypatch.setattr(pages, "TRACK_SEAL_PUBLIC_PT_ENABLED", pt)
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=60, admin_key=admin_key
    )
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    return signed_in(client) if sign_in else client


def _paid_report(client: TestClient, data: bytes) -> str:
    """A platform report uploaded by the signed-in account and paid."""
    response = client.post(
        "/audits",
        files={"report": ("r.htm", data, "text/html")},
        data={"consent": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:300]
    audit_id = response.headers["location"].split("?")[0].rsplit("/", 1)[1]
    client.app.state.store.mark_paid(audit_id, stripe_session_id="cs_" + audit_id, at=_now())
    return audit_id


def _now() -> datetime:
    return datetime.now(UTC)


def _csrf(client: TestClient, path: str = ES) -> str:
    """The session's CSRF token from the records page (or, when it has no
    form yet, from the account page: the token is the session's)."""
    for candidate in (path, "/cuenta"):
        page = client.get(candidate)
        assert page.status_code == 200, (page.status_code, candidate)
        match = re.search(r"name='csrf' value='([^']+)'", page.text)
        if match:
            return match.group(1)
    raise AssertionError("no CSRF field")


def _open(client: TestClient, audit_id: str) -> str:
    response = client.post(
        f"{ES}/abrir", data={"audit_id": audit_id, "csrf": _csrf(client)}, follow_redirects=False
    )
    assert response.status_code == 303, response.text[:300]
    location = response.headers["location"]
    assert location.endswith("?done=opened"), location
    return location.split("/")[-1].split("?")[0]


def _act(client: TestClient, seal_id: str, action: str, **data: str) -> str:
    response = client.post(
        f"{ES}/{seal_id}/{action}", data={"csrf": _csrf(client), **data}, follow_redirects=False
    )
    assert response.status_code == 303, response.text[:300]
    return response.headers["location"]


def _public_path(client: TestClient, seal_id: str) -> str:
    detail = client.get(f"{ES}/{seal_id}").text
    match = re.search(r"href='(/historial/[^']+)'>P", detail)
    assert match, "no public link"
    return match.group(1)


def _without_1000003() -> bytes:
    table = rows.load(MT4, MT4_STATEMENT_HTML)
    trade = next(r for r in table.rows if r.kind == rows.KIND_MT4_TRADE and r.text(0) == "1000003")
    return edit.delete_row(MT4, trade.index)


def _clean(page: str) -> None:
    assert find_claims(page) == [], page[:200]


# ---------------------------------------------------------------------------
# Switches and sign-in
# ---------------------------------------------------------------------------


def test_everything_is_404_while_the_switch_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert pages.TRACK_SEAL_ENABLED is False
    client = _client(tmp_path, monkeypatch, enabled=False, public=True, pt=True)
    for lang in LANGUAGES:
        for kind in ("records", "example", "coherence"):
            assert client.get(PATHS[lang][kind]).status_code == 404, (lang, kind)
        assert client.get(f"{PATHS[lang]['public']}/abc").status_code == 404
        assert client.post(f"{PATHS[lang]['records']}/abrir", data={"csrf": "x"}).status_code == 404
    assert client.get(pages.PANEL_RECORDS_PATH).status_code == 404
    assert client.post(pages.PANEL_RECORDS_PATH, data={"key": KEY}).status_code == 404


def test_the_examples_alone_can_go_live_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invented examples may ship with the file-consistency page before
    the private use is switched on: nothing else is mounted with them."""
    assert pages.TRACK_SEAL_EXAMPLES_ENABLED is False
    monkeypatch.setattr(pages, "TRACK_SEAL_EXAMPLES_ENABLED", True)
    client = _client(tmp_path, monkeypatch, enabled=False, public=True, pt=True)
    for lang in LANGUAGES:
        for kind in ("example", "coherence"):
            page = client.get(PATHS[lang][kind])
            assert page.status_code == 200, (lang, kind)
            assert find_claims(page.text) == []
        assert client.get(PATHS[lang]["records"]).status_code == 404
        assert client.get(f"{PATHS[lang]['public']}/abcdefghij").status_code == 404
    assert client.get(pages.PANEL_RECORDS_PATH).status_code == 404


def test_public_routes_wait_for_their_own_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, public=False)
    assert client.get(ES).status_code == 200
    assert client.get("/historial/ejemplo").status_code == 200
    assert client.get("/historial/abcdefghij").status_code == 404
    assert client.get("/historial/abcdefghij/badge.svg").status_code == 404
    assert client.get("/historial/abcdefghij/chain.json").status_code == 404


def test_account_pages_need_a_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, sign_in=False)
    for path in (ES, EN, PT, f"{ES}/abcdefghij"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert "next=" in response.headers["location"]
    for action in ("abrir",):
        response = client.post(f"{ES}/{action}", data={"csrf": "x"}, follow_redirects=False)
        assert response.status_code == 303
    response = client.post(f"{ES}/abcdefghij/terminar", data={"csrf": "x"}, follow_redirects=False)
    assert response.status_code == 303


def test_a_wrong_csrf_token_is_refused_by_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id = _paid_report(client, MT4)
    response = client.post(
        f"{ES}/abrir", data={"audit_id": audit_id, "csrf": "wrong"}, follow_redirects=False
    )
    assert response.status_code == 303 and "error=csrf" in response.headers["location"]
    assert service.list_records(client.app.state.store, _account_id(client)) == []


def _account_id(client: TestClient) -> str:
    account = client.app.state.store.find_account("tester@example.com")
    assert account is not None
    return account.id


# ---------------------------------------------------------------------------
# The flow: open, upload, events, publish, public page, badge, chain, delete
# ---------------------------------------------------------------------------


def test_open_upload_publish_and_the_public_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    store = client.app.state.store
    first = _paid_report(client, edit.cut_statement(MT4, keep_to=D1))
    second = _paid_report(client, _without_1000003())
    third = _paid_report(client, MT4)

    listing = client.get(ES)
    assert listing.status_code == 200 and "noindex" in listing.text
    assert first in listing.text and second in listing.text and "abrir" in listing.text
    assert COPY["es"]["none"] in listing.text
    _clean(listing.text)

    seal_id = _open(client, first)
    detail = client.get(f"{ES}/{seal_id}?done=opened")
    assert detail.status_code == 200
    assert COPY["es"]["done_opened"] in detail.text
    assert COPY["es"]["event_opened"] in detail.text
    assert "aún sin clase: 0 de 30 observaciones" in detail.text
    assert "MEASURED" in detail.text and "DECLARED" in detail.text
    assert COPY["es"]["fresh_current"] in detail.text
    assert COPY["es"]["chain_ok"] in detail.text
    record = service.get_record(store, seal_id)
    assert record is not None and record.head_hash in detail.text
    # The opening report is linked: only the others can continue the record.
    assert f"value='{first}'" not in detail.text.split("cargar")[1]
    _clean(detail.text)

    # The second statement drops a recorded trade: a mismatch event with detail.
    location = _act(client, seal_id, "cargar", audit_id=second)
    assert location.endswith("?done=mismatch&n=1"), location
    detail = client.get(location).text
    assert "Esta carga no coincide con la anterior en 1 operaciones" in detail
    assert COPY["es"]["event_mismatch"] in detail
    assert "1 que faltan · operaciones cerradas" in detail
    for text in PRIVATE_TEXT[:9]:
        assert text not in detail, text
    events = service.record_events(store, seal_id)
    # Events of the same second sort by their random id: compare as a set.
    assert sorted(event.kind for event in events) == ["mismatch", "opened"]
    # The uploads table with position, date, cut-off, counts and hash.
    uploads = service.record_uploads(store, seal_id)
    assert len(uploads) == 2 and uploads[1].hash in detail
    assert COPY["es"]["uploads_title"] in detail

    # Refusals become sentences: the same report again, then the full file
    # whose cut-off does not advance past the second statement's.
    location = _act(client, seal_id, "cargar", audit_id=second)
    assert location.endswith("?error=already_linked")
    assert COPY["es"]["refusal_already_linked"] in client.get(location).text
    location = _act(client, seal_id, "cargar", audit_id=third)
    assert location.endswith("?error=cutoff_not_advanced"), location
    assert COPY["es"]["refusal_cutoff_not_advanced"] in client.get(location).text
    assert len(service.record_uploads(store, seal_id)) == 2

    # Publishing needs the holder's box.
    location = _act(client, seal_id, "publicar")
    assert location.endswith("?error=holder_not_confirmed")
    assert COPY["es"]["refusal_holder_not_confirmed"] in client.get(location).text
    assert service.get_record(store, seal_id).published is False  # type: ignore[union-attr]
    location = _act(client, seal_id, "publicar", holder="on")
    assert location.endswith("?done=published")
    detail = client.get(location).text
    assert COPY["es"]["done_published"] in detail
    assert COPY["es"]["badge_title"] in detail and "[img]" in detail and "![" in detail
    public_path = _public_path(client, seal_id)
    assert public_path.startswith("/historial/") and seal_id not in public_path

    # The public page: allow-list only (the head moved with the second upload).
    record = service.get_record(store, seal_id)
    assert record is not None and record.upload_count == 2
    page = client.get(public_path)
    assert page.status_code == 200 and "noindex" in page.text
    text = page.text
    for private in (*PRIVATE_TEXT, seal_id, first, second, third):
        assert private.lower() not in text.lower(), private
    assert "público desde el " in text and "días después de abrirse" in text
    assert COPY["es"]["account_records"].format(n=1) in text
    assert COPY["es"]["paid_note"] in text
    assert COPY["es"]["class_full_note"] in text
    assert COPY["es"]["in_progress"] in text
    assert COPY["es"]["other_record"] in text
    assert COPY["es"]["public_notice"][:60] in text
    assert record.head_hash in text
    assert COPY["es"]["event_mismatch"] in text and "que faltan" not in text
    assert "mailto:" not in text and "http://" not in text.split("</head>")[1].replace(
        "http://www.w3.org", ""
    )
    _clean(text)
    english = client.get(public_path.replace("/historial/", "/record/"))
    assert english.status_code == 200 and COPY["en"]["paid_note"] in english.text
    _clean(english.text)
    # Portuguese waits for its own switch.
    assert client.get(public_path.replace("/historial/", "/pt/historico/")).status_code == 404

    # The badge and the chain.
    badge = client.get(public_path + "/badge.svg")
    assert badge.headers["content-type"].startswith("image/svg+xml")
    assert BADGE_NOTICE["es"] in badge.text and "en curso" in badge.text
    assert f"{BRAND} · " in badge.text
    for private in PRIVATE_TEXT:
        assert private not in badge.text
    english_badge = client.get(public_path + "/badge.svg?lang=en").text
    assert BADGE_NOTICE["en"] in english_badge and "in progress" in english_badge
    chain = client.get(public_path + "/chain.json")
    assert chain.status_code == 200
    payload = chain.json()
    assert payload["chain_ok"] is True and payload["broken_position"] is None
    assert set(payload["recipe"]) == {
        "entry_hash",
        "canonical_json",
        "previous_hash",
        "head_hash",
        "at",
    }
    previous = ""
    for entry in payload["entries"]:
        body = {k: v for k, v in entry.items() if k != "hash"}
        assert body["previous_hash"] == previous
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        assert digest == entry["hash"]
        previous = digest
    assert previous == payload["head_hash"] == record.head_hash  # type: ignore[union-attr]
    for private in PRIVATE_TEXT:
        assert private not in chain.text

    # Unpublish: the page is gone, the account page keeps "public since".
    location = _act(client, seal_id, "despublicar")
    assert location.endswith("?done=unpublished")
    assert client.get(public_path).status_code == 404
    assert client.get(public_path + "/badge.svg").status_code == 404
    assert client.get(public_path + "/chain.json").status_code == 404
    detail = client.get(f"{ES}/{seal_id}").text
    assert COPY["es"]["event_unpublished"] in detail
    assert service.get_record(store, seal_id).published_since  # type: ignore[union-attr]

    # End: frozen, still publishable; then delete with the confirmation step.
    location = _act(client, seal_id, "terminar")
    assert location.endswith("?done=ended")
    detail = client.get(location).text
    assert COPY["es"]["done_ended"] in detail and "Terminado el " in detail
    assert "cargar" not in detail.split("Eventos")[0].split("ts-actions")[-1]
    location = _act(client, seal_id, "terminar")
    assert location.endswith("?error=record_not_open")
    confirm = client.post(
        f"{ES}/{seal_id}/borrar", data={"csrf": _csrf(client)}, follow_redirects=False
    )
    assert confirm.status_code == 200
    assert COPY["es"]["delete_confirm_title"] in confirm.text
    assert "name='confirm' value='yes'" in confirm.text
    assert service.get_record(store, seal_id) is not None
    _clean(confirm.text)
    location = _act(client, seal_id, "borrar", confirm="yes")
    assert location == f"{ES}?done=deleted"
    assert COPY["es"]["done_deleted"] in client.get(location).text
    assert client.get(f"{ES}/{seal_id}").status_code == 404
    # Once published, the public link is a tombstone with the date only.
    tomb = client.get(public_path)
    assert tomb.status_code == 200
    assert "retirado por quien lo abrió el " in tomb.text
    main = tomb.text.split("<main")[1]
    for word in ("badge MEASURED", COPY["es"]["uploads"], record.head_hash, "público desde"):
        assert word not in main
    assert client.get(public_path + "/badge.svg").status_code == 404
    assert client.get(public_path + "/chain.json").status_code == 404
    _clean(tomb.text)
    assert service.quota(store, _account_id(client)) == (1, 5)


def test_english_and_portuguese_account_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    first = _paid_report(client, edit.cut_statement(MT4, keep_to=D1))
    seal_id = _open(client, first)
    for lang, base in (("en", EN), ("pt", PT)):
        listing = client.get(base)
        assert listing.status_code == 200
        assert COPY[lang]["title"] in listing.text and seal_id in listing.text
        assert html.escape(COPY[lang]["holder_checkbox"]) in listing.text
        _clean(listing.text)
        detail = client.get(f"{base}/{seal_id}")
        assert detail.status_code == 200 and COPY[lang]["uploads_title"] in detail.text
        _clean(detail.text)
        response = client.post(
            f"{base}/{seal_id}/publicar",
            data={"csrf": _csrf(client, base), "holder": "on"},
            follow_redirects=False,
        )
        assert response.headers["location"] == f"{base}/{seal_id}?done=published"
        response = client.post(
            f"{base}/{seal_id}/despublicar",
            data={"csrf": _csrf(client, base)},
            follow_redirects=False,
        )
        assert response.headers["location"] == f"{base}/{seal_id}?done=unpublished"


def test_every_refusal_sentence_renders_in_every_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    for lang, base in (("es", ES), ("en", EN), ("pt", PT)):
        for code in service.REFUSAL_CODES:
            page = client.get(f"{base}?error={code}")
            assert page.status_code == 200
            expected = COPY[lang][f"refusal_{code}"].format(allowed=service.MAX_RECORDS_PER_ACCOUNT)
            assert expected in page.text.replace("&#x27;", "'"), (lang, code)
            _clean(page.text)
        page = client.get(f"{base}?error=nonsense&done=nonsense&n=abc")
        assert page.status_code == 200 and "nonsense" not in page.text


def test_a_foreign_or_unknown_report_cannot_open_a_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        f"{ES}/abrir",
        data={"audit_id": "no-such-report", "csrf": _csrf(client)},
        follow_redirects=False,
    )
    assert response.headers["location"] == f"{ES}?error=not_found"
    response = client.post(
        f"{ES}/abrir",
        data={"audit_id": "../etc/passwd", "csrf": _csrf(client)},
        follow_redirects=False,
    )
    assert response.headers["location"] == f"{ES}?error=not_found"
    unpaid = (
        client.post(
            "/audits",
            files={"report": ("r.htm", MT4, "text/html")},
            data={"consent": "on"},
            follow_redirects=False,
        )
        .headers["location"]
        .split("?")[0]
        .rsplit("/", 1)[1]
    )
    response = client.post(
        f"{ES}/abrir", data={"audit_id": unpaid, "csrf": _csrf(client)}, follow_redirects=False
    )
    assert response.headers["location"] == f"{ES}?error=unpaid"
    assert unpaid not in client.get(ES).text.split("abrir")[1].split("</select>")[0]
    assert client.get(f"{ES}/no-such-record").status_code == 404


def test_stale_records_say_since_when(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    store = client.app.state.store
    seal_id = _open(client, _paid_report(client, edit.cut_statement(MT4, keep_to=D1)))
    old = (_now() - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with store.engine.begin() as conn:
        conn.execute(
            store.track_seals.update()
            .where(store.track_seals.c.id == seal_id)
            .values(last_upload_at=old)
        )
    detail = client.get(f"{ES}/{seal_id}").text
    assert f"sin cargas desde {old[:10]}" in detail
    assert COPY["es"]["fresh_current"] not in detail


def test_a_broken_chain_is_attributed_to_the_service_and_hides_the_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    store = client.app.state.store
    seal_id = _open(client, _paid_report(client, edit.cut_statement(MT4, keep_to=D1)))
    _act(client, seal_id, "publicar", holder="on")
    public_path = _public_path(client, seal_id)
    assert COPY["es"]["chain_broken"] not in client.get(public_path).text
    with store.engine.begin() as conn:
        conn.execute(
            store.track_seal_uploads.update()
            .where(store.track_seal_uploads.c.seal_id == seal_id)
            .values(hash="0" * 64)
        )
    page = client.get(public_path).text
    assert COPY["es"]["chain_broken"] in page
    assert "aún sin clase" not in page and "class='acct-cls'" not in page
    assert COPY["es"]["chain_broken"] in client.get(f"{ES}/{seal_id}").text
    assert client.get(public_path + "/chain.json").json()["chain_ok"] is False
    panel = client.post(pages.PANEL_RECORDS_PATH, data={"key": KEY}).text
    assert pages.PANEL_TEXT["chain_broken"] in panel
    assert pages.PANEL_TEXT["broken_warning"] in panel


def test_one_set_of_operations_admits_one_public_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    cut = edit.cut_statement(MT4, keep_to=D1)
    one = _open(client, _paid_report(client, cut))
    two = _open(client, _paid_report(client, cut))
    assert _act(client, one, "publicar", holder="on").endswith("?done=published")
    location = _act(client, two, "publicar", holder="on")
    assert location.endswith("?error=already_public")
    assert COPY["es"]["refusal_already_public"] in client.get(location).text


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------


def test_the_examples_show_the_banner_in_three_languages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, public=False, sign_in=False)
    for lang in LANGUAGES:
        page = client.get(PATHS[lang]["example"])
        assert page.status_code == 200 and "noindex" in page.text
        copy = COPY[lang]
        text = html.unescape(page.text)
        assert copy["example_banner"] in text
        assert copy["event_mismatch"] in text
        assert copy["fresh_stale"].format(date="2026-06-20") in text
        assert copy["time_to_know"] in text and "acct-cls" in text
        assert copy["ttk_months"].format(months="7", pace="11.5") in text
        assert copy["unpublished_period"].format(start="2026-04-10", end="2026-04-25") in text
        assert copy["public_since"].format(date="2026-03-20", days=18) in text
        assert "/badge.svg" not in text and "/chain.json'" not in text
        _clean(page.text)

        page = client.get(PATHS[lang]["coherence"])
        assert page.status_code == 200 and "noindex" in page.text
        text = html.unescape(page.text)
        assert copy["example_banner"] in text
        for key in ("coh_original", "coh_copied", "coh_changed", "coh_careful", "coh_method"):
            assert copy[key] in text, key
        assert text.count(copy["coh_none"]) == 2
        assert copy["coh_found"].format(n=2) in text
        assert "DUPLICATE_TICKET" in text.split("<details>")[1]
        assert "DUPLICATE_TICKET" not in text.split("<details>")[0]
        assert "90000001" not in text and "Ejemplo Inventado" not in text
        _clean(page.text)


def test_the_example_route_wins_over_a_public_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, public=True, pt=True, sign_in=False)
    assert client.get("/historial/ejemplo").status_code == 200
    assert client.get("/record/sample").status_code == 200
    assert client.get("/pt/historico/exemplo").status_code == 200
    assert client.get("/historial/ejemplo/chain.json").status_code == 404


def test_the_coherence_variants_are_built_from_the_invented_statement() -> None:
    original, copied, changed, careful = pages.coherence_variants()
    assert original == pages.SYNTHETIC_STATEMENT
    assert len(copied) > len(original) > len(careful)
    assert changed != original and abs(len(changed) - len(original)) <= 1
    results = pages.coherence_results()
    assert results is pages.coherence_results()
    assert [r.count("INFO") + r.count("SIGNAL") for r in results] == [0, 2, 2, 0]
    assert results[1].check("DUPLICATE_TICKET").status == "INFO"
    assert results[2].check("TOTALS_VS_ROWS").status == "INFO"
    assert results[3].count("SIGNAL") == 0


# ---------------------------------------------------------------------------
# Owner panel
# ---------------------------------------------------------------------------


def test_the_panel_needs_the_key_and_hides_reversibly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    login = client.get(pages.PANEL_RECORDS_PATH)
    assert login.status_code == 200 and "type='password' name='key'" in login.text
    assert "noindex" in login.text and pages.PANEL_RECORDS_PATH in login.text
    wrong = client.post(pages.PANEL_RECORDS_PATH, data={"key": "x" * 40})
    assert wrong.status_code == 403
    seal_id = _open(client, _paid_report(client, edit.cut_statement(MT4, keep_to=D1)))
    _act(client, seal_id, "publicar", holder="on")
    public_path = _public_path(client, seal_id)
    public_id = public_path.rsplit("/", 1)[1]
    panel = client.post(pages.PANEL_RECORDS_PATH, data={"key": KEY})
    assert panel.status_code == 200 and public_id in panel.text
    assert pages.PANEL_TEXT["chain_ok"] in panel.text and "value='hide'" in panel.text
    assert "tester@example.com" not in panel.text
    _clean(panel.text)
    hidden = client.post(
        pages.PANEL_RECORDS_PATH, data={"key": KEY, "action": "hide", "seal_id": seal_id}
    )
    assert hidden.status_code == 200 and pages.PANEL_TEXT["hidden"] in hidden.text
    assert client.get(public_path).status_code == 404
    assert client.get(public_path + "/badge.svg").status_code == 404
    detail = client.get(f"{ES}/{seal_id}").text
    assert COPY["es"]["hidden_note"] in detail and COPY["es"]["event_hidden"] in detail
    shown = client.post(
        pages.PANEL_RECORDS_PATH, data={"key": KEY, "action": "unhide", "seal_id": seal_id}
    )
    assert pages.PANEL_TEXT["shown"] in shown.text
    assert client.get(public_path).status_code == 200
    missing = client.post(
        pages.PANEL_RECORDS_PATH, data={"key": KEY, "action": "hide", "seal_id": "nope"}
    )
    assert pages.PANEL_TEXT["not_found"] in missing.text
    events = [e.kind for e in service.record_events(client.app.state.store, seal_id)]
    assert sorted(events) == ["hidden", "opened", "published", "shown"]


def test_the_panel_is_off_without_a_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, admin_key="", sign_in=False)
    assert client.get(pages.PANEL_RECORDS_PATH).status_code == 404
    assert client.post(pages.PANEL_RECORDS_PATH, data={"key": "x"}).status_code == 404


# ---------------------------------------------------------------------------
# Site rules
# ---------------------------------------------------------------------------


def test_new_paths_are_out_of_the_sitemap_and_robots_allows_nothing_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, public=True, pt=True, sign_in=False)
    sitemap = client.get("/sitemap.xml").text
    for lang in LANGUAGES:
        for value in PATHS[lang].values():
            assert value + "<" not in sitemap and value + "/" not in sitemap, value
    assert pages.PANEL_RECORDS_PATH not in sitemap
    robots = client.get("/robots.txt").text
    assert "Disallow: /cuenta" in robots and "Disallow: /account" in robots


def test_pages_carry_the_brand_and_pass_the_guard_in_every_language() -> None:
    for lang in LANGUAGES:
        page = pages.example_page(lang)
        assert f"<span>{BRAND}</span></a>" in page and f"<title>{BRAND}" not in page[:0]
        _clean(page)
        _clean(pages.coherence_example_page(lang))
        badge = pages.record_badge_svg(
            overall="B", public_id="abc123", last_upload="2026-09-26", locale=lang
        )
        assert f"{BRAND} · " in badge and BADGE_NOTICE[lang] in badge and ">B<" in badge
        assert find_claims(badge) == []
    _clean(pages.panel_login_page())
    _clean(pages.panel_records_page(key="k", records=[]))
