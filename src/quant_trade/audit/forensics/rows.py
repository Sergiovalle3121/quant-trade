"""Read-only access to the raw rows of an uploaded report.

The importers turn a report into trades; the battery needs the rows as the
platform printed them: every cell's text, hidden cells, ``title``
attributes, section and column layout. This module reads the file again
through the importers' own readers (``unwrap``, ``decode_text``,
``read_xlsx``, ``_read_html``, ``_read_delimited``) without mutating them,
classifies each row with the importers' own predicates and hands out frozen
tuples. Nothing here interprets a number.

A public reader is requested from the importers' owner; until it lands, the
private names used here are pinned by a test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from quant_trade.audit import importers, schema
from quant_trade.audit.forensics import families

# Sections ------------------------------------------------------------------
SECTION_HEADER = "header"
SECTION_CLOSED = "closed"
SECTION_OPEN = "open"
SECTION_WORKING = "working"
SECTION_POSITIONS = "positions"
SECTION_OPEN_POSITIONS = "open_positions"
SECTION_ORDERS = "orders"
SECTION_DEALS = "deals"
SECTION_TESTER = "tester"
SECTION_SUMMARY = "summary"
SECTION_CSV = "csv"
SECTION_OTHER = "other"

# Row kinds -----------------------------------------------------------------
KIND_HEADER = "header"
KIND_TITLE = "title"
KIND_LABEL = "label"
KIND_MT4_TRADE = "mt4_trade"
KIND_MT4_CASH = "mt4_cash"
KIND_MT4_CREDIT = "mt4_credit"
KIND_MT4_CANCELLED = "mt4_cancelled"
KIND_MT4_PENDING = "mt4_pending"
KIND_MT4_OPEN = "mt4_open"
KIND_MT4_WORKING = "mt4_working"
KIND_MT5_DEAL = "mt5_deal"
KIND_MT5_POSITION = "mt5_position"
KIND_MT5_ORDER = "mt5_order"
KIND_MT5_OPEN_POSITION = "mt5_open_position"
KIND_MT4_TESTER = "mt4_tester"
KIND_CSV = "csv"
KIND_FOOTER = "footer"
KIND_OTHER = "other"

#: Encodings ``decode_text`` can choose, as codes.
ENCODING_CODES = (
    "utf8_bom",
    "utf16le_bom",
    "utf16be_bom",
    "utf16le",
    "utf16be",
    "utf8",
    "cp1251",
    "cp1252",
    "latin1",
)
GENERATOR_CODES = (
    "metaquotes",
    "client_terminal",
    "strategy_tester",
    "excel",
    "word",
    "mshtml",
    "other",
    "none",
)
#: Traces a re-save through a browser or an Office program leaves in the
#: page, as ``(code, needle)``. ``mso-`` counts only outside the
#: ``mso-number-format`` rule that every genuine MetaTrader page carries in
#: its own stylesheet.
_RESAVE_MARKERS: tuple[tuple[str, str], ...] = (
    ("meta_charset", "<meta charset"),
    ("saved_from_url", "saved from url"),
    ("progid", "progid"),
    ("xmlns_o", "xmlns:o="),
    ("mso", "mso-"),
    ("class_xl", "class=xl"),
)
_PLATFORM_STYLE = "mso-number-format"

_MT5_ORDER_STATES = frozenset(
    {"filled", "canceled", "cancelled", "expired", "rejected", "placed", "partial", "started"}
)
_MT4_PENDING = frozenset({"buy limit", "sell limit", "buy stop", "sell stop"})
_MT4_SIDES = frozenset({"buy", "sell"})
_MT4_DIGITS = re.compile(r"^\d+$")


@dataclass(frozen=True)
class RawCell:
    text: str
    hidden: bool = False
    title: str = ""


@dataclass(frozen=True)
class RawRow:
    index: int
    texts: tuple[str, ...]
    cells: tuple[RawCell, ...]
    section: str
    kind: str
    header_row: int
    """Raw index of the closest header row above, ``-1`` when none."""

    def text(self, position: int) -> str:
        return self.texts[position] if 0 <= position < len(self.texts) else ""


@dataclass(frozen=True)
class RawTable:
    source_format: str
    family: str
    rows: tuple[RawRow, ...]
    labels: tuple[tuple[str, str], ...]
    """``Label: value`` pairs of the header and summary, first occurrence wins."""
    generator: str
    encoding: str
    line_endings: str
    markers: int
    truncated: bool
    header: tuple[str, ...] = ()
    """Delimited files: the column names."""
    delimiter: str = ""
    title_present: bool = False
    account_label_present: bool = False
    header_texts: tuple[tuple[int, tuple[str, ...]], ...] = ()
    """``(raw index, texts)`` of every header row, so a check can map columns."""

    def label(self, name: str) -> str | None:
        for key, value in self.labels:
            if key == name:
                return value
        return None

    def section(self, name: str) -> tuple[RawRow, ...]:
        return tuple(row for row in self.rows if row.section == name)

    def kind(self, name: str) -> tuple[RawRow, ...]:
        return tuple(row for row in self.rows if row.kind == name)

    def header_of(self, row: RawRow) -> tuple[str, ...]:
        for index, texts in self.header_texts:
            if index == row.header_row:
                return texts
        return ()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load(data: bytes, source_format: str | None) -> RawTable:
    """The raw rows of ``data`` as a frozen table.

    ``ReportFormatError`` from the importers' readers propagates unchanged:
    the caller already refused such a file at upload time.
    """
    importers._check_size(data)
    raw = importers.unwrap(data)
    family = families.family_of(source_format)
    if importers._is_workbook(raw):
        return _load_workbook(raw, source_format, family)
    text = importers.decode_text(raw)
    encoding = encoding_code(raw)
    endings = line_endings(text)
    markers = resave_markers(text)
    if family in families.CSV_FAMILIES or (family == families.OTHER and not _looks_html(text)):
        header, rows, delimiter = importers._read_delimited(text)
        return _from_delimited(
            header, rows, delimiter, source_format, family, encoding, endings, markers
        )
    reader = importers._read_html(text)
    return _from_reader(reader, source_format, family, encoding, endings, markers)


def _looks_html(text: str) -> bool:
    lowered = text.lstrip()[:4000].lower()
    return "<html" in lowered or "<table" in lowered or "<!doctype html" in lowered


def _load_workbook(raw: bytes, source_format: str | None, family: str) -> RawTable:
    sheets = importers.read_xlsx(raw)
    if family in {families.MT5_HISTORY, families.MT5_TESTER}:
        found = importers._mt5_workbook(sheets)
        if found is not None:
            return _from_reader(found[1], source_format, family, "none", "none", 0)
    ordered = list(sheets.values())
    if family == families.TRADINGVIEW:
        # The export's first sheet is "Performance"; the trades come later.
        ordered = [rows for rows in ordered if rows and importers._is_tradingview_header(rows[0])]
    for rows in ordered:
        if rows:
            header = tuple(importers._as_text(value) for value in rows[0])
            body = [[importers._as_text(value) for value in row] for row in rows[1:]]
            return _from_delimited(list(header), body, "", source_format, family, "none", "none", 0)
    return RawTable(source_format or "", family, (), (), "none", "none", "none", 0, False)


def encoding_code(data: bytes) -> str:
    """The encoding ``decode_text`` picks, as a code (its rules, re-applied)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf8_bom"
    if data.startswith(b"\xff\xfe"):
        return "utf16le_bom"
    if data.startswith(b"\xfe\xff"):
        return "utf16be_bom"
    utf16 = importers._looks_utf16(data)
    if utf16 == "utf-16-le":
        return "utf16le"
    if utf16 == "utf-16-be":
        return "utf16be"
    try:
        data.decode("utf-8")
        return "utf8"
    except UnicodeDecodeError:
        pass
    if importers._looks_cp1251(data):
        return "cp1251"
    try:
        data.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError:
        return "latin1"


