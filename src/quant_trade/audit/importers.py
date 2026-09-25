"""Read the file a trader already has: platform reports and trade lists.

A retail trader does not have a ``timestamp,equity`` CSV. They have a
MetaTrader report, a TradingView "List of trades" or a NinjaTrader grid
export. This module turns one such file into what the audit consumes:
closed round trips (``ParsedTrades``) and a closed-trade balance curve
(``equity_csv``), plus the platform's own figures kept apart as metadata.

Rules the importers follow, so that the audit never reports more than the
file supports:

- Detection is by content, never by file name alone. Decoding tries the
  byte-order mark, then UTF-8, UTF-16 and cp1252 (MetaTrader 5 writes
  UTF-16 LE with a BOM; MetaTrader 4 writes the Windows code page).
- HTML is read with the standard library ``html.parser`` only, XLSX and
  SpreadsheetML with ``zipfile`` and ``xml.etree`` only. No script in an
  uploaded file is executed, no external entity is resolved (a document
  type declaration is refused), and a compressed workbook is refused when
  it would inflate past a fixed limit.
- The platform's money P&L is authoritative. ``Trade.pnl`` and
  ``client_pnl`` hold the reported gross profit (before commission and
  swap, when the file separates them; the net figure otherwise, with a
  warning). Platform volume is often in lots or contracts, so the contract
  size per symbol is inferred as the median of
  ``|profit| / (|exit - entry| * volume)`` and folded into
  ``Trade.quantity``, which keeps the audit's recomputed gross P&L equal to
  the platform's.
- Commission, swap and fee totals appear in ``fees`` only when the file
  states them, as signed effects on P&L (negative is a cost). A missing key
  means the file did not separate that cost.
- The balance curve is end-of-day, one row per business day (calendar days
  when trades close on a weekend), from the day before the first entry to
  the last exit, starting at the initial balance. Deposits and withdrawals
  after the start are removed from the returns (the curve is then a
  flow-adjusted index). It is built from closed trades, so it never shows
  floating drawdown, and every import says so.
- Nothing personal is copied into ``metadata``: no account number, no
  account holder name.
- Every repair or assumption is a warning; a file that cannot be read is a
  ``ReportFormatError`` (a ``ParseError``) that names what was expected, in
  English and Spanish.

Formats, pairing rules and samples come from
``docs/research/audit_iteration4/formats_metatrader.json`` and
``formats_other_platforms.json``.
"""

from __future__ import annotations

import csv
import io
import math
import re
import statistics
import zipfile
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree
from xml.parsers import expat

from quant_trade.audit.schema import (
    MAX_REPORT_BYTES,
    MAX_TRADES,
    ParsedTrades,
    ParseError,
    printed_step,
)
from quant_trade.core.models import Trade

MT5_TESTER_HTML = "mt5_tester_html"
MT5_HISTORY_HTML = "mt5_history_html"
MT4_TESTER_HTML = "mt4_tester_html"
MT4_STATEMENT_HTML = "mt4_statement_html"
TRADINGVIEW_CSV = "tradingview_csv"
TRADINGVIEW_XLSX = "tradingview_xlsx"
NINJATRADER_CSV = "ninjatrader_csv"
QUANTCONNECT_TRADES_CSV = "quantconnect_trades_csv"
BACKTESTINGPY_CSV = "backtestingpy_csv"
VECTORBT_CSV = "vectorbt_csv"
MYFXBOOK_CSV = "myfxbook_csv"
MQL5_SIGNAL_CSV = "mql5_signal_csv"
FXBLUE_CSV = "fxblue_csv"
MT5_OPTIMIZATION_XML = "mt5_optimization_xml"
MT5_TESTER_XLSX = "mt5_tester_xlsx"
MT5_HISTORY_XLSX = "mt5_history_xlsx"

#: Every format ``import_report`` turns into trades and a balance curve.
REPORT_FORMATS: tuple[str, ...] = (
    MT5_TESTER_HTML,
    MT5_TESTER_XLSX,
    MT5_HISTORY_HTML,
    MT5_HISTORY_XLSX,
    MT4_TESTER_HTML,
    MT4_STATEMENT_HTML,
    TRADINGVIEW_CSV,
    TRADINGVIEW_XLSX,
    NINJATRADER_CSV,
    QUANTCONNECT_TRADES_CSV,
    BACKTESTINGPY_CSV,
    VECTORBT_CSV,
    MYFXBOOK_CSV,
    MQL5_SIGNAL_CSV,
    FXBLUE_CSV,
)

#: Used when the file does not state a starting balance and none is supplied.
DEFAULT_INITIAL_BALANCE = 10_000.0

#: A workbook may not inflate past this many bytes, nor hold more members.
MAX_XLSX_UNCOMPRESSED_BYTES = 40_000_000
MAX_XLSX_MEMBERS = 500
#: Cells past this column are ignored (platform exports use a few dozen),
#: and a sheet may not spread past this many cells once its rows are laid
#: out: a single cell at column ZZZZZZ would otherwise ask for a row of
#: hundreds of millions of empty cells.
MAX_XLSX_COLUMNS = 256
MAX_XLSX_CELLS = 5_000_000

FLOATING_DRAWDOWN_WARNING = (
    "the balance curve is built from closed trades only; it does not show floating "
    "(open-trade) drawdown, so the real drawdown was at least as deep"
)
CONTRACT_SIZE_WARNING = "contract size inferred from reported profit"
CONVERSION_DRIFT_WARNING = (
    "money per point changes with the conversion to the account currency, so the "
    "size was inferred per trade from its reported profit"
)
NAIVE_TIME_WARNING = (
    "the file's times carry no timezone (platform or server time); they were read as UTC"
)

_EPS = 1e-9


class ReportFormatError(ParseError):
    """A platform file that cannot be imported, with a code and a Spanish message.

    ``str(error)`` is the English message, as for every ``ParseError``;
    ``message_es`` and ``localized("es")`` give the Spanish one.
    """

    def __init__(self, code: str, message: str, message_es: str) -> None:
        super().__init__(message, message_es=message_es, code=code)


@dataclass(frozen=True)
class ImportedReport:
    """One platform file, normalised for the audit.

    ``fees`` holds signed totals (negative is a cost) for the cost components
    the file itemises: ``commission``, ``swap`` and ``fee``. ``metadata``
    holds the platform's descriptive fields and its own (DECLARED) summary
    figures as text; it never holds an account number or a person's name.
    """

    source_format: str
    trades: ParsedTrades
    equity_csv: bytes
    initial_balance: float | None
    currency: str | None
    fees: dict[str, float]
    warnings: list[str]
    metadata: dict[str, str]
    #: The instrument of each trade in ``trades`` (empty string when unknown),
    #: so the grid and concurrency flags never mix symbols.
    symbols: list[str] = field(default_factory=list)
    #: Deposits (positive) and withdrawals (negative) the file lists, in time
    #: order, including those before the first trade and after the last.
    cash_flows: list[tuple[datetime, float]] = field(default_factory=list)


@dataclass(frozen=True)
class OptimizationSummary:
    """What an optimisation export proves: how many configurations were tried."""

    source_format: str
    passes: int
    parameters: list[str]
    warnings: list[str]
    #: Numeric cells of each pass (parameters and result columns), for the
    #: parameter-stability check; at most ``MAX_OPTIMIZATION_ROWS`` rows.
    table: list[dict[str, float]] = field(default_factory=list)
    #: What the export's title names ("MyEA EURUSD,H1 2024.01.01-2024.06.30"),
    #: so the upload can be checked against the report; None when not stated.
    expert: str | None = None
    symbol: str | None = None
    timeframe: str | None = None


# ---------------------------------------------------------------------------
# Decoding and cell values
# ---------------------------------------------------------------------------


def _check_size(data: bytes) -> None:
    if not data or not data.strip():
        raise ReportFormatError("empty_file", "the file is empty", "el archivo está vacío")
    if len(data) > MAX_REPORT_BYTES:
        raise ReportFormatError(
            "file_too_large",
            f"the file is {len(data):,} bytes; the limit is {MAX_REPORT_BYTES:,}",
            f"el archivo pesa {len(data):,} bytes; el límite es {MAX_REPORT_BYTES:,}",
        )


def _looks_utf16(data: bytes) -> str | None:
    sample = data[:4000]
    if len(sample) < 4:
        return None
    even_nuls = sample[0::2].count(0)
    odd_nuls = sample[1::2].count(0)
    half = len(sample) / 2
    if odd_nuls > 0.3 * half and even_nuls < 0.05 * half:
        return "utf-16-le"
    if even_nuls > 0.3 * half and odd_nuls < 0.05 * half:
        return "utf-16-be"
    return None


def decode_text(data: bytes) -> str:
    """Decode by BOM, then BOM-less UTF-16, then strict UTF-8, then cp1251
    when Russian report words appear, then cp1252.

    NUL characters are dropped: no report prints one, and PostgreSQL refuses
    to store text that holds one (a stray NUL in a name failed the upload)."""
    return _decode_text(data).replace("\x00", "")


def _decode_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    utf16 = _looks_utf16(data)
    if utf16 is not None:
        return data.decode(utf16, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if _looks_cp1251(data):
        return data.decode("cp1251", errors="replace")
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


#: Words a Russian MetaTrader report prints in its summary. A terminal set
#: to Russian writes the MT4 tester report in cp1251 without declaring it, and
#: read as cp1252 those words become unreadable symbols.
_CYRILLIC_MARKERS = ("Символ", "Период", "Начальный депозит", "Всего сделок", "Прибыль")


def _looks_cp1251(data: bytes) -> bool:
    """Whether BOM-less, non-UTF-8 bytes are Cyrillic text in cp1251."""
    try:
        text = data.decode("cp1251")
    except UnicodeDecodeError:
        return False
    return any(marker in text for marker in _CYRILLIC_MARKERS)


_NUMBER_NOISE = re.compile(r"[\s  $€£¥%]")


def _comma_is_decimal(text: str) -> bool:
    """Whether a number written for a ``.`` decimal plainly uses a decimal comma.

    Terminals set to Spanish, Portuguese or German may print ``1.234,56`` or
    ``1 234,56``. A comma after the last dot, or a single comma followed by
    other than three digits, cannot be a thousands separator. ``1,234`` stays
    one thousand two hundred thirty-four.
    """
    if "," not in text:
        return False
    if "." in text:
        return text.rfind(",") > text.rfind(".")
    return text.count(",") == 1 and re.search(r",\d{3}$", text) is None


def _num(value: Any, *, decimal: str = ".") -> float | None:
    """Read a platform number: spaces as thousands, ``(x)`` as negative, ``$``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = _NUMBER_NOISE.sub("", text)
    if decimal == "." and _comma_is_decimal(text):
        decimal = ","
    text = text.replace(".", "").replace(",", ".") if decimal == "," else text.replace(",", "")
    if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", text):
        return None
    number = float(text)
    if negative:
        number = -abs(number)
    return number if math.isfinite(number) else None


def _lead_num(value: str | None) -> float | None:
    """The first number of a summary cell such as ``7 025.85 (11.00%)``."""
    if value is None:
        return None
    return _num(value.split("(")[0])


def lead_number(value: str | None) -> float | None:
    """Public name of ``_lead_num`` for the report's reading check."""
    return _lead_num(value)


_YMD = re.compile(
    r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6})\d*)?)?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$"
)
_DMY = re.compile(
    r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6})\d*)?)?)?"
    r"\s*([AaPp][Mm])?$"
)


def _offset(text: str | None) -> timezone | None:
    if not text:
        return None
    if text == "Z":
        return UTC
    sign = 1 if text[0] == "+" else -1
    digits = text[1:].replace(":", "")
    return timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))


def _build_time(
    year: int,
    month: int,
    day: int,
    hour: str | None,
    minute: str | None,
    second: str | None,
    fraction: str | None,
    tz: timezone | None,
) -> datetime | None:
    try:
        moment = datetime(
            year,
            month,
            day,
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            int((fraction or "0").ljust(6, "0")),
        )
    except ValueError:
        return None
    if tz is None:
        return moment.replace(tzinfo=UTC)
    return moment.replace(tzinfo=tz).astimezone(UTC)


def _excel_serial(value: float) -> datetime | None:
    if not 1.0 <= value <= 2_958_465.0:
        return None
    moment = datetime(1899, 12, 30) + timedelta(days=value)
    micro = moment.microsecond
    moment = moment.replace(microsecond=0) + timedelta(seconds=round(micro / 1_000_000))
    return moment.replace(tzinfo=UTC)


@dataclass
class _TimeColumn:
    values: list[datetime | None]
    naive: bool


def _parse_times(values: Sequence[Any], *, serial_numbers: bool = False) -> _TimeColumn:
    """Parse one column of timestamps, deciding day-first versus month-first once."""
    texts = [
        None if value is None else value if isinstance(value, int | float) else str(value).strip()
        for value in values
    ]
    dayfirst: bool | None = None
    saw_dmy = False
    saw_ampm = False
    for text in texts:
        if not isinstance(text, str):
            continue
        match = _DMY.match(text)
        if match is None:
            continue
        saw_dmy = True
        first, second = int(match.group(1)), int(match.group(2))
        if match.group(8):
            saw_ampm = True
        if first > 12:
            dayfirst = True
            break
        if second > 12:
            dayfirst = False
            break
    if saw_dmy and dayfirst is None:
        if saw_ampm:
            dayfirst = False
        else:
            raise ReportFormatError(
                "ambiguous_dates",
                "the dates could be day/month or month/day; export them as YYYY-MM-DD "
                "(for example switch the platform to English) and upload again",
                "las fechas pueden ser día/mes o mes/día; expórtalas como AAAA-MM-DD "
                "(por ejemplo, con la plataforma en inglés) y vuelve a subir el archivo",
            )
    parsed: list[datetime | None] = []
    naive = False
    for text in texts:
        if text is None or text == "":
            parsed.append(None)
            continue
        if isinstance(text, int | float):
            parsed.append(_excel_serial(float(text)) if serial_numbers else None)
            naive = naive or serial_numbers
            continue
        ymd = _YMD.match(text)
        if ymd is not None:
            tz = _offset(ymd.group(8))
            naive = naive or tz is None
            parsed.append(
                _build_time(
                    int(ymd.group(1)),
                    int(ymd.group(2)),
                    int(ymd.group(3)),
                    ymd.group(4),
                    ymd.group(5),
                    ymd.group(6),
                    ymd.group(7),
                    tz,
                )
            )
            continue
        dmy = _DMY.match(text)
        if dmy is not None:
            first, second = int(dmy.group(1)), int(dmy.group(2))
            day, month = (first, second) if dayfirst else (second, first)
            hour = dmy.group(4)
            if hour is not None and dmy.group(8):
                value = int(hour) % 12 + (12 if dmy.group(8).lower() == "pm" else 0)
                hour = str(value)
            naive = True
            parsed.append(
                _build_time(
                    int(dmy.group(3)),
                    month,
                    day,
                    hour,
                    dmy.group(5),
                    dmy.group(6),
                    dmy.group(7),
                    None,
                )
            )
            continue
        if serial_numbers:
            number = _num(text)
            if number is not None:
                naive = True
                parsed.append(_excel_serial(number))
                continue
        parsed.append(None)
    return _TimeColumn(parsed, naive)


def _one_time(text: str | None) -> datetime | None:
    if not text:
        return None
    return _parse_times([text]).values[0]


def _clip(text: str, limit: int = 200) -> str:
    return " ".join(text.split())[:limit]


# ---------------------------------------------------------------------------
# Normalised intermediate shapes
# ---------------------------------------------------------------------------


@dataclass
class _Trip:
    """One closed round trip in platform units, before contract-size inference."""

    symbol: str
    side: str
    volume: float
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    gross: float
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0

    @property
    def net(self) -> float:
        return self.gross + self.commission + self.swap + self.fee


