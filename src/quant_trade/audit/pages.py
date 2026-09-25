"""Static HTML for the audit service: landing, upload form, error page, the
public verification page and its badge.

Plain strings with ``html.escape`` on every dynamic value and no template
engine. The look (fonts, colours, motion) lives in ``theme``; the one script
is the same-origin ``/static/app.js``, and every page works without it. The
copy avoids every profit-claim pattern the guard knows; the test suite runs
the guard over these pages.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from quant_trade.audit.accounts import FREE_PREVIEWS_PER_MONTH as _FREE
from quant_trade.audit.audiences import (
    AUDIENCE_COPY,
    AUDIENCE_PAGES,
    PLATFORMS_EN,
    PLATFORMS_ES,
    PLATFORMS_PT,
    Audience,
    audience_url,
)
from quant_trade.audit.guides import (
    GUIDES,
    GUIDES_COPY,
    REPORT_GUIDES,
    Guide,
    guide_url,
    guides_index_url,
)
from quant_trade.audit.legal import LegalText, legal_url
from quant_trade.audit.method import COPY as METHOD_COPY
from quant_trade.audit.method import REFERENCES, dimension_rows, method_url
from quant_trade.audit.portuguese import (
    AUDIENCES_PT,
    CLASS_B_PT,
    COPY_PT,
    DIMENSION_TITLES_PT,
    DISCLAIMER_PT,
    INVESTOR_PT,
    LANGUAGE_NAMES,
    METHOD_LINK_PT,
    MONTHS_PT,
    STATUS_TEXT_PT,
    TRUST_PT,
    UI_PT,
    link_locale,
)
from quant_trade.audit.prop_presets import AS_OF, DEFAULT_PRESET, PRESETS, preset_label
from quant_trade.audit.redflags import FLAG_TITLES
from quant_trade.audit.report import (
    CLASS_LADDER,
    DIMENSION_TITLES,
    DISCLAIMER,
    SOURCE_NAMES,
    STATUS_TEXT,
)
from quant_trade.audit.seo import BRAND, TAGLINE, PageMeta, head_meta, page_paths, private_meta
from quant_trade.audit.settings import PACK_CREDITS
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
from quant_trade.audit.verdict import DIMENSION_ORDER, class_text, meaning

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

_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "title": f"{BRAND} · Auditoría de backtests",
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
            f"{len(FLAG_TITLES)} banderas rojas: datos duplicados, picos, marcas congeladas y más.",
            "Comparación con el benchmark que aportes, si aportas uno.",
        ],
        "not_title": "Qué no hacemos",
        "not": (
            "No ejecutamos operaciones, no custodiamos fondos ni claves, no recomendamos "
            "estrategias y no predecimos resultados. Auditamos el archivo que subes."
        ),
        "form_title": "Solicitar una auditoría",
        "report": "Informe de tu plataforma (recomendado)",
        "report_short": "Tal cual lo guarda tu plataforma: HTML, XLSX o CSV, hasta 10 MB.",
        "report_help": (
            "El archivo tal cual: informe HTML del probador o del historial de MetaTrader 5 o 4 "
            "(o el XLSX que exporta MetaTrader 5), "
            "lista de operaciones de TradingView (CSV o XLSX), el CSV de operaciones de "
            "NinjaTrader, QuantConnect, backtesting.py o vectorbt, o el historial de "
            "operaciones en CSV o Excel de cualquier otro bróker o exchange. Reconoce el "
            "formato de exportación de " + PLATFORMS_ES + ". Hasta 10 MB."
        ),
        "live": "Estado de cuenta real o demo (opcional)",
        "live_help": (
            "El historial de la cuenta donde corre el robot (MetaTrader, el CSV que exporta "
            "Myfxbook, FX Blue o una señal de MQL5, u otro de los formatos de arriba). Te "
            "decimos si se comporta como el backtest y revisamos sus depósitos y retiros."
        ),
        "optimization": "Exportación de optimización de MT5 (XML, opcional)",
        "optimization_help": (
            "Cuenta las configuraciones que probaste: el Sharpe deflactado usa ese número real."
        ),
        "equity": (
            "Curva de equity o serie de retornos (CSV o Excel; obligatoria si no subes un informe)"
        ),
        "equity_help": (
            "Columnas: timestamp y equity (o return), en CSV, texto de Excel o XLSX. También la "
            "tabla de rentabilidades mensuales de un fondo (un año por fila, un mes por "
            "columna). Hasta 5 MB."
        ),
        "initial_balance": "Balance inicial (si el informe no lo indica)",
        "challenge": "Reto de prop firm a simular",
        "challenge_help": "Reglas leídas en la web oficial de cada firma el {as_of}. "
        "El informe cita la fuente; confirma las reglas con la firma antes de pagar su reto.",
        "trades": "Operaciones cerradas (CSV, opcional)",
        "trades_help": "entry_time, exit_time, quantity, entry_price, exit_price, side.",
        "benchmark": "Benchmark (CSV, opcional)",
        "variants": "Matriz de variantes (CSV, opcional)",
        "variants_help": "Una columna de retornos por variante probada; habilita el PBO.",
        "trials": "Configuraciones probadas antes de elegir esta (vacío = sin declarar)",
        "cost_bps": (
            "Coste extra por lado en puntos básicos, además del que ya detalla tu informe "
            "(vacío = 0)"
        ),
        "oos_start": "Inicio del tramo fuera de muestra (opcional)",
        "net_of_fees": (
            "Son rentabilidades de un fondo, ya netas de sus comisiones (solo historial mensual)"
        ),
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
        "paid_note": (
            "Con tu cuenta, el primer informe completo es gratis; después, vistas previas "
            "gratis y el informe completo por USD {price:.0f}."
        ),
        "signin_first": (
            "Antes de subir, crea tu cuenta gratis: tu primer informe sale completo, con PDF, "
            "sin pagar. Si ya compraste un código, puedes subir sin cuenta."
        ),
        "signin_create": "Crear cuenta gratis",
        "signin_enter": "Ya tengo cuenta",
        "waitlist_title": "Avísame cuando haya novedades",
        "email": "Correo",
        "join": "Apuntarme",
        "joined": "Apuntado. Gracias.",
        "error_title": "No se pudo auditar",
        "back": "Volver",
        "disclaimer": "Aviso",
        "sample_link": "Ver un informe de ejemplo completo (datos sintéticos)",
        "meta_description": (
            "Auditoría estadística de backtests e historiales de trading para forex, acciones, "
            "futuros y cripto. Sube el informe de MetaTrader, TradingView, NinjaTrader, Python o "
            "tu curva de equity y recibe un veredicto de A a D, con cada número etiquetado "
            "según su evidencia."
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
        "guide_q": "¿Qué archivo exporto?",
        "map_title": "¿Tu plataforma no aparece o su archivo da error? Indica sus columnas",
        "map_help": (
            "Solo para una lista en CSV o Excel. Escribe el nombre exacto de cada columna tal "
            "como aparece en la primera fila del archivo; al elegir el archivo te sugerimos "
            "sus nombres. Con una fila por operación: entrada, salida, cantidad y precios. "
            "Con una fila por ejecución: hora, lado, cantidad y precio. Lo que dejes vacío "
            "se reconoce solo."
        ),
        "map_groups": (
            ("Una fila por operación", ("entry_time", "exit_time", "entry_price", "exit_price")),
            ("Una fila por ejecución", ("time", "price")),
            (
                "En los dos casos",
                ("side", "quantity", "symbol", "profit", "commission", "multiplier"),
            ),
        ),
        "map_found": "Columnas de tu archivo:",
        "or_word": "o",
        "map_roles": {
            "entry_time": "Fecha y hora de entrada",
            "exit_time": "Fecha y hora de salida",
            "entry_price": "Precio de entrada",
            "exit_price": "Precio de salida",
            "time": "Fecha y hora de la ejecución",
            "price": "Precio de la ejecución",
            "side": "Lado (compra o venta)",
            "quantity": "Cantidad",
            "symbol": "Símbolo",
            "profit": "Resultado de la operación",
            "commission": "Comisión",
            "multiplier": "Multiplicador del contrato",
        },
        "guide_list": "Guía para",
        "optimization_guide": "Cómo exportar el XML de optimización",
        "v_description": "{cls_label} {overall} · auditada el {date} · {notice}.",
        "how_title": "Cómo funciona",
        "how": [
            "Sube el archivo de tu plataforma tal cual: un backtest, el historial de una cuenta o "
            "una serie de retornos.",
            "En segundos ves gratis la clase de A a D, las gráficas, las banderas rojas y qué "
            "significa cada dimensión en lenguaje llano.",
            "Si quieres todos los números, desbloqueas el informe completo en la misma página "
            "y lo guardas en PDF.",
            "Si quieres, publica una página de verificación con sello para compartirla.",
        ],
        "prices_title": "Precios",
        "price_free_title": "Vista previa",
        "price_free": (
            "Clase de A a D, explicación de cada dimensión, gráficas, banderas rojas y hashes."
        ),
        "price_full_title": "Informe completo",
        "price_full": (
            "Todo el detalle numérico sin marca de agua, simulador de reto, riesgo remuestreado, "
            "preguntas para el vendedor y página de verificación pública con sello."
        ),
        "price_free_mode": (
            "Ahora mismo el servicio está en modo gratuito: el informe completo se entrega con "
            "marca de agua y sin coste."
        ),
        "pay_card": (
            "Pago con tarjeta desde el propio informe, procesado por Stripe: lo ves completo "
            "al momento, sin esperar un código."
        ),
        "pay_code": (
            "Pago por transferencia u otro medio que acordamos por WhatsApp: al confirmarse el "
            "pago te enviamos un código de acceso y lo escribes en el formulario o en el informe."
        ),
        "contact": "Pedir un código",
        "price_pack": "Pack de {n} informes: USD {price:.0f} (USD {each:.0f} cada uno).",
        "refund_note": (
            "Si el informe lee mal tu archivo (operaciones, saldo o fechas que no coinciden con "
            "tu plataforma) y no podemos corregirlo, te devolvemos el importe de ese informe."
        ),
        "account_note": (
            "Tu primer informe completo, gratis al crear tu cuenta; después, "
            f"{_FREE} vistas previas gratis al mes, y tus informes y créditos en un solo lugar."
        ),
        "account_link": "Crear cuenta",
        "faq_title": "Preguntas frecuentes",
        "faq": [
            (
                "¿Qué archivo subo?",
                "El informe de tu plataforma tal cual: MetaTrader 5 o 4 (HTML), TradingView "
                "(CSV o XLSX), NinjaTrader, QuantConnect, backtesting.py o vectorbt. Para "
                "revisar la cuenta de otro trader, el historial en CSV que exporta Myfxbook, "
                "FX Blue o una señal de MQL5. De tu bróker, exchange o diario, "
                "su historial de operaciones en CSV o Excel: reconoce el formato de exportación "
                "de " + PLATFORMS_ES + ", y en cualquier otro las columnas se reconocen por su "
                "nombre. También sirve una curva de equity en CSV.",
            ),
            (
                "¿Sirve para acciones, cripto, futuros o un fondo?",
                "Sí. Rigor no depende del mercado: mide el historial que subes. Para una cartera "
                "de acciones o cripto, o para un fondo o un gestor, sube su curva de equity o su "
                "serie de retornos (diaria, semanal o mensual) en CSV o Excel; de un fondo sirve "
                "también la tabla de rentabilidades mensuales de su ficha. Los informes de "
                "TradingView, NinjaTrader, QuantConnect, backtesting.py y vectorbt sirven para "
                "cualquier activo.",
            ),
            (
                "¿Qué recibo y cuánto tarda?",
                "En segundos, la vista previa gratuita: clase de A a D, gráficas, banderas rojas "
                "y qué significa cada dimensión. El informe completo añade cada cifra, pruebas "
                "de estrés, riesgo y capital, simulador de retos, la cuenta real frente al "
                "backtest si la subes, preguntas para el vendedor y el PDF. Mira el ejemplo "
                "completo antes de pagar.",
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
        "title": f"{BRAND} · Backtest audit",
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
            f"{len(FLAG_TITLES)} red flags: duplicate data, spikes, frozen marks and more.",
            "A comparison against the benchmark you supply, if you supply one.",
        ],
        "not_title": "What we do not do",
        "not": (
            "We execute no trades, hold no funds or keys, recommend no strategies and predict "
            "no results. We audit the file you upload."
        ),
        "form_title": "Request an audit",
        "report": "Your platform report (recommended)",
        "report_short": "As your platform saves it: HTML, XLSX or CSV, up to 10 MB.",
        "report_help": (
            "The file as it is: a MetaTrader 5 or 4 tester or history HTML report (or the "
            "XLSX MetaTrader 5 exports), a "
            "TradingView list of trades (CSV or XLSX), the trades CSV of NinjaTrader, "
            "QuantConnect, backtesting.py or vectorbt, or the CSV or Excel trade history of "
            "any other broker or exchange. It recognises the export format of "
            + PLATFORMS_EN
            + ". Up to 10 MB."
        ),
        "live": "Live or demo account statement (optional)",
        "live_help": (
            "The history of the account running the robot (MetaTrader, the CSV exported by "
            "Myfxbook, FX Blue or an MQL5 signal, or any format above). We tell you whether "
            "it behaves like the backtest and review its deposits and withdrawals."
        ),
        "optimization": "MT5 optimisation export (XML, optional)",
        "optimization_help": (
            "Counts the configurations you tried: the deflated Sharpe uses that real number."
        ),
        "equity": "Equity curve or return series (CSV or Excel; required without a report)",
        "equity_help": (
            "Columns: timestamp and equity (or return), as CSV, Excel text or XLSX. Also a "
            "fund's monthly returns table (a year per row, a month per column). Up to 5 MB."
        ),
        "initial_balance": "Starting balance (if the report does not state it)",
        "challenge": "Prop-firm challenge to simulate",
        "challenge_help": "Rules read on each firm's official site on {as_of}. "
        "The report cites the source; confirm the rules with the firm before paying for its "
        "challenge.",
        "trades": "Closed trades (CSV, optional)",
        "trades_help": "entry_time, exit_time, quantity, entry_price, exit_price, side.",
        "benchmark": "Benchmark (CSV, optional)",
        "variants": "Variant matrix (CSV, optional)",
        "variants_help": "One return column per variant tried; enables the PBO.",
        "trials": "Configurations tried before choosing this one (blank = not declared)",
        "cost_bps": (
            "Extra cost per side in basis points, on top of what your report already itemises "
            "(blank = 0)"
        ),
        "oos_start": "Out-of-sample start (optional)",
        "net_of_fees": (
            "These are a fund's returns, already net of its fees (monthly track record only)"
        ),
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
        "paid_note": (
            "With your account, the first full report is free; after that, free previews "
            "and the full report for USD {price:.0f}."
        ),
        "signin_first": (
            "Before you upload, create your free account: your first report comes out in full, "
            "with the PDF, at no cost. If you bought a code, you can upload without an account."
        ),
        "signin_create": "Create a free account",
        "signin_enter": "I have an account",
        "waitlist_title": "Tell me when there is news",
        "email": "E-mail",
        "join": "Join",
        "joined": "Joined. Thank you.",
        "error_title": "Could not audit",
        "back": "Back",
        "disclaimer": "Notice",
        "sample_link": "See a full sample report (synthetic data)",
        "meta_description": (
            "Statistical audit of trading backtests and track records for forex, stocks, futures "
            "and crypto. Upload your MetaTrader, TradingView, NinjaTrader or Python report or "
            "your equity curve and get an A to D verdict, with every number tagged by its "
            "evidence."
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
        "guide_q": "Which file do I export?",
        "map_title": "Platform not listed, or its file fails? Name its columns",
        "map_help": (
            "Only for a CSV or Excel list. Type each column's exact name as it appears in the "
            "file's first row; once you pick the file we suggest its names. One row per trade: "
            "entry, exit, quantity and prices. One row per fill: time, side, quantity and "
            "price. Anything left blank is recognised on its own."
        ),
        "map_groups": (
            ("One row per trade", ("entry_time", "exit_time", "entry_price", "exit_price")),
            ("One row per fill", ("time", "price")),
            ("Either way", ("side", "quantity", "symbol", "profit", "commission", "multiplier")),
        ),
        "map_found": "Columns in your file:",
        "or_word": "or",
        "map_roles": {
            "entry_time": "Entry date and time",
            "exit_time": "Exit date and time",
            "entry_price": "Entry price",
            "exit_price": "Exit price",
            "time": "Fill date and time",
            "price": "Fill price",
            "side": "Side (buy or sell)",
            "quantity": "Quantity",
            "symbol": "Symbol",
            "profit": "Trade result",
            "commission": "Commission",
            "multiplier": "Contract multiplier",
        },
        "guide_list": "Guide for",
        "optimization_guide": "How to export the optimisation XML",
        "v_description": "{cls_label} {overall} · audited on {date} · {notice}.",
        "how_title": "How it works",
        "how": [
            "Upload your platform's file as it is: a backtest, an account history or a return "
            "series.",
            "In seconds you see, free, the A to D class, the charts, the red flags and what "
            "each dimension means in plain language.",
            "If you want every number, you unlock the full report on the same page and keep "
            "it as a PDF.",
            "If you want, publish a verification page with a badge to share it.",
        ],
        "prices_title": "Pricing",
        "price_free_title": "Preview",
        "price_free": ("A to D class, what each dimension means, charts, red flags and hashes."),
        "price_full_title": "Full report",
        "price_full": (
            "Every number without a watermark, challenge simulator, resampled risk, questions "
            "for the vendor and a public verification page with a badge."
        ),
        "price_free_mode": (
            "The service is in free mode right now: the full report is delivered with a "
            "watermark at no cost."
        ),
        "pay_card": (
            "Card payment from the report itself, processed by Stripe: you see it in full at "
            "once, without waiting for a code."
        ),
        "pay_code": (
            "Pay by bank transfer or another method we agree on WhatsApp: once the payment is "
            "confirmed you receive an access code and enter it in the form or in the report."
        ),
        "contact": "Ask for a code",
        "price_pack": "Pack of {n} reports: USD {price:.0f} (USD {each:.0f} each).",
        "refund_note": (
            "If the report misreads your file (trades, balance or dates that do not match your "
            "platform) and we cannot fix it, we refund that report."
        ),
        "account_note": (
            "Your first full report, free when you create your account; then "
            f"{_FREE} free previews a month, and your reports and credits in one place."
        ),
        "account_link": "Create an account",
        "faq_title": "Frequently asked questions",
        "faq": [
            (
                "Which file do I upload?",
                "Your platform report as it is: MetaTrader 5 or 4 (HTML), TradingView (CSV or "
                "XLSX), NinjaTrader, QuantConnect, backtesting.py or vectorbt. To review another "
                "trader's account, the CSV history exported by Myfxbook, FX Blue or an MQL5 "
                "signal. From your broker, exchange or journal, its trade history as CSV "
                "or Excel: it recognises the export format of " + PLATFORMS_EN + ", and in any "
                "other the columns are recognised by their names. An equity curve in CSV "
                "works too.",
            ),
            (
                "Does it work for stocks, crypto, futures or a fund?",
                "Yes. Rigor does not depend on the market: it measures the history you upload. "
                "For a stock or crypto portfolio, or for a fund or a manager, upload its equity "
                "curve or return series (daily, weekly or monthly) as CSV or Excel; for a fund, "
                "the monthly returns table from its factsheet works too. TradingView, "
                "NinjaTrader, QuantConnect, backtesting.py and vectorbt reports work for any "
                "asset.",
            ),
            (
                "What do I get and how long does it take?",
                "In seconds, the free preview: A to D class, charts, red flags and what each "
                "dimension means. The full report adds every figure, stress tests, risk and "
                "capital, the challenge simulator, the live account against the backtest if you "
                "upload it, questions for the vendor and the PDF. See the full sample before you "
                "pay.",
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

#: Interface words the redesigned pages add on top of ``_COPY``.
_UI: dict[str, dict[str, Any]] = {
    "es": {
        "skip": "Saltar al contenido",
        "nav_how": "Cómo funciona",
        "nav_sample": "Ejemplo",
        "footer_sample_pdf": "Ejemplo en PDF",
        "footer_check": "Comprobar un informe",
        "v_check": "¿Te enviaron el PDF o el JSON de este informe? Comprueba que no se editó.",
        "v_check_link": "Comprobar un archivo",
        "nav_pricing": "Precios",
        "nav_guides": "Guías",
        "nav_faq": "Preguntas",
        "nav_account": "Mi cuenta",
        "nav_compare": "Comparar",
        "nav_menu": "Menú",
        "cta": "Empezar gratis",
        "cta_full": "Empieza con la vista previa gratis",
        "cta_short": "Auditar",
        "hero_a": "Sube tu backtest o tu historial.",
        "hero_b": "Te decimos si es evidencia o suerte.",
        "trust": [
            ("shield", "Sin conexión a tu bróker"),
            ("hash", "Huella SHA-256 de cada archivo"),
            ("globe", "Informe en español o inglés"),
            ("key", "Primer informe completo gratis con tu cuenta"),
        ],
        "mock_url": "informe · clase B",
        "mock_k": "Veredicto",
        "cta_sample": "Ver un informe de ejemplo",
        "hero_lead": (
            "Para traders de cualquier mercado, quien compra un robot, quien va a un reto de "
            "prop firm y quien invierte con un gestor. Sube el archivo que ya tienes y recibe "
            "en segundos un veredicto de A a D sobre sobreajuste, costes, fuera de muestra y "
            "calidad de datos, con cada número etiquetado según su evidencia."
        ),
        "mock_cap": "Ilustración con datos sintéticos",
        "mock_is": "Dentro de muestra",
        "mock_oos": "Fuera de muestra",
        "mock_kpis": [
            ("0,41", "Sharpe deflactado"),
            ("120", "Intentos contados"),
            ("3,2 pb", "Coste de equilibrio"),
        ],
        "chip_trials": "Intentos reales desde el XML de MT5",
        "chip_hash": "Cada número con su evidencia",
        "platforms": "Lee el archivo que ya tienes",
        "platforms_also": "Y reconoce el formato de exportación de",
        "problem_eyebrow": "El problema",
        "problem_title": ("Un backtest bonito", "no es evidencia."),
        "problem_lead": (
            "Casi cualquier estrategia se ve bien en papel. Estas son las tres razones por las "
            "que la mayoría no aguanta fuera del probador."
        ),
        "problems": [
            (
                "Sobreajuste",
                "Pruebas cien configuraciones y te quedas con la mejor. El azar, por sí solo, "
                "ya dibuja una curva preciosa.",
            ),
            (
                "Costes",
                "Comisión, spread y deslizamiento se comen las ventajas finas. Muchos backtests "
                "los cuentan como cero.",
            ),
            (
                "Datos",
                "Barras duplicadas, precios congelados o huecos inflan el resultado sin que "
                "nadie lo note.",
            ),
        ],
        "dims_eyebrow": "Qué medimos",
        "dims_title": ("Seis dimensiones.", "Un veredicto de A\u00a0a\u00a0D."),
        "dims_lead": (
            "Cada dimensión sale como Supera, Débil, No supera o No medido, con dos frases en "
            "lenguaje llano sobre qué significa para ti."
        ),
        "stats": [
            ("6", "dimensiones auditadas"),
            ("{flags}", "banderas rojas revisadas en cada archivo"),
            ("{presets}", "retos de prop firms simulables"),
            ("{platforms}", "plataformas que se leen tal cual"),
        ],
        "evidence_eyebrow": "Evidencia",
        "evidence_title": ("Cada número dice", "de dónde sale."),
        "evidence_lead": (
            "La diferencia entre una opinión y una auditoría. Nunca presentamos lo que tú "
            "declaras como si lo hubiéramos medido."
        ),
        "evidence": [
            ("MEASURED", "Lo calculamos nosotros a partir de tu archivo."),
            ("DECLARED", "Lo dijiste tú o lo dice tu plataforma; no lo podemos comprobar."),
            ("NOT_MEASURED", "Faltaban datos para medirlo, y te decimos cuáles."),
        ],
        "diff_eyebrow": "Por qué es distinta",
        "diff_title": ("Hecha para quien", "va a arriesgar su dinero."),
        "diffs": [
            (
                "layers",
                "Intentos reales",
                "Con el XML de optimización de MT5 contamos las configuraciones que probaste, y "
                "el Sharpe deflactado usa ese número, no uno supuesto.",
            ),
            (
                "hash",
                "Evidencia por huella",
                "Cada archivo auditado queda identificado por su SHA-256: cualquiera puede "
                "comprobar que es exactamente el mismo.",
            ),
            (
                "dice",
                "Riesgo remuestreado",
                "Drawdown probable a un año y simulación de retos de prop firms, con sus "
                "supuestos escritos al lado.",
            ),
            (
                "eye",
                "Página pública con sello",
                "Publica la verificación de tu auditoría y enséñala con un sello que dice "
                "exactamente qué es y qué no es.",
            ),
        ],
        "how_eyebrow": "Proceso",
        "pricing_eyebrow": "Precios",
        "plan_free": "Vista previa",
        "plan_free_amount": "Gratis",
        "plan_free_note": f"con tu cuenta: el primer informe completo y {_FREE} al mes",
        "plan_full": "Informe completo",
        "plan_full_note": "por auditoría",
        "plan_badge": "Completo",
        "free_items": [
            "Clase de A a D y resumen en lenguaje llano",
            "Qué significa cada dimensión para ti",
            "Gráficas de equity, drawdown y retornos mensuales",
            "Banderas rojas y huellas de tus archivos",
        ],
        "full_items": [
            "Todo el detalle numérico, sin marca de agua",
            "Simulador de reto de prop firm",
            "Riesgo remuestreado a un año y el capital que pide",
            "Pruebas de estrés: el resultado sin sus mejores operaciones",
            "La cuenta real frente a su backtest",
            "Preguntas para el vendedor del robot o el gestor",
            "Si funciona en cada mercado o uno carga con el resto",
            "Para fondos: calendario año por mes, peor mes y tiempo en recuperarse",
            "El dinero real detrás del % de una cuenta: depósitos, recargas y pérdidas abiertas",
            "Página de verificación pública con sello",
        ],
        "upload_eyebrow": "Empieza aquí",
        "upload_title": ("Tu auditoría,", "en un solo archivo."),
        "upload_lead": (
            "Sube el informe tal cual lo guarda tu plataforma. La clase, las gráficas y la "
            "explicación de cada dimensión son gratis."
        ),
        "upload_points": [
            "Tu archivo nunca se publica.",
            (
                "Tu primer informe completo, gratis al crear tu cuenta; después, "
                f"{_FREE} vistas previas gratis al mes. Sin tarjeta."
            ),
            "Borrado automático si no desbloqueas el informe.",
        ],
        "drop_title": "Arrastra tu informe aquí",
        "drop_sub": "o haz clic para elegirlo · hasta 10 MB",
        "drop_small": "Arrastra o haz clic",
        "no_report": "¿No tienes informe? Sube tu curva de equity",
        "extras": "Añadir más archivos",
        "extras_note": "Opcional: XML de optimización, cuenta real o demo, reto de prop firm",
        "advanced": "Opciones avanzadas",
        "advanced_note": "Todo tiene un valor por defecto",
        "busy_title": "Auditando tu archivo",
        "busy_sub": "No cierres esta página.",
        "busy_steps": [
            "Leyendo el archivo",
            "Midiendo significación e intentos",
            "Remuestreando escenarios",
            "Redactando el veredicto",
        ],
        "faq_eyebrow": "Preguntas",
        "final_title": ("Antes de arriesgar dinero en una estrategia,", "mírala con lupa."),
        "final_lead": "Sube el informe y recibe la clase, las gráficas y su explicación sin coste.",
        "footer_product": "Producto",
        "footer_legal": "Legal",
        "footer_news": "Novedades",
        "footer_base": (
            "Solo análisis estadístico: sin órdenes, sin custodia y sin claves de bróker."
        ),
        "v_eyebrow": "Verificación pública",
        "v_copy": "Copiar código",
        "v_copied": "Copiado",
        "v_id": "ID",
        "guides_eyebrow": "Guías de exportación",
        "legal_eyebrow": "Legal",
        "error_eyebrow": "Algo no cuadra",
    },
    "en": {
        "skip": "Skip to content",
        "nav_how": "How it works",
        "nav_sample": "Sample",
        "footer_sample_pdf": "Sample as PDF",
        "footer_check": "Check a report",
        "v_check": "Were you sent this report's PDF or JSON? Check that it was not edited.",
        "v_check_link": "Check a file",
        "nav_pricing": "Pricing",
        "nav_guides": "Guides",
        "nav_faq": "FAQ",
        "nav_account": "My account",
        "nav_compare": "Compare",
        "nav_menu": "Menu",
        "cta": "Start free",
        "cta_full": "Start with the free preview",
        "cta_short": "Audit",
        "hero_a": "Upload your backtest or track record.",
        "hero_b": "We tell you whether it is evidence or luck.",
        "trust": [
            ("shield", "No connection to your broker"),
            ("hash", "SHA-256 fingerprint of every file"),
            ("globe", "Report in English or Spanish"),
            ("key", "First full report free with your account"),
        ],
        "mock_url": "report · class B",
        "mock_k": "Verdict",
        "cta_sample": "See a sample report",
        "hero_lead": (
            "For traders in any market, robot buyers, prop-firm traders and anyone investing "
            "with a manager. Upload the file you already have and get, in seconds, a verdict "
            "from A to D on overfitting, costs, out-of-sample and data quality, with every "
            "number labelled by its evidence."
        ),
        "mock_cap": "Illustration with synthetic data",
        "mock_is": "In sample",
        "mock_oos": "Out of sample",
        "mock_kpis": [
            ("0.41", "Deflated Sharpe"),
            ("120", "Trials counted"),
            ("3.2 bp", "Break-even cost"),
        ],
        "chip_trials": "Real trial count from the MT5 XML",
        "chip_hash": "Every number with its evidence",
        "platforms": "Reads the file you already have",
        "platforms_also": "It also recognises the export format of",
        "problem_eyebrow": "The problem",
        "problem_title": ("A good-looking backtest", "is not evidence."),
        "problem_lead": (
            "Almost any strategy looks good on paper. These are the three reasons most of them "
            "do not hold up outside the tester."
        ),
        "problems": [
            (
                "Overfitting",
                "Try a hundred settings and keep the best. Chance alone already draws a "
                "beautiful curve.",
            ),
            (
                "Costs",
                "Commission, spread and slippage eat thin edges. Many backtests count them as "
                "zero.",
            ),
            (
                "Data",
                "Duplicate bars, frozen prices or gaps inflate the result without anyone noticing.",
            ),
        ],
        "dims_eyebrow": "What we measure",
        "dims_title": ("Six dimensions.", "One verdict from A\u00a0to\u00a0D."),
        "dims_lead": (
            "Each dimension comes out as Pass, Weak, Fail or Not measured, with two plain "
            "sentences on what it means for you."
        ),
        "stats": [
            ("6", "audited dimensions"),
            ("{flags}", "red flags checked on every file"),
            ("{presets}", "prop-firm challenges to simulate"),
            ("{platforms}", "platforms read as they are"),
        ],
        "evidence_eyebrow": "Evidence",
        "evidence_title": ("Every number says", "where it comes from."),
        "evidence_lead": (
            "The difference between an opinion and an audit. What you declare is never shown "
            "as if we had measured it."
        ),
        "evidence": [
            ("MEASURED", "We computed it from your file."),
            ("DECLARED", "You or your platform stated it; we cannot check it."),
            ("NOT_MEASURED", "Data was missing to measure it, and we tell you which."),
        ],
        "diff_eyebrow": "What makes it different",
        "diff_title": ("Built for people about", "to put their money at risk."),
        "diffs": [
            (
                "layers",
                "Real trial counts",
                "With the MT5 optimisation XML we count the settings you tried, and the "
                "deflated Sharpe uses that number, not an assumed one.",
            ),
            (
                "hash",
                "Fingerprint evidence",
                "Every audited file is identified by its SHA-256: anyone can check it is "
                "exactly the same file.",
            ),
            (
                "dice",
                "Resampled risk",
                "Likely one-year drawdown and prop-firm challenge simulation, with their "
                "assumptions written next to them.",
            ),
            (
                "eye",
                "Public page with a badge",
                "Publish your audit's verification page and show it with a badge that says "
                "exactly what it is and what it is not.",
            ),
        ],
        "how_eyebrow": "Process",
        "pricing_eyebrow": "Pricing",
        "plan_free": "Preview",
        "plan_free_amount": "Free",
        "plan_free_note": f"with your account: the first full report and {_FREE} a month",
        "plan_full": "Full report",
        "plan_full_note": "per audit",
        "plan_badge": "Complete",
        "free_items": [
            "Class A to D and a plain-language summary",
            "What each dimension means for you",
            "Equity, drawdown and monthly return charts",
            "Red flags and your files' fingerprints",
        ],
        "full_items": [
            "Every number in detail, no watermark",
            "Prop-firm challenge simulator",
            "Resampled one-year risk and the capital it needs",
            "Stress tests: the result without its best trades",
            "The live account against its backtest",
            "Questions to ask the robot's vendor or the manager",
            "Whether it works on each market or one carries the rest",
            "For funds: year-by-month calendar, worst month and time to recover",
            "The real money behind an account's %: deposits, top-ups and open losses",
            "Public verification page with a badge",
        ],
        "upload_eyebrow": "Start here",
        "upload_title": ("Your audit,", "from a single file."),
        "upload_lead": (
            "Upload the report exactly as your platform saves it. The class, the charts and the "
            "explanation of each dimension are free."
        ),
        "upload_points": [
            "Your file is never published.",
            (
                "Your first full report, free when you create your account; then "
                f"{_FREE} free previews a month. No card."
            ),
            "Deleted automatically if you do not unlock the report.",
        ],
        "drop_title": "Drop your report here",
        "drop_sub": "or click to choose it · up to 10 MB",
        "drop_small": "Drop or click",
        "no_report": "No report? Upload your equity curve",
        "extras": "Add more files",
        "extras_note": "Optional: optimisation XML, live or demo account, prop-firm challenge",
        "advanced": "Advanced options",
        "advanced_note": "Everything has a default",
        "busy_title": "Auditing your file",
        "busy_sub": "Keep this page open.",
        "busy_steps": [
            "Reading the file",
            "Measuring significance and trials",
            "Resampling scenarios",
            "Writing the verdict",
        ],
        "faq_eyebrow": "Questions",
        "final_title": ("Before you put money on a strategy,", "take a close look."),
        "final_lead": "Upload the report and get the class, the charts and their explanation free.",
        "footer_product": "Product",
        "footer_legal": "Legal",
        "footer_news": "News",
        "footer_base": "Statistical analysis only: no orders, no custody and no broker keys.",
        "v_eyebrow": "Public verification",
        "v_copy": "Copy code",
        "v_copied": "Copied",
        "v_id": "ID",
        "guides_eyebrow": "Export guides",
        "legal_eyebrow": "Legal",
        "error_eyebrow": "Something is off",
    },
}

# Portuguese: the landing and its shell (``portuguese``); other pages link to English.
_COPY["pt"] = COPY_PT
_UI["pt"] = UI_PT

#: Platforms the importers read, for the landing's scrolling strip.
PLATFORMS: tuple[str, ...] = (
    "MetaTrader 5",
    "MetaTrader 4",
    "TradingView",
    "NinjaTrader",
    "QuantConnect",
    "backtesting.py",
    "vectorbt",
    "Myfxbook",
    "FX Blue",
    "MQL5 Signals",
    "CSV",
)

_DIMENSION_ICONS: dict[str, str] = {
    "statistical_significance": "bell",
    "multiplicity": "layers",
    "costs": "percent",
    "out_of_sample": "split",
    "data_quality": "database",
    "benchmark": "target",
}

#: The status of each dimension in the landing's illustration (synthetic).
_MOCK_STATUSES: tuple[tuple[str, str], ...] = (
    ("statistical_significance", "PASS"),
    ("multiplicity", "WEAK"),
    ("costs", "PASS"),
    ("out_of_sample", "WEAK"),
    ("data_quality", "PASS"),
    ("benchmark", "NOT_APPLICABLE"),
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _locale(locale: str) -> str:
    return locale if locale in _COPY else "es"


def _home(locale: str) -> str:
    return {"en": "/en", "pt": "/pt"}.get(locale, "/")


def _other_name(locale: str) -> str:
    return "English" if locale == "es" else "Español"


def _dimension_titles(locale: str) -> dict[str, str]:
    return DIMENSION_TITLES_PT if locale == "pt" else DIMENSION_TITLES[locale]


def _class_text(overall: str, locale: str) -> str:
    return CLASS_B_PT if locale == "pt" and overall == "B" else class_text(overall, locale)


def _disclaimer(locale: str) -> str:
    return DISCLAIMER_PT if locale == "pt" else DISCLAIMER[locale]


def _method_title(locale: str) -> str:
    return METHOD_LINK_PT if locale == "pt" else str(METHOD_COPY[locale]["title"])


def _sample_url(locale: str) -> str:
    """The sample report, in English from a Portuguese page."""
    return "/ejemplo?lang=es" if locale == "es" else "/sample?lang=en"


def _switch_links(
    locale: str, switch_href: str, alternates: dict[str, str] | None, *, menu: bool = False
) -> str:
    """The language links: every other language the page exists in.

    ``alternates`` maps each language to this page's address in it; without
    it, ``switch_href`` is the one other language (Spanish or English). With
    two others the bar shows short codes (EN, PT) and the phone menu the names.
    """
    if alternates:
        others = [(lang, href) for lang, href in alternates.items() if lang != locale]
    elif switch_href:
        others = [("en" if locale == "es" else "es", switch_href)]
    else:
        others = []
    cls = "" if menu else " class='lang'"
    return "".join(
        f"<a{cls} href='{_e(href)}' hreflang='{lang}' lang='{lang}'"
        + (
            f" title='{_e(LANGUAGE_NAMES[lang])}'>{lang.upper()}</a>"
            if len(others) > 1 and not menu
            else f">{_e(LANGUAGE_NAMES[lang])}</a>"
        )
        for lang, href in others
    )


def _preset_options(locale: str) -> str:
    options = []
    for key in sorted(PRESETS):
        rules = PRESETS[key]
        selected = " selected" if key == DEFAULT_PRESET else ""
        label = preset_label(rules.firm, rules.program, rules.phase, locale)
        options.append(f"<option value='{_e(key)}'{selected}>{_e(label)}</option>")
    return "".join(options)


def _compare_url(locale: str) -> str:
    return "/comparar" if locale == "es" else "/compare"


def _nav(
    locale: str,
    switch_href: str,
    *,
    solid: bool = False,
    alternates: dict[str, str] | None = None,
) -> str:
    ui = _UI[locale]
    home = _home(locale)
    linked = link_locale(locale)
    account = "/account" if linked == "en" else "/cuenta"
    links = (
        f"<a href='{home}#how'>{_e(ui['nav_how'])}</a>"
        f"<a href='{_sample_url(linked)}'>{_e(ui['nav_sample'])}</a>"
        f"<a href='{home}#pricing'>{_e(ui['nav_pricing'])}</a>"
        f"<a href='{_e(guides_index_url(locale))}'>{_e(ui['nav_guides'])}</a>"
        f"<a href='{_compare_url(linked)}'>{_e(ui['nav_compare'])}</a>"
        f"<a href='{home}#faq'>{_e(ui['nav_faq'])}</a>"
    )
    switch = _switch_links(locale, switch_href, alternates)
    # Phones: the same links in a menu that opens without script (<details>).
    menu = (
        f"<details class='menu'><summary aria-label='{_e(ui['nav_menu'])}'>"
        "<span class='burger' aria-hidden='true'><i></i><i></i><i></i></span></summary>"
        f"<nav class='menu-panel' aria-label='{_e(ui['nav_menu'])}'>{links}"
        + _switch_links(locale, switch_href, alternates, menu=True)
        + f"<a href='{account}'>{_e(ui['nav_account'])}</a>"
        + f"<a class='btn btn-primary' href='{home}#subir'>{_e(ui['cta'])}</a></nav></details>"
    )
    return (
        f"<header class='nav{' nav-solid' if solid else ''}'><div class='wrap nav-in'>"
        + logo(home)
        + f"<nav class='nav-links' aria-label='{_e(BRAND)}'>{links}</nav>"
        + f"<div class='nav-end'>{switch}<a class='lang' href='{account}'>"
        f"{_e(ui['nav_account'])}</a><a class='btn btn-sm' href='{home}#subir'>"
        f"{_e(ui['cta_short'])}</a>{menu}</div></div></header>"
    )


def _head(title: str, locale: str, meta_html: str = "") -> str:
    """The document head. ``meta_html`` comes from ``seo``; without it the
    page is private (``noindex``)."""
    meta_html = meta_html or private_meta(title, locale)
    return (
        f"<!doctype html><html lang='{_e(locale)}'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='theme-color' content='#05070b'>"
        f"<title>{_e(title)}</title>{meta_html}<style>{STYLE}</style>{SCRIPT_TAG}</head>"
    )


def _page(
    title: str,
    locale: str,
    body: str,
    *,
    meta_html: str = "",
    switch_href: str = "",
    solid_nav: bool = False,
    alternates: dict[str, str] | None = None,
) -> str:
    """A whole page: head, navigation, ``body`` (the ``main`` content) and footer.

    ``alternates`` (language to address) lists every language the page exists
    in; without it the switch offers ``switch_href`` only."""
    ui = _UI[locale]
    return (
        _head(title, locale, meta_html)
        + f"<body><a class='skip' href='#main'>{_e(ui['skip'])}</a>"
        + _nav(locale, switch_href, solid=solid_nav, alternates=alternates)
        + f"<main id='main'>{body}</main>"
        + _footer(locale)
        + "</body></html>"
    )


def _public_meta(title: str, description: str, locale: str, path: str, base_url: str) -> str:
    return head_meta(
        PageMeta(title=title, description=description, locale=locale, paths=page_paths(path)),
        base_url=base_url,
    )


def sample_meta(locale: str, base_url: str) -> str:
    """Head tags for the sample report, the one indexable report page."""
    locale = _locale(locale)
    copy = _COPY[locale]
    title = f"{copy['sample_link']} · {copy['title']}"
    path = "/ejemplo" if locale == "es" else "/sample"
    return _public_meta(title, copy["sample_description"], locale, path, base_url)


def _guide_links(locale: str) -> str:
    return " · ".join(
        f"<a href='{_e(guide_url(g.slug, locale))}'>{_e(g.platform_for(locale))}</a>"
        for g in REPORT_GUIDES
    )


def _check_url(locale: str) -> str:
    """The page where anyone checks a report file was not edited."""
    return "/check" if locale == "en" else "/comprobar"


def _footer(locale: str) -> str:
    copy = _COPY[locale]
    ui = _UI[locale]
    home = _home(locale)
    linked = link_locale(locale)
    sample = "/ejemplo" if linked == "es" else "/sample"
    product = (
        f"<li><a href='{home}#how'>{_e(ui['nav_how'])}</a></li>"
        f"<li><a href='{_sample_url(linked)}'>{_e(ui['nav_sample'])}</a></li>"
        f"<li><a href='{sample}.pdf' download>{_e(ui['footer_sample_pdf'])}</a></li>"
        f"<li><a href='{home}#pricing'>{_e(ui['nav_pricing'])}</a></li>"
        f"<li><a href='{_e(guides_index_url(locale))}'>{_e(ui['nav_guides'])}</a></li>"
        f"<li><a href='{_compare_url(linked)}'>{_e(ui['nav_compare'])}</a></li>"
        f"<li><a href='{_check_url(linked)}'>{_e(ui['footer_check'])}</a></li>"
        f"<li><a href='{_e(method_url(linked))}'>{_e(_method_title(locale))}</a></li>"
    )
    legal = (
        f"<li><a href='{_e(legal_url('terms', linked))}'>{_e(copy['terms_link'])}</a></li>"
        f"<li><a href='{_e(legal_url('privacy', linked))}'>{_e(copy['privacy_link'])}</a></li>"
    )
    return (
        "<footer class='foot'><div class='wrap'><div class='foot-grid'>"
        f"<div>{logo(home)}<p class='tagline'>{_e(TAGLINE[locale])}. {_e(ui['footer_base'])}</p>"
        f"</div><div><h4>{_e(ui['footer_product'])}</h4><ul>{product}</ul></div>"
        f"<div><h4>{_e(ui['footer_legal'])}</h4><ul>{legal}</ul></div></div>"
        f"<div class='disclaimer'><strong>{_e(copy['disclaimer'])}.</strong> "
        f"{_e(_disclaimer(locale))}</div></div></footer>"
    )


def _title_pair(pair: tuple[str, str], *, tag: str = "h2", cls: str = "h2") -> str:
    return f"<{tag} class='{cls}'>{_e(pair[0])} <em>{_e(pair[1])}</em></{tag}>"


def _section_head(eyebrow: str, title: str, lead: str = "", *, center: bool = False) -> str:
    return (
        f"<div class='section-head{' center' if center else ''}' data-reveal>"
        f"<div class='eyebrow'><span class='dot'></span>{_e(eyebrow)}</div>{title}"
        + (f"<p class='lead'>{_e(lead)}</p>" if lead else "")
        + "</div>"
    )


def _spark_paths() -> tuple[str, str]:
    """A deterministic synthetic curve for the landing's illustration."""
    seed, level, values = 20260924, 0.0, []
    for _ in range(72):
        seed = (seed * 1103515245 + 12345) % 2**31
        level += (seed / 2**31 - 0.5) * 1.6 + 0.16
        values.append(level)
    lo, hi = min(values), max(values)
    points = [
        (4 + i * 432 / (len(values) - 1), 124 - (v - lo) / (hi - lo or 1) * 100)
        for i, v in enumerate(values)
    ]
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return line, f"{line} L436,132 L4,132 Z"


