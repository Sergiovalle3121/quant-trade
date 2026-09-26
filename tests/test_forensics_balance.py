"""``BALANCE_CHAIN`` and ``VOLUME_IN_OUT`` of the forensics battery, on the fixtures.

Every test is offline: the fixtures are read from disk, altered in memory
by one edit, and the outcome is compared with what the platform's own
running balance (or open volume) predicts. The importer's own
``"N Balance cell(s)"`` warning is reconciled with ``n_hits`` on the
fixtures only (D12), never on corpus files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_audit_importers import _as_workbook_rows, xlsx

from quant_trade.audit import importers
from quant_trade.audit.forensics import rows
from quant_trade.audit.forensics.checks import Context, balance
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import EVIDENCE, MEASURED, NOT_MEASURED, RawOutcome
from quant_trade.audit.forensics.review import REASONS, review

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
FORBIDDEN = ("12345678", "Demo Trader", "Synthetic", "FixtureEA")
CHECKS = ("BALANCE_CHAIN", "VOLUME_IN_OUT")
HTML_FIXTURES = ("mt4_statement.htm", "mt5_history.html", "mt5_tester.html", "mt4_tester.htm")
CSV_FIXTURES = ("tradingview_g1.csv", "tradingview_g3b.csv", "ninjatrader.csv")
MONEY = re.compile(r"^-?\d+\.\d+$")
BALANCE_WARNING = re.compile(r"(\d+) Balance cell\(s\) do not equal")

BALANCE_KEYS = (
    "n_rows",
    "n_hits",
    "first_break_row",
    "largest_gap",
    "restarts",
    "ties_fixed",
    "hidden_cost_rows",
    "skipped_first",
    "initial_balance_implied",
)
VOLUME_KEYS = ("n_rows", "n_hits", "n_symbols", "first_negative_row", "pre_period_positions")

#: The balance cells of the tester fixture's trade deals (one per row).
TESTER_TRADE_BALANCES = (
    "9 998.60",
    "10 022.90",
    "10 011.75",
    "10 011.40",
    "10 011.05",
    "10 067.85",
    "10 067.15",
    "10 085.05",
    "10 063.05</td><td>end",
)
#: The first trade deal's hidden Cost cell and the cells that follow it.
HISTORY_COST_ROW = (
    '<td nowrap class="hidden">{cost}</td><td nowrap>-0.35</td><td nowrap>0.00</td>'
    "<td nowrap>0.00</td><td nowrap>0.00</td><td nowrap>999.65</td>"
)


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _load(data: bytes, source_format: str | None = "") -> tuple[rows.RawTable, Context]:
    fmt = importers.detect_format(data) if source_format == "" else source_format
    table = rows.load(data, fmt)
    header = read_header(table)
    return table, Context(family=table.family, header=header, currency=header.currency)


def _run(check: str, data: bytes, source_format: str | None = "") -> RawOutcome:
    table, ctx = _load(data, source_format)
    outcome: RawOutcome = getattr(balance, f"run_{check}")(table, ctx)
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


def _swapped_lines(data: bytes, first: str, second: str) -> bytes:
    """The file with the line holding ``first`` and the next line (holding
    ``second``) exchanged."""
    lines = data.split(b"\n")
    at = next(index for index, line in enumerate(lines) if first.encode() in line)
    assert second.encode() in lines[at + 1], second
    lines[at], lines[at + 1] = lines[at + 1], lines[at]
    return b"\n".join(lines)


def _figures(outcome: RawOutcome) -> dict[str, str]:
    return {key: value for key, value, _ in outcome.figures}


def _evidence(outcome: RawOutcome) -> dict[str, str]:
    return {key: evidence for key, _, evidence in outcome.figures}


def _assert_well_formed(outcome: RawOutcome) -> None:
    for key, value, evidence in outcome.figures:
        assert isinstance(key, str) and key
        assert isinstance(value, str) and (value.isdigit() or MONEY.match(value)), (key, value)
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


def _importer_breaks(data: bytes, name: str) -> int:
    """The importer's own count of Balance cells off the running balance."""
    report = importers.import_report(data, name)
    found = [BALANCE_WARNING.match(warning) for warning in report.warnings]
    counts = [int(match.group(1)) for match in found if match]
    assert len(counts) <= 1
    return counts[0] if counts else 0


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


