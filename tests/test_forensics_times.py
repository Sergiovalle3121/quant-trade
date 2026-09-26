"""The time checks of the file-consistency battery: ``TIME_SANITY``,
``ROW_ORDER`` and ``MARKET_HOURS``.

Every fixture is read unaltered (no hits, or the documented reason) and
then with one cell changed; figures are text with a valid evidence tag and
never carry a name, an account or a symbol from the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows
from quant_trade.audit.forensics.checks import Context, times
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import EVIDENCE, MAX_EXAMPLES, RawOutcome
from quant_trade.audit.forensics.review import REASONS
from quant_trade.audit.forensics.rows import RawCell, RawRow, RawTable

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT_FIXTURES = ("mt4_statement.htm", "mt5_history.html", "mt5_tester.html", "mt4_tester.htm")
CSV_FIXTURES = ("tradingview_g1.csv", "tradingview_g3b.csv", "ninjatrader.csv")
PRIVATE_TEXT = ("12345678", "Demo Trader", "Synthetic", "SyntheticBroker-Demo", "FixtureEA")
CHECKS = (times.run_TIME_SANITY, times.run_ROW_ORDER, times.run_MARKET_HOURS)

#: Tiny exports built from the header shapes the importers recognise; no
#: real account, name or broker appears in them.
MYFXBOOK = (
    b"Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Close Price,"
    b"Commission,Swap,Pips,Profit,Gain,Comment\n"
    b",1004,12/21/2023 02:55,12/22/2023 16:07,EURUSD,Buy,0.10,0,0,1.09500,1.10000,-0.70,-0.20,"
    b"50.0,49.10,0.5,\n"
    b",1003,12/20/2023 17:55,12/21/2023 04:46,GBPUSD,Sell,0.10,0,0,1.27000,1.26500,-0.70,0.00,"
    b"50.0,49.30,0.5,\n"
    b",1002,12/19/2023 09:00,12/19/2023 15:30,EURUSD,Sell,0.10,0,0,1.09800,1.09700,-0.70,0.00,"
    b"10.0,9.30,0.1,\n"
    b",1001,12/18/2023 09:00,12/18/2023 12:00,USDJPY,Buy,0.10,0,0,142.000,142.500,-0.70,0.00,"
    b"50.0,35.00,0.3,\n"
    b",1000,12/01/2023 08:00,12/01/2023 08:00,,Deposit,,,,,,,,,1000.00,,\n"
    b"Open Trades\n"
    b",Ticket,Open Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Profit,Pips\n"
    b",1005,12/26/2023 09:00,EURUSD,Buy,0.10,0,0,1.10000,1.00,1.0\n"
)
MQL5 = (
    b"Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit;Comment\n"
    b"2025.11.14 13:08:13;Buy;0.10;EURUSD;1.16000;0.00000;0.00000;2025.11.14 18:22:40;1.16100;"
    b"-0.70;0.00;10.00;\n"
    b"2025.11.13 20:32:54;Sell;0.10;GBPUSD;1.31000;0.00000;0.00000;2025.11.14 09:00:00;1.30900;"
    b"-0.70;0.00;10.00;\n"
    b"2025.11.12 10:00:00;Buy;0.10;EURUSD;1.15900;0.00000;0.00000;2025.11.12 12:00:00;1.16000;"
    b"-0.70;0.00;10.00;\n"
    b"2025.11.11 10:00:00;Sell;0.10;AUDUSD;0.65000;0.00000;0.00000;2025.11.11 12:00:00;0.64900;"
    b"-0.70;0.00;10.00;\n"
    b"2025.11.01 00:00:00;Balance;;;;;;;;0.00;0.00;1000.00;Deposit\n"
)
FXBLUE = (
    b"Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,Open date,"
    b"Close date,Profit,Swap,Commission,Net profit,T/P,S/L,Pips,Result,Trade duration (hours),"
    b"Magic number,Order comment,Account\n"
    b"Deposit,1,,0,,0,0,2025/04/01 10:00:00,2025/04/01 10:00:00,2025/04/01,2025/04/01,1000,0,0,"
    b"1000,0,0,0,,0,0,,1\n"
    b"Closed position,2,EURUSD,0.1,Buy,1.09,1.1,2025/04/22 16:44:01,2025/04/23 10:00:00,"
    b"2025/04/22,2025/04/23,100,0,-0.7,99.3,0,0,100,Won,17,0,,1\n"
    b"Closed position,3,USDJPY,0.1,Sell,150,149,2025/04/23 09:00:00,2025/04/24 10:00:00,"
    b"2025/04/23,2025/04/24,60,0,-0.7,59.3,0,0,100,Won,25,0,,1\n"
    b"Closed position,4,USTEC,0.1,Sell,18000,17990,2025/04/24 09:00:00,2025/04/25 10:00:00,"
    b"2025/04/24,2025/04/25,10,0,-0.7,9.3,0,0,10,Won,25,0,,1\n"
    b"Open position,5,EURUSD,0.1,Buy,1.1,1.1,2025/04/25 09:00:00,1970/01/01 00:00:00,"
    b"2025/04/25,1970/01/01,0,0,0,0,0,0,0,,0,0,,1\n"
)
SAMPLES = {"myfxbook": MYFXBOOK, "mql5_signal": MQL5, "fxblue": FXBLUE}


def _table(data: bytes) -> RawTable:
    return rows.load(data, importers.detect_format(data))


def _load(name: str) -> RawTable:
    return _table((FIXTURES / name).read_bytes())


def _altered(name: str, old: str, new: str) -> RawTable:
    data = (FIXTURES / name).read_bytes()
    assert data.count(old.encode()) == 1, old
    return _table(data.replace(old.encode(), new.encode()))


def _context(table: RawTable) -> Context:
    return Context(family=table.family, header=read_header(table))


def _run(check: object, table: RawTable) -> RawOutcome:
    assert callable(check)
    outcome = check(table, _context(table))
    assert isinstance(outcome, RawOutcome)
    _assert_well_formed(outcome)
    return outcome


def _figure(outcome: RawOutcome, key: str) -> str:
    for name, value, _evidence in outcome.figures:
        if name == key:
            return value
    raise KeyError(key)


def _assert_well_formed(outcome: RawOutcome) -> None:
    for key, value, evidence in outcome.figures:
        assert isinstance(key, str) and isinstance(value, str), (key, value)
        assert evidence in EVIDENCE, (key, evidence)
        assert "." not in value or not value.replace(".", "").replace("-", "").isdigit(), value
    serialised = json.dumps([list(figure) for figure in outcome.figures])
    for private in PRIVATE_TEXT:
        assert private not in serialised, private
    assert list(outcome.examples) == sorted(outcome.examples)
    assert len(outcome.examples) <= MAX_EXAMPLES
    if outcome.not_measured:
        assert outcome.reason in REASONS
    else:
        assert outcome.reason == ""
        assert _figure(outcome, "n_hits") == str(outcome.hits)
        assert _figure(outcome, "n_rows").isdigit()
        assert (outcome.hits > 0) == bool(outcome.examples)


# ---------------------------------------------------------------------------
# Unaltered fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MT_FIXTURES)
@pytest.mark.parametrize("check", CHECKS, ids=lambda check: check.__name__)
def test_metatrader_fixtures_have_no_hits(name: str, check: object) -> None:
    outcome = _run(check, _load(name))
    assert not outcome.not_measured, outcome
    assert outcome.hits == 0 and outcome.examples == ()


def test_time_sanity_figures_on_fixtures() -> None:
    statement = _run(times.run_TIME_SANITY, _load("mt4_statement.htm"))
    assert _figure(statement, "n_rows") == "3"
    assert _figure(statement, "report_date") == "2024-03-08T18:30:00Z"
    assert _figure(statement, "report_date_source") == "header"
    assert _figure(statement, "max_ahead_seconds") == "0"
    assert ("report_date", "2024-03-08T18:30:00Z", "DECLARED") in statement.figures
    tester = _run(times.run_TIME_SANITY, _load("mt5_tester.html"))
    # Period end 2024.01.09 plus one day; deals, positions and filled orders.
    assert _figure(tester, "report_date") == "2024-01-10T00:00:00Z"
    assert _figure(tester, "report_date_source") == "period_end"
    assert _figure(tester, "n_rows") == "9"
    assert _figure(tester, "zero_duration") == "0"  # an order filling at placement is not one
    history = _run(times.run_TIME_SANITY, _load("mt5_history.html"))
    assert _figure(history, "n_rows") == "8"  # 2 positions + 2 orders + 4 deals
    mt4_tester = _run(times.run_TIME_SANITY, _load("mt4_tester.htm"))
    assert _figure(mt4_tester, "report_date") == "2024-01-07T00:00:00Z"
    assert _figure(mt4_tester, "n_rows") == "11"  # 12 rows minus the close at stop


def test_row_order_figures_on_fixtures() -> None:
    expected = {
        "mt4_statement.htm": ("3", "asc", "majority", "ticket", "0"),
        "mt5_history.html": ("4", "asc", "chronological", "deal", "0"),
        "mt5_tester.html": ("8", "asc", "chronological", "deal", "0"),
        "mt4_tester.htm": ("11", "asc", "chronological", "event", "0"),
        "tradingview_g1.csv": ("2", "desc", "majority", "entry", "0"),
        "tradingview_g3b.csv": ("3", "asc", "majority", "entry", "0"),
        "ninjatrader.csv": ("2", "asc", "majority", "exit", "0"),
    }
    for name, (n_rows, direction, rule, key, ties) in expected.items():
        outcome = _run(times.run_ROW_ORDER, _load(name))
        assert not outcome.not_measured and outcome.hits == 0, name
        assert _figure(outcome, "n_rows") == n_rows, name
        assert _figure(outcome, "direction") == direction, name
        assert ("direction_rule", rule, "DECLARED") in outcome.figures, name
        assert ("order_key", key, "DECLARED") in outcome.figures, name
        assert _figure(outcome, "ties") == ties, name


def test_market_hours_figures_on_fixtures() -> None:
    tester = _run(times.run_MARKET_HOURS, _load("mt5_tester.html"))
    assert _figure(tester, "symbols_measured") == "2"  # EURUSD and GBPUSD; gold is not listed
    assert _figure(tester, "timestamps_measured") == "5"
    assert _figure(tester, "core_hits") == "0"
    assert _figure(tester, "holiday_hits") == "0"
    assert ("window", "sat13_sun08", "DECLARED") in tester.figures
    assert _figure(tester, "inferred_offset_minutes") == "0"
    statement = _run(times.run_MARKET_HOURS, _load("mt4_statement.htm"))
    assert _figure(statement, "symbols_measured") == "1"
    assert _figure(statement, "timestamps_measured") == "2"
    history = _run(times.run_MARKET_HOURS, _load("mt5_history.html"))
    assert _figure(history, "n_rows") == "3"  # the EURUSD position, its two deals
    assert _figure(history, "timestamps_measured") == "4"
    mt4_tester = _run(times.run_MARKET_HOURS, _load("mt4_tester.htm"))
    assert _figure(mt4_tester, "symbols_measured") == "1"  # from the Symbol label
    assert _figure(mt4_tester, "n_rows") == "7"  # buy/sell/close/tp/sl events only


@pytest.mark.parametrize("name", CSV_FIXTURES)
def test_csv_fixtures(name: str) -> None:
    table = _load(name)
    sanity = _run(times.run_TIME_SANITY, table)
    assert sanity.not_measured and sanity.reason == "no_header_date"
    assert ("after_report_date", "no_header_date", "NOT_MEASURED") in sanity.figures
    assert _figure(sanity, "unparseable") == "0"
    order = _run(times.run_ROW_ORDER, table)
    assert not order.not_measured and order.hits == 0
    hours = _run(times.run_MARKET_HOURS, table)
    assert hours.not_measured
    assert hours.reason == (
        "no_column" if table.family == families.TRADINGVIEW else "no_listed_symbol"
    )


@pytest.mark.parametrize("family", sorted(SAMPLES))
def test_account_export_samples(family: str) -> None:
    table = _table(SAMPLES[family])
    assert table.family == family
    sanity = _run(times.run_TIME_SANITY, table)
    assert sanity.not_measured and sanity.reason == "no_header_date"
    assert _figure(sanity, "n_rows") == "4"  # FX Blue: three closed plus one open position
    order = _run(times.run_ROW_ORDER, table)
    assert order.hits == 0
    assert _figure(order, "direction") == ("asc" if family == "fxblue" else "desc")
    assert ("order_key", "close", "DECLARED") in order.figures
    hours = _run(times.run_MARKET_HOURS, table)
    assert not hours.not_measured and hours.hits == 0
    assert _figure(hours, "symbols_measured") == ("2" if family == "fxblue" else "3")


@pytest.mark.parametrize("name", ("backtestingpy_trades.csv", "quantconnect_trades.csv"))
@pytest.mark.parametrize("check", CHECKS, ids=lambda check: check.__name__)
def test_other_formats_are_not_covered(name: str, check: object) -> None:
    outcome = _run(check, _load(name))
    assert outcome.not_measured and outcome.reason == "format_not_covered"


# ---------------------------------------------------------------------------
# TIME_SANITY alterations
# ---------------------------------------------------------------------------

CLOSE_OF_FIRST_TRADE = "2024.03.05 11:40:31"  # raw row 4 of the MT4 statement


def test_time_sanity_unparseable_cell() -> None:
    table = _altered("mt4_statement.htm", CLOSE_OF_FIRST_TRADE, "2024.02.30 11:40:31")
    outcome = _run(times.run_TIME_SANITY, table)
    assert outcome.hits == 1 and outcome.examples == (4,)
    assert _figure(outcome, "unparseable") == "1"
    assert _figure(outcome, "close_before_open_over_1h") == "0"


def test_time_sanity_close_before_open() -> None:
    table = _altered("mt4_statement.htm", CLOSE_OF_FIRST_TRADE, "2024.03.04 07:00:00")
    outcome = _run(times.run_TIME_SANITY, table)
    assert outcome.hits == 1 and outcome.examples == (4,)
    assert _figure(outcome, "close_before_open_over_1h") == "1"
    assert _figure(outcome, "backwards_within_1h") == "0"


def test_time_sanity_backwards_within_an_hour_is_a_figure_only() -> None:
    table = _altered("mt4_statement.htm", CLOSE_OF_FIRST_TRADE, "2024.03.04 08:45:00")
    outcome = _run(times.run_TIME_SANITY, table)
    assert outcome.hits == 0
    assert _figure(outcome, "backwards_within_1h") == "1"
    zero = _altered("mt4_statement.htm", CLOSE_OF_FIRST_TRADE, "2024.03.04 09:15:02")
    assert _figure(_run(times.run_TIME_SANITY, zero), "zero_duration") == "1"


def test_time_sanity_row_after_report_date() -> None:
    table = _altered("mt4_statement.htm", CLOSE_OF_FIRST_TRADE, "2024.03.10 09:00:00")
    outcome = _run(times.run_TIME_SANITY, table)
    assert outcome.hits == 1 and outcome.examples == (4,)
    assert _figure(outcome, "after_report_date") == "1"
    assert _figure(outcome, "max_ahead_seconds") == str((1 * 24 + 14) * 3600 + 30 * 60)
    # Inside the 14 h server-clock allowance: a figure, not a hit.
    ahead = _altered("mt4_statement.htm", CLOSE_OF_FIRST_TRADE, "2024.03.09 08:00:00")
    outcome = _run(times.run_TIME_SANITY, ahead)
    assert outcome.hits == 0
    assert _figure(outcome, "max_ahead_seconds") == str(13 * 3600 + 30 * 60)


def test_time_sanity_without_header_date() -> None:
    table = _altered("mt4_statement.htm", "2024 March 8, 18:30", "")
    outcome = _run(times.run_TIME_SANITY, table)
    assert outcome.not_measured and outcome.reason == "no_header_date"
    assert _figure(outcome, "n_rows") == "3"


def test_time_sanity_tester_rows_after_period_end() -> None:
    # Deal 9 of the MT5 tester, raw row 31, moved two days past the period.
    table = _altered("mt5_tester.html", "2024.01.05 14:00:00", "2024.01.11 14:00:00")
    outcome = _run(times.run_TIME_SANITY, table)
    assert outcome.hits == 1 and outcome.examples == (31,)
    assert _figure(outcome, "after_report_date") == "1"
    # The end-of-test deal is excluded even when it is moved.
    end = _altered("mt5_tester.html", "2024.01.08 10:00:00", "2024.01.12 10:00:00")
    assert _run(times.run_TIME_SANITY, end).hits == 0
    # MT4 tester: the buy at raw row 16 moved past the period end.
    mt4 = _altered("mt4_tester.htm", "2024.01.04 12:00", "2024.01.10 12:00")
    outcome = _run(times.run_TIME_SANITY, mt4)
    assert outcome.hits == 1 and outcome.examples == (16,)


def test_time_sanity_mt5_history_unparseable_deal() -> None:
    # The withdrawal deal is a balance row: excluded. The EURUSD position's
    # open time appears in the Positions, Deals and Orders tables.
    data = (FIXTURES / "mt5_history.html").read_bytes()
    assert data.count(b"2024.03.04 13:02:44") == 2  # position close, deal
    table = _table(data.replace(b"2024.03.04 13:02:44", b"2024.03.04 25:02:44"))
    outcome = _run(times.run_TIME_SANITY, table)
    assert outcome.hits == 2 and outcome.examples == (8, 18)
    assert _figure(outcome, "unparseable") == "2"


# ---------------------------------------------------------------------------
# ROW_ORDER alterations
# ---------------------------------------------------------------------------


def test_row_order_inversion_in_tester_deals() -> None:
    # Deal 5 (raw row 27) moved before deal 4 (2024.01.03 10:15).
    table = _altered("mt5_tester.html", "2024.01.04 08:00:00", "2024.01.03 09:00:00")
    outcome = _run(times.run_ROW_ORDER, table)
    assert outcome.hits == 1 and outcome.examples == (27,)
    assert _figure(outcome, "direction") == "asc"


def test_row_order_tester_direction_is_fixed() -> None:
    # A descending tester table is all inversions: the rule is chronological.
    data = (FIXTURES / "mt5_tester.html").read_bytes()
    swapped = data.replace(b"2024.01.02 09:00:00</td><td>2", b"2024.01.09 09:00:00</td><td>2")
    outcome = _run(times.run_ROW_ORDER, _table(swapped))
    assert outcome.hits == 1 and outcome.examples == (25,)


def test_row_order_inversion_in_tradingview_entries() -> None:
    # G3b lists oldest first; trade 2's entry (raw row 4) moved after trade 3's
    # (raw row 6), which then reads as the step against the majority.
    table = _altered("tradingview_g3b.csv", "2026-03-03 10:00", "2026-03-05 10:00")
    outcome = _run(times.run_ROW_ORDER, table)
    assert outcome.hits == 1 and outcome.examples == (6,)
    assert _figure(outcome, "direction") == "asc"
    # Exit rows never count: moving one changes nothing.
    exits = _altered("tradingview_g3b.csv", "2026-03-03 13:00", "2026-03-09 13:00")
    assert _run(times.run_ROW_ORDER, exits).hits == 0


def test_row_order_inversion_in_signal_export() -> None:
    data = MQL5.replace(b"2025.11.12 12:00:00", b"2025.11.15 12:00:00")
    outcome = _run(times.run_ROW_ORDER, _table(data))
    assert outcome.hits == 1 and outcome.examples == (3,)
    assert _figure(outcome, "direction") == "desc"


def test_row_order_statement_keeps_the_monotonic_key() -> None:
    # The Account History tab exports in whatever column it was sorted by:
    # here tickets and open times zigzag while the close times rise.
    data = (FIXTURES / "mt4_statement.htm").read_bytes()
    head, _sep, tail = data.rpartition(b"2024.03.04 10:00:00")  # the third trade's open
    zigzag = (head + b"2024.03.01 09:00:00" + tail).replace(b"1000005", b"1000000")
    outcome = _run(times.run_ROW_ORDER, _table(zigzag))
    assert outcome.hits == 1 and outcome.examples == (7,)
    assert ("order_key", "ticket", "DECLARED") in outcome.figures
    by_close = zigzag.replace(b"2024.03.05 11:40:31", b"2024.03.04 12:00:00")
    outcome = _run(times.run_ROW_ORDER, _table(by_close))
    assert outcome.hits == 0
    assert ("order_key", "close", "DECLARED") in outcome.figures
    assert _figure(outcome, "direction") == "asc"


def test_row_order_needs_two_rows() -> None:
    table = _table(FXBLUE.split(b"\n")[0] + b"\n" + FXBLUE.split(b"\n")[2] + b"\n")
    outcome = _run(times.run_ROW_ORDER, table)
    assert outcome.not_measured and outcome.reason == "no_qualifying_row"


def test_row_order_grouped_statement_restarts_at_subtotals() -> None:
    # Third trade given the lowest ticket and the earliest open time: every
    # key zigzags, so the ticket key (the platform's own) reports it.
    data = (FIXTURES / "mt4_statement.htm").read_bytes()
    head, _sep, tail = data.rpartition(b"2024.03.04 10:00:00")
    scrambled = (head + b"2024.03.01 09:00:00" + tail).replace(b"1000005", b"1000000")
    outcome = _run(times.run_ROW_ORDER, _table(scrambled))
    assert outcome.hits == 1 and outcome.examples == (7,)
    # A "Total for" subtotal line before it (a grouped report) starts a new
    # run: nothing is compared across the line.
    marker = b'<tr align=right><td title="from #1000003[sl]">'
    assert scrambled.count(marker) == 1
    grouped = scrambled.replace(
        marker, b"<tr><td>Total for: group</td><td>-1.00</td></tr>\n" + marker
    )
    table = _table(grouped)
    assert table.rows[7].kind == rows.KIND_OTHER and table.rows[8].kind == rows.KIND_MT4_TRADE
    assert [item.chain for item in times._timed_rows(table)] == [0, 0, 1]
    outcome = _run(times.run_ROW_ORDER, table)
    assert outcome.hits == 0 and _figure(outcome, "n_rows") == "3"
    assert ("order_key", "ticket", "DECLARED") in outcome.figures


def test_row_order_ninjatrader_accounts_are_separate_runs() -> None:
    data = (FIXTURES / "ninjatrader.csv").read_bytes().rstrip(b"\r\n") + b"\n"
    extra = (
        b"3,ES 03-26,Other,DemoStrategy,Long,1,6000.00,6001.00,1/2/2026 9:35:00 AM,"
        b"1/2/2026 10:05:00 AM,Long,Profit target,$50.00,$50.00,$5.08,$0.00,$0.00,$0.00,"
        b"$0.00,$10.00,$60.00,$10.00,6,\n"
        b"4,ES 03-26,Other,DemoStrategy,Short,1,6000.00,5999.00,1/3/2026 9:35:00 AM,"
        b"1/3/2026 10:05:00 AM,Short,Profit target,$50.00,$100.00,$5.08,$0.00,$0.00,$0.00,"
        b"$0.00,$10.00,$60.00,$10.00,3,\n"
    )
    outcome = _run(times.run_ROW_ORDER, _table(data + extra))
    assert outcome.hits == 0 and _figure(outcome, "n_rows") == "4"
    same_account = data + extra.replace(b",Other,", b",Backtest,")
    outcome = _run(times.run_ROW_ORDER, _table(same_account))
    assert outcome.hits == 1 and outcome.examples == (3,)


def test_ambiguous_csv_dates_are_not_examined() -> None:
    # Without AM/PM every date could be day-first or month-first; the
    # importers refuse such a file and the checks examine nothing.
    data = (FIXTURES / "ninjatrader.csv").read_bytes().replace(b" AM", b"").replace(b" PM", b"")
    table = _table(data)
    sanity = _run(times.run_TIME_SANITY, table)
    assert sanity.not_measured and _figure(sanity, "n_rows") == "0"
    assert _figure(sanity, "unparseable") == "0"
    order = _run(times.run_ROW_ORDER, table)
    assert order.not_measured and order.reason == "no_qualifying_row"


# ---------------------------------------------------------------------------
# MARKET_HOURS alterations
# ---------------------------------------------------------------------------

GBPUSD_DEAL_TIME = "2024.01.05 14:00:00"  # deal 9, raw row 31, a listed pair
XAUUSD_DEAL_TIME = "2024.01.04 08:00:00"  # deal 5, raw row 27, not listed


def test_market_hours_saturday_afternoon_is_a_hit() -> None:
    table = _altered("mt5_tester.html", GBPUSD_DEAL_TIME, "2024.01.06 15:00:00")
    outcome = _run(times.run_MARKET_HOURS, table)
    assert outcome.hits == 1 and outcome.examples == (31,)
    assert _figure(outcome, "core_hits") == "1"


def test_market_hours_core_edge_is_a_figure_only() -> None:
    table = _altered("mt5_tester.html", GBPUSD_DEAL_TIME, "2024.01.06 12:30:00")
    outcome = _run(times.run_MARKET_HOURS, table)
    assert outcome.hits == 0
    assert _figure(outcome, "core_hits") == "1"
    sunday = _altered("mt5_tester.html", GBPUSD_DEAL_TIME, "2024.01.07 08:30:00")
    outcome = _run(times.run_MARKET_HOURS, sunday)
    assert outcome.hits == 0 and _figure(outcome, "core_hits") == "1"
    early_sunday = _altered("mt5_tester.html", GBPUSD_DEAL_TIME, "2024.01.07 07:59:00")
    assert _run(times.run_MARKET_HOURS, early_sunday).hits == 1


def test_market_hours_ignores_unlisted_symbols_and_end_of_test() -> None:
    gold = _altered("mt5_tester.html", XAUUSD_DEAL_TIME, "2024.01.06 15:00:00")
    assert _run(times.run_MARKET_HOURS, gold).hits == 0
    end = _altered("mt5_tester.html", "2024.01.08 10:00:00", "2024.01.06 15:00:00")
    assert _run(times.run_MARKET_HOURS, end).hits == 0


def test_market_hours_holiday_is_a_figure() -> None:
    table = _altered("mt5_tester.html", GBPUSD_DEAL_TIME, "2024.01.01 14:00:00")
    outcome = _run(times.run_MARKET_HOURS, table)
    assert outcome.hits == 0
    assert _figure(outcome, "holiday_hits") == "1"


def test_market_hours_no_listed_symbol() -> None:
    table = _altered("mt4_statement.htm", "eurusd", "us30")
    outcome = _run(times.run_MARKET_HOURS, table)
    assert outcome.not_measured and outcome.reason == "no_listed_symbol"


def test_market_hours_on_account_exports() -> None:
    # Myfxbook: a close on Saturday 15:00 (2023-12-23) on a listed pair.
    weekend = MYFXBOOK.replace(b"12/22/2023 16:07", b"12/23/2023 15:00")
    outcome = _run(times.run_MARKET_HOURS, _table(weekend))
    assert outcome.hits == 1 and outcome.examples == (1,)
    # FX Blue: an open position's placeholder close time is never examined.
    outcome = _run(times.run_MARKET_HOURS, _table(FXBLUE))
    assert _figure(outcome, "timestamps_measured") == "5"


def test_inferred_offset_prefers_the_smallest_clean_offset() -> None:
    friday_2330 = 4 * 1440 + 23 * 60 + 30
    monday_0030 = 30
    assert times._inferred_offset([friday_2330, monday_0030]) == 120
    assert times._inferred_offset([]) == 0
    assert times._inferred_offset([2 * 1440 + 600]) == 0  # a Wednesday: every offset is clean


def test_mt5_order_cells_follow_the_header() -> None:
    xlsx_header = ("Open Time", "Order", "Symbol", "Type", "Volume", "", "Price", "S / L",
                   "T / P", "Time", "", "State", "Comment")  # fmt: skip
    row = RawRow(1, ("x",) * 14, (RawCell("x"),) * 14, rows.SECTION_ORDERS, rows.KIND_MT5_ORDER, 0)
    table = RawTable("mt5_tester_xlsx", families.MT5_TESTER, (row,), (), "none", "none", "none", 0,
                     False, header_texts=((0, xlsx_header),))  # fmt: skip
    assert times._mt5_order_cells(table, row) == (9, 11)
    localised = RawTable("mt5_tester_html", families.MT5_TESTER, (row,), (), "none", "none",
                         "none", 0, False, header_texts=((0, ("Hora",) * 11),))  # fmt: skip
    assert times._mt5_order_cells(localised, row) == (8, 9)


# ---------------------------------------------------------------------------
# Determinism and hygiene
# ---------------------------------------------------------------------------


def _every_table() -> list[tuple[str, RawTable]]:
    found = [(name, _load(name)) for name in MT_FIXTURES + CSV_FIXTURES]
    found += [(name, _table(data)) for name, data in SAMPLES.items()]
    found.append(("saturday", _altered("mt5_tester.html", GBPUSD_DEAL_TIME, "2024.01.06 15:00:00")))
    return found


@pytest.mark.parametrize("check", CHECKS, ids=lambda check: check.__name__)
def test_outcomes_are_deterministic(check: object) -> None:
    for name, table in _every_table():
        first, second = _run(check, table), _run(check, table)
        assert first == second, (name, check)


def test_no_private_text_in_any_figure() -> None:
    for name, table in _every_table():
        for check in CHECKS:
            serialised = json.dumps([list(figure) for figure in _run(check, table).figures])
            for private in PRIVATE_TEXT:
                assert private not in serialised, (name, check.__name__)
            for symbol in ("EURUSD", "GBPUSD", "XAUUSD", "eurusd"):
                assert symbol not in serialised, (name, check.__name__)
