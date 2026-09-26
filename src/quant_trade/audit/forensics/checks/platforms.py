"""Platform invariants of the two delimited trade lists (§3.21, §3.22).

``TV_INVARIANTS`` reads a TradingView "List of trades": every trade is one
entry row and one exit row that repeat the trade-level values, the trade
numbers run without gaps, the cumulative P&L at a flat moment is the sum of
every trade closed by then (TradingView adds the open P&L of trades still
open, so other moments are not examined), ``Size (value)`` is the entry
price times the quantity times one multiplier per file, ``Return %`` is the
net P&L over that value plus the entry's share of the commission, and no
exit precedes its entry. The trade closed last may be an end-of-data close
and is left out of the three value identities.

``NT_INVARIANTS`` reads a NinjaTrader "Trades" grid: trade numbers run
without gaps or repeats, ``Cum. net profit`` is the running sum of
``Profit`` in trade-number order across the whole grid (also when it holds
several accounts), ``ETD == MFE - Profit`` and no exit precedes its entry.

Both are ``INFO`` by design in v1. Column names come from the importers'
own readers (``_is_tradingview_header``, ``_tv_columns``,
``_ninjatrader_index``), called read-only; times through ``_parse_times``,
which decides day-first once per column exactly as the importer did.
Figures hold counts, codes and derived numbers only: no symbol, account,
signal or comment text ever leaves the file.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quant_trade.audit import importers
from quant_trade.audit.forensics import families
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.money import as_text, parse_money
from quant_trade.audit.forensics.results import MAX_EXAMPLES, MEASURED, Figure, RawOutcome
from quant_trade.audit.forensics.rows import KIND_CSV, RawRow, RawTable
from quant_trade.audit.forensics.thresholds import (
    MONEY_TOLERANCE,
    RATIO_TOLERANCE,
    TV_CUMULATIVE_SLACK_BASE,
    TV_CUMULATIVE_SLACK_PER_ROW,
)

_INTEGER = re.compile(r"^\d+$")
#: A NinjaTrader money cell in the "Currency" display unit carries a sign or a code.
_CURRENCY_MARK = re.compile(r"[$€£¥]|[A-Z]{3}")
#: TradingView columns whose value belongs to the trade, printed on both rows.
_TV_TRADE_LEVEL = re.compile(
    r"^(run-up|drawdown|favorable excursion|adverse excursion|mfe|mae"
    r"|positive exkursion|negative exkursion)( .+)?$"
    r"|^(net p&l|net pnl|profit|g&v netto|cum\. profit|cumulative p&l|cumulative pnl"
    r"|kumulativer g&v|return|commission) %$"
    r"|^(duration|dauer)( \(.+\))?$"
)
_TV_SIZE_VALUE = re.compile(r"^(position size \(value\)|size \(value\)|größe \(wert\))$")
_TV_RETURN_PCT = re.compile(r"^return %$")
#: The ratio ``Size (value) / (entry price × qty)`` is read to this grid before
#: the file's one multiplier is chosen (the most common ratio, smallest on a tie).
_MULTIPLIER_GRID = Decimal("0.000001")
#: TradingView prints P&L with this many significant digits (trailing zeros
#: trimmed); a printed value is rounded at that digit.
TV_SIGNIFICANT_DIGITS = 8
_HUNDRED = Decimal(100)
_TWO = Decimal(2)

_NT_REQUIRED = frozenset({"profit"})


def _count(key: str, value: int) -> Figure:
    return (key, str(value), MEASURED)


def _number(text: str) -> int | None:
    """A trade number: digits only (``_as_text`` already wrote ``1.0`` as ``1``)."""
    value = text.strip()
    return int(value) if _INTEGER.match(value) else None


def _times(texts: list[str], *, serial: bool) -> list[datetime | None] | None:
    """One column of times through the importer's parser, ``None`` when the
    column cannot be read at all (ambiguous day/month order)."""
    try:
        return importers._parse_times(texts, serial_numbers=serial).values
    except importers.ReportFormatError:
        return None


def _suffix(header_text: str) -> str:
    """The currency token of a TradingView column name (``Price USD`` → ``USD``)."""
    tokens = header_text.split()
    if len(tokens) < 2:
        return ""
    last = tokens[-1]
    return "" if last == "%" or last.endswith(")") else last


def _same_cell(left: str, right: str) -> bool:
    a, b = parse_money(left), parse_money(right)
    if a is not None and b is not None:
        return a == b
    return left.strip() == right.strip()


def _examples(indexes: list[int]) -> tuple[int, ...]:
    return tuple(sorted(set(indexes))[:MAX_EXAMPLES])


# ---------------------------------------------------------------------------
# TradingView
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Trade:
    number: int
    rows: tuple[RawRow, ...]
    entry: RawRow | None
    exit: RawRow | None
    is_open: bool

    @property
    def first_index(self) -> int:
        return self.rows[0].index


def _tv_trades(
    rows: tuple[RawRow, ...],
    columns: dict[str, int],
    times: list[datetime | None] | None,
    position: dict[int, int],
) -> tuple[list[_Trade], list[RawRow]]:
    """Rows grouped by trade number, in ascending number order; rows without
    a number come back separately."""
    groups: dict[int, list[RawRow]] = {}
    unnumbered: list[RawRow] = []
    for row in rows:
        number = _number(row.text(columns["trade"]))
        if number is None:
            unnumbered.append(row)
        else:
            groups.setdefault(number, []).append(row)
    trades: list[_Trade] = []
    for number in sorted(groups):
        members = tuple(groups[number])
        trades.append(_tv_trade(number, members, columns, times, position))
    return trades, unnumbered


def _tv_trade(
    number: int,
    members: tuple[RawRow, ...],
    columns: dict[str, int],
    times: list[datetime | None] | None,
    position: dict[int, int],
) -> _Trade:
    entry: RawRow | None = None
    exit_: RawRow | None = None
    if len(members) == 2:
        roles = {importers._tv_role(row.text(columns["type"])): row for row in members}
        if set(roles) == {"entry", "exit"}:
            entry, exit_ = roles["entry"], roles["exit"]
        elif times is not None:
            first, second = members
            moments = times[position[first.index]], times[position[second.index]]
            if moments[0] is not None and moments[1] is not None:
                entry, exit_ = (first, second) if moments[0] <= moments[1] else (second, first)
    elif len(members) == 1 and importers._tv_role(members[0].text(columns["type"])) == "entry":
        entry = members[0]
    is_open = False
    if exit_ is not None:
        signal = exit_.text(columns["signal"]).lower() if "signal" in columns else ""
        blank = not exit_.text(columns["time"]).strip() and not exit_.text(columns["price"]).strip()
        is_open = signal in importers._TV_OPEN_SIGNALS or blank
    elif entry is not None and len(members) == 1:
        is_open = True
    return _Trade(number, members, entry, exit_, is_open)


def _tv_multiplier(
    closed: list[_Trade], columns: dict[str, int], size_column: int
) -> Decimal | None:
    """The file's one contract multiplier: the most common ratio, smallest on a tie."""
    counts: dict[Decimal, int] = {}
    for trade in closed:
        assert trade.entry is not None and trade.exit is not None
        value = parse_money(trade.exit.text(size_column))
        price = parse_money(trade.entry.text(columns["price"]))
        qty = parse_money(trade.exit.text(columns["qty"]))
        if value is None or price is None or qty is None or price * qty == 0:
            continue
        ratio = (value / (price * qty)).quantize(_MULTIPLIER_GRID)
        counts[ratio] = counts.get(ratio, 0) + 1
    if not counts:
        return None
    best = max(counts.values())
    return min(ratio for ratio, count in counts.items() if count == best)


