"""Subtractive editing of a real report's bytes, one ``<tr>`` block at a time.

The continuity regression, the forgery lab and the sealed stretch all need
a statement that is *the same file with fewer rows*: never a template, never
a re-serialisation. Every helper here decodes the upload the way the
importers do (``decode_text``), finds the ``<tr>...</tr>`` blocks of the
text, edits or drops whole blocks and re-encodes with the file's own codec
and byte-order mark, so every kept row keeps its original bytes.

Raw row indexes coincide with ``rows.load(data, fmt).rows[i].index``: both
walk the rows the importers' ``_TableReader`` sees, in order (a test pins
this on the fixtures). Only HTML families are editable here; a delimited
export is a list of lines, which a test cuts by itself.
"""

from __future__ import annotations

import bisect
import html
import re
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows

__all__ = [
    "Block",
    "cut_statement",
    "delete_row",
    "drop_cash_row",
    "duplicate_row",
    "move_to_open_section",
    "rename_symbol",
    "rows_of",
    "set_cell",
    "set_header_date",
    "shift_all_times",
    "shift_time",
]

_TR_OPEN = re.compile(r"<tr\b", re.IGNORECASE)
_TR_CLOSE = re.compile(r"</tr\s*>", re.IGNORECASE)
_TABLE_CLOSE = re.compile(r"</table\s*>", re.IGNORECASE)
_SKIPPED = re.compile(
    r"<!--.*?-->|<script\b.*?</script\s*>|<style\b.*?</style\s*>", re.IGNORECASE | re.DOTALL
)
_CELL = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_CELL_OPEN = re.compile(r"<t[dh]\b", re.IGNORECASE)
_CLASS = re.compile(r"""class\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_BOLD = re.compile(r"^(\s*<b>\s*)(.*?)(\s*</b>\s*)$", re.IGNORECASE | re.DOTALL)
_MT_TIME = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$")
_MT4_DATE = re.compile(r"^\d{4}\s+[A-Za-z]+\s+\d{1,2},\s*\d{1,2}:\d{2}$")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_CODECS = {
    "utf8_bom": ("utf-8", b"\xef\xbb\xbf"),
    "utf16le_bom": ("utf-16-le", b"\xff\xfe"),
    "utf16be_bom": ("utf-16-be", b"\xfe\xff"),
    "utf16le": ("utf-16-le", b""),
    "utf16be": ("utf-16-be", b""),
    "utf8": ("utf-8", b""),
    "cp1251": ("cp1251", b""),
    "cp1252": ("cp1252", b""),
    "latin1": ("latin-1", b""),
}
_EDITABLE = frozenset({families.MT4_STATEMENT, families.MT5_HISTORY})
FLOW_KINDS = ("deposit", "withdrawal", "balance", "credit")
_MT4_DATED = frozenset(
    {
        rows.KIND_MT4_CANCELLED,
        rows.KIND_MT4_PENDING,
        rows.KIND_MT4_OPEN,
        rows.KIND_MT4_WORKING,
    }
)
_MT4_TRADE_SECTIONS = frozenset({rows.SECTION_CLOSED, rows.SECTION_OPEN, rows.SECTION_WORKING})


class Block(NamedTuple):
    """One ``<tr>`` block of the decoded text and the texts its cells show."""

    start: int
    end: int
    raw: str
    texts: tuple[str, ...]


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def rows_of(text: str) -> list[Block]:
    """The ``<tr>`` blocks of ``text`` in document order, skipping those
    without a cell (the importers' reader skips them too). Comments, scripts
    and styles are masked so a ``<tr>`` inside them is not a row.

    The texts come from one pass of the importers' reader over the whole
    document when it sees as many rows as there are blocks (the normal
    case); otherwise each block is read on its own."""
    masked = _SKIPPED.sub(lambda match: " " * (match.end() - match.start()), text)
    opens = [match.start() for match in _TR_OPEN.finditer(masked)]
    closes = [(match.start(), match.end()) for match in _TR_CLOSE.finditer(masked)]
    close_starts = [start for start, _ in closes]
    tables = [match.start() for match in _TABLE_CLOSE.finditer(masked)]
    spans: list[tuple[int, int]] = []
    for position, start in enumerate(opens):
        candidates: list[tuple[int, int]] = []
        found = bisect.bisect_left(close_starts, start)
        if found < len(closes):
            candidates.append(closes[found])
        if position + 1 < len(opens):
            candidates.append((opens[position + 1], opens[position + 1]))
        found = bisect.bisect_left(tables, start)
        if found < len(tables):
            candidates.append((tables[found], tables[found]))
        end = min(candidates)[1] if candidates else len(text)
        if _CELL_OPEN.search(masked, start, end) is not None:
            spans.append((start, end))
    reader = importers._read_html(text)
    if len(reader.rows) == len(spans):
        return [
            Block(start, end, text[start:end], tuple(row.texts))
            for (start, end), row in zip(spans, reader.rows, strict=True)
        ]
    blocks: list[Block] = []
    for start, end in spans:
        raw = text[start:end]
        found_rows = importers._read_html(raw).rows
        if found_rows:
            blocks.append(Block(start, end, raw, tuple(found_rows[0].texts)))
    return blocks


class _Document:
    """The decoded text of one upload, its codec and its blocks."""

    def __init__(self, data: bytes) -> None:
        raw = importers.unwrap(data)
        self.codec, self.bom = _CODECS[rows.encoding_code(raw)]
        self.text = importers.decode_text(raw)
        self.blocks = rows_of(self.text)

    def block(self, index: int) -> Block:
        if not 0 <= index < len(self.blocks):
            raise ValueError("row_not_found")
        return self.blocks[index]

    def rebuild(
        self, replaced: dict[int, str | None], inserted: dict[int, list[str]] | None = None
    ) -> bytes:
        """The file with blocks replaced (``None`` drops one) and new
        blocks appended right after the block of an index."""
        pieces: list[str] = []
        cursor = 0
        for index, block in enumerate(self.blocks):
            pieces.append(self.text[cursor : block.start])
            if index in replaced:
                new = replaced[index]
                if new is not None:
                    pieces.append(new)
            else:
                pieces.append(block.raw)
            for extra in (inserted or {}).get(index, []):
                pieces.append("\n" + extra)
            cursor = block.end
        pieces.append(self.text[cursor:])
        return self.bom + "".join(pieces).encode(self.codec, errors="replace")


# ---------------------------------------------------------------------------
# Cells inside a block
# ---------------------------------------------------------------------------


def _class_tokens(attrs: str) -> set[str]:
    match = _CLASS.search(attrs)
    if match is None:
        return set()
    value = match.group(1) or match.group(2) or match.group(3) or ""
    return set(value.split())


def _visible_cells(raw: str) -> list[tuple[int, int, str]]:
    """``(inner start, inner end, inner html)`` of every visible cell."""
    found: list[tuple[int, int, str]] = []
    for match in _CELL.finditer(raw):
        if "hidden" in _class_tokens(match.group(2)):
            continue
        found.append((match.start(3), match.end(3), match.group(3)))
    return found


def _with_cell(raw: str, column: int, content: str, *, raw_html: bool = False) -> str:
    """``raw`` with the visible cell ``column`` showing ``content``; a
    ``<b>`` wrapper around the old content is kept."""
    cells = _visible_cells(raw)
    if not 0 <= column < len(cells):
        raise ValueError("cell_not_found")
    start, end, inner = cells[column]
    new = content if raw_html else html.escape(content, quote=False)
    bold = _BOLD.match(inner)
    if bold is not None:
        new = bold.group(1) + new + bold.group(3)
    return raw[:start] + new + raw[end:]


def _shifted_time(text: str, delta: timedelta) -> str:
    match = _MT_TIME.match(text.strip())
    parsed = importers._one_time(text.strip()) if match is not None else None
    if match is None or parsed is None:
        raise ValueError("not_a_time")
    moment = parsed + delta
    if match.group(4) is None:
        return moment.strftime("%Y.%m.%d")
    if match.group(6) is None:
        return moment.strftime("%Y.%m.%d %H:%M")
    return moment.strftime("%Y.%m.%d %H:%M:%S")


def _shift_block(block: Block, delta: timedelta) -> str:
    raw = block.raw
    for column, text in enumerate(block.texts):
        if importers._is_mt_time(text):
            raw = _with_cell(raw, column, _shifted_time(text, delta))
    return raw


# ---------------------------------------------------------------------------
# One-row helpers
# ---------------------------------------------------------------------------


def delete_row(data: bytes, raw_index: int) -> bytes:
    """The file without the block at ``raw_index``."""
    document = _Document(data)
    document.block(raw_index)
    return document.rebuild({raw_index: None})


def set_cell(data: bytes, raw_index: int, column_index: int, new_text: str) -> bytes:
    """The file with one visible cell's text replaced (attributes kept)."""
    document = _Document(data)
    block = document.block(raw_index)
    return document.rebuild({raw_index: _with_cell(block.raw, column_index, new_text)})


def duplicate_row(
    data: bytes,
    raw_index: int,
    edits: dict[int, str] | None = None,
    *,
    shift: timedelta | None = None,
) -> bytes:
    """The file with a copy of the block inserted right after the original
    (raw index ``raw_index + 1``), its time cells moved by ``shift`` and the
    cells in ``edits`` (column -> text) replaced."""
    document = _Document(data)
    block = document.block(raw_index)
    copy = _shift_block(block, shift) if shift is not None else block.raw
    for column, text in (edits or {}).items():
        copy = _with_cell(copy, column, text)
    return document.rebuild({}, inserted={raw_index: [copy]})


def shift_time(data: bytes, raw_index: int, column_index: int, delta: timedelta) -> bytes:
    """The file with one MetaTrader time cell moved by ``delta`` (same
    precision as printed)."""
    document = _Document(data)
    block = document.block(raw_index)
    if not 0 <= column_index < len(block.texts):
        raise ValueError("cell_not_found")
    moved = _shifted_time(block.texts[column_index], delta)
    return document.rebuild({raw_index: _with_cell(block.raw, column_index, moved)})


def shift_all_times(data: bytes, delta: timedelta) -> bytes:
    """Every MetaTrader time cell of every row moved by ``delta``: a
    synthetic server-clock offset."""
    document = _Document(data)
    replaced: dict[int, str | None] = {}
    for index, block in enumerate(document.blocks):
        if any(importers._is_mt_time(text) for text in block.texts):
            replaced[index] = _shift_block(block, delta)
    return document.rebuild(replaced)


def rename_symbol(data: bytes, old: str, new: str, *, source_format: str | None = None) -> bytes:
    """Every symbol cell equal to ``old`` (case-insensitive) rewritten as
    ``new``, in trade, open, position, deal and order rows."""
    document, table = _open(data, source_format)
    replaced: dict[int, str | None] = {}
    for row in table.rows:
        column = _symbol_column(table, row)
        if column is None or row.text(column).lower() != old.lower():
            continue
        replaced[row.index] = _with_cell(document.blocks[row.index].raw, column, new)
    return document.rebuild(replaced)


def drop_cash_row(
    data: bytes, kind: str, *, before: datetime | None = None, source_format: str | None = None
) -> bytes:
    """The file without its first cash row of ``kind`` (``deposit``,
    ``withdrawal``, ``balance`` or ``credit``), optionally dated at or
    before ``before``. ``ValueError("not_applicable")`` when there is none."""
    if kind not in FLOW_KINDS:
        raise ValueError("unknown_kind")
    document, table = _open(data, source_format)
    limit = _naive(before) if before is not None else None
    for row in table.rows:
        found = _cash_of(table, row)
        if found is None:
            continue
        at, amount = found
        if kind in _kinds_of(row, amount) and (limit is None or at <= limit):
            return document.rebuild({row.index: None})
    raise ValueError("not_applicable")


def set_header_date(data: bytes, when: datetime, *, source_format: str | None = None) -> bytes:
    """The report's own date (MT4 first-row cell, MT5 ``Date:`` label)
    rewritten as ``when``."""
    document, table = _open(data, source_format)
    found = _header_date_cell(table)
    if found is None:
        raise ValueError("no_header_date")
    index, column = found
    return document.rebuild(
        {index: _with_cell(document.blocks[index].raw, column, _date_text(table.family, when))}
    )


def move_to_open_section(data: bytes, raw_index: int, *, source_format: str | None = None) -> bytes:
    """An MT4 closed trade re-listed under ``Open Trades:`` (no close time,
    current price = open price, swap and profit ``0.00``)."""
    document, table = _open(data, source_format)
    if table.family != families.MT4_STATEMENT:
        raise ValueError("not_mt4_statement")
    row = table.rows[raw_index] if 0 <= raw_index < len(table.rows) else None
    if row is None or row.kind != rows.KIND_MT4_TRADE:
        raise ValueError("not_a_closed_trade")
    anchor = _mt4_open_header(table)
    replaced: dict[int, str | None] = {raw_index: None}
    for other in table.rows:
        if other.section == rows.SECTION_OPEN and _is_placeholder(other):
            replaced[other.index] = None
    open_raw = _mt4_as_open(table, row, document.blocks[raw_index].raw)
    return document.rebuild(replaced, inserted={anchor: [open_raw]})


# ---------------------------------------------------------------------------
# cut_statement
# ---------------------------------------------------------------------------


def cut_statement(
    data: bytes,
    *,
    keep_from: datetime | None = None,
    keep_to: datetime | None = None,
    blank_balances: bool = False,
    keep_flows_from: datetime | None = None,
    source_format: str | None = None,
) -> bytes:
    """A shorter statement made of the original rows.

    Tail cut (``keep_to = D``): closed trades with ``close <= D`` and cash
    rows with ``at <= D`` stay; a trade open across ``D`` is re-listed as
    open (MT4: under ``Open Trades:``; MT5: at the end of the Positions
    table without a close time, a shape not yet verified against a real
    export); the totals and summary rows go; the header date becomes ``D``.
    Balance cells are left as printed (cumulative in time).

    Head cut (``keep_from = S``): closed trades with ``open >= S`` and cash
    rows with ``at >= S`` stay; trades straddling ``S`` go entirely (MT5:
    the exit deal matched on symbol, time and price goes too, the entry
    deal is before ``S``); ``blank_balances`` empties every Deals ``Balance``
    cell so the importer builds the curve from the declared starting
    balance. ``keep_flows_from`` moves the cash-row threshold on its own
    (the sealed stretch folds flows dated before its first trade into the
    starting balance).

    Only MT4 statements and MT5 history pages are editable this way
    (``ValueError("not_editable")`` otherwise).
    """
    if keep_from is None and keep_to is None:
        raise ValueError("no_cut")
    document, table = _open(data, source_format)
    if table.family not in _EDITABLE:
        raise ValueError("not_editable")
    start = _naive(keep_from) if keep_from is not None else None
    end = _naive(keep_to) if keep_to is not None else None
    flows_from = _naive(keep_flows_from) if keep_flows_from is not None else start
    if table.family == families.MT4_STATEMENT:
        replaced, inserted = _cut_mt4(document, table, start, end, flows_from)
    else:
        replaced, inserted = _cut_mt5(document, table, start, end, flows_from, blank_balances)
    if end is not None:
        found = _header_date_cell(table)
        if found is not None:
            index, column = found
            base = replaced.get(index, document.blocks[index].raw)
            if base is not None:
                replaced[index] = _with_cell(base, column, _date_text(table.family, end))
    return document.rebuild(replaced, inserted=inserted)


def _cut_mt4(
    document: _Document,
    table: rows.RawTable,
    start: datetime | None,
    end: datetime | None,
    flows_from: datetime | None,
) -> tuple[dict[int, str | None], dict[int, list[str]]]:
    replaced: dict[int, str | None] = {}
    moved: list[str] = []
    previous_kept = True
    for row in table.rows:
        block = document.blocks[row.index]
        keep = True
        if row.kind == rows.KIND_MT4_TRADE:
            columns = rows.mt4_columns(table, row)
            opened = _time_of(row.text(columns["open_time"]))
            closed = _time_of(row.text(columns["close_time"]))
            keep = _keep_trade(opened, closed, start, end)
            if keep and end is not None and closed is not None and closed > end:
                moved.append(_mt4_as_open(table, row, block.raw))
                keep = False
        elif row.kind in {rows.KIND_MT4_CASH, rows.KIND_MT4_CREDIT}:
            at = _time_of(row.text(rows.mt4_columns(table, row)["open_time"]))
            keep = _within(at, flows_from, end)
        elif row.kind in _MT4_DATED:
            at = _time_of(row.text(rows.mt4_columns(table, row)["open_time"]))
            keep = _within(at, start, end)
        elif row.kind == rows.KIND_FOOTER:
            keep = False
        elif row.kind == rows.KIND_LABEL:
            keep = row.section == rows.SECTION_HEADER
        elif row.kind == rows.KIND_OTHER and row.section in _MT4_TRADE_SECTIONS:
            # A comment row follows its trade; ``No transactions`` is settled below.
            keep = previous_kept or _is_placeholder(row)
        if not keep:
            replaced[row.index] = None
        previous_kept = keep
    inserted: dict[int, list[str]] = {}
    if moved:
        inserted[_mt4_open_header(table)] = moved
        for row in table.rows:
            if row.section == rows.SECTION_OPEN and _is_placeholder(row):
                replaced[row.index] = None
    return replaced, inserted


def _cut_mt5(
    document: _Document,
    table: rows.RawTable,
    start: datetime | None,
    end: datetime | None,
    flows_from: datetime | None,
    blank_balances: bool,
) -> tuple[dict[int, str | None], dict[int, list[str]]]:
    replaced: dict[int, str | None] = {}
    converted: list[str] = []
    last_position: int | None = None
    positions_header: int | None = None
    straddlers: list[tuple[str, datetime, str]] = []
    for row in table.rows:
        block = document.blocks[row.index]
        keep = True
        if row.kind == rows.KIND_MT5_POSITION:
            columns = rows.mt5_position_columns(table, row)
            opened = _time_of(row.text(columns["open"]))
            closed = _time_of(row.text(columns["close"]))
            keep = _keep_trade(opened, closed, start, end)
            if (
                not keep
                and start is not None
                and opened is not None
                and closed is not None
                and opened < start <= closed
            ):
                symbol = row.text(columns["symbol"]).lower()
                straddlers.append((symbol, closed, row.text(columns["close_price"])))
            if keep and end is not None and closed is not None and closed > end:
                converted.append(_mt5_as_open(columns, block.raw))
                keep = False
            if keep:
                last_position = row.index
        elif row.kind == rows.KIND_HEADER and row.section == rows.SECTION_POSITIONS:
            if positions_header is None:
                positions_header = row.index
        elif row.kind == rows.KIND_MT5_OPEN_POSITION:
            keep = _within(_time_of(row.text(0)), start, end)
        elif row.kind == rows.KIND_MT5_DEAL:
            columns = rows.mt5_columns(table, row)
            at = _time_of(row.text(columns["time"]))
            is_balance = row.text(columns["type"]).lower() == "balance"
            keep = _within(at, flows_from if is_balance else start, end)
            if keep and not is_balance and straddlers:
                keep = not _closes_straddler(row, columns, straddlers)
            if keep and blank_balances and "balance" in columns:
                replaced[row.index] = _with_cell(block.raw, columns["balance"], "")
        elif row.kind == rows.KIND_MT5_ORDER:
            placed = _time_of(row.text(0))
            filled = _time_of(row.text(8))
            keep = _within(placed, start, None) and _within(filled or placed, None, end)
        elif row.kind == rows.KIND_FOOTER:
            keep = False
        elif row.kind == rows.KIND_LABEL:
            keep = row.section == rows.SECTION_HEADER
        if not keep:
            replaced[row.index] = None
    inserted: dict[int, list[str]] = {}
    if converted:
        anchor = last_position if last_position is not None else positions_header
        if anchor is None:
            raise ValueError("no_positions_section")
        inserted[anchor] = converted
    return replaced, inserted


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------


def _open(data: bytes, source_format: str | None) -> tuple[_Document, rows.RawTable]:
    """The document and its classified rows; the format is detected from
    the content when the caller does not pass the one already known."""
    document = _Document(data)
    if source_format is None:
        source_format = importers.detect_format(data)
    table = rows.load(data, source_format)
    if table.family in families.CSV_FAMILIES or not document.blocks:
        raise ValueError("not_editable")
    if len(document.blocks) != len(table.rows):
        raise ValueError("rows_misaligned")
    return document, table


def _naive(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def _time_of(text: str) -> datetime | None:
    if not importers._is_mt_time(text.strip()):
        return None
    parsed = importers._one_time(text.strip())
    return None if parsed is None else _naive(parsed)


def _within(at: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if at is None:
        return True
    if start is not None and at < start:
        return False
    return not (end is not None and at > end)


def _keep_trade(
    opened: datetime | None,
    closed: datetime | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Whether a closed trade stays (it may still be re-listed as open when
    it closes after ``end``)."""
    if opened is None or closed is None:
        return True
    if start is not None and opened < start:
        return False
    return not (end is not None and opened > end)


def _cash_of(table: rows.RawTable, row: rows.RawRow) -> tuple[datetime, float] | None:
    """``(time, amount)`` of an MT4 balance/credit row or an MT5 balance deal."""
    if row.kind in {rows.KIND_MT4_CASH, rows.KIND_MT4_CREDIT}:
        at_column = rows.mt4_columns(table, row)["open_time"]
        at = _time_of(row.text(at_column))
        amounts = [
            value
            for value in (importers._num(text) for text in row.texts[at_column + 2 :])
            if value is not None
        ]
        if at is None or not amounts:
            return None
        return at, amounts[-1]
    if row.kind == rows.KIND_MT5_DEAL:
        columns = rows.mt5_columns(table, row)
        if row.text(columns["type"]).lower() != "balance":
            return None
        at = _time_of(row.text(columns["time"]))
        amount = importers._num(row.text(columns["profit"]))
        if at is None or amount is None:
            return None
        return at, amount
    return None


def _kinds_of(row: rows.RawRow, amount: float) -> set[str]:
    """The flow kinds a cash row answers to."""
    if row.kind == rows.KIND_MT4_CREDIT:
        return {"credit"}
    kinds = {"balance"}
    if amount > 0:
        kinds.add("deposit")
    elif amount < 0:
        kinds.add("withdrawal")
    return kinds


def _symbol_column(table: rows.RawTable, row: rows.RawRow) -> int | None:
    if row.kind in {rows.KIND_MT4_TRADE, rows.KIND_MT4_OPEN}:
        return rows.mt4_columns(table, row)["symbol"]
    if row.kind == rows.KIND_MT5_POSITION:
        return rows.mt5_position_columns(table, row)["symbol"]
    if row.kind == rows.KIND_MT5_DEAL:
        return rows.mt5_columns(table, row).get("symbol")
    if row.kind in {rows.KIND_MT5_ORDER, rows.KIND_MT5_OPEN_POSITION}:
        return 2
    return None


def _is_placeholder(row: rows.RawRow) -> bool:
    """MT4's one-cell ``No transactions`` row of an empty section."""
    return (
        row.kind == rows.KIND_OTHER
        and len(row.texts) == 1
        and bool(row.texts[0])
        and not any(character.isdigit() for character in row.texts[0])
    )


def _mt4_open_header(table: rows.RawTable) -> int:
    for row in table.rows:
        if row.kind == rows.KIND_HEADER and row.section == rows.SECTION_OPEN:
            return row.index
    raise ValueError("no_open_section")


def _mt4_as_open(table: rows.RawTable, row: rows.RawRow, raw: str) -> str:
    columns = rows.mt4_columns(table, row)
    out = _with_cell(raw, columns["close_time"], "&nbsp;", raw_html=True)
    out = _with_cell(out, columns["close_price"], row.text(columns["open_price"]))
    out = _with_cell(out, columns["profit"], "0.00")
    if "swap" in columns:
        out = _with_cell(out, columns["swap"], "0.00")
    return out


def _mt5_as_open(columns: dict[str, int], raw: str) -> str:
    out = _with_cell(raw, columns["close"], "")
    out = _with_cell(out, columns["close_price"], "")
    out = _with_cell(out, columns["profit"], "0.00")
    return _with_cell(out, columns["swap"], "0.00")


def _closes_straddler(
    row: rows.RawRow, columns: dict[str, int], straddlers: list[tuple[str, datetime, str]]
) -> bool:
    if row.text(columns["direction"]).lower() not in {"out", "out by", "in/out"}:
        return False
    symbol = row.text(columns.get("symbol", 2)).lower()
    at = _time_of(row.text(columns["time"]))
    price = importers._num(row.text(columns["price"]))
    for straddler_symbol, closed, close_price in straddlers:
        if symbol != straddler_symbol or at != closed:
            continue
        expected = importers._num(close_price)
        if expected is None or price is None or abs(expected - price) <= 1e-9:
            return True
    return False


def _header_date_cell(table: rows.RawTable) -> tuple[int, int] | None:
    """``(raw index, column)`` of the report's date cell, if printed."""
    if table.family == families.MT4_STATEMENT and table.rows:
        first = table.rows[0]
        for column, text in enumerate(first.texts):
            if _MT4_DATE.match(text.strip()):
                return first.index, column
    if table.family == families.MT5_HISTORY:
        for row in table.rows:
            if row.section != rows.SECTION_HEADER:
                break
            if row.kind != rows.KIND_LABEL:
                continue
            for column, text in enumerate(row.texts):
                if column > 0 and " " in text and importers._is_mt_time(text):
                    return row.index, column
    return None


def _date_text(family: str, when: datetime) -> str:
    when = _naive(when)
    if family == families.MT4_STATEMENT:
        return f"{when.year} {_MONTHS[when.month - 1]} {when.day}, {when:%H:%M}"
    return when.strftime("%Y.%m.%d %H:%M")
