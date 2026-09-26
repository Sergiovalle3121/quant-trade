"""``TICKET_LINKS`` and ``CROSS_COPIES``: one record the platform printed twice.

A partially closed MT4 order leaves two rows that name each other through
the ticket cell's ``title`` (``to #N`` on the closed part, ``from #M`` on the
remainder); an MT5 history report prints every closed position in three
tables (Positions, Orders, Deals). The platform wrote every copy from one
record, so a cell edited in one place and not in the others leaves the
copies apart. Nothing from the file enters a figure: tickets, symbols and
comments become counts, and examples are raw row indexes.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, money, rows
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import MAX_EXAMPLES, MEASURED, Figure, RawOutcome
from quant_trade.audit.forensics.rows import RawRow, RawTable
from quant_trade.audit.forensics.thresholds import ORDER_FILL_DRIFT


def _count(key: str, value: int) -> Figure:
    return (key, str(value), MEASURED)


def _price_key(text: str) -> str:
    """The printed price as a comparable text: value and printed decimals at
    once (``2080.10`` and ``2080.1`` differ), or the raw text when the cell is
    not a number."""
    return money.normalise_text(text) or text.strip()


def _volume(text: str) -> Decimal:
    value = money.parse_money(text)
    return value if value is not None else Decimal(0)


# ---------------------------------------------------------------------------
# TICKET_LINKS — MT4 statement ``to #`` / ``from #``
# ---------------------------------------------------------------------------

_LINK = re.compile(r"\b(to|from)\s*#\s*(\d+)", re.IGNORECASE)
_MT4_LINK_KINDS = frozenset({rows.KIND_MT4_TRADE, rows.KIND_MT4_OPEN})


@dataclass(frozen=True)
class _Mt4Trade:
    index: int
    ticket: str
    symbol: str
    side: str
    open_time: datetime | None
    open_price: str
    to_links: tuple[str, ...]
    from_links: tuple[str, ...]


def _ticket_text(text: str) -> str:
    stripped = text.strip()
    return stripped.lstrip("0") or "0" if stripped.isdigit() else stripped


def _links(comment: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``to #`` and ``from #`` tickets named in a comment, in printed order."""
    found = [
        (match.group(1).lower(), _ticket_text(match.group(2))) for match in _LINK.finditer(comment)
    ]
    to_links = tuple(ticket for word, ticket in found if word == "to")
    from_links = tuple(ticket for word, ticket in found if word == "from")
    return to_links, from_links


def _mt4_comment(table: RawTable, row: RawRow, ticket_at: int, comment_at: int) -> str:
    """The row's comment: the ticket cell's ``title`` (a title equal to the
    ticket is the numbered layout's tooltip, not a comment), else the Comment
    column of the numbered layout, else the single text of a comment row the
    2009 builds print right after the trade."""
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


def _mt4_trades(table: RawTable) -> tuple[_Mt4Trade, ...]:
    found: list[_Mt4Trade] = []
    for row in table.rows:
        if row.kind not in _MT4_LINK_KINDS:
            continue
        columns = rows.mt4_columns(table, row)
        names = [text.strip().lower() for text in table.header_of(row)]
        ticket_at = names.index("ticket") if "ticket" in names else 0
        comment_at = names.index("comment") if "comment" in names else -1
        to_links, from_links = _links(_mt4_comment(table, row, ticket_at, comment_at))
        found.append(
            _Mt4Trade(
                index=row.index,
                ticket=_ticket_text(row.text(ticket_at)),
                symbol=row.text(columns["symbol"]).strip().lower(),
                side=row.text(columns["type"]).strip().lower(),
                open_time=importers._one_time(row.text(columns["open_time"]).strip()),
                open_price=_price_key(row.text(columns["open_price"])),
                to_links=to_links,
                from_links=from_links,
            )
        )
    return tuple(found)


def _same_origin(one: _Mt4Trade, other: _Mt4Trade) -> bool:
    """Both halves of a split order keep the symbol, side, open time and open
    price of the original."""
    return (
        one.index != other.index
        and one.symbol == other.symbol
        and one.side == other.side
        and one.open_time is not None
        and one.open_time == other.open_time
        and one.open_price != ""
        and one.open_price == other.open_price
    )


