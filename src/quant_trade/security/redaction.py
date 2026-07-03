from __future__ import annotations

import json
import re
from typing import Any

SECRET_KEYS = re.compile(r"(secret|token|api[_-]?key|password|credential|bearer)", re.I)
SECRET_VALUE = re.compile(
    r"(AKIA[0-9A-Z]{16}|APCA-[A-Z0-9]{16,}|Bearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|[A-Za-z0-9_\-]{32,})"
)
ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|authorization)(\s*[:=]\s*)([^\s,'\"}]+)"
)
REDACTED = "[REDACTED]"


def redacted_preview(value: str) -> str:
    return "[REDACTED:" + str(len(value)) + "]"


def sanitize_text(text: str) -> str:
    return SECRET_VALUE.sub(REDACTED, ASSIGNMENT.sub(r"\1\2[REDACTED]", text))


def sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if SECRET_KEYS.search(str(key)):
            clean[key] = REDACTED
        elif isinstance(value, dict):
            clean[key] = sanitize_dict(value)
        elif isinstance(value, list):
            clean[key] = [
                sanitize_dict(x) if isinstance(x, dict) else sanitize_text(str(x)) for x in value
            ]
        elif isinstance(value, str):
            clean[key] = sanitize_text(value)
        else:
            clean[key] = value
    return clean


def sanitize_jsonl(text: str) -> str:
    out = []
    for line in text.splitlines():
        try:
            out.append(json.dumps(sanitize_dict(json.loads(line)), sort_keys=True))
        except json.JSONDecodeError:
            out.append(sanitize_text(line))
    return "\n".join(out)


def sanitize_report(text: str) -> str:
    return sanitize_text(text)
