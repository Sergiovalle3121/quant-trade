"""Checks of this module (implementation pending)."""

from __future__ import annotations

from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import RawOutcome
from quant_trade.audit.forensics.rows import RawTable


def run_TIME_SANITY(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_ROW_ORDER(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")


def run_MARKET_HOURS(table: RawTable, ctx: Context) -> RawOutcome:
    return RawOutcome.skip("format_not_covered")
