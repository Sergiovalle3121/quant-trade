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

from quant_trade.audit.funnel import DIRECT, REF_DAYS, REF_TAGS, ref_label
from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import _e, _field, _page, _page_hero
from quant_trade.audit.settings import DEFAULT_PANEL_PATH

if TYPE_CHECKING:
    from quant_trade.audit.funnel import Funnel, FunnelCounts
    from quant_trade.audit.store import (
        AccessCodeRecord,
        CheckoutOrder,
        EmailDeliveryIssue,
        InstitutionalRequest,
        RefusedPayment,
        StripeRefundRecord,
    )

#: The default path; the service serves the panel at ``AUDIT_PANEL_PATH`` when set.
PANEL_PATH = DEFAULT_PANEL_PATH
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
    "public_card": "Tarjeta pública",
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
    "orders_title": "Compras con tarjeta registradas",
    "orders_lead": (
        "Una fila es una sesión pagada, no un informe ni un crédito. Un duplicado es otro cobro "
        "que requiere revisión de reembolso. Un cobro retenido no entregó el informe y también "
        "requiere revisión; registrar la revisión no ejecuta el reembolso. "
        "Solo cobros con entorno live confirmado entran en el embudo comercial."
    ),
    "orders_cols": "Fecha|Sesión|Informe|Plan|Entorno|Cobro registrado USD|Entrega|Resolución",
    "refunds_title": "Devoluciones observadas en Stripe",
    "refunds_lead": (
        "Cada fila es un reembolso, incluso parcial. Solo los vinculados a una orden de Rigor, "
        "en USD y con último estado conocido succeeded entran en la cifra del embudo. "
        "Un succeeded puede fallar después; revisa Stripe antes de informar ingresos finales."
    ),
    "refunds_cols": "Observado|Reembolso|Orden|Importe y moneda|Estado|Conciliación",
    "mail_title": "Avisos de compra por correo pendientes de atención",
    "mail_lead": (
        "Solo se muestran identificadores y estado, nunca direcciones ni contenido. "
        "Comprueba el transporte SMTP antes de reintentar. Un aviso puede haberse enviado "
        "antes de que un fallo impidiera registrar la entrega."
    ),
    "mail_counts": "Fallidos: {dead}. Atrasados más de 15 minutos: {overdue}.",
    "mail_cols": "Creado|Id de orden|Tipo|Estado|Intentos|Próximo intento|Acción",
    "mail_requeue": "Reintentar aviso",
    "mail_requeued": "Aviso reencolado. El trabajador intentará enviarlo.",
    "mail_not_requeued": (
        "No se reencoló: exige aviso fallido, orden live compatible y correo actual confirmado."
    ),
    "institutional_title": "Solicitudes institucionales",
    "institutional_lead": (
        "Solicitudes más recientes. Datos del solicitante: DECLARED. "
        "Fecha de recepción y seguimiento: MEASURED."
    ),
    "institutional_none": "Todavía no hay solicitudes institucionales.",
    "institutional_cols": (
        "Fecha (MEASURED)|Organización|Contacto|Tipo (DECLARED)|Frecuencia (DECLARED)|"
        "Años (DECLARED)|Benchmark (DECLARED)|Variantes (DECLARED)|Seguimiento"
    ),
    "institutional_contact": "Marcar contactado",
    "institutional_done": "Contactado",
    "institutional_contacted": "Solicitud marcada como contactada.",
    "institutional_not_found": "No hay una solicitud con ese id.",
    "institutional_hidden": "Texto omitido",
    "institutional_yes": "Sí",
    "institutional_no": "No",
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
    "funnel_title": "Embudo de ventas: últimos {days} días",
    "funnel_lead": (
        "De dónde vienen tus clientes. Publica cada enlace con su etiqueta al final, por "
        "ejemplo {example}, y aquí verás cuántas visitas, cuentas y pagos trae cada "
        "publicación. Sin etiqueta, o con una que no está en la lista, cuenta como «sin "
        "etiqueta»."
    ),
    "funnel_by_ref": "Por etiqueta",
    "funnel_by_ref_locale": "Por canal e idioma",
    "funnel_by_day": "Por día e idioma",
    "funnel_country": "Por país del comprador",
    "funnel_country_missing": (
        "Sólo las compras nuevas con dirección de facturación comprobada por Stripe tienen "
        "país observado. Las compras anteriores figuran NOT_MEASURED. Visitas, registros y "
        "cargas por país siguen NOT_MEASURED: no se deduce el país del idioma ni la IP."
    ),
    "funnel_country_cols": "País facturado|Compras live|Entregas|Cobro bruto USD",
    "funnel_contribution": (
        "Contribución = cobro bruto confirmado − devoluciones − comisiones de pago y cambio "
        "− impuestos sobre esas comisiones − costo variable de informes gratis y pagados "
        "− infraestructura − soporte − adquisición. NOT_MEASURED hasta registrar esos costos "
        "observados por cohorte; el saldo tras devoluciones no es beneficio ni ingreso neto."
    ),
    "funnel_empty": "Todavía no hay nada que contar en estos días.",
    "funnel_ref_cols": (
        "Etiqueta|Qué es|Visitas estimadas|Cuentas|Correos confirmados|Cargas guardadas|"
        "Informe gratis|Vistas previas|Invitaciones aceptadas|Sesiones Checkout creadas|"
        "Compras confirmadas|Cuentas con primera compra|Más compras de la cuenta|"
        "Compras live entregadas|Derechos vendidos|"
        "Créditos regalados|Créditos canjeados|Cobro bruto USD|Devoluciones USD registradas|"
        "Saldo de cobros USD tras devoluciones registradas|Contribución USD"
    ),
    "funnel_day_cols": (
        "Día|Idioma|Visitas estimadas|Cuentas|Correos confirmados|Cargas guardadas|"
        "Informe gratis|Vistas previas|Invitaciones aceptadas|Sesiones Checkout creadas|"
        "Compras confirmadas|Cuentas con primera compra|Más compras de la cuenta|"
        "Compras live entregadas|Derechos vendidos|"
        "Créditos regalados|Créditos canjeados|Cobro bruto USD|Devoluciones USD registradas|"
        "Saldo de cobros USD tras devoluciones registradas|Contribución USD"
    ),
    "funnel_ref_locale_cols": (
        "Etiqueta|Idioma|Visitas estimadas|Cuentas|Correos confirmados|Cargas guardadas|"
        "Informe gratis|Vistas previas|Invitaciones aceptadas|Sesiones Checkout creadas|"
        "Compras confirmadas|Cuentas con primera compra|Más compras de la cuenta|"
        "Compras live entregadas|Derechos vendidos|"
        "Créditos regalados|Créditos canjeados|Cobro bruto USD|Devoluciones USD registradas|"
        "Saldo de cobros USD tras devoluciones registradas|Contribución USD"
    ),
    "funnel_total": "Total",
    "funnel_anon": "Vistas previas sin cuenta",
    "funnel_anon_cols": (
        "Etiqueta|Vistas previas sin cuenta|Pasaron después a una cuenta (registro o entrada)"
    ),
    "funnel_anon_note": (
        "Subidas sin cuenta que mostraron la clase y las banderas rojas (AUDIT_ANON_PREVIEW), "
        "por la etiqueta con la que llegó el navegador, y cuántas de ellas quedaron después en "
        "una cuenta al registrarse o entrar desde el informe. Las dos cifras se cuentan por "
        "su propio día, así que en una ventana pueden no coincidir."
    ),
    "funnel_direct": "sin etiqueta",
    "funnel_tags": "Etiquetas que cuentan",
    "funnel_limits": (
        "Las visitas son de la página principal y de las páginas de cada caso, sin robots ni "
        "vistas previas de enlaces; solo se guarda un contador por día, idioma y etiqueta, sin "
        "dirección ni identificador de navegador en la base de visitas. La etiqueta se recuerda "
        "{ref_days} días en el navegador y queda "
        "en la cuenta si se crea. Los pagos e informes se cuentan por el idioma de la cuenta; "
        "sin cuenta aparecen con «-». Las visitas son navegadores observados, no personas únicas. "
        "El cobro bruto proviene de sesiones live confirmadas en USD antes de devoluciones, "
        "comisiones e impuestos; no es ingreso neto ni dinero recibido en el banco. "
        "Las devoluciones son sólo reembolsos enlazados y en USD cuyo último estado conocido "
        "es succeeded, fechados cuando Rigor los observó; un fallo posterior puede corregirlos. "
        "El saldo mostrado es la resta de estas dos cifras, no dinero recibido en el banco "
        "ni beneficio. No incluye reembolsos sin enlace, otras monedas, comisiones, FX, "
        "impuestos ni pagos a cuenta bancaria; las devoluciones anteriores a este registro "
        "también requieren conciliación en Stripe. Sesiones test o de modo desconocido "
        "se muestran arriba para revisión pero se excluyen del embudo. "
        "La cuenta asociada pertenece al informe y no identifica al titular de la tarjeta. "
        "Los códigos manuales no cuentan como compras sin cobro verificado. "
        "Los correos confirmados son los que aún coinciden con la cuenta; las cargas son informes "
        "importados y guardados, no intentos fallidos. Una invitación aceptada es una cuenta "
        "creada con enlace válido, no un premio. Checkout cuenta sesiones con URL creada, "
        "no visitas a Stripe ni cargos; incluye test y live. Las entregas son órdenes live "
        "marcadas entregadas, no todos los informes gratuitos ni canjes."
    ),
}

