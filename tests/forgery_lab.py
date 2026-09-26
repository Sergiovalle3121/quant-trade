"""Forgery lab: one-step alterations of a real report and which check finds them.

Every alteration ("seed") is one edit a forger could make by hand on the
raw file: delete a losing row, change one profit, move a close time into
the weekend, duplicate a winning trade, edit a summary total, hide a row.
The HTML families are edited with ``forensics.edit`` (whole ``<tr>``
blocks, the file's own bytes and codec); the delimited families by plain
text replacement of one line. The battery runs on the original and on the
altered bytes, and a check "finds" the seed when its hit count rose or its
status moved from not found (``CLEAN`` / ``NOT_MEASURED``) to found
(``INFO`` / ``SIGNAL``): whether it says ``INFO`` or ``SIGNAL`` is the
calibration table's business, not the file's.

Usage::

    python tests/forgery_lab.py --fixtures [--out RESULT.json]
    python tests/forgery_lab.py MANIFEST ROOT [--reserved|--all] [--out RESULT.json]

The corpus run is read-only over genuine files; its output holds counts,
check ids, manifest paths, SHA-256 prefixes and figures, never a cell of a
file. Everything here is deterministic: no clock, no randomness, sorted
output.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.audit import factsheet, importers
from quant_trade.audit.forensics import edit, families, money, review, rows, symbols
from quant_trade.audit.forensics.checks import totals
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import STATUS_INFO, STATUS_SIGNAL, ForensicResult
from quant_trade.audit.forensics.rows import RawRow, RawTable

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
#: Files above this size are skipped in the corpus run (runtime), with a note.
MAX_CORPUS_BYTES = 2_000_000
FOUND_STATUSES = frozenset({STATUS_INFO, STATUS_SIGNAL})
MONTHLY = families.MONTHLY

MT4 = families.MT4_STATEMENT
MT5 = families.MT5_HISTORY
MT5T = families.MT5_TESTER
MT4T = families.MT4_TESTER
MYFX = families.MYFXBOOK
MQL5 = families.MQL5_SIGNAL
FXB = families.FXBLUE
TV = families.TRADINGVIEW
NT = families.NINJATRADER
HTML = (MT4, MT5, MT5T, MT4T)
CSV = (MYFX, MQL5, FXB, TV, NT)
ALL = HTML + CSV
#: Families whose row order is judged by the majority direction of the
#: file (a swap needs three rows before it can run against the majority).
_MAJORITY_ORDER = frozenset({MT4, MYFX, MQL5, FXB, TV, NT})

Apply = Callable[[bytes, RawTable], "bytes | None"]
FrameApply = Callable[[pd.DataFrame], pd.DataFrame]

_ONE_MINUTE = timedelta(minutes=1)
_ONE_DAY = timedelta(days=1)
_TICKS_WORSE = 10
_SUMMARY_SHIFT = Decimal("100.00")
_HIDDEN_NUMBER = "5.00"
_HIDDEN_TEXT = "n/a"
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
_EXTENSION = {"html": "htm", "xlsx": "xlsx", "csv": "csv", "xml": "xml"}


# ---------------------------------------------------------------------------
# Seeds and results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Seed:
    """One alteration: ``apply(data, table)`` returns the altered bytes, or
    ``None`` when the file has no qualifying row. ``expected_checks`` are
    the checks the spec says should find it; ``overrides`` replace them for
    one family (an empty tuple documents a known limit)."""

    id: str
    families: tuple[str, ...]
    apply: Apply
    expected_checks: tuple[str, ...]
    overrides: tuple[tuple[str, tuple[str, ...]], ...] = ()
    edit: str = ""
    apply_frame: FrameApply | None = None

    def expected_for(self, family: str) -> tuple[str, ...]:
        for name, checks in self.overrides:
            if name == family:
                return checks
        return self.expected_checks


@dataclass(frozen=True)
class SeedResult:
    seed_id: str
    applied: bool
    found_by: tuple[str, ...]
    expected_found: bool
    family: str = ""
    expected: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    figures: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    """The figures of every expected check after the alteration."""
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed_id,
            "family": self.family,
            "applied": self.applied,
            "found_by": list(self.found_by),
            "expected": list(self.expected),
            "expected_found": self.expected_found,
            "unexpected": list(self.unexpected),
            "figures": {check: dict(items) for check, items in self.figures},
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Raw editing: HTML blocks and delimited lines
# ---------------------------------------------------------------------------


def _codec(raw: bytes) -> tuple[str, bytes]:
    return _CODECS[rows.encoding_code(raw)]


def _html_editable(table: RawTable) -> bool:
    return (
        table.family in families.HTML_FAMILIES and table.source_format not in families.XLSX_FORMATS
    )


class _Html:
    """The decoded page and its ``<tr>`` blocks, aligned with ``table.rows``."""

    def __init__(self, data: bytes, table: RawTable) -> None:
        if not _html_editable(table):
            raise ValueError("not_editable")
        raw = importers.unwrap(data)
        self.codec, self.bom = _codec(raw)
        self.text = importers.decode_text(raw)
        self.blocks = edit.rows_of(self.text)
        if len(self.blocks) != len(table.rows):
            raise ValueError("rows_misaligned")

    def rebuild(self, replaced: dict[int, str]) -> bytes:
        pieces: list[str] = []
        cursor = 0
        for index, block in enumerate(self.blocks):
            pieces.append(self.text[cursor : block.start])
            pieces.append(replaced.get(index, block.raw))
            cursor = block.end
        pieces.append(self.text[cursor:])
        return self.bom + "".join(pieces).encode(self.codec, errors="replace")


_TAG = re.compile(r"<(td|th)\b([^>]*)>", re.IGNORECASE)
_CELL = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_CLASS = re.compile(r"""class\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_TR_OPEN = re.compile(r"<tr\b", re.IGNORECASE)


def _class_value(attrs: str) -> str | None:
    match = _CLASS.search(attrs)
    if match is None:
        return None
    return match.group(1) or match.group(2) or match.group(3) or ""


def _hide_cells(raw: str) -> str:
    """Every cell of the block given the class the terminal uses for hidden cells."""

    def hidden(match: re.Match[str]) -> str:
        tag, attrs = match.group(1), match.group(2)
        found = _CLASS.search(attrs)
        if found is None:
            return f'<{tag} class="hidden"{attrs}>'
        value = found.group(1) or found.group(2) or found.group(3) or ""
        if "hidden" in value.split():
            return match.group(0)
        start, end = found.span()
        return f'<{tag}{attrs[:start]}class="{value} hidden"{attrs[end:]}>'

    return _TAG.sub(hidden, raw)


def _style_hidden(raw: str) -> str:
    """The block's ``<tr>`` given ``style="display:none"`` (a browser hides
    it; the audit's reader does not honour styles)."""
    return _TR_OPEN.sub('<tr style="display:none"', raw, count=1)


def _fill_hidden_cell(raw: str, content: str) -> str | None:
    """The first hidden cell of the block filled with ``content``."""
    for match in _CELL.finditer(raw):
        value = _class_value(match.group(2))
        if value is not None and "hidden" in value.split():
            return raw[: match.start(3)] + content + raw[match.end(3) :]
    return None


class _Csv:
    """The physical lines of a delimited export, aligned with ``table.rows``
    the way ``importers._read_delimited`` reads them (blank lines, an
    Excel ``sep=`` line and a lone title line skipped)."""

    def __init__(self, data: bytes, table: RawTable) -> None:
        if (
            table.family not in families.CSV_FAMILIES
            or table.source_format in families.XLSX_FORMATS
        ):
            raise ValueError("not_editable")
        raw = importers.unwrap(data)
        self.codec, self.bom = _codec(raw)
        self.lines = importers.decode_text(raw).splitlines(keepends=True)
        self.delimiter = table.delimiter or ","
        logical = [(i, line) for i, line in enumerate(self.lines) if line.strip()]
        if logical and re.fullmatch(r"sep=.", logical[0][1].strip().lstrip("﻿")):
            logical.pop(0)
        if logical and logical[0][1].strip().lstrip("﻿").lower() in {
            "history",
            "closed trades",
        }:
            logical.pop(0)
        self.line_of: dict[int, int] = {}
        raw_index = 0
        for physical, line in logical:
            cells = self.split(line)
            if raw_index > 0 and not any(cells):
                continue
            if raw_index >= len(table.rows):
                raise ValueError("rows_misaligned")
            texts = table.rows[raw_index].texts
            aligned = tuple(cells) == texts or (
                raw_index == 0 and tuple(cell.lstrip("﻿") for cell in cells) == texts
            )
            if not aligned:
                raise ValueError("rows_misaligned")
            self.line_of[raw_index] = physical
            raw_index += 1
        if raw_index != len(table.rows):
            raise ValueError("rows_misaligned")

    def split(self, line: str) -> list[str]:
        reader = csv.reader([line.rstrip("\r\n")], delimiter=self.delimiter)
        return [cell.strip() for cell in next(reader, [])]

    def join(self, cells: Sequence[str], like: str) -> str:
        out = io.StringIO()
        csv.writer(out, delimiter=self.delimiter, lineterminator="").writerow(list(cells))
        ending = like[len(like.rstrip("\r\n")) :]
        return out.getvalue() + ending

    def line(self, index: int) -> str:
        return self.lines[self.line_of[index]]

    def with_cell(self, index: int, column: int, text: str) -> str:
        line = self.line(index)
        cells = self.split(line)
        if not 0 <= column < len(cells):
            raise ValueError("cell_not_found")
        cells[column] = text
        return self.join(cells, line)

    def rebuild(
        self, replaced: dict[int, str | None], inserted: dict[int, list[str]] | None = None
    ) -> bytes:
        out: list[str] = []
        physical_of = {physical: index for index, physical in self.line_of.items()}
        for physical, line in enumerate(self.lines):
            index = physical_of.get(physical)
            if index is None:
                out.append(line)
                continue
            extras = (inserted or {}).get(index, [])
            ending = line[len(line.rstrip("\r\n")) :] or "\n"
            if index in replaced:
                new = replaced[index]
                if new is not None:
                    out.append(new)
            else:
                out.append(line)
            if extras and out and not out[-1].endswith(("\n", "\r")):
                out[-1] += ending  # a last line without its newline
            for extra in extras:
                if not extra.endswith(("\n", "\r")):
                    extra += ending
                out.append(extra)
        return self.bom + "".join(out).encode(self.codec, errors="replace")


