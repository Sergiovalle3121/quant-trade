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
from typing import Any

from quant_trade.audit import charts
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import localize
from quant_trade.audit.legal import legal_links_html
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.redflags import flag_title
from quant_trade.audit.schema import AuditResult, Dimension
from quant_trade.audit.seo import BRAND, TAGLINE, private_meta
from quant_trade.audit.theme import SCRIPT_TAG, STYLE, aurora, class_ring, grid_bg, logo
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
        "client_text_note": (
            "La descripción no se reproduce en este informe; consta en el JSON. Expresiones de "
            "promesa de resultados detectadas en ella"
        ),
        "seal": "Sello del holdout declarado",
        "pay": "Desbloquear el informe completo",
        "locked": "Sección disponible en el informe completo",
        "disclaimer": "Aviso",
        "json_sha": "sha256 del JSON de la auditoría",
        "thresholds": "Umbrales aplicados",
        "print": "Imprimir / guardar PDF",
        "switch": "English",
        "yes": "sí",
        "no": "no",
        "redeem": "¿Tienes un código de acceso? Escríbelo para ver el informe completo",
        "redeem_button": "Canjear código",
        "buy_code": "¿No tienes código? Pídelo aquí",
        "publish": "Publicar verificación pública",
        "publish_help": (
            "Crea una página pública con la clase, las dimensiones y los hashes, y un sello "
            "para tu web. Nunca muestra tus archivos, operaciones ni descripción."
        ),
        "meaning": "Qué significa para ti",
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
        "client_text_note": (
            "The description is not reproduced here; it is in the JSON. Result-promise "
            "expressions detected in it"
        ),
        "seal": "Declared holdout seal",
        "pay": "Unlock the full report",
        "locked": "Section available in the full report",
        "disclaimer": "Notice",
        "json_sha": "sha256 of the audit JSON",
        "thresholds": "Thresholds applied",
        "print": "Print / save PDF",
        "switch": "Español",
        "yes": "yes",
        "no": "no",
        "redeem": "Have an access code? Enter it to see the full report",
        "redeem_button": "Redeem code",
        "buy_code": "No code yet? Ask for one here",
        "publish": "Publish a public verification",
        "publish_help": (
            "Creates a public page with the class, the dimensions and the hashes, and a badge "
            "for your site. It never shows your files, trades or description."
        ),
        "meaning": "What this means for you",
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
    },
}

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
        if abs(value) >= 1000:
            return f"{value:,.1f}"
        return f"{value:.4f}"
    return _e(value)


def _badge(cls: str) -> str:
    return f'<span class="badge {_e(cls)}">{_e(cls)}</span>'


def _is_evidence(value: Any) -> bool:
    return isinstance(value, dict) and "evidence" in value and "value" in value


def _locale_of(labels: dict[str, str]) -> str:
    return "es" if labels is LABELS["es"] else "en"


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
            f"<tr><td>{_e(_key_label(key, labels))}</td><td>{shown}</td>"
            f"<td>{_badge(value['evidence'])}</td><td class='muted'>{_e(note)}</td></tr>"
        )
    if not rows:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        f"<table><tr><th>{_e(labels['metric'])}</th><th>{_e(labels['value'])}</th>"
        f"<th>{_e(labels['evidence'])}</th><th>{_e(labels['note'])}</th></tr>"
        + "".join(rows)
        + "</table>"
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
        + _e(", ".join(f"{k}={v}" for k, v in verdict["thresholds"].items()))
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


