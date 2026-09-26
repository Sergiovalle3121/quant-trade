"""Checks of this module (implementation pending)."""

from __future__ import annotations

from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import RawOutcome
from quant_trade.audit.forensics.rows import RawTable


def run_DEAL_SEQUENCE(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_TESTER_NUMBERING(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_TICKET_ORDER(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_DUPLICATE_TICKET(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")
