"""Ticket and numbering checks of the battery.

``DEAL_SEQUENCE``: a MetaTrader 5 server hands out deal and order tickets
in time order. ``TESTER_NUMBERING``: a strategy tester numbers its rows
locally from one. ``TICKET_ORDER``: MT4-style tickets against open and
close times, descriptive only (a filled pending order prints its
activation time under the ticket it got at placement). ``DUPLICATE_TICKET``:
no id is printed twice within its table.

Every figure is a count or a number of seconds. Ticket ids, symbols and
comments never leave the file; examples are raw-row indexes (D16). A figure
a family cannot measure is still emitted, as ``0`` with ``NOT_MEASURED``, so
each check carries one key set whatever the family.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows, thresholds
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import (
    MAX_EXAMPLES,
    MEASURED,
    NOT_MEASURED,
    Figure,
    RawOutcome,
)
from quant_trade.audit.forensics.rows import RawRow, RawTable

_SIDES = frozenset({"buy", "sell"})
#: MT4 tester row types that leave an order open when the run ends on them.
_MT4_TESTER_OPENERS = frozenset(
    {"buy", "sell", "buy limit", "sell limit", "buy stop", "sell stop", "swap open"}
)
#: MT4 statement kinds that carry a ticket.
_MT4_TICKET_KINDS = frozenset(
    {
        rows.KIND_MT4_TRADE,
        rows.KIND_MT4_CASH,
        rows.KIND_MT4_CREDIT,
        rows.KIND_MT4_CANCELLED,
        rows.KIND_MT4_PENDING,
        rows.KIND_MT4_OPEN,
        rows.KIND_MT4_WORKING,
    }
)
#: A comment marking a row that keeps an older open time under a newer ticket
#: (partial-close remainder, rollover reopen).
_REOPEN_MARKS = ("from #", "swap open")
#: Myfxbook prints the positions still open under one of these titles.
_MYFXBOOK_OPEN_TITLES = frozenset({"open trades", "open orders", "open positions"})
_FXBLUE_CLOSED = "closed position"
#: A tester's first deal is its initial deposit (every corpus file so far).
_MT5_TESTER_FIRST_DEAL = 1

_MT5_FAMILIES = frozenset({families.MT5_HISTORY, families.MT5_TESTER})


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _int(text: str) -> int | None:
    """The cell as a non-negative integer, or ``None`` when it is not one."""
    value = text.strip()
    if not value or not value.isascii() or not value.isdigit():
        return None
    return int(value)


def _count(key: str, value: int) -> Figure:
    return (key, str(value), MEASURED)


def _unmeasured(key: str) -> Figure:
    return (key, "0", NOT_MEASURED)


def _examples(indexes: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted(set(indexes))[:MAX_EXAMPLES])


def _times(texts: Sequence[str]) -> list[datetime | None]:
    """One printed column of times, read the importers' way (day-first
    decided once per column); an unreadable column reads as no times."""
    try:
        return importers._parse_times(list(texts)).values
    except importers.ReportFormatError:
        return [None] * len(texts)


def _column(names: Sequence[str], *wanted: str) -> int | None:
    """The position of the first of ``wanted`` among ``names`` (case-insensitive)."""
    lowered = [name.strip().lower() for name in names]
    for name in wanted:
        if name in lowered:
            return lowered.index(name)
    return None


def _seconds(delta: timedelta) -> int:
    return delta.days * 86400 + delta.seconds


# ---------------------------------------------------------------------------
# Numbering of a local sequence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Numbering:
    count: int
    distinct: int
    highest: int
    missing: int
    """Numbers absent between the expected start (or the lowest seen) and the highest."""
    duplicates: tuple[int, ...]
    """Row indexes whose number was already seen."""
    out_of_order: tuple[int, ...]
    """Row indexes whose number is below the previous row's."""
    jumps: tuple[int, ...]
    """Row indexes where the number skips past the previous one plus one."""


def _numbering(numbers: Sequence[tuple[int, int]], start: int | None = None) -> _Numbering:
    """Read ``(number, row index)`` pairs in file order against ``start, start+1, ...``."""
    seen: set[int] = set()
    duplicates: list[int] = []
    out_of_order: list[int] = []
    jumps: list[int] = []
    previous: int | None = None
    for value, index in numbers:
        if value in seen:
            duplicates.append(index)
        elif previous is None:
            if start is not None and value != start:
                jumps.append(index)
        elif value < previous:
            out_of_order.append(index)
        elif value > previous + 1:
            jumps.append(index)
        seen.add(value)
        previous = value
    if not seen:
        return _Numbering(0, 0, 0, 0, (), (), ())
    lowest, highest = min(seen), max(seen)
    first = lowest if start is None else min(start, lowest)
    missing = (highest - first + 1) - len(seen)
    return _Numbering(
        count=len(numbers),
        distinct=len(seen),
        highest=highest,
        missing=missing,
        duplicates=tuple(duplicates),
        out_of_order=tuple(out_of_order),
        jumps=tuple(jumps),
    )


