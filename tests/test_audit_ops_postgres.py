"""Opt-in PostgreSQL staging checks using disposable, synthetic databases.

Set QA_POSTGRES_URL to a PostgreSQL admin URL on 127.0.0.1 with database
``postgres``. Each test creates its own ``rigor_qa_*`` database and removes it
after closing all connections. No production URL or customer data is accepted.
QA_PG_BIN optionally points to pg_dump/pg_restore. QA_REPORT_DIR receives
counts, timings, hashes and synthetic report artifacts, never customer data
or credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

import pytest

sa = pytest.importorskip("sqlalchemy")
psycopg = pytest.importorskip("psycopg")
pytest.importorskip("fastapi")

from audit_fixtures import csv_bytes, positive_drift  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402

from quant_trade.audit.accounts import SESSION_COOKIE, hash_secret  # noqa: E402
from quant_trade.audit.payments import fulfil  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import Store, account_order_ref, make_store  # noqa: E402
from quant_trade.audit.web import REPORT_SIZE_FACTOR, create_app  # noqa: E402


def _admin_url() -> URL:
    value = os.environ.get("QA_POSTGRES_URL", "")
    if not value:
        pytest.skip("QA_POSTGRES_URL is unset; PostgreSQL checks are opt-in")
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or url.host != "127.0.0.1"
        or not url.port
        or url.database != "postgres"
    ):
        pytest.fail("QA_POSTGRES_URL must target 127.0.0.1:<explicit port>/postgres")
    return url.set(drivername="postgresql+psycopg")


def _dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture
def local_databases():
    admin = _admin_url()
    names: list[str] = []
    stores: list[Store] = []

    def create(*, initialise: bool = True) -> tuple[URL, Store | None]:
        name = "rigor_qa_" + uuid.uuid4().hex
        with psycopg.connect(_dsn(admin), autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        names.append(name)
        url = admin.set(database=name)
        store = make_store(url.render_as_string(hide_password=False)) if initialise else None
        if store is not None:
            stores.append(store)
        return url, store

    yield create
    for store in stores:
        store.engine.dispose()
    with psycopg.connect(_dsn(admin), autocommit=True) as conn:
        for name in names:
            # Names are generated above, and the admin endpoint is loopback only.
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _evidence(name: str, values: dict[str, Any]) -> None:
    directory = os.environ.get("QA_REPORT_DIR", "")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{name}.json").write_text(
            json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def _audit(store: Store, audit_id: str) -> None:
    data = b"timestamp,equity\n2026-01-01,10000\n2026-01-02,10001\n"
    store.create_audit(
        audit_id=audit_id,
        created_at=datetime.now(UTC),
        token_hash=hashlib.sha256(audit_id.encode()).hexdigest(),
        client_ip="127.0.0.1",
        declared_json="{}",
        result_json=json.dumps({"audit_id": audit_id}),
        report_html="<html><body>Synthetic staging report</body></html>",
        overall_class="B",
        digests={"equity.csv": hashlib.sha256(data).hexdigest()},
        equity_csv=data,
    )


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_postgres_same_counter_concurrent_upserts(local_databases, workers: int) -> None:
    _, store = local_databases()
    assert store is not None
    barrier = threading.Barrier(workers)

    def count(_: int) -> None:
        barrier.wait(timeout=30)
        for _ in range(25):
            store.count_ops(
                day="2026-10-05", locale="es", operation="audit", outcome="success", bucket_ms=500
            )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(count, range(workers)))
    rows = store.ops_rows("2026-10-05")
    assert len(rows) == 1 and rows[0]["count"] == workers * 25
    _evidence(
        f"postgres-counter-{workers}",
        {
            "workers": workers,
            "expected": workers * 25,
            "observed": rows[0]["count"],
            "lost_increments": 0,
        },
    )


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_postgres_credit_contention_loses_no_credits(local_databases, workers: int) -> None:
    _, store = local_databases()
    assert store is not None
    now = datetime.now(UTC)
    account = store.create_account(
        email="credits@example.test", password_hash="synthetic-unused", locale="es", at=now
    )
    assert account is not None
    _, code = store.create_access_code(credits=4, note="synthetic QA", at=now)
    store.link_code(account.id, code.id, at=now)
    ids = [f"credit{i}" for i in range(16)]
    for audit_id in ids:
        _audit(store, audit_id)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        unlocked = list(
            pool.map(lambda audit_id: store.redeem_with_account(audit_id, account.id, at=now), ids)
        )
    paid = sum(bool(store.get_audit(audit_id).paid) for audit_id in ids)
    assert sum(unlocked) == paid == 4
    assert store.account_credits(account.id, now) == 0
    # Duplicate retries must never consume credits for the same paid report.
    _, extra = store.create_access_code(credits=8, note="synthetic retries", at=now)
    store.link_code(account.id, extra.id, at=now)
    _audit(store, "duplicate")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        duplicates = list(
            pool.map(
                lambda _: store.redeem_with_account("duplicate", account.id, at=now), range(16)
            )
        )
    assert sum(duplicates) == 1
    assert store.account_credits(account.id, now) == 7
    _evidence(
        f"postgres-credit-{workers}",
        {
            "workers": workers,
            "contention_attempts": 16,
            "credits_available": 4,
            "paid_reports": paid,
            "duplicate_attempts": 16,
            "duplicate_unlocks": 1,
            "remaining_credits": 7,
            "credits_lost": 0,
        },
    )


def _snapshot(store: Store) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    with store.engine.connect() as conn:
        for name, table in sorted(store.metadata.tables.items()):
            statement = sa.select(table).order_by(*list(table.primary_key.columns))
            rows = [dict(row) for row in conn.execute(statement).mappings()]
            content = json.dumps(rows, sort_keys=True, default=lambda value: value.hex())
            snapshot[name] = {
                "rows": len(rows),
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
    return snapshot


def test_postgres_additive_schema_preserves_populated_existing_tables(local_databases) -> None:
    url, store = local_databases()
    assert store is not None
    _audit(store, "existing-before-upgrade")
    now = datetime.now(UTC)
    account = store.create_account(
        email="upgrade@example.test", password_hash="synthetic-unused", locale="es", at=now
    )
    assert account is not None
    _, code = store.create_access_code(credits=3, note="synthetic upgrade", at=now)
    store.link_code(account.id, code.id, at=now)
    new_tables = {"ops_counters", "ops_jobs", "commercial_costs"}
    before = {name: rows for name, rows in _snapshot(store).items() if name not in new_tables}
    # Simulate the old schema in this disposable database, then restart Store.
    with store.engine.begin() as conn:
        for name in new_tables:
            store.metadata.tables[name].drop(conn)
    upgraded = make_store(url.render_as_string(hide_password=False))
    try:
        after = _snapshot(upgraded)
        assert {name: rows for name, rows in after.items() if name not in new_tables} == before
        assert new_tables.issubset(after)
        assert all(after[name]["rows"] == 0 for name in new_tables)
        assert upgraded.account_credits(account.id, now) == 3
        _evidence(
            "postgres-schema-upgrade",
            {
                "existing_tables_unchanged": len(before),
                "new_tables": sorted(new_tables),
                "credits_preserved": 3,
                "report_preserved": True,
            },
        )
    finally:
        upgraded.engine.dispose()


def _pg_tool(name: str, url: URL, *arguments: str) -> None:
    folder = os.environ.get("QA_PG_BIN", "")
    executable = Path(folder) / (name + (".exe" if os.name == "nt" else ""))
    if not folder or not executable.is_file():
        pytest.skip("QA_PG_BIN is required for real pg_dump/pg_restore checks")
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    result = subprocess.run(
        [
            str(executable),
            "--host",
            "127.0.0.1",
            "--port",
            str(url.port),
            "--username",
            str(url.username),
            "--dbname",
            str(url.database),
            *arguments,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stderr


def test_postgres_dump_restore_preserves_synthetic_ledger_and_session(
    local_databases, tmp_path: Path
) -> None:
    source_url, source = local_databases()
    target_url, _ = local_databases(initialise=False)
    assert source is not None
    now = datetime.now(UTC)
    account = source.create_account(
        email="restore@example.test", password_hash="synthetic-unused", locale="es", at=now
    )
    assert account is not None
    token = uuid.uuid4().hex + uuid.uuid4().hex
    source.create_session(
        account.id, token_sha256=hash_secret(token), csrf="synthetic-csrf", at=now, days=30
    )
    settings = AuditSettings(
        database_url=source_url.render_as_string(hide_password=False),
        free_mode=False,
        access_codes=True,
        stripe_secret_key="sk_live_synthetic_never_sent",
        stripe_webhook_secret="whsec_synthetic_never_sent",
        approved_markets=frozenset({"MX"}),
    )
    order = source.reserve_checkout(
        account_order_ref(account.id),
        account_id=account.id,
        plan="pack",
        amount_cents=6900,
        currency="usd",
        at=now,
        declared_country="MX",
        locale="es",
    )
    session_id = "cs_live_synthetic_restore"
    source.attach_checkout_session(
        order.id,
        session_id=session_id,
        checkout_url="https://checkout.stripe.test/synthetic",
        expires_at=now + timedelta(hours=1),
    )
    session = {
        "id": session_id,
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": 6900,
        "customer_details": {"address": {"country": "MX"}},
        "metadata": {
            "app": "rigor",
            "account_id": account.id,
            "order_id": order.id,
            "plan": "pack",
        },
    }
    # Stripe settlement is synthetic and entirely in-process: no HTTP request.
    assert fulfil(source, settings, session, at=now) == account_order_ref(account.id)
    assert fulfil(source, settings, session, at=now) == account_order_ref(account.id)
    assert source.account_credits(account.id, now) == 3
    _audit(source, "restore-report")
    source.link_audit(account.id, "restore-report", via="upload", at=now)
    assert source.redeem_with_account("restore-report", account.id, at=now)
    source.count_ops(
        day="2026-10-05", locale="es", operation="audit", outcome="success", bucket_ms=500
    )
    source.record_ops_job(at=now, success=True, deleted_count=0)
    before = _snapshot(source)
    archive = tmp_path / "synthetic.dump"
    started = time.perf_counter()
    _pg_tool("pg_dump", source_url, "--format=custom", "--file", str(archive))
    _pg_tool(
        "pg_restore",
        target_url,
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-privileges",
        str(archive),
    )
    restored = make_store(target_url.render_as_string(hide_password=False))
    try:
        assert _snapshot(restored) == before
        assert restored.account_credits(account.id, now) == 2
        assert restored.get_checkout_order(order.id).status == "delivered"
        assert restored.get_audit("restore-report", with_blobs=True).equity_csv is not None
        with TestClient(
            create_app(AuditSettings(database_url=str(target_url)), restored)
        ) as client:
            client.cookies.set(SESSION_COOKIE, token)
            assert client.get("/cuenta", follow_redirects=False).status_code == 200
        _evidence(
            "postgres-restore",
            {
                "all_tables_equal": True,
                "tables_checked": len(before),
                "row_counts": {name: values["rows"] for name, values in before.items()},
                "credits_remaining": 2,
                "session_restored": True,
                "order_restored": True,
                "report_blob_restored": True,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "archive_bytes": archive.stat().st_size,
                "external_stripe_requests": 0,
                "emails_sent": 0,
                "environment": "local PostgreSQL; not Railway",
            },
        )
    finally:
        restored.engine.dispose()


def _padded_csv(data: bytes, size: int) -> bytes:
    assert len(data) <= size
    blocks, tail = divmod(size - len(data), 81)
    return data + (b" " * 80 + b"\n") * blocks + b" " * tail


def _load_quotas(total: int) -> dict[int, int]:
    assert 15 <= total <= 500
    quotas = {level: level for level in (1, 2, 4, 8)}
    extra = total - 15
    for level in quotas:
        quotas[level] += extra * level // 15
    quotas[8] += total - sum(quotas.values())
    return quotas


def test_postgres_bounded_upload_load_1_2_4_8(local_databases, tmp_path: Path) -> None:
    import httpx

    total = int(os.environ.get("QA_UPLOAD_COUNT", "15"))
    extended = os.environ.get("QA_EXTENDED_STAGING") == "true"
    require_pdf = os.environ.get("QA_REQUIRE_PDF") == "true"
    bootstrap = int(os.environ.get("QA_BOOTSTRAP_SAMPLES", "100"))
    slots = int(os.environ.get("QA_AUDIT_SLOTS", "2"))
    assert 100 <= bootstrap <= 10000 and 1 <= slots <= 8
    quotas = _load_quotas(total)
    url, store = local_databases()
    assert store is not None
    settings = AuditSettings(
        database_url=url.render_as_string(hide_password=False),
        bootstrap_samples=bootstrap,
        free_mode=False,
        access_codes=True,
        max_uploads_per_hour_per_ip=max(100, total + 10),
        max_concurrent_audits=slots,
        audit_queue_seconds=30,
    )
    app = create_app(settings, store)

    def external_forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("staging must not contact Stripe or email services")

    app.state.checkout_factory = external_forbidden
    app.state.account_checkout_factory = external_forbidden
    app.state.card_check_factory = external_forbidden
    app.state.mail_domain_check = lambda _: True
    data = _padded_csv(csv_bytes(positive_drift(400)), 20 * 1024)
    size_payloads = (
        (data, _padded_csv(data, 1024 * 1024), _padded_csv(data, settings.max_upload_bytes))
        if extended
        else (data,)
    )
    now = datetime.now(UTC)
    code, _ = store.create_access_code(credits=total + 10, note="synthetic load", at=now)

    async def run() -> dict[str, Any]:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            page = await client.get("/registro")
            import re

            csrf = re.search(r"name='csrf' value='([^']+)'", page.text)
            assert csrf is not None
            response = await client.post(
                "/registro",
                data={
                    "email": "load@example.test",
                    "password": "synthetic staging password",
                    "csrf": csrf.group(1),
                },
            )
            assert response.status_code == 303
            account = store.find_account("load@example.test")
            assert account is not None
            store.spend_welcome(account.id, at=now)
            store.link_code(account.id, store.code_id(code), at=now)
            evidence: list[dict[str, Any]] = []
            locations: list[str] = []
            sent_count = 0
            for concurrency, requests in quotas.items():

                async def upload(index: int) -> tuple[int, float, str]:
                    payload = size_payloads[index] if index < len(size_payloads) else data
                    start = time.perf_counter()
                    result = await client.post(
                        "/audits",
                        files={"equity": ("equity.csv", payload, "text/csv")},
                        data={
                            "trials": "3",
                            "cost_bps": "5",
                            "consent": "on",
                            "access_code": code,
                        },
                    )
                    return (
                        result.status_code,
                        time.perf_counter() - start,
                        result.headers.get("location", ""),
                    )

                results: list[tuple[int, float, str]] = []
                for batch_start in range(0, requests, concurrency):
                    batch = min(concurrency, requests - batch_start)
                    results.extend(
                        await asyncio.gather(
                            *(upload(sent_count + index) for index in range(batch))
                        )
                    )
                    sent_count += batch
                assert [status for status, _, _ in results] == [303] * requests
                timings = sorted(duration for _, duration, _ in results)
                for _, _, location in results:
                    assert location.startswith("/audits/")
                    report = await client.get(location)
                    assert report.status_code == 200
                    audit_id = location.split("/audits/", 1)[1].split("?", 1)[0]
                    record = store.get_audit(audit_id, with_blobs=True)
                    assert record is not None and record.paid and record.report_html
                    assert record.equity_csv is not None
                    locations.append(location)
                evidence.append(
                    {
                        "concurrency": concurrency,
                        "requests": requests,
                        "successes": requests,
                        "internal_errors": 0,
                        "p50_seconds": round(median(timings), 3),
                        "p95_seconds": round(timings[math.ceil(len(timings) * 0.95) - 1], 3),
                        "latency_seconds": [round(duration, 3) for duration in timings],
                    }
                )
            assert store.get_access_code(code).credits_used == total
            assert store.account_credits(account.id, now) == 10
            assert store.count_audits() == total
            rejection_checks: list[dict[str, Any]] = []
            if extended:

                async def rejected(who: Any, name: str, payload: bytes, expected: int) -> None:
                    before = store.account_credits(account.id, now)
                    result = await who.post(
                        "/audits",
                        files={"equity": ("equity.csv", payload, "text/csv")},
                        data={
                            "trials": "3",
                            "cost_bps": "5",
                            "consent": "on",
                            "access_code": code,
                        },
                    )
                    assert result.status_code == expected
                    assert store.account_credits(account.id, now) == before
                    assert store.count_audits() == total
                    rejection_checks.append(
                        {
                            "case": name,
                            "status": result.status_code,
                            "credits_consumed": 0,
                            "bytes": len(payload),
                        }
                    )

                await rejected(client, "invalid_csv", b"bad_header\nnot_equity\n", 400)
                # Equity can also carry a platform report. The CSV reader's
                # own limit rejects with 400; the larger form limit uses 413.
                await rejected(client, "over_csv_limit", size_payloads[-1] + b"x", 400)
                await rejected(
                    client,
                    "over_equity_form_limit",
                    _padded_csv(data, settings.max_upload_bytes * REPORT_SIZE_FACTOR) + b"x",
                    413,
                )
                admission = app.state.upload_admission_slots
                held = 0
                while admission.acquire(blocking=False):
                    held += 1
                try:
                    await rejected(client, "admission_saturated", data, 503)
                finally:
                    for _ in range(held):
                        admission.release()

                busy_app = create_app(replace(settings, audit_queue_seconds=1), store)
                busy_app.state.checkout_factory = external_forbidden
                busy_app.state.account_checkout_factory = external_forbidden
                borrowers = [object() for _ in range(slots)]
                for borrower in borrowers:
                    await busy_app.state.audit_slots.acquire_on_behalf_of(borrower)
                try:
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=busy_app),
                        base_url="http://testserver",
                        cookies=client.cookies,
                    ) as busy_client:
                        await rejected(busy_client, "analysis_queue_timeout", data, 503)
                finally:
                    for borrower in borrowers:
                        busy_app.state.audit_slots.release_on_behalf_of(borrower)
                    busy_app.state.operations.flush()

            pdf_evidence: dict[str, Any] = {"tested": False}
            if require_pdf:
                report_path, query = locations[0].split("?", 1)
                pdf = await client.get(report_path + "/pdf?" + query)
                assert pdf.status_code == 200
                assert pdf.content.startswith(b"%PDF-") and len(pdf.content) > 1000
                digest = hashlib.sha256(pdf.content).hexdigest()
                assert store.find_issued(digest) is not None
                directory = Path(os.environ.get("QA_REPORT_DIR", str(tmp_path)))
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "synthetic-real-report.pdf").write_bytes(pdf.content)
                pdf_evidence = {
                    "tested": True,
                    "status": pdf.status_code,
                    "bytes": len(pdf.content),
                    "sha256": digest,
                    "mocked": False,
                }
            app.state.operations.flush()
            counters = store.ops_rows(now.date().isoformat())
            uploads = sum(row["count"] for row in counters if row["operation"] == "upload")
            audits = sum(row["count"] for row in counters if row["operation"] == "audit")
            upload_successes = sum(
                row["count"]
                for row in counters
                if row["operation"] == "upload" and row["outcome"] == "success"
            )
            audit_successes = sum(
                row["count"]
                for row in counters
                if row["operation"] == "audit" and row["outcome"] == "success"
            )
            assert upload_successes == audit_successes == total
            assert uploads == total + len(rejection_checks)
            assert audits >= total
            assert not any(row["outcome"] == "error" for row in counters)
            restore_evidence: dict[str, Any] = {"tested": False}
            if extended:
                # Keep a synthetic paid order and its idempotent credit grant
                # alongside the real reports in the same restore exercise.
                payment_settings = replace(
                    settings,
                    stripe_secret_key="sk_live_synthetic_never_sent",
                    stripe_webhook_secret="whsec_synthetic_never_sent",
                    approved_markets=frozenset({"MX"}),
                )
                order = store.reserve_checkout(
                    account_order_ref(account.id),
                    account_id=account.id,
                    plan="pack",
                    amount_cents=6900,
                    currency="usd",
                    at=now,
                    declared_country="MX",
                    locale="es",
                )
                session_id = "cs_live_synthetic_staging_pack"
                store.attach_checkout_session(
                    order.id,
                    session_id=session_id,
                    checkout_url="https://checkout.stripe.test/synthetic",
                    expires_at=now + timedelta(hours=1),
                )
                session = {
                    "id": session_id,
                    "payment_status": "paid",
                    "livemode": True,
                    "currency": "usd",
                    "amount_total": 6900,
                    "customer_details": {"address": {"country": "MX"}},
                    "metadata": {
                        "app": "rigor",
                        "account_id": account.id,
                        "order_id": order.id,
                        "plan": "pack",
                    },
                }
                assert fulfil(store, payment_settings, session, at=now) == account_order_ref(
                    account.id
                )
                assert fulfil(store, payment_settings, session, at=now) == account_order_ref(
                    account.id
                )
                assert store.account_credits(account.id, now) == 13
                # Back up real reports produced above, including the original uploaded bytes.
                before = _snapshot(store)
                target_url, _ = local_databases(initialise=False)
                archive = tmp_path / "real-synthetic-reports.dump"
                started = time.perf_counter()
                _pg_tool("pg_dump", url, "--format=custom", "--file", str(archive))
                _pg_tool(
                    "pg_restore",
                    target_url,
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-privileges",
                    str(archive),
                )
                restored = make_store(target_url.render_as_string(hide_password=False))
                try:
                    assert _snapshot(restored) == before
                    assert restored.account_credits(account.id, now) == 13
                    assert restored.get_checkout_order(order.id).status == "delivered"
                    restore_app = create_app(
                        replace(
                            settings, database_url=target_url.render_as_string(hide_password=False)
                        ),
                        restored,
                    )
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=restore_app),
                        base_url="http://testserver",
                        cookies=client.cookies,
                    ) as restored_client:
                        assert (await restored_client.get("/cuenta")).status_code == 200
                        assert (await restored_client.get(locations[0])).status_code == 200
                    audit_id = locations[0].split("/audits/", 1)[1].split("?", 1)[0]
                    record = restored.get_audit(audit_id, with_blobs=True)
                    original = store.get_audit(audit_id, with_blobs=True)
                    assert record.report_html == original.report_html
                    assert record.equity_csv == original.equity_csv
                    html_bytes = record.report_html.encode("utf-8")
                    directory = Path(os.environ.get("QA_REPORT_DIR", str(tmp_path)))
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "restored-synthetic-report.html").write_bytes(html_bytes)
                    restore_evidence = {
                        "tested": True,
                        "tables_equal": len(before),
                        "reports_restored": total,
                        "remaining_credits": 13,
                        "session_restored": True,
                        "synthetic_paid_order_restored": True,
                        "pack_credits_added_once": 3,
                        "original_upload_bytes_equal": True,
                        "html_bytes": len(html_bytes),
                        "html_sha256": hashlib.sha256(html_bytes).hexdigest(),
                        "archive_bytes": archive.stat().st_size,
                        "duration_seconds": round(time.perf_counter() - started, 3),
                    }
                finally:
                    restored.engine.dispose()
            return {
                "levels": evidence,
                "rejections": rejection_checks,
                "pdf": pdf_evidence,
                "real_report_restore": restore_evidence,
            }

    measured = asyncio.run(run())
    _evidence(
        "postgres-load",
        {
            **measured,
            "uploads": total,
            "reports": total,
            "credits_lost": 0,
            "internal_errors": 0,
            "bootstrap_samples": bootstrap,
            "rows_per_upload": 400,
            "tested_file_bytes": [len(payload) for payload in size_payloads],
            "file_padding": "blank whitespace rows; not additional observations",
            "csv_limit_bytes": settings.max_upload_bytes,
            "equity_form_limit_bytes": settings.max_upload_bytes * REPORT_SIZE_FACTOR,
            "max_concurrent_audits": slots,
            "queue_seconds": 30,
            "external_stripe_requests": 0,
            "emails_sent": 0,
            "pdf_rendering_tested": require_pdf,
            "environment": "local PostgreSQL, in-process ASGI; not Railway or a capacity guarantee",
        },
    )
