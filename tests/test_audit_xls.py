"""Excel 97-2003 workbooks (.xls) are read like .xlsx workbooks.

Every file here is written byte by byte by ``biff8`` from Microsoft's
published formats; no third-party file is used.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

import pytest
from biff8 import xls

from quant_trade.audit import importers, mapping
from quant_trade.audit.importers import (
    ReportFormatError,
    detect_format,
    import_report,
    read_xlsx,
    unwrap,
)
from quant_trade.audit.schema import parse_equity_csv

HEADER = ["Symbol", "Side", "Quantity", "Open Time", "Open Price", "Close Time", "Close Price"]


def _trades() -> list[list[object]]:
    return [
        HEADER,
        *(
            [
                "EURUSD",
                "Buy",
                1,
                datetime(2026, 1, day, 10, 0),
                1.1,
                datetime(2026, 1, day, 12, 30),
                1.101 if day % 2 else 1.0995,
            ]
            for day in range(2, 12)
        ),
    ]


def test_a_trade_list_saved_as_xls_is_read_like_a_workbook() -> None:
    data = xls({"Movimientos": _trades()})
    assert unwrap(data) == data
    assert detect_format(data) is not None
    trades = import_report(data, "movimientos.xls").trades.trades
    assert len(trades) == 10
    assert trades[0].entry_time.isoformat().startswith("2026-01-02T10:00")
    assert trades[0].exit_time.isoformat().startswith("2026-01-02T12:30")
    assert [round(trade.exit_price, 4) for trade in trades[:2]] == [1.0995, 1.101]


def test_dates_come_back_as_text_and_blank_cells_are_trimmed() -> None:
    rows = [["Fecha", "Saldo", "Nota"], [datetime(2026, 8, 1, 9, 30), 1.25, None]]
    assert read_xlsx(xls({"Hoja1": rows})) == {
        "Hoja1": [["Fecha", "Saldo", "Nota"], ["2026-08-01 09:30:00", 1.25]]
    }


def test_the_column_screen_offers_an_xls_sheet() -> None:
    rows = [
        ["Fecha", "Resultado", "Nota"],
        *([f"2026-01-{d:02d}", d - 10, "x"] for d in range(2, 20)),
    ]
    table = mapping.read_table(xls({"Hoja1": rows}))
    assert table is not None and table.header == ["Fecha", "Resultado", "Nota"]


def test_an_equity_curve_saved_as_xls_is_read() -> None:
    rows = [["timestamp", "equity"]] + [
        [datetime(2026, 1, day), 10_000 + 10 * day] for day in range(1, 29)
    ]
    series = parse_equity_csv(xls({"Curva": rows}))
    assert len(series.frame) == 28
    assert float(series.frame["equity"].iloc[-1]) == 10_280


def test_an_xls_inside_a_zip_is_read() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("movimientos.xls", xls({"Hoja1": _trades()}))
    assert len(import_report(buffer.getvalue(), "export.zip").trades.trades) == 10


def test_a_sheet_past_the_cell_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importers, "MAX_XLSX_CELLS", 20)
    with pytest.raises(ReportFormatError) as refused:
        read_xlsx(xls({"Hoja1": _trades()}))
    assert refused.value.code == "xlsx_too_large"


@pytest.mark.parametrize(
    "damage",
    [
        lambda data: data[:600],
        lambda data: data[:1024] + b"\xff" * (len(data) - 1024),
        lambda data: data.replace("Workbook".encode("utf-16-le"), "Nothing!".encode("utf-16-le")),
    ],
)
def test_a_damaged_or_foreign_ole_file_gets_the_plain_answer(damage: object) -> None:
    data = damage(xls({"Hoja1": _trades()}))  # type: ignore[operator]
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "cuenta.xls")
    assert refused.value.code == "legacy_xls"
    assert ".xlsx" in str(refused.value)
    assert detect_format(data) is None
