"""Check a report file against what the service handed out. Offline."""

from __future__ import annotations

from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift
from fastapi.testclient import TestClient

from quant_trade.audit import check as check_lib
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit.guard import find_claims
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app


def _client(tmp_path: Path) -> tuple[TestClient, object]:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store)), store


def _upload(client: TestClient) -> tuple[str, str]:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}
    response = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    assert response.status_code == 303
    audit_id, query = response.headers["location"].removeprefix("/audits/").split("?")
    return audit_id, query


def _check(client: TestClient, content: bytes, path: str = "/comprobar", name: str = "r.json"):  # type: ignore[no-untyped-def]
    return client.post(path, files={"report": (name, content, "application/octet-stream")})


def test_the_json_a_buyer_received_is_recognised(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, query = _upload(client)
    content = client.get(f"/audits/{audit_id}.json?{query}").content
    response = _check(client, content)
    assert response.status_code == 200
    assert "Este archivo no se editó" in response.text
    assert "archivo JSON" in response.text and "de clase" in response.text
    assert find_claims(response.text) == []


def test_one_changed_byte_is_not_recognised(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, query = _upload(client)
    content = client.get(f"/audits/{audit_id}.json?{query}").content
    edited = content.replace(b'"account"', b'"accounT"', 1)
    assert edited != content
    response = _check(client, edited)
    assert "Rigor no generó este archivo" in response.text
    english = _check(client, edited, "/check")
    assert "Rigor did not produce this file" in english.text


def test_a_downloaded_pdf_is_recognised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def render(_page: str, *, audit_id: str, locale: str, wait_seconds: float = 0.0) -> bytes:
        return b"%PDF-" + audit_id.encode() + locale.encode()

    monkeypatch.setattr(pdf_lib, "report_pdf", render)
    client, _ = _client(tmp_path)
    audit_id, query = _upload(client)
    pdf = client.get(f"/audits/{audit_id}/pdf?{query}").content
    response = _check(client, pdf, "/check", "report.pdf")
    assert "This file was not edited" in response.text and "PDF Rigor produced" in response.text


def test_a_published_report_links_its_public_page(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, query = _upload(client)
    published = client.post(f"/audits/{audit_id}/publish?{query}", follow_redirects=False)
    public_id = published.headers["location"].split("/v/")[1].split("?")[0]
    content = client.get(f"/audits/{audit_id}.json?{query}").content
    assert f"/v/{public_id}?lang=es" in _check(client, content).text


def test_a_deleted_audit_is_no_longer_recognised(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    audit_id, query = _upload(client)
    content = client.get(f"/audits/{audit_id}.json?{query}").content
    assert store.delete_audit(audit_id)  # type: ignore[attr-defined]
    assert "Rigor no generó este archivo" in _check(client, content).text


def test_the_checked_file_is_not_kept(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    before = store.count_audits()  # type: ignore[attr-defined]
    _check(client, b"%PDF-some other file")
    assert store.count_audits() == before  # type: ignore[attr-defined]
    with store.engine.connect() as conn:  # type: ignore[attr-defined]
        rows = conn.execute(store.issued_files.select()).all()  # type: ignore[attr-defined]
    assert rows == []


@pytest.mark.parametrize(("path", "locale"), [("/comprobar", "es"), ("/check", "en")])
def test_the_page_exists_in_both_languages(tmp_path: Path, path: str, locale: str) -> None:
    client, _ = _client(tmp_path)
    page = client.get(path).text
    assert check_lib.COPY[locale]["title"] in page
    assert ("/check" if locale == "es" else "/comprobar") in page
    assert "enctype='multipart/form-data'" in page
    assert find_claims(page) == []


def test_empty_large_and_repeated_checks_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _client(tmp_path)
    assert _check(client, b"").status_code == 400
    assert client.post("/comprobar", data={"lang": "es"}).status_code == 400
    monkeypatch.setattr(check_lib, "MAX_CHECK_BYTES", 10)
    assert _check(client, b"x" * 11).status_code == 413
    monkeypatch.setattr(check_lib, "CHECKS_PER_HOUR_PER_IP", 3)
    assert _check(client, b"abc").status_code == 429


def test_every_text_passes_the_guard() -> None:
    for copy in check_lib.COPY.values():
        for value in copy.values():
            texts = (
                [value]
                if isinstance(value, str)
                else list(value.values())
                if isinstance(value, dict)
                else [part for pair in value for part in pair]
            )
            for text in texts:
                assert find_claims(text) == [], text


@pytest.mark.skipif(not pdf_lib.available(), reason="WeasyPrint/Pango not installed")
def test_the_sample_pdf_is_recognised_as_the_sample(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    pdf = client.get("/ejemplo.pdf").content
    response = _check(client, pdf, name="rigor-ejemplo.pdf")
    assert "Es el informe de ejemplo de Rigor, sin cambios." in response.text


def test_recording_is_idempotent_and_never_blocks_a_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    client, store = _client(tmp_path)
    at = datetime(2026, 1, 2, tzinfo=UTC)
    first = store.record_issued(b"same", audit_id="a", kind="pdf", at=at)  # type: ignore[attr-defined]
    assert store.record_issued(b"same", audit_id="b", kind="json", at=at) == first  # type: ignore[attr-defined]
    assert store.find_issued(first).audit_id == "a"  # type: ignore[attr-defined]
    audit_id, query = _upload(client)

    def broken(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("database down")

    monkeypatch.setattr(store, "record_issued", broken)
    assert client.get(f"/audits/{audit_id}.json?{query}").status_code == 200
