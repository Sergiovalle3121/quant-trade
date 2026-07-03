from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quant_trade.cloud.exceptions import LockError


class LockRecord(BaseModel):
    lock_name: str
    owner_run_id: str
    acquired_at_utc: str
    expires_at_utc: str

    def expired(self) -> bool:
        exp = datetime.fromisoformat(self.expires_at_utc)
        exp = exp if exp.tzinfo else exp.replace(tzinfo=UTC)
        return exp <= datetime.now(UTC)


class LocalFileLock:
    def __init__(self, lock_dir: Path | str = "state/cloud/locks") -> None:
        self.lock_dir = Path(lock_dir)

    def _path(self, name: str) -> Path:
        return self.lock_dir / (name.replace("/", "_") + ".json")

    def acquire_lock(self, lock_name: str, owner_run_id: str, ttl_minutes: int) -> LockRecord:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(lock_name)
        if path.exists():
            old = LockRecord(**json.loads(path.read_text()))
            if not old.expired():
                raise LockError("lock already held")
        now = datetime.now(UTC)
        rec = LockRecord(
            lock_name=lock_name,
            owner_run_id=owner_run_id,
            acquired_at_utc=now.isoformat(),
            expires_at_utc=(now + timedelta(minutes=ttl_minutes)).isoformat(),
        )
        path.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
        return rec

    def release_lock(self, lock_name: str, owner_run_id: str) -> None:
        path = self._path(lock_name)
        if not path.exists():
            return
        rec = LockRecord(**json.loads(path.read_text()))
        if rec.owner_run_id != owner_run_id:
            raise LockError("lock owned by another run")
        path.unlink()

    def force_release_lock(self, lock_name: str) -> None:
        path = self._path(lock_name)
        if path.exists():
            path.unlink()


class DynamoDbLock:
    def __init__(self, table_name: str, client: Any | None = None) -> None:
        self.table_name = table_name
        self.client = client

    def acquire_lock(self, lock_name: str, owner_run_id: str, ttl_minutes: int) -> LockRecord:
        now = datetime.now(UTC)
        rec = LockRecord(
            lock_name=lock_name,
            owner_run_id=owner_run_id,
            acquired_at_utc=now.isoformat(),
            expires_at_utc=(now + timedelta(minutes=ttl_minutes)).isoformat(),
        )
        if self.client is None:
            raise LockError("DynamoDB client is required")
        self.client.put_item(
            TableName=self.table_name,
            Item={k: {"S": str(v)} for k, v in rec.model_dump().items()},
            ConditionExpression="attribute_not_exists(lock_name)",
        )
        return rec

    def release_lock(self, lock_name: str, owner_run_id: str) -> None:
        if self.client is None:
            raise LockError("DynamoDB client is required")
        self.client.delete_item(TableName=self.table_name, Key={"lock_name": {"S": lock_name}})

    def force_release_lock(self, lock_name: str) -> None:
        self.release_lock(lock_name, "force")
