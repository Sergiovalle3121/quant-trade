"""Two audits side by side: before and after a change, or two robots.

The customer pastes the links of two of their own reports; the server reads
each audit id and owner token from the link, checks both like any report
page does, and shows the class, the six dimensions, the key figures and the
stress tests in two columns. Only reports that are paid (or every report in
free mode) can be compared, so nothing locked is revealed. The page is
private (``noindex``), the links travel in a POST body, never in a URL, and
every text is fixed and passes the profit-claim guard.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.report import LABELS, SOURCE_NAMES, STATUS_TEXT, _dimension_title, _kpi_list
from quant_trade.audit.theme import class_ring
from quant_trade.audit.verdict import DIMENSION_ORDER

#: An audit id as the store issues it (hex) and a token (URL-safe base64).
_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_LINK_CHARS = 600

COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Comparar informes",
        "title": "Dos informes, lado a lado",
        "lead": (
            "Pega los enlaces de dos de tus informes (la dirección de la página del informe, "
            "con su token). Sirve para ver qué cambió entre dos versiones de una estrategia o "
            "entre dos robots. Solo se comparan informes completos."
        ),
        "link_a": "Enlace del primer informe",
        "link_b": "Enlace del segundo informe",
        "placeholder": "https://…/audits/…?token=…",
        "submit": "Comparar",
        "bad_link": "No reconocemos uno de los enlaces: copia la dirección completa del informe.",
        "not_found": "No encontramos uno de los informes, o su enlace no es el correcto.",
        "locked": (
            "Uno de los informes aún no está desbloqueado; solo se comparan informes completos."
        ),
        "same": "Pegaste el mismo informe dos veces.",
        "class": "Clase",
        "figure": "Cifra",
        "report_a": "Informe 1",
        "report_b": "Informe 2",
        "dimensions": "Dimensiones",
        "figures": "Cifras clave",
        "period": "Periodo",
        "source": "Archivo",
        "open": "Abrir informe",
        "again": "Comparar otros",
        "note": (
            "Cada informe se lee con sus propios archivos y declaraciones. Una diferencia de "
            "clase dice qué pruebas cambiaron, no que una versión vaya a funcionar mejor."
        ),
        "from_report": "Comparar con otro informe tuyo",
        "from_report_help": "Pega el enlace de otro informe tuyo para verlos lado a lado.",
        "shows_title": "Qué vas a ver",
        "shows": (
            ("La clase de cada informe", "A, B, C o D, una junto a la otra."),
            ("Las dimensiones que cambiaron", "Qué pruebas cambiaron de resultado."),
            ("Las cifras clave", "Cada cifra con su etiqueta de evidencia, lado a lado."),
        ),
    },
    "en": {
        "eyebrow": "Compare reports",
        "title": "Two reports, side by side",
        "lead": (
            "Paste the links of two of your reports (the address of the report page, with its "
            "token). It shows what changed between two versions of a strategy or between two "
            "robots. Only full reports can be compared."
        ),
        "link_a": "Link to the first report",
        "link_b": "Link to the second report",
        "placeholder": "https://…/audits/…?token=…",
        "submit": "Compare",
        "bad_link": "One of the links is not recognised: copy the report's whole address.",
        "not_found": "One of the reports was not found, or its link is not the right one.",
        "locked": "One of the reports is not unlocked yet; only full reports can be compared.",
        "same": "The same report was pasted twice.",
        "class": "Class",
        "figure": "Figure",
        "report_a": "Report 1",
        "report_b": "Report 2",
        "dimensions": "Dimensions",
        "figures": "Key figures",
        "period": "Period",
        "source": "File",
        "open": "Open report",
        "again": "Compare others",
        "note": (
            "Each report is read from its own files and declarations. A class difference says "
            "which tests changed, not that one version will work better."
        ),
        "from_report": "Compare with another of your reports",
        "from_report_help": "Paste the link of another of your reports to see them side by side.",
        "shows_title": "What you will see",
        "shows": (
            ("Each report's class", "A, B, C or D, next to each other."),
            ("The dimensions that changed", "Which tests changed result from one to the other."),
            ("The key figures", "Every figure with its evidence tag, side by side."),
        ),
    },
}

COMPARE_CSS = (
    ".cmp-form{display:grid;gap:14px;max-width:720px}"
    ".cmp-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:28px;"
    "align-items:start}"
    ".cmp-grid .cmp-form{background:#fff;border:1px solid var(--border);border-radius:24px;"
    "padding:clamp(22px,3vw,36px);box-shadow:0 30px 60px -40px rgba(0,0,0,.25)}"
    ".cmp-aside h2{font-size:.72rem;font-family:var(--mono);text-transform:uppercase;"
    "letter-spacing:.16em;color:var(--text-3);font-weight:500;margin:6px 0 18px}"
    ".cmp-aside ol{list-style:none;margin:0;padding:0;counter-reset:s}"
    ".cmp-aside li{counter-increment:s;display:grid;grid-template-columns:34px 1fr;gap:2px 12px;"
    "padding:16px 0;border-top:1px solid var(--border)}"
    ".cmp-aside li::before{content:counter(s,decimal-leading-zero);grid-row:span 2;"
    "font-family:var(--mono);font-size:.78rem;color:var(--text-3);padding-top:2px}"
    ".cmp-aside b{font-weight:600;letter-spacing:-.01em}"
    ".cmp-aside span{color:var(--text-2);font-size:.9rem}"
    ".cmp-aside p{font-size:.84rem;color:var(--text-3);margin:18px 0 0}"
    "@media (max-width:860px){.cmp-grid{grid-template-columns:minmax(0,1fr)}}"
    ".cmp-head{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;"
    "margin:0 0 22px}"
    ".cmp-card{border:1px solid var(--border);border-radius:18px;padding:18px;display:flex;"
    "gap:16px;align-items:center;background:#fff}"
    ".cmp-card .k{font-size:.8rem;color:var(--text-3);text-transform:uppercase;"
    "letter-spacing:.08em}.cmp-card p{margin:4px 0 0;font-size:.86rem;color:var(--text-2)}"
    "@media (max-width:620px){.cmp-head{grid-template-columns:minmax(0,1fr)}}"
    ".cmp td.diff{font-weight:600}"
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def parse_report_link(text: str) -> tuple[str, str] | None:
    """``(audit_id, token)`` from a report address, or None.

    Accepts the full URL or just its path and query, as a customer copies it
    from the address bar.
    """
    text = (text or "").strip()
    if not text or len(text) > MAX_LINK_CHARS:
        return None
    parts = urlsplit(
        text if "://" in text else "https://x" + ("" if text.startswith("/") else "/") + text
    )
    match = re.search(r"/audits/([^/?#]+)/?$", parts.path)
    tokens = parse_qs(parts.query).get("token", [])
    if not match or len(tokens) != 1:
        return None
    audit_id, token = match.group(1), tokens[0]
    if not _ID.match(audit_id) or not _TOKEN.match(token):
        return None
    return audit_id, token


def _status_cell(status: str, locale: str) -> str:
    text = STATUS_TEXT.get(locale, STATUS_TEXT["es"]).get(status, status)
    return f"<span class='badge {_e(status)}'>{_e(text)}</span>"


def _card(data: dict[str, Any], name: str, href: str, locale: str) -> str:
    copy = COPY[locale]
    inputs = data.get("inputs") or {}
    first = str(inputs.get("first_timestamp", ""))[:10]
    last = str(inputs.get("last_timestamp", ""))[:10]
    source = SOURCE_NAMES.get(
        str(inputs.get("source_format")), inputs.get("source_format") or "CSV"
    )
    overall = str(data["verdict"]["overall"])
    return (
        "<div class='cmp-card'>" + class_ring(overall) + f"<div><div class='k'>{_e(name)}</div>"
        f"<strong>{_e(copy['class'])} {_e(overall)}</strong>"
        f"<p>{_e(copy['period'])}: {_e(first)} → {_e(last)} · {_e(copy['source'])}: "
        f"{_e(source)}</p>"
        f"<p><a href='{_e(href)}'>{_e(copy['open'])}</a></p></div></div>"
    )


def comparison_body(
    a: dict[str, Any], b: dict[str, Any], *, href_a: str, href_b: str, locale: str
) -> str:
    """The comparison's main content for two stored results."""
    locale = "en" if locale == "en" else "es"
    copy = COPY[locale]
    labels = LABELS[locale]
    head = (
        "<div class='cmp-head'>"
        + _card(a, copy["report_a"], href_a, locale)
        + _card(b, copy["report_b"], href_b, locale)
        + "</div>"
    )
    dims_a = {d["name"]: d["status"] for d in a["verdict"]["dimensions"]}
    dims_b = {d["name"]: d["status"] for d in b["verdict"]["dimensions"]}
    dim_rows = "".join(
        f"<tr><td>{_e(_dimension_title(name, locale))}</td>"
        f"<td>{_status_cell(dims_a.get(name, 'NOT_MEASURED'), locale)}</td>"
        f"<td>{_status_cell(dims_b.get(name, 'NOT_MEASURED'), locale)}</td></tr>"
        for name in DIMENSION_ORDER
    )
    kpis_a = {label: shown for label, shown, _ in _kpi_list(a, labels)}
    kpis_b = {label: shown for label, shown, _ in _kpi_list(b, labels)}
    order = list(kpis_a) + [label for label in kpis_b if label not in kpis_a]
    figure_rows = "".join(
        f"<tr><td>{_e(label)}</td>"
        f"<td{' class=diff' if kpis_a.get(label) != kpis_b.get(label) else ''}>"
        f"{_e(kpis_a.get(label, '—'))}</td>"
        f"<td{' class=diff' if kpis_a.get(label) != kpis_b.get(label) else ''}>"
        f"{_e(kpis_b.get(label, '—'))}</td></tr>"
        for label in order
    )
    header = f"<tr><th></th><th>{_e(copy['report_a'])}</th><th>{_e(copy['report_b'])}</th></tr>"
    return (
        head
        + f"<h2>{_e(copy['dimensions'])}</h2><table class='cmp'>{header}{dim_rows}</table>"
        + f"<h2>{_e(copy['figures'])}</h2><table class='cmp'>{header}{figure_rows}</table>"
        + f"<p class='muted'>{_e(copy['note'])}</p>"
    )


