"""Private daily upload rejection aggregates remain bounded and optional."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift
from fastapi.testclient import TestClient

from quant_trade.audit.guard import find_claims
from quant_trade.audit.ops import OpsCounter, OpsMiddleware
from quant_trade.audit.ops_panel import upload_attempts_line, upload_rejections_section
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
KEY = "synthetic-owner-key-" + "k" * 30


def _store(tmp_path: Path) -> Any:
    return make_store(f"sqlite:///{tmp_path}/audit.db")


def test_rejections_aggregate_by_utc_day_category_format_and_detector(tmp_path: Path) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)
    for _ in range(2):
        counter.observe_rejection("columns_missing", "csv", "mapping", at=NOW)
    counter.observe_rejection("dates_unreadable", "csv", "schema", at=NOW)
    counter.observe_rejection("files_mismatch", "csv", "schema", at=NOW)
    counter.observe_rejection("columns_missing", "html", "mapping", at=NOW)
    local_midnight = datetime(2026, 10, 8, 23, tzinfo=timezone(timedelta(hours=-6)))
    counter.observe_rejection("columns_missing", "csv", "mapping", at=local_midnight)
    assert store.upload_rejection_rows("2000-01-01") == []  # no request-path SQL writes
    counter.flush()
    counter.flush()
    rows = store.upload_rejection_rows("2000-01-01")
    assert len(rows) == 5 and sum(row["count"] for row in rows) == 6
    assert {
        (row["day"], row["category"], row["detected_format"], row["detector"]): row["count"]
        for row in rows
    } == {
        ("2026-10-08", "columns_missing", "csv", "mapping"): 2,
        ("2026-10-08", "dates_unreadable", "csv", "schema"): 1,
        ("2026-10-08", "files_mismatch", "csv", "schema"): 1,
        ("2026-10-08", "columns_missing", "html", "mapping"): 1,
        ("2026-10-09", "columns_missing", "csv", "mapping"): 1,
    }
    assert len(store.upload_rejection_rows("2026-10-09")) == 1


@pytest.mark.parametrize("field", ["category", "detected_format", "detector", "day"])
def test_store_rejects_arbitrary_counter_dimensions(tmp_path: Path, field: str) -> None:
    store = _store(tmp_path)
    values = dict(
        day="2026-10-08", category="format_unknown", detected_format="unknown", detector="upload"
    )
    values[field] = "private-file-customer@example.invalid-192.0.2.1"
    with pytest.raises(ValueError):
        store.count_upload_rejection(**values)
    assert store.upload_rejection_rows("2000-01-01") == []


def test_counter_cannot_persist_unbounded_values(tmp_path: Path) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)
    private = "private-file-customer@example.invalid-192.0.2.1"
    counter.observe_rejection(private, private, private, at=NOW)
    counter.observe_rejection("format_unknown", private, private, at=NOW)
    counter.flush()
    (row,) = store.upload_rejection_rows("2000-01-01")
    assert row["count"] == 1 and row["detected_format"] == "unknown"
    assert private not in str(row)


def test_rejection_retry_does_not_duplicate_successful_buckets(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)
    counter.observe("upload", "invalid", 0.2, at=NOW)
    counter.observe_rejection("columns_missing", "csv", "mapping", at=NOW)
    counter.observe_rejection("format_unknown", "unknown", "detect_format", at=NOW)
    persist = store.count_upload_rejection

    def fail_one(**values: Any) -> None:
        if values["category"] == "format_unknown":
            raise OSError("private-db-password")
        persist(**values)

    monkeypatch.setattr(store, "count_upload_rejection", fail_one)
    counter.flush()
    assert counter.flush_failed
    assert sum(row["count"] for row in store.upload_rejection_rows("2000-01-01")) == 1
    monkeypatch.setattr(store, "count_upload_rejection", persist)
    counter.flush()
    counter.flush()
    assert not counter.flush_failed
    assert sum(row["count"] for row in store.upload_rejection_rows("2000-01-01")) == 2
    assert sum(row["count"] for row in store.ops_rows("2000-01-01")) == 1
    assert "private-db-password" not in caplog.text


def test_rejections_share_the_bounded_buffer(tmp_path: Path, monkeypatch: Any) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)
    monkeypatch.setattr("quant_trade.audit.ops.MAX_PENDING_KEYS", 2)
    counter.observe("upload", "invalid", 0.2, at=NOW)
    counter.observe_rejection("format_unknown", at=NOW)
    counter.observe_rejection("columns_missing", "csv", "mapping", at=NOW)
    counter.observe_rejection("format_unknown", at=NOW)
    counter.flush()
    assert counter.dropped == 1
    (row,) = store.upload_rejection_rows("2000-01-01")
    assert row["count"] == 2 and row["category"] == "format_unknown"


@pytest.mark.parametrize(
    "status,category",
    [
        (400, "invalid_upload"),
        (408, "upload_timeout"),
        (413, "too_large"),
        (422, "invalid_upload"),
        (429, "rate_limited"),
        (503, "service_busy"),
        (303, None),
        (402, None),
        (500, None),
    ],
)
def test_middleware_fallback_counts_each_rejected_request_once(
    tmp_path: Path, status: int, category: str | None
) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"rejected"})

    async def send(message: Any) -> None:
        pass

    asyncio.run(
        OpsMiddleware(inner, counter=counter)(
            {"type": "http", "method": "POST", "path": "/audits"}, None, send
        )
    )
    counter.flush()
    rows = store.upload_rejection_rows("2000-01-01")
    if category is None:
        assert rows == []
    else:
        assert len(rows) == 1 and rows[0]["category"] == category and rows[0]["count"] == 1


def test_seven_day_owner_table_excludes_older_and_future_rows_and_passes_guard() -> None:
    rows = [
        dict(day=day, category="columns_missing", detected_format="csv", count=count)
        for day, count in [
            ("2026-10-01", 100),
            ("2026-10-02", 2),
            ("2026-10-08", 3),
            ("2026-10-09", 100),
        ]
    ]
    rows.append(dict(day="2026-10-08", category="files_mismatch", detected_format="csv", count=4))
    html = upload_rejections_section(rows, at=NOW)
    assert "Subidas rechazadas (últimos 7 días)" in html
    assert "<td>columns_missing</td><td>csv</td><td>5</td>" in html
    assert "<td>files_mismatch</td><td>csv</td><td>4</td>" in html
    assert "100" not in html and find_claims(html) == []
    attempts = upload_attempts_line(
        [
            dict(operation="upload", outcome="success", count=2),
            dict(operation="upload", outcome="invalid", count=3),
            dict(operation="pdf", outcome="success", count=100),
        ]
    )
    assert "MEASURED · 5 / 2 (30 días)" in attempts
    assert find_claims(attempts) == []


@pytest.mark.parametrize("status", [303, 422])
def test_middleware_uses_parser_annotation_only_for_rejected_uploads(
    tmp_path: Path, status: int
) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        scope["state"] = dict(
            ops_rejection_category="columns_missing",
            ops_rejection_format="tradingview_csv",
            ops_rejection_detector="importers",
        )
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"response"})

    async def send(message: Any) -> None:
        pass

    asyncio.run(
        OpsMiddleware(inner, counter=counter)(
            {"type": "http", "method": "POST", "path": "/audits"}, None, send
        )
    )
    counter.flush()
    rows = store.upload_rejection_rows("2000-01-01")
    if status == 303:
        assert rows == []
    else:
        assert len(rows) == 1
        assert rows[0] == dict(
            day=datetime.now(UTC).date().isoformat(),
            category="columns_missing",
            detected_format="tradingview_csv",
            detector="importers",
            count=1,
        )


def test_rejection_telemetry_failure_cannot_change_response(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    counter = OpsCounter(_store(tmp_path))
    responses: list[dict[str, Any]] = []

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise OSError("private-customer-file.csv")

    monkeypatch.setattr(counter, "observe_rejection", unavailable)

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 422, "headers": []})
        await send({"type": "http.response.body", "body": b"safe explanation"})

    async def send(message: Any) -> None:
        responses.append(message)

    asyncio.run(
        OpsMiddleware(inner, counter=counter)(
            {"type": "http", "method": "POST", "path": "/audits"}, None, send
        )
    )
    assert responses[0]["status"] == 422 and responses[1]["body"] == b"safe explanation"
    assert "private-customer-file.csv" not in caplog.text


def test_real_upload_rejections_and_attempts_are_visible_only_with_owner_key(
    tmp_path: Path,
) -> None:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, admin_key=KEY
    )
    store = make_store(settings.database_url)
    app = create_app(settings, store)
    with TestClient(app) as client:
        rejected = client.post(
            "/audits",
            files={"report": ("private-customer-file.html", b"unrecognized contents", "text/html")},
            data={"consent": "on"},
            follow_redirects=False,
        )
        assert rejected.status_code in (400, 422)
        accepted = client.post(
            "/audits",
            files={"equity": ("synthetic.csv", csv_bytes(positive_drift(300)), "text/csv")},
            data={"consent": "on"},
            follow_redirects=False,
        )
        assert accepted.status_code == 303
        app.state.operations.flush()
        (rejection,) = store.upload_rejection_rows("2000-01-01")
        assert rejection["count"] == 1
        assert "private-customer-file" not in str(rejection)
        assert "id='upload-rejections'" not in client.get("/panel").text
        wrong = client.post("/panel", data={"key": "wrong"})
        assert wrong.status_code == 403 and "id='upload-rejections'" not in wrong.text
        owner = client.post("/panel", data={"key": KEY})
        assert owner.status_code == 200
        assert "id='upload-rejections'" in owner.text
        assert "id='upload-attempts'" in owner.text and "2 / 1 (30 días)" in owner.text
        assert rejection["category"] in owner.text
        assert "private-customer-file" not in owner.text
        assert find_claims(owner.text) == []
