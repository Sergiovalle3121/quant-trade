"""Render an ``AuditResult`` as JSON and as a self-contained HTML page.

The JSON is the record: canonical, NaN-free, hashed, and the thing a client
can hand to a third party together with the file digests to prove what was
audited. The HTML is the same numbers with labels, an evidence badge on every
value, and a fixed disclaimer. The client's free-text description never
reaches the HTML (only its length and hash do); it lives in the JSON, where
it is theirs.

Both renderings pass the profit-claim guard before they are returned. A
report that fails the guard is a bug in this module, not a report.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from quant_trade.audit import charts
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import localize
from quant_trade.audit.importers import lead_number
from quant_trade.audit.legal import legal_links_html
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.prop_presets import preset_label
from quant_trade.audit.redflags import flag_title
from quant_trade.audit.schema import AuditResult, Dimension
from quant_trade.audit.seo import BRAND, TAGLINE, private_meta
from quant_trade.audit.theme import (
    CLASS_COLOURS,
    SCRIPT_TAG,
    STYLE,
    aurora,
    class_ring,
    grid_bg,
    icon,
    logo,
)
from quant_trade.audit.verdict import DIMENSION_ORDER, NOT_MEASURED_ES, meaning, summary
from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    pretty_dumps,
    sha256_of_text,
)

WATERMARK_TEXT = {"es": "VISTA PREVIA — SIN PAGAR", "en": "PREVIEW — UNPAID"}

DISCLAIMER = {
    "es": (
        "Esta auditoría es una herramienta de investigación estadística aplicada a datos "
        "aportados por el cliente. No es asesoría de inversión, no ejecuta operaciones, no "
        "custodia fondos ni claves, y no predice resultados futuros. Cada valor lleva su "
        "etiqueta de evidencia: MEASURED se calculó desde el archivo, DECLARED lo afirmó el "
        "cliente y no se pudo verificar, NOT_MEASURED no se pudo calcular con lo aportado."
    ),
    "en": (
        "This audit is a statistical research tool applied to client-supplied data. It is "
        "not investment advice, executes no trades, holds no funds or keys, and does not "
        "predict future results. Every value carries its evidence tag: MEASURED was computed "
        "from the file, DECLARED was asserted by the client and could not be verified, "
        "NOT_MEASURED could not be computed from what was supplied."
    ),
}

LABELS: dict[str, dict[str, str]] = {
    "es": {
        "title": f"{BRAND} · Auditoría de backtest",
        "generated": "Generada",
        "audit_id": "Identificador",
        "inputs": "Archivos auditados (sha256)",
        "verdict": "Veredicto",
        "dimensions": "Dimensiones",
        "dimension": "Dimensión",
        "status": "Estado",
        "reasons": "Razones",
        "performance": "Rendimiento anualizado",
        "significance": "Significación estadística",
        "multiplicity": "Multiplicidad (número de intentos)",
        "sensitivity": "Sensibilidad del Sharpe deflactado al número de intentos",
        "bootstrap": "Bootstrap estacionario (por período)",
        "holdout": "Fuera de muestra declarado",
        "costs": "Costes de operación",
        "benchmark": "Benchmark aportado",
        "cscv": "Sobreajuste por validación cruzada combinatoria (CSCV)",
        "subperiods": "Subperíodos (años naturales)",
        "rolling": "Ventanas móviles",
        "red_flags": "Banderas rojas",
        "not_measured": "No medido",
        "declared": "Declarado por el cliente",
        "metric": "Métrica",
        "value": "Valor",
        "evidence": "Evidencia",
        "note": "Nota",
        "none": "ninguna",
        "trials": "intentos",
        "expected_max": "Sharpe máximo esperado sin habilidad",
        "dsr": "Sharpe deflactado (DSR)",
        "multiplier": "Multiplicador",
        "bps": "pb por lado",
        "gross": "Bruto",
        "cost": "Coste",
        "net": "Neto",
        "win_rate": "Aciertos",
        "trades": "Operaciones",
        "in_sample": "En muestra",
        "out_of_sample": "Fuera de muestra",
        "year": "Año",
        "return": "Retorno",
        "max_drawdown": "Drawdown máximo",
        "window": "Ventana",
        "min_return": "Retorno mínimo",
        "min_drawdown": "Drawdown mínimo",
        "share_negative": "Fracción negativa",
        "code": "Código",
        "severity": "Severidad",
        "detail": "Detalle",
        "warnings": "Avisos de lectura",
        "client_text": "Descripción del cliente",
        "client_text_none": "No se escribió una descripción de la estrategia.",
        "chars": "{n} caracteres",
        "client_text_note": (
            "La descripción no se reproduce en este informe; consta en el JSON. Expresiones de "
            "promesa de resultados detectadas en ella"
        ),
        "seal": "Sello del holdout declarado",
        "pay": "Pagar con tarjeta",
        "pay_pack": "Comprar el paquete de 3 (USD {price:.0f})",
        "pay_secure": (
            "Pago seguro con Stripe. Ves el informe completo en cuanto se confirma el pago; "
            "nosotros no vemos ni guardamos los datos de tu tarjeta."
        ),
        "buy_code_alt": "¿Prefieres pagar por transferencia? Pide un código aquí",
        "pack_left": (
            "Te quedan {n} informes de tu paquete. Para usarlos, escribe este código al "
            "desbloquear tus próximos informes:"
        ),
        "pack_used": "Ya usaste los informes de tu paquete (código {code}).",
        "pack_keep": "Guárdalo: también aparece aquí cada vez que abres este informe.",
        "locked": "Sección disponible en el informe completo",
        "disclaimer": "Aviso",
        "json_sha": "sha256 del JSON de la auditoría",
        "thresholds": "Umbrales aplicados",
        "print": "Imprimir / guardar PDF",
        "pdf": "Descargar PDF",
        "obs": "observaciones",
        "source_equity": "curva de equity",
        "source_returns": "serie de retornos",
        "variance_policy": (
            "Varianza usada: la mayor entre la observada en las variantes que subiste y la "
            "que produce el error de muestreo."
        ),
        "pdf_long": "Descargar el informe en PDF",
        "switch": "English",
        "yes": "sí",
        "no": "no",
        "redeem": "¿Tienes un código de acceso? Escríbelo para ver el informe completo",
        "redeem_button": "Canjear código",
        "buy_code": "¿No tienes código? Pídelo aquí",
        "generic_rules": "Reglas de referencia genéricas, no las de una firma concreta.",
        "unlock_jump": "Desbloquear el informe completo",
        "unlock_nav": "Desbloquear",
        "account": "El dinero real de la cuenta",
        "account_intro": (
            "El porcentaje de ganancia que muestran los sitios de historiales quita los "
            "depósitos y los retiros. Aquí lo ponemos junto al dinero que la cuenta ganó o "
            "perdió operando, los depósitos hechos en plena pérdida y las posiciones que "
            "seguían abiertas al imprimir el historial."
        ),
        "account_backtest": (
            "Esta revisión es para historiales de cuentas reales o demo de MetaTrader 4 o 5. "
            "Tu archivo es un backtest."
        ),
        "account_gain": "Ganancia en %, como la muestran los sitios de historiales.",
        "account_money": "Resultado de operar, en dinero, sobre {deposited} depositados.",
        "account_floating": "Pérdida abierta sobre el balance al imprimir el historial.",
        "account_clean": (
            "No vimos depósitos en plena pérdida, ni una pérdida abierta grande, ni un "
            "porcentaje que se aparte del dinero."
        ),
        "account_live": (
            "Revisión del historial que subiste como cuenta real. Sus banderas se muestran "
            "aquí y no cambian la clase del backtest."
        ),
        "account_deposits": "Depósitos después de empezar a operar, de mayor a menor",
        "account_date": "Fecha",
        "account_amount": "Importe",
        "account_before": "Balance antes",
        "account_drawdown": "Drawdown entonces",
        "account_scope": ("Leído del archivo tal como lo subiste; nada se comprobó con el bróker."),
        "timing": "Cuándo gana y cuándo pierde",
        "timing_intro": (
            "Tus operaciones agrupadas por el día y la hora de entrada. Si casi todo el "
            "resultado sale de un solo día o de una sola franja, un cambio de horario del "
            "servidor, de festivos o de noticias puede borrarlo."
        ),
        "timing_best_day": "El {share:.0%} del resultado neto sale de los {day}.",
        "timing_best_block": "El {share:.0%} del resultado neto sale de la franja {block}.",
        "timing_day": "Día de entrada",
        "timing_block": "Hora de entrada",
        "timing_trades": "Operaciones",
        "timing_net": "Resultado neto",
        "timing_hits": "Aciertos",
        "live": "Backtest frente a cuenta real",
        "live_intro": (
            "Si las operaciones de la cuenta real salieran del mismo backtest, ¿qué tan raro "
            "sería su resultado? Tomamos al azar operaciones del backtest, tantas como tiene "
            "la cuenta real, {samples:,} veces, y ubicamos la cuenta real entre esas historias."
        ),
        "live_CONSISTENT": (
            "La cuenta real se comporta como el backtest: su resultado neto y su peor caída "
            "caen dentro de lo que el backtest hacía esperar."
        ),
        "live_EDGE": (
            "La cuenta real está en el borde: su resultado neto o su peor caída quedan peor "
            "que en el 95 % de las historias del backtest. Puede ser una mala racha, pero "
            "merece preguntas al vendedor."
        ),
        "live_INCONSISTENT": (
            "La cuenta real no se comporta como el backtest: su resultado neto o su peor caída "
            "quedan peor que en el 99 % de las historias del backtest."
        ),
        "live_ABOVE": (
            "La cuenta real queda por encima del 99 % de las historias del backtest. Un "
            "resultado así suele indicar que los dos archivos no son de la misma "
            "configuración, tamaño o cuenta: pregúntalo."
        ),
        "live_badge_CONSISTENT": "Coherente",
        "live_badge_EDGE": "En el borde",
        "live_badge_INCONSISTENT": "No coherente",
        "live_badge_ABOVE": "Revisar",
        "live_col_backtest": "Backtest",
        "live_col_live": "Cuenta real",
        "live_col_live_rescaled": "Cuenta real, a tamaño del backtest",
        "live_col_expected": "Rango esperado (90 %)",
        "live_trades": "Operaciones",
        "live_period": "Periodo",
        "live_per_month": "Operaciones al mes",
        "live_win_rate": "Aciertos",
        "live_net": "Resultado neto",
        "live_fall": "Peor caída",
        "live_avg_win": "Ganancia media",
        "live_avg_loss": "Pérdida media",
        "live_below": "Historias del backtest con un resultado neto igual o peor",
        "live_fall_above": "Historias del backtest con una caída igual o más profunda",
        "live_rescaled": (
            "La cuenta real opera {ratio:.2f} veces el tamaño del backtest: cada operación "
            "real se ajustó al tamaño mediano del backtest antes de comparar."
        ),
        "live_same_size": "Mismo tamaño de posición (±25 %): se compara tal cual.",
        "live_pace": (
            "La cuenta real hace {ratio:.1f} veces las operaciones al mes del backtest: puede "
            "no ser la misma configuración."
        ),
        "live_overlap": (
            "Parte de la cuenta real cae dentro del periodo del backtest: esas fechas pudieron "
            "usarse para ajustar el backtest, así que la comparación es menos exigente."
        ),
        "live_symbols": "La cuenta real opera símbolos que el backtest no tiene: {symbols}.",
        "live_pair": "Mismas fechas, operación por operación",
        "live_pair_intro": (
            "Del {start} al {end} los dos archivos cubren los mismos días. Buscamos cada "
            "operación real en el backtest: mismo lado, mismo símbolo y entrada a menos de "
            "60 minutos."
        ),
        "live_pair_found": "Operaciones reales encontradas en el backtest",
        "live_pair_of": "{matched} de {total} ({share})",
        "live_pair_missing": "Operaciones del backtest sin su operación real",
        "live_pair_entry": "Diferencia mediana de precio al entrar",
        "live_pair_exit": "Diferencia mediana de precio al salir",
        "live_pair_gap": "Diferencia de resultado en las emparejadas",
        "live_pair_gap_value": "{total} ({each} por operación)",
        "live_pair_bps": "{bps} pb",
        "live_pair_low": (
            "Menos de la mitad de las operaciones reales aparecen en el backtest en esas "
            "fechas: probablemente no es la misma configuración. Pide al vendedor el backtest "
            "exacto de esa cuenta."
        ),
        "live_pair_help": (
            "pb = puntos básicos (0,01 % del precio); positivo es peor para la cuenta. La "
            "diferencia de resultado está al tamaño del backtest; negativa es lo que la cuenta "
            "real hizo por debajo del backtest en las mismas operaciones."
        ),
        "reading": "Lectura de tu archivo",
        "reading_intro": (
            "Antes de analizar nada, volvimos a contar tus operaciones fila por fila y lo "
            "comparamos con el resumen que imprime tu plataforma."
        ),
        "reading_platform": "Tu plataforma",
        "reading_rows": "Leído de las filas",
        "reading_ok": "Coincide",
        "reading_bad": "No coincide",
        "reading_all_ok": "Todo coincide: el análisis parte de los mismos números que ves tú.",
        "reading_some_bad": (
            "Algo no coincide. Revisa los avisos de lectura más abajo y, si crees que leímos "
            "mal tu archivo, escríbenos con el identificador del informe."
        ),
        "boot_line": "Bootstrap estacionario por bloques, remuestreos:",
        "boot_block": "bloque",
        "point": "Estimación",
        "engine": "motor",
        "seed": "semilla",
        "code_request": f"Hola, quiero un código de {BRAND} para el informe {{id}}.",
        "keep_link": (
            "Guarda el enlace de esta página: es la única forma de volver a tu informe. "
            "No pedimos correo ni cuenta."
        ),
        "pack": "pack de 3 informes: USD {price:.0f}",
        "publish": "Publicar verificación pública",
        "publish_help": (
            "Crea una página pública con la clase, las dimensiones y los hashes, y un sello "
            "para tu web. Nunca muestra tus archivos, operaciones ni descripción."
        ),
        "meaning": "Qué significa para ti",
        "ladder": "Qué pide cada clase",
        "ladder_intro": (
            "La clase no mide cuánto ganó el backtest, sino cuántas preguntas responden tus "
            "archivos. Una clase mejor no significa que la estrategia vaya a funcionar."
        ),
        "ladder_class": "Clase",
        "ladder_needs": "Qué hace falta",
        "ladder_you": "Tu informe",
        "charts": "Gráficas",
        "detail_heading": "Detalle",
        "locked_intro": (
            "El veredicto, las gráficas y las explicaciones son gratis. El detalle numérico de "
            "estas secciones se entrega en el informe completo"
        ),
        "trade_stats": "Estadísticas de las operaciones",
        "long": "Largos",
        "short": "Cortos",
        "risk": "Riesgo remuestreado a un año",
        "risk_dd": "Drawdown máximo a un año",
        "risk_prob": "Probabilidad de una caída de al menos",
        "risk_underwater": "Periodos seguidos bajo el máximo",
        "challenge": "Simulador de reto de prop firm",
        "challenge_rules": "Reglas simuladas",
        "outcome": "Resultado",
        "probability": "Probabilidad",
        "pass": "Llega al objetivo",
        "fail_daily_loss": "Rompe la pérdida diaria",
        "fail_total_loss": "Rompe la pérdida total",
        "unfinished": "No termina a tiempo",
        "ci95": "Intervalo del 95 % de llegar al objetivo",
        "days_to_target": "Días hábiles hasta el objetivo (p25 / p50 / p75)",
        "assumptions": "Supuestos",
        "source": "Fuente",
        "as_of": "leída el",
        "questions": "Preguntas para hacerle al vendedor",
        "flags_free": "Banderas rojas detectadas",
        "report_source": "Formato del archivo",
        "platform": "Datos que declara la plataforma",
        "optimization": "Exportación de optimización",
        "passes": "configuraciones probadas",
        "trials_used": "Intentos usados en el Sharpe deflactado",
        "horizon": "1 año",
        "reasons_detail": "Razones por dimensión",
        "fees": "Costes que detalla el informe",
        "plan": "Plan para subir de clase",
        "plan_intro": (
            "Lo que las reglas de la auditoría necesitarían ver en cada dimensión abierta, "
            "de lo más decisivo a lo menos. Una clase mejor significa que los archivos "
            "responden más preguntas, no que la estrategia vaya a funcionar."
        ),
        "plan_class": "Con esta dimensión en PASS y las demás igual, la clase sería",
        "plan_none": "Todas las dimensiones pasan: no queda ningún paso abierto.",
        "plan_locked": "pasos concretos, con las cifras de tu archivo, en el informe completo",
        "kpis": "Resumen ejecutivo",
        "toc": "Secciones del informe",
        "toc_unlock": "Informe completo",
        "kpis_locked": "Las cifras clave de tu archivo se muestran en el informe completo.",
        "kpi_return": "Retorno total",
        "kpi_drawdown": "Drawdown máximo",
        "kpi_dd_p95": "Drawdown p95 remuestreado, 1 año",
        "kpi_sharpe": "Sharpe anualizado",
        "kpi_pf": "Profit factor",
        "kpi_trades": "Operaciones · % de aciertos",
        "kpi_breakeven": "Coste extra que lo lleva a cero",
        "kpi_stress": "Sin las 5 mejores operaciones",
        "kpi_stress_curve": "Sin los 5 mejores periodos",
        "bps_side": "pb por lado",
        "stress": "Pruebas de estrés: sin los mejores resultados",
        "stress_intro": (
            "Quitamos los mejores periodos y operaciones de lo que subiste y medimos lo que "
            "queda. Si el total cae a cero o menos, depende de unos pocos eventos que pueden "
            "no repetirse. No es una previsión."
        ),
        "stress_curve": "Sobre la curva (retorno total compuesto)",
        "stress_trades": "Sobre las operaciones cerradas (resultado neto tras comisiones y swap)",
        "scenario": "Escenario",
        "stress_result": "Queda",
        "stress_change": "Cambio",
        "stress_positive": "¿Sigue sobre cero?",
        "original": "Original",
        "stress_count": "de {total} escenarios quedan en cero o por debajo",
        "top5_share": "Las 5 mejores operaciones suman este múltiplo del resultado neto",
    },
    "en": {
        "title": f"{BRAND} · Backtest audit",
        "generated": "Generated",
        "audit_id": "Identifier",
        "inputs": "Audited files (sha256)",
        "verdict": "Verdict",
        "dimensions": "Dimensions",
        "dimension": "Dimension",
        "status": "Status",
        "reasons": "Reasons",
        "performance": "Annualised performance",
        "significance": "Statistical significance",
        "multiplicity": "Multiplicity (number of trials)",
        "sensitivity": "Deflated Sharpe sensitivity to the number of trials",
        "bootstrap": "Stationary bootstrap (per period)",
        "holdout": "Declared out-of-sample",
        "costs": "Trading costs",
        "benchmark": "Supplied benchmark",
        "cscv": "Combinatorially symmetric cross-validation (CSCV) overfitting",
        "subperiods": "Sub-periods (calendar years)",
        "rolling": "Rolling windows",
        "red_flags": "Red flags",
        "not_measured": "Not measured",
        "declared": "Declared by the client",
        "metric": "Metric",
        "value": "Value",
        "evidence": "Evidence",
        "note": "Note",
        "none": "none",
        "trials": "trials",
        "expected_max": "Expected max Sharpe without skill",
        "dsr": "Deflated Sharpe (DSR)",
        "multiplier": "Multiplier",
        "bps": "bps per side",
        "gross": "Gross",
        "cost": "Cost",
        "net": "Net",
        "win_rate": "Win rate",
        "trades": "Trades",
        "in_sample": "In sample",
        "out_of_sample": "Out of sample",
        "year": "Year",
        "return": "Return",
        "max_drawdown": "Max drawdown",
        "window": "Window",
        "min_return": "Min return",
        "min_drawdown": "Min drawdown",
        "share_negative": "Share negative",
        "code": "Code",
        "severity": "Severity",
        "detail": "Detail",
        "warnings": "Parse warnings",
        "client_text": "Client description",
        "client_text_none": "No strategy description was written.",
        "chars": "{n} characters",
        "client_text_note": (
            "The description is not reproduced here; it is in the JSON. Result-promise "
            "expressions detected in it"
        ),
        "seal": "Declared holdout seal",
        "pay": "Pay by card",
        "pay_pack": "Buy the pack of 3 (USD {price:.0f})",
        "pay_secure": (
            "Secure payment with Stripe. You see the full report as soon as the payment is "
            "confirmed; we never see or store your card details."
        ),
        "buy_code_alt": "Prefer a bank transfer? Ask for a code here",
        "pack_left": (
            "You have {n} reports left in your pack. To use them, enter this code when you "
            "unlock your next reports:"
        ),
        "pack_used": "You have used the reports in your pack (code {code}).",
        "pack_keep": "Keep it: it also shows here every time you open this report.",
        "locked": "Section available in the full report",
        "disclaimer": "Notice",
        "json_sha": "sha256 of the audit JSON",
        "thresholds": "Thresholds applied",
        "print": "Print / save PDF",
        "pdf": "Download PDF",
        "obs": "observations",
        "source_equity": "equity curve",
        "source_returns": "return series",
        "variance_policy": (
            "Variance used: the larger of the one observed across the variants you uploaded "
            "and the one sampling error produces."
        ),
        "pdf_long": "Download the report as PDF",
        "switch": "Español",
        "yes": "yes",
        "no": "no",
        "redeem": "Have an access code? Enter it to see the full report",
        "redeem_button": "Redeem code",
        "buy_code": "No code yet? Ask for one here",
        "generic_rules": "Generic reference rules, not any one firm's terms.",
        "unlock_jump": "Unlock the full report",
        "unlock_nav": "Unlock",
        "account": "The account's real money",
        "account_intro": (
            "The percentage gain track-record sites show takes deposits and withdrawals out. "
            "Here it sits next to the money the account made or lost by trading, deposits "
            "made in a deep drawdown, and positions still open when the history was printed."
        ),
        "account_backtest": (
            "This review is for real or demo account histories from MetaTrader 4 or 5. "
            "Your file is a backtest."
        ),
        "account_gain": "Percentage gain, as track-record sites show it.",
        "account_money": "Trading result, in money, on {deposited} deposited.",
        "account_floating": "Open loss over the balance when the history was printed.",
        "account_clean": (
            "We saw no deposit in a deep drawdown, no large open loss and no percentage that "
            "departs from the money."
        ),
        "account_live": (
            "Review of the history you uploaded as the live account. Its flags are shown "
            "here and do not change the backtest's class."
        ),
        "account_deposits": "Deposits after trading began, largest first",
        "account_date": "Date",
        "account_amount": "Amount",
        "account_before": "Balance before",
        "account_drawdown": "Drawdown then",
        "account_scope": "Read from the file as uploaded; nothing was checked with the broker.",
        "timing": "When it wins and when it loses",
        "timing_intro": (
            "Your trades grouped by entry day and time. If nearly all the result comes from "
            "one day or one session, a change of server time, holidays or news can erase it."
        ),
        "timing_best_day": "{share:.0%} of the net result comes from {day}s.",
        "timing_best_block": "{share:.0%} of the net result comes from the {block} session.",
        "timing_day": "Entry day",
        "timing_block": "Entry time",
        "timing_trades": "Trades",
        "timing_net": "Net result",
        "timing_hits": "Win rate",
        "live": "Backtest against the live account",
        "live_intro": (
            "If the live account's trades came from the same backtest, how unusual would its "
            "result be? We drew backtest trades at random, as many as the live account holds, "
            "{samples:,} times, and placed the live account among those histories."
        ),
        "live_CONSISTENT": (
            "The live account behaves like the backtest: its net result and its deepest fall "
            "lie within what the backtest led to expect."
        ),
        "live_EDGE": (
            "The live account is at the edge: its net result or its deepest fall is worse "
            "than in 95 % of the backtest's histories. It may be a bad streak, but it deserves "
            "questions to the seller."
        ),
        "live_INCONSISTENT": (
            "The live account does not behave like the backtest: its net result or its "
            "deepest fall is worse than in 99 % of the backtest's histories."
        ),
        "live_ABOVE": (
            "The live account sits above 99 % of the backtest's histories. A result like "
            "this usually means the two files do not share the same configuration, size or "
            "account: ask."
        ),
        "live_badge_CONSISTENT": "Consistent",
        "live_badge_EDGE": "At the edge",
        "live_badge_INCONSISTENT": "Not consistent",
        "live_badge_ABOVE": "Check",
        "live_col_backtest": "Backtest",
        "live_col_live": "Live account",
        "live_col_live_rescaled": "Live, at the backtest's size",
        "live_col_expected": "Expected range (90 %)",
        "live_trades": "Trades",
        "live_period": "Period",
        "live_per_month": "Trades per month",
        "live_win_rate": "Win rate",
        "live_net": "Net result",
        "live_fall": "Deepest fall",
        "live_avg_win": "Average win",
        "live_avg_loss": "Average loss",
        "live_below": "Backtest histories with a net result as low or lower",
        "live_fall_above": "Backtest histories with a fall as deep or deeper",
        "live_rescaled": (
            "The live account trades {ratio:.2f} times the backtest's size: each live trade "
            "was scaled to the backtest's median size before comparing."
        ),
        "live_same_size": "Same position size (±25 %): compared as traded.",
        "live_pace": (
            "The live account makes {ratio:.1f} times the backtest's trades per month: it may "
            "not be the same configuration."
        ),
        "live_overlap": (
            "Part of the live account falls inside the backtest's period: those dates may "
            "have been used to fit the backtest, so the comparison is less demanding."
        ),
        "live_symbols": "The live account trades symbols the backtest lacks: {symbols}.",
        "live_pair": "Same dates, trade by trade",
        "live_pair_intro": (
            "From {start} to {end} both files cover the same days. Each live trade was "
            "looked up in the backtest: same side, same symbol and an entry less than 60 "
            "minutes apart."
        ),
        "live_pair_found": "Live trades found in the backtest",
        "live_pair_of": "{matched} of {total} ({share})",
        "live_pair_missing": "Backtest trades without their live trade",
        "live_pair_entry": "Median price difference at entry",
        "live_pair_exit": "Median price difference at exit",
        "live_pair_gap": "Result difference on the paired trades",
        "live_pair_gap_value": "{total} ({each} per trade)",
        "live_pair_bps": "{bps} bp",
        "live_pair_low": (
            "Fewer than half the live trades appear in the backtest on those dates: it is "
            "probably not the same configuration. Ask the seller for that account's exact "
            "backtest."
        ),
        "live_pair_help": (
            "bp = basis points (0.01 % of the price); positive is worse for the account. The "
            "result difference is at the backtest's size; negative is what the live account "
            "made below the backtest on the same trades."
        ),
        "reading": "How your file was read",
        "reading_intro": (
            "Before analysing anything, we re-counted your trades row by row and compared "
            "them with the summary your platform prints."
        ),
        "reading_platform": "Your platform",
        "reading_rows": "Read from the rows",
        "reading_ok": "Matches",
        "reading_bad": "Does not match",
        "reading_all_ok": "Everything matches: the analysis starts from the same numbers you see.",
        "reading_some_bad": (
            "Something does not match. Check the reading notes further down and, if you think "
            "your file was misread, write to us with the report id."
        ),
        "boot_line": "Stationary block bootstrap, resamples:",
        "boot_block": "block",
        "point": "Estimate",
        "engine": "engine",
        "seed": "seed",
        "code_request": f"Hello, I would like a {BRAND} code for report {{id}}.",
        "keep_link": (
            "Save this page's link: it is the only way back to your report. "
            "We ask for no email and no account."
        ),
        "pack": "pack of 3 reports: USD {price:.0f}",
        "publish": "Publish a public verification",
        "publish_help": (
            "Creates a public page with the class, the dimensions and the hashes, and a badge "
            "for your site. It never shows your files, trades or description."
        ),
        "meaning": "What this means for you",
        "ladder": "What each class requires",
        "ladder_intro": (
            "The class does not measure how much the backtest made, but how many questions "
            "your files answer. A better class does not mean the strategy will work."
        ),
        "ladder_class": "Class",
        "ladder_needs": "What it takes",
        "ladder_you": "Your report",
        "charts": "Charts",
        "detail_heading": "Detail",
        "locked_intro": (
            "The verdict, charts and explanations are free. The numeric detail of these "
            "sections comes with the full report"
        ),
        "trade_stats": "Trade statistics",
        "long": "Long",
        "short": "Short",
        "risk": "Resampled one-year risk",
        "risk_dd": "Maximum drawdown over one year",
        "risk_prob": "Probability of a fall of at least",
        "risk_underwater": "Consecutive periods below the peak",
        "challenge": "Prop-firm challenge simulator",
        "challenge_rules": "Rules simulated",
        "outcome": "Outcome",
        "probability": "Probability",
        "pass": "Reaches the target",
        "fail_daily_loss": "Breaks the daily loss limit",
        "fail_total_loss": "Breaks the total loss limit",
        "unfinished": "Does not finish in time",
        "ci95": "95 % interval of reaching the target",
        "days_to_target": "Business days to the target (p25 / p50 / p75)",
        "assumptions": "Assumptions",
        "source": "Source",
        "as_of": "read on",
        "questions": "Questions to ask the vendor",
        "flags_free": "Red flags found",
        "report_source": "File format",
        "platform": "Figures the platform states",
        "optimization": "Optimisation export",
        "passes": "configurations tried",
        "trials_used": "Trials used in the deflated Sharpe",
        "horizon": "1 year",
        "reasons_detail": "Reasons by dimension",
        "fees": "Costs the report itemises",
        "plan": "Plan to reach a better class",
        "plan_intro": (
            "What the audit's rules would need to see in each open dimension, most decisive "
            "first. A better class means the files answer more questions, not that the "
            "strategy will work."
        ),
        "plan_class": "With this dimension at PASS and the rest unchanged, the class would be",
        "plan_none": "Every dimension passes: no step is left open.",
        "plan_locked": "concrete steps, with your file's figures, in the full report",
        "kpis": "Executive summary",
        "toc": "Report sections",
        "toc_unlock": "Full report",
        "kpis_locked": "Your file's key figures are shown in the full report.",
        "kpi_return": "Total return",
        "kpi_drawdown": "Maximum drawdown",
        "kpi_dd_p95": "Resampled drawdown p95, 1 year",
        "kpi_sharpe": "Annualised Sharpe",
        "kpi_pf": "Profit factor",
        "kpi_trades": "Trades · win rate",
        "kpi_breakeven": "Extra cost that takes it to zero",
        "kpi_stress": "Without the best 5 trades",
        "kpi_stress_curve": "Without the best 5 periods",
        "bps_side": "bps per side",
        "stress": "Stress tests: without the best outcomes",
        "stress_intro": (
            "We remove the best periods and trades from what you uploaded and measure what "
            "is left. If the total falls to zero or below, it rests on a few events that may "
            "not repeat. This is not a forecast."
        ),
        "stress_curve": "On the curve (compounded total return)",
        "stress_trades": "On the closed trades (net result after commission and swap)",
        "scenario": "Scenario",
        "stress_result": "Left",
        "stress_change": "Change",
        "stress_positive": "Still above zero?",
        "original": "Original",
        "stress_count": "of {total} scenarios end at zero or below",
        "top5_share": "The best 5 trades add up to this multiple of the net result",
    },
}

DIMENSION_TITLES: dict[str, dict[str, str]] = {
    "es": {
        "statistical_significance": "Significación estadística",
        "multiplicity": "Número de intentos (Sharpe deflactado)",
        "costs": "Costes",
        "out_of_sample": "Fuera de muestra",
        "data_quality": "Calidad de datos y forma de operar",
        "benchmark": "Benchmark",
    },
    "en": {
        "statistical_significance": "Statistical significance",
        "multiplicity": "Number of trials (deflated Sharpe)",
        "costs": "Costs",
        "out_of_sample": "Out of sample",
        "data_quality": "Data quality and trading pattern",
        "benchmark": "Benchmark",
    },
}

STATUS_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "PASS": "Supera",
        "WEAK": "Débil",
        "FAIL": "No supera",
        "NOT_MEASURED": "No medido",
        "NOT_APPLICABLE": "No aplica",
    },
    "en": {
        "PASS": "Pass",
        "WEAK": "Weak",
        "FAIL": "Fail",
        "NOT_MEASURED": "Not measured",
        "NOT_APPLICABLE": "Not applicable",
    },
}

#: Reader-facing names of the numeric keys; the key itself when absent.
KEY_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "total_return": "Retorno total",
        "cagr": "Retorno anual compuesto",
        "volatility": "Volatilidad anual",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "max_drawdown": "Drawdown máximo",
        "win_rate": "Aciertos",
        "trade_count": "Operaciones",
        "gross_profit": "Beneficio bruto de las ganadoras",
        "gross_loss": "Pérdida bruta de las perdedoras",
        "fees_total": "Comisiones y swap",
        "net_pnl": "Resultado neto",
        "profit_factor": "Factor de beneficio",
        "expectancy": "Esperanza por operación",
        "average_win": "Ganancia media",
        "average_loss": "Pérdida media",
        "payoff_ratio": "Ratio ganancia/pérdida media",
        "largest_win_share": "Peso de la mayor ganadora",
        "deposits_count": "Depósitos",
        "deposits_total": "Dinero depositado",
        "withdrawals_count": "Retiros",
        "withdrawals_total": "Dinero retirado",
        "later_deposits": "Depósitos después de empezar a operar",
        "trading_result": "Resultado de operar, en dinero",
        "percent_gain": "Ganancia en %",
        "result_on_deposits": "Resultado sobre lo depositado",
        "withdrawn_share": "Parte retirada de lo depositado",
        "top_ups": "Depósitos en plena pérdida",
        "floating_pnl": "Resultado flotante al imprimir",
        "floating_share": "Flotante sobre el balance",
        "max_consecutive_wins": "Máximo de ganadoras seguidas",
        "max_consecutive_losses": "Máximo de perdedoras seguidas",
        "mean_holding_hours": "Horas medias por operación",
        "median_holding_hours": "Horas medianas por operación",
        "sqn": "SQN",
        "trades_per_month": "Operaciones por mes",
        "observations": "Observaciones",
        "psr": "Sharpe probabilístico (PSR)",
        "min_track_record_length": "Historial mínimo necesario",
        "observations_short_by": "Observaciones que faltan",
        "trials": "Intentos",
        "cost_bps_per_side": "Coste por lado (pb)",
        "oos_start": "Inicio fuera de muestra",
        "benchmark_applicable": "Aplica benchmark",
        "initial_balance": "Balance inicial",
        "dsr_at_declared": "DSR con los intentos declarados",
        "dsr_at_trials_used": "DSR con los intentos usados",
        "trials_to_half": "Intentos que bajan el DSR a 0.5",
        "trials_used": "Intentos usados",
        "skewness": "Asimetría",
        "kurtosis": "Curtosis",
        "floor": "Mínimo por error de muestreo",
        "observed_across_variants": "Observado en las variantes",
        "sharpe_variance_used": "Varianza del Sharpe usada",
        "sharpe_per_period": "Sharpe por periodo",
        "break_even_bps": "Coste de equilibrio (pb por lado)",
        "break_even_multiple": "Múltiplo de coste de equilibrio",
        "reference_bps": "Coste de referencia (pb por lado)",
        "dataset_digest": "Huella del conjunto de datos",
    },
    "en": {
        "total_return": "Total return",
        "cagr": "Compound annual return",
        "volatility": "Annual volatility",
        "max_drawdown": "Maximum drawdown",
        "win_rate": "Win rate",
        "trade_count": "Trades",
        "gross_profit": "Gross profit of winners",
        "gross_loss": "Gross loss of losers",
        "fees_total": "Commission and swap",
        "net_pnl": "Net result",
        "profit_factor": "Profit factor",
        "expectancy": "Expectancy per trade",
        "average_win": "Average win",
        "average_loss": "Average loss",
        "payoff_ratio": "Average win / average loss",
        "largest_win_share": "Share of the largest win",
        "deposits_count": "Deposits",
        "deposits_total": "Money deposited",
        "withdrawals_count": "Withdrawals",
        "withdrawals_total": "Money withdrawn",
        "later_deposits": "Deposits after trading began",
        "trading_result": "Trading result, in money",
        "percent_gain": "Percentage gain",
        "result_on_deposits": "Result on the money deposited",
        "withdrawn_share": "Share of deposits withdrawn",
        "top_ups": "Deposits in a deep drawdown",
        "floating_pnl": "Floating result when printed",
        "floating_share": "Floating result / balance",
        "max_consecutive_wins": "Most consecutive wins",
        "max_consecutive_losses": "Most consecutive losses",
        "mean_holding_hours": "Mean hours per trade",
        "median_holding_hours": "Median hours per trade",
        "trades_per_month": "Trades per month",
        "psr": "Probabilistic Sharpe (PSR)",
        "min_track_record_length": "Minimum track record needed",
        "observations_short_by": "Observations missing",
        "cost_bps_per_side": "Cost per side (bps)",
        "oos_start": "Out-of-sample start",
        "benchmark_applicable": "Benchmark applies",
        "initial_balance": "Initial balance",
        "dsr_at_declared": "DSR at the declared trials",
        "dsr_at_trials_used": "DSR at the trials used",
        "trials_to_half": "Trials that bring DSR to 0.5",
        "trials_used": "Trials used",
        "trials": "Trials",
        "observations": "Observations",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "sqn": "SQN",
        "skewness": "Skewness",
        "kurtosis": "Kurtosis",
        "floor": "Sampling-error floor",
        "observed_across_variants": "Observed across variants",
        "sharpe_variance_used": "Sharpe variance used",
        "sharpe_per_period": "Sharpe per period",
        "break_even_bps": "Break-even cost (bps per side)",
        "break_even_multiple": "Break-even cost multiple",
        "reference_bps": "Reference cost (bps per side)",
        "dataset_digest": "Dataset digest",
    },
}

#: Amounts in the account currency: always two decimals, like the platforms.
MONEY_KEYS = {
    "gross_profit",
    "gross_loss",
    "fees_total",
    "net_pnl",
    "gross_pnl",
    "total_cost",
    "expectancy",
    "average_win",
    "average_loss",
    "commission",
    "swap",
    "deposits_total",
    "withdrawals_total",
    "trading_result",
    "floating_pnl",
    "amount",
    "balance_before",
}
#: Ratios a trader reads at two decimals (a profit factor of 1.25, not 1.2453).
RATIO_KEYS = {"profit_factor", "payoff_ratio", "cost_bps_per_side"}

PERCENT_KEYS = {
    "total_return",
    "cagr",
    "volatility",
    "max_drawdown",
    "win_rate",
    "excess_return",
    "strategy_total_return",
    "benchmark_total_return",
    "tracking_error",
    "strategy_max_drawdown",
    "benchmark_max_drawdown",
    "overlap_share",
    "return",
    "min_return",
    "min_drawdown",
    "share_negative",
    "psr",
    "dsr",
    "pbo",
    "p5",
    "p50",
    "p95",
    "p99",
    "point_estimate",
    "largest_win_share",
    "dsr_at_declared",
    "dsr_at_trials_used",
    "percent_gain",
    "result_on_deposits",
    "withdrawn_share",
    "floating_share",
    "drawdown",
}


def to_json(result: AuditResult) -> str:
    return pretty_dumps(result.model_dump(mode="json")) + "\n"


def result_sha256(result: AuditResult) -> str:
    return sha256_of_text(canonical_dumps(result.model_dump(mode="json")))


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _fmt(value: Any, *, key: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if key in PERCENT_KEYS:
            return f"{value:.2%}"
        if key in MONEY_KEYS:
            return f"{value:,.2f}"
        if key in RATIO_KEYS:
            return f"{value:.2f}"
        if value.is_integer() and abs(value) < 1e15:
            return f"{int(value):,}"
        # Four decimals only where they carry information (a per-period Sharpe of
        # 0.1856); anything at or above one reads at two, like the platforms.
        if abs(value) >= 1:
            return f"{value:,.2f}"
        return f"{value:.4f}"
    return _e(value)


def _badge(cls: str) -> str:
    return f'<span class="badge {_e(cls)}">{_e(cls)}</span>'


#: Red-flag severities as a reader says them; the class keeps the colour.
SEVERITY_TEXT: dict[str, dict[str, str]] = {
    "es": {"FAIL": "Grave", "WARN": "Aviso", "INFO": "Nota"},
    "en": {"FAIL": "Serious", "WARN": "Warning", "INFO": "Note"},
}


def _severity_badge(severity: str, locale: str) -> str:
    text = SEVERITY_TEXT.get(locale, SEVERITY_TEXT["en"]).get(severity, severity)
    return f'<span class="badge {_e(severity)}">{_e(text)}</span>'


#: The platform's own summary fields, named as the customer knows them.
PLATFORM_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "strategy": "Estrategia",
        "symbol": "Símbolo",
        "period": "Periodo",
        "broker": "Bróker",
        "server": "Servidor",
        "account_type": "Tipo de cuenta",
        "margin_mode": "Modo de margen",
        "leverage": "Apalancamiento",
        "history_quality": "Calidad del historial",
        "report_date": "Fecha del informe",
        "start": "Inicio",
        "end": "Fin",
        "inputs": "Parámetros",
        "input_names": "Nombres de los parámetros",
        "variants": "Variantes",
        "declared_total_net_profit": "Beneficio neto total",
        "declared_total_trades": "Operaciones totales",
        "declared_total_deals": "Transacciones totales",
        "declared_balance_drawdown_maximal": "Drawdown máximo del balance",
        "declared_equity_drawdown_maximal": "Drawdown máximo de la equity",
        "declared_equity_drawdown_relative": "Drawdown relativo de la equity",
        "declared_maximal_drawdown": "Drawdown máximo",
        "declared_relative_drawdown": "Drawdown relativo",
        "declared_sharpe_ratio": "Sharpe",
        "declared_profit_factor": "Profit factor",
        "declared_balance": "Balance",
        "declared_equity": "Equity",
        "declared_final_equity": "Equity final",
        "declared_closed_trade_pnl": "Resultado de operaciones cerradas",
        "declared_floating_pnl": "Resultado flotante",
    },
    "en": {
        "strategy": "Strategy",
        "symbol": "Symbol",
        "period": "Period",
        "broker": "Broker",
        "server": "Server",
        "account_type": "Account type",
        "margin_mode": "Margin mode",
        "leverage": "Leverage",
        "history_quality": "History quality",
        "report_date": "Report date",
        "start": "Start",
        "end": "End",
        "inputs": "Inputs",
        "input_names": "Input names",
        "variants": "Variants",
        "declared_total_net_profit": "Total net profit",
        "declared_total_trades": "Total trades",
        "declared_total_deals": "Total deals",
        "declared_balance_drawdown_maximal": "Balance drawdown maximal",
        "declared_equity_drawdown_maximal": "Equity drawdown maximal",
        "declared_equity_drawdown_relative": "Equity drawdown relative",
        "declared_maximal_drawdown": "Maximal drawdown",
        "declared_relative_drawdown": "Relative drawdown",
        "declared_sharpe_ratio": "Sharpe ratio",
        "declared_profit_factor": "Profit factor",
        "declared_balance": "Balance",
        "declared_equity": "Equity",
        "declared_final_equity": "Final equity",
        "declared_closed_trade_pnl": "Closed trade P/L",
        "declared_floating_pnl": "Floating P/L",
    },
}


def platform_label(key: str, locale: str) -> str:
    """A platform field's name; an unknown key is shown as plain words."""
    names = PLATFORM_LABELS.get(locale, PLATFORM_LABELS["en"])
    return names.get(key) or key.replace("_", " ").capitalize()


