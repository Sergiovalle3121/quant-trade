"""Historial continuo: the continuity core of the continuous track record.

Each upload of an account statement is reduced to a *snapshot* of canonical
records (closed trades, cash rows, positions listed open, months of a
monthly table) made only of the printed cell texts. The next upload is
compared with the previous snapshot (``compare_uploads``): it is refused
when it cannot be the same continuous record (another account, another
format or currency, a partial period, no new operations, rows in the
future) and otherwise yields an event, ``uploaded`` when every operation
already recorded is still there unchanged and ``mismatch`` with the count
and kind of the operations that differ. Every upload becomes one entry of a
hash chain (``chain_entry``, ``entry_hash``, ``verify_chain``) of flat
strings and integers, and the sealed stretch of the record is a head cut
of the latest file (``sealed_stretch_bytes``).

Nothing here stores or logs an account number, a name, a broker, a comment,
a file name or an audit id: the account keys are compared in memory by the
caller's local variables and never enter a snapshot, an entry or an
outcome. Tester reports are never accepted. Everything is deterministic:
no clock (``now`` is a parameter), no floats in records (cell texts read as
``Decimal`` when compared), no text copied from the file beyond symbols,
sides, references, kinds and printed figures.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from quant_trade.audit import importers
from quant_trade.audit.factsheet import MonthlyGrid
from quant_trade.audit.forensics import edit, families, header, money, rows
from quant_trade.audit.forensics.review import METHOD_VERSION
from quant_trade.audit.importers import ImportedReport
from quant_trade.evidence.canonical_json import canonical_dumps

__all__ = [
    "EVENT_MISMATCH",
    "EVENT_UPLOADED",
    "FLOW_KINDS",
    "KIND_FLOW",
    "KIND_MONTH",
    "KIND_OPEN",
    "KIND_TRADE",
    "MONTHLY_FORMAT",
    "OPERATION_KINDS",
    "RECIPE_VERSION",
    "REFUSAL_CODES",
    "SUPPORTED_FAMILIES",
    "Figures",
    "Operation",
    "Outcome",
    "Record",
    "Refusal",
    "Snapshot",
    "chain_entry",
    "clock_offset",
    "compare_uploads",
    "entry_hash",
    "load_snapshot",
    "sealed_stretch_bytes",
    "snapshot",
    "snapshot_json",
    "snapshot_monthly",
    "symbol_map",
    "trades_sha256",
    "verify_chain",
]

RECIPE_VERSION = "track-seal-1"

KIND_TRADE = "t"
KIND_FLOW = "f"
KIND_OPEN = "o"
KIND_MONTH = "m"

FLOW_DEPOSIT = "deposit"
FLOW_WITHDRAWAL = "withdrawal"
FLOW_BALANCE = "balance"
FLOW_CREDIT = "credit"
FLOW_KINDS = (FLOW_DEPOSIT, FLOW_WITHDRAWAL, FLOW_BALANCE, FLOW_CREDIT)

EVENT_UPLOADED = "uploaded"
EVENT_MISMATCH = "mismatch"
REFUSAL_CODES = (
    "account_differs",
    "format_changed",
    "currency_changed",
    "partial_statement",
    "already_recorded",
    "cutoff_not_advanced",
    "future_rows",
    "earlier_rows",
)
OPERATION_KINDS = ("deleted", "inserted", "changed", "open_changed")

#: Account families the continuous record accepts (never a tester).
SUPPORTED_FAMILIES = frozenset(
    {
        families.MT4_STATEMENT,
        families.MT5_HISTORY,
        families.MYFXBOOK,
        families.MQL5_SIGNAL,
        families.FXBLUE,
    }
)
#: The ``source_format`` of a snapshot built from a monthly returns table.
MONTHLY_FORMAT = "monthly_table"

#: A later export may start this much after the previous one (D13).
PARTIAL_GRACE = timedelta(seconds=60)
#: Server clocks run up to 14 h ahead of UTC; one more minute of slack.
FUTURE_GRACE = timedelta(hours=14, seconds=60)
#: The largest server-clock offset a re-export may show (§6.4).
MAX_OFFSET = timedelta(hours=14)
#: The share of matched trades one whole-minute offset must explain.
OFFSET_SHARE = Decimal("0.9")
#: Sealed stretch: the day after the record was opened (§6.7; the extra
#: ``+ 14 h`` for server clocks ahead of UTC is an open question).
SEALED_MARGIN = timedelta(days=1)

_RECORD_KEYS: dict[str, tuple[str, ...]] = {
    KIND_TRADE: (
        "k",
        "ref",
        "sym",
        "side",
        "vol",
        "open",
        "close",
        "px_in",
        "px_out",
        "pnl",
        "comm",
        "swap",
        "fee",
    ),
    KIND_FLOW: ("k", "ref", "at", "amount", "kind"),
    KIND_OPEN: ("k", "ref", "sym", "side", "vol", "open", "px_in"),
    KIND_MONTH: ("k", "ym", "ret"),
}
_COMPARED: dict[str, tuple[str, ...]] = {
    KIND_TRADE: (
        "sym",
        "side",
        "vol",
        "open",
        "close",
        "px_in",
        "px_out",
        "pnl",
        "comm",
        "swap",
        "fee",
    ),
    KIND_FLOW: ("at", "amount", "kind"),
}
_NUMERIC = frozenset({"vol", "px_in", "px_out", "pnl", "comm", "swap", "fee", "amount", "ret"})
_TIME_FIELDS = ("open", "close", "at")
_SIDES = {"buy": "long", "sell": "short"}


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    """One canonical record: strings only, the cell texts without
    separators (§6.2). Fields a kind does not use stay ``""``."""

    k: str
    ref: str = ""
    sym: str = ""
    side: str = ""
    vol: str = ""
    open: str = ""
    close: str = ""
    px_in: str = ""
    px_out: str = ""
    pnl: str = ""
    comm: str = ""
    swap: str = ""
    fee: str = ""
    at: str = ""
    amount: str = ""
    kind: str = ""
    ym: str = ""
    ret: str = ""

    @property
    def end(self) -> str:
        """When the record is settled: close, cash time, open or month."""
        return {KIND_TRADE: self.close, KIND_FLOW: self.at, KIND_OPEN: self.open}.get(
            self.k, self.ym
        )

    def as_dict(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in _RECORD_KEYS[self.k]}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Record:
        kind = str(data.get("k", ""))
        if kind not in _RECORD_KEYS:
            raise ValueError("unknown_record_kind")
        return cls(**{key: str(data.get(key, "")) for key in _RECORD_KEYS[kind]})


@dataclass(frozen=True)
class Snapshot:
    """What one upload contributes to the record (§6.1)."""

    source_format: str
    family: str
    currency: str
    closed: tuple[Record, ...]
    cash: tuple[Record, ...]
    open_listed: tuple[Record, ...]
    months: tuple[Record, ...]
    first_at: str
    cutoff: str
    header_date: str

    @property
    def last_month(self) -> str:
        return max((month.ym for month in self.months), default="")

    def as_dict(self) -> dict[str, object]:
        return {
            "source_format": self.source_format,
            "family": self.family,
            "currency": self.currency,
            "closed": [record.as_dict() for record in self.closed],
            "cash": [record.as_dict() for record in self.cash],
            "open_listed": [record.as_dict() for record in self.open_listed],
            "months": [record.as_dict() for record in self.months],
            "first_at": self.first_at,
            "cutoff": self.cutoff,
            "header_date": self.header_date,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Snapshot:
        def records(name: str) -> tuple[Record, ...]:
            listed = data.get(name, [])
            if not isinstance(listed, list):
                raise ValueError("bad_snapshot")
            return tuple(Record.from_dict(item) for item in listed)

        return cls(
            source_format=str(data.get("source_format", "")),
            family=str(data.get("family", "")),
            currency=str(data.get("currency", "")),
            closed=records("closed"),
            cash=records("cash"),
            open_listed=records("open_listed"),
            months=records("months"),
            first_at=str(data.get("first_at", "")),
            cutoff=str(data.get("cutoff", "")),
            header_date=str(data.get("header_date", "")),
        )


@dataclass(frozen=True)
class Refusal:
    """The new upload cannot continue the record; no event is written."""

    code: str


@dataclass(frozen=True)
class Operation:
    """One operation of the previous snapshot that the new upload changed."""

    kind: str
    k: str
    ref: str
    at: str
    fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "k": self.k,
            "ref": self.ref,
            "at": self.at,
            "fields": list(self.fields),
        }


@dataclass(frozen=True)
class Figures:
    """The upload's measured figures (all integers)."""

    new_closed: int = 0
    new_flows: int = 0
    clock_offset_minutes: int = 0
    symbols_renamed: int = 0
    clock_offset_resolved: int = 1

    def as_dict(self) -> dict[str, int]:
        return {
            "new_closed": self.new_closed,
            "new_flows": self.new_flows,
            "clock_offset_minutes": self.clock_offset_minutes,
            "symbols_renamed": self.symbols_renamed,
            "clock_offset_resolved": self.clock_offset_resolved,
        }


