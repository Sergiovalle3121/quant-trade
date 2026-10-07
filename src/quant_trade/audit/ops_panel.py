"""Private owner views: approximate telemetry and explicitly recorded USD costs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from quant_trade.audit.ops import percentile_bucket, retention_status
from quant_trade.audit.pages import _e
from quant_trade.audit.store_ops import COST_CATEGORIES, OUTCOMES

COST_LABELS = {
    "infrastructure": "Infraestructura (incluye uso variable)",
    "payments": "Stripe, cambio e impuestos sobre comisiones",
    "acquisition": "Adquisición / campaña",
    "support": "Soporte observado",
}


def amount_cents(text: str) -> int:
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("invalid observed cost amount") from exc
    exponent = amount.as_tuple().exponent
    if (
        not amount.is_finite()
        or not 0 <= amount <= 10**10
        or not isinstance(exponent, int)
        or exponent < -2
    ):
        raise ValueError("invalid USD amount")
    return int(amount * 100)


def table(headers: list[str], rows: list[list[str]]) -> str:
    return (
        "<div style='overflow-x:auto'><table><thead><tr>"
        + "".join(f"<th>{_e(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)
        + "</tbody></table></div>"
    )


def operations_section(
    rows: list[dict[str, Any]],
    job: dict[str, Any] | None,
    *,
    enabled: bool,
    at: datetime,
    dropped: int = 0,
    flush_failed: bool = False,
) -> str:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["operation"], row["locale"])].append(row)
    cells = []
    for (operation, locale), values in sorted(groups.items()):
        successes = [r for r in values if r["outcome"] == "success"]
        cells.append(
            [
                operation,
                locale,
                *(
                    str(sum(r["count"] for r in values if r["outcome"] == kind))
                    for kind in OUTCOMES
                ),
                percentile_bucket(successes, 0.5),
                percentile_bucket(successes, 0.95),
            ]
        )
    status = retention_status(job, enabled=enabled, at=at)
    labels = {
        "disabled": "Automática apagada: requiere purga manual",
        "not_measured": "NOT_MEASURED: aún sin éxito registrado",
        "overdue": "Atención: más de 36 horas sin éxito",
        "failed": "Atención: último intento falló",
        "ok": "Último éxito dentro de 36 horas",
    }
    health = job or {}
    return (
        "<section id='operations'><h2 style='margin-top:40px'>Operación privada · 30 días</h2>"
        "<p>MEASURED · contadores agregados, sin archivos, direcciones "
        "ni identificadores de clientes. "
        "p50/p95 son límites superiores de histograma de solicitudes exitosas; no un tiempo "
        "exacto. Upload incluye cuerpo y espera; audit incluye importación y cálculo; "
        "queue mide espera; PDF incluye caché. Idioma es el observado, "
        "o ES antes de leer el formulario. "
        "El buffer se guarda cada 60 s: puede perderse al caer el proceso.</p>"
        + table(
            [
                "Operación",
                "Idioma",
                "Éxito",
                "Inválido",
                "Ocupado",
                "Error",
                "Denegado",
                "p50",
                "p95",
            ],
            cells,
        )
        + f"<p>Telemetría pendiente de reintento: {'sí' if flush_failed else 'no'}. "
        f"Eventos descartados en este proceso: {dropped}.</p>"
        + "<h3>Retención</h3>"
        + f"<p>{_e(labels[status])}</p>"
        + table(
            ["Intento", "Éxito", "Último resultado", "Purga del último intento"],
            [
                [
                    str(health.get("last_attempt_at") or "NOT_MEASURED"),
                    str(health.get("last_success_at") or "NOT_MEASURED"),
                    str(health.get("error_code") or "—"),
                    "NOT_MEASURED"
                    if health.get("error_code")
                    else str(health.get("deleted_count", "NOT_MEASURED")),
                ]
            ],
        )
        + "<p>Un aviso aquí no cambia las rutas de salud ni reinicia el servicio.</p></section>"
    )


def contribution(gross: int, refunds: int, costs: list[dict[str, Any]]) -> str:
    known = {r["category"] for r in costs}
    if known != set(COST_CATEGORIES):
        return "NOT_MEASURED: faltan categorías; cero debe registrarse explícitamente"
    total = sum(int(r["amount_usd_cents"]) for r in costs)
    result = gross - refunds - total
    margin = f"{Decimal(result) * 100 / Decimal(gross):.2f}%" if gross else "NOT_MEASURED"
    return f"DECLARED · USD {result / 100:.2f} · margen sobre cobros: {margin}"


def cost_notice(*, error: str = "", saved: bool = False) -> str:
    notice = "<p role='status'>Costo observado guardado.</p>" if saved else ""
    if error == "unavailable":
        notice += "<p role='alert'>No se pudo guardar el costo. Inténtalo de nuevo.</p>"
    elif error:
        notice += (
            "<p role='alert'>Revisa período, USD con hasta dos decimales y referencia interna.</p>"
        )
    return notice


def commercial_section(
    *,
    key: str,
    panel_path: str,
    start: str,
    end: str,
    counts: dict[str, int],
    costs: list[dict[str, Any]],
    x_start: str,
    x_counts: dict[str, int],
    x_costs: list[dict[str, Any]],
    error: str = "",
    saved: bool = False,
) -> str:
    notice = cost_notice(error=error, saved=saved)

    def cost_rows(values: list[dict[str, Any]]) -> list[list[str]]:
        return [
            [
                COST_LABELS[r["category"]],
                f"{r['amount_usd_cents'] / 100:.2f}",
                r["source_reference"],
                r["updated_at"],
            ]
            for r in values
        ]

    rows = [
        [
            "Total 30 días",
            start,
            end,
            f"{counts.get('gross_usd_cents', 0) / 100:.2f}",
            f"{counts.get('refund_usd_cents', 0) / 100:.2f}",
            contribution(
                counts.get("gross_usd_cents", 0), counts.get("refund_usd_cents", 0), costs
            ),
        ],
        [
            "Cohorte X 14 días",
            x_start,
            end,
            f"{x_counts['gross_usd_cents'] / 100:.2f}",
            f"{x_counts['refund_usd_cents'] / 100:.2f}",
            contribution(x_counts["gross_usd_cents"], x_counts["refund_usd_cents"], x_costs),
        ],
    ]
    options = "".join(f"<option value='{k}'>{_e(v)}</option>" for k, v in COST_LABELS.items())
    cohort = [
        [
            str(x_counts[k])
            for k in (
                "signups",
                "email_verified",
                "first_upload",
                "welcome",
                "buyers",
                "repeat_buyers",
                "deliveries",
            )
        ]
    ]
    return (
        "<section id='commercial'><h2 style='margin-top:40px'>Costos y contribución comercial</h2>"
        + notice
        + table(
            [
                "Período UTC",
                "Desde",
                "Hasta",
                "Cobro live USD · MEASURED",
                "Devolución USD · MEASURED",
                "Contribución / margen",
            ],
            rows,
        )
        + "<p>Cobros y devoluciones provienen del ledger de Rigor, no del payout bancario. "
        "Costos y contribución son DECLARED por el dueño, no auditados por Rigor. Se calculan "
        "solo cuando las cuatro categorías están registradas para el mismo período y ámbito; "
        "incluye el costo de uso de informes gratuitos y pagos en infraestructura. "
        "No se asigna un precio a CPU o tiempo. "
        "Conciliar facturas, impuestos y Stripe por separado.</p>"
        + "<h3>Cohorte de X · 14 días</h3><p>MEASURED · cuentas creadas en el período UTC "
        "con primera etiqueta "
        "x o x-*. Eventos hasta el cierre del período; cada cuenta cuenta una vez por etapa. "
        "Repetición exige más de una orden entregada; no incluye dobles cargos. "
        "Una cohorte reciente sigue incompleta. Sin etiqueta no se atribuye a X.</p>"
        + table(
            [
                "Cuentas",
                "Correo confirmado",
                "Primera carga",
                "Regalo entregado",
                "Compradores",
                "Compradores repetidos",
                "Órdenes entregadas",
            ],
            cohort,
        )
        + "<h3>Costos registrados · total 30 días</h3>"
        + table(["Categoría", "USD", "Referencia interna", "Actualizado"], cost_rows(costs))
        + "<h3>Costos asignados · cohorte X 14 días</h3>"
        + table(["Categoría", "USD", "Referencia interna", "Actualizado"], cost_rows(x_costs))
        + f"<form method='post' action='{_e(panel_path)}'>"
        + f"<input type='hidden' name='key' value='{_e(key)}'>"
        "<input type='hidden' name='action' value='cost_record'>"
        "<p>Registrar un total observado por categoría. Una corrección reemplaza ese total; "
        "no se suma por reenviar el formulario. Para X, asigna únicamente los costos "
        "de esa cohorte y documenta la asignación en tu registro contable. "
        "No subas facturas ni datos de clientes.</p>"
        "<label>Ámbito <select name='cost_scope'><option value='all'>Total</option>"
        "<option value='x'>Cohorte X</option></select></label>"
        + f"<label>Desde UTC <input type='date' name='cost_start' required value='{start}'></label>"
        + f"<label>Hasta UTC <input type='date' name='cost_end' required value='{end}'></label>"
        + f"<label>Categoría <select name='cost_category'>{options}</select></label>"
        + "<label>Importe USD <input name='cost_amount' inputmode='decimal' "
        "required maxlength='20' "
        "placeholder='0.00'></label><label>Referencia interna <input name='cost_reference' "
        "required maxlength='80' placeholder='FACTURA-2026-10'></label>"
        "<button class='btn btn-dark' type='submit'>Guardar costo observado</button>"
        "</form></section>"
    )
