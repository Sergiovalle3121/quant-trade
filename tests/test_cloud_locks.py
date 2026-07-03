from datetime import UTC, datetime, timedelta

import pytest

from quant_trade.cloud.exceptions import LockError
from quant_trade.cloud.locks import DynamoDbLock, LocalFileLock, LockRecord


def test_local_lock(tmp_path):
    lock = LocalFileLock(tmp_path)
    r = lock.acquire_lock("x", "run", 1)
    assert r.owner_run_id == "run"
    lock.release_lock("x", "run")


def test_overlap_rejected(tmp_path):
    lock = LocalFileLock(tmp_path)
    lock.acquire_lock("x", "a", 1)
    with pytest.raises(LockError):
        lock.acquire_lock("x", "b", 1)


def test_expired_replaced(tmp_path):
    lock = LocalFileLock(tmp_path)
    p = lock._path("x")
    p.parent.mkdir(exist_ok=True)
    p.write_text(
        LockRecord(
            lock_name="x",
            owner_run_id="old",
            acquired_at_utc="t",
            expires_at_utc=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        ).model_dump_json()
    )
    assert lock.acquire_lock("x", "new", 1).owner_run_id == "new"


def test_dynamo_mock():
    class C:
        def put_item(self, **kw):
            self.kw = kw

        def delete_item(self, **kw):
            self.deleted = kw

    c = C()
    assert DynamoDbLock("t", c).acquire_lock("x", "r", 1).lock_name == "x"
