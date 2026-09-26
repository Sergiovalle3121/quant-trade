"""Checks of this module (implementation pending)."""

from __future__ import annotations

from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import RawOutcome
from quant_trade.audit.forensics.rows import RawTable


def run_FILE_TRACE(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_STATEMENT_PERIOD(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_HIDDEN_CONTENT(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")
