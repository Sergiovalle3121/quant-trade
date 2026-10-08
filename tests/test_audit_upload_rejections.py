"""Synthetic upload refusals: guidance, preserved declarations and private counts."""

from __future__ import annotations

import logging
from html import escape, unescape
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from quant_trade.audit import pdf_tables, web
from quant_trade.audit.guard import find_claims
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.upload_rejections import REJECTION_COPY, rejection_guidance

CURVE = b"timestamp,equity\n2024-01-01,100\n2024-01-02,101\n"
KEY = "synthetic-owner-key-" + "k" * 32


def _app(tmp_path: Path, **kwargs: Any) -> Any:
    cfg = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        free_mode=True,
        bootstrap_samples=100,
        admin_key=KEY,
        **kwargs,
    )
    return web.create_app(cfg, make_store(cfg.database_url))


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize(
    ("category", "field", "content", "detected", "status", "detector"),
    [
        ("format_unknown", "report", b"\x7fELF" + b"x" * 9000, "unknown", 400, "header"),
        (
            "format_unknown",
            "report",
            b"<html><body>unknown</body></html>",
            "html",
            400,
            "importers",
        ),
        ("image", "report", b"\x89PNG\r\n\x1a\n" + b"x" * 9000, "image", 400, "header"),
        ("pdf_no_trades", "report", b"%PDF-1.4\n%%EOF", "pdf", 400, "importers"),
        ("too_few_rows", "equity", b"timestamp,equity\n2024-01-01,100\n", "csv", 400, "schema"),
        (
            "dates_unreadable",
            "equity",
            b"timestamp,equity\n15/03/2024,100\n03/16/2024,101\n",
            "csv",
            400,
            "schema",
        ),
        (
            "columns_missing",
            "report",
            b"When,Amount\n2024-01-01,100\n2024-01-02,101\n",
            "csv",
            422,
            "mapping",
        ),
        (
            "invalid_values",
            "equity",
            b"timestamp,equity\n2024-01-01,1e25\n2024-01-02,1e26\n",
            "csv",
            400,
            "schema",
        ),
        ("empty_file", "report", b"", "unknown", 400, "form"),
    ],
)
def test_synthetic_refusal_explains_cause_and_records_only_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    locale: str,
    category: str,
    field: str,
    content: bytes,
    detected: str,
    status: int,
    detector: str,
) -> None:
    # No external PDF process or network is needed to represent a table-less PDF.
    monkeypatch.setattr(pdf_tables, "_extract", lambda data: {})
    app = _app(tmp_path)
    caplog.set_level(logging.DEBUG)
    email = "private-upload@example.invalid"
    ip = "192.0.2.231"
    private = f"PRIVATE-description-<unsafe> {email}"
    with TestClient(app) as client:
        answer = client.post(
            "/audits",
            files={field: ("PRIVATE-file-name.csv", content)},
            headers={"X-Forwarded-For": ip},
            data={
                "consent": "on",
                "locale": locale,
                "trials": "7",
                "cost_bps": "2.5",
                "description": private,
                "oos_start": "2024-01-02",
            },
        )
        assert answer.status_code == status, answer.text[:500]
        assert (
            rejection_guidance(category, detected, locale, file_inspected=category != "empty_file")
            in answer.text
        )
        assert find_claims(answer.text) == []
        assert "name='trials'" in answer.text and "value='7'" in answer.text
        assert escape(private, quote=True) in answer.text
        app.state.operations.flush()
        rows = app.state.store.upload_rejection_rows("2000-01-01")
        assert len(rows) == 1
        assert rows[0]["category"] == category
        assert rows[0]["detected_format"] == detected
        assert rows[0]["detector"] == detector
        assert rows[0]["count"] == 1
        for secret in ("PRIVATE", email, ip):
            assert secret not in str(rows) + caplog.text


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize(
    ("category", "status", "detector"),
    [
        ("too_large", 413, "body_limit"),
        ("rate_limited", 429, "rate_limit"),
        ("invalid_declaration", 400, "form"),
        ("invalid_upload", 400, "importers"),
        ("service_busy", 503, "admission"),
    ],
)
def test_request_refusals_have_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    locale: str,
    category: str,
    status: int,
    detector: str,
) -> None:
    app = _app(tmp_path, max_upload_bytes=100, max_uploads_per_hour_per_ip=1)
    caplog.set_level(logging.DEBUG)
    email = "private-refusal@example.invalid"
    ip = "192.0.2.232"
    content = CURVE
    data = {
        "consent": "on",
        "locale": locale,
        "trials": "4",
        "description": f"PRIVATE-description {email}",
    }
    if category == "too_large":
        content += b"x" * 300
    elif category == "rate_limited":
        monkeypatch.setattr(app.state.store, "count_uploads_since", lambda *args: 1)
    elif category == "invalid_declaration":
        data["trials"] = "0"
    elif category == "invalid_upload":

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("PRIVATE-file.csv PRIVATE-content@example.invalid")

        monkeypatch.setattr(web, "build_inputs", broken)
    elif category == "service_busy":

        async def no_slot(*args: Any) -> bool:
            return False

        monkeypatch.setattr(web, "_take_slot", no_slot)
    with TestClient(app) as client:
        answer = client.post(
            "/audits",
            files={"equity": ("PRIVATE-file.csv", content)},
            data=data,
            headers={"X-Forwarded-For": ip},
        )
        assert answer.status_code == status, answer.text[:500]
        assert f'data-upload-rejection="{category}"' in answer.text
        reason, step = REJECTION_COPY[locale][category]
        assert reason in unescape(answer.text) and step in unescape(answer.text)
        assert "href=" in answer.text and find_claims(answer.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert row["category"] == category and row["detector"] == detector
        assert row["count"] == 1
        for secret in ("PRIVATE", email, ip):
            assert secret not in str(row) + caplog.text
        if category == "invalid_upload":
            (warning,) = [
                record
                for record in caplog.records
                if record.getMessage() == "upload could not be parsed: RuntimeError"
            ]
            assert warning.levelno == logging.WARNING
            assert warning.exc_info is None


@pytest.mark.parametrize("signature", [b"\x7fELF", b"\x89PNG\r\n\x1a\n"])
def test_definite_unsupported_header_never_reads_whole_file_or_calls_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signature: bytes,
) -> None:
    original = UploadFile.read
    reads: list[int] = []

    async def bounded_read(self: UploadFile, size: int = -1) -> bytes:
        reads.append(size)
        assert size == 4096
        return await original(self, size)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a definite unsupported header reached a parser")

    monkeypatch.setattr(UploadFile, "read", bounded_read)
    monkeypatch.setattr(web, "is_return_series", forbidden)
    monkeypatch.setattr(web, "build_inputs", forbidden)
    with TestClient(_app(tmp_path)) as client:
        answer = client.post(
            "/audits",
            files={"report": ("data.bin", signature + b"x" * 100_000)},
            data={"consent": "on"},
        )
    assert answer.status_code == 400
    assert reads == [4096]


def test_owner_panel_shows_rejections_and_attempts_but_accepted_is_not_rejected(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        rejected = client.post(
            "/audits",
            files={"report": ("private.png", b"\x89PNG\r\n\x1a\n")},
            data={"consent": "on"},
        )
        assert rejected.status_code == 400
        accepted = client.post(
            "/audits",
            files={"equity": ("curve.csv", csv_bytes(positive_drift(60)))},
            data={"consent": "on"},
            follow_redirects=False,
        )
        assert accepted.status_code == 303, accepted.text[:300]
        panel_path = app.state.panel_path
        assert "upload-rejections" not in client.get(panel_path).text
        assert "upload-rejections" not in client.post(panel_path, data={"key": "wrong"}).text
        panel = client.post(panel_path, data={"key": KEY})
        assert panel.status_code == 200
        assert "Subidas rechazadas (últimos 7 días)" in panel.text
        assert "<td>image</td><td>image</td><td>1</td>" in panel.text
        assert "Subidas intentadas / aceptadas:" in panel.text
        assert "2 / 1 (30 días)" in panel.text
        assert find_claims(panel.text) == []
        rows = app.state.store.upload_rejection_rows("2000-01-01")
        assert sum(row["count"] for row in rows) == 1