def _half_unit(value: Decimal) -> Decimal:
    """Half of the last digit TradingView prints: eight significant digits."""
    if value == 0:
        return Decimal(0)
    return Decimal(5).scaleb(value.adjusted() - TV_SIGNIFICANT_DIGITS)


@dataclass(frozen=True)
class _Closed:
    """A closed trade with both times, in the cumulative sweep."""

    trade: _Trade
    entry_at: datetime
    exit_at: datetime
    net: Decimal
    cum: Decimal | None


def _tv_cumulative(
    closed: list[_Closed], last: _Trade | None, hit: Callable[[str, _Trade], None]
) -> int:
    """Cumulative P&L against the sum of every trade closed by then, at flat
    moments only: TradingView adds the open P&L of trades still open at an
    exit (pyramiding, partial exits, margin calls), so a moment with another
    trade open, or with two exits at once, is not examined. The last trade
    closed may be an end-of-data close and is not examined either. Returns
    the number of trades examined."""
    by_exit = sorted(closed, key=lambda item: (item.exit_at, item.trade.number))
    exits = [item.exit_at for item in by_exit]
    entries = sorted(item.entry_at for item in by_exit)
    sums = [Decimal(0)]
    slack = [Decimal(0)]
    for item in by_exit:
        sums.append(sums[-1] + item.net)
        slack.append(slack[-1] + max(TV_CUMULATIVE_SLACK_PER_ROW, _half_unit(item.net)))
    examined = 0
    for item in by_exit:
        if item.cum is None or (last is not None and item.trade.number == last.number):
            continue
        moment = item.exit_at
        closed_by = bisect.bisect_right(exits, moment)
        closed_before = bisect.bisect_left(exits, moment)
        entered_by = bisect.bisect_right(entries, moment)
        if entered_by - closed_by > 0 or closed_by - closed_before > 1:
            continue
        examined += 1
        allowed = slack[closed_by] + max(TV_CUMULATIVE_SLACK_BASE, _half_unit(item.cum))
        if abs(item.cum - sums[closed_by]) > allowed:
            hit("cumulative", item.trade)
    return examined


