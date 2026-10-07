"""Localised form and report copy for client-declared periodic return series."""

from __future__ import annotations

import html
import math
from typing import Any

from quant_trade.audit.period_analysis import REASONS

SERIES_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "title": "Serie de rendimientos por periodo",
        "intro": (
            "Para una serie con fecha y rendimiento, confirma la frecuencia y la unidad. "
            "La frecuencia, la unidad y las etiquetas bruto/neto son DECLARED; las cifras "
            "calculadas desde el archivo son MEASURED."
        ),
        "frequency": "Frecuencia de la serie",
        "frequency_auto": "Inferir de las fechas (DECLARED)",
        "frequencies": {"daily": "Diaria", "weekly": "Semanal", "monthly": "Mensual"},
        "unit": "Unidad de los rendimientos",
        "unit_help": (
            "Los porcentajes pequeños sin el signo % pueden confundirse con fracciones. "
            "Confirma la unidad; la detección automática es DECLARED."
        ),
        "unit_auto": "Detectar desde el archivo (DECLARED)",
        "units": {"fraction": "Fracción", "percent": "Porcentaje"},
        "ppy": "Periodos por año",
        "basis": "Serie utilizada",
        "bases": {
            "return": "Rendimiento",
            "gross_return": "Bruto",
            "net_return": "Neto",
            "gross": "Bruto",
            "net": "Neto",
        },
        "confirmed": "Frecuencia confirmada en el formulario",
        "unit_confirmed": "Unidad confirmada en el formulario",
        "unit_no": "Detectada del archivo; pendiente de confirmación",
        "yes": "Sí",
        "no": "Inferida de las fechas; pendiente de confirmación",
        "benchmark_source": "Fuente del benchmark",
        "sources": {
            "uploaded file": "Archivo aportado",
            "embedded column": "Columna del archivo aportado",
            "not supplied": "No aportado",
        },
        "benchmark_ppy": "Periodos por año del benchmark",
        "benchmark_mismatch": (
            "La frecuencia del benchmark difiere de la serie; la comparación no se mide."
        ),
        "gross": "Serie bruta",
        "net": "Serie neta",
        "total_return": "Cambio acumulado de la serie",
        "sharpe": "Sharpe anualizado",
        "costs": "Sensibilidad a la diferencia declarada entre bruto y neto",
        "cost_note": (
            "El estrés se deriva de la diferencia declarada entre bruto y neto. No mide "
            "costos de operación individuales ni reconstruye operaciones."
        ),
        "cost_basis": "Referencia de costo",
        "cost_difference": "Rendimiento bruto menos rendimiento neto",
        "multiplier": "Multiplicador de la diferencia",
        "cost_missing": "Faltan series bruta y neta comparables para medir esta sensibilidad.",
        "missing": "No medido",
        "calculator": "Abrir la calculadora con esta frecuencia",
        "institutional_title": "¿Tienes una señal o cartera modelo con reglas fijas?",
        "institutional_text": (
            "Rigor audita la serie de rendimientos: significación, Sharpe deflactado por "
            "intentos, fuera de muestra, calidad de datos y comparación contra tu benchmark. "
            "Cada cifra, Medida o Declarada."
        ),
        "contact": "Contactar",
    },
    "en": {
        "title": "Periodic return series",
        "intro": (
            "For a series with a date and return, confirm the frequency and unit. Frequency, "
            "unit and gross/net labels are DECLARED; figures computed from the file are MEASURED."
        ),
        "frequency": "Series frequency",
        "frequency_auto": "Infer from dates (DECLARED)",
        "frequencies": {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"},
        "unit": "Return unit",
        "unit_help": (
            "Small percentages without a % sign can be confused with fractions. "
            "Confirm the unit; automatic detection is DECLARED."
        ),
        "unit_auto": "Detect from the file (DECLARED)",
        "units": {"fraction": "Fraction", "percent": "Percentage"},
        "ppy": "Periods per year",
        "basis": "Series used",
        "bases": {
            "return": "Return",
            "gross_return": "Gross",
            "net_return": "Net",
            "gross": "Gross",
            "net": "Net",
        },
        "confirmed": "Frequency confirmed in the form",
        "unit_confirmed": "Unit confirmed in the form",
        "unit_no": "Detected from the file; awaiting confirmation",
        "yes": "Yes",
        "no": "Inferred from dates; awaiting confirmation",
        "benchmark_source": "Benchmark source",
        "sources": {
            "uploaded file": "Uploaded file",
            "embedded column": "Column in the uploaded file",
            "not supplied": "Not supplied",
        },
        "benchmark_ppy": "Benchmark periods per year",
        "benchmark_mismatch": (
            "The benchmark frequency differs from the series; the comparison is not measured."
        ),
        "gross": "Gross series",
        "net": "Net series",
        "total_return": "Cumulative series change",
        "sharpe": "Annualised Sharpe",
        "costs": "Sensitivity to the declared gross/net difference",
        "cost_note": (
            "The stress derives from the declared gross/net difference. It does not measure "
            "individual trading costs or reconstruct trades."
        ),
        "cost_basis": "Cost reference",
        "cost_difference": "Gross return minus net return",
        "multiplier": "Difference multiplier",
        "cost_missing": "Comparable gross and net series are needed to measure this sensitivity.",
        "missing": "Not measured",
        "calculator": "Open the calculator with this frequency",
        "institutional_title": "Do you have a signal or model portfolio with fixed rules?",
        "institutional_text": (
            "Rigor audits the return series: significance, Sharpe deflated by trials, "
            "out-of-sample, data quality and comparison against your benchmark. "
            "Every figure, Measured or Declared."
        ),
        "contact": "Contact us",
    },
    "pt": {
        "title": "Série de retornos por período",
        "intro": (
            "Para uma série com data e retorno, confirme a frequência e a unidade. A frequência, "
            "a unidade e os rótulos bruto/líquido são DECLARED; os números calculados a partir "
            "do arquivo são MEASURED."
        ),
        "frequency": "Frequência da série",
        "frequency_auto": "Inferir pelas datas (DECLARED)",
        "frequencies": {"daily": "Diária", "weekly": "Semanal", "monthly": "Mensal"},
        "unit": "Unidade dos retornos",
        "unit_help": (
            "Porcentagens pequenas sem o sinal % podem ser confundidas com frações. "
            "Confirme a unidade; a detecção automática é DECLARED."
        ),
        "unit_auto": "Detectar pelo arquivo (DECLARED)",
        "units": {"fraction": "Fração", "percent": "Porcentagem"},
        "ppy": "Períodos por ano",
        "basis": "Série utilizada",
        "bases": {
            "return": "Retorno",
            "gross_return": "Bruto",
            "net_return": "Líquido",
            "gross": "Bruto",
            "net": "Líquido",
        },
        "confirmed": "Frequência confirmada no formulário",
        "unit_confirmed": "Unidade confirmada no formulário",
        "unit_no": "Detectada pelo arquivo; aguardando confirmação",
        "yes": "Sim",
        "no": "Inferida pelas datas; aguardando confirmação",
        "benchmark_source": "Fonte do benchmark",
        "sources": {
            "uploaded file": "Arquivo enviado",
            "embedded column": "Coluna do arquivo enviado",
            "not supplied": "Não enviado",
        },
        "benchmark_ppy": "Períodos por ano do benchmark",
        "benchmark_mismatch": (
            "A frequência do benchmark difere da série; a comparação não é medida."
        ),
        "gross": "Série bruta",
        "net": "Série líquida",
        "total_return": "Variação acumulada da série",
        "sharpe": "Sharpe anualizado",
        "costs": "Sensibilidade à diferença declarada entre bruto e líquido",
        "cost_note": (
            "O estresse deriva da diferença declarada entre bruto e líquido. Não mede "
            "custos de operação individuais nem reconstrói operações."
        ),
        "cost_basis": "Referência de custo",
        "cost_difference": "Retorno bruto menos retorno líquido",
        "multiplier": "Multiplicador da diferença",
        "cost_missing": "Faltam séries bruta e líquida comparáveis para medir esta sensibilidade.",
        "missing": "Não medido",
        "calculator": "Abrir a calculadora com esta frequência",
        "institutional_title": "Você tem um sinal ou uma carteira modelo com regras fixas?",
        "institutional_text": (
            "Rigor audita a série de retornos: significância, Sharpe deflacionado por "
            "tentativas, fora da amostra, qualidade dos dados e comparação com seu benchmark. "
            "Cada número, Medido ou Declarado."
        ),
        "contact": "Entrar em contato",
    },
}


