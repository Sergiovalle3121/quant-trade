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
from quant_trade.audit.theme import icon

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
        "drop_title": "Arrastra aquí el informe",
        "drop_sub": "o haz clic para elegirlo · hasta 20 MB",
        "found_title": "Este archivo no se editó",
        "found": (
            "Es idéntico, byte a byte, al {kind} que Rigor generó el {date} para un informe "
            "de clase {cls}."
        ),
        "found_no_class": "Es idéntico, byte a byte, al {kind} que Rigor generó el {date}.",
        "sample": "Es el informe de ejemplo de Rigor, sin cambios.",
        "public": "Ver su página pública",
        "missing_title": "Rigor no tiene registro de este archivo",
        "missing": (
            "No coincide con ningún archivo que Rigor tenga registrado. Puede haberse editado, "
            "venir de otro sitio o ser anterior al 25 de septiembre de 2026, cuando Rigor "
            "empezó a registrar los informes que entrega. Pide al vendedor el enlace a su "
            "página pública en Rigor, o que descargue el informe de nuevo y te lo envíe."
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
        "drop_title": "Drop the report here",
        "drop_sub": "or click to choose it · up to 20 MB",
        "found_title": "This file was not edited",
        "found": (
            "It is identical, byte for byte, to the {kind} Rigor produced on {date} for a "
            "class {cls} report."
        ),
        "found_no_class": "It is identical, byte for byte, to the {kind} Rigor produced on {date}.",
        "sample": "It is Rigor's sample report, unchanged.",
        "public": "See its public page",
        "missing_title": "Rigor has no record of this file",
        "missing": (
            "It matches no file Rigor has on record. It may have been edited, come from "
            "elsewhere, or predate 25 September 2026, when Rigor started recording the "
            "reports it hands out. Ask the seller for the link to its public page on Rigor, "
            "or to download the report again and send it to you."
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
    ".chk-grid{display:grid;gap:clamp(28px,5vw,72px);"
    "grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);align-items:start}"
    "@media (max-width:759px){.chk-grid{grid-template-columns:minmax(0,1fr)}}"
    ".chk-form .field{margin:0}"
    ".chk-form .btn{width:100%;justify-content:center;margin-top:20px}"
    ".chk-form .error{margin:0 0 18px}"
    ".chk-aside h2{font-size:1.25rem;letter-spacing:-.02em;margin:0 0 20px}"
    ".chk-steps{list-style:none;margin:0;padding:0;display:grid;gap:20px}"
    ".chk-steps li{display:grid;grid-template-columns:40px minmax(0,1fr);gap:14px;"
    "align-items:start}"
    ".chk-steps .icon{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;"
    "border:1px solid var(--border-2);background:var(--surface)}"
    ".chk-steps .icon svg{width:18px;height:18px}"
    ".chk-steps b{display:block;font-weight:600;letter-spacing:-.01em;margin:1px 0 2px}"
    ".chk-steps span{color:var(--text-2);font-size:.92rem;line-height:1.55}"
    ".chk-note{margin:24px 0 0;padding-top:18px;border-top:1px solid var(--border);"
    "color:var(--text-3);font-size:.86rem;line-height:1.55}"
    ".chk-result{--tone:var(--ok);display:grid;grid-template-columns:48px minmax(0,1fr);"
    "gap:18px;padding:clamp(20px,3vw,30px);margin:0 0 clamp(28px,4vw,44px);"
    "border-radius:var(--r-xl,22px);overflow-wrap:anywhere;"
    "border:1px solid color-mix(in srgb,var(--tone) 45%,transparent);"
    "background:color-mix(in srgb,var(--tone) 7%,var(--surface))}"
    ".chk-result.bad{--tone:var(--warn)}"
    ".chk-mark{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;"
    "color:var(--tone);background:color-mix(in srgb,var(--tone) 14%,transparent)}"
    ".chk-mark svg{width:24px;height:24px}"
    ".chk-result h2{margin:4px 0 6px;font-size:clamp(1.3rem,2.4vw,1.6rem);letter-spacing:-.03em}"
    ".chk-result .chk-text{margin:0;font-size:1.02rem;line-height:1.55}"
    ".chk-result .btn{margin-top:16px}"
    ".chk-scope{margin:16px 0 0;color:var(--text-2);font-size:.88rem;line-height:1.55}"
    ".chk-hash{margin:12px 0 0;display:flex;flex-wrap:wrap;gap:6px 10px;align-items:baseline;"
    "font-size:.78rem;color:var(--text-3)}"
    ".chk-hash code{font:500 .74rem var(--mono);word-break:break-all;color:var(--text-2)}"
    "@media (max-width:620px){.chk-result{grid-template-columns:minmax(0,1fr);gap:12px}"
    ".chk-mark{width:40px;height:40px}}"
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
    formats = "".join(f"<span>{kind}</span>" for kind in ("PDF", "JSON"))
    form = (
        f"<form class='panel chk-form' method='post' action='{check_path(locale)}' "
        f"enctype='multipart/form-data'>{error_html}"
        f"<input type='hidden' name='lang' value='{locale}'>"
        f"<div class='field'><label for='report'>{_e(copy['file'])}</label>"
        f"<div class='drop drop-main'><div class='icon'>{icon('upload')}</div>"
        f"<div class='drop-title'>{_e(copy['drop_title'])}</div>"
        f"<div class='drop-sub'>{_e(copy['drop_sub'])}</div>"
        f"<div class='formats'>{formats}</div><div class='drop-file' aria-live='polite'></div>"
        "<input id='report' type='file' name='report' required "
        "accept='.pdf,.json,application/pdf,application/json'></div></div>"
        f"<button class='btn btn-primary btn-lg' type='submit'>{_e(copy['submit'])}</button>"
        "</form>"
    )
    steps = "".join(
        f"<li><div class='icon'>{icon(mark)}</div><div><b>{_e(k)}</b><span>{_e(v)}</span></div>"
        "</li>"
        for mark, (k, v) in zip(("hash", "database", "lock"), copy["shows"], strict=True)
    )
    aside = (
        f"<aside class='chk-aside'><h2>{_e(copy['shows_title'])}</h2>"
        f"<ol class='chk-steps'>{steps}</ol><p class='chk-note'>{_e(copy['note'])}</p></aside>"
    )
    return f"<div class='chk-grid'>{form}{aside}</div>"


def check_result(found: IssuedFile | None, digest: str, locale: str) -> str:
    """What the page says about one file, then the form again."""
    locale = _locale(locale)
    copy = COPY[locale]
    link = ""
    if found is None:
        tone, mark, title, text = "bad", "alert", copy["missing_title"], copy["missing"]
    else:
        tone, mark, title = "ok", "check", copy["found_title"]
        kind = copy["kinds"].get(found.kind, found.kind)
        date = _date(found.issued_at, locale)
        if found.audit_id == SAMPLE_AUDIT_ID:
            text = copy["sample"]
        elif found.overall_class:
            text = copy["found"].format(kind=kind, date=date, cls=found.overall_class)
        else:
            text = copy["found_no_class"].format(kind=kind, date=date)
        if found.public_id:
            href = f"/v/{_e(found.public_id)}?lang={locale}"
            link = (
                f"<a class='btn btn-ghost btn-sm' href='{href}'>{_e(copy['public'])}"
                f"{icon('arrow')}</a>"
            )
    box = (
        f"<div class='chk-result {tone}' role='status'><div class='chk-mark'>{icon(mark)}</div>"
        f"<div><h2>{_e(title)}</h2><p class='chk-text'>{_e(text)}</p>{link}"
        f"<p class='chk-scope'>{_e(copy['scope'])}</p>"
        f"<p class='chk-hash'><span>SHA-256</span><code>{_e(digest)}</code></p></div></div>"
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