@dataclass
class _Cash:
    """One change of the account balance, in file order."""

    time: datetime
    amount: float
    is_flow: bool
    reported_balance: float | None = None


@dataclass
class _Draft:
    """Everything a format parser found, before the shared assembly step."""

    source_format: str
    trips: list[_Trip]
    cash: list[_Cash] | None = None
    initial_balance: float | None = None
    initial_note: str = ""
    currency: str | None = None
    itemised: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    invalid_rows: int = 0
    naive_times: bool = True


# ---------------------------------------------------------------------------
# HTML tables
# ---------------------------------------------------------------------------


@dataclass
class _Cell:
    text: str
    attrs: dict[str, str]

    @property
    def hidden(self) -> bool:
        return "hidden" in self.attrs.get("class", "").split()


@dataclass
class _Row:
    attrs: dict[str, str]
    cells: list[_Cell]

    @property
    def visible(self) -> list[_Cell]:
        return [cell for cell in self.cells if not cell.hidden]

    @property
    def texts(self) -> list[str]:
        return [cell.text for cell in self.visible]

    @property
    def is_mt_header(self) -> bool:
        return self.attrs.get("bgcolor", "").lower() in {"#e5f0fc", "#c0c0c0"}


class _TableReader(HTMLParser):
    """Collect every table row of a document, tolerating sloppy markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_Row] = []
        self.meta: dict[str, str] = {}
        self.title = ""
        self._row: _Row | None = None
        self._cell: _Cell | None = None
        self._buffer: list[str] = []
        self._in_title = False
        self._skip = 0

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._cell.text = " ".join("".join(self._buffer).replace("\xa0", " ").split())
            self._row.cells.append(self._cell)
        self._cell = None
        self._buffer = []

    def _close_row(self) -> None:
        self._close_cell()
        if self._row is not None and self._row.cells:
            self.rows.append(self._row)
        self._row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag == "tr":
            self._close_row()
            self._row = _Row(values, [])
        elif tag in {"td", "th"}:
            self._close_cell()
            if self._row is None:
                self._row = _Row({}, [])
            self._cell = _Cell("", values)
        elif tag == "br" and self._cell is not None:
            self._buffer.append(" ")
        elif tag == "meta" and "name" in values:
            self.meta[values["name"].lower()] = values.get("content", "")
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
        elif tag in {"td", "th"}:
            self._close_cell()
        elif tag in {"tr", "table"}:
            self._close_row()
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
        elif self._cell is not None:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._close_row()


def _read_html(text: str) -> _TableReader:
    reader = _TableReader()
    reader.feed(text)
    reader.close()
    return reader


def _labels(rows: Iterable[_Row]) -> dict[str, str]:
    """Label/value pairs: a cell ending in ``:`` followed by its value cell.

    ``Currency: USD`` written inside one cell (the MT4 statement) is also
    read. The first occurrence of a label wins.
    """
    found: dict[str, str] = {}
    for row in rows:
        texts = row.texts
        for index, text in enumerate(texts):
            if text.endswith(":") and len(text) > 1:
                if index + 1 < len(texts) and not texts[index + 1].endswith(":"):
                    found.setdefault(text[:-1].strip(), texts[index + 1])
            else:
                inline = re.match(r"^(Currency|Leverage):\s*(\S.*)$", text)
                if inline is not None:
                    found.setdefault(inline.group(1), inline.group(2))
    return found


_MT5_DIRECTIONS = {"in", "out", "in/out", "out by"}
_MT5_TESTER_COLUMNS = (
    "time",
    "deal",
    "symbol",
    "type",
    "direction",
    "volume",
    "price",
    "order",
    "commission",
    "swap",
    "profit",
    "balance",
    "comment",
)
_MT5_HISTORY_COLUMNS = (
    "time",
    "deal",
    "symbol",
    "type",
    "direction",
    "volume",
    "price",
    "order",
    "commission",
    "fee",
    "swap",
    "profit",
    "balance",
    "comment",
)
_MT_TIME = re.compile(r"^\d{4}\.\d{2}\.\d{2}( \d{2}:\d{2}(:\d{2})?)?$")


def _is_mt_time(text: str) -> bool:
    return bool(_MT_TIME.match(text))


def _is_mt5_deal(texts: list[str]) -> bool:
    return (
        len(texts) >= 13
        and _is_mt_time(texts[0])
        and (texts[3].lower() == "balance" or texts[4].lower() in _MT5_DIRECTIONS)
    )


def _is_mt5_position(texts: list[str]) -> bool:
    return (
        len(texts) >= 13
        and _is_mt_time(texts[0])
        and _is_mt_time(texts[8])
        and texts[3].lower() in {"buy", "sell"}
        and _num(texts[4]) is not None
        and _num(texts[9]) is not None
    )


_MT4_TYPES = {
    "buy",
    "sell",
    "modify",
    "close",
    "t/p",
    "s/l",
    "close at stop",
    "close by",
    "buy limit",
    "sell limit",
    "buy stop",
    "sell stop",
    "delete",
    "swap close",
    "swap open",
}
#: "swap close" / "swap open": some brokers close every position at rollover
#: and reopen it under a new ticket; MetaTrader counts the close as a trade.
_MT4_CLOSES = {"close", "t/p", "s/l", "close at stop", "close by", "swap close"}


def _is_mt4_tester_row(texts: list[str]) -> bool:
    return (
        len(texts) in {9, 10}
        and texts[0].isdigit()
        and _is_mt_time(texts[1])
        and texts[2].lower() in _MT4_TYPES
    )


#: Column positions of the MetaTrader 4 statement's closed trades, as build
#: 600+ writes them (with "Taxes"). Other layouts are read from their header.
_MT4_STATEMENT_COLUMNS = {
    "open_time": 1,
    "type": 2,
    "size": 3,
    "symbol": 4,
    "open_price": 5,
    "close_time": 8,
    "close_price": 9,
    "commission": 10,
    "taxes": 11,
    "swap": 12,
    "profit": 13,
}
_MT4_STATEMENT_NAMES = {
    "size": "size",
    "lots": "size",
    "item": "symbol",
    "symbol": "symbol",
    "commission": "commission",
    "commis": "commission",
    "taxes": "taxes",
    "swap": "swap",
    "profit": "profit",
    "trade p/l": "profit",
}


def _mt4_statement_columns(texts: list[str]) -> dict[str, int] | None:
    """Map a statement's "Closed Transactions" header, or ``None`` if it is not one.

    Builds before 600 have no "Taxes" column (13 columns) and some brokers
    add a row number and a comment (15 columns), so positions come from
    the header whenever there is one.
    """
    names = [text.strip().lower() for text in texts]
    if "ticket" not in names or "open time" not in names or "close time" not in names:
        return None
    columns: dict[str, int] = {
        "open_time": names.index("open time"),
        "close_time": names.index("close time"),
    }
    if "type" in names:
        columns["type"] = names.index("type")
    for index, name in enumerate(names):
        if name == "price":
            key = "open_price" if index < columns["close_time"] else "close_price"
            columns.setdefault(key, index)
        elif name in _MT4_STATEMENT_NAMES:
            columns.setdefault(_MT4_STATEMENT_NAMES[name], index)
    needed = {"type", "size", "symbol", "open_price", "close_price", "profit"}
    return columns if needed <= columns.keys() else None


def _is_mt4_statement_trade(
    texts: list[str], columns: dict[str, int] = _MT4_STATEMENT_COLUMNS
) -> bool:
    return (
        len(texts) > max(columns.values())
        and _is_mt_time(texts[columns["open_time"]])
        and texts[columns["type"]].lower() in {"buy", "sell"}
        and _is_mt_time(texts[columns["close_time"]])
    )


def _mt4_statement_rows(reader: _TableReader) -> Iterable[tuple[list[str], dict[str, int]]]:
    """Every row with the column map of the closest header above it."""
    columns = _MT4_STATEMENT_COLUMNS
    for row in reader.rows:
        found = _mt4_statement_columns(row.texts)
        if found is not None:
            columns = found
            continue
        yield row.texts, columns


def _html_format(reader: _TableReader) -> str | None:
    deals = [row.texts for row in reader.rows if _is_mt5_deal(row.texts)]
    positions = any(_is_mt5_position(row.texts) for row in reader.rows)
    title = reader.title.lower()
    generator = reader.meta.get("generator", "").lower()
    if deals or positions:
        if "trade history report" in title or generator == "client terminal" or positions:
            return MT5_HISTORY_HTML
        if "strategy tester" in title or generator == "strategy tester":
            return MT5_TESTER_HTML
        return MT5_HISTORY_HTML if len(deals[0]) >= 14 else MT5_TESTER_HTML
    if any(_is_mt4_tester_row(row.texts) for row in reader.rows):
        return MT4_TESTER_HTML
    if any(
        _is_mt4_statement_trade(texts, columns) for texts, columns in _mt4_statement_rows(reader)
    ):
        return MT4_STATEMENT_HTML
    return None


# ---------------------------------------------------------------------------
# MetaTrader 5
# ---------------------------------------------------------------------------


@dataclass
class _Deal:
    time: datetime
    symbol: str
    type: str
    direction: str
    volume: float
    price: float
    commission: float
    fee: float
    swap: float
    profit: float
    balance: float | None
    comment: str

    @property
    def amount(self) -> float:
        return self.commission + self.fee + self.swap + self.profit


#: Deals-table headers seen in real exports that are not the English names:
#: build 1940 wrote "Trade" and "Profit Column"; a Russian terminal writes Russian.
_MT5_DEAL_HEADER_ALIASES = {
    "trade": "deal",
    "profit column": "profit",
    "время": "time",
    "сделка": "deal",
    "символ": "symbol",
    "тип": "type",
    "направление": "direction",
    "объем": "volume",
    "объём": "volume",
    "цена": "price",
    "ордер": "order",
    "комиссия": "commission",
    "сбор": "fee",
    "своп": "swap",
    "прибыль": "profit",
    "баланс": "balance",
    "комментарий": "comment",
}
_MT5_DEAL_REQUIRED = {"time", "type", "direction", "volume", "price", "profit", "balance"}


def _mt5_column_map(header: list[str] | None, width: int) -> dict[str, int]:
    if header is not None:
        names = [text.strip().lower() for text in header]
        names = [_MT5_DEAL_HEADER_ALIASES.get(name, name) for name in names]
        mapped = {name: index for index, name in enumerate(names) if name}
        if mapped.keys() >= _MT5_DEAL_REQUIRED:
            return mapped
    columns = _MT5_HISTORY_COLUMNS if width >= 14 else _MT5_TESTER_COLUMNS
    return {name: index for index, name in enumerate(columns)}


def _mt5_deals(reader: _TableReader) -> tuple[list[_Deal], int]:
    deals: list[_Deal] = []
    invalid = 0
    header: list[str] | None = None
    for row in reader.rows:
        texts = row.texts
        if row.is_mt_header:
            header = texts
            continue
        if not _is_mt5_deal(texts):
            continue
        columns = _mt5_column_map(header, len(texts))

        def cell(name: str, texts: list[str] = texts, columns: dict[str, int] = columns) -> str:
            index = columns.get(name)
            return texts[index] if index is not None and index < len(texts) else ""

        moment = _one_time(cell("time"))
        kind = cell("type").lower()
        direction = cell("direction").lower()
        values = {name: _num(cell(name)) for name in ("commission", "fee", "swap", "profit")}
        volume = _num(cell("volume"))
        price = _num(cell("price"))
        is_trade = kind in {"buy", "sell"}
        if moment is None or (is_trade and (volume is None or price is None)):
            invalid += 1
            continue
        deals.append(
            _Deal(
                time=moment,
                symbol=cell("symbol").upper(),
                type=kind,
                direction=direction,
                volume=volume or 0.0,
                price=price or 0.0,
                commission=values["commission"] or 0.0,
                fee=values["fee"] or 0.0,
                swap=values["swap"] or 0.0,
                profit=values["profit"] or 0.0,
                balance=_num(cell("balance")),
                comment=cell("comment"),
            )
        )
    return deals, invalid


@dataclass
class _Lot:
    side: str
    volume: float
    price: float
    time: datetime
    commission: float
    fee: float
    swap: float


@dataclass
class _Fifo:
    """FIFO pairing of MT5 deals (tester reports and history fallback)."""

    trips: list[_Trip] = field(default_factory=list)
    lots: dict[str, list[_Lot]] = field(default_factory=dict)
    hedging: bool = False
    netting: bool = False
    unmatched_closes: int = 0
    closing_deals: int = 0
    forced_closes: int = 0
    #: Contract size per symbol from a first pass. With it, a hedging close
    #: picks the open entry of its own volume whose price explains the
    #: deal's profit, instead of the oldest one (see ``_pair_mt5_deals``).
    sizes: dict[str, float] = field(default_factory=dict)
    #: Closes that could belong to more than one open entry of their volume.
    ambiguous_closes: int = 0

    def _order(self, deal: _Deal, side: str, volume: float, profit: float) -> list[_Lot]:
        queue = self.lots.get(deal.symbol, [])
        size = self.sizes.get(deal.symbol)
        same = [lot for lot in queue if lot.side == side and lot.volume > _EPS]
        exact = [lot for lot in same if abs(lot.volume - volume) <= 1e-9 * max(1.0, volume)]
        if len(same) >= 2 and exact and (len(exact) > 1 or exact[0] is not same[0]):
            self.ambiguous_closes += 1
        if size is None or len(same) < 2 or not exact:
            return queue
        direction = 1.0 if side == "long" else -1.0

        def error(lot: _Lot) -> float:
            return abs((deal.price - lot.price) * direction * volume * size - profit)

        best = min(exact, key=error)
        if error(best) < error(same[0]) - 1e-9 * max(1.0, abs(profit)):
            return [best, *(lot for lot in queue if lot is not best)]
        return queue

    def open(self, deal: _Deal, side: str, volume: float, share: float) -> None:
        queue = self.lots.setdefault(deal.symbol, [])
        if any(lot.side != side for lot in queue):
            self.hedging = True
        queue.append(
            _Lot(
                side,
                volume,
                deal.price,
                deal.time,
                deal.commission * share,
                deal.fee * share,
                deal.swap * share,
            )
        )

    def open_volume(self, symbol: str, side: str) -> float:
        return sum(lot.volume for lot in self.lots.get(symbol, []) if lot.side == side)

    def close(
        self, deal: _Deal, side: str, volume: float, cost_share: float, profit: float
    ) -> None:
        queue = self.lots.get(deal.symbol, [])
        slices: list[tuple[_Lot, float, float, float, float]] = []
        remaining = volume
        for lot in self._order(deal, side, volume, profit):
            if remaining <= _EPS:
                break
            if lot.side != side or lot.volume <= _EPS:
                continue
            take = min(lot.volume, remaining)
            fraction = take / lot.volume
            entry_costs = (lot.commission * fraction, lot.fee * fraction, lot.swap * fraction)
            lot.commission -= entry_costs[0]
            lot.fee -= entry_costs[1]
            lot.swap -= entry_costs[2]
            lot.volume -= take
            remaining -= take
            slices.append((lot, take, *entry_costs))
        self.lots[deal.symbol] = [lot for lot in queue if lot.volume > _EPS]
        if remaining > _EPS:
            self.unmatched_closes += 1
        if not slices:
            return
        # One closing deal is one trade, as the platform counts it ("Total
        # Trades"), even when it closes several entries: the entry is their
        # volume-weighted price and the earliest entry time.
        taken = sum(take for _, take, *_ in slices)
        share = taken / volume * cost_share if volume > 0 else 0.0
        self.trips.append(
            _Trip(
                symbol=deal.symbol,
                side=side,
                volume=taken,
                entry_time=min(lot.time for lot, *_ in slices),
                exit_time=deal.time,
                entry_price=sum(lot.price * take for lot, take, *_ in slices) / taken,
                exit_price=deal.price,
                gross=profit,
                commission=sum(item[2] for item in slices) + deal.commission * share,
                fee=sum(item[3] for item in slices) + deal.fee * share,
                swap=sum(item[4] for item in slices) + deal.swap * share,
            )
        )

    def apply(self, deal: _Deal) -> None:
        fill_side = "long" if deal.type == "buy" else "short"
        opposite = "short" if fill_side == "long" else "long"
        if deal.comment.lower().startswith("end of test"):
            self.forced_closes += 1
        if deal.direction == "in":
            self.open(deal, fill_side, deal.volume, 1.0)
        elif deal.direction in {"out", "out by"}:
            self.closing_deals += 1
            if deal.direction == "out by":
                self.hedging = True
            self.close(deal, opposite, deal.volume, 1.0, deal.profit)
        elif deal.direction == "in/out":
            self.closing_deals += 1
            self.netting = True
            existing = min(self.open_volume(deal.symbol, opposite), deal.volume)
            close_share = existing / deal.volume if deal.volume > 0 else 0.0
            if existing > _EPS:
                self.close(deal, opposite, existing, close_share, deal.profit)
            rest = deal.volume - existing
            if rest > _EPS:
                self.open(deal, fill_side, rest, 1.0 - close_share)

    def leftover(self) -> int:
        return sum(1 for queue in self.lots.values() for lot in queue if lot.volume > _EPS)


def _pair_mt5_deals(deals: list[_Deal]) -> _Fifo:
    """Pair trade deals into round trips.

    A netting account pairs exactly. A hedging account's report does not
    say which entry a closing deal closes, so a first-in first-out pass
    estimates each symbol's contract size, and a second pass lets every
    close take the open entry of its own volume whose price explains the
    deal's profit best (first in, first out among equals).
    """
    fifo = _Fifo()
    for deal in deals:
        fifo.apply(deal)
    if not fifo.ambiguous_closes:
        return fifo
    sizes = _contract_sizes(fifo.trips)
    rematched = _Fifo(sizes={trip.symbol: sizes[trip.symbol] for trip in fifo.trips})
    for deal in deals:
        rematched.apply(deal)
    rematched.hedging = rematched.hedging or fifo.hedging
    return rematched


def _fifo_warnings(fifo: _Fifo) -> list[str]:
    warnings: list[str] = []
    if fifo.hedging or fifo.ambiguous_closes:
        warnings.append(
            "hedging account: the report does not say which entry each close belongs to; "
            "closes were matched to the open entry whose price explains their profit, "
            "else first-in first-out, so per-trade entry price and holding time are "
            "approximate (money results stay exact)"
        )
    if fifo.unmatched_closes:
        warnings.append(
            f"{fifo.unmatched_closes} closing deal(s) had no matching open volume; their "
            "money is in the balance but not in the trade list"
        )
    if fifo.leftover():
        warnings.append(
            f"{fifo.leftover()} position(s) still open at the end of the report; excluded "
            "from the closed trades"
        )
    if fifo.forced_closes:
        warnings.append(f"{fifo.forced_closes} deal(s) closed by the tester at the end of the test")
    return warnings


def _deal_cash(deals: list[_Deal]) -> list[_Cash]:
    return [
        _Cash(deal.time, deal.amount, deal.type not in {"buy", "sell"}, deal.balance)
        for deal in deals
    ]


def _compare(
    warnings: list[str], what: str, declared: float | None, measured: float, tolerance: float
) -> None:
    if declared is not None and abs(declared - measured) > tolerance:
        warnings.append(
            f"{what}: the report states {declared:,.2f} but the rows add up to {measured:,.2f}"
        )


def _period_dates(value: str) -> tuple[str, str] | None:
    found = re.findall(r"\d{4}\.\d{2}\.\d{2}", value)
    if len(found) >= 2:
        return found[-2].replace(".", "-"), found[-1].replace(".", "-")
    return None


#: Summary labels by the English name the parsers use. Older builds and other
#: terminal languages print other words for the same figure: the Russian
#: names come from a real Russian report, the Spanish ones from the Spanish
#: MetaTrader 5 help ("Informe de simulación") and from real Spanish,
#: Italian, Portuguese, Chinese and Czech reports
#: (docs/research/audit_iteration4/mt_languages_check.md), matched without case.
_MT5_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "Expert": ("Советник", "Asesor", "Asesor Experto", "Experto", "Expert Advisor (Robô)", "专家"),
    "Symbol": ("Символ", "Símbolo", "Simbolo", "Ativo", "交易品种"),
    "Period": ("Период", "Período", "Periodo", "Periodo", "期间"),
    "Company": (
        "Broker",
        "Брокер",
        "Компания",
        "Compañía",
        "Empresa",
        "Corredor",
        "Società",
        "公司",
        "交易商",
        "Firma",
    ),
    "Currency": ("Валюта", "Divisa", "Moneda", "Valuta", "Moeda", "货币"),
    "Initial Deposit": ("Начальный депозит", "Depósito inicial", "Deposito Iniziale", "初始入金"),
    "Leverage": ("Плечо", "Apalancamiento", "Leva", "Alavancagem", "杠杆"),
    "History Quality": (
        "Качество истории",
        "Calidad del historial",
        "Qualità dello Storico",
        "Qualidade do histórico",
        "质量历史",
    ),
    "Total Net Profit": (
        "Net profit",
        "Чистая прибыль",
        "Beneficio Neto",
        "Profitto Totale Netto",
        "Lucro Líquido Total",
        "总净盈利",
        "總淨盈利",
        "Čistý zisk celkem",
    ),
    "Total Trades": (
        "Всего трейдов",
        "Total de Trades",
        "Total de operaciones ejecutadas",
        "Numero di Operazioni di Trading Totali",
        "Total de Negociações",
        "交易总计",
        "交易總計",
        "Všechny transakce",
    ),
    "Total Deals": (
        "Всего сделок",
        "Total de transacciones",
        "Affari Totali",
        "Ofertas Total",
        "总成交",
    ),
    "Balance Drawdown Maximal": (
        "Максимальная просадка по балансу",
        "Reducción Máxima del Saldo",
        "Reducción máxima del balance",
        "Bilancio Drawdown Massimo",
        "Rebaixamento Máximo do Saldo",
        "最大结余亏损",
        "最大本日餘額虧損",
        "Maximální ztráta na zůstatku od lokálního maxima",
    ),
    "Equity Drawdown Maximal": (
        "Максимальная просадка по средствам",
        "Reducción máxima del capital",
        "Reducción máxima de la equidad",
        "Equità Drawdown Massima",
        "Rebaixamento Máximo do Capital Líquido",
        "最大净值亏损",
    ),
    "Equity Drawdown Relative": (
        "Relative equity drawdown",
        "Относительная просадка по средствам",
        "Reducción relativa del capital",
        "Reducción relativa de la equidad",
        "Equità Drawdown Relativa",
        "Rebaixamento Relativo do Capital Líquido",
        "相对净值亏损",
    ),
    "Sharpe Ratio": (
        "Коэффициент Шарпа",
        "Ratio de Sharpe",
        "El Ratio de Sharpe",
        "Indice di Sharpe",
        "Índice de Sharpe",
        "夏普比率",
        "Sharpeho poměr",
    ),
    "Profit Factor": (
        "Прибыльность",
        "Factor de Rentabilidad",
        "Factor de Beneficio",
        "Fattore di Profitto",
        "Fator de Lucro",
        "盈利因子",
        "Ukazatel zisku",
    ),
    "Account": ("Cuenta", "Conta", "Conto", "Счет", "帳戶", "账户", "Účet"),
    "Date": ("Fecha", "Data", "Дата", "日期", "Datum"),
    "Equity": ("權益數", "Majetek"),
    "Floating P/L": ("浮動 P/L", "Pohyblivý P/L"),
}


def _mt5_labels(rows: Iterable[_Row]) -> dict[str, str]:
    """``_labels`` plus the English name for every known alias found."""
    found = _labels(rows)
    lowered = {key.lower(): value for key, value in found.items()}
    for english, aliases in _MT5_LABEL_ALIASES.items():
        if english in found:
            continue
        for alias in aliases:
            if alias.lower() in lowered:
                found[english] = lowered[alias.lower()]
                break
    return found


def _parse_mt5_tester(reader: _TableReader) -> _Draft:
    deals, invalid = _mt5_deals(reader)
    labels = _mt5_labels(reader.rows)
    draft = _Draft(MT5_TESTER_HTML, [], invalid_rows=invalid)
    draft.itemised = {"commission", "swap"}
    fifo = _pair_mt5_deals([deal for deal in deals if deal.type in {"buy", "sell"}])
    draft.trips = fifo.trips
    draft.cash = _deal_cash(deals)
    draft.warnings.extend(_fifo_warnings(fifo))
    deposit = _lead_num(labels.get("Initial Deposit"))
    if deposit is not None:
        draft.initial_balance = deposit
        draft.initial_note = "Initial Deposit"
    draft.currency = labels.get("Currency") or None
    meta = draft.metadata
    for label, key in (
        ("Expert", "strategy"),
        ("Symbol", "symbol"),
        ("Period", "period"),
        ("Company", "broker"),
        ("Leverage", "leverage"),
        ("History Quality", "history_quality"),
        ("Total Net Profit", "declared_total_net_profit"),
        ("Total Trades", "declared_total_trades"),
        ("Total Deals", "declared_total_deals"),
        ("Balance Drawdown Maximal", "declared_balance_drawdown_maximal"),
        ("Equity Drawdown Maximal", "declared_equity_drawdown_maximal"),
        ("Equity Drawdown Relative", "declared_equity_drawdown_relative"),
        ("Sharpe Ratio", "declared_sharpe_ratio"),
        ("Profit Factor", "declared_profit_factor"),
    ):
        if labels.get(label):
            meta[key] = _clip(labels[label])
    if "Period" in labels:
        window = _period_dates(labels["Period"])
        if window is not None:
            meta["start"], meta["end"] = window
    inputs = _mt5_inputs(reader.rows)
    if inputs:
        meta["inputs"] = str(len(inputs))
        meta["input_names"] = _clip(", ".join(inputs), 500)
        values = _mt5_input_values(reader.rows)
        if values:
            meta["input_values"] = _clip("; ".join(values), 2000)
    trades_declared = _lead_num(labels.get("Total Trades"))
    _compare(
        draft.warnings,
        "closing deals vs Total Trades",
        trades_declared,
        float(fifo.closing_deals),
        0.5,
    )
    flows_after_start = [deal for deal in deals if deal.type not in {"buy", "sell"}][1:]
    if deals and deals[-1].balance is not None and deposit is not None and not flows_after_start:
        _compare(
            draft.warnings,
            "net profit",
            _lead_num(labels.get("Total Net Profit")),
            deals[-1].balance - deposit,
            0.011,
        )
        _compare(
            draft.warnings,
            "balance drawdown maximal",
            _lead_num(labels.get("Balance Drawdown Maximal")),
            _deal_balance_drawdown(deals),
            0.011,
        )
    return draft


def _deal_balance_drawdown(deals: list[_Deal]) -> float:
    """Deepest fall of the report's own Balance column, deal by deal, in money.

    This is how the tester computes "Balance Drawdown Maximal", so the two
    agree on an untouched report (checked on 13 real reports).
    """
    peak: float | None = None
    deepest = 0.0
    for deal in deals:
        if deal.balance is None:
            continue
        peak = deal.balance if peak is None else max(peak, deal.balance)
        deepest = max(deepest, peak - deal.balance)
    return deepest


def _mt5_inputs(rows: list[_Row]) -> list[str]:
    names: list[str] = []
    collecting = False
    for row in rows:
        texts = row.texts
        if len(texts) < 2:
            if collecting:
                break
            continue
        if texts[0] == "Inputs:":
            collecting = True
        elif collecting and texts[0] != "":
            break
        if collecting and "=" in texts[1]:
            names.append(texts[1].split("=", 1)[0].strip())
    return names


def _mt5_input_values(rows: list[_Row]) -> list[str]:
    """``name=value`` of each tester input, in the report's order."""
    pairs: list[str] = []
    collecting = False
    for row in rows:
        texts = row.texts
        if len(texts) < 2:
            if collecting:
                break
            continue
        if texts[0] == "Inputs:":
            collecting = True
        elif collecting and texts[0] != "":
            break
        if collecting and "=" in texts[1]:
            name, value = texts[1].split("=", 1)
            pairs.append(f"{name.strip()}={value.strip()}")
    return pairs