_SPARK_LINE, _SPARK_AREA = _spark_paths()
#: Where the illustration's out-of-sample stretch starts (x in the 440-wide box).
_SPARK_SPLIT = 316


def _mock(locale: str) -> str:
    """The landing's illustration of a report, built from synthetic values."""
    ui = _UI[locale]
    titles = _dimension_titles(locale)
    rows = "".join(
        f"<li style='--i:{i}'><span>{_e(titles[name].split(' (')[0])}</span>"
        f"{_status_chip(status, locale)}</li>"
        for i, (name, status) in enumerate(_MOCK_STATUSES)
    )
    grid = "".join(
        f"<line class='spark-grid' x1='0' x2='440' y1='{y}' y2='{y}'/>" for y in (24, 58, 92, 126)
    )
    kpis = "".join(
        f"<div><strong>{_e(value)}</strong><span>{_e(label)}</span></div>"
        for value, label in ui["mock_kpis"]
    )
    split = _SPARK_SPLIT
    return (
        "<div class='stage rise' style='--i:5'>"
        f"<div class='mock spot' role='img' aria-label='{_e(ui['mock_cap'])}'>"
        "<div class='mock-top'><div class='mock-dots'><i></i><i></i><i></i></div>"
        f"<span class='mock-url'>{_e(BRAND.lower())} · {_e(ui['mock_url'])}</span></div>"
        "<div class='mock-body'><div class='mock-col'><div class='mock-head'>"
        + class_ring("B")
        + f"<div><div class='mock-k'>{_e(ui['mock_k'])}</div>"
        f"<div class='mock-t'>{_e(_class_text('B', locale))}</div></div></div>"
        f"<ul class='mock-dims'>{rows}</ul></div>"
        "<div class='mock-col'>"
        "<svg class='spark' viewBox='0 0 440 140' aria-hidden='true'><defs>"
        "<linearGradient id='spa' x1='0' x2='0' y1='0' y2='1'>"
        "<stop offset='0' stop-color='#f4f4f6' stop-opacity='.16'/>"
        "<stop offset='1' stop-color='#f4f4f6' stop-opacity='0'/></linearGradient></defs>"
        f"<rect class='spark-oos' x='{split}' y='0' width='{440 - split}' height='140'/>"
        f"{grid}<path class='spark-area' d='{_SPARK_AREA}'/>"
        f"<path class='spark-line' pathLength='1' d='{_SPARK_LINE}'/>"
        f"<line class='spark-split' x1='{split}' x2='{split}' y1='0' y2='140'/>"
        f"<text class='spark-lbl' x='6' y='12'>{_e(ui['mock_is'])}</text>"
        f"<text class='spark-lbl' x='{split + 6}' y='12'>{_e(ui['mock_oos'])}</text></svg>"
        f"<div class='mock-kpis'>{kpis}</div>"
        "<div class='mock-tags'><span class='badge MEASURED'>MEASURED</span>"
        "<span class='badge DECLARED'>DECLARED</span>"
        "<span class='badge NOT_MEASURED'>NOT_MEASURED</span></div></div></div></div>"
        f"<div class='mock-cap'>{_e(ui['mock_cap'])}</div></div>"
    )


