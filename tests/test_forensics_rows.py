"""The battery's read-only row reader: it wraps the importers' private
readers, classifies rows with their predicates and never holds the account."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows
from quant_trade.audit.forensics.header import read_header
from quant_trade.evidence.canonical_json import canonical_dumps

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT_FIXTURES = ("mt4_statement.htm", "mt5_history.html", "mt5_tester.html", "mt4_tester.htm")
PRIVATE_TEXT = ("12345678", "Demo Trader", "Synthetic Broker", "SyntheticBroker-Demo", "FixtureEA")


def _load(name: str) -> rows.RawTable:
    data = (FIXTURES / name).read_bytes()
    return rows.load(data, importers.detect_format(data))


def test_private_importer_names_are_pinned() -> None:
    """The reader relies on these private names; a rename must be noticed."""
    assert inspect.signature(importers._read_html).parameters.keys() == {"text"}
    assert inspect.signature(importers._read_delimited).parameters.keys() == {"text"}
    assert inspect.signature(importers._mt5_workbook).parameters.keys() == {"sheets"}
    assert inspect.signature(importers._mt4_statement_columns).parameters.keys() == {"texts"}
    assert set(inspect.signature(importers._mt5_column_map).parameters) == {"header", "width"}
    for name in ("_is_mt5_deal", "_is_mt5_position", "_is_mt4_tester_row", "_is_mt_time"):
        assert callable(getattr(importers, name)), name
    assert set(inspect.signature(importers._is_mt4_statement_trade).parameters) >= {"texts"}
    for name in (
        "_check_size",
        "_labels",
        "_mt5_labels",
        "_mt4_pairs",
        "_looks_utf16",
        "_looks_cp1251",
        "_comma_is_decimal",
        "_one_time",
        "_period_dates",
        "_as_text",
        "_is_workbook",
    ):
        assert callable(getattr(importers, name)), name
    assert isinstance(importers._MT4_STATEMENT_COLUMNS, dict)
    assert isinstance(importers._MT5_DEAL_HEADER_ALIASES, dict)
    row = importers._Row({}, [importers._Cell("x", {"class": "hidden", "title": "t"})])
    assert row.cells[0].hidden and row.cells[0].attrs["title"] == "t"
    assert row.texts == [] and row.is_mt_header is False


@pytest.mark.parametrize("name", sorted(path.name for path in FIXTURES.iterdir()))
def test_encoding_code_matches_decode_text(name: str) -> None:
    data = (FIXTURES / name).read_bytes()
    code = rows.encoding_code(data)
    assert code in rows.ENCODING_CODES
    expected = {
        "utf8_bom": "utf-8",
        "utf16le_bom": "utf-16-le",
        "utf16be_bom": "utf-16-be",
        "utf16le": "utf-16-le",
        "utf16be": "utf-16-be",
        "utf8": "utf-8",
        "cp1251": "cp1251",
        "cp1252": "cp1252",
        "latin1": "latin-1",
    }[code]
    body = data[3:] if code == "utf8_bom" else data[2:] if code.endswith("_bom") else data
    assert importers.decode_text(data) == body.decode(expected, errors="replace").replace(
        "\x00", ""
    )


def test_encoding_codes_for_boms_and_cyrillic() -> None:
    assert rows.encoding_code(b"\xef\xbb\xbfabc") == "utf8_bom"
    assert rows.encoding_code(b"\xff\xfea\x00b\x00") == "utf16le_bom"
    assert rows.encoding_code(b"\xfe\xff\x00a\x00b") == "utf16be_bom"
    assert rows.encoding_code("Всего сделок 5".encode("cp1251")) == "cp1251"
    assert rows.encoding_code("caf\xe9 12.50".encode("cp1252")) == "cp1252"
    assert rows.encoding_code(("a\x00" * 100).encode("latin-1")) == "utf16le"


def test_mt4_statement_rows_are_classified() -> None:
    table = _load("mt4_statement.htm")
    assert table.family == families.MT4_STATEMENT
    assert table.generator == "metaquotes" and table.markers == 0
    kinds = [(row.section, row.kind) for row in table.rows]
    assert kinds.count(("closed", "mt4_trade")) == 3
    assert kinds.count(("closed", "mt4_cash")) == 2
    assert kinds.count(("closed", "mt4_credit")) == 1
    assert kinds.count(("closed", "mt4_cancelled")) == 1
    assert kinds.count(("closed", "footer")) == 1
    assert ("open", "header") in kinds and ("closed", "header") in kinds
    trade = table.kind("mt4_trade")[0]
    assert trade.cells[0].title == "[tp]" and trade.texts[0] == "1000002"
    assert rows.mt4_columns(table, trade)["profit"] == 13
    assert table.label("Currency") == "USD"
    assert table.account_label_present is True
    header = read_header(table)
    assert header.currency == "USD" and header.has_account is True
    assert (
        header.report_date is not None and header.report_date.isoformat() == "2024-03-08T18:30:00"
    )
    assert header.report_date_source == "header"


def test_mt5_history_rows_are_classified() -> None:
    table = _load("mt5_history.html")
    assert table.family == families.MT5_HISTORY and table.generator == "client_terminal"
    assert len(table.kind("mt5_deal")) == 6
    assert len(table.kind("mt5_position")) == 2
    assert len(table.kind("mt5_order")) == 2
    deal = table.kind("mt5_deal")[1]
    columns = rows.mt5_columns(table, deal)
    assert deal.texts[columns["deal"]] == "9001" and deal.texts[columns["balance"]] == "999.65"
    assert any(cell.hidden for cell in deal.cells)
    position = table.kind("mt5_position")[0]
    assert rows.mt5_position_columns(table, position)["close"] == 8
    assert any(cell.hidden for cell in position.cells)
    header = read_header(table)
    assert header.currency == "USD" and header.margin_mode == "hedge"
    assert header.account_type == "demo" and header.has_account is True
    assert (
        header.report_date is not None and header.report_date.isoformat() == "2024-03-08T18:30:00"
    )


def test_tester_rows_are_classified() -> None:
    mt5 = _load("mt5_tester.html")
    assert mt5.family == families.MT5_TESTER and mt5.generator == "strategy_tester"
    assert len(mt5.kind("mt5_deal")) == 10 and len(mt5.kind("mt5_order")) == 1
    assert mt5.label("Total Net Profit") == "63.05"
    assert read_header(mt5).report_date_source == "period_end"
    mt4 = _load("mt4_tester.htm")
    assert mt4.family == families.MT4_TESTER
    assert len(mt4.kind("mt4_tester")) == 12
    assert mt4.label("Initial deposit") == "10000.00"
    assert read_header(mt4).report_date is not None
    assert read_header(mt4).report_date.isoformat() == "2024-01-06T00:00:00"


def test_csv_rows_keep_the_header() -> None:
    table = _load("tradingview_g3b.csv")
    assert table.family == families.TRADINGVIEW
    assert table.rows[0].kind == "header" and table.header == table.rows[0].texts
    assert all(row.kind == "csv" for row in table.rows[1:])
    assert table.delimiter


def test_workbook_rows_read_like_html() -> None:
    from quant_trade.audit import importers as im

    html = (FIXTURES / "mt5_tester.html").read_bytes()
    xlsx = _workbook_of(html)
    table = rows.load(xlsx, im.MT5_TESTER_XLSX)
    assert table.family == families.MT5_TESTER and table.generator == "none"
    assert len(table.kind("mt5_deal")) == 10


def _workbook_of(html: bytes) -> bytes:
    """The fixture's rows as a minimal .xlsx (the importers read the same rows)."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    reader = importers._read_html(importers.decode_text(html))
    cells = []
    for r, row in enumerate(reader.rows, 1):
        for c, text in enumerate(row.texts):
            if text:
                ref = f"{_column(c)}{r}"
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>')
        cells.append("\n")
    sheet_rows = []
    for r, chunk in enumerate("".join(cells).split("\n"), 1):
        if chunk:
            sheet_rows.append(f'<row r="{r}">{chunk}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main"><sheetData>' + "".join(sheet_rows) + "</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/'
        '2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-'
        'package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def _column(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def test_account_key_is_read_only_in_memory() -> None:
    mt4 = (FIXTURES / "mt4_statement.htm").read_bytes()
    mt5 = (FIXTURES / "mt5_history.html").read_bytes()
    assert rows.account_key(mt4, importers.MT4_STATEMENT_HTML) == "12345678"
    assert rows.account_key(mt5, importers.MT5_HISTORY_HTML) == "12345678"
    assert (
        rows.account_key((FIXTURES / "mt5_tester.html").read_bytes(), importers.MT5_TESTER_HTML)
        is None
    )
    assert (
        rows.account_key((FIXTURES / "tradingview_g1.csv").read_bytes(), importers.TRADINGVIEW_CSV)
        is None
    )
    fxblue = b"Ticket,Account,Symbol\n1,777,EURUSD\n2,777,GBPUSD\n"
    assert rows.account_key(fxblue, importers.FXBLUE_CSV) == "777"
    two = b"Ticket,Account,Symbol\n1,777,EURUSD\n2,778,GBPUSD\n"
    assert rows.account_key(two, importers.FXBLUE_CSV) is None


@pytest.mark.parametrize("name", MT_FIXTURES)
def test_table_metadata_holds_no_account_or_name(name: str) -> None:
    table = _load(name)
    serialised = canonical_dumps(
        {
            "labels": [] if name != "mt4_tester.htm" else [],
            "generator": table.generator,
            "encoding": table.encoding,
            "line_endings": table.line_endings,
            "header": list(table.header),
            "present": [table.title_present, table.account_label_present],
        }
    )
    for private in PRIVATE_TEXT:
        assert private not in serialised
    # The header dataclass has no field for the number, the name or the broker.
    fields = set(read_header(table).__dataclass_fields__)
    assert fields == {
        "currency",
        "report_date",
        "report_date_source",
        "margin_mode",
        "account_type",
        "has_account",
    }


def test_truncation_flag_when_rows_exceed_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from quant_trade.audit import schema

    monkeypatch.setattr(schema, "MAX_ROWS", 5)
    table = _load("mt5_tester.html")
    assert table.truncated is True and len(table.rows) == 5
    csv = _load("tradingview_g3b.csv")
    assert csv.truncated is True and len(csv.rows) == 6


def test_unknown_format_falls_back_to_other_family() -> None:
    table = rows.load(b"a,b\n1,2\n", None)
    assert table.family == families.OTHER and table.rows[0].kind == "header"
    html = rows.load(b"<html><table><tr><td>x</td></tr></table></html>", None)
    assert html.family == families.OTHER and html.rows[0].kind == "other"
