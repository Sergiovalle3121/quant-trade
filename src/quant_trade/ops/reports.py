from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SECRET_KEYS = ("secret", "token", "key", "password", "credential", "webhook")


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id(prefix: str = "ops") -> str:
    return f"{prefix}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def to_plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(marker in key.lower() for marker in SECRET_KEYS)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        lower = value.lower()
        if any(marker in lower for marker in ("api_key=", "token=", "secret=", "password=")):
            return "[REDACTED]"
    return value


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(to_plain(data)), indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_md(path: Path, title: str, sections: dict[str, Any]) -> Path:
    lines = [f"# {title}", "", "Paper trading / dry-run only. No live trading.", ""]
    for heading, content in sections.items():
        body = (
            content if isinstance(content, str) else json.dumps(redact(to_plain(content)), indent=2)
        )
        lines += [f"## {heading}", "", body, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row}) or ["message"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows([{key: redact(row.get(key, "")) for key in keys} for row in rows])
    return path