def _status_chip(status: str, locale: str) -> str:
    text = (STATUS_TEXT_PT if locale == "pt" else STATUS_TEXT[locale]).get(status, status)
    return f"<span class='badge {_e(status)}'>{_e(text)}</span>"


def _hero(locale: str, sample: str) -> str:
    ui = _UI[locale]
    trust = "".join(f"<li>{icon(name)}{_e(text)}</li>" for name, text in ui["trust"])
    return (
        "<section class='hero dark'>" + aurora() + grid_bg() + "<div class='wrap'>"
        f"<div class='pill rise' style='--i:0'><span class='dot'></span>"
        f"{_e(TAGLINE[locale])}</div>"
        f"<h1 class='display'><span class='l rise' style='--i:1'>{_e(ui['hero_a'])}</span>"
        f"<em class='l rise' style='--i:2'>{_e(ui['hero_b'])}</em></h1>"
        f"<p class='lead rise' style='--i:3'>{_e(ui['hero_lead'])}</p>"
        "<div class='hero-cta rise' style='--i:4'>"
        f"<a class='btn btn-primary btn-lg' href='#subir'>{_e(ui['cta'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(sample)}'>{_e(ui['cta_sample'])}{icon('arrow')}</a></div>"
        f"<ul class='trust rise' style='--i:4'>{trust}</ul>" + _mock(locale) + "</div></section>"
    )


