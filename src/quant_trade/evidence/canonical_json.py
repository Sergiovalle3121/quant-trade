"""Canonical JSON serialization and atomic, hash-stable artifact writes.

Evidence artifacts must be REAL JSON (never YAML behind a ``.json`` name),
byte-stable for hashing (sorted keys, fixed separators), and free of silent
corruption (no NaN/Infinity, atomic replace so a crash never leaves a torn
file). Every consumer that trusts an artifact can therefore re-hash the exact
bytes it read.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def canonical_dumps(obj: Any) -> str:
    """Deterministic JSON: sorted keys, fixed separators, NaN/Infinity rejected.

    Two semantically equal payloads always produce byte-identical output, so
    SHA-256 of the text is a stable content address.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_stringify_unknown,
    )


def _stringify_unknown(value: Any) -> str:
    # Paths, datetimes, Decimals, enums: stable string form. Anything exotic
    # becomes an explicit string rather than a serialization crash — but NaN
    # and Infinity still raise via allow_nan=False before reaching here.
    return str(value)


def pretty_dumps(obj: Any) -> str:
    """Human-readable variant (still real JSON, still NaN-free, sorted keys)."""
    return json.dumps(
        obj, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False,
        default=_stringify_unknown,
    )


def sha256_of_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_of_text(text: str) -> str:
    return sha256_of_bytes(text.encode("utf-8"))


def sha256_of_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: str | Path, text: str) -> Path:
    """Write via a temp file + ``os.replace`` so readers never see a torn file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return target


def atomic_write_json(path: str | Path, obj: Any, *, pretty: bool = True) -> Path:
    """Atomically write real JSON. Returns the path written."""
    text = pretty_dumps(obj) if pretty else canonical_dumps(obj)
    return atomic_write_text(path, text + ("\n" if pretty else ""))


def load_json(path: str | Path) -> Any:
    """Strict JSON load — no YAML fallback, no silent recovery."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
