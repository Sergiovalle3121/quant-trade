from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_trade.execution.safety import sanitize_raw_payload


def append_audit_event(
    audit_dir: Path | str,
    event_type: str,
    message: str,
    *,
    provider: str = "unknown",
    mode: str = "unknown",
    paper: bool = True,
    severity: str = "info",
    details: dict[str, Any] | None = None,
    actor: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    path = Path(audit_dir) / "broker_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event_id": str(uuid.uuid4()),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "severity": severity,
        "provider": provider,
        "mode": mode,
        "paper": paper,
        "message": message,
        "details": sanitize_raw_payload(details or {}),
        "actor": actor,
        "run_id": run_id,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return event
