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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree

from quant_trade.audit.schema import MAX_TRADES, MAX_UPLOAD_BYTES, ParsedTrades, ParseError
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
MT5_OPTIMIZATION_XML = "mt5_optimization_xml"

#: Every format ``import_report`` turns into trades and a balance curve.
REPORT_FORMATS: tuple[str, ...] = (
    MT5_TESTER_HTML,
    MT5_HISTORY_HTML,
    MT4_TESTER_HTML,
    MT4_STATEMENT_HTML,
    TRADINGVIEW_CSV,
    TRADINGVIEW_XLSX,
    NINJATRADER_CSV,
    QUANTCONNECT_TRADES_CSV,
    BACKTESTINGPY_CSV,
    VECTORBT_CSV,
)

#: Used when the file does not state a starting balance and none is supplied.
DEFAULT_INITIAL_BALANCE = 10_000.0

#: A workbook may not inflate past this many bytes, nor hold more members.
MAX_XLSX_UNCOMPRESSED_BYTES = 40_000_000
MAX_XLSX_MEMBERS = 500

FLOATING_DRAWDOWN_WARNING = (
    "the balance curve is built from closed trades only; it does not show floating "
    "(open-trade) drawdown, so the real drawdown was at least as deep"
)
CONTRACT_SIZE_WARNING = "contract size inferred from reported profit"
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


@dataclass(frozen=True)
class OptimizationSummary:
    """What an optimisation export proves: how many configurations were tried."""

    source_format: str
    passes: int
    parameters: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Decoding and cell values
# ---------------------------------------------------------------------------


def _check_size(data: bytes) -> None:
    if not data or not data.strip():
        raise ReportFormatError("empty_file", "the file is empty", "el archivo está vacío")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ReportFormatError(
            "file_too_large",
            f"the file is {len(data):,} bytes; the limit is {MAX_UPLOAD_BYTES:,}",
            f"el archivo pesa {len(data):,} bytes; el límite es {MAX_UPLOAD_BYTES:,}",
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
    """Decode by BOM, then strict UTF-8, then BOM-less UTF-16, then cp1252."""
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
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


_NUMBER_NOISE = re.compile(r"[\s  $€£¥%]")


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
}
_MT4_CLOSES = {"close", "t/p", "s/l", "close at stop", "close by"}


def _is_mt4_tester_row(texts: list[str]) -> bool:
    return (
        len(texts) in {9, 10}
        and texts[0].isdigit()
        and _is_mt_time(texts[1])
        and texts[2].lower() in _MT4_TYPES
    )


def _is_mt4_statement_trade(texts: list[str]) -> bool:
    return (
        len(texts) >= 14
        and _is_mt_time(texts[1])
        and texts[2].lower() in {"buy", "sell"}
        and _is_mt_time(texts[8])
    )


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
    if any(_is_mt4_statement_trade(row.texts) for row in reader.rows):
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


