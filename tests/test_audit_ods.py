"""OpenDocument spreadsheets (.ods) are read like Excel workbooks.

Every file here is built in the test from the OpenDocument 1.2 structure
(a ``mimetype`` member and ``content.xml``); no third-party file is used.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from quant_trade.audit import mapping
from quant_trade.audit.importers import (
    ReportFormatError,
    detect_format,
    import_report,
    read_xlsx,
    unwrap,
)
from quant_trade.audit.schema import parse_equity_csv

OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def _cell(value: object) -> str:
    if value is None:
        return "<table:table-cell/>"
    if isinstance(value, tuple):
        kind, raw, shown = value
        attribute = {"date": "date-value", "time": "time-value"}.get(kind, "value")
        return (
            f'<table:table-cell office:value-type="{kind}" office:{attribute}="{raw}">'
            f"<text:p>{shown}</text:p></table:table-cell>"
        )
    if isinstance(value, int | float):
        return (
            f'<table:table-cell office:value-type="float" office:value="{value}">'
            f"<text:p>{value}</text:p></table:table-cell>"
        )
    return (
        f'<table:table-cell office:value-type="string"><text:p>{value}</text:p></table:table-cell>'
    )


def _ods(rows: list[list[object]], *, tail: str = "", name: str = "Hoja1") -> bytes:
    body = "".join(
        "<table:table-row>" + "".join(map(_cell, row)) + "</table:table-row>" for row in rows
    )
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="{OFFICE}" '
        f'xmlns:table="{TABLE}" xmlns:text="{TEXT}" office:version="1.2"><office:body>'
        f'<office:spreadsheet><table:table table:name="{name}">{body}{tail}</table:table>'
        "</office:spreadsheet></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.spreadsheet"
        )
        archive.writestr("content.xml", content)
        archive.writestr("META-INF/manifest.xml", "<manifest/>")
    return buffer.getvalue()


#: What LibreOffice writes after the last used row and column of a sheet.
EDGE = (
    '<table:table-row table:number-rows-repeated="1048560">'
    '<table:table-cell table:number-columns-repeated="1024"/></table:table-row>'
)

HEADER = ["Symbol", "Side", "Quantity", "Open Time", "Open Price", "Close Time", "Close Price"]


def _trade(day: int, close: float) -> list[object]:
    return [
        "EURUSD",
        "Buy",
        1,
        ("date", f"2026-01-{day:02d}T10:00:00", f"{day:02d}/01/2026 10:00"),
        1.1,
        ("date", f"2026-01-{day:02d}T12:00:00", f"{day:02d}/01/2026 12:00"),
        close,
    ]


def test_a_trade_list_saved_as_ods_is_read_like_a_workbook() -> None:
    rows = [HEADER, *(_trade(day, 1.101 if day % 2 else 1.0995) for day in range(2, 12))]
    data = _ods(rows, tail=EDGE)
    assert unwrap(data) == data
    assert detect_format(data) is not None
    trades = import_report(data, "operaciones.ods").trades.trades
    assert len(trades) == 10
    assert [round(trade.exit_price, 4) for trade in trades[:2]] == [1.0995, 1.101]
    assert trades[0].entry_time.isoformat().startswith("2026-01-02T10:00")


def test_cells_repeated_to_the_sheet_edge_are_never_laid_out() -> None:
    sheets = read_xlsx(_ods([["a", "b"]], tail=EDGE))
    assert sheets == {"Hoja1": [["a", "b"], []]}


def test_repeated_cells_and_rows_with_values_are_expanded() -> None:
    tail = (
        '<table:table-row table:number-rows-repeated="2">'
        '<table:table-cell office:value-type="string" table:number-columns-repeated="3">'
        "<text:p>x</text:p></table:table-cell></table:table-row>"
    )
    assert read_xlsx(_ods([], tail=tail))["Hoja1"] == [["x", "x", "x"], ["x", "x", "x"]]


def test_percent_time_and_currency_cells_keep_their_value() -> None:
    rows = [
        [
            ("percentage", "0.0125", "1.25 %"),
            ("time", "PT09H30M00S", "09:30"),
            ("currency", "-12.5", "-$12.50"),
        ]
    ]
    [row, *_] = read_xlsx(_ods(rows))["Hoja1"]
    assert float(row[0]) == pytest.approx(0.0125)
    assert row[1] == "09:30:00"
    assert row[2] == -12.5


def test_a_repeated_row_past_the_cell_limit_is_refused() -> None:
    tail = (
        '<table:table-row table:number-rows-repeated="999999999">'
        '<table:table-cell office:value-type="string"><text:p>x</text:p></table:table-cell>'
        "</table:table-row>"
    )
    with pytest.raises(ReportFormatError) as refused:
        read_xlsx(_ods([], tail=tail))
    assert refused.value.code == "xlsx_too_large"


def test_the_column_screen_offers_an_ods_sheet() -> None:
    rows = [
        ["Fecha", "Resultado", "Nota"],
        *([f"2026-01-{d:02d}", d - 10, "x"] for d in range(2, 20)),
    ]
    table = mapping.read_table(_ods(rows, tail=EDGE))
    assert table is not None and table.header == ["Fecha", "Resultado", "Nota"]


def test_an_equity_curve_saved_as_ods_is_read() -> None:
    rows = [["timestamp", "equity"]] + [
        [("date", f"2026-01-{day:02d}", f"{day:02d}/01/2026"), 10_000 + 10 * day]
        for day in range(1, 29)
    ]
    series = parse_equity_csv(_ods(rows, tail=EDGE))
    assert len(series.frame) == 28
    assert float(series.frame["equity"].iloc[-1]) == 10_280


def test_a_document_that_is_not_a_spreadsheet_is_still_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", "<x/>")
    with pytest.raises(ReportFormatError) as refused:
        import_report(buffer.getvalue(), "carta.odt")
    assert refused.value.code == "opendocument_sheet"
    assert "not a spreadsheet" in str(refused.value)
    assert "no es una hoja de cálculo" in refused.value.message_es
    assert "não é uma planilha" in refused.value.localized("pt")


def test_a_time_a_hair_under_the_minute_rounds_up_as_a_whole() -> None:
    rows = [
        [
            ("time", "PT15H29M59.999999997S", "15:30"),
            ("time", "PT09H05M01.4S", "09:05"),
            ("time", "PT23H59M59.6S", "23:59"),
        ]
    ]
    assert read_xlsx(_ods(rows))["Hoja1"] == [["15:30:00", "09:05:01", "23:59:59"]]


def test_a_table_inside_a_cell_is_not_read_into_the_outer_sheet() -> None:
    nested = (
        '<table:table-row><table:table-cell><table:table table:name="Dentro">'
        '<table:table-row><table:table-cell office:value-type="string"><text:p>y</text:p>'
        "</table:table-cell></table:table-row></table:table></table:table-cell></table:table-row>"
    )
    grouped = (
        "<table:table-row-group><table:table-row>"
        '<table:table-cell office:value-type="string"><text:p>z</text:p></table:table-cell>'
        "</table:table-row></table:table-row-group>"
    )
    sheets = read_xlsx(_ods([["x"]], tail=nested + grouped))
    assert sheets["Hoja1"] == [["x"], [], ["z"]]
    assert sheets["Dentro"] == [["y"]]
