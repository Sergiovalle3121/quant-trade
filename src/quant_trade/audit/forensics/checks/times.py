"""Time checks: ``TIME_SANITY``, ``ROW_ORDER`` and ``MARKET_HOURS``.

Every check here reads the timestamps a platform printed and compares them
with the file's own dates, with the row order and with the weekend closure
of the major currency pairs. Symbols, tickets and comments never leave this
module: figures are counts, codes and ISO dates, examples are row indexes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows, symbols, thresholds
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

# Row roles -------------------------------------------------------------------
#: A buy/sell row with a symbol: examined by every check.
ROLE_TRADE = "trade"
#: A filled MetaTrader 5 order: placement and fill times, no market check.
ROLE_ORDER = "order"
#: A tester event that is not a fill (modify, delete, pending, swap).
ROLE_EVENT = "event"

# Source tables ---------------------------------------------------------------
TABLE_DEALS = "deals"
TABLE_POSITIONS = "positions"
TABLE_OPEN_POSITIONS = "open_positions"
TABLE_ORDERS = "orders"
TABLE_CLOSED = "closed"
TABLE_OPEN = "open"
TABLE_TESTER = "tester"
TABLE_CSV = "csv"

DIRECTION_ASC = "asc"
DIRECTION_DESC = "desc"
#: MetaTrader 5 deals and MetaTrader 4 tester rows are written in time order.
RULE_CHRONOLOGICAL = "chronological"
#: Statements and exports whose direction is the majority of their steps.
RULE_MAJORITY = "majority"

#: A tester's period ends on its last date; rows may fall anywhere on that day.
_PERIOD_END_SLACK = timedelta(days=1)

_TIMED_FAMILIES = frozenset(
    {families.MT4_STATEMENT, families.MT4_TESTER, families.MT5_HISTORY, families.MT5_TESTER}
    | families.CSV_FAMILIES
)
_CHRONOLOGICAL_FAMILIES = frozenset(
    {families.MT5_HISTORY, families.MT5_TESTER, families.MT4_TESTER}
)
_SIDES = frozenset({"buy", "sell"})
_MT5_DIRECTIONS = frozenset({"in", "out", "in/out", "out by"})
_MT4_TESTER_CLOSES = frozenset({"close", "t/p", "s/l", "close by"})
_MT4_TESTER_END = "close at stop"
_MT5_END_OF_TEST = "end of test"
_MT5_FILLED = "filled"
_MYFXBOOK_OPEN_SECTIONS = frozenset({"open trades", "open orders", "open positions"})
_FXBLUE_CLOSED = "closed position"
_FXBLUE_OPEN = "open position"
_NT_SIDES = frozenset({"long", "short", "longue", "court", "courte"})

_MINUTES_PER_WEEK = 7 * 24 * 60
#: Forex closes Friday 22:00 UTC (winter) and reopens 48 h later.
_CLOSURE_START_MINUTE = 4 * 24 * 60 + 22 * 60
_CLOSURE_MINUTES = 48 * 60


@dataclass(frozen=True)
class _Timed:
    """One row's timestamps, read once for the three checks."""

    index: int
    role: str
    table: str
    symbol: str
    opened_text: str
    closed_text: str
    opened: datetime | None
    closed: datetime | None
    chain: int = 0
    """Rows of one ordered run: a subtotal row or a change of account in the
    file starts a new chain, and row order is never compared across chains."""

    @property
    def stamp(self) -> datetime | None:
        """The row's single time: its open time, else its close time."""
        return self.opened if self.opened is not None else self.closed


# ---------------------------------------------------------------------------
# Reading the rows
# ---------------------------------------------------------------------------


def _naive(text: str) -> datetime | None:
    """A MetaTrader cell as a naive datetime (server time read as UTC)."""
    parsed = importers._one_time(text) if importers._is_mt_time(text) else None
    return parsed.replace(tzinfo=None) if parsed is not None else None