def line_endings(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and lf:
        return "mixed"
    if crlf:
        return "crlf"
    if lf:
        return "lf"
    return "none"


def marker_codes(text: str) -> tuple[str, ...]:
    """The re-save markers present in the page, as codes, in a fixed order."""
    lowered = text[:200_000].lower().replace(_PLATFORM_STYLE, "")
    return tuple(code for code, needle in _RESAVE_MARKERS if needle in lowered)


def resave_markers(text: str) -> int:
    return len(marker_codes(text))


def generator_code(meta_generator: str) -> str:
    lowered = meta_generator.lower()
    if not lowered:
        return "none"
    for needle, code in (
        ("metaquotes", "metaquotes"),
        ("client terminal", "client_terminal"),
        ("strategy tester", "strategy_tester"),
        ("metatrader", "metatrader"),
        ("excel", "excel"),
        ("word", "word"),
        ("mshtml", "mshtml"),
    ):
        if needle in lowered:
            return code
    return "other"


# ---------------------------------------------------------------------------
# HTML families
# ---------------------------------------------------------------------------


def _from_reader(
    reader: Any,
    source_format: str | None,
    family: str,
    encoding: str,
    endings: str,
    markers: int,
) -> RawTable:
    rows: list[RawRow] = []
    header_texts: list[tuple[int, tuple[str, ...]]] = []
    section = SECTION_HEADER
    header_row = -1
    columns = dict(importers._MT4_STATEMENT_COLUMNS)
    truncated = False
    limit = schema.MAX_ROWS
    for index, row in enumerate(reader.rows):
        if index >= limit:
            truncated = True
            break
        texts = tuple(row.texts)
        cells = tuple(
            RawCell(cell.text, cell.hidden, cell.attrs.get("title", "")) for cell in row.cells
        )
        kind = KIND_OTHER
        if family == families.MT4_STATEMENT:
            found = importers._mt4_statement_columns(list(texts))
            if found is not None or (row.is_mt_header and "ticket" in {t.lower() for t in texts}):
                if found is not None:
                    columns = found
                section = _mt4_section_of_header(texts, section)
                kind = KIND_HEADER
                header_row = index
            else:
                title = _mt4_title(texts)
                if title is not None:
                    section = title
                    kind = KIND_TITLE
                elif _is_label_row(texts):
                    kind = KIND_LABEL
                else:
                    kind = _mt4_kind(texts, columns, section)
        elif family in {families.MT5_HISTORY, families.MT5_TESTER}:
            if row.is_mt_header:
                section = _mt5_section_of_header(texts)
                kind = KIND_HEADER
                header_row = index
            elif importers._is_mt5_deal(list(texts)):
                kind = KIND_MT5_DEAL
                section = SECTION_DEALS if section != SECTION_DEALS else section
            elif importers._is_mt5_position(list(texts)):
                kind = KIND_MT5_POSITION
                if section not in {SECTION_POSITIONS, SECTION_OPEN_POSITIONS}:
                    section = SECTION_POSITIONS
            elif _is_mt5_order(texts):
                kind = KIND_MT5_ORDER
                section = SECTION_ORDERS
            elif _is_mt5_open_position(texts):
                kind = KIND_MT5_OPEN_POSITION
                section = SECTION_OPEN_POSITIONS
            elif _is_label_row(texts):
                kind = KIND_LABEL
            elif _is_footer(texts):
                kind = KIND_FOOTER
            elif len(texts) == 1 and texts[0]:
                kind = KIND_TITLE
                if section in {
                    SECTION_DEALS,
                    SECTION_POSITIONS,
                    SECTION_ORDERS,
                    SECTION_OPEN_POSITIONS,
                }:
                    section = SECTION_SUMMARY
        elif family == families.MT4_TESTER:
            if row.is_mt_header:
                section = SECTION_TESTER
                kind = KIND_HEADER
                header_row = index
            elif importers._is_mt4_tester_row(list(texts)):
                kind = KIND_MT4_TESTER
                section = SECTION_TESTER
            elif _is_label_row(texts) or len(texts) >= 2:
                kind = KIND_LABEL
        else:
            kind = KIND_OTHER
        if kind == KIND_HEADER:
            header_texts.append((index, texts))
        rows.append(RawRow(index, texts, cells, section, kind, header_row))
    labels = _labels(reader, family)
    title = getattr(reader, "title", "") or ""
    return RawTable(
        source_format=source_format or "",
        family=family,
        rows=tuple(rows),
        labels=labels,
        generator=generator_code(getattr(reader, "meta", {}).get("generator", "")),
        encoding=encoding,
        line_endings=endings,
        markers=markers,
        truncated=truncated,
        title_present=bool(title.strip()),
        account_label_present=_account_present(reader, family, title),
        header_texts=tuple(header_texts),
    )


def _labels(reader: Any, family: str) -> tuple[tuple[str, str], ...]:
    if family == families.MT4_TESTER:
        found = importers._mt4_pairs(reader.rows)
    elif family in {families.MT5_HISTORY, families.MT5_TESTER}:
        found = importers._mt5_labels(reader.rows)
    else:
        found = importers._labels(reader.rows)
    return tuple((key, value) for key, value in found.items())


def _account_present(reader: Any, family: str, title: str) -> bool:
    if family == families.MT4_STATEMENT:
        first = reader.rows[0].texts if reader.rows else []
        return any(text.startswith(("Account:", "A/C No:")) for text in first) or bool(
            re.match(r"^Statement:\s*\d+", title)
        )
    if family == families.MT5_HISTORY:
        labels = importers._mt5_labels(reader.rows)
        return bool(labels.get("Account")) or bool(re.match(r"^\d{3,}:", title))
    return False


def _mt4_title(texts: tuple[str, ...]) -> str | None:
    if len(texts) != 1:
        return None
    name = texts[0].strip().lower().rstrip(":")
    return {
        "closed transactions": SECTION_CLOSED,
        "open trades": SECTION_OPEN,
        "working orders": SECTION_WORKING,
        "summary": SECTION_SUMMARY,
        "details": SECTION_SUMMARY,
    }.get(name)


def _mt4_section_of_header(texts: tuple[str, ...], current: str) -> str:
    names = [text.strip().lower() for text in texts]
    if "market price" in names:
        return SECTION_WORKING
    if "close time" in names:
        return SECTION_CLOSED
    if "ticket" in names and "open time" in names:
        return SECTION_OPEN
    return current


def _mt4_kind(texts: tuple[str, ...], columns: dict[str, int], section: str) -> str:
    if not texts:
        return KIND_OTHER
    if section in {SECTION_SUMMARY, SECTION_HEADER}:
        return KIND_LABEL if _is_label_row(texts) or len(texts) >= 2 else KIND_OTHER
    at = columns["open_time"]
    kind_index = columns["type"]
    kind = texts[kind_index].lower() if len(texts) > kind_index else ""
    has_time = len(texts) > at and importers._is_mt_time(texts[at])
    if section == SECTION_CLOSED:
        if importers._is_mt4_statement_trade(list(texts), columns):
            return KIND_MT4_TRADE
        if has_time and kind == "balance":
            return KIND_MT4_CASH
        if has_time and kind == "credit":
            return KIND_MT4_CREDIT
        if has_time and any(text.lower() == "cancelled" for text in texts):
            return KIND_MT4_CANCELLED
        if has_time and kind in _MT4_PENDING:
            return KIND_MT4_PENDING
        if texts and _MT4_DIGITS.match(texts[0]) and has_time:
            return KIND_OTHER
        return KIND_FOOTER if _is_footer(texts) else KIND_OTHER
    if section == SECTION_OPEN:
        if has_time and kind in _MT4_SIDES:
            return KIND_MT4_OPEN
        if has_time and kind == "balance":
            return KIND_MT4_CASH
        return KIND_FOOTER if _is_footer(texts) else KIND_OTHER
    if section == SECTION_WORKING:
        if has_time and kind in _MT4_PENDING:
            return KIND_MT4_WORKING
        return KIND_OTHER
    return KIND_OTHER


def _mt5_section_of_header(texts: tuple[str, ...]) -> str:
    names = [
        importers._MT5_DEAL_HEADER_ALIASES.get(t.strip().lower(), t.strip().lower()) for t in texts
    ]
    if "direction" in names or "deal" in names or "balance" in names:
        return SECTION_DEALS
    if "state" in names or (len(names) == 11 and names[0] != names[8]):
        return SECTION_ORDERS
    if "position" in names or (len(names) >= 13 and names[0] == names[8] and names[5] == names[9]):
        return SECTION_POSITIONS
    if len(names) >= 13 and names[0] != names[8]:
        return SECTION_DEALS
    return SECTION_OTHER


_MT5_VOLUME = re.compile(r"^\d+(\.\d+)?\s*/\s*\d+(\.\d+)?$")


def _is_mt5_order(texts: tuple[str, ...]) -> bool:
    return (
        len(texts) >= 10
        and importers._is_mt_time(texts[0])
        and texts[1].isdigit()
        and bool(_MT5_VOLUME.match(texts[4]))
    )


def _is_mt5_open_position(texts: tuple[str, ...]) -> bool:
    """An "Open Positions" row: open time, position id, symbol, side, volume
    and price, with no close time in the ninth cell."""
    return (
        len(texts) >= 10
        and importers._is_mt_time(texts[0])
        and texts[1].isdigit()
        and texts[3].lower() in {"buy", "sell"}
        and importers._num(texts[4]) is not None
        and not importers._is_mt_time(texts[8])
        and not _MT5_VOLUME.match(texts[4])
    )


def _is_label_row(texts: tuple[str, ...]) -> bool:
    return any(text.endswith(":") and len(text) > 1 for text in texts) or any(
        re.match(r"^(Currency|Leverage):\s*\S", text) for text in texts
    )


def _is_footer(texts: tuple[str, ...]) -> bool:
    """A totals row: only numbers and blanks, at least two numbers."""
    numbers = [text for text in texts if text and importers._num(text) is not None]
    blanks = [text for text in texts if not text]
    return len(numbers) >= 2 and len(numbers) + len(blanks) == len(texts)


# ---------------------------------------------------------------------------
# Delimited families
# ---------------------------------------------------------------------------


def _from_delimited(
    header: list[str],
    body: list[list[str]],
    delimiter: str,
    source_format: str | None,
    family: str,
    encoding: str,
    endings: str,
    markers: int,
) -> RawTable:
    rows: list[RawRow] = []
    truncated = False
    header_texts = tuple(text.strip() for text in header)
    rows.append(
        RawRow(
            0, header_texts, tuple(RawCell(t) for t in header_texts), SECTION_CSV, KIND_HEADER, -1
        )
    )
    for offset, values in enumerate(body):
        if offset >= schema.MAX_ROWS:
            truncated = True
            break
        texts = tuple(str(value).strip() for value in values)
        rows.append(
            RawRow(offset + 1, texts, tuple(RawCell(t) for t in texts), SECTION_CSV, KIND_CSV, 0)
        )
    return RawTable(
        source_format=source_format or "",
        family=family,
        rows=tuple(rows),
        labels=(),
        generator="none",
        encoding=encoding,
        line_endings=endings,
        markers=markers,
        truncated=truncated,
        header=header_texts,
        delimiter=delimiter,
        header_texts=((0, header_texts),),
    )


# ---------------------------------------------------------------------------
# Column maps (pure functions of header texts, delegated to the importers)
# ---------------------------------------------------------------------------


def mt4_columns(table: RawTable, row: RawRow) -> dict[str, int]:
    """The closed-trades column map of the header above ``row``."""
    header = table.header_of(row)
    found = importers._mt4_statement_columns(list(header)) if header else None
    return found if found is not None else dict(importers._MT4_STATEMENT_COLUMNS)


def mt5_columns(table: RawTable, row: RawRow) -> dict[str, int]:
    """The deals column map of the header above ``row`` (visible cells).

    A workbook may store one blank trailing cell past the comment; the
    width that picks the layout ignores trailing blanks.
    """
    header = table.header_of(row)
    width = len(row.texts)
    while width > 0 and not row.texts[width - 1]:
        width -= 1
    return importers._mt5_column_map(list(header) if header else None, width)


def mt5_position_columns(table: RawTable, row: RawRow) -> dict[str, int]:
    index = {
        "open": 0,
        "position": 1,
        "symbol": 2,
        "type": 3,
        "volume": 4,
        "price": 5,
        "sl": 6,
        "tp": 7,
        "close": 8,
        "close_price": 9,
        "commission": 10,
        "swap": 11,
        "profit": 12,
    }
    header = table.header_of(row)
    if header and len(header) == len(row.texts):
        names = [text.lower() for text in header]
        if "position" in names and names.count("time") == 2 and names.count("price") == 2:
            times = [i for i, name in enumerate(names) if name == "time"]
            prices = [i for i, name in enumerate(names) if name == "price"]
            index.update(
                open=times[0],
                close=times[1],
                price=prices[0],
                close_price=prices[1],
                symbol=names.index("symbol"),
                type=names.index("type"),
                volume=names.index("volume"),
                commission=names.index("commission"),
                swap=names.index("swap"),
                profit=names.index("profit"),
                position=names.index("position"),
            )
    return index


# ---------------------------------------------------------------------------
# The account key (continuity only; never stored)
# ---------------------------------------------------------------------------


def account_key(data: bytes, source_format: str | None) -> str | None:
    """The account number printed in the file, for an in-memory comparison
    between two uploads of one continuous record. Callers hold it in a local
    variable and discard it; it is never written, hashed or logged."""
    raw = importers.unwrap(data)
    family = families.family_of(source_format)
    if family not in {families.MT4_STATEMENT, families.MT5_HISTORY, families.FXBLUE}:
        return None
    if importers._is_workbook(raw):
        sheets = importers.read_xlsx(raw)
        found = importers._mt5_workbook(sheets)
        if found is None:
            return None
        reader = found[1]
        title = reader.title
    else:
        text = importers.decode_text(raw)
        if family == families.FXBLUE:
            header, body, _ = importers._read_delimited(text)
            names = [name.strip().lower() for name in header]
            if "account" not in names:
                return None
            column = names.index("account")
            values = {row[column].strip() for row in body if len(row) > column and row[column]}
            return values.pop() if len(values) == 1 else None
        reader = importers._read_html(text)
        title = reader.title
    if family == families.MT4_STATEMENT:
        first = reader.rows[0].texts if reader.rows else []
        for text in first:
            found_number = re.match(r"^(?:Account|A/C No):\s*(\d+)", text)
            if found_number:
                return found_number.group(1)
        match = re.match(r"^Statement:\s*(\d+)", title)
        return match.group(1) if match else None
    labels = importers._mt5_labels(reader.rows)
    account = labels.get("Account", "")
    match = re.match(r"^(\d+)", account.strip())
    if match:
        return match.group(1)
    match = re.match(r"^(\d{3,}):", title)
    return match.group(1) if match else None
