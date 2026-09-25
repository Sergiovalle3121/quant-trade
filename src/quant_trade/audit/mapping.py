"""A file no importer recognised, shown back to the customer to name its columns.

Instead of ending in "we could not read your file", the upload answers with
the file's own columns and a few of its rows, one menu per field (entry and
exit time, prices, quantity, side, profit...), and the customer sends the same
file again with their choice. A signed-in customer's choice is remembered for
that exact header, so the next export from the same platform just works.

Nothing here keeps the file: the page shows the header and at most
``SAMPLE_ROWS`` rows back to the person who uploaded them, and the stored
mapping holds only column names and a hash of the header.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_trade.audit import importers as imp
from quant_trade.audit import universal
from quant_trade.audit.pages import _COPY, _e, _error_card, _page, _page_hero
from quant_trade.audit.seo import BRAND

#: Refusals a column mapping can fix: the table was read, its columns were not.
MAPPABLE_CODES = frozenset(
    {
        "unknown_format",
        "universal_columns_missing",
        "universal_column_unreadable",
        "universal_unknown_column",
        "universal_column_twice",
    }
)
#: Rows of the file shown under its header, so each column's content is visible.
SAMPLE_ROWS = 3
#: Columns offered in each menu; wider tables are trade lists no one maps by hand.
MAX_COLUMNS = 80
#: The form fields the mapping page carries over from the first upload.
CARRIED_FIELDS: tuple[str, ...] = (
    "locale",
    "consent",
    "trials",
    "cost_bps",
    "oos_start",
    "description",
    "benchmark_applicable",
    "challenge",
    "initial_balance",
    "access_code",
    "net_of_fees",
)

COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Tu archivo",
        "title": "Dinos qué es cada columna",
        "lead": (
            "Leímos tu archivo pero no reconocimos sus columnas. Elige en cada menú la columna "
            "que corresponde y vuelve a subir el mismo archivo: lo auditamos con tu elección."
        ),
        "found": "Así se ve tu archivo",
        "found_help": "La cabecera y las primeras filas, tal como las leímos.",
        "choose": "Elige las columnas",
        "choose_help": (
            "Con una fila por operación: entrada, salida, cantidad y precios. Con una fila por "
            "ejecución (cada compra y cada venta): hora, lado, cantidad y precio. Lo demás es "
            "opcional."
        ),
        "none": "— ninguna —",
        "example": "ej.",
        "file": "Vuelve a elegir el mismo archivo",
        "file_help": (
            "Por seguridad no guardamos el archivo hasta auditarlo, así que el navegador "
            "necesita que lo elijas otra vez."
        ),
        "remember": (
            "Si tienes cuenta, recordamos esta elección para archivos con la misma cabecera: "
            "la próxima vez se lee solo."
        ),
        "extra": (
            "Si también subiste otros archivos (curva, benchmark, variantes), vuelve al "
            "formulario para añadirlos."
        ),
        "submit": "Auditar con estas columnas",
        "back": "Volver al formulario",
        "unnamed": "(sin nombre)",
        "unknown": (
            "Tu archivo: no es el informe de una plataforma que reconozcamos, pero sí una "
            "tabla. Indica qué es cada columna y lo auditamos."
        ),
    },
    "en": {
        "eyebrow": "Your file",
        "title": "Tell us what each column is",
        "lead": (
            "We read your file but did not recognise its columns. Pick the matching column in "
            "each menu and upload the same file again: we audit it with your choice."
        ),
        "found": "What your file looks like",
        "found_help": "The header and the first rows, as we read them.",
        "choose": "Choose the columns",
        "choose_help": (
            "With one row per trade: entry, exit, quantity and prices. With one row per fill "
            "(each buy and each sell): time, side, quantity and price. The rest is optional."
        ),
        "none": "— none —",
        "example": "e.g.",
        "file": "Choose the same file again",
        "file_help": (
            "For your safety we do not keep the file until it is audited, so the browser needs "
            "you to pick it again."
        ),
        "remember": (
            "With an account, we remember this choice for files with the same header: next "
            "time it is read on its own."
        ),
        "extra": (
            "If you also uploaded other files (curve, benchmark, variants), go back to the form "
            "to add them."
        ),
        "submit": "Audit with these columns",
        "back": "Back to the form",
        "unnamed": "(no name)",
        "unknown": (
            "Your file: it is not the report of a platform we recognise, but it is a table. "
            "Say what each column is and we audit it."
        ),
    },
}


@dataclass(frozen=True)
class Table:
    """A file's header row and the first rows under it, as text."""

    header: list[str]
    samples: list[list[str]]

    @property
    def names(self) -> list[str]:
        """The columns a menu can offer: named, each name once, in file order."""
        seen: dict[str, None] = {}
        for name in self.header:
            if name.strip():
                seen.setdefault(name.strip(), None)
        return list(seen)[:MAX_COLUMNS]


