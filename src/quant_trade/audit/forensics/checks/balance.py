"""``BALANCE_CHAIN`` and ``VOLUME_IN_OUT``: the running figures a platform prints.

``BALANCE_CHAIN`` (spec §3.4): every MetaTrader 5 deal and every MetaTrader 4
tester close prints the account balance after it, so the balance of a row
must be the balance of the previous row plus the money the row moved
(commission, fee, swap, profit, and a hidden ``Cost`` cell when a broker
fills it). Deal types whose effect on the balance is not their own money
(credit, correction, bonus, dividend...) restart the chain after them; two
deals of one second printed out of execution order are forgiven when
swapping them closes both gaps. ``VOLUME_IN_OUT`` (spec §3.19): per symbol,
deals that close (``out``, ``out by``) never exceed what earlier deals
opened (``in``); an ``in/out`` deal closes everything and opens the
remainder. ``INFO`` by design in v1.

Money is ``Decimal`` from the printed text; symbols never leave the file
(they are counted, D16); examples are raw-row indexes. Figures a family
cannot measure are still emitted, as ``0`` with ``NOT_MEASURED``, so each
check carries one key set whatever the family.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, money, rows, thresholds
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import (
    MAX_EXAMPLES,
    MEASURED,
    NOT_MEASURED,
    Figure,
    RawOutcome,
)
from quant_trade.audit.forensics.rows import RawRow, RawTable

_MT5_FAMILIES = frozenset({families.MT5_HISTORY, families.MT5_TESTER})
_SIDES = frozenset({"buy", "sell"})
#: Deal types whose printed money is exactly what they move on the balance.
_CHAINED_TYPES = frozenset({"buy", "sell", "balance"})
#: The money columns of a deal, added when the column exists.
_MONEY_COLUMNS = ("commission", "fee", "swap", "profit")
_DIRECTION_IN = "in"
_DIRECTIONS_OUT = frozenset({"out", "out by"})
_DIRECTION_REVERSE = "in/out"
#: A deal-shaped row: an MT time first and the importers' minimum width
#: (``_is_mt5_deal``); rows of a type the importers do not read (credit,
#: correction...) look like this but are not ``mt5_deal`` rows.
_MT5_DEAL_WIDTH = 13
#: MetaTrader 4 tester columns: the layout is fixed whatever the language.
_MT4_TESTER_TIME = 1
_MT4_TESTER_TYPE = 2
_MT4_TESTER_PROFIT = 8
_MT4_TESTER_BALANCE = 9
#: Printed decimals of the ``largest_gap`` figure.
_GAP_DECIMALS = 2
_ZERO = Decimal(0)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _count(key: str, value: int) -> Figure:
    return (key, str(value), MEASURED)


def _unmeasured(key: str) -> Figure:
    return (key, "0", NOT_MEASURED)


def _amount(key: str, value: Decimal, decimals: int | None = None) -> Figure:
    return (key, money.as_text(value, decimals), MEASURED)


def _row_figure(key: str, index: int | None) -> Figure:
    """A raw-row index, or ``0`` unmeasured when no row qualifies."""
    return _count(key, index) if index is not None else _unmeasured(key)


def _examples(indexes: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted(set(indexes))[:MAX_EXAMPLES])


def _money_or_zero(text: str) -> Decimal | None:
    """A money cell: blank reads as zero, an unreadable text as ``None``."""
    if not text.strip():
        return _ZERO
    return money.parse_money(text)


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Link:
    """One row of a running-balance table, as money."""

    index: int
    time: str
    """The printed time, compared as text for same-second ties."""
    amount: Decimal
    balance: Decimal | None
    chained: bool
    """False for a row whose effect on the balance is unknown (restart)."""
    cost_read: bool = False


@dataclass(frozen=True)
class _Chain:
    compared: int
    breaks: tuple[int, ...]
    largest_gap: Decimal
    restarts: int
    ties_fixed: int
    skipped_first: int
    """Rows that seeded the chain without a comparison (the first row, and
    the first row after each restart)."""


def _swapped_fits(before: Decimal, first: _Link, second: _Link) -> bool:
    """Whether ``second`` executed before ``first`` (same printed second)
    explains both printed balances."""
    first_balance, second_balance = first.balance, second.balance
    if first_balance is None or second_balance is None:
        return False
    if not second.chained or second.time != first.time:
        return False
    tolerance = thresholds.MONEY_TOLERANCE
    return (
        abs(before + second.amount - second_balance) <= tolerance
        and abs(second_balance + first.amount - first_balance) <= tolerance
    )


def _walk(links: Sequence[_Link], seed: Decimal | None, *, ties: bool) -> _Chain:
    """Follow the printed balances in file order from ``seed`` (``None``: the
    first row seeds). A row without a balance carries its money to the next
    comparison; a restart row drops the chain."""
    previous = seed
    carry = _ZERO
    compared = 0
    breaks: list[int] = []
    largest = _ZERO
    restarts = 0
    ties_fixed = 0
    skipped_first = 0
    position = 0
    while position < len(links):
        link = links[position]
        position += 1
        if not link.chained:
            restarts += 1
            previous = None
            carry = _ZERO
            continue
        if link.balance is None:
            carry += link.amount
            continue
        if previous is None:
            previous = link.balance
            carry = _ZERO
            skipped_first += 1
            continue
        gap = abs(link.balance - (previous + carry + link.amount))
        if gap > thresholds.MONEY_TOLERANCE:
            following = links[position] if position < len(links) else None
            if (
                ties
                and carry == _ZERO
                and following is not None
                and _swapped_fits(previous, link, following)
            ):
                # ``following`` executed first; the balance after both is the
                # one printed on ``link``, the later of the two.
                ties_fixed += 1
                compared += 2
                previous = link.balance
                position += 1
                continue
            breaks.append(link.index)
        compared += 1
        largest = max(largest, gap)
        previous = link.balance
        carry = _ZERO
    return _Chain(
        compared=compared,
        breaks=tuple(breaks),
        largest_gap=largest,
        restarts=restarts,
        ties_fixed=ties_fixed,
        skipped_first=skipped_first,
    )


# ---------------------------------------------------------------------------
# MetaTrader 5 deals
# ---------------------------------------------------------------------------


def _deal_shaped(row: RawRow) -> bool:
    return len(row.texts) >= _MT5_DEAL_WIDTH and importers._is_mt_time(row.text(0))


def _mt5_deal_rows(table: RawTable) -> list[RawRow]:
    """Deal rows in file order: the importers' deals plus deal-shaped rows of
    the Deals table they do not read (credit, correction, bonus...)."""
    return [
        row
        for row in table.rows
        if row.kind == rows.KIND_MT5_DEAL
        or (row.kind == rows.KIND_OTHER and row.section == rows.SECTION_DEALS and _deal_shaped(row))
    ]


def _hidden_cost(table: RawTable, row: RawRow) -> Decimal | None:
    """The number in the row's hidden cells (a broker-filled ``Cost``), read
    at the positions the header hides; ``None`` when no hidden cell holds one."""
    positions: list[int] = []
    if 0 <= row.header_row < len(table.rows):
        header = table.rows[row.header_row]
        positions = [i for i, cell in enumerate(header.cells) if cell.hidden]
    if not positions:
        positions = [i for i, cell in enumerate(row.cells) if cell.hidden]
    total: Decimal | None = None
    for position in positions:
        if position >= len(row.cells) or not row.cells[position].hidden:
            continue
        value = money.parse_money(row.cells[position].text)
        if value is not None:
            total = value if total is None else total + value
    return total


def _mt5_link(table: RawTable, row: RawRow) -> _Link:
    columns = rows.mt5_columns(table, row)
    time = row.text(columns.get("time", 0))
    kind = row.text(columns.get("type", 3)).lower()
    balance_at = columns.get("balance")
    balance = money.parse_money(row.text(balance_at)) if balance_at is not None else None
    if row.kind != rows.KIND_MT5_DEAL or kind not in _CHAINED_TYPES:
        return _Link(row.index, time, _ZERO, balance, chained=False)
    amount = _ZERO
    for name in _MONEY_COLUMNS:
        at = columns.get(name)
        if at is None:
            continue
        value = _money_or_zero(row.text(at))
        if value is None:
            return _Link(row.index, time, _ZERO, balance, chained=False)
        amount += value
    cost = _hidden_cost(table, row)
    if cost is not None:
        amount += cost
    return _Link(row.index, time, amount, balance, chained=True, cost_read=cost is not None)


def _mt5_balance_chain(table: RawTable) -> RawOutcome:
    deal_rows = _mt5_deal_rows(table)
    if not deal_rows:
        return RawOutcome.skip("no_table")
    links = [_mt5_link(table, row) for row in deal_rows]
    counted = (_count("n_rows", len(links)),)
    with_balance = [link for link in links if link.balance is not None]
    if not with_balance:
        return RawOutcome.skip("no_column", figures=counted)
    if len(with_balance) < 2:
        return RawOutcome.skip("no_qualifying_row", figures=counted)
    chain = _walk(links, None, ties=True)
    if chain.compared == 0:
        return RawOutcome.skip("no_qualifying_row", figures=counted)
    first = with_balance[0]
    implied = (
        _amount("initial_balance_implied", first.balance - first.amount)
        if first.chained and first.balance is not None
        else _unmeasured("initial_balance_implied")
    )
    figures = (
        *counted,
        _count("n_hits", len(chain.breaks)),
        _row_figure("first_break_row", chain.breaks[0] if chain.breaks else None),
        _amount("largest_gap", chain.largest_gap, _GAP_DECIMALS),
        _count("restarts", chain.restarts),
        _count("ties_fixed", chain.ties_fixed),
        _count("hidden_cost_rows", sum(1 for link in links if link.cost_read)),
        _count("skipped_first", chain.skipped_first),
        implied,
    )
    return RawOutcome(hits=len(chain.breaks), figures=figures, examples=_examples(chain.breaks))


# ---------------------------------------------------------------------------
# MetaTrader 4 tester
# ---------------------------------------------------------------------------


def _mt4_tester_links(table: RawTable) -> list[_Link]:
    """The closing rows (``_MT4_CLOSES``), whose Profit is net and whose
    Balance is the balance after them."""
    links: list[_Link] = []
    for row in table.kind(rows.KIND_MT4_TESTER):
        if row.text(_MT4_TESTER_TYPE).lower() not in importers._MT4_CLOSES:
            continue
        profit = _money_or_zero(row.text(_MT4_TESTER_PROFIT))
        balance = money.parse_money(row.text(_MT4_TESTER_BALANCE))
        if profit is None:
            links.append(_Link(row.index, row.text(_MT4_TESTER_TIME), _ZERO, balance, False))
        else:
            links.append(_Link(row.index, row.text(_MT4_TESTER_TIME), profit, balance, True))
    return links


def _mt4_tester_balance_chain(table: RawTable) -> RawOutcome:
    if not table.kind(rows.KIND_MT4_TESTER):
        return RawOutcome.skip("no_table")
    links = _mt4_tester_links(table)
    counted = (_count("n_rows", len(links)),)
    if not any(link.balance is not None for link in links):
        return RawOutcome.skip("no_qualifying_row", figures=counted)
    seed = money.parse_money(table.label("Initial deposit") or "")
    chain = _walk(links, seed, ties=False)
    if chain.compared == 0:
        return RawOutcome.skip("no_qualifying_row", figures=counted)
    figures = (
        *counted,
        _count("n_hits", len(chain.breaks)),
        _row_figure("first_break_row", chain.breaks[0] if chain.breaks else None),
        _amount("largest_gap", chain.largest_gap, _GAP_DECIMALS),
        _unmeasured("restarts"),
        _unmeasured("ties_fixed"),
        _unmeasured("hidden_cost_rows"),
        _count("skipped_first", chain.skipped_first),
        _unmeasured("initial_balance_implied"),
    )
    return RawOutcome(hits=len(chain.breaks), figures=figures, examples=_examples(chain.breaks))


def run_BALANCE_CHAIN(table: RawTable, ctx: Context) -> RawOutcome:
    if table.family in _MT5_FAMILIES:
        return _mt5_balance_chain(table)
    if table.family == families.MT4_TESTER:
        return _mt4_tester_balance_chain(table)
    if table.family == families.MT4_STATEMENT or table.family in families.CSV_FAMILIES:
        # No running balance column in these formats.
        return RawOutcome.skip("no_column")
    return RawOutcome.skip("format_not_covered")


# ---------------------------------------------------------------------------
# VOLUME_IN_OUT
# ---------------------------------------------------------------------------


def _pre_period_volume(
    table: RawTable, first_deal_time: str
) -> tuple[dict[str, Decimal], int] | None:
    """Per symbol, the volume of closed positions opened before the first
    deal of the Deals table: their ``in`` deals lie outside a custom-period
    export, so their closes would otherwise exceed what the file opened
    (scoping rule from the corpus, D3). ``None`` when the file prints no
    Positions table (old builds), in which case nothing can be seeded."""
    positions = table.kind(rows.KIND_MT5_POSITION)
    if not positions:
        return None
    first = importers._one_time(first_deal_time)
    seeded: dict[str, Decimal] = {}
    count = 0
    for row in positions:
        columns = rows.mt5_position_columns(table, row)
        opened = importers._one_time(row.text(columns["open"]))
        symbol = row.text(columns["symbol"]).strip()
        volume = money.parse_money(row.text(columns["volume"]))
        if first is None or opened is None or opened >= first or not symbol or volume is None:
            continue
        seeded[symbol] = seeded.get(symbol, _ZERO) + volume
        count += 1
    return seeded, count


def run_VOLUME_IN_OUT(table: RawTable, ctx: Context) -> RawOutcome:
    if table.family not in _MT5_FAMILIES:
        return RawOutcome.skip("format_not_covered")
    deals = table.kind(rows.KIND_MT5_DEAL)
    if not deals:
        return RawOutcome.skip("no_table")
    first_columns = rows.mt5_columns(table, deals[0])
    seeded = _pre_period_volume(table, deals[0].text(first_columns.get("time", 0)))
    # Symbol text is a dictionary key only; it never reaches a figure (D16).
    open_volume: dict[str, Decimal] = {} if seeded is None else dict(seeded[0])
    negative_at: dict[str, int] = {}
    seen: set[str] = set()
    examined = 0
    for row in deals:
        columns = rows.mt5_columns(table, row)
        if not {"type", "direction", "symbol", "volume"} <= columns.keys():
            return RawOutcome.skip("no_column")
        if row.text(columns["type"]).lower() not in _SIDES:
            continue
        direction = row.text(columns["direction"]).lower()
        symbol = row.text(columns["symbol"]).strip()
        volume = money.parse_money(row.text(columns["volume"]))
        if not symbol or volume is None:
            continue
        current = open_volume.get(symbol, _ZERO)
        if direction == _DIRECTION_IN:
            current += volume
        elif direction in _DIRECTIONS_OUT:
            current -= volume
        elif direction == _DIRECTION_REVERSE:
            current = volume - current
        else:
            continue
        examined += 1
        seen.add(symbol)
        open_volume[symbol] = current
        if current < _ZERO and symbol not in negative_at:
            negative_at[symbol] = row.index
    if examined == 0:
        return RawOutcome.skip("no_qualifying_row")
    first_negative = min(negative_at.values()) if negative_at else None
    figures = (
        _count("n_rows", examined),
        _count("n_hits", len(negative_at)),
        _count("n_symbols", len(seen)),
        _row_figure("first_negative_row", first_negative),
        _count("pre_period_positions", seeded[1])
        if seeded is not None
        else _unmeasured("pre_period_positions"),
    )
    return RawOutcome(
        hits=len(negative_at), figures=figures, examples=_examples(negative_at.values())
    )