def _to_link_holds(closed_part: _Mt4Trade, remainder: _Mt4Trade) -> bool:
    """The remainder names the closed part it came from, unless it was split
    again and its comment now names its own remainder instead."""
    named = closed_part.ticket in remainder.from_links or bool(remainder.to_links)
    return named and _same_origin(closed_part, remainder)


def _from_link_holds(remainder: _Mt4Trade, closed_part: _Mt4Trade) -> bool:
    return remainder.ticket in closed_part.to_links and _same_origin(remainder, closed_part)


def run_TICKET_LINKS(table: RawTable, ctx: Context) -> RawOutcome:
    """Every ``to #N`` / ``from #M`` reference of an MT4 statement, resolved
    against the Closed Transactions and Open Trades rows.

    A reference whose ticket is not in the file (closed outside a custom
    period, or a remainder that is neither closed nor still open at the
    report time) is ``links_unresolved``, never a hit.
    """
    if table.family != families.MT4_STATEMENT:
        return RawOutcome.skip("format_not_covered")
    trades = _mt4_trades(table)
    by_ticket: dict[str, _Mt4Trade] = {}
    for trade in trades:
        by_ticket.setdefault(trade.ticket, trade)
    n_links = inconsistent = unresolved = 0
    examples: list[int] = []
    for trade in trades:
        broken = 0
        for target in trade.to_links:
            n_links += 1
            remainder = by_ticket.get(target)
            if remainder is None:
                unresolved += 1
            elif not _to_link_holds(trade, remainder):
                broken += 1
        for source in trade.from_links:
            n_links += 1
            closed_part = by_ticket.get(source)
            if closed_part is None:
                unresolved += 1
            elif not _from_link_holds(trade, closed_part):
                broken += 1
        if broken:
            inconsistent += broken
            examples.append(trade.index)
    figures = (
        _count("n_rows", len(trades)),
        _count("n_hits", inconsistent),
        _count("n_links", n_links),
        _count("links_inconsistent", inconsistent),
        _count("links_unresolved", unresolved),
    )
    if n_links == 0:
        return RawOutcome.skip("no_qualifying_row", figures)
    return RawOutcome(hits=inconsistent, figures=figures, examples=tuple(examples[:MAX_EXAMPLES]))


# ---------------------------------------------------------------------------
# CROSS_COPIES — MT5 history Positions vs Deals vs Orders
# ---------------------------------------------------------------------------

_ENTRY_DIRECTIONS = frozenset({"in"})
_EXIT_DIRECTIONS = frozenset({"out", "out by"})
#: Order states that contradict a deal filled from that order ("partial" and
#: "filled" do not; a state the terminal wrote in another language is not judged).
_ORDER_NOT_FILLED = frozenset({"canceled", "cancelled", "expired", "rejected", "placed", "started"})

_ExitKey = tuple[str, datetime | None, str]
_TimeKey = tuple[str, datetime | None]


@dataclass(frozen=True)
class _Position:
    index: int
    ident: str
    symbol: str
    volume: Decimal
    open_time: datetime | None
    open_price: str
    close_time: datetime | None
    close_price: str

    @property
    def exit_key(self) -> _ExitKey:
        return (self.symbol, self.close_time, self.close_price)


@dataclass(frozen=True)
class _Deal:
    index: int
    symbol: str
    direction: str
    volume: Decimal
    price: str
    time: datetime | None
    order: str

    @property
    def exit_key(self) -> _ExitKey:
        return (self.symbol, self.time, self.price)


@dataclass(frozen=True)
class _Order:
    ident: str
    symbol: str
    fill_time: datetime | None
    state: str


def _positions(table: RawTable) -> tuple[_Position, ...]:
    found: list[_Position] = []
    for row in table.kind(rows.KIND_MT5_POSITION):
        columns = rows.mt5_position_columns(table, row)
        found.append(
            _Position(
                index=row.index,
                ident=_ticket_text(row.text(columns["position"])),
                symbol=row.text(columns["symbol"]).strip().lower(),
                volume=_volume(row.text(columns["volume"])),
                open_time=importers._one_time(row.text(columns["open"]).strip()),
                open_price=_price_key(row.text(columns["price"])),
                close_time=importers._one_time(row.text(columns["close"]).strip()),
                close_price=_price_key(row.text(columns["close_price"])),
            )
        )
    return tuple(found)