def compare_form(locale: str, *, link_a: str = "", error: str = "") -> str:
    """The form with two link fields (``link_a`` prefilled from a report)."""
    locale = "en" if locale == "en" else "es"
    copy = COPY[locale]
    action = "/comparar" if locale == "es" else "/compare"
    error_html = f"<div class='error'>{_e(error)}</div>" if error else ""
    form = (
        f"<form class='cmp-form' method='post' action='{action}'>{error_html}"
        f"<input type='hidden' name='lang' value='{locale}'>"
        f"<div class='field'><label for='link_a'>{_e(copy['link_a'])}</label>"
        f"<input id='link_a' type='url' name='link_a' required maxlength='{MAX_LINK_CHARS}' "
        f"autocomplete='off' spellcheck='false' placeholder='{_e(copy['placeholder'])}' "
        f"value='{_e(link_a)}'></div>"
        f"<div class='field'><label for='link_b'>{_e(copy['link_b'])}</label>"
        f"<input id='link_b' type='url' name='link_b' required maxlength='{MAX_LINK_CHARS}' "
        f"autocomplete='off' spellcheck='false' placeholder='{_e(copy['placeholder'])}'></div>"
        f"<div><button class='btn btn-primary' type='submit'>{_e(copy['submit'])}</button></div>"
        "</form>"
    )
    shows = "".join(f"<li><b>{_e(k)}</b><span>{_e(v)}</span></li>" for k, v in copy["shows"])
    aside = (
        f"<aside class='cmp-aside'><h2>{_e(copy['shows_title'])}</h2><ol>{shows}</ol>"
        f"<p>{_e(copy['note'])}</p></aside>"
    )
    return f"<div class='cmp-grid'>{form}{aside}</div>"


def guard_page(page: str) -> str:
    """``page`` after the profit-claim guard; raises ``AuditReportError`` on a hit."""
    assert_report_clean(page, "")
    return page


__all__ = [
    "COMPARE_CSS",
    "COPY",
    "MAX_LINK_CHARS",
    "compare_form",
    "comparison_body",
    "guard_page",
    "parse_report_link",
]
