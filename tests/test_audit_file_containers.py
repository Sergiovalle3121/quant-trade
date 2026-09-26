"""Zipped exports, trade tables saved as web pages (often named .xls), and a
plain answer for old Excel workbooks, OpenDocument sheets and PDFs."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from quant_trade.audit import mapping
from quant_trade.audit.guard import find_claims
from quant_trade.audit.importers import ReportFormatError, detect_format, import_report

TRADES = (
    "Symbol,Side,Quantity,Open Time,Open Price,Close Time,Close Price,Profit\n"
    + "".join(
        f"EURUSD,Buy,1,2026-01-{day:02d} 10:00,1.1000,2026-01-{day:02d} 12:00,1.1010,"
        f"{10 if day % 2 else -5}\n"
        for day in range(2, 20)
    )
).encode()


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _web_page(csv: bytes) -> bytes:
    rows = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in line.split(",")) + "</tr>"
        for line in csv.decode().strip().splitlines()
    )
    head = "<html><head><title>Movimientos</title></head>"
    return f"{head}<body><table>{rows}</table></body></html>".encode()


def _pnl(data: bytes) -> list[float]:
    return [round(trade.pnl, 2) for trade in import_report(data, "export").trades.trades]


def test_a_zip_holding_one_export_reads_like_the_export() -> None:
    expected = _pnl(TRADES)
    assert len(expected) == 18
    assert _pnl(_zip({"history.csv": TRADES})) == expected
    # macOS keeps a shadow copy in __MACOSX; hidden files are not exports either.
    assert _pnl(_zip({"h/history.csv": TRADES, "__MACOSX/h/._history.csv": b"x"})) == expected
    assert _pnl(_zip({"history.csv": TRADES, ".DS_Store": b"x"})) == expected
    assert detect_format(_zip({"history.csv": TRADES})) == detect_format(TRADES)


def test_a_trade_table_saved_as_a_web_page_is_read() -> None:
    page = _web_page(TRADES)
    assert _pnl(page) == _pnl(TRADES)
    assert _pnl(_zip({"movimientos.xls": page})) == _pnl(TRADES)


def test_a_web_page_without_a_trade_table_names_what_is_missing() -> None:
    page = _web_page(b"Symbol,Side,Comment\nEURUSD,Buy,hola\n")
    with pytest.raises(ReportFormatError) as refused:
        import_report(page, "x.xls")
    assert refused.value.code in {"unknown_format", "universal_columns_missing"}


@pytest.mark.parametrize(
    ("data", "code", "fix"),
    [
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600, "legacy_xls", ".xlsx"),
        (b"%PDF-1.7\n%binary", "pdf_statement", "CSV"),
        (
            _zip(
                {
                    "mimetype": b"application/vnd.oasis.opendocument.spreadsheet",
                    "content.xml": b"<x/>",
                }
            ),
            "opendocument_sheet",
            ".xlsx",
        ),
        (_zip({"statement.pdf": b"%PDF-1.7"}), "zip_contents", "CSV"),
        (_zip({"a.csv": TRADES, "b.csv": TRADES}), "zip_contents", "CSV"),
        (_zip({"r.xls": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600}), "legacy_xls", ".xlsx"),
    ],
)
def test_files_that_cannot_be_read_say_how_to_get_one_that_can(
    data: bytes, code: str, fix: str
) -> None:
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "upload")
    error = refused.value
    assert error.code == code
    english, spanish = str(error), error.localized("es")
    assert fix in english and fix in spanish
    assert find_claims(english) == [] and find_claims(spanish) == []
    assert detect_format(data) is None


def test_the_column_screen_reads_web_pages_and_zips_but_not_metatrader_reports() -> None:
    header = "Fecha,Resultado,Nota"
    rows = "".join(f"2026-01-{day:02d},{day - 10},x\n" for day in range(2, 20))
    csv = f"{header}\n{rows}".encode()
    for data in (_web_page(csv), _zip({"diario.csv": csv}), _zip({"diario.xls": _web_page(csv)})):
        table = mapping.read_table(data)
        assert table is not None and table.header == ["Fecha", "Resultado", "Nota"]
    from test_audit_importers import mt5_tester_report  # noqa: PLC0415

    assert mapping.read_table(mt5_tester_report(30)) is None


def test_the_upload_form_lets_a_customer_pick_these_files(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from quant_trade.audit.settings import AuditSettings  # noqa: PLC0415
    from quant_trade.audit.store import make_store  # noqa: PLC0415
    from quant_trade.audit.web import create_app  # noqa: PLC0415

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db")
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    page = client.get("/").text
    assert "name='report' accept='.htm,.html,.csv,.txt,.tsv,.xlsx,.xls,.zip'" in page
    answer = client.post(
        "/audits",
        files={"report": ("viejo.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)},
        data={"consent": "on"},
    )
    assert answer.status_code == 400
    assert "guárdalo como .xlsx o CSV" in answer.text
