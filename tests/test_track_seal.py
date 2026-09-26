"""Historial continuo: snapshots, upload comparison, chain and sealed stretch.

Every test is offline and deterministic: the fixtures, tiny inline CSVs in
the tracking exports' own shapes, and ``now`` passed by hand.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from quant_trade.audit import importers
from quant_trade.audit import track_seal as seal
from quant_trade.audit.factsheet import MonthlyGrid
from quant_trade.audit.forensics import edit, families, rows
from quant_trade.audit.schema import parse_equity_csv
from quant_trade.evidence.canonical_json import canonical_dumps

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = "mt4_statement.htm"
MT5 = "mt5_history.html"
PRIVATE_TEXT = (
    "12345678",
    "Demo Trader",
    "Synthetic",
    "SyntheticBroker",
    "FixtureEA",
    "to #",
    "from #",
    "[tp]",
    "[sl]",
    "Credit In",
    "cancelled",
    ".htm",
)
NOW = datetime(2024, 3, 9, tzinfo=UTC)
D1 = datetime(2024, 3, 4, 23, 59, 59)
D2 = datetime(2024, 3, 5, 23, 59, 59)
KEY = "same"


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _snapshot(data: bytes, *, imported: bool = True) -> seal.Snapshot:
    fmt = importers.detect_format(data)
    report = importers.import_report(data) if imported else None
    return seal.snapshot(data, fmt, report)


def _table(data: bytes) -> rows.RawTable:
    return rows.load(data, importers.detect_format(data))


def _row(table: rows.RawTable, kind: str, ref: str, column: int = 0) -> rows.RawRow:
    return next(row for row in table.rows if row.kind == kind and row.text(column) == ref)


def _compare(prev: bytes, new: bytes, **kwargs: object) -> seal.Refusal | seal.Outcome:
    options = {"now": NOW, "prev_key": KEY, "new_key": KEY}
    options.update(kwargs)
    return seal.compare_uploads(_snapshot(prev), _snapshot(new), **options)  # type: ignore[arg-type]


def _shift_trades(data: bytes, delta: timedelta) -> bytes:
    """Every closed trade's open and close time moved by ``delta``."""
    table = _table(data)
    for row in table.rows:
        if row.kind == rows.KIND_MT4_TRADE:
            columns = rows.mt4_columns(table, row)
            cells = (columns["open_time"], columns["close_time"])
        elif row.kind == rows.KIND_MT5_POSITION:
            columns = rows.mt5_position_columns(table, row)
            cells = (columns["open"], columns["close"])
        else:
            continue
        for column in cells:
            data = edit.shift_time(data, row.index, column, delta)
    return data


def _uploaded(outcome: seal.Refusal | seal.Outcome) -> seal.Outcome:
    assert isinstance(outcome, seal.Outcome), outcome
    assert outcome.event == seal.EVENT_UPLOADED and outcome.count == 0, outcome
    return outcome


def _one_mismatch(outcome: seal.Refusal | seal.Outcome, kind: str, k: str) -> seal.Operation:
    assert isinstance(outcome, seal.Outcome), outcome
    assert outcome.event == seal.EVENT_MISMATCH, outcome
    assert outcome.count == 1 and len(outcome.operations) == 1, outcome
    (operation,) = outcome.operations
    assert operation.kind == kind and operation.k == k, operation
    return operation


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def test_mt4_snapshot_records_match_the_printed_cells() -> None:
    snap = _snapshot(_bytes(MT4))
    assert snap.family == families.MT4_STATEMENT and snap.currency == "USD"
    assert snap.first_at == "2024-03-01T08:00:00Z" and snap.cutoff == "2024-03-07T10:00:00Z"
    assert snap.header_date == "2024-03-08T18:30:00Z"
    assert [record.as_dict() for record in snap.closed] == [
        {
            "k": "t",
            "ref": "1000003",
            "sym": "XAUUSD",
            "side": "short",
            "vol": "0.50",
            "open": "2024-03-04T10:00:00Z",
            "close": "2024-03-04T13:02:44Z",
            "px_in": "2080.10",
            "px_out": "2084.60",
            "pnl": "-225.00",
            "comm": "-3.50",
            "swap": "0.00",
            "fee": "0.00",
        },
        {
            "k": "t",
            "ref": "1000002",
            "sym": "EURUSD",
            "side": "long",
            "vol": "1.00",
            "open": "2024-03-04T09:15:02Z",
            "close": "2024-03-05T11:40:31Z",
            "px_in": "1.08500",
            "px_out": "1.08700",
            "pnl": "200.00",
            "comm": "-7.00",
            "swap": "-6.20",
            "fee": "0.00",
        },
        {
            "k": "t",
            "ref": "1000005",
            "sym": "XAUUSD",
            "side": "short",
            "vol": "0.50",
            "open": "2024-03-04T10:00:00Z",
            "close": "2024-03-06T09:30:00Z",
            "px_in": "2080.10",
            "px_out": "2083.00",
            "pnl": "-145.00",
            "comm": "-3.50",
            "swap": "-4.10",
            "fee": "0.00",
        },
    ]
    assert [record.as_dict() for record in snap.cash] == [
        {
            "k": "f",
            "ref": "1000001",
            "at": "2024-03-01T08:00:00Z",
            "amount": "10000.00",
            "kind": "deposit",
        },
        {
            "k": "f",
            "ref": "1000006",
            "at": "2024-03-06T10:00:00Z",
            "amount": "500.00",
            "kind": "credit",
        },
        {
            "k": "f",
            "ref": "1000007",
            "at": "2024-03-07T10:00:00Z",
            "amount": "-1000.00",
            "kind": "withdrawal",
        },
    ]
    assert snap.open_listed == () and snap.months == ()


