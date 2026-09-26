"""The trade table of a PDF statement, read only when it is plainly a table.

A PDF is a printed page, not data: its rows are rebuilt from where the
text sits. So a PDF is read under stricter rules than any other upload:

- Only ruled tables are read (pdfplumber's line strategy): cells drawn
  with borders. Text laid out with spaces is refused, never guessed.
- The extraction runs in a child process killed after
  ``MAX_PDF_SECONDS``, with its memory and CPU capped, because a crafted
  PDF can make pdfminer loop and a thread cannot be stopped.
- At most ``MAX_PDF_PAGES`` pages and ``MAX_PAGE_CHARS`` characters per
  page; a scanned PDF (no text) is refused.
- The pieces of a table split across pages are joined only when every
  piece has the same columns; a header repeated on each page is dropped.
  A row cut by a page break (most of its cells empty) makes the whole
  file refused: a misread trade costs more than a refusal.
- The rows always go to the column screen, where the customer names the
  columns and is told the rows came from a PDF (``importers``,
  ``mapping``); a PDF is never matched to a known platform on its own.

Run as ``python -m quant_trade.audit.pdf_tables`` it is the child: the PDF
on standard input, the tables as JSON on standard output.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quant_trade.audit.importers import ReportFormatError

MAX_PDF_PAGES = 30
MAX_PAGE_CHARS = 20_000
MAX_PDF_SECONDS = 10
#: The child's address space: pdfminer and pdfium on a 10 MB file stay well under it.
MAX_PDF_MEMORY = 1 << 30
#: A data row must fill at least this share of the header's named columns.
MIN_ROW_FILL = 0.6
PDF_SIGNATURE = b"%PDF-"


def is_pdf(data: bytes) -> bool:
    return data.lstrip()[:5] == PDF_SIGNATURE


def unreadable() -> ReportFormatError:
    """The answer for a PDF whose table cannot be read with confidence."""
    # Imported here: the child process needs none of the importers.
    from quant_trade.audit.importers import ReportFormatError

    return ReportFormatError(
        "pdf_statement",
        "the PDF's trade table could not be read reliably: download the history from the "
        "platform as CSV, Excel or HTML instead (the guides show where)",
        "la tabla de operaciones del PDF no se pudo leer con seguridad: descarga el "
        "historial de la plataforma en CSV, Excel o HTML (las guías muestran dónde)",
    )


def _too_many_pages() -> ReportFormatError:
    from quant_trade.audit.importers import ReportFormatError

    return ReportFormatError(
        "pdf_statement",
        f"the PDF has more than {MAX_PDF_PAGES} pages: download the history from the "
        "platform as CSV, Excel or HTML instead, or a PDF of a shorter period",
        f"el PDF tiene más de {MAX_PDF_PAGES} páginas: descarga el historial de la "
        "plataforma en CSV, Excel o HTML, o un PDF de un periodo más corto",
    )


def rows(data: bytes) -> list[list[str]]:
    """The statement's table, header first, or a refusal that says to export CSV."""
    return [list(row) for row in _rows(data)]


@functools.lru_cache(maxsize=4)
def _rows(data: bytes) -> tuple[tuple[str, ...], ...]:
    # Cached by content: the upload, the column screen and the mapped read
    # each ask for the same file, and the child costs up to seconds. A
    # refusal is not cached (an exception), so it is simply asked again.
    found = _extract(data)
    if found.get("refusal") == "pages":
        raise _too_many_pages()
    if "tables" not in found:
        raise unreadable()
    return tuple(tuple(row) for row in stitch(found["tables"]))


def _extract(data: bytes) -> dict[str, Any]:
    package_root = Path(__file__).resolve().parents[2]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(package_root),
        "PYTHONHASHSEED": "0",
    }
    try:
        done = subprocess.run(  # noqa: S603 - our own module, no shell
            [sys.executable, "-m", "quant_trade.audit.pdf_tables"],
            input=data,
            capture_output=True,
            timeout=MAX_PDF_SECONDS,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise unreadable() from exc
    if done.returncode != 0:
        return {}
    try:
        answer = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return answer if isinstance(answer, dict) else {}


def _clean(cell: object) -> str:
    return " ".join(str(cell).split()) if cell is not None else ""


def stitch(tables: list[list[list[Any]]]) -> list[list[str]]:
    """One table from the pieces found on each page, or a refusal.

    Every piece must have the first piece's columns; a piece that starts
    with the same header drops it. A data row filling less than
    ``MIN_ROW_FILL`` of the header's named columns is a row cut by a page
    break or a layout the reader did not follow: the file is refused.
    """
    pieces = [[[_clean(cell) for cell in row] for row in table] for table in tables]
    pieces = [
        [row for row in piece if any(row)] for piece in pieces if any(any(row) for row in piece)
    ]
    if not pieces:
        raise unreadable()
    header = pieces[0][0]
    named = [index for index, name in enumerate(header) if name]
    if len(named) < 3 or len(set(header[i] for i in named)) != len(named):
        raise unreadable()
    body: list[list[str]] = []
    for position, piece in enumerate(pieces):
        if any(len(row) != len(header) for row in piece):
            raise unreadable()
        start = 1 if position == 0 or piece[0] == header else 0
        body.extend(piece[start:])
    if len(body) < 2:
        raise unreadable()
    for row in body:
        filled = sum(1 for index in named if row[index])
        if filled < MIN_ROW_FILL * len(named):
            raise unreadable()
    return [header, *body]


def _child() -> int:
    """Read the PDF on standard input, write its ruled tables as JSON."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MAX_PDF_MEMORY, MAX_PDF_MEMORY))
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_PDF_SECONDS, MAX_PDF_SECONDS))
    except (ImportError, ValueError, OSError):
        pass  # the parent's timeout still bounds the run
    import io

    import pdfplumber

    data = sys.stdin.buffer.read()
    answer: dict[str, Any]
    try:
        with pdfplumber.open(io.BytesIO(data)) as document:
            if len(document.pages) > MAX_PDF_PAGES:
                answer = {"refusal": "pages"}
            else:
                tables: list[list[list[Any]]] = []
                text = 0
                answer = {}
                for page in document.pages:
                    characters = len(page.chars)
                    if characters > MAX_PAGE_CHARS:
                        answer = {"refusal": "dense"}
                        break
                    text += characters
                    tables.extend(page.extract_tables())
                if not answer:
                    answer = {"tables": tables} if text and tables else {"refusal": "no_table"}
    except Exception:  # noqa: BLE001 - any damage is the same refusal
        answer = {"refusal": "damaged"}
    sys.stdout.write(json.dumps(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(_child())