@dataclass(frozen=True)
class Outcome:
    """The event of one accepted upload."""

    event: str
    count: int
    operations: tuple[Operation, ...] = ()
    figures: Figures = field(default_factory=Figures)

    def detail_json(self) -> str:
        return canonical_dumps([operation.as_dict() for operation in self.operations])


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def snapshot(data: bytes, source_format: str | None, imported: ImportedReport | None) -> Snapshot:
    """The canonical records of one account statement.

    ``imported`` is the report the store already holds for the upload; it
    supplies the currency the importer read and, for an MT5 history without
    a Positions table (older builds and XLSX exports, where the printed
    cells are not the trades), the trades the importer paired, with
    ``ref = ""`` (a weaker record, documented as such).
    """
    family = families.family_of(source_format)
    if family in families.TESTER_FAMILIES:
        raise ValueError("tester_not_allowed")
    if family not in SUPPORTED_FAMILIES:
        raise ValueError("format_not_supported")
    table = rows.load(data, source_format)
    hint = imported.currency if imported is not None else None
    found = header.read_header(table, hint)
    currency = (hint or found.currency or "").strip().upper()
    if family == families.MT4_STATEMENT:
        closed, cash, open_listed = _mt4_records(table)
    elif family == families.MT5_HISTORY:
        closed, cash, open_listed = _mt5_records(table, imported)
    elif family == families.MYFXBOOK:
        closed, cash, open_listed = _myfxbook_records(table)
    elif family == families.MQL5_SIGNAL:
        closed, cash, open_listed = _mql5_records(table)
    else:
        closed, cash, open_listed = _fxblue_records(table)
    header_date = _iso(found.report_date) if found.report_date is not None else ""
    return _build(source_format or "", family, currency, closed, cash, open_listed, (), header_date)


def snapshot_monthly(grid: MonthlyGrid, *, currency: str = "") -> Snapshot:
    """The months of a monthly returns table, as records ``k = "m"``.

    The grid holds fractions as floats; ``ret`` is the percentage written
    from the float's shortest text, the same way on every upload."""
    months: list[Record] = []
    for stamp, ret in zip(grid.frame["timestamp"], grid.frame["ret"], strict=True):
        moment = stamp.to_pydatetime()
        value = (Decimal(repr(float(ret))) * 100).normalize()
        months.append(
            Record(k=KIND_MONTH, ym=f"{moment.year:04d}-{moment.month:02d}", ret=_text(value))
        )
    months.sort(key=lambda record: record.ym)
    first_at = f"{months[0].ym}-01T00:00:00Z" if months else ""
    cutoff = _month_end_iso(months[-1].ym) if months else ""
    return Snapshot(
        source_format=MONTHLY_FORMAT,
        family=families.MONTHLY,
        currency=currency.strip().upper(),
        closed=(),
        cash=(),
        open_listed=(),
        months=tuple(months),
        first_at=first_at,
        cutoff=cutoff,
        header_date="",
    )


