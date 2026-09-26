"""The continuous track record's store hooks: inert while its tables are empty.

Every test runs on SQLite and, when ``RIGOR_TEST_PG_URL`` names a PostgreSQL
database (a throwaway one: its tables are dropped), on PostgreSQL too, since
the hooks run inside the store's own transactions.
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quant_trade.audit import forensics_web, store_hooks, track_seal_pages
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import VIA_UPLOAD, Store, make_store

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
PG_URL = os.environ.get("RIGOR_TEST_PG_URL", "")
BACKENDS = ["sqlite", "postgresql"] if PG_URL else ["sqlite"]


@pytest.fixture(params=BACKENDS)
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Store:
    if request.param == "sqlite":
        return make_store(f"sqlite:///{tmp_path}/audit.db")
    built = make_store(PG_URL)
    built.metadata.drop_all(built.engine)
    built.metadata.create_all(built.engine)
    return built


def _create(store: Store, audit_id: str, *, at: datetime = NOW) -> None:
    store.create_audit(
        audit_id=audit_id,
        created_at=at,
        token_hash="h" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json=f'{{"audit_id": "{audit_id}"}}',
        report_html="<html></html>",
        overall_class="B",
        digests={"equity.csv": "e" * 64},
        equity_csv=b"timestamp,equity\n",
    )


def _account(store: Store, email: str) -> str:
    account = store.create_account(email=email, password_hash="x", locale="es", at=NOW)
    assert account is not None
    return account.id


def _seal(
    store: Store,
    account_id: str | None,
    *,
    audit_id: str | None = None,
    status: str = store_hooks.STATUS_OPEN,
    published_since: str | None = None,
    ended_at: str | None = None,
) -> str:
    seal_id = secrets.token_urlsafe(16)
    with store.engine.begin() as conn:
        conn.execute(
            store.track_seals.insert().values(
                id=seal_id,
                public_id=secrets.token_urlsafe(9),
                account_id=account_id,
                opened_at="2026-09-01T00:00:00Z",
                status=status,
                source_format="mt5_history_html",
                currency="USD",
                method_version="1",
                recipe_version="1",
                upload_count=1,
                head_hash="a" * 64,
                published_since=published_since,
                published=published_since is not None,
                ended_at=ended_at,
            )
        )
        conn.execute(
            store.track_seal_uploads.insert().values(
                id=secrets.token_urlsafe(16),
                seal_id=seal_id,
                position=0,
                at="2026-09-01T00:00:00Z",
                audit_id=audit_id,
                source_format="mt5_history_html",
                cutoff="2026-08-31T00:00:00Z",
                closed_count=10,
                flow_count=1,
                currency="USD",
                trades_sha256="b" * 64,
                previous_hash="",
                hash="a" * 64,
                recipe_version="1",
                entry_json="{}",
            )
        )
        conn.execute(
            store.track_seal_events.insert().values(
                id=secrets.token_urlsafe(16),
                seal_id=seal_id,
                at="2026-09-01T00:00:00Z",
                kind="opened",
                count=0,
                detail_json="",
            )
        )
    return seal_id


def _count(store: Store, table, **where) -> int:
    sa = store._sa
    query = sa.select(sa.func.count()).select_from(table)
    for key, value in where.items():
        query = query.where(getattr(table.c, key) == value)
    with store.engine.connect() as conn:
        return int(conn.execute(query).scalar() or 0)


def _seal_row(store: Store, seal_id: str):
    with store.engine.connect() as conn:
        return (
            conn.execute(
                store._sa.select(store.track_seals).where(store.track_seals.c.id == seal_id)
            )
            .mappings()
            .first()
        )


def test_tables_exist_and_start_empty(store: Store) -> None:
    for table in (
        store.track_seals,
        store.track_seal_uploads,
        store.track_seal_events,
        store.track_seal_quota,
    ):
        assert _count(store, table) == 0
    columns = {column.name for column in store.track_seals.columns}
    assert {"published_since", "withdrawn_at", "holder_confirmed_at", "publish_hash"} <= columns
    assert not any("account_number" in column.name for column in store.track_seals.columns)


def test_delete_export_and_purge_unchanged_while_empty(store: Store) -> None:
    account_id = _account(store, "a@example.com")
    _create(store, "own")
    _create(store, "old", at=NOW - timedelta(days=40))
    store.link_audit(account_id, "own", at=NOW, via=VIA_UPLOAD)
    assert store.delete_audit("own") is True
    assert store.delete_audit("own") is False
    export = store.account_export(account_id)
    assert export is not None and export["track_records"] == []
    assert store.purge_expired(NOW, retention_days=30, dry_run=True) == 1
    assert store.purge_expired(NOW, retention_days=30) == 1
    assert store.purge_expired(NOW, retention_days=30) == 0
    _create(store, "mine")
    store.link_audit(account_id, "mine", at=NOW, via=VIA_UPLOAD)
    assert store.delete_account(account_id, with_reports=True) == ["mine"]
    assert store.get_account(account_id) is None
    assert store.get_audit("mine") is None


def test_deleting_a_linked_report_ends_the_seal_with_an_event(store: Store) -> None:
    account_id = _account(store, "b@example.com")
    _create(store, "link")
    seal_id = _seal(store, account_id, audit_id="link")
    other = _seal(store, account_id, audit_id=None)
    assert store.delete_audit("link") is True
    row = _seal_row(store, seal_id)
    assert row is not None
    assert row["status"] == store_hooks.STATUS_ENDED
    assert row["ended_reason"] == store_hooks.ENDED_REPORT_DELETED
    assert row["ended_at"] is not None
    assert _count(store, store.track_seal_uploads, seal_id=seal_id, audit_id=None) == 1
    assert _count(store, store.track_seal_events, seal_id=seal_id, kind="ended") == 1
    untouched = _seal_row(store, other)
    assert untouched is not None and untouched["status"] == store_hooks.STATUS_OPEN
    # Ending is idempotent: a second deletion of another link adds nothing.
    with store.engine.begin() as conn:
        assert store_hooks.end_seals(store, conn, [seal_id], reason="holder", now=NOW) == []


def test_deleting_the_account_withdraws_its_seals(store: Store) -> None:
    account_id = _account(store, "c@example.com")
    stranger = _account(store, "d@example.com")
    public = _seal(store, account_id, published_since="2026-09-02T00:00:00Z")
    private = _seal(store, account_id)
    theirs = _seal(store, stranger)
    with store.engine.begin() as conn:
        conn.execute(store.track_seal_quota.insert().values(account_id=account_id, opened=2))
    store.delete_account(account_id)
    assert _seal_row(store, private) is None
    tomb = _seal_row(store, public)
    assert tomb is not None
    assert tomb["status"] == store_hooks.STATUS_WITHDRAWN
    assert tomb["account_id"] is None and tomb["withdrawn_at"] is not None
    assert tomb["published"] is False and tomb["published_since"] is not None
    assert tomb["head_hash"] == "" and tomb["sealed_json"] is None
    assert _count(store, store.track_seal_uploads, seal_id=public) == 0
    assert _count(store, store.track_seal_events, seal_id=public) == 0
    assert _count(store, store.track_seal_quota, account_id=account_id) == 0
    kept = _seal_row(store, theirs)
    assert kept is not None and kept["account_id"] == stranger
    assert _count(store, store.track_seal_uploads, seal_id=theirs) == 1


def test_purge_drops_only_ended_unpublished_seals_past_the_window(store: Store) -> None:
    account_id = _account(store, "e@example.com")
    stale = _seal(
        store, account_id, status=store_hooks.STATUS_ENDED, ended_at="2026-07-01T00:00:00Z"
    )
    fresh = _seal(
        store, account_id, status=store_hooks.STATUS_ENDED, ended_at="2026-09-20T00:00:00Z"
    )
    public = _seal(
        store,
        account_id,
        status=store_hooks.STATUS_ENDED,
        ended_at="2026-07-01T00:00:00Z",
        published_since="2026-06-01T00:00:00Z",
    )
    open_seal = _seal(store, account_id)
    store.purge_expired(NOW, retention_days=30)
    assert _seal_row(store, stale) is None
    assert _count(store, store.track_seal_uploads, seal_id=stale) == 0
    assert _count(store, store.track_seal_events, seal_id=stale) == 0
    for seal_id in (fresh, public, open_seal):
        assert _seal_row(store, seal_id) is not None
        assert _count(store, store.track_seal_uploads, seal_id=seal_id) == 1
    # A dry run touches nothing.
    stale2 = _seal(
        store, account_id, status=store_hooks.STATUS_ENDED, ended_at="2026-07-01T00:00:00Z"
    )
    store.purge_expired(NOW, retention_days=30, dry_run=True)
    assert _seal_row(store, stale2) is not None


def test_export_lists_the_seals_without_files(store: Store) -> None:
    account_id = _account(store, "f@example.com")
    _create(store, "src")
    seal_id = _seal(store, account_id, audit_id="src")
    export = store.account_export(account_id)
    assert export is not None
    (record,) = export["track_records"]
    assert record["id"] == seal_id and record["status"] == "open"
    assert record["uploads"][0]["report"] == "src"
    assert record["uploads"][0]["closed_operations"] == 10
    assert record["events"] == [{"at": "2026-09-01T00:00:00Z", "kind": "opened", "operations": 0}]
    assert "snapshot_json" not in str(record)
    assert "account_number" not in str(record)


def test_switches_are_off_and_nothing_is_mounted(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.web import create_app

    assert forensics_web.FORENSICS_ENABLED is False
    assert track_seal_pages.TRACK_SEAL_ENABLED is False
    assert track_seal_pages.TRACK_SEAL_PUBLIC_ENABLED is False
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    for path in (
        "/audits/abc/coherencia",
        "/cuenta/historiales",
        "/account/records",
        "/pt/conta/historicos",
        "/historial/ejemplo",
        "/historial/abc",
        "/coherencia/ejemplo",
        "/panel/historiales",
    ):
        assert client.get(path).status_code == 404, path
    assert "/health" in {route.path for route in client.app.routes}