def _mt5_column_map(header: list[str] | None, width: int) -> dict[str, int]:
    if header is not None:
        names = [text.strip().lower() for text in header]
        if "direction" in names and "balance" in names:
            return {name: index for index, name in enumerate(names) if name}
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
        for lot in queue:
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
        direction = 1.0 if side == "long" else -1.0
        weights = [(deal.price - lot.price) * direction * take for lot, take, *_ in slices]
        total_weight = sum(weights)
        spread = sum(abs(weight) for weight in weights)
        if spread <= 0 or abs(total_weight) < 1e-6 * spread:
            weights = [take for _, take, *_ in slices]
            total_weight = sum(weights)
        for (lot, take, commission, fee, swap), weight in zip(slices, weights, strict=True):
            share = take / volume * cost_share if volume > 0 else 0.0
            self.trips.append(
                _Trip(
                    symbol=deal.symbol,
                    side=side,
                    volume=take,
                    entry_time=lot.time,
                    exit_time=deal.time,
                    entry_price=lot.price,
                    exit_price=deal.price,
                    gross=profit * weight / total_weight if total_weight else 0.0,
                    commission=commission + deal.commission * share,
                    fee=fee + deal.fee * share,
                    swap=swap + deal.swap * share,
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


def _fifo_warnings(fifo: _Fifo) -> list[str]:
    warnings: list[str] = []
    if fifo.hedging:
        warnings.append(
            "hedging account: entries were paired first-in first-out, so per-trade entry "
            "price and holding time are approximate (money results stay exact)"
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


def _parse_mt5_tester(reader: _TableReader) -> _Draft:
    deals, invalid = _mt5_deals(reader)
    labels = _labels(reader.rows)
    draft = _Draft(MT5_TESTER_HTML, [], invalid_rows=invalid)
    draft.itemised = {"commission", "swap"}
    fifo = _Fifo()
    for deal in deals:
        if deal.type in {"buy", "sell"}:
            fifo.apply(deal)
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
    return draft


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
    labels = _labels(reader.rows)
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
        open_positions = _count_opened_not_closed(trade_deals, positions)
        if open_positions:
            draft.warnings.append(
                f"{open_positions} position(s) opened in the report were not closed; excluded"
            )
    else:
        fifo = _Fifo()
        for deal in trade_deals:
            fifo.apply(deal)
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


def _mt4_pairs(rows: list[_Row]) -> dict[str, str]:
    found: dict[str, str] = {}
    for row in rows:
        texts = row.texts
        for index in range(len(texts) - 1):
            if texts[index] in _MT4_LABELS:
                found.setdefault(texts[index], texts[index + 1])
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
                tickets[order] = _Mt4Ticket(
                    "long" if kind == "buy" else "short", size, price, moment
                )
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
    for row in reader.rows:
        texts = row.texts
        if _is_mt4_statement_trade(texts):
            entry_time = _one_time(texts[1])
            exit_time = _one_time(texts[8])
            volume = _num(texts[3])
            entry_price = _num(texts[5])
            exit_price = _num(texts[9])
            profit = _num(texts[13])
            if None in (entry_time, exit_time, volume, entry_price, exit_price, profit):
                draft.invalid_rows += 1
                continue
            assert entry_time is not None and exit_time is not None
            trip = _Trip(
                symbol=texts[4].upper(),
                side="long" if texts[2].lower() == "buy" else "short",
                volume=volume or 0.0,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price or 0.0,
                exit_price=exit_price or 0.0,
                gross=profit or 0.0,
                commission=_num(texts[10]) or 0.0,
                fee=_num(texts[11]) or 0.0,
                swap=_num(texts[12]) or 0.0,
            )
            draft.trips.append(trip)
            cash.append(_Cash(exit_time, trip.net, False))
            continue
        if (
            len(texts) in {4, 5}
            and _is_mt_time(texts[1])
            and texts[2].lower() in {"balance", "credit"}
        ):
            moment = _one_time(texts[1])
            amount = _num(texts[-1])
            if moment is None or amount is None:
                draft.invalid_rows += 1
            elif texts[2].lower() == "credit":
                credits += 1
            else:
                cash.append(_Cash(moment, amount, True))
            continue
        if any(text.lower() == "cancelled" for text in texts) and _is_mt_time(
            texts[1] if len(texts) > 1 else ""
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
    if not lines:
        return [], [], ","
    head = lines[0]
    delimiter = max((",", ";", "\t"), key=head.count)
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = [[cell.strip() for cell in row] for row in reader]
    header = rows[0]
    return header, [row for row in rows[1:] if any(cell for cell in row)], delimiter


_XML_FORBIDDEN = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


def _xml(data: bytes) -> ElementTree.Element:
    if _XML_FORBIDDEN.search(data):
        raise ReportFormatError(
            "xml_doctype",
            "the file declares a document type, which is refused for safety",
            "el archivo declara un tipo de documento, que se rechaza por seguridad",
        )
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ReportFormatError(
            "bad_xml", f"the XML could not be read: {exc}", f"no se pudo leer el XML: {exc}"
        ) from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if letters is None:
        return -1
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
    except zipfile.BadZipFile as exc:
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
            return _xml(archive.read(name))

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


def _sheet_rows(sheet: ElementTree.Element, shared: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
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
            draft.initial_note = "inferred from cumulative P&L and cumulative P&L %"
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
    return {trip.symbol: sizes.get(trip.symbol, 1.0) for trip in trips}


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
    trade_symbols: list[str] = []
    invalid = draft.invalid_rows
    for trip in trips:
        quantity = trip.volume * sizes[trip.symbol]
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
        trip for trip in trips if trip.volume > 0 and trip.entry_price > 0 and trip.exit_price > 0
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
        ),
        equity_csv=equity_csv,
        initial_balance=initial,
        currency=draft.currency,
        fees=fees,
        warnings=warnings,
        metadata=metadata,
        symbols=trade_symbols,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
        "statement (HTML), a TradingView list of trades (CSV or XLSX), or a trades CSV "
        "from NinjaTrader, QuantConnect, backtesting.py or vectorbt",
        "el archivo no es un informe compatible. Se espera: un informe o estado de cuenta "
        "de MetaTrader 5 o 4 (HTML), una lista de operaciones de TradingView (CSV o XLSX) "
        "o un CSV de operaciones de NinjaTrader, QuantConnect, backtesting.py o vectorbt",
    )


def detect_format(data: bytes, filename: str | None = None) -> str | None:
    """Name the format of ``data`` by its content, or ``None`` if unknown.

    ``filename`` is only a tie-breaker; the content decides.
    """
    if not data:
        return None
    if _is_zip(data):
        try:
            sheets = read_xlsx(data)
        except ParseError:
            return None
        if any(rows and _is_tradingview_header(rows[0]) for rows in sheets.values()):
            return TRADINGVIEW_XLSX
        return None
    text = decode_text(data)
    stripped = text.lstrip()
    if stripped.startswith("<?xml") or stripped[:200].lower().startswith("<workbook"):
        if _is_optimization_xml(text):
            return MT5_OPTIMIZATION_XML
        return None
    lowered = stripped[:4000].lower()
    if "<html" in lowered or "<table" in lowered or "<!doctype html" in lowered:
        return _html_format(_read_html(text))
    header, _, _ = _read_delimited(text)
    if header:
        return _table_format(header)
    return None


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
        if not any(rows and _is_tradingview_header(rows[0]) for rows in sheets.values()):
            raise _unknown_format()
        return _assemble(_parse_tradingview_xlsx(sheets), initial_balance)
    source_format = detect_format(data, filename)
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
        reader = _read_html(decode_text(data))
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
                    while len(cells) < int(skip_to) - 1:
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
    for values in rows[header_at + 1 :]:
        if not values or _num(values[0]) is None:
            continue
        if values[0] in passes:
            duplicates += 1
        passes.add(values[0])
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
    )


__all__ = [
    "BACKTESTINGPY_CSV",
    "DEFAULT_INITIAL_BALANCE",
    "MT4_STATEMENT_HTML",
    "MT4_TESTER_HTML",
    "MT5_HISTORY_HTML",
    "MT5_OPTIMIZATION_XML",
    "MT5_TESTER_HTML",
    "NINJATRADER_CSV",
    "QUANTCONNECT_TRADES_CSV",
    "REPORT_FORMATS",
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
