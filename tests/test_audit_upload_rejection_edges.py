"""Rejection edge paths retain forms, private visibility and admission accounting."""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from quant_trade.audit.guard import find_claims
from quant_trade.audit.ops import OpsMiddleware
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.upload_rejections import rejection_guidance
from quant_trade.audit.web import AuditAdmissionMiddleware, create_app

KEY = "synthetic-owner-key-" + "k" * 32
ONE_ROW = b"timestamp,equity\n2024-01-01,100\n"


def _app(tmp_path: Path) -> Any:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        free_mode=True,
        bootstrap_samples=100,
        admin_key=KEY,
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
        assert rejection_guidance("invalid_declaration", "unknown", locale) in response.text
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
        assert rejection_guidance("invalid_upload", "unknown", locale) in response.text
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
    assert rejection_guidance("upload_timeout", "unknown", locale) in page
    assert find_claims(page) == []
    assert slots.acquire(blocking=False)
    slots.release()
    app.state.operations.flush()
    (row,) = app.state.store.upload_rejection_rows("2000-01-01")
    assert row["category"] == "upload_timeout" and row["count"] == 1
    assert row["detector"] == "admission"
