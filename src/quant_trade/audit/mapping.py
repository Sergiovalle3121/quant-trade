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
from datetime import UTC, datetime, timedelta

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
        "mapped_curve_unreadable",
    }
)
#: Rows of the file shown under its header, so each column's content is visible.
SAMPLE_ROWS = 3
#: Columns offered in each menu and shown in the preview.
MAX_COLUMNS = 80
#: A header wider than this gets the plain refusal: no one names columns by
#: hand in such a table, and rendering it would cost the server for nothing.
MAX_HEADER = universal.WIDEST_HEADER
#: Two fields that are enough on their own: a date with each trade's result
#: (``profit``), or a date with the account's balance or equity.
CURVE_ROLES: tuple[str, ...] = ("date", "balance")
#: Every field the mapping page can post.
FORM_ROLES: tuple[str, ...] = (*universal.ROLES, *CURVE_ROLES)
#: Columns that can stand for the date of a result or balance row.
_DATE_ROLES: tuple[str, ...] = ("date", "exit_time", "time")

MAPPED_PROFIT_WARNING = (
    "the curve was built from each trade's date and result only; without prices, "
    "quantities or entry times, holding times, entry timing and trade-level checks "
    "cannot be measured"
)
MAPPED_BALANCE_WARNING = (
    "the curve was read from the balance column you named; the file lists no trades, so "
    "trade-level checks cannot be measured"
)
MAPPED_DROPPED_WARNING = "{n} row(s) without a readable date or amount were left out"
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
        "curve_group": "Si solo tienes fecha y resultado, o fecha y saldo",
        "curve_help": (
            "Basta con la fecha y el «Resultado de la operación» de arriba, o con la fecha y "
            "el saldo: Rigor arma la curva con eso."
        ),
        "role_date": "Fecha",
        "role_balance": "Saldo o equity de la cuenta",
        "more_columns": "y {n} columnas más, que no se muestran",
        "missing": "Para leerlo como {what} aún falta: {fields}.",
        "also": (
            "También basta con una fecha y el resultado de cada operación, o con una fecha y "
            "el saldo."
        ),
        "what_trade": "una fila por operación",
        "what_fill": "una fila por ejecución",
        "what_profit": "fecha y resultado",
        "what_balance": "fecha y saldo",
        "few_rows": (
            "Tu archivo: con esas columnas quedan menos de dos filas con fecha y cifra "
            "legibles. Revisa que la fecha y la cifra sean las columnas correctas."
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
        "curve_group": "If you only have a date and a result, or a date and a balance",
        "curve_help": (
            "A date with the 'Trade result' above is enough, or a date with the balance: "
            "Rigor builds the curve from that."
        ),
        "role_date": "Date",
        "role_balance": "Account balance or equity",
        "more_columns": "and {n} more columns, not shown",
        "missing": "To read it as {what}, still missing: {fields}.",
        "also": "A date with each trade's result, or a date with the balance, is enough too.",
        "what_trade": "one row per trade",
        "what_fill": "one row per fill",
        "what_profit": "date and result",
        "what_balance": "date and balance",
        "few_rows": (
            "Your file: with those columns fewer than two rows have a readable date and "
            "figure. Check that the date and the figure are the right columns."
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


@dataclass(frozen=True)
class _Body:
    """A table's header and every row under it, with how its numbers read."""

    header: list[str]
    rows: list[list[str]]
    serial: bool
    decimal: str


def _body(rows: list[list[str]], *, serial: bool, decimal: str) -> _Body | None:
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    at = _header_at(rows)
    if at is None or at + 1 >= len(rows) or len(rows[at]) > MAX_HEADER:
        return None
    header = [cell.strip() for cell in rows[at]]
    body = [[cell.strip() for cell in row[: len(header)]] for row in rows[at + 1 :]]
    return _Body(header, body, serial, decimal)


def _read_body(data: bytes) -> _Body | None:
    try:
        if imp._is_zip(data):
            for sheet in imp.read_xlsx(data).values():
                found = _body(
                    [[imp._as_text(cell) for cell in row] for row in sheet],
                    serial=True,
                    decimal=".",
                )
                if found is not None:
                    return found
            return None
        text = imp.decode_text(data)
        lowered = text.lstrip()[:4000].lower()
        if "<html" in lowered or "<table" in lowered or text.lstrip().startswith("<"):
            return None
        # A 200,000-column header is not a table anyone names by hand.
        top = text[:4_000_000].splitlines()[: imp.UNIVERSAL_HEADER_SCAN + 1]
        if any(line.count(mark) > MAX_HEADER * 4 for line in top for mark in ",;\t|"):
            return None
        header, rows, delimiter = imp._read_delimited(text)
    except (imp.ReportFormatError, ValueError):
        return None
    return _body([header, *rows], serial=False, decimal="," if delimiter == ";" else ".")


def read_table(data: bytes) -> Table | None:
    """The header and first rows of a CSV or Excel list, or ``None`` when the
    file is not a table (an HTML report, a PDF, a damaged workbook) or its
    header is wider than ``MAX_HEADER`` columns."""
    body = _read_body(data)
    if body is None:
        return None
    return Table(body.header, body.rows[:SAMPLE_ROWS])


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
        if role in FORM_ROLES and isinstance(name, str) and name in names
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


def _date_role(columns: Mapping[str, str]) -> str | None:
    return next((role for role in _DATE_ROLES if columns.get(role)), None)


def curve_kind(columns: Mapping[str, str]) -> str | None:
    """``balance`` or ``profit`` when the mapping names a date with a balance,
    or a date with each trade's result and not a full trade or fill list;
    else ``None`` (the universal reader takes the mapping)."""
    if _date_role(columns) is None:
        return None
    if columns.get("balance"):
        return "balance"
    full = all(columns.get(role) for role in universal.TRADE_ROLES) or all(
        columns.get(role) for role in universal.FILL_ROLES
    )
    if columns.get("profit") and not full:
        return "profit"
    return None


def _figures(values: list[str], decimal: str) -> list[float | None]:
    read = [universal._amount(value, decimal) for value in values]
    other = "." if decimal == "," else ","
    swapped = [universal._amount(value, other) for value in values]
    # A comma-decimal column in a comma-free export, or the reverse.
    if sum(x is not None for x in swapped) > sum(x is not None for x in read):
        return swapped
    return read


def curve_from_columns(
    data: bytes,
    columns: Mapping[str, str],
    *,
    initial_balance: float | None,
    locale: str = "es",
) -> tuple[bytes, list[str]]:
    """An equity CSV (``timestamp,equity``) from a date column and either the
    balance or each trade's result, with the warnings that go with it.

    Results are chained from ``initial_balance`` (the declared one, else
    ``DEFAULT_INITIAL_BALANCE`` with the importers' own warning), one day
    before the first result, so the first trade counts as a return.
    """
    kind = curve_kind(columns)
    body = _read_body(data)
    date_role = _date_role(columns)
    if kind is None or body is None or date_role is None:
        raise imp.ReportFormatError("mapped_curve_unreadable", _few_rows("en"), _few_rows("es"))
    names = [cell.strip() for cell in body.header]
    try:
        date_at = names.index(columns[date_role])
        value_at = names.index(columns[kind])
    except ValueError as exc:
        raise imp.ReportFormatError(
            "mapped_curve_unreadable", _few_rows("en"), _few_rows("es")
        ) from exc

    def cell(row: list[str], at: int) -> str:
        return row[at] if at < len(row) else ""

    times = universal._times(
        [cell(row, date_at) for row in body.rows],
        body.serial,
        zone=universal.header_zone(names[date_at]),
    ).values
    figures = _figures([cell(row, value_at) for row in body.rows], body.decimal)
    points = sorted(
        (
            (when.astimezone(UTC).replace(tzinfo=None) if when.tzinfo else when, figure)
            for when, figure in zip(times, figures, strict=True)
            if when is not None and figure is not None
        ),
        key=lambda point: point[0],
    )
    dropped = len(body.rows) - len(points)
    if len(points) < 2:
        raise imp.ReportFormatError("mapped_curve_unreadable", _few_rows("en"), _few_rows("es"))
    warnings: list[str] = []
    curve: dict[datetime, float] = {}
    if kind == "balance":
        warnings.append(MAPPED_BALANCE_WARNING)
        for when, figure in points:
            curve[when] = figure
    else:
        warnings.append(MAPPED_PROFIT_WARNING)
        start = initial_balance
        if start is None or start <= 0:
            start = imp.DEFAULT_INITIAL_BALANCE
            warnings.append(
                f"the file does not state a starting balance; {start:,.0f} was assumed, "
                "which scales every return and drawdown"
            )
        first = points[0][0]
        curve[datetime(first.year, first.month, first.day) - timedelta(days=1)] = start
        level = start
        for when, figure in points:
            level += figure
            curve[when] = level
            if level <= 0:
                day = when.date().isoformat()
                raise imp.ReportFormatError(
                    "mapped_results_below_zero",
                    f"the results add up to zero or less on {day} from a starting balance of "
                    f"{start:,.0f}: state the account's starting balance on the form and "
                    "upload it again",
                    f"Los resultados suman cero o menos el {day} desde un balance inicial de "
                    f"{start:,.0f}: declara el balance inicial de la cuenta en el formulario y "
                    "vuelve a subirlo.",
                )
    if dropped:
        warnings.append(MAPPED_DROPPED_WARNING.format(n=dropped))
    lines = ["timestamp,equity"]
    lines.extend(f"{when.isoformat(sep=' ')},{value!r}" for when, value in curve.items())
    return ("\n".join(lines) + "\n").encode(), warnings


def _few_rows(locale: str) -> str:
    return COPY[locale]["few_rows"]


def missing_fields(columns: Mapping[str, str], locale: str = "es") -> str:
    """Which fields the customer's choice still lacks, for the closest way
    to read the file, and that a date with a result or balance is enough."""
    locale = "en" if locale == "en" else "es"
    words = COPY[locale]
    labels: Mapping[str, str] = {
        **_COPY[locale]["map_roles"],
        "date": words["role_date"],
        "balance": words["role_balance"],
    }
    has_date = _date_role(columns) is not None
    ways = (
        ("trade", universal.TRADE_ROLES),
        ("fill", universal.FILL_ROLES),
        ("profit", ("date", "profit")),
        ("balance", ("date", "balance")),
    )

    def lacking(roles: Sequence[str]) -> list[str]:
        return [role for role in roles if not (has_date if role == "date" else columns.get(role))]

    def named(roles: Sequence[str]) -> int:
        return sum(1 for role in roles if columns.get(role))

    # The way the customer's own choice points to, then the one closest to done.
    what, roles = min(ways, key=lambda way: (-named(way[1]), len(lacking(way[1]))))
    fields = ", ".join(labels[role] for role in lacking(roles))
    text = words["missing"].format(what=words[f"what_{what}"], fields=fields)
    return text if what in ("profit", "balance") else f"{text} {words['also']}"


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
    shown = table.header[:MAX_COLUMNS]
    head = "".join(f"<th>{_e(imp._clip(name, 40) or words['unnamed'])}</th>" for name in shown)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{_e(imp._clip(row[i], 40) if i < len(row) else '')}</td>"
            for i in range(len(shown))
        )
        + "</tr>"
        for row in table.samples
    )
    hidden = len(table.header) - len(shown)
    more = f"<p class='help'>{_e(words['more_columns'].format(n=hidden))}</p>" if hidden > 0 else ""
    return (
        f"<div class='tscroll'><table style='white-space:nowrap'><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>{more}"
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
    curve_labels = {"date": words["role_date"], "balance": words["role_balance"]}
    groups += (
        f"<fieldset class='map-group'><legend>{_e(words['curve_group'])}</legend>"
        f"<p class='help'>{_e(words['curve_help'])}</p><div class='form-grid'>"
        + "".join(
            _select(role, curve_labels[role], table, picked.get(role, ""), words)
            for role in CURVE_ROLES
        )
        + "</div></fieldset>"
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