def _column_times(values: list[str], *, serial: bool) -> list[datetime | None] | None:
    """One CSV column parsed the way the importers parse it (day-first is
    decided once per column); ``None`` for a column whose day and month
    cannot be told apart, which the importers refuse at upload."""
    try:
        parsed = importers._parse_times(values, serial_numbers=serial).values
    except importers.ReportFormatError:
        return None
    return [when.replace(tzinfo=None) if when is not None else None for when in parsed]


def _timed_rows(table: RawTable) -> tuple[_Timed, ...]:
    family = table.family
    if family == families.MT4_STATEMENT:
        return _mt4_statement_rows(table)
    if family == families.MT4_TESTER:
        return _mt4_tester_rows(table)
    if family in {families.MT5_HISTORY, families.MT5_TESTER}:
        return _mt5_rows(table)
    if family in families.CSV_FAMILIES:
        return _csv_rows(table)
    return ()


def _mt(
    index: int, role: str, source: str, symbol: str, opened: str, closed: str, chain: int = 0
) -> _Timed:
    return _Timed(
        index, role, source, symbol, opened, closed, _naive(opened), _naive(closed), chain
    )


def _is_subtotal(row: RawRow) -> bool:
    """A grouped statement prints a "Total for" line after each group of
    closed trades: a row of the closed section that is neither a trade nor
    a numbered row and starts with a word."""
    first = row.text(0)
    return (
        row.section == rows.SECTION_CLOSED
        and row.kind in {rows.KIND_OTHER, rows.KIND_LABEL}
        and bool(first)
        and not first.isdigit()
    )


def _mt4_statement_rows(table: RawTable) -> tuple[_Timed, ...]:
    found: list[_Timed] = []
    chain = 0
    open_chain = False
    for row in table.rows:
        if open_chain and _is_subtotal(row):
            chain += 1
            open_chain = False
        if row.kind == rows.KIND_MT4_TRADE:
            columns = rows.mt4_columns(table, row)
            open_chain = True
            found.append(
                _mt(
                    row.index,
                    ROLE_TRADE,
                    TABLE_CLOSED,
                    row.text(columns["symbol"]),
                    row.text(columns["open_time"]),
                    row.text(columns["close_time"]),
                    chain,
                )
            )
        elif row.kind == rows.KIND_MT4_OPEN:
            columns = rows.mt4_columns(table, row)
            found.append(
                _mt(
                    row.index,
                    ROLE_TRADE,
                    TABLE_OPEN,
                    row.text(columns["symbol"]),
                    row.text(columns["open_time"]),
                    "",
                )
            )
    return tuple(found)


def _mt4_tester_rows(table: RawTable) -> tuple[_Timed, ...]:
    symbol = table.label("Symbol") or ""
    found: list[_Timed] = []
    for row in table.kind(rows.KIND_MT4_TESTER):
        kind = row.text(2).lower()
        when = row.text(1)
        if kind == _MT4_TESTER_END:
            continue
        if kind in _SIDES:
            found.append(_mt(row.index, ROLE_TRADE, TABLE_TESTER, symbol, when, ""))
        elif kind in _MT4_TESTER_CLOSES:
            found.append(_mt(row.index, ROLE_TRADE, TABLE_TESTER, symbol, "", when))
        else:
            found.append(_mt(row.index, ROLE_EVENT, TABLE_TESTER, symbol, when, ""))
    return tuple(found)


def _mt5_order_cells(table: RawTable, row: RawRow) -> tuple[int, int]:
    """``(fill time, state)`` positions of an Orders row: from its header
    when the header is in English, else the eleven-column layout."""
    names = [text.strip().lower() for text in table.header_of(row)]
    if "state" in names:
        return (names.index("time") if "time" in names else 8), names.index("state")
    return 8, 9


