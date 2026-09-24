"""The report as a PDF: only for unlocked reports, never touching the network."""

from __future__ import annotations

from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift

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
    return TestClient(create_app(settings, make_store(settings.database_url)))


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
