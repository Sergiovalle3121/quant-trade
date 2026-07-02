from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_trade.paper.models import PaperEvent


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def create_event(
    timestamp: str,
    event_type: str,
    message: str,
    severity: str = "info",
    details: dict[str, Any] | None = None,
) -> PaperEvent:
    return PaperEvent(
        str(uuid.uuid4()), timestamp, event_type, severity, message, details or {}, utc_now_iso()
    )


def event_to_json(event: PaperEvent) -> str:
    return json.dumps(event.to_dict(), sort_keys=True)


def append_event(path: Path, event: PaperEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(event_to_json(event) + "\n")