def run_TV_INVARIANTS(table: RawTable, ctx: Context) -> RawOutcome:
    if table.family != families.TRADINGVIEW:
        return RawOutcome.skip("format_not_covered")
    if not table.header or not importers._is_tradingview_header(table.header):
        return RawOutcome.skip("no_table")
    try:
        columns, _currency = importers._tv_columns(table.header)
    except importers.ReportFormatError:
        return RawOutcome.skip("no_column")
    rows = table.kind(KIND_CSV)
    if not rows:
        return RawOutcome.skip("no_qualifying_row")
    serial = table.source_format in families.XLSX_FORMATS
    times = _times([row.text(columns["time"]) for row in rows], serial=serial)
    position = {row.index: at for at, row in enumerate(rows)}
    trades, unnumbered = _tv_trades(rows, columns, times, position)
    names = [text.lower() for text in table.header]
    trade_level = sorted(
        {columns[key] for key in ("qty", "net", "cum", "cum_pct", "commission") if key in columns}
        | {at for at, name in enumerate(names) if _TV_TRADE_LEVEL.match(name)}
        | {at for at, name in enumerate(names) if _TV_SIZE_VALUE.match(name)}
    )
    size_column = next((at for at, name in enumerate(names) if _TV_SIZE_VALUE.match(name)), None)
    return_column = next((at for at, name in enumerate(names) if _TV_RETURN_PCT.match(name)), None)
    # Return % is read only when the export itemises the commission it charges
    # and prices and P&L share a currency (a commission that is not printed
    # still sits in TradingView's denominator).
    return_examinable = (
        return_column is not None
        and size_column is not None
        and "commission" in columns
        and _suffix(table.header[columns["price"]]) == _suffix(table.header[columns["net"]])
    )

    hits: dict[tuple[str, int], int] = {}  # ("trade", number) | ("row", index) -> raw index
    counts = {
        "numbering_start": 0,
        "numbering_gaps": 0,
        "pair_shape": 0,
        "pair_values": 0,
        "size_value": 0,
        "cumulative": 0,
        "return_pct": 0,
        "exit_before_entry": 0,
    }
    examined = {"size_value": 0, "cumulative": 0, "return_pct": 0, "time": 0}

    def hit(key: str, trade: _Trade) -> None:
        counts[key] += 1
        hits.setdefault(("trade", trade.number), trade.first_index)

    closed: list[_Trade] = []
    timed: list[_Closed] = []
    previous: int | None = None
    for trade in trades:
        if previous is None:
            if trade.number != 1:
                hit("numbering_start", trade)
        elif trade.number != previous + 1:
            hit("numbering_gaps", trade)
        previous = trade.number
        if trade.entry is None or trade.exit is None:
            if not trade.is_open:
                hit("pair_shape", trade)
            continue
        if trade.is_open:
            continue
        closed.append(trade)
        if any(not _same_cell(trade.entry.text(at), trade.exit.text(at)) for at in trade_level):
            hit("pair_values", trade)
        if times is None:
            continue
        entry_at = times[position[trade.entry.index]]
        exit_at = times[position[trade.exit.index]]
        if entry_at is None or exit_at is None:
            continue
        examined["time"] += 1
        if exit_at < entry_at:
            hit("exit_before_entry", trade)
            continue
        net = parse_money(trade.exit.text(columns["net"]))
        cum = parse_money(trade.exit.text(columns["cum"])) if "cum" in columns else None
        if net is not None:
            timed.append(_Closed(trade, entry_at, exit_at, net, cum))

    # The trade closed last (latest exit, highest number on a tie) may be an
    # end-of-data close: its value, return and cumulative are not examined.
    last: _Trade | None = None
    if timed and len(timed) == len(closed):
        last = max(timed, key=lambda item: (item.exit_at, item.trade.number)).trade
        examined["cumulative"] = _tv_cumulative(timed, last, hit)

    multiplier = _tv_multiplier(closed, columns, size_column) if size_column is not None else None
    for trade in closed:
        assert trade.entry is not None and trade.exit is not None
        if size_column is None or multiplier is None:
            break
        if last is not None and trade.number == last.number:
            continue
        value = parse_money(trade.exit.text(size_column))
        price = parse_money(trade.entry.text(columns["price"]))
        qty = parse_money(trade.exit.text(columns["qty"]))
        if value is None or price is None or qty is None or price * qty == 0:
            continue
        examined["size_value"] += 1
        if abs(value - price * qty * multiplier) > MONEY_TOLERANCE:
            hit("size_value", trade)
        if not return_examinable or value == 0:
            continue
        assert return_column is not None
        net = parse_money(trade.exit.text(columns["net"]))
        printed = parse_money(trade.exit.text(return_column))
        commission = abs(parse_money(trade.exit.text(columns["commission"])) or Decimal(0))
        if net is None or printed is None:
            continue
        # The denominator is the entry value plus the entry order's share of the
        # commission; that share is not printed, so the band covers every share
        # between none and all of it, around half.
        denominator = value + commission / _TWO
        if denominator == 0:
            continue
        examined["return_pct"] += 1
        expected = net / denominator * _HUNDRED
        allowed = (
            RATIO_TOLERANCE
            + MONEY_TOLERANCE / _TWO * _HUNDRED / denominator
            + abs(net) * (commission / _TWO) / (denominator * denominator) * _HUNDRED
        )
        if abs(printed - expected) > allowed:
            hit("return_pct", trade)

    for row in unnumbered:
        counts["pair_shape"] += 1
        hits.setdefault(("row", row.index), row.index)

    figures: list[Figure] = [
        _count("n_rows", len(rows)),
        _count("n_trades", len(trades)),
        _count("n_open", sum(1 for trade in trades if trade.is_open)),
        _count("n_closed", len(closed)),
        _count("rows_without_number", len(unnumbered)),
        _count("n_hits", len(hits)),
    ]
    figures.extend(_count(key, value) for key, value in counts.items())
    figures.extend(_count(f"{key}_examined", value) for key, value in examined.items())
    figures.append(_count("last_trade_excluded", 1 if last is not None else 0))
    if multiplier is not None and examined["size_value"]:
        figures.append(("size_multiplier", as_text(multiplier.normalize()), MEASURED))
    return RawOutcome(
        hits=len(hits), figures=tuple(figures), examples=_examples(list(hits.values()))
    )