def _mt5_rows(table: RawTable) -> tuple[_Timed, ...]:
    found: list[_Timed] = []
    for row in table.rows:
        if row.kind == rows.KIND_MT5_DEAL:
            columns = rows.mt5_columns(table, row)
            kind = row.text(columns.get("type", 3)).lower()
            direction = row.text(columns.get("direction", 4)).lower()
            comment_at = columns.get("comment")
            comment = row.text(comment_at).lower() if comment_at is not None else ""
            if kind not in _SIDES or direction not in _MT5_DIRECTIONS:
                continue
            if _MT5_END_OF_TEST in comment:
                continue
            found.append(
                _mt(
                    row.index,
                    ROLE_TRADE,
                    TABLE_DEALS,
                    row.text(columns.get("symbol", 2)),
                    row.text(columns.get("time", 0)),
                    "",
                )
            )
        elif row.kind == rows.KIND_MT5_POSITION:
            columns = rows.mt5_position_columns(table, row)
            if row.text(columns["type"]).lower() not in _SIDES:
                continue
            found.append(
                _mt(
                    row.index,
                    ROLE_TRADE,
                    TABLE_POSITIONS,
                    row.text(columns["symbol"]),
                    row.text(columns["open"]),
                    row.text(columns["close"]),
                )
            )
        elif row.kind == rows.KIND_MT5_OPEN_POSITION:
            if row.text(3).lower() not in _SIDES:
                continue
            found.append(
                _mt(row.index, ROLE_TRADE, TABLE_OPEN_POSITIONS, row.text(2), row.text(0), "")
            )
        elif row.kind == rows.KIND_MT5_ORDER:
            fill_at, state_at = _mt5_order_cells(table, row)
            if row.text(state_at).lower() != _MT5_FILLED:
                continue
            found.append(
                _mt(
                    row.index, ROLE_ORDER, TABLE_ORDERS, row.text(2), row.text(0), row.text(fill_at)
                )
            )
    return tuple(found)


@dataclass(frozen=True)
class _CsvPick:
    index: int
    symbol: str
    opened: str
    closed: str
    chain: int = 0


def _csv_rows(table: RawTable) -> tuple[_Timed, ...]:
    names = [text.strip().lower() for text in table.header]
    body = table.kind(rows.KIND_CSV)
    family = table.family
    picks: list[_CsvPick] = []
    if family == families.MYFXBOOK:
        picks = _myfxbook_picks(names, body)
    elif family == families.MQL5_SIGNAL:
        picks = _mql5_picks(names, body)
    elif family == families.FXBLUE:
        picks = _fxblue_picks(names, body)
    elif family == families.TRADINGVIEW:
        picks = _tradingview_picks(table, body)
    elif family == families.NINJATRADER:
        picks = _ninjatrader_picks(table, body)
    serial = table.source_format in families.XLSX_FORMATS
    opened = _column_times([pick.opened for pick in picks], serial=serial)
    closed = _column_times([pick.closed for pick in picks], serial=serial)
    return tuple(
        _Timed(
            pick.index,
            ROLE_TRADE,
            TABLE_CSV,
            pick.symbol,
            pick.opened if opened is not None else "",
            pick.closed if closed is not None else "",
            opened[position] if opened is not None else None,
            closed[position] if closed is not None else None,
            pick.chain,
        )
        for position, pick in enumerate(picks)
    )


def _at(names: list[str], name: str) -> int | None:
    return names.index(name) if name in names else None


def _myfxbook_picks(names: list[str], body: tuple[RawRow, ...]) -> list[_CsvPick]:
    opened_at, closed_at = _at(names, "open date"), _at(names, "close date")
    symbol_at, action_at = _at(names, "symbol"), _at(names, "action")
    if None in (opened_at, closed_at, symbol_at, action_at):
        return []
    assert opened_at is not None and closed_at is not None
    assert symbol_at is not None and action_at is not None
    picks: list[_CsvPick] = []
    for row in body:
        first = row.text(0).lower()
        if first in _MYFXBOOK_OPEN_SECTIONS or (row.text(1).lower(), row.text(2).lower()) == (
            "ticket",
            "open date",
        ):
            break  # the positions still open follow; they are not history
        if row.text(action_at).lower() in _SIDES:
            picks.append(
                _CsvPick(row.index, row.text(symbol_at), row.text(opened_at), row.text(closed_at))
            )
    return picks