def _specs(locale: str) -> str:
    """The key figures in a row, then the platforms the importers read."""
    ui = _UI[locale]
    counts = {
        "presets": len(PRESETS),
        "platforms": len(PLATFORMS),
        "flags": len(FLAG_TITLES),
    }
    specs = "".join(
        f"<div data-reveal style='--i:{i}'><b data-count>{_e(value.format(**counts))}</b>"
        f"<span>{_e(label)}</span></div>"
        for i, (value, label) in enumerate(ui["stats"])
    )
    platforms = "".join(f"<li>{_e(name)}</li>" for name in PLATFORMS)
    recognised = {"es": PLATFORMS_ES, "pt": PLATFORMS_PT}.get(locale, PLATFORMS_EN)
    also = (
        f"<p class='platforms-also'>{_e(ui['platforms_also'])} "
        f"<a href='{_e(guide_url('csv-universal', locale))}'>{_e(recognised)}</a>.</p>"
    )
    return (
        "<section class='dark' style='padding-bottom:clamp(88px,11vw,150px)'><div class='wrap'>"
        f"<div class='specs'>{specs}</div>"
        f"<div class='platforms' data-reveal><p>{_e(ui['platforms'])}</p><ul>{platforms}</ul>"
        f"{also}</div>"
        "</div></section>"
    )


#: Who Rigor is for: each visitor finds their case, what they upload and what
#: they get, before reading how the audit works.
AUDIENCES: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Para quién es",
        "title": ("Un mismo rigor,", "sea cual sea tu mercado."),
        "lead": (
            "Forex, acciones, futuros o cripto; tu estrategia, un robot comprado, un reto o el "
            "dinero que confías a otro. Busca tu caso."
        ),
        "upload": "Subes",
        "get": "Recibes",
        "items": [
            (
                "layers",
                "Compras o usas un robot (EA)",
                "El backtest del vendedor se ve perfecto y no sabes si es sobreajuste.",
                "el informe del probador de MetaTrader 4 o 5 y, si lo tienes, el XML de "
                "optimización.",
                "si el resultado aguanta el número de intentos, costes más altos y quitarle sus "
                "mejores operaciones, y qué preguntarle al vendedor.",
                "mt5",
            ),
            (
                "chart",
                "Operas acciones, futuros, forex o cripto",
                "No sabes si tu ventaja es real o si la encontraste a fuerza de probar.",
                "la lista de operaciones de TradingView o NinjaTrader, el CSV de QuantConnect, "
                "backtesting.py o vectorbt, el historial en CSV o Excel de cualquier bróker, "
                "exchange o diario (Interactive Brokers, Tradovate, thinkorswim, Binance y "
                "más), o tu curva de equity.",
                "significación, Sharpe deflactado, costes, si sigue funcionando en el periodo "
                "reciente y qué capital pide.",
                "tradingview",
            ),
            (
                "target",
                "Vas a pagar un reto de prop firm",
                "Una mala racha puede tumbar la cuenta aunque la estrategia funcione.",
                "tu backtest o tu historial y el reto que quieres simular.",
                "con qué frecuencia tocarías la pérdida diaria o la total en {presets} retos de "
                "FTMO, FundedNext, The5ers y Topstep, remuestreando tu propio historial.",
                "",
            ),
            (
                "eye",
                "Inviertes con un gestor, una señal o un fondo",
                "El porcentaje que te enseñan puede venir de depósitos, de pocos meses buenos o "
                "de un backtest.",
                "el historial de su cuenta (MetaTrader, Myfxbook, FX Blue o señal de MQL5) o su "
                "tabla de rentabilidades mensuales en CSV o Excel.",
                "el resultado separado de depósitos y retiros, si la cuenta se parece a su "
                "backtest, si el historial es evidencia o suerte y, con 24 meses o más, su "
                "calendario año por mes y su caída más profunda.",
                "cuenta-proveedor",
            ),
        ],
        "guide": "Qué archivo subir",
        "more": "Ver qué revisa para tu caso",
        "also": "Otro caso:",
        "start": "Empezar",
    },
    "en": {
        "eyebrow": "Who it is for",
        "title": ("The same rigour,", "whatever your market."),
        "lead": (
            "Forex, stocks, futures or crypto; your own strategy, a robot you bought, a "
            "challenge or money you hand to someone else. Find your case."
        ),
        "upload": "You upload",
        "get": "You get",
        "items": [
            (
                "layers",
                "You buy or run a robot (EA)",
                "The vendor's backtest looks perfect and you cannot tell whether it is overfit.",
                "the MetaTrader 4 or 5 tester report and, if you have it, the optimisation XML.",
                "whether the result survives the number of trials, higher costs and losing its "
                "best trades, and what to ask the vendor.",
                "mt5",
            ),
            (
                "chart",
                "You trade stocks, futures, forex or crypto",
                "You do not know whether your edge is real or you found it by trying enough.",
                "the TradingView or NinjaTrader list of trades, the QuantConnect, backtesting.py "
                "or vectorbt CSV, the CSV or Excel history of any broker, exchange or journal "
                "(Interactive Brokers, Tradovate, thinkorswim, Binance and more), or your "
                "equity curve.",
                "significance, deflated Sharpe, costs, whether it still works in the recent "
                "period and how much capital it needs.",
                "tradingview",
            ),
            (
                "target",
                "You are about to pay for a prop-firm challenge",
                "One bad streak can end the account even when the strategy works.",
                "your backtest or history and the challenge you want to simulate.",
                "how often you would hit the daily or total loss limit in {presets} FTMO, "
                "FundedNext, The5ers and Topstep challenges, resampling your own history.",
                "",
            ),
            (
                "eye",
                "You invest with a manager, a signal or a fund",
                "The percentage you are shown may come from deposits, a few good months or a "
                "backtest.",
                "their account history (MetaTrader, Myfxbook, FX Blue or an MQL5 signal) or "
                "their monthly returns table as CSV or Excel.",
                "the result kept apart from deposits and withdrawals, whether the account looks "
                "like its backtest, whether the history is evidence or luck and, with 24 "
                "months or more, its year-by-month calendar and deepest fall.",
                "cuenta-proveedor",
            ),
        ],
        "guide": "Which file to upload",
        "more": "See what it checks for your case",
        "also": "Another case:",
        "start": "Start",
    },
}

AUDIENCES["pt"] = AUDIENCES_PT


def _audiences(locale: str) -> str:
    words = AUDIENCES[locale]
    cards = []
    for i, (name, title, pain, upload, get, _guide) in enumerate(words["items"]):
        page = AUDIENCE_PAGES[i]
        link = f"<a href='{_e(audience_url(page.slug, locale))}'>{_e(words['more'])}</a>"
        cards.append(
            f"<div class='card spot audience' data-reveal style='--i:{i % 2}'>"
            f"<div class='icon'>{icon(name)}</div><h3>{_e(title)}</h3><p>{_e(pain)}</p>"
            f"<p><strong>{_e(words['upload'])}:</strong> {_e(upload)}</p>"
            f"<p><strong>{_e(words['get'])}:</strong> "
            f"{_e(get.format(presets=len(PRESETS)))}</p><p>{link}</p></div>"
        )
    # Pages beyond the four cards get a plain link under them.
    extra = "".join(
        f"<p class='muted audience-also'>{_e(words['also'])} "
        f"<a href='{_e(audience_url(page.slug, locale))}'>{_e(page.text[locale].title)}</a></p>"
        for page in AUDIENCE_PAGES[len(words["items"]) :]
    )
    return (
        "<section class='section light' id='para-quien'><div class='wrap'>"
        + _section_head(words["eyebrow"], _title_pair(words["title"]), words["lead"])
        + f"<div class='cards cards-2'>{''.join(cards)}</div>{extra}</div></section>"
    )


