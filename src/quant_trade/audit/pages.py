"""Static HTML for the audit service: landing, upload form, error page, the
public verification page and its badge.

Plain strings with ``html.escape`` on every dynamic value, no template
engine, no JavaScript. The copy avoids every profit-claim pattern the guard
knows; the test suite runs the guard over these pages.
"""

from __future__ import annotations

import html
from typing import Any

from quant_trade.audit.guides import (
    GUIDES,
    GUIDES_COPY,
    REPORT_GUIDES,
    Guide,
    guide_url,
    guides_index_url,
)
from quant_trade.audit.i18n import localize
from quant_trade.audit.legal import LegalText, legal_links_html, legal_url
from quant_trade.audit.prop_presets import DEFAULT_PRESET, PRESETS
from quant_trade.audit.report import DIMENSION_TITLES, DISCLAIMER, STATUS_TEXT
from quant_trade.audit.seo import PageMeta, head_meta, page_paths, private_meta
from quant_trade.audit.verdict import class_text, meaning

#: The fixed wording of the badge and of the verification page's notice. It
#: states what the audit is and denies what it is not; it never mentions
#: growth, return or profit. Changing it needs a test and a line in
#: docs/AUDIT_SAAS.md.
BADGE_NOTICE: dict[str, str] = {
    "es": (
        "Auditoría estadística de datos aportados – no verificados con el bróker – "
        "no garantiza resultados"
    ),
    "en": (
        "Statistical audit of supplied data – not verified with a broker – "
        "not a performance guarantee"
    ),
}

VERIFICATION_NOTICE: dict[str, str] = {
    "es": (
        "Esta página resume una auditoría estadística de datos que aportó el cliente, no "
        "verificados con el bróker. La clase describe la evidencia que había en el archivo "
        "auditado en la fecha indicada; no garantiza resultados futuros, no es asesoría de "
        "inversión y no avala a ningún vendedor ni producto. Los hashes permiten comprobar "
        "que un archivo es exactamente el que se auditó."
    ),
    "en": (
        "This page summarises a statistical audit of data the client supplied, not verified "
        "with a broker. The class describes the evidence in the audited file on the date "
        "shown; it is not a guarantee of future results, not investment advice and not an "
        "endorsement of any vendor or product. The hashes let anyone check that a file is "
        "exactly the one that was audited."
    ),
}

SAMPLE_BANNER: dict[str, str] = {
    "es": (
        "Informe de ejemplo con datos sintéticos generados por ordenador: no es la cuenta ni "
        "la estrategia de nadie. Así se ve un informe completo."
    ),
    "en": (
        "Sample report built from computer-generated synthetic data: it is nobody's account "
        "or strategy. This is what a full report looks like."
    ),
}

