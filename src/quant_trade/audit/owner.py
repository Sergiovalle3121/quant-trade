"""The owner panel: create and disable access codes from a browser.

It exists so the owner can sell a code by WhatsApp from a phone, without the
Railway CLI. It is off unless ``AUDIT_ADMIN_KEY`` is set (see
``settings.MIN_ADMIN_KEY_LENGTH``). The key travels only in POST bodies, never
in a URL, so it is not in access logs; every response is ``no-store`` and
``noindex``. A new code is shown once, like ``audit codes create``; the list
shows ids, notes and credits, never a code. The page is for the owner only,
so it is in Spanish.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from quant_trade.audit.pages import _e, _field, _page, _page_hero

if TYPE_CHECKING:
    from quant_trade.audit.store import AccessCodeRecord, RefusedPayment

PANEL_PATH = "/panel"
MAX_CREDITS = 100
MAX_NOTE_CHARS = 120
MAX_EXPIRES_DAYS = 3650
#: Wrong keys per address per hour before the panel answers 429.
MAX_FAILED_LOGINS_PER_HOUR = 5

TEXT: dict[str, str] = {
    "title": "Panel del dueño",
    "eyebrow": "Solo para ti",
    "login_lead": "Escribe tu clave de administrador para crear y ver códigos de acceso.",
    "key": "Clave de administrador",
    "enter": "Entrar",
    "wrong_key": "La clave no es correcta.",
    "too_many": "Demasiados intentos con una clave incorrecta. Espera una hora.",
    "create_title": "Crear un código",
    "credits": "Auditorías que desbloquea",
    "note": "Nota (quién lo compró y cómo pagó)",
    "expires": "Días hasta que caduque (vacío: no caduca)",
    "create": "Crear código",
    "new_code": "Código nuevo. Cópialo y envíalo ahora: no se puede volver a mostrar.",
    "invalid": "Revisa los datos: créditos entre 1 y 100, nota de hasta 120 caracteres y "
    "caducidad entre 1 y 3650 días.",
    "codes_title": "Códigos creados",
    "none": "Todavía no hay códigos.",
    "disable": "Desactivar",
    "disabled": "Código desactivado.",
    "not_found": "No hay un código activo con ese id.",
    "active": "activo",
    "off": "desactivado",
    "never": "nunca",
    "cols": "Id|Nota|Usados|Total|Creado|Caduca|Estado|",
    "refused_title": "Pagos con tarjeta que no abrieron un informe",
    "refused_lead": "Stripe cobró estos pagos, pero Rigor no abrió ningún informe. Búscalo "
    "en Stripe por el id de sesión y reembolsa, o crea un código para el cliente.",
    "refused_cols": "Fecha|Sesión de Stripe|Informe|Motivo",
    "reset_title": "Restablecer la contraseña de un cliente",
    "reset_lead": (
        "Crea un enlace de un solo uso (caduca en 24 horas) para un cliente que olvidó su "
        "contraseña. Antes, confirma que te escribe desde el correo de su cuenta."
    ),
    "reset_email": "Correo de la cuenta",
    "reset_create": "Crear enlace",
    "reset_link": "Enlace creado. Cópialo y envíalo ahora: no se puede volver a mostrar.",
    "reset_unknown": "No hay ninguna cuenta con ese correo.",
    "accounts": "Cuentas de clientes",
}

#: The panel is in Spanish; ``payments.refusal`` reasons are logged in English.
REFUSAL_REASONS: dict[str, str] = {
    "no Checkout session or no audit id": "sin sesión de Stripe o sin informe",
    "test payment for an audit not listed for testing": "pago de prueba",
    "unknown audit": "el informe no existe",
    "unknown plan": "plan desconocido",
    "no Rigor marker": "no es un enlace de Rigor (falta app=rigor)",
    "not USD": "no se cobró en dólares",
    "no amount": "sin monto",
    "below the plan price": "pagó menos que el precio",
}


def _key_field(key: str) -> str:
    return f"<input type='hidden' name='key' value='{_e(key)}'>"


def _shell(body: str) -> str:
    return _page(
        TEXT["title"],
        "es",
        _page_hero(TEXT["eyebrow"], TEXT["title"])
        + f"<div class='paper page-main'><div class='wrap wrap-narrow'>{body}</div></div>",
        solid_nav=True,
    )


def login_page(*, error: str = "") -> str:
    """The key form. ``error`` is one of the ``TEXT`` keys or empty."""
    err = f"<div class='error'>{_e(TEXT[error])}</div>" if error else ""
    return _shell(
        err
        + f"<p>{_e(TEXT['login_lead'])}</p>"
        + f"<form method='post' action='{PANEL_PATH}'>"
        + _field(
            TEXT["key"],
            "<input type='password' name='key' required autocomplete='current-password' "
            "maxlength='256'>",
        )
        + f"<button class='btn btn-dark' type='submit'>{_e(TEXT['enter'])}</button></form>"
    )


def _codes_table(key: str, codes: Sequence[AccessCodeRecord]) -> str:
    if not codes:
        return f"<p class='muted'>{_e(TEXT['none'])}</p>"
    head = "".join(f"<th>{_e(col)}</th>" for col in TEXT["cols"].split("|"))
    rows = []
    for record in reversed(codes):
        action = ""
        if not record.disabled:
            action = (
                f"<form method='post' action='{PANEL_PATH}'>{_key_field(key)}"
                "<input type='hidden' name='action' value='disable'>"
                f"<input type='hidden' name='code_id' value='{_e(record.id)}'>"
                f"<button class='btn btn-ghost' type='submit'>{_e(TEXT['disable'])}</button>"
                "</form>"
            )
        cells = (
            record.id,
            record.note,
            str(record.credits_used),
            str(record.credits_total),
            record.created_at[:10],
            (record.expires_at or TEXT["never"])[:10],
            TEXT["off"] if record.disabled else TEXT["active"],
        )
        tds = "".join(f"<td>{_e(c)}</td>" for c in cells)
        rows.append(f"<tr>{tds}<td>{action}</td></tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _refused_table(refused: Sequence[RefusedPayment]) -> str:
    if not refused:
        return ""
    head = "".join(f"<th>{_e(col)}</th>" for col in TEXT["refused_cols"].split("|"))
    rows = []
    for payment in refused:
        cells = (
            payment.created_at[:16].replace("T", " "),
            payment.session_id,
            payment.audit_id,
            REFUSAL_REASONS.get(payment.reason, payment.reason),
        )
        rows.append("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in cells) + "</tr>")
    return (
        f"<h2 style='margin-top:32px'>{_e(TEXT['refused_title'])}</h2>"
        f"<div class='error'>{_e(TEXT['refused_lead'])}</div>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def panel_page(
    *,
    key: str,
    codes: Sequence[AccessCodeRecord],
    refused: Sequence[RefusedPayment] = (),
    new_code: str = "",
    flash: str = "",
    error: str = "",
    reset_link: str = "",
    accounts: int = 0,
) -> str:
    """The panel after a correct key: the create form, a new code once, the list."""
    shown = ""
    if new_code:
        shown = (
            f"<div class='flash'>{_e(TEXT['new_code'])}</div>"
            f"<p><code style='font-size:1.4rem;user-select:all'>{_e(new_code)}</code></p>"
        )
    notice = f"<div class='flash'>{_e(TEXT[flash])}</div>" if flash else ""
    err = f"<div class='error'>{_e(TEXT[error])}</div>" if error else ""
    create = (
        f"<h2 style='margin-top:32px'>{_e(TEXT['create_title'])}</h2>"
        f"<form method='post' action='{PANEL_PATH}'>{_key_field(key)}"
        "<input type='hidden' name='action' value='create'>"
        + _field(
            TEXT["credits"],
            f"<input type='number' name='credits' value='1' min='1' max='{MAX_CREDITS}' required>",
        )
        + _field(
            TEXT["note"],
            f"<input type='text' name='note' maxlength='{MAX_NOTE_CHARS}' autocomplete='off'>",
        )
        + _field(
            TEXT["expires"],
            f"<input type='number' name='expires_days' min='1' max='{MAX_EXPIRES_DAYS}'>",
        )
        + f"<button class='btn btn-dark' type='submit'>{_e(TEXT['create'])}</button></form>"
    )
    listing = f"<h2 style='margin-top:40px'>{_e(TEXT['codes_title'])}</h2>"
    listing += _codes_table(key, codes)
    reset_shown = ""
    if reset_link:
        reset_shown = (
            f"<div class='flash'>{_e(TEXT['reset_link'])}</div>"
            f"<p><code style='user-select:all;word-break:break-all'>{_e(reset_link)}</code></p>"
        )
    reset = (
        f"<h2 style='margin-top:40px'>{_e(TEXT['reset_title'])}</h2>"
        f"<p class='muted'>{_e(TEXT['accounts'])}: {accounts}</p>"
        f"<p>{_e(TEXT['reset_lead'])}</p>"
        + reset_shown
        + f"<form method='post' action='{PANEL_PATH}'>{_key_field(key)}"
        "<input type='hidden' name='action' value='reset'>"
        + _field(
            TEXT["reset_email"],
            "<input type='email' name='email' maxlength='254' autocomplete='off' required>",
        )
        + f"<button class='btn btn-dark' type='submit'>{_e(TEXT['reset_create'])}</button></form>"
    )
    return _shell(err + shown + notice + _refused_table(refused) + create + listing + reset)


__all__ = [
    "MAX_CREDITS",
    "MAX_EXPIRES_DAYS",
    "MAX_FAILED_LOGINS_PER_HOUR",
    "MAX_NOTE_CHARS",
    "PANEL_PATH",
    "REFUSAL_REASONS",
    "TEXT",
    "login_page",
    "panel_page",
]
