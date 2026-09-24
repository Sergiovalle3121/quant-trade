"""Every customer page in Spanish (the default) and English, with a switch."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, synthetic_mt5_report

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import BADGE_NOTICE  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

SWITCH = {"es": ">English</a>", "en": ">Español</a>"}


def _client(tmp_path: Path, **overrides) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
        **overrides,
    )
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store)), store


def _upload(client: TestClient, locale: str = "es", **data) -> tuple[str, str]:
    files = {"report": ("ReportTester.html", synthetic_mt5_report(days=120), "text/html")}
    payload = {"consent": "on", "locale": locale, **data}
    response = client.post("/audits", files=files, data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    return location.split("/audits/")[1].split("?")[0], location.split("token=")[1]


def _assert_page(text: str, locale: str) -> None:
    assert f"<html lang='{locale}'>" in text
    assert SWITCH[locale] in text, "no language switch"
    assert find_claims(text) == []


def test_every_public_page_exists_in_both_languages(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    pages = {
        "es": ["/", "/ejemplo", "/terminos", "/privacidad"],
        "en": ["/en", "/?lang=en", "/sample", "/terms", "/privacy"],
    }
    for locale, paths in pages.items():
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
            _assert_page(response.text, locale)
    # Spanish stays the default on the addresses already shared.
    assert "Sube tu backtest" in client.get("/").text
    assert "Upload your backtest" in client.get("/en").text
    assert "/sample?lang=en" in client.get("/ejemplo").text
    assert "/ejemplo?lang=es" in client.get("/sample").text


def test_the_report_opens_in_its_upload_language_and_switches(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, token = _upload(client, "es")
    default = client.get(f"/audits/{audit_id}?token={token}").text
    _assert_page(default, "es")
    assert f"/audits/{audit_id}?token={token}&amp;lang=en" in default
    assert "Avisos de lectura: informe:" in default
    assert "closed trades only" not in default
    english = client.get(f"/audits/{audit_id}?token={token}&lang=en").text
    _assert_page(english, "en")
    assert "Parse warnings: report:" in english and "closed trades only" in english
    assert "Qué significa para ti" not in english
    assert f"/audits/{audit_id}?token={token}&amp;lang=es" in english
    # The stored result is the same whichever language reads it.
    first = client.get(f"/audits/{audit_id}.json?token={token}").json()
    assert first["declared"]["locale"] == "es"

    audit_en, token_en = _upload(client, "en")
    _assert_page(client.get(f"/audits/{audit_en}?token={token_en}").text, "en")
    # An unknown value falls back to the upload language.
    _assert_page(client.get(f"/audits/{audit_en}?token={token_en}&lang=fr").text, "en")


def test_publishing_keeps_the_reader_language(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, token = _upload(client, "es")
    response = client.post(
        f"/audits/{audit_id}/publish?token={token}&lang=en", follow_redirects=False
    )
    location = response.headers["location"]
    assert location.endswith("?lang=en")
    public_id = location.split("/v/")[1].split("?")[0]
    _assert_page(client.get(f"/v/{public_id}?lang=en").text, "en")
    _assert_page(client.get(f"/v/{public_id}").text, "es")
    badge_es = client.get(f"/v/{public_id}/badge.svg").text
    badge_en = client.get(f"/v/{public_id}/badge.svg?lang=en").text
    assert BADGE_NOTICE["es"] in badge_es and BADGE_NOTICE["en"] in badge_en
    assert find_claims(badge_es) == [] and find_claims(badge_en) == []


def test_a_locked_preview_keeps_its_language_through_the_code_form(tmp_path: Path) -> None:
    client, store = _client(
        tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/000"
    )
    audit_id, token = _upload(client, "es")
    preview = client.get(f"/audits/{audit_id}?token={token}&lang=en").text
    _assert_page(preview, "en")
    assert f"/audits/{audit_id}/redeem?token={token}&amp;lang=en" in preview
    code, _ = store.create_access_code(  # type: ignore[attr-defined]
        credits=1, note="", at=datetime(2026, 9, 24, tzinfo=UTC)
    )
    response = client.post(
        f"/audits/{audit_id}/redeem?token={token}&lang=en",
        data={"code": code},
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("&lang=en&code=applied")
    page = client.get(response.headers["location"]).text
    _assert_page(page, "en")
    assert "Access code applied" in page


def test_error_pages_follow_the_language_and_offer_the_switch(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    for locale, expected in (("es", "No encontramos"), ("en", "We could not find")):
        response = client.get(f"/audits/nope?token=x&lang={locale}")
        assert response.status_code == 404
        assert expected in response.text
        _assert_page(response.text, locale)
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}
    refused = client.post("/audits", files=files, data={"locale": "en"})
    assert refused.status_code == 400 and "You must accept the terms" in refused.text
    _assert_page(refused.text, "en")