def _is_evidence(value: Any) -> bool:
    return isinstance(value, dict) and "evidence" in value and "value" in value


def _locale_of(labels: dict[str, str]) -> str:
    return "es" if labels is LABELS["es"] else "en"


#: What the customer's file was, as they know it; the same in both languages.
SOURCE_NAMES: dict[str, str] = {
    "mt5_tester_html": "MetaTrader 5 Strategy Tester (HTML)",
    "mt5_tester_xlsx": "MetaTrader 5 Strategy Tester (Excel)",
    "mt5_history_html": "MetaTrader 5 history (HTML)",
    "mt5_history_xlsx": "MetaTrader 5 history (Excel)",
    "mt4_tester_html": "MetaTrader 4 Strategy Tester (HTML)",
    "mt4_statement_html": "MetaTrader 4 statement (HTML)",
    "tradingview_csv": "TradingView (CSV)",
    "tradingview_xlsx": "TradingView (Excel)",
    "ninjatrader_csv": "NinjaTrader (CSV)",
    "quantconnect_trades_csv": "QuantConnect (CSV)",
    "backtestingpy_csv": "backtesting.py (CSV)",
    "vectorbt_csv": "vectorbt (CSV)",
}


#: How often the uploaded series is sampled, as ``schema.infer_frequency`` labels it.
FREQUENCY_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "monthly": "mensual",
        "weekly": "semanal",
        "daily_trading": "diario (días hábiles)",
        "daily_calendar": "diario (todos los días)",
        "hourly": "por hora",
        "intraday": "intradía",
    },
    "en": {
        "monthly": "monthly",
        "weekly": "weekly",
        "daily_trading": "daily (trading days)",
        "daily_calendar": "daily (calendar days)",
        "hourly": "hourly",
        "intraday": "intraday",
    },
}