# ---------------------------------------------------------------------------
# MT4 statement rows
# ---------------------------------------------------------------------------


def _mt4_ticket_at(table: RawTable, row: RawRow) -> int:
    """The ticket column: index 0 unless the header names it elsewhere
    (the numbered 15-column layout puts a row number first)."""
    found = _column(table.header_of(row), "ticket")
    return 0 if found is None else found


def _mt4_comment(table: RawTable, row: RawRow, ticket_at: int) -> str:
    """The row's comment, lower-cased: the ticket cell's ``title``, else a
    comment column, else (2009 layout) the single text of the ``other`` row
    printed right after the trade."""
    for position in (ticket_at, 0):
        if position < len(row.cells) and row.cells[position].title:
            return row.cells[position].title.lower()
    comment_at = _column(table.header_of(row), "comment")
    if comment_at is not None and row.text(comment_at):
        return row.text(comment_at).lower()
    following = row.index + 1
    if following < len(table.rows):
        after = table.rows[following]
        if after.kind == rows.KIND_OTHER and after.section == rows.SECTION_CLOSED:
            texts = [text for text in after.texts if text]
            if len(texts) == 1:
                return texts[0].lower()
    return ""


def _reopened(comment: str) -> bool:
    return any(mark in comment for mark in _REOPEN_MARKS)


# ---------------------------------------------------------------------------
# DEAL_SEQUENCE
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Stamped:
    ticket: int
    time: datetime
    index: int
    order: int | None = None


def _mt5_trade_deals(table: RawTable) -> list[_Stamped] | None:
    """Buy/sell deals with a readable ticket and time, in file order;
    ``None`` when the Deals columns cannot be mapped."""
    picked: list[tuple[int, int, int | None]] = []
    time_texts: list[str] = []
    for row in table.kind(rows.KIND_MT5_DEAL):
        columns = rows.mt5_columns(table, row)
        if "deal" not in columns or "time" not in columns or "type" not in columns:
            return None
        if row.text(columns["type"]).lower() not in _SIDES:
            continue
        ticket = _int(row.text(columns["deal"]))
        if ticket is None:
            continue
        order_at = columns.get("order")
        order = None if order_at is None else _int(row.text(order_at))
        picked.append((ticket, row.index, order))
        time_texts.append(row.text(columns["time"]))
    times = _times(time_texts)
    return [
        _Stamped(ticket, time, index, order)
        for (ticket, index, order), time in zip(picked, times, strict=True)
        if time is not None
    ]


def _mt5_orders(table: RawTable) -> list[_Stamped]:
    """Orders with a readable ticket (col 1) and placement time (col 0)."""
    picked: list[tuple[int, int]] = []
    time_texts: list[str] = []
    for row in table.kind(rows.KIND_MT5_ORDER):
        ticket = _int(row.text(1))
        if ticket is None:
            continue
        picked.append((ticket, row.index))
        time_texts.append(row.text(0))
    times = _times(time_texts)
    return [
        _Stamped(ticket, time, index)
        for (ticket, index), time in zip(picked, times, strict=True)
        if time is not None
    ]


