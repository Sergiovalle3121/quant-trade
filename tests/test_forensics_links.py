"""TICKET_LINKS and CROSS_COPIES: the copies a platform prints of one record.

Every test loads the synthetic fixtures (or a one-step alteration of their
bytes) offline, runs the check module directly and reads the figures as
text. Nothing here touches the network or a real file.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

from quant_trade.audit.forensics import rows
from quant_trade.audit.forensics.checks import Context, links
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import EVIDENCE, STATUS_CLEAN, STATUS_INFO, RawOutcome
from quant_trade.audit.importers import detect_format

# The package re-exports the ``review`` function under the module's name.
review = importlib.import_module("quant_trade.audit.forensics.review")

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = "mt4_statement.htm"
MT5 = "mt5_history.html"
PRIVATE = ("12345678", "Demo Trader", "Synthetic", "FixtureEA")
COUNT = re.compile(r"^-?\d+$")


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def table_of(data: bytes) -> rows.RawTable:
    return rows.load(data, detect_format(data))


def outcome(check: str, data: bytes) -> RawOutcome:
    table = table_of(data)
    header = read_header(table)
    ctx = Context(family=table.family, header=header, currency=header.currency)
    runner = getattr(links, f"run_{check}")
    result: RawOutcome = runner(table, ctx)
    return result


def figure(result: RawOutcome, key: str) -> str:
    for name, value, _evidence in result.figures:
        if name == key:
            return value
    raise KeyError(key)


def index_of(data: bytes, text: str) -> int:
    """The raw index of the first row carrying ``text`` in one of its cells."""
    for row in table_of(data).rows:
        if text in row.texts:
            return row.index
    raise AssertionError(text)


def replaced(data: bytes, old: str, new: str) -> bytes:
    assert data.count(old.encode()) == 1, old
    return data.replace(old.encode(), new.encode())


def without_line(data: bytes, marker: str) -> bytes:
    lines = data.splitlines(keepends=True)
    kept = [line for line in lines if marker.encode() not in line]
    assert len(kept) == len(lines) - 1, marker
    return b"".join(kept)


def assert_well_formed(result: RawOutcome) -> None:
    keys = [name for name, _value, _evidence in result.figures]
    assert "n_rows" in keys and "n_hits" in keys
    assert len(keys) == len(set(keys))
    for name, value, evidence in result.figures:
        assert isinstance(name, str) and isinstance(value, str)
        assert evidence in EVIDENCE
        assert COUNT.match(value), (name, value)
    assert list(result.examples) == sorted(result.examples)
    assert len(result.examples) <= 5
    serialised = json.dumps([list(item) for item in result.figures])
    for secret in PRIVATE:
        assert secret not in serialised


# ---------------------------------------------------------------------------
# TICKET_LINKS
# ---------------------------------------------------------------------------


def test_links_parsed_from_comment_text() -> None:
    assert links._links("from #1000003[sl]") == ((), ("1000003",))
    assert links._links("to #1000005") == (("1000005",), ())
    assert links._links("from #12 to #13") == (("13",), ("12",))
    assert links._links("V1+V2[tp]") == ((), ())
    assert links._links("") == ((), ())


def test_ticket_links_clean_on_fixture() -> None:
    result = outcome("TICKET_LINKS", fixture(MT4))
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0
    assert result.examples == ()
    assert figure(result, "n_rows") == "3"
    assert figure(result, "n_links") == "2"
    assert figure(result, "links_inconsistent") == "0"
    assert figure(result, "links_unresolved") == "0"
    assert review.decide("TICKET_LINKS", "mt4_statement", result) == STATUS_CLEAN


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # the remainder's open price no longer matches the closed part
        (
            "<td>xauusd</td><td>2080.10</td><td>2083.00</td>",
            "<td>xauusd</td><td>2080.20</td><td>2083.00</td>",
        ),
        # the remainder's symbol no longer matches
        (
            "<td>xauusd</td><td>2080.10</td><td>2083.00</td>",
            "<td>xagusd</td><td>2080.10</td><td>2083.00</td>",
        ),
        # the remainder points at a different ticket than the one pointing at it
        ('title="from #1000003[sl]"', 'title="from #1000002[sl]"'),
    ],
)
def test_ticket_links_hit_when_the_pair_disagrees(old: str, new: str) -> None:
    data = replaced(fixture(MT4), old, new)
    result = outcome("TICKET_LINKS", data)
    assert_well_formed(result)
    assert result.hits == 2
    assert figure(result, "n_links") == "2"
    assert figure(result, "links_inconsistent") == "2"
    assert figure(result, "links_unresolved") == "0"
    assert result.examples == (index_of(data, "1000003"), index_of(data, "1000005"))
    assert review.decide("TICKET_LINKS", "mt4_statement", result) == STATUS_INFO


def test_ticket_links_missing_ticket_is_unresolved_not_a_hit() -> None:
    data = without_line(fixture(MT4), 'title="from #1000003[sl]"')
    result = outcome("TICKET_LINKS", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_links") == "1"
    assert figure(result, "links_unresolved") == "1"
    assert review.decide("TICKET_LINKS", "mt4_statement", result) == STATUS_CLEAN


def test_ticket_links_open_trade_resolves_a_from_link() -> None:
    """The remainder of a split order sits in Open Trades while it is open."""
    data = without_line(fixture(MT4), 'title="from #1000003[sl]"')
    open_row = (
        '<tr align=right><td title="from #1000003">1000005</td>'
        "<td class=msdate nowrap>2024.03.04 10:00:00</td><td>sell</td><td class=mspt>0.50</td>"
        "<td>xauusd</td><td>2080.10</td><td>2083.00</td><td>0.00</td><td>&nbsp;</td>"
        "<td>2079.00</td><td class=mspt>-3.50</td><td class=mspt>0.00</td>"
        "<td class=mspt>-4.10</td><td class=mspt>55.00</td></tr>\n"
    )
    data = replaced(
        data,
        "<tr align=right><td colspan=13 align=center>No transactions</td></tr>",
        open_row.strip(),
    )
    result = outcome("TICKET_LINKS", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    assert figure(result, "n_links") == "2"
    assert figure(result, "links_unresolved") == "0"


def test_ticket_links_reads_the_comment_row_of_2009_builds() -> None:
    """Old builds print the comment as a row after the trade, not as a title."""
    data = re.sub(rb' title="[^"]*"', b"", fixture(MT4))
    assert b"title=" not in data
    lines = data.splitlines(keepends=True)
    out: list[bytes] = []
    for line in lines:
        out.append(line)
        if b"<td>2080.10</td><td>0.00</td><td>0.00</td>" in line:
            out.append(b"<tr align=right><td></td><td></td><td>to #1000005</td></tr>\n")
        elif b"<td>2080.10</td><td>2083.00</td>" in line:
            out.append(b"<tr align=right><td></td><td></td><td>from #1000003[sl]</td></tr>\n")
    data = b"".join(out)
    result = outcome("TICKET_LINKS", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_links") == "2"
    assert figure(result, "links_unresolved") == "0"


NUMBERED = b"""<html><head><title>Statement</title></head><body><table>
<tr><td>A/C No: 1</td><td>Name: Name</td><td>2006.08.01 05:04 (local time)</td></tr>
<tr><td>Closed Transactions:</td></tr>
<tr><td>N</td><td>Ticket</td><td>Open Time</td><td>Type</td><td>Lots</td><td>Symbol</td>
<td>Price</td><td>S/L</td><td>T/P</td><td>Close Time</td><td>Price</td><td>Commis</td>
<td>Swap</td><td>Trade P/L</td><td>Comment</td></tr>
<tr><td>1</td><td title="200">200</td><td>2006.07.27 13:27</td><td>sell</td><td>2.50</td>
<td>eurusd</td><td>1.2764</td><td>0.0000</td><td>0.0000</td><td>2006.07.27 13:34</td>
<td>1.2768</td><td>0.00</td><td>0.00</td><td>-100.00</td><td>to #201</td></tr>
<tr><td>2</td><td title="201">201</td><td>2006.07.27 13:27</td><td>sell</td><td>1.00</td>
<td>eurusd</td><td>1.2764</td><td>0.0000</td><td>0.0000</td><td>2006.07.28 13:34</td>
<td>1.2700</td><td>0.00</td><td>0.00</td><td>640.00</td><td>from #200[tp]</td></tr>
</table></body></html>
"""


def test_ticket_links_reads_the_comment_column_of_the_numbered_layout() -> None:
    result = outcome("TICKET_LINKS", NUMBERED)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_links") == "2"
    altered = NUMBERED.replace(b"<td>1.00</td>\n<td>eurusd</td>", b"<td>1.00</td>\n<td>gbpusd</td>")
    assert altered != NUMBERED
    result = outcome("TICKET_LINKS", altered)
    assert result.hits == 2
    assert result.examples == (index_of(altered, "200"), index_of(altered, "201"))


def test_ticket_links_without_any_link_is_not_measured() -> None:
    data = replaced(fixture(MT4), 'title="to #1000005"', 'title=""')
    data = replaced(data, 'title="from #1000003[sl]"', 'title="[sl]"')
    result = outcome("TICKET_LINKS", data)
    assert result.not_measured
    assert result.reason == "no_qualifying_row"
    assert result.reason in review.REASONS
    assert figure(result, "n_links") == "0"


def test_ticket_links_other_families_are_not_covered() -> None:
    result = outcome("TICKET_LINKS", fixture(MT5))
    assert result.not_measured
    assert result.reason == "format_not_covered"


# ---------------------------------------------------------------------------
# CROSS_COPIES
# ---------------------------------------------------------------------------

POSITION_5001_CLOSE = '<td class="">2024.03.05 11:40:31</td><td class="">1.08700</td>'
ORDER_5001_FILL = '<td>2024.03.04 09:15:02</td><td colspan="2">filled</td>'


def test_cross_copies_clean_on_fixture() -> None:
    result = outcome("CROSS_COPIES", fixture(MT5))
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0
    assert result.examples == ()
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_positions") == "2"
    assert figure(result, "positions_before_period") == "0"
    assert figure(result, "entries_inconsistent") == "0"
    assert figure(result, "exits_inconsistent") == "0"
    assert figure(result, "orders_inconsistent") == "0"
    # orders 5003 and 5004 are named by deals but absent from the Orders table
    assert figure(result, "orders_unresolved") == "2"
    assert figure(result, "no_orders_table") == "0"
    assert int(figure(result, "copies_compared")) > 0
    assert review.decide("CROSS_COPIES", "mt5_history", result) == STATUS_CLEAN


@pytest.mark.parametrize(
    ("old", "new", "counter"),
    [
        (
            POSITION_5001_CLOSE,
            POSITION_5001_CLOSE.replace("1.08700", "1.08710"),
            "exits_inconsistent",
        ),
        ('<td class="">0.10</td>', '<td class="">0.20</td>', "entries_inconsistent"),
        (ORDER_5001_FILL, ORDER_5001_FILL.replace("filled", "canceled"), "orders_inconsistent"),
        (ORDER_5001_FILL, ORDER_5001_FILL.replace("09:15:02", "09:15:05"), "orders_inconsistent"),
        (
            '<td>5001</td><td>EURUSD</td><td>buy</td><td class="hidden"',
            '<td>5001</td><td>GBPUSD</td><td>buy</td><td class="hidden"',
            "entries_inconsistent",
        ),
    ],
)
def test_cross_copies_hit_when_one_copy_is_edited(old: str, new: str, counter: str) -> None:
    data = replaced(fixture(MT5), old, new)
    result = outcome("CROSS_COPIES", data)
    assert_well_formed(result)
    assert result.hits == 1
    assert figure(result, counter) == "1"
    assert result.examples == (index_of(data, "5001"),)
    assert review.decide("CROSS_COPIES", "mt5_history", result) == STATUS_INFO


def test_cross_copies_order_symbol_edit_is_a_hit() -> None:
    data = replaced(
        fixture(MT5),
        "<td>5001</td><td>EURUSD</td><td>buy</td><td>0.10 / 0.10</td>",
        "<td>5001</td><td>GBPUSD</td><td>buy</td><td>0.10 / 0.10</td>",
    )
    result = outcome("CROSS_COPIES", data)
    assert result.hits == 1
    assert figure(result, "orders_inconsistent") == "1"
    assert result.examples == (index_of(data, "5001"),)


def test_cross_copies_volume_edit_breaks_entry_and_exit_but_counts_once() -> None:
    data = replaced(fixture(MT5), '<td class="">0.10</td>', '<td class="">0.20</td>')
    result = outcome("CROSS_COPIES", data)
    assert result.hits == 1
    assert figure(result, "entries_inconsistent") == "1"
    assert figure(result, "exits_inconsistent") == "1"


def test_cross_copies_fill_time_within_one_second_is_not_a_hit() -> None:
    data = replaced(fixture(MT5), ORDER_5001_FILL, ORDER_5001_FILL.replace("09:15:02", "09:15:03"))
    result = outcome("CROSS_COPIES", data)
    assert result.hits == 0


def test_cross_copies_deleted_entry_deal_is_a_hit() -> None:
    data = without_line(fixture(MT5), "<td nowrap>9001</td>")
    result = outcome("CROSS_COPIES", data)
    assert_well_formed(result)
    assert result.hits == 1
    assert figure(result, "entries_inconsistent") == "1"
    assert result.examples == (index_of(data, "5001"),)


def test_cross_copies_position_before_the_first_deal_is_skipped() -> None:
    data = replaced(
        fixture(MT5),
        "<td>2024.03.04 09:20:10</td><td>5003</td>",
        "<td>2024.02.28 09:20:10</td><td>5003</td>",
    )
    result = outcome("CROSS_COPIES", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_positions") == "1"
    assert figure(result, "positions_before_period") == "1"


def test_cross_copies_partial_close_is_scoped_out_not_a_hit() -> None:
    """A position closed in two parts prints one row carrying the last exit's
    time and the volume-weighted exit price (seen on a real file): the deals
    at the close time cover the last part only."""
    first_part = (
        '<tr bgcolor="#FFFFFF" align="right"><td nowrap>2024.03.05 10:00:00</td>'
        "<td nowrap>9006</td><td nowrap>EURUSD</td><td nowrap>sell</td><td nowrap>out</td>"
        "<td nowrap>0.06</td><td nowrap>1.08700</td><td nowrap>5006</td>"
        '<td nowrap class="hidden"></td><td nowrap>-0.21</td><td nowrap>0.00</td>'
        "<td nowrap>0.00</td><td nowrap>12.00</td><td nowrap>1 002.16</td><td nowrap></td></tr>\n"
    )
    data = b"".join(
        first_part.encode() + line if b"<td nowrap>9004</td>" in line else line
        for line in fixture(MT5).splitlines(keepends=True)
    )
    data = replaced(
        data,
        "<td nowrap>0.10</td><td nowrap>1.08700</td>",
        "<td nowrap>0.04</td><td nowrap>1.08700</td>",
    )
    result = outcome("CROSS_COPIES", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_positions") == "2"
    assert figure(result, "exits_partial") == "1"
    assert figure(result, "exits_inconsistent") == "0"
    # the earlier part's deal belongs to no row of the Positions table, so its
    # absent order is not looked up; the two absent orders of the fixture remain
    assert figure(result, "orders_unresolved") == "2"
    # without the earlier part there is nothing to explain the shrunken deal
    shrunken = without_line(data, "<td nowrap>9006</td>")
    result = outcome("CROSS_COPIES", shrunken)
    assert result.hits == 1
    assert figure(result, "exits_partial") == "0"
    assert figure(result, "exits_inconsistent") == "1"
    assert result.examples == (index_of(shrunken, "5001"),)


def test_cross_copies_without_orders_table_reports_it_as_a_figure() -> None:
    lines = fixture(MT5).splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if b"<b>Orders</b>" in line)
    end = next(i for i, line in enumerate(lines) if b"<b>Deals</b>" in line)
    data = b"".join(lines[:start] + lines[end:])
    result = outcome("CROSS_COPIES", data)
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0
    assert figure(result, "no_orders_table") == "1"
    assert figure(result, "orders_unresolved") == "0"
    assert figure(result, "orders_inconsistent") == "0"


@pytest.mark.parametrize("edit", [("Hedge)", "Netting)"), (",&nbsp;Hedge)", ")")])
def test_cross_copies_needs_a_hedge_account(edit: tuple[str, str]) -> None:
    data = replaced(fixture(MT5), *edit)
    result = outcome("CROSS_COPIES", data)
    assert result.not_measured
    assert result.reason == "netting_or_unknown_margin_mode"
    assert result.reason in review.REASONS


def test_cross_copies_without_positions_table_is_not_measured() -> None:
    data = without_line(fixture(MT5), '<td>5001</td><td>EURUSD</td><td>buy</td><td class="hidden"')
    data = without_line(data, '<td>5003</td><td>XAUUSD</td><td>sell</td><td class="hidden"')
    result = outcome("CROSS_COPIES", data)
    assert result.not_measured
    assert result.reason == "no_table"


@pytest.mark.parametrize("name", [MT4, "mt5_tester.html", "mt4_tester.htm", "tradingview_g1.csv"])
def test_cross_copies_other_families_are_not_covered(name: str) -> None:
    result = outcome("CROSS_COPIES", fixture(name))
    assert result.not_measured
    assert result.reason == "format_not_covered"


# ---------------------------------------------------------------------------
# Determinism and privacy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("check", "name"),
    [("TICKET_LINKS", MT4), ("CROSS_COPIES", MT5), ("TICKET_LINKS", MT5), ("CROSS_COPIES", MT4)],
)
def test_outcomes_are_deterministic_and_carry_nothing_private(check: str, name: str) -> None:
    first = outcome(check, fixture(name))
    second = outcome(check, fixture(name))
    assert first == second
    serialised = json.dumps(
        {"figures": [list(f) for f in first.figures], "examples": list(first.examples)}
    )
    for secret in PRIVATE:
        assert secret not in serialised
    assert "1000003" not in serialised and "5001" not in serialised