def _problems(locale: str) -> str:
    ui = _UI[locale]
    items = "".join(
        f"<div data-reveal style='--i:{i}'><span class='n'>0{i + 1}</span>"
        f"<h3>{_e(title)}</h3><p>{_e(text)}</p></div>"
        for i, (title, text) in enumerate(ui["problems"])
    )
    return (
        "<section class='section light'><div class='wrap'>"
        + _section_head(ui["problem_eyebrow"], _title_pair(ui["problem_title"]), ui["problem_lead"])
        + f"<div class='trio'>{items}</div></div></section>"
    )


def _dimensions(locale: str, copy: dict[str, Any]) -> str:
    ui = _UI[locale]
    titles = _dimension_titles(locale)
    cards = "".join(
        f"<div class='card spot' data-reveal style='--i:{i % 3}'>"
        f"<div class='icon'>{icon(_DIMENSION_ICONS[name])}</div>"
        f"<h3>{_e(titles[name])}</h3><p>{_e(text)}</p></div>"
        for i, (name, text) in enumerate(zip(DIMENSION_ORDER, copy["measure"], strict=False))
    )
    return (
        "<section class='section dark' id='measure'><div class='wrap'>"
        + _section_head(copy["measure_title"], _title_pair(ui["dims_title"]))
        + f"<p class='statement'>{_e(copy['pitch'])}</p>"
        + f"<div class='cards'>{cards}</div>"
        + "</div></section>"
    )


def _evidence(locale: str, copy: dict[str, Any]) -> str:
    ui = _UI[locale]
    rows = "".join(
        f"<div class='tag-row' data-reveal style='--i:{i}'><div>"
        f"<span class='badge {tag}'>{tag}</span></div><p>{_e(text)}</p></div>"
        for i, (tag, text) in enumerate(ui["evidence"])
    )
    return (
        "<section class='section light'><div class='wrap split'><div class='sticky'>"
        + _section_head(
            ui["evidence_eyebrow"], _title_pair(ui["evidence_title"]), ui["evidence_lead"]
        )
        + f"<div class='disclaimer' data-reveal><strong>{_e(copy['not_title'])}.</strong> "
        f"{_e(copy['not'])}</div></div><div class='tags'>{rows}</div></div></section>"
    )


#: Why a stranger can trust Rigor before paying: each claim comes with the
#: page where they can check it. Nothing here promises a result.
TRUST_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Trabajo real, no humo",
        "title": ("Sin bots, sin señales,", "sin promesas."),
        "lead": (
            "Rigor no vende estrategias ni resultados: mide el archivo que subes y te enseña "
            "cómo lo mide. Todo lo de esta sección lo puedes comprobar antes de pagar."
        ),
        "items": [
            (
                "eye",
                "Mira un informe entero antes de pagar",
                "El ejemplo es un informe completo, con su PDF, hecho con datos sintéticos: ves "
                "exactamente lo que recibes.",
                "Ver el ejemplo",
                "sample",
            ),
            (
                "layers",
                "Métodos publicados, no una caja negra",
                "Sharpe probabilístico y deflactado (Bailey y López de Prado), probabilidad de "
                "sobreajuste y bootstrap estacionario (Politis y Romano). Cada prueba y cada "
                "umbral están escritos.",
                "Leer la metodología",
                "method",
            ),
            (
                "shield",
                "No vendemos bots ni señales",
                "No ejecutamos órdenes ni pedimos las claves de tu bróker, y ningún informe "
                "promete resultados: un filtro automático frena cualquier texto que lo haga.",
                "",
                "",
            ),
            (
                "hash",
                "Un informe que no se puede retocar",
                "Cada informe lleva la huella SHA-256 de tus archivos y de su resultado; "
                "cualquiera puede comprobar que un PDF o un JSON no se editó.",
                "Comprobar un informe",
                "check",
            ),
            (
                "lock",
                "Tu archivo es tuyo",
                "Nunca se publica. Si no desbloqueas el informe, se borra a los {retention} "
                "días, y puedes borrar tu cuenta y tus informes cuando quieras.",
                "Política de privacidad",
                "privacy",
            ),
            (
                "card",
                "Si lee mal tu archivo, te devolvemos el importe",
                "Si las operaciones, el saldo o las fechas no coinciden con tu plataforma y no "
                "podemos corregirlo, te devolvemos lo que pagaste por ese informe.",
                "Términos del servicio",
                "terms",
            ),
        ],
        "who": "Quién está detrás: {name}, {address}.",
        "ask": "¿Dudas antes de subir? Escríbenos por WhatsApp; responde una persona.",
        "ask_link": "Escribir por WhatsApp",
    },
    "en": {
        "eyebrow": "Real work, not hype",
        "title": ("No bots, no signals,", "no promises."),
        "lead": (
            "Rigor sells no strategies and no results: it measures the file you upload and "
            "shows you how it measures it. You can check everything in this section before "
            "you pay."
        ),
        "items": [
            (
                "eye",
                "See a whole report before you pay",
                "The sample is a full report, with its PDF, built from synthetic data: you see "
                "exactly what you get.",
                "See the sample",
                "sample",
            ),
            (
                "layers",
                "Published methods, not a black box",
                "Probabilistic and deflated Sharpe (Bailey and López de Prado), probability of "
                "backtest overfitting and the stationary bootstrap (Politis and Romano). Every "
                "test and every threshold is written down.",
                "Read the methodology",
                "method",
            ),
            (
                "shield",
                "We sell no bots and no signals",
                "We place no orders and ask for no broker keys, and no report promises results: "
                "an automatic filter stops any text that does.",
                "",
                "",
            ),
            (
                "hash",
                "A report that cannot be retouched",
                "Every report carries the SHA-256 fingerprint of your files and of its result; "
                "anyone can check that a PDF or JSON was not edited.",
                "Check a report",
                "check",
            ),
            (
                "lock",
                "Your file stays yours",
                "It is never published. If you do not unlock the report it is deleted after "
                "{retention} days, and you can delete your account and your reports whenever "
                "you like.",
                "Privacy policy",
                "privacy",
            ),
            (
                "card",
                "If it misreads your file, you get your money back",
                "If the trades, balance or dates do not match your platform and we cannot fix "
                "it, we refund what you paid for that report.",
                "Terms of service",
                "terms",
            ),
        ],
        "who": "Who is behind it: {name}, {address}.",
        "ask": "Questions before you upload? Write to us on WhatsApp; a person answers.",
        "ask_link": "Write on WhatsApp",
    },
    "pt": TRUST_PT,
}


def _trust(locale: str, *, retention_days: int, operator: tuple[str, str], contact_url: str) -> str:
    """Why trust Rigor, each point with the page that proves it."""
    words = TRUST_COPY[locale]
    linked = link_locale(locale)
    hrefs = {
        "sample": _sample_url(linked),
        "method": method_url(linked),
        "check": _check_url(linked),
        "privacy": legal_url("privacy", linked),
        "terms": legal_url("terms", linked),
    }
    cards = "".join(
        f"<div class='card spot' data-reveal style='--i:{i % 3}'>"
        f"<div class='icon'>{icon(name)}</div><h3>{_e(title)}</h3>"
        f"<p>{_e(text.format(retention=retention_days))}</p>"
        + (f"<p><a href='{_e(hrefs[target])}'>{_e(label)}</a></p>" if target else "")
        + "</div>"
        for i, (name, title, text, label, target) in enumerate(words["items"])
    )
    name, address = operator
    who = (
        f"<p class='trust-who'>{_e(words['who'].format(name=name, address=address))}</p>"
        if name and address
        else ""
    )
    ask = (
        f"<p class='trust-ask'>{_e(words['ask'])} "
        f"<a href='{_e(contact_url)}' rel='noopener'>{_e(words['ask_link'])}</a></p>"
        if contact_url
        else ""
    )
    return (
        "<section class='section light' id='confianza'><div class='wrap'>"
        + _section_head(words["eyebrow"], _title_pair(words["title"]), words["lead"])
        + f"<div class='cards'>{cards}</div>"
        + (f"<div class='trust-foot' data-reveal>{who}{ask}</div>" if who or ask else "")
        + "</div></section>"
    )


def _differences(locale: str) -> str:
    ui = _UI[locale]
    cards = "".join(
        f"<div class='card spot' data-reveal style='--i:{i % 2}'>"
        f"<div class='icon'>{icon(name)}</div><h3>{_e(title)}</h3><p>{_e(text)}</p></div>"
        for i, (name, title, text) in enumerate(ui["diffs"])
    )
    return (
        "<section class='section light'><div class='wrap'>"
        + _section_head(ui["diff_eyebrow"], _title_pair(ui["diff_title"]))
        + f"<div class='cards cards-2'>{cards}</div>{_investor_card(locale)}</div></section>"
    )


#: The landing's pointer for someone about to copy or fund another trader.
INVESTOR_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Para quien va a copiar o invertir",
        "title": "¿Vas a copiar o invertir con alguien?",
        "text": (
            "Pide el historial completo de su cuenta de MetaTrader y súbelo junto a su "
            "backtest. Rigor lee el dinero que de verdad entró y salió y te dice si la cuenta "
            "se parece a lo que muestra el backtest, con cada cifra etiquetada según su evidencia."
        ),
        "points": (
            "Depósitos y retiros separados del resultado de operar",
            "La cuenta real frente a miles de historias de su backtest",
            "Sin conectarnos a su bróker ni a tu dinero",
        ),
        "cta": "Cómo revisar su cuenta",
    },
    "en": {
        "eyebrow": "For anyone about to copy or invest",
        "title": "About to copy or invest with someone?",
        "text": (
            "Ask for the full history of their MetaTrader account and upload it with their "
            "backtest. Rigor reads the money that really went in and out and tells you whether "
            "the account looks like its backtest, with every figure labelled by its evidence."
        ),
        "points": (
            "Deposits and withdrawals kept apart from trading results",
            "The live account set against thousands of histories from its backtest",
            "No connection to their broker or to your money",
        ),
        "cta": "How to review their account",
    },
}

INVESTOR_COPY["pt"] = INVESTOR_PT


def _investor_card(locale: str) -> str:
    words = INVESTOR_COPY[locale]
    points = "".join(f"<li>{icon('check')}<span>{_e(p)}</span></li>" for p in words["points"])
    return (
        "<div class='investor' data-reveal>"
        f"<div><span class='eyebrow'><span class='dot'></span>{_e(words['eyebrow'])}</span>"
        f"<h3>{_e(words['title'])}</h3><p>{_e(words['text'])}</p>"
        f"<a class='btn btn-dark' href='{_e(guide_url('cuenta-proveedor', locale))}'>"
        f"{_e(words['cta'])}<span class='go'>{icon('arrow')}</span></a></div>"
        f"<ul class='checks'>{points}</ul></div>"
    )


def _how_html(copy: dict[str, Any], locale: str) -> str:
    ui = _UI[locale]
    steps = "".join(
        f"<li data-reveal style='--i:{i}'>{_e(step)}</li>" for i, step in enumerate(copy["how"])
    )
    return (
        "<section class='section dark' id='how'><div class='wrap'>"
        + _section_head(ui["how_eyebrow"], f"<h2 class='h2'>{_e(copy['how_title'])}</h2>")
        + f"<ol class='steps'>{steps}</ol>"
        + f"<div class='section-tight' data-reveal style='padding-bottom:0'><p class='muted'>"
        f"{_e(copy['guides_text'])} "
        f"<a href='{_e(guides_index_url(locale))}'>{_e(copy['guides_link'])}</a>"
        "</p></div>" + "</div></section>"
    )


def _checks(items: list[str]) -> str:
    return (
        "<ul class='checks'>"
        + "".join(f"<li>{icon('check')}<span>{_e(item)}</span></li>" for item in items)
        + "</ul>"
    )


def _prices_html(
    copy: dict[str, Any],
    locale: str,
    *,
    free_mode: bool,
    price_usd: float,
    access_codes: bool,
    card_payments: bool,
    contact_url: str,
    pack_price_usd: float = 0.0,
) -> str:
    ui = _UI[locale]
    head = _section_head(ui["pricing_eyebrow"], f"<h2 class='h2'>{_e(copy['prices_title'])}</h2>")
    if free_mode:
        body = (
            "<div class='prices prices-one'><div class='price featured' data-reveal>"
            f"<span class='price-name'>{_e(ui['plan_full'])}</span>"
            f"<div class='price-amount'>{_e(ui['plan_free_amount'])}</div>"
            f"<p class='muted'>{_e(copy['price_free_mode'])}</p>"
            + _checks(ui["free_items"] + ui["full_items"])
            + f"<a class='btn btn-primary' href='#subir'>{_e(ui['cta'])}</a></div></div>"
        )
    else:
        ways = []
        if card_payments:
            ways.append(f"<li>{icon('check')}<span>{_e(copy['pay_card'])}</span></li>")
        if access_codes:
            link = (
                f" <a href='{_e(contact_url)}' rel='noopener'>{_e(copy['contact'])}</a>"
                if contact_url
                else ""
            )
            ways.append(f"<li>{icon('check')}<span>{_e(copy['pay_code'])}{link}</span></li>")
        body = (
            "<div class='prices'>"
            f"<div class='price' data-reveal style='--i:0'><span class='price-name'>"
            f"{_e(copy['price_free_title'])}</span>"
            f"<div class='price-amount'>{_e(ui['plan_free_amount'])}"
            f"<small>{_e(ui['plan_free_note'])}</small></div>"
            f"<p class='muted'>{_e(copy['price_free'])}</p>"
            + _checks(ui["free_items"])
            + f"<a class='btn btn-ghost' href='#subir'>{_e(ui['cta'])}</a></div>"
            f"<div class='price featured' data-reveal style='--i:1'>"
            f"<span class='ribbon'>{_e(ui['plan_badge'])}</span>"
            f"<span class='price-name'>{_e(copy['price_full_title'])}"
            f"</span><div class='price-amount'>USD {price_usd:.0f}"
            f"<small>{_e(ui['plan_full_note'])}</small></div>"
            f"<p class='muted'>{_e(copy['price_full'])}</p>"
            + (
                "<p class='price-pack'><strong>"
                + _e(
                    copy["price_pack"].format(
                        n=PACK_CREDITS, price=pack_price_usd, each=pack_price_usd / PACK_CREDITS
                    )
                )
                + "</strong></p>"
                if pack_price_usd
                else ""
            )
            + _checks(ui["full_items"])
            + f"<a class='btn btn-primary' href='#subir'>{_e(ui['cta_full'])}</a></div></div>"
            + (f"<ul class='checks pay-ways' data-reveal>{''.join(ways)}</ul>" if ways else "")
            + f"<p class='muted refund-note' data-reveal>{_e(copy['refund_note'])}</p>"
            + f"<p class='muted account-note' data-reveal>{_e(copy['account_note'])} "
            f"<a href='{'/registro' if locale == 'es' else '/signup'}'>"
            f"{_e(copy['account_link'])}</a></p>"
            + f"<p class='method-link' data-reveal><a href='{_e(method_url(link_locale(locale)))}'>"
            f"{_e(_method_title(locale))}{icon('arrow')}</a></p>"
        )
    return (
        f"<section class='section dark' id='pricing'><div class='wrap'>{head}{body}</div></section>"
    )