def _copy(locale: str) -> dict[str, Any]:
    return SERIES_COPY.get(locale, SERIES_COPY["es"])


def _badge(tag: str) -> str:
    return f"<span class='badge {tag}'>{tag}</span>"


def series_fields(locale: str) -> str:
    """Optional declarations for periodic-return uploads; empty values mean inference."""
    copy = _copy(locale)
    fields = []
    for name, label, automatic, values in (
        ("return_frequency", "frequency", "frequency_auto", "frequencies"),
        ("return_unit", "unit", "unit_auto", "units"),
    ):
        options = f"<option value=''>{html.escape(copy[automatic])}</option>"
        options += "".join(
            f"<option value='{html.escape(value)}'>{html.escape(text)} (DECLARED)</option>"
            for value, text in copy[values].items()
        )
        help_text = (
            f"<p class='help' id='{name}-help'>{html.escape(copy['unit_help'])}</p>"
            if name == "return_unit"
            else ""
        )
        described = f" aria-describedby='{name}-help'" if help_text else ""
        fields.append(
            f"<label for='{name}'>{html.escape(copy[label])} {_badge('DECLARED')}</label>"
            f"<select id='{name}' name='{name}'{described}>{options}</select>{help_text}"
        )
    return (
        "<fieldset class='return-series-fields'>"
        f"<legend>{html.escape(copy['title'])}</legend><p>{html.escape(copy['intro'])}</p>"
        + "".join(fields)
        + "</fieldset>"
    )


