"""Checks of this module (implementation pending)."""

from __future__ import annotations

from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import RawOutcome
from quant_trade.audit.forensics.rows import RawTable


def run_TICKET_LINKS(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_CROSS_COPIES(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")