# --- Family-neutral one-row operations ---------------------------------------


def _aligned(data: bytes, table: RawTable) -> None:
    """Raises ``ValueError('rows_misaligned')`` when ``edit`` and ``rows``
    do not count the same ``<tr>`` blocks: an edit by row index would then
    land on another row."""
    _Html(data, table)


def _delete(data: bytes, table: RawTable, index: int) -> bytes:
    if _html_editable(table):
        _aligned(data, table)
        return edit.delete_row(data, index)
    return _Csv(data, table).rebuild({index: None})


def _set(data: bytes, table: RawTable, index: int, column: int, text: str) -> bytes:
    if _html_editable(table):
        _aligned(data, table)
        return edit.set_cell(data, index, column, text)
    document = _Csv(data, table)
    return document.rebuild({index: document.with_cell(index, column, text)})


def _duplicate(
    data: bytes,
    table: RawTable,
    index: int,
    edits: dict[int, str] | None = None,
    *,
    shift: timedelta | None = None,
) -> bytes:
    if _html_editable(table):
        _aligned(data, table)
        return edit.duplicate_row(data, index, edits, shift=shift)
    document = _Csv(data, table)
    line = document.line(index)
    cells = document.split(line)
    for column, text in (edits or {}).items():
        cells[column] = text
    return document.rebuild({}, inserted={index: [document.join(cells, line)]})


def _swap(data: bytes, table: RawTable, first: int, second: int) -> bytes:
    if _html_editable(table):
        page = _Html(data, table)
        return page.rebuild({first: page.blocks[second].raw, second: page.blocks[first].raw})
    document = _Csv(data, table)
    return document.rebuild({first: document.line(second), second: document.line(first)})


# ---------------------------------------------------------------------------
# Reading the closed rows of every family
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Closed:
    """A closed trade as one row: the MT4 statement's trade, the MT5 exit
    deal, the MT4 tester's close row, a delimited export's closed trade."""

    index: int
    profit_at: int
    price_at: int
    time_at: int
    symbol: str
    profit: Decimal | None
    price: Decimal | None
    time: datetime | None
    side: str = ""
    """``long``/``short`` of the position closed, ``""`` when unknown."""
    symbol_at: int | None = None
    ticket_at: int | None = None
    ticket: int | None = None
    open_price: Decimal | None = None
    open_time: datetime | None = None
    comment: str = ""
    level_at: int | None = None
    """The S/L or T/P cell the comment marker refers to (MT4 statement)."""
    level: Decimal | None = None
    marker: str = ""
    not_fill: bool = False
    """An MT4 tester close row that is not a market fill (``close at stop``
    ends the test, ``swap close`` is a rollover): no market-hours question."""


@dataclass(frozen=True)
class _Pick:
    """A delimited row and where its trade fields sit (``-1``: absent)."""

    row: RawRow
    profit_at: int
    exit_at: int
    close_at: int
    symbol_at: int
    entry_at: int
    open_at: int
    side: str


_SIDES = {"buy": "long", "sell": "short", "long": "long", "short": "short"}
_MT5_EXITS = frozenset({"out", "out by"})
_MT4_TESTER_FILLS = frozenset({"close", "t/p", "s/l", "close by"})
_MT5_MARKER = re.compile(r"(?:^|\[)(tp|sl) ([0-9][0-9.,]*)\]?$", re.IGNORECASE)


def _naive(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=None) if moment is not None else None


def _mt_time(text: str) -> datetime | None:
    stripped = text.strip()
    if not importers._is_mt_time(stripped):
        return None
    return _naive(importers._one_time(stripped))


def _column_times(texts: Sequence[str]) -> list[datetime | None]:
    try:
        return [_naive(value) for value in importers._parse_times(list(texts)).values]
    except importers.ReportFormatError:
        return [None] * len(texts)


def _names(texts: Sequence[str]) -> list[str]:
    return [text.strip().lower() for text in texts]


def _at(names: list[str], *wanted: str) -> int:
    """The position of the first of ``wanted`` among ``names``, ``-1`` when none."""
    for name in wanted:
        if name in names:
            return names.index(name)
    return -1


def _mt4_comment(row: RawRow, ticket_at: int) -> str:
    title = row.cells[ticket_at].title.strip() if ticket_at < len(row.cells) else ""
    return title.lower() if title and title != row.text(ticket_at).strip() else ""


def _mt4_statement_closed(table: RawTable) -> list[_Closed]:
    found: list[_Closed] = []
    for row in table.kind(rows.KIND_MT4_TRADE):
        columns = rows.mt4_columns(table, row)
        names = _names(table.header_of(row))
        compact = [re.sub(r"\s+", "", name) for name in names]
        ticket_at = names.index("ticket") if "ticket" in names else 0
        sl_at = compact.index("s/l") if "s/l" in compact else columns["open_price"] + 1
        tp_at = compact.index("t/p") if "t/p" in compact else columns["open_price"] + 2
        comment = _mt4_comment(row, ticket_at)
        marker = "tp" if "[tp]" in comment else "sl" if "[sl]" in comment else ""
        level_at = tp_at if marker == "tp" else sl_at if marker == "sl" else None
        ticket = row.text(ticket_at).strip()
        found.append(
            _Closed(
                index=row.index,
                profit_at=columns["profit"],
                price_at=columns["close_price"],
                time_at=columns["close_time"],
                symbol=row.text(columns["symbol"]).strip(),
                profit=money.parse_money(row.text(columns["profit"])),
                price=money.parse_money(row.text(columns["close_price"])),
                time=_mt_time(row.text(columns["close_time"])),
                side=_SIDES.get(row.text(columns["type"]).lower(), ""),
                symbol_at=columns["symbol"],
                ticket_at=ticket_at,
                ticket=int(ticket) if ticket.isdigit() else None,
                open_price=money.parse_money(row.text(columns["open_price"])),
                open_time=_mt_time(row.text(columns["open_time"])),
                comment=comment,
                level_at=level_at,
                level=money.parse_money(row.text(level_at)) if level_at is not None else None,
                marker=marker,
            )
        )
    return found


def _mt5_closed(table: RawTable) -> list[_Closed]:
    found: list[_Closed] = []
    for row in table.kind(rows.KIND_MT5_DEAL):
        columns = rows.mt5_columns(table, row)
        if not {"deal", "time", "type", "direction", "price", "profit", "symbol"} <= set(columns):
            continue
        if row.text(columns["direction"]).strip().lower() not in _MT5_EXITS:
            continue
        deal_side = _SIDES.get(row.text(columns["type"]).lower(), "")
        comment_at = columns.get("comment")
        comment = row.text(comment_at).strip().lower() if comment_at is not None else ""
        match = _MT5_MARKER.search(comment)
        ticket = row.text(columns["deal"]).strip()
        found.append(
            _Closed(
                index=row.index,
                profit_at=columns["profit"],
                price_at=columns["price"],
                time_at=columns["time"],
                symbol=row.text(columns["symbol"]).strip(),
                profit=money.parse_money(row.text(columns["profit"])),
                price=money.parse_money(row.text(columns["price"])),
                time=_mt_time(row.text(columns["time"])),
                side={"long": "short", "short": "long"}.get(deal_side, ""),
                symbol_at=columns["symbol"],
                ticket_at=columns["deal"],
                ticket=int(ticket) if ticket.isdigit() else None,
                comment=comment,
                level=money.parse_money(match.group(2)) if match is not None else None,
                marker=match.group(1).lower() if match is not None else "",
            )
        )
    return found


def _mt4_tester_closed(table: RawTable) -> list[_Closed]:
    opened: dict[str, tuple[str, Decimal | None, datetime | None]] = {}
    found: list[_Closed] = []
    for row in table.kind(rows.KIND_MT4_TESTER):
        kind = row.text(2).strip().lower()
        order = row.text(3).strip()
        if kind in _SIDES:
            opened.setdefault(
                order, (_SIDES[kind], money.parse_money(row.text(5)), _mt_time(row.text(1)))
            )
            continue
        if kind not in importers._MT4_CLOSES or money.parse_money(row.text(8)) is None:
            continue
        side, open_price, open_time = opened.get(order, ("", None, None))
        number = row.text(0).strip()
        found.append(
            _Closed(
                index=row.index,
                profit_at=8,
                price_at=5,
                time_at=1,
                symbol=table.label("Symbol") or "",
                profit=money.parse_money(row.text(8)),
                price=money.parse_money(row.text(5)),
                time=_mt_time(row.text(1)),
                side=side,
                ticket_at=0,
                ticket=int(number) if number.isdigit() else None,
                open_price=open_price,
                open_time=open_time,
                not_fill=kind not in _MT4_TESTER_FILLS,
            )
        )
    return found


def _csv_body(table: RawTable) -> list[RawRow]:
    """The closed-history rows of a delimited export: for Myfxbook everything
    before the open-trades block (the importer stops at the same place)."""
    body: list[RawRow] = []
    for row in table.kind(rows.KIND_CSV):
        if table.family == MYFX:
            lowered = [text.lower() for text in row.texts[:3]]
            if (lowered and lowered[0] in {"open trades", "open orders", "open positions"}) or (
                lowered[1:3] == ["ticket", "open date"]
            ):
                break
        body.append(row)
    return body


