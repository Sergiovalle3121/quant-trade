"""Evidence report utilities."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any


def to_dict(model: Any) -> dict[str, Any]:
    return asdict(model)