LOCALE_NAMES: dict[str, str] = {"es": "español", "en": "inglés", "pt": "portugués", "-": "-"}

INSTITUTIONAL_TYPES: dict[str, str] = {
    "signal": "Señal",
    "model_portfolio": "Cartera modelo",
    "fund": "Fondo",
    "ea": "EA",
}
INSTITUTIONAL_FREQUENCIES: dict[str, str] = {
    "daily": "Diaria",
    "weekly": "Semanal",
    "monthly": "Mensual",
}

#: The panel is in Spanish; ``payments.refusal`` reasons are logged in English.
REFUSAL_REASONS: dict[str, str] = {
    "no Checkout session or no audit id": "sin sesión de Stripe o sin informe",
    "test payment for an audit not listed for testing": "pago de prueba",
    "payment mode mismatch": "entorno de pago incorrecto",
    "unknown audit": "el informe no existe",
    "unknown plan": "plan desconocido",
    "no Rigor marker": "no es un enlace de Rigor (falta app=rigor)",
    "not USD": "no se cobró en dólares",
    "no amount": "sin monto",
    "below the plan price": "pagó menos que el precio",
    "unknown order": "la orden no existe",
    "order mismatch": "la sesión no coincide con la orden",
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


def login_page(*, error: str = "", panel_path: str = PANEL_PATH) -> str:
    """The key form. ``error`` is one of the ``TEXT`` keys or empty."""
    err = f"<div class='error'>{_e(TEXT[error])}</div>" if error else ""
    return _shell(
        err
        + f"<p>{_e(TEXT['login_lead'])}</p>"
        + f"<form method='post' action='{_e(panel_path)}'>"
        + _field(
            TEXT["key"],
            "<input type='password' name='key' required autocomplete='current-password' "
            "maxlength='256'>",
        )
        + f"<button class='btn btn-dark' type='submit'>{_e(TEXT['enter'])}</button></form>"
    )


def _codes_table(key: str, codes: Sequence[AccessCodeRecord], panel_path: str = PANEL_PATH) -> str:
    if not codes:
        return f"<p class='muted'>{_e(TEXT['none'])}</p>"
    head = "".join(f"<th>{_e(col)}</th>" for col in TEXT["cols"].split("|"))
    rows = []
    for record in reversed(codes):
        action = ""
        if not record.disabled:
            action = (
                f"<form method='post' action='{_e(panel_path)}'>{_key_field(key)}"
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


def _institutional_table(
    key: str, requests: Sequence[InstitutionalRequest], panel_path: str = PANEL_PATH
) -> str:
    """Private contact details and declared inputs; never render the free text or findings."""
    intro = (
        f"<h2 style='margin-top:32px'>{_e(TEXT['institutional_title'])}</h2>"
        f"<p class='muted'>{_e(TEXT['institutional_lead'])}</p>"
    )
    if not requests:
        return intro + f"<p class='muted'>{_e(TEXT['institutional_none'])}</p>"

    def safe_text(value: str) -> str:
        # Intake validates these fields too; old/imported rows must remain safe to render.
        return _e(TEXT["institutional_hidden"] if find_claims(value) else value)

    head = "".join(f"<th>{_e(col)}</th>" for col in TEXT["institutional_cols"].split("|"))
    rows = []
    for record in requests:
        contact = f"{safe_text(record.name)}<br>{safe_text(record.email)}"
        cells = (
            safe_text(record.created_at[:10]),
            safe_text(record.organization),
            contact,
            _e(INSTITUTIONAL_TYPES.get(record.strategy_type, "—")),
            _e(INSTITUTIONAL_FREQUENCIES.get(record.frequency, "—")),
            safe_text(record.history_years),
            _e(TEXT["institutional_yes"] if record.has_benchmark else TEXT["institutional_no"]),
            _e(str(record.variants)),
        )
        if record.contacted_at:
            action = (
                f"{_e(TEXT['institutional_done'])} · {safe_text(record.contacted_at[:10])} "
                "(MEASURED)"
            )
        else:
            action = (
                f"<form method='post' action='{_e(panel_path)}'>{_key_field(key)}"
                "<input type='hidden' name='action' value='institutional_contacted'>"
                f"<input type='hidden' name='request_id' value='{_e(record.id)}'>"
                f"<button class='btn btn-ghost' type='submit'>"
                f"{_e(TEXT['institutional_contact'])}</button></form>"
            )
        cells_html = "".join(f"<td>{cell}</td>" for cell in cells)
        rows.append(f"<tr>{cells_html}<td>{action}</td></tr>")
    return (
        intro + "<div style='overflow-x:auto'><table id='institutional-requests'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


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


def _orders_table(orders: Sequence[CheckoutOrder]) -> str:
    if not orders:
        return ""
    rows: list[list[str]] = []
    for order in orders:
        if order.status not in ("delivered", "duplicate", "paid_review"):
            continue
        cells = (
            order.confirmed_at[:16].replace("T", " "),
            order.session_id,
            order.audit_id,
            order.plan,
            (
                "live"
                if order.livemode is True
                else "test"
                if order.livemode is False
                else "no medido"
            ),
            f"{order.paid_amount_cents / 100:.2f}",
            (
                "entregado"
                if order.status == "delivered"
                else "cargo duplicado"
                if order.status == "duplicate"
                else "cobrado; entrega retenida"
            ),
            (
                "revisar reembolso manualmente"
                if order.resolution == "manual_refund_review"
                else "sesión original conciliada"
                if order.resolution == "legacy_reconciled"
                else order.resolution or "-"
            ),
        )
        rows.append(list(cells))
    if not rows:
        return ""
    return (
        f"<h2 style='margin-top:32px'>{_e(TEXT['orders_title'])}</h2>"
        f"<p class='muted'>{_e(TEXT['orders_lead'])}</p>" + _table(TEXT["orders_cols"], rows)
    )


def _refunds_table(refunds: Sequence[StripeRefundRecord]) -> str:
    if not refunds:
        return ""
    rows: list[list[str]] = []
    for refund in refunds:
        amount = (
            f"{refund.amount_minor / 100:.2f} USD"
            if refund.currency == "usd"
            else f"{refund.amount_minor} unidades menores {refund.currency.upper()}"
        )
        rows.append(
            [
                refund.last_seen_at[:16].replace("T", " "),
                refund.refund_id,
                refund.order_id or "-",
                amount,
                refund.status,
                "enlazado" if refund.order_id else "sin enlace; revisar",
            ]
        )
    return (
        f"<h2 style='margin-top:32px'>{_e(TEXT['refunds_title'])}</h2>"
        f"<p class='muted'>{_e(TEXT['refunds_lead'])}</p>" + _table(TEXT["refunds_cols"], rows)
    )


def _mail_issues_table(
    key: str,
    issues: Sequence[EmailDeliveryIssue],
    counts: dict[str, int],
    panel_path: str = PANEL_PATH,
) -> str:
    rows = []
    for issue in issues:
        action = "-"
        if issue.status == "dead":
            action = (
                f"<form method='post' action='{_e(panel_path)}'>{_key_field(key)}"
                "<input type='hidden' name='action' value='mail_requeue'>"
                f"<input type='hidden' name='mail_id' value='{_e(issue.id)}'>"
                f"<button class='btn btn-ghost' type='submit'>{_e(TEXT['mail_requeue'])}</button>"
                "</form>"
            )
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{_e(value)}</td>"
                for value in (
                    issue.created_at[:16].replace("T", " "),
                    issue.id,
                    issue.kind,
                    issue.status,
                    str(issue.attempts),
                    issue.next_attempt_at[:16].replace("T", " "),
                )
            )
            + f"<td>{action}</td></tr>"
        )
    head = "".join(f"<th>{_e(col)}</th>" for col in TEXT["mail_cols"].split("|"))
    table = (
        "<div style='overflow-x:auto'><table><thead><tr>"
        + head
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        if rows
        else ""
    )
    return (
        f"<h2 style='margin-top:32px'>{_e(TEXT['mail_title'])}</h2>"
        f"<p class='muted'>{_e(TEXT['mail_lead'])}</p>"
        f"<p>{_e(TEXT['mail_counts'].format(**counts))}</p>" + table
    )


def _counts_cells(counts: FunnelCounts) -> list[str]:
    c = counts.counts
    return [
        str(c["visits"]),
        str(c["signups"]),
        str(c["email_verified"]),
        str(c["uploads"]),
        str(c["welcome"]),
        str(c["previews"]),
        str(c["referrals_accepted"]),
        str(c["checkout_started"]),
        str(c["purchases"]),
        str(c["buyers"]),
        str(c["repeat_purchases"]),
        str(c["deliveries"]),
        str(c["rights_sold"]),
        str(c["gift_credits"]),
        str(c["credit_used"]),
        f"{c['gross_usd_cents'] / 100:.2f}",
        f"{c['refund_usd_cents'] / 100:.2f}",
        f"{(c['gross_usd_cents'] - c['refund_usd_cents']) / 100:.2f}",
        "NOT_MEASURED",
    ]


def _table(cols: str, rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_e(col)}</th>" for col in cols.split("|"))
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in rows)
    return (
        "<div style='overflow-x:auto'>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def funnel_section(
    funnel: Funnel,
    *,
    days: int,
    example: str,
    country_rows: Sequence[tuple[str, int, int, int]] = (),
    anon_previews: bool = False,
) -> str:
    """Visits, accounts, free reports, previews and payments by tag and by day.

    ``anon_previews`` (``AUDIT_ANON_PREVIEW`` on) adds the previews uploaded
    without an account and how many went on an account afterwards.
    """
    title = TEXT["funnel_title"].format(days=days)
    lead = TEXT["funnel_lead"].format(example=example)
    out = f"<h2 style='margin-top:40px'>{_e(title)}</h2><p>{_e(lead)}</p>"
    if not funnel.by_ref:
        out += f"<p class='muted'>{_e(TEXT['funnel_empty'])}</p>"
    else:
        ordered = sorted(
            funnel.by_ref.items(),
            key=lambda item: (
                -item[1].paid,
                -item[1].counts["signups"],
                -item[1].counts["visits"],
                item[0],
            ),
        )
        ref_rows = [
            [
                TEXT["funnel_direct"] if ref == DIRECT else ref,
                ref_label(ref),
                *_counts_cells(counts),
            ]
            for ref, counts in ordered
        ]
        ref_rows.append([TEXT["funnel_total"], "", *_counts_cells(funnel.total)])
        ref_locale_rows = [
            [
                TEXT["funnel_direct"] if ref == DIRECT else ref,
                LOCALE_NAMES.get(locale, locale),
                *_counts_cells(counts),
            ]
            for (ref, locale), counts in sorted(
                funnel.by_ref_locale.items(),
                key=lambda item: (
                    -item[1].paid,
                    -item[1].counts["signups"],
                    -item[1].counts["visits"],
                    item[0],
                ),
            )
        ]
        day_rows = [
            [day, LOCALE_NAMES.get(locale, locale), *_counts_cells(counts)]
            for (day, locale), counts in sorted(
                funnel.by_day.items(), key=lambda item: (item[0][0], item[0][1]), reverse=True
            )
        ]
        out += (
            f"<h3>{_e(TEXT['funnel_by_ref'])}</h3>"
            + _table(TEXT["funnel_ref_cols"], ref_rows)
            + f"<h3>{_e(TEXT['funnel_by_ref_locale'])}</h3>"
            + _table(TEXT["funnel_ref_locale_cols"], ref_locale_rows)
            + f"<h3>{_e(TEXT['funnel_by_day'])}</h3>"
            + _table(TEXT["funnel_day_cols"], day_rows)
        )
    tags = ", ".join(f"{tag} ({label})" for tag, label in REF_TAGS.items()) + (
        ". Además, cualquier etiqueta de campaña por comunidad: plataforma (dc, tg, rd, fo,"
        " fb, yt, nl, ev, x, tv, li, dir, ph, hn), mercado opcional de dos letras y número"
        " de 2 o 3 cifras, como dc-us-103, tg-mx-161 o dir-04."
    )
    if anon_previews:
        anon_rows = [
            [
                TEXT["funnel_direct"] if ref == DIRECT else ref,
                str(counts.counts["anon_previews"]),
                str(counts.counts["anon_linked"]),
            ]
            for ref, counts in sorted(funnel.by_ref.items())
            if counts.counts["anon_previews"] or counts.counts["anon_linked"]
        ]
        anon_rows.append(
            [
                TEXT["funnel_total"],
                str(funnel.total.counts["anon_previews"]),
                str(funnel.total.counts["anon_linked"]),
            ]
        )
        out += (
            f"<h3>{_e(TEXT['funnel_anon'])}</h3>"
            f"<p class='muted'>{_e(TEXT['funnel_anon_note'])}</p>"
            + _table(TEXT["funnel_anon_cols"], anon_rows)
        )
    country_table = (
        _table(
            TEXT["funnel_country_cols"],
            [
                [country, str(purchases), str(deliveries), f"{gross / 100:.2f}"]
                for country, purchases, deliveries, gross in country_rows
            ],
        )
        if country_rows
        else ""
    )
    out += (
        f"<h3>{_e(TEXT['funnel_country'])}</h3>"
        f"<p class='muted'>{_e(TEXT['funnel_country_missing'])}</p>"
        + country_table
        + f"<p class='muted'>{_e(TEXT['funnel_contribution'])}</p>"
        f"<details><summary>{_e(TEXT['funnel_tags'])}</summary><p class='muted'>{_e(tags)}</p>"
        "</details>"
        f"<p class='muted'>{_e(TEXT['funnel_limits'].format(ref_days=REF_DAYS))}</p>"
    )
    return out


