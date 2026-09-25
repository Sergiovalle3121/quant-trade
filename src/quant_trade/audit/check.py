"""Check a report file: was it edited after Rigor produced it?

A buyer usually receives a Rigor report from the seller, as a PDF or as the
JSON result. Every file the service hands out has its SHA-256 recorded
(``Store.record_issued``). On this page anyone drops the file they were
given; the server hashes it as it streams in, keeps nothing, and says
whether those exact bytes came from Rigor, when, and for which class.

It says only that the file is unchanged. It never says the strategy is good,
and every text passes the profit-claim guard in both languages.
"""

from __future__ import annotations

import html
from typing import Any

from quant_trade.audit.store import IssuedFile

#: The largest file the page reads; a report PDF is far smaller.
MAX_CHECK_BYTES = 20 * 1024 * 1024
#: Checks per address and hour.
CHECKS_PER_HOUR_PER_IP = 60
#: The audit id the sample report's files are recorded under.
SAMPLE_AUDIT_ID = "sample"

_MONTHS = {
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}

COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Comprobar un informe",
        "title": "¿Este informe salió así de Rigor?",
        "lead": (
            "Si un vendedor te envió un informe de Rigor, súbelo aquí. Te decimos si el "
            "archivo es exactamente el que Rigor generó o si alguien lo cambió después."
        ),
        "file": "Informe que te enviaron (PDF o JSON)",
        "submit": "Comprobar",
        "found_title": "Este archivo no se editó",
        "found": (
            "Es idéntico, byte a byte, al {kind} que Rigor generó el {date} para un informe "
            "de clase {cls}."
        ),
        "found_no_class": "Es idéntico, byte a byte, al {kind} que Rigor generó el {date}.",
        "sample": "Es el informe de ejemplo de Rigor, sin cambios.",
        "public": "Ver su página pública",
        "missing_title": "Rigor no generó este archivo",
        "missing": (
            "No coincide con ningún archivo que Rigor haya entregado: puede haberse editado "
            "después o venir de otro sitio. Pide al vendedor el enlace a su página pública en "
            "Rigor, o el archivo tal como lo descargó."
        ),
        "scope": (
            "Esto solo dice si el archivo cambió desde que Rigor lo generó. No dice nada sobre "
            "si la estrategia funcionará."
        ),
        "no_file": "Elige el archivo del informe que quieres comprobar.",
        "too_large": "El archivo pasa de 20 MB; un informe de Rigor pesa mucho menos.",
        "again": "Comprobar otro archivo",
        "kinds": {"pdf": "PDF", "json": "archivo JSON"},
        "shows_title": "Cómo funciona",
        "shows": (
            (
                "Una huella del archivo",
                "Calculamos la huella SHA-256 del archivo; cambiar un solo carácter la cambia.",
            ),
            (
                "La comparamos con lo entregado",
                "Rigor guarda la huella de cada informe que entrega, nunca el archivo.",
            ),
            ("No guardamos tu archivo", "Se lee, se calcula la huella y se descarta."),
        ),
        "note": (
            "Un PDF impreso de nuevo, una captura o una copia editada nunca coinciden: "
            "compara el archivo tal como se descargó de Rigor."
        ),
    },
    "en": {
        "eyebrow": "Check a report",
        "title": "Did this report leave Rigor like this?",
        "lead": (
            "If a seller sent you a Rigor report, upload it here. We tell you whether the file "
            "is exactly the one Rigor produced or whether someone changed it afterwards."
        ),
        "file": "Report you were sent (PDF or JSON)",
        "submit": "Check",
        "found_title": "This file was not edited",
        "found": (
            "It is identical, byte for byte, to the {kind} Rigor produced on {date} for a "
            "class {cls} report."
        ),
        "found_no_class": "It is identical, byte for byte, to the {kind} Rigor produced on {date}.",
        "sample": "It is Rigor's sample report, unchanged.",
        "public": "See its public page",
        "missing_title": "Rigor did not produce this file",
        "missing": (
            "It matches no file Rigor has handed out: it may have been edited afterwards or "
            "come from elsewhere. Ask the seller for the link to its public page on Rigor, or "
            "for the file as they downloaded it."
        ),
        "scope": (
            "This only says whether the file changed since Rigor produced it. It says nothing "
            "about whether the strategy will work."
        ),
        "no_file": "Choose the report file you want to check.",
        "too_large": "The file is over 20 MB; a Rigor report is much smaller.",
        "again": "Check another file",
        "kinds": {"pdf": "PDF", "json": "JSON file"},
        "shows_title": "How it works",
        "shows": (
            (
                "A fingerprint of the file",
                "We compute the file's SHA-256 fingerprint; changing one character changes it.",
            ),
            (
                "We compare it with what was handed out",
                "Rigor keeps the fingerprint of every report it hands out, never the file.",
            ),
            ("Your file is not kept", "It is read, fingerprinted and discarded."),
        ),
        "note": (
            "A PDF printed again, a screenshot or an edited copy never matches: check the file "
            "as it was downloaded from Rigor."
        ),
    },
}