#: The verdict's thresholds as a reader names them.
THRESHOLD_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "psr_pass": "PSR para superar",
        "psr_weak": "PSR mínimo",
        "dsr_pass": "DSR para superar",
        "dsr_weak": "DSR mínimo",
        "pbo_max": "PBO máximo",
        "cost_pass_multiplier": "múltiplo de coste que debe aguantar",
        "oos_sharpe_pass": "Sharpe fuera de muestra mínimo",
        "oos_gap_max": "caída máxima del Sharpe fuera de muestra",
        "benchmark_drawdown_ratio_max": "drawdown máximo frente al benchmark (veces)",
    },
    "en": {
        "psr_pass": "PSR to pass",
        "psr_weak": "minimum PSR",
        "dsr_pass": "DSR to pass",
        "dsr_weak": "minimum DSR",
        "pbo_max": "maximum PBO",
        "cost_pass_multiplier": "cost multiple it must withstand",
        "oos_sharpe_pass": "minimum out-of-sample Sharpe",
        "oos_gap_max": "maximum out-of-sample Sharpe drop",
        "benchmark_drawdown_ratio_max": "maximum drawdown versus the benchmark (times)",
    },
}


def _key_label(key: str, labels: dict[str, str]) -> str:
    return KEY_LABELS[_locale_of(labels)].get(key, key)


