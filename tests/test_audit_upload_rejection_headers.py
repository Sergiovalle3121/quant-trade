"""A header refusal describes the uploaded file without misnaming its field."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from quant_trade.audit import pdf_tables
from quant_trade.audit.guard import find_claims
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.upload_rejections import REJECTION_COPY
from quant_trade.audit.web import UPLOAD_NAMES, create_app, message

CURVE = b"timestamp,equity\n2024-01-01,100\n2024-01-02,101\n"


def _app(tmp_path: Path) -> Any:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", free_mode=True)
    return create_app(settings, make_store(settings.database_url))


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize("field", tuple(UPLOAD_NAMES))
def test_image_refusal_never_misnames_another_field_as_the_equity_curve(
    tmp_path: Path, locale: str, field: str
) -> None:
    files = {"equity": ("curve.csv", CURVE)}
    files[field] = ("image.png", b"\x89PNG\r\n\x1a\n")
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
        assert payload["category"] == payload["format"] == "image"
        if field == "equity":
            assert payload["error"] == message("curve_is_picture", locale)
        else:
            assert payload["error"] == REJECTION_COPY[locale]["image"][0]
            assert "equity" not in payload["error"].lower()
        assert find_claims(payload["error"]) == []
        assert find_claims(payload["guidance_html"]) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert (row["category"], row["detected_format"], row["detector"]) == (
            "image",
            "image",
            "header",
        )


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