def _drop(
    name: str,
    label: str,
    accept: str,
    help_html: str,
    locale: str,
    *,
    main: bool = False,
) -> str:
    ui = _UI[locale]
    if main:
        formats = "".join(f"<span>{_e(p)}</span>" for p in PLATFORMS)
        return (
            f"<div class='field'><label for='f-{name}'>{_e(label)}</label>"
            f"<div class='drop drop-main'><div class='icon'>{icon('upload')}</div>"
            f"<div class='drop-title'>{_e(ui['drop_title'])}</div>"
            f"<div class='drop-sub'>{_e(ui['drop_sub'])}</div>"
            f"<div class='formats'>{formats}</div><div class='drop-file' aria-live='polite'></div>"
            f"<input id='f-{name}' type='file' name='{name}' accept='{accept}'></div>"
            f"<div class='help'>{help_html}</div></div>"
        )
    return (
        f"<div class='field'><label for='f-{name}'>{_e(label)}</label>"
        f"<div class='drop'><div class='icon'>{icon('file')}</div><div class='drop-txt'>"
        f"<div class='drop-title'>{_e(ui['drop_small'])}</div>"
        f"<div class='drop-file' aria-live='polite'></div>"
        f"<input id='f-{name}' type='file' name='{name}' accept='{accept}'></div></div>"
        + (f"<div class='help'>{help_html}</div>" if help_html else "")
        + "</div>"
    )


def _field(label: str, control: str, help_text: str = "") -> str:
    """A labelled form control; the label and help text are tied to it by id."""
    match = re.search(r"name='([a-z_]+)'", control)
    if not match:
        return (
            f"<div class='field'><label>{_e(label)}</label>{control}"
            + (f"<div class='help'>{_e(help_text)}</div>" if help_text else "")
            + "</div>"
        )
    ident = f"f-{match.group(1)}"
    attrs = f" id='{ident}'" + (f" aria-describedby='{ident}-help'" if help_text else "")
    control = control.replace(match.group(0), match.group(0) + attrs, 1)
    return (
        f"<div class='field'><label for='{ident}'>{_e(label)}</label>{control}"
        + (f"<div class='help' id='{ident}-help'>{_e(help_text)}</div>" if help_text else "")
        + "</div>"
    )


def _signin_first(copy: dict[str, Any], locale: str) -> str:
    """Before the file: the upload needs an account (or a bought code)."""
    signup, signin = ("/registro", "/entrar") if locale == "es" else ("/signup", "/login")
    return (
        f"<div class='signin-first'><p>{_e(copy['signin_first'])}</p>"
        "<div class='inline-form'>"
        f"<a class='btn btn-primary' href='{signup}'>{_e(copy['signin_create'])}</a>"
        f"<a class='btn btn-ghost' href='{signin}'>{_e(copy['signin_enter'])}</a>"
        "</div></div>"
    )


def _upload_form(
    copy: dict[str, Any],
    locale: str,
    *,
    note: str,
    flash: str,
    err: str,
    access_codes: bool,
    retention_days: int,
    extras_open: bool = False,
    signin_first: bool = False,
) -> str:
    ui = _UI[locale]
    linked = link_locale(locale)
    # The report exists in Spanish and English; a Portuguese page asks for English.
    selected = {"es": "", "en": ""}
    selected[linked] = " selected"
    code_field = ""
    if access_codes:
        code_field = _field(
            copy["access_code"],
            "<input type='text' name='access_code' maxlength='40' autocomplete='off' "
            "placeholder='AUD-XXXX-XXXX-XXXX' spellcheck='false'>",
            copy["access_code_help"],
        )
    # One short line; the full list of formats and the export guides open on demand.
    report_help = (
        f"{_e(copy['report_short'])}<details class='more-help'><summary>"
        f"{_e(copy['guide_q'])}</summary>"
        f"<p>{_e(copy['report_help'])}</p>"
        f"<p>{_e(copy['guide_list'])}: {_guide_links(locale)}</p></details>"
    )
    mapping = (
        "<details class='adv map-columns'><summary><span>"
        f"{_e(copy['map_title'])}</span>"
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
        "aria-hidden='true'><path d='M6 9l6 6 6-6'/></svg></summary><div class='adv-body'>"
        f"<p class='help'>{_e(copy['map_help'])}</p>"
        "<datalist id='report-columns'></datalist>"
        "<p class='map-found' id='report-columns-shown' hidden>"
        f"<span>{_e(copy['map_found'])}</span></p>"
        + "".join(
            f"<fieldset class='map-group'><legend>{_e(title)}</legend><div class='form-grid'>"
            + "".join(
                _field(
                    copy["map_roles"][role],
                    f"<input type='text' name='col_{role}' maxlength='100' list='report-columns' "
                    "autocomplete='off' spellcheck='false'>",
                )
                for role in roles
            )
            + "</div></fieldset>"
            for title, roles in copy["map_groups"]
        )
        + "</div></details>"
    )
    optimization_help = (
        f"{_e(copy['optimization_help'])} <a href='{_e(guide_url('mt5-optimization', locale))}'>"
        f"{_e(copy['optimization_guide'])}</a>"
    )
    advanced = (
        "<details class='adv'><summary><span>"
        f"{_e(ui['advanced'])} <small>· {_e(ui['advanced_note'])}</small></span>"
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
        "aria-hidden='true'><path d='M6 9l6 6 6-6'/></svg></summary><div class='adv-body'>"
        + _drop("trades", copy["trades"], ".csv,text/csv", _e(copy["trades_help"]), locale)
        + "<div class='form-grid'>"
        + _drop("benchmark", copy["benchmark"], ".csv,text/csv", "", locale)
        + _drop("variants", copy["variants"], ".csv,text/csv", _e(copy["variants_help"]), locale)
        + _field(
            copy["trials"], "<input type='number' name='trials' min='1' step='1' placeholder='1'>"
        )
        + _field(
            copy["cost_bps"],
            "<input type='number' name='cost_bps' min='0' step='0.1' placeholder='0'>",
        )
        + _field(copy["oos_start"], "<input type='date' name='oos_start'>")
        + _field(
            copy["benchmark_applicable"],
            f"<select name='benchmark_applicable'><option value='yes'>{_e(copy['yes'])}</option>"
            f"<option value='no'>{_e(copy['no'])}</option></select>",
        )
        + _field(
            copy["initial_balance"],
            "<input type='number' name='initial_balance' min='0' step='0.01'>",
        )
        + "</div>"
        + "<label class='check'><input type='checkbox' name='net_of_fees' value='on'>"
        + f"<span>{_e(copy['net_of_fees'])}</span></label>"
        + _field(
            copy["description"],
            "<textarea name='description' rows='3' maxlength='2000'></textarea>",
        )
        + "</div></details>"
    )
    points = "".join(
        f"<li>{icon('check')}<span>{_e(point)}</span></li>" for point in ui["upload_points"]
    )
    busy_steps = "".join(
        f"<li style='--i:{i}'>{_e(step)}</li>" for i, step in enumerate(ui["busy_steps"])
    )
    return (
        "<section class='section light' id='subir'><div class='wrap upload'>"
        "<div class='sticky'>"
        + _section_head(ui["upload_eyebrow"], _title_pair(ui["upload_title"]), ui["upload_lead"])
        + f"<ul class='checks' data-reveal>{points}</ul></div>"
        + "<div class='panel' data-reveal>"
        + f"<h2 class='label' style='font-size:1.2rem;margin-bottom:6px'>{_e(copy['form_title'])}"
        "</h2>"
        + f"{flash}{err}<p class='panel-note'>{icon('shield')}{_e(note)}</p>"
        + (_signin_first(copy, locale) if signin_first else "")
        + "<form method='post' action='/audits' enctype='multipart/form-data' data-busy='busy'>"
        + _drop(
            "report",
            copy["report"],
            ".htm,.html,.csv,.xlsx",
            report_help,
            locale,
            main=True,
        )
        + mapping
        + f"<div class='or-rule' aria-hidden='true'><span>{_e(copy['or_word'])}</span></div>"
        + _drop(
            "equity",
            copy["equity"],
            ".csv,.txt,.tsv,.xlsx,text/csv",
            _e(copy["equity_help"]),
            locale,
        )
        # The one-file case stays short; the second files and the challenge open on demand.
        + f"<details class='adv extras'{' open' if extras_open else ''}><summary><span>"
        f"{_e(ui['extras'])} <small>· {_e(ui['extras_note'])}</small></span>"
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
        "aria-hidden='true'><path d='M6 9l6 6 6-6'/></svg></summary><div class='adv-body'>"
        "<div class='form-grid'>"
        + _drop("optimization", copy["optimization"], ".xml", optimization_help, locale)
        + _drop("live", copy["live"], ".htm,.html,.csv,.xlsx", _e(copy["live_help"]), locale)
        + "</div>"
        + _field(
            copy["challenge"],
            f"<select name='challenge'>{_preset_options(linked)}</select>",
            copy["challenge_help"].format(as_of=_plain_date(AS_OF, locale)),
        )
        + "</div></details>"
        + "<div class='form-grid'>"
        + _field(
            copy["locale"],
            f"<select name='locale'><option value='es'{selected['es']}>Español</option>"
            f"<option value='en'{selected['en']}>English</option></select>",
            copy.get("locale_note", ""),
        )
        + code_field
        + "</div>"
        + advanced
        + "<label class='check'><input type='checkbox' name='consent' value='on' required>"
        f"<span>{_e(copy['consent'].format(retention=retention_days))} "
        f"{_e(copy['consent_read'])} "
        f"<a href='{_e(legal_url('terms', linked))}'>{_e(copy['terms_link'])}</a> · "
        f"<a href='{_e(legal_url('privacy', linked))}'>{_e(copy['privacy_link'])}</a></span>"
        "</label>" + "<div class='submit-row'><button class='btn btn-primary btn-lg btn-block' "
        f"type='submit'>{_e(copy['submit'])}<span class='go'>{icon('arrow')}</span></button></div>"
        + "</form></div></div>"
        + "<div class='busy' id='busy' role='status' aria-live='polite'><div class='busy-card'>"
        f"<div class='loader'></div><h2>{_e(ui['busy_title'])}</h2>"
        f"<p class='muted'>{_e(ui['busy_sub'])}</p><ol>{busy_steps}</ol></div></div>" + "</section>"
    )


def _faq_html(copy: dict[str, Any], locale: str, *, retention_days: int) -> str:
    ui = _UI[locale]
    items = "".join(
        f"<details><summary>{_e(question)}</summary>"
        f"<p>{_e(answer.format(retention=retention_days))}</p></details>"
        for question, answer in copy["faq"]
    )
    return (
        "<section class='section dark' id='faq'><div class='wrap wrap-mid'>"
        + _section_head(ui["faq_eyebrow"], f"<h2 class='h2'>{_e(copy['faq_title'])}</h2>")
        + f"<div class='faq' data-reveal>{items}</div></div></section>"
    )


def _final_cta(copy: dict[str, Any], locale: str, sample: str, *, joined: bool) -> str:
    ui = _UI[locale]
    flash = f"<div class='flash'>{_e(copy['joined'])}</div>" if joined else ""
    return (
        "<section class='section dark' style='padding-top:0'><div class='wrap'>"
        "<div class='cta-band center' data-reveal style='max-width:900px'>"
        + _title_pair(ui["final_title"])
        + f"<p class='lead' style='margin-top:24px'>{_e(ui['final_lead'])}</p>"
        "<div class='hero-cta' style='justify-content:center'>"
        f"<a class='btn btn-primary btn-lg' href='#subir'>{_e(ui['cta'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(sample)}'>{_e(ui['cta_sample'])}{icon('arrow')}</a></div>"
        f"<div class='news center' id='news'><p class='label'>{_e(copy['waitlist_title'])}</p>"
        f"{flash}<form class='inline-form' method='post' action='/waitlist'>"
        f"<input type='email' name='email' required placeholder='{_e(copy['email'])}' "
        f"aria-label='{_e(copy['email'])}'><input type='hidden' name='lang' value='{_e(locale)}'>"
        f"<button class='btn btn-ghost' type='submit'>{_e(copy['join'])}</button></form></div>"
        "</div></div></section>"
    )


#: The landing in each language, for its language switch.
LANDING_PATHS: dict[str, str] = {"es": "/", "en": "/en", "pt": "/pt"}


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
    pack_price_usd: float = 0.0,
    extras_open: bool = False,
    signed_in: bool | None = None,
    operator: tuple[str, str] = ("", ""),
) -> str:
    """``signed_in=False`` says, above the file fields, that an upload needs an account.

    ``operator`` (name, address) is shown under "who is behind it" when both are set."""
    locale = _locale(locale)
    copy = _COPY[locale]
    meta = _public_meta(copy["title"], copy["meta_description"], locale, _home(locale), base_url)
    note = copy["free_note"] if free_mode else copy["paid_note"].format(price=price_usd)
    sample = _sample_url(link_locale(locale))
    flash = f"<div class='flash'>{_e(copy['joined'])}</div>" if joined else ""
    err = f"<div class='error'>{_e(error)}</div>" if error else ""
    body = (
        _hero(locale, sample)
        + _specs(locale)
        + _audiences(locale)
        + _problems(locale)
        + _dimensions(locale, copy)
        + _evidence(locale, copy)
        + _how_html(copy, locale)
        + _differences(locale)
        + _trust(locale, retention_days=retention_days, operator=operator, contact_url=contact_url)
        + _prices_html(
            copy,
            locale,
            free_mode=free_mode,
            price_usd=price_usd,
            access_codes=access_codes,
            card_payments=card_payments,
            contact_url=contact_url,
            pack_price_usd=pack_price_usd,
        )
        + _upload_form(
            copy,
            locale,
            note=note,
            flash=flash if not joined else "",
            err=err,
            access_codes=access_codes,
            retention_days=retention_days,
            extras_open=extras_open,
            signin_first=signed_in is False and not free_mode,
        )
        + _faq_html(copy, locale, retention_days=retention_days)
        + _final_cta(copy, locale, sample, joined=joined)
    )
    return _page(copy["title"], locale, body, meta_html=meta, alternates=LANDING_PATHS)