def run_DEAL_SEQUENCE(table: RawTable, ctx: Context) -> RawOutcome:
    if table.family not in _MT5_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    if not table.kind(rows.KIND_MT5_DEAL):
        return RawOutcome.skip("no_table")
    deals = _mt5_trade_deals(table)
    if deals is None:
        return RawOutcome.skip("no_column")
    orders = _mt5_orders(table)
    counts = (
        _count("n_rows", len(deals) + len(orders)),
        _count("n_deals", len(deals)),
        _count("n_orders", len(orders)),
    )
    if len(deals) < 2:
        return RawOutcome.skip("no_qualifying_row", figures=counts)
    ticket_inversions: list[int] = []
    time_inversions: list[int] = []
    for previous, current in zip(deals, deals[1:], strict=False):
        if current.ticket <= previous.ticket:
            ticket_inversions.append(current.index)
        if current.time < previous.time:
            time_inversions.append(current.index)
    hits = len(ticket_inversions) + len(time_inversions)
    figures: list[Figure] = [
        *counts,
        _count("n_hits", hits),
        _count("ticket_inversions", len(ticket_inversions)),
        _count("time_inversions", len(time_inversions)),
    ]
    if orders:
        placed = sorted(orders, key=lambda order: (order.time, order.index))
        order_inversions = sum(
            1
            for previous, current in zip(placed, placed[1:], strict=False)
            if current.ticket <= previous.ticket
        )
        known = {order.ticket for order in orders}
        missing = sum(1 for deal in deals if deal.order is None or deal.order not in known)
        figures.append(_count("order_inversions", order_inversions))
        figures.append(_count("orders_missing_for_deals", missing))
    else:
        figures.append(_unmeasured("order_inversions"))
        figures.append(_unmeasured("orders_missing_for_deals"))
    return RawOutcome(
        hits=hits,
        figures=tuple(figures),
        examples=_examples(ticket_inversions + time_inversions),
    )


# ---------------------------------------------------------------------------
# TESTER_NUMBERING
# ---------------------------------------------------------------------------


def run_TESTER_NUMBERING(table: RawTable, ctx: Context) -> RawOutcome:
    if table.family == families.MT4_TESTER:
        return _mt4_tester_numbering(table)
    if table.family == families.MT5_TESTER:
        return _mt5_tester_numbering(table)
    return RawOutcome.skip("format_not_covered")


def _mt4_tester_numbering(table: RawTable) -> RawOutcome:
    """``#`` must run ``1..N``; an order number seen once must be an opener
    (the run ended with it open), else it is counted as a figure."""
    tester = table.kind(rows.KIND_MT4_TESTER)
    if not tester:
        return RawOutcome.skip("no_table")
    numbers: list[tuple[int, int]] = []
    for row in tester:
        number = _int(row.text(0))
        if number is not None:
            numbers.append((number, row.index))
    if not numbers:
        return RawOutcome.skip("no_qualifying_row")
    sequence = _numbering(numbers, start=1)
    rows_of_order: dict[int, int] = {}
    last_type: dict[int, str] = {}
    for row in tester:
        order = _int(row.text(3))
        if order is None:
            continue
        rows_of_order[order] = rows_of_order.get(order, 0) + 1
        last_type[order] = row.text(2).lower()
    single = sum(
        1
        for order, count in rows_of_order.items()
        if count == 1 and last_type[order] not in _MT4_TESTER_OPENERS
    )
    hits = sequence.missing + len(sequence.duplicates) + len(sequence.out_of_order)
    figures = (
        _count("n_rows", len(tester)),
        _count("n_hits", hits),
        _count("expected_max", len(numbers)),
        _count("seen", sequence.highest),
        _count("duplicates", len(sequence.duplicates)),
        _count("out_of_order", len(sequence.out_of_order)),
        _count("gaps", sequence.missing),
        _unmeasured("deal_gaps"),
        _unmeasured("order_gaps"),
        _count("orders_single_row", single),
    )
    return RawOutcome(
        hits=hits,
        figures=figures,
        examples=_examples(sequence.duplicates + sequence.out_of_order + sequence.jumps),
    )


def _mt5_tester_numbering(table: RawTable) -> RawOutcome:
    """Deal numbers rise from 1 without repeats; order numbers never repeat.
    Gaps are figures only until the shared-counter hypothesis is settled (D18)."""
    deals = table.kind(rows.KIND_MT5_DEAL)
    if not deals:
        return RawOutcome.skip("no_table")
    deal_numbers: list[tuple[int, int]] = []
    for row in deals:
        columns = rows.mt5_columns(table, row)
        if "deal" not in columns:
            return RawOutcome.skip("no_column")
        number = _int(row.text(columns["deal"]))
        if number is not None:
            deal_numbers.append((number, row.index))
    if not deal_numbers:
        return RawOutcome.skip("no_qualifying_row")
    order_numbers: list[tuple[int, int]] = []
    for row in table.kind(rows.KIND_MT5_ORDER):
        number = _int(row.text(1))
        if number is not None:
            order_numbers.append((number, row.index))
    deal_sequence = _numbering(deal_numbers, start=_MT5_TESTER_FIRST_DEAL)
    order_sequence = _numbering(order_numbers)
    duplicates = deal_sequence.duplicates + order_sequence.duplicates
    out_of_order = deal_sequence.out_of_order + order_sequence.out_of_order
    hits = len(duplicates) + len(out_of_order)
    figures = (
        _count("n_rows", len(deal_numbers) + len(order_numbers)),
        _count("n_hits", hits),
        _count("expected_max", deal_sequence.distinct),
        _count("seen", deal_sequence.highest),
        _count("duplicates", len(duplicates)),
        _count("out_of_order", len(out_of_order)),
        _unmeasured("gaps"),
        _count("deal_gaps", deal_sequence.missing),
        _count("order_gaps", order_sequence.missing),
        _unmeasured("orders_single_row"),
    )
    return RawOutcome(hits=hits, figures=figures, examples=_examples(duplicates + out_of_order))