def snapshot_json(snap: Snapshot) -> str:
    """The ``snapshot_json`` column: canonical JSON of the records."""
    return canonical_dumps(snap.as_dict())


def load_snapshot(text: str) -> Snapshot:
    """A snapshot read back from its ``snapshot_json`` column."""
    return Snapshot.from_dict(json.loads(text))


def trades_sha256(snap: Snapshot) -> str:
    """SHA-256 of the sorted closed trades, cash rows and months up to the
    cutoff: one hash per set of operations, whatever the row order of the
    file."""
    settled = [
        record.as_dict()
        for record in snap.closed + snap.cash + snap.months
        if record.end and record.end <= snap.cutoff
    ]
    settled.sort(key=canonical_dumps)
    return hashlib.sha256(canonical_dumps(settled).encode("utf-8")).hexdigest()


def _build(
    source_format: str,
    family: str,
    currency: str,
    closed: Iterable[Record],
    cash: Iterable[Record],
    open_listed: Iterable[Record],
    months: Iterable[Record],
    header_date: str,
) -> Snapshot:
    closed_sorted = tuple(sorted(closed, key=lambda r: (r.close, r.open, r.ref, r.sym, r.vol)))
    cash_sorted = tuple(sorted(cash, key=lambda r: (r.at, r.ref, r.amount)))
    open_sorted = tuple(sorted(open_listed, key=lambda r: (r.open, r.ref, r.sym, r.vol)))
    starts = [r.open for r in closed_sorted if r.open] + [r.at for r in cash_sorted if r.at]
    ends = [r.close for r in closed_sorted if r.close] + [r.at for r in cash_sorted if r.at]
    return Snapshot(
        source_format=source_format,
        family=family,
        currency=currency,
        closed=closed_sorted,
        cash=cash_sorted,
        open_listed=open_sorted,
        months=tuple(sorted(months, key=lambda r: r.ym)),
        first_at=min(starts, default=""),
        cutoff=max(ends, default=""),
        header_date=header_date,
    )


# --- MetaTrader 4 statement -------------------------------------------------


def _mt4_records(
    table: rows.RawTable,
) -> tuple[list[Record], list[Record], list[Record]]:
    closed: list[Record] = []
    cash: list[Record] = []
    open_listed: list[Record] = []
    for row in table.rows:
        if row.kind == rows.KIND_MT4_TRADE:
            columns = rows.mt4_columns(table, row)
            closed.append(
                Record(
                    k=KIND_TRADE,
                    ref=row.text(0).strip(),
                    sym=row.text(columns["symbol"]).strip().upper(),
                    side=_side(row.text(columns["type"])),
                    vol=_figure(row.text(columns["size"])),
                    open=_time(row.text(columns["open_time"])),
                    close=_time(row.text(columns["close_time"])),
                    px_in=_figure(row.text(columns["open_price"])),
                    px_out=_figure(row.text(columns["close_price"])),
                    pnl=_figure(row.text(columns["profit"])),
                    comm=_figure(row.text(columns["commission"]))
                    if "commission" in columns
                    else "",
                    swap=_figure(row.text(columns["swap"])) if "swap" in columns else "",
                    fee=_figure(row.text(columns["taxes"])) if "taxes" in columns else "",
                )
            )
        elif row.kind in {rows.KIND_MT4_CASH, rows.KIND_MT4_CREDIT}:
            at_column = rows.mt4_columns(table, row)["open_time"]
            amount = ""
            for text in row.texts[at_column + 2 :]:
                if money.parse_money(text) is not None:
                    amount = text
            if not amount:
                continue
            kind = FLOW_CREDIT if row.kind == rows.KIND_MT4_CREDIT else _flow_kind_by_sign(amount)
            cash.append(
                Record(
                    k=KIND_FLOW,
                    ref=row.text(0).strip(),
                    at=_time(row.text(at_column)),
                    amount=_figure(amount),
                    kind=kind,
                )
            )
        elif row.kind == rows.KIND_MT4_OPEN:
            columns = rows.mt4_columns(table, row)
            open_listed.append(
                Record(
                    k=KIND_OPEN,
                    ref=row.text(0).strip(),
                    sym=row.text(columns["symbol"]).strip().upper(),
                    side=_side(row.text(columns["type"])),
                    vol=_figure(row.text(columns["size"])),
                    open=_time(row.text(columns["open_time"])),
                    px_in=_figure(row.text(columns["open_price"])),
                )
            )
    return closed, cash, open_listed


# --- MetaTrader 5 history ---------------------------------------------------