def _csv_picks(table: RawTable) -> tuple[list[_Pick], int]:
    """The closed rows of a delimited export and the ticket column (``-1``)."""
    names = _names(table.header)
    body = _csv_body(table)
    family = table.family
    picks: list[_Pick] = []
    if family == MYFX:
        action_at, symbol_at = _at(names, "action"), _at(names, "symbol")
        entry_at, exit_at = _at(names, "open price"), _at(names, "close price")
        profit_at, close_at = _at(names, "profit"), _at(names, "close date")
        if -1 in (action_at, symbol_at, entry_at, exit_at, profit_at, close_at):
            return [], -1
        open_at = _at(names, "open date")
        for row in body:
            side = _SIDES.get(row.text(action_at).lower(), "")
            if side:
                picks.append(
                    _Pick(row, profit_at, exit_at, close_at, symbol_at, entry_at, open_at, side)
                )
        return picks, _at(names, "ticket")
    if family == MQL5:
        kind_at, symbol_at, profit_at = (
            _at(names, "type"),
            _at(names, "symbol"),
            _at(names, "profit"),
        )
        if -1 in (kind_at, profit_at) or names.count("time") < 2 or "price" not in names:
            return [], -1
        close_at = names.index("time", 1)
        if "price" not in names[close_at:]:
            return [], -1
        exit_at, entry_at = names.index("price", close_at), names.index("price")
        for row in body:
            side = _SIDES.get(row.text(kind_at).lower(), "")
            if side:
                picks.append(_Pick(row, profit_at, exit_at, close_at, symbol_at, entry_at, 0, side))
        return picks, -1
    if family == FXB:
        kind_at, side_at = _at(names, "type"), _at(names, "buy/sell")
        entry_at, exit_at = _at(names, "open price"), _at(names, "close price")
        profit_at, close_at = _at(names, "profit"), _at(names, "close time")
        if -1 in (kind_at, side_at, entry_at, exit_at, profit_at, close_at):
            return [], -1
        symbol_at, open_at = _at(names, "symbol"), _at(names, "open time")
        for row in body:
            if row.text(kind_at).strip().lower() != "closed position":
                continue
            side = _SIDES.get(row.text(side_at).lower(), "")
            picks.append(
                _Pick(row, profit_at, exit_at, close_at, symbol_at, entry_at, open_at, side)
            )
        return picks, _at(names, "ticket")
    if family == NT:
        columns = importers._ninjatrader_index(list(table.header))
        if any(key not in columns for key in ("market pos.", "exit price", "profit", "exit time")):
            return [], -1
        for row in body:
            side = _SIDES.get(row.text(columns["market pos."]).strip().lower(), "")
            if side:
                picks.append(
                    _Pick(
                        row,
                        columns["profit"],
                        columns["exit price"],
                        columns["exit time"],
                        columns.get("instrument", -1),
                        columns.get("entry price", -1),
                        columns.get("entry time", -1),
                        side,
                    )
                )
        return picks, columns.get("trade number", -1)
    return [], -1


def _csv_closed(table: RawTable) -> list[_Closed]:
    if table.family == TV:
        return _tradingview_closed(table)
    picks, ticket_at = _csv_picks(table)
    comma = table.delimiter == ";" and table.family == NT
    closes = _column_times([pick.row.text(pick.close_at) for pick in picks])
    opens = _column_times(
        [pick.row.text(pick.open_at) if pick.open_at >= 0 else "" for pick in picks]
    )
    out: list[_Closed] = []
    for position, pick in enumerate(picks):
        row = pick.row
        ticket = row.text(ticket_at).strip() if ticket_at >= 0 else ""
        out.append(
            _Closed(
                index=row.index,
                profit_at=pick.profit_at,
                price_at=pick.exit_at,
                time_at=pick.close_at,
                symbol=row.text(pick.symbol_at).strip() if pick.symbol_at >= 0 else "",
                profit=_csv_money(row.text(pick.profit_at), comma),
                price=_csv_money(row.text(pick.exit_at), comma),
                time=closes[position],
                side=pick.side,
                symbol_at=pick.symbol_at if pick.symbol_at >= 0 else None,
                ticket_at=ticket_at if ticket_at >= 0 else None,
                ticket=int(ticket) if ticket.isdigit() else None,
                open_price=_csv_money(row.text(pick.entry_at), comma)
                if pick.entry_at >= 0
                else None,
                open_time=opens[position],
            )
        )
    return out


def _tv_columns(table: RawTable) -> dict[str, int] | None:
    try:
        columns, _currency = importers._tv_columns(list(table.header))
    except importers.ReportFormatError:
        return None
    return columns


def _tradingview_closed(table: RawTable) -> list[_Closed]:
    """One row per closed trade: the exit row, which carries the trade's
    net P&L and exit price; the entry row's price is the open price."""
    columns = _tv_columns(table)
    if columns is None:
        return []
    groups: dict[str, list[RawRow]] = {}
    order: list[str] = []
    for row in _csv_body(table):
        number = row.text(columns["trade"]).strip()
        if number not in groups:
            order.append(number)
        groups.setdefault(number, []).append(row)
    picked: list[tuple[RawRow, RawRow, str]] = []
    for number in order:
        pair = groups[number]
        if len(pair) != 2:
            continue
        roles = {importers._tv_role(row.text(columns["type"])): row for row in pair}
        if set(roles) != {"entry", "exit"}:
            continue
        exit_ = roles["exit"]
        signal = exit_.text(columns["signal"]).strip().lower() if "signal" in columns else ""
        if not signal or signal in importers._TV_OPEN_SIGNALS:
            continue
        side = importers._tv_side(roles["entry"].text(columns["type"])) or ""
        picked.append((roles["entry"], exit_, side))
    closes = _column_times([exit_.text(columns["time"]) for _entry, exit_, _side in picked])
    opens = _column_times([entry.text(columns["time"]) for entry, _exit, _side in picked])
    out: list[_Closed] = []
    for position, (entry, exit_, side) in enumerate(picked):
        number = exit_.text(columns["trade"]).strip()
        out.append(
            _Closed(
                index=exit_.index,
                profit_at=columns["net"],
                price_at=columns["price"],
                time_at=columns["time"],
                symbol="",
                profit=money.parse_money(exit_.text(columns["net"])),
                price=money.parse_money(exit_.text(columns["price"])),
                time=closes[position],
                side=side,
                ticket_at=columns["trade"],
                ticket=int(number) if number.isdigit() else None,
                open_price=money.parse_money(entry.text(columns["price"])),
                open_time=opens[position],
            )
        )
    return out


def _csv_money(text: str, comma_decimal: bool) -> Decimal | None:
    if not comma_decimal:
        return money.parse_money(text)
    value = text.strip()
    negative = value.startswith("(") and value.endswith(")")
    value = re.sub(r"[\s$€£¥()]", "", value).replace(".", "").replace(",", ".")
    number = money.parse_money(value)
    if number is None:
        return None
    return -abs(number) if negative else number


def closed_rows(table: RawTable) -> list[_Closed]:
    family = table.family
    if family == MT4:
        return _mt4_statement_closed(table)
    if family in {MT5, MT5T}:
        return _mt5_closed(table)
    if family == MT4T:
        return _mt4_tester_closed(table)
    if family in families.CSV_FAMILIES:
        return _csv_closed(table)
    return []


def _loss_target(closed: Sequence[_Closed]) -> _Closed | None:
    """The losing row with the largest loss (ties: first in file order)."""
    losses = [row for row in closed if row.profit is not None and row.profit < 0]
    if not losses:
        return None
    return min(losses, key=lambda row: (row.profit, row.index))


def _largest_target(closed: Sequence[_Closed]) -> _Closed | None:
    """The row with the largest absolute result (ties: first in file order)."""
    priced = [row for row in closed if row.profit is not None and row.profit != 0]
    if not priced:
        return None
    return max(priced, key=lambda row: (abs(row.profit or 0), -row.index))


def _win_target(closed: Sequence[_Closed]) -> _Closed | None:
    """The winning row with the lowest ticket (else the first in file order)."""
    wins = [row for row in closed if row.profit is not None and row.profit > 0]
    if not wins:
        return None
    return min(wins, key=lambda row: (row.ticket if row.ticket is not None else 0, row.index))


# ---------------------------------------------------------------------------
# Writing cells in the file's own style
# ---------------------------------------------------------------------------