def _deals(table: RawTable) -> tuple[_Deal, ...]:
    """The entry and exit deals; balance rows are not deals of a position."""
    found: list[_Deal] = []
    for row in table.kind(rows.KIND_MT5_DEAL):
        columns = rows.mt5_columns(table, row)
        direction = row.text(columns.get("direction", -1)).strip().lower()
        if direction not in _ENTRY_DIRECTIONS and direction not in _EXIT_DIRECTIONS:
            continue
        order_at = columns.get("order")
        found.append(
            _Deal(
                index=row.index,
                symbol=row.text(columns.get("symbol", -1)).strip().lower(),
                direction=direction,
                volume=_volume(row.text(columns.get("volume", -1))),
                price=_price_key(row.text(columns.get("price", -1))),
                time=importers._one_time(row.text(columns.get("time", -1)).strip()),
                order=_ticket_text(row.text(order_at)) if order_at is not None else "",
            )
        )
    return tuple(found)


def _first_deal_time(table: RawTable) -> datetime | None:
    """The earliest time in the Deals table, balance deals included: the
    period the report covers starts there."""
    first: datetime | None = None
    for row in table.kind(rows.KIND_MT5_DEAL):
        columns = rows.mt5_columns(table, row)
        moment = importers._one_time(row.text(columns.get("time", 0)).strip())
        if moment is not None and (first is None or moment < first):
            first = moment
    return first


def _orders(table: RawTable) -> dict[str, _Order]:
    """Orders by ticket, first row wins. The layout is fixed: Open Time,
    Order, Symbol, Type, Volume / Filled, Price, S/L, T/P, Time, State, Comment."""
    found: dict[str, _Order] = {}
    for row in table.kind(rows.KIND_MT5_ORDER):
        ident = _ticket_text(row.text(1))
        found.setdefault(
            ident,
            _Order(
                ident=ident,
                symbol=row.text(2).strip().lower(),
                fill_time=importers._one_time(row.text(8).strip()),
                state=row.text(9).strip().lower(),
            ),
        )
    return found


def _partial_close(
    position: _Position,
    exits_by_time: dict[_TimeKey, list[_Deal]],
    volume_by_time: dict[_TimeKey, Decimal],
    out_times: dict[str, list[datetime]],
) -> bool:
    """A position closed in parts prints one row carrying the last exit's
    time and the volume-weighted exit price: the deals at that time cover the
    last part only, and an earlier exit deal of the symbol sits inside the
    position's life. Such a row is scoped out, never a hit (D3: seen on a
    genuine file)."""
    if position.open_time is None or position.close_time is None:
        return False
    key = (position.symbol, position.close_time)
    last = exits_by_time.get(key, [])
    if not last:
        return False
    if sum((deal.volume for deal in last), Decimal(0)) >= volume_by_time.get(key, Decimal(0)):
        return False
    times = out_times.get(position.symbol, [])
    return bisect_left(times, position.close_time) > bisect_right(times, position.open_time)


def _order_copy_holds(deal: _Deal, order: _Order) -> bool:
    if order.symbol != deal.symbol:
        return False
    if deal.time is None or order.fill_time is None:
        return False
    if abs(order.fill_time - deal.time) > ORDER_FILL_DRIFT:
        return False
    return order.state not in _ORDER_NOT_FILLED


