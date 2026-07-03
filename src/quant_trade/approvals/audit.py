from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SECRET_MARKERS = ("secret", "token", "api_key", "password", "credential")


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if any(marker in key.lower() for marker in SECRET_MARKERS):
            out[key] = "[REDACTED]"
        else:
            out[key] = value
    return out


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sanitize(payload), sort_keys=True, default=str) + "\n")
