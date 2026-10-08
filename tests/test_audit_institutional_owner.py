"""Institutional requests remain behind the owner key; contact status persists."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims, scan_client_text  # noqa: E402
from quant_trade.audit.owner import (  # noqa: E402
    INSTITUTIONAL_FREQUENCIES,
    INSTITUTIONAL_TYPES,
    TEXT,
    panel_page,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import Store, make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

KEY = "owner-institutional-" + "k" * 32
AT = datetime(2026, 10, 7, 10, tzinfo=UTC)
PRIVATE_DESCRIPTION = "PRIVATE-INSTITUTIONAL-NOTE: rentable"


def _seed(store: Store) -> str:
    return store.add_institutional_request(
        name="Persona Ejemplo",
        organization="Gestora Ejemplo",
        email="contacto@example.test",
        strategy_type="model_portfolio",
        frequency="monthly",
        history_years="3.5",
        has_benchmark=True,
        variants=12,
        description=PRIVATE_DESCRIPTION,
        claim_findings=scan_client_text(PRIVATE_DESCRIPTION),
        locale="es",
        ref="f6",
        at=AT,
    )


def _client(
    tmp_path: Path, *, admin_key: str = KEY, panel_path: str = "/panel"
) -> tuple[TestClient, Store, str]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        admin_key=admin_key,
        panel_path=panel_path,
    )
    store = make_store(settings.database_url)
    request_id = _seed(store)
    return TestClient(create_app(settings, store)), store, request_id


def test_requests_are_absent_without_a_posted_owner_key(tmp_path: Path) -> None:
    client, store, request_id = _client(tmp_path)
    responses = (
        client.get("/panel"),
        client.get("/panel", params={"key": KEY}),
        client.post("/panel", data={"key": "wrong-owner-key"}),
        client.post(
            "/panel",
            params={"key": KEY},
            data={"action": "institutional_contacted", "request_id": request_id},
        ),
        client.post(
            "/panel",
            data={"key": "wrong", "action": "institutional_contacted", "request_id": request_id},
        ),
    )
    assert [response.status_code for response in responses] == [200, 200, 403, 400, 403]
    for response in responses:
        assert "id='institutional-requests'" not in response.text
        assert "Gestora Ejemplo" not in response.text
        assert "contacto@example.test" not in response.text
        assert PRIVATE_DESCRIPTION not in response.text
        assert response.headers["Cache-Control"] == "no-store"
    assert store.list_institutional_requests()[0].contacted_at == ""


@pytest.mark.parametrize("admin_key", ["", "short-key"])
def test_requests_cannot_be_read_or_changed_when_panel_is_disabled(
    tmp_path: Path, admin_key: str
) -> None:
    client, store, request_id = _client(tmp_path, admin_key=admin_key)
    for response in (
        client.get("/panel"),
        client.post(
            "/panel",
            data={"key": KEY, "action": "institutional_contacted", "request_id": request_id},
        ),
    ):
        assert response.status_code == 404
        assert "Gestora Ejemplo" not in response.text
        assert "id='institutional-requests'" not in response.text
    assert store.list_institutional_requests()[0].contacted_at == ""


def test_owner_sees_declared_inputs_and_contact_without_free_text(tmp_path: Path) -> None:
    client, _, request_id = _client(tmp_path)
    response = client.post("/panel", data={"key": KEY})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    for cell in (
        "2026-10-07",
        "Gestora Ejemplo",
        "Cartera modelo",
        "Mensual",
        "3.5",
        "Sí",
        "12",
    ):
        assert f"<td>{cell}</td>" in response.text
    assert "Persona Ejemplo<br>contacto@example.test" in response.text
    assert "Años (Declarado)" in response.text
    assert "Variantes (Declarado)" in response.text
    assert f"name='request_id' value='{request_id}'" in response.text
    assert "name='action' value='institutional_contacted'" in response.text
    assert PRIVATE_DESCRIPTION not in response.text
    assert "audit_client_text" not in response.text
    assert find_claims(response.text) == []


@pytest.mark.parametrize("panel_path", ["/panel", "/oficina-institucional/entrada"])
def test_marking_contacted_persists_and_uses_the_configured_panel_path(
    tmp_path: Path, panel_path: str
) -> None:
    client, store, request_id = _client(tmp_path, panel_path=panel_path)
    initial = client.post(panel_path, data={"key": KEY})
    assert f"<form method='post' action='{panel_path}'>" in initial.text
    assert "name='action' value='institutional_contacted'" in initial.text
    payload = {"key": KEY, "action": "institutional_contacted", "request_id": request_id}
    response = client.post(panel_path, data=payload)
    assert response.status_code == 200
    assert TEXT["institutional_contacted"] in response.text
    assert "name='action' value='institutional_contacted'" not in response.text
    recorded_at = store.list_institutional_requests()[0].contacted_at
    assert recorded_at
    assert "Contactado · " + recorded_at[:10] in response.text
    reopened = make_store(f"sqlite:///{tmp_path}/audit.db")
    assert reopened.list_institutional_requests()[0].contacted_at == recorded_at
    assert client.post(panel_path, data=payload).status_code == 200
    assert store.list_institutional_requests()[0].contacted_at == recorded_at
    if panel_path != "/panel":
        assert "action='/panel'" not in response.text
        assert client.get("/panel").status_code == 404


def test_unknown_request_does_not_change_another_request(tmp_path: Path) -> None:
    client, store, _ = _client(tmp_path)
    response = client.post(
        "/panel", data={"key": KEY, "action": "institutional_contacted", "request_id": "missing"}
    )
    assert response.status_code == 200
    assert TEXT["institutional_not_found"] in response.text
    assert store.list_institutional_requests()[0].contacted_at == ""


@pytest.mark.parametrize(
    "headers", [{"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://elsewhere.test"}]
)
def test_cross_site_contact_changes_are_refused(tmp_path: Path, headers: dict[str, str]) -> None:
    client, store, request_id = _client(tmp_path)
    response = client.post(
        "/panel",
        headers=headers,
        data={"key": KEY, "action": "institutional_contacted", "request_id": request_id},
    )
    assert response.status_code == 403
    assert store.list_institutional_requests()[0].contacted_at == ""
    assert "Gestora Ejemplo" not in response.text


def test_owner_request_ui_escapes_input_and_neutralizes_claims(tmp_path: Path) -> None:
    _, store, _ = _client(tmp_path)
    request = replace(
        store.list_institutional_requests()[0],
        name="<script>alert('name')</script>",
        organization="Una cartera rentable",
        email="certified@example.test",
    )
    page = panel_page(key=KEY, codes=(), institutional_requests=[request])
    assert "<script>alert('name')</script>" not in page
    assert "&lt;script&gt;alert(&#x27;name&#x27;)&lt;/script&gt;" in page
    assert "Una cartera rentable" not in page
    assert "certified@example.test" not in page
    assert page.count(TEXT["institutional_hidden"]) == 2
    assert PRIVATE_DESCRIPTION not in page
    assert find_claims(page) == []


def test_owner_request_copy_passes_the_claim_guard() -> None:
    texts = [value for name, value in TEXT.items() if name.startswith("institutional_")]
    texts += list(INSTITUTIONAL_TYPES.values()) + list(INSTITUTIONAL_FREQUENCIES.values())
    for text in texts:
        assert find_claims(text) == [], text
    assert find_claims(panel_page(key=KEY, codes=())) == []