def _is_number(cell: str) -> bool:
    return imp._num(cell, decimal=".") is not None or imp._num(cell, decimal=",") is not None


def _header_at(rows: Sequence[Sequence[str]]) -> int | None:
    """The first top row that reads as a header: two or more named cells,
    mostly words (a preamble line such as ``UID: 123`` has one cell)."""
    for index, row in enumerate(rows[: imp.UNIVERSAL_HEADER_SCAN]):
        filled = [cell for cell in row if cell.strip()]
        if len(filled) >= 2 and sum(_is_number(cell) for cell in filled) * 2 < len(filled):
            return index
    return None


def _table(rows: list[list[str]]) -> Table | None:
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    at = _header_at(rows)
    if at is None or at + 1 >= len(rows):
        return None
    header = [cell.strip() for cell in rows[at]]
    samples = [
        [cell.strip() for cell in row[: len(header)]] for row in rows[at + 1 : at + 1 + SAMPLE_ROWS]
    ]
    return Table(header, samples)


def read_table(data: bytes) -> Table | None:
    """The header and first rows of a CSV or Excel list, or ``None`` when the
    file is not a table (an HTML report, a PDF, a damaged workbook)."""
    try:
        if imp._is_zip(data):
            for sheet in imp.read_xlsx(data).values():
                found = _table([[imp._as_text(cell) for cell in row] for row in sheet])
                if found is not None:
                    return found
            return None
        text = imp.decode_text(data)
        lowered = text.lstrip()[:4000].lower()
        if "<html" in lowered or "<table" in lowered or text.lstrip().startswith("<"):
            return None
        header, rows, _ = imp._read_delimited(text)
    except (imp.ReportFormatError, ValueError):
        return None
    return _table([header, *rows])


def header_signature(header: Sequence[str]) -> str:
    """The SHA-256 of a header's normalised names: the same export from the
    same platform has the same signature, whatever its rows hold."""
    names = "\x1f".join(universal.normalise(str(name)) for name in header)
    return hashlib.sha256(names.encode("utf-8")).hexdigest()


def usable_mapping(columns: Mapping[str, str], table: Table) -> dict[str, str]:
    """A stored or posted mapping kept to known fields and to columns the
    table holds, so a stale choice never reaches the reader."""
    names = set(table.names)
    return {
        role: name
        for role, name in columns.items()
        if role in universal.ROLES and isinstance(name, str) and name in names
    }


def dumps(columns: Mapping[str, str]) -> str:
    return json.dumps(dict(sorted(columns.items())), ensure_ascii=False)


def loads(text: str | None) -> dict[str, str]:
    try:
        found = json.loads(text or "{}")
    except ValueError:
        return {}
    if not isinstance(found, dict):
        return {}
    return {str(role): str(name) for role, name in found.items() if isinstance(name, str)}


def guessed(table: Table) -> dict[str, str]:
    """Each field's column as the universal reader would guess it by name."""
    return {
        role: table.header[index].strip()
        for role, index in universal.guess_columns(table.header).items()
        if role in universal.ROLES and table.header[index].strip()
    }


def _example(table: Table, name: str) -> str:
    try:
        index = [cell.strip() for cell in table.header].index(name)
    except ValueError:
        return ""
    for row in table.samples:
        if index < len(row) and row[index].strip():
            return imp._clip(row[index].strip(), 24)
    return ""