# ---------------------------------------------------------------------------
# TICKET_ORDER
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Timed:
    ticket: int
    index: int
    opened: datetime | None
    closed: datetime | None


def _csv_rows(table: RawTable) -> tuple[RawRow, ...]:
    return table.kind(rows.KIND_CSV)


def _myfxbook_body(table: RawTable) -> list[RawRow]:
    """The closed-history rows: everything before the open-trades block,
    whose rows shift their columns (the importer stops at the same place)."""
    kept: list[RawRow] = []
    for row in _csv_rows(table):
        lowered = [text.lower() for text in row.texts[:3]]
        if (lowered and lowered[0] in _MYFXBOOK_OPEN_TITLES) or lowered[1:3] == [
            "ticket",
            "open date",
        ]:
            break
        kept.append(row)
    return kept


def _fxblue_accounts(table: RawTable) -> int:
    """How many distinct ``Account`` values the export holds (0 without the column)."""
    account_at = _column(table.header, "account")
    if account_at is None:
        return 0
    return len({row.text(account_at) for row in _csv_rows(table) if row.text(account_at)})


def _timed(
    body: Sequence[RawRow],
    ticket_at: int,
    open_at: int,
    close_at: int | None,
    comment_at: int | None,
) -> list[_Timed]:
    picked: list[tuple[int, int]] = []
    open_texts: list[str] = []
    close_texts: list[str] = []
    for row in body:
        ticket = _int(row.text(ticket_at))
        if ticket is None:
            continue
        if comment_at is not None and _reopened(row.text(comment_at).lower()):
            continue
        picked.append((ticket, row.index))
        open_texts.append(row.text(open_at))
        close_texts.append("" if close_at is None else row.text(close_at))
    opened = _times(open_texts)
    closed = _times(close_texts)
    return [
        _Timed(ticket, index, open_time, close_time)
        for (ticket, index), open_time, close_time in zip(picked, opened, closed, strict=True)
    ]


def _mt4_statement_timed(table: RawTable) -> list[_Timed]:
    """Closed trades with a ticket, minus partial-close remainders and
    rollover reopens (they keep an older open time under a newer ticket)."""
    picked: list[tuple[int, int]] = []
    open_texts: list[str] = []
    close_texts: list[str] = []
    for row in table.kind(rows.KIND_MT4_TRADE):
        ticket_at = _mt4_ticket_at(table, row)
        ticket = _int(row.text(ticket_at))
        if ticket is None or _reopened(_mt4_comment(table, row, ticket_at)):
            continue
        columns = rows.mt4_columns(table, row)
        picked.append((ticket, row.index))
        open_texts.append(row.text(columns["open_time"]))
        close_texts.append(row.text(columns["close_time"]))
    opened = _times(open_texts)
    closed = _times(close_texts)
    return [
        _Timed(ticket, index, open_time, close_time)
        for (ticket, index), open_time, close_time in zip(picked, opened, closed, strict=True)
    ]


def _myfxbook_timed(table: RawTable) -> list[_Timed] | None:
    names = table.header
    ticket_at = _column(names, "ticket")
    open_at = _column(names, "open date")
    action_at = _column(names, "action")
    if ticket_at is None or open_at is None or action_at is None:
        return None
    body = [row for row in _myfxbook_body(table) if row.text(action_at).lower() in _SIDES]
    return _timed(body, ticket_at, open_at, _column(names, "close date"), _column(names, "comment"))


def _fxblue_timed(table: RawTable) -> list[_Timed] | None:
    names = table.header
    ticket_at = _column(names, "ticket")
    open_at = _column(names, "open time")
    type_at = _column(names, "type")
    if ticket_at is None or open_at is None or type_at is None:
        return None
    body = [row for row in _csv_rows(table) if row.text(type_at).lower() == _FXBLUE_CLOSED]
    comment_at = _column(names, "order comment", "comment")
    return _timed(body, ticket_at, open_at, _column(names, "close time"), comment_at)


