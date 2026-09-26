"""PDF statements: read only as a ruled table, always through the column screen.

Every PDF here is printed in the test from HTML with WeasyPrint (already the
report's PDF engine); no third-party file is used.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("pdfplumber")
weasyprint = pytest.importorskip("weasyprint")

from quant_trade.audit import mapping, pdf_tables  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.importers import (  # noqa: E402
    PDF_ROWS_WARNING,
    ReportFormatError,
    detect_format,
    import_report,
)

HEADER = ["Apertura", "Cierre", "Símbolo", "Tipo", "Volumen", "Precio apertura", "Precio cierre"]
COLUMNS = {
    "entry_time": "Apertura",
    "exit_time": "Cierre",
    "symbol": "Símbolo",
    "side": "Tipo",
    "quantity": "Volumen",
    "entry_price": "Precio apertura",
    "exit_price": "Precio cierre",
}
RULED = (
    "table{border-collapse:collapse} td,th{border:1px solid #000;padding:2px 4px} "
    "tr{page-break-inside:avoid;break-inside:avoid}"
)


def _row(day: int) -> list[str]:
    month, date = 1 + (day - 1) // 28, 1 + (day - 1) % 28
    close = "1.1010" if day % 3 else "1.0990"
    return [
        f"2026-{month:02d}-{date:02d} 10:00",
        f"2026-{month:02d}-{date:02d} 12:00",
        "EURUSD",
        "Buy",
        "1",
        "1.1000",
        close,
    ]


def _statement(rows: list[list[str]], *, css: str = RULED, pages: int = 0) -> bytes:
    head = "".join(f"<th>{name}</th>" for name in HEADER)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    filler = "".join("<p style='page-break-before:always'>.</p>" for _ in range(pages))
    html = (
        f"<html><head><style>{css}</style></head><body><h1>Estado de cuenta</h1>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{filler}"
        "</body></html>"
    )
    return weasyprint.HTML(string=html).write_pdf()


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    pdf_tables._rows.cache_clear()
    yield
    pdf_tables._rows.cache_clear()


#: 90 trades: the table runs over several pages, its header repeated on each.
TRADES = [_row(day) for day in range(1, 91)]


def test_a_ruled_statement_goes_to_the_column_screen_not_to_a_platform() -> None:
    data = _statement(TRADES)
    assert detect_format(data) is None
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "estado.pdf")
    assert refused.value.code == "pdf_columns"
    assert refused.value.code in mapping.MAPPABLE_CODES
    assert "columnas" in refused.value.message_es
    assert "colunas" in refused.value.localized("pt")
    table = mapping.read_table(data)
    assert table is not None and table.pdf
    assert table.header == HEADER
    assert table.samples[0] == _row(1)


def test_the_screen_says_the_rows_came_from_a_pdf_in_every_language() -> None:
    table = mapping.read_table(_statement(TRADES))
    assert table is not None
    notices = {"es": "vienen de la tabla de un PDF", "en": "come from a table in a PDF"}
    notices["pt"] = "vêm da tabela de um PDF"
    for locale, notice in notices.items():
        page = mapping.mapping_page(table, "x", locale=locale)
        assert notice in page
        assert find_claims(mapping.COPY[locale]["pdf_notice"]) == []
    plain = mapping.Table(table.header, table.samples)
    assert "vienen de la tabla de un PDF" not in mapping.mapping_page(plain, "x")


def test_the_named_columns_read_every_page_once_and_the_report_says_it_was_a_pdf() -> None:
    report = import_report(_statement(TRADES), "estado.pdf", columns=COLUMNS)
    trades = report.trades.trades
    assert len(trades) == 90
    assert trades[0].entry_time.isoformat().startswith("2026-01-01T10:00")
    assert round(sum(trade.pnl for trade in trades), 4) == round(60 * 0.001 - 30 * 0.001, 4)
    assert PDF_ROWS_WARNING in report.warnings


def test_text_laid_out_without_rules_is_refused_with_how_to_export() -> None:
    data = _statement(TRADES[:10], css="td,th{padding:2px 8px}")
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "estado.pdf")
    assert refused.value.code == "pdf_statement"
    english, spanish, portuguese = (
        str(refused.value),
        refused.value.message_es,
        refused.value.localized("pt"),
    )
    assert "CSV" in english and "CSV" in spanish and "CSV" in portuguese
    assert "could not be read reliably" in english
    assert "no se pudo leer con seguridad" in spanish
    assert "não pôde ser lida com segurança" in portuguese
    for text in (english, spanish, portuguese):
        assert find_claims(text) == []
    assert mapping.read_table(data) is None


def test_a_pdf_past_the_page_limit_is_refused() -> None:
    data = _statement(TRADES[:3], pages=pdf_tables.MAX_PDF_PAGES)
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "estado.pdf")
    assert refused.value.code == "pdf_statement"
    assert f"more than {pdf_tables.MAX_PDF_PAGES} pages" in str(refused.value)
    assert "mais de 30 páginas" in refused.value.localized("pt")


def test_a_damaged_pdf_or_a_slow_one_gets_the_same_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ReportFormatError) as damaged:
        import_report(b"%PDF-1.7\n%binary", "estado.pdf")
    assert damaged.value.code == "pdf_statement"
    monkeypatch.setattr(pdf_tables, "MAX_PDF_SECONDS", 0.001)
    with pytest.raises(ReportFormatError) as slow:
        import_report(_statement(TRADES[:5]), "estado.pdf")
    assert slow.value.code == "pdf_statement"


def test_pieces_with_other_columns_are_refused() -> None:
    header = ["Fecha", "Símbolo", "Resultado"]
    first = [header, ["2026-01-01", "ES", "10"], ["2026-01-02", "ES", "12"]]
    assert pdf_tables.stitch([first, [header, ["2026-01-03", "ES", "-4"]]]) == [
        header,
        ["2026-01-01", "ES", "10"],
        ["2026-01-02", "ES", "12"],
        ["2026-01-03", "ES", "-4"],
    ]
    with pytest.raises(ReportFormatError):
        pdf_tables.stitch([first, [["2026-01-03", "ES", "-4", "x"]]])


def test_a_row_cut_by_a_page_break_refuses_the_whole_file() -> None:
    header = ["Fecha", "Símbolo", "Resultado", "Comisión", "Nota"]
    rows = [header, ["2026-01-01", "ES", "10", "1", ""], ["2026-01-02", "", "", "", ""]]
    with pytest.raises(ReportFormatError):
        pdf_tables.stitch([rows])


@pytest.mark.parametrize(
    "header",
    [["Fecha", "", ""], ["Fecha", "Fecha", "Resultado"]],
)
def test_a_header_that_names_too_little_is_refused(header: list[str]) -> None:
    with pytest.raises(ReportFormatError):
        pdf_tables.stitch([[header, ["a", "b", "c"], ["d", "e", "f"]]])


def test_the_upload_shows_the_screen_with_the_notice_then_reads_the_named_columns(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    files = {"report": ("estado.pdf", _statement(TRADES), "application/pdf")}
    screen = client.post("/audits", files=files, data={"consent": "on"})
    assert screen.status_code == 422, screen.text[:300]
    assert "vienen de la tabla de un PDF" in screen.text
    named = {f"col_{role}": name for role, name in COLUMNS.items()}
    posted = client.post(
        "/audits", files=files, data={"consent": "on", **named}, follow_redirects=False
    )
    assert posted.status_code == 303, posted.text[:500]