def _select(role: str, label: str, table: Table, chosen: str, words: Mapping[str, str]) -> str:
    options = [f"<option value=''>{_e(words['none'])}</option>"]
    for name in table.names:
        example = _example(table, name)
        text = f"{imp._clip(name, 50)}" + (f" · {words['example']} {example}" if example else "")
        selected = " selected" if name == chosen else ""
        options.append(f"<option value='{_e(name)}'{selected}>{_e(text)}</option>")
    ident = f"m-{role}"
    return (
        f"<div class='field'><label for='{ident}'>{_e(label)}</label>"
        f"<select id='{ident}' name='col_{role}'>{''.join(options)}</select></div>"
    )


def _preview(table: Table, words: Mapping[str, str]) -> str:
    head = "".join(
        f"<th>{_e(imp._clip(name, 40) or words['unnamed'])}</th>" for name in table.header
    )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{_e(imp._clip(row[i], 40) if i < len(row) else '')}</td>"
            for i in range(len(table.header))
        )
        + "</tr>"
        for row in table.samples
    )
    return (
        f"<div class='tscroll'><table style='white-space:nowrap'><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def mapping_page(
    table: Table,
    problem: str,
    *,
    locale: str = "es",
    carried: Mapping[str, str] | None = None,
    chosen: Mapping[str, str] | None = None,
) -> str:
    """The page that shows the file's columns and asks which is which.

    ``problem`` is the refusal in the customer's language, ``carried`` the
    first upload's other form fields (sent again unchanged), ``chosen`` the
    columns to preselect (the customer's own choice, else the reader's guess).
    """
    locale = "en" if locale == "en" else "es"
    words = COPY[locale]
    form_copy = _COPY[locale]
    labels: Mapping[str, str] = form_copy["map_roles"]
    picked = dict(guessed(table))
    picked.update(usable_mapping(chosen or {}, table))
    groups = "".join(
        f"<fieldset class='map-group'><legend>{_e(title)}</legend><div class='form-grid'>"
        + "".join(_select(role, labels[role], table, picked.get(role, ""), words) for role in roles)
        + "</div></fieldset>"
        for title, roles in form_copy["map_groups"]
    )
    hidden = "".join(
        f"<input type='hidden' name='{name}' value='{_e(value)}'>"
        for name, value in (carried or {}).items()
        if name in CARRIED_FIELDS and value
    )
    if "locale" not in (carried or {}):
        hidden += f"<input type='hidden' name='locale' value='{locale}'>"
    body = (
        _page_hero(words["eyebrow"], words["title"], words["lead"], dot="warn")
        + "<div class='paper page-main'><div class='wrap'>"
        + _error_card(problem, locale)
        + f"<section class='map-preview' style='margin-top:32px'><h2>{_e(words['found'])}</h2>"
        f"<p class='help'>{_e(words['found_help'])}</p>{_preview(table, words)}</section>"
        "<form class='map-form' action='/audits' method='post' enctype='multipart/form-data' "
        "style='margin-top:36px'>"
        f"{hidden}<h2>{_e(words['choose'])}</h2><p class='help'>{_e(words['choose_help'])}</p>"
        f"{groups}"
        "<div class='field'><label for='m-report'>"
        f"{_e(words['file'])}</label>"
        "<input id='m-report' type='file' name='report' required "
        "accept='.csv,.txt,.tsv,.xlsx,text/csv' aria-describedby='m-report-help'>"
        f"<div class='help' id='m-report-help'>{_e(words['file_help'])}</div></div>"
        f"<p class='help'>{_e(words['remember'])}</p><p class='help'>{_e(words['extra'])}</p>"
        "<div class='back-row'>"
        f"<button class='btn btn-dark' type='submit'>{_e(words['submit'])}</button>"
        f"<a class='btn btn-ghost' href='/?lang={locale}#subir'>{_e(words['back'])}</a>"
        "</div></form></div></div>"
    )
    return _page(f"{words['title']} · {BRAND}", locale, body, solid_nav=True)