def _evidence_rows(section: dict[str, Any], labels: dict[str, str], *, skip: set[str]) -> str:
    rows = []
    for key, value in section.items():
        if key in skip or not _is_evidence(value):
            continue
        raw = value["value"]
        shown = _e(labels["yes" if raw else "no"]) if isinstance(raw, bool) else _fmt(raw, key=key)
        note = localize(value.get("note", ""), _locale_of(labels))
        rows.append(
            f"<tr><td>{_e(_key_label(key, labels))}</td><td class='val'>{shown}</td>"
            f"<td>{_badge(value['evidence'])}</td><td class='muted'>{_e(note)}</td></tr>"
        )
    if not rows:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        "<table class='metrics'><colgroup><col class='c-k'><col class='c-v'>"
        "<col class='c-e'><col></colgroup>"
        f"<thead><tr><th>{_e(labels['metric'])}</th><th class='val'>{_e(labels['value'])}</th>"
        f"<th>{_e(labels['evidence'])}</th><th>{_e(labels['note'])}</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _status_line(section: dict[str, Any], labels: dict[str, str]) -> str:
    status = section.get("status")
    if status == "NOT_MEASURED":
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>"
            f"{_e(_localized_reason(section.get('reason', ''), _locale_of(labels)))}"
            "</span></p>"
        )
    return ""


#: Spanish for the not-measured reasons the engine writes, beyond the verdict's.
REASONS_ES: dict[str, str] = {
    "the curve is too short or not positive": "la curva es muy corta o no es positiva",
    "fewer than two closed trades": "menos de dos operaciones cerradas",
    **NOT_MEASURED_ES,
    "no trades uploaded": "no se subieron operaciones",
    "no variants uploaded": "no se subió la matriz de variantes",
    "fewer than ten returns": "menos de diez retornos",
    "the simulator needs daily or finer data; the upload is coarser": (
        "el simulador necesita datos diarios o más finos; los subidos son más gruesos"
    ),
}


def _localized_reason(reason: str, locale: str) -> str:
    if locale != "es":
        return reason
    return REASONS_ES.get(reason) or localize(reason, locale)


def _status_badge(status: str, locale: str) -> str:
    text = STATUS_TEXT.get(locale, STATUS_TEXT["es"]).get(status, status)
    return f'<span class="badge {_e(status)}">{_e(text)}</span>'


def _dimension_title(name: str, locale: str) -> str:
    return DIMENSION_TITLES.get(locale, DIMENSION_TITLES["es"]).get(name, name)


def _meaning_html(verdict: dict[str, Any], locale: str) -> str:
    by_name = {d["name"]: d for d in verdict["dimensions"]}
    items = []
    for name in DIMENSION_ORDER:
        dimension = by_name.get(name)
        if dimension is None:
            continue
        items.append(
            f"<div class='item s-{_e(dimension['status'])}'>"
            f"<h3>{_e(_dimension_title(name, locale))} "
            f"{_status_badge(dimension['status'], locale)}</h3>"
            f"<p>{_e(meaning(name, dimension['status'], locale))}</p></div>"
        )
    return "<div class='meaning'>" + "".join(items) + "</div>"


def _reasons_html(verdict: dict[str, Any], locale: str, labels: dict[str, str]) -> str:
    rows = []
    for d in verdict["dimensions"]:
        reasons = d.get("reasons_es") if locale == "es" and d.get("reasons_es") else d["reasons"]
        rows.append(
            f"<tr><td>{_e(_dimension_title(d['name'], locale))}</td>"
            f"<td>{_status_badge(d['status'], locale)}</td><td>{_e('; '.join(reasons))}</td></tr>"
        )
    return (
        f"<table><tr><th>{_e(labels['dimension'])}</th><th>{_e(labels['status'])}</th>"
        f"<th>{_e(labels['reasons'])}</th></tr>{''.join(rows)}</table>"
        f"<p class='muted'>{_e(labels['thresholds'])}: "
        + _e(
            " · ".join(
                f"{THRESHOLD_LABELS[locale].get(k, k)} {v:g}"
                for k, v in verdict["thresholds"].items()
            )
        )
        + "</p>"
    )


def _charts_html(data: dict[str, Any], locale: str) -> str:
    series = data.get("series")
    if not series:
        return ""
    note = series.get("note") if series.get("note") != "as uploaded" else None
    if note and locale == "es":
        note = "Balance reconstruido con operaciones cerradas: no muestra el drawdown flotante."
    figures = [
        charts.equity_chart(series["timestamps"], series["equity"], locale=locale, note=note),
        charts.drawdown_chart(series["timestamps"], series["equity"], locale=locale, note=note),
    ]
    risk = data.get("risk") or {}
    fan = risk.get("fan")
    if fan:
        paths = {key: fan[key] for key in charts.FAN_PERCENTILES if key in fan}
        figures.append(
            charts.fan_chart(
                paths, locale=locale, horizon_label=LABELS.get(locale, LABELS["es"])["horizon"]
            )
        )
    figures.append(
        charts.monthly_heatmap(
            series["month_end_timestamps"], series["month_end_equity"], locale=locale
        )
    )
    return "".join(figures)


PLAN_CSS = (
    ".plan{grid-template-columns:minmax(0,1fr)}"
    ".plan .item h3{justify-content:flex-start;gap:12px}"
    ".plan .item h3 .step-n{font-family:var(--mono);color:var(--text-3);font-weight:500}"
    ".plan .item h3 .step-t{flex:1;min-width:0}"
    ".plan .item ul{margin:10px 0 0;padding-left:1.1rem;color:var(--text-2);font-size:.92rem}"
    ".plan .item li{margin:4px 0}"
    ".plan .item .plan-class{margin-top:10px;font-size:.85rem;color:var(--text-3)}"
)


def _plan_html(data: dict[str, Any], locale: str, labels: dict[str, str], *, locked: bool) -> str:
    """The improvement plan; locked pages show only each step's title."""
    steps = improvement_plan(data, locale)
    if not steps:
        return f"<p class='muted'>{_e(labels['plan_none'])}</p>"
    items = []
    for number, step in enumerate(steps, start=1):
        head = (
            f"<h3><span class='step-n'>{number:02d}</span> "
            f"<span class='step-t'>{_e(step.title)}</span> "
            f"{_status_badge(step.status, locale)}</h3>"
        )
        if locked:
            items.append(f"<div class='item s-{_e(step.status)}'>{head}</div>")
            continue
        actions = (
            "<ul>" + "".join(f"<li>{_e(action)}</li>" for action in step.actions) + "</ul>"
            if step.actions
            else ""
        )
        better = (
            f"<p class='plan-class'>{_e(labels['plan_class'])} "
            f"<strong>{_e(step.class_if_passed)}</strong>.</p>"
            if step.class_if_passed
            else ""
        )
        items.append(
            f"<div class='item s-{_e(step.status)}'>{head}<p>{_e(step.finding)}</p>"
            f"{actions}{better}</div>"
        )
    intro = (
        f"<p class='muted'>{len(steps)} {_e(labels['plan_locked'])}.</p>"
        if locked
        else f"<p class='muted'>{_e(labels['plan_intro'])}</p>"
    )
    return intro + "<div class='meaning plan'>" + "".join(items) + "</div>"


KPI_CSS = (
    ".kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0}"
    "@media (max-width:760px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}"
    ".kpi{border:1px solid var(--border);border-radius:16px;padding:16px 18px;background:#fff}"
    ".kpi b{display:block;font-family:var(--serif);font-weight:400;"
    "font-size:clamp(1.6rem,3vw,2.1rem);line-height:1.1;letter-spacing:-.01em}"
    ".kpi span{display:block;margin-top:6px;color:var(--text-2);font-size:.82rem}"
    ".kpi.bad b{color:var(--bad)}.kpi.good b{color:var(--ok)}"
    ".kpi.locked b{display:flex;align-items:center;gap:10px;height:1.1em;color:var(--text-3)}"
    ".kpi.locked svg{width:.62em;height:.62em;flex:none}"
    ".kpi.locked i{display:block;height:.5em;width:62%;border-radius:999px;"
    "background:linear-gradient(90deg,#ececef 0%,#f6f6f8 50%,#ececef 100%);"
    "background-size:200% 100%;"
    "animation:kpi-sk 2.4s ease-in-out infinite}"
    "@keyframes kpi-sk{from{background-position:100% 0}to{background-position:-100% 0}}"
    "@media (prefers-reduced-motion:reduce){.kpi.locked i{animation:none}}"
)


def _ev_value(block: Any) -> float | None:
    if isinstance(block, dict) and block.get("evidence") != "NOT_MEASURED":
        value = block.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _kpi_list(data: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, str, str]]:
    """``(label, shown value, tone)`` for each key figure that was measured."""
    perf = data.get("performance") or {}
    stats = data.get("trade_stats") or {}
    costs = data.get("costs") or {}
    risk = data.get("risk") or {}
    stress = data.get("stress") or {}
    out: list[tuple[str, str, str]] = []

    def add(label: str, value: float | None, shown: str, tone: str = "") -> None:
        if value is not None:
            out.append((labels[label], shown, tone))

    total = _ev_value(perf.get("total_return"))
    add("kpi_return", total, f"{total:+.1%}" if total is not None else "")
    dd = _ev_value(perf.get("max_drawdown"))
    add("kpi_drawdown", dd, f"{dd:.1%}" if dd is not None else "")
    p95 = _ev_value((risk.get("max_drawdown") or {}).get("p95"))
    add("kpi_dd_p95", p95, f"{p95:.1%}" if p95 is not None else "")
    sharpe = _ev_value(perf.get("sharpe"))
    add("kpi_sharpe", sharpe, f"{sharpe:.2f}" if sharpe is not None else "")
    pf = _ev_value(stats.get("profit_factor"))
    add("kpi_pf", pf, f"{pf:.2f}" if pf is not None else "")
    count = _ev_value(stats.get("trade_count"))
    rate = _ev_value(stats.get("win_rate"))
    if count is not None and rate is not None:
        out.append((labels["kpi_trades"], f"{count:,.0f} · {rate:.0%}", ""))
    breakeven = _ev_value(costs.get("break_even_bps"))
    reference = _ev_value(costs.get("reference_bps")) or 0.0
    if breakeven is not None:
        tone = "bad" if breakeven < 3 * reference else "good"
        label = f"{labels['kpi_breakeven']} ({labels['bps_side']})"
        out.append((label, f"{breakeven:,.2f}", tone))
    for block, scenario, label, percent in (
        (stress.get("trades") or {}, "best_5_trades", "kpi_stress", False),
        (stress.get("returns") or {}, "best_5_periods", "kpi_stress_curve", True),
    ):
        row = next((r for r in block.get("rows", []) if r.get("scenario") == scenario), None)
        value = _ev_value(row["result"]) if row else None
        if value is not None:
            shown = f"{value:+.1%}" if percent else f"{value:+,.2f}"
            out.append((labels[label], shown, "good" if value > 0 else "bad"))
    return out