def _raw(item: Any) -> Any:
    return item.get("value") if isinstance(item, dict) else None


def _value(item: Any, copy: dict[str, Any], *, percent: bool = False) -> str:
    value = _raw(item)
    tag = item.get("evidence") if isinstance(item, dict) else None
    if (
        tag not in {"DECLARED", "MEASURED"}
        or isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
    ):
        return f"{html.escape(copy['missing'])} {_badge('NOT_MEASURED')}"
    shown = f"{value * 100:.2f}%" if percent else f"{value:,.4g}"
    return f"{shown} {_badge(tag)}"


def _coded(item: Any, names: dict[str, str], copy: dict[str, Any]) -> str:
    code = _raw(item)
    if not isinstance(code, str) or code not in names:
        return f"{html.escape(copy['missing'])} {_badge('NOT_MEASURED')}"
    return f"{html.escape(names[code])} {_badge('DECLARED')}"


def series_report(data: dict[str, Any], locale: str) -> str:
    """Render only return-series metadata and metrics, never a client description."""
    inputs = data.get("inputs", {})
    series = inputs.get("return_series") if isinstance(inputs, dict) else None
    if not isinstance(series, dict):
        return ""
    copy = _copy(locale)
    rows = []
    for key, names in (
        ("frequency", "frequencies"),
        ("unit", "units"),
        ("basis", "bases"),
        ("benchmark_source", "sources"),
    ):
        rows.append((copy[key], _coded(series.get(key), copy[names], copy)))
    rows.append((copy["ppy"], _value(series.get("periods_per_year"), copy)))
    confirmed = _raw(series.get("frequency_confirmed"))
    if isinstance(confirmed, bool):
        rows.append(
            (
                copy["confirmed"],
                html.escape(copy["yes" if confirmed else "no"]) + _badge("DECLARED"),
            )
        )
    unit_confirmed = _raw(series.get("unit_confirmed"))
    if isinstance(unit_confirmed, bool):
        rows.append(
            (
                copy["unit_confirmed"],
                html.escape(copy["yes" if unit_confirmed else "unit_no"]) + _badge("DECLARED"),
            )
        )
    benchmark_ppy = series.get("benchmark_periods_per_year")
    if isinstance(benchmark_ppy, dict):
        rows.append((copy["benchmark_ppy"], _value(benchmark_ppy, copy)))
    parts = [
        "<section id='return-series' class='card'>",
        f"<h2>{html.escape(copy['title'])}</h2><p>{html.escape(copy['intro'])}</p>",
        "<dl>" + "".join(f"<dt>{html.escape(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>",
    ]
    for name in ("gross", "net"):
        metrics = series.get(name)
        if isinstance(metrics, dict):
            parts.append(f"<h3>{html.escape(copy[name])} {_badge('DECLARED')}</h3><dl>")
            if "unit" in metrics:
                parts.append(
                    f"<dt>{html.escape(copy['unit'])}</dt>"
                    f"<dd>{_coded(metrics['unit'], copy['units'], copy)}</dd>"
                )
            for key in ("total_return", "sharpe"):
                parts.append(
                    f"<dt>{html.escape(copy[key])}</dt>"
                    f"<dd>{_value(metrics.get(key), copy, percent=key == 'total_return')}</dd>"
                )
            parts.append("</dl>")
    ppy = _raw(series.get("periods_per_year"))
    bench_ppy = _raw(benchmark_ppy)
    if isinstance(bench_ppy, (float, int)) and ppy != bench_ppy:
        parts.append(f"<p>{html.escape(copy['benchmark_mismatch'])} {_badge('NOT_MEASURED')}</p>")
    costs = data.get("costs", {})
    if isinstance(costs, dict) and costs.get("kind") == "period_returns":
        parts.extend(
            [f"<h3>{html.escape(copy['costs'])}</h3>", f"<p>{html.escape(copy['cost_note'])}</p>"]
        )
        reference = costs.get("reference_basis")
        if _raw(reference) == "gross_return - net_return":
            parts.append(
                f"<p>{html.escape(copy['cost_basis'])}: "
                f"{html.escape(copy['cost_difference'])} {_badge('DECLARED')}</p>"
            )
        if costs.get("status") == "MEASURED":
            parts.append(
                "<table><thead><tr>"
                + "".join(
                    f"<th scope='col'>{html.escape(copy[key])}</th>"
                    for key in ("multiplier", "total_return", "sharpe")
                )
                + "</tr></thead><tbody>"
            )
            for row in costs.get("rows", []):
                if isinstance(row, dict):
                    parts.append(
                        f"<tr><td>{_value(row.get('multiplier'), copy)}</td>"
                        f"<td>{_value(row.get('total_return'), copy, percent=True)}</td>"
                        f"<td>{_value(row.get('sharpe_annualised'), copy)}</td></tr>"
                    )
            parts.append("</tbody></table>")
        else:
            reason = next(
                (
                    names.get(locale, names["es"])
                    for names in REASONS.values()
                    if names["en"] == costs.get("reason")
                ),
                copy["cost_missing"],
            )
            parts.append(f"<p>{html.escape(reason)} {_badge('NOT_MEASURED')}</p>")
    if ppy in (252, 52, 12):
        from quant_trade.audit.calculator import calculator_url

        url = f"{calculator_url(locale)}?periods_per_year={int(ppy)}"
        parts.append(f"<p><a href='{html.escape(url)}'>{html.escape(copy['calculator'])}</a></p>")
    parts.append("</section>")
    return "".join(parts)


def institutional_block(locale: str, contact_url: str) -> str:
    """A concise institutional audience entry point to the existing contact form."""
    copy = _copy(locale)
    return (
        "<section class='card institutional' id='institutional'>"
        f"<h2>{html.escape(copy['institutional_title'])}</h2>"
        f"<p>{html.escape(copy['institutional_text'])}</p>"
        f"<a class='button' href='{html.escape(contact_url, quote=True)}'>"
        f"{html.escape(copy['contact'])}</a></section>"
    )