def _mql5_picks(names: list[str], body: tuple[RawRow, ...]) -> list[_CsvPick]:
    kind_at, symbol_at = _at(names, "type"), _at(names, "symbol")
    if kind_at is None or symbol_at is None or names.count("time") < 2:
        return []
    closed_at = names.index("time", 1)
    return [
        _CsvPick(row.index, row.text(symbol_at), row.text(0), row.text(closed_at))
        for row in body
        if row.text(kind_at).lower() in _SIDES
    ]


def _fxblue_picks(names: list[str], body: tuple[RawRow, ...]) -> list[_CsvPick]:
    kind_at, symbol_at = _at(names, "type"), _at(names, "symbol")
    opened_at, closed_at = _at(names, "open time"), _at(names, "close time")
    if None in (kind_at, symbol_at, opened_at, closed_at):
        return []
    assert kind_at is not None and symbol_at is not None
    assert opened_at is not None and closed_at is not None
    picks: list[_CsvPick] = []
    for row in body:
        kind = row.text(kind_at).lower()
        if kind == _FXBLUE_CLOSED:
            picks.append(
                _CsvPick(row.index, row.text(symbol_at), row.text(opened_at), row.text(closed_at))
            )
        elif kind == _FXBLUE_OPEN:  # its close time is the epoch placeholder
            picks.append(_CsvPick(row.index, row.text(symbol_at), row.text(opened_at), ""))
    return picks


def _tradingview_picks(table: RawTable, body: tuple[RawRow, ...]) -> list[_CsvPick]:
    try:
        columns, _currency = importers._tv_columns(list(table.header))
    except importers.ReportFormatError:
        return []
    time_at, kind_at = columns["time"], columns["type"]
    picks: list[_CsvPick] = []
    for row in body:
        when = row.text(time_at)
        if not when:
            continue
        # A list of trades holds an entry row and an exit row per trade; the
        # exit is printed first, so only entry rows carry an order.
        if importers._tv_role(row.text(kind_at)) == "exit":
            picks.append(_CsvPick(row.index, "", "", when))
        else:
            picks.append(_CsvPick(row.index, "", when, ""))
    return picks


def _ninjatrader_picks(table: RawTable, body: tuple[RawRow, ...]) -> list[_CsvPick]:
    columns = importers._ninjatrader_index(list(table.header))
    needed = ("entry time", "exit time", "instrument", "market pos.")
    if any(name not in columns for name in needed):
        return []
    # A grid may list several accounts one after another: each account's
    # trades form their own ordered run.
    account_at = columns.get("account")
    chains: dict[str, int] = {}
    picks: list[_CsvPick] = []
    for row in body:
        if row.text(columns["market pos."]).strip().lower() not in _NT_SIDES:
            continue
        account = row.text(account_at).strip() if account_at is not None else ""
        chain = chains.setdefault(account, len(chains))
        picks.append(
            _CsvPick(
                row.index,
                row.text(columns["instrument"]),
                row.text(columns["entry time"]),
                row.text(columns["exit time"]),
                chain,
            )
        )
    return picks


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _count(key: str, value: int) -> Figure:
    return (key, str(value), MEASURED)


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _examples(indexes: list[int]) -> tuple[int, ...]:
    return tuple(sorted(indexes)[:MAX_EXAMPLES])


def _report_date(ctx: Context) -> tuple[datetime | None, str]:
    """The date rows are compared with: the printed header date, or the day
    after a tester's period end."""
    header = ctx.header
    if header.report_date is None:
        return None, ""
    if header.report_date_source == "period_end":
        return header.report_date + _PERIOD_END_SLACK, header.report_date_source
    return header.report_date, header.report_date_source


# ---------------------------------------------------------------------------
# TIME_SANITY
# ---------------------------------------------------------------------------