def _mt5_records(
    table: rows.RawTable, imported: ImportedReport | None
) -> tuple[list[Record], list[Record], list[Record]]:
    closed: list[Record] = []
    cash: list[Record] = []
    open_listed: list[Record] = []
    for row in table.rows:
        if row.kind == rows.KIND_MT5_POSITION:
            columns = rows.mt5_position_columns(table, row)
            closed.append(
                Record(
                    k=KIND_TRADE,
                    ref=row.text(columns["position"]).strip(),
                    sym=row.text(columns["symbol"]).strip().upper(),
                    side=_side(row.text(columns["type"])),
                    vol=_figure(row.text(columns["volume"])),
                    open=_time(row.text(columns["open"])),
                    close=_time(row.text(columns["close"])),
                    px_in=_figure(row.text(columns["price"])),
                    px_out=_figure(row.text(columns["close_price"])),
                    pnl=_figure(row.text(columns["profit"])),
                    comm=_figure(row.text(columns["commission"])),
                    swap=_figure(row.text(columns["swap"])),
                    fee="",
                )
            )
        elif row.kind == rows.KIND_MT5_DEAL:
            columns = rows.mt5_columns(table, row)
            if row.text(columns["type"]).lower() != "balance":
                continue
            amount = row.text(columns["profit"])
            if money.parse_money(amount) is None:
                continue
            cash.append(
                Record(
                    k=KIND_FLOW,
                    ref=row.text(columns.get("deal", 1)).strip(),
                    at=_time(row.text(columns["time"])),
                    amount=_figure(amount),
                    kind=_flow_kind_by_sign(amount),
                )
            )
        elif row.kind == rows.KIND_MT5_OPEN_POSITION:
            open_listed.append(
                Record(
                    k=KIND_OPEN,
                    ref=row.text(1).strip(),
                    sym=row.text(2).strip().upper(),
                    side=_side(row.text(3)),
                    vol=_figure(row.text(4)),
                    open=_time(row.text(0)),
                    px_in=_figure(row.text(5)),
                )
            )
    if not closed:
        if imported is None:
            raise ValueError("imported_required")
        closed = _paired_records(imported)
    return closed, cash, open_listed


def _paired_records(imported: ImportedReport) -> list[Record]:
    """Closed trades from the importer's own deal pairing: no reference,
    figures written from its numbers (the weaker MT5 record)."""
    parsed = imported.trades
    found: list[Record] = []
    for index, trade in enumerate(parsed.trades):
        gross = parsed.client_pnl[index] if index < len(parsed.client_pnl) else None
        fee = parsed.fees[index] if parsed.fees is not None and index < len(parsed.fees) else None
        found.append(
            Record(
                k=KIND_TRADE,
                ref="",
                sym=(imported.symbols[index] if index < len(imported.symbols) else "").upper(),
                side=parsed.sides[index] if index < len(parsed.sides) else "",
                vol=_float_text(trade.quantity),
                open=_iso(trade.entry_time),
                close=_iso(trade.exit_time),
                px_in=_float_text(trade.entry_price),
                px_out=_float_text(trade.exit_price),
                pnl=_float_text(gross if gross is not None else trade.pnl),
                comm="",
                swap="",
                fee=_float_text(-fee) if fee is not None else "",
            )
        )
    return found


# --- Myfxbook, MQL5 signal, FX Blue -----------------------------------------


