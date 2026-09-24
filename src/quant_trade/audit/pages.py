"""Static HTML for the audit service: landing, upload form, error page.

Plain strings with ``html.escape`` on every dynamic value, no template
engine, no JavaScript. The copy avoids every profit-claim pattern the guard
knows; the test suite runs the guard over these pages.
"""

from __future__ import annotations

import html
from typing import Any

from quant_trade.audit.prop_presets import DEFAULT_PRESET, PRESETS
from quant_trade.audit.report import DISCLAIMER

_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:auto;padding:24px;
color:#1a1a1a;background:#fff;max-width:820px;line-height:1.5}
h1{font-size:1.9rem;margin:.3em 0}h2{font-size:1.2rem;margin-top:1.6em}
form{border:1px solid #ddd;border-radius:8px;padding:16px 20px;margin:1em 0}
label{display:block;margin:.6em 0 .2em;font-weight:600;font-size:.95rem}
input[type=text],input[type=number],input[type=email],input[type=date],select,textarea{
width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid #bbb;border-radius:5px}
input[type=file]{margin:.2em 0}
button{background:#1b5e20;color:#fff;border:0;padding:10px 16px;border-radius:6px;
font-weight:600;cursor:pointer;margin-top:1em}
.muted{color:#666;font-size:.9rem}.flash{background:#e3f2e6;color:#1b5e20;padding:8px 12px;
border-radius:6px;margin:.6em 0}.error{background:#fde2e1;color:#8b1a10;padding:8px 12px;
border-radius:6px;margin:.6em 0}.disclaimer{background:#f7f7f7;border-left:4px solid #999;
padding:10px 14px;margin:1.6em 0;font-size:.9rem}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}
@media (max-width:640px){.grid{grid-template-columns:1fr}}
"""

_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "title": "Auditoría de backtests",
        "headline": "Sube tu backtest. Te decimos si es estadísticamente real.",
        "pitch": (
            "La mayoría de los backtests que lucen bien en papel fallan en real por sobreajuste, "
            "costes no contados o datos con errores. Esta auditoría aplica los estimadores de "
            "Bailey y López de Prado (Sharpe probabilístico, Sharpe deflactado por número de "
            "intentos, bootstrap estacionario) a la curva que subes y te devuelve un veredicto "
            "con cada número etiquetado según su evidencia."
        ),
        "measure_title": "Qué medimos",
        "measure": [
            "Si el Sharpe se distingue de cero dada la longitud, la asimetría y la curtosis.",
            "Cuánto sobrevive después de descontar el número de intentos que declaras.",
            "Qué pasa a 1x, 2x y 3x el coste de operación, y el coste de equilibrio.",
            "Si el tramo fuera de muestra que declaras aguanta.",
            "Catorce banderas rojas de calidad de datos: duplicados, picos, marcas congeladas.",
            "Comparación con el benchmark que aportes, si aportas uno.",
        ],
        "not_title": "Qué no hacemos",
        "not": (
            "No ejecutamos operaciones, no custodiamos fondos ni claves, no recomendamos "
            "estrategias y no predecimos resultados. Auditamos el archivo que subes."
        ),
        "form_title": "Solicitar una auditoría",
        "report": "Informe de tu plataforma (recomendado)",
        "report_help": (
            "El archivo tal cual: informe HTML del probador o del historial de MetaTrader 5 o 4, "
            "lista de operaciones de TradingView (CSV o XLSX), o el CSV de operaciones de "
            "NinjaTrader, QuantConnect, backtesting.py o vectorbt. Hasta 5 MB."
        ),
        "optimization": "Exportación de optimización de MT5 (XML, opcional)",
        "optimization_help": (
            "Cuenta las configuraciones que probaste: el Sharpe deflactado usa ese número real."
        ),
        "equity": "Curva de equity o serie de retornos (CSV; obligatoria si no subes un informe)",
        "equity_help": "Columnas: timestamp y equity (o return). Hasta 5 MB.",
        "initial_balance": "Balance inicial (si el informe no lo indica)",
        "challenge": "Reto de prop firm a simular",
        "trades": "Operaciones cerradas (CSV, opcional)",
        "trades_help": "entry_time, exit_time, quantity, entry_price, exit_price, side.",
        "benchmark": "Benchmark (CSV, opcional)",
        "variants": "Matriz de variantes (CSV, opcional)",
        "variants_help": "Una columna de retornos por variante probada; habilita el PBO.",
        "trials": "Intentos probados antes de elegir esta versión",
        "cost_bps": "Coste por lado en puntos básicos (comisión + deslizamiento)",
        "oos_start": "Inicio del tramo fuera de muestra (opcional)",
        "benchmark_applicable": "¿Aplica un benchmark?",
        "yes": "Sí",
        "no": "No",
        "locale": "Idioma del informe",
        "description": "Descripción (opcional, no se publica en el informe)",
        "consent": (
            "Entiendo que esto es una herramienta de investigación estadística, no asesoría "
            "de inversión, y que el archivo se borra a los 30 días si no se paga."
        ),
        "submit": "Auditar",
        "free_note": "Modo gratuito: el informe completo se entrega con marca de agua.",
        "paid_note": "Vista previa gratuita; el informe completo cuesta USD {price:.0f}.",
        "waitlist_title": "Avísame cuando haya novedades",
        "email": "Correo",
        "join": "Apuntarme",
        "joined": "Apuntado. Gracias.",
        "error_title": "No se pudo auditar",
        "back": "Volver",
        "disclaimer": "Aviso",
    },
    "en": {
        "title": "Backtest audit",
        "headline": "Upload your backtest. We tell you whether it is statistically real.",
        "pitch": (
            "Most backtests that look good on paper fail live through overfitting, uncounted "
            "costs or broken data. This audit applies the Bailey and López de Prado estimators "
            "(probabilistic Sharpe, Sharpe deflated by the number of trials, stationary "
            "bootstrap) to the curve you upload and returns a verdict with every number "
            "labelled by its evidence."
        ),
        "measure_title": "What we measure",
        "measure": [
            "Whether the Sharpe ratio is distinguishable from zero given length, skew and "
            "kurtosis.",
            "How much survives after discounting the number of trials you declare.",
            "What happens at 1x, 2x and 3x the trading cost, and the break-even cost.",
            "Whether the out-of-sample window you declare holds up.",
            "Fourteen data-quality red flags: duplicates, spikes, frozen marks.",
            "A comparison against the benchmark you supply, if you supply one.",
        ],
        "not_title": "What we do not do",
        "not": (
            "We execute no trades, hold no funds or keys, recommend no strategies and predict "
            "no results. We audit the file you upload."
        ),
        "form_title": "Request an audit",
        "report": "Your platform report (recommended)",
        "report_help": (
            "The file as it is: a MetaTrader 5 or 4 tester or history HTML report, a "
            "TradingView list of trades (CSV or XLSX), or the trades CSV of NinjaTrader, "
            "QuantConnect, backtesting.py or vectorbt. Up to 5 MB."
        ),
        "optimization": "MT5 optimisation export (XML, optional)",
        "optimization_help": (
            "Counts the configurations you tried: the deflated Sharpe uses that real number."
        ),
        "equity": "Equity curve or return series (CSV; required without a report)",
        "equity_help": "Columns: timestamp and equity (or return). Up to 5 MB.",
        "initial_balance": "Starting balance (if the report does not state it)",
        "challenge": "Prop-firm challenge to simulate",
        "trades": "Closed trades (CSV, optional)",
        "trades_help": "entry_time, exit_time, quantity, entry_price, exit_price, side.",
        "benchmark": "Benchmark (CSV, optional)",
        "variants": "Variant matrix (CSV, optional)",
        "variants_help": "One return column per variant tried; enables the PBO.",
        "trials": "Trials tried before choosing this version",
        "cost_bps": "Cost per side in basis points (commission + slippage)",
        "oos_start": "Out-of-sample start (optional)",
        "benchmark_applicable": "Does a benchmark apply?",
        "yes": "Yes",
        "no": "No",
        "locale": "Report language",
        "description": "Description (optional, never shown in the report)",
        "consent": (
            "I understand this is a statistical research tool, not investment advice, and that "
            "the file is deleted after 30 days if unpaid."
        ),
        "submit": "Audit",
        "free_note": "Free mode: the full report is delivered with a watermark.",
        "paid_note": "Free preview; the full report costs USD {price:.0f}.",
        "waitlist_title": "Tell me when there is news",
        "email": "E-mail",
        "join": "Join",
        "joined": "Joined. Thank you.",
        "error_title": "Could not audit",
        "back": "Back",
        "disclaimer": "Notice",
    },
}


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _preset_options() -> str:
    options = []
    for key in sorted(PRESETS):
        rules = PRESETS[key]
        selected = " selected" if key == DEFAULT_PRESET else ""
        label = f"{rules.firm} · {rules.program} · {rules.phase}"
        options.append(f"<option value='{_e(key)}'{selected}>{_e(label)}</option>")
    return "".join(options)


def _head(title: str, locale: str) -> str:
    return (
        f"<!doctype html><html lang='{_e(locale)}'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
    )


def _footer(locale: str) -> str:
    copy = _COPY[locale]
    return (
        f"<div class='disclaimer'><strong>{_e(copy['disclaimer'])}.</strong> "
        f"{_e(DISCLAIMER[locale])}</div></body></html>"
    )


def landing(
    *,
    locale: str = "es",
    free_mode: bool = True,
    price_usd: float = 0.0,
    joined: bool = False,
    error: str | None = None,
) -> str:
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    other = "en" if locale == "es" else "es"
    note = copy["free_note"] if free_mode else copy["paid_note"].format(price=price_usd)
    measure = "".join(f"<li>{_e(item)}</li>" for item in copy["measure"])
    flash = f"<div class='flash'>{_e(copy['joined'])}</div>" if joined else ""
    err = f"<div class='error'>{_e(error)}</div>" if error else ""
    selected = {"es": "", "en": ""}
    selected[locale] = " selected"
    return (
        _head(copy["title"], locale)
        + f"<p class='muted'><a href='/?lang={other}'>{'English' if locale == 'es' else 'Español'}"
        "</a></p>"
        + f"<h1>{_e(copy['headline'])}</h1><p>{_e(copy['pitch'])}</p>"
        + f"<h2>{_e(copy['measure_title'])}</h2><ul>{measure}</ul>"
        + f"<h2>{_e(copy['not_title'])}</h2><p>{_e(copy['not'])}</p>"
        + f"<h2>{_e(copy['form_title'])}</h2>{flash}{err}<p class='muted'>{_e(note)}</p>"
        + "<form method='post' action='/audits' enctype='multipart/form-data'>"
        + f"<label>{_e(copy['report'])}</label><input type='file' name='report' "
        "accept='.htm,.html,.csv,.xlsx,.txt'>"
        + f"<div class='muted'>{_e(copy['report_help'])}</div>"
        + f"<label>{_e(copy['optimization'])}</label><input type='file' name='optimization' "
        "accept='.xml'>"
        + f"<div class='muted'>{_e(copy['optimization_help'])}</div>"
        + f"<label>{_e(copy['equity'])}</label><input type='file' name='equity' "
        "accept='.csv,text/csv'>"
        + f"<div class='muted'>{_e(copy['equity_help'])}</div>"
        + f"<label>{_e(copy['trades'])}</label><input type='file' name='trades' "
        "accept='.csv,text/csv'>"
        + f"<div class='muted'>{_e(copy['trades_help'])}</div>"
        + "<div class='grid'>"
        + f"<div><label>{_e(copy['benchmark'])}</label><input type='file' name='benchmark' "
        "accept='.csv,text/csv'></div>"
        + f"<div><label>{_e(copy['variants'])}</label><input type='file' name='variants' "
        f"accept='.csv,text/csv'><div class='muted'>{_e(copy['variants_help'])}</div></div>"
        + f"<div><label>{_e(copy['trials'])}</label><input type='number' name='trials' min='1' "
        "value='1' required></div>"
        + f"<div><label>{_e(copy['cost_bps'])}</label><input type='number' name='cost_bps' "
        "min='0' step='0.1' value='5'></div>"
        + f"<div><label>{_e(copy['oos_start'])}</label><input type='date' name='oos_start'></div>"
        + f"<div><label>{_e(copy['benchmark_applicable'])}</label>"
        f"<select name='benchmark_applicable'><option value='yes'>{_e(copy['yes'])}</option>"
        f"<option value='no'>{_e(copy['no'])}</option></select></div>"
        + f"<div><label>{_e(copy['initial_balance'])}</label><input type='number' "
        "name='initial_balance' min='0' step='0.01'></div>"
        + f"<div><label>{_e(copy['challenge'])}</label><select name='challenge'>"
        + _preset_options()
        + "</select></div>"
        + f"<div><label>{_e(copy['locale'])}</label><select name='locale'>"
        f"<option value='es'{selected['es']}>Español</option>"
        f"<option value='en'{selected['en']}>English</option></select></div>"
        + "</div>"
        + f"<label>{_e(copy['description'])}</label><textarea name='description' rows='3' "
        "maxlength='2000'></textarea>"
        + f"<label><input type='checkbox' name='consent' value='on' required> {_e(copy['consent'])}"
        "</label>"
        + f"<button type='submit'>{_e(copy['submit'])}</button></form>"
        + f"<h2>{_e(copy['waitlist_title'])}</h2><form method='post' action='/waitlist'>"
        f"<label>{_e(copy['email'])}</label><input type='email' name='email' required>"
        f"<input type='hidden' name='lang' value='{_e(locale)}'>"
        f"<button type='submit'>{_e(copy['join'])}</button></form>" + _footer(locale)
    )


def error_page(message: str, *, locale: str = "es") -> str:
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    return (
        _head(copy["error_title"], locale)
        + f"<h1>{_e(copy['error_title'])}</h1><div class='error'>{_e(message)}</div>"
        + f"<p><a href='/?lang={_e(locale)}'>{_e(copy['back'])}</a></p>"
        + _footer(locale)
    )


__all__ = ["error_page", "landing"]