def run_TIME_SANITY(table: RawTable, ctx: Context) -> RawOutcome:
    """Unparseable times, closes before opens and rows after the report date."""
    if table.family not in _TIMED_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    loose = table.family in families.CSV_FAMILIES
    report_date, source = _report_date(ctx)
    limit = report_date + thresholds.AFTER_REPORT_DATE_ALLOWED if report_date is not None else None
    n_rows = unparseable = before = after = backwards = zero = 0
    max_ahead = 0
    hits: list[int] = []
    for timed in _timed_rows(table):
        cells = [
            (text, when)
            for text, when in ((timed.opened_text, timed.opened), (timed.closed_text, timed.closed))
            if text
        ]
        if not cells:
            continue
        n_rows += 1
        row_unparseable = row_after = row_before = False
        for text, when in cells:
            if when is None:
                row_unparseable = row_unparseable or loose or importers._is_mt_time(text)
                continue
            if report_date is not None:
                ahead = int((when - report_date).total_seconds())
                max_ahead = max(max_ahead, ahead)
                if limit is not None and when > limit:
                    row_after = True
        if timed.opened is not None and timed.closed is not None:
            gap = timed.closed - timed.opened
            if gap < -thresholds.CLOSE_BEFORE_OPEN_ALLOWED:
                row_before = True
            elif gap < timedelta(0):
                backwards += 1
            elif gap == timedelta(0) and timed.role == ROLE_TRADE:
                zero += 1  # orders fill at their placement second: not counted
        unparseable += int(row_unparseable)
        before += int(row_before)
        after += int(row_after)
        if row_unparseable or row_before or row_after:
            hits.append(timed.index)
    measured: tuple[Figure, ...] = (
        _count("n_rows", n_rows),
        _count("n_hits", len(hits)),
        _count("unparseable", unparseable),
        _count("close_before_open_over_1h", before),
        _count("backwards_within_1h", backwards),
        _count("zero_duration", zero),
    )
    if report_date is None:
        # Without a printed report date (CSV exports, some old statements)
        # the calendar and close-before-open rules still measure; only the
        # after-report-date rule is out of reach.
        figures = measured + (
            ("after_report_date", "no_header_date", NOT_MEASURED),
            ("report_date", "", NOT_MEASURED),
            ("report_date_source", "", NOT_MEASURED),
            ("max_ahead_seconds", "0", NOT_MEASURED),
        )
    else:
        figures = measured + (
            _count("after_report_date", after),
            ("report_date", _iso(report_date), DECLARED),
            ("report_date_source", source, DECLARED),
            _count("max_ahead_seconds", max_ahead),
        )
    if n_rows == 0:
        return RawOutcome.skip("no_qualifying_row", figures=figures)
    return RawOutcome(hits=len(hits), figures=figures, examples=_examples(hits))


# ---------------------------------------------------------------------------
# ROW_ORDER
# ---------------------------------------------------------------------------


#: ``(row index, sort key, chain)`` in file order; the key is an integer
#: (seconds of a time, or a ticket number) so every candidate compares alike.
_Stamps = list[tuple[int, int, int]]
_EPOCH = datetime(1970, 1, 1)

#: Order keys: which column of a row the platform sorts by.
KEY_DEAL = "deal"
KEY_EVENT = "event"
KEY_TICKET = "ticket"
KEY_OPEN = "open"
KEY_CLOSE = "close"
KEY_ENTRY = "entry"
KEY_EXIT = "exit"


def _seconds(when: datetime) -> int:
    return int((when - _EPOCH).total_seconds())


def _stamps(timed: tuple[_Timed, ...], pick: str, source: str | None = None) -> _Stamps:
    found: _Stamps = []
    for item in timed:
        if source is not None and item.table != source:
            continue
        when = item.opened if pick == "opened" else item.closed if pick == "closed" else item.stamp
        if when is not None:
            found.append((item.index, _seconds(when), item.chain))
    return found