CHECK_CSS = (
    ".chk-grid{display:grid;gap:28px;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);"
    "align-items:start}"
    "@media (max-width:759px){.chk-grid{grid-template-columns:1fr}}"
    ".chk-form{display:grid;gap:16px}"
    ".chk-form input[type=file]{width:100%;max-width:100%}"
    ".chk-aside ol{margin:0;padding-left:1.2em;display:grid;gap:10px}"
    ".chk-aside li b{display:block}"
    ".chk-result{border:1px solid var(--border);border-radius:16px;padding:18px 20px;"
    "margin:0 0 18px;overflow-wrap:anywhere}"
    ".chk-result.ok{border-color:var(--pass,#1a7f4b)}"
    ".chk-result.bad{border-color:var(--fail,#b42318)}"
    ".chk-result h2{margin:0 0 8px}"
    ".chk-result code{font-size:.8rem;word-break:break-all}"
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _locale(locale: str) -> str:
    return "en" if locale == "en" else "es"


def _date(iso: str, locale: str) -> str:
    try:
        year, month, day = (int(part) for part in iso[:10].split("-"))
        return f"{day} {_MONTHS[locale][month - 1]} {year}"
    except (ValueError, IndexError):
        return iso[:10]


def check_path(locale: str) -> str:
    return "/check" if _locale(locale) == "en" else "/comprobar"


def check_form(locale: str, *, error: str = "") -> str:
    """The upload field, with how the check works beside it."""
    locale = _locale(locale)
    copy = COPY[locale]
    error_html = f"<div class='error' role='alert'>{_e(error)}</div>" if error else ""
    form = (
        f"<form class='chk-form' method='post' action='{check_path(locale)}' "
        f"enctype='multipart/form-data'>{error_html}"
        f"<input type='hidden' name='lang' value='{locale}'>"
        f"<div class='field'><label for='report'>{_e(copy['file'])}</label>"
        "<input id='report' type='file' name='report' required "
        "accept='.pdf,.json,application/pdf,application/json'></div>"
        f"<div><button class='btn btn-primary' type='submit'>{_e(copy['submit'])}</button></div>"
        "</form>"
    )
    steps = "".join(f"<li><b>{_e(k)}</b><span>{_e(v)}</span></li>" for k, v in copy["shows"])
    aside = (
        f"<aside class='chk-aside'><h2>{_e(copy['shows_title'])}</h2><ol>{steps}</ol>"
        f"<p>{_e(copy['note'])}</p></aside>"
    )
    return f"<div class='chk-grid'>{form}{aside}</div>"


def check_result(found: IssuedFile | None, digest: str, locale: str) -> str:
    """What the page says about one file, then the form again."""
    locale = _locale(locale)
    copy = COPY[locale]
    if found is None:
        box = (
            f"<div class='chk-result bad' role='status'><h2>{_e(copy['missing_title'])}</h2>"
            f"<p>{_e(copy['missing'])}</p>"
        )
    else:
        kind = copy["kinds"].get(found.kind, found.kind)
        date = _date(found.issued_at, locale)
        if found.audit_id == SAMPLE_AUDIT_ID:
            text = copy["sample"]
        elif found.overall_class:
            text = copy["found"].format(kind=kind, date=date, cls=found.overall_class)
        else:
            text = copy["found_no_class"].format(kind=kind, date=date)
        box = (
            f"<div class='chk-result ok' role='status'><h2>{_e(copy['found_title'])}</h2>"
            f"<p>{_e(text)}</p>"
        )
        if found.public_id:
            href = f"/v/{_e(found.public_id)}?lang={locale}"
            box += f"<p><a href='{href}'>{_e(copy['public'])}</a></p>"
    box += (
        f"<p class='muted'>{_e(copy['scope'])}</p>"
        f"<p class='muted'>SHA-256 <code>{_e(digest)}</code></p></div>"
    )
    return box + check_form(locale)


__all__ = [
    "CHECKS_PER_HOUR_PER_IP",
    "CHECK_CSS",
    "COPY",
    "MAX_CHECK_BYTES",
    "SAMPLE_AUDIT_ID",
    "check_form",
    "check_path",
    "check_result",
]