CLASS_COLOURS: dict[str, str] = {"A": "#1b5e20", "B": "#2e7d32", "C": "#b26a00", "D": "#8b1a10"}

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
table{border-collapse:collapse;width:100%;margin:.4em 0;font-size:.92rem}
th,td{border:1px solid #e3e3e3;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f5f5f5}code{font-size:.85em;word-break:break-all}
.cls{display:inline-block;font-size:2.4rem;font-weight:800;color:#fff;border-radius:8px;
padding:2px 16px;margin-right:12px;vertical-align:middle}
.status{display:inline-block;padding:1px 6px;border-radius:4px;font-size:.8rem;font-weight:600;
background:#eee;color:#333}.steps li{margin:.3em 0}
.prices{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.prices div{border:1px solid #ddd;border-radius:8px;padding:10px 14px}
@media (max-width:640px){.prices{grid-template-columns:1fr}}
details{border-bottom:1px solid #eee;padding:.4em 0}summary{font-weight:600;cursor:pointer}
pre{white-space:pre-wrap;word-break:break-all;background:#f7f7f7;padding:8px 10px;border-radius:6px}
@media (max-width:640px){.grid{grid-template-columns:1fr}}
img,svg{max-width:100%;height:auto}
@media (max-width:759px){body{padding:16px}table{display:block;overflow-x:auto}}
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
            "El archivo tal cual: informe HTML del probador o del historial de MetaTrader 5 o 4 "
            "(o el XLSX que exporta MetaTrader 5), "
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
            "de inversión, y que el archivo se borra a los {retention} días si no se paga. "
            "Acepto los términos del servicio y la política de privacidad."
        ),
        "consent_read": "Léelos antes de subir:",
        "terms_link": "Términos del servicio",
        "privacy_link": "Política de privacidad",
        "legal_updated": "Última actualización",
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
        "sample_link": "Ver un informe de ejemplo completo (datos sintéticos)",
        "meta_description": (
            "Sube el informe de MetaTrader, TradingView, NinjaTrader o Python y recibe un "
            "veredicto de A a D sobre sobreajuste, costes, fuera de muestra y calidad de datos, "
            "con cada número etiquetado según su evidencia."
        ),
        "sample_description": (
            "Informe completo de ejemplo de la auditoría de backtests, hecho con datos "
            "sintéticos: veredicto, gráficas, riesgo remuestreado y simulación de reto."
        ),
        "guides_title": "Qué archivo subir",
        "guides_text": (
            "Sube el archivo que ya guarda tu plataforma. Si no sabes cuál exportar, hay una "
            "guía corta para cada una."
        ),
        "guides_link": "Ver las guías de exportación",
        "guide_for": "¿Qué archivo exporto? Guía para",
        "optimization_guide": "Cómo exportar el XML de optimización",
        "v_description": "{cls_label} {overall} · auditada el {date} · {notice}.",
        "how_title": "Cómo funciona",
        "how": [
            "Sube el informe de tu plataforma tal cual y, si lo tienes, el XML de optimización.",
            "Recibe al momento la clase de A a D, las gráficas y qué significa cada dimensión "
            "en lenguaje llano.",
            "Si quieres todos los números, desbloquea el informe completo.",
            "Si quieres, publica una página de verificación con sello para compartirla.",
        ],
        "prices_title": "Precios",
        "price_free_title": "Vista previa: gratis",
        "price_free": (
            "Clase de A a D, explicación de cada dimensión, gráficas, banderas rojas y hashes."
        ),
        "price_full_title": "Informe completo: USD {price:.0f}",
        "price_full": (
            "Todo el detalle numérico sin marca de agua, simulador de reto, riesgo remuestreado, "
            "preguntas para el vendedor y página de verificación pública con sello."
        ),
        "price_free_mode": (
            "Ahora mismo el servicio está en modo gratuito: el informe completo se entrega con "
            "marca de agua y sin coste."
        ),
        "pay_card": "Pago con tarjeta desde el propio informe.",
        "pay_code": (
            "Pago por transferencia, Mercado Pago o WhatsApp: recibes un código de acceso y lo "
            "escribes en el formulario o en el informe."
        ),
        "contact": "Pedir un código",
        "faq_title": "Preguntas frecuentes",
        "faq": [
            (
                "¿Qué archivo subo?",
                "El informe de tu plataforma tal cual: MetaTrader 5 o 4 (HTML), TradingView "
                "(CSV o XLSX), NinjaTrader, QuantConnect, backtesting.py o vectorbt. También "
                "sirve una curva de equity en CSV.",
            ),
            (
                "¿Por qué subir el XML de optimización de MT5?",
                "Porque cuenta las configuraciones que probaste. Con ese número real, el Sharpe "
                "deflactado descuenta la suerte de haber elegido la mejor entre muchas.",
            ),
            (
                "¿Qué significan MEASURED, DECLARED y NOT_MEASURED?",
                "MEASURED se calculó desde tu archivo; DECLARED lo indicaste tú y no se pudo "
                "comprobar; NOT_MEASURED no se pudo calcular con lo que subiste.",
            ),
            (
                "¿Esto predice resultados o el desenlace de un reto de prop firm?",
                "No. Mide la evidencia estadística del archivo que subes. El simulador de retos "
                "y el riesgo remuestreado son estimaciones sobre tu propio historial, con sus "
                "supuestos escritos, no predicciones.",
            ),
            (
                "¿Comprobáis mis operaciones con el bróker?",
                "No. Auditamos los datos que aportas; no nos conectamos a ningún bróker ni "
                "pedimos claves. Por eso el sello dice que los datos no están comprobados con "
                "el bróker.",
            ),
            (
                "¿Qué pasa con mi archivo?",
                "Se guarda para poder regenerar tu informe. Si no pagas, se borra a los "
                "{retention} días y solo quedan la clase y los hashes. Nunca se publica: la "
                "página de verificación muestra la clase, las dimensiones y los hashes, y solo "
                "si tú la publicas.",
            ),
            (
                "¿Cómo se usa el sello?",
                "Publica la verificación desde tu informe y copia el código del sello en tu web, "
                "Telegram o foro. El sello describe una auditoría estadística; no es una promesa "
                "de resultados y no debe presentarse como tal.",
            ),
        ],
        "v_title": "Verificación pública de auditoría",
        "v_class": "Clase",
        "v_audited": "Fecha de la auditoría",
        "v_published": "Publicada",
        "v_dimensions": "Dimensiones",
        "v_dimension": "Dimensión",
        "v_status": "Resultado",
        "v_meaning": "Qué significa",
        "v_inputs": "Hashes de los archivos auditados (SHA-256)",
        "v_details": "Datos de la auditoría",
        "v_format": "Formato del archivo",
        "v_engine": "Motor",
        "v_trials_declared": "Intentos declarados",
        "v_trials_used": "Intentos usados en el Sharpe deflactado",
        "v_result_sha": "SHA-256 del resultado",
        "v_notice": "Aviso",
        "v_badge": "Sello para tu web",
        "v_badge_help": "Copia este código en tu web, Telegram o foro:",
        "access_code": "Código de acceso (opcional)",
        "access_code_help": "Si compraste un código, escríbelo y el informe nace completo.",
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
            "The file as it is: a MetaTrader 5 or 4 tester or history HTML report (or the "
            "XLSX MetaTrader 5 exports), a "
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
            "the file is deleted after {retention} days if unpaid. I accept the terms of service "
            "and the privacy policy."
        ),
        "consent_read": "Read them before uploading:",
        "terms_link": "Terms of service",
        "privacy_link": "Privacy policy",
        "legal_updated": "Last updated",
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
        "sample_link": "See a full sample report (synthetic data)",
        "meta_description": (
            "Upload your MetaTrader, TradingView, NinjaTrader or Python report and get an A to "
            "D verdict on overfitting, costs, out-of-sample and data quality, with every number "
            "tagged by its evidence."
        ),
        "sample_description": (
            "A full sample report of the backtest audit, built from synthetic data: verdict, "
            "charts, resampled risk and challenge simulation."
        ),
        "guides_title": "Which file to upload",
        "guides_text": (
            "Upload the file your platform already saves. If you are not sure which one to "
            "export, there is a short guide for each."
        ),
        "guides_link": "See the export guides",
        "guide_for": "Which file do I export? Guide for",
        "optimization_guide": "How to export the optimisation XML",
        "v_description": "{cls_label} {overall} · audited on {date} · {notice}.",
        "how_title": "How it works",
        "how": [
            "Upload your platform report as it is and, if you have it, the optimisation XML.",
            "Get the A to D class, the charts and what each dimension means in plain language "
            "right away.",
            "If you want every number, unlock the full report.",
            "If you want, publish a verification page with a badge to share it.",
        ],
        "prices_title": "Pricing",
        "price_free_title": "Preview: free",
        "price_free": ("A to D class, what each dimension means, charts, red flags and hashes."),
        "price_full_title": "Full report: USD {price:.0f}",
        "price_full": (
            "Every number without a watermark, challenge simulator, resampled risk, questions "
            "for the vendor and a public verification page with a badge."
        ),
        "price_free_mode": (
            "The service is in free mode right now: the full report is delivered with a "
            "watermark at no cost."
        ),
        "pay_card": "Card payment from the report itself.",
        "pay_code": (
            "Pay by bank transfer, Mercado Pago or WhatsApp: you receive an access code and "
            "enter it in the form or in the report."
        ),
        "contact": "Ask for a code",
        "faq_title": "Frequently asked questions",
        "faq": [
            (
                "Which file do I upload?",
                "Your platform report as it is: MetaTrader 5 or 4 (HTML), TradingView (CSV or "
                "XLSX), NinjaTrader, QuantConnect, backtesting.py or vectorbt. An equity curve "
                "in CSV works too.",
            ),
            (
                "Why upload the MT5 optimisation XML?",
                "Because it counts the configurations you tried. With that real number, the "
                "deflated Sharpe discounts the luck of picking the best of many.",
            ),
            (
                "What do MEASURED, DECLARED and NOT_MEASURED mean?",
                "MEASURED was computed from your file; DECLARED is what you stated and could not "
                "be checked; NOT_MEASURED could not be computed from what you uploaded.",
            ),
            (
                "Does this predict results or the outcome of a prop-firm challenge?",
                "No. It measures the statistical evidence in the file you upload. The challenge "
                "simulator and the resampled risk are estimates from your own history, with "
                "their assumptions written down, not predictions.",
            ),
            (
                "Do you check my trades with the broker?",
                "No. We audit the data you supply; we connect to no broker and ask for no keys. "
                "That is why the badge says the data was not checked with a broker.",
            ),
            (
                "What happens to my file?",
                "It is kept so your report can be regenerated. If unpaid it is deleted after "
                "{retention} days and only the class and the hashes remain. It is never "
                "published: the verification page shows the class, the dimensions and the "
                "hashes, and only if you publish it.",
            ),
            (
                "How is the badge used?",
                "Publish the verification from your report and copy the badge code to your "
                "site, Telegram or forum. The badge describes a statistical audit; it is not a "
                "promise of results and must not be presented as one.",
            ),
        ],
        "v_title": "Public audit verification",
        "v_class": "Class",
        "v_audited": "Audit date",
        "v_published": "Published",
        "v_dimensions": "Dimensions",
        "v_dimension": "Dimension",
        "v_status": "Result",
        "v_meaning": "What it means",
        "v_inputs": "Hashes of the audited files (SHA-256)",
        "v_details": "Audit details",
        "v_format": "File format",
        "v_engine": "Engine",
        "v_trials_declared": "Trials declared",
        "v_trials_used": "Trials used in the deflated Sharpe",
        "v_result_sha": "SHA-256 of the result",
        "v_notice": "Notice",
        "v_badge": "Badge for your site",
        "v_badge_help": "Copy this code to your site, Telegram or forum:",
        "access_code": "Access code (optional)",
        "access_code_help": "If you bought a code, enter it and the report is born complete.",
    },
}


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _preset_options(locale: str) -> str:
    options = []
    for key in sorted(PRESETS):
        rules = PRESETS[key]
        selected = " selected" if key == DEFAULT_PRESET else ""
        label = " · ".join(
            localize(part, locale) for part in (rules.firm, rules.program, rules.phase)
        )
        options.append(f"<option value='{_e(key)}'{selected}>{_e(label)}</option>")
    return "".join(options)


def _head(title: str, locale: str, meta_html: str = "") -> str:
    """The page head. ``meta_html`` comes from ``seo``; without it the page is
    private (``noindex``)."""
    meta_html = meta_html or private_meta(title, locale)
    return (
        f"<!doctype html><html lang='{_e(locale)}'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_e(title)}</title>{meta_html}<style>{_CSS}</style></head><body>"
    )


def _public_meta(title: str, description: str, locale: str, path: str, base_url: str) -> str:
    return head_meta(
        PageMeta(title=title, description=description, locale=locale, paths=page_paths(path)),
        base_url=base_url,
    )


def sample_meta(locale: str, base_url: str) -> str:
    """Head tags for the sample report, the one indexable report page."""
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    title = f"{copy['sample_link']} · {copy['title']}"
    path = "/ejemplo" if locale == "es" else "/sample"
    return _public_meta(title, copy["sample_description"], locale, path, base_url)


def _guide_links(locale: str) -> str:
    return " · ".join(
        f"<a href='{_e(guide_url(g.slug, locale))}'>{_e(g.platform)}</a>" for g in REPORT_GUIDES
    )


def _footer(locale: str) -> str:
    copy = _COPY[locale]
    return (
        f"<div class='disclaimer'><strong>{_e(copy['disclaimer'])}.</strong> "
        f"{_e(DISCLAIMER[locale])}</div>{legal_links_html(locale)}</body></html>"
    )


def landing(
    *,
    locale: str = "es",
    free_mode: bool = True,
    price_usd: float = 0.0,
    joined: bool = False,
    error: str | None = None,
    access_codes: bool = False,
    card_payments: bool = False,
    contact_url: str = "",
    retention_days: int = 30,
    base_url: str = "",
) -> str:
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    other = "en" if locale == "es" else "es"
    meta = _public_meta(
        copy["title"], copy["meta_description"], locale, "/" if locale == "es" else "/en", base_url
    )
    note = copy["free_note"] if free_mode else copy["paid_note"].format(price=price_usd)
    measure = "".join(f"<li>{_e(item)}</li>" for item in copy["measure"])
    sample = f"/ejemplo?lang={locale}" if locale == "es" else "/sample?lang=en"
    code_field = ""
    if access_codes:
        code_field = (
            f"<label>{_e(copy['access_code'])}</label><input type='text' name='access_code' "
            "maxlength='40' autocomplete='off' placeholder='AUD-XXXX-XXXX-XXXX'>"
            f"<div class='muted'>{_e(copy['access_code_help'])}</div>"
        )
    flash = f"<div class='flash'>{_e(copy['joined'])}</div>" if joined else ""
    err = f"<div class='error'>{_e(error)}</div>" if error else ""
    selected = {"es": "", "en": ""}
    selected[locale] = " selected"
    return (
        _head(copy["title"], locale, meta)
        + f"<p class='muted'><a href='/?lang={other}'>{'English' if locale == 'es' else 'Español'}"
        "</a></p>"
        + f"<h1>{_e(copy['headline'])}</h1><p>{_e(copy['pitch'])}</p>"
        + f"<h2>{_e(copy['measure_title'])}</h2><ul>{measure}</ul>"
        + f"<p><a href='{_e(sample)}'>{_e(copy['sample_link'])}</a></p>"
        + f"<h2>{_e(copy['not_title'])}</h2><p>{_e(copy['not'])}</p>"
        + _how_html(copy)
        + f"<h2>{_e(copy['guides_title'])}</h2><p>{_e(copy['guides_text'])} "
        f"<a href='{_e(guides_index_url(locale))}'>{_e(copy['guides_link'])}</a></p>"
        + _prices_html(
            copy,
            free_mode=free_mode,
            price_usd=price_usd,
            access_codes=access_codes,
            card_payments=card_payments,
            contact_url=contact_url,
        )
        + f"<h2 id='subir'>{_e(copy['form_title'])}</h2>{flash}{err}<p class='muted'>{_e(note)}</p>"
        + "<form method='post' action='/audits' enctype='multipart/form-data'>"
        + f"<label>{_e(copy['report'])}</label><input type='file' name='report' "
        "accept='.htm,.html,.csv,.xlsx,.txt'>"
        + f"<div class='muted'>{_e(copy['report_help'])}</div>"
        + f"<div class='muted'>{_e(copy['guide_for'])}: {_guide_links(locale)}</div>"
        + f"<label>{_e(copy['optimization'])}</label><input type='file' name='optimization' "
        "accept='.xml'>" + f"<div class='muted'>{_e(copy['optimization_help'])} "
        f"<a href='{_e(guide_url('mt5-optimization', locale))}'>"
        f"{_e(copy['optimization_guide'])}</a></div>"
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
        + _preset_options(locale)
        + "</select></div>"
        + f"<div><label>{_e(copy['locale'])}</label><select name='locale'>"
        f"<option value='es'{selected['es']}>Español</option>"
        f"<option value='en'{selected['en']}>English</option></select></div>"
        + "</div>"
        + code_field
        + f"<label>{_e(copy['description'])}</label><textarea name='description' rows='3' "
        "maxlength='2000'></textarea>"
        + f"<label><input type='checkbox' name='consent' value='on' required> "
        f"{_e(copy['consent'].format(retention=retention_days))}</label>"
        + f"<div class='muted'>{_e(copy['consent_read'])} "
        f"<a href='{_e(legal_url('terms', locale))}'>{_e(copy['terms_link'])}</a> · "
        f"<a href='{_e(legal_url('privacy', locale))}'>{_e(copy['privacy_link'])}</a></div>"
        + f"<button type='submit'>{_e(copy['submit'])}</button></form>"
        + f"<h2>{_e(copy['waitlist_title'])}</h2><form method='post' action='/waitlist'>"
        f"<label>{_e(copy['email'])}</label><input type='email' name='email' required>"
        f"<input type='hidden' name='lang' value='{_e(locale)}'>"
        f"<button type='submit'>{_e(copy['join'])}</button></form>"
        + _faq_html(copy, retention_days=retention_days)
        + _footer(locale)
    )


def _how_html(copy: dict[str, Any]) -> str:
    steps = "".join(f"<li>{_e(step)}</li>" for step in copy["how"])
    return f"<h2>{_e(copy['how_title'])}</h2><ol class='steps'>{steps}</ol>"


def _prices_html(
    copy: dict[str, Any],
    *,
    free_mode: bool,
    price_usd: float,
    access_codes: bool,
    card_payments: bool,
    contact_url: str,
) -> str:
    if free_mode:
        return f"<h2>{_e(copy['prices_title'])}</h2><p>{_e(copy['price_free_mode'])}</p>"
    ways = []
    if card_payments:
        ways.append(f"<li>{_e(copy['pay_card'])}</li>")
    if access_codes:
        link = (
            f" <a href='{_e(contact_url)}' rel='noopener'>{_e(copy['contact'])}</a>"
            if contact_url
            else ""
        )
        ways.append(f"<li>{_e(copy['pay_code'])}{link}</li>")
    return (
        f"<h2>{_e(copy['prices_title'])}</h2><div class='prices'>"
        f"<div><strong>{_e(copy['price_free_title'])}</strong><p>{_e(copy['price_free'])}</p>"
        "</div>"
        f"<div><strong>{_e(copy['price_full_title'].format(price=price_usd))}</strong>"
        f"<p>{_e(copy['price_full'])}</p></div></div>"
        + (f"<ul>{''.join(ways)}</ul>" if ways else "")
    )


def _faq_html(copy: dict[str, Any], *, retention_days: int) -> str:
    items = "".join(
        f"<details><summary>{_e(question)}</summary>"
        f"<p>{_e(answer.format(retention=retention_days))}</p></details>"
        for question, answer in copy["faq"]
    )
    return f"<h2>{_e(copy['faq_title'])}</h2>{items}"


def _evidence_value(item: Any) -> str:
    if isinstance(item, dict) and "value" in item:
        return f"{item.get('value')} ({item.get('evidence', '')})"
    return "-" if item is None else str(item)


def verification_page(
    result: dict[str, Any],
    *,
    public_id: str,
    published_at: str,
    result_sha256: str,
    base_url: str,
    locale: str = "es",
) -> str:
    """The public page of a published audit.

    Built from an allow-list of fields: class, dates, dimension statuses with
    their fixed plain-language text, input hashes, source format, engine,
    trial counts and a fixed notice. The description, trades, files and
    token are never read here, so they cannot leak.
    """
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    other = "en" if locale == "es" else "es"
    verdict = result["verdict"]
    overall = str(verdict["overall"])
    titles = DIMENSION_TITLES.get(locale, DIMENSION_TITLES["es"])
    statuses = STATUS_TEXT.get(locale, STATUS_TEXT["es"])
    rows = "".join(
        f"<tr><td>{_e(titles.get(d['name'], d['name']))}</td>"
        f"<td><span class='status'>{_e(statuses.get(d['status'], d['status']))}</span></td>"
        f"<td>{_e(meaning(d['name'], d['status'], locale))}</td></tr>"
        for d in verdict["dimensions"]
    )
    inputs = result.get("inputs", {})
    digests = dict(inputs.get("digests", {}))
    if inputs.get("dataset_digest"):
        digests["dataset_digest"] = inputs["dataset_digest"]
    digest_rows = "".join(
        f"<tr><td>{_e(name)}</td><td><code>{_e(value)}</code></td></tr>"
        for name, value in digests.items()
    )
    engine = result.get("engine", {})
    declared = result.get("declared", {})
    trials_used = result.get("multiplicity", {}).get("trials_used")
    details = [
        (copy["v_format"], inputs.get("source_format") or inputs.get("source") or "-"),
        (copy["v_engine"], f"{engine.get('name', '')} {engine.get('package_version', '')}"),
        (copy["v_trials_declared"], _evidence_value(declared.get("trials"))),
        (copy["v_trials_used"], _evidence_value(trials_used)),
        (copy["v_result_sha"], result_sha256),
    ]
    detail_rows = "".join(
        f"<tr><td>{_e(label)}</td><td><code>{_e(value)}</code></td></tr>"
        for label, value in details
    )
    page_url = f"{base_url}/v/{public_id}"
    badge_url = f"{page_url}/badge.svg?lang={locale}"
    snippet = (
        f"<a href='{page_url}'><img src='{badge_url}' alt='{BADGE_NOTICE[locale]}' "
        "width='480' height='72'></a>"
    )
    colour = CLASS_COLOURS.get(overall, "#333")
    title = f"{copy['v_title']} · {'Clase' if locale == 'es' else 'Class'} {overall}"
    description = copy["v_description"].format(
        cls_label="Clase" if locale == "es" else "Class",
        overall=overall,
        date=str(result.get("generated_at_utc", ""))[:10],
        notice=BADGE_NOTICE[locale],
    )
    # Never indexed (an unpublished page should not linger in search), but it
    # previews its class and date when the link is shared.
    meta = head_meta(
        PageMeta(
            title=title,
            description=description,
            locale=locale,
            paths={"es": f"/v/{public_id}", "en": f"/v/{public_id}?lang=en"},
            index=False,
        ),
        base_url=base_url,
    )
    return (
        _head(title, locale, meta) + f"<p class='muted'><a href='/v/{_e(public_id)}?lang={other}'>"
        f"{'English' if locale == 'es' else 'Español'}</a></p>"
        + f"<h1>{_e(copy['v_title'])}</h1>"
        + f"<p><span class='cls' style='background:{colour}'>{_e(overall)}</span>"
        f"{_e(class_text(overall, locale))}</p>"
        + f"<p class='muted'>{_e(copy['v_audited'])}: {_e(result.get('generated_at_utc', ''))}"
        f" · {_e(copy['v_published'])}: {_e(published_at)} · ID <code>{_e(public_id)}</code></p>"
        + f"<div class='disclaimer'><strong>{_e(copy['v_notice'])}.</strong> "
        f"{_e(VERIFICATION_NOTICE[locale])}</div>"
        + f"<h2>{_e(copy['v_dimensions'])}</h2><table><tr><th>{_e(copy['v_dimension'])}</th>"
        f"<th>{_e(copy['v_status'])}</th><th>{_e(copy['v_meaning'])}</th></tr>{rows}</table>"
        + f"<h2>{_e(copy['v_inputs'])}</h2><table>{digest_rows}</table>"
        + f"<h2>{_e(copy['v_details'])}</h2><table>{detail_rows}</table>"
        + f"<h2>{_e(copy['v_badge'])}</h2>"
        f"<p><img src='/v/{_e(public_id)}/badge.svg?lang={_e(locale)}' "
        f"alt='{_e(BADGE_NOTICE[locale])}' width='480' height='72'></p>"
        f"<p class='muted'>{_e(copy['v_badge_help'])}</p><pre><code>{_e(snippet)}</code></pre>"
        + _footer(locale)
    )


def badge_svg(*, overall: str, public_id: str, audited_on: str, locale: str = "es") -> str:
    """The badge: class, id, date and the fixed notice. Never a return figure."""
    locale = locale if locale in BADGE_NOTICE else "es"
    title = "Auditoría de backtest" if locale == "es" else "Backtest audit"
    label = "Clase" if locale == "es" else "Class"
    colour = CLASS_COLOURS.get(overall, "#333")
    notice = BADGE_NOTICE[locale]
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='480' height='72' viewBox='0 0 480 72' "
        f"role='img' aria-label='{_e(f'{title} · {label} {overall} · {notice}')}'>"
        f"<title>{_e(f'{title} · {label} {overall} · {notice}')}</title>"
        "<rect width='480' height='72' rx='8' fill='#ffffff' stroke='#999'/>"
        f"<rect width='72' height='72' rx='8' fill='{colour}'/>"
        "<text x='36' y='50' font-family='Segoe UI,Roboto,Arial,sans-serif' font-size='40' "
        f"font-weight='800' fill='#fff' text-anchor='middle'>{_e(overall)}</text>"
        "<text x='84' y='24' font-family='Segoe UI,Roboto,Arial,sans-serif' font-size='15' "
        f"font-weight='700' fill='#1a1a1a'>{_e(title)} · {_e(label)} {_e(overall)}</text>"
        "<text x='84' y='42' font-family='Segoe UI,Roboto,Arial,sans-serif' font-size='11' "
        f"fill='#444'>{_e(audited_on)} · ID {_e(public_id)}</text>"
        "<text x='84' y='60' font-family='Segoe UI,Roboto,Arial,sans-serif' font-size='9' "
        f"fill='#666' textLength='388' lengthAdjust='spacingAndGlyphs'>{_e(notice)}</text>"
        "</svg>"
    )


def legal_page(
    text: LegalText, *, locale: str = "es", kind: str = "terms", base_url: str = ""
) -> str:
    """The terms or the privacy policy as one page, with a language switch."""
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    other = "en" if locale == "es" else "es"
    path = legal_url(kind, locale).split("?", 1)[0]
    description = f"{text.title} · {copy['title']}. {DISCLAIMER[locale]}"
    meta = _public_meta(text.title, description, locale, path, base_url)
    warning = f"<div class='error'>{_e(text.warning)}</div>" if text.warning else ""
    sections = "".join(
        f"<h2>{_e(heading)}</h2>" + "".join(f"<p>{_e(line)}</p>" for line in lines)
        for heading, lines in text.sections
    )
    return (
        _head(text.title, locale, meta)
        + f"<p class='muted'><a href='/?lang={_e(locale)}'>{_e(copy['back'])}</a> · "
        f"<a href='?lang={other}'>{'English' if locale == 'es' else 'Español'}</a></p>"
        + f"<h1>{_e(text.title)}</h1>{warning}{sections}"
        + f"<p class='muted'>{_e(copy['legal_updated'])}: {_e(text.updated)}</p>"
        + _footer(locale)
    )


def error_page(message: str, *, locale: str = "es") -> str:
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    other = "en" if locale == "es" else "es"
    return (
        _head(copy["error_title"], locale)
        + f"<h1>{_e(copy['error_title'])}</h1><div class='error'>{_e(message)}</div>"
        + f"<p><a href='/?lang={_e(locale)}'>{_e(copy['back'])}</a> · "
        f"<a href='{_e(guides_index_url(locale))}'>{_e(GUIDES_COPY[locale]['title'])}</a> · "
        f"<a href='/?lang={other}' hreflang='{other}'>{'English' if locale == 'es' else 'Español'}"
        "</a></p>" + _footer(locale)
    )


def guides_index_page(*, locale: str = "es", base_url: str = "") -> str:
    """The list of export guides."""
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    words = GUIDES_COPY[locale]
    other = "en" if locale == "es" else "es"
    meta = _public_meta(
        f"{words['title']} · {copy['title']}",
        words["summary"],
        locale,
        guides_index_url(locale),
        base_url,
    )
    items = "".join(
        f"<li><a href='{_e(guide_url(g.slug, locale))}'>{_e(g.text[locale].title)}</a>"
        f"<div class='muted'>{_e(g.text[locale].summary)}</div></li>"
        for g in GUIDES
    )
    return (
        _head(f"{words['title']} · {copy['title']}", locale, meta)
        + f"<p class='muted'><a href='/?lang={_e(locale)}'>{_e(words['back'])}</a> · "
        f"<a href='{_e(guides_index_url(other))}' hreflang='{other}'>"
        f"{'English' if locale == 'es' else 'Español'}</a></p>"
        + f"<h1>{_e(words['title'])}</h1><p>{_e(words['intro'])}</p>"
        + f"<ul class='guides'>{items}</ul>"
        + f"<p><a href='/?lang={_e(locale)}#subir'>{_e(words['form'])}</a></p>"
        + _footer(locale)
    )


def guide_page(guide: Guide, *, locale: str = "es", base_url: str = "") -> str:
    """One platform's export guide."""
    locale = locale if locale in _COPY else "es"
    copy = _COPY[locale]
    words = GUIDES_COPY[locale]
    text = guide.text[locale]
    other = "en" if locale == "es" else "es"
    title = f"{text.title} · {copy['title']}"
    meta = _public_meta(title, text.summary, locale, guide_url(guide.slug, locale), base_url)
    steps = "".join(f"<li>{_e(step)}</li>" for step in text.steps)
    tips = "".join(f"<li>{_e(tip)}</li>" for tip in text.tips)
    return (
        _head(title, locale, meta)
        + f"<p class='muted'><a href='{_e(guides_index_url(locale))}'>{_e(words['all'])}</a>"
        f" · <a href='{_e(guide_url(guide.slug, other))}' hreflang='{other}'>"
        f"{'English' if locale == 'es' else 'Español'}</a></p>"
        + f"<h1>{_e(text.title)}</h1><p>{_e(text.summary)}</p>"
        + f"<h2>{_e(words['file'])}</h2><p>{_e(text.file)}</p>"
        + f"<h2>{_e(words['steps'])}</h2><ol class='steps'>{steps}</ol>"
        + f"<h2>{_e(words['upload'])}</h2><p>{_e(text.upload)}</p>"
        + f"<h2>{_e(words['tips'])}</h2><ul>{tips}</ul>"
        + f"<p><a href='/?lang={_e(locale)}#subir'>{_e(words['form'])}</a></p>"
        + _footer(locale)
    )


__all__ = [
    "BADGE_NOTICE",
    "SAMPLE_BANNER",
    "VERIFICATION_NOTICE",
    "badge_svg",
    "error_page",
    "guide_page",
    "guides_index_page",
    "landing",
    "legal_page",
    "sample_meta",
    "verification_page",
]
