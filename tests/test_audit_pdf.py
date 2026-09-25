"""The report as a PDF: only for unlocked reports, never touching the network."""

from __future__ import annotations

from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import pdf as pdf_lib  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

needs_pdf = pytest.mark.skipif(not pdf_lib.available(), reason="WeasyPrint/Pango not installed")


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def _upload(client: TestClient) -> str:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}
    response = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def _pdf_link(page: str) -> str:
    start = page.index("/pdf?token=")
    href_start = page.rindex("'", 0, start) + 1
    return page[href_start : page.index("'", start)].replace("&amp;", "&")


@needs_pdf
def test_an_unlocked_report_downloads_as_pdf(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get(_upload(client)).text
    assert "Descargar el informe en PDF" in page
    response = client.get(_pdf_link(page))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith('attachment; filename="rigor-')
    assert "no-store" in response.headers["cache-control"]
    assert response.content.startswith(b"%PDF")


def test_a_locked_report_has_no_pdf(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/0")
    location = _upload(client)
    page = client.get(location).text
    assert "/pdf?token=" not in page
    audit_id, query = location.removeprefix("/audits/").split("?")
    assert client.get(f"/audits/{audit_id}/pdf?{query}").status_code == 402
    client.cookies.clear()  # a visitor without the account
    assert client.get(f"/audits/{audit_id}/pdf?token=wrong").status_code == 404


def test_busy_and_missing_renderer_answer_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    audit_id, query = _upload(client).removeprefix("/audits/").split("?")
    for error, text in ((pdf_lib.PdfBusy, "unos segundos"), (pdf_lib.PdfUnavailable, "imprimir")):

        def fail(*_args: object, _error: type[Exception] = error, **_kwargs: object) -> bytes:
            raise _error("x")

        monkeypatch.setattr(pdf_lib, "report_pdf", fail)
        response = client.get(f"/audits/{audit_id}/pdf?{query}")
        assert response.status_code == 503
        assert text in response.text


@needs_pdf
def test_the_pdf_never_fetches_outside_urls() -> None:
    fetcher = pdf_lib._fetcher()
    for url in (
        "https://example.com/x.png",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "https://pdf.invalid/static/../../etc/passwd",
        "https://pdf.invalid/audits/x",
    ):
        with pytest.raises(ValueError):
            fetcher.fetch(url)
    font = fetcher.fetch("https://pdf.invalid/static/fonts/inter-var.woff2")
    assert font.read()[:4] == b"wOF2"
    page = "<html><head></head><body><img src='https://example.com/x.png'>ok</body></html>"
    assert pdf_lib.report_pdf(page, audit_id="a1", locale="es").startswith(b"%PDF")


def test_download_names_are_safe() -> None:
    assert pdf_lib.filename("abc123") == "rigor-abc123.pdf"
    assert pdf_lib.filename('a"b/../c') == "rigor-abc.pdf"
    assert pdf_lib.filename("") == "rigor-report.pdf"


@needs_pdf
def test_the_sample_report_downloads_as_pdf(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/0")
    for page_path, pdf_path in (("/ejemplo", "/ejemplo.pdf"), ("/sample", "/sample.pdf")):
        assert f"href='{pdf_path}'" in client.get(page_path).text
        response = client.get(pdf_path)
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
        assert response.headers["content-disposition"].startswith("attachment")


def test_the_footer_links_the_sample_pdf(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert "href='/ejemplo.pdf'" in client.get("/").text
    assert "href='/sample.pdf'" in client.get("/en").text


def test_summary_tiles_and_cards_never_split_across_pages() -> None:
    from quant_trade.audit.pdf import PDF_CSS

    assert ".kpi,.meaning .item,.recon tr{page-break-inside:avoid;break-inside:avoid}" in PDF_CSS


@needs_pdf
def test_a_second_pdf_waits_for_a_free_slot() -> None:
    import threading

    for _ in range(pdf_lib.MAX_CONCURRENT_PDFS):
        assert pdf_lib._SLOTS.acquire(blocking=False)
    page = "<html><head></head><body><p>x</p></body></html>"
    try:
        with pytest.raises(pdf_lib.PdfBusy):
            pdf_lib.report_pdf(page, audit_id="a", locale="es")
        threading.Timer(0.3, pdf_lib._SLOTS.release).start()
        content = pdf_lib.report_pdf(page, audit_id="a", locale="es", wait_seconds=10)
        assert content.startswith(b"%PDF")
    finally:
        for _ in range(pdf_lib.MAX_CONCURRENT_PDFS - 1):
            pdf_lib._SLOTS.release()


def test_a_second_download_of_the_same_report_is_not_rendered_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ten customers at once waited past the old 25 s for two render slots;
    # a double click must not take a second slot.
    calls: list[str] = []

    def render(_page: str, *, audit_id: str, locale: str, wait_seconds: float = 0.0) -> bytes:
        calls.append(locale)
        assert wait_seconds >= 60
        return b"%PDF-" + locale.encode()

    monkeypatch.setattr(pdf_lib, "report_pdf", render)
    client = _client(tmp_path)
    audit_id, query = _upload(client).removeprefix("/audits/").split("?")
    first = client.get(f"/audits/{audit_id}/pdf?{query}")
    second = client.get(f"/audits/{audit_id}/pdf?{query}")
    english = client.get(f"/audits/{audit_id}/pdf?{query}&lang=en")
    assert first.content == second.content == b"%PDF-es"
    assert english.content == b"%PDF-en"
    assert calls == ["es", "en"]
    client.cookies.clear()  # a visitor without the account
    assert client.get(f"/audits/{audit_id}/pdf?token=wrong").status_code == 404


def test_pdf_buttons_say_the_pdf_is_being_prepared(tmp_path: Path) -> None:
    """A render takes a few seconds: the buttons carry the busy text the script
    shows on click, and pages without script say it beside the button."""
    from quant_trade.audit.guard import find_claims
    from quant_trade.audit.theme import STATIC_DIR

    client = _client(tmp_path)
    location = _upload(client)
    for lang, busy, wait in (
        ("es", "Generando tu PDF… (unos segundos)", "El PDF tarda unos segundos en generarse."),
        ("en", "Preparing your PDF… (a few seconds)", "The PDF takes a few seconds to prepare."),
    ):
        pages = (client.get(f"{location}&lang={lang}").text,)
        pages += (client.get("/ejemplo" if lang == "es" else "/sample").text,)
        for page in pages:
            assert page.count(f"download data-busy='{busy}'") == 2
            assert f"<noscript> <span class='muted'>{wait}</span></noscript>" in page
            assert find_claims(page) == []
    script = (STATIC_DIR / "app.js").read_text()
    assert "a[download][data-busy]" in script and "aria-busy" in script