def _csv_columns(names: Sequence[str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for index, name in enumerate(names):
        columns.setdefault(name.strip().lower(), index)
    return columns


def _cell(texts: Sequence[str], columns: Mapping[str, int], name: str) -> str:
    index = columns.get(name)
    return texts[index] if index is not None and index < len(texts) else ""


def _column_times(values: Sequence[str]) -> list[str]:
    parsed = importers._parse_times(list(values)).values
    return [_iso(moment) if moment is not None else "" for moment in parsed]


def _myfxbook_records(
    table: rows.RawTable,
) -> tuple[list[Record], list[Record], list[Record]]:
    columns = _csv_columns(table.header)
    lots = "units/lots" if "units/lots" in columns else "lots"
    body = [row.texts for row in table.rows[1:]]
    kept, open_rows = body, []
    for position, texts in enumerate(body):
        lowered = [text.strip().lower() for text in texts[:3]]
        if (lowered and lowered[0] in importers._OPEN_SECTIONS) or lowered[1:3] == [
            "ticket",
            "open date",
        ]:
            kept, open_rows = body[:position], body[position:]
            break
    opens = _column_times([_cell(texts, columns, "open date") for texts in kept])
    closes = _column_times([_cell(texts, columns, "close date") for texts in kept])
    closed: list[Record] = []
    cash: list[Record] = []
    for position, texts in enumerate(kept):
        action = _cell(texts, columns, "action").strip().lower()
        if action in importers._FLOW_ACTIONS:
            cash.append(
                Record(
                    k=KIND_FLOW,
                    ref=_cell(texts, columns, "ticket").strip(),
                    at=opens[position],
                    amount=_figure(_cell(texts, columns, "profit")),
                    kind=action,
                )
            )
        elif action in _SIDES:
            closed.append(
                Record(
                    k=KIND_TRADE,
                    ref=_cell(texts, columns, "ticket").strip(),
                    sym=_cell(texts, columns, "symbol").strip().upper(),
                    side=_SIDES[action],
                    vol=_figure(_cell(texts, columns, lots)),
                    open=opens[position],
                    close=closes[position],
                    px_in=_figure(_cell(texts, columns, "open price")),
                    px_out=_figure(_cell(texts, columns, "close price")),
                    pnl=_figure(_cell(texts, columns, "profit")),
                    comm=_figure(_cell(texts, columns, "commission")),
                    swap=_figure(_cell(texts, columns, "swap")),
                    fee="",
                )
            )
    open_listed = _myfxbook_open(open_rows)
    return closed, cash, open_listed


def _myfxbook_open(open_rows: list[tuple[str, ...]]) -> list[Record]:
    header_at = next(
        (i for i, texts in enumerate(open_rows) if "profit" in {t.strip().lower() for t in texts}),
        None,
    )
    if header_at is None:
        return []
    columns = _csv_columns(open_rows[header_at])
    listed = open_rows[header_at + 1 :]
    opens = _column_times([_cell(texts, columns, "open date") for texts in listed])
    lots = "units/lots" if "units/lots" in columns else "lots"
    found: list[Record] = []
    for position, texts in enumerate(listed):
        action = _cell(texts, columns, "action").strip().lower()
        if action not in _SIDES:
            continue
        found.append(
            Record(
                k=KIND_OPEN,
                ref=_cell(texts, columns, "ticket").strip(),
                sym=_cell(texts, columns, "symbol").strip().upper(),
                side=_SIDES[action],
                vol=_figure(_cell(texts, columns, lots)),
                open=opens[position],
                px_in=_figure(_cell(texts, columns, "open price")),
            )
        )
    return found


def _mql5_records(
    table: rows.RawTable,
) -> tuple[list[Record], list[Record], list[Record]]:
    names = [text.strip().lower() for text in table.header]
    close_at = names.index("time", 1)
    close_price_at = names.index("price", close_at)
    open_price_at = names.index("price")
    volume_at = names.index("volume")
    columns = {
        name: position
        for position, name in reversed(list(enumerate(names)))
        if name not in {"time", "price", "volume"}
    }
    body = [row.texts for row in table.rows[1:]]
    opens = _column_times([texts[0] if texts else "" for texts in body])
    closes = _column_times([_at(texts, close_at) for texts in body])
    closed: list[Record] = []
    cash: list[Record] = []
    for position, texts in enumerate(body):
        kind = _cell(texts, columns, "type").strip().lower()
        profit = _cell(texts, columns, "profit")
        if kind == "balance":
            if money.parse_money(profit) is None:
                continue
            cash.append(
                Record(
                    k=KIND_FLOW,
                    ref="",
                    at=opens[position],
                    amount=_figure(profit),
                    kind=_flow_kind_by_sign(profit),
                )
            )
        elif kind in _SIDES:
            closed.append(
                Record(
                    k=KIND_TRADE,
                    ref="",
                    sym=_cell(texts, columns, "symbol").strip().upper(),
                    side=_SIDES[kind],
                    vol=_figure(_at(texts, volume_at)),
                    open=opens[position],
                    close=closes[position],
                    px_in=_figure(_at(texts, open_price_at)),
                    px_out=_figure(_at(texts, close_price_at)),
                    pnl=_figure(profit),
                    comm=_figure(_cell(texts, columns, "commission")),
                    swap=_figure(_cell(texts, columns, "swap")),
                    fee="",
                )
            )
    return closed, cash, []


def _fxblue_records(
    table: rows.RawTable,
) -> tuple[list[Record], list[Record], list[Record]]:
    columns = _csv_columns(table.header)
    body = [row.texts for row in table.rows[1:]]
    if "account" in columns:
        counts: Counter[str] = Counter(
            _cell(texts, columns, "account")
            for texts in body
            if _cell(texts, columns, "type").strip().lower() == "closed position"
        )
        if len(counts) > 1:
            chosen = max(sorted(counts), key=lambda name: counts[name])
            body = [texts for texts in body if _cell(texts, columns, "account") == chosen]
    opens = _column_times([_cell(texts, columns, "open time") for texts in body])
    closes = _column_times([_cell(texts, columns, "close time") for texts in body])
    closed: list[Record] = []
    cash: list[Record] = []
    open_listed: list[Record] = []
    for position, texts in enumerate(body):
        kind = _cell(texts, columns, "type").strip().lower()
        if kind in importers._FLOW_ACTIONS:
            amount = _cell(texts, columns, "net profit")
            if money.parse_money(amount) is None:
                amount = _cell(texts, columns, "profit")
            cash.append(
                Record(
                    k=KIND_FLOW,
                    ref=_cell(texts, columns, "ticket").strip(),
                    at=opens[position] or closes[position],
                    amount=_figure(amount),
                    kind=kind,
                )
            )
            continue
        side = _SIDES.get(_cell(texts, columns, "buy/sell").strip().lower(), "")
        if kind == "closed position":
            closed.append(
                Record(
                    k=KIND_TRADE,
                    ref=_cell(texts, columns, "ticket").strip(),
                    sym=_cell(texts, columns, "symbol").strip().upper(),
                    side=side,
                    vol=_figure(_cell(texts, columns, "lots")),
                    open=opens[position],
                    close=closes[position],
                    px_in=_figure(_cell(texts, columns, "open price")),
                    px_out=_figure(_cell(texts, columns, "close price")),
                    pnl=_figure(_cell(texts, columns, "profit")),
                    comm=_figure(_cell(texts, columns, "commission")),
                    swap=_figure(_cell(texts, columns, "swap")),
                    fee="",
                )
            )
        elif kind == "open position":
            open_listed.append(
                Record(
                    k=KIND_OPEN,
                    ref=_cell(texts, columns, "ticket").strip(),
                    sym=_cell(texts, columns, "symbol").strip().upper(),
                    side=side,
                    vol=_figure(_cell(texts, columns, "lots")),
                    open=opens[position],
                    px_in=_figure(_cell(texts, columns, "open price")),
                )
            )
    return closed, cash, open_listed


# --- shared text helpers ----------------------------------------------------


def _at(texts: Sequence[str], index: int) -> str:
    return texts[index] if 0 <= index < len(texts) else ""


def _side(text: str) -> str:
    return _SIDES.get(text.strip().lower(), "")


def _figure(text: str) -> str:
    """The printed figure without separators, ``""`` when not a number."""
    return money.normalise_text(text)


def _text(value: Decimal) -> str:
    return money.as_text(value)


def _float_text(value: float) -> str:
    return money.as_text(Decimal(repr(float(value))))


def _canon(value: str) -> str:
    """A figure in one spelling (``1.08150`` and ``1.0815`` compare equal),
    or the text itself when it is not a number."""
    number = money.parse_money(value)
    if number is None:
        return value
    return money.as_text(number.normalize())


def _flow_kind_by_sign(amount: str) -> str:
    number = money.parse_money(amount)
    if number is None or number == 0:
        return FLOW_BALANCE
    return FLOW_DEPOSIT if number > 0 else FLOW_WITHDRAWAL


def _iso(moment: datetime) -> str:
    return _naive(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def _time(text: str) -> str:
    parsed = importers._one_time(text.strip())
    return _iso(parsed) if parsed is not None else ""


def _naive(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def _dt(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")


def _month_end_iso(ym: str) -> str:
    year, month = int(ym[:4]), int(ym[5:7])
    first_next = datetime(year + (month // 12), month % 12 + 1, 1)
    return _iso(first_next - timedelta(seconds=1))


# ---------------------------------------------------------------------------
# Tolerances: clock offset and symbol renames (§6.4)
# ---------------------------------------------------------------------------


def _matched_trades(prev: Snapshot, new: Snapshot) -> list[tuple[Record, Record]]:
    """Closed trades of both snapshots paired by reference, or, when a side
    has none, by (symbol, side, volume, prices, P&L)."""
    by_ref = all(r.ref for r in prev.closed) and all(r.ref for r in new.closed)

    def key(record: Record) -> tuple[str, ...]:
        if by_ref:
            return (record.ref,)
        return (
            record.sym,
            record.side,
            _canon(record.vol),
            _canon(record.px_in),
            _canon(record.px_out),
            _canon(record.pnl),
        )

    return _pair_by(prev.closed, new.closed, key)[0]


def _pair_by(
    previous: Sequence[Record],
    current: Sequence[Record],
    key: Callable[[Record], tuple[str, ...]],
) -> tuple[list[tuple[Record, Record]], list[Record], list[Record]]:
    """Pairs of records sharing a key (in time order within a key), plus
    the unpaired records of each side."""
    groups_prev: dict[tuple[str, ...], list[Record]] = {}
    groups_new: dict[tuple[str, ...], list[Record]] = {}
    for record in previous:
        groups_prev.setdefault(key(record), []).append(record)
    for record in current:
        groups_new.setdefault(key(record), []).append(record)
    pairs: list[tuple[Record, Record]] = []
    unpaired_prev: list[Record] = []
    unpaired_new: list[Record] = []
    for group_key in sorted(set(groups_prev) | set(groups_new)):
        left = sorted(groups_prev.get(group_key, []), key=lambda r: (r.end, r.open, r.ref))
        right = sorted(groups_new.get(group_key, []), key=lambda r: (r.end, r.open, r.ref))
        pairs.extend(zip(left, right, strict=False))
        unpaired_prev.extend(left[len(right) :])
        unpaired_new.extend(right[len(left) :])
    return pairs, unpaired_prev, unpaired_new


def clock_offset(prev: Snapshot, new: Snapshot) -> tuple[int, bool]:
    """``(minutes, resolved)``: the whole-minute shift of the new export's
    clock against the previous one, when one shift of at most 14 h explains
    at least 90 % of the matched trades; else ``(0, False)`` and the
    differences count as changes."""
    pairs = _matched_trades(prev, new)
    seconds: Counter[int] = Counter()
    for old, current in pairs:
        if old.open and current.open:
            seconds[int((_dt(current.open) - _dt(old.open)).total_seconds())] += 1
    if not seconds:
        return 0, True
    mode, count = sorted(seconds.items(), key=lambda item: (-item[1], abs(item[0]), item[0]))[0]
    total = sum(seconds.values())
    if (
        mode % 60 == 0
        and abs(mode) <= MAX_OFFSET.total_seconds()
        and Decimal(count) >= OFFSET_SHARE * Decimal(total)
    ):
        return mode // 60, True
    return 0, False


def symbol_map(prev: Snapshot, new: Snapshot, offset: int = 0) -> dict[str, str]:
    """``{previous symbol: new symbol}`` over the matched trades, accepted
    only when it is a consistent bijection; ``{}`` otherwise."""
    del offset  # the pairing is by reference or by figures, never by time
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for old, current in _matched_trades(prev, new):
        forward.setdefault(old.sym, set()).add(current.sym)
        backward.setdefault(current.sym, set()).add(old.sym)
    if any(len(targets) != 1 for targets in forward.values()) or any(
        len(sources) != 1 for sources in backward.values()
    ):
        return {}
    return {old: next(iter(targets)) for old, targets in forward.items() if old not in targets}


def _normalised(snap: Snapshot, minutes: int, renames: Mapping[str, str]) -> Snapshot:
    """The snapshot with every time moved by ``minutes`` and every renamed
    symbol written as the previous export wrote it."""
    if not minutes and not renames:
        return snap
    delta = timedelta(minutes=minutes)
    inverse = {new: old for old, new in renames.items()}

    def shift(iso: str) -> str:
        return _iso(_dt(iso) + delta) if iso else ""

    def fix(record: Record) -> Record:
        values = record.as_dict()
        for name in _TIME_FIELDS:
            if name in values:
                values[name] = shift(values[name])
        if "sym" in values:
            values["sym"] = inverse.get(values["sym"], values["sym"])
        return Record.from_dict(values)

    return Snapshot(
        source_format=snap.source_format,
        family=snap.family,
        currency=snap.currency,
        closed=tuple(fix(r) for r in snap.closed),
        cash=tuple(fix(r) for r in snap.cash),
        open_listed=tuple(fix(r) for r in snap.open_listed),
        months=snap.months,
        first_at=shift(snap.first_at),
        cutoff=shift(snap.cutoff),
        header_date=snap.header_date,
    )


# ---------------------------------------------------------------------------
# compare_uploads (§6.3, D13)
# ---------------------------------------------------------------------------


def compare_uploads(
    prev: Snapshot,
    new: Snapshot,
    *,
    now: datetime,
    prev_key: str | None,
    new_key: str | None,
    prev_at: datetime | None = None,
) -> Refusal | Outcome:
    """Whether ``new`` continues the record ``prev`` describes, and how.

    ``prev_key`` and ``new_key`` are the account keys the caller read into
    local variables (``rows.account_key``); they are compared here and go
    no further. ``prev_at`` is when the previous upload was made (Rigor's
    clock), which decides whether the last month of a monthly table may
    still change.
    """
    if prev_key and new_key and prev_key != new_key:
        return Refusal("account_differs")
    if new.family != prev.family or new.source_format != prev.source_format:
        # The HTML and workbook readers of one platform do not print the
        # same references and volumes, so a record keeps one export format.
        return Refusal("format_changed")
    if new.currency != prev.currency:
        return Refusal("currency_changed")
    minutes, resolved = clock_offset(prev, new)
    renames = symbol_map(prev, new, minutes)
    current = _normalised(new, -minutes, renames)
    if (
        prev.first_at
        and current.first_at
        and _dt(current.first_at) > _dt(prev.first_at) + PARTIAL_GRACE
    ):
        return Refusal("partial_statement")
    if current.cutoff == prev.cutoff and trades_sha256(current) == trades_sha256(prev):
        # The same export again (daily exporters re-save a quiet day): not a
        # break and not a new link in the chain.
        return Refusal("already_recorded")
    if current.cutoff <= prev.cutoff:
        return Refusal("cutoff_not_advanced")
    horizon = _iso(_naive(now) + FUTURE_GRACE)
    if current.cutoff > horizon or any(
        moment > horizon
        for record in current.closed + current.cash + current.open_listed
        for moment in (record.open, record.close, record.at)
        if moment
    ):
        return Refusal("future_rows")
    if prev_key is None or new_key is None:
        first5 = sorted(prev.closed, key=lambda r: (r.close, r.ref))[:5]
        identities = {_identity(r) for r in current.closed}
        if any(_identity(r) not in identities for r in first5):
            return Refusal("account_differs")
    operations: list[Operation] = []
    for kind in (KIND_TRADE, KIND_FLOW):
        previous = [r for r in prev.closed + prev.cash if r.k == kind]
        settled = [r for r in current.closed + current.cash if r.k == kind and r.end <= prev.cutoff]
        operations.extend(_diff(previous, settled, kind))
    operations.extend(_open_changes(prev.open_listed, current, prev.cutoff))
    operations.extend(_month_changes(prev, current, prev_at))
    operations.sort(key=lambda op: (OPERATION_KINDS.index(op.kind), op.k, op.at, op.ref))
    if (
        operations
        and prev.first_at
        and all(op.kind == "inserted" and op.at < prev.first_at for op in operations)
    ):
        # A wider export that starts before the first upload: everything the
        # record holds matches, so it is not a break; extending a record
        # backwards is a decision for its owner, not a silent re-anchoring.
        return Refusal("earlier_rows")
    figures = Figures(
        new_closed=sum(1 for r in current.closed if r.close > prev.cutoff),
        new_flows=sum(1 for r in current.cash if r.at > prev.cutoff),
        clock_offset_minutes=minutes,
        symbols_renamed=len(renames),
        clock_offset_resolved=1 if resolved else 0,
    )
    event = EVENT_UPLOADED if not operations else EVENT_MISMATCH
    return Outcome(
        event=event, count=len(operations), operations=tuple(operations), figures=figures
    )


def _identity(record: Record) -> tuple[str, ...]:
    """What names a trade when no account number can: instrument, side,
    volume and both times. Money is left out so an edited price or P&L on an
    early trade surfaces as a change, not as another account."""
    return (record.sym, record.side, _canon(record.vol), record.open, record.close)


def _diff(previous: list[Record], settled: list[Record], kind: str) -> list[Operation]:
    by_ref = bool(previous or settled) and all(r.ref for r in previous + settled)

    def key(record: Record) -> tuple[str, ...]:
        if by_ref:
            return (record.ref,)
        if kind == KIND_TRADE:
            return (record.open, record.sym, record.side, _canon(record.vol))
        return (record.at,)

    pairs, deleted, inserted = _pair_by(previous, settled, key)
    found: list[Operation] = []
    for old, current in pairs:
        fields = tuple(
            name
            for name in _COMPARED[kind]
            if not _same(name, getattr(old, name), getattr(current, name))
        )
        if fields:
            found.append(Operation("changed", kind, old.ref, old.end, fields))
    found.extend(Operation("deleted", kind, r.ref, r.end) for r in deleted)
    found.extend(Operation("inserted", kind, r.ref, r.end) for r in inserted)
    return found


def _same(name: str, old: str, current: str) -> bool:
    if name in _NUMERIC:
        return _canon(old) == _canon(current)
    return old == current


def _open_changes(listed: Sequence[Record], current: Snapshot, prev_cutoff: str) -> list[Operation]:
    """Positions the previous export listed open must be accounted for by
    positions still open plus pieces closed since the previous cutoff (MT4
    ``from #`` remainders, swap close/open re-tickets). Volumes are summed
    per (open time, symbol, side, open price): a strategy that opens several
    identical positions in one second (one per magic number, as FX Blue
    exports show) closes them at different times."""

    def key(record: Record) -> tuple[str, str, str, str]:
        return (record.open, record.sym, record.side, _canon(record.px_in))

    accounted: dict[tuple[str, str, str, str], Decimal] = {}
    since = [record for record in current.closed if record.close > prev_cutoff]
    for record in current.open_listed + tuple(since):
        volume = money.parse_money(record.vol)
        if volume is not None:
            accounted[key(record)] = accounted.get(key(record), Decimal(0)) + volume
    groups: dict[tuple[str, str, str, str], list[Record]] = {}
    for record in listed:
        groups.setdefault(key(record), []).append(record)
    found: list[Operation] = []
    for group_key, records in groups.items():
        volumes = [money.parse_money(record.vol) for record in records]
        total = sum((volume for volume in volumes if volume is not None), Decimal(0))
        if any(volume is None for volume in volumes) or accounted.get(group_key) != total:
            found.extend(
                Operation("open_changed", KIND_OPEN, record.ref, record.open) for record in records
            )
    return found


def _month_changes(prev: Snapshot, current: Snapshot, prev_at: datetime | None) -> list[Operation]:
    if not prev.months:
        return []
    last = prev.last_month
    current_months = {record.ym: record.ret for record in current.months}
    inside_last = prev_at is None or _naive(prev_at).strftime("%Y-%m") == last
    found: list[Operation] = []
    for record in prev.months:
        value = current_months.get(record.ym)
        if value is not None and _canon(value) == _canon(record.ret):
            continue
        if record.ym < last or (record.ym == last and not inside_last):
            kind = "deleted" if value is None else "changed"
            found.append(Operation(kind, KIND_MONTH, "", record.ym, ("ret",) if value else ()))
    return found


# ---------------------------------------------------------------------------
# Chain (§6.5, D14)
# ---------------------------------------------------------------------------


def chain_entry(
    *,
    position: int,
    at: datetime,
    cutoff: str,
    closed_count: int,
    flow_count: int,
    currency: str,
    source_format: str,
    trades_sha256: str,
    event_kind: str,
    event_count: int,
    previous_hash: str = "",
    method_version: str = METHOD_VERSION,
) -> dict[str, str | int]:
    """The flat chain entry of one upload (strings and integers only)."""
    return {
        "v": RECIPE_VERSION,
        "position": int(position),
        "at": _iso(at),
        "cutoff": cutoff,
        "closed_count": int(closed_count),
        "flow_count": int(flow_count),
        "currency": currency,
        "source_format": source_format,
        "method_version": method_version,
        "trades_sha256": trades_sha256,
        "event_kind": event_kind,
        "event_count": int(event_count),
        "previous_hash": previous_hash,
    }


def entry_hash(entry: Mapping[str, object]) -> str:
    """``sha256(canonical_dumps(entry))``; a ``hash`` key, if present, is
    left out of the text hashed."""
    body = {key: value for key, value in entry.items() if key != "hash"}
    return hashlib.sha256(canonical_dumps(body).encode("utf-8")).hexdigest()


def verify_chain(entries: Sequence[Mapping[str, object]]) -> tuple[bool, int | None]:
    """Recompute every hash and link; ``(True, None)`` when the chain holds,
    else ``(False, position of the first entry that does not)``."""
    previous = ""
    for index, entry in enumerate(entries):
        position = entry.get("position")
        expected_position = index + 1
        bad = (
            position != expected_position
            or entry.get("previous_hash") != previous
            or entry.get("hash") != entry_hash(entry)
        )
        if bad:
            return False, int(position) if isinstance(position, int) else expected_position
        previous = str(entry.get("hash", ""))
    return True, None


# ---------------------------------------------------------------------------
# Sealed stretch (§6.7)
# ---------------------------------------------------------------------------


def sealed_stretch_bytes(
    latest_bytes: bytes,
    source_format: str | None,
    opened_at: datetime,
    *,
    imported: ImportedReport | None = None,
) -> tuple[bytes, Decimal | None]:
    """The latest statement cut to the trades opened from ``S = opened_at +
    1 day`` on, and the balance ``B0`` the stretch starts from.

    ``B0`` is the importer's starting balance of the full file plus the
    cash rows and the net result of the trades settled before ``S``. The
    importer's starting balance already includes the deposits made before
    the first trade, so those are not added twice; and a cash row dated
    between ``S`` and the first kept trade is folded into ``B0`` and cut
    (the importer would otherwise take it as the whole starting balance).
    Whether ``S`` should carry an extra ``+ 14 h`` for server clocks ahead
    of UTC is open (§10).
    """
    snap = snapshot(latest_bytes, source_format, imported)
    if imported is None:
        imported = importers.import_report(latest_bytes)
    if imported.initial_balance is None:
        return latest_bytes, None
    start = _naive(opened_at) + SEALED_MARGIN
    start_iso = _iso(start)
    first_entry = min((r.open for r in snap.closed if r.open), default="")
    flows = [r for r in snap.cash if r.kind != FLOW_CREDIT]
    counted_opening = any(r.at <= first_entry for r in flows) if first_entry else False
    balance = Decimal(repr(float(imported.initial_balance)))
    for flow in flows:
        if flow.at < start_iso and not (counted_opening and flow.at <= first_entry):
            balance += _signed_flow(flow)
    for trade in snap.closed:
        if trade.close and trade.close < start_iso:
            balance += _net(trade)
    kept_entry = min((r.open for r in snap.closed if r.open >= start_iso), default="")
    flows_from = start
    if kept_entry:
        folded = [r for r in flows if start_iso <= r.at <= kept_entry]
        if folded:
            balance += sum((_signed_flow(r) for r in folded), Decimal(0))
            flows_from = _dt(kept_entry) + timedelta(seconds=1)
    cut = edit.cut_statement(
        latest_bytes, keep_from=start, blank_balances=True, keep_flows_from=flows_from
    )
    return cut, balance.quantize(Decimal("0.01"))


def _signed_flow(record: Record) -> Decimal:
    amount = money.parse_money(record.amount) or Decimal(0)
    if record.kind == FLOW_DEPOSIT:
        return abs(amount)
    if record.kind == FLOW_WITHDRAWAL:
        return -abs(amount)
    return amount


def _net(record: Record) -> Decimal:
    total = Decimal(0)
    for name in ("pnl", "comm", "swap", "fee"):
        value = money.parse_money(getattr(record, name))
        if value is not None:
            total += value
    return total