def _kpis_html(data: dict[str, Any], labels: dict[str, str], *, locked: bool) -> str:
    kpis = _kpi_list(data, labels)
    if not kpis:
        return ""
    tiles = "".join(
        f"<div class='kpi locked'><b aria-hidden='true'>{icon('lock')}<i></i></b>"
        f"<span>{_e(label)}</span></div>"
        if locked
        else f"<div class='kpi {tone}'><b>{_e(shown)}</b><span>{_e(label)}</span></div>"
        for label, shown, tone in kpis
    )
    note = f"<p class='muted'>{_e(labels['kpis_locked'])}</p>" if locked else ""
    return note + f"<div class='kpis'>{tiles}</div>"


STRESS_SCENARIOS: dict[str, dict[str, str]] = {
    "es": {
        "best_1pct_periods": "Sin el mejor 1 % de periodos ({removed})",
        "best_5_periods": "Sin los 5 mejores periodos",
        "best_10_periods": "Sin los 10 mejores periodos",
        "best_1_trades": "Sin la mejor operación",
        "best_5_trades": "Sin las 5 mejores operaciones",
        "best_10pct_trades": "Sin el mejor 10 % de operaciones ({removed})",
        "best_month": "Sin el mejor mes ({month})",
    },
    "en": {
        "best_1pct_periods": "Without the best 1 % of periods ({removed})",
        "best_5_periods": "Without the best 5 periods",
        "best_10_periods": "Without the best 10 periods",
        "best_1_trades": "Without the best trade",
        "best_5_trades": "Without the best 5 trades",
        "best_10pct_trades": "Without the best 10 % of trades ({removed})",
        "best_month": "Without the best month ({month})",
    },
}


def _stress_value(value: Any, *, percent: bool, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    if percent:
        return f"{value:+.1%}" if signed else f"{value:.1%}"
    return f"{value:+,.2f}" if signed else f"{value:,.2f}"


def _stress_table(
    block: dict[str, Any], locale: str, labels: dict[str, str], *, percent: bool
) -> str:
    names = STRESS_SCENARIOS.get(locale, STRESS_SCENARIOS["es"])
    original = block["original"]
    rows = [
        f"<tr class='base'><td>{_e(labels['original'])} {_badge(original['evidence'])}</td>"
        f"<td class='val'>{_stress_value(original['value'], percent=percent)}</td>"
        "<td></td><td></td></tr>"
    ]
    for row in block.get("rows", []):
        name = names.get(row["scenario"], row["scenario"]).format(
            removed=row.get("removed", ""), month=row.get("month", "")
        )
        ok = row.get("stays_positive")
        below = row["result"]["value"] <= 0
        rows.append(
            f"<tr><td>{_e(name)}</td>"
            f"<td class='val{' neg' if below else ''}'>"
            f"{_stress_value(row['result']['value'], percent=percent)}</td>"
            f"<td class='val delta'>"
            f"{_stress_value(row['change']['value'], percent=percent, signed=True)}</td>"
            f"<td><span class='badge {'PASS' if ok else 'FAIL'}'>"
            f"{_e((labels['yes'] if ok else labels['no']).capitalize())}</span></td></tr>"
        )
    return (
        "<table class='stress'><colgroup><col><col class='c-n'><col class='c-n'>"
        "<col class='c-b'></colgroup><thead>"
        f"<tr><th>{_e(labels['scenario'])}</th><th class='val'>{_e(labels['stress_result'])}</th>"
        f"<th class='val'>{_e(labels['stress_change'])}</th>"
        f"<th>{_e(labels['stress_positive'])}</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _stress_html(stress: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    if not stress:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    blocks = [
        (labels["stress_curve"], stress.get("returns") or {}, True),
        (labels["stress_trades"], stress.get("trades") or {}, False),
    ]
    measured_rows = [
        row
        for _, block, _ in blocks
        if block.get("status") == "MEASURED"
        for row in block.get("rows", [])
    ]
    out = f"<p class='muted'>{_e(labels['stress_intro'])}</p>"
    if measured_rows:
        broken = sum(1 for row in measured_rows if not row.get("stays_positive"))
        out += (
            f"<p><strong>{broken}</strong> "
            f"{_e(labels['stress_count'].format(total=len(measured_rows)))}.</p>"
        )
    for title, block, percent in blocks:
        out += f"<h3>{_e(title)}</h3>"
        if block.get("status") != "MEASURED":
            out += _status_line(block, labels)
            continue
        out += _stress_table(block, locale, labels, percent=percent)
        share = block.get("top5_share")
        if share:
            out += (
                f"<p>{_e(labels['top5_share'])}: {share['value']:.2f}x "
                f"{_badge(share['evidence'])}</p>"
            )
    return out


def _flags_free_html(flags: list[dict[str, Any]], locale: str, labels: dict[str, str]) -> str:
    if not flags:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        "<ul class='flag-list'>"
        + "".join(
            f"<li>{_severity_badge(flag['severity'], locale)} "
            f"{_e(flag_title(flag['code'], locale))} "
            f"<code>{_e(flag['code'])}</code></li>"
            for flag in flags
        )
        + "</ul>"
    )


def _trade_stats_html(stats: dict[str, Any] | None, labels: dict[str, str]) -> str:
    if not stats:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    html_text = _status_line(stats, labels)
    if stats.get("status") != "MEASURED":
        return html_text
    html_text += _evidence_rows(stats, labels, skip={"long", "short"})
    for side in ("long", "short"):
        if isinstance(stats.get(side), dict):
            html_text += f"<h3>{_e(labels[side])}</h3>" + _evidence_rows(
                stats[side], labels, skip=set()
            )
    return html_text


def _value_cell(item: dict[str, Any], *, percent: bool) -> str:
    value = item.get("value")
    shown = _fmt(value, key="p50" if percent else "")
    return f"{shown} {_badge(item.get('evidence', 'NOT_MEASURED'))}"


def _assumptions(block: Any, locale: str, labels: dict[str, str]) -> str:
    if not isinstance(block, dict):
        return ""
    items = block.get(locale) or block.get("es") or []
    return (
        f"<p class='muted'>{_e(labels['assumptions'])}:</p><ul class='muted'>"
        + "".join(f"<li>{_e(item)}</li>" for item in items)
        + "</ul>"
    )


