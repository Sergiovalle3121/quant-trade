"""Subtractive editing of a real report's ``<tr>`` blocks: the same file
with fewer rows, never a template, re-encoded the way it came."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import edit, header, rows

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = "mt4_statement.htm"
MT5 = "mt5_history.html"
HTML_FIXTURES = (MT4, MT5, "mt5_tester.html", "mt4_tester.htm")
D1 = datetime(2024, 3, 4, 23, 59, 59)
D2 = datetime(2024, 3, 5, 23, 59, 59)
INITIAL_NOTE = (
    "the file does not state a starting balance; 10,000 was assumed, which scales every "
    "return and drawdown"
)
OPEN_NOTE = "1 position(s) opened in the report were not closed; excluded"


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _table(data: bytes) -> rows.RawTable:
    return rows.load(data, importers.detect_format(data))


def _row(table: rows.RawTable, kind: str, ref: str, column: int = 0) -> rows.RawRow:
    return next(row for row in table.rows if row.kind == kind and row.text(column) == ref)


def _trades(report: importers.ImportedReport) -> list[tuple[datetime, datetime, float]]:
    return [
        (t.entry_time.replace(tzinfo=None), t.exit_time.replace(tzinfo=None), round(t.pnl, 2))
        for t in report.trades.trades
    ]


def _kinds(warnings: list[str]) -> set[str]:
    """Warnings as kinds: the text before the first colon, digits masked."""
    return {re.sub(r"\d[\d,.]*", "N", warning.split(":")[0]) for warning in warnings}


#: The warning kinds a cut may add: the starting-balance note and, for an
#: MT5 tail cut with a trade open across the cut, the importer's note that
#: an entry deal has no position row (a real export shows the same).
ALLOWED_NEW = _kinds([INITIAL_NOTE, OPEN_NOTE])


def _new_kinds(cut: bytes, full: bytes, **kwargs: float) -> set[str]:
    before = importers.import_report(full)
    after = importers.import_report(cut, **kwargs)
    return _kinds(after.warnings) - _kinds(before.warnings)


MT4_TRADES = {
    "1000003": (datetime(2024, 3, 4, 10, 0), datetime(2024, 3, 4, 13, 2, 44), -225.0),
    "1000002": (datetime(2024, 3, 4, 9, 15, 2), datetime(2024, 3, 5, 11, 40, 31), 200.0),
    "1000005": (datetime(2024, 3, 4, 10, 0), datetime(2024, 3, 6, 9, 30), -145.0),
}
MT5_TRADES = {
    "5003": (datetime(2024, 3, 4, 9, 20, 10), datetime(2024, 3, 4, 13, 2, 44), -9.0),
    "5001": (datetime(2024, 3, 4, 9, 15, 2), datetime(2024, 3, 5, 11, 40, 31), 20.0),
}


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", HTML_FIXTURES)
def test_raw_indexes_coincide_with_rows_load(name: str) -> None:
    data = _bytes(name)
    text = importers.decode_text(data)
    blocks = edit.rows_of(text)
    table = _table(data)
    assert [block.texts for block in blocks] == [row.texts for row in table.rows]
    assert [index for index, _ in enumerate(blocks)] == [row.index for row in table.rows]
    for block in blocks:
        assert text[block.start : block.end] == block.raw
        assert block.raw.lower().startswith("<tr")


def test_rows_inside_comments_scripts_and_styles_are_not_rows() -> None:
    text = (
        "<html><body><script>var x = '<tr><td>1</td></tr>';</script>"
        "<!-- <tr><td>2</td></tr> --><style>tr { color: red }</style>"
        "<table><tr><td>3</td></tr><tr class=x>no cells here</table></body></html>"
    )
    blocks = edit.rows_of(text)
    assert [block.texts for block in blocks] == [("3",)]
    reader = importers._read_html(text)
    assert [tuple(row.texts) for row in reader.rows] == [("3",)]


# ---------------------------------------------------------------------------
# One-row helpers
# ---------------------------------------------------------------------------


def test_delete_row_keeps_every_other_byte() -> None:
    data = _bytes(MT4)
    text = importers.decode_text(data)
    table = _table(data)
    row = _row(table, rows.KIND_MT4_TRADE, "1000003")
    block = edit.rows_of(text)[row.index]
    out = edit.delete_row(data, row.index)
    assert importers.decode_text(out) == text[: block.start] + text[block.end :]
    assert len(_table(out).kind(rows.KIND_MT4_TRADE)) == 2
    assert len(importers.import_report(out).trades.trades) == 2
    with pytest.raises(ValueError, match="row_not_found"):
        edit.delete_row(data, len(table.rows))


def test_set_cell_changes_one_text_and_keeps_the_attributes() -> None:
    data = _bytes(MT4)
    table = _table(data)
    row = _row(table, rows.KIND_MT4_TRADE, "1000003")
    profit = rows.mt4_columns(table, row)["profit"]
    out = edit.set_cell(data, row.index, profit, "-225.01")
    after = _table(out)
    assert len(after.rows) == len(table.rows)
    for before_row, after_row in zip(table.rows, after.rows, strict=True):
        if before_row.index != row.index:
            assert before_row.texts == after_row.texts
    changed = after.rows[row.index]
    assert changed.text(profit) == "-225.01"
    assert changed.texts[:profit] == row.texts[:profit]
    assert changed.cells[0].title == row.cells[0].title  # the ticket's comment attribute
    block = edit.rows_of(importers.decode_text(out))[row.index]
    assert "class=mspt" in block.raw
    with pytest.raises(ValueError, match="cell_not_found"):
        edit.set_cell(data, row.index, 40, "x")


def test_duplicate_row_inserts_a_shifted_copy_right_after() -> None:
    data = _bytes(MT4)
    table = _table(data)
    row = _row(table, rows.KIND_MT4_TRADE, "1000003")
    out = edit.duplicate_row(data, row.index, {0: "1000009"}, shift=timedelta(minutes=1))
    after = _table(out)
    assert len(after.rows) == len(table.rows) + 1
    assert after.rows[row.index].texts == row.texts
    copy = after.rows[row.index + 1]
    assert copy.kind == rows.KIND_MT4_TRADE
    assert copy.text(0) == "1000009"
    assert copy.text(1) == "2024.03.04 10:01:00"
    assert copy.text(8) == "2024.03.04 13:03:44"
    assert copy.texts[2:8] == row.texts[2:8] and copy.texts[9:] == row.texts[9:]
    assert len(importers.import_report(out).trades.trades) == 4


def test_shift_time_moves_one_cell_with_its_printed_precision() -> None:
    data = _bytes(MT4)
    table = _table(data)
    row = _row(table, rows.KIND_MT4_TRADE, "1000003")
    out = edit.shift_time(data, row.index, 8, timedelta(minutes=120))
    assert _table(out).rows[row.index].text(8) == "2024.03.04 15:02:44"
    mt5 = _bytes(MT5)
    table5 = _table(mt5)
    label = next(row for row in table5.rows if row.text(0) == "Date:")
    out5 = edit.shift_time(mt5, label.index, 1, timedelta(minutes=120))
    assert _table(out5).rows[label.index].text(1) == "2024.03.08 20:30"
    with pytest.raises(ValueError, match="not_a_time"):
        edit.shift_time(data, row.index, 2, timedelta(minutes=1))


def test_shift_all_times_moves_every_time_cell_and_nothing_else() -> None:
    data = _bytes(MT5)
    before = _table(data)
    after = _table(edit.shift_all_times(data, timedelta(minutes=120)))
    moved = 0
    for old, new in zip(before.rows, after.rows, strict=True):
        for old_text, new_text in zip(old.texts, new.texts, strict=True):
            if importers._is_mt_time(old_text):
                old_time = importers._one_time(old_text)
                new_time = importers._one_time(new_text)
                assert old_time is not None and new_time is not None
                assert new_time - old_time == timedelta(minutes=120)
                moved += 1
            else:
                assert old_text == new_text
    assert moved > 10


def test_rename_symbol_rewrites_every_symbol_cell() -> None:
    data = _bytes(MT4)
    before = _table(data)
    after = _table(edit.rename_symbol(data, "EURUSD", "EURUSD.pro"))
    renamed = [
        (old.index, column)
        for old, new in zip(before.rows, after.rows, strict=True)
        for column, (old_text, new_text) in enumerate(zip(old.texts, new.texts, strict=True))
        if old_text != new_text
    ]
    row = _row(before, rows.KIND_MT4_TRADE, "1000002")
    assert renamed == [(row.index, rows.mt4_columns(before, row)["symbol"])]
    assert after.rows[row.index].text(4) == "EURUSD.pro"
    mt5_after = _table(edit.rename_symbol(_bytes(MT5), "eurusd", "EURUSD.pro"))
    assert sum(1 for row in mt5_after.rows for text in row.texts if text == "EURUSD.pro") == 5


def test_drop_cash_row_removes_the_first_matching_flow() -> None:
    data = _bytes(MT4)
    out = edit.drop_cash_row(data, "withdrawal")
    after = _table(out)
    assert not any(row.text(0) == "1000007" for row in after.rows)
    assert [amount for _, amount in importers.import_report(out).cash_flows] == [10000.0]
    with pytest.raises(ValueError, match="not_applicable"):
        edit.drop_cash_row(data, "withdrawal", before=datetime(2024, 3, 6))
    with pytest.raises(ValueError, match="not_applicable"):
        edit.drop_cash_row(_bytes(MT5), "credit")
    with pytest.raises(ValueError, match="unknown_kind"):
        edit.drop_cash_row(data, "bonus")
    credit_free = _table(edit.drop_cash_row(data, "credit"))
    assert not credit_free.kind(rows.KIND_MT4_CREDIT)
    mt5 = _table(edit.drop_cash_row(_bytes(MT5), "withdrawal"))
    assert not any(row.text(1) == "9005" for row in mt5.kind(rows.KIND_MT5_DEAL))
    assert len(mt5.kind(rows.KIND_MT5_DEAL)) == 5


@pytest.mark.parametrize("name", (MT4, MT5))
def test_set_header_date_rewrites_the_reports_date(name: str) -> None:
    when = datetime(2024, 3, 4, 23, 59, tzinfo=UTC)
    out = edit.set_header_date(_bytes(name), when)
    found = header.read_header(_table(out))
    assert found.report_date == when.replace(tzinfo=None)
    assert found.report_date_source == "header"


def test_move_to_open_section_relists_an_mt4_trade_as_open() -> None:
    data = _bytes(MT4)
    table = _table(data)
    row = _row(table, rows.KIND_MT4_TRADE, "1000005")
    out = edit.move_to_open_section(data, row.index)
    after = _table(out)
    assert len(after.kind(rows.KIND_MT4_TRADE)) == 2
    (opened,) = after.kind(rows.KIND_MT4_OPEN)
    assert opened.section == rows.SECTION_OPEN
    assert opened.text(0) == "1000005"
    assert opened.text(8) == "" and opened.text(9) == opened.text(5)
    assert opened.text(13) == "0.00" and opened.text(12) == "0.00"
    assert opened.texts[1:8] == row.texts[1:8]
    assert not any(row.text(0) == "No transactions" for row in after.section(rows.SECTION_OPEN))
    assert len(importers.import_report(out).trades.trades) == 2
    with pytest.raises(ValueError, match="not_a_closed_trade"):
        edit.move_to_open_section(data, 0)
    with pytest.raises(ValueError, match="not_mt4_statement"):
        edit.move_to_open_section(_bytes(MT5), 0)


# ---------------------------------------------------------------------------
# cut_statement
# ---------------------------------------------------------------------------


def test_mt4_tail_cut_keeps_the_expected_subset() -> None:
    data = _bytes(MT4)
    cut1 = edit.cut_statement(data, keep_to=D1)
    report1 = importers.import_report(cut1)
    assert _trades(report1) == [MT4_TRADES["1000003"]]
    assert [amount for _, amount in report1.cash_flows] == [10000.0]
    assert report1.initial_balance == 10000.0
    assert _new_kinds(cut1, data) == set()
    table1 = _table(cut1)
    assert {row.text(0) for row in table1.kind(rows.KIND_MT4_OPEN)} == {"1000002", "1000005"}
    assert table1.label("Balance") is None and table1.label("Closed P/L") is None
    assert not table1.kind(rows.KIND_FOOTER)
    assert header.read_header(table1).report_date == datetime(2024, 3, 4, 23, 59)
    cut2 = edit.cut_statement(data, keep_to=D2)
    report2 = importers.import_report(cut2)
    assert _trades(report2) == [MT4_TRADES["1000003"], MT4_TRADES["1000002"]]
    assert _new_kinds(cut2, data) == set()
    table2 = _table(cut2)
    assert {row.text(0) for row in table2.kind(rows.KIND_MT4_OPEN)} == {"1000005"}
    # The kept rows are the original bytes.
    original = {block.raw for block in edit.rows_of(importers.decode_text(data))}
    for block in edit.rows_of(importers.decode_text(cut2)):
        if block.texts and block.texts[0] in {"1000001", "1000002", "1000003", "Ticket"}:
            assert block.raw in original


def test_mt5_tail_cut_keeps_the_expected_subset() -> None:
    data = _bytes(MT5)
    cut1 = edit.cut_statement(data, keep_to=D1)
    report1 = importers.import_report(cut1)
    assert _trades(report1) == [MT5_TRADES["5003"]]
    assert report1.initial_balance == 1000.0
    assert _new_kinds(cut1, data) <= ALLOWED_NEW
    table1 = _table(cut1)
    deals = [row.text(1) for row in table1.kind(rows.KIND_MT5_DEAL)]
    assert deals == ["9000", "9001", "9002", "9003"]
    (opened,) = table1.kind(rows.KIND_MT5_OPEN_POSITION)
    assert opened.text(1) == "5001" and opened.text(8) == "" and opened.text(12) == "0.00"
    assert [row.text(1) for row in table1.kind(rows.KIND_MT5_ORDER)] == ["5001"]
    assert table1.label("Balance") is None and table1.label("Total Net Profit") is None
    assert table1.label("Date") == "2024.03.04 23:59"
    cut2 = edit.cut_statement(data, keep_to=D2)
    report2 = importers.import_report(cut2)
    assert _trades(report2) == [MT5_TRADES["5003"], MT5_TRADES["5001"]]
    assert _new_kinds(cut2, data) == set()
    assert not _table(cut2).kind(rows.KIND_MT5_OPEN_POSITION)
    assert [amount for _, amount in report2.cash_flows] == [1000.0]


def test_mt4_head_cut_drops_trades_and_cash_before_the_start() -> None:
    data = _bytes(MT4)
    cut = edit.cut_statement(data, keep_from=datetime(2024, 3, 4, 9, 30))
    report = importers.import_report(cut, initial_balance=10000.0)
    assert _trades(report) == [MT4_TRADES["1000003"], MT4_TRADES["1000005"]]
    assert report.initial_balance == 10000.0
    assert [amount for _, amount in report.cash_flows] == [-1000.0]
    assert _new_kinds(cut, data, initial_balance=10000.0) == set()
    table = _table(cut)
    assert not any(row.text(0) == "1000001" for row in table.rows)


def test_mt5_head_cut_drops_straddlers_with_their_exit_deal_and_blanks_balances() -> None:
    data = _bytes(MT5)
    cut = edit.cut_statement(data, keep_from=datetime(2024, 3, 4, 9, 18), blank_balances=True)
    table = _table(cut)
    assert [row.text(1) for row in table.kind(rows.KIND_MT5_POSITION)] == ["5003"]
    deals = table.kind(rows.KIND_MT5_DEAL)
    assert [row.text(1) for row in deals] == ["9002", "9003", "9005"]
    balance = rows.mt5_columns(table, deals[0])["balance"]
    assert all(row.text(balance) == "" for row in deals)
    report = importers.import_report(cut, initial_balance=1000.0)
    assert _trades(report) == [MT5_TRADES["5003"]]
    assert report.initial_balance == 1000.0
    assert not any("Balance cell" in warning for warning in report.warnings)
    assert _new_kinds(cut, data, initial_balance=1000.0) <= ALLOWED_NEW


def test_a_window_cut_combines_both_rules() -> None:
    data = _bytes(MT4)
    cut = edit.cut_statement(data, keep_from=datetime(2024, 3, 4, 9, 30), keep_to=D2)
    report = importers.import_report(cut, initial_balance=10000.0)
    assert _trades(report) == [MT4_TRADES["1000003"]]
    assert {row.text(0) for row in _table(cut).kind(rows.KIND_MT4_OPEN)} == {"1000005"}


@pytest.mark.parametrize(
    ("codec", "bom"),
    [("utf-16-le", b"\xff\xfe"), ("utf-8", b"\xef\xbb\xbf"), ("utf-16-be", b"\xfe\xff")],
)
def test_the_files_encoding_and_byte_order_mark_are_kept(codec: str, bom: bytes) -> None:
    plain = _bytes(MT5)
    text = importers.decode_text(plain)
    data = bom + text.encode(codec)
    assert importers.detect_format(data) == importers.MT5_HISTORY_HTML
    cut = edit.cut_statement(data, keep_to=D2)
    assert cut.startswith(bom)
    assert rows.encoding_code(cut) == rows.encoding_code(data)
    assert importers.decode_text(cut) == importers.decode_text(
        edit.cut_statement(plain, keep_to=D2)
    )
    assert _trades(importers.import_report(cut)) == [MT5_TRADES["5003"], MT5_TRADES["5001"]]


def test_a_cp1252_file_comes_back_in_cp1252() -> None:
    text = importers.decode_text(_bytes(MT4)).replace("Synthetic Broker", "Synthétic Bröker")
    data = text.encode("cp1252")
    assert rows.encoding_code(data) == "cp1252"
    cut = edit.cut_statement(data, keep_to=D2)
    assert rows.encoding_code(cut) == "cp1252"
    assert "Synthétic Bröker" in importers.decode_text(cut)
    assert _trades(importers.import_report(cut)) == [MT4_TRADES["1000003"], MT4_TRADES["1000002"]]


def test_refusals_are_value_errors_with_codes() -> None:
    with pytest.raises(ValueError, match="no_cut"):
        edit.cut_statement(_bytes(MT4))
    with pytest.raises(ValueError, match="not_editable"):
        edit.cut_statement(_bytes("tradingview_g1.csv"), keep_to=D1)
    with pytest.raises(ValueError, match="not_editable"):
        edit.cut_statement(_bytes("mt5_tester.html"), keep_to=D1)


def test_edits_are_deterministic() -> None:
    data = _bytes(MT4)
    assert edit.cut_statement(data, keep_to=D1) == edit.cut_statement(data, keep_to=D1)
    assert edit.shift_all_times(data, timedelta(hours=1)) == edit.shift_all_times(
        data, timedelta(hours=1)
    )