def _mt5_positions(reader: _TableReader) -> tuple[list[_Trip], int]:
    trips: list[_Trip] = []
    invalid = 0
    header: list[str] | None = None
    for row in reader.rows:
        texts = row.texts
        if row.is_mt_header:
            header = texts
            continue
        if not _is_mt5_position(texts):
            continue
        index = {
            "open": 0,
            "symbol": 2,
            "type": 3,
            "volume": 4,
            "price": 5,
            "close": 8,
            "close_price": 9,
            "commission": 10,
            "swap": 11,
            "profit": 12,
        }
        if header is not None and len(header) == len(texts):
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
                )
        entry_time = _one_time(texts[index["open"]])
        exit_time = _one_time(texts[index["close"]])
        volume = _num(texts[index["volume"]])
        entry_price = _num(texts[index["price"]])
        exit_price = _num(texts[index["close_price"]])
        profit = _num(texts[index["profit"]])
        if None in (entry_time, exit_time, volume, entry_price, exit_price, profit):
            invalid += 1
            continue
        assert entry_time is not None and exit_time is not None
        trips.append(
            _Trip(
                symbol=texts[index["symbol"]].upper(),
                side="long" if texts[index["type"]].lower() == "buy" else "short",
                volume=volume or 0.0,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price or 0.0,
                exit_price=exit_price or 0.0,
                gross=profit or 0.0,
                commission=_num(texts[index["commission"]]) or 0.0,
                swap=_num(texts[index["swap"]]) or 0.0,
            )
        )
    return trips, invalid