def _risk_html(risk: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    if not risk:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    html_text = _status_line(risk, labels)
    if risk.get("status") == "MEASURED":
        dd = risk["max_drawdown"]
        html_text += (
            f"<table><tr><th>{_e(labels['risk_dd'])}</th><th>p50</th><th>p95</th><th>p99</th></tr>"
            f"<tr><td></td>"
            + "".join(f"<td>{_value_cell(dd[q], percent=True)}</td>" for q in ("p50", "p95", "p99"))
            + "</tr></table>"
        )
        probs = risk["probability_drawdown_at_least"]
        html_text += (
            f"<table><tr><th>{_e(labels['risk_prob'])}</th><th>{_e(labels['probability'])}</th>"
            "</tr>"
            + "".join(
                f"<tr><td>{float(level):.0%}</td><td>{_value_cell(item, percent=True)}</td></tr>"
                for level, item in probs.items()
            )
            + "</table>"
        )
        under = risk["longest_underwater_periods"]
        html_text += (
            f"<p>{_e(labels['risk_underwater'])}: p50 {_value_cell(under['p50'], percent=False)}"
            f", p95 {_value_cell(under['p95'], percent=False)}</p>"
        )
    return html_text + _assumptions(risk.get("assumptions"), locale, labels)


def _challenge_html(challenge: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    if not challenge:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    rules = challenge.get("rules", {})
    html_text = (
        f"<p><strong>{_e(labels['challenge_rules'])}:</strong> "
        + _e(
            preset_label(
                str(rules.get("firm", "")),
                str(rules.get("program", "")),
                str(rules.get("phase", "")),
                locale,
            )
        )
        + f" (<code>{_e(challenge.get('preset', ''))}</code>). "
        + (
            f"{_e(labels['source'])}: {_e(rules.get('source_url', ''))}, {_e(labels['as_of'])} "
            f"{_e(rules.get('as_of', ''))}.</p>"
            if str(rules.get("source_url", "")).startswith("https://")
            else f"{_e(labels['generic_rules'])}</p>"
        )
    )
    html_text += _status_line(challenge, labels)
    if challenge.get("status") == "MEASURED":
        probability = challenge["probability"]
        html_text += (
            f"<table><tr><th>{_e(labels['outcome'])}</th><th>{_e(labels['probability'])}</th></tr>"
            + "".join(
                f"<tr><td>{_e(labels[key])}</td>"
                f"<td>{_value_cell(probability[key], percent=True)}</td></tr>"
                for key in ("pass", "fail_daily_loss", "fail_total_loss", "unfinished")
            )
            + "</table>"
        )
        ci = challenge["pass_probability_ci95"]
        days = challenge["days_to_target"]
        html_text += (
            f"<p>{_e(labels['ci95'])}: {_value_cell(ci['low'], percent=True)} – "
            f"{_value_cell(ci['high'], percent=True)}</p>"
            f"<p>{_e(labels['days_to_target'])}: "
            + " / ".join(_value_cell(days[q], percent=False) for q in ("p25", "p50", "p75"))
            + "</p>"
        )
    notes = rules.get("notes") or []
    if notes:
        html_text += (
            "<ul class='muted'>"
            + "".join(f"<li>{_e(localize(n, locale))}</li>" for n in notes)
            + "</ul>"
        )
    return html_text + _assumptions(challenge.get("assumptions"), locale, labels)


def _questions_html(questions: list[dict[str, str]], locale: str, labels: dict[str, str]) -> str:
    if not questions:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        "<ol>"
        + "".join(f"<li>{_e(q.get(locale) or q.get('es', ''))}</li>" for q in questions)
        + "</ol>"
    )


def _source_html(data: dict[str, Any], labels: dict[str, str]) -> str:
    inputs = data["inputs"]
    out = ""
    source_format = inputs.get("source_format")
    if source_format and source_format != "csv":
        shown = SOURCE_NAMES.get(source_format, source_format)
        out += f"<p>{_e(labels['report_source'])}: {_e(shown)}</p>"
    optimization = inputs.get("optimization")
    if optimization:
        passes = optimization["passes"]
        out += (
            f"<p>{_e(labels['optimization'])}: {_fmt(passes['value'])} {_e(labels['passes'])} "
            f"{_badge(passes['evidence'])}</p>"
        )
    metadata = inputs.get("report_metadata") or {}
    if metadata:
        out += (
            f"<p class='muted'>{_e(labels['platform'])} {_badge('DECLARED')}</p><table>"
            + "".join(
                f"<tr><td>{_e(platform_label(key, _locale_of(labels)))}</td>"
                f"<td>{_e(value)}</td></tr>"
                for key, value in metadata.items()
            )
            + "</table>"
        )
    return out


def _other(locale: str) -> str:
    return "en" if locale == "es" else "es"


def _summary_in(data: dict[str, Any], locale: str) -> str:
    """The verdict sentence rebuilt in ``locale`` from the stored dimensions."""
    trials = data["multiplicity"].get("trials_used") or data["declared"].get("trials") or {}
    return summary(
        [Dimension.model_validate(d) for d in data["verdict"]["dimensions"]],
        data["verdict"]["overall"],
        locale="en" if locale == "en" else "es",
        trials=int(trials.get("value") or 1),
        trials_evidence=str(trials.get("evidence") or "DECLARED"),
    )


def _prefilled(contact_url: str, message: str) -> str:
    """A WhatsApp link that opens with ``message`` typed; other links unchanged."""
    parts = urlsplit(contact_url)
    if parts.netloc not in {"wa.me", "api.whatsapp.com"} or "text=" in parts.query:
        return contact_url
    query = (parts.query + "&" if parts.query else "") + "text=" + quote(message)
    return urlunsplit(parts._replace(query=query))


def _short_time(stamp: str) -> str:
    """``2026-09-24T19:40:12.123456Z`` as ``2026-09-24 19:40 UTC``."""
    stamp = str(stamp)
    return f"{stamp[:10]} {stamp[11:16]} UTC" if len(stamp) >= 16 else stamp


#: Totals a platform prints that the audit re-counts from the file's rows:
#: ``(metadata key, trade-stats key, tolerance, is a count)``. The profit
#: factor is left out: platforms count commission and swap in it differently.
READING_CHECKS: tuple[tuple[str, str, float, bool], ...] = (
    ("declared_total_trades", "trade_count", 0.5, True),
    ("declared_total_net_profit", "net_pnl", 0.011, False),
)


def _lead_number(text: object) -> float | None:
    """The first number in a platform figure such as ``'1 279.20 (38.80%)'``.

    Read as the importers read it, so ``'1 279,20'`` from a terminal set to
    Spanish or Portuguese is 1279.20 too.
    """
    number = lead_number(str(text or ""))
    if number is not None:
        return number
    match = re.match(r"\s*(-?[\d\s]+(?:\.\d+)?)", str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(" ", "").replace("\u00a0", ""))
    except ValueError:
        return None


def _reading_rows(data: dict[str, Any]) -> list[tuple[str, float, float, bool]]:
    """``(label key, platform value, value read from the rows, matches)``."""
    meta = (data.get("inputs") or {}).get("report_metadata") or {}
    stats = data.get("trade_stats") or {}
    rows = []
    for meta_key, stat_key, tolerance, _count in READING_CHECKS:
        declared = _lead_number(meta.get(meta_key))
        measured = _ev_value(stats.get(stat_key))
        closing = _lead_number(meta.get("closing_deals"))
        if stat_key == "trade_count" and closing is not None and closing == declared:
            # MetaTrader counts each partial close as a trade: its figure is
            # the file's own closing deals, one per row of the Deals table.
            measured = closing
        if declared is None or measured is None:
            continue
        if stat_key == "net_pnl":
            # Each printed trade result is rounded to the cent, the platform's
            # total is not: up to half a cent per trade is rounding.
            trades = _ev_value(stats.get("trade_count")) or 0
            tolerance = max(tolerance, 0.005 * trades)
        rows.append((stat_key, declared, measured, abs(declared - measured) <= tolerance))
    return rows


def _reading_html(data: dict[str, Any], labels: dict[str, str]) -> str:
    """Did the audit read the file the way the platform did? Shown before
    payment too: these are the customer's own totals, re-counted."""
    rows = _reading_rows(data)
    if not rows:
        return ""

    def number(key: str, value: float) -> str:
        return f"{value:,.0f}" if key == "trade_count" else f"{value:,.2f}"

    body = "".join(
        f"<div class='recon-row {'ok' if ok else 'bad'}'>"
        f"<div class='recon-k'>{_e(_key_label(key, labels))}</div>"
        f"<div class='recon-v'><span><small>{_e(labels['reading_platform'])}</small>"
        f"<b>{_e(number(key, declared))}</b></span>"
        f"<i aria-hidden='true'>{'=' if ok else '≠'}</i>"
        f"<span><small>{_e(labels['reading_rows'])}</small>"
        f"<b>{_e(number(key, measured))}</b></span></div>"
        f"<span class='badge {'PASS' if ok else 'FAIL'}'>"
        f"{_e(labels['reading_ok'] if ok else labels['reading_bad'])}</span></div>"
        for key, declared, measured, ok in rows
    )
    all_ok = all(ok for *_, ok in rows)
    return (
        f"<p class='muted'>{_e(labels['reading_intro'])}</p>"
        f"<div class='recon'>{body}</div>"
        f"<p class='recon-foot {'ok' if all_ok else 'bad'}'>"
        f"{_e(labels['reading_all_ok' if all_ok else 'reading_some_bad'])}</p>"
    )


WEEKDAYS: dict[str, tuple[str, ...]] = {
    "es": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}


def _block_name(key: int) -> str:
    start = key * 4
    return f"{start:02d}:00–{start + 3:02d}:59"


LIVE_TONE = {"CONSISTENT": "PASS", "EDGE": "WEAK", "INCONSISTENT": "FAIL", "ABOVE": "WEAK"}


def _live_html(live: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """The live statement placed among resampled backtest histories."""
    if not live:
        return ""
    if live.get("status") != "MEASURED":
        return _status_line(live, labels)
    outcome = live["outcome"]
    bt, lv, expected = live["backtest"], live["live"], live["expected"]

    def money(value: float) -> str:
        return f"{value:,.2f}"

    def pct(value: float) -> str:
        return f"{value:.0%}"

    def band(key: str, fmt: Any) -> str:
        return f"{fmt(expected[key]['p5'])} … {fmt(expected[key]['p95'])}"

    def cell(side: dict[str, Any], key: str, fmt: Any) -> str:
        item = side.get(key)
        return fmt(item["value"]) if item else "—"

    rows = [
        (labels["live_trades"], f"{bt['trades']['value']:,}", f"{lv['trades']['value']:,}", ""),
        (
            labels["live_period"],
            f"{bt['start']} – {bt['end']}",
            f"{lv['start']} – {lv['end']}",
            "",
        ),
        (
            labels["live_per_month"],
            f"{bt['per_month']['value']:.1f}",
            f"{lv['per_month']['value']:.1f}",
            "",
        ),
        (
            labels["live_win_rate"],
            cell(bt, "win_rate", pct),
            cell(lv, "win_rate", pct),
            band("win_rate", pct),
        ),
        (labels["live_net"], cell(bt, "net", money), cell(lv, "net", money), band("net", money)),
        (
            labels["live_fall"],
            cell(bt, "max_fall", money),
            cell(lv, "max_fall", money),
            band("max_fall", money),
        ),
        (labels["live_avg_win"], cell(bt, "avg_win", money), cell(lv, "avg_win", money), ""),
        (labels["live_avg_loss"], cell(bt, "avg_loss", money), cell(lv, "avg_loss", money), ""),
    ]
    live_head = "live_col_live_rescaled" if live.get("rescaled") else "live_col_live"
    table = (
        "<table class='live'><thead><tr><th></th>"
        f"<th class='val'>{_e(labels[live_head])}</th>"
        f"<th class='val'>{_e(labels['live_col_expected'])}</th>"
        f"<th class='val'>{_e(labels['live_col_backtest'])}</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{_e(name)}</td>"
            f"<td class='val' data-l='{_e(labels[live_head])}'><strong>{_e(b)}</strong></td>"
            f"<td class='val{'' if c else ' empty'}' data-l='{_e(labels['live_col_expected'])}'>"
            f"{_e(c)}</td>"
            f"<td class='val' data-l='{_e(labels['live_col_backtest'])}'>{_e(a)}</td></tr>"
            for name, a, b, c in rows
        )
        + "</tbody></table>"
    )
    notes = [
        labels["live_rescaled"].format(ratio=live["size_ratio"]["value"])
        if live.get("rescaled")
        else labels["live_same_size"]
    ]
    if live.get("pace_differs"):
        notes.append(labels["live_pace"].format(ratio=live["pace_ratio"]["value"]))
    if live.get("overlap"):
        notes.append(labels["live_overlap"])
    if live.get("new_symbols"):
        notes.append(labels["live_symbols"].format(symbols=", ".join(live["new_symbols"])))
    tails = (
        "<div class='facts'>"
        + "".join(
            f"<div class='fact'><b>{pct(live[key]['value'])}</b>"
            f"<p>{_e(labels[label])} {_badge(live[key]['evidence'])}</p></div>"
            for label, key in (("live_below", "net_below"), ("live_fall_above", "fall_above"))
        )
        + "</div>"
    )
    return (
        f"<p class='muted'>{_e(labels['live_intro'].format(samples=live['samples']))}</p>"
        f"<p class='live-verdict lv-{LIVE_TONE[outcome]}'><span class='badge {LIVE_TONE[outcome]}'>"
        f"{_e(labels['live_badge_' + outcome])}</span> {_e(labels['live_' + outcome])}</p>"
        + table
        + tails
        + "".join(f"<p class='muted'>{_e(note)}</p>" for note in notes)
        + f"<p class='muted'>{_e(localize(live.get('note', ''), locale))}</p>"
        + _pairing_html(live.get("pairing"), locale, labels)
    )


def _pairing_html(pairing: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """Live trades paired with the backtest's on the dates both files cover."""
    if not pairing or pairing.get("status") != "MEASURED":
        return ""

    def number(value: float, digits: int = 2) -> str:
        return f"{value:,.{digits}f}"

    def value(item: dict[str, Any], fmt: Any) -> str:
        if item.get("evidence") != "MEASURED":
            reason = _localized_reason(item.get("note", ""), locale)
            return f"{_badge('NOT_MEASURED')} <span class='muted'>{_e(reason)}</span>"
        return f"{_e(fmt(item['value']))} {_badge('MEASURED')}"

    share = pairing["matched_share"]
    found = labels["live_pair_of"].format(
        matched=pairing["matched"]["value"],
        total=pairing["live_trades"]["value"],
        share=f"{share['value']:.0%}" if share.get("value") is not None else "—",
    )
    rows = [
        (labels["live_pair_found"], f"{_e(found)} {_badge('MEASURED')}"),
        (
            labels["live_pair_missing"],
            f"{pairing['missing_live']['value']:,} {_badge('MEASURED')}",
        ),
        (
            labels["live_pair_entry"],
            value(pairing["entry_bps"], lambda v: labels["live_pair_bps"].format(bps=number(v, 1))),
        ),
        (
            labels["live_pair_exit"],
            value(pairing["exit_bps"], lambda v: labels["live_pair_bps"].format(bps=number(v, 1))),
        ),
    ]
    gap = pairing["result_gap"]
    if gap.get("evidence") == "MEASURED":
        each = pairing["result_gap_per_trade"]["value"]
        text = labels["live_pair_gap_value"].format(total=number(gap["value"]), each=number(each))
        rows.append((labels["live_pair_gap"], f"{_e(text)} {_badge('MEASURED')}"))
    else:
        rows.append((labels["live_pair_gap"], value(gap, str)))
    intro = labels["live_pair_intro"].format(start=pairing["start"], end=pairing["end"])
    low = (
        f"<p><span class='badge WEAK'>{_e(labels['live_badge_ABOVE'])}</span> "
        f"{_e(labels['live_pair_low'])}</p>"
        if pairing.get("low_match")
        else ""
    )
    return (
        f"<h3>{_e(labels['live_pair'])}</h3><p class='muted'>{_e(intro)}</p>"
        + low
        + "<table class='pair'><tbody>"
        + "".join(f"<tr><td>{_e(name)}</td><td class='val'>{cell}</td></tr>" for name, cell in rows)
        + "</tbody></table>"
        + f"<p class='muted'>{_e(labels['live_pair_help'])}</p>"
    )


def _timing_table(rows: list[dict[str, Any]], head: str, name: Any, labels: dict[str, str]) -> str:
    widest = max((abs(row["net"]["value"]) for row in rows), default=0.0) or 1.0

    def net_cell(net: float) -> str:
        width = max(2.0, abs(net) / widest * 100)
        side = "neg" if net < 0 else "pos"
        return (
            f"<td class='val tbar {side}'><span class='tbar-track' aria-hidden='true'>"
            f"<span style='--w:{width:.0f}%'></span></span><b>{net:+,.2f}</b></td>"
        )

    body = "".join(
        f"<tr><td>{_e(name(row['key']))}</td><td class='val'>{row['trades']['value']:,}</td>"
        f"{net_cell(row['net']['value'])}"
        f"<td class='val'>{row['win_rate']['value']:.0%}</td></tr>"
        for row in rows
    )
    return (
        "<table class='timing'><colgroup><col class='c-k'><col class='c-n'><col>"
        "<col class='c-n'></colgroup>"
        f"<thead><tr><th>{_e(head)}</th><th class='val'>{_e(labels['timing_trades'])}</th>"
        f"<th class='val'>{_e(labels['timing_net'])}</th>"
        f"<th class='val'>{_e(labels['timing_hits'])}</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _account_html(account: dict[str, Any] | None, labels: dict[str, str]) -> str:
    """Deposits, withdrawals and open positions of an account history."""
    if not account or account.get("status") != "MEASURED":
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>"
            f"{_e(labels['account_backtest'])}</span></p>"
        )
    out = f"<p class='muted'>{_e(labels['account_intro'])}</p>"
    if account.get("source") == "live":
        out += f"<p>{_e(labels['account_live'])}</p>"
        found = account.get("flags") or []
        if found:
            locale = _locale_of(labels)
            out += (
                "<ul>"
                + "".join(
                    f"<li>{_severity_badge(flag['severity'], locale)} "
                    f"{_e(flag_title(flag['code'], locale))}: "
                    f"{_e(localize(flag['detail'], locale))}</li>"
                    for flag in found
                )
                + "</ul>"
            )
    facts = []
    gain = account["percent_gain"]["value"]
    if gain is not None:
        facts.append(
            f"<div class='fact'><b>{gain:.0%}</b><p>{_e(labels['account_gain'])}</p></div>"
        )
    money = account["trading_result"]["value"]
    deposited = _fmt(float(account["deposits"]["total"]["value"]), key="deposits_total")
    facts.append(
        f"<div class='fact'><b>{_fmt(float(money), key='trading_result')}</b>"
        f"<p>{_e(labels['account_money'].format(deposited=deposited))}</p></div>"
    )
    floating = account["floating_share"]["value"]
    if floating is not None and floating < 0:
        facts.append(
            f"<div class='fact'><b>{-floating:.0%}</b><p>{_e(labels['account_floating'])}</p></div>"
        )
    out += f"<div class='facts'>{''.join(facts)}</div>"
    flat = {
        "deposits_count": account["deposits"]["count"],
        "deposits_total": account["deposits"]["total"],
        "withdrawals_count": account["withdrawals"]["count"],
        "withdrawals_total": account["withdrawals"]["total"],
        **{
            key: account[key]
            for key in (
                "trading_result",
                "percent_gain",
                "result_on_deposits",
                "withdrawn_share",
                "later_deposits",
                "top_ups",
                "floating_pnl",
                "floating_share",
            )
        },
    }
    out += _evidence_rows(flat, labels, skip=set())
    listed = account.get("deposit_list") or []
    if listed:
        rows = "".join(
            f"<tr><td>{_e(str(item['time'])[:10])}</td>"
            f"<td class='val'>{_fmt(float(item['amount']['value']), key='amount')}</td>"
            f"<td class='val'>{_fmt(item['balance_before']['value'], key='balance_before')}</td>"
            f"<td class='val'>{_fmt(item['drawdown']['value'], key='drawdown')}</td></tr>"
            for item in listed
        )
        out += (
            f"<h3>{_e(labels['account_deposits'])}</h3>"
            "<table class='metrics'><thead><tr>"
            f"<th>{_e(labels['account_date'])}</th>"
            f"<th class='val'>{_e(labels['account_amount'])}</th>"
            f"<th class='val'>{_e(labels['account_before'])}</th>"
            f"<th class='val'>{_e(labels['account_drawdown'])}</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    if account.get("clean"):
        out += f"<p>{_e(labels['account_clean'])}</p>"
    out += f"<p class='muted'>{_e(labels['account_scope'])}</p>"
    return out


def _timing_fact(share: float, sentence: str) -> str:
    return f"<div class='fact'><b>{share:.0%}</b><p>{_e(sentence)}</p></div>"


def _timing_html(timing: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """Trades by weekday and four-hour block, with the best group's share."""
    if not timing or timing.get("status") != "MEASURED":
        reason = (timing or {}).get("reason", "")
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>"
            f"{_e(localize(reason, locale))}</span></p>"
        )
    days = WEEKDAYS.get(locale, WEEKDAYS["es"])
    out = f"<p class='muted'>{_e(labels['timing_intro'])}</p>"
    facts = ""
    best_day = timing.get("best_weekday")
    if best_day:
        share = best_day["share"]["value"]
        text = labels["timing_best_day"].format(share=share, day=days[best_day["key"]])
        facts += _timing_fact(share, text)
    best_block = timing.get("best_block")
    if best_block:
        share = best_block["share"]["value"]
        text = labels["timing_best_block"].format(share=share, block=_block_name(best_block["key"]))
        facts += _timing_fact(share, text)
    if facts:
        out += f"<div class='facts'>{facts}</div>"
    out += _timing_table(timing["weekdays"], labels["timing_day"], lambda k: days[k], labels)
    if timing.get("blocks"):
        out += _timing_table(timing["blocks"], labels["timing_block"], _block_name, labels)
    out += f"<p class='muted'>{_e(localize(timing.get('note', ''), locale))}</p>"
    return out


#: What each class requires, in the words of ``verdict.overall_class``.
CLASS_LADDER: dict[str, tuple[tuple[str, str], ...]] = {
    "es": (
        (
            "A",
            "La estadística y el número de intentos superan; costes, fuera de muestra y "
            "benchmark superan o no aplican; los datos no tienen banderas graves ni avisos.",
        ),
        (
            "B",
            "La estadística y el número de intentos superan y nada falla, pero falta medir "
            "o reforzar costes, fuera de muestra, benchmark o calidad de datos.",
        ),
        (
            "C",
            "Una dimensión no supera, o la estadística o el número de intentos quedan en débil.",
        ),
        (
            "D",
            "Los datos o la estadística no superan, o no superan dos dimensiones o más.",
        ),
    ),
    "en": (
        (
            "A",
            "Statistics and number of trials pass; costs, out-of-sample and benchmark pass "
            "or do not apply; the data has no serious or warning flags.",
        ),
        (
            "B",
            "Statistics and number of trials pass and nothing fails, but costs, "
            "out-of-sample, benchmark or data quality still need measuring or strengthening.",
        ),
        ("C", "One dimension fails, or statistics or number of trials are weak."),
        ("D", "The data or the statistics fail, or two dimensions or more fail."),
    ),
}


def _ladder_html(current: str, labels: dict[str, str]) -> str:
    """The four classes and what each requires, with this report's marked."""
    rows = "".join(
        f"<li class='rung{' you' if cls == current else ''}' style='--c:{CLASS_COLOURS[cls]}'>"
        f"<span class='rung-cls'>{cls}</span><p>{_e(text)}</p>"
        + (f"<span class='rung-you'>{_e(labels['ladder_you'])}</span>" if cls == current else "")
        + "</li>"
        for cls, text in CLASS_LADDER[_locale_of(labels)]
    )
    return (
        f"<p class='muted'>{_e(labels['ladder_intro'])}</p>"
        f"<ol class='ladder' aria-label='{_e(labels['ladder_class'])}'>{rows}</ol>"
    )


def _only_unmeasured(body: str) -> bool:
    """True when a section has nothing but NOT_MEASURED marks to show."""
    return "badge NOT_MEASURED" in body and not any(
        f"badge {tag}" in body
        for tag in ('MEASURED"', "MEASURED'", "DECLARED", "PASS", "WEAK", "FAIL")
    )


def _pack_notice(labels: dict[str, str], code: str, left: int) -> str:
    """The code a card-paid pack left for the next reports, on the paid report."""
    if not code:
        return ""
    if left < 1:
        return f"<div class='notice'>{_e(labels['pack_used'].format(code=code))}</div>"
    return (
        f"<div class='notice'><p>{_e(labels['pack_left'].format(n=left))}</p>"
        f"<p><code>{_e(code)}</code></p>"
        f"<p class='muted'>{_e(labels['pack_keep'])}</p></div>"
    )


def render_html(
    result: AuditResult,
    *,
    watermark: bool,
    free_mode: bool = True,
    price_usd: float | None = None,
    checkout_url: str | None = None,
    redeem_url: str | None = None,
    publish_url: str | None = None,
    notice: str | None = None,
    contact_url: str | None = None,
    legal_links: bool = False,
    locale: str | None = None,
    switch_url: str | None = None,
    head_meta: str | None = None,
    compare_link: str | None = None,
    pack_price_usd: float = 0.0,
    pdf_url: str | None = None,
    pack_code: str = "",
    pack_credits_left: int = 0,
) -> str:
    """The audit as one HTML document.

    ``locale`` shows the page in a language other than the one chosen at
    upload: the verdict sentence is rebuilt from its fixed templates and the
    engine's English notes are translated; the result itself is unchanged.
    ``switch_url`` is the same page in the other language. ``head_meta`` is
    the page's search and preview tags; without it the page is ``noindex``,
    as every client report is.

    The verdict, the plain-language explanations, the charts, the input
    hashes and the list of red flags are always shown. In paid mode an
    unpaid audit gets the detail sections as titles only: their numbers are
    not rendered, so they are not in the page source either. Free mode shows
    everything under a watermark.
    """
    data = result.model_dump(mode="json")
    declared_locale = data["declared"].get("locale", "es")
    locale = locale if locale in LABELS else declared_locale
    labels = LABELS.get(locale, LABELS["es"])
    locked = watermark and not free_mode
    verdict = data["verdict"]
    if locale != declared_locale:
        verdict = {**verdict, "summary": _summary_in(data, locale)}

    paybox = ""
    price = f"USD {price_usd:,.0f}" if price_usd else ""
    pack = labels["pack"].format(price=pack_price_usd) if pack_price_usd else ""
    price_html = (
        f"<div class='buy-price'><b>{_e(price)}</b>"
        + (f"<span>{_e(pack)}</span>" if pack else "")
        + "</div>"
        if price
        else ""
    )
    if locked and checkout_url:
        # Card payment is the main way to pay; the pack is the second button.
        pack_button = (
            "<button class='btn btn-ghost btn-lg' type='submit' name='plan' value='pack'>"
            f"{_e(labels['pay_pack'].format(price=pack_price_usd))}</button>"
            if pack_price_usd
            else ""
        )
        paybox = (
            f"<form class='paybox buy' method='post' action='{_e(checkout_url)}'>"
            + price_html
            + "<div><div class='inline-form'>"
            "<button class='btn btn-primary btn-lg' type='submit' name='plan' value='single'>"
            f"{icon('card')}{_e(labels['pay'])}</button>{pack_button}</div>"
            f"<p class='muted pay-secure'>{icon('lock')}<span>{_e(labels['pay_secure'])}</span></p>"
            "</div></form>"
        )
    if locked and redeem_url:
        if contact_url:
            # Where a client without a code buys one (bank transfer, WhatsApp).
            contact_url = _prefilled(
                contact_url, labels["code_request"].format(id=data["audit_id"])
            )
            if checkout_url:
                # With card payment on, WhatsApp is the alternative, not the main button.
                paybox += (
                    f"<p class='paybox pay-alt'><a href='{_e(contact_url)}' "
                    f"rel='noopener noreferrer' target='_blank'>{icon('chat')}"
                    f"<span>{_e(labels['buy_code_alt'])}</span></a></p>"
                )
            else:
                paybox += (
                    "<div class='paybox buy'>"
                    + price_html
                    + f"<a class='btn btn-primary btn-lg' href='{_e(contact_url)}' "
                    f"rel='noopener noreferrer' target='_blank'>{icon('chat')}"
                    f"{_e(labels['buy_code'])}</a></div>"
                )
        main_button = contact_url or checkout_url
        paybox += (
            f"<form class='paybox' method='post' action='{_e(redeem_url)}'>"
            f"<label for='redeem-code'>{_e(labels['redeem'])}</label><div class='inline-form'>"
            "<input id='redeem-code' type='text' name='code' required maxlength='40' "
            "autocomplete='off' spellcheck='false' placeholder='AUD-XXXX-XXXX-XXXX'>"
            f"<button class='btn {'btn-ghost' if main_button else 'btn-primary'}' type='submit'>"
            f"{_e(labels['redeem_button'])}</button></div></form>"
        )
    compare_html = ""
    if compare_link and not locked:
        from quant_trade.audit.compare import COPY as COMPARE_COPY
        from quant_trade.audit.compare import MAX_LINK_CHARS

        ccopy = COMPARE_COPY["en" if locale == "en" else "es"]
        action = "/compare" if locale == "en" else "/comparar"
        compare_html = (
            f"<form class='publish no-print' method='post' action='{action}'>"
            f"<p class='muted'>{_e(ccopy['from_report_help'])}</p>"
            f"<input type='hidden' name='lang' value='{_e(locale)}'>"
            f"<input type='hidden' name='link_a' value='{_e(compare_link)}'>"
            f"<div class='inline-form'><input type='url' name='link_b' required "
            f"maxlength='{MAX_LINK_CHARS}' autocomplete='off' spellcheck='false' "
            f"aria-label='{_e(ccopy['link_b'])}' placeholder='{_e(ccopy['placeholder'])}'>"
            f"<button class='btn btn-dark' type='submit'>{_e(ccopy['submit'])}</button></div>"
            "</form>"
        )
    publish_html = ""
    if publish_url and not locked:
        publish_html = (
            f"<form class='publish' method='post' action='{_e(publish_url)}'>"
            f"<p class='muted'>{_e(labels['publish_help'])}</p>"
            f"<button class='btn btn-dark' type='submit'>{_e(labels['publish'])}</button></form>"
        )

    inputs_html = (
        "<table>"
        + "".join(
            f"<tr><td>{_e(name)}</td><td><code>{_e(digest)}</code></td></tr>"
            for name, digest in data["inputs"]["digests"].items()
        )
        + (
            f"<tr><td>{_e(_key_label('dataset_digest', labels))}</td>"
            f"<td><code>{_e(data['inputs']['dataset_digest'])}</code>"
            "</td></tr></table>"
        )
    )
    inputs_html += (
        f"<p class='muted'>{_e(_short_time(data['inputs']['first_timestamp'])[:10])} → "
        f"{_e(_short_time(data['inputs']['last_timestamp'])[:10])} · "
        f"{_e(FREQUENCY_TEXT[locale].get(data['inputs']['frequency_label'], ''))} · "
        f"{_fmt(data['inputs']['observations']['value'])} {_e(labels['obs'])} · "
        f"{_e(labels['source_' + data['inputs']['source']])}</p>"
    )
    if data["inputs"]["parse_warnings"]:
        inputs_html += (
            f"<p class='muted'>{_e(labels['warnings'])}: "
            + _e("; ".join(localize(w, locale) for w in data["inputs"]["parse_warnings"]))
            + "</p>"
        )

    declared_html = _evidence_rows(data["declared"], labels, skip=set())
    description = data["declared"].get("description", "")
    findings = data.get("client_text_findings", [])
    if description:
        declared_html += (
            f"<p class='muted'>{_e(labels['client_text'])}: "
            f"{_e(labels['chars'].format(n=len(description)))}, sha256 "
            f"<code>{_e(sha256_of_text(description))}</code>. {_e(labels['client_text_note'])}: "
            f"{len(findings)}.</p>"
        )
    else:
        declared_html += f"<p class='muted'>{_e(labels['client_text_none'])}</p>"

    sens = data["multiplicity"].get("sensitivity", [])
    sens_html = ""
    if sens:
        sens_html = (
            f"<table><tr><th>{_e(labels['trials'])}</th><th>{_e(labels['expected_max'])}</th>"
            f"<th>{_e(labels['dsr'])}</th></tr>"
            + "".join(
                f"<tr><td>{_fmt(row['n_trials'])}</td>"
                f"<td>{_fmt(row['expected_max_sharpe_per_period']['value'])}</td>"
                f"<td>{_fmt(row['dsr']['value'], key='dsr')}</td></tr>"
                for row in sens
            )
            + "</table>"
        )
    multiplicity_html = (
        _status_line(data["multiplicity"], labels)
        + _evidence_rows(data["multiplicity"], labels, skip={"sensitivity"})
        + f"<p class='muted'>{_e(labels['variance_policy'])}</p>"
        + sens_html
    )

    boot = data["bootstrap"]
    boot_html = _status_line(boot, labels)
    if boot.get("status") == "MEASURED":
        boot_html += (
            f"<p class='muted'>{_e(labels['boot_line'])}"
            f" {_fmt(boot['samples'])} · {_e(labels['boot_block'])} {_fmt(boot['block_size'])}</p>"
            f"<table><tr><th></th><th>{_e(labels['point'])}</th><th>p5</th>"
            "<th>p50</th><th>p95</th></tr>"
        )
        for stat in ("sharpe_per_period", "total_return"):
            band = boot[stat]
            key = "p5" if stat == "total_return" else ""
            boot_html += (
                f"<tr><td>{_e(_key_label(stat, labels))}</td>"
                + "".join(
                    f"<td>{_fmt(band[p]['value'], key=key)} {_badge(band[p]['evidence'])}</td>"
                    for p in ("point_estimate", "p5", "p50", "p95")
                )
                + "</tr>"
            )
        boot_html += "</table>"

    hold = data["holdout"]
    hold_html = _status_line(hold, labels) + _evidence_rows(
        hold, labels, skip={"in_sample", "out_of_sample"}
    )
    if hold.get("status") == "MEASURED":
        for side in ("in_sample", "out_of_sample"):
            hold_html += f"<h3>{_e(labels[side])}</h3>" + _evidence_rows(
                hold[side], labels, skip=set()
            )

    cost = data["costs"]
    cost_html = _status_line(cost, labels) + _evidence_rows(cost, labels, skip={"rows"})
    if cost.get("rows"):
        cost_html += (
            f"<table><tr><th>{_e(labels['multiplier'])}</th><th>{_e(labels['bps'])}</th>"
            f"<th>{_e(labels['gross'])}</th><th>{_e(labels['cost'])}</th><th>{_e(labels['net'])}"
            f"</th><th>{_e(labels['win_rate'])}</th><th>{_e(labels['trades'])}</th></tr>"
            + "".join(
                f"<tr><td>{_fmt(row['multiplier'])}x</td>"
                f"<td>{_fmt(row['cost_bps_per_side'], key='cost_bps_per_side')}</td>"
                f"<td>{_fmt(row['gross_pnl']['value'], key='gross_pnl')}</td>"
                f"<td>{_fmt(row['total_cost']['value'], key='total_cost')}"
                f"</td><td>{_fmt(row['net_pnl']['value'], key='net_pnl')}</td>"
                f"<td>{_fmt(row['win_rate']['value'], key='win_rate')}</td>"
                f"<td>{_fmt(row['trades'])}</td></tr>"
                for row in cost["rows"]
            )
            + "</table>"
        )

    bench_html = _status_line(data["benchmark"], labels) + _evidence_rows(
        data["benchmark"], labels, skip=set()
    )
    cscv_html = _status_line(data["cscv"], labels) + _evidence_rows(
        data["cscv"], labels, skip=set()
    )
    if data["cscv"].get("status") == "MEASURED":
        cscv_html += (
            "<p class='muted'>"
            + _e(
                ", ".join(
                    f"{k}={data['cscv'][k]}"
                    for k in (
                        "partitions",
                        "combinations",
                        "parameter_variants",
                        "observations_used",
                    )
                )
            )
            + "</p>"
        )

    sub_html = (
        f"<table><tr><th>{_e(labels['year'])}</th><th>{_e(labels['return'])}</th>"
        f"<th>{_e(labels['max_drawdown'])}</th></tr>"
        + "".join(
            f"<tr><td>{row['year']}</td><td>{_fmt(row['return']['value'], key='return')}</td>"
            f"<td>{_fmt(row['max_drawdown']['value'], key='max_drawdown')}</td></tr>"
            for row in data["subperiods"]
        )
        + "</table>"
        if data["subperiods"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )
    roll_html = (
        f"<table><tr><th>{_e(labels['window'])}</th><th>{_e(labels['min_return'])}</th>"
        f"<th>{_e(labels['min_drawdown'])}</th><th>{_e(labels['share_negative'])}</th></tr>"
        + "".join(
            f"<tr><td>{row['window']}</td>"
            f"<td>{_fmt(row['min_return']['value'], key='min_return')}</td>"
            f"<td>{_fmt(row['min_drawdown']['value'], key='min_drawdown')}</td>"
            f"<td>{_fmt(row['share_negative']['value'], key='share_negative')}</td></tr>"
            for row in data["rolling"]
        )
        + "</table>"
        if data["rolling"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    flags_html = (
        f"<table><tr><th>{_e(labels['code'])}</th><th>{_e(labels['severity'])}</th>"
        f"<th>{_e(labels['detail'])}</th></tr>"
        + "".join(
            f"<tr><td>{_e(flag['code'])}</td><td>{_severity_badge(flag['severity'], locale)}</td>"
            f"<td>{_e(localize(flag['detail'], locale))}</td></tr>"
            for flag in data["red_flags"]
        )
        + "</table>"
        if data["red_flags"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    seal = data["seal"]
    seal_html = _status_line(seal, labels)
    if seal.get("holdout_seal"):
        hs = seal["holdout_seal"]
        seal_html += (
            "<table>"
            + "".join(
                f"<tr><td>{_e(k)}</td><td><code>{_e(hs[k])}</code></td></tr>"
                for k in (
                    "seal_id",
                    "selection_start",
                    "selection_end",
                    "holdout_start",
                    "holdout_end",
                    "sealed_at_utc",
                    "seal",
                )
            )
            + "</table>"
        )

    not_measured = [
        f"{labels[name]}: {_localized_reason(section.get('reason', ''), locale)}"
        for name, section in (
            ("significance", data["significance"]),
            ("multiplicity", data["multiplicity"]),
            ("bootstrap", data["bootstrap"]),
            ("holdout", data["holdout"]),
            ("costs", data["costs"]),
            ("benchmark", data["benchmark"]),
            ("cscv", data["cscv"]),
            ("risk", data.get("risk") or {}),
            ("challenge", data.get("challenge") or {}),
        )
        if section.get("status") == "NOT_MEASURED"
    ]
    nm_html = (
        "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in not_measured) + "</ul>"
        if not_measured
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    trials = data["multiplicity"].get("trials_used")
    if trials:
        multiplicity_html = (
            f"<p>{_e(labels['trials_used'])}: {_fmt(trials['value'])} {_badge(trials['evidence'])}"
            f" <span class='muted'>{_e(localize(trials.get('note', ''), locale))}</span></p>"
            + multiplicity_html
        )
    fees = data["costs"].get("reported_fees")
    if fees:
        cost_html += f"<h3>{_e(labels['fees'])}</h3>" + _evidence_rows(fees, labels, skip=set())

    detail: list[tuple[str, str]] = [
        (labels["plan"], _plan_html(data, locale, labels, locked=False)),
        (labels["reasons_detail"], _reasons_html(verdict, locale, labels)),
        *(
            [(labels["live"], _live_html(data.get("live"), locale, labels))]
            if data.get("live")
            else []
        ),
        *(
            [(labels["account"], _account_html(data.get("account"), labels))]
            if (data.get("account") or {}).get("status") == "MEASURED"
            else []
        ),
        (labels["stress"], _stress_html(data.get("stress"), locale, labels)),
        (labels["timing"], _timing_html(data.get("timing"), locale, labels)),
        (labels["trade_stats"], _trade_stats_html(data.get("trade_stats"), labels)),
        (labels["risk"], _risk_html(data.get("risk"), locale, labels)),
        (labels["challenge"], _challenge_html(data.get("challenge"), locale, labels)),
        (labels["questions"], _questions_html(data.get("vendor_questions", []), locale, labels)),
        (labels["performance"], _evidence_rows(data["performance"], labels, skip=set())),
        (
            labels["significance"],
            _status_line(data["significance"], labels)
            + _evidence_rows(data["significance"], labels, skip=set()),
        ),
        (labels["multiplicity"], multiplicity_html),
        (labels["bootstrap"], boot_html),
        (labels["holdout"], hold_html),
        (labels["costs"], cost_html),
        (labels["benchmark"], bench_html),
        (labels["cscv"], cscv_html),
        (labels["subperiods"], sub_html),
        (labels["rolling"], roll_html),
        (labels["red_flags"], flags_html),
    ]
    if locked:
        detail_html = (
            f"<div class='lockbox' id='unlock'><p>{_e(labels['locked_intro'])}:</p><ul>"
            + "".join(
                f"<li>{_e(title)}</li>" for title, body in detail if not _only_unmeasured(body)
            )
            + f"</ul>{paybox}</div>"
        )
    else:
        detail_html = "".join(
            f"<section class='detail' id='r-d{i}'><h2>{_e(title)}</h2>{body}</section>"
            for i, (title, body) in enumerate(detail, 1)
        )

    watermark_html = ""
    if watermark:
        text = WATERMARK_TEXT.get(locale, WATERMARK_TEXT["es"])
        watermark_html = (
            f"<div class='watermark'>{_e(text)}</div><div class='banner'>{_e(text)}</div>"
        )

    if locked and (redeem_url or checkout_url):
        # A watermarked preview is not worth printing: the header offers the unlock instead.
        print_html = (
            f"<a class='print-btn' href='#unlock'>{icon('lock')}{_e(labels['unlock_nav'])}</a>"
        )
    elif pdf_url and not locked:
        print_html = f"<a class='print-btn' href='{_e(pdf_url)}' download>{_e(labels['pdf'])}</a>"
    else:
        print_html = (
            "<button type='button' class='print-btn' "
            f"onclick='window.print()'>{_e(labels['print'])}</button>"
        )
    toolbar = (
        "<div class='nav-end no-print'>"
        + print_html
        + (
            f" <a class='lang-switch' href='{_e(switch_url)}' hreflang='{_e(_other(locale))}'>"
            f"{_e(labels['switch'])}</a>"
            if switch_url
            else ""
        )
        + "</div>"
    )
    home = "/en" if locale == "en" else "/"
    header = (
        f"<header class='nav nav-solid'><div class='wrap nav-in'>{logo(home)}{toolbar}</div>"
        "</header>"
    )
    engine = data["engine"]
    meta = (
        f"<span>{_e(labels['audit_id'])} {_e(data['audit_id'])}</span>"
        f"<span>{_e(labels['generated'])} {_e(_short_time(data['generated_at_utc']))}</span>"
        f"<span class='meta-x'>{_e(labels['engine'])} {_e(engine['name'])} "
        f"{_e(engine['package_version'])}</span>"
        f"<span class='meta-x'>{_e(labels['seed'])} {_e(engine['seed'])}</span>"
    )
    hero = (
        "<section class='report-hero'>"
        + aurora()
        + grid_bg()
        + "<div class='wrap wrap-mid'>"
        + watermark_html
        + (f"<div class='notice'>{_e(notice)}</div>" if notice else "")
        + _pack_notice(labels, pack_code, pack_credits_left)
        + f"<div class='eyebrow rise'><span class='dot'></span>{_e(labels['title'])}</div>"
        + f"<h1 class='rise' style='--i:1'>{_e(labels['verdict'])} {_e(verdict['overall'])}</h1>"
        + f"<div class='meta-line rise' style='--i:2'>{meta}</div>"
        + "<div class='verdict rise' style='--i:3'>"
        + class_ring(str(verdict["overall"]), size="lg")
        + f"<div><div class='verdict-k'>{_e(labels['verdict'])}</div>"
        + _verdict_html(str(verdict["summary"]))
        + "</div></div>"
        + (
            f"<p class='rise no-print' style='--i:4'><a class='btn btn-primary' "
            f"href='{_e(pdf_url)}' download>{_e(labels['pdf_long'])}</a></p>"
            if pdf_url and not locked
            else ""
        )
        + (
            f"<p class='rise' style='--i:4'><a class='btn btn-primary' href='#unlock'>"
            f"{_e(labels['unlock_jump'])}</a></p>"
            f"<p class='muted keep-link rise' style='--i:4'>{_e(labels['keep_link'])}</p>"
            if locked and (redeem_url or checkout_url)
            else ""
        )
        + "</div></section>"
    )

    toc: list[tuple[str, str]] = []

    def section(title: str, content: str, key: str = "") -> str:
        if key:
            toc.append((key, title))
        anchor = f" id='{_e(key)}'" if key else ""
        return f"<section class='rsec'{anchor}><h2>{_e(title)}</h2>{content}</section>"

    footer = (
        "<div class='report-foot'>"
        f"<div class='disclaimer'><strong>{_e(labels['disclaimer'])}.</strong> "
        f"{_e(DISCLAIMER.get(locale, DISCLAIMER['es']))}</div>"
        f"<p class='muted'>{_e(labels['json_sha'])}: <code>{_e(result_sha256(result))}</code></p>"
        + (legal_links_html(locale) if legal_links else "")
        + f"<p class='muted'>{_e(BRAND)} · {_e(TAGLINE.get(locale, TAGLINE['es']))}</p></div>"
    )
    kpis_html = _kpis_html(data, labels, locked=locked)
    reading_html = _reading_html(data, labels)
    sections = [
        section(labels["reading"], reading_html, "r-reading") if reading_html else "",
        section(labels["kpis"], kpis_html, "r-kpis") if kpis_html else "",
        section(labels["meaning"], _meaning_html(verdict, locale), "r-meaning"),
        section(labels["ladder"], _ladder_html(str(verdict["overall"]), labels), "r-ladder"),
        section(labels["charts"], _charts_html(data, locale), "r-charts"),
        section(
            labels["flags_free"], _flags_free_html(data["red_flags"], locale, labels), "r-flags"
        ),
        section(labels["plan"], _plan_html(data, locale, labels, locked=True), "r-plan")
        if locked
        else "",
        detail_html,
        publish_html,
        compare_html,
        section(labels["inputs"], inputs_html + _source_html(data, labels), "r-inputs"),
        section(labels["declared"], declared_html),
        section(labels["not_measured"], nm_html),
        section(labels["seal"], seal_html),
        footer,
    ]
    # The detail sections (or the lock box) sit between the plan and the inputs.
    detail_toc = (
        [("unlock", labels["toc_unlock"])]
        if locked
        else [(f"r-d{i}", title) for i, (title, _) in enumerate(detail, 1)]
    )
    toc = toc[:-1] + detail_toc + toc[-1:]
    page_title = f"{labels['title']} {verdict['overall']} · {data['audit_id'][:8]}"
    return (
        "<!doctype html><html lang='"
        + _e(locale)
        + "'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, "
        "initial-scale=1'><meta name='theme-color' content='#05070b'><title>"
        + _e(page_title)
        + "</title>"
        + (head_meta if head_meta is not None else private_meta(page_title, locale))
        + "<style>"
        + STYLE
        + charts.CHART_CSS
        + PLAN_CSS
        + KPI_CSS
        + "</style>"
        + SCRIPT_TAG
        + "</head><body>"
        + header
        + hero
        + _report_toc(toc, labels["toc"])
        + "<main id='main' class='paper report-main'><div class='wrap wrap-mid'>"
        + "".join(sections)
        + "</div></main></body></html>"
    )


def _verdict_html(summary: str) -> str:
    """The verdict: its first sentence as the headline, the rest as detail."""
    lead, sep, rest = summary.partition(". ")
    if not sep:
        return f"<p class='verdict-text'>{_e(summary)}</p>"
    return f"<p class='verdict-text'><span class='verdict-lead'>{_e(lead)}.</span> {_e(rest)}</p>"


def _report_toc(entries: list[tuple[str, str]], label: str) -> str:
    """A sticky row of links to the report's sections (hidden in print)."""
    links = "".join(f"<li><a href='#{_e(key)}'>{_e(title)}</a></li>" for key, title in entries)
    return (
        f"<nav class='report-toc no-print' aria-label='{_e(label)}'><div class='wrap wrap-mid'>"
        f"<ol data-toc>{links}</ol></div></nav>"
    )


def guard_texts(result: AuditResult, html_text: str) -> None:
    """Run the profit-claim guard over the HTML and over the JSON with the
    client's own text withheld (it is reported, never repeated)."""
    payload = result.model_dump(mode="json")
    payload["declared"]["description"] = "<client description withheld from guard>"
    payload["client_text_findings"] = [
        {"count": len(result.client_text_findings), "note": "withheld from guard"}
    ]
    assert_report_clean(html_text, canonical_dumps(payload))


def render(
    result: AuditResult,
    *,
    watermark: bool,
    free_mode: bool = True,
    price_usd: float | None = None,
    checkout_url: str | None = None,
    redeem_url: str | None = None,
    publish_url: str | None = None,
    notice: str | None = None,
    contact_url: str | None = None,
    legal_links: bool = False,
    locale: str | None = None,
    switch_url: str | None = None,
    head_meta: str | None = None,
    compare_link: str | None = None,
    pack_price_usd: float = 0.0,
    pdf_url: str | None = None,
    pack_code: str = "",
    pack_credits_left: int = 0,
) -> tuple[str, str]:
    """``(html, json)`` for a result, both guarded. Raises ``AuditReportError``."""
    html_text = render_html(
        result,
        watermark=watermark,
        free_mode=free_mode,
        price_usd=price_usd,
        checkout_url=checkout_url,
        redeem_url=redeem_url,
        publish_url=publish_url,
        notice=notice,
        contact_url=contact_url,
        legal_links=legal_links,
        locale=locale,
        switch_url=switch_url,
        head_meta=head_meta,
        compare_link=compare_link,
        pack_price_usd=pack_price_usd,
        pdf_url=pdf_url,
        pack_code=pack_code,
        pack_credits_left=pack_credits_left,
    )
    guard_texts(result, html_text)
    return html_text, to_json(result)


__all__ = [
    "DISCLAIMER",
    "LABELS",
    "WATERMARK_TEXT",
    "guard_texts",
    "render",
    "render_html",
    "result_sha256",
    "to_json",
]