def _evidence_value(item: Any) -> str:
    """A figure and its evidence tag as HTML: "120" then the DECLARED badge."""
    if isinstance(item, dict) and "value" in item:
        value = item.get("value")
        shown = "—" if value is None else _e(f"{value:,}" if isinstance(value, int) else value)
        evidence = str(item.get("evidence", ""))
        tag = (
            f" <span class='badge {_e(evidence)}'>{_e(evidence)}</span>"
            if evidence in ("MEASURED", "DECLARED", "NOT_MEASURED")
            else ""
        )
        return f"<span class='vc'>{shown}{tag}</span>"
    return "—" if item is None else _e(str(item))


def _page_hero(eyebrow: str, title: str, lead: str = "", crumbs: str = "", *, dot: str = "") -> str:
    return (
        "<section class='page-hero'>"
        + aurora()
        + grid_bg()
        + "<div class='wrap'>"
        + (f"<div class='crumbs rise' style='--i:0'>{crumbs}</div>" if crumbs else "")
        + f"<div class='eyebrow rise' style='--i:1;margin-top:18px'>"
        f"<span class='dot{' ' + dot if dot else ''}'></span>"
        f"{_e(eyebrow)}</div><h1 class='rise' style='--i:2'>{_e(title)}</h1>"
        + (f"<p class='lead rise' style='--i:3'>{_e(lead)}</p>" if lead else "")
        + "</div></section>"
    )


_MONTHS = {
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "pt": MONTHS_PT,
}


def _plain_date(stamp: str, locale: str) -> str:
    """An ISO date as ``25 sep 2026`` or ``Sep 25, 2026``; anything else as it came."""
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    month = _MONTHS[locale][when.month - 1]
    if locale in ("es", "pt"):
        return f"{when.day} {month} {when.year}"
    return f"{month} {when.day}, {when.year}"


def _utc_time(stamp: str, locale: str) -> str:
    """An ISO UTC stamp as a readable ``<time>`` (24 sep 2026 · 17:30 UTC).

    The exact stamp stays in the ``datetime`` attribute; anything that does
    not parse is shown as it came.
    """
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return _e(stamp)
    month = _MONTHS[locale][when.month - 1]
    if locale == "es":
        day = f"{when.day} {month} {when.year}"
    else:
        day = f"{month} {when.day}, {when.year}"
    return f"<time datetime='{_e(stamp)}'>{day} · {when:%H:%M} UTC</time>"


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
    locale = _locale(locale)
    copy = _COPY[locale]
    ui = _UI[locale]
    other = "en" if locale == "es" else "es"
    verdict = result["verdict"]
    overall = str(verdict["overall"])
    titles = DIMENSION_TITLES.get(locale, DIMENSION_TITLES["es"])
    # The same cards as the report's "what it means for you", so a buyer
    # reads one dimension at a time on a phone.
    cards = "".join(
        f"<div class='item s-{_e(str(d['status']))}'>"
        f"<h3>{_e(titles.get(d['name'], d['name']))} {_status_chip(str(d['status']), locale)}</h3>"
        f"<p>{_e(meaning(d['name'], d['status'], locale))}</p></div>"
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
        (
            copy["v_format"],
            SOURCE_NAMES.get(str(inputs.get("source_format")), "")
            or inputs.get("source_format")
            or inputs.get("source")
            or "-",
        ),
        (copy["v_engine"], f"{engine.get('name', '')} {engine.get('package_version', '')}"),
    ]
    # Words read as words, figures carry their evidence badge, and only the
    # hash keeps the code style.
    detail_rows = (
        "".join(f"<tr><td>{_e(label)}</td><td>{_e(value)}</td></tr>" for label, value in details)
        + "".join(
            f"<tr><td>{_e(label)}</td><td>{_evidence_value(item)}</td></tr>"
            for label, item in (
                (copy["v_trials_declared"], declared.get("trials")),
                (copy["v_trials_used"], trials_used),
            )
        )
        + f"<tr><td>{_e(copy['v_result_sha'])}</td><td><code>{_e(result_sha256)}</code></td></tr>"
    )
    page_url = f"{base_url}/v/{public_id}"
    badge_url = f"{page_url}/badge.svg?lang={locale}"
    snippet = (
        f"<a href='{page_url}'><img src='{badge_url}' alt='{BADGE_NOTICE[locale]}' "
        "width='480' height='72'></a>"
    )
    cls_label = "Clase" if locale == "es" else "Class"
    title = f"{copy['v_title']} · {cls_label} {overall}"
    audited = str(result.get("generated_at_utc", ""))
    description = copy["v_description"].format(
        cls_label=cls_label, overall=overall, date=audited[:10], notice=BADGE_NOTICE[locale]
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
    hero = (
        "<section class='page-hero'>" + aurora() + grid_bg() + "<div class='wrap'>"
        f"<div class='eyebrow rise'><span class='dot'></span>{_e(ui['v_eyebrow'])}</div>"
        f"<h1 class='rise' style='--i:1'>{_e(copy['v_title'])}</h1>"
        "<div class='v-hero rise' style='--i:2'>"
        + class_ring(overall, size="xl")
        + f"<div><div class='verdict-k'>{_e(cls_label)} {_e(overall)}</div>"
        f"<p class='verdict-text'>{_e(class_text(overall, locale))}</p>"
        "<div class='v-facts'>"
        f"<div><b>{_e(copy['v_audited'])}</b><span>{_utc_time(audited, locale)}</span></div>"
        f"<div><b>{_e(copy['v_published'])}</b><span>{_utc_time(published_at, locale)}</span></div>"
        f"<div><b>{_e(ui['v_id'])}</b><span>{_e(public_id)}</span></div>"
        "</div></div></div></div></section>"
    )
    main = (
        "<div class='paper page-main'><div class='wrap wrap-mid'>"
        f"<div class='disclaimer' style='margin-bottom:16px'><strong>{_e(copy['v_notice'])}."
        f"</strong> {_e(VERIFICATION_NOTICE[locale])}</div>"
        f"<p class='check-cta'>{icon('shield')}<span>{_e(ui['v_check'])} "
        f"<a href='{_check_url(locale)}'>{_e(ui['v_check_link'])}</a></span></p>"
        f"<section class='rsec'><h2>{_e(copy['v_dimensions'])}</h2>"
        f"<div class='meaning'>{cards}</div></section>"
        f"<section class='rsec'><h2>{_e(copy['v_inputs'])}</h2>"
        f"<table class='kv'>{digest_rows}</table></section>"
        f"<section class='rsec'><h2>{_e(copy['v_details'])}</h2>"
        f"<table class='kv'>{detail_rows}</table>"
        "</section>"
        f"<section class='rsec'><h2>{_e(copy['v_badge'])}</h2><div class='badge-preview'>"
        f"<img src='/v/{_e(public_id)}/badge.svg?lang={_e(locale)}' "
        f"alt='{_e(BADGE_NOTICE[locale])}' width='480' height='72'></div>"
        f"<p class='muted' style='margin-top:18px'>{_e(copy['v_badge_help'])}</p>"
        f"<pre><code id='badge-code'>{_e(snippet)}</code></pre>"
        f"<div class='copy-row'><button class='btn btn-dark btn-sm' type='button' "
        f"data-copy='badge-code' data-done='{_e(ui['v_copied'])}' hidden>{_e(ui['v_copy'])}"
        "</button></div></section></div></div>"
    )
    return _page(
        title,
        locale,
        hero + main,
        meta_html=meta,
        switch_href=f"/v/{public_id}?lang={other}",
        solid_nav=True,
    )


def badge_svg(*, overall: str, public_id: str, audited_on: str, locale: str = "es") -> str:
    """The badge: class, id, date and the fixed notice. Never a return figure."""
    locale = locale if locale in BADGE_NOTICE else "es"
    title = BRAND
    label = "Clase" if locale == "es" else "Class"
    colour = CLASS_COLOURS.get(overall, "#475569")
    notice = BADGE_NOTICE[locale]
    font = "Inter,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='480' height='72' viewBox='0 0 480 72' "
        f"role='img' aria-label='{_e(f'{title} · {label} {overall} · {notice}')}'>"
        f"<title>{_e(f'{title} · {label} {overall} · {notice}')}</title>"
        "<rect x='.5' y='.5' width='479' height='71' rx='16' fill='#0b0b0d' stroke='#2a2a2f'/>"
        "<rect x='8' y='8' width='56' height='56' rx='12' fill='#141416' "
        f"stroke='{colour}' stroke-width='2'/>"
        f"<text x='36' y='49' font-family='{font}' font-size='34' font-weight='600' "
        f"fill='{colour}' text-anchor='middle' letter-spacing='-1'>{_e(overall)}</text>"
        f"<text x='78' y='26' font-family='{font}' font-size='15' font-weight='650' "
        f"fill='#f4f4f6' letter-spacing='-.3'>{_e(title)} · {_e(label)} {_e(overall)}</text>"
        "<rect x='78' y='33' width='42' height='1.5' rx='.75' fill='#8a8a90'/>"
        f"<text x='128' y='37' font-family='{font}' font-size='10.5' fill='#a3a3aa'>"
        f"{_e(audited_on)} · ID {_e(public_id)}</text>"
        f"<text x='78' y='58' font-family='{font}' font-size='9' fill='#86868c' "
        f"textLength='390' lengthAdjust='spacingAndGlyphs'>{_e(notice)}</text>"
        "</svg>"
    )


_TOC_LABEL = {"es": "En esta página", "en": "On this page", "pt": "Nesta página"}


def _doc(sections: list[tuple[str, str]], locale: str, *, lead: str = "", aside: str = "") -> str:
    """A long-form page: the article plus a sticky index of its sections.

    ``sections`` are (heading, body html) pairs; each heading gets an anchor
    the index links to. The index is hidden on narrow screens.
    """
    article = lead + "".join(
        f"<h2 id='s{i}'>{_e(heading)}</h2>{body}" for i, (heading, body) in enumerate(sections, 1)
    )
    toc = "".join(
        f"<li><a href='#s{i}'>{_e(heading)}</a></li>" for i, (heading, _) in enumerate(sections, 1)
    )
    return (
        f"<div class='doc'><article class='prose'>{article}</article>"
        f"<aside class='toc' aria-label='{_e(_TOC_LABEL[locale])}'><div class='toc-in'>"
        f"<b>{_e(_TOC_LABEL[locale])}</b><ol data-toc>{toc}</ol>{aside}</div></aside></div>"
    )


