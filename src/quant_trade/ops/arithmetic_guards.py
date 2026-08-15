"""Shared input guards for fail-closed, hash-bound arithmetic modules.

Every helper here separates *absent* input (which makes a result
``INSUFFICIENT_EVIDENCE``) from *invalid* input (which makes it ``NO_GO``), and
represents rejected values canonically so that even a bad request still has a
stable digest.  A caller cannot smuggle a favourable result past these by
supplying ``True`` where a number is expected, or a NaN where a rate is.
"""

from __future__ import annotations

import math
from typing import Any


def qualified_type_name(value: Any) -> str:
    """Name a rejected value's type without ever calling ``repr`` on it."""
    return f"{type(value).__module__}.{type(value).__qualname__}"


def invalid_safe(value: Any) -> Any:
    """Represent rejected values canonically so even bad requests are hash-bound."""
    if isinstance(value, float) and not math.isfinite(value):
        label = "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
        return {"__invalid_float__": label}
    if isinstance(value, dict):
        return {str(key): invalid_safe(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [invalid_safe(child) for child in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return {"__invalid_type__": qualified_type_name(value)}


def finite_number(
    value: Any,
    name: str,
    missing: list[str],
    blockers: list[str],
    *,
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> float | None:
    """Accept a finite number, recording why it was rejected when it is not."""
    if value is None:
        missing.append(name)
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        blockers.append(f"{name} must be a finite number")
        return None
    number = float(value)
    if not math.isfinite(number):
        blockers.append(f"{name} must be finite")
        return None
    if not allow_negative and number < 0:
        blockers.append(f"{name} must be finite and non-negative")
        return None
    if number == 0 and not allow_zero:
        blockers.append(f"{name} must be finite and positive")
        return None
    return number


def positive_integer(
    value: Any,
    name: str,
    missing: list[str],
    blockers: list[str],
) -> int | None:
    """Accept a strictly positive ``int``; ``bool`` is not an integer here."""
    if value is None:
        missing.append(name)
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        blockers.append(f"{name} must be a positive integer")
        return None
    return value


__all__ = [
    "finite_number",
    "invalid_safe",
    "positive_integer",
    "qualified_type_name",
]