def _ticket_order(timed: Sequence[_Timed]) -> RawOutcome:
    """Sort by ticket; a time that runs backwards by more than the allowance
    between adjacent tickets is an inversion (open time: a hit; close time:
    a figure)."""
    entries = sorted(
        (entry for entry in timed if entry.opened is not None),
        key=lambda entry: (entry.ticket, entry.index),
    )
    if len(entries) < 2:
        return RawOutcome.skip("no_qualifying_row", figures=(_count("n_rows", len(entries)),))
    allowed = thresholds.TICKET_TIME_BACKWARDS_ALLOWED
    open_inversions: list[int] = []
    close_inversions = 0
    max_open = 0
    max_close = 0
    for previous, current in zip(entries, entries[1:], strict=False):
        if previous.opened is None or current.opened is None:
            continue
        backwards = previous.opened - current.opened
        max_open = max(max_open, _seconds(backwards))
        if backwards > allowed:
            open_inversions.append(current.index)
        if previous.closed is not None and current.closed is not None:
            backwards = previous.closed - current.closed
            max_close = max(max_close, _seconds(backwards))
            if backwards > allowed:
                close_inversions += 1
    figures = (
        _count("n_rows", len(entries)),
        _count("n_hits", len(open_inversions)),
        _count("inversions_open_time", len(open_inversions)),
        _count("inversions_close_time", close_inversions),
        _count("max_backwards_seconds", max_open),
        _count("max_backwards_seconds_close", max_close),
    )
    return RawOutcome(
        hits=len(open_inversions), figures=figures, examples=_examples(open_inversions)
    )


def run_TICKET_ORDER(table: RawTable, ctx: Context) -> RawOutcome:
    timed: list[_Timed] | None
    if table.family == families.MT4_STATEMENT:
        timed = _mt4_statement_timed(table)
    elif table.family == families.MYFXBOOK:
        timed = _myfxbook_timed(table)
    elif table.family == families.FXBLUE:
        accounts = _fxblue_accounts(table)
        if accounts > 1:
            return RawOutcome.skip(
                "several_accounts", figures=(_count("accounts_in_file", accounts),)
            )
        timed = _fxblue_timed(table)
    else:
        return RawOutcome.skip("format_not_covered")
    if timed is None:
        return RawOutcome.skip("no_column")
    return _ticket_order(timed)


# ---------------------------------------------------------------------------
# DUPLICATE_TICKET
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Identified:
    space: str
    """The id space: ids repeat across spaces legitimately (MT5 deal 2, order 2)."""
    group: str
    """The table whose rows are compared for identical text."""
    value: str
    """The id as printed; compared, never emitted."""
    index: int
    texts: tuple[str, ...]


def _mt4_statement_ids(table: RawTable) -> list[_Identified]:
    items: list[_Identified] = []
    for row in table.rows:
        if row.kind not in _MT4_TICKET_KINDS:
            continue
        value = row.text(_mt4_ticket_at(table, row)).strip()
        if _int(value) is not None:
            items.append(_Identified("tickets", row.section, value, row.index, row.texts))
    return items


def _mt5_ids(table: RawTable) -> list[_Identified]:
    """Deal ids, order ids and position ids, each within its own table. The
    Deals' ``Order`` column repeats on partial fills and is never an id here."""
    items: list[_Identified] = []
    for row in table.rows:
        at: int | None
        if row.kind == rows.KIND_MT5_DEAL:
            at, space = rows.mt5_columns(table, row).get("deal"), "deals"
        elif row.kind == rows.KIND_MT5_ORDER:
            at, space = 1, "orders"
        elif row.kind == rows.KIND_MT5_POSITION:
            at, space = rows.mt5_position_columns(table, row)["position"], "positions"
        elif row.kind == rows.KIND_MT5_OPEN_POSITION:
            at, space = 1, "positions"
        else:
            continue
        if at is None:
            continue
        value = row.text(at).strip()
        if _int(value) is not None:
            items.append(_Identified(space, space, value, row.index, row.texts))
    return items


def _csv_ids(body: Sequence[RawRow], at: int, *, digits: bool) -> list[_Identified]:
    items: list[_Identified] = []
    for row in body:
        value = row.text(at).strip()
        if not value or (digits and _int(value) is None):
            continue
        items.append(_Identified("ids", "rows", value, row.index, row.texts))
    return items


