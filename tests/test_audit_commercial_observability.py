"""Private, additive telemetry and costs; customer delivery remains independent."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in
from fastapi.testclient import TestClient

from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import spanish
from quant_trade.audit.ops import OpsCounter, OpsMiddleware, percentile_bucket, retention_status
from quant_trade.audit.ops_panel import amount_cents, contribution
from quant_trade.audit.pages import landing
from quant_trade.audit.retention import run_retention
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import account_order_ref, make_store
from quant_trade.audit.store_ops import COST_CATEGORIES, stamp
from quant_trade.audit.web import create_app

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
KEY = "private-operator-key-" + "k" * 30


def _store(tmp_path: Path) -> Any:
    return make_store(f"sqlite:///{tmp_path}/audit.db")


def _app(tmp_path: Path, **settings: Any) -> Any:
    cfg = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        admin_key=KEY,
        **settings,
    )
    return create_app(cfg, make_store(cfg.database_url))


def test_counter_retries_failed_sql_without_duplicate_completed_keys(tmp_path, monkeypatch) -> None:
    store, calls = _store(tmp_path), []
    counter = OpsCounter(store)
    counter.observe("upload", "success", 0.1, at=NOW)
    counter.observe("upload", "success", 0.1, at=NOW)
    counter.observe("pdf", "busy", 2, at=NOW, locale="en")
    original = store.count_ops

    def fail_pdf(**values: Any) -> None:
        calls.append(values)
        if values["operation"] == "pdf":
            raise OSError("private connection secret must not be logged")
        original(**values)

    monkeypatch.setattr(store, "count_ops", fail_pdf)
    counter.flush()
    assert counter.flush_failed
    assert sum(row["count"] for row in store.ops_rows("2026-10-05")) == 2
    monkeypatch.setattr(store, "count_ops", original)
    counter.flush()
    counter.flush()
    assert not counter.flush_failed
    assert sum(row["count"] for row in store.ops_rows("2026-10-05")) == 3
    assert calls[0]["amount"] == 2


def test_in_memory_counter_failure_never_escapes(monkeypatch) -> None:
    counter = OpsCounter(object())
    monkeypatch.setattr(
        counter, "_observe", lambda *a, **kw: (_ for _ in ()).throw(OSError("secret"))
    )
    counter.observe("audit", "success", 1)


def test_worker_or_flush_failure_cannot_break_application_lifecycle(monkeypatch) -> None:
    counter = OpsCounter(object())

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("private failure details")

    monkeypatch.setattr("quant_trade.audit.ops.threading.Thread.start", unavailable)
    counter.start()
    assert counter._thread is None and counter.flush_failed
    monkeypatch.setattr(counter, "_flush", unavailable)
    counter.stop()
    assert counter.flush_failed


@pytest.mark.parametrize("started", [False, True])
def test_shutdown_and_panel_flush_do_not_wait_for_a_stuck_writer(started: bool) -> None:
    entered, release = threading.Event(), threading.Event()

    class StuckStore:
        def count_ops(self, **values: Any) -> None:
            entered.set()
            assert release.wait(5)

    counter = OpsCounter(StuckStore(), interval_seconds=0.001)
    counter.observe("audit", "success", 1)
    if started:
        counter.start()
        assert entered.wait(2)
        before = time.monotonic()
        counter.flush()  # the private panel cannot queue behind a blocked writer
        assert time.monotonic() - before < 0.2
    before = time.monotonic()
    try:
        counter.stop(timeout=0.03)
        assert time.monotonic() - before < 0.5
        assert entered.wait(2)
        assert counter.flush_failed
        assert counter._thread is not None and counter._thread.is_alive()
    finally:
        release.set()
        if counter._thread is not None:
            counter._thread.join(2)
    assert counter._thread is not None and not counter._thread.is_alive()


def test_buffer_is_bounded_and_histograms_do_not_invent_exact_times(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("quant_trade.audit.ops.MAX_PENDING_KEYS", 2)
    counter = OpsCounter(_store(tmp_path))
    for kind in ("success", "invalid", "busy"):
        counter.observe("upload", kind, 0.5, at=NOW)
    counter.observe("upload", "success", 0.5, at=NOW)
    counter.flush()
    assert counter.dropped == 1
    rows = counter._store.ops_rows("2026-10-05")
    assert sum(r["count"] for r in rows) == 3
    assert percentile_bucket([], 0.95) == "NOT_MEASURED"
    assert (
        percentile_bucket(
            [{"bucket_ms": 500, "count": 19}, {"bucket_ms": 120001, "count": 1}], 0.95
        )
        == "≤0.5 s"
    )
    assert percentile_bucket([{"bucket_ms": 120001, "count": 1}], 0.95) == ">120 s"


@pytest.mark.parametrize(
    "status,outcome",
    [(303, "success"), (413, "invalid"), (503, "busy"), (500, "error"), (402, "denied")],
)
def test_middleware_counts_before_multipart_without_customer_data(
    tmp_path, status, outcome
) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)

    async def receive() -> Any:
        raise AssertionError("body must not be read")

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"result"})

    async def send(message: Any) -> None:
        pass

    asyncio.run(
        OpsMiddleware(inner, counter=counter)(
            {
                "type": "http",
                "method": "POST",
                "path": "/audits",
                "query_string": b"lang=en&token=private-token",
            },
            receive,
            send,
        )
    )
    counter.flush()
    (row,) = store.ops_rows("2000-01-01")
    assert (row["operation"], row["outcome"], row["locale"]) == ("upload", outcome, "en")
    assert "private-token" not in str(row)


def test_failed_telemetry_preserves_real_upload_and_pdf(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    monkeypatch.setattr(pdf_lib, "report_pdf", lambda *a, **kw: b"%PDF-1.4 synthetic offline")
    app = _app(tmp_path)

    def fail_sql(**values: Any) -> None:
        raise OSError("secret-db-password")

    monkeypatch.setattr(app.state.store, "count_ops", fail_sql)
    original_counter = type(app.state.store).count_ops
    with TestClient(app) as client:
        signed_in(client)
        upload = client.post(
            "/audits",
            files={"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")},
            data={"consent": "on", "locale": "en"},
            follow_redirects=False,
        )
        assert upload.status_code == 303
        location = upload.headers["location"]
        assert client.get(location).status_code == 200
        audit_id, query = location.removeprefix("/audits/").split("?")
        response = client.get(f"/audits/{audit_id}/pdf?{query}")
        assert response.status_code == 200 and response.content.startswith(b"%PDF")
        app.state.operations.flush()
        assert app.state.operations.flush_failed
        panel = client.post("/panel", data={"key": KEY})
        assert panel.status_code == 200
        assert "Telemetría pendiente de reintento: sí" in panel.text
        assert "Cohorte X 14 días" in panel.text
        assert "consulta de telemetría no disponible" not in panel.text
        monkeypatch.setattr(
            app.state.store,
            "count_ops",
            lambda **values: original_counter(app.state.store, **values),
        )
        app.state.operations.flush()
        rows = app.state.store.ops_rows("2000-01-01")
        assert {(r["operation"], r["outcome"]) for r in rows} == {
            (operation, "success") for operation in ("upload", "audit", "queue", "pdf")
        }
        assert all(row["locale"] == "en" and row["count"] == 1 for row in rows)
    assert "secret-db-password" not in caplog.text


@pytest.mark.parametrize(
    "path,locale", [("/ejemplo.pdf", "es"), ("/sample.pdf", "en"), ("/pt/exemplo.pdf", "pt")]
)
def test_public_pdf_samples_use_their_page_language(tmp_path, path, locale) -> None:
    store = _store(tmp_path)
    counter = OpsCounter(store)

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"%PDF"})

    async def send(message: Any) -> None:
        pass

    asyncio.run(
        OpsMiddleware(inner, counter=counter)(
            {"type": "http", "method": "GET", "path": path}, None, send
        )
    )
    counter.flush()
    (row,) = store.ops_rows("2000-01-01")
    assert (row["operation"], row["locale"], row["count"]) == ("pdf", locale, 1)


def test_retention_persists_first_failure_and_recovers_without_regression(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(
        store, "purge_expired", lambda *a, **kw: (_ for _ in ()).throw(OSError("secret"))
    )
    with pytest.raises(OSError):
        run_retention(store, retention_days=30, now=NOW)
    failed = store.ops_job()
    assert failed["error_code"] == "purge_failed" and failed["last_success_at"] is None
    assert retention_status(failed, enabled=True, at=NOW) == "failed"
    monkeypatch.setattr(store, "purge_expired", lambda *a, **kw: 3)
    later = NOW + timedelta(hours=1)
    assert run_retention(store, retention_days=30, now=later) == 3
    store.record_ops_job(at=NOW - timedelta(hours=1), success=False)
    recovered = store.ops_job()
    assert recovered["last_success_at"] == stamp(later)
    assert recovered["last_attempt_at"] == stamp(later)
    assert recovered["deleted_count"] == 3 and recovered["error_code"] == ""
    assert retention_status(recovered, enabled=True, at=later + timedelta(hours=36)) == "ok"
    assert (
        retention_status(recovered, enabled=True, at=later + timedelta(hours=36, seconds=1))
        == "overdue"
    )


def test_retention_health_write_failure_does_not_rollback_purge(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(store, "purge_expired", lambda *a, **kw: 2)
    monkeypatch.setattr(
        store, "record_ops_job", lambda **kw: (_ for _ in ()).throw(OSError("secret"))
    )
    assert run_retention(store, retention_days=30, now=NOW) == 2
    assert store.ops_job() is None


def test_operational_data_remains_private_and_does_not_change_health(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    app = _app(tmp_path)
    app.state.store.record_ops_job(at=NOW, success=False)
    app.state.operations.observe("pdf", "busy", 4, at=NOW)
    with TestClient(app) as client:
        for path in ("/health", "/ready", "/live", "/panel"):
            page = client.get(path)
            assert page.status_code == 200
            assert "purge_failed" not in page.text and "id='operations'" not in page.text
        assert client.post("/panel", data={"key": "wrong"}).status_code == 403
        page = client.post("/panel", data={"key": KEY})
        assert "id='operations'" in page.text and "purge_failed" in page.text
        assert page.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "1.001", "1e1000", "invalid"])
def test_cost_amount_cannot_round_or_accept_unbounded_values(amount) -> None:
    with pytest.raises(ValueError):
        amount_cents(amount)


def test_cost_persistence_failure_is_not_a_validation_error(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path)
    store = app.state.store
    today = datetime.now(UTC).date().isoformat()

    def unavailable(**values: Any) -> None:
        raise OSError("secret connection details")

    monkeypatch.setattr(store, "record_commercial_cost", unavailable)
    data = {
        "key": KEY,
        "action": "cost_record",
        "cost_start": today,
        "cost_end": today,
        "cost_scope": "all",
        "cost_category": "infrastructure",
        "cost_amount": "1.23",
        "cost_reference": "QA-cost",
    }
    with TestClient(app) as client:
        page = client.post("/panel", data=data)
        assert page.status_code == 200
        assert "No se pudo guardar el costo" in page.text
        assert "Revisa período" not in page.text and "secret connection" not in page.text
        assert "Costo observado guardado" not in page.text
        # Validation is before persistence, including malformed decimals.
        invalid = client.post("/panel", data={**data, "cost_amount": "invalid"})
        assert "Revisa período" in invalid.text
        assert "No se pudo guardar el costo" not in invalid.text
        monkeypatch.setattr(store, "ops_rows", lambda *a: (_ for _ in ()).throw(OSError()))
        hidden = client.post("/panel", data=data)
        assert "consulta de telemetría no disponible" in hidden.text
        assert "No se pudo guardar el costo" in hidden.text


def test_costs_require_exact_windows_explicit_zeros_and_authorized_operator(tmp_path) -> None:
    app = _app(tmp_path)
    now = datetime.now(UTC).date()
    start = (now - timedelta(days=29)).isoformat()
    end = now.isoformat()
    data = {
        "action": "cost_record",
        "cost_start": start,
        "cost_end": end,
        "cost_scope": "all",
        "cost_category": "infrastructure",
        "cost_amount": "12.34",
        "cost_reference": "INV-2026-10",
    }
    with TestClient(app) as client:
        assert client.post("/panel", data={"key": "wrong", **data}).status_code == 403
        assert app.state.store.commercial_cost_rows(start, end) == []
        for amount in ("12.34", "12.34", "13.00"):
            page = client.post("/panel", data={"key": KEY, **data, "cost_amount": amount})
            assert "Costo observado guardado" in page.text
            assert find_claims(page.text) == []
        rows = app.state.store.commercial_cost_rows(start, end)
        assert len(rows) == 1 and rows[0]["amount_usd_cents"] == 1300
        assert "NOT_MEASURED" in contribution(2900, 0, rows)
        for category in COST_CATEGORIES[1:]:
            client.post(
                "/panel", data={"key": KEY, **data, "cost_category": category, "cost_amount": "0"}
            )
        rows = app.state.store.commercial_cost_rows(start, end)
        assert "USD 16.00" in contribution(2900, 0, rows)
        assert "USD -17.00" in contribution(0, 400, rows)
        assert app.state.store.commercial_cost_rows(start, end, "x") == []
        invalid = client.post("/panel", data={"key": KEY, **data, "cost_amount": "4.001"})
        assert "Revisa período" in invalid.text
        corrected = app.state.store.commercial_cost_rows(start, end)
        assert (
            next(r for r in corrected if r["category"] == "infrastructure")["amount_usd_cents"]
            == 1300
        )


def test_x_cohort_uses_account_creation_first_touch_and_delivered_repeats(tmp_path) -> None:
    store = _store(tmp_path)
    accounts = []
    for index, (when, tag) in enumerate(
        [(NOW, "x-mx-01"), (NOW - timedelta(days=20), "x"), (NOW, "f6")]
    ):
        account = store.create_account(
            email=f"cohort-{index}@example.test", password_hash="unused", locale="es", at=when
        )
        assert account is not None
        store.set_account_ref(account.id, tag, at=when)
        accounts.append(account)
    store.set_account_ref(accounts[2].id, "x", at=NOW)  # first touch remains f6
    with store.engine.begin() as conn:
        conn.execute(
            store.verified_emails.insert().values(
                account_id=accounts[0].id, email=accounts[0].email, verified_at=stamp(NOW)
            )
        )
    for account, statuses in [
        (accounts[0], ["delivered", "delivered", "duplicate"]),
        (accounts[1], ["delivered"]),
        (accounts[2], ["delivered"]),
    ]:
        for index, status in enumerate(statuses):
            order = store.reserve_checkout(
                account_order_ref(account.id),
                account_id=account.id,
                plan="single",
                amount_cents=2900,
                currency="usd",
                at=NOW + timedelta(minutes=index),
            )
            with store.engine.begin() as conn:
                conn.execute(
                    store.checkout_orders.update()
                    .where(store.checkout_orders.c.id == order.id)
                    .values(
                        status=status,
                        confirmed_at=stamp(NOW),
                        livemode=True,
                        paid_amount_cents=2900,
                    )
                )
    counts = store.x_cohort_counts("2026-09-22", "2026-10-05")
    assert (
        counts["signups"],
        counts["email_verified"],
        counts["buyers"],
        counts["repeat_buyers"],
        counts["deliveries"],
    ) == (1, 1, 1, 1, 2)
    assert counts["gross_usd_cents"] == 8700  # duplicate is a charge, never a delivery
    assert "example.test" not in str(counts)


def test_email_confirmation_note_is_localized_and_conditional() -> None:
    english = (
        "Confirm your email to receive the first full report free. "
        "If required, you verify a card without a charge."
    )
    expected = {
        "es": spanish(english),
        "en": english,
        "pt": (
            "Confirme seu e-mail para receber o primeiro relatório completo grátis. "
            "Se necessário, valide um cartão sem cobrança."
        ),
    }
    for locale, note in expected.items():
        assert note is not None
        page = landing(locale=locale, email_confirmation=True)
        assert note in page and "welcome-confirmation" in page
        assert find_claims(page) == []
        assert "welcome-confirmation" not in landing(locale=locale, email_confirmation=False)