def _ticket_stamps(table: RawTable, timed: tuple[_Timed, ...]) -> _Stamps:
    """A statement's closed trades by their ticket number, the column the
    terminal itself sorts by (a filled pending order keeps the ticket of
    its placement, so its open time may precede its neighbours')."""
    chains = {item.index: item.chain for item in timed if item.table == TABLE_CLOSED}
    found: _Stamps = []
    for row in table.rows:
        if row.index not in chains:
            continue
        names = [text.strip().lower() for text in table.header_of(row)]
        ticket = row.text(names.index("ticket") if "ticket" in names else 0)
        if ticket.isdigit():
            found.append((row.index, int(ticket), chains[row.index]))
    return found


def _order_candidates(table: RawTable) -> tuple[tuple[str, _Stamps], ...]:
    """The keys a family's rows may be sorted by, in file order, the
    platform's own first: deal times; tester event times; a statement's
    tickets, else its open or close times (the Account History tab exports
    in whatever column it was sorted by); the close times of account
    exports; a TradingView list's entry rows (its exit row precedes the
    entry row of the same trade); a NinjaTrader grid's exit or entry times
    (the grid is exported as the user sorted it)."""
    family = table.family
    timed = _timed_rows(table)
    if family in {families.MT5_HISTORY, families.MT5_TESTER}:
        return ((KEY_DEAL, _stamps(timed, "opened", TABLE_DEALS)),)
    if family == families.MT4_TESTER:
        return ((KEY_EVENT, _stamps(timed, "stamp")),)
    if family == families.MT4_STATEMENT:
        return (
            (KEY_TICKET, _ticket_stamps(table, timed)),
            (KEY_OPEN, _stamps(timed, "opened", TABLE_CLOSED)),
            (KEY_CLOSE, _stamps(timed, "closed", TABLE_CLOSED)),
        )
    if family == families.TRADINGVIEW:
        return ((KEY_ENTRY, _stamps(timed, "opened")),)
    if family == families.NINJATRADER:
        return ((KEY_EXIT, _stamps(timed, "closed")), (KEY_ENTRY, _stamps(timed, "opened")))
    return ((KEY_CLOSE, _stamps(timed, "closed")),)


@dataclass(frozen=True)
class _Ordering:
    key: str
    n_rows: int
    hits: tuple[int, ...]
    direction: str
    ties: int


def _steps(stamps: _Stamps) -> list[tuple[int, int, int]]:
    """``(row index of the later row, earlier key, later key)`` for every
    adjacent pair of one chain."""
    return [
        (index, earlier, later)
        for (_, earlier, chain), (index, later, next_chain) in zip(stamps, stamps[1:], strict=False)
        if chain == next_chain
    ]


def _ordering(key: str, stamps: _Stamps, rule: str) -> _Ordering:
    steps = _steps(stamps)
    rising = sum(1 for _, earlier, later in steps if later > earlier)
    falling = sum(1 for _, earlier, later in steps if later < earlier)
    ties = len(steps) - rising - falling
    if rule == RULE_CHRONOLOGICAL:
        direction = DIRECTION_ASC
    else:
        direction = DIRECTION_DESC if falling > rising else DIRECTION_ASC
    hits = tuple(
        index
        for index, earlier, later in steps
        if (later < earlier if direction == DIRECTION_ASC else later > earlier)
    )
    return _Ordering(key, len(stamps), hits, direction, ties)


def run_ROW_ORDER(table: RawTable, ctx: Context) -> RawOutcome:
    """Adjacent rows whose keys run against the table's direction."""
    family = table.family
    if family not in _TIMED_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    rule = RULE_CHRONOLOGICAL if family in _CHRONOLOGICAL_FAMILIES else RULE_MAJORITY
    orderings = [
        _ordering(key, stamps, rule)
        for key, stamps in _order_candidates(table)
        if len(_steps(stamps)) >= 1
    ]
    if not orderings:
        return RawOutcome.skip("no_qualifying_row")
    best = orderings[0]
    for candidate in orderings[1:]:
        if len(candidate.hits) < len(best.hits):
            best = candidate
    figures: tuple[Figure, ...] = (
        _count("n_rows", best.n_rows),
        _count("n_hits", len(best.hits)),
        ("direction", best.direction, MEASURED),
        ("direction_rule", rule, DECLARED),
        ("order_key", best.key, DECLARED),
        _count("ties", best.ties),
    )
    return RawOutcome(hits=len(best.hits), figures=figures, examples=_examples(list(best.hits)))