# ---------------------------------------------------------------------------
# NinjaTrader
# ---------------------------------------------------------------------------


def _nt_cell(row: RawRow, columns: dict[str, int], name: str) -> str:
    at = columns.get(name)
    return row.text(at) if at is not None else ""


def run_NT_INVARIANTS(table: RawTable, ctx: Context) -> RawOutcome:
    if table.family != families.NINJATRADER:
        return RawOutcome.skip("format_not_covered")
    if not table.header:
        return RawOutcome.skip("no_table")
    columns = importers._ninjatrader_index(list(table.header))
    if not set(columns) >= _NT_REQUIRED:
        return RawOutcome.skip("no_column")
    rows = table.kind(KIND_CSV)
    if not rows:
        return RawOutcome.skip("no_qualifying_row")
    # A grid holding several accounts still numbers its trades and runs its
    # cumulative across every row, so the accounts are counted, not split.
    accounts = {_nt_cell(row, columns, "account").strip() for row in rows}
    accounts.discard("")
    # Display unit: only the "Currency" grid carries a sign or a code on Profit.
    if not any(_CURRENCY_MARK.search(_nt_cell(row, columns, "profit")) for row in rows):
        return RawOutcome.skip("no_qualifying_row")

    # Trade-number order (the grid may have been sorted by any column before export),
    # ties by raw index; a grid without a number column keeps its file order.
    has_numbers = "trade number" in columns
    numbered: list[tuple[int, RawRow]] = []
    unnumbered: list[RawRow] = []
    if has_numbers:
        for row in rows:
            number = _number(_nt_cell(row, columns, "trade number"))
            if number is None:
                unnumbered.append(row)
            else:
                numbered.append((number, row))
        ordered = sorted(numbered, key=lambda item: (item[0], item[1].index))
    else:
        ordered = [(at, row) for at, row in enumerate(rows, start=1)]

    hits: dict[int, int] = {}
    counts = {
        "numbering_start": 0,
        "numbering_gaps": 0,
        "numbering_duplicates": 0,
        "cumulative": 0,
        "etd": 0,
        "exit_before_entry": 0,
    }
    examined = {"cumulative": 0, "etd": 0, "time": 0}

    def hit(key: str, row: RawRow) -> None:
        counts[key] += 1
        hits.setdefault(row.index, row.index)

    entry_texts = [_nt_cell(row, columns, "entry time") for _n, row in ordered]
    exit_texts = [_nt_cell(row, columns, "exit time") for _n, row in ordered]
    both = _times(entry_texts + exit_texts, serial=False) if "entry time" in columns else None
    running = Decimal(0)
    previous: int | None = None
    for k, (number, row) in enumerate(ordered, start=1):
        if has_numbers:
            if previous is None:
                if number != 1:
                    hit("numbering_start", row)
            elif number == previous:
                hit("numbering_duplicates", row)
            elif number != previous + 1:
                hit("numbering_gaps", row)
            previous = number
        profit = parse_money(_nt_cell(row, columns, "profit"))
        if profit is not None:
            running += profit
            cum = parse_money(_nt_cell(row, columns, "cum. net profit"))
            if cum is not None:
                examined["cumulative"] += 1
                if abs(cum - running) > MONEY_TOLERANCE * k:
                    hit("cumulative", row)
            mfe = parse_money(_nt_cell(row, columns, "mfe"))
            etd = parse_money(_nt_cell(row, columns, "etd"))
            if mfe is not None and etd is not None:
                examined["etd"] += 1
                if abs(etd - (mfe - profit)) > MONEY_TOLERANCE:
                    hit("etd", row)
        if both is not None:
            entry_at, exit_at = both[k - 1], both[len(ordered) + k - 1]
            if entry_at is not None and exit_at is not None:
                examined["time"] += 1
                if exit_at < entry_at:
                    hit("exit_before_entry", row)
    for row in unnumbered:
        hits.setdefault(row.index, row.index)

    figures: list[Figure] = [
        _count("n_rows", len(rows)),
        _count("n_trades", len(ordered)),
        _count("n_accounts", len(accounts)),
        _count("rows_without_number", len(unnumbered)),
        _count("n_hits", len(hits)),
    ]
    figures.extend(_count(key, value) for key, value in counts.items())
    figures.extend(_count(f"{key}_examined", value) for key, value in examined.items())
    return RawOutcome(
        hits=len(hits), figures=tuple(figures), examples=_examples(list(hits.values()))
    )
