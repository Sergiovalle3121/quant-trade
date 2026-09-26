"""``review``: run every check on a file and apply the one status rule."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from typing import Any

from quant_trade.audit.forensics import families
from quant_trade.audit.forensics.calibration import (
    CALIBRATION,
    SIGNAL_CAPABLE,
    THRESHOLDS,
    clopper_pearson_upper_pct,
)
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import (
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    STATUS_SIGNAL,
    STATUSES,
    CheckResult,
    ForensicResult,
    RawOutcome,
)
from quant_trade.audit.forensics.rows import RawTable, load

#: Bump on ANY change that can move a status or a figure.
METHOD_VERSION = "forensics-1"

CHECK_ORDER = (
    "FILE_TRACE",
    "TOTALS_VS_ROWS",
    "SUMMARY_IDENTITIES",
    "BALANCE_CHAIN",
    "DEAL_SEQUENCE",
    "TESTER_NUMBERING",
    "TICKET_ORDER",
    "DUPLICATE_TICKET",
    "TICKET_LINKS",
    "CROSS_COPIES",
    "SLTP_FILL",
    "PNL_SIGN",
    "PRICE_IMPLIED_PNL",
    "PRICE_PRECISION",
    "TIME_SANITY",
    "ROW_ORDER",
    "MARKET_HOURS",
    "HIDDEN_CONTENT",
    "VOLUME_IN_OUT",
    "STATEMENT_PERIOD",
    "TV_INVARIANTS",
    "NT_INVARIANTS",
    "MONTHLY_DIGITS",
)

#: Which module implements each check; ``run_<CHECK_ID>`` inside it.
_MODULES = {
    "FILE_TRACE": "trace",
    "STATEMENT_PERIOD": "trace",
    "HIDDEN_CONTENT": "trace",
    "TOTALS_VS_ROWS": "totals",
    "SUMMARY_IDENTITIES": "totals",
    "BALANCE_CHAIN": "balance",
    "VOLUME_IN_OUT": "balance",
    "DEAL_SEQUENCE": "tickets",
    "TESTER_NUMBERING": "tickets",
    "TICKET_ORDER": "tickets",
    "DUPLICATE_TICKET": "tickets",
    "TICKET_LINKS": "links",
    "CROSS_COPIES": "links",
    "SLTP_FILL": "prices",
    "PNL_SIGN": "prices",
    "PRICE_IMPLIED_PNL": "prices",
    "PRICE_PRECISION": "prices",
    "TIME_SANITY": "times",
    "ROW_ORDER": "times",
    "MARKET_HOURS": "times",
    "TV_INVARIANTS": "platforms",
    "NT_INVARIANTS": "platforms",
    "MONTHLY_DIGITS": "monthly",
}

#: Checks whose answer depends on reading every row in order.
ORDER_SENSITIVE = frozenset(
    {
        "BALANCE_CHAIN",
        "DEAL_SEQUENCE",
        "TESTER_NUMBERING",
        "TICKET_ORDER",
        "ROW_ORDER",
        "VOLUME_IN_OUT",
        "TV_INVARIANTS",
        "NT_INVARIANTS",
    }
)

#: The closed list of ``NOT_MEASURED`` reason codes.
REASONS = (
    "format_not_covered",
    "no_table",
    "no_column",
    "no_qualifying_row",
    "no_listed_symbol",
    "xlsx_precision_lost",
    "variable_precision_format",
    "no_header_date",
    "no_declared_totals",
    "netting_or_unknown_margin_mode",
    "no_orders_table",
    "several_accounts",
    "too_few_values",
    "quote_currency_differs",
    "truncated",
    "caps_hit",
)

Runner = Callable[[RawTable, Context], RawOutcome]


def _runner(check_id: str) -> Runner:
    module = importlib.import_module(f"quant_trade.audit.forensics.checks.{_MODULES[check_id]}")
    runner: Runner = getattr(module, f"run_{check_id}")
    return runner


def decide(check_id: str, family: str, raw: RawOutcome) -> str:
    """The one status rule; no check bypasses it."""
    if raw.not_measured:
        return STATUS_NOT_MEASURED
    if raw.hits == 0:
        return STATUS_CLEAN
    cell = CALIBRATION.get((check_id, family))
    if (
        cell is not None
        and cell.granted
        and check_id in SIGNAL_CAPABLE
        and raw.hits > THRESHOLDS.get((check_id, family), 0)
    ):
        return STATUS_SIGNAL
    return STATUS_INFO


def calibration_line(check_id: str, family: str) -> tuple[tuple[str, str], ...]:
    cell = CALIBRATION.get((check_id, family))
    if cell is None:
        return ()
    return (
        ("n", str(cell.n)),
        ("n_reserved", str(cell.n_reserved)),
        ("unexplained", str(cell.unexplained)),
        ("cp95_upper_pct", clopper_pearson_upper_pct(cell.unexplained, cell.n)),
        ("frozen", cell.frozen),
    )


def review(
    data: bytes,
    *,
    source_format: str | None,
    imported_warnings: Sequence[str] = (),
    monthly: Any = None,
    currency: str | None = None,
) -> ForensicResult:
    """Run the battery on ``data``; pure, deterministic, never re-imports."""
    if monthly is not None:
        table = RawTable("monthly", families.MONTHLY, (), (), "none", "none", "none", 0, False)
    else:
        table = load(data, source_format)
    header = read_header(table, currency)
    ctx = Context(
        family=table.family,
        header=header,
        imported_warnings=tuple(imported_warnings),
        monthly=monthly,
        currency=header.currency,
    )
    checks: list[CheckResult] = []
    for check_id in CHECK_ORDER:
        if table.truncated and check_id in ORDER_SENSITIVE:
            raw = RawOutcome.skip("truncated")
        else:
            raw = _runner(check_id)(table, ctx)
        if raw.not_measured and raw.reason not in REASONS:
            raise ValueError(f"{check_id}: unknown reason {raw.reason!r}")
        status = decide(check_id, table.family, raw)
        checks.append(
            CheckResult(
                id=check_id,
                status=status,
                figures=raw.figures,
                examples=tuple(sorted(raw.examples)[:5]),
                reason=raw.reason if status == STATUS_NOT_MEASURED else "",
                applies=status != STATUS_NOT_MEASURED,
                calibration=calibration_line(check_id, table.family),
            )
        )
    counts = tuple((name, sum(1 for c in checks if c.status == name)) for name in STATUSES)
    return ForensicResult(
        method_version=METHOD_VERSION,
        source_format=table.source_format,
        family=table.family,
        checks=tuple(checks),
        rows_read=len(table.rows),
        truncated=table.truncated,
        header_present=header.has_account,
        counts=counts,
    )


__all__ = [
    "CHECK_ORDER",
    "METHOD_VERSION",
    "ORDER_SENSITIVE",
    "REASONS",
    "STATUS_CLEAN",
    "STATUS_INFO",
    "STATUS_SIGNAL",
    "decide",
    "review",
]
