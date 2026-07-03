"""Deterministic local content hashes; no secrets or external signing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def approval_hash(payload: dict[str, Any]) -> str:
    clean = {k: v for k, v in payload.items() if k != "content_hash"}
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
