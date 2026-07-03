from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from quant_trade.cloud.storage import StorageBackend


class Heartbeat(BaseModel):
    deployment_name: str
    job_name: str
    run_id: str
    status: str
    started_at_utc: str
    completed_at_utc: str | None = None
    last_update_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    git_sha: str | None = None
    image_tag: str | None = None
    mode: str
    broker_provider: str
    paper_submission_enabled: bool
    kill_switch_active: bool
    summary: dict[str, Any] = Field(default_factory=dict)


def write_heartbeat(storage: StorageBackend, uri: str, heartbeat: Heartbeat) -> None:
    storage.write_json(uri, heartbeat.model_dump(mode="json"))


def read_heartbeat(storage: StorageBackend, uri: str) -> Heartbeat:
    return Heartbeat(**storage.read_json(uri))


def is_stale(heartbeat: Heartbeat, threshold_minutes: int) -> bool:
    try:
        last = datetime.fromisoformat(heartbeat.last_update_utc)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last).total_seconds() > threshold_minutes * 60