def _needed_decimals(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _decimals_for(original: str, value: Decimal) -> int:
    """The printed decimals of ``original``, or more when ``value`` needs
    them (an export that trims zeros prints ``49.6`` and ``49.61`` alike)."""
    printed = money.printed_decimals(original)
    return max(printed if printed is not None else 0, _needed_decimals(value))


def _restyle_money(original: str, value: Decimal) -> str:
    """``value`` written like ``original``: a leading currency sign kept,
    parentheses for a negative when the original used them, a decimal comma
    when the original had one."""
    text = original.strip()
    lead = re.match(r"^[($€£¥\s]*", text)
    currency = "".join(ch for ch in (lead.group(0) if lead else "") if ch in "$€£¥")
    parens = text.startswith("(") and text.endswith(")")
    comma = importers._comma_is_decimal(re.sub(r"[\s$€£¥()]", "", text))
    body = money.as_text(abs(value), _decimals_for(text, value))
    if comma:
        body = body.replace(".", ",")
    if value < 0:
        return f"({currency}{body})" if parens else f"-{currency}{body}"
    return f"{currency}{body}"


def _price_text(original: str, value: Decimal) -> str:
    return money.as_text(value, _decimals_for(original, value))


def _tick(original: str) -> Decimal:
    decimals = money.printed_decimals(original) or 0
    return Decimal(1).scaleb(-decimals)


_TIME_SHAPE = re.compile(
    r"^(\d{1,4})([./-])(\d{1,2})([./-])(\d{1,4})"
    r"(?:([ T]+)(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(\s*[AaPp][Mm])?)?$"
)


def _rewrite_time(original: str, parsed: datetime, target: datetime) -> str | None:
    """``target`` written in the layout of ``original`` (year-first or
    day/month order as the importer read it, same zero padding, AM/PM kept).
    ``None`` when the layout cannot be told."""
    match = _TIME_SHAPE.match(original.strip())
    if match is None:
        return None
    first, sep1, second, sep2, third, gap, hour, _minute, seconds, ampm = match.groups()
    if len(first) == 4:
        order = ("y", "m", "d")
    else:
        day_first = int(first) == parsed.day and int(second) == parsed.month
        month_first = int(first) == parsed.month and int(second) == parsed.day
        if parsed.day == parsed.month:
            day_first, month_first = False, bool(ampm)
        if day_first:
            order = ("d", "m", "y")
        elif month_first:
            order = ("m", "d", "y")
        else:
            return None
    widths = (len(first), len(second), len(third))
    values = {"y": target.year, "m": target.month, "d": target.day}
    parts = [str(values[name]).zfill(width) for name, width in zip(order, widths, strict=True)]
    out = f"{parts[0]}{sep1}{parts[1]}{sep2}{parts[2]}"
    if hour is None:
        return out
    hour_value = target.hour
    suffix = ""
    if ampm:
        upper = ampm.strip().isupper()
        afternoon = target.hour >= 12
        suffix = (" PM" if afternoon else " AM") if upper else (" pm" if afternoon else " am")
        hour_value = target.hour % 12 or 12
    out += f"{gap}{str(hour_value).zfill(len(hour))}:{target.minute:02d}"
    if seconds is not None:
        out += f":{target.second:02d}"
    return out + suffix


def _set_time(data: bytes, table: RawTable, row: _Closed, target: datetime) -> bytes | None:
    """The row's close time rewritten as ``target`` in the cell's own shape."""
    if row.time is None:
        return None
    if _html_editable(table):
        _aligned(data, table)
        return edit.shift_time(data, row.index, row.time_at, target - row.time)
    original = table.rows[row.index].text(row.time_at)
    text = _rewrite_time(original, row.time, target)
    if text is None:
        return None
    return _set(data, table, row.index, row.time_at, text)


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


def _profit_shift(delta: Decimal) -> Apply:
    def apply(data: bytes, table: RawTable) -> bytes | None:
        target = _largest_target(closed_rows(table))
        if target is None or target.profit is None:
            return None
        original = table.rows[target.index].text(target.profit_at)
        text = _restyle_money(original, target.profit + delta)
        return _set(data, table, target.index, target.profit_at, text)

    return apply


def _profit_flip(data: bytes, table: RawTable) -> bytes | None:
    target = _loss_target(closed_rows(table))
    if target is None or target.profit is None:
        return None
    original = table.rows[target.index].text(target.profit_at)
    text = _restyle_money(original, -target.profit)
    return _set(data, table, target.index, target.profit_at, text)


def _delete_loss(data: bytes, table: RawTable) -> bytes | None:
    closed = closed_rows(table)
    if table.family == NT and closed:
        closed = closed[:-1]  # the last row leaves no running figure behind it
    elif table.family == TV and closed:
        latest = max(closed, key=lambda row: (row.time or datetime.min, row.index))
        closed = [row for row in closed if row is not latest]  # its cumulative is not examined
    target = _loss_target(closed)
    if target is None:
        return None
    if table.family == TV:
        return _delete_pair(data, table, target.index)
    return _delete(data, table, target.index)


def _delete_pair(data: bytes, table: RawTable, exit_index: int) -> bytes | None:
    """Both rows of a TradingView trade go: the exit row and its entry row."""
    columns = _tv_columns(table)
    if columns is None:
        return None
    number = table.rows[exit_index].text(columns["trade"])
    replaced: dict[int, str | None] = {
        row.index: None for row in table.kind(rows.KIND_CSV) if row.text(columns["trade"]) == number
    }
    return _Csv(data, table).rebuild(replaced)


def _price_mirror(data: bytes, table: RawTable) -> bytes | None:
    """The close price reflected around the open price: the move keeps its
    size and changes its sign, the printed digits stay."""
    if table.family == MT5:
        return _position_price_mirror(data, table)
    if table.family == TV:
        columns = _tv_columns(table)
        if columns is None or "commission" not in columns:
            return None  # no gross result to judge the sign of (G1 layout)
    candidates = [
        row
        for row in closed_rows(table)
        if row.open_price is not None
        and row.price is not None
        and row.price != row.open_price
        and row.profit
    ]
    target = _largest_target(candidates)
    if target is None or target.open_price is None or target.price is None:
        return None
    original = table.rows[target.index].text(target.price_at)
    mirrored = 2 * target.open_price - target.price
    if mirrored <= 0:
        return None
    return _set(data, table, target.index, target.price_at, _price_text(original, mirrored))


def _position_price_mirror(data: bytes, table: RawTable) -> bytes | None:
    """MT5 history: the Positions row's close price (the copy the deals repeat)."""
    best: tuple[Decimal, int, int, Decimal] | None = None
    for row in table.kind(rows.KIND_MT5_POSITION):
        columns = rows.mt5_position_columns(table, row)
        opened = money.parse_money(row.text(columns["price"]))
        closed = money.parse_money(row.text(columns["close_price"]))
        profit = money.parse_money(row.text(columns["profit"]))
        if opened is None or closed is None or profit is None or profit == 0 or opened == closed:
            continue
        if best is None or (abs(profit), -row.index) > (best[0], -best[1]):
            best = (abs(profit), row.index, columns["close_price"], 2 * opened - closed)
    if best is None or best[3] <= 0:
        return None
    _size, index, column, mirrored = best
    return _set(data, table, index, column, _price_text(table.rows[index].text(column), mirrored))


def _sltp_violation(data: bytes, table: RawTable) -> bytes | None:
    """A take-profit (or, on the MT5 tester, a stop-loss) fill moved ten
    ticks past its level, on the side the platform never fills."""
    marked = [row for row in closed_rows(table) if row.marker and row.level and row.price]
    if table.family == MT5T:
        marked.sort(key=lambda row: (row.marker != "tp", row.index))
    else:
        marked = [row for row in marked if row.marker == "tp"]
    for row in marked:
        if row.side not in {"long", "short"} or row.level is None or row.price is None:
            continue
        original = table.rows[row.index].text(row.price_at)
        ticks = _TICKS_WORSE * _tick(original)
        worse_for_tp = row.level - ticks if row.side == "long" else row.level + ticks
        better_for_sl = row.level + ticks if row.side == "long" else row.level - ticks
        new_price = worse_for_tp if row.marker == "tp" else better_for_sl
        if new_price <= 0:
            continue
        return _set(data, table, row.index, row.price_at, _price_text(original, new_price))
    return None


def _dropped_zero(data: bytes, table: RawTable) -> bytes | None:
    """The close price printed with one decimal fewer (a trailing zero
    dropped) or, without a trailing zero, one decimal more."""
    if not _html_editable(table):
        return None
    for row in closed_rows(table):
        original = table.rows[row.index].text(row.price_at).strip()
        if row.price is None or row.price == 0 or "." not in original:
            continue
        drop = original.endswith("0") and not original.endswith(".0")
        new = original[:-1] if drop else original + "0"
        return _set(data, table, row.index, row.price_at, new)
    return None


def _max_id(table: RawTable) -> int | None:
    family = table.family
    values: list[int] = []
    if family == MT4:
        for row in table.rows:
            if row.section in {rows.SECTION_CLOSED, rows.SECTION_OPEN, rows.SECTION_WORKING}:
                names = _names(table.header_of(row))
                text = row.text(names.index("ticket") if "ticket" in names else 0).strip()
                if text.isdigit():
                    values.append(int(text))
    elif family in {MT5, MT5T}:
        for row in table.kind(rows.KIND_MT5_DEAL):
            text = row.text(rows.mt5_columns(table, row).get("deal", 1)).strip()
            if text.isdigit():
                values.append(int(text))
    elif family == MT4T:
        texts = [row.text(0).strip() for row in table.kind(rows.KIND_MT4_TESTER)]
        values = [int(text) for text in texts if text.isdigit()]
    else:
        values = [row.ticket for row in closed_rows(table) if row.ticket is not None]
    return max(values) if values else None


def _duplicate_new_ticket(data: bytes, table: RawTable) -> bytes | None:
    target = _win_target(closed_rows(table))
    highest = _max_id(table)
    if target is None or target.ticket_at is None or highest is None:
        return None
    shift = _ONE_MINUTE if _html_editable(table) else None
    return _duplicate(data, table, target.index, {target.ticket_at: str(highest + 1)}, shift=shift)


def _duplicate_same_ticket(data: bytes, table: RawTable) -> bytes | None:
    target = _win_target(closed_rows(table))
    if target is None or target.ticket_at is None:
        return None
    return _duplicate(data, table, target.index)


@dataclass(frozen=True)
class _Cash:
    index: int
    amount: Decimal


def _cash_rows(table: RawTable) -> list[_Cash]:
    """Deposits and withdrawals in file order (balance rows, never credits)."""
    found: list[_Cash] = []
    family = table.family
    if family == MT4:
        for row in table.kind(rows.KIND_MT4_CASH):
            at = rows.mt4_columns(table, row)["open_time"]
            amounts = [money.parse_money(text) for text in row.texts[at + 2 :]]
            numbers = [amount for amount in amounts if amount is not None]
            if numbers:
                found.append(_Cash(row.index, numbers[-1]))
    elif family in {MT5, MT5T}:
        for row in table.kind(rows.KIND_MT5_DEAL):
            columns = rows.mt5_columns(table, row)
            if row.text(columns.get("type", 3)).lower() != "balance":
                continue
            amount = money.parse_money(row.text(columns.get("profit", -1)))
            if amount is not None:
                found.append(_Cash(row.index, amount))
    elif family in {MYFX, FXB, MQL5}:
        names = _names(table.header)
        kind_at, amount_at = _at(names, "action", "type"), _at(names, "profit")
        if kind_at < 0 or amount_at < 0:
            return []
        for row in _csv_body(table):
            kind = row.text(kind_at).strip().lower()
            amount = money.parse_money(row.text(amount_at))
            if amount is None or amount == 0:
                continue
            if kind in {"deposit", "withdrawal"} or (kind == "balance" and family == MQL5):
                found.append(_Cash(row.index, amount))
    return found


def _drop_cash(want_withdrawal: bool) -> Apply:
    """The last matching cash row removed. On the MT5 families only a row
    with deals on both sides qualifies: the first deal seeds the balance
    chain and nothing follows the last, so neither leaves a trace."""

    def apply(data: bytes, table: RawTable) -> bytes | None:
        matching = [cash for cash in _cash_rows(table) if (cash.amount < 0) == want_withdrawal]
        if table.family in {MT5, MT5T}:
            deals = table.kind(rows.KIND_MT5_DEAL)
            first, last = deals[0].index, deals[-1].index
            matching = [cash for cash in matching if first < cash.index < last]
        if not matching:
            return None
        return _delete(data, table, matching[-1].index)

    return apply


_SUMMARY_CONCEPTS = {
    MT4: ("closed_pnl", "closed_trade_pnl"),
    MT5: ("net_profit",),
    MT5T: ("net_profit",),
    MT4T: ("net_profit",),
}


def _summary_total(data: bytes, table: RawTable) -> bytes | None:
    """The declared net result (the label the importer compares with the
    rows) moved by 100.00, found through the check's own alias table."""
    aliases = totals._ALIASES.get(table.family, {})
    for concept in _SUMMARY_CONCEPTS.get(table.family, ()):
        for row in table.rows:
            if row.kind != rows.KIND_LABEL:
                continue
            for position in range(len(row.texts) - 1):
                text = row.texts[position].strip().rstrip(":").strip().lower()
                if aliases.get(text) != concept:
                    continue
                original = row.texts[position + 1]
                value = money.parse_money(original.split("(", 1)[0])
                if value is None:
                    continue
                shifted = _restyle_money(original, value + _SUMMARY_SHIFT)
                return _set(data, table, row.index, position + 1, shifted)
    return None


def _header_backwards(data: bytes, table: RawTable) -> bytes | None:
    stamps = [
        row.open_time if row.open_time is not None else row.time
        for row in closed_rows(table)
        if row.open_time is not None or row.time is not None
    ]
    if not stamps or not _html_editable(table):
        return None
    earliest = min(stamp for stamp in stamps if stamp is not None)
    try:
        return edit.set_header_date(data, earliest - _ONE_DAY, source_format=table.source_format)
    except ValueError:
        return None


def _hide_row(data: bytes, table: RawTable) -> bytes | None:
    target = _loss_target(closed_rows(table))
    if target is None or not _html_editable(table):
        return None
    page = _Html(data, table)
    return page.rebuild({target.index: _hide_cells(page.blocks[target.index].raw)})


def _hide_row_style(data: bytes, table: RawTable) -> bytes | None:
    target = _loss_target(closed_rows(table))
    if target is None or not _html_editable(table):
        return None
    page = _Html(data, table)
    return page.rebuild({target.index: _style_hidden(page.blocks[target.index].raw)})


def _fill_hidden(content: str, *, any_row: bool = False) -> Apply:
    """The hidden ``Cost`` cell of a deal filled; not the first deal, which
    seeds the balance chain without a comparison. With ``any_row`` a hidden
    cell of any other row (a Positions row) when no deal has one."""

    def apply(data: bytes, table: RawTable) -> bytes | None:
        if not _html_editable(table):
            return None
        page = _Html(data, table)
        candidates: list[RawRow] = list(table.kind(rows.KIND_MT5_DEAL)[1:])
        if any_row:
            candidates += [row for row in table.rows if row.kind != rows.KIND_MT5_DEAL]
        for row in candidates:
            if not any(cell.hidden for cell in row.cells):
                continue
            raw = _fill_hidden_cell(page.blocks[row.index].raw, content)
            if raw is not None:
                return page.rebuild({row.index: raw})
        return None

    return apply


def _move_to_open(data: bytes, table: RawTable) -> bytes | None:
    target = _loss_target(closed_rows(table))
    if target is None or table.family != MT4 or not _html_editable(table):
        return None
    _aligned(data, table)
    try:
        return edit.move_to_open_section(data, target.index, source_format=table.source_format)
    except ValueError:
        return None


def _mt4_keys(row: _Closed) -> tuple[Any, ...] | None:
    if row.ticket is None or row.open_time is None or row.time is None:
        return None
    return row.ticket, row.open_time, row.time


def _swap_adjacent(data: bytes, table: RawTable) -> bytes | None:
    """Two adjacent closed rows exchanged. Chronological tables (MT5 deals,
    MT4 tester rows): the first two trade rows. Majority-ordered tables need
    three rows and a pair that steps in the file's direction on every key
    the check may pick (MT4 statement: ticket, open and close time; account
    exports: close time; NinjaTrader: exit and entry time), between
    neighbours that do not step against it, so the swap adds an inversion
    on every key."""
    family = table.family
    if family in {MT5, MT5T}:
        indexes = [
            row.index
            for row in table.kind(rows.KIND_MT5_DEAL)
            if row.text(rows.mt5_columns(table, row).get("type", 3)).lower() in {"buy", "sell"}
        ]
    elif family == MT4T:
        indexes = [row.index for row in table.kind(rows.KIND_MT4_TESTER)]
    else:
        closed = closed_rows(table)
        if len(closed) < 3:
            return None
        if family == MT4:
            keyed = [(row.index, _mt4_keys(row)) for row in closed]
        elif family == NT:
            keyed = [
                (row.index, (row.time, row.open_time) if row.time and row.open_time else None)
                for row in closed
            ]
        else:
            keyed = [(row.index, (row.time,) if row.time is not None else None) for row in closed]
        return _swap_keyed(data, table, keyed)
    for first, second in zip(indexes, indexes[1:], strict=False):
        if second == first + 1 and table.rows[first].texts != table.rows[second].texts:
            return _swap(data, table, first, second)
    return None


def _compare(earlier: Any, later: Any) -> int:
    return (later > earlier) - (later < earlier)


def _swap_keyed(
    data: bytes, table: RawTable, keyed: list[tuple[int, tuple[Any, ...] | None]]
) -> bytes | None:
    keys = [key for _index, key in keyed if key is not None]
    if not keys:
        return None
    width = len(keys[0])
    directions: list[int] = []
    for column in range(width):
        steps = [_compare(a[column], b[column]) for a, b in zip(keys, keys[1:], strict=False)]
        directions.append(-1 if steps.count(-1) > steps.count(1) else 1)
    for position in range(len(keyed) - 1):
        first, second = keyed[position], keyed[position + 1]
        if second[0] != first[0] + 1:
            continue
        window = [key for _index, key in keyed[max(0, position - 1) : position + 3]]
        if any(key is None for key in window):
            continue
        pair_at = min(position, 1)
        qualifies = True
        for column, sign in enumerate(directions):
            steps = [
                _compare(a[column], b[column])  # type: ignore[index]
                for a, b in zip(window, window[1:], strict=False)
            ]
            if steps[pair_at] != sign or any(step == -sign for step in steps):
                qualifies = False
                break
        if qualifies:
            return _swap(data, table, first[0], second[0])
    return None


def _price_decimals(table: RawTable, row: _Closed) -> int | None:
    return money.printed_decimals(table.rows[row.index].text(row.price_at))


def _symbol_change(data: bytes, table: RawTable) -> bytes | None:
    """One row's symbol replaced by another symbol of the same file whose
    prices are printed with other digits (CSV: another quote currency,
    with at least two rows)."""
    closed = [row for row in closed_rows(table) if row.symbol and row.symbol_at is not None]
    if not closed or table.family == MT4T:
        return None
    by_symbol: dict[str, list[_Closed]] = {}
    for row in closed:
        by_symbol.setdefault(row.symbol.lower(), []).append(row)
    if len(by_symbol) < 2:
        return None
    delimited = table.family in families.CSV_FAMILIES
    for row in closed:
        own = _price_decimals(table, row)
        for symbol, others in by_symbol.items():
            if symbol == row.symbol.lower():
                continue
            if delimited:
                differs = len(others) >= 2 and symbol[-3:] != row.symbol.lower()[-3:]
            else:
                # Strictly inside the other symbol's rows: at an end, the
                # check reads a one-time change of digits as a migration.
                inside = others[0].index < row.index < others[-1].index
                differs = (
                    inside
                    and own is not None
                    and all(_price_decimals(table, other) not in {None, own} for other in others)
                )
            if differs:
                assert row.symbol_at is not None
                return _set(data, table, row.index, row.symbol_at, others[0].symbol)
    return None


def _number_change(kind: str) -> Apply:
    """An MT5 deal (or tester order) number replaced by one past the highest
    printed, on a row that is not the table's last."""

    def apply(data: bytes, table: RawTable) -> bytes | None:
        if table.family not in {MT5, MT5T}:
            return None
        if kind == "deal":
            picked = [
                (row.index, rows.mt5_columns(table, row).get("deal", 1))
                for row in table.kind(rows.KIND_MT5_DEAL)
                if row.text(rows.mt5_columns(table, row).get("type", 3)).lower() in {"buy", "sell"}
            ]
        else:
            named = {
                row.text(rows.mt5_columns(table, row)["order"]).strip()
                for row in table.kind(rows.KIND_MT5_DEAL)
                if "order" in rows.mt5_columns(table, row)
            }
            orders = table.kind(rows.KIND_MT5_ORDER)
            linked = [row for row in orders if row.text(1).strip() in named]
            picked = [(row.index, 1) for row in (linked or orders)]
        texts = [table.rows[index].text(at).strip() for index, at in picked]
        numbers = [int(text) for text in texts if text.isdigit()]
        if len(picked) < 2 or not numbers:
            return None
        index, at = picked[0]
        return _set(data, table, index, at, str(max(numbers) + 1))

    return apply


def _next_saturday(moment: datetime) -> datetime:
    """The first Saturday 15:00 at or after ``moment`` (inside the counted
    weekend window on every server offset)."""
    ahead = (5 - moment.weekday()) % 7
    saturday = (moment + timedelta(days=ahead)).replace(hour=15, minute=0, second=0, microsecond=0)
    return saturday if saturday >= moment else saturday + timedelta(days=7)


def _close_weekend(data: bytes, table: RawTable) -> bytes | None:
    for row in closed_rows(table):
        if row.time is None or row.not_fill or symbols.normalise_pair(row.symbol) is None:
            continue
        return _set_time(data, table, row, _next_saturday(row.time))
    return None


def _close_within_hours(data: bytes, table: RawTable) -> bytes | None:
    """One close time moved one minute later without passing the next row."""
    closed = [row for row in closed_rows(table) if row.time is not None]
    for position, row in enumerate(closed):
        assert row.time is not None
        target = row.time + _ONE_MINUTE
        if target.weekday() >= 5:
            continue
        following = closed[position + 1].time if position + 1 < len(closed) else None
        if following is not None and following <= target:
            continue
        return _set_time(data, table, row, target)
    return None


def _close_after_report(data: bytes, table: RawTable) -> bytes | None:
    report = read_header(table).report_date
    if report is None:
        return None
    for row in closed_rows(table):
        if row.time is None:
            continue
        return _set_time(data, table, row, report + 2 * _ONE_DAY)
    return None


# --- Monthly table -------------------------------------------------------------

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def monthly_sample(years: int = 6, first_year: int = 2018) -> pd.DataFrame:
    """A deterministic factsheet grid: one row per year, twelve months in
    percentage points at two decimals, and the year's compounded total."""
    records: list[dict[str, Any]] = []
    for offset in range(years):
        year = first_year + offset
        values = [
            Decimal(((year * 12 + month) * 37) % 97 - 40) / Decimal(50) for month in range(1, 13)
        ]
        growth = Decimal(1)
        for value in values:
            growth *= 1 + value / 100
        record: dict[str, Any] = {"Year": year}
        for name, value in zip(MONTH_NAMES, values, strict=True):
            record[name] = float(value)
        record["Total"] = float(((growth - 1) * 100).quantize(Decimal("0.01")))
        records.append(record)
    return pd.DataFrame(records)


def _monthly_value(frame: pd.DataFrame) -> pd.DataFrame:
    """One month of the first year raised by one percentage point."""
    altered = frame.copy()
    first = altered.index[0]
    altered.loc[first, MONTH_NAMES[2]] = float(altered.loc[first, MONTH_NAMES[2]]) + 1.0
    return altered


def _monthly_identity(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy()


def _identity(data: bytes, table: RawTable) -> bytes | None:
    return data


# --- The table of seeds ----------------------------------------------------------

IDENTITY = Seed(
    "identity",
    ALL + (MONTHLY,),
    _identity,
    (),
    edit="no edit (control)",
    apply_frame=_monthly_identity,
)

SEEDS: tuple[Seed, ...] = (
    Seed(
        "delete_losing_row",
        ALL,
        _delete_loss,
        ("TOTALS_VS_ROWS",),
        overrides=(
            (MT5, ("BALANCE_CHAIN", "CROSS_COPIES", "TOTALS_VS_ROWS")),
            (MT5T, ("BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MT4T, ("TESTER_NUMBERING", "BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MYFX, ()),
            (MQL5, ()),
            (FXB, ()),
            (TV, ("TV_INVARIANTS",)),
            (NT, ("NT_INVARIANTS",)),
        ),
        edit="the closed row with the largest loss removed (TradingView: both rows of the trade)",
    ),
    Seed(
        "profit_plus_cent",
        ALL,
        _profit_shift(Decimal("0.01")),
        (),
        overrides=((TV, ("TV_INVARIANTS",)),),
        edit="the largest result moved by +0.01 (inside every money tolerance)",
    ),
    Seed(
        "profit_plus_unit",
        ALL,
        _profit_shift(Decimal("1.00")),
        ("TOTALS_VS_ROWS",),
        overrides=(
            (MT4, ("TOTALS_VS_ROWS", "PRICE_IMPLIED_PNL")),
            (MT5, ("BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MT5T, ("BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MT4T, ("BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MYFX, ()),
            (MQL5, ()),
            (FXB, ()),
            (TV, ("TV_INVARIANTS",)),
            (NT, ("NT_INVARIANTS",)),
        ),
        edit="the largest result moved by +1.00",
    ),
    Seed(
        "profit_sign_flip",
        ALL,
        _profit_flip,
        ("PNL_SIGN",),
        overrides=(
            (MT4, ("TOTALS_VS_ROWS", "PNL_SIGN", "PRICE_IMPLIED_PNL")),
            (MT5, ("BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MT5T, ("BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MT4T, ("BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (TV, ("TV_INVARIANTS", "PNL_SIGN")),
            (NT, ("NT_INVARIANTS", "PNL_SIGN")),
        ),
        edit="the largest loss written as a win of the same size",
    ),
    Seed(
        "close_price_mirror",
        (MT4, MT5, MT4T) + CSV,
        _price_mirror,
        ("PNL_SIGN",),
        overrides=(
            (MT4, ("PNL_SIGN", "PRICE_IMPLIED_PNL")),
            (MT5, ("CROSS_COPIES", "PNL_SIGN")),
            (MT4T, ()),
        ),
        edit="the close price reflected around the open price (same digits, move sign flipped)",
    ),
    Seed(
        "sltp_fill_violation",
        (MT4, MT5, MT5T),
        _sltp_violation,
        ("SLTP_FILL",),
        overrides=((MT5, ("SLTP_FILL", "CROSS_COPIES")),),
        edit="a [tp] fill moved ten ticks past its level (MT5 tester: or [sl] ten ticks nearer)",
    ),
    Seed(
        "close_price_dropped_zero",
        HTML,
        _dropped_zero,
        ("PRICE_PRECISION",),
        edit="one close price printed with a trailing zero dropped (or one decimal added)",
    ),
    Seed(
        "duplicate_new_ticket",
        ALL,
        _duplicate_new_ticket,
        ("TOTALS_VS_ROWS",),
        overrides=(
            (MT4, ("TOTALS_VS_ROWS", "TICKET_ORDER")),
            (
                MT5,
                ("BALANCE_CHAIN", "DEAL_SEQUENCE", "CROSS_COPIES", "TOTALS_VS_ROWS", "ROW_ORDER"),
            ),
            (
                MT5T,
                (
                    "BALANCE_CHAIN",
                    "DEAL_SEQUENCE",
                    "TESTER_NUMBERING",
                    "TOTALS_VS_ROWS",
                    "ROW_ORDER",
                ),
            ),
            (MT4T, ("TESTER_NUMBERING", "BALANCE_CHAIN", "TOTALS_VS_ROWS")),
            (MYFX, ("TICKET_ORDER",)),
            (MQL5, ()),
            (FXB, ("TICKET_ORDER",)),
            (TV, ("DUPLICATE_TICKET", "TV_INVARIANTS")),
            (NT, ("NT_INVARIANTS",)),
        ),
        edit="the winning row with the lowest ticket copied under ticket max+1 (HTML: +1 min)",
    ),
    Seed(
        "duplicate_same_ticket",
        ALL,
        _duplicate_same_ticket,
        ("DUPLICATE_TICKET",),
        overrides=(
            (MT4, ("DUPLICATE_TICKET", "TOTALS_VS_ROWS")),
            (MT5, ("DUPLICATE_TICKET", "BALANCE_CHAIN", "DEAL_SEQUENCE", "CROSS_COPIES")),
            (MT5T, ("DUPLICATE_TICKET", "BALANCE_CHAIN", "DEAL_SEQUENCE", "TESTER_NUMBERING")),
            (MT4T, ("TESTER_NUMBERING", "BALANCE_CHAIN")),
            (MQL5, ()),
            (TV, ("DUPLICATE_TICKET", "TV_INVARIANTS")),
            (NT, ("DUPLICATE_TICKET", "NT_INVARIANTS")),
        ),
        edit="the winning row with the lowest ticket copied verbatim right after itself",
    ),
    Seed(
        "drop_withdrawal",
        (MT4, MT5, MT5T, MYFX, MQL5, FXB),
        _drop_cash(want_withdrawal=True),
        (),
        overrides=((MT5, ("BALANCE_CHAIN",)), (MT5T, ("BALANCE_CHAIN",))),
        edit="the last withdrawal row removed (MT5: one with deals on both sides)",
    ),
    Seed(
        "drop_deposit",
        (MT4, MT5, MT5T, MYFX, MQL5, FXB),
        _drop_cash(want_withdrawal=False),
        (),
        overrides=((MT5, ("BALANCE_CHAIN",)), (MT5T, ("BALANCE_CHAIN",))),
        edit="the last deposit row removed (MT5: one with deals on both sides)",
    ),
    Seed(
        "summary_total_edit",
        HTML,
        _summary_total,
        ("TOTALS_VS_ROWS", "SUMMARY_IDENTITIES"),
        edit="the declared net result (Closed P/L, Total Net Profit) moved by +100.00",
    ),
    Seed(
        "header_date_backwards",
        (MT4, MT5),
        _header_backwards,
        ("TIME_SANITY",),
        edit="the report's own date set one day before the first closed row",
    ),
    Seed(
        "hide_row_class",
        HTML,
        _hide_row,
        ("HIDDEN_CONTENT",),
        overrides=(
            (MT4, ("TOTALS_VS_ROWS",)),
            (MT4T, ("TESTER_NUMBERING", "BALANCE_CHAIN", "TOTALS_VS_ROWS")),
        ),
        edit="every cell of the largest losing row given class=hidden",
    ),
    Seed(
        "hide_row_style",
        HTML,
        _hide_row_style,
        (),
        edit="the largest losing row given style=display:none (the reader ignores styles)",
    ),
    Seed(
        "fill_hidden_text",
        (MT5, MT5T),
        _fill_hidden(_HIDDEN_TEXT, any_row=True),
        ("HIDDEN_CONTENT",),
        edit="a hidden cell (a deal's Cost, else a Positions cell) filled with text",
    ),
    Seed(
        "fill_hidden_number",
        (MT5, MT5T),
        _fill_hidden(_HIDDEN_NUMBER),
        ("BALANCE_CHAIN",),
        edit="a deal's hidden Cost cell filled with 5.00 (read into the balance chain)",
    ),
    Seed(
        "move_to_open",
        (MT4,),
        _move_to_open,
        ("TOTALS_VS_ROWS",),
        edit="the largest losing trade re-listed under Open Trades",
    ),
    Seed(
        "swap_adjacent_rows",
        ALL,
        _swap_adjacent,
        ("ROW_ORDER",),
        overrides=(
            (MT5, ("ROW_ORDER", "DEAL_SEQUENCE", "BALANCE_CHAIN")),
            (MT5T, ("ROW_ORDER", "DEAL_SEQUENCE", "BALANCE_CHAIN", "TESTER_NUMBERING")),
            (MT4T, ("ROW_ORDER", "TESTER_NUMBERING", "BALANCE_CHAIN")),
            (TV, ()),
        ),
        edit="two adjacent closed rows exchanged",
    ),
    Seed(
        "symbol_change_row",
        (MT4, MT5, MT5T) + CSV,
        _symbol_change,
        ("PRICE_PRECISION",),
        overrides=(
            (MT5, ("PRICE_PRECISION", "CROSS_COPIES")),
            (MYFX, ()),
            (MQL5, ()),
            (FXB, ()),
            (TV, ()),
            (NT, ()),
        ),
        edit="one row's symbol replaced by another symbol of the file printed with other digits",
    ),
    Seed(
        "deal_number_change",
        (MT5, MT5T),
        _number_change("deal"),
        ("DEAL_SEQUENCE",),
        overrides=((MT5T, ("DEAL_SEQUENCE", "TESTER_NUMBERING")),),
        edit="the first trade deal's number replaced by max+1",
    ),
    Seed(
        "order_number_change",
        (MT5, MT5T),
        _number_change("order"),
        ("TESTER_NUMBERING",),
        overrides=((MT5, ("CROSS_COPIES",)),),
        edit="an order's number (one a deal names, else the first) replaced by max+1",
    ),
    Seed(
        "close_time_weekend",
        (MT4, MT5, MT5T, MT4T, MYFX, MQL5, FXB),
        _close_weekend,
        ("MARKET_HOURS",),
        edit="a listed pair's close time moved to the next Saturday 15:00",
    ),
    Seed(
        "close_time_within_hours",
        (MT4, MT5, MT5T, MT4T, MYFX, MQL5, FXB, NT),
        _close_within_hours,
        (),
        overrides=((MT5, ("CROSS_COPIES",)),),
        edit="a close time moved one minute later, row order kept",
    ),
    Seed(
        "close_time_after_report",
        HTML,
        _close_after_report,
        ("TIME_SANITY",),
        edit="a close time moved two days past the report's own date",
    ),
    Seed(
        "monthly_value",
        (MONTHLY,),
        _identity,
        ("MONTHLY_DIGITS",),
        edit="one month of a factsheet grid raised by one percentage point",
        apply_frame=_monthly_value,
    ),
)

SEED_IDS = tuple(seed.id for seed in SEEDS)


# ---------------------------------------------------------------------------
# Running seeds
# ---------------------------------------------------------------------------


def _upload_name(source_format: str | None) -> str:
    suffix = (source_format or "").rsplit("_", 1)[-1]
    return "upload." + _EXTENSION.get(suffix, "txt")


def _review(data: bytes, source_format: str | None) -> ForensicResult:
    """The battery as the corpus runner feeds it: the importer's warnings
    and currency when the import succeeds, none when it refuses the file."""
    warnings: list[str] = []
    currency: str | None = None
    try:
        imported = importers.import_report(data, _upload_name(source_format))
        warnings = list(imported.warnings)
        currency = imported.currency
    except Exception:  # noqa: BLE001 - the battery still runs when the import refuses
        pass
    return review(data, source_format=source_format, imported_warnings=warnings, currency=currency)


def _hits(result: ForensicResult, check_id: str) -> int:
    value = result.check(check_id).figure("n_hits")
    return int(value) if value is not None and value.isdigit() else 0


def found_by(before: ForensicResult, after: ForensicResult) -> tuple[str, ...]:
    """Checks whose status moved to found, or whose hit count rose."""
    found: list[str] = []
    for check in after.checks:
        if check.status not in FOUND_STATUSES:
            continue
        previous = before.check(check.id)
        rose = _hits(after, check.id) > _hits(before, check.id)
        if previous.status not in FOUND_STATUSES or rose:
            found.append(check.id)
    return tuple(found)


Figures = tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def _figures(result: ForensicResult, checks: Sequence[str]) -> Figures:
    out: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for check_id in checks:
        check = result.check(check_id)
        items: list[tuple[str, str]] = [("status", check.status)]
        if check.reason:
            items.append(("reason", check.reason))
        items.extend((key, value) for key, value, _evidence in check.figures)
        out.append((check_id, tuple(items)))
    return tuple(out)


def _result(
    seed: Seed,
    family: str,
    applied: bool,
    found: tuple[str, ...],
    after: ForensicResult | None,
    note: str = "",
) -> SeedResult:
    expected = seed.expected_for(family)
    return SeedResult(
        seed_id=seed.id,
        applied=applied,
        found_by=found,
        expected_found=bool(set(found) & set(expected)),
        family=family,
        expected=expected,
        unexpected=tuple(check for check in found if check not in expected),
        figures=_figures(after, expected) if after is not None else (),
        note=note,
    )


def run_seeds(
    data: bytes,
    source_format: str | None,
    seeds: Sequence[Seed] = SEEDS,
    *,
    monthly: pd.DataFrame | None = None,
) -> list[SeedResult]:
    """Every seed that lists the file's family, applied to ``data`` and
    reviewed against the original. ``monthly`` runs the monthly seeds on a
    factsheet grid instead of a file."""
    if monthly is not None:
        return _run_monthly(monthly, seeds)
    table = rows.load(data, source_format)
    family = table.family
    before = _review(data, source_format)
    results: list[SeedResult] = []
    for seed in seeds:
        if family not in seed.families:
            continue
        try:
            altered = seed.apply(data, table)
        except ValueError as error:
            results.append(_result(seed, family, False, (), None, note=f"not_applicable:{error}"))
            continue
        if altered is None:
            results.append(_result(seed, family, False, (), None, note="not_applicable"))
            continue
        try:
            after = _review(altered, source_format)
        except (importers.ReportFormatError, ValueError) as error:
            note = f"review_refused:{type(error).__name__}"
            results.append(_result(seed, family, True, (), None, note=note))
            continue
        results.append(_result(seed, family, True, found_by(before, after), after))
    return results


def _run_monthly(frame: pd.DataFrame, seeds: Sequence[Seed]) -> list[SeedResult]:
    grid = factsheet.monthly_grid(frame)
    before = review(b"", source_format=None, monthly=grid)
    results: list[SeedResult] = []
    for seed in seeds:
        if MONTHLY not in seed.families or seed.apply_frame is None:
            continue
        altered = factsheet.monthly_grid(seed.apply_frame(frame))
        after = review(b"", source_format=None, monthly=altered)
        results.append(_result(seed, MONTHLY, True, found_by(before, after), after))
    return results


# ---------------------------------------------------------------------------
# Fixtures and inline samples
# ---------------------------------------------------------------------------

FIXTURE_NAMES = (
    "mt4_statement.htm",
    "mt5_history.html",
    "mt5_tester.html",
    "mt4_tester.htm",
    "tradingview_g1.csv",
    "tradingview_g3b.csv",
    "ninjatrader.csv",
)

#: Tiny delimited exports in the header shapes the importers recognise
#: (no real account, name or broker), each with a losing trade and three
#: symbols, one of them quoted in another currency.
SAMPLES: dict[str, bytes] = {
    "myfxbook.csv": (
        b"Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Close Price,"
        b"Commission,Swap,Pips,Profit,Gain,Comment\n"
        b",1005,12/21/2023 02:55,12/22/2023 16:07,EURUSD,Buy,0.10,0,0,1.09500,1.10000,-0.70,-0.20,"
        b"50.0,49.10,0.5,\n"
        b",1004,12/20/2023 17:55,12/21/2023 04:46,GBPUSD,Sell,0.10,0,0,1.27000,1.26500,-0.70,0.00,"
        b"50.0,49.30,0.5,\n"
        b",1003,12/19/2023 09:00,12/19/2023 15:30,EURUSD,Sell,0.10,0,0,1.09800,1.09700,-0.70,0.00,"
        b"10.0,9.30,0.1,\n"
        b",1002,12/18/2023 09:00,12/18/2023 12:00,USDJPY,Buy,0.10,0,0,142.000,142.500,-0.70,0.00,"
        b"50.0,35.00,0.3,\n"
        b",1001,12/15/2023 09:00,12/15/2023 12:00,GBPUSD,Buy,0.10,0,0,1.27200,1.26700,-0.70,0.00,"
        b"-50.0,-50.70,-0.5,\n"
        b",1000,12/01/2023 08:00,12/01/2023 08:00,,Deposit,,,,,,,,,1000.00,,\n"
        b"Open Trades\n"
        b",Ticket,Open Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Profit,Pips\n"
        b",1006,12/26/2023 09:00,EURUSD,Buy,0.10,0,0,1.10000,1.00,1.0\n"
    ),
    "mql5_signal.csv": (
        b"Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit;Comment\n"
        b"2025.11.14 13:08:13;Buy;0.10;EURUSD;1.16000;0.00000;0.00000;2025.11.14 18:22:40;1.16100;"
        b"-0.70;0.00;10.00;\n"
        b"2025.11.13 20:32:54;Sell;0.10;GBPUSD;1.31000;0.00000;0.00000;2025.11.14 09:00:00;1.30900;"
        b"-0.70;0.00;10.00;\n"
        b"2025.11.12 10:00:00;Buy;0.10;EURUSD;1.15900;0.00000;0.00000;2025.11.12 12:00:00;1.15800;"
        b"-0.70;0.00;-10.00;\n"
        b"2025.11.11 10:00:00;Sell;0.10;USDJPY;150.000;0.000;0.000;2025.11.11 12:00:00;149.500;"
        b"-0.70;0.00;33.44;\n"
        b"2025.11.10 10:00:00;Sell;0.10;GBPUSD;1.31200;0.00000;0.00000;2025.11.10 12:00:00;1.31100;"
        b"-0.70;0.00;10.00;\n"
        b"2025.11.01 00:00:00;Balance;;;;;;;;0.00;0.00;1000.00;Deposit\n"
    ),
    "fxblue.csv": (
        b"Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,Open date,"
        b"Close date,Profit,Swap,Commission,Net profit,T/P,S/L,Pips,Result,Trade duration (hours),"
        b"Magic number,Order comment,Account\n"
        b"Deposit,1,,0,,0,0,2025/04/01 10:00:00,2025/04/01 10:00:00,2025/04/01,2025/04/01,1000,0,0,"
        b"1000,0,0,0,,0,0,,1\n"
        b"Closed position,2,EURUSD,0.1,Buy,1.09,1.1,2025/04/22 16:44:01,2025/04/23 10:00:00,"
        b"2025/04/22,2025/04/23,100,0,-0.7,99.3,0,0,100,Won,17,0,,1\n"
        b"Closed position,3,EURUSD,0.1,Sell,1.1,1.101,2025/04/23 09:00:00,2025/04/24 10:00:00,"
        b"2025/04/23,2025/04/24,-10,0,-0.7,-10.7,0,0,-10,Lost,25,0,,1\n"
        b"Closed position,4,USDJPY,0.1,Sell,150,149.5,2025/04/24 09:00:00,2025/04/25 10:00:00,"
        b"2025/04/24,2025/04/25,33.44,0,-0.7,32.74,0,0,50,Won,25,0,,1\n"
        b"Closed position,5,USTEC,0.1,Sell,18000,17990,2025/04/25 09:00:00,2025/04/28 10:00:00,"
        b"2025/04/25,2025/04/28,10,0,-0.7,9.3,0,0,10,Won,73,0,,1\n"
        b"Open position,6,EURUSD,0.1,Buy,1.1,1.1,2025/04/29 09:00:00,1970/01/01 00:00:00,"
        b"2025/04/29,1970/01/01,0,0,0,0,0,0,0,,0,0,,1\n"
    ),
}


def fixture_files() -> list[tuple[str, bytes]]:
    """The repo fixtures the lab runs on, then the inline samples."""
    files = [(name, (FIXTURES / name).read_bytes()) for name in FIXTURE_NAMES]
    files.extend(sorted(SAMPLES.items()))
    return files


def run_fixtures(seeds: Sequence[Seed] = SEEDS) -> dict[str, list[SeedResult]]:
    """Seed results per fixture name (plus ``monthly`` for the grid sample)."""
    out: dict[str, list[SeedResult]] = {}
    for name, data in fixture_files():
        out[name] = run_seeds(data, importers.detect_format(data), seeds)
    out["monthly"] = run_seeds(b"", None, seeds, monthly=monthly_sample())
    return out


# ---------------------------------------------------------------------------
# Corpus run
# ---------------------------------------------------------------------------


def _split(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # The same deterministic split as the calibration runner.
    from forensics_corpus import split

    return split(entries)


@dataclass
class _Cell:
    applicable: int = 0
    found: int = 0
    misses: list[dict[str, Any]] = field(default_factory=list)
    unexpected: dict[str, int] = field(default_factory=dict)
    not_applicable: int = 0
    notes: dict[str, int] = field(default_factory=dict)


def run_corpus(manifest: Path, root: Path, *, which: str) -> dict[str, Any]:
    entries = [entry for entry in json.loads(manifest.read_text()) if entry.get("genuine")]
    calibration, reserved = _split(entries)
    chosen = {"calibration": calibration, "reserved": reserved, "all": calibration + reserved}
    cells: dict[tuple[str, str], _Cell] = {}
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    files_run = 0
    for entry in sorted(chosen[which], key=lambda item: item["path"]):
        if entry["bytes"] > MAX_CORPUS_BYTES:
            skipped.append(
                {"path": entry["path"], "bytes": entry["bytes"], "format": entry["format"]}
            )
            continue
        data = (root / entry["path"]).read_bytes()
        try:
            results = run_seeds(data, entry["format"])
        except Exception as error:  # noqa: BLE001 - one bad file never stops the run
            errors.append({"path": entry["path"], "error": type(error).__name__})
            continue
        files_run += 1
        for result in results:
            cell = cells.setdefault((result.seed_id, result.family), _Cell())
            if not result.applied:
                cell.not_applicable += 1
                cell.notes[result.note] = cell.notes.get(result.note, 0) + 1
                continue
            cell.applicable += 1
            for check in result.unexpected:
                cell.unexpected[check] = cell.unexpected.get(check, 0) + 1
            if result.expected_found:
                cell.found += 1
            else:
                cell.misses.append(
                    {
                        "path": entry["path"],
                        "sha256_prefix": entry["sha256"][:12],
                        "found_by": list(result.found_by),
                        "figures": {check: dict(items) for check, items in result.figures},
                        "note": result.note,
                    }
                )
    by_id = {seed.id: seed for seed in SEEDS}
    table = [
        {
            "seed": seed_id,
            "family": family,
            "applicable": cell.applicable,
            "not_applicable": cell.not_applicable,
            "found": cell.found,
            "missed": cell.applicable - cell.found,
            "rate": money.ratio_text(cell.found, cell.applicable),
            "expected": list(by_id[seed_id].expected_for(family)),
            "unexpected": dict(sorted(cell.unexpected.items())),
            "not_applicable_notes": dict(sorted(cell.notes.items())),
            "misses": cell.misses,
        }
        for (seed_id, family), cell in sorted(cells.items())
    ]
    return {
        "which": which,
        "files_run": files_run,
        "skipped_over_2mb": skipped,
        "errors": errors,
        "table": table,
    }


def print_table(table: list[dict[str, Any]]) -> None:
    print(
        f"{'seed':26} {'family':14} {'appl':>5} {'n/a':>4} {'found':>5} {'miss':>5} "
        f"{'rate':>6}  expected"
    )
    for row in table:
        print(
            f"{row['seed']:26} {row['family']:14} {row['applicable']:5d} "
            f"{row['not_applicable']:4d} {row['found']:5d} {row['missed']:5d} "
            f"{row['rate']:>6}  {','.join(row['expected'])}"
        )


def fixtures_report(results: dict[str, list[SeedResult]]) -> dict[str, Any]:
    return {name: [item.as_dict() for item in items] for name, items in sorted(results.items())}


def print_fixtures(results: dict[str, list[SeedResult]]) -> None:
    print(f"{'file':20} {'seed':26} {'applied':>7} {'found':>5}  found_by | expected")
    for name, items in sorted(results.items()):
        for item in items:
            print(
                f"{name:20} {item.seed_id:26} {int(item.applied):7d} "
                f"{int(item.expected_found):5d}  {','.join(item.found_by)} | "
                f"{','.join(item.expected)} {item.note}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("root", nargs="?", type=Path)
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--reserved", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.fixtures:
        results = run_fixtures()
        print_fixtures(results)
        if args.out:
            args.out.write_text(json.dumps(fixtures_report(results), indent=1, sort_keys=True))
            print("written", args.out)
        return 0
    if args.manifest is None or args.root is None:
        parser.error("MANIFEST and ROOT are required without --fixtures")
    which = "all" if args.all else "reserved" if args.reserved else "calibration"
    result = run_corpus(args.manifest, args.root, which=which)
    print_table(result["table"])
    print(
        f"{result['files_run']} file(s) run, {len(result['skipped_over_2mb'])} skipped over 2 MB, "
        f"{len(result['errors'])} error(s)"
    )
    if args.out:
        args.out.write_text(json.dumps(result, indent=1, sort_keys=True))
        print("written", args.out)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())
