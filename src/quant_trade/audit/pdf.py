"""The full report as a PDF file the customer downloads with one click.

The PDF is the report page itself, laid out for A4 paper by WeasyPrint with
the page's own print stylesheet plus the few rules below. It never reaches
the network: the only resources it may load are the site's own self-hosted
fonts (read from the package) and inline ``data:`` URIs; every other URL is
refused. WeasyPrint is optional (it needs Pango from the system), so the web
service answers 503 when it is missing instead of failing to start.
"""

from __future__ import annotations

import html
import threading
from typing import Any
from urllib.parse import urlsplit

from quant_trade.audit.seo import BRAND
from quant_trade.audit.theme import static_file

#: At most this many PDFs are laid out at once; a render takes a few seconds
#: of CPU, so a burst of clicks waits its turn instead of starving uploads.
MAX_CONCURRENT_PDFS = 2
_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_PDFS)
#: Relative URLs in the page resolve against this host, which never exists:
#: the fetcher answers ``/static/`` paths from the package and nothing else.
_BASE_HOST = "pdf.invalid"

#: Rules WeasyPrint needs on top of the page's print stylesheet: A4 margins,
#: a running footer, and fixed sizes where the screen styles use ``clamp()``.
PDF_CSS = """
@page{size:A4;margin:15mm 13mm 17mm;
@bottom-left{content:"__FOOTER__";font:7.5pt 'Inter',sans-serif;color:#666}
@bottom-right{content:counter(page) " / " counter(pages);font:7.5pt 'Inter',sans-serif;
color:#666}}
body{font-size:9.5pt}
.report-hero h1{font-size:30pt;line-height:1.1;margin:6px 0 10px}
.rsec>h2,.detail>h2{display:block;font-size:14pt;margin:0 0 10px}
.rsec>h2::before,.detail>h2::before{display:inline-block;vertical-align:-3px;margin-right:9px}
.badge{display:inline-block;white-space:nowrap}
.badge::before{display:inline-block;margin-right:5px;vertical-align:1px}
.rsec,.detail{margin:0 0 22px}
.report-main{padding:8px 0}
table{page-break-inside:auto}tr{page-break-inside:avoid}
.kpi b{font-size:15pt}
.kpi,.meaning .item,.recon tr{page-break-inside:avoid;break-inside:avoid}
svg{max-width:100%}
table.live{table-layout:fixed;width:100%;font-size:8.5pt}
table.live .val{white-space:normal}table.live td:first-child{width:22%}
table.pair{width:100%;font-size:8.5pt}table.pair td:first-child{width:55%}
"""


class PdfUnavailable(RuntimeError):
    """WeasyPrint (or the system library it needs) is not installed."""


class PdfBusy(RuntimeError):
    """Every PDF slot is taken; the customer should try again shortly."""


def available() -> bool:
    """True when this process can lay out PDFs."""
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _fetcher() -> Any:
    """A WeasyPrint URL fetcher that serves the site's own fonts and inline
    ``data:`` URIs, and refuses every other URL (no network, no files)."""
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    class LocalFetcher(URLFetcher):
        def fetch(self, url: str, headers: Any = None) -> Any:
            parts = urlsplit(url)
            if parts.scheme == "data":
                return super().fetch(url, headers)
            if parts.netloc == _BASE_HOST and parts.path.startswith("/static/"):
                found = static_file(parts.path.removeprefix("/static/"))
                if found is not None:
                    content, media_type = found
                    return URLFetcherResponse(
                        url, body=content, headers={"Content-Type": media_type}
                    )
            raise ValueError(f"the PDF may not load {url!r}")

    return LocalFetcher(allowed_protocols=("data", "https"), allow_redirects=False)


def footer_text(audit_id: str, locale: str) -> str:
    word = {"en": "report", "pt": "relatório"}.get(locale, "informe")
    return f"{BRAND} · {word} {audit_id}"


def report_pdf(page_html: str, *, audit_id: str, locale: str, wait_seconds: float = 0.0) -> bytes:
    """``page_html`` (a rendered report) as PDF bytes.

    Raises ``PdfUnavailable`` without WeasyPrint and ``PdfBusy`` when
    ``MAX_CONCURRENT_PDFS`` renders are still running after ``wait_seconds``
    (a second click on the download button waits its turn instead of
    failing at once).
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise PdfUnavailable(str(exc)) from exc
    acquired = (
        _SLOTS.acquire(timeout=wait_seconds) if wait_seconds > 0 else _SLOTS.acquire(blocking=False)
    )
    if not acquired:
        raise PdfBusy("too many PDFs at once")
    try:
        footer = footer_text(audit_id, locale).replace("\\", "").replace('"', "")
        # Inside the page, after its own styles, so these rules win the cascade.
        style = "<style>" + PDF_CSS.replace("__FOOTER__", footer) + "</style>"
        page_html = page_html.replace("</head>", style + "</head>", 1)
        document = HTML(string=page_html, base_url=f"https://{_BASE_HOST}/", url_fetcher=_fetcher())
        return bytes(document.write_pdf())
    finally:
        _SLOTS.release()


def filename(audit_id: str) -> str:
    """The download name, made only of safe characters."""
    safe = "".join(ch for ch in audit_id if ch.isalnum())[:40] or "report"
    return f"{BRAND.lower()}-{html.escape(safe)}.pdf"


__all__ = [
    "MAX_CONCURRENT_PDFS",
    "PDF_CSS",
    "PdfBusy",
    "PdfUnavailable",
    "available",
    "filename",
    "footer_text",
    "report_pdf",
]