def _duplicates(items: Sequence[_Identified], extra: tuple[Figure, ...]) -> RawOutcome:
    if not items:
        return RawOutcome.skip("no_qualifying_row")
    counts: dict[tuple[str, str], int] = {}
    for item in items:
        key = (item.space, item.value)
        counts[key] = counts.get(key, 0) + 1
    repeated = {key for key, count in counts.items() if count > 1}
    examples = [item.index for item in items if (item.space, item.value) in repeated]
    seen_texts: set[tuple[str, tuple[str, ...]]] = set()
    identical = 0
    for item in items:
        shape = (item.group, item.texts)
        if shape in seen_texts:
            identical += 1
        seen_texts.add(shape)
    figures = (
        _count("n_rows", len(items)),
        _count("n_ids", len(counts)),
        _count("n_hits", len(repeated)),
        _count("identical_rows", identical),
        *extra,
    )
    return RawOutcome(hits=len(repeated), figures=figures, examples=_examples(examples))


def _tradingview_groups(table: RawTable) -> RawOutcome:
    """Every trade number owns an entry row and an exit row; the last trade
    may be open with its entry row alone."""
    names = [name.strip().lower() for name in table.header]
    trade_at = next((i for i, name in enumerate(names) if importers._TV_TRADE.match(name)), None)
    type_at = next((i for i, name in enumerate(names) if importers._TV_TYPE.match(name)), None)
    positions = importers._TV_POSITIONS.get(len(names), {})
    if trade_at is None:
        trade_at = positions.get("trade")
    if type_at is None:
        type_at = positions.get("type")
    if trade_at is None:
        return RawOutcome.skip("no_column")
    groups: dict[str, list[RawRow]] = {}
    for row in _csv_rows(table):
        value = row.text(trade_at).strip()
        if value:
            groups.setdefault(value, []).append(row)
    if not groups:
        return RawOutcome.skip("no_qualifying_row")
    numbered = [(number, value) for value in groups if (number := _int(value)) is not None]
    last = max(numbered)[1] if numbered else None
    open_last = 0
    hits: list[int] = []
    for value, members in groups.items():
        if len(members) == 2:
            continue
        role = None if type_at is None else importers._tv_role(members[0].text(type_at))
        if len(members) == 1 and value == last and role != "exit":
            open_last = 1
            continue
        hits.append(members[0].index)
    seen_texts: set[tuple[str, ...]] = set()
    identical = 0
    for row in _csv_rows(table):
        if row.texts in seen_texts:
            identical += 1
        seen_texts.add(row.texts)
    figures = (
        _count("n_rows", sum(len(members) for members in groups.values())),
        _count("n_ids", len(groups)),
        _count("n_hits", len(hits)),
        _count("identical_rows", identical),
        _unmeasured("accounts_in_file"),
        _count("open_last_trade", open_last),
    )
    return RawOutcome(hits=len(hits), figures=figures, examples=_examples(hits))


def run_DUPLICATE_TICKET(table: RawTable, ctx: Context) -> RawOutcome:
    family = table.family
    extra: tuple[Figure, ...] = (_unmeasured("accounts_in_file"), _unmeasured("open_last_trade"))
    items: list[_Identified] | None
    if family == families.MT4_STATEMENT:
        items = _mt4_statement_ids(table)
    elif family in _MT5_FAMILIES:
        items = _mt5_ids(table)
    elif family == families.MYFXBOOK:
        ticket_at = _column(table.header, "ticket")
        body = _myfxbook_body(table)
        items = None if ticket_at is None else _csv_ids(body, ticket_at, digits=True)
    elif family == families.FXBLUE:
        accounts = _fxblue_accounts(table)
        if accounts > 1:
            return RawOutcome.skip(
                "several_accounts", figures=(_count("accounts_in_file", accounts),)
            )
        extra = (_count("accounts_in_file", accounts), _unmeasured("open_last_trade"))
        ticket_at = _column(table.header, "ticket")
        items = None if ticket_at is None else _csv_ids(_csv_rows(table), ticket_at, digits=True)
    elif family == families.TRADINGVIEW:
        return _tradingview_groups(table)
    elif family == families.NINJATRADER:
        trade_at = importers._ninjatrader_index(list(table.header)).get("trade number")
        items = None if trade_at is None else _csv_ids(_csv_rows(table), trade_at, digits=False)
    else:
        return RawOutcome.skip("format_not_covered")
    if items is None:
        return RawOutcome.skip("no_column")
    return _duplicates(items, extra)