def _flags_free_html(flags: list[dict[str, Any]], locale: str, labels: dict[str, str]) -> str:
    if not flags:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        "<ul class='flag-list'>"
        + "".join(
            f"<li>{_badge(flag['severity'])} {_e(flag_title(flag['code'], locale))} "
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
        f"{_e(localize(rules.get('firm', ''), locale))} "
        f"{_e(localize(rules.get('program', ''), locale))} "
        f"{_e(localize(rules.get('phase', ''), locale))} "
        f"(<code>{_e(challenge.get('preset', ''))}</code>). "
        f"{_e(labels['source'])}: {_e(rules.get('source_url', ''))}, {_e(labels['as_of'])} "
        f"{_e(rules.get('as_of', ''))}.</p>"
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
        out += f"<p>{_e(labels['report_source'])}: <code>{_e(source_format)}</code></p>"
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
                f"<tr><td>{_e(key)}</td><td>{_e(value)}</td></tr>"
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
    if locked and checkout_url:
        price = f" (USD {price_usd:,.0f})" if price_usd else ""
        paybox = (
            f"<form class='paybox' method='post' action='{_e(checkout_url)}'>"
            f"<button class='btn btn-primary btn-lg' type='submit'>{_e(labels['pay'])}{_e(price)}"
            "</button></form>"
        )
    if locked and redeem_url:
        paybox += (
            f"<form class='paybox' method='post' action='{_e(redeem_url)}'>"
            f"<label for='redeem-code'>{_e(labels['redeem'])}</label><div class='inline-form'>"
            "<input id='redeem-code' type='text' name='code' required maxlength='40' "
            "autocomplete='off' spellcheck='false' placeholder='AUD-XXXX-XXXX-XXXX'>"
            f"<button class='btn btn-primary' type='submit'>{_e(labels['redeem_button'])}</button>"
            "</div></form>"
        )
        if contact_url:
            # Where a client without a code buys one (bank transfer, WhatsApp).
            price = f" (USD {price_usd:,.0f})" if price_usd else ""
            paybox += (
                f"<p class='paybox'><a href='{_e(contact_url)}' rel='noopener noreferrer' "
                f"target='_blank'>{_e(labels['buy_code'])}{_e(price)}</a></p>"
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
            f"<tr><td>dataset_digest</td><td><code>{_e(data['inputs']['dataset_digest'])}</code>"
            "</td></tr></table>"
        )
    )
    inputs_html += (
        f"<p class='muted'>{_e(data['inputs']['first_timestamp'])} → "
        f"{_e(data['inputs']['last_timestamp'])}, {_e(data['inputs']['frequency_label'])}, "
        f"{_fmt(data['inputs']['observations']['value'])} obs, "
        f"source={_e(data['inputs']['source'])}</p>"
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
    declared_html += (
        f"<p class='muted'>{_e(labels['client_text'])}: {len(description)} chars, sha256 "
        f"<code>{_e(sha256_of_text(description))}</code>. {_e(labels['client_text_note'])}: "
        f"{len(findings)}.</p>"
    )

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
        + f"<p class='muted'>variance policy: {_e(data['multiplicity']['variance_policy'])}</p>"
        + sens_html
    )

    boot = data["bootstrap"]
    boot_html = _status_line(boot, labels)
    if boot.get("status") == "MEASURED":
        boot_html += (
            f"<p class='muted'>method={_e(boot['method'])}, samples={_fmt(boot['samples'])}, "
            f"block={_fmt(boot['block_size'])}</p><table><tr><th></th><th>point</th><th>p5</th>"
            "<th>p50</th><th>p95</th></tr>"
        )
        for stat in ("sharpe_per_period", "total_return"):
            band = boot[stat]
            key = "p5" if stat == "total_return" else ""
            boot_html += (
                f"<tr><td>{_e(stat)}</td>"
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
                f"<tr><td>{_fmt(row['multiplier'])}x</td><td>{_fmt(row['cost_bps_per_side'])}</td>"
                f"<td>{_fmt(row['gross_pnl']['value'])}</td><td>{_fmt(row['total_cost']['value'])}"
                f"</td><td>{_fmt(row['net_pnl']['value'])}</td>"
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
            f"<tr><td>{_e(flag['code'])}</td><td>{_badge(flag['severity'])}</td>"
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
            f"<div class='lockbox'><p>{_e(labels['locked_intro'])}:</p><ul>"
            + "".join(f"<li>{_e(title)}</li>" for title, _ in detail)
            + f"</ul>{paybox}</div>"
        )
    else:
        detail_html = "".join(
            f"<section class='detail'><h2>{_e(title)}</h2>{body}</section>"
            for title, body in detail
        )

    watermark_html = ""
    if watermark:
        text = WATERMARK_TEXT.get(locale, WATERMARK_TEXT["es"])
        watermark_html = (
            f"<div class='watermark'>{_e(text)}</div><div class='banner'>{_e(text)}</div>"
        )

    toolbar = (
        "<div class='nav-end no-print'><button type='button' class='print-btn' "
        f"onclick='window.print()'>{_e(labels['print'])}</button>"
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
        f"<span>{_e(labels['generated'])} {_e(data['generated_at_utc'])}</span>"
        f"<span>engine {_e(engine['name'])} {_e(engine['package_version'])}</span>"
        f"<span>seed {_e(engine['seed'])}</span>"
    )
    hero = (
        "<section class='report-hero'>"
        + aurora()
        + grid_bg()
        + "<div class='wrap wrap-mid'>"
        + watermark_html
        + (f"<div class='notice'>{_e(notice)}</div>" if notice else "")
        + f"<div class='eyebrow rise'><span class='dot'></span>{_e(labels['title'])}</div>"
        + f"<h1 class='rise' style='--i:1'>{_e(labels['verdict'])} {_e(verdict['overall'])}</h1>"
        + f"<div class='meta-line rise' style='--i:2'>{meta}</div>"
        + "<div class='verdict rise' style='--i:3'>"
        + class_ring(str(verdict["overall"]), size="lg")
        + f"<div><div class='verdict-k'>{_e(labels['verdict'])}</div>"
        f"<p class='verdict-text'>{_e(verdict['summary'])}</p></div></div>"
        + ("" if locked else paybox)
        + "</div></section>"
    )

    def section(title: str, content: str) -> str:
        return f"<section class='rsec'><h2>{_e(title)}</h2>{content}</section>"

    footer = (
        "<div class='report-foot'>"
        f"<div class='disclaimer'><strong>{_e(labels['disclaimer'])}.</strong> "
        f"{_e(DISCLAIMER.get(locale, DISCLAIMER['es']))}</div>"
        f"<p class='muted'>{_e(labels['json_sha'])}: <code>{_e(result_sha256(result))}</code></p>"
        + (legal_links_html(locale) if legal_links else "")
        + f"<p class='muted'>{_e(BRAND)} · {_e(TAGLINE.get(locale, TAGLINE['es']))}</p></div>"
    )
    sections = [
        section(labels["meaning"], _meaning_html(verdict, locale)),
        section(labels["charts"], _charts_html(data, locale)),
        section(labels["flags_free"], _flags_free_html(data["red_flags"], locale, labels)),
        section(labels["plan"], _plan_html(data, locale, labels, locked=True)) if locked else "",
        detail_html,
        publish_html,
        section(labels["inputs"], inputs_html + _source_html(data, labels)),
        section(labels["declared"], declared_html),
        section(labels["not_measured"], nm_html),
        section(labels["seal"], seal_html),
        footer,
    ]
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
        + "</style>"
        + SCRIPT_TAG
        + "</head><body>"
        + header
        + hero
        + "<main id='main' class='paper report-main'><div class='wrap wrap-mid'>"
        + "".join(sections)
        + "</div></main></body></html>"
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
