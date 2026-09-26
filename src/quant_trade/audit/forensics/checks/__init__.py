"""One module per group of checks; each exposes ``run_<CHECK_ID>(table, ctx)``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quant_trade.audit.forensics.header import Header
from quant_trade.audit.forensics.rows import RawTable


@dataclass(frozen=True)
class Context:
    family: str
    header: Header
    imported_warnings: tuple[str, ...] = ()
    monthly: Any = None
    """A ``factsheet.MonthlyGrid`` when the upload is a monthly table."""
    currency: str = ""


__all__ = ["Context", "RawTable"]