@pytest.mark.parametrize("name", ("mt5_history.html", "mt5_tester.html", "mt4_tester.htm"))
def test_balance_chain_key_set_is_the_same_for_every_family(name: str) -> None:
    outcome = _run("BALANCE_CHAIN", _fixture(name))
    assert tuple(_figures(outcome)) == BALANCE_KEYS


# ---------------------------------------------------------------------------
# BALANCE_CHAIN: MT5 history
# ---------------------------------------------------------------------------


def test_balance_chain_history_fixture() -> None:
    outcome = _run("BALANCE_CHAIN", _fixture("mt5_history.html"))
    assert _figures(outcome) == {
        "n_rows": "6",
        "n_hits": "0",
        "first_break_row": "0",
        "largest_gap": "0.00",
        "restarts": "0",
        "ties_fixed": "0",
        "hidden_cost_rows": "0",
        "skipped_first": "1",
        "initial_balance_implied": "0.00",
    }
    evidence = _evidence(outcome)
    assert evidence["first_break_row"] == NOT_MEASURED
    assert {evidence[key] for key in BALANCE_KEYS if key != "first_break_row"} == {MEASURED}


def test_balance_chain_history_edited_balance_breaks_twice() -> None:
    """An edited Balance cell breaks its own row and the next one, which is
    chained from the printed (edited) balance."""
    data = _altered(
        _fixture("mt5_history.html"), "<td nowrap>990.37</td>", "<td nowrap>990.00</td>"
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 2
    assert outcome.examples == (18, 19)
    figures = _figures(outcome)
    assert (figures["first_break_row"], figures["largest_gap"]) == ("18", "0.37")
    assert _evidence(outcome)["first_break_row"] == MEASURED


def test_balance_chain_history_deleted_deal_breaks_the_next_row() -> None:
    data = _without_lines(_fixture("mt5_history.html"), "<td nowrap>9003</td>")
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 1
    assert outcome.examples == (18,)
    figures = _figures(outcome)
    assert (figures["n_rows"], figures["largest_gap"]) == ("5", "9.14")


def test_balance_chain_history_edited_deposit_moves_the_implied_initial_balance() -> None:
    data = _altered(
        _fixture("mt5_history.html"),
        "<td nowrap>1 000.00</td><td nowrap>1 000.00</td>",
        "<td nowrap>1 000.00</td><td nowrap>1 100.00</td>",
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 1
    assert outcome.examples == (16,)
    assert _figures(outcome)["initial_balance_implied"] == "100.00"


@pytest.mark.parametrize(
    "replacement",
    [
        "<td nowrap>correction</td><td nowrap>in</td>",
        "<td nowrap>credit</td><td nowrap></td>",
    ],
)
def test_balance_chain_history_back_office_deal_restarts_the_chain(replacement: str) -> None:
    """A deal of another type (read by the importers or not) has an unknown
    effect on the balance: the chain restarts after it, without a hit."""
    data = _altered(
        _fixture("mt5_history.html"), "<td nowrap>sell</td><td nowrap>in</td>", replacement
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert (figures["n_rows"], figures["restarts"], figures["skipped_first"]) == ("6", "1", "2")


def test_balance_chain_history_hidden_cost_is_read_and_added() -> None:
    fixture = _fixture("mt5_history.html")
    zero = _altered(fixture, HISTORY_COST_ROW.format(cost=""), HISTORY_COST_ROW.format(cost="0.00"))
    outcome = _run("BALANCE_CHAIN", zero)
    assert outcome.hits == 0
    assert _figures(outcome)["hidden_cost_rows"] == "1"
    charged = _altered(
        fixture, HISTORY_COST_ROW.format(cost=""), HISTORY_COST_ROW.format(cost="-0.20")
    )
    outcome = _run("BALANCE_CHAIN", charged)
    assert outcome.hits == 1
    assert outcome.examples == (16,)
    figures = _figures(outcome)
    assert (figures["hidden_cost_rows"], figures["largest_gap"]) == ("1", "0.20")


def test_balance_chain_history_xlsx_twin_reads_like_the_html() -> None:
    html = _fixture("mt5_history.html")
    workbook = xlsx({"Sheet1": _as_workbook_rows(html)})
    fmt = importers.detect_format(workbook, "report.xlsx")
    assert fmt == importers.MT5_HISTORY_XLSX
    outcome = _run("BALANCE_CHAIN", workbook, fmt)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert (figures["n_rows"], figures["largest_gap"]) == ("6", "0.00")
    assert figures["initial_balance_implied"] == "0"


# ---------------------------------------------------------------------------
# BALANCE_CHAIN: MT5 tester
# ---------------------------------------------------------------------------


def test_balance_chain_tester_fixture() -> None:
    outcome = _run("BALANCE_CHAIN", _fixture("mt5_tester.html"))
    figures = _figures(outcome)
    assert (figures["n_rows"], figures["n_hits"], figures["largest_gap"]) == ("10", "0", "0.00")
    assert (figures["skipped_first"], figures["initial_balance_implied"]) == ("1", "0.00")


def test_balance_chain_tester_edited_balance() -> None:
    data = _altered(_fixture("mt5_tester.html"), "<td>10 011.75</td>", "<td>10 011.00</td>")
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 2
    assert outcome.examples == (26, 27)
    assert _figures(outcome)["largest_gap"] == "0.75"


def test_balance_chain_tester_same_second_deals_out_of_order_are_a_tie() -> None:
    """Two deals of one second printed in the wrong order are forgiven when
    swapping them closes both gaps; with different seconds they are hits."""
    swapped = _swapped_lines(
        _fixture("mt5_tester.html"),
        "<td>2024.01.04 08:00:00</td><td>5</td>",
        "<td>2024.01.04 08:05:00</td><td>6</td>",
    )
    outcome = _run("BALANCE_CHAIN", swapped)
    assert outcome.hits == 3
    assert outcome.examples == (27, 28, 29)
    assert _figures(outcome)["ties_fixed"] == "0"
    tied = _altered(
        swapped,
        "<td>2024.01.04 08:05:00</td><td>6</td>",
        "<td>2024.01.04 08:00:00</td><td>6</td>",
    )
    outcome = _run("BALANCE_CHAIN", tied)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert (figures["ties_fixed"], figures["largest_gap"]) == ("1", "0.00")


def test_balance_chain_tester_with_one_deal_has_nothing_to_compare() -> None:
    data = _without_lines(
        _fixture("mt5_tester.html"), *(f"<td>{cell}" for cell in TESTER_TRADE_BALANCES)
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.not_measured and outcome.reason == "no_qualifying_row"
    assert _figures(outcome)["n_rows"] == "1"


def test_balance_chain_without_a_deals_table() -> None:
    data = _without_lines(
        _fixture("mt5_tester.html"),
        *(f"<td>{cell}" for cell in TESTER_TRADE_BALANCES),
        "<td>10 000.00</td><td>10 000.00</td>",
    )
    outcome = _run("BALANCE_CHAIN", data, importers.MT5_TESTER_HTML)
    assert outcome.not_measured and outcome.reason == "no_table"


# ---------------------------------------------------------------------------
# BALANCE_CHAIN: MT4 tester
# ---------------------------------------------------------------------------


def test_balance_chain_mt4_tester_fixture() -> None:
    outcome = _run("BALANCE_CHAIN", _fixture("mt4_tester.htm"))
    assert _figures(outcome) == {
        "n_rows": "4",
        "n_hits": "0",
        "first_break_row": "0",
        "largest_gap": "0.00",
        "restarts": "0",
        "ties_fixed": "0",
        "hidden_cost_rows": "0",
        "skipped_first": "0",
        "initial_balance_implied": "0",
    }
    evidence = _evidence(outcome)
    assert evidence["n_rows"] == MEASURED
    assert evidence["skipped_first"] == MEASURED
    for key in ("restarts", "ties_fixed", "hidden_cost_rows", "initial_balance_implied"):
        assert evidence[key] == NOT_MEASURED


def test_balance_chain_mt4_tester_edited_balance() -> None:
    data = _altered(
        _fixture("mt4_tester.htm"), "<td class=mspt>10069.60</td>", "<td class=mspt>10060.60</td>"
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 2
    assert outcome.examples == (17, 21)
    assert _figures(outcome)["largest_gap"] == "9.00"


def test_balance_chain_mt4_tester_edited_initial_deposit_breaks_the_first_close() -> None:
    data = _altered(
        _fixture("mt4_tester.htm"),
        "<td>Initial deposit</td><td align=right>10000.00</td>",
        "<td>Initial deposit</td><td align=right>9000.00</td>",
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 1
    assert outcome.examples == (12,)
    assert _figures(outcome)["largest_gap"] == "1000.00"


def test_balance_chain_mt4_tester_without_initial_deposit_seeds_on_the_first_close() -> None:
    data = _altered(
        _fixture("mt4_tester.htm"),
        "<td>Initial deposit</td><td align=right>10000.00</td>",
        "<td>Initial</td><td align=right>10000.00</td>",
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 0
    assert _figures(outcome)["skipped_first"] == "1"


def test_balance_chain_mt4_tester_deleted_close() -> None:
    data = _without_lines(_fixture("mt4_tester.htm"), "<td>6</td><td class=msdate>")
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 1
    assert outcome.examples == (16,)
    assert _figures(outcome)["n_rows"] == "3"


def test_balance_chain_mt4_tester_blank_balance_carries_the_profit_forward() -> None:
    data = _altered(
        _fixture("mt4_tester.htm"),
        "<td class=mspt>100.00</td><td class=mspt>10099.60</td>",
        "<td class=mspt>100.00</td><td class=mspt></td>",
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.hits == 0
    assert _figures(outcome)["n_rows"] == "4"


def test_balance_chain_mt4_tester_without_closes() -> None:
    data = _without_lines(
        _fixture("mt4_tester.htm"),
        "<td>3</td><td class=msdate>",
        "<td>6</td><td class=msdate>",
        "<td>8</td><td class=msdate>",
        "<td>12</td><td class=msdate>",
    )
    outcome = _run("BALANCE_CHAIN", data)
    assert outcome.not_measured and outcome.reason == "no_qualifying_row"


# ---------------------------------------------------------------------------
# BALANCE_CHAIN: formats without a running balance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ("mt4_statement.htm",) + CSV_FIXTURES)
def test_balance_chain_formats_without_a_balance_column(name: str) -> None:
    outcome = _run("BALANCE_CHAIN", _fixture(name))
    assert outcome.not_measured and outcome.reason == "no_column"


def test_balance_chain_unknown_format() -> None:
    outcome = _run("BALANCE_CHAIN", _fixture("ninjatrader.csv"), None)
    assert outcome.not_measured and outcome.reason == "format_not_covered"


# ---------------------------------------------------------------------------
# BALANCE_CHAIN: the importer's own count (D12, fixtures only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("mt5_history.html", "<td nowrap>990.37</td>", "<td nowrap>990.00</td>"),
        ("mt5_tester.html", "<td>10 011.75</td>", "<td>10 011.00</td>"),
        ("mt4_tester.htm", "<td class=mspt>10069.60</td>", "<td class=mspt>10060.60</td>"),
    ],
)
def test_balance_chain_agrees_with_the_importer_on_a_seeded_break(
    name: str, old: str, new: str
) -> None:
    """One edited trade balance, followed by another trade: the importer
    counts the edited row and its successor, as the chain does."""
    clean = _fixture(name)
    assert _run("BALANCE_CHAIN", clean).hits == _importer_breaks(clean, name) == 0
    seeded = _altered(clean, old, new)
    assert _run("BALANCE_CHAIN", seeded).hits == _importer_breaks(seeded, name) == 2


def test_balance_chain_chains_flows_the_importer_ignores() -> None:
    """The importer drops cash flows after the last trade's date; the chain
    reads every printed row, so a break on the last trade also breaks the
    withdrawal after it."""
    seeded = _altered(
        _fixture("mt5_history.html"), "<td nowrap>1 009.40</td>", "<td nowrap>1 000.00</td>"
    )
    assert _importer_breaks(seeded, "mt5_history.html") == 1
    outcome = _run("BALANCE_CHAIN", seeded)
    assert outcome.hits == 2
    assert outcome.examples == (19, 20)


# ---------------------------------------------------------------------------
# VOLUME_IN_OUT
# ---------------------------------------------------------------------------


def test_volume_in_out_history_fixture() -> None:
    outcome = _run("VOLUME_IN_OUT", _fixture("mt5_history.html"))
    assert tuple(_figures(outcome)) == VOLUME_KEYS
    assert _figures(outcome) == {
        "n_rows": "4",
        "n_hits": "0",
        "n_symbols": "2",
        "first_negative_row": "0",
        "pre_period_positions": "0",
    }
    evidence = _evidence(outcome)
    assert evidence["first_negative_row"] == NOT_MEASURED
    assert evidence["n_symbols"] == MEASURED
    assert evidence["pre_period_positions"] == MEASURED


def test_volume_in_out_tester_fixture_reverses_with_in_out() -> None:
    """GBPUSD: in 0.1, in/out 0.3 (closes 0.1, opens 0.2), out 0.2 -> 0."""
    outcome = _run("VOLUME_IN_OUT", _fixture("mt5_tester.html"))
    assert _figures(outcome) == {
        "n_rows": "9",
        "n_hits": "0",
        "n_symbols": "3",
        "first_negative_row": "0",
        "pre_period_positions": "0",
    }
    # A tester prints no Positions table: nothing to seed, nothing to count.
    assert _evidence(outcome)["pre_period_positions"] == NOT_MEASURED


def test_volume_in_out_history_deleted_entry_leaves_a_close_without_an_open() -> None:
    data = _without_lines(_fixture("mt5_history.html"), "<td nowrap>9002</td>")
    outcome = _run("VOLUME_IN_OUT", data)
    assert outcome.hits == 1
    assert outcome.examples == (17,)
    figures = _figures(outcome)
    assert (figures["n_rows"], figures["n_symbols"], figures["first_negative_row"]) == (
        "3",
        "2",
        "17",
    )
    assert _evidence(outcome)["first_negative_row"] == MEASURED


def test_volume_in_out_position_opened_before_the_period_seeds_its_symbol() -> None:
    """A custom-period export lists, in Positions, positions opened before
    its first deal: their ``in`` lies outside the file, so their volume
    seeds the symbol (scoping rule from a genuine corpus file, D3)."""
    partial = _without_lines(_fixture("mt5_history.html"), "<td nowrap>9002</td>")
    assert _run("VOLUME_IN_OUT", partial).hits == 1
    opened_earlier = _altered(
        partial,
        "<td>2024.03.04 09:20:10</td><td>5003</td>",
        "<td>2024.02.28 09:20:10</td><td>5003</td>",
    )
    outcome = _run("VOLUME_IN_OUT", opened_earlier)
    assert outcome.hits == 0
    figures = _figures(outcome)
    assert (figures["n_symbols"], figures["pre_period_positions"]) == ("2", "1")
    # Opened at the first deal's own second: inside the file, no seed.
    opened_with_first = _altered(
        partial,
        "<td>2024.03.04 09:20:10</td><td>5003</td>",
        "<td>2024.03.01 08:00:00</td><td>5003</td>",
    )
    outcome = _run("VOLUME_IN_OUT", opened_with_first)
    assert outcome.hits == 1
    assert _figures(outcome)["pre_period_positions"] == "0"


def test_volume_in_out_seed_never_hides_a_close_beyond_it() -> None:
    """The seed covers only the pre-period volume: a larger close still hits."""
    data = _altered(
        _without_lines(_fixture("mt5_history.html"), "<td nowrap>9002</td>"),
        "<td>2024.03.04 09:20:10</td><td>5003</td>",
        "<td>2024.02.28 09:20:10</td><td>5003</td>",
    )
    data = _altered(
        data, "<td nowrap>out</td><td nowrap>0.02</td>", "<td nowrap>out</td><td nowrap>0.03</td>"
    )
    outcome = _run("VOLUME_IN_OUT", data)
    assert outcome.hits == 1
    assert outcome.examples == (17,)


def test_volume_in_out_counts_symbols_not_rows() -> None:
    data = _without_lines(
        _fixture("mt5_history.html"), "<td nowrap>9001</td>", "<td nowrap>9002</td>"
    )
    outcome = _run("VOLUME_IN_OUT", data)
    assert outcome.hits == 2
    assert outcome.examples == (16, 17)
    assert _figures(outcome)["first_negative_row"] == "16"


@pytest.mark.parametrize(
    ("old", "new", "example"),
    [
        ("<td>in/out</td><td>0.3</td>", "<td>in/out</td><td>0.05</td>", 31),
        ("<td>out</td><td>0.2</td>", "<td>out</td><td>0.5</td>", 32),
        (
            "<td>out</td><td>0.1</td><td>1.10250</td>",
            "<td>out</td><td>0.3</td><td>1.10250</td>",
            25,
        ),
    ],
)
def test_volume_in_out_tester_edited_volume(old: str, new: str, example: int) -> None:
    outcome = _run("VOLUME_IN_OUT", _altered(_fixture("mt5_tester.html"), old, new))
    assert outcome.hits == 1
    assert outcome.examples == (example,)
    assert _figures(outcome)["n_symbols"] == "3"


def test_volume_in_out_without_trade_deals() -> None:
    data = _without_lines(
        _fixture("mt5_tester.html"), *(f"<td>{cell}" for cell in TESTER_TRADE_BALANCES)
    )
    outcome = _run("VOLUME_IN_OUT", data)
    assert outcome.not_measured and outcome.reason == "no_qualifying_row"


def test_volume_in_out_without_a_deals_table() -> None:
    data = _without_lines(
        _fixture("mt5_tester.html"),
        *(f"<td>{cell}" for cell in TESTER_TRADE_BALANCES),
        "<td>10 000.00</td><td>10 000.00</td>",
    )
    outcome = _run("VOLUME_IN_OUT", data, importers.MT5_TESTER_HTML)
    assert outcome.not_measured and outcome.reason == "no_table"


def test_volume_in_out_xlsx_twin() -> None:
    html = _fixture("mt5_tester.html")
    workbook = xlsx({"Sheet1": _as_workbook_rows(html)})
    fmt = importers.detect_format(workbook, "report.xlsx")
    assert fmt == importers.MT5_TESTER_XLSX
    outcome = _run("VOLUME_IN_OUT", workbook, fmt)
    assert outcome.hits == 0
    assert _figures(outcome)["n_symbols"] == "3"


@pytest.mark.parametrize("name", ("mt4_statement.htm", "mt4_tester.htm") + CSV_FIXTURES)
def test_volume_in_out_other_formats(name: str) -> None:
    outcome = _run("VOLUME_IN_OUT", _fixture(name))
    assert outcome.not_measured and outcome.reason == "format_not_covered"