def run_CROSS_COPIES(table: RawTable, ctx: Context) -> RawOutcome:
    """Each Positions row of an MT5 history report against its entry deals
    (``in`` deals whose Order is the position id), its exit deals (``out`` /
    ``out by`` deals at the same symbol, close time and close price) and, when
    the Orders table exists, the orders those deals name.

    Hedge accounts only: a netting account's deals carry no position id.
    Exit volumes are summed per (symbol, close time, close price) group
    across every Positions row of that group, so positions closed together
    by one order compare as one. A position closed in parts prints one row
    with the last exit's time and the volume-weighted exit price, which no
    single deal repeats: it is ``exits_partial``, never a hit. A position
    opened before the first deal in the file has no entry deal here and is
    skipped; an order placed before the period is ``orders_unresolved``.
    """
    if table.family != families.MT5_HISTORY:
        return RawOutcome.skip("format_not_covered")
    if ctx.header.margin_mode != "hedge":
        return RawOutcome.skip("netting_or_unknown_margin_mode")
    positions = _positions(table)
    deals = _deals(table)
    if not positions or not deals:
        return RawOutcome.skip("no_table")
    first_deal = _first_deal_time(table)
    if first_deal is None:
        return RawOutcome.skip("no_qualifying_row")
    in_scope = tuple(
        position
        for position in positions
        if position.open_time is not None and position.open_time >= first_deal
    )
    before = len(positions) - len(in_scope)
    has_orders = any(row.section == rows.SECTION_ORDERS for row in table.rows)
    orders = _orders(table) if has_orders else {}

    entries_by_order: dict[str, list[_Deal]] = {}
    exits_by_key: dict[_ExitKey, list[_Deal]] = {}
    exits_by_time: dict[_TimeKey, list[_Deal]] = {}
    out_times: dict[str, list[datetime]] = {}
    for deal in deals:
        if deal.direction in _ENTRY_DIRECTIONS:
            entries_by_order.setdefault(deal.order, []).append(deal)
        else:
            exits_by_key.setdefault(deal.exit_key, []).append(deal)
            exits_by_time.setdefault((deal.symbol, deal.time), []).append(deal)
            if deal.time is not None:
                out_times.setdefault(deal.symbol, []).append(deal.time)
    for symbol_times in out_times.values():
        symbol_times.sort()
    volume_by_id: dict[str, Decimal] = {}
    volume_by_key: dict[_ExitKey, Decimal] = {}
    volume_by_time: dict[_TimeKey, Decimal] = {}
    for position in positions:
        time_key = (position.symbol, position.close_time)
        volume_by_id[position.ident] = (
            volume_by_id.get(position.ident, Decimal(0)) + position.volume
        )
        volume_by_key[position.exit_key] = (
            volume_by_key.get(position.exit_key, Decimal(0)) + position.volume
        )
        volume_by_time[time_key] = volume_by_time.get(time_key, Decimal(0)) + position.volume

    copies = 0
    entries_bad = exits_bad = orders_bad = partial = 0
    examples: list[int] = []
    order_verdicts: dict[int, bool | None] = {}
    for position in in_scope:
        broken = False
        entries = entries_by_order.get(position.ident, [])
        if not entries:
            entries_bad += 1
            broken = True
        else:
            copies += 3 * len(entries) + 1
            entry_ok = all(
                deal.symbol == position.symbol
                and deal.time == position.open_time
                and deal.price == position.open_price
                for deal in entries
            )
            entry_ok = entry_ok and sum(
                (deal.volume for deal in entries), Decimal(0)
            ) == volume_by_id.get(position.ident, Decimal(0))
            if not entry_ok:
                entries_bad += 1
                broken = True
        exits = exits_by_key.get(position.exit_key, [])
        copies += 1
        if exits and sum((deal.volume for deal in exits), Decimal(0)) == volume_by_key.get(
            position.exit_key, Decimal(0)
        ):
            pass
        elif _partial_close(position, exits_by_time, volume_by_time, out_times):
            partial += 1
            exits = exits_by_time.get((position.symbol, position.close_time), [])
        else:
            exits_bad += 1
            broken = True
        if has_orders:
            order_ok = True
            for deal in entries + exits:
                if deal.index not in order_verdicts:
                    order = orders.get(deal.order) if deal.order else None
                    if order is None:
                        order_verdicts[deal.index] = None
                    else:
                        copies += 3
                        order_verdicts[deal.index] = _order_copy_holds(deal, order)
                if order_verdicts[deal.index] is False:
                    order_ok = False
            if not order_ok:
                orders_bad += 1
                broken = True
        if broken:
            examples.append(position.index)

    unresolved = sum(1 for verdict in order_verdicts.values() if verdict is None)
    figures = (
        _count("n_rows", len(positions)),
        _count("n_hits", len(examples)),
        _count("n_positions", len(in_scope)),
        _count("positions_before_period", before),
        _count("copies_compared", copies),
        _count("entries_inconsistent", entries_bad),
        _count("exits_inconsistent", exits_bad),
        _count("exits_partial", partial),
        _count("orders_inconsistent", orders_bad),
        _count("orders_unresolved", unresolved),
        _count("no_orders_table", 0 if has_orders else 1),
    )
    if not in_scope:
        return RawOutcome.skip("no_qualifying_row", figures)
    return RawOutcome(
        hits=len(examples), figures=figures, examples=tuple(sorted(examples)[:MAX_EXAMPLES])
    )