def _parse_mt5_history(reader: _TableReader) -> _Draft:
    deals, invalid_deals = _mt5_deals(reader)
    positions, invalid_positions = _mt5_positions(reader)
    labels = _mt5_labels(reader.rows)
    draft = _Draft(MT5_HISTORY_HTML, [], invalid_rows=invalid_deals + invalid_positions)
    draft.itemised = {"commission", "swap"}
    trade_deals = [deal for deal in deals if deal.type in {"buy", "sell"}]
    if positions:
        draft.trips = positions
        fee_total = sum(deal.fee for deal in trade_deals)
        if abs(fee_total) > _EPS:
            draft.warnings.append(
                f"the Deals table charges {fee_total:,.2f} in fees that the Positions table "
                "does not itemise per trade; they are in the balance curve only"
            )
        # MetaTrader counts every closing deal as a trade, so a position
        # closed in two parts is one row here and two in "Total Trades".
        closing = sum(1 for deal in trade_deals if deal.direction in {"out", "out_by"})
        if closing:
            draft.metadata["closing_deals"] = str(closing)
        open_positions = _count_opened_not_closed(trade_deals, positions)
        if open_positions:
            draft.warnings.append(
                f"{open_positions} position(s) opened in the report were not closed; excluded"
            )
    else:
        fifo = _pair_mt5_deals(trade_deals)
        draft.trips = fifo.trips
        draft.itemised.add("fee")
        draft.warnings.extend(_fifo_warnings(fifo))
    draft.cash = _deal_cash(deals)
    if deals and deals[0].type in {"buy", "sell"}:
        first = deals[0]
        if first.balance is not None:
            draft.initial_balance = first.balance - first.amount
            draft.initial_note = "first Balance row minus its own amount"
    account = labels.get("Account", "")
    inside = re.search(r"\(([^)]*)\)", account)
    if inside is not None:
        parts = [part.strip() for part in inside.group(1).split(",")]
        # Newer terminals put the leverage after the currency: (USD, 1:500, ...).
        leverage = [part for part in parts if re.fullmatch(r"1:\d+", part)]
        if leverage:
            draft.metadata["leverage"] = leverage[0]
            parts = [part for part in parts if part not in leverage]
        if parts and re.fullmatch(r"[A-Z]{3,4}", parts[0]):
            draft.currency = parts[0]
        if len(parts) >= 2:
            draft.metadata["server"] = _clip(parts[1])
        if len(parts) >= 3:
            draft.metadata["account_type"] = _clip(parts[2])
        if len(parts) >= 4:
            draft.metadata["margin_mode"] = _clip(parts[3])
    for label, key in (
        ("Company", "broker"),
        ("Date", "report_date"),
        ("Total Net Profit", "declared_total_net_profit"),
        ("Total Trades", "declared_total_trades"),
        ("Equity", "declared_final_equity"),
        ("Floating P/L", "declared_floating_pnl"),
    ):
        if labels.get(label):
            draft.metadata[key] = _clip(labels[label])
    measured = sum(trip.net for trip in draft.trips)
    _compare(
        draft.warnings,
        "net profit of closed positions",
        _lead_num(labels.get("Total Net Profit")),
        measured,
        0.011 * max(1, len(draft.trips)),
    )
    return draft


def _count_opened_not_closed(deals: list[_Deal], positions: list[_Trip]) -> int:
    opened = sum(1 for deal in deals if deal.direction == "in")
    return max(0, opened - len(positions))


# ---------------------------------------------------------------------------
# MetaTrader 4
# ---------------------------------------------------------------------------

_MT4_LABELS = {
    "Symbol": "symbol",
    "Period": "period",
    "Model": "model",
    "Parameters": "parameters",
    "Modelling quality": "modelling_quality",
    "Mismatched charts errors": "mismatched_chart_errors",
    "Spread": "spread",
    "Initial deposit": "initial_deposit",
    "Total net profit": "declared_total_net_profit",
    "Total trades": "declared_total_trades",
    "Maximal drawdown": "declared_maximal_drawdown",
    "Relative drawdown": "declared_relative_drawdown",
    "Profit factor": "declared_profit_factor",
}


#: The same summary labels as terminals set to other languages print them,
#: from real public reports (docs/research/audit_iteration4/mt_languages_check.md).
_MT4_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "Symbol": ("Символ", "Ativo"),
    "Period": ("Период", "Período"),
    "Model": ("Модель", "Modelo"),
    "Parameters": ("Параметры", "Parâmetros"),
    "Modelling quality": ("Качество моделирования", "Qualidade do modelamento"),
    "Mismatched charts errors": (
        "Ошибки рассогласования графиков",
        "Erros de gráficos incompatíveis",
    ),
    "Spread": ("Спред",),
    "Initial deposit": ("Начальный депозит", "Depósito Inicial"),
    "Total net profit": ("Чистая прибыль", "Lucro líquido total"),
    "Total trades": ("Всего сделок", "Total de negociações"),
    "Maximal drawdown": ("Максимальная просадка", "Rebaixamento Máximo"),
    "Relative drawdown": ("Относительная просадка", "Rebaixamento Relativo"),
    "Profit factor": ("Прибыльность", "Fator de lucro"),
}
_MT4_ENGLISH = {
    alias.lower(): english
    for english, aliases in _MT4_LABEL_ALIASES.items()
    for alias in (english, *aliases)
}


def _mt4_pairs(rows: list[_Row]) -> dict[str, str]:
    """Summary label → value, under the English label whatever the language."""
    found: dict[str, str] = {}
    for row in rows:
        texts = row.texts
        for index in range(len(texts) - 1):
            english = _MT4_ENGLISH.get(texts[index].strip().lower())
            if english is not None:
                found.setdefault(english, texts[index + 1])
    return found


@dataclass
class _Mt4Ticket:
    side: str
    volume: float
    price: float
    time: datetime


def _parse_mt4_tester(reader: _TableReader) -> _Draft:
    draft = _Draft(MT4_TESTER_HTML, [])
    pairs = _mt4_pairs(reader.rows)
    tickets: dict[str, _Mt4Ticket] = {}
    cash: list[_Cash] = []
    close_rows = 0
    unpaired = 0
    linked = 0
    forced = 0
    # Sides of positions closed at rollover, reopened in order by "swap open".
    rolled: list[str] = []
    # Tickets a partial close left open: MT4 moves the rest to a new ticket,
    # printed as a "buy"/"sell" row at the close's time and the entry price.
    partial: list[tuple[_Mt4Ticket, datetime]] = []
    for row in reader.rows:
        texts = row.texts
        if not _is_mt4_tester_row(texts):
            continue
        kind = texts[2].lower()
        order = texts[3]
        moment = _one_time(texts[1])
        size = _num(texts[4])
        price = _num(texts[5])
        if moment is None or size is None or price is None:
            draft.invalid_rows += 1
            continue
        if kind in {"buy", "sell"}:
            if order not in tickets:
                side = "long" if kind == "buy" else "short"
                rest = next(
                    (
                        old
                        for old, at in partial
                        if at == moment
                        and old.side == side
                        and abs(old.volume - size) <= _EPS
                        and abs(old.price - price) <= _EPS * max(1.0, abs(price))
                    ),
                    None,
                )
                if rest is not None:
                    tickets[order] = _Mt4Ticket(side, size, rest.price, rest.time)
                    rest.volume = 0.0
                else:
                    tickets[order] = _Mt4Ticket(side, size, price, moment)
            continue
        if kind == "swap open":
            if rolled and order not in tickets:
                tickets[order] = _Mt4Ticket(rolled.pop(0), size, price, moment)
            else:
                draft.invalid_rows += 1
            continue
        if kind not in _MT4_CLOSES:
            continue
        close_rows += 1
        profit = _num(texts[8]) if len(texts) > 8 else None
        balance = _num(texts[9]) if len(texts) > 9 else None
        if profit is None:
            draft.invalid_rows += 1
            continue
        cash.append(_Cash(moment, profit, False, balance))
        if kind == "close at stop":
            forced += 1
        ticket = tickets.get(order)
        if ticket is None or ticket.volume <= _EPS:
            candidates = [t for t in tickets.values() if abs(t.volume - size) <= _EPS]
            if len(candidates) == 1:
                ticket = candidates[0]
                linked += 1
            else:
                unpaired += 1
                continue
        take = min(size, ticket.volume)
        ticket.volume -= take
        if ticket.volume > _EPS:
            partial.append((ticket, moment))
        if kind == "swap close":
            rolled.append(ticket.side)
        draft.trips.append(
            _Trip(
                symbol=_mt4_symbol(pairs.get("Symbol", "")),
                side=ticket.side,
                volume=take,
                entry_time=ticket.time,
                exit_time=moment,
                entry_price=ticket.price,
                exit_price=price,
                gross=profit,
            )
        )
    draft.cash = cash
    draft.warnings.append(
        "MetaTrader 4 tester profit already includes swap and commission; costs are not "
        "itemised, so the trade P&L is net"
    )
    if linked:
        draft.warnings.append(
            f"{linked} close row(s) referenced an unknown ticket and were linked to the one "
            "open ticket with the same size"
        )
    if unpaired:
        draft.warnings.append(
            f"{unpaired} close row(s) could not be paired with an entry; their money is in "
            "the balance but not in the trade list"
        )
    still_open = sum(1 for ticket in tickets.values() if ticket.volume > _EPS)
    if still_open:
        draft.warnings.append(f"{still_open} position(s) never closed; excluded")
    if forced:
        draft.warnings.append(f"{forced} trade(s) closed by the tester at the end of the test")
    deposit = _num(pairs.get("Initial deposit"))
    if deposit is not None:
        draft.initial_balance = deposit
        draft.initial_note = "Initial deposit"
    for label, key in _MT4_LABELS.items():
        if pairs.get(label):
            draft.metadata[key] = _clip(pairs[label])
    parameters = pairs.get("Parameters", "")
    names = [part.split("=", 1)[0].strip() for part in parameters.split(";") if "=" in part]
    if names:
        draft.metadata["inputs"] = str(len(names))
        draft.metadata["input_names"] = _clip(", ".join(names), 500)
    strategy = reader.title.split(":", 1)[1].strip() if ":" in reader.title else ""
    if strategy:
        draft.metadata["strategy"] = _clip(strategy)
    if reader.meta.get("server"):
        draft.metadata["server"] = _clip(reader.meta["server"])
    window = _period_dates(pairs.get("Period", ""))
    if window is not None:
        draft.metadata["start"], draft.metadata["end"] = window
    _compare(
        draft.warnings,
        "close rows vs Total trades",
        _num(pairs.get("Total trades")),
        float(close_rows),
        0.5,
    )
    _compare(
        draft.warnings,
        "net profit",
        _lead_num(pairs.get("Total net profit")),
        sum(item.amount for item in cash),
        0.011 * max(1, len(cash)),
    )
    return draft


def _mt4_symbol(value: str) -> str:
    return value.split("(")[0].strip().upper()


def _parse_mt4_statement(reader: _TableReader) -> _Draft:
    draft = _Draft(MT4_STATEMENT_HTML, [])
    draft.itemised = {"commission", "swap", "fee"}
    labels = _labels(reader.rows)
    cash: list[_Cash] = []
    credits = 0
    cancelled = 0
    for texts, columns in _mt4_statement_rows(reader):
        if _is_mt4_statement_trade(texts, columns):

            def cell(name: str, texts: list[str] = texts, columns: dict[str, int] = columns) -> str:
                index = columns.get(name)
                return texts[index] if index is not None and index < len(texts) else ""

            entry_time = _one_time(cell("open_time"))
            exit_time = _one_time(cell("close_time"))
            volume = _num(cell("size"))
            entry_price = _num(cell("open_price"))
            exit_price = _num(cell("close_price"))
            profit = _num(cell("profit"))
            if None in (entry_time, exit_time, volume, entry_price, exit_price, profit):
                draft.invalid_rows += 1
                continue
            assert entry_time is not None and exit_time is not None
            trip = _Trip(
                symbol=cell("symbol").upper(),
                side="long" if cell("type").lower() == "buy" else "short",
                volume=volume or 0.0,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price or 0.0,
                exit_price=exit_price or 0.0,
                gross=profit or 0.0,
                commission=_num(cell("commission")) or 0.0,
                fee=_num(cell("taxes")) or 0.0,
                swap=_num(cell("swap")) or 0.0,
            )
            draft.trips.append(trip)
            cash.append(_Cash(exit_time, trip.net, False))
            continue
        at = columns["open_time"]
        kind = texts[columns["type"]].lower() if len(texts) > columns["type"] else ""
        if kind in {"balance", "credit"} and _is_mt_time(texts[at]):
            moment = _one_time(texts[at])
            # The amount is the last number on the row: the Profit cell of a
            # 4-5 cell row, or before the comment in the numbered layout.
            amounts = [
                value for value in (_num(text) for text in texts[at + 2 :]) if value is not None
            ]
            if moment is None or not amounts:
                draft.invalid_rows += 1
            elif kind == "credit":
                credits += 1
            else:
                cash.append(_Cash(moment, amounts[-1], True))
            continue
        if any(text.lower() == "cancelled" for text in texts) and _is_mt_time(
            texts[at] if len(texts) > at else ""
        ):
            cancelled += 1
    cash.sort(key=lambda item: item.time)
    draft.cash = cash
    if credits:
        draft.warnings.append(
            f"{credits} credit row(s) excluded: broker credit is not the trader's balance"
        )
    first_entry = min((trip.entry_time for trip in draft.trips), default=None)
    has_opening_flow = first_entry is not None and any(
        item.is_flow and item.time <= first_entry for item in cash
    )
    if not has_opening_flow:
        balance = _num(labels.get("Balance"))
        deposits = _num(labels.get("Deposit/Withdrawal"))
        closed = _num(labels.get("Closed Trade P/L"))
        if balance is not None and deposits is not None and closed is not None:
            draft.initial_balance = balance - deposits - closed
            draft.initial_note = "summary Balance minus Deposit/Withdrawal minus Closed Trade P/L"
    draft.currency = labels.get("Currency") or None
    for label, key in (
        ("Closed Trade P/L", "declared_closed_trade_pnl"),
        ("Balance", "declared_balance"),
        ("Equity", "declared_equity"),
        ("Floating P/L", "declared_floating_pnl"),
        ("Total Trades", "declared_total_trades"),
        ("Maximal Drawdown", "declared_maximal_drawdown"),
        ("Leverage", "leverage"),
    ):
        if labels.get(label):
            draft.metadata[key] = _clip(labels[label])
    _compare(
        draft.warnings,
        "closed trade P/L",
        _num(labels.get("Closed P/L") or labels.get("Closed Trade P/L")),
        sum(trip.net for trip in draft.trips),
        0.011 * max(1, len(draft.trips)),
    )
    return draft


# ---------------------------------------------------------------------------
# Delimited text and XLSX
# ---------------------------------------------------------------------------


def _read_delimited(text: str) -> tuple[list[str], list[list[str]], str]:
    lines = [line for line in text.splitlines() if line.strip()]
    hint: str | None = None
    # Excel's "sep=," first line (FX Blue) names the delimiter; a lone title
    # line ("History", as some Myfxbook copies start) precedes the header.
    if lines and re.fullmatch(r"sep=.", lines[0].strip().lstrip("\ufeff")):
        hint = lines.pop(0).strip()[-1]
    if lines and lines[0].strip().lstrip("\ufeff").lower() in {"history", "closed trades"}:
        lines.pop(0)
    if not lines:
        return [], [], ","
    head = lines[0]
    delimiter = hint or max((",", ";", "\t"), key=head.count)
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    try:
        rows = [[cell.strip() for cell in row] for row in reader]
    except csv.Error as exc:
        # An unbalanced quote swallowing the file, or a cell past the
        # module's field limit: not a trade list, and never a server error.
        raise ReportFormatError(
            "bad_csv",
            "the file could not be read as a delimited list of trades",
            "el archivo no se pudo leer como una lista de operaciones separada por comas",
        ) from exc
    header = rows[0]
    return header, [row for row in rows[1:] if any(cell for cell in row)], delimiter


_XML_FORBIDDEN = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


def _xml_doctype_error() -> ReportFormatError:
    return ReportFormatError(
        "xml_doctype",
        "the file declares a document type, which is refused for safety",
        "el archivo declara un tipo de documento, que se rechaza por seguridad",
    )


class _DoctypeRefused(Exception):
    """Raised from inside expat the moment a DOCTYPE or ENTITY appears."""


def _refuse(*_: Any) -> None:
    raise _DoctypeRefused


def _xml(data: bytes) -> ElementTree.Element:
    """Parse XML with no document type at all: no entity can be declared.

    The byte check catches the ASCII spellings cheaply; a first streaming pass
    with bare expat catches the rest (a UTF-16 or UTF-32 member inside a
    workbook, where the bytes of ``<!DOCTYPE`` are interleaved with NULs) and
    stops at the declaration, before any entity could be expanded.
    """
    if _XML_FORBIDDEN.search(data):
        raise _xml_doctype_error()
    probe = expat.ParserCreate()
    probe.StartDoctypeDeclHandler = _refuse
    probe.EntityDeclHandler = _refuse
    try:
        probe.Parse(data, True)
    except _DoctypeRefused as exc:
        raise _xml_doctype_error() from exc
    except expat.ExpatError:
        pass  # malformed XML: the parse below reports it
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ReportFormatError(
            "bad_xml", f"the XML could not be read: {exc}", f"no se pudo leer el XML: {exc}"
        ) from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference[:8].upper())
    if letters is None:
        return -1
    if len(letters.group(0)) > 3:
        # Past XFD, Excel's last column: never a real cell.
        return 26**4
    index = 0
    for char in letters.group(0):
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _xlsx_too_big() -> ReportFormatError:
    return ReportFormatError(
        "xlsx_too_large",
        "the workbook inflates past the size limit; export the list of trades as CSV instead",
        "el libro de Excel supera el límite al descomprimirse; exporta la lista de "
        "operaciones como CSV",
    )


