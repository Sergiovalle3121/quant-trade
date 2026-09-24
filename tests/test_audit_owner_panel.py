"""The owner panel: codes created from a browser behind AUDIT_ADMIN_KEY."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.owner import MAX_FAILED_LOGINS_PER_HOUR, TEXT  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import hash_access_code, make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

KEY = "k" * 40
CODE = re.compile(r"AUD-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}")


def _client(tmp_path: Path, admin_key: str = KEY) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        admin_key=admin_key,
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
