"""What the file says about its own making: ``FILE_TRACE``, ``STATEMENT_PERIOD``
and ``HIDDEN_CONTENT`` (spec §3.1, §3.20, §3.17).

Every figure is a code, a count or an ISO date (D16): no text of the file
reaches the result. Scoping rules found on the real corpus (D3: a hit on a
genuine file becomes a rule, never a nudged threshold):

- Every MetaTrader HTML export (137 of 137 real files) styles its cells with
  ``mso-number-format`` so that Excel reads the numbers; ``rows.resave_markers``
  counts that stylesheet as one ``mso-`` marker. On a MetaTrader page one
  marker is therefore the platform's own and only markers beyond it count.
  ``rows`` hands over a count, not the markers themselves, so a page that
  lacks the stylesheet but carries one foreign marker is not a hit either.
- The MT5 optimizer writes an Excel XML Spreadsheet whose ``progid``,
  ``xmlns:o=`` and ``mso-application`` are the format's own (three markers).
- 51 of 70 real MT4 statements and 8 of 22 real MT4 tester reports carry no
  ``generator`` meta at all, so ``none`` is native for the MT4 families. MT5
  exports always name their terminal or tester.
- FX Blue exports may hold several account labels; the importer reads the one
  with the most closed positions, and so does ``STATEMENT_PERIOD``.
- A genuine MT5 export hides only empty cells (the Positions filler, the Deals'
  ``Cost`` column) plus the ``Cost`` label of the Deals header itself; header
  rows are therefore outside the non-empty rule and a number in a deal's hidden
  ``Cost`` cell is ``BALANCE_CHAIN``'s to report.

``STATEMENT_PERIOD`` spans the closed record only (the closed-transactions
section of an MT4 statement, the Deals table of an MT5 history, the rows
before Myfxbook's "Open Trades" block): open trades and working orders are
the current state, not the period. ``opens_with_deposit`` is ``1`` when the
earliest dated row is a positive balance operation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, money, rows
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import (
    DECLARED,
    MAX_EXAMPLES,
    MEASURED,
    NOT_MEASURED,
    Figure,
    RawOutcome,
)
from quant_trade.audit.forensics.rows import RawRow, RawTable

# ---------------------------------------------------------------------------
# FILE_TRACE
# ---------------------------------------------------------------------------

_MT_HTML_FAMILIES = frozenset(
    {families.MT4_STATEMENT, families.MT4_TESTER, families.MT5_HISTORY, families.MT5_TESTER}
)
#: Generator codes a genuine export of the family may carry; a family not
#: listed has no expectation (CSV exports and unknown formats carry none).
_NATIVE_GENERATORS: dict[str, frozenset[str]] = {
    families.MT4_STATEMENT: frozenset({"metaquotes", "none"}),
    families.MT4_TESTER: frozenset({"metaquotes", "none"}),
    families.MT5_HISTORY: frozenset({"client_terminal", "metatrader"}),
    families.MT5_TESTER: frozenset({"strategy_tester", "metatrader"}),
}
#: Generator codes of the MetaTrader terminals and testers ("metatrader":
#: older MT5 builds wrote "MetaTrader 5" as the generator).
_MT_GENERATORS = frozenset({"metaquotes", "client_terminal", "strategy_tester", "metatrader"})
#: Re-save markers a format carries by construction (the optimizer's Excel XML).
_PLATFORM_MARKERS_BY_FORMAT: dict[str, int] = {importers.MT5_OPTIMIZATION_XML: 3}
#: The ``sections`` bitmask; MT5 "Open Positions" shares the ``open`` bit with
#: MT4 "Open Trades", and the MT4 tester's single table has its own bit.
_SECTION_BITS: tuple[tuple[str, int], ...] = (
    (rows.SECTION_CLOSED, 1),
    (rows.SECTION_OPEN, 2),
    (rows.SECTION_WORKING, 4),
    (rows.SECTION_ORDERS, 8),
    (rows.SECTION_DEALS, 16),
    (rows.SECTION_POSITIONS, 32),
    (rows.SECTION_SUMMARY, 64),
    (rows.SECTION_TESTER, 128),
)
_SECTION_ALIASES = {rows.SECTION_OPEN_POSITIONS: rows.SECTION_OPEN}
#: Rows that do not make a section present (a title alone, a spacer).
_STRUCTURAL_KINDS = frozenset({rows.KIND_TITLE, rows.KIND_OTHER})
#: Rows whose cells are the platform's printed numbers.
_DATA_KINDS = frozenset(
    {
        rows.KIND_MT4_TRADE,
        rows.KIND_MT4_CASH,
        rows.KIND_MT4_CREDIT,
        rows.KIND_MT4_CANCELLED,
        rows.KIND_MT4_PENDING,
        rows.KIND_MT4_OPEN,
        rows.KIND_MT4_WORKING,
        rows.KIND_MT5_DEAL,
        rows.KIND_MT5_POSITION,
        rows.KIND_MT5_ORDER,
        rows.KIND_MT5_OPEN_POSITION,
        rows.KIND_MT4_TESTER,
        rows.KIND_CSV,
    }
)
#: Spaces, currency signs and the percent sign around a printed number (the
#: importers' own noise set, re-declared here so the check owns its rule).
_CELL_NOISE = re.compile(r"[\s  $€£¥%]")


def run_FILE_TRACE(table: RawTable, ctx: Context) -> RawOutcome:
    """Encoding, line endings, generator, re-save markers and layout counts."""
    native = _generator_native(table)
    platform = _platform_markers(table)
    excess = max(0, table.markers - platform)
    title_attrs = 0
    hidden_cells = 0
    for row in table.rows:
        for cell in row.cells:
            if cell.title:
                title_attrs += 1
            if cell.hidden:
                hidden_cells += 1
    hits = (0 if native else 1) + excess
    figures: tuple[Figure, ...] = (
        ("n_rows", str(len(table.rows)), MEASURED),
        ("n_hits", str(hits), MEASURED),
        ("encoding", table.encoding, MEASURED),
        ("line_endings", table.line_endings, MEASURED),
        ("generator", table.generator, MEASURED),
        ("generator_native", "1" if native else "0", MEASURED),
        ("resave_markers", str(table.markers), MEASURED),
        ("platform_markers", str(platform), MEASURED),
        ("title_attrs", str(title_attrs), MEASURED),
        ("hidden_cells", str(hidden_cells), MEASURED),
        ("decimal_comma", _decimal_comma(table), MEASURED),
        ("sections", str(_sections_code(table)), MEASURED),
    )
    return RawOutcome(hits=hits, figures=figures)


def _generator_native(table: RawTable) -> bool:
    if table.source_format in families.XLSX_FORMATS:
        return table.generator == "none"
    expected = _NATIVE_GENERATORS.get(table.family)
    return expected is None or table.generator in expected


def _platform_markers(table: RawTable) -> int:
    """Re-save markers the platform's own export carries by construction:
    the optimizer's Excel XML. (The ``mso-number-format`` stylesheet of every
    MetaTrader HTML page is not a marker: ``rows.marker_codes`` skips it.)"""
    return _PLATFORM_MARKERS_BY_FORMAT.get(table.source_format, 0)


def _decimal_comma(table: RawTable) -> str:
    """``1`` when the first printed number with a separator uses a decimal
    comma (the importers' own rule), ``0`` otherwise or without one."""
    for row in table.rows:
        if row.kind not in _DATA_KINDS:
            continue
        for text in row.texts:
            cleaned = _CELL_NOISE.sub("", text)
            if ("," not in cleaned and "." not in cleaned) or money.parse_money(text) is None:
                continue
            return "1" if importers._comma_is_decimal(cleaned) else "0"
    return "0"


def _sections_code(table: RawTable) -> int:
    present: set[str] = set()
    for row in table.rows:
        if row.kind not in _STRUCTURAL_KINDS:
            present.add(_SECTION_ALIASES.get(row.section, row.section))
    return sum(bit for name, bit in _SECTION_BITS if name in present)


# ---------------------------------------------------------------------------
# STATEMENT_PERIOD
# ---------------------------------------------------------------------------

_PERIOD_FAMILIES = frozenset(
    {
        families.MT4_STATEMENT,
        families.MT5_HISTORY,
        families.MYFXBOOK,
        families.MQL5_SIGNAL,
        families.FXBLUE,
    }
)
#: The dated rows of an MT4 statement's closed record.
_MT4_RECORD_KINDS = frozenset(
    {
        rows.KIND_MT4_TRADE,
        rows.KIND_MT4_CASH,
        rows.KIND_MT4_CREDIT,
        rows.KIND_MT4_CANCELLED,
        rows.KIND_MT4_PENDING,
    }
)
#: Myfxbook lists the positions still open after one of these titles, or
#: after a second header whose second and third names are these.
_MYFXBOOK_OPEN_TITLES = frozenset({"open trades", "open orders", "open positions"})
_MYFXBOOK_OPEN_HEADER = ("ticket", "open date")


@dataclass(frozen=True)
class _Dated:
    index: int
    start: datetime
    """Naive UTC, the file's own clock."""
    end: datetime
    deposit: bool


@dataclass(frozen=True)
class _Record:
    dated: tuple[_Dated, ...] = ()
    reason: str = ""
    """A skip reason, or ``""`` when the record could be read."""
    accounts: int = 1
    """Distinct account labels in the file; ``1`` when the format prints none."""


def run_STATEMENT_PERIOD(table: RawTable, ctx: Context) -> RawOutcome:
    """The span of the closed record, as printed; never a finding by itself."""
    if table.family not in _PERIOD_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    record = _dated_rows(table)
    if record.reason:
        return RawOutcome.skip(record.reason)
    if not record.dated:
        return RawOutcome.skip("no_qualifying_row")
    earliest = min(record.dated, key=lambda item: (item.start, item.index))
    first_at = earliest.start
    last_at = max(item.end for item in record.dated)
    report_date = ctx.header.report_date
    figures: tuple[Figure, ...] = (
        ("n_rows", str(len(record.dated)), MEASURED),
        ("n_hits", "0", MEASURED),
        ("first_row_at", _iso(first_at), MEASURED),
        ("last_row_at", _iso(last_at), MEASURED),
        ("opens_with_deposit", "1" if earliest.deposit else "0", MEASURED),
        ("n_accounts", str(record.accounts), MEASURED),
        ("report_date", _iso(report_date), DECLARED)
        if report_date is not None
        else ("report_date", "", NOT_MEASURED),
    )
    return RawOutcome(hits=0, figures=figures)


def _dated_rows(table: RawTable) -> _Record:
    """The dated rows of the closed record, or the reason none could be read."""
    if table.family == families.MT4_STATEMENT:
        return _Record(tuple(_mt4_dated(table)))
    if table.family == families.MT5_HISTORY:
        return _Record(tuple(_mt5_dated(table)))
    try:
        if table.family == families.MYFXBOOK:
            return _myfxbook_dated(table)
        if table.family == families.MQL5_SIGNAL:
            return _mql5_dated(table)
        return _fxblue_dated(table)
    except importers.ReportFormatError:
        # Ambiguous day/month dates: the importer refuses such a file at
        # upload, so the battery never meets one; stay pure all the same.
        return _Record(reason="no_qualifying_row")


def _mt4_dated(table: RawTable) -> list[_Dated]:
    dated: list[_Dated] = []
    for row in table.rows:
        if row.section != rows.SECTION_CLOSED or row.kind not in _MT4_RECORD_KINDS:
            continue
        columns = rows.mt4_columns(table, row)
        opened = _naive(row.text(columns["open_time"]))
        closed = _naive(row.text(columns["close_time"]))
        if opened is None and closed is None:
            continue
        deposit = row.kind == rows.KIND_MT4_CASH and _mt4_amount(row, columns["type"]) > 0
        dated.append(_span(row.index, opened, closed, deposit))
    return dated


def _mt4_amount(row: RawRow, after: int) -> money.Decimal:
    """The amount of a balance row: its last printed number past the type cell
    (the comment cell spans the price columns)."""
    for text in reversed(row.texts[after + 1 :]):
        amount = money.parse_money(text)
        if amount is not None:
            return amount
    return money.Decimal(0)


def _mt5_dated(table: RawTable) -> list[_Dated]:
    dated: list[_Dated] = []
    for row in table.kind(rows.KIND_MT5_DEAL):
        columns = rows.mt5_columns(table, row)
        moment = _naive(row.text(columns.get("time", 0)))
        if moment is None:
            continue
        profit = money.parse_money(row.text(columns.get("profit", -1)))
        balance_deal = not row.text(columns.get("symbol", 2))
        deposit = balance_deal and profit is not None and profit > 0
        dated.append(_Dated(row.index, moment, moment, deposit))
    return dated


def _myfxbook_dated(table: RawTable) -> _Record:
    names = _names(table)
    if "open date" not in names:
        return _Record(reason="no_column")
    body: list[RawRow] = []
    for row in table.rows:
        if row.kind != rows.KIND_CSV:
            continue
        lowered = tuple(text.lower() for text in row.texts[:3])
        if (lowered and lowered[0] in _MYFXBOOK_OPEN_TITLES) or (
            lowered[1:3] == _MYFXBOOK_OPEN_HEADER
        ):
            break
        body.append(row)
    opened = _column_times(body, names["open date"])
    closed = _column_times(body, names.get("close date", -1))
    action = names.get("action", -1)
    dated: list[_Dated] = []
    for row, start, end in zip(body, opened, closed, strict=True):
        if start is None and end is None:
            continue
        deposit = row.text(action).strip().lower() == "deposit"
        dated.append(_span(row.index, start, end, deposit))
    return _Record(tuple(dated))


def _mql5_dated(table: RawTable) -> _Record:
    lowered = [text.strip().lower() for text in table.header]
    if not lowered or lowered[0] != "time" or "type" not in lowered:
        return _Record(reason="no_column")
    close_at = lowered.index("time", 1) if lowered.count("time") > 1 else -1
    kind_at = lowered.index("type")
    profit_at = lowered.index("profit") if "profit" in lowered else -1
    body = list(table.kind(rows.KIND_CSV))
    opened = _column_times(body, 0)
    closed = _column_times(body, close_at)
    dated: list[_Dated] = []
    for row, start, end in zip(body, opened, closed, strict=True):
        if start is None and end is None:
            continue
        profit = money.parse_money(row.text(profit_at))
        deposit = (
            row.text(kind_at).strip().lower() == "balance" and profit is not None and profit > 0
        )
        dated.append(_span(row.index, start, end, deposit))
    return _Record(tuple(dated))


def _fxblue_dated(table: RawTable) -> _Record:
    names = _names(table)
    if "open time" not in names:
        return _Record(reason="no_column")
    body = list(table.kind(rows.KIND_CSV))
    kind_at = names.get("type", -1)
    accounts = 1
    account = names.get("account")
    if account is not None:
        body, accounts = _busiest_account(body, account, kind_at)
    opened = _column_times(body, names["open time"])
    closed = _column_times(body, names.get("close time", -1))
    dated: list[_Dated] = []
    for row, start, end in zip(body, opened, closed, strict=True):
        if start is None and end is None:
            continue
        deposit = row.text(kind_at).strip().lower() == "deposit"
        dated.append(_span(row.index, start, end, deposit))
    return _Record(tuple(dated), accounts=accounts)


def _busiest_account(body: list[RawRow], account: int, kind_at: int) -> tuple[list[RawRow], int]:
    """The rows of the account label with the most closed positions (the
    importer's own choice; a tie goes to the label seen first) and how many
    labels the file holds. One label, or none, keeps every row."""
    closed: dict[str, int] = {}
    for row in body:
        label = row.text(account).strip()
        if not label:
            continue
        closed.setdefault(label, 0)
        if row.text(kind_at).strip().lower() == "closed position":
            closed[label] += 1
    if len(closed) <= 1:
        return body, 1
    chosen = max(closed, key=lambda label: closed[label])
    return [row for row in body if row.text(account).strip() == chosen], len(closed)


def _names(table: RawTable) -> dict[str, int]:
    """Lower-cased column names of a delimited file, first occurrence wins."""
    names: dict[str, int] = {}
    for position, text in enumerate(table.header):
        names.setdefault(text.strip().lower(), position)
    return names


def _column_times(body: list[RawRow], position: int) -> list[datetime | None]:
    """One column parsed with the importers' day-first rule, as naive UTC."""
    if position < 0:
        return [None] * len(body)
    parsed = importers._parse_times([row.text(position) for row in body])
    return [_as_naive(moment) for moment in parsed.values]


def _span(index: int, start: datetime | None, end: datetime | None, deposit: bool) -> _Dated:
    """A row's span; a close before its open (FX Blue prints the epoch for
    positions still open) counts as no close."""
    first = start if start is not None else end
    assert first is not None
    last = end if end is not None and end >= first else first
    return _Dated(index, first, last, deposit)


def _naive(text: str) -> datetime | None:
    return _as_naive(importers._one_time(text.strip())) if text.strip() else None


def _as_naive(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment


def _iso(moment: datetime) -> str:
    return _as_naive_strict(moment).isoformat(timespec="seconds") + "Z"


def _as_naive_strict(moment: datetime) -> datetime:
    converted = _as_naive(moment)
    assert converted is not None
    return converted


# ---------------------------------------------------------------------------
# HIDDEN_CONTENT
# ---------------------------------------------------------------------------

_HIDDEN_FAMILIES = frozenset({families.MT5_HISTORY, families.MT5_TESTER})


def run_HIDDEN_CONTENT(table: RawTable, ctx: Context) -> RawOutcome:
    """Hidden cells that carry text, and rows hidden whole."""
    if table.family not in _HIDDEN_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    if table.source_format in families.XLSX_FORMATS:
        return RawOutcome.skip("no_column")
    n_hidden = 0
    nonempty = 0
    hidden_rows = 0
    examples: list[int] = []
    for row in table.rows:
        hidden = [position for position, cell in enumerate(row.cells) if cell.hidden]
        n_hidden += len(hidden)
        if not hidden:
            continue
        hit = False
        if len(hidden) == len(row.cells):
            hidden_rows += 1
            hit = True
        if row.kind != rows.KIND_HEADER:
            cost = _hidden_header_positions(table, row) if row.kind == rows.KIND_MT5_DEAL else ()
            for position in hidden:
                text = row.cells[position].text
                if not text:
                    continue
                if position in cost and money.parse_money(text) is not None:
                    continue
                nonempty += 1
                hit = True
        if hit:
            examples.append(row.index)
    hits = nonempty + hidden_rows
    figures: tuple[Figure, ...] = (
        ("n_rows", str(len(table.rows)), MEASURED),
        ("n_hits", str(hits), MEASURED),
        ("n_hidden_cells", str(n_hidden), MEASURED),
        ("hidden_nonempty", str(nonempty), MEASURED),
        ("hidden_rows", str(hidden_rows), MEASURED),
    )
    return RawOutcome(hits=hits, figures=figures, examples=tuple(examples[:MAX_EXAMPLES]))


def _hidden_header_positions(table: RawTable, row: RawRow) -> tuple[int, ...]:
    """Cell positions the header above ``row`` hides (the Deals' ``Cost``)."""
    if not 0 <= row.header_row < len(table.rows):
        return ()
    header = table.rows[row.header_row]
    if header.kind != rows.KIND_HEADER:
        return ()
    return tuple(position for position, cell in enumerate(header.cells) if cell.hidden)


__all__ = ["run_FILE_TRACE", "run_HIDDEN_CONTENT", "run_STATEMENT_PERIOD"]
