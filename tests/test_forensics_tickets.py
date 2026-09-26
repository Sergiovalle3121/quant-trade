"""Ticket and numbering checks of the forensics battery, on the fixtures.

Every test is offline: the fixtures are read from disk, altered in memory
by one edit, and the outcome is compared with what the platform's own
numbering predicts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import rows
from quant_trade.audit.forensics.checks import Context, tickets
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import EVIDENCE, MEASURED, NOT_MEASURED, RawOutcome
from quant_trade.audit.forensics.review import REASONS, review

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
FORBIDDEN = ("12345678", "Demo Trader", "Synthetic", "FixtureEA")
CHECKS = ("DEAL_SEQUENCE", "TESTER_NUMBERING", "TICKET_ORDER", "DUPLICATE_TICKET")
HTML_FIXTURES = ("mt4_statement.htm", "mt5_history.html", "mt5_tester.html", "mt4_tester.htm")
CSV_FIXTURES = ("tradingview_g1.csv", "tradingview_g3b.csv", "ninjatrader.csv")

MYFXBOOK = (
    "Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Close Price,"
    "Commission,Swap,Pips,Profit,Comment\n"
    "101,03/14/2024 09:15,03/15/2024 11:40,EURUSD,Buy,1.00,0,0,1.08500,1.08700,-7.00,-6.20,"
    "20.0,200.00,\n"
    "102,03/14/2024 10:00,03/14/2024 13:02,XAUUSD,Sell,0.50,0,0,2080.10,2084.60,-3.50,0.00,"
    "-45.0,-225.00,\n"
    "103,03/15/2024 12:00,03/16/2024 09:30,GBPUSD,Buy,0.10,0,0,1.26000,1.26410,-1.00,0.00,"
    "41.0,41.00,\n"
    "104,03/14/2024 10:00,03/16/2024 09:30,XAUUSD,Sell,0.25,0,0,2080.10,2083.00,-1.75,-2.05,"
    "-29.0,-72.50,from #102\n"
    "105,03/13/2024 08:00,03/13/2024 08:00,,Deposit,,,,,,,,,1000.00,\n"
    "Open Trades\n"
    ",Ticket,Open Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Profit\n"
    ",106,03/17/2024 08:00,EURUSD,Buy,0.200,0,0,1.09000,5.00\n"
)

FXBLUE_HEADER = (
    "Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,Open date,"
    "Close date,Profit,Swap,Commission,Net profit,T/P,S/L,Pips,Result,Trade duration (hours),"
    "Magic number,Order comment,Account\n"
)
FXBLUE_ROWS = (
    "Closed position,201,EURUSD,1.00,Buy,1.08500,1.08700,2025/03/04 09:15:02,"
    "2025/03/05 11:40:31,2025/03/04,2025/03/05,200.00,-6.20,-7.00,186.80,1.08700,1.08000,20.0,"
    "Won,26.4,0,,{account}\n"
    "Closed position,202,XAUUSD,0.50,Sell,2080.10,2084.60,2025/03/04 10:00:00,"
    "2025/03/04 13:02:44,2025/03/04,2025/03/04,-225.00,0.00,-3.50,-228.50,0,0,-45.0,Lost,3.0,0,"
    ",{account}\n"
    "Closed position,203,GBPUSD,0.10,Buy,1.26000,1.26410,2025/03/05 12:00:00,"
    "2025/03/06 09:30:00,2025/03/05,2025/03/06,41.00,0.00,-1.00,40.00,0,0,41.0,Won,21.5,0,,"
    "{account}\n"
    "Deposit,204,,0,,0,0,2025/03/01 08:00:00,2025/03/01 08:00:00,2025/03/01,2025/03/01,"
    "1000.00,0,0,1000.00,0,0,0,,0,0,,{account}\n"
    "Open position,205,EURUSD,0.10,Buy,1.09000,0,2025/03/07 08:00:00,1970/01/01 00:00:00,"
    "2025/03/07,1970/01/01,5.00,0,0,5.00,0,0,5.0,,0,0,,{account}\n"
)


def _fxblue(*accounts: str) -> bytes:
    body = "".join(FXBLUE_ROWS.format(account=account) for account in accounts)
    return (FXBLUE_HEADER + body).encode()


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _load(data: bytes) -> tuple[rows.RawTable, Context]:
    table = rows.load(data, importers.detect_format(data))
    header = read_header(table)
    return table, Context(family=table.family, header=header, currency=header.currency)


def _run(check: str, data: bytes) -> RawOutcome:
    table, ctx = _load(data)
    outcome: RawOutcome = getattr(tickets, f"run_{check}")(table, ctx)
    _assert_well_formed(outcome)
    return outcome


def _altered(data: bytes, old: str, new: str, *, count: int = 1) -> bytes:
    assert data.count(old.encode()) == count, old
    return data.replace(old.encode(), new.encode())


def _without_lines(data: bytes, *markers: str) -> bytes:
    lines = data.split(b"\n")
    kept = [line for line in lines if not any(marker.encode() in line for marker in markers)]
    assert len(kept) == len(lines) - len(markers), markers
    return b"\n".join(kept)


def _figures(outcome: RawOutcome) -> dict[str, str]:
    return {key: value for key, value, _ in outcome.figures}


def _evidence(outcome: RawOutcome) -> dict[str, str]:
    return {key: evidence for key, _, evidence in outcome.figures}


def _assert_well_formed(outcome: RawOutcome) -> None:
    for key, value, evidence in outcome.figures:
        assert isinstance(key, str) and key
        assert isinstance(value, str) and value.isdigit(), (key, value)
        assert evidence in EVIDENCE
        for word in FORBIDDEN:
            assert word not in value
    assert list(outcome.examples) == sorted(set(outcome.examples))
    assert len(outcome.examples) <= 5
    if outcome.not_measured:
        assert outcome.reason in REASONS
        assert outcome.hits == 0
    else:
        assert outcome.reason == ""
        assert _figures(outcome)["n_hits"] == str(outcome.hits)
        assert "n_rows" in _figures(outcome)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", HTML_FIXTURES + CSV_FIXTURES)
@pytest.mark.parametrize("check", CHECKS)
def test_unaltered_fixture_has_no_hit_and_is_deterministic(name: str, check: str) -> None:
    first = _run(check, _fixture(name))
    second = _run(check, _fixture(name))
    assert first == second
    assert first.hits == 0
    assert first.examples == ()


@pytest.mark.parametrize("name", HTML_FIXTURES + CSV_FIXTURES)
def test_review_runs_every_check(name: str) -> None:
    data = _fixture(name)
    result = review(data, source_format=importers.detect_format(data))
    for check in CHECKS:
        found = result.check(check)
        assert found.status in {"CLEAN", "NOT_MEASURED"}
        assert found.applies == (found.status != "NOT_MEASURED")
    serialised = str(result.as_dict())
    for word in FORBIDDEN:
        assert word not in serialised


# ---------------------------------------------------------------------------
# DEAL_SEQUENCE
# ---------------------------------------------------------------------------


def test_deal_sequence_history_fixture() -> None:
    outcome = _run("DEAL_SEQUENCE", _fixture("mt5_history.html"))
    assert _figures(outcome) == {
        "n_rows": "6",
        "n_deals": "4",
        "n_orders": "2",
        "n_hits": "0",
        "ticket_inversions": "0",
        "time_inversions": "0",
        "order_inversions": "0",
        "orders_missing_for_deals": "2",
    }
    assert set(_evidence(outcome).values()) == {MEASURED}


def test_deal_sequence_tester_fixture_counts_orders_missing_as_figure() -> None:
    outcome = _run("DEAL_SEQUENCE", _fixture("mt5_tester.html"))
    figures = _figures(outcome)
    assert (figures["n_deals"], figures["n_orders"]) == ("9", "1")
    assert figures["orders_missing_for_deals"] == "8"
    assert outcome.hits == 0


def test_deal_sequence_ticket_inversion() -> None:
    data = _altered(_fixture("mt5_history.html"), "<td nowrap>9003</td>", "<td nowrap>9001</td>")
    outcome = _run("DEAL_SEQUENCE", data)
    assert outcome.hits == 1
    assert _figures(outcome)["ticket_inversions"] == "1"
    assert _figures(outcome)["time_inversions"] == "0"
    assert outcome.examples == (18,)


def test_deal_sequence_time_inversion() -> None:
    data = _altered(
        _fixture("mt5_history.html"),
        "<td nowrap>2024.03.05 11:40:31</td>",
        "<td nowrap>2024.03.04 12:00:00</td>",
    )
    outcome = _run("DEAL_SEQUENCE", data)
    assert outcome.hits == 1
    assert _figures(outcome)["time_inversions"] == "1"
    assert outcome.examples == (19,)


def test_deal_sequence_order_inversion_is_a_figure_only() -> None:
    data = _altered(
        _fixture("mt5_history.html"),
        "<td>5001</td><td>EURUSD</td><td>buy</td><td>0.10 / 0.10</td>",
        "<td>5003</td><td>EURUSD</td><td>buy</td><td>0.10 / 0.10</td>",
    )
    outcome = _run("DEAL_SEQUENCE", data)
    assert outcome.hits == 0
    assert _figures(outcome)["order_inversions"] == "1"
    assert _figures(outcome)["orders_missing_for_deals"] == "2"


def test_deal_sequence_without_orders_table() -> None:
    data = _altered(_fixture("mt5_history.html"), "<td>0.10 / 0.10</td>", "<td>x</td>", count=2)
    outcome = _run("DEAL_SEQUENCE", data)
    assert outcome.hits == 0
    assert _figures(outcome)["n_orders"] == "0"
    assert _evidence(outcome)["order_inversions"] == NOT_MEASURED
    assert _evidence(outcome)["orders_missing_for_deals"] == NOT_MEASURED


def test_deal_sequence_needs_two_trade_deals() -> None:
    data = _without_lines(
        _fixture("mt5_history.html"),
        "<td nowrap>9002</td>",
        "<td nowrap>9003</td>",
        "<td nowrap>9004</td>",
    )
    outcome = _run("DEAL_SEQUENCE", data)
    assert outcome.not_measured and outcome.reason == "no_qualifying_row"
    assert _figures(outcome)["n_deals"] == "1"


@pytest.mark.parametrize("name", ("mt4_statement.htm", "mt4_tester.htm", "ninjatrader.csv"))
def test_deal_sequence_other_formats(name: str) -> None:
    outcome = _run("DEAL_SEQUENCE", _fixture(name))
    assert outcome.not_measured and outcome.reason == "format_not_covered"


# ---------------------------------------------------------------------------
# TESTER_NUMBERING
# ---------------------------------------------------------------------------


def test_tester_numbering_mt4_fixture() -> None:
    outcome = _run("TESTER_NUMBERING", _fixture("mt4_tester.htm"))
    figures = _figures(outcome)
    assert figures == {
        "n_rows": "12",
        "n_hits": "0",
        "expected_max": "12",
        "seen": "12",
        "duplicates": "0",
        "out_of_order": "0",
        "gaps": "0",
        "deal_gaps": "0",
        "order_gaps": "0",
        "orders_single_row": "0",
    }
    evidence = _evidence(outcome)
    assert evidence["gaps"] == MEASURED
    assert evidence["deal_gaps"] == NOT_MEASURED
    assert evidence["orders_single_row"] == MEASURED


def test_tester_numbering_mt4_deleted_row_leaves_a_gap() -> None:
    data = _without_lines(_fixture("mt4_tester.htm"), "<td>5</td><td class=msdate>")
    outcome = _run("TESTER_NUMBERING", data)
    assert outcome.hits == 1
    figures = _figures(outcome)
    assert (figures["gaps"], figures["expected_max"], figures["seen"]) == ("1", "11", "12")
    assert figures["orders_single_row"] == "0"
    assert outcome.examples == (14,)


def test_tester_numbering_mt4_order_left_with_one_closing_row() -> None:
    data = _without_lines(
        _fixture("mt4_tester.htm"),
        "<td>4</td><td class=msdate>",
        "<td>5</td><td class=msdate>",
    )
    outcome = _run("TESTER_NUMBERING", data)
    figures = _figures(outcome)
    assert (outcome.hits, figures["gaps"], figures["orders_single_row"]) == (2, "2", "1")


def test_tester_numbering_mt4_open_order_with_one_row_is_not_counted() -> None:
    data = _without_lines(
        _fixture("mt4_tester.htm"),
        "<td>5</td><td class=msdate>",
        "<td>6</td><td class=msdate>",
    )
    outcome = _run("TESTER_NUMBERING", data)
    assert _figures(outcome)["orders_single_row"] == "0"
    assert _figures(outcome)["gaps"] == "2"


def test_tester_numbering_mt4_duplicate_number() -> None:
    data = _altered(
        _fixture("mt4_tester.htm"), "<td>8</td><td class=msdate>", "<td>7</td><td class=msdate>"
    )
    outcome = _run("TESTER_NUMBERING", data)
    figures = _figures(outcome)
    assert (figures["duplicates"], figures["gaps"], outcome.hits) == ("1", "1", 2)
    assert outcome.examples == (17, 18)


def test_tester_numbering_mt4_out_of_order_number() -> None:
    data = _altered(
        _fixture("mt4_tester.htm"), "<td>3</td><td class=msdate>", "<td>13</td><td class=msdate>"
    )
    outcome = _run("TESTER_NUMBERING", data)
    figures = _figures(outcome)
    assert (figures["out_of_order"], figures["gaps"], figures["seen"]) == ("1", "1", "13")
    assert outcome.hits == 2
    assert outcome.examples == (12, 13)


def test_tester_numbering_mt5_fixture() -> None:
    outcome = _run("TESTER_NUMBERING", _fixture("mt5_tester.html"))
    figures = _figures(outcome)
    assert figures == {
        "n_rows": "11",
        "n_hits": "0",
        "expected_max": "10",
        "seen": "10",
        "duplicates": "0",
        "out_of_order": "0",
        "gaps": "0",
        "deal_gaps": "0",
        "order_gaps": "0",
        "orders_single_row": "0",
    }
    evidence = _evidence(outcome)
    assert evidence["deal_gaps"] == MEASURED
    assert evidence["gaps"] == NOT_MEASURED


def test_tester_numbering_mt5_duplicate_deal() -> None:
    data = _altered(
        _fixture("mt5_tester.html"),
        "<td>2024.01.03 10:15:00</td><td>4</td>",
        "<td>2024.01.03 10:15:00</td><td>3</td>",
    )
    outcome = _run("TESTER_NUMBERING", data)
    figures = _figures(outcome)
    assert (outcome.hits, figures["duplicates"], figures["deal_gaps"]) == (1, "1", "1")
    assert outcome.examples == (26,)


def test_tester_numbering_mt5_out_of_order_deal_and_gap_figure() -> None:
    data = _altered(
        _fixture("mt5_tester.html"),
        "<td>2024.01.04 16:00:00</td><td>7</td>",
        "<td>2024.01.04 16:00:00</td><td>70</td>",
    )
    outcome = _run("TESTER_NUMBERING", data)
    figures = _figures(outcome)
    assert (outcome.hits, figures["out_of_order"]) == (1, "1")
    assert (figures["deal_gaps"], figures["expected_max"], figures["seen"]) == ("60", "10", "70")
    assert outcome.examples == (30,)


def test_tester_numbering_mt5_duplicate_order() -> None:
    fixture = _fixture("mt5_tester.html")
    row = fixture[fixture.index(b'<tr bgcolor="#FFFFFF" align=right><td>2024.01.02 09:00:00') :]
    row = row[: row.index(b"</tr>") + 5]
    data = fixture.replace(row, row + b"\n   " + row)
    outcome = _run("TESTER_NUMBERING", data)
    assert outcome.hits == 1
    assert _figures(outcome)["duplicates"] == "1"
    assert outcome.examples == (20,)


@pytest.mark.parametrize("name", ("mt4_statement.htm", "mt5_history.html", "tradingview_g1.csv"))
def test_tester_numbering_other_formats(name: str) -> None:
    outcome = _run("TESTER_NUMBERING", _fixture(name))
    assert outcome.not_measured and outcome.reason == "format_not_covered"


# ---------------------------------------------------------------------------
# TICKET_ORDER
# ---------------------------------------------------------------------------


def test_ticket_order_mt4_fixture_measures_close_inversion_without_a_hit() -> None:
    outcome = _run("TICKET_ORDER", _fixture("mt4_statement.htm"))
    assert _figures(outcome) == {
        "n_rows": "2",
        "n_hits": "0",
        "inversions_open_time": "0",
        "inversions_close_time": "1",
        "max_backwards_seconds": "0",
        "max_backwards_seconds_close": "81467",
    }


def test_ticket_order_mt4_open_time_inversion() -> None:
    data = _altered(_fixture("mt4_statement.htm"), "2024.03.04 09:15:02", "2024.03.04 11:00:00")
    outcome = _run("TICKET_ORDER", data)
    assert outcome.hits == 1
    assert _figures(outcome)["max_backwards_seconds"] == "3600"
    assert outcome.examples == (5,)


def test_ticket_order_mt4_backwards_within_allowance() -> None:
    data = _altered(_fixture("mt4_statement.htm"), "2024.03.04 09:15:02", "2024.03.04 10:00:30")
    outcome = _run("TICKET_ORDER", data)
    assert outcome.hits == 0
    assert _figures(outcome)["max_backwards_seconds"] == "30"


def test_ticket_order_mt4_comment_in_following_row_still_excludes_remainder() -> None:
    fixture = _fixture("mt4_statement.htm")
    untitled = _altered(fixture, '<td title="from #1000003[sl]">1000005</td>', "<td>1000005</td>")
    assert _figures(_run("TICKET_ORDER", untitled))["n_rows"] == "3"
    commented = _altered(
        untitled,
        "<td class=mspt>-145.00</td></tr>",
        "<td class=mspt>-145.00</td></tr>\n"
        "<tr align=right><td colspan=10></td><td colspan=4>from #1000003[sl]</td></tr>",
    )
    assert _figures(_run("TICKET_ORDER", commented))["n_rows"] == "2"


def test_ticket_order_myfxbook() -> None:
    assert importers.detect_format(MYFXBOOK.encode()) == importers.MYFXBOOK_CSV
    outcome = _run("TICKET_ORDER", MYFXBOOK.encode())
    assert outcome.hits == 0
    assert _figures(outcome)["n_rows"] == "3"
    altered = MYFXBOOK.replace("103,03/15/2024 12:00", "103,03/14/2024 08:00")
    outcome = _run("TICKET_ORDER", altered.encode())
    assert outcome.hits == 1
    assert outcome.examples == (3,)
    assert _figures(outcome)["max_backwards_seconds"] == "7200"


def test_ticket_order_myfxbook_without_ticket_column() -> None:
    header, body = MYFXBOOK.split("\n", 1)
    stripped = (
        header.replace("Ticket,", "")
        + "\n"
        + "\n".join(
            line.split(",", 1)[1] if line[:1].isdigit() else line for line in body.split("\n")
        )
    )
    outcome = _run("TICKET_ORDER", stripped.encode())
    assert outcome.not_measured and outcome.reason == "no_column"


def test_ticket_order_fxblue() -> None:
    data = _fxblue("1001")
    assert importers.detect_format(data) == importers.FXBLUE_CSV
    outcome = _run("TICKET_ORDER", data)
    assert outcome.hits == 0
    assert _figures(outcome)["n_rows"] == "3"
    altered = data.replace(
        b"203,GBPUSD,0.10,Buy,1.26000,1.26410,2025/03/05 12:00:00",
        b"203,GBPUSD,0.10,Buy,1.26000,1.26410,2025/03/04 08:00:00",
    )
    outcome = _run("TICKET_ORDER", altered)
    assert outcome.hits == 1
    assert outcome.examples == (3,)


def test_ticket_order_fxblue_several_accounts() -> None:
    outcome = _run("TICKET_ORDER", _fxblue("1001", "1002"))
    assert outcome.not_measured and outcome.reason == "several_accounts"
    assert _figures(outcome) == {"accounts_in_file": "2"}


@pytest.mark.parametrize("name", ("mt5_history.html", "mt5_tester.html", "tradingview_g3b.csv"))
def test_ticket_order_other_formats(name: str) -> None:
    outcome = _run("TICKET_ORDER", _fixture(name))
    assert outcome.not_measured and outcome.reason == "format_not_covered"


# ---------------------------------------------------------------------------
# DUPLICATE_TICKET
# ---------------------------------------------------------------------------


def test_duplicate_ticket_mt4_fixture() -> None:
    outcome = _run("DUPLICATE_TICKET", _fixture("mt4_statement.htm"))
    figures = _figures(outcome)
    assert (figures["n_rows"], figures["n_ids"], figures["identical_rows"]) == ("7", "7", "0")
    assert _evidence(outcome)["accounts_in_file"] == NOT_MEASURED


def test_duplicate_ticket_mt4_repeated_ticket() -> None:
    data = _altered(
        _fixture("mt4_statement.htm"),
        '<td title="Withdrawal">1000007</td>',
        '<td title="Withdrawal">1000006</td>',
    )
    outcome = _run("DUPLICATE_TICKET", data)
    assert outcome.hits == 1
    assert _figures(outcome)["n_ids"] == "6"
    assert outcome.examples == (8, 9)


def test_duplicate_ticket_mt5_history_fixture() -> None:
    outcome = _run("DUPLICATE_TICKET", _fixture("mt5_history.html"))
    assert (_figures(outcome)["n_rows"], _figures(outcome)["n_ids"]) == ("10", "10")


def test_duplicate_ticket_mt5_repeated_deal() -> None:
    data = _altered(_fixture("mt5_history.html"), "<td nowrap>9005</td>", "<td nowrap>9004</td>")
    outcome = _run("DUPLICATE_TICKET", data)
    assert outcome.hits == 1
    assert outcome.examples == (19, 20)


def test_duplicate_ticket_mt5_repeated_position_keeps_spaces_apart() -> None:
    data = _altered(
        _fixture("mt5_history.html"), "<td>5003</td><td>XAUUSD</td>", "<td>5001</td><td>XAUUSD</td>"
    )
    outcome = _run("DUPLICATE_TICKET", data)
    assert outcome.hits == 1
    assert outcome.examples == (7, 8)


def test_duplicate_ticket_mt5_tester_deal_and_order_share_numbers() -> None:
    outcome = _run("DUPLICATE_TICKET", _fixture("mt5_tester.html"))
    assert (_figures(outcome)["n_rows"], _figures(outcome)["n_ids"]) == ("11", "11")
    assert outcome.hits == 0


def test_duplicate_ticket_mt5_identical_rows_figure() -> None:
    fixture = _fixture("mt5_history.html")
    start = fixture.index(b'<tr bgcolor="#FFFFFF" align="right"><td nowrap>2024.03.04 09:20:10')
    row = fixture[start:]
    row = row[: row.index(b"</tr>") + 5]
    outcome = _run("DUPLICATE_TICKET", fixture.replace(row, row + b"\n        " + row))
    assert outcome.hits == 1
    assert _figures(outcome)["identical_rows"] == "1"
    assert outcome.examples == (17, 18)


def test_duplicate_ticket_tradingview_fixtures() -> None:
    g1 = _run("DUPLICATE_TICKET", _fixture("tradingview_g1.csv"))
    assert (_figures(g1)["n_rows"], _figures(g1)["n_ids"]) == ("4", "2")
    g3b = _run("DUPLICATE_TICKET", _fixture("tradingview_g3b.csv"))
    assert (_figures(g3b)["n_rows"], _figures(g3b)["n_ids"]) == ("6", "3")
    assert _figures(g3b)["open_last_trade"] == "0"
    assert _evidence(g3b)["open_last_trade"] == MEASURED


def test_duplicate_ticket_tradingview_open_last_trade_is_allowed() -> None:
    data = _without_lines(_fixture("tradingview_g3b.csv"), "3,Exit long")
    outcome = _run("DUPLICATE_TICKET", data)
    assert outcome.hits == 0
    assert _figures(outcome)["open_last_trade"] == "1"


def test_duplicate_ticket_tradingview_missing_row_of_an_earlier_trade() -> None:
    data = _without_lines(_fixture("tradingview_g3b.csv"), "2,Exit short")
    outcome = _run("DUPLICATE_TICKET", data)
    assert outcome.hits == 1
    assert outcome.examples == (3,)


def test_duplicate_ticket_tradingview_copied_row() -> None:
    fixture = _fixture("tradingview_g3b.csv")
    line = fixture.split(b"\n")[2]
    data = fixture.replace(line + b"\n", line + b"\n" + line + b"\n")
    outcome = _run("DUPLICATE_TICKET", data)
    assert outcome.hits == 1
    assert _figures(outcome)["identical_rows"] == "1"
    assert outcome.examples == (1,)


def test_duplicate_ticket_ninjatrader() -> None:
    data = _altered(_fixture("ninjatrader.csv"), "\n2,ES 03-26", "\n1,ES 03-26")
    outcome = _run("DUPLICATE_TICKET", data)
    assert outcome.hits == 1
    assert outcome.examples == (1, 2)


def test_duplicate_ticket_myfxbook() -> None:
    outcome = _run("DUPLICATE_TICKET", MYFXBOOK.encode())
    assert (_figures(outcome)["n_rows"], _figures(outcome)["n_ids"]) == ("5", "5")
    altered = MYFXBOOK.replace("\n105,", "\n104,")
    outcome = _run("DUPLICATE_TICKET", altered.encode())
    assert outcome.hits == 1
    assert outcome.examples == (4, 5)


def test_duplicate_ticket_fxblue_accounts() -> None:
    outcome = _run("DUPLICATE_TICKET", _fxblue("1001"))
    assert _figures(outcome)["n_rows"] == "5"
    assert (_figures(outcome)["accounts_in_file"], _evidence(outcome)["accounts_in_file"]) == (
        "1",
        MEASURED,
    )
    several = _run("DUPLICATE_TICKET", _fxblue("1001", "1002"))
    assert several.not_measured and several.reason == "several_accounts"


def test_duplicate_ticket_mt4_tester_is_not_measured() -> None:
    outcome = _run("DUPLICATE_TICKET", _fixture("mt4_tester.htm"))
    assert outcome.not_measured and outcome.reason == "format_not_covered"