def read_xlsx(data: bytes) -> dict[str, list[list[Any]]]:
    """Every sheet of a workbook as rows of text or numbers (standard library only)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, EOFError, OSError, ValueError) as exc:
        raise ReportFormatError(
            "bad_xlsx", "the workbook could not be opened", "no se pudo abrir el libro de Excel"
        ) from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_XLSX_MEMBERS:
            raise _xlsx_too_big()
        if sum(info.file_size for info in infos) > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise _xlsx_too_big()
        names = {info.filename for info in infos}

        def load(name: str) -> ElementTree.Element | None:
            if name not in names:
                return None
            try:
                data = archive.read(name)
            except (
                zipfile.BadZipFile,
                zlib.error,
                EOFError,
                NotImplementedError,
                RuntimeError,
            ) as exc:
                # A damaged or encrypted member, or one whose declared size
                # is a lie (the read stops at the declared size, then the CRC
                # check fails): a clear refusal, never a server error.
                raise ReportFormatError(
                    "bad_xlsx",
                    "the workbook is damaged or encrypted and could not be read",
                    "el libro de Excel está dañado o cifrado y no se pudo leer",
                ) from exc
            return _xml(data)

        workbook = load("xl/workbook.xml")
        if workbook is None:
            raise ReportFormatError(
                "bad_xlsx", "the workbook has no sheets", "el libro de Excel no tiene hojas"
            )
        relations = load("xl/_rels/workbook.xml.rels")
        targets: dict[str, str] = {}
        if relations is not None:
            for rel in relations.iter():
                if _local(rel.tag) == "Relationship":
                    target = rel.get("Target", "")
                    target = target.lstrip("/")
                    if not target.startswith("xl/"):
                        target = "xl/" + target
                    targets[rel.get("Id", "")] = target
        shared: list[str] = []
        strings = load("xl/sharedStrings.xml")
        if strings is not None:
            for item in strings:
                if _local(item.tag) == "si":
                    shared.append(
                        "".join(node.text or "" for node in item.iter() if _local(node.tag) == "t")
                    )
        sheets: dict[str, list[list[Any]]] = {}
        position = 0
        for node in workbook.iter():
            if _local(node.tag) != "sheet":
                continue
            position += 1
            rel_id = next((value for key, value in node.attrib.items() if _local(key) == "id"), "")
            target = targets.get(rel_id, f"xl/worksheets/sheet{position}.xml")
            sheet = load(target)
            if sheet is not None:
                sheets[node.get("name", f"Sheet{position}")] = _sheet_rows(sheet, shared)
        return sheets


def xlsx_as_csv(data: bytes, time_headers: Sequence[str]) -> bytes:
    """The first non-empty sheet of a workbook as UTF-8 CSV bytes.

    Excel stores dates as day serials, so a column whose header names a
    time (``time_headers``, compared lower-case and stripped) has its
    numbers written as ISO timestamps. A workbook with no data gives b"".
    """
    import csv

    sheets = read_xlsx(data)
    rows = next((rows for rows in sheets.values() if any(any(r) for r in rows)), [])
    rows = [row for row in rows if any(cell not in (None, "") for cell in row)]
    if not rows:
        return b""
    header = [_as_text(cell).lower() for cell in rows[0]]
    times = {i for i, name in enumerate(header) if name in set(time_headers)}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([_as_text(cell) for cell in rows[0]])
    for row in rows[1:]:
        cells: list[str] = []
        for i, cell in enumerate(row):
            moment = (
                _excel_serial(float(cell))
                if i in times and isinstance(cell, float | int) and not isinstance(cell, bool)
                else None
            )
            cells.append(moment.isoformat() if moment is not None else _as_text(cell))
        writer.writerow(cells)
    return out.getvalue().encode("utf-8")


def _sheet_rows(sheet: ElementTree.Element, shared: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cells = 0
    for row in sheet.iter():
        if _local(row.tag) != "row":
            continue
        values: dict[int, Any] = {}
        next_index = 0
        for cell in row:
            if _local(cell.tag) != "c":
                continue
            reference = cell.get("r")
            index = _column_index(reference) if reference else next_index
            next_index = index + 1
            if not 0 <= index < MAX_XLSX_COLUMNS:
                continue
            kind = cell.get("t", "n")
            raw = next((child.text for child in cell if _local(child.tag) == "v"), None)
            value: Any
            if kind == "s" and raw is not None and raw.isdigit() and int(raw) < len(shared):
                value = shared[int(raw)]
            elif kind == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter() if _local(node.tag) == "t")
            elif kind in {"str", "e"}:
                value = raw if kind == "str" else None
            elif kind == "b":
                value = raw
            else:
                number = _num(raw) if raw is not None else None
                value = number
            values[index] = value
        if values:
            width = max(values) + 1
            cells += width
            if cells > MAX_XLSX_CELLS:
                raise _xlsx_too_big()
            rows.append([values.get(i) for i in range(width)])
        else:
            rows.append([])
    return rows


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# ---------------------------------------------------------------------------
# TradingView
# ---------------------------------------------------------------------------

_TV_TRADE = re.compile(r"^(trade #|trade number)$")
_TV_TYPE = re.compile(r"^(type|typ)$")
_TV_PATTERNS: dict[str, re.Pattern[str]] = {
    "trade": _TV_TRADE,
    "type": _TV_TYPE,
    "signal": re.compile(r"^signal$"),
    "time": re.compile(r"^(date/time|date and time|datum und uhrzeit)$"),
    "price": re.compile(r"^(price|preis)( \S+)?$"),
    "qty": re.compile(r"^(contracts|position size \(qty\)|size \(qty\)|größe \(menge\))$"),
    "net": re.compile(r"^(profit|net p&l|net pnl|g&v netto)( (?!%)\S+)?$"),
    "commission": re.compile(r"^commission( \S+)?$"),
    "cum": re.compile(
        r"^(cum\. profit|cumulative p&l|cumulative pnl|kumulativer g&v)( (?!%)\S+)?$"
    ),
    "cum_pct": re.compile(r"^(cum\. profit|cumulative p&l|cumulative pnl|kumulativer g&v) %$"),
}
#: Column positions by generation, used when the header is in an unknown language.
_TV_POSITIONS: dict[int, dict[str, int]] = {
    14: {"trade": 0, "type": 1, "signal": 2, "time": 3, "price": 4, "qty": 5, "net": 6,
         "cum": 8, "cum_pct": 9},
    15: {"trade": 0, "type": 1, "time": 2, "signal": 3, "price": 4, "qty": 5, "net": 7,
         "cum": 13, "cum_pct": 14},
    17: {"trade": 0, "type": 1, "time": 2, "signal": 3, "price": 4, "qty": 5, "net": 7,
         "commission": 9, "cum": 14, "cum_pct": 15},
}  # fmt: skip
_TV_OPEN_SIGNALS = {"open", "offen"}


def _is_tradingview_header(header: Sequence[Any]) -> bool:
    cells = [_as_text(cell).lower() for cell in header]
    return len(cells) >= 2 and bool(_TV_TRADE.match(cells[0])) and bool(_TV_TYPE.match(cells[1]))


def _tv_side(kind: str) -> str | None:
    lowered = kind.lower()
    if "long" in lowered or "larg" in lowered:
        return "long"
    if "short" in lowered or "cort" in lowered:
        return "short"
    return None


def _tv_role(kind: str) -> str | None:
    lowered = kind.lower().strip()
    if lowered.startswith("entry") or lowered.endswith("-einstieg"):
        return "entry"
    if lowered.startswith("exit") or lowered.endswith("-ausstieg"):
        return "exit"
    return None


def _tv_columns(header: Sequence[Any]) -> tuple[dict[str, int], str | None]:
    cells = [_as_text(cell).lower() for cell in header]
    columns: dict[str, int] = {}
    currency: str | None = None
    for index, cell in enumerate(cells):
        for key, pattern in _TV_PATTERNS.items():
            if key not in columns and pattern.match(cell):
                columns[key] = index
                if key == "net":
                    suffix = _as_text(header[index]).split()[-1]
                    if re.fullmatch(r"[A-Z]{3,5}", suffix):
                        currency = suffix
    required = {"trade", "type", "time", "price", "qty", "net"}
    if not required <= set(columns) and len(cells) in _TV_POSITIONS:
        columns = dict(_TV_POSITIONS[len(cells)])
    if not required <= set(columns):
        missing = ", ".join(sorted(required - set(columns)))
        raise ReportFormatError(
            "tradingview_columns",
            f"the TradingView list of trades is missing column(s): {missing}; export it "
            "with TradingView in English",
            f"a la lista de operaciones de TradingView le faltan columnas: {missing}; "
            "expórtala con TradingView en inglés",
        )
    return columns, currency


def _parse_tradingview(
    header: Sequence[Any], rows: list[list[Any]], source_format: str, *, serial_dates: bool
) -> _Draft:
    columns, currency = _tv_columns(header)
    draft = _Draft(source_format, [], currency=currency)
    width = len(header)
    rows = [row + [None] * (width - len(row)) for row in rows]

    def get(row: list[Any], key: str) -> Any:
        index = columns.get(key)
        return row[index] if index is not None and index < len(row) else None

    times = _parse_times([get(row, "time") for row in rows], serial_numbers=serial_dates)
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(_as_text(get(row, "trade")), []).append(index)
    open_trades = 0
    malformed = 0
    has_commission = "commission" in columns
    last_cum: tuple[int, float] | None = None
    capital_hint: tuple[float, float] | None = None
    for number, indexes in groups.items():
        if len(indexes) != 2:
            malformed += 1
            continue
        roles = {_tv_role(_as_text(get(rows[i], "type"))): i for i in indexes}
        if set(roles) != {"entry", "exit"}:
            first, second = indexes
            earlier = times.values[first], times.values[second]
            if None in earlier:
                malformed += 1
                continue
            assert earlier[0] is not None and earlier[1] is not None
            roles = (
                {"entry": first, "exit": second}
                if earlier[0] <= earlier[1]
                else {"entry": second, "exit": first}
            )
        entry, exit_ = rows[roles["entry"]], rows[roles["exit"]]
        if _as_text(get(exit_, "signal")).lower() in _TV_OPEN_SIGNALS:
            open_trades += 1
            continue
        side = _tv_side(_as_text(get(entry, "type"))) or _tv_side(_as_text(get(exit_, "type")))
        entry_time = times.values[roles["entry"]]
        exit_time = times.values[roles["exit"]]
        volume = _num(get(exit_, "qty"))
        entry_price = _num(get(entry, "price"))
        exit_price = _num(get(exit_, "price"))
        net = _num(get(exit_, "net"))
        if (
            side is None
            or entry_time is None
            or exit_time is None
            or volume is None
            or entry_price is None
            or exit_price is None
            or net is None
        ):
            malformed += 1
            continue
        paid = abs(_num(get(exit_, "commission")) or 0.0) if has_commission else 0.0
        draft.trips.append(
            _Trip(
                symbol="",
                side=side,
                volume=abs(volume),
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                gross=net + paid,
                commission=-paid,
            )
        )
        cum = _num(get(exit_, "cum"))
        order = int(_num(number) or 0)
        if cum is not None and (last_cum is None or order > last_cum[0]):
            last_cum = (order, cum)
        cum_pct = _num(get(exit_, "cum_pct"))
        if (
            cum is not None
            and cum_pct is not None
            and cum_pct != 0
            and (capital_hint is None or abs(cum_pct) > abs(capital_hint[1]))
        ):
            capital_hint = (cum, cum_pct)
    draft.invalid_rows = malformed
    draft.naive_times = times.naive
    if has_commission:
        draft.itemised = {"commission"}
    else:
        draft.warnings.append(
            "this TradingView export does not itemise commission; trade P&L is net of the "
            "commission set in the strategy properties"
        )
    if open_trades:
        draft.warnings.append(f"{open_trades} open trade(s) at the end of the export; excluded")
    if malformed:
        draft.warnings.append(f"{malformed} trade number(s) without one entry and one exit row")
    if last_cum is not None:
        _compare(
            draft.warnings,
            "cumulative P&L",
            last_cum[1],
            sum(trip.net for trip in draft.trips),
            0.011 * max(1, len(draft.trips)),
        )
    if capital_hint is not None:
        estimate = _capital_from_percent(*capital_hint)
        if estimate is not None:
            draft.initial_balance = estimate
            draft.initial_note = "the cumulative P&L and cumulative P&L % columns"
    return draft


def _capital_from_percent(cum: float, cum_pct: float) -> float | None:
    """Initial capital implied by a cumulative P&L and its (2-decimal) percentage.

    Only used when the percentage is at least 1 % (rounding error at most
    0.5 %); the estimate is snapped to the roundest number within that error.
    """
    if abs(cum_pct) < 1.0:
        return None
    estimate = cum / (cum_pct / 100.0)
    if estimate <= 0:
        return None
    tolerance = estimate * 0.005 / abs(cum_pct)
    for digits in range(1, 16):
        magnitude = 10 ** (math.floor(math.log10(estimate)) - digits + 1)
        snapped = round(estimate / magnitude) * magnitude
        if abs(snapped - estimate) <= tolerance:
            return float(snapped)
    return round(estimate, 2)


_TV_PROPERTY_KNOWN = {
    "trading range",
    "backtesting range",
    "symbol",
    "timeframe",
    "point value",
    "chart type",
    "currency",
    "tick size",
    "precision",
    "initial capital",
    "order size",
    "pyramiding",
    "commission",
    "slippage",
    "verify price for limit orders",
    "margin for long positions",
    "margin for short positions",
    "recalculate after order is filled",
    "recalculate on every tick",
    "recalculate on bar close",
    "backtesting precision. use bar magnifier",
}


def _parse_tradingview_xlsx(sheets: dict[str, list[list[Any]]]) -> _Draft:
    trades_sheet = next(
        (rows for rows in sheets.values() if rows and _is_tradingview_header(rows[0])), None
    )
    if trades_sheet is None:
        raise _unknown_format()
    draft = _parse_tradingview(
        trades_sheet[0], trades_sheet[1:], TRADINGVIEW_XLSX, serial_dates=True
    )
    properties = sheets.get("Properties")
    if properties is None:
        properties = next(
            (
                rows
                for rows in sheets.values()
                if rows and [_as_text(c).lower() for c in rows[0][:2]] == ["name", "value"]
            ),
            None,
        )
    if properties:
        values = {
            _as_text(row[0]).lower(): _as_text(row[1]) for row in properties[1:] if len(row) >= 2
        }
        capital = _num(values.get("initial capital"))
        if capital is not None and capital > 0:
            draft.initial_balance = capital
            draft.initial_note = "Properties: Initial capital"
        if values.get("currency") and draft.currency is None:
            draft.currency = values["currency"]
        for key in (
            "symbol",
            "timeframe",
            "commission",
            "slippage",
            "pyramiding",
            "backtesting range",
            "backtesting precision. use bar magnifier",
        ):
            if values.get(key):
                draft.metadata[key.split(".")[0].replace(" ", "_")] = _clip(values[key])
        inputs = [name for name in values if name and name not in _TV_PROPERTY_KNOWN]
        if inputs:
            draft.metadata["inputs"] = str(len(inputs))
        symbol = values.get("symbol", "")
        for trip in draft.trips:
            trip.symbol = symbol.upper()
    return draft


# ---------------------------------------------------------------------------
# NinjaTrader, QuantConnect, backtesting.py, vectorbt
# ---------------------------------------------------------------------------


def _index(header: list[str]) -> dict[str, int]:
    return {cell.strip().lower(): position for position, cell in enumerate(header)}


def _table_format(header: list[str]) -> str | None:
    names = set(_index(header))
    if _is_tradingview_header(header):
        return TRADINGVIEW_CSV
    if {"trade number", "instrument", "market pos."} <= names:
        return NINJATRADER_CSV
    if {"entry time", "symbols", "exit time", "direction", "p&l"} <= names:
        return QUANTCONNECT_TRADES_CSV
    if {"size", "entrybar", "exitbar", "entryprice", "exitprice", "pnl"} <= names:
        return BACKTESTINGPY_CSV
    if {"avg entry price", "avg exit price", "pnl", "direction", "status"} <= names:
        return VECTORBT_CSV
    if _is_myfxbook_header(names):
        return MYFXBOOK_CSV
    if _is_mql5_signal_header(header):
        return MQL5_SIGNAL_CSV
    if _is_fxblue_header(names):
        return FXBLUE_CSV
    return None


def _cells(row: list[str], columns: dict[str, int], name: str) -> str:
    index = columns.get(name)
    return row[index] if index is not None and index < len(row) else ""


def _parse_ninjatrader(header: list[str], rows: list[list[str]], delimiter: str) -> _Draft:
    columns = _index(header)
    decimal = "," if delimiter == ";" else "."
    draft = _Draft(NINJATRADER_CSV, [])
    draft.itemised = {"commission"}
    entry_times = _parse_times([_cells(row, columns, "entry time") for row in rows])
    exit_times = _parse_times([_cells(row, columns, "exit time") for row in rows])
    fee_columns = [
        name
        for name in ("commission", "clearing fee", "exchange fee", "ip fee", "nfa fee")
        if name in columns
    ]
    last_cum: float | None = None
    for position, row in enumerate(rows):
        side = _cells(row, columns, "market pos.").lower()
        volume = _num(_cells(row, columns, "qty"), decimal=decimal)
        entry_price = _num(_cells(row, columns, "entry price"), decimal=decimal)
        exit_price = _num(_cells(row, columns, "exit price"), decimal=decimal)
        net = _num(_cells(row, columns, "profit"), decimal=decimal)
        entry_time = entry_times.values[position]
        exit_time = exit_times.values[position]
        if (
            side not in {"long", "short"}
            or entry_time is None
            or exit_time is None
            or volume is None
            or entry_price is None
            or exit_price is None
            or net is None
        ):
            draft.invalid_rows += 1
            continue
        paid = sum(
            abs(_num(_cells(row, columns, name), decimal=decimal) or 0.0) for name in fee_columns
        )
        draft.trips.append(
            _Trip(
                symbol=_cells(row, columns, "instrument"),
                side=side,
                volume=abs(volume),
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                gross=net + paid,
                commission=-paid,
            )
        )
        cum = _num(_cells(row, columns, "cum. net profit"), decimal=decimal)
        if cum is not None:
            last_cum = cum
        strategy = _cells(row, columns, "strategy")
        if strategy:
            draft.metadata.setdefault("strategy", _clip(strategy))
    draft.naive_times = True
    if draft.trips and all(trip.commission == 0 for trip in draft.trips):
        draft.warnings.append("every trade has zero commission and fees")
    if last_cum is not None:
        _compare(
            draft.warnings,
            "Cum. net profit",
            last_cum,
            sum(trip.net for trip in draft.trips),
            0.011 * max(1, len(draft.trips)),
        )
    return draft


def _parse_quantconnect(header: list[str], rows: list[list[str]]) -> _Draft:
    columns = _index(header)
    draft = _Draft(QUANTCONNECT_TRADES_CSV, [])
    draft.itemised = {"commission"}
    entry_times = _parse_times([_cells(row, columns, "entry time") for row in rows])
    exit_times = _parse_times([_cells(row, columns, "exit time") for row in rows])
    multi_leg = 0
    for position, row in enumerate(rows):
        direction = _cells(row, columns, "direction").lower()
        side = {"buy": "long", "long": "long", "sell": "short", "short": "short"}.get(direction)
        volume = _num(_cells(row, columns, "quantity"))
        entry_price = _num(_cells(row, columns, "entry price"))
        exit_price = _num(_cells(row, columns, "exit price"))
        gross = _num(_cells(row, columns, "p&l"))
        fees = abs(_num(_cells(row, columns, "fees")) or 0.0)
        entry_time = entry_times.values[position]
        exit_time = exit_times.values[position]
        if (
            side is None
            or entry_time is None
            or exit_time is None
            or volume is None
            or entry_price is None
            or exit_price is None
            or gross is None
        ):
            draft.invalid_rows += 1
            continue
        symbol = " ".join(_cells(row, columns, "symbols").split())
        if "," in symbol:
            multi_leg += 1
        draft.trips.append(
            _Trip(
                symbol=symbol.upper(),
                side=side,
                volume=abs(volume),
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                gross=gross,
                commission=-fees,
            )
        )
    draft.naive_times = entry_times.naive or exit_times.naive
    if multi_leg:
        draft.warnings.append(f"{multi_leg} multi-leg trade(s) kept as single trades")
    return draft


def _parse_backtestingpy(header: list[str], rows: list[list[str]]) -> _Draft:
    columns = _index(header)
    draft = _Draft(BACKTESTINGPY_CSV, [])
    has_commission = "commission" in columns
    entry_times = _parse_times([_cells(row, columns, "entrytime") for row in rows])
    exit_times = _parse_times([_cells(row, columns, "exittime") for row in rows])
    for position, row in enumerate(rows):
        size = _num(_cells(row, columns, "size"))
        entry_price = _num(_cells(row, columns, "entryprice"))
        exit_price = _num(_cells(row, columns, "exitprice"))
        net = _num(_cells(row, columns, "pnl"))
        entry_time = entry_times.values[position]
        exit_time = exit_times.values[position]
        if (
            size is None
            or size == 0
            or entry_time is None
            or exit_time is None
            or entry_price is None
            or exit_price is None
            or net is None
        ):
            draft.invalid_rows += 1
            continue
        paid = abs(_num(_cells(row, columns, "commission")) or 0.0) if has_commission else 0.0
        draft.trips.append(
            _Trip(
                symbol="",
                side="long" if size > 0 else "short",
                volume=abs(size),
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                gross=net + paid,
                commission=-paid,
            )
        )
    draft.naive_times = entry_times.naive or exit_times.naive
    if has_commission:
        draft.itemised = {"commission"}
    else:
        draft.warnings.append(
            "this backtesting.py version folds commission into the fill prices; "
            "costs are not itemised"
        )
    return draft


def _parse_vectorbt(header: list[str], rows: list[list[str]]) -> _Draft:
    columns = _index(header)
    draft = _Draft(VECTORBT_CSV, [])
    draft.itemised = {"commission"}
    variants: list[str] = []
    for row in rows:
        key = _cells(row, columns, "column")
        if key not in variants:
            variants.append(key)
    chosen = variants[0] if variants else ""
    if len(variants) > 1:
        draft.warnings.append(
            f"the file holds {len(variants)} parameter variants; only the first "
            f"({_clip(chosen, 60)}) was imported"
        )
        draft.metadata["variants"] = str(len(variants))
    entry_times = _parse_times([_cells(row, columns, "entry timestamp") for row in rows])
    exit_times = _parse_times([_cells(row, columns, "exit timestamp") for row in rows])
    open_trades = 0
    for position, row in enumerate(rows):
        if _cells(row, columns, "column") != chosen:
            continue
        if _cells(row, columns, "status").lower() != "closed":
            open_trades += 1
            continue
        side = _cells(row, columns, "direction").lower()
        volume = _num(_cells(row, columns, "size"))
        entry_price = _num(_cells(row, columns, "avg entry price"))
        exit_price = _num(_cells(row, columns, "avg exit price"))
        net = _num(_cells(row, columns, "pnl"))
        entry_time = entry_times.values[position]
        exit_time = exit_times.values[position]
        if (
            side not in {"long", "short"}
            or entry_time is None
            or exit_time is None
            or volume is None
            or entry_price is None
            or exit_price is None
            or net is None
        ):
            draft.invalid_rows += 1
            continue
        paid = abs(_num(_cells(row, columns, "entry fees")) or 0.0) + abs(
            _num(_cells(row, columns, "exit fees")) or 0.0
        )
        draft.trips.append(
            _Trip(
                symbol=chosen.upper() if re.fullmatch(r"[\w\-./:]+", chosen) else "",
                side=side,
                volume=abs(volume),
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                gross=net + paid,
                commission=-paid,
            )
        )
    draft.naive_times = entry_times.naive or exit_times.naive
    if open_trades:
        draft.warnings.append(f"{open_trades} open trade(s) excluded")
    return draft


# ---------------------------------------------------------------------------
# Shared assembly: contract sizes, trades and the balance curve
# ---------------------------------------------------------------------------


def _significant(value: float, digits: int = 6) -> float:
    if value == 0 or not math.isfinite(value):
        return value
    return round(value, digits - 1 - math.floor(math.log10(abs(value))))


def _snap(size: float) -> float:
    """Round a contract size to 1, 2, 2.5 or 5 times a power of ten when within 3 %.

    Costs folded into a net P&L bend the inferred size slightly (1.02 instead
    of 1); real contract sizes are round numbers, and a size that is not
    (a quote currency converted to the account currency) is left alone.
    """
    if size <= 0:
        return size
    power = 10.0 ** math.floor(math.log10(size))
    for base in (1.0, 2.0, 2.5, 5.0, 10.0):
        candidate = base * power
        if abs(size - candidate) <= 0.03 * candidate:
            return _significant(candidate)
    return _significant(size)


def _contract_sizes(trips: list[_Trip]) -> dict[str, float]:
    ratios: dict[str, list[float]] = {}
    for trip in trips:
        move = abs(trip.exit_price - trip.entry_price)
        if move > 0 and trip.volume > 0 and trip.gross != 0:
            ratios.setdefault(trip.symbol, []).append(abs(trip.gross) / (move * trip.volume))
    sizes = {symbol: _snap(statistics.median(values)) for symbol, values in ratios.items()}
    for symbol in sizes:
        if _unit_size_fits([trip for trip in trips if trip.symbol == symbol]):
            sizes[symbol] = 1.0
    return {trip.symbol: sizes.get(trip.symbol, 1.0) for trip in trips}


def _unit_size_fits(trips: list[_Trip]) -> bool:
    """True when a contract size of one reproduces every reported profit to
    the precision the file prints it (a one-unit forex trade that made
    0.00127 shows 0.001), so rounding is not mistaken for another size."""
    return all(
        abs(abs(trip.gross) - abs(trip.exit_price - trip.entry_price) * trip.volume)
        <= printed_step(trip.gross) / 2 + _EPS
        for trip in trips
    )


#: A symbol whose recomputed gross P&L misses the reported one by more
#: than this share of its gross, with one contract size, is re-sized per trade.
CONVERSION_DRIFT_SHARE = 0.01
#: A per-trade size is used only within this band around the symbol's size:
#: account-currency conversion drifts slowly; a wider gap is something else.
CONVERSION_DRIFT_BAND = (0.8, 1.25)


def _trip_ratio(trip: _Trip) -> float | None:
    move = abs(trip.exit_price - trip.entry_price)
    if move > 0 and trip.volume > 0 and trip.gross != 0:
        return abs(trip.gross) / (move * trip.volume)
    return None


def _trip_size(trip: _Trip, size: float) -> float:
    ratio = _trip_ratio(trip)
    low, high = CONVERSION_DRIFT_BAND
    if ratio is not None and low <= ratio / size <= high:
        return ratio
    return size


def _drifting_symbols(trips: list[_Trip], sizes: dict[str, float]) -> set[str]:
    """Symbols whose money value per point changes during the report.

    A pair quoted in another currency than the account's (USDJPY in a USD
    account, an index CFD in AUD) pays a profit converted at each close's
    rate, so one contract size cannot reproduce every gross P&L. Those
    symbols get a per-trade size from the reported profit, within
    ``CONVERSION_DRIFT_BAND``, so the audit's recomputed P&L matches the
    platform's. Only for files whose P&L is gross of commission and swap.
    """
    missed: dict[str, float] = {}
    gross: dict[str, float] = {}
    for trip in trips:
        direction = 1.0 if trip.side == "long" else -1.0
        ours = (trip.exit_price - trip.entry_price) * direction * trip.volume * sizes[trip.symbol]
        missed[trip.symbol] = missed.get(trip.symbol, 0.0) + abs(ours - trip.gross)
        gross[trip.symbol] = gross.get(trip.symbol, 0.0) + abs(ours)
    return {
        symbol
        for symbol, miss in missed.items()
        if gross[symbol] > 0 and miss / gross[symbol] > CONVERSION_DRIFT_SHARE
    }


def _previous_day(day: date, business: bool) -> date:
    day -= timedelta(days=1)
    while business and day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _days(start: date, end: date, business: bool) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        if not business or day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _balance_curve(
    draft: _Draft, trips: list[_Trip], fallback_initial: float | None
) -> tuple[bytes, float, list[str]]:
    warnings: list[str] = []
    if draft.cash is not None:
        cash = sorted(draft.cash, key=lambda item: item.time)
    else:
        cash = [_Cash(trip.exit_time, trip.net, False) for trip in trips]
        cash.sort(key=lambda item: item.time)
    first_entry = min(trip.entry_time for trip in trips)
    last_exit = max(trip.exit_time for trip in trips)

    opening = [item for item in cash if item.is_flow and item.time <= first_entry]
    later = [item for item in cash if not (item.is_flow and item.time <= first_entry)]
    initial: float
    if opening:
        initial = sum(item.amount for item in opening)
        if draft.initial_balance is not None and abs(draft.initial_balance - initial) > 0.011:
            warnings.append(
                f"the stated initial balance {draft.initial_balance:,.2f} differs from the "
                f"deposits before the first trade ({initial:,.2f}); the deposits were used"
            )
    elif draft.initial_balance is not None:
        initial = draft.initial_balance
        if draft.initial_note:
            warnings.append(f"initial balance {initial:,.2f} taken from {draft.initial_note}")
    elif fallback_initial is not None:
        initial = fallback_initial
    else:
        initial = DEFAULT_INITIAL_BALANCE
        warnings.append(
            f"the file does not state a starting balance; {DEFAULT_INITIAL_BALANCE:,.0f} "
            "was assumed, which scales every return and drawdown"
        )

    in_range = [item for item in later if item.time.date() <= last_exit.date()]
    ignored = sum(1 for item in later if item.is_flow and item.time.date() > last_exit.date())
    if ignored:
        warnings.append(f"{ignored} cash flow(s) after the last trade ignored")
    balance = initial
    breaks = 0
    closing: dict[date, float] = {}
    flows: dict[date, float] = {}
    for item in in_range:
        balance += item.amount
        if item.reported_balance is not None:
            if abs(item.reported_balance - balance) > 0.011:
                breaks += 1
            balance = item.reported_balance
        day = item.time.date()
        closing[day] = balance
        if item.is_flow:
            flows[day] = flows.get(day, 0.0) + item.amount
    if breaks:
        warnings.append(
            f"{breaks} Balance cell(s) do not equal the previous balance plus the row's "
            "money; the reported Balance was kept"
        )

    business = not any(item.time.weekday() >= 5 for item in in_range if not item.is_flow) and (
        not any(trip.exit_time.weekday() >= 5 for trip in trips)
    )
    daily = sorted((day, closing[day], flows.get(day, 0.0)) for day in closing)
    start = _previous_day(first_entry.date(), business)
    level = initial
    index = initial
    rows = [(start, initial)]
    adjusted = bool(flows)
    pointer = 0
    for day in _days(first_entry.date(), last_exit.date(), business):
        before = level
        flow = 0.0
        # Events on a skipped weekend day land on the next business day.
        while pointer < len(daily) and daily[pointer][0] <= day:
            level = daily[pointer][1]
            flow += daily[pointer][2]
            pointer += 1
        if level <= 0 or before <= 0:
            raise ReportFormatError(
                "balance_not_positive",
                "the reconstructed balance reaches zero or below; state the real starting "
                "balance so returns can be computed",
                "el balance reconstruido llega a cero o menos; indica el balance inicial "
                "real para poder calcular los retornos",
            )
        if adjusted:
            index *= 1.0 + (level - before - flow) / before
            rows.append((day, index))
        else:
            rows.append((day, level))
    if adjusted:
        warnings.append(
            "deposits or withdrawals were removed: the curve is a flow-adjusted index "
            "that starts at the initial balance"
        )
    text = "timestamp,equity\n" + "".join(f"{day.isoformat()},{value:.6f}\n" for day, value in rows)
    return text.encode("utf-8"), initial, warnings


def _assemble(draft: _Draft, fallback_initial: float | None) -> ImportedReport:
    if not draft.trips:
        raise ReportFormatError(
            "no_closed_trades",
            f"the {draft.source_format} file has no closed trades",
            f"el archivo ({draft.source_format}) no contiene operaciones cerradas",
        )
    if len(draft.trips) > MAX_TRADES:
        raise ReportFormatError(
            "too_many_trades",
            f"the file has {len(draft.trips):,} closed trades; the limit is {MAX_TRADES:,}",
            f"el archivo tiene {len(draft.trips):,} operaciones cerradas; el límite es "
            f"{MAX_TRADES:,}",
        )
    trips = sorted(draft.trips, key=lambda trip: (trip.exit_time, trip.entry_time))
    sizes = _contract_sizes(trips)
    warnings = list(draft.warnings)
    unusual = sorted(
        {(trip.symbol, sizes[trip.symbol]) for trip in trips if abs(sizes[trip.symbol] - 1) > 0.005}
    )
    if unusual:
        listed = ", ".join(f"{symbol or 'all'} x{size:g}" for symbol, size in unusual)
        warnings.append(f"{CONTRACT_SIZE_WARNING}: {listed}")
    trades: list[Trade] = []
    sides: list[str] = []
    client_pnl: list[float | None] = []
    trade_fees: list[float] = []
    trade_symbols: list[str] = []
    invalid = draft.invalid_rows
    drifting = _drifting_symbols(trips, sizes) if draft.itemised else set()
    if drifting:
        warnings.append(f"{CONVERSION_DRIFT_WARNING}: {', '.join(sorted(drifting))}")
    for trip in trips:
        if trip.exit_time < trip.entry_time:
            invalid += 1  # a trade cannot close before it opens: a damaged row
            continue
        quantity = trip.volume * sizes[trip.symbol]
        if trip.symbol in drifting:
            quantity = trip.volume * _trip_size(trip, sizes[trip.symbol])
        notional = trip.entry_price * quantity
        try:
            trade = Trade(
                entry_time=trip.entry_time,
                exit_time=trip.exit_time,
                quantity=quantity,
                entry_price=trip.entry_price,
                exit_price=trip.exit_price,
                pnl=trip.gross,
                return_pct=trip.gross / notional if notional > 0 else 0.0,
            )
        except ValueError:
            invalid += 1
            continue
        trades.append(trade)
        sides.append(trip.side)
        client_pnl.append(trip.gross)
        trade_fees.append(-(trip.commission + trip.swap + trip.fee))
        trade_symbols.append(trip.symbol)
    if not trades:
        raise ReportFormatError(
            "no_closed_trades",
            "no closed trade has positive prices and volume",
            "ninguna operación cerrada tiene precio y volumen positivos",
        )
    if invalid:
        warnings.append(f"{invalid} row(s) with unreadable or non-positive fields dropped")
    kept = [
        trip
        for trip in trips
        if trip.volume > 0
        and trip.entry_price > 0
        and trip.exit_price > 0
        and trip.exit_time >= trip.entry_time
    ]
    equity_csv, initial, curve_warnings = _balance_curve(draft, kept or trips, fallback_initial)
    warnings.extend(curve_warnings)
    if draft.naive_times:
        warnings.append(NAIVE_TIME_WARNING)
    warnings.append(FLOATING_DRAWDOWN_WARNING)
    fees: dict[str, float] = {}
    for component in ("commission", "swap", "fee"):
        if component in draft.itemised:
            fees[component] = round(sum(getattr(trip, component) for trip in trips), 10)
    metadata = dict(draft.metadata)
    metadata.setdefault("start", min(trip.entry_time for trip in trips).date().isoformat())
    metadata.setdefault("end", max(trip.exit_time for trip in trips).date().isoformat())
    symbols = sorted({trip.symbol for trip in trips if trip.symbol})
    if symbols and "symbol" not in metadata:
        metadata["symbol"] = _clip(", ".join(symbols))
    return ImportedReport(
        source_format=draft.source_format,
        trades=ParsedTrades(
            trades=trades,
            sides=sides,
            client_pnl=client_pnl,
            invalid_rows=invalid,
            warnings=list(warnings),
            fees=trade_fees if draft.itemised else None,
        ),
        equity_csv=equity_csv,
        initial_balance=initial,
        currency=draft.currency,
        fees=fees,
        warnings=warnings,
        metadata=metadata,
        symbols=trade_symbols,
        cash_flows=sorted(
            (item.time, item.amount) for item in draft.cash or [] if item.is_flow and item.amount
        ),
    )


# ---------------------------------------------------------------------------
# Account-tracking exports: Myfxbook, MQL5 signals, FX Blue
# ---------------------------------------------------------------------------

#: A section title after which a tracking export lists positions still open.
_OPEN_SECTIONS = {"open trades", "open orders", "open positions"}
_SIDES = {"buy": "long", "sell": "short"}
_FLOW_ACTIONS = {"deposit", "withdrawal"}


def _flow(amount: float, kind: str) -> float:
    """A deposit as a positive amount, a withdrawal as a negative one."""
    return -abs(amount) if kind == "withdrawal" else abs(amount)


def _is_myfxbook_header(names: set[str]) -> bool:
    return {"open date", "close date", "symbol", "action", "open price", "close price",
            "profit"} <= names and bool(names & {"units/lots", "lots"})  # fmt: skip


def _parse_myfxbook(header: list[str], rows: list[list[str]]) -> _Draft:
    """Myfxbook's "Export" of an account's history (CSV).

    ``Profit`` is the net result in the account's currency (commission and
    swap included), so the gross is rebuilt as profit minus both. Deposits
    and withdrawals are rows whose Action says so, dated by Open Date. The
    positions still open follow an "Open Trades" title and are left out.
    """
    columns = _index(header)
    lots = "units/lots" if "units/lots" in columns else "lots"
    draft = _Draft(MYFXBOOK_CSV, [])
    kept: list[list[str]] = []
    open_rows: list[list[str]] = []
    for position, row in enumerate(rows):
        lowered = [cell.strip().lower() for cell in row[:3]]
        if (lowered and lowered[0] in _OPEN_SECTIONS) or lowered[1:3] == ["ticket", "open date"]:
            open_rows = rows[position:]
            break
        kept.append(row)
    open_times = _parse_times([_cells(row, columns, "open date") for row in kept])
    close_times = _parse_times([_cells(row, columns, "close date") for row in kept])
    itemised: set[str] = {name for name in ("commission", "swap") if name in columns}
    draft.itemised = itemised
    cash: list[_Cash] = []
    for position, row in enumerate(kept):
        action = _cells(row, columns, "action").strip().lower()
        profit = _num(_cells(row, columns, "profit"))
        if action in _FLOW_ACTIONS:
            moment = open_times.values[position]
            if moment is None or profit is None:
                draft.invalid_rows += 1
            elif profit:
                cash.append(_Cash(moment, _flow(profit, action), True))
            continue
        side = _SIDES.get(action)
        if side is None:
            continue  # pending orders and other rows that are not closed trades
        commission = _num(_cells(row, columns, "commission")) or 0.0
        swap = _num(_cells(row, columns, "swap")) or 0.0
        volume = _num(_cells(row, columns, lots))
        entry_price = _num(_cells(row, columns, "open price"))
        exit_price = _num(_cells(row, columns, "close price"))
        entry_time = open_times.values[position]
        exit_time = close_times.values[position]
        if None in (volume, entry_price, exit_price, profit, entry_time, exit_time):
            draft.invalid_rows += 1
            continue
        assert volume is not None and entry_price is not None and exit_price is not None
        assert profit is not None and entry_time is not None and exit_time is not None
        trip = _Trip(
            symbol=_cells(row, columns, "symbol").upper(),
            side=side,
            volume=abs(volume),
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            gross=profit - commission - swap,
            commission=commission,
            swap=swap,
        )
        draft.trips.append(trip)
        cash.append(_Cash(exit_time, trip.net, False))
    if any(item.is_flow for item in cash):
        draft.cash = sorted(cash, key=lambda item: item.time)
    _floating_from_open(draft, open_rows, cash)
    draft.naive_times = True
    return draft


def _floating_from_open(draft: _Draft, open_rows: list[list[str]], cash: list[_Cash]) -> None:
    """The open positions' result a Myfxbook export lists after "Open Trades".

    Stored as the file's own (DECLARED) floating result with the balance the
    rows imply, so the account review can say how much the balance hides.
    """
    header_at = next(
        (i for i, row in enumerate(open_rows) if "profit" in {c.strip().lower() for c in row}),
        None,
    )
    if header_at is None:
        return
    columns = _index(open_rows[header_at])
    profits = [_num(_cells(row, columns, "profit")) for row in open_rows[header_at + 1 :]]
    floating = [value for value in profits if value is not None]
    if not floating:
        return
    draft.metadata["declared_floating_pnl"] = f"{sum(floating):.2f}"
    if any(item.is_flow for item in cash):
        draft.metadata["declared_balance"] = f"{sum(item.amount for item in cash):.2f}"


def _is_mql5_signal_header(header: list[str]) -> bool:
    names = [cell.strip().lower() for cell in header]
    return (
        bool(names)
        and names[0] == "time"
        and names.count("time") == 2
        # The closing price follows the second Time; without it there is no exit.
        and "price" in names[names.index("time", 1) :]
        and {"type", "volume", "symbol", "price", "commission", "swap", "profit"} <= set(names)
    )


def _parse_mql5_signal(header: list[str], rows: list[list[str]]) -> _Draft:
    """The history or positions CSV an MQL5.com signal page exports.

    Columns repeat (``Time``, ``Price``): the first pair is the opening, the
    pair after the second ``Time`` the closing. ``Profit`` is gross, with
    commission and swap in their own columns. ``Balance`` rows are the
    account's deposits, withdrawals and other balance operations.
    """
    names = [cell.strip().lower() for cell in header]
    close_at = names.index("time", 1)
    close_price_at = names.index("price", close_at)
    columns = {
        name: position
        for position, name in enumerate(names)
        if name not in {"time", "price", "volume"}
    }
    draft = _Draft(MQL5_SIGNAL_CSV, [])
    draft.itemised = {"commission", "swap"}

    def cell(row: list[str], at: int) -> str:
        return row[at] if at < len(row) else ""

    open_times = _parse_times([cell(row, 0) for row in rows])
    close_times = _parse_times([cell(row, close_at) for row in rows])
    cash: list[_Cash] = []
    for position, row in enumerate(rows):
        kind = cell(row, columns["type"]).strip().lower()
        profit = _num(cell(row, columns["profit"]))
        if kind == "balance":
            moment = open_times.values[position]
            if moment is None or profit is None:
                draft.invalid_rows += 1
            elif profit:
                cash.append(_Cash(moment, profit, True))
            continue
        side = _SIDES.get(kind)
        if side is None:
            continue  # cancelled pending orders
        volume = _num(cell(row, 2))
        entry_price = _num(cell(row, 4))
        exit_price = _num(cell(row, close_price_at))
        entry_time = open_times.values[position]
        exit_time = close_times.values[position]
        if None in (volume, entry_price, exit_price, profit, entry_time, exit_time):
            draft.invalid_rows += 1
            continue
        assert volume is not None and entry_price is not None and exit_price is not None
        assert profit is not None and entry_time is not None and exit_time is not None
        trip = _Trip(
            symbol=cell(row, columns["symbol"]).upper(),
            side=side,
            volume=abs(volume),
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            gross=profit,
            commission=_num(cell(row, columns["commission"])) or 0.0,
            swap=_num(cell(row, columns["swap"])) or 0.0,
        )
        draft.trips.append(trip)
        cash.append(_Cash(exit_time, trip.net, False))
    if any(item.is_flow for item in cash):
        draft.cash = sorted(cash, key=lambda item: item.time)
    draft.naive_times = open_times.naive or close_times.naive
    return draft


def _is_fxblue_header(names: set[str]) -> bool:
    return {"type", "ticket", "buy/sell", "open price", "close price", "open time",
            "close time", "net profit"} <= names  # fmt: skip


def _parse_fxblue(header: list[str], rows: list[list[str]]) -> _Draft:
    """FX Blue's CSV of an account's orders.

    ``Closed position`` rows are trades (``Profit`` gross, ``Swap`` and
    ``Commission`` apart); ``Deposit`` and ``Withdrawal`` rows move money.
    An export that holds several accounts is read for the one with the most
    closed trades, with a warning: mixing accounts would mix balances.
    """
    columns = _index(header)
    draft = _Draft(FXBLUE_CSV, [])
    draft.itemised = {"commission", "swap"}
    if "account" in columns:
        counts: dict[str, int] = {}
        for row in rows:
            if _cells(row, columns, "type").strip().lower() == "closed position":
                name = _cells(row, columns, "account")
                counts[name] = counts.get(name, 0) + 1
        if len(counts) > 1:
            chosen = max(counts, key=lambda name: counts[name])
            rows = [row for row in rows if _cells(row, columns, "account") == chosen]
            draft.warnings.append(
                f"the file holds {len(counts)} accounts; only the one with the most closed "
                f"trades ({counts[chosen]}) was read"
            )
    open_times = _parse_times([_cells(row, columns, "open time") for row in rows])
    close_times = _parse_times([_cells(row, columns, "close time") for row in rows])
    cash: list[_Cash] = []
    for position, row in enumerate(rows):
        kind = _cells(row, columns, "type").strip().lower()
        if kind in _FLOW_ACTIONS:
            moment = open_times.values[position] or close_times.values[position]
            amount = _num(_cells(row, columns, "net profit"))
            if amount is None:
                amount = _num(_cells(row, columns, "profit"))
            if moment is None or amount is None:
                draft.invalid_rows += 1
            elif amount:
                cash.append(_Cash(moment, _flow(amount, kind), True))
            continue
        if kind != "closed position":
            continue  # open positions and pending orders
        side = _SIDES.get(_cells(row, columns, "buy/sell").strip().lower())
        volume = _num(_cells(row, columns, "lots"))
        entry_price = _num(_cells(row, columns, "open price"))
        exit_price = _num(_cells(row, columns, "close price"))
        profit = _num(_cells(row, columns, "profit"))
        entry_time = open_times.values[position]
        exit_time = close_times.values[position]
        if side is None or None in (volume, entry_price, exit_price, profit, entry_time, exit_time):
            draft.invalid_rows += 1
            continue
        assert volume is not None and entry_price is not None and exit_price is not None
        assert profit is not None and entry_time is not None and exit_time is not None
        trip = _Trip(
            symbol=_cells(row, columns, "symbol").upper(),
            side=side,
            volume=abs(volume),
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            gross=profit,
            commission=_num(_cells(row, columns, "commission")) or 0.0,
            swap=_num(_cells(row, columns, "swap")) or 0.0,
        )
        draft.trips.append(trip)
        cash.append(_Cash(exit_time, trip.net, False))
    if any(item.is_flow for item in cash):
        draft.cash = sorted(cash, key=lambda item: item.time)
    draft.naive_times = True
    return draft


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _sheet_reader(rows: list[list[Any]]) -> _TableReader:
    """A MetaTrader 5 workbook sheet, as the HTML parsers read the report.

    The terminal's "Report > Open XML (MS Office Excel)" export holds the
    same rows as its HTML report; column headers lose their colour, so a
    row is a header when it names the Deals or Positions columns.
    """
    reader = _TableReader()
    width = 0
    for values in rows:
        texts = [_as_text(value) for value in values]
        if not any(texts):
            continue
        names = {text.strip().lower() for text in texts}
        names = {_MT5_DEAL_HEADER_ALIASES.get(name, name) for name in names}
        is_header = {"time", "symbol", "type", "volume"} <= names
        if is_header:
            while texts and not texts[-1]:
                texts.pop()
            width = len(texts)
        elif _is_mt_time(texts[0]):
            # A workbook stores no cell for an empty trailing Comment.
            texts.extend([""] * (width - len(texts)))
        else:
            # Summary rows merge each label and value over several columns:
            # drop the empty cells so every "Label:" sits next to its value.
            texts = [text for text in texts if text]
        attrs = {"bgcolor": "#E5F0FC"} if is_header else {}
        reader.rows.append(_Row(attrs, [_Cell(text, {}) for text in texts]))
    first = reader.rows[0].texts[0] if reader.rows else ""
    reader.title = first
    return reader


def _mt5_workbook(sheets: dict[str, list[list[Any]]]) -> tuple[str, _TableReader] | None:
    """The MetaTrader 5 report in a workbook, as (format, reader), if any."""
    for rows in sheets.values():
        reader = _sheet_reader(rows)
        found = _html_format(reader)
        if found in {MT5_TESTER_HTML, MT5_HISTORY_HTML}:
            return (MT5_TESTER_XLSX if found == MT5_TESTER_HTML else MT5_HISTORY_XLSX), reader
    return None


def _is_zip(data: bytes) -> bool:
    return data.startswith(b"PK\x03\x04")


def _is_optimization_xml(text: str) -> bool:
    head = text[:4000].lower()
    return "urn:schemas-microsoft-com:office:spreadsheet" in head or (
        "<workbook" in head and "tester optimizator results" in text[:20000].lower()
    )


def _unknown_format() -> ReportFormatError:
    return ReportFormatError(
        "unknown_format",
        "the file is not a supported report. Expected: a MetaTrader 5 or 4 report or "
        "statement (HTML, or XLSX for MetaTrader 5), a TradingView list of trades "
        "(CSV or XLSX), a trades CSV from NinjaTrader, QuantConnect, backtesting.py "
        "or vectorbt, or an account history CSV from Myfxbook, FX Blue or an MQL5 signal",
        "el archivo no es un informe compatible. Se espera: un informe o estado de cuenta "
        "de MetaTrader 5 o 4 (HTML, o XLSX de MetaTrader 5), una lista de operaciones de "
        "TradingView (CSV o XLSX), "
        "un CSV de operaciones de NinjaTrader, QuantConnect, backtesting.py o vectorbt, "
        "o el historial en CSV de Myfxbook, FX Blue o una señal de MQL5",
    )


def detect_format(data: bytes, filename: str | None = None) -> str | None:
    """Name the format of ``data`` by its content, or ``None`` if unknown.

    ``filename`` is only a tie-breaker; the content decides.
    """
    return _detect(data)[0]


def _detect(data: bytes) -> tuple[str | None, _TableReader | None]:
    """The format of ``data`` and, for an HTML report, its parsed tables, so
    the import reads a large report once instead of twice."""
    if not data:
        return None, None
    if _is_zip(data):
        try:
            sheets = read_xlsx(data)
        except ParseError:
            return None, None
        if any(rows and _is_tradingview_header(rows[0]) for rows in sheets.values()):
            return TRADINGVIEW_XLSX, None
        workbook = _mt5_workbook(sheets)
        return (workbook[0] if workbook is not None else None), None
    text = decode_text(data)
    stripped = text.lstrip()
    if stripped.startswith("<?xml") or stripped[:200].lower().startswith("<workbook"):
        if _is_optimization_xml(text):
            return MT5_OPTIMIZATION_XML, None
        return None, None
    lowered = stripped[:4000].lower()
    if "<html" in lowered or "<table" in lowered or "<!doctype html" in lowered:
        reader = _read_html(text)
        return _html_format(reader), reader
    header, _, _ = _read_delimited(text)
    if header:
        return _table_format(header), None
    return None, None


def import_report(
    data: bytes, filename: str | None = None, *, initial_balance: float | None = None
) -> ImportedReport:
    """Import one platform file into trades and a closed-trade balance curve.

    ``initial_balance`` is used only when the file itself does not state
    the starting balance (the client's declaration beats the 10 000 default
    but never overrides the file).
    """
    _check_size(data)
    if _is_zip(data):
        # Read the workbook here so that its own errors (too large, damaged)
        # reach the client instead of a generic "unknown format".
        sheets = read_xlsx(data)
        if any(rows and _is_tradingview_header(rows[0]) for rows in sheets.values()):
            return _assemble(_parse_tradingview_xlsx(sheets), initial_balance)
        workbook = _mt5_workbook(sheets)
        if workbook is None:
            raise _unknown_format()
        workbook_format, reader = workbook
        workbook_draft = (
            _parse_mt5_tester(reader)
            if workbook_format == MT5_TESTER_XLSX
            else _parse_mt5_history(reader)
        )
        workbook_draft.source_format = workbook_format
        return _assemble(workbook_draft, initial_balance)
    source_format, html_reader = _detect(data)
    if source_format == MT5_OPTIMIZATION_XML:
        raise ReportFormatError(
            "optimization_file",
            "this is a MetaTrader 5 optimisation export: upload it as the optimisation file, "
            "and the single-test report as the report",
            "esto es una exportación de optimización de MetaTrader 5: súbela como archivo de "
            "optimización, y el informe de la prueba individual como informe",
        )
    if source_format is None:
        raise _unknown_format()
    if initial_balance is not None and not (math.isfinite(initial_balance) and initial_balance > 0):
        raise ReportFormatError(
            "bad_initial_balance",
            "the starting balance must be a positive number",
            "el balance inicial debe ser un número positivo",
        )
    draft: _Draft
    if source_format in {MT5_TESTER_HTML, MT5_HISTORY_HTML, MT4_TESTER_HTML, MT4_STATEMENT_HTML}:
        reader = html_reader if html_reader is not None else _read_html(decode_text(data))
        parser = {
            MT5_TESTER_HTML: _parse_mt5_tester,
            MT5_HISTORY_HTML: _parse_mt5_history,
            MT4_TESTER_HTML: _parse_mt4_tester,
            MT4_STATEMENT_HTML: _parse_mt4_statement,
        }[source_format]
        draft = parser(reader)
    else:
        header, rows, delimiter = _read_delimited(decode_text(data))
        if source_format == TRADINGVIEW_CSV:
            draft = _parse_tradingview(header, [list(row) for row in rows], TRADINGVIEW_CSV,
                                       serial_dates=False)  # fmt: skip
        elif source_format == NINJATRADER_CSV:
            draft = _parse_ninjatrader(header, rows, delimiter)
        elif source_format == QUANTCONNECT_TRADES_CSV:
            draft = _parse_quantconnect(header, rows)
        elif source_format == BACKTESTINGPY_CSV:
            draft = _parse_backtestingpy(header, rows)
        elif source_format == MYFXBOOK_CSV:
            draft = _parse_myfxbook(header, rows)
        elif source_format == MQL5_SIGNAL_CSV:
            draft = _parse_mql5_signal(header, rows)
        elif source_format == FXBLUE_CSV:
            draft = _parse_fxblue(header, rows)
        else:
            draft = _parse_vectorbt(header, rows)
    return _assemble(draft, initial_balance)


_OPTIMIZATION_STANDARD = {
    "pass",
    "result",
    "profit",
    "expected payoff",
    "profit factor",
    "recovery factor",
    "sharpe ratio",
    "custom",
    "equity dd %",
    "trades",
}


#: "MyEA EURUSD,H1 2024.01.01-2024.06.30", as MetaTrader titles the export.
_OPTIMIZATION_TITLE = re.compile(
    r"^(?P<expert>.+?)\s+(?P<symbol>[^\s,]+),(?P<timeframe>[A-Z]{1,2}\d{0,2})\b"
)
#: Passes kept for the parameter-stability check.
MAX_OPTIMIZATION_ROWS = 50_000
#: Columns read per row of an optimisation export; cells placed past it are ignored.
MAX_OPTIMIZATION_COLUMNS = 4_096


def parse_optimization(data: bytes, filename: str | None = None) -> OptimizationSummary:
    """Count the passes of a MetaTrader 5 optimisation export (SpreadsheetML XML).

    The pass count is the number of configurations the optimiser tried,
    which is the honest trial count for the deflated Sharpe ratio. It says
    nothing about returns: the file has no per-period data.
    """
    del filename
    _check_size(data)
    text = decode_text(data)
    if not _is_optimization_xml(text):
        raise ReportFormatError(
            "not_optimization",
            "expected a MetaTrader 5 optimisation export (XML, 'Tester Optimizator Results')",
            "se esperaba una exportación de optimización de MetaTrader 5 (XML, "
            "'Tester Optimizator Results')",
        )
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    root = _xml(body.encode("utf-8"))
    title = next(
        ((node.text or "").strip() for node in root.iter() if _local(node.tag) == "Title"), ""
    )
    named = _OPTIMIZATION_TITLE.match(title)
    rows: list[list[str]] = []
    for sheet in root.iter():
        if _local(sheet.tag) != "Worksheet":
            continue
        for row in sheet.iter():
            if _local(row.tag) != "Row":
                continue
            cells: list[str] = []
            for cell in row:
                if _local(cell.tag) != "Cell":
                    continue
                skip_to = next(
                    (value for key, value in cell.attrib.items() if _local(key) == "Index"), None
                )
                if skip_to is not None and skip_to.isdigit():
                    # A crafted ss:Index="200000000" would pad the row with
                    # millions of empty cells; no export is that wide.
                    target = int(skip_to) if len(skip_to) <= 6 else MAX_OPTIMIZATION_COLUMNS + 1
                    if target > MAX_OPTIMIZATION_COLUMNS:
                        break
                    while len(cells) < target - 1:
                        cells.append("")
                cells.append(
                    "".join(
                        (node.text or "") for node in cell.iter() if _local(node.tag) == "Data"
                    ).strip()
                )
            rows.append(cells)
        if rows:
            break
    header_at = next(
        (i for i, row in enumerate(rows) if row and row[0].strip().lower() == "pass"), None
    )
    if header_at is None:
        raise ReportFormatError(
            "optimization_header",
            "the optimisation file has no 'Pass' header row",
            "el archivo de optimización no tiene la fila de encabezado 'Pass'",
        )
    header = rows[header_at]
    names = [name.strip() for name in header]
    lowered = [name.lower() for name in names]
    if "trades" in lowered:
        parameters = [name for name in names[lowered.index("trades") + 1 :] if name]
    else:
        parameters = [name for name in names if name and name.lower() not in _OPTIMIZATION_STANDARD]
    passes: set[str] = set()
    duplicates = 0
    table: list[dict[str, float]] = []
    for values in rows[header_at + 1 :]:
        if not values or _num(values[0]) is None:
            continue
        if values[0] in passes:
            duplicates += 1
            passes.add(values[0])
            continue
        passes.add(values[0])
        if len(table) < MAX_OPTIMIZATION_ROWS:
            numbers = {
                name: number
                for name, value in zip(names, values, strict=False)
                if name and (number := _num(value)) is not None
            }
            table.append(numbers)
    if not passes:
        raise ReportFormatError(
            "optimization_empty",
            "the optimisation file lists no passes",
            "el archivo de optimización no contiene pasadas",
        )
    warnings: list[str] = []
    if duplicates:
        warnings.append(f"{duplicates} repeated pass number(s) counted once")
    warnings.append(
        "the pass count is the number of configurations the optimiser tried; a genetic "
        "optimisation lists only the passes it evaluated"
    )
    return OptimizationSummary(
        source_format=MT5_OPTIMIZATION_XML,
        passes=len(passes),
        parameters=parameters,
        warnings=warnings,
        table=table,
        expert=named.group("expert") if named else None,
        symbol=named.group("symbol") if named else None,
        timeframe=named.group("timeframe") if named else None,
    )


def _plain(name: str) -> str:
    """``Experts\\Folder\\MyEA.ex5`` and ``myea`` alike: ``MYEA``."""
    base = re.split(r"[\\/]", name.strip())[-1]
    base = re.sub(r"\.(ex5|mq5|ex4|mq4)$", "", base, flags=re.IGNORECASE)
    return "".join(ch for ch in base.upper() if ch.isalnum())


def optimization_mismatch(
    summary: OptimizationSummary, report: dict[str, str]
) -> tuple[str, str, str] | None:
    """``(what, in the export, in the report)`` when the export is not the report's robot.

    Only what both files state is compared: the robot's name, the symbol
    (a broker suffix such as ``EURUSD.m`` still matches), the timeframe and
    the input names. A file that states less is given the benefit of the doubt.
    """
    expert, reported = summary.expert, report.get("strategy")
    if expert and reported and _plain(expert) != _plain(reported):
        return "robot", expert, reported
    symbol, reported = summary.symbol, report.get("symbol")
    if symbol and reported:
        a, b = _plain(symbol), _plain(reported)
        if not (a.startswith(b) or b.startswith(a)):
            return "symbol", symbol, reported
    timeframe = summary.timeframe
    reported = (report.get("period") or "").split(" ")[0]
    if timeframe and reported and timeframe.upper() != reported.upper():
        return "timeframe", timeframe, reported
    listed = report.get("input_names") or ""
    names = {_plain(name) for name in listed.split(",") if name.strip()}
    tried = {_plain(name) for name in summary.parameters}
    if names and tried and not names & tried:
        return "inputs", ", ".join(summary.parameters[:4]), listed
    return None


__all__ = [
    "BACKTESTINGPY_CSV",
    "DEFAULT_INITIAL_BALANCE",
    "MT4_STATEMENT_HTML",
    "MT4_TESTER_HTML",
    "MT5_HISTORY_HTML",
    "MT5_HISTORY_XLSX",
    "MT5_OPTIMIZATION_XML",
    "MT5_TESTER_HTML",
    "MT5_TESTER_XLSX",
    "MQL5_SIGNAL_CSV",
    "MYFXBOOK_CSV",
    "FXBLUE_CSV",
    "NINJATRADER_CSV",
    "QUANTCONNECT_TRADES_CSV",
    "REPORT_FORMATS",
    "optimization_mismatch",
    "TRADINGVIEW_CSV",
    "TRADINGVIEW_XLSX",
    "VECTORBT_CSV",
    "ImportedReport",
    "OptimizationSummary",
    "ReportFormatError",
    "decode_text",
    "detect_format",
    "import_report",
    "parse_optimization",
    "read_xlsx",
]