def test_mt5_snapshot_records_match_the_printed_cells() -> None:
    snap = _snapshot(_bytes(MT5))
    assert snap.family == families.MT5_HISTORY and snap.currency == "USD"
    assert [record.as_dict() for record in snap.closed] == [
        {
            "k": "t",
            "ref": "5003",
            "sym": "XAUUSD",
            "side": "short",
            "vol": "0.02",
            "open": "2024-03-04T09:20:10Z",
            "close": "2024-03-04T13:02:44Z",
            "px_in": "2080.10",
            "px_out": "2084.60",
            "pnl": "-9.00",
            "comm": "-0.28",
            "swap": "0.00",
            "fee": "",
        },
        {
            "k": "t",
            "ref": "5001",
            "sym": "EURUSD",
            "side": "long",
            "vol": "0.10",
            "open": "2024-03-04T09:15:02Z",
            "close": "2024-03-05T11:40:31Z",
            "px_in": "1.08500",
            "px_out": "1.08700",
            "pnl": "20.00",
            "comm": "-0.70",
            "swap": "-0.62",
            "fee": "",
        },
    ]
    assert [record.as_dict() for record in snap.cash] == [
        {
            "k": "f",
            "ref": "9000",
            "at": "2024-03-01T08:00:00Z",
            "amount": "1000.00",
            "kind": "deposit",
        },
        {
            "k": "f",
            "ref": "9005",
            "at": "2024-03-06T10:00:00Z",
            "amount": "-100.00",
            "kind": "withdrawal",
        },
    ]
    assert snap.cutoff == "2024-03-06T10:00:00Z"
    # The same records without the importer's report (the Positions table is printed).
    assert _snapshot(_bytes(MT5), imported=False).closed == snap.closed


def test_mt5_without_positions_table_uses_the_importers_pairing() -> None:
    data = _bytes(MT5)
    table = _table(data)
    stripped = data
    for row in reversed(table.kind(rows.KIND_MT5_POSITION)):
        stripped = edit.delete_row(stripped, row.index)
    report = importers.import_report(stripped)
    snap = seal.snapshot(stripped, importers.MT5_HISTORY_HTML, report)
    assert [(r.ref, r.sym, r.side, r.open, r.close) for r in snap.closed] == [
        ("", "XAUUSD", "short", "2024-03-04T09:20:10Z", "2024-03-04T13:02:44Z"),
        ("", "EURUSD", "long", "2024-03-04T09:15:02Z", "2024-03-05T11:40:31Z"),
    ]
    with pytest.raises(ValueError, match="imported_required"):
        seal.snapshot(stripped, importers.MT5_HISTORY_HTML, None)


def test_tester_and_unknown_formats_are_refused() -> None:
    with pytest.raises(ValueError, match="tester_not_allowed"):
        _snapshot(_bytes("mt5_tester.html"))
    with pytest.raises(ValueError, match="tester_not_allowed"):
        _snapshot(_bytes("mt4_tester.htm"))
    with pytest.raises(ValueError, match="format_not_supported"):
        _snapshot(_bytes("tradingview_g1.csv"))


@pytest.mark.parametrize("name", (MT4, MT5))
def test_snapshot_json_round_trips_and_holds_nothing_private(name: str) -> None:
    snap = _snapshot(_bytes(name))
    text = seal.snapshot_json(snap)
    assert seal.load_snapshot(text) == snap
    assert text == seal.snapshot_json(_snapshot(_bytes(name)))
    assert json.loads(text) == json.loads(canonical_dumps(snap.as_dict()))
    for private in PRIVATE_TEXT:
        assert private not in text, private
    leaves = re.findall(r'"[^"]*"', text)
    assert all(not leaf.strip('"').startswith(("Deposit", "Withdrawal")) for leaf in leaves)


