"""``FILE_TRACE``, ``STATEMENT_PERIOD`` and ``HIDDEN_CONTENT``: the file's
own trace, the span of its record and what its hidden cells hold.

Every fixture is synthetic; the CSV samples copy the header shapes of real
Myfxbook, MQL5-signal and FX Blue exports (see ``test_audit_tracking_exports``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows
from quant_trade.audit.forensics.checks import Context, trace
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import (
    DECLARED,
    EVIDENCE,
    MEASURED,
    NOT_MEASURED,
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    RawOutcome,
)
from quant_trade.audit.forensics.review import REASONS, review

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT_FIXTURES = ("mt4_statement.htm", "mt5_history.html", "mt5_tester.html", "mt4_tester.htm")
CSV_FIXTURES = ("tradingview_g1.csv", "tradingview_g3b.csv", "ninjatrader.csv")
PRIVATE_TEXT = ("12345678", "Demo Trader", "Synthetic", "SyntheticBroker-Demo", "FixtureEA")
CHECKS: tuple[Callable[[rows.RawTable, Context], RawOutcome], ...] = (
    trace.run_FILE_TRACE,
    trace.run_STATEMENT_PERIOD,
    trace.run_HIDDEN_CONTENT,
)

MYFXBOOK = (
    "\n".join(
        [
            "Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,"
            "Close Price,Commission,Swap,Pips,Profit,Gain,Comment,Magic Number",
            ",1001,01/02/2024 09:00,,,Deposit,0.010,0,0,0,0,0,0,0.0,1000.00,0,Deposit,0",
            ",1002,01/03/2024 10:00,01/03/2024 12:00,EURUSD,Buy,0.10,0,0,1.10000,1.10200,"
            "-0.7000,-0.3000,20.0,19.00,1.90,,7",
            ",1003,01/15/2024 10:00,01/15/2024 18:30,EURUSD,Sell,0.10,0,0,1.09500,1.09600,"
            "-0.7000,0.0000,-10.0,-10.70,-1.05,,7",
            ",1004,01/20/2024 08:00,,,Withdrawal,0.010,0,0,0,0,0,0,0.0,-200.00,0,Withdrawal,0",
            ",1005,01/22/2024 10:00,01/23/2024 11:00,GBPUSD,Buy,0.20,0,0,1.26000,1.26100,"
            "-1.4000,0.0000,10.0,18.60,2.30,,7",
            "Open Trades",
            "Tags,Ticket,Open Date,Symbol,Action,Lots,Open Price,TP,SL,Profit",
            ",1006,01/25/2024 10:00,EURUSD,Buy,0.10,1.09000,0,0,-55.00",
        ]
    )
    + "\n"
).encode("utf-8")
MQL5_SIGNAL = (
    "﻿"
    + "\n".join(
        [
            "Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit;Comment",
            "2024.03.01 08:00:00;Balance;;;;;;;;;;1 000.00;Deposit",
            "2024.03.04 09:00:00;Buy;0.10;EURUSD;1.08000;;;2024.03.04 15:00:00;1.08150;-0.50;"
            "-0.10;15.00;",
            "2024.03.05 09:00:00;Sell;0.10;EURUSD;1.08500;;;2024.03.05 11:00:00;1.08400;-0.50;"
            "0.00;10.00;",
            "2024.03.06 09:00:00;Buy Stop;0.10;EURUSD;1.09000;;;2024.03.06 12:00:00;1.09000;;;;"
            "cancelled",
            "2024.03.08 12:00:00;Balance;;;;;;;;;;-100.00;Withdrawal",
        ]
    )
).encode("utf-8")
MQL5_DECIMAL_COMMA = "\n".join(
    [
        "Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit;Comment",
        "2024.03.04 09:00:00;Buy;0,10;EURUSD;1,08000;;;2024.03.04 15:00:00;1,08150;-0,50;"
        "-0,10;15,00;",
    ]
).encode("utf-8")
FXBLUE_HEAD = (
    "Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,"
    "Open date,Close date,Profit,Swap,Commission,Net profit,T/P,S/L,Pips,Result,"
    "Trade duration (hours),Magic number,Order comment,Account"
)


def _fxblue(accounts: tuple[str, ...] = ("main",)) -> bytes:
    lines = ["sep=,", FXBLUE_HEAD]
    for account in accounts:
        lines += [
            f"Deposit,1,,0,,0,0,2024/10/01 08:00:00,2024/10/01 08:00:00,2024/10/01,2024/10/01,"
            f"5000,0,0,5000,0,0,0,n/a,0,0,,{account}",
            f"Closed position,2,EURUSD,1,Buy,1.1000,1.1010,2024/10/02 09:00:00,"
            f"2024/10/02 10:00:00,2024/10/02,2024/10/02,100,-2,-5,93,0,0,10,Win,1,1,,{account}",
            f"Closed position,3,EURUSD,1,Sell,1.1020,1.1030,2024/10/03 09:00:00,"
            f"2024/10/03 11:00:00,2024/10/03,2024/10/03,-100,0,-5,-105,0,0,-10,Loss,2,1,,{account}",
            f"Open position,4,EURUSD,1,Buy,1.1000,1.0900,2024/10/04 09:00:00,"
            f"1970/01/01 00:00:00,2024/10/04,1970/01/01,-1000,0,0,-1000,0,0,-100,Loss,0,1,,"
            f"{account}",
        ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _table(data: bytes, source_format: str | None = None) -> rows.RawTable:
    return rows.load(data, source_format or importers.detect_format(data))


def _ctx(table: rows.RawTable) -> Context:
    header = read_header(table)
    return Context(family=table.family, header=header, currency=header.currency)


def _run(
    check: Callable[[rows.RawTable, Context], RawOutcome],
    data: bytes,
    source_format: str | None = None,
) -> RawOutcome:
    table = _table(data, source_format)
    return check(table, _ctx(table))


def _figure(outcome: RawOutcome, key: str) -> str | None:
    for name, value, _evidence in outcome.figures:
        if name == key:
            return value
    return None


def _evidence(outcome: RawOutcome, key: str) -> str | None:
    for name, _value, evidence in outcome.figures:
        if name == key:
            return evidence
    return None


def _altered(data: bytes, old: bytes, new: bytes) -> bytes:
    assert data.count(old) == 1, old
    return data.replace(old, new)


def _without_row(data: bytes, needle: bytes) -> bytes:
    """The fixture without the ``<tr>`` that holds ``needle``."""
    at = data.index(needle)
    start = data.rfind(b"<tr", 0, at)
    end = data.index(b"</tr>", at) + len(b"</tr>")
    return data[:start] + data[end:]


def _serialised(outcome: RawOutcome) -> str:
    return json.dumps([list(figure) for figure in outcome.figures])


# ---------------------------------------------------------------------------
# Shape, privacy and determinism, over every sample and alteration
# ---------------------------------------------------------------------------


def _samples() -> list[tuple[str, bytes]]:
    mt4 = _fixture("mt4_statement.htm")
    mt5 = _fixture("mt5_history.html")
    return [
        *((name, _fixture(name)) for name in MT_FIXTURES + CSV_FIXTURES),
        ("myfxbook", MYFXBOOK),
        ("mql5", MQL5_SIGNAL),
        ("mql5_comma", MQL5_DECIMAL_COMMA),
        ("fxblue", _fxblue()),
        ("fxblue_two_accounts", _fxblue(("a", "b"))),
        ("mt4_resaved", _altered(mt4, b"<head>", b'<head><meta charset="utf-8">')),
        ("mt4_no_deposit", _without_row(mt4, b'title="Deposit"')),
        ("mt5_hidden_text", _altered(mt5, b'5001</td><td nowrap class="hidden"></td>',
                                     b'5001</td><td nowrap class="hidden">note</td>')),
    ]  # fmt: skip


@pytest.mark.parametrize("name,data", _samples(), ids=[name for name, _ in _samples()])
def test_figures_are_text_with_evidence_and_no_private_text(name: str, data: bytes) -> None:
    for check in CHECKS:
        outcome = _run(check, data)
        keys = [key for key, _value, _evidence in outcome.figures]
        assert len(keys) == len(set(keys)), (check.__name__, keys)
        if not outcome.not_measured:
            assert {"n_rows", "n_hits"} <= set(keys), check.__name__
            assert _figure(outcome, "n_hits") == str(outcome.hits)
        for key, value, evidence in outcome.figures:
            assert key == key.lower() and isinstance(value, str), (check.__name__, key)
            assert evidence in EVIDENCE, (check.__name__, key)
        assert list(outcome.examples) == sorted(outcome.examples)
        assert len(outcome.examples) <= 5
        serialised = _serialised(outcome)
        for private in PRIVATE_TEXT:
            assert private not in serialised, (check.__name__, private)


@pytest.mark.parametrize("name,data", _samples(), ids=[name for name, _ in _samples()])
def test_outcomes_are_deterministic(name: str, data: bytes) -> None:
    for check in CHECKS:
        assert _run(check, data) == _run(check, data), check.__name__


# ---------------------------------------------------------------------------
# FILE_TRACE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,generator,sections,title_attrs,hidden_cells",
    [
        ("mt4_statement.htm", "metaquotes", "67", "8", "0"),
        ("mt5_history.html", "client_terminal", "120", "0", "9"),
        ("mt5_tester.html", "strategy_tester", "24", "0", "0"),
        ("mt4_tester.htm", "metaquotes", "128", "0", "0"),
    ],
)
def test_file_trace_reads_the_native_fixtures(
    name: str, generator: str, sections: str, title_attrs: str, hidden_cells: str
) -> None:
    outcome = _run(trace.run_FILE_TRACE, _fixture(name))
    assert outcome.hits == 0 and not outcome.not_measured
    assert _figure(outcome, "generator") == generator
    assert _figure(outcome, "generator_native") == "1"
    assert _figure(outcome, "encoding") == "utf8"
    assert _figure(outcome, "line_endings") == "lf"
    assert _figure(outcome, "resave_markers") == "0"
    assert _figure(outcome, "platform_markers") == "0"
    assert _figure(outcome, "title_attrs") == title_attrs
    assert _figure(outcome, "hidden_cells") == hidden_cells
    assert _figure(outcome, "decimal_comma") == "0"
    assert _figure(outcome, "sections") == sections
    assert outcome.examples == ()


@pytest.mark.parametrize("name", CSV_FIXTURES)
def test_file_trace_on_delimited_files(name: str) -> None:
    outcome = _run(trace.run_FILE_TRACE, _fixture(name))
    assert outcome.hits == 0
    assert _figure(outcome, "generator") == "none"
    assert _figure(outcome, "generator_native") == "1"
    assert _figure(outcome, "platform_markers") == "0"
    assert _figure(outcome, "sections") == "0"
    assert _figure(outcome, "n_rows") == str(len(_table(_fixture(name)).rows))


def test_file_trace_counts_a_resave_marker_beyond_the_platform_stylesheet() -> None:
    mt5 = _fixture("mt5_history.html")
    stylesheet = b'<style>.msdate { mso-number-format:"General Date"; }</style>'
    with_stylesheet = _altered(mt5, b"</head>", stylesheet + b"</head>")
    outcome = _run(trace.run_FILE_TRACE, with_stylesheet)
    # The platform's own ``mso-number-format`` rule is not a marker.
    assert _figure(outcome, "resave_markers") == "0"
    assert _figure(outcome, "platform_markers") == "0"
    assert outcome.hits == 0
    resaved = _altered(with_stylesheet, b"<head>", b'<head><meta charset="utf-8">')
    outcome = _run(trace.run_FILE_TRACE, resaved)
    assert _figure(outcome, "resave_markers") == "1"
    assert outcome.hits == 1 and _figure(outcome, "n_hits") == "1"
    mt4 = _altered(_fixture("mt4_statement.htm"), b"</head>", stylesheet + b"</head>")
    outcome = _run(trace.run_FILE_TRACE, mt4)
    assert _figure(outcome, "resave_markers") == "0" and outcome.hits == 0
    outcome = _run(trace.run_FILE_TRACE, _altered(mt4, b"<head>", b'<head><meta charset="utf-8">'))
    assert _figure(outcome, "resave_markers") == "1" and outcome.hits == 1
    # A lone foreign marker on a page without the stylesheet is a hit too.
    lone = _altered(_fixture("mt4_statement.htm"), b"<head>", b'<head><meta charset="utf-8">')
    outcome = _run(trace.run_FILE_TRACE, lone)
    assert _figure(outcome, "resave_markers") == "1" and outcome.hits == 1
    # An Office re-save carries several markers: each one counts.
    office = _altered(lone, b"<html>", b'<html xmlns:o="urn:schemas-microsoft-com:office:office">')
    office = _altered(office, b"</head>", b"<style>.xl65 { mso-font-charset:0; }</style></head>")
    outcome = _run(trace.run_FILE_TRACE, office)
    assert _figure(outcome, "resave_markers") == "3" and outcome.hits == 3
    # A MetaTrader page the importers do not read: no allowance needed.
    trade_report = rows.RawTable("", families.OTHER, (), (), "client_terminal", "utf16le_bom",
                                 "crlf", 0, False)  # fmt: skip
    outcome = trace.run_FILE_TRACE(trade_report, _ctx(trade_report))
    assert _figure(outcome, "platform_markers") == "0" and outcome.hits == 0
    optimizer = rows.RawTable(importers.MT5_OPTIMIZATION_XML, families.OTHER, (), (), "none",
                              "utf8", "crlf", 3, False)  # fmt: skip
    outcome = trace.run_FILE_TRACE(optimizer, _ctx(optimizer))
    assert _figure(outcome, "platform_markers") == "3" and outcome.hits == 0


def test_file_trace_accepts_the_older_metatrader_generator() -> None:
    mt5 = _fixture("mt5_history.html")
    older = _altered(mt5, b'content="client terminal"', b'content="MetaTrader 5"')
    outcome = _run(trace.run_FILE_TRACE, older)
    assert _figure(outcome, "generator") == "metatrader"
    assert _figure(outcome, "generator_native") == "1" and outcome.hits == 0
    tester = _altered(
        _fixture("mt5_tester.html"), b'content="strategy tester"', b'content="MetaTrader 5"'
    )
    outcome = _run(trace.run_FILE_TRACE, tester)
    assert _figure(outcome, "generator_native") == "1" and outcome.hits == 0
    mt4 = _altered(
        _fixture("mt4_statement.htm"),
        b'content="MetaQuotes Software Corp."',
        b'content="MetaTrader 5"',
    )
    outcome = _run(trace.run_FILE_TRACE, mt4)
    assert _figure(outcome, "generator_native") == "0" and outcome.hits == 1


def test_file_trace_generator_rules() -> None:
    mt5 = _fixture("mt5_history.html")
    excel = _altered(mt5, b'content="client terminal"', b'content="Microsoft Excel 15"')
    outcome = _run(trace.run_FILE_TRACE, excel)
    assert _figure(outcome, "generator") == "excel"
    assert _figure(outcome, "generator_native") == "0"
    assert outcome.hits == 1
    stripped = _altered(mt5, b'<meta name="generator" content="client terminal">', b"")
    outcome = _run(trace.run_FILE_TRACE, stripped)
    assert _figure(outcome, "generator") == "none" and outcome.hits == 1
    # MT4 builds write no generator meta at all: ``none`` is native there.
    mt4 = _fixture("mt4_statement.htm")
    stripped = _altered(mt4, b'<meta name="generator" content="MetaQuotes Software Corp.">', b"")
    outcome = _run(trace.run_FILE_TRACE, stripped)
    assert _figure(outcome, "generator") == "none"
    assert _figure(outcome, "generator_native") == "1" and outcome.hits == 0
    mshtml = _altered(mt4, b'content="MetaQuotes Software Corp."', b'content="MSHTML 10.00"')
    outcome = _run(trace.run_FILE_TRACE, mshtml)
    assert _figure(outcome, "generator") == "mshtml" and outcome.hits == 1


def test_file_trace_reads_the_decimal_comma_from_the_first_printed_number() -> None:
    outcome = _run(trace.run_FILE_TRACE, MQL5_DECIMAL_COMMA, importers.MQL5_SIGNAL_CSV)
    assert _figure(outcome, "decimal_comma") == "1"
    assert _figure(outcome, "encoding") == "utf8"
    outcome = _run(trace.run_FILE_TRACE, MQL5_SIGNAL)
    assert _figure(outcome, "decimal_comma") == "0"
    assert _figure(outcome, "encoding") == "utf8_bom"
    outcome = _run(trace.run_FILE_TRACE, _fxblue())
    assert _figure(outcome, "line_endings") == "crlf"


def test_file_trace_on_workbook_and_monthly_tables() -> None:
    xlsx = rows.RawTable(
        importers.MT5_HISTORY_XLSX, families.MT5_HISTORY, (), (), "none", "none", "none", 0, False
    )
    outcome = trace.run_FILE_TRACE(xlsx, _ctx(xlsx))
    assert outcome.hits == 0 and _figure(outcome, "generator_native") == "1"
    assert _figure(outcome, "n_rows") == "0" and _figure(outcome, "sections") == "0"
    monthly = rows.RawTable("monthly", families.MONTHLY, (), (), "none", "none", "none", 0, False)
    outcome = trace.run_FILE_TRACE(monthly, _ctx(monthly))
    assert outcome.hits == 0 and not outcome.not_measured


# ---------------------------------------------------------------------------
# STATEMENT_PERIOD
# ---------------------------------------------------------------------------


def test_statement_period_of_the_mt4_statement() -> None:
    outcome = _run(trace.run_STATEMENT_PERIOD, _fixture("mt4_statement.htm"))
    assert outcome.hits == 0 and not outcome.not_measured
    assert _figure(outcome, "n_rows") == "7"
    assert _figure(outcome, "first_row_at") == "2024-03-01T08:00:00Z"
    # The withdrawal is the last dated row; the last close is 2024-03-06.
    assert _figure(outcome, "last_row_at") == "2024-03-07T10:00:00Z"
    assert _figure(outcome, "opens_with_deposit") == "1"
    assert _figure(outcome, "report_date") == "2024-03-08T18:30:00Z"
    assert _evidence(outcome, "report_date") == DECLARED
    assert _evidence(outcome, "first_row_at") == MEASURED


def test_statement_period_without_the_opening_deposit() -> None:
    data = _without_row(_fixture("mt4_statement.htm"), b'title="Deposit"')
    outcome = _run(trace.run_STATEMENT_PERIOD, data)
    assert _figure(outcome, "n_rows") == "6"
    assert _figure(outcome, "opens_with_deposit") == "0"
    assert _figure(outcome, "first_row_at") == "2024-03-04T09:15:02Z"
    # A withdrawal first is not a deposit.
    data = _altered(_fixture("mt4_statement.htm"), b"2024.03.07 10:00:00", b"2024.02.07 10:00:00")
    outcome = _run(trace.run_STATEMENT_PERIOD, data)
    assert _figure(outcome, "first_row_at") == "2024-02-07T10:00:00Z"
    assert _figure(outcome, "opens_with_deposit") == "0"


def test_statement_period_of_the_mt5_history() -> None:
    data = _fixture("mt5_history.html")
    outcome = _run(trace.run_STATEMENT_PERIOD, data)
    assert _figure(outcome, "n_rows") == "6"
    assert _figure(outcome, "first_row_at") == "2024-03-01T08:00:00Z"
    assert _figure(outcome, "last_row_at") == "2024-03-06T10:00:00Z"
    assert _figure(outcome, "opens_with_deposit") == "1"
    assert _figure(outcome, "report_date") == "2024-03-08T18:30:00Z"
    outcome = _run(trace.run_STATEMENT_PERIOD, _without_row(data, b"<td nowrap>9000</td>"))
    assert _figure(outcome, "n_rows") == "5"
    assert _figure(outcome, "opens_with_deposit") == "0"
    assert _figure(outcome, "first_row_at") == "2024-03-04T09:15:02Z"


def test_statement_period_of_tracking_exports() -> None:
    outcome = _run(trace.run_STATEMENT_PERIOD, MYFXBOOK)
    # Five rows of the closed record; the "Open Trades" block is not the period.
    assert _figure(outcome, "n_rows") == "5"
    assert _figure(outcome, "first_row_at") == "2024-01-02T09:00:00Z"
    assert _figure(outcome, "last_row_at") == "2024-01-23T11:00:00Z"
    assert _figure(outcome, "opens_with_deposit") == "1"
    assert _figure(outcome, "report_date") == ""
    assert _evidence(outcome, "report_date") == NOT_MEASURED
    outcome = _run(trace.run_STATEMENT_PERIOD, MQL5_SIGNAL)
    assert _figure(outcome, "n_rows") == "5"
    assert _figure(outcome, "first_row_at") == "2024-03-01T08:00:00Z"
    assert _figure(outcome, "last_row_at") == "2024-03-08T12:00:00Z"
    assert _figure(outcome, "opens_with_deposit") == "1"
    outcome = _run(trace.run_STATEMENT_PERIOD, _fxblue())
    assert _figure(outcome, "n_rows") == "4"
    assert _figure(outcome, "first_row_at") == "2024-10-01T08:00:00Z"
    # FX Blue prints the epoch as the close of an open position: not a date.
    assert _figure(outcome, "last_row_at") == "2024-10-04T09:00:00Z"
    assert _figure(outcome, "opens_with_deposit") == "1"
    assert _figure(outcome, "n_accounts") == "1"
    # Two account labels: the one with the most closed positions is the
    # record (the importer's choice); a tie goes to the label seen first.
    outcome = _run(trace.run_STATEMENT_PERIOD, _fxblue(("a", "b")))
    assert not outcome.not_measured
    assert _figure(outcome, "n_accounts") == "2" and _figure(outcome, "n_rows") == "4"
    assert _figure(outcome, "last_row_at") == "2024-10-04T09:00:00Z"
    later = _fxblue(("a", "b")).replace(
        b"2024/10/03 11:00:00,2024/10/03,2024/10/03,-100,0,-5,-105,0,0,-10,Loss,2,1,,b",
        b"2024/10/09 11:00:00,2024/10/03,2024/10/03,-100,0,-5,-105,0,0,-10,Loss,2,1,,b",
    )
    outcome = _run(trace.run_STATEMENT_PERIOD, later)
    assert _figure(outcome, "last_row_at") == "2024-10-04T09:00:00Z"  # still account "a"


def test_statement_period_skips_and_reasons() -> None:
    for name in ("mt5_tester.html", "mt4_tester.htm", "tradingview_g1.csv", "ninjatrader.csv"):
        outcome = _run(trace.run_STATEMENT_PERIOD, _fixture(name))
        assert outcome.not_measured and outcome.reason == "format_not_covered", name
    header_only = MQL5_SIGNAL.split(b"\n")[0] + b"\n"
    outcome = _run(trace.run_STATEMENT_PERIOD, header_only, importers.MQL5_SIGNAL_CSV)
    assert outcome.not_measured and outcome.reason == "no_qualifying_row"
    undated = _altered(MYFXBOOK, b"Open Date,Close Date", b"Opened,Closed")
    outcome = _run(trace.run_STATEMENT_PERIOD, undated, importers.MYFXBOOK_CSV)
    assert outcome.not_measured and outcome.reason == "no_column"
    for reason in ("format_not_covered", "no_qualifying_row", "no_column"):
        assert reason in REASONS


# ---------------------------------------------------------------------------
# HIDDEN_CONTENT
# ---------------------------------------------------------------------------


def test_hidden_content_of_the_native_fixtures() -> None:
    outcome = _run(trace.run_HIDDEN_CONTENT, _fixture("mt5_history.html"))
    assert outcome.hits == 0 and not outcome.not_measured
    # Two Positions fillers, the Deals header's Cost label, six deals' Cost.
    assert _figure(outcome, "n_hidden_cells") == "9"
    assert _figure(outcome, "hidden_nonempty") == "0"
    assert _figure(outcome, "hidden_rows") == "0"
    assert _figure(outcome, "n_rows") == "27"
    outcome = _run(trace.run_HIDDEN_CONTENT, _fixture("mt5_tester.html"))
    assert outcome.hits == 0 and _figure(outcome, "n_hidden_cells") == "0"


def test_hidden_content_finds_text_in_hidden_cells() -> None:
    mt5 = _fixture("mt5_history.html")
    deal = b'5001</td><td nowrap class="hidden"></td>'
    noted = _altered(mt5, deal, deal.replace(b"></td>", b">note</td>"))
    outcome = _run(trace.run_HIDDEN_CONTENT, noted)
    assert outcome.hits == 1 and outcome.examples == (16,)
    assert _figure(outcome, "hidden_nonempty") == "1"
    assert _figure(outcome, "hidden_rows") == "0"
    # A number in a deal's hidden Cost cell belongs to BALANCE_CHAIN.
    costed = _altered(mt5, deal, deal.replace(b"></td>", b">1.23</td>"))
    outcome = _run(trace.run_HIDDEN_CONTENT, costed)
    assert outcome.hits == 0 and outcome.examples == ()
    filler = b'<td class="hidden" colspan="8"></td><td class="">0.10</td>'
    filled = _altered(mt5, filler, filler.replace(b'"8"></td>', b'"8">1.23</td>'))
    outcome = _run(trace.run_HIDDEN_CONTENT, filled)
    # A number hidden in a Positions filler is not a Cost cell.
    assert outcome.hits == 1 and outcome.examples == (7,)


def test_hidden_content_finds_rows_hidden_whole() -> None:
    mt5 = _fixture("mt5_history.html")
    header_end = b"<td nowrap><b>Comment</b></td></tr>"
    hidden_row = b'<tr><td class="hidden">x</td><td class="hidden"></td></tr>'
    outcome = _run(trace.run_HIDDEN_CONTENT, _altered(mt5, header_end, header_end + hidden_row))
    assert _figure(outcome, "hidden_rows") == "1"
    assert _figure(outcome, "hidden_nonempty") == "1"
    assert outcome.hits == 2 and outcome.examples == (15,)
    assert _figure(outcome, "n_hidden_cells") == "11"


def test_hidden_content_skips() -> None:
    for name in ("mt4_statement.htm", "mt4_tester.htm", "tradingview_g1.csv"):
        outcome = _run(trace.run_HIDDEN_CONTENT, _fixture(name))
        assert outcome.not_measured and outcome.reason == "format_not_covered", name
    xlsx = rows.RawTable(
        importers.MT5_TESTER_XLSX, families.MT5_TESTER, (), (), "none", "none", "none", 0, False
    )
    outcome = trace.run_HIDDEN_CONTENT(xlsx, _ctx(xlsx))
    assert outcome.not_measured and outcome.reason == "no_column"


# ---------------------------------------------------------------------------
# Through review(): the one status rule
# ---------------------------------------------------------------------------


def test_review_statuses_of_the_trace_checks() -> None:
    mt4 = _fixture("mt4_statement.htm")
    result = review(mt4, source_format=importers.MT4_STATEMENT_HTML)
    assert result.check("FILE_TRACE").status == STATUS_CLEAN
    assert result.check("STATEMENT_PERIOD").status == STATUS_CLEAN
    assert result.check("HIDDEN_CONTENT").status == STATUS_NOT_MEASURED
    assert result.check("HIDDEN_CONTENT").reason == "format_not_covered"
    resaved = _altered(mt4, b'content="MetaQuotes Software Corp."', b'content="Microsoft Word 15"')
    result = review(resaved, source_format=importers.MT4_STATEMENT_HTML)
    assert result.check("FILE_TRACE").status == STATUS_INFO
    assert result.check("FILE_TRACE").figure("generator") == "word"
    mt5 = _fixture("mt5_history.html")
    result = review(mt5, source_format=importers.MT5_HISTORY_HTML)
    assert result.check("HIDDEN_CONTENT").status == STATUS_CLEAN
    deal = b'5001</td><td nowrap class="hidden"></td>'
    hidden = _altered(mt5, deal, deal.replace(b"></td>", b">note</td>"))
    result = review(hidden, source_format=importers.MT5_HISTORY_HTML)
    assert result.check("HIDDEN_CONTENT").status == STATUS_INFO
    assert result.check("HIDDEN_CONTENT").examples == (16,)
