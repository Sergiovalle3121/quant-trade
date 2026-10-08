"""A header refusal describes the uploaded file without misnaming its field."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from quant_trade.audit import pdf_tables
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import spanish
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.upload_rejections import REJECTION_COPY, rejection_guidance
from quant_trade.audit.web import UPLOAD_NAMES, create_app, message

CURVE = b"timestamp,equity\n2024-01-01,100\n2024-01-02,101\n"


def _app(tmp_path: Path) -> Any:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", free_mode=True)
    return create_app(settings, make_store(settings.database_url))


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize("field", tuple(UPLOAD_NAMES))
@pytest.mark.parametrize(
    ("content", "category", "detected", "message_key"),
    (
        (b"\x89PNG\r\n\x1a\n", "image", "image", "file_is_picture"),
        (b"\x7fELF", "format_unknown", "unknown", "file_not_a_report"),
    ),
)
def test_header_refusal_names_its_field_without_repeating_the_guidance(
    tmp_path: Path,
    locale: str,
    field: str,
    content: bytes,
    category: str,
    detected: str,
    message_key: str,
) -> None:
    files = {"equity": ("curve.csv", CURVE)}
    files[field] = ("file.bin", content)
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/audits",
            files=files,
            data={"consent": "on", "locale": locale},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["category"] == category
        assert payload["format"] == detected
        if category == "image" and field == "equity":
            assert payload["error"] == message("curve_is_picture", locale)
        else:
            assert payload["error"] == message(
                message_key, locale, what=UPLOAD_NAMES[field][locale]
            )
        if field != "equity":
            assert "equity" not in payload["error"].lower()
        assert payload["error"] != REJECTION_COPY[locale][category][0]
        assert payload["guidance_html"] == rejection_guidance(category, detected, locale)
        assert find_claims(payload["error"]) == []
        assert find_claims(payload["guidance_html"]) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert (row["category"], row["detected_format"], row["detector"]) == (
            category,
            detected,
            "header",
        )


@pytest.mark.parametrize("message_key", ("file_is_picture", "file_not_a_report"))
def test_header_message_templates_keep_their_spanish_rule(message_key: str) -> None:
    assert spanish(message(message_key, "en", what="x")) == message(message_key, "es", what="x")


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_auxiliary_header_refusal_identifies_the_file_it_inspected(
    tmp_path: Path, locale: str
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/audits",
            files={"trades": ("image.png", b"\x89PNG\r\n\x1a\n")},
            data={"consent": "on", "locale": locale},
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 400
    payload = response.json()
    assert payload["category"] == payload["format"] == "image"
    assert payload["guidance_html"] == rejection_guidance("image", "image", locale)
    assert find_claims(payload["guidance_html"]) == []


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize(
    ("files", "category"),
    (
        ({"trades": ("trades.csv", CURVE), "variants": ("variants.csv", CURVE)}, "empty_file"),
        (
            {
                "report": ("report.csv", b""),
                "equity": ("curve.csv", b"timestamp,equity\n2024-01-01,100\n"),
            },
            "too_few_rows",
        ),
    ),
)
def test_auxiliary_bytes_do_not_claim_the_primary_format_was_inspected(
    tmp_path: Path, locale: str, files: dict[str, tuple[str, bytes]], category: str
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/audits",
            files=files,
            data={"consent": "on", "locale": locale},
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 400
    payload = response.json()
    assert payload["category"] == category
    assert payload["format"] == "unknown"
    assert payload["guidance_html"] == rejection_guidance(
        category, "unknown", locale, file_inspected=False
    )
    assert find_claims(payload["guidance_html"]) == []


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_pdf_report_without_a_table_has_a_field_neutral_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    monkeypatch.setattr(pdf_tables, "_extract", lambda data: {})
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/audits",
            files={"report": ("report.pdf", b"%PDF-1.4\n%%EOF")},
            data={"consent": "on", "locale": locale},
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 400
    payload = response.json()
    assert payload["category"] == "pdf_no_trades"
    assert payload["format"] == "pdf"
    assert "PDF" in payload["error"]
    assert "equity" not in payload["error"].lower()
    assert find_claims(payload["error"]) == []
    assert find_claims(payload["guidance_html"]) == []