def test_trades_sha256_is_one_hash_per_set_of_operations() -> None:
    data = _bytes(MT4)
    snap = _snapshot(data)
    digest = seal.trades_sha256(snap)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    settled = sorted(
        (record.as_dict() for record in snap.closed + snap.cash if record.end <= snap.cutoff),
        key=canonical_dumps,
    )
    expected = hashlib.sha256(
        json.dumps(settled, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert digest == expected
    # A different set of operations (one trade less) is another hash; the
    # header date is not part of it.
    table = _table(data)
    fewer = edit.delete_row(data, _row(table, rows.KIND_MT4_TRADE, "1000003").index)
    assert seal.trades_sha256(_snapshot(fewer)) != digest
    redated = edit.set_header_date(data, datetime(2024, 3, 9, 1, 0))
    assert seal.trades_sha256(_snapshot(redated)) == digest


# ---------------------------------------------------------------------------
# Sequences on the fixtures: cut(D1) -> cut(D2) -> full
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", (MT4, MT5))
def test_tail_cuts_then_the_full_file_are_uploaded_without_operations(name: str) -> None:
    full = _bytes(name)
    cut1 = edit.cut_statement(full, keep_to=D1)
    cut2 = edit.cut_statement(full, keep_to=D2)
    first = _uploaded(_compare(cut1, cut2))
    assert first.figures.new_closed == 1 and first.figures.clock_offset_resolved == 1
    second = _uploaded(_compare(cut2, full))
    assert second.figures.new_closed == (1 if name == MT4 else 0)
    assert second.figures.new_flows == (2 if name == MT4 else 1)
    assert second.figures.clock_offset_minutes == 0 and second.figures.symbols_renamed == 0
    assert second.detail_json() == "[]"
    # Determinism: the same inputs give the same outcome.
    assert _compare(cut2, full) == second


def test_mt4_seeded_alterations_give_exactly_one_operation() -> None:
    full = _bytes(MT4)
    cut2 = edit.cut_statement(full, keep_to=D2)
    table = _table(full)
    trade = _row(table, rows.KIND_MT4_TRADE, "1000003")
    profit = rows.mt4_columns(table, trade)["profit"]

    deleted = _one_mismatch(_compare(cut2, edit.delete_row(full, trade.index)), "deleted", "t")
    assert deleted.ref == "1000003" and deleted.at == "2024-03-04T13:02:44Z"

    edited = edit.set_cell(full, trade.index, profit, "-225.01")
    changed = _one_mismatch(_compare(cut2, edited), "changed", "t")
    assert changed.ref == "1000003" and changed.fields == ("pnl",)

    copied = edit.duplicate_row(full, trade.index, {0: "1000009"}, shift=timedelta(minutes=1))
    inserted = _one_mismatch(_compare(cut2, copied), "inserted", "t")
    assert inserted.ref == "1000009" and inserted.at == "2024-03-04T13:03:44Z"

    # The withdrawal of the fixture is after the cut: the removal is seeded
    # against the full file, with a later trade so the cutoff advances.
    later = edit.duplicate_row(
        full,
        _row(table, rows.KIND_MT4_TRADE, "1000002").index,
        {0: "1000010"},
        shift=timedelta(days=4),
    )
    removed = _one_mismatch(
        _compare(
            full, edit.drop_cash_row(later, "withdrawal"), now=datetime(2024, 3, 10, tzinfo=UTC)
        ),
        "deleted",
        "f",
    )
    assert removed.ref == "1000007" and removed.at == "2024-03-07T10:00:00Z"
    detail = json.loads(_compare(cut2, edited).detail_json())  # type: ignore[union-attr]
    assert detail == [
        {
            "kind": "changed",
            "k": "t",
            "ref": "1000003",
            "at": "2024-03-04T13:02:44Z",
            "fields": ["pnl"],
        }
    ]


def test_mt5_seeded_alterations_give_exactly_one_operation() -> None:
    full = _bytes(MT5)
    cut2 = edit.cut_statement(full, keep_to=D2)
    table = _table(full)
    position = _row(table, rows.KIND_MT5_POSITION, "5003", 1)
    profit = rows.mt5_position_columns(table, position)["profit"]

    deleted = _one_mismatch(_compare(cut2, edit.delete_row(full, position.index)), "deleted", "t")
    assert deleted.ref == "5003"

    edited = edit.set_cell(full, position.index, profit, "-9.01")
    changed = _one_mismatch(_compare(cut2, edited), "changed", "t")
    assert changed.ref == "5003" and changed.fields == ("pnl",)

    copied = edit.duplicate_row(full, position.index, {1: "5009"}, shift=timedelta(minutes=1))
    inserted = _one_mismatch(_compare(cut2, copied), "inserted", "t")
    assert inserted.ref == "5009"

    later = edit.duplicate_row(full, position.index, {1: "5010"}, shift=timedelta(days=4))
    removed = _one_mismatch(
        _compare(
            full, edit.drop_cash_row(later, "withdrawal"), now=datetime(2024, 3, 10, tzinfo=UTC)
        ),
        "deleted",
        "f",
    )
    assert removed.ref == "9005"


@pytest.mark.parametrize("name", (MT4, MT5))
def test_a_whole_minute_clock_offset_is_a_figure_not_an_event(name: str) -> None:
    full = _bytes(name)
    cut2 = edit.cut_statement(full, keep_to=D2)
    shifted = edit.shift_all_times(full, timedelta(minutes=120))
    outcome = _uploaded(_compare(cut2, shifted))
    assert outcome.figures.clock_offset_minutes == 120
    assert outcome.figures.clock_offset_resolved == 1
    assert seal.clock_offset(_snapshot(cut2), _snapshot(shifted)) == (120, True)
    # Half a minute is not a server clock: unresolved, and the rows differ
    # (the trades alone are moved, so the export still starts where it did).
    odd = _shift_trades(full, timedelta(seconds=90))
    assert seal.clock_offset(_snapshot(cut2), _snapshot(odd)) == (0, False)
    outcome_odd = _compare(cut2, odd)
    assert isinstance(outcome_odd, seal.Outcome)
    assert outcome_odd.event == seal.EVENT_MISMATCH
    assert outcome_odd.figures.clock_offset_resolved == 0


@pytest.mark.parametrize("name", (MT4, MT5))
def test_a_symbol_rename_is_a_figure_not_an_event(name: str) -> None:
    full = _bytes(name)
    cut2 = edit.cut_statement(full, keep_to=D2)
    renamed = edit.rename_symbol(full, "EURUSD", "EURUSD.pro")
    assert seal.symbol_map(_snapshot(cut2), _snapshot(renamed)) == {"EURUSD": "EURUSD.PRO"}
    outcome = _uploaded(_compare(cut2, renamed))
    assert outcome.figures.symbols_renamed == 1
    assert outcome.figures.clock_offset_minutes == 0


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_refusals_in_order() -> None:
    full = _bytes(MT4)
    cut2 = edit.cut_statement(full, keep_to=D2)
    assert _compare(cut2, full, prev_key="1", new_key="2") == seal.Refusal("account_differs")
    assert _compare(cut2, _bytes(MT5)) == seal.Refusal("format_changed")
    other = dataclasses.replace(_snapshot(full), currency="EUR")
    assert seal.compare_uploads(
        _snapshot(cut2), other, now=NOW, prev_key=KEY, new_key=KEY
    ) == seal.Refusal("currency_changed")
    head = edit.cut_statement(full, keep_from=datetime(2024, 3, 4, 9, 30))
    assert _compare(cut2, head) == seal.Refusal("partial_statement")
    assert _compare(full, full) == seal.Refusal("already_recorded")
    assert _compare(full, cut2) == seal.Refusal("cutoff_not_advanced")
    assert _compare(cut2, full, now=datetime(2024, 3, 5, tzinfo=UTC)) == seal.Refusal("future_rows")
    # A key on one side only still compares the earliest trades.
    assert _uploaded(_compare(cut2, full, prev_key=None))
    for code in ("account_differs", "format_changed", "currency_changed", "partial_statement"):
        assert code in seal.REFUSAL_CODES


def test_the_same_export_again_is_already_recorded_not_a_break() -> None:
    full = _bytes(MT4)
    # A re-save with a later report date and no new row: same trades, same cutoff.
    resaved = edit.set_header_date(
        full, datetime(2024, 3, 9, 7, 0), source_format=importers.MT4_STATEMENT_HTML
    )
    assert _compare(full, resaved) == seal.Refusal("already_recorded")
    # The same cutoff with a different set of trades is still a refusal of its own.
    table = _table(full)
    trade = _row(table, rows.KIND_MT4_TRADE, "1000003")
    edited = edit.set_cell(full, trade.index, rows.mt4_columns(table, trade)["profit"], "9.99")
    assert _compare(full, edited) == seal.Refusal("cutoff_not_advanced")


def test_a_workbook_after_a_web_page_is_a_format_change() -> None:
    full = _bytes(MT5)
    cut2 = edit.cut_statement(full, keep_to=D2)
    workbook = dataclasses.replace(_snapshot(full), source_format=importers.MT5_HISTORY_XLSX)
    assert seal.compare_uploads(
        _snapshot(cut2), workbook, now=NOW, prev_key=KEY, new_key=KEY
    ) == seal.Refusal("format_changed")


def test_rows_before_the_first_upload_are_not_a_break() -> None:
    full = _bytes(MT4)
    window = edit.cut_statement(full, keep_from=datetime(2024, 3, 4, 9, 30), keep_to=D2)
    wider = edit.cut_statement(full, keep_to=D2)
    # The later-starting file was uploaded first; a wider export that adds
    # only earlier rows (and new ones after the cutoff) is refused with its
    # own code, never a mismatch.
    assert _compare(window, full) == seal.Refusal("earlier_rows")
    assert _uploaded(_compare(wider, full))


def test_keys_never_enter_the_outcome() -> None:
    full = _bytes(MT4)
    cut2 = edit.cut_statement(full, keep_to=D2)
    outcome = _compare(cut2, full, prev_key="99887766", new_key="99887766")
    assert "99887766" not in repr(outcome)
    assert "99887766" not in seal.snapshot_json(_snapshot(full))


# ---------------------------------------------------------------------------
# Tracking exports: Myfxbook, MQL5 signal, FX Blue (inline, in their shapes)
# ---------------------------------------------------------------------------

MYFXBOOK_HEAD = (
    "Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Close Price,"
    "Commission,Swap,Pips,Profit,Gain,Comment,Magic Number,Duration (DD:HH:MM:SS),"
    "Profitable(%),Profitable(time duration),Drawdown,Risk:Reward,Max(pips),Max(USD),"
    "Min(pips),Min(USD),Entry Accuracy(%),Exit Accuracy(%),ProfitMissed(pips),"
    "ProfitMissed(USD)"
)
TAIL = ",,,,,,,,,,,,"
MYFXBOOK_ROWS = [
    ",1001,01/02/2024 09:00,,,Deposit,0.010,0,0,0,0,0,0,0.0,1000.00,0,Deposit,0,00:00:00:00" + TAIL,
    ",1002,01/03/2024 10:00,01/03/2024 12:00,EURUSD,Buy,0.10,0,0,1.10000,1.10200,-0.7000,-0.3000,"
    "20.0,19.00,1.90,,7,00:02:00:00" + TAIL,
    ",1003,01/15/2024 10:00,01/15/2024 18:30,EURUSD.m,Sell,0.10,0,0,1.09500,1.09600,-0.7000,"
    "0.0000,-10.0,-10.70,-1.05,[sl],7,00:08:30:00" + TAIL,
    ",1004,01/20/2024 08:00,,,Withdrawal,0.010,0,0,0,0,0,0,0.0,-200.00,0,Withdrawal,0,"
    "00:00:00:00" + TAIL,
    ",1005,01/22/2024 10:00,01/23/2024 11:00,GBPUSD,Buy,0.20,0,0,1.27000,1.27100,-1.4000,0.0000,"
    "10.0,18.60,2.29,,7,01:01:00:00" + TAIL,
]
MYFXBOOK_OPEN = [
    "",
    "Open Trades",
    "Tags,Ticket,Open Date,Symbol,Action,Lots,Open Price,TP,SL,Profit,Pips,Swap",
    ",1006,01/25/2024 10:00,EURUSD,Buy,0.10,1.09000,0,0,-55.00,-55.0,0",
]


def _myfxbook(lines: list[str]) -> bytes:
    return ("\n".join([MYFXBOOK_HEAD, *lines]) + "\n").encode("utf-8")


def test_myfxbook_records_and_sequence() -> None:
    full = _myfxbook(MYFXBOOK_ROWS + MYFXBOOK_OPEN)
    snap = _snapshot(full)
    assert snap.family == families.MYFXBOOK and snap.currency == ""
    assert [
        (r.ref, r.sym, r.side, r.vol, r.open, r.close, r.px_out, r.pnl, r.comm) for r in snap.closed
    ] == [
        (
            "1002",
            "EURUSD",
            "long",
            "0.10",
            "2024-01-03T10:00:00Z",
            "2024-01-03T12:00:00Z",
            "1.10200",
            "19.00",
            "-0.7000",
        ),
        (
            "1003",
            "EURUSD.M",
            "short",
            "0.10",
            "2024-01-15T10:00:00Z",
            "2024-01-15T18:30:00Z",
            "1.09600",
            "-10.70",
            "-0.7000",
        ),
        (
            "1005",
            "GBPUSD",
            "long",
            "0.20",
            "2024-01-22T10:00:00Z",
            "2024-01-23T11:00:00Z",
            "1.27100",
            "18.60",
            "-1.4000",
        ),
    ]
    assert [(r.ref, r.at, r.amount, r.kind) for r in snap.cash] == [
        ("1001", "2024-01-02T09:00:00Z", "1000.00", "deposit"),
        ("1004", "2024-01-20T08:00:00Z", "-200.00", "withdrawal"),
    ]
    assert [(r.ref, r.sym, r.side, r.vol, r.open, r.px_in) for r in snap.open_listed] == [
        ("1006", "EURUSD", "long", "0.10", "2024-01-25T10:00:00Z", "1.09000")
    ]
    earlier = _myfxbook(MYFXBOOK_ROWS[:3])
    outcome = _uploaded(_compare(earlier, full, prev_key=None, new_key=None))
    assert outcome.figures.new_closed == 1 and outcome.figures.new_flows == 1
    altered = _myfxbook(
        [row.replace("-10.70,-1.05", "-10.71,-1.05") for row in MYFXBOOK_ROWS] + MYFXBOOK_OPEN
    )
    changed = _one_mismatch(_compare(earlier, altered, prev_key=None, new_key=None), "changed", "t")
    assert changed.ref == "1003" and changed.fields == ("pnl",)
    # Without an account number, one of the five earliest trades missing
    # cannot be told from another account: a refusal, never an event.
    without = _myfxbook([row for row in MYFXBOOK_ROWS if ",1002," not in row] + MYFXBOOK_OPEN)
    assert _compare(earlier, without, prev_key=None, new_key=None) == seal.Refusal(
        "account_differs"
    )
    # Positions listed open must still be open or closed since.
    still = _myfxbook(MYFXBOOK_ROWS[:4] + MYFXBOOK_OPEN)
    later_closed = _myfxbook(
        MYFXBOOK_ROWS
        + [
            ",1006,01/25/2024 10:00,01/26/2024 10:00,EURUSD,Buy,0.10,0,0,1.09000,1.09100,-0.7000,0,"
            "10.0,9.30,0.9,,7,01:00:00:00" + TAIL
        ]
    )
    assert _uploaded(_compare(still, later_closed, prev_key=None, new_key=None))
    vanished = _myfxbook(MYFXBOOK_ROWS)
    gone = _one_mismatch(
        _compare(still, vanished, prev_key=None, new_key=None), "open_changed", "o"
    )
    assert gone.ref == "1006" and gone.at == "2024-01-25T10:00:00Z"


MQL5_HEAD = "\ufeffTime;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit;Comment"
MQL5_DEPOSIT = "2024.03.01 08:00:00;Balance;;;;;;;;;;1 000.00;Deposit"
MQL5_TRADES = [
    "2024.03.04 09:00:00;Buy;0.10;EURUSD;1.08000;;;2024.03.04 15:00:00;1.08150;-0.50;-0.10;15.00;",
    "2024.03.05 09:00:00;Sell;0.10;EURUSD;1.08500;;;2024.03.05 11:00:00;1.08400;-0.50;0.00;10.00;",
    "2024.03.06 09:00:00;Buy Stop;0.10;EURUSD;1.09000;;;2024.03.06 12:00:00;1.09000;;;;cancelled",
    "2024.03.07 09:00:00;Sell;0.20;XAUUSD;2 150.00;;;2024.03.07 10:00:00;2 145.00;-1.00;0.00;"
    "100.00;",
    "2024.03.08 09:00:00;Buy;0.10;EURUSD;1.08100;;;2024.03.08 15:00:00;1.08150;-0.50;0.00;5.00;",
    "2024.03.11 09:00:00;Buy;0.10;EURUSD;1.08200;;;2024.03.11 15:00:00;1.08250;-0.50;0.00;5.00;",
    "2024.03.12 09:00:00;Sell;0.10;EURUSD;1.08300;;;2024.03.12 15:00:00;1.08250;-0.50;0.00;5.00;",
]
MQL5_LATER = (
    "2024.03.13 09:00:00;Buy;0.10;EURUSD;1.08000;;;2024.03.13 15:00:00;1.08100;-0.50;0.00;10.00;"
)
MQL5_WITHDRAWAL = "2024.03.14 12:00:00;Balance;;;;;;;;;;-100.00;Withdrawal"


def _mql5(lines: list[str]) -> bytes:
    return "\n".join([MQL5_HEAD, *lines]).encode("utf-8")


def test_mql5_signal_records_have_no_reference_and_pair_by_fields() -> None:
    earlier = _mql5([MQL5_DEPOSIT, *MQL5_TRADES])
    full = _mql5([MQL5_DEPOSIT, *MQL5_TRADES, MQL5_LATER, MQL5_WITHDRAWAL])
    snap = _snapshot(full)
    assert snap.family == families.MQL5_SIGNAL
    assert [(r.ref, r.sym, r.side, r.vol, r.open, r.px_in, r.px_out, r.pnl) for r in snap.closed][
        :3
    ] == [
        ("", "EURUSD", "long", "0.10", "2024-03-04T09:00:00Z", "1.08000", "1.08150", "15.00"),
        ("", "EURUSD", "short", "0.10", "2024-03-05T09:00:00Z", "1.08500", "1.08400", "10.00"),
        ("", "XAUUSD", "short", "0.20", "2024-03-07T09:00:00Z", "2150.00", "2145.00", "100.00"),
    ]
    assert len(snap.closed) == 7  # the cancelled Buy Stop is not a trade
    assert [(r.ref, r.at, r.amount, r.kind) for r in snap.cash] == [
        ("", "2024-03-01T08:00:00Z", "1000.00", "deposit"),
        ("", "2024-03-14T12:00:00Z", "-100.00", "withdrawal"),
    ]
    now = datetime(2024, 3, 15, tzinfo=UTC)
    outcome = _uploaded(_compare(earlier, full, now=now, prev_key=None, new_key=None))
    assert outcome.figures.new_closed == 1 and outcome.figures.new_flows == 1
    without = _mql5([MQL5_DEPOSIT, *MQL5_TRADES[:-1], MQL5_LATER, MQL5_WITHDRAWAL])
    deleted = _one_mismatch(
        _compare(earlier, without, now=now, prev_key=None, new_key=None), "deleted", "t"
    )
    assert deleted.ref == "" and deleted.at == "2024-03-12T15:00:00Z"
    # Without an account number, the earliest trades must be there unchanged.
    retyped = _mql5(
        [
            MQL5_DEPOSIT,
            MQL5_TRADES[0].replace("2024.03.04 09:00:00", "2024.03.04 09:01:00"),
            *MQL5_TRADES[1:],
            MQL5_LATER,
            MQL5_WITHDRAWAL,
        ]
    )
    assert _compare(earlier, retyped, now=now, prev_key=None, new_key=None) == seal.Refusal(
        "account_differs"
    )


FXBLUE_HEAD = (
    "Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,"
    "Open date,Close date,Profit,Swap,Commission,Net profit,T/P,S/L,Pips,Result,"
    "Trade duration (hours),Magic number,Order comment,Account"
)
FXBLUE_ROWS = [
    "Deposit,1,,0,,0,0,2024/10/01 08:00:00,2024/10/01 08:00:00,2024/10/01,2024/10/01,"
    "5000,0,0,5000,0,0,0,n/a,0,0,,main",
    "Closed position,2,EURUSD,1,Buy,1.1000,1.1010,2024/10/02 09:00:00,2024/10/02 10:00:00,"
    "2024/10/02,2024/10/02,100,-2,-5,93,0,0,10,Win,1,1,,main",
    "Closed position,3,EURUSD,1,Sell,1.1020,1.1030,2024/10/03 09:00:00,2024/10/03 11:00:00,"
    "2024/10/03,2024/10/03,-100,0,-5,-105,0,0,-10,Loss,2,1,,main",
]
FXBLUE_OPEN = (
    "Open position,4,EURUSD,1,Buy,1.1000,1.0900,2024/10/04 09:00:00,1970/01/01 00:00:00,"
    "2024/10/04,1970/01/01,-1000,0,0,-1000,0,0,-100,Loss,0,1,,main"
)
FXBLUE_CLOSED_4 = (
    "Closed position,4,EURUSD,1,Buy,1.1000,1.1050,2024/10/04 09:00:00,2024/10/05 09:00:00,"
    "2024/10/04,2024/10/05,500,0,-5,495,0,0,50,Win,24,1,,main"
)
FXBLUE_PENDING = (
    "Pending order,5,EURUSD,1,Buy Stop,1.2000,0,2024/10/04 09:00:00,1970/01/01 00:00:00,"
    "2024/10/04,1970/01/01,0,0,0,0,0,0,0,n/a,0,1,,main"
)


def _fxblue(lines: list[str]) -> bytes:
    return ("\r\n".join(["sep=,", FXBLUE_HEAD, *lines]) + "\r\n").encode("utf-8")


def test_fxblue_records_and_sequence() -> None:
    earlier = _fxblue(FXBLUE_ROWS + [FXBLUE_OPEN, FXBLUE_PENDING])
    snap = _snapshot(earlier)
    assert snap.family == families.FXBLUE
    assert [
        (r.ref, r.sym, r.side, r.vol, r.open, r.close, r.px_in, r.px_out, r.pnl, r.comm)
        for r in snap.closed
    ] == [
        (
            "2",
            "EURUSD",
            "long",
            "1",
            "2024-10-02T09:00:00Z",
            "2024-10-02T10:00:00Z",
            "1.1000",
            "1.1010",
            "100",
            "-5",
        ),
        (
            "3",
            "EURUSD",
            "short",
            "1",
            "2024-10-03T09:00:00Z",
            "2024-10-03T11:00:00Z",
            "1.1020",
            "1.1030",
            "-100",
            "-5",
        ),
    ]
    assert [(r.ref, r.at, r.amount, r.kind) for r in snap.cash] == [
        ("1", "2024-10-01T08:00:00Z", "5000", "deposit")
    ]
    assert [(r.ref, r.sym, r.side, r.vol, r.open, r.px_in) for r in snap.open_listed] == [
        ("4", "EURUSD", "long", "1", "2024-10-04T09:00:00Z", "1.1000")
    ]
    later = _fxblue(FXBLUE_ROWS + [FXBLUE_CLOSED_4, FXBLUE_PENDING])
    key = rows.account_key(earlier, importers.FXBLUE_CSV)
    assert key == rows.account_key(later, importers.FXBLUE_CSV)
    outcome = _uploaded(
        seal.compare_uploads(
            snap, _snapshot(later), now=datetime(2024, 10, 6, tzinfo=UTC), prev_key=key, new_key=key
        )
    )
    assert outcome.figures.new_closed == 1
    altered = _fxblue(
        [
            FXBLUE_ROWS[0],
            FXBLUE_ROWS[1].replace(",100,-2,", ",101,-2,"),
            FXBLUE_ROWS[2],
            FXBLUE_CLOSED_4,
        ]
    )
    changed = _one_mismatch(
        seal.compare_uploads(
            snap,
            _snapshot(altered),
            now=datetime(2024, 10, 6, tzinfo=UTC),
            prev_key=key,
            new_key=key,
        ),
        "changed",
        "t",
    )
    assert changed.ref == "2" and changed.fields == ("pnl",)


def test_identical_open_positions_closed_at_different_times_are_accounted_together() -> None:
    """A strategy may open several identical positions in one second (one per
    magic number); the export lists them open with one open time and price
    and closes them at different times: volumes are summed per key."""
    opened = [
        FXBLUE_OPEN.replace("Open position,4,", f"Open position,{ticket},") for ticket in (4, 5, 6)
    ]
    earlier = _fxblue(FXBLUE_ROWS + opened)
    closes = ("2024/10/05 09:00:00", "2024/10/06 09:00:00", "2024/10/07 09:00:00")
    closed = [
        FXBLUE_CLOSED_4.replace("Closed position,4,", f"Closed position,{ticket},").replace(
            "2024/10/05 09:00:00", when
        )
        for ticket, when in zip((4, 5, 6), closes, strict=True)
    ]
    later = _fxblue(FXBLUE_ROWS + closed)
    now = datetime(2024, 10, 8, tzinfo=UTC)
    assert _uploaded(_compare(earlier, later, now=now, prev_key="main", new_key="main"))
    partly = _fxblue(FXBLUE_ROWS + closed[:2] + opened[2:])
    assert _uploaded(_compare(earlier, partly, now=now, prev_key="main", new_key="main"))
    short = _fxblue(FXBLUE_ROWS + closed[:2])
    outcome = _compare(earlier, short, now=now, prev_key="main", new_key="main")
    assert isinstance(outcome, seal.Outcome) and outcome.event == seal.EVENT_MISMATCH
    assert outcome.count == 3 and {op.kind for op in outcome.operations} == {"open_changed"}


# ---------------------------------------------------------------------------
# Monthly tables
# ---------------------------------------------------------------------------


def _grid(values: dict[str, float]) -> MonthlyGrid:
    stamps = [pd.Timestamp(ym) + pd.offsets.MonthEnd(0) for ym in values]
    return MonthlyGrid(frame=pd.DataFrame({"timestamp": stamps, "ret": list(values.values())}))


def test_monthly_snapshot_and_comparison() -> None:
    LATER = datetime(2024, 4, 5, tzinfo=UTC)
    prev = seal.snapshot_monthly(_grid({"2024-01": 0.012, "2024-02": -0.005}))
    assert prev.family == families.MONTHLY and prev.source_format == seal.MONTHLY_FORMAT
    assert [record.as_dict() for record in prev.months] == [
        {"k": "m", "ym": "2024-01", "ret": "1.2"},
        {"k": "m", "ym": "2024-02", "ret": "-0.5"},
    ]
    assert prev.first_at == "2024-01-01T00:00:00Z" and prev.cutoff == "2024-02-29T23:59:59Z"
    assert prev.last_month == "2024-02"
    same = seal.snapshot_monthly(_grid({"2024-01": 0.012, "2024-02": -0.005, "2024-03": 0.02}))
    assert _uploaded(seal.compare_uploads(prev, same, now=LATER, prev_key=None, new_key=None))
    revised = seal.snapshot_monthly(_grid({"2024-01": 0.013, "2024-02": -0.006, "2024-03": 0.02}))
    inside = seal.compare_uploads(
        prev,
        revised,
        now=LATER,
        prev_key=None,
        new_key=None,
        prev_at=datetime(2024, 2, 20, tzinfo=UTC),
    )
    january = _one_mismatch(inside, "changed", "m")
    assert january.at == "2024-01" and january.fields == ("ret",)
    after = seal.compare_uploads(
        prev,
        revised,
        now=LATER,
        prev_key=None,
        new_key=None,
        prev_at=datetime(2024, 3, 2, tzinfo=UTC),
    )
    assert isinstance(after, seal.Outcome) and after.count == 2
    assert [operation.at for operation in after.operations] == ["2024-01", "2024-02"]
    assert seal.compare_uploads(prev, prev, now=LATER, prev_key=None, new_key=None) == seal.Refusal(
        "already_recorded"
    )


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


def _chain(count: int = 3) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    previous = ""
    for position in range(1, count + 1):
        entry: dict[str, object] = dict(
            seal.chain_entry(
                position=position,
                at=datetime(2026, 10, position, 10, 11, 12, tzinfo=UTC),
                cutoff=f"2026-09-{27 + position}T21:59:59Z",
                closed_count=40 + position,
                flow_count=3,
                currency="USD",
                source_format=importers.MT4_STATEMENT_HTML,
                trades_sha256="ab" * 32,
                event_kind="uploaded",
                event_count=0,
                previous_hash=previous,
            )
        )
        entry["hash"] = seal.entry_hash(entry)
        previous = str(entry["hash"])
        entries.append(entry)
    return entries


def test_chain_entries_are_flat_and_fit_the_upload_columns() -> None:
    entries = _chain()
    genesis = entries[0]
    assert genesis["previous_hash"] == "" and genesis["v"] == seal.RECIPE_VERSION == "track-seal-1"
    assert genesis["method_version"] == "forensics-1"
    assert genesis["at"] == "2026-10-01T10:11:12Z"
    for entry in entries:
        for key, value in entry.items():
            assert isinstance(value, str | int) and not isinstance(value, bool), key
    columns = {
        "position",
        "at",
        "cutoff",
        "closed_count",
        "flow_count",
        "currency",
        "source_format",
        "trades_sha256",
        "previous_hash",
        "hash",
    }
    assert columns <= set(genesis)
    assert entries[1]["previous_hash"] == entries[0]["hash"]
    assert seal.verify_chain(entries) == (True, None)
    assert seal.verify_chain([]) == (True, None)


def test_a_tampered_entry_or_link_is_detected() -> None:
    entries = _chain()
    tampered = [dict(entry) for entry in entries]
    tampered[1]["closed_count"] = 99
    assert seal.verify_chain(tampered) == (False, 2)
    relinked = [dict(entry) for entry in entries]
    relinked[2]["previous_hash"] = "0" * 64
    assert seal.verify_chain(relinked) == (False, 3)
    genesis = [dict(entry) for entry in entries]
    genesis[0]["previous_hash"] = "1" * 64
    assert seal.verify_chain(genesis) == (False, 1)
    assert seal.verify_chain(entries[1:]) == (False, 2)


def test_the_head_recomputes_with_hashlib_and_json_only() -> None:
    entries = _chain()
    head = ""
    for entry in entries:
        body = {key: value for key, value in entry.items() if key != "hash"}
        assert body["previous_hash"] == head
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        head = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert head == entry["hash"]
    assert head == entries[-1]["hash"]


# ---------------------------------------------------------------------------
# Sealed stretch
# ---------------------------------------------------------------------------


def _curve_start(report: importers.ImportedReport) -> float:
    frame = parse_equity_csv(report.equity_csv).frame
    return float(frame["equity"].iloc[0])


def test_mt4_sealed_stretch_starts_at_b0_with_the_trades_opened_after_s() -> None:
    full = _bytes(MT4)
    opened_at = datetime(2024, 3, 3, 9, 30, tzinfo=UTC)  # S = 2024-03-04 09:30
    cut, b0 = seal.sealed_stretch_bytes(full, importers.MT4_STATEMENT_HTML, opened_at)
    assert b0 == Decimal("10000.00")
    report = importers.import_report(cut, initial_balance=float(b0))
    assert [
        (t.entry_time.replace(tzinfo=None), t.exit_time.replace(tzinfo=None), t.pnl)
        for t in report.trades.trades
    ] == [
        (datetime(2024, 3, 4, 10, 0), datetime(2024, 3, 4, 13, 2, 44), -225.0),
        (datetime(2024, 3, 4, 10, 0), datetime(2024, 3, 6, 9, 30), -145.0),
    ]
    assert report.initial_balance == 10000.0
    assert _curve_start(report) == 10000.0
    assert not any("starting balance" in warning for warning in report.warnings)


def test_mt4_sealed_stretch_counts_earlier_trades_and_folds_early_flows() -> None:
    full = _bytes(MT4)
    table = _table(full)
    later = edit.duplicate_row(
        full,
        _row(table, rows.KIND_MT4_TRADE, "1000002").index,
        {0: "1000010"},
        shift=timedelta(days=3),
    )
    opened_at = datetime(2024, 3, 5, 12, 0, tzinfo=UTC)  # S = 2024-03-06 12:00
    cut, b0 = seal.sealed_stretch_bytes(later, importers.MT4_STATEMENT_HTML, opened_at)
    # 10 000 - 228.50 + 186.80 - 152.60 (the three trades closed before S, net).
    assert b0 == Decimal("9805.70")
    report = importers.import_report(cut, initial_balance=float(b0))
    assert [t.pnl for t in report.trades.trades] == [200.0]
    assert [amount for _, amount in report.cash_flows] == [-1000.0]
    assert _curve_start(report) == 9805.70
    # A flow between S and the first kept trade is folded into B0 and cut.
    withdrawal = _row(_table(later), rows.KIND_MT4_CASH, "1000007")
    early = edit.shift_time(later, withdrawal.index, 1, timedelta(minutes=-60))
    cut_early, b0_early = seal.sealed_stretch_bytes(early, importers.MT4_STATEMENT_HTML, opened_at)
    assert b0_early == Decimal("8805.70")
    report_early = importers.import_report(cut_early, initial_balance=float(b0_early))
    assert report_early.cash_flows == []
    assert _curve_start(report_early) == 8805.70


def test_mt5_sealed_stretch_drops_the_straddler_and_its_exit_deal() -> None:
    full = _bytes(MT5)
    opened_at = datetime(2024, 3, 3, 9, 18, tzinfo=UTC)  # S = 2024-03-04 09:18
    cut, b0 = seal.sealed_stretch_bytes(full, importers.MT5_HISTORY_HTML, opened_at)
    assert b0 == Decimal("1000.00")
    report = importers.import_report(cut, initial_balance=float(b0))
    assert [t.pnl for t in report.trades.trades] == [-9.0]
    assert report.initial_balance == 1000.0 and _curve_start(report) == 1000.0
    assert not any("Balance cell" in warning for warning in report.warnings)
    table = _table(cut)
    assert [row.text(1) for row in table.kind(rows.KIND_MT5_DEAL)] == ["9002", "9003", "9005"]


def test_sealed_stretch_refuses_tester_files() -> None:
    with pytest.raises(ValueError, match="tester_not_allowed"):
        seal.sealed_stretch_bytes(_bytes("mt5_tester.html"), importers.MT5_TESTER_HTML, NOW)


# ---------------------------------------------------------------------------
# Privacy of everything serialised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", (MT4, MT5))
def test_nothing_private_reaches_snapshot_outcome_or_entry(name: str) -> None:
    full = _bytes(name)
    cut2 = edit.cut_statement(full, keep_to=D2)
    table = _table(full)
    kind = rows.KIND_MT4_TRADE if name == MT4 else rows.KIND_MT5_POSITION
    victim = next(row for row in table.rows if row.kind == kind)
    outcome = _compare(cut2, edit.delete_row(full, victim.index))
    assert isinstance(outcome, seal.Outcome) and outcome.event == seal.EVENT_MISMATCH
    snap = _snapshot(full)
    entry = seal.chain_entry(
        position=1,
        at=NOW,
        cutoff=snap.cutoff,
        closed_count=len(snap.closed),
        flow_count=len(snap.cash),
        currency=snap.currency,
        source_format=snap.source_format,
        trades_sha256=seal.trades_sha256(snap),
        event_kind=outcome.event,
        event_count=outcome.count,
    )
    serialised = "\n".join(
        [
            seal.snapshot_json(snap),
            outcome.detail_json(),
            canonical_dumps(outcome.figures.as_dict()),
            canonical_dumps(entry),
            repr(outcome),
        ]
    )
    for private in PRIVATE_TEXT:
        assert private not in serialised, private
    assert "audit" not in canonical_dumps(entry)