def legal_page(
    text: LegalText, *, locale: str = "es", kind: str = "terms", base_url: str = ""
) -> str:
    """The terms or the privacy policy as one page, with a language switch."""
    locale = _locale(locale)
    copy = _COPY[locale]
    ui = _UI[locale]
    other = "en" if locale == "es" else "es"
    path = legal_url(kind, locale).split("?", 1)[0]
    description = f"{text.title} · {copy['title']}. {DISCLAIMER[locale]}"
    meta = _public_meta(text.title, description, locale, path, base_url)
    warning = f"<div class='error'>{_e(text.warning)}</div>" if text.warning else ""
    sections = [
        (heading, "".join(f"<p>{_e(line)}</p>" for line in lines))
        for heading, lines in text.sections
    ]
    crumbs = (
        f"<a href='/?lang={_e(locale)}'>{_e(copy['back'])}</a><span>/</span>"
        f"<a href='?lang={other}'>{_other_name(locale)}</a>"
    )
    body = (
        _page_hero(ui["legal_eyebrow"], text.title, crumbs=crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(sections, locale, lead=warning)
        + f"<p class='muted doc-foot'>{_e(copy['legal_updated'])}: {_e(text.updated)}</p>"
        "</div></div>"
    )
    return _page(
        text.title, locale, body, meta_html=meta, switch_href=f"?lang={other}", solid_nav=True
    )


def compare_page(content: str, *, locale: str = "es", lead: str = "", switch_href: str = "") -> str:
    """The private page that compares two reports (``audit/compare.py`` builds ``content``)."""
    from quant_trade.audit.compare import COMPARE_CSS, COPY

    locale = _locale(locale)
    copy = COPY[locale]
    other = "en" if locale == "es" else "es"
    other_path = switch_href or ("/compare" if other == "en" else "/comparar")
    body = (
        _page_hero(copy["eyebrow"], copy["title"], lead or copy["lead"])
        + f"<div class='paper page-main'><div class='wrap'><style>{COMPARE_CSS}</style>"
        + content
        + "</div></div>"
    )
    return _page(copy["title"], locale, body, switch_href=other_path, solid_nav=True)


def check_page(content: str, *, locale: str = "es", base_url: str = "") -> str:
    """The page that checks a report file (``audit/check.py`` builds ``content``)."""
    from quant_trade.audit.check import CHECK_CSS, COPY, check_path

    locale = _locale(locale)
    copy = COPY[locale]
    other = "en" if locale == "es" else "es"
    body = (
        _page_hero(copy["eyebrow"], copy["title"], copy["lead"])
        + f"<div class='paper page-main'><div class='wrap'><style>{CHECK_CSS}</style>"
        + content
        + "</div></div>"
    )
    meta = (
        _public_meta(copy["title"], copy["lead"], locale, check_path(locale), base_url)
        if base_url
        else ""
    )
    return _page(
        copy["title"],
        locale,
        body,
        meta_html=meta,
        switch_href=check_path(other),
        solid_nav=True,
    )


_ERROR_TITLES = {
    "es": {"page": "Página no encontrada", "server": "Algo falló"},
    "en": {"page": "Page not found", "server": "Something went wrong"},
}


#: Where an importer's message starts listing the formats it reads.
_EXPECTED_MARKERS = ("Se espera:", "Expected:")
#: "...: sube la optimización del mismo robot" reads as the fix, so it gets its own line.
_ACTION = re.compile(
    r"[:;]\s+(?=(?:sube|vuelve|exp[oó]rta\w*|revisa|pide|upload|export|check|ask|re-export|optimi[sz]e)\b)",
    re.I,
)
_ACTION_LABEL = {"es": "Qué hacer:", "en": "What to do:"}


def _error_card(message: str, locale: str = "es") -> str:
    """The error as a card: the upload field, the problem, then what is expected
    or what to do."""
    field, rest = "", message.strip()
    head, sep, tail = rest.partition(": ")
    # "Estado de cuenta real: el archivo..." names the field; a sentence never does.
    if sep and len(head) <= 40 and "." not in head and tail:
        field, rest = head, tail
    expected = ""
    for marker in _EXPECTED_MARKERS:
        before, found, after = rest.partition(marker)
        if found and before.strip() and after.strip():
            rest = before.strip()
            expected = f"<p class='err-exp'><b>{_e(marker)}</b>{_e(after)}</p>"
            break
    if not expected:
        parts = _ACTION.split(rest, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            rest, action = parts[0].strip(), parts[1].strip()
            rest = rest if rest[-1] in ".!?" else rest + "."
            action = action[:1].upper() + action[1:].rstrip(".") + "."
            expected = (
                f"<p class='err-exp'><b>{_e(_ACTION_LABEL.get(locale, _ACTION_LABEL['es']))}</b> "
                f"{_e(action)}</p>"
            )
    rest = rest[:1].upper() + rest[1:]
    rest = rest if rest[-1:] in ".!?" else rest + "."
    return (
        f"<div class='error-card' role='alert'><div class='err-ico'>{icon('alert')}</div><div>"
        + (f"<p class='err-field'>{_e(field)}</p>" if field else "")
        + f"<p class='err-msg'>{_e(rest)}</p>{expected}</div></div>"
    )


def error_page(message: str, *, locale: str = "es", kind: str = "audit") -> str:
    """An error page; ``kind`` picks the title: audit, page (404) or server."""
    locale = _locale(locale)
    copy = _COPY[locale]
    ui = _UI[locale]
    other = "en" if locale == "es" else "es"
    title = _ERROR_TITLES[locale].get(kind, copy["error_title"])
    body = (
        _page_hero(ui["error_eyebrow"], title, dot="warn")
        + "<div class='paper page-main'><div class='wrap wrap-narrow'>"
        f"{_error_card(message, locale)}<div class='back-row'>"
        f"<a class='btn btn-dark' href='/?lang={_e(locale)}#subir'>{_e(copy['back'])}</a>"
        f"<a class='btn btn-ghost' href='{_e(guides_index_url(locale))}'>"
        f"{_e(GUIDES_COPY[locale]['title'])}</a>"
        f"<a class='btn btn-ghost' href='/?lang={other}' hreflang='{other}'>{_other_name(locale)}"
        "</a></div></div></div>"
    )
    return _page(title, locale, body, switch_href=f"/?lang={other}", solid_nav=True)


def method_page(*, locale: str = "es", base_url: str = "") -> str:
    """The public methodology: tests, thresholds, labels, limits and sources."""
    locale = _locale(locale)
    copy = _COPY[locale]
    words: dict[str, Any] = METHOD_COPY[locale]
    other = "en" if locale == "es" else "es"
    title = f"{words['title']} · {copy['title']}"
    meta = _public_meta(title, words["summary"], locale, method_url(locale), base_url)

    def bullets(items: list[str], mark: str = "check") -> str:
        return (
            f"<ul class='checks{'' if mark == 'check' else ' nots'}'>"
            + "".join(f"<li>{icon(mark)}<span>{_e(item)}</span></li>" for item in items)
            + "</ul>"
        )

    dims_table = (
        "<div class='mdims'>"
        + "".join(
            f"<div class='mdim'><div class='icon'>{icon(dim_icon)}</div>"
            f"<h3>{_e(question)}</h3><p>{_e(measure)}</p>"
            f"<div class='mdim-rule'><span>{_e(words['col_pass'])}</span><p>{_e(rule)}</p></div>"
            "</div>"
            for (question, measure, rule), dim_icon in zip(
                dimension_rows(locale), _DIMENSION_ICONS.values(), strict=True
            )
        )
        + "</div>"
    )
    ladder = "".join(
        f"<li class='rung' style='--c:{CLASS_COLOURS[cls]}'><span class='rung-cls'>{_e(cls)}</span>"
        f"<p>{_e(text)}</p></li>"
        for cls, text in CLASS_LADDER[locale]
    )
    evidence = "".join(
        f"<li><span class='badge {_e(tag)}'>{_e(tag)}</span><span>{_e(text)}</span></li>"
        for tag, text in words["evidence"]
    )
    flags = "".join(
        f"<li>{_e(titles.get(locale, titles['en']))}</li>" for titles in FLAG_TITLES.values()
    )
    refs = "".join(f"<li>{_e(ref)}</li>" for ref in REFERENCES)
    crumbs = (
        f"<a href='/?lang={_e(locale)}'>{_e(GUIDES_COPY[locale]['back'])}</a><span>/</span>"
        f"<a href='{_e(method_url(other))}' hreflang='{other}'>{_other_name(locale)}</a>"
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["summary"], crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            [
                (words["independence_title"], bullets(words["independence"])),
                (words["dims_title"], dims_table),
                (words["ladder_title"], f"<ol class='ladder'>{ladder}</ol>"),
                (words["evidence_title"], f"<ul class='mtags'>{evidence}</ul>"),
                (words["flags_title"], f"<ul class='chips'>{flags}</ul>"),
                (words["repro_title"], bullets(words["repro"])),
                (words["limits_title"], bullets(words["limits"], "minus")),
                (words["refs_title"], f"<ol class='refs'>{refs}</ol>"),
            ],
            locale,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(_form_url(locale))}'>"
            f"{_e(GUIDES_COPY[locale]['form'])}<span class='go'>{icon('arrow')}</span></a>",
        )
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, switch_href=method_url(other), solid_nav=True)


#: Guides for an account's history rather than a backtest, listed apart on /guias.
ACCOUNT_GUIDES = frozenset({"cuenta-proveedor", "myfxbook", "mql5-signal", "fxblue"})
_GUIDE_GROUPS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "es": (
        ("Backtests", "Informes del probador de estrategias y listas de operaciones."),
        (
            "Cuentas reales",
            "El historial de una cuenta, la tuya o la de alguien a quien vas a copiar.",
        ),
    ),
    "en": (
        ("Backtests", "Strategy tester reports and trade lists."),
        ("Live accounts", "An account's history, yours or that of someone you plan to copy."),
    ),
    "pt": (
        ("Backtests", "Relatórios do testador de estratégias e listas de operações."),
        (
            "Contas reais",
            "O histórico de uma conta, a sua ou a de alguém que você pretende copiar.",
        ),
    ),
}


def _form_url(locale: str) -> str:
    """The landing's upload form in ``locale``."""
    return "/pt#subir" if locale == "pt" else f"/?lang={locale}#subir"


def _language_crumbs(alternates: dict[str, str], locale: str) -> str:
    """Breadcrumb links to the page in every other language."""
    return "".join(
        f"<span>/</span><a href='{_e(href)}' hreflang='{lang}' lang='{lang}'>"
        f"{_e(LANGUAGE_NAMES[lang])}</a>"
        for lang, href in alternates.items()
        if lang != locale
    )


def guides_index_page(*, locale: str = "es", base_url: str = "") -> str:
    """The list of export guides."""
    locale = _locale(locale)
    copy = _COPY[locale]
    ui = _UI[locale]
    words = GUIDES_COPY[locale]
    alternates = {lang: guides_index_url(lang) for lang in ("es", "en", "pt")}
    meta = _public_meta(
        f"{words['title']} · {copy['title']}",
        words["summary"],
        locale,
        guides_index_url(locale),
        base_url,
    )
    groups = ""
    for account, (title, lead) in (
        (False, _GUIDE_GROUPS[locale][0]),
        (True, _GUIDE_GROUPS[locale][1]),
    ):
        chosen = [g for g in GUIDES if (g.slug in ACCOUNT_GUIDES) == account]
        items = "".join(
            f"<li data-reveal style='--i:{i % 2}'><a href='{_e(guide_url(g.slug, locale))}'>"
            f"<b>{_e(g.text[locale].title)}{icon('arrow')}</b>"
            f"<span>{_e(g.text[locale].summary)}</span></a></li>"
            for i, g in enumerate(chosen)
        )
        groups += (
            f"<section class='guide-group'><h2>{_e(title)}</h2><p>{_e(lead)}</p>"
            f"<ul class='guide-list guides'>{items}</ul></section>"
        )
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(words['back'])}</a>" + _language_crumbs(
        alternates, locale
    )
    body = (
        _page_hero(ui["guides_eyebrow"], words["title"], words["intro"], crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        f"{groups}<div class='back-row'>"
        f"<a class='btn btn-dark' href='{_e(_form_url(locale))}'>{_e(words['form'])}"
        f"<span class='go'>{icon('arrow')}</span></a></div></div></div>"
    )
    return _page(
        f"{words['title']} · {copy['title']}",
        locale,
        body,
        meta_html=meta,
        alternates=alternates,
        solid_nav=True,
    )


def guide_page(guide: Guide, *, locale: str = "es", base_url: str = "") -> str:
    """One platform's export guide."""
    locale = _locale(locale)
    copy = _COPY[locale]
    ui = _UI[locale]
    words = GUIDES_COPY[locale]
    text = guide.text[locale]
    alternates = {lang: guide_url(guide.slug, lang) for lang in ("es", "en", "pt")}
    title = f"{text.title} · {copy['title']}"
    meta = _public_meta(title, text.summary, locale, guide_url(guide.slug, locale), base_url)
    steps = "".join(f"<li>{_e(step)}</li>" for step in text.steps)
    tips = "".join(f"<li>{icon('check')}<span>{_e(tip)}</span></li>" for tip in text.tips)
    crumbs = f"<a href='{_e(guides_index_url(locale))}'>{_e(words['all'])}</a>" + (
        _language_crumbs(alternates, locale)
    )
    body = (
        _page_hero(ui["guides_eyebrow"], text.title, text.summary, crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            [
                (words["file"], f"<p>{_e(text.file)}</p>"),
                (words["steps"], f"<ol class='list-steps steps-guide'>{steps}</ol>"),
                (words["upload"], f"<p>{_e(text.upload)}</p>"),
                (words["tips"], f"<ul class='checks'>{tips}</ul>"),
            ],
            locale,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(_form_url(locale))}'>"
            f"{_e(words['form'])}<span class='go'>{icon('arrow')}</span></a>",
        )
        + f"<div class='back-row'><a class='btn btn-dark' href='{_e(_form_url(locale))}'>"
        f"{_e(words['form'])}<span class='go'>{icon('arrow')}</span></a></div></div></div>"
    )
    return _page(
        title,
        locale,
        body,
        meta_html=meta,
        alternates=alternates,
        solid_nav=True,
    )


def audience_page(
    audience: Audience,
    *,
    locale: str = "es",
    base_url: str = "",
    free_mode: bool = False,
    price_usd: float = 0.0,
    pack_price_usd: float = 0.0,
) -> str:
    """One visitor's case: the problem, what to upload, what Rigor checks."""
    locale = _locale(locale)
    copy = _COPY[locale]
    words = AUDIENCE_COPY[locale]
    text = audience.text[locale]
    linked = link_locale(locale)
    title = f"{text.title} · {BRAND}"
    meta = _public_meta(title, text.summary, locale, audience_url(audience.slug, locale), base_url)
    sample = _sample_url(linked)
    pains = "".join(f"<li>{icon('alert')}<span>{_e(item)}</span></li>" for item in text.pains)
    uploads = "".join(
        f"<li>{icon('file')}<span>{_e(item)}"
        + (f" <a href='{_e(guide_url(guide, locale))}'>{_e(words['guide'])}</a>" if guide else "")
        + "</span></li>"
        for item, guide in text.uploads
    )
    checks = "".join(
        f"<li>{icon('check')}<span><strong>{_e(name)}{'' if name.endswith(('?', '.')) else '.'}"
        f"</strong> {_e(body)}</span></li>"
        for name, body in text.checks
    )
    limits = "".join(f"<li>{icon('minus')}<span>{_e(item)}</span></li>" for item in text.limits)
    price = (
        copy["price_free_mode"]
        if free_mode or not price_usd
        else words["price_text"].format(price=price_usd, pack=pack_price_usd or price_usd * 3)
    )
    faq = "".join(
        f"<details><summary>{_e(q)}</summary><p>{_e(a.format(presets=len(PRESETS)))}</p></details>"
        for q, a in text.faq
    )
    others = "".join(
        f"<li><a href='{_e(audience_url(page.slug, locale))}'>"
        f"<span>{_e(page.text[locale].title)}</span>{icon('arrow')}</a></li>"
        for page in AUDIENCE_PAGES
        if page.slug != audience.slug
    )
    # Robot buyers land on the form with the live-account box already open.
    if locale == "pt":
        start = "/pt" + ("?extras=1" if audience.open_extras else "") + "#subir"
    else:
        start = f"/?lang={locale}" + ("&extras=1" if audience.open_extras else "") + "#subir"
    buttons = (
        "<div class='hero-cta'>"
        f"<a class='btn btn-dark' href='{_e(start)}'>{_e(words['start'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(sample)}'>{_e(words['sample'])}{icon('arrow')}</a>"
        "</div>"
    )
    alternates = {lang: audience_url(audience.slug, lang) for lang in ("es", "en", "pt")}
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(words['home'])}</a>" + _language_crumbs(
        alternates, locale
    )
    body = (
        _page_hero(words["eyebrow"], text.title, text.summary, crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            [
                (words["pains"], f"<ul class='checks aud-pains'>{pains}</ul>"),
                (words["uploads"], f"<ul class='checks'>{uploads}</ul>"),
                (words["checks"], f"<ul class='checks aud-checks'>{checks}</ul>"),
                (words["limits"], f"<ul class='checks'>{limits}</ul>"),
                (words["price"], f"<div class='aud-price'><p>{_e(price)}</p>{buttons}</div>"),
                (words["faq"], f"<div class='faq'>{faq}</div>"),
                (words["others"], f"<ul class='aud-others'>{others}</ul>"),
            ],
            locale,
            lead=buttons,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(start)}'>"
            f"{_e(words['start'])}<span class='go'>{icon('arrow')}</span></a>",
        )
        + "</div></div>"
    )
    return _page(
        title,
        locale,
        body,
        meta_html=meta,
        alternates=alternates,
        solid_nav=True,
    )


__all__ = [
    "BADGE_NOTICE",
    "SAMPLE_BANNER",
    "VERIFICATION_NOTICE",
    "audience_page",
    "badge_svg",
    "error_page",
    "guide_page",
    "guides_index_page",
    "landing",
    "legal_page",
    "method_page",
    "sample_meta",
    "verification_page",
]