# ---------------------------------------------------------------------------
# MARKET_HOURS
# ---------------------------------------------------------------------------


def _minute_of_week(when: datetime) -> int:
    return when.weekday() * 1440 + when.hour * 60 + when.minute


def _in_window(minute: int, window: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    (start_day, start_hour), (end_day, end_hour) = window
    return start_day * 1440 + start_hour * 60 <= minute < end_day * 1440 + end_hour * 60


def _is_holiday(when: datetime) -> bool:
    return (when.month, when.day) in {(12, 25), (1, 1)}


def _inferred_offset(minutes: list[int]) -> int:
    """The server offset, in minutes, that puts the fewest timestamps inside
    the 48 h weekend closure; ties go to the offset closest to zero."""
    low, high = thresholds.OFFSET_RANGE_MINUTES
    best_offset, best_count = 0, len(minutes) + 1
    for offset in range(low, high + 1, thresholds.OFFSET_STEP_MINUTES):
        count = sum(
            1
            for minute in minutes
            if (minute - offset - _CLOSURE_START_MINUTE) % _MINUTES_PER_WEEK < _CLOSURE_MINUTES
        )
        if count < best_count or (
            count == best_count and (abs(offset), -offset) < (abs(best_offset), -best_offset)
        ):
            best_offset, best_count = offset, count
    return best_offset


def run_MARKET_HOURS(table: RawTable, ctx: Context) -> RawOutcome:
    """Trades of the major pairs stamped inside the weekend closure."""
    family = table.family
    if family not in _TIMED_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    if family == families.TRADINGVIEW:
        return RawOutcome.skip("no_column")
    listed: list[tuple[_Timed, str]] = []
    for timed in _timed_rows(table):
        if timed.role != ROLE_TRADE:
            continue
        pair = symbols.normalise_pair(timed.symbol)
        if pair is not None:
            listed.append((timed, pair))
    if not listed:
        return RawOutcome.skip("no_listed_symbol")
    pairs: set[str] = set()
    minutes: list[int] = []
    n_rows = counted = core = holidays = 0
    hits: list[int] = []
    for timed, pair in listed:
        stamps = [when for when in (timed.opened, timed.closed) if when is not None]
        if not stamps:
            continue
        n_rows += 1
        pairs.add(pair)
        row_counted = row_core = False
        for when in stamps:
            minute = _minute_of_week(when)
            minutes.append(minute)
            row_counted = row_counted or _in_window(minute, thresholds.WEEKEND_COUNTED)
            row_core = row_core or _in_window(minute, thresholds.WEEKEND_CORE)
            holidays += int(_is_holiday(when))
        counted += int(row_counted)
        core += int(row_core)
        if row_counted:
            hits.append(timed.index)
    if not minutes:
        return RawOutcome.skip("no_qualifying_row")
    figures: tuple[Figure, ...] = (
        _count("n_rows", n_rows),
        _count("n_hits", counted),
        _count("symbols_measured", len(pairs)),
        _count("timestamps_measured", len(minutes)),
        _count("core_hits", core),
        ("inferred_offset_minutes", str(_inferred_offset(minutes)), MEASURED),
        _count("holiday_hits", holidays),
        ("window", thresholds.WEEKEND_WINDOW_CODE, DECLARED),
    )
    return RawOutcome(hits=len(hits), figures=figures, examples=_examples(hits))


__all__ = ["run_MARKET_HOURS", "run_ROW_ORDER", "run_TIME_SANITY"]
