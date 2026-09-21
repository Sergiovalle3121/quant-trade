"""Store: create, read, pay once, purge only what retention allows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from quant_trade.audit.store import make_store  # noqa: E402

NOW = datetime(2026, 1, 31, tzinfo=UTC)


def _store(tmp_path: Path):
    return make_store(f"sqlite:///{tmp_path}/nested/audit.db")


def _create(store, audit_id: str, *, at: datetime) -> None:
    store.create_audit(
        audit_id=audit_id,
        created_at=at,
        token_hash="h" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json=f'{{"audit_id": "{audit_id}"}}',
        report_html="<html></html>",
        overall_class="B",
        digests={"equity.csv": "e" * 64, "trades.csv": "t" * 64},
        equity_csv=b"timestamp,equity\n",
        trades_csv=b"x",
    )


def test_create_and_read_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, "a1", at=NOW)
    record = store.get_audit("a1", with_blobs=True)
    assert record is not None
    assert record.paid is False
    assert record.digests == {"equity.csv": "e" * 64, "trades.csv": "t" * 64}
    assert record.equity_csv == b"timestamp,equity\n"
    assert record.created_at == "2026-01-31T00:00:00Z"
    assert store.get_audit("missing") is None
    assert store.get_audit("a1").equity_csv is None  # blobs stay out unless asked


def test_mark_paid_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, "a1", at=NOW)
    assert store.mark_paid("a1", stripe_session_id="cs_1", at=NOW) is True
    assert store.mark_paid("a1", stripe_session_id="cs_2", at=NOW) is False
    assert store.mark_paid("nope", stripe_session_id="cs_3", at=NOW) is False
    record = store.get_audit("a1")
    assert record is not None and record.paid and record.stripe_session_id == "cs_1"


def test_rate_limit_counter_and_waitlist(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for index in range(3):
        _create(store, f"a{index}", at=NOW - timedelta(minutes=index * 20))
    assert store.count_uploads_since("1.2.3.4", NOW - timedelta(hours=1)) == 3
    assert store.count_uploads_since("1.2.3.4", NOW - timedelta(minutes=30)) == 2
    assert store.count_uploads_since("9.9.9.9", NOW - timedelta(hours=1)) == 0
    assert store.add_waitlist(" Ana@Example.com ", at=NOW) is True
    assert store.add_waitlist("ana@example.com", at=NOW) is False
    assert store.waitlist_emails() == ["ana@example.com"]


def test_purge_keeps_paid_and_recent_and_preserves_hashes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, "old_unpaid", at=NOW - timedelta(days=40))
    _create(store, "old_paid", at=NOW - timedelta(days=40))
    _create(store, "recent", at=NOW - timedelta(days=5))
    store.mark_paid("old_paid", stripe_session_id="cs", at=NOW)
    assert store.purge_expired(NOW, retention_days=30, dry_run=True) == 1
    assert store.get_audit("old_unpaid", with_blobs=True).equity_csv is not None
    assert store.purge_expired(NOW, retention_days=30) == 1
    purged = store.get_audit("old_unpaid", with_blobs=True)
    assert purged is not None
    assert purged.purged_at is not None
    assert purged.equity_csv is None and purged.report_html is None
    assert purged.result_json is None
    assert purged.digests["equity.csv"] == "e" * 64
    assert purged.overall_class == "B"
    assert store.get_audit("old_paid", with_blobs=True).equity_csv is not None
    assert store.get_audit("recent", with_blobs=True).equity_csv is not None
    assert store.purge_expired(NOW, retention_days=30) == 0
