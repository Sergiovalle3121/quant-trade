"""Printed numbers, read as text: ``Decimal`` at the file's own precision.

The battery compares what the platform printed, never a float: ``1 009.40``
is the decimal ``1009.40`` with two printed decimals. Thousands separators
(space, non-breaking space, comma before three digits) are dropped; a
decimal comma is honoured with the importer's own rule.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from quant_trade.audit import importers

_NOISE = re.compile(r"[\s  $€£¥%]")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def parse_money(text: str | None) -> Decimal | None:
    """The printed number as a ``Decimal``, or ``None`` when the cell is not one.

    ``(12.50)`` reads as ``-12.50``; ``-0.00`` stays a signed zero whose
    ``normalise_text`` form is ``0.00``.
    """
    if text is None:
        return None
    value = text.strip()
    if not value:
        return None
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    value = _NOISE.sub("", value)
    if importers._comma_is_decimal(value):
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    if not _NUMBER.match(value):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return -abs(number) if negative else number


def printed_decimals(text: str | None) -> int | None:
    """How many digits follow the decimal mark in the printed cell."""
    if text is None:
        return None
    value = _NOISE.sub("", text.strip().strip("()"))
    if not value:
        return None
    if importers._comma_is_decimal(value):
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    if not _NUMBER.match(value):
        return None
    return len(value.split(".")[1]) if "." in value else 0


def as_text(value: Decimal, decimals: int | None = None) -> str:
    """A ``Decimal`` as text, ``-0.00`` written ``0.00``."""
    if decimals is not None:
        value = value.quantize(Decimal(1).scaleb(-decimals))
    if value == 0:
        value = abs(value)
    return format(value, "f")


def normalise_text(text: str) -> str:
    """The printed figure without separators: what a canonical record stores."""
    number = parse_money(text)
    return as_text(number) if number is not None else ""


def ratio_text(numerator: int, denominator: int) -> str:
    """A ratio with three decimals, ``0.000`` when there is no denominator."""
    if denominator <= 0:
        return "0.000"
    return as_text(Decimal(numerator) / Decimal(denominator), 3)


def tolerance(count: int = 1) -> Decimal:
    """The importers' convention for two printed money cells: half a cent of
    rounding on each side plus a hair, per comparison."""
    return Decimal("0.011") * max(1, count)
