"""Rejection edge paths retain forms, private visibility and admission accounting."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from html import unescape
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from quant_trade.audit.guard import find_claims
from quant_trade.audit.ops import OpsMiddleware
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.upload_rejections import (
    DETECTED_FORMATS,
    REJECTION_CATEGORIES,
    rejection_guidance,
)
from quant_trade.audit.web import AuditAdmissionMiddleware, create_app, request_body_limit

KEY = "synthetic-owner-key-" + "k" * 32
ONE_ROW = b"timestamp,equity\n2024-01-01,100\n"


def _app(tmp_path: Path, **kwargs: Any) -> Any:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        free_mode=True,
        bootstrap_samples=100,
        admin_key=KEY,
        **kwargs,
    )
    return create_app(settings, make_store(settings.database_url))


def test_empty_report_picker_does_not_hide_rejected_equity_format(tmp_path: Path) -> None:
    # A browser includes the unused report picker with an explicit empty filename.
    body = (
        b'--edge\r\nContent-Disposition: form-data; name="report"; filename=""\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n\r\n"
        b'--edge\r\nContent-Disposition: form-data; name="equity"; filename="curve.csv"\r\n'
        b"Content-Type: text/csv\r\n\r\n" + ONE_ROW + b"\r\n"
        b'--edge\r\nContent-Disposition: form-data; name="consent"\r\n\r\non\r\n--edge--\r\n'
    )
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/audits",
            content=body,
            headers={"content-type": "multipart/form-data; boundary=edge"},
        )
        assert response.status_code == 400
        assert rejection_guidance("too_few_rows", "csv", "es") in response.text
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert row["detected_format"] == "csv" and row["category"] == "too_few_rows"


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_form_validation_preserves_columns_declarations_and_language(
    tmp_path: Path,
    locale: str,
) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/audits",
            files={"equity": ("curve.csv", ONE_ROW)},
            data={
                "trials": "1234567890123",
                "cost_bps": "2.5",
                "consent": "on",
                "locale": locale,
                "col_profit": "Result & fees",
                "description": "Trial notes",
                "return_frequency": "monthly",
                "return_unit": "percent",
            },
        )
        assert response.status_code == 400
        assert (
            rejection_guidance("invalid_declaration", "unknown", locale, file_inspected=False)
            in response.text
        )
        for name, value in (
            ("trials", "1234567890123"),
            ("cost_bps", "2.5"),
            ("col_profit", "Result &amp; fees"),
        ):
            assert re.search(rf"<input[^>]*name='{name}'[^>]*value='{value}'", response.text)
        assert ">Trial notes</textarea>" in response.text
        assert f"<option value='{locale}' selected>" in response.text
        assert "<option value='monthly' selected>" in response.text
        assert "<option value='percent' selected>" in response.text
        assert find_claims(response.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert row["category"] == "invalid_declaration" and row["detector"] == "form"


def test_rejection_query_failure_keeps_existing_operations_and_retention_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(tmp_path)
    caplog.set_level(logging.DEBUG)

    def unavailable(since_day: str) -> Any:
        raise RuntimeError("PRIVATE-query-detail")

    monkeypatch.setattr(app.state.store, "upload_rejection_rows", unavailable)
    with TestClient(app) as client:
        response = client.post(app.state.panel_path, data={"key": KEY})
    assert response.status_code == 200
    assert "<section id='operations'>" in response.text
    assert "<h3>Retención</h3>" in response.text
    assert "Automática apagada: requiere purga manual" in response.text
    assert "Subidas rechazadas:" in response.text and "consulta no disponible." in response.text
    assert "PRIVATE-query-detail" not in response.text + caplog.text
    assert find_claims(response.text) == []


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_malformed_multipart_uses_localized_upload_guidance(tmp_path: Path, locale: str) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            f"/audits?lang={locale}",
            content=b"garbage",
            headers={"content-type": "multipart/form-data"},
        )
        assert response.status_code == 400
        assert (
            rejection_guidance("invalid_upload", "unknown", locale, file_inspected=False)
            in response.text
        )
        assert find_claims(response.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert row["category"] == "invalid_upload" and row["count"] == 1


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_stalled_body_uses_localized_guidance_and_counts_one_timeout(
    tmp_path: Path,
    locale: str,
) -> None:
    app = _app(tmp_path)
    configured = next(item for item in app.user_middleware if item.cls is AuditAdmissionMiddleware)
    slots = threading.BoundedSemaphore(1)

    async def read_body(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        raise AssertionError("the stalled body unexpectedly finished")

    admission = AuditAdmissionMiddleware(
        read_body,
        slots=slots,
        paused=False,
        reject=configured.kwargs["reject"],
        body_seconds=0.01,
    )
    observed = OpsMiddleware(admission, counter=app.state.operations)
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/audits",
        "headers": [],
        "query_string": f"lang={locale}".encode(),
        "state": {},
    }
    messages: list[dict[str, Any]] = []

    async def scenario() -> None:
        stalled = asyncio.Event()

        async def receive() -> Any:
            await stalled.wait()

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await observed(scope, receive, send)

    asyncio.run(scenario())
    assert messages[0]["status"] == 408
    page = b"".join(item.get("body", b"") for item in messages).decode()
    assert rejection_guidance("upload_timeout", "unknown", locale, file_inspected=False) in page
    assert find_claims(page) == []
    assert slots.acquire(blocking=False)
    slots.release()
    app.state.operations.flush()
    (row,) = app.state.store.upload_rejection_rows("2000-01-01")
    assert row["category"] == "upload_timeout" and row["count"] == 1
    assert row["detector"] == "admission"


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_missing_consent_preserves_declarations_and_counts_form_refusal(
    tmp_path: Path,
    locale: str,
) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/audits",
            files={"equity": ("curve.csv", ONE_ROW)},
            data={
                "locale": locale,
                "trials": "7",
                "cost_bps": "2.5",
                "oos_start": "2024-01-02",
                "description": "Synthetic consent notes",
                "col_profit": "Result & fees",
                "return_frequency": "monthly",
                "return_unit": "percent",
            },
        )
        assert response.status_code == 400
        assert (
            rejection_guidance("invalid_declaration", "unknown", locale, file_inspected=False)
            in response.text
        )
        for name, value in (
            ("trials", "7"),
            ("cost_bps", "2.5"),
            ("oos_start", "2024-01-02"),
            ("col_profit", "Result &amp; fees"),
        ):
            assert re.search(rf"<input[^>]*name='{name}'[^>]*value='{value}'", response.text)
        assert ">Synthetic consent notes</textarea>" in response.text
        for selected in (locale, "monthly", "percent"):
            assert f"<option value='{selected}' selected>" in response.text
        assert find_claims(response.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert (row["category"], row["detected_format"], row["detector"], row["count"]) == (
            "invalid_declaration",
            "unknown",
            "form",
            1,
        )


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_form_without_any_file_counts_empty_upload(tmp_path: Path, locale: str) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/audits", data={"consent": "on", "locale": locale})
        assert response.status_code == 400
        assert (
            rejection_guidance("empty_file", "unknown", locale, file_inspected=False)
            in response.text
        )
        assert find_claims(response.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert (row["category"], row["detected_format"], row["detector"], row["count"]) == (
            "empty_file",
            "unknown",
            "form",
            1,
        )


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_oversized_request_body_has_guidance_and_counts_body_limit(
    tmp_path: Path,
    locale: str,
) -> None:
    upload_limit = 100
    app = _app(tmp_path, max_upload_bytes=upload_limit)
    with TestClient(app) as client:
        response = client.post(
            f"/audits?lang={locale}",
            content=b"x" * (request_body_limit(upload_limit) + 1),
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 413
        assert (
            rejection_guidance("too_large", "unknown", locale, file_inspected=False)
            in response.text
        )
        assert find_claims(response.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert (row["category"], row["detected_format"], row["detector"], row["count"]) == (
            "too_large",
            "unknown",
            "body_limit",
            1,
        )


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_unavailable_admission_slot_has_guidance_and_counts_busy(
    tmp_path: Path,
    locale: str,
) -> None:
    app = _app(tmp_path)
    slots = app.state.upload_admission_slots
    held = 0
    while slots.acquire(blocking=False):
        held += 1
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/audits?lang={locale}",
                files={"equity": ("curve.csv", ONE_ROW)},
                data={"consent": "on", "locale": locale},
            )
            assert response.status_code == 503
            assert (
                rejection_guidance("service_busy", "unknown", locale, file_inspected=False)
                in response.text
            )
            assert find_claims(response.text) == []
            app.state.operations.flush()
            (row,) = app.state.store.upload_rejection_rows("2000-01-01")
            assert (row["category"], row["detected_format"], row["detector"], row["count"]) == (
                "service_busy",
                "unknown",
                "admission",
                1,
            )
    finally:
        for _ in range(held):
            slots.release()


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize(
    ("content", "status", "category", "detected", "detector"),
    [
        (b"\x89PNG\r\n\x1a\n", 400, "image", "image", "header"),
        (
            b"When,Amount\n2024-01-01,100\n2024-01-02,101\n",
            422,
            "columns_missing",
            "csv",
            "mapping",
        ),
    ],
)
def test_json_upload_and_mapping_refusals_use_safe_localized_guidance(
    tmp_path: Path,
    locale: str,
    content: bytes,
    status: int,
    category: str,
    detected: str,
    detector: str,
) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/audits",
            files={"report": ("synthetic.csv", content)},
            data={"consent": "on", "locale": locale},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == status
        assert response.headers["content-type"].startswith("application/json")
        payload = response.json()
        assert payload["category"] == category and category in REJECTION_CATEGORIES
        assert payload["format"] == detected and detected in DETECTED_FORMATS
        assert payload["guidance_html"] == rejection_guidance(category, detected, locale)
        assert "<script" not in payload["guidance_html"].lower()
        assert find_claims(payload["guidance_html"]) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert row["detector"] == detector


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_real_rejection_guide_links_load_in_the_selected_language(
    tmp_path: Path,
    locale: str,
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/audits",
            files={"report": ("synthetic.png", b"\x89PNG\r\n\x1a\n")},
            data={"consent": "on", "locale": locale},
        )
        assert response.status_code == 400
        block = re.search(r'<div[^>]*data-upload-rejection="image"[^>]*>(.*?)</div>', response.text)
        assert block is not None
        hrefs = re.findall(r'href="([^"]+)"', block.group(1))
        assert len(hrefs) == 4
        for href in hrefs:
            guide = client.get(unescape(href))
            assert guide.status_code == 200, href
            assert f"<html lang='{locale}'>" in guide.text, href
