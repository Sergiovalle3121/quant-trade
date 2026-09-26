"""Price checks: ``SLTP_FILL``, ``PNL_SIGN``, ``PRICE_IMPLIED_PNL`` and
``PRICE_PRECISION`` (spec §3.11 to §3.14).

A take-profit fills at its level or better and a stop-loss at its level or
worse (D8, inequalities, never equalities); the gross result of a closed
trade carries the sign of its price move; on a symbol quoted in the account
currency the gross result is the price move times the volume times one
contract size (D9); a terminal prints every price of a symbol with that
symbol's digits. Every value is read as ``Decimal`` from the printed text.
Symbols, tickets and comments never leave this module: figures are counts,
examples are raw row indexes (D16). Scoping rules found on genuine files are
rows excluded by a property of the terminal, never a nudged threshold (D3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, money, rows, symbols, thresholds
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import MAX_EXAMPLES, MEASURED, Figure, RawOutcome
from quant_trade.audit.forensics.rows import RawRow, RawTable

SIDE_LONG = "long"
SIDE_SHORT = "short"
MARKER_TP = "tp"
MARKER_SL = "sl"

_SIDE_WORDS = {
    "buy": SIDE_LONG,
    "sell": SIDE_SHORT,
    "long": SIDE_LONG,
    "short": SIDE_SHORT,
    "longue": SIDE_LONG,
    "court": SIDE_SHORT,
    "courte": SIDE_SHORT,
}
#: MetaTrader 5 deals that close (all or part of) a position.
_MT5_EXIT_DIRECTIONS = frozenset({"out", "out by", "in/out"})
#: The server's own comment on a deal filled by a take-profit or stop-loss:
#: ``[tp 1.08700]`` on a history report, ``sl 1.09900`` on a tester report.
_MT5_MARKER = re.compile(r"(?:^|\[)(tp|sl) ([0-9][0-9.,]*)\]?$", re.IGNORECASE)
_MYFXBOOK_OPEN_SECTIONS = frozenset({"open trades", "open orders", "open positions"})
_FXBLUE_CLOSED = "closed position"
_TV_OPEN_SIGNALS = frozenset({"open", "offen"})
_TV_VALUE = re.compile(r"^(position size \(value\)|size \(value\))( \S+)?$")
_NT_FEES = ("commission", "clearing fee", "exchange fee", "ip fee", "nfa fee")
#: MetaTrader 4 tester rows of a position closed and reopened at rollover.
_MT4_SWAP_OPEN = "swap open"
_MT4_MODIFY = "modify"
#: Families whose stop-loss fills are judged. A strategy tester executes a
#: stop at its level or at the first tick beyond it; a live server under
#: market execution fills the triggered stop at the market, which the
#: genuine corpus shows a few points better than the level (scoping, D3).
_SL_JUDGED_FAMILIES = frozenset({families.MT5_TESTER})

_PNL_SIGN_FAMILIES = frozenset(
    {
        families.MT4_STATEMENT,
        families.MT5_HISTORY,
        families.MYFXBOOK,
        families.MQL5_SIGNAL,
        families.FXBLUE,
        families.TRADINGVIEW,
        families.NINJATRADER,
    }
)
_IMPLIED_PNL_FAMILIES = frozenset(
    {
        families.MT4_STATEMENT,
        families.MT5_HISTORY,
        families.MYFXBOOK,
        families.MQL5_SIGNAL,
        families.FXBLUE,
        families.TRADINGVIEW,
    }
)
#: Exports that trim trailing zeros: printed digits say nothing there. The
#: MQL5 signal CSV is one of them (its prices are floats as written, down
#: to ``2084.6`` and float noise such as sixteen decimals; genuine corpus).
_VARIABLE_PRECISION_FAMILIES = frozenset(
    {
        families.MYFXBOOK,
        families.FXBLUE,
        families.TRADINGVIEW,
        families.NINJATRADER,
        families.MQL5_SIGNAL,
    }
)
_FIXED_PRECISION_FAMILIES = frozenset(
    {families.MT4_STATEMENT, families.MT4_TESTER, families.MT5_HISTORY, families.MT5_TESTER}
)
#: Families whose period can span a broker's digit migration (4 to 5, 2 to
#: 3): a live account's record. A tester run prices one symbol with one
#: digit count from start to end.
_MIGRATION_FAMILIES = frozenset({families.MT4_STATEMENT, families.MT5_HISTORY})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _count(key: str, value: int) -> Figure:
    return (key, str(value), MEASURED)


def _examples(indexes: list[int]) -> tuple[int, ...]:
    return tuple(sorted(set(indexes))[:MAX_EXAMPLES])


def _names(texts: tuple[str, ...]) -> list[str]:
    return [text.strip().lower() for text in texts]


def _compact(name: str) -> str:
    return re.sub(r"\s+", "", name)


def _at(names: list[str], name: str) -> int | None:
    return names.index(name) if name in names else None


def _side(text: str) -> str | None:
    return _SIDE_WORDS.get(text.strip().lower())


def _sign(side: str) -> Decimal:
    return Decimal(1) if side == SIDE_LONG else Decimal(-1)


def _money(text: str, *, comma_decimal: bool = False) -> Decimal | None:
    """The printed cell as a ``Decimal``; with ``comma_decimal`` the comma
    is the decimal mark whatever follows it (a ``;``-delimited export)."""
    if not comma_decimal:
        return money.parse_money(text)
    value = text.strip()
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    value = re.sub(r"[\s$€£¥]", "", value).replace(".", "").replace(",", ".")
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return -abs(number) if negative else number


def _mt4_level_columns(names: list[str], columns: dict[str, int]) -> tuple[int, int]:
    """``(S/L, T/P)`` positions of a statement row: from the header when it
    names them, else the two cells after the open price."""
    compact = [_compact(name) for name in names]
    sl_at = compact.index("s/l") if "s/l" in compact else columns["open_price"] + 1
    tp_at = compact.index("t/p") if "t/p" in compact else columns["open_price"] + 2
    return sl_at, tp_at


def _mt4_comment(table: RawTable, row: RawRow, names: list[str]) -> str:
    """The row's comment: the ticket cell's ``title`` (a title equal to the
    ticket is the numbered layout's tooltip, not a comment), else the Comment
    column of the numbered layout, else the single text of the comment row
    the 2009 builds print right after the trade."""
    ticket_at = names.index("ticket") if "ticket" in names else 0
    comment_at = names.index("comment") if "comment" in names else -1
    ticket = row.text(ticket_at).strip()
    title = row.cells[ticket_at].title.strip() if 0 <= ticket_at < len(row.cells) else ""
    if title and title != ticket:
        return title
    if comment_at >= 0 and row.text(comment_at).strip():
        return row.text(comment_at).strip()
    following = row.index + 1
    if following < len(table.rows):
        candidate = table.rows[following]
        if (
            candidate.index == following
            and candidate.kind == rows.KIND_OTHER
            and candidate.section == row.section
        ):
            texts = [text.strip() for text in candidate.texts if text.strip()]
            if len(texts) == 1:
                return texts[0]
    return ""


def _mt5_order_columns(names: list[str]) -> tuple[int, int, int, int]:
    """``(symbol, price, S/L, T/P)`` positions of an Orders row: from an
    English header, else the eleven-column layout."""
    compact = [_compact(name) for name in names]
    if "symbol" in compact and "price" in compact and "s/l" in compact and "t/p" in compact:
        return (
            compact.index("symbol"),
            compact.index("price"),
            compact.index("s/l"),
            compact.index("t/p"),
        )
    return 2, 5, 6, 7


# ---------------------------------------------------------------------------
# SLTP_FILL
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fill:
    """A close the platform marked as a take-profit or stop-loss fill."""

    index: int
    marker: str
    side: str
    """The side of the position that was closed."""
    close: Decimal | None
    level: Decimal | None


def _mt4_fills(table: RawTable) -> list[_Fill]:
    found: list[_Fill] = []
    for row in table.kind(rows.KIND_MT4_TRADE):
        names = _names(table.header_of(row))
        comment = _mt4_comment(table, row, names).lower()
        if "[tp]" in comment:
            marker = MARKER_TP
        elif "[sl]" in comment:
            marker = MARKER_SL
        else:
            continue
        columns = rows.mt4_columns(table, row)
        side = _side(row.text(columns["type"]))
        if side is None:
            continue
        sl_at, tp_at = _mt4_level_columns(names, columns)
        level_at = tp_at if marker == MARKER_TP else sl_at
        found.append(
            _Fill(
                index=row.index,
                marker=marker,
                side=side,
                close=_money(row.text(columns["close_price"])),
                level=_money(row.text(level_at)),
            )
        )
    return found


def _mt5_fills(table: RawTable) -> list[_Fill]:
    found: list[_Fill] = []
    for row in table.kind(rows.KIND_MT5_DEAL):
        columns = rows.mt5_columns(table, row)
        comment_at = columns.get("comment")
        if comment_at is None:
            continue
        match = _MT5_MARKER.search(row.text(comment_at).strip())
        if match is None:
            continue
        if row.text(columns.get("direction", -1)).strip().lower() not in _MT5_EXIT_DIRECTIONS:
            continue
        deal_side = _side(row.text(columns.get("type", -1)))
        if deal_side is None:
            continue
        found.append(
            _Fill(
                index=row.index,
                marker=match.group(1).lower(),
                side=SIDE_SHORT if deal_side == SIDE_LONG else SIDE_LONG,
                close=_money(row.text(columns.get("price", -1))),
                level=_money(match.group(2)),
            )
        )
    return found


def _fill_violates(marker: str, side: str, close: Decimal, level: Decimal) -> bool:
    """A take-profit fills at its level or better, a stop-loss at its level
    or worse; positive slippage is allowed by the inequality (D8)."""
    if marker == MARKER_TP:
        return close < level if side == SIDE_LONG else close > level
    return close > level if side == SIDE_LONG else close < level


def run_SLTP_FILL(table: RawTable, ctx: Context) -> RawOutcome:
    """Every close the platform marked ``[tp]`` / ``[sl]`` against the level
    it names: a statement's S/L or T/P cell, a deal comment's price.

    A statement row whose level cell reads zero was cleared after the fill
    and is ``levels_cleared``, not measured. A take-profit is a limit order
    and fills at its level or better everywhere. A stop-loss fills at its
    level or worse on a tester; on a live account under market execution it
    fills at the market once triggered, and genuine statements show it a few
    points better than the level, so there a better stop fill is
    ``sl_better_fills``, never a hit (D3 scoping by the generating terminal).
    """
    family = table.family
    if family == families.MT4_STATEMENT:
        fills = _mt4_fills(table)
    elif family in {families.MT5_HISTORY, families.MT5_TESTER}:
        fills = _mt5_fills(table)
    else:
        return RawOutcome.skip("format_not_covered")
    judge_stops = family in _SL_JUDGED_FAMILIES
    n_rows = n_tp = n_sl = tp_hits = sl_hits = sl_better = cleared = 0
    hits: list[int] = []
    for fill in fills:
        if fill.close is None:
            continue
        n_rows += 1
        if fill.level is None or fill.level == 0:
            cleared += 1
            continue
        violates = _fill_violates(fill.marker, fill.side, fill.close, fill.level)
        if fill.marker == MARKER_TP:
            n_tp += 1
            if violates:
                tp_hits += 1
                hits.append(fill.index)
            continue
        n_sl += 1
        if violates:
            sl_better += 1
            if judge_stops:
                sl_hits += 1
                hits.append(fill.index)
    figures: tuple[Figure, ...] = (
        _count("n_rows", n_rows),
        _count("n_hits", len(hits)),
        _count("n_tp", n_tp),
        _count("n_sl", n_sl),
        _count("tp_hits", tp_hits),
        _count("sl_hits", sl_hits),
        _count("sl_better_fills", sl_better),
        _count("levels_cleared", cleared),
    )
    if n_tp + n_sl == 0:
        return RawOutcome.skip("no_qualifying_row", figures)
    return RawOutcome(hits=len(hits), figures=figures, examples=_examples(hits))


# ---------------------------------------------------------------------------
# Closed trades, read once for PNL_SIGN and PRICE_IMPLIED_PNL
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Trip:
    index: int
    symbol: str
    side: str
    entry: Decimal
    exit: Decimal
    gross: Decimal
    volume: Decimal | None
    account: str = ""


@dataclass(frozen=True)
class _Trips:
    trips: tuple[_Trip, ...] = ()
    unparsed: int = 0
    reason: str = ""
    """A ``NOT_MEASURED`` reason when the table or a column is missing."""
    volume_column: bool = True


def _trip(
    index: int,
    symbol: str,
    side: str | None,
    entry: Decimal | None,
    exit_: Decimal | None,
    gross: Decimal | None,
    volume: Decimal | None,
    account: str = "",
) -> _Trip | None:
    if side is None or entry is None or exit_ is None or gross is None:
        return None
    return _Trip(index, symbol, side, entry, exit_, gross, volume, account)


def _collect(found: list[_Trip | None], **extra: object) -> _Trips:
    trips = tuple(item for item in found if item is not None)
    unparsed = sum(1 for item in found if item is None)
    volume_column = bool(extra.get("volume_column", True))
    return _Trips(trips=trips, unparsed=unparsed, volume_column=volume_column)


def _mt4_statement_trips(table: RawTable) -> _Trips:
    found: list[_Trip | None] = []
    for row in table.kind(rows.KIND_MT4_TRADE):
        columns = rows.mt4_columns(table, row)
        found.append(
            _trip(
                row.index,
                row.text(columns["symbol"]).strip().lower(),
                _side(row.text(columns["type"])),
                _money(row.text(columns["open_price"])),
                _money(row.text(columns["close_price"])),
                _money(row.text(columns["profit"])),
                _money(row.text(columns["size"])),
            )
        )
    return _collect(found)


def _mt5_position_trips(table: RawTable) -> _Trips:
    positions = table.kind(rows.KIND_MT5_POSITION)
    if not positions:
        return _Trips(reason="no_table")
    found: list[_Trip | None] = []
    for row in positions:
        columns = rows.mt5_position_columns(table, row)
        found.append(
            _trip(
                row.index,
                row.text(columns["symbol"]).strip().lower(),
                _side(row.text(columns["type"])),
                _money(row.text(columns["price"])),
                _money(row.text(columns["close_price"])),
                _money(row.text(columns["profit"])),
                _money(row.text(columns["volume"])),
            )
        )
    return _collect(found)


def _myfxbook_trips(table: RawTable) -> _Trips:
    names = _names(table.header)
    action_at, symbol_at = _at(names, "action"), _at(names, "symbol")
    entry_at, exit_at = _at(names, "open price"), _at(names, "close price")
    profit_at = _at(names, "profit")
    if None in (action_at, entry_at, exit_at, profit_at):
        return _Trips(reason="no_column")
    assert action_at is not None and entry_at is not None
    assert exit_at is not None and profit_at is not None
    volume_at = _at(names, "units/lots")
    if volume_at is None:
        volume_at = _at(names, "lots")
    commission_at, swap_at = _at(names, "commission"), _at(names, "swap")
    found: list[_Trip | None] = []
    for row in table.kind(rows.KIND_CSV):
        first = row.text(0).lower()
        if first in _MYFXBOOK_OPEN_SECTIONS or (
            row.text(1).lower(),
            row.text(2).lower(),
        ) == ("ticket", "open date"):
            break  # the positions still open follow; they are not history
        side = _side(row.text(action_at))
        if side is None:
            continue  # deposits, withdrawals, pending orders
        net = _money(row.text(profit_at))
        commission = _money(row.text(commission_at)) if commission_at is not None else None
        swap = _money(row.text(swap_at)) if swap_at is not None else None
        gross = net - (commission or Decimal(0)) - (swap or Decimal(0)) if net is not None else None
        found.append(
            _trip(
                row.index,
                row.text(symbol_at).strip().lower() if symbol_at is not None else "",
                side,
                _money(row.text(entry_at)),
                _money(row.text(exit_at)),
                gross,
                _money(row.text(volume_at)) if volume_at is not None else None,
            )
        )
    return _collect(found, volume_column=volume_at is not None)


def _mql5_trips(table: RawTable) -> _Trips:
    names = _names(table.header)
    kind_at, symbol_at = _at(names, "type"), _at(names, "symbol")
    volume_at, profit_at = _at(names, "volume"), _at(names, "profit")
    if kind_at is None or profit_at is None or names.count("time") < 2 or "price" not in names:
        return _Trips(reason="no_column")
    entry_at = names.index("price")
    close_at = names.index("time", 1)
    if "price" not in names[close_at:]:
        return _Trips(reason="no_column")
    exit_at = names.index("price", close_at)
    found: list[_Trip | None] = []
    for row in table.kind(rows.KIND_CSV):
        side = _side(row.text(kind_at))
        if side is None:
            continue  # balance rows and cancelled pending orders
        found.append(
            _trip(
                row.index,
                row.text(symbol_at).strip().lower() if symbol_at is not None else "",
                side,
                _money(row.text(entry_at)),
                _money(row.text(exit_at)),
                _money(row.text(profit_at)),
                _money(row.text(volume_at)) if volume_at is not None else None,
            )
        )
    return _collect(found, volume_column=volume_at is not None)


def _fxblue_trips(table: RawTable) -> _Trips:
    names = _names(table.header)
    kind_at, side_at = _at(names, "type"), _at(names, "buy/sell")
    entry_at, exit_at = _at(names, "open price"), _at(names, "close price")
    profit_at, symbol_at = _at(names, "profit"), _at(names, "symbol")
    if None in (kind_at, side_at, entry_at, exit_at, profit_at):
        return _Trips(reason="no_column")
    assert kind_at is not None and side_at is not None and entry_at is not None
    assert exit_at is not None and profit_at is not None
    volume_at, account_at = _at(names, "lots"), _at(names, "account")
    found: list[_Trip | None] = []
    for row in table.kind(rows.KIND_CSV):
        if row.text(kind_at).strip().lower() != _FXBLUE_CLOSED:
            continue  # deposits, open positions and pending orders
        found.append(
            _trip(
                row.index,
                row.text(symbol_at).strip().lower() if symbol_at is not None else "",
                _side(row.text(side_at)),
                _money(row.text(entry_at)),
                _money(row.text(exit_at)),
                _money(row.text(profit_at)),
                _money(row.text(volume_at)) if volume_at is not None else None,
                row.text(account_at).strip() if account_at is not None else "",
            )
        )
    return _collect(found, volume_column=volume_at is not None)


def _tradingview_trips(table: RawTable) -> _Trips:
    """One trip per trade number from its entry and exit rows; the gross is
    the exit row's net P&L plus the commission it itemises, the volume the
    exit row's size in value divided by the entry price (the value route:
    the point value of a contract is inside it)."""
    try:
        columns, _currency = importers._tv_columns(list(table.header))
    except importers.ReportFormatError:
        return _Trips(reason="no_column")
    if "commission" not in columns:
        return _Trips(reason="no_column")
    names = _names(table.header)
    value_at = next((i for i, name in enumerate(names) if _TV_VALUE.match(name)), None)
    groups: dict[str, list[RawRow]] = {}
    order: list[str] = []
    for row in table.kind(rows.KIND_CSV):
        number = row.text(columns["trade"]).strip()
        if number not in groups:
            order.append(number)
        groups.setdefault(number, []).append(row)
    found: list[_Trip | None] = []
    for number in order:
        pair = groups[number]
        if len(pair) != 2:
            found.append(None)
            continue
        roles = {importers._tv_role(row.text(columns["type"])): row for row in pair}
        if set(roles) != {"entry", "exit"}:
            found.append(None)
            continue
        entry, exit_ = roles["entry"], roles["exit"]
        signal = exit_.text(columns["signal"]).strip().lower()
        if not signal or signal in _TV_OPEN_SIGNALS:
            continue  # still open at the end of the export: no exit order

        side = importers._tv_side(entry.text(columns["type"])) or importers._tv_side(
            exit_.text(columns["type"])
        )
        entry_price = _money(entry.text(columns["price"]))
        net = _money(exit_.text(columns["net"]))
        commission = _money(exit_.text(columns["commission"]))
        gross = net + abs(commission or Decimal(0)) if net is not None else None
        value = _money(exit_.text(value_at)) if value_at is not None else None
        volume = (
            value / entry_price
            if value is not None and entry_price is not None and entry_price != 0
            else None
        )
        found.append(
            _trip(
                min(entry.index, exit_.index),
                "",
                side,
                entry_price,
                _money(exit_.text(columns["price"])),
                gross,
                volume,
            )
        )
    return _collect(found, volume_column=value_at is not None)


def _ninjatrader_trips(table: RawTable) -> _Trips:
    columns = importers._ninjatrader_index(list(table.header))
    needed = ("market pos.", "entry price", "exit price", "profit")
    if any(name not in columns for name in needed):
        return _Trips(reason="no_column")
    comma = table.delimiter == ";"
    fee_columns = [columns[name] for name in _NT_FEES if name in columns]
    found: list[_Trip | None] = []
    for row in table.kind(rows.KIND_CSV):
        side = _side(row.text(columns["market pos."]))
        if side is None:
            continue
        net = _money(row.text(columns["profit"]), comma_decimal=comma)
        paid = sum(
            (abs(_money(row.text(at), comma_decimal=comma) or Decimal(0)) for at in fee_columns),
            Decimal(0),
        )
        found.append(
            _trip(
                row.index,
                row.text(columns["instrument"]).strip() if "instrument" in columns else "",
                side,
                _money(row.text(columns["entry price"]), comma_decimal=comma),
                _money(row.text(columns["exit price"]), comma_decimal=comma),
                net + paid if net is not None else None,
                _money(row.text(columns["qty"]), comma_decimal=comma) if "qty" in columns else None,
            )
        )
    return _collect(found, volume_column="qty" in columns)


def _trips(table: RawTable) -> _Trips:
    family = table.family
    if family == families.MT4_STATEMENT:
        return _mt4_statement_trips(table)
    if family == families.MT5_HISTORY:
        return _mt5_position_trips(table)
    if family == families.MYFXBOOK:
        return _myfxbook_trips(table)
    if family == families.MQL5_SIGNAL:
        return _mql5_trips(table)
    if family == families.FXBLUE:
        return _fxblue_trips(table)
    if family == families.TRADINGVIEW:
        return _tradingview_trips(table)
    if family == families.NINJATRADER:
        return _ninjatrader_trips(table)
    return _Trips(reason="format_not_covered")


# ---------------------------------------------------------------------------
# PNL_SIGN
# ---------------------------------------------------------------------------


def run_PNL_SIGN(table: RawTable, ctx: Context) -> RawOutcome:
    """The sign of each closed trade's gross result against the sign of its
    price move. Zero-result legs (a ``close by`` books the result on one
    ticket) and zero moves are skipped. Never the testers: an MT4 tester's
    Profit is net of swap and commission, an MT5 tester needs deal pairing.
    """
    if table.family not in _PNL_SIGN_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    read = _trips(table)
    if read.reason:
        return RawOutcome.skip(read.reason)
    n_rows = zero_gross = zero_move = 0
    hits: list[int] = []
    for trip in read.trips:
        n_rows += 1
        if trip.gross == 0:
            zero_gross += 1
            continue
        move = (trip.exit - trip.entry) * _sign(trip.side)
        if move == 0:
            zero_move += 1
            continue
        if (trip.gross > 0) != (move > 0):
            hits.append(trip.index)
    figures: tuple[Figure, ...] = (
        _count("n_rows", n_rows),
        _count("n_hits", len(hits)),
        _count("n_zero_gross", zero_gross),
        _count("n_zero_move", zero_move),
        _count("rows_unparsed", read.unparsed),
    )
    if n_rows == 0:
        return RawOutcome.skip("no_qualifying_row", figures)
    return RawOutcome(hits=len(hits), figures=figures, examples=_examples(hits))


# ---------------------------------------------------------------------------
# PRICE_IMPLIED_PNL
# ---------------------------------------------------------------------------


def _fits(trip: _Trip, multiplier: int) -> bool:
    assert trip.volume is not None
    expected = _sign(trip.side) * (trip.exit - trip.entry) * trip.volume * multiplier
    return abs(trip.gross - expected) <= thresholds.MONEY_TOLERANCE


def _best_multiplier(trips: list[_Trip]) -> tuple[int, list[bool]]:
    """The contract multiplier that reproduces the most rows; ties go to the
    first of the fixed list."""
    best, best_fits, best_count = thresholds.CONTRACT_MULTIPLIERS[0], [False] * len(trips), -1
    for multiplier in thresholds.CONTRACT_MULTIPLIERS:
        fits = [_fits(trip, multiplier) for trip in trips]
        count = sum(1 for fit in fits if fit)
        if count > best_count:
            best, best_fits, best_count = multiplier, fits, count
    return best, best_fits


def _busiest_account(trips: tuple[_Trip, ...]) -> tuple[tuple[_Trip, ...], int]:
    """The trips of the account with the most closed trades and how many
    accounts the file holds; ties go to the account printed first."""
    counts: dict[str, int] = {}
    first: dict[str, int] = {}
    for position, trip in enumerate(trips):
        counts[trip.account] = counts.get(trip.account, 0) + 1
        first.setdefault(trip.account, position)
    if len(counts) <= 1:
        return trips, len(counts)
    chosen = max(counts, key=lambda name: (counts[name], -first[name]))
    return tuple(trip for trip in trips if trip.account == chosen), len(counts)


def run_PRICE_IMPLIED_PNL(table: RawTable, ctx: Context) -> RawOutcome:
    """Per symbol quoted in the account currency (or gold and silver on a USD
    account), the gross result of every closed trade against the price move
    times the volume times the one contract size that fits most rows.

    A symbol with one row cannot be told from a non-standard contract; a
    symbol whose best multiplier explains fewer than two thirds of its rows
    is ``symbols_no_fit``, never a hit. A TradingView list names no symbol:
    it is one contract whose point value sits inside the size in value, so
    the currency rule does not apply to it. An FX Blue export holding several
    accounts is read for the busiest one, as the importer reads it: two
    brokers may size one symbol differently. ``INFO`` by design in v1 (D9).
    """
    family = table.family
    if family not in _IMPLIED_PNL_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    read = _trips(table)
    if read.reason:
        return RawOutcome.skip(read.reason)
    if not read.volume_column:
        return RawOutcome.skip("no_column")
    candidates, accounts = read.trips, 1
    if family == families.FXBLUE:
        candidates, accounts = _busiest_account(read.trips)
    order: list[str] = []
    by_symbol: dict[str, list[_Trip]] = {}
    for trip in candidates:
        if trip.volume is None or trip.volume == 0:
            continue
        if trip.symbol not in by_symbol:
            order.append(trip.symbol)
        by_symbol.setdefault(trip.symbol, []).append(trip)
    measured = no_fit = single = differs = n_rows = 0
    hits: list[int] = []
    for symbol in order:
        trips = by_symbol[symbol]
        if family != families.TRADINGVIEW and not symbols.priced_in(symbol, ctx.currency):
            differs += 1
            continue
        if len(trips) < 2:
            single += 1
            continue
        _multiplier, fits = _best_multiplier(trips)
        fitted = sum(1 for fit in fits if fit)
        if Decimal(fitted) / Decimal(len(trips)) < thresholds.IMPLIED_PNL_MIN_FIT:
            no_fit += 1
            continue
        measured += 1
        n_rows += len(trips)
        hits.extend(trip.index for trip, fit in zip(trips, fits, strict=True) if not fit)
    figures: tuple[Figure, ...] = (
        _count("n_rows", n_rows),
        _count("n_hits", len(hits)),
        _count("n_symbols_measured", measured),
        _count("symbols_no_fit", no_fit),
        _count("symbols_single_row", single),
        _count("symbols_quote_differs", differs),
        _count("accounts_in_file", accounts),
    )
    if measured == 0:
        if differs and not (single or no_fit):
            return RawOutcome.skip("quote_currency_differs", figures)
        return RawOutcome.skip("no_qualifying_row", figures)
    return RawOutcome(hits=len(hits), figures=figures, examples=_examples(hits))


# ---------------------------------------------------------------------------
# PRICE_PRECISION
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PriceCell:
    index: int
    symbol: str
    section: str
    decimals: int


def _decimals(text: str) -> int | None:
    """Printed decimals of a non-zero price cell; zeros and text are skipped."""
    value = money.parse_money(text)
    if value is None or value == 0:
        return None
    return money.printed_decimals(text)


def _add_cells(
    found: list[_PriceCell], row: RawRow, symbol: str, positions: tuple[int, ...]
) -> None:
    for at in positions:
        decimals = _decimals(row.text(at))
        if decimals is not None:
            found.append(_PriceCell(row.index, symbol, row.section, decimals))


def _mt4_price_columns(names: list[str], columns: dict[str, int]) -> tuple[int, int, int, int]:
    """``(open price, close price, S/L, T/P)`` of a statement row, from the
    header when it names two prices (the Open Trades header has no close
    time, so the importer's map does not read it), else the importer's map."""
    prices = [i for i, name in enumerate(names) if name == "price"]
    if len(prices) >= 2:
        open_at, close_at = prices[0], prices[1]
    else:
        open_at, close_at = columns["open_price"], columns["close_price"]
    sl_at, tp_at = _mt4_level_columns(names, {"open_price": open_at})
    return open_at, close_at, sl_at, tp_at


def _mt4_statement_cells(table: RawTable) -> list[_PriceCell]:
    found: list[_PriceCell] = []
    for row in table.rows:
        if row.kind not in {rows.KIND_MT4_TRADE, rows.KIND_MT4_OPEN}:
            continue
        columns = rows.mt4_columns(table, row)
        names = _names(table.header_of(row))
        symbol_at = columns["symbol"]
        for name in ("item", "symbol"):
            if name in names:
                symbol_at = names.index(name)
                break
        _add_cells(found, row, row.text(symbol_at).strip(), _mt4_price_columns(names, columns))
    return found


def _mt4_tester_cells(table: RawTable) -> list[_PriceCell]:
    """Price, S/L and T/P of every row of the run's single symbol, except the
    Price of a ``swap open`` row and of the ``modify`` rows of the order it
    reopened: a position closed and reopened at rollover carries a
    swap-adjusted open price beyond the symbol's digits (genuine corpus)."""
    tester_rows = table.kind(rows.KIND_MT4_TESTER)
    reopened = {
        row.text(3).strip() for row in tester_rows if row.text(2).strip().lower() == _MT4_SWAP_OPEN
    }
    found: list[_PriceCell] = []
    for row in tester_rows:
        kind = row.text(2).strip().lower()
        adjusted = kind == _MT4_SWAP_OPEN or (
            kind == _MT4_MODIFY and row.text(3).strip() in reopened
        )
        _add_cells(found, row, "", (6, 7) if adjusted else (5, 6, 7))
    return found


def _mt5_cells(table: RawTable) -> list[_PriceCell]:
    found: list[_PriceCell] = []
    for row in table.rows:
        if row.kind == rows.KIND_MT5_DEAL:
            columns = rows.mt5_columns(table, row)
            symbol = row.text(columns.get("symbol", 2)).strip()
            if symbol:
                _add_cells(found, row, symbol, (columns.get("price", 6),))
        elif row.kind == rows.KIND_MT5_POSITION:
            columns = rows.mt5_position_columns(table, row)
            _add_cells(
                found,
                row,
                row.text(columns["symbol"]).strip(),
                (columns["price"], columns["close_price"], columns["sl"], columns["tp"]),
            )
        elif row.kind == rows.KIND_MT5_ORDER:
            symbol_at, price_at, sl_at, tp_at = _mt5_order_columns(_names(table.header_of(row)))
            _add_cells(found, row, row.text(symbol_at).strip(), (price_at, sl_at, tp_at))
        elif row.kind == rows.KIND_MT5_OPEN_POSITION:
            _add_cells(found, row, row.text(2).strip(), (5, 6, 7))
    return found


def _precision_cells(table: RawTable) -> list[_PriceCell]:
    family = table.family
    if family == families.MT4_STATEMENT:
        return _mt4_statement_cells(table)
    if family == families.MT4_TESTER:
        return _mt4_tester_cells(table)
    if family in {families.MT5_HISTORY, families.MT5_TESTER}:
        return _mt5_cells(table)
    return []


def _row_decimals(cells: list[_PriceCell]) -> list[tuple[int, str, frozenset[int]]]:
    """``(row index, section, decimals seen in the row)`` in file order."""
    out: list[tuple[int, str, set[int]]] = []
    for cell in cells:
        if out and out[-1][0] == cell.index:
            out[-1][2].add(cell.decimals)
        else:
            out.append((cell.index, cell.section, {cell.decimals}))
    return [(index, section, frozenset(seen)) for index, section, seen in out]


def _split_row(cells: list[_PriceCell]) -> int | None:
    """The first row of the second regime when a symbol's digits changed
    once (a broker's 4-to-5-digit migration inside the period): every row
    prints one count, each table changes at most once, and every change adds
    digits from the same count to the same other count (a broker never took
    a digit away). ``None`` otherwise."""
    per_row = _row_decimals(cells)
    if any(len(seen) != 1 for _index, _section, seen in per_row):
        return None
    change: tuple[int, int] | None = None
    first_change: int | None = None
    changes_in_section: dict[str, int] = {}
    previous: dict[str, int] = {}
    for index, section, seen in per_row:
        (count,) = tuple(seen)
        before = previous.get(section)
        previous[section] = count
        if before is None or before == count:
            continue
        if count < before:
            return None
        changes_in_section[section] = changes_in_section.get(section, 0) + 1
        if changes_in_section[section] > 1:
            return None
        if change is None:
            change, first_change = (before, count), index
        elif change != (before, count):
            return None
    return first_change


def _mode(cells: list[_PriceCell]) -> int:
    """The most frequent count; ties go to the count printed first."""
    frequency: dict[int, int] = {}
    first: dict[int, int] = {}
    for position, cell in enumerate(cells):
        frequency[cell.decimals] = frequency.get(cell.decimals, 0) + 1
        first.setdefault(cell.decimals, position)
    return max(frequency, key=lambda count: (frequency[count], -first[count]))


def run_PRICE_PRECISION(table: RawTable, ctx: Context) -> RawOutcome:
    """Per symbol as printed, the histogram of printed decimals over open
    price, close price and non-zero S/L and T/P. A symbol printed with two
    or more counts is a hit and its rows outside the mode are the examples;
    on a live account's record a clean one-time gain of digits is
    ``split_symbols`` (a broker migration), not a hit. Spreadsheet exports
    lost their zeros; tracking exports and platform CSVs trim them.
    """
    family = table.family
    if family in _VARIABLE_PRECISION_FAMILIES:
        return RawOutcome.skip("variable_precision_format")
    if table.source_format in families.XLSX_FORMATS:
        return RawOutcome.skip("xlsx_precision_lost")
    if family not in _FIXED_PRECISION_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    cells = _precision_cells(table)
    if not cells:
        return RawOutcome.skip("no_qualifying_row")
    order: list[str] = []
    by_symbol: dict[str, list[_PriceCell]] = {}
    for cell in cells:
        if cell.symbol not in by_symbol:
            order.append(cell.symbol)
        by_symbol.setdefault(cell.symbol, []).append(cell)
    mixed = off_rows = 0
    split_rows: list[int] = []
    hits: list[int] = []
    for symbol in order:
        items = by_symbol[symbol]
        if len({cell.decimals for cell in items}) == 1:
            continue
        split = _split_row(items) if family in _MIGRATION_FAMILIES else None
        if split is not None:
            split_rows.append(split)
            continue
        mixed += 1
        mode = _mode(items)
        off = sorted({cell.index for cell in items if cell.decimals != mode})
        off_rows += len(off)
        hits.extend(off)
    figures: tuple[Figure, ...] = (
        _count("n_rows", len({cell.index for cell in cells})),
        _count("n_hits", mixed),
        _count("n_symbols", len(order)),
        _count("n_rows_off_mode", off_rows),
        _count("split_symbols", len(split_rows)),
    )
    if split_rows:
        figures += (_count("split_at_row", min(split_rows)),)
    return RawOutcome(hits=mixed, figures=figures, examples=_examples(hits))


__all__ = ["run_PNL_SIGN", "run_PRICE_IMPLIED_PNL", "run_PRICE_PRECISION", "run_SLTP_FILL"]