def panel_page(
    *,
    key: str,
    codes: Sequence[AccessCodeRecord],
    refused: Sequence[RefusedPayment] = (),
    orders: Sequence[CheckoutOrder] = (),
    refunds: Sequence[StripeRefundRecord] = (),
    mail_issues: Sequence[EmailDeliveryIssue] = (),
    mail_warning_counts: dict[str, int] | None = None,
    institutional_requests: Sequence[InstitutionalRequest] = (),
    new_code: str = "",
    flash: str = "",
    error: str = "",
    reset_link: str = "",
    accounts: int = 0,
    funnel: str = "",
    panel_path: str = PANEL_PATH,
    observability: str = "",
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
        f"<form method='post' action='{_e(panel_path)}'>{_key_field(key)}"
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
    listing += _codes_table(key, codes, panel_path)
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
        + f"<form method='post' action='{_e(panel_path)}'>{_key_field(key)}"
        "<input type='hidden' name='action' value='reset'>"
        + _field(
            TEXT["reset_email"],
            "<input type='email' name='email' maxlength='254' autocomplete='off' required>",
        )
        + f"<button class='btn btn-dark' type='submit'>{_e(TEXT['reset_create'])}</button></form>"
    )
    return _shell(
        err
        + shown
        + notice
        + f"<form method='post' action='{_e(panel_path)}'>{_key_field(key)}"
        + "<input type='hidden' name='action' value='public_card'>"
        + f"<button class='btn btn-ghost' type='submit'>{_e(TEXT['public_card'])}</button></form>"
        + _institutional_table(key, institutional_requests, panel_path)
        + _refused_table(refused)
        + _orders_table(orders)
        + _refunds_table(refunds)
        + _mail_issues_table(
            key, mail_issues, mail_warning_counts or {"dead": 0, "overdue": 0}, panel_path
        )
        + funnel
        + observability
        + create
        + listing
        + reset
    )


__all__ = [
    "MAX_CREDITS",
    "MAX_EXPIRES_DAYS",
    "MAX_FAILED_LOGINS_PER_HOUR",
    "MAX_NOTE_CHARS",
    "PANEL_PATH",
    "REFUSAL_REASONS",
    "LOCALE_NAMES",
    "TEXT",
    "funnel_section",
    "login_page",
    "panel_page",
]
