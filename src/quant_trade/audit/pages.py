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
import textwrap
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

from quant_trade.audit import accounts, institutional, reading, winrate
from quant_trade.audit.accounts import FREE_PREVIEWS_PER_MONTH as _FREE
from quant_trade.audit.article_numbers import STREAK_ROWS
from quant_trade.audit.articles import (
    ARTICLES,
    ARTICLES_BY_KEY,
    ARTICLES_COPY,
    INDEPENDENT_LUCK_EXAMPLE,
    LUCK_TABLE_COPY,
    LUCK_TABLE_INPUTS,
    STREAK_ARTICLE_KEY,
    STREAK_TABLE_AFTER,
    STREAK_TABLE_COPY,
    WIN_RATE_RATES,
    WIN_RATE_TABLE_COPY,
    WIN_RATE_TRADE_COUNTS,
    Article,
    _num,
    article_url,
    articles_index_faq,
    articles_index_url,
    next_step_call,
    next_step_links,
    related_links,
    win_rate_interval,
)
from quant_trade.audit.audiences import (
    AUDIENCE_COPY,
    AUDIENCE_PAGES,
    PLATFORMS_EN,
    PLATFORMS_ES,
    PLATFORMS_PT,
    RECOGNISED_PLATFORMS,
    Audience,
    audience_url,
)
from quant_trade.audit.calculator import (
    CALCULATOR_PATH,
    CalculatorInput,
    calculator_copy,
    calculator_url,
    compute,
    read_input,
    share_url,
)
from quant_trade.audit.calculator import COPY as CALCULATOR_COPY
from quant_trade.audit.calculator import REASONS as CALCULATOR_REASONS
from quant_trade.audit.calculator_card import count_text, result_figures, what_if_figures
from quant_trade.audit.completed_count import completed_count_html
from quant_trade.audit.examples import (
    EXAMPLES_COPY,
    EXAMPLES_PATH,
    examples_content,
    examples_url,
)
from quant_trade.audit.guide_capabilities import GUIDE_TOOL, guide_points, guide_purpose
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
from quant_trade.audit.method import dimension_rows, method_url, references
from quant_trade.audit.ownership import FORM as OWNERSHIP_FORM
from quant_trade.audit.ownership import ROLES as OWNERSHIP_ROLES
from quant_trade.audit.portuguese import (
    AUDIENCES_PT,
    CLASS_B_PT,
    COPY_PT,
    DIMENSION_TITLES_PT,
    DISCLAIMER_PT,
    INVESTOR_PT,
    LANGUAGE_NAMES,
    MONTHS_PT,
    STATUS_TEXT_PT,
    UI_PT,
    link_locale,
)
from quant_trade.audit.pricing import PRICING_COPY, PRICING_PATH, offer_text, usd
from quant_trade.audit.prop_presets import AS_OF, DEFAULT_PRESET, PRESETS, preset_label
from quant_trade.audit.public_card import PublicClaim
from quant_trade.audit.redflags import FLAG_TITLES
from quant_trade.audit.report import (
    CLASS_LADDER,
    DIMENSION_TITLES,
    DISCLAIMER,
    FREQUENCY_TEXT,
    STATUS_TEXT,
    data_age_days,
    evidence_label,
    localize_tags,
    localize_text_nodes,
    report_kind,
    source_name,
)
from quant_trade.audit.seo import (
    BRAND,
    OG_IMAGE_SIZE,
    TAGLINE,
    PageMeta,
    article_structured_data,
    articles_faq_structured_data,
    head_meta,
    page_paths,
    private_meta,
    tools_structured_data,
    web_application_structured_data,
)
from quant_trade.audit.series_ui import series_fields
from quant_trade.audit.settings import PACK_CREDITS
from quant_trade.audit.sharing import COPY as SHARING_COPY
from quant_trade.audit.sharing import share_block
from quant_trade.audit.theme import (
    CLASS_COLOURS,
    SCRIPT_TAG,
    STYLE,
    aurora,
    class_ring,
    grid_bg,
    icon,
    logo,
    static_ready,
)
from quant_trade.audit.tools_hub import COPY as TOOLS_COPY
from quant_trade.audit.tools_hub import TOOL_KEYS, TOOLS_PATH, tools_url
from quant_trade.audit.verdict import class_text, meaning, trials_undeclared

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
    "pt": (
        "Auditoria estatística de dados fornecidos – não verificados com a corretora – "
        "não garante resultados"
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
    "pt": (
        "Esta página resume uma auditoria estatística de dados que o cliente forneceu, não "
        "verificados com a corretora. A classe descreve a evidência que havia no arquivo "
        "auditado na data indicada; não garante resultados futuros, não é recomendação de "
        "investimento e não endossa nenhum vendedor nem produto. Os hashes permitem conferir "
        "que um arquivo é exatamente o que foi auditado."
    ),
}

#: The class word on the verification page and its badge.
CLASS_WORD: dict[str, str] = {"es": "Clase", "en": "Class", "pt": "Classe"}

#: The sample report's address in each language.
SAMPLE_PAGE_PATHS: dict[str, str] = {"es": "/ejemplo", "en": "/sample", "pt": "/pt/exemplo"}

SAMPLE_BANNER: dict[str, str] = {
    "es": (
        "Informe de ejemplo con datos sintéticos generados por computadora: no es la cuenta ni "
        "la estrategia de nadie. Así se ve un informe completo."
    ),
    "en": (
        "Sample report built from computer-generated synthetic data: it is nobody's account "
        "or strategy. This is what a full report looks like."
    ),
    "pt": (
        "Relatório de exemplo feito com dados sintéticos gerados por computador: não é a conta "
        "nem a estratégia de ninguém. Assim fica um relatório completo."
    ),
}

_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "title": f"{BRAND} · Auditoría de backtests",
        "headline": "Sube tu backtest. Te decimos si es estadísticamente real.",
        "pitch": (
            "La mayoría de los backtests que lucen bien en papel fallan en real por sobreajuste, "
            "costos no contados o datos con errores. Esta auditoría aplica los estimadores de "
            "Bailey y López de Prado (Sharpe probabilístico, Sharpe deflactado por número de "
            "intentos, bootstrap estacionario) a la curva que subes y te devuelve un veredicto "
            "con cada número etiquetado según su evidencia."
        ),
        "measure_title": "Qué medimos",
        "measure": [
            "Si el Sharpe se distingue de cero dada la longitud, la asimetría y la curtosis.",
            "Cuánto sobrevive después de descontar el número de intentos que declaras.",
            "Qué pasa a 1x, 2x y 3x el costo de operación, y el costo de equilibrio.",
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
        "report_short": "Tal cual lo guarda tu plataforma: HTML, XLSX, CSV o PDF, hasta 10 MB.",
        "report_help": (
            "El archivo tal cual: informe HTML del probador o del historial de MetaTrader 5 o 4 "
            "(o el XLSX que exporta MetaTrader 5), "
            "lista de operaciones de TradingView (CSV o XLSX), el CSV de operaciones de "
            "NinjaTrader, QuantConnect, backtesting.py o vectorbt, o el historial de "
            "operaciones en CSV o Excel de cualquier otro bróker o exchange. Reconoce el "
            "formato de exportación de " + PLATFORMS_ES + ". También un estado de cuenta en PDF "
            "con su tabla de operaciones: antes de medir revisas las columnas. Hasta 10 MB."
        ),
        "live": "Estado de cuenta real o demo (opcional)",
        "live_help": (
            "El historial de la cuenta donde corre el robot (MetaTrader, el CSV que exporta "
            "Myfxbook, FX Blue o una señal de MQL5, u otro de los formatos de arriba). Te "
            "decimos si se comporta como el backtest y revisamos sus depósitos y retiros. "
            "Hasta 10 MB."
        ),
        "optimization": "Exportación de optimización de MT5 (XML, opcional)",
        "optimization_help": (
            "Cuenta las configuraciones que probaste: el Sharpe deflactado usa ese número "
            "real. Hasta 10 MB."
        ),
        "equity": (
            "Curva de equity o serie de retornos (CSV o Excel; obligatoria si no subes un informe)"
        ),
        "equity_help": (
            "Columnas: timestamp y equity (o return), en CSV, texto de Excel o XLSX. También la "
            "tabla de rentabilidades mensuales de un fondo (un año por fila, un mes por "
            "columna). Hasta 5 MB (si sueltas aquí un informe de plataforma, hasta 10 MB)."
        ),
        "initial_balance": "Balance inicial (si el informe no lo indica)",
        "challenge": "Reto de prop firm a simular",
        "challenge_help": "Reglas leídas en la web oficial de cada firma el {as_of}. "
        "El informe cita la fuente; confirma las reglas con la firma antes de pagar su reto.",
        "trades": "Operaciones cerradas (CSV, opcional)",
        "trades_help": (
            "entry_time, exit_time, quantity, entry_price, exit_price, side. Hasta 5 MB."
        ),
        "dates_hint": (
            "Se leen mejor las fechas como año-mes-día (2026-03-31) y el punto decimal. Si tu "
            "archivo usa día/mes/año, dilo en la descripción."
        ),
        "benchmark": "Benchmark (CSV/XLSX, opcional)",
        "benchmark_help": "Hasta 5 MB.",
        "variants": "Matriz de variantes (CSV, opcional)",
        "variants_help": (
            "Una columna de retornos por variante probada; habilita el PBO. Hasta 5 MB."
        ),
        "trials": "¿Cuántas configuraciones o versiones se probaron antes de elegir esta?",
        "trials_help": (
            "Configuraciones probadas antes de elegir esta. Si lo dejas vacío, el informe usa 1 "
            "(el caso más favorable) y la clase queda como máximo en B. Si subes el XML de "
            "optimización de MT5 se cuentan solas."
        ),
        "cost_bps": (
            "Costo extra por lado en puntos básicos, además del que ya detalla tu informe "
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
            "sin pagar."
        ),
        "signin_create": "Crear cuenta gratis",
        "signin_enter": "Ya tengo cuenta",
        "waitlist_title": "Recibe guías y novedades",
        "email": "Correo",
        "join": "Apuntarme",
        "joined": "Apuntado. Gracias.",
        "error_title": "No se pudo auditar",
        "back": "Volver",
        "disclaimer": "Aviso",
        "sample_link": "Ver un informe de ejemplo completo (datos sintéticos)",
        "meta_description": (
            "Sube tu archivo de operaciones o curva de equity: Rigor revisa costos, número "
            "de pruebas y coherencia de datos. Clase de A a D."
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
            "Crea tu cuenta con tu correo: tu primer informe completo es gratis.",
            "Sube el archivo de tu plataforma tal cual: un backtest, el historial de una cuenta o "
            "una serie de retornos.",
            "Ves la clase de A a D, las gráficas y qué significa cada dimensión, en lenguaje "
            "llano.",
            "Cada auditoría siguiente la pagas desde tu cuenta, y tus informes quedan guardados "
            "ahí.",
        ],
        "prices_title": "Precios",
        "price_free_title": "Primer informe",
        "price_free": (
            "Completo y con PDF al crear tu cuenta. Después, {n} vistas previas gratis al mes "
            "con la clase, las gráficas y las banderas rojas."
        ),
        "price_full_title": "Informe completo",
        "price_full": (
            "Para la versión corregida de tu estrategia, otro robot o tu cuenta del mes "
            "siguiente. Desde tu cuenta lo comparas lado a lado con tu informe anterior."
        ),
        "price_free_mode": (
            "Ahora mismo el servicio está en modo gratuito: el informe completo se entrega con "
            "marca de agua y sin costo."
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
        "price_pack": "Paquete de {n} informes: {price} ({each} cada uno).",
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
                "nombre. También sirve una curva de equity en CSV, o un estado de cuenta en PDF "
                "con su tabla de operaciones, cuyas columnas revisas antes de medir.",
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
                "¿Qué recibo?",
                "Gratis, la vista previa: clase de A a D, gráficas, la revisión de "
                f"{len(FLAG_TITLES)} banderas rojas y qué significa cada dimensión. "
                "El informe completo añade cada cifra, pruebas "
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
                "¿Comprueban mis operaciones con el bróker?",
                "No. Auditamos los datos que aportas; no nos conectamos a ningún bróker ni "
                "pedimos claves. Por eso el sello dice que los datos no están comprobados con "
                "el bróker.",
            ),
            (
                "¿Qué pasa con mi archivo?",
                "Se guarda para poder regenerar tu informe. Si no pagas, se borra a los "
                "{retention} días y solo quedan la clase y los hashes (y lo que muestra tu "
                "página de verificación, si la publicaste). Nunca se publica: la página de "
                "verificación muestra la clase, las dimensiones, los hashes, qué se auditó y el "
                "periodo de los datos, y solo si tú la publicas.",
            ),
            (
                "¿Y si olvido mi contraseña?",
                "En Mi cuenta creas una clave de recuperación y la guardas. Si olvidas la "
                "contraseña, con tu correo y esa clave pones una nueva tú mismo, sin esperar un "
                "correo. Si activaste la verificación en dos pasos, también te pedimos el "
                "código de tu app. De la clave solo guardamos su huella, nunca la clave misma.",
            ),
            (
                "¿Qué tan protegida está mi cuenta?",
                "Puedes activar la verificación en dos pasos con una app de autenticación "
                "(Google Authenticator, 1Password u otra): entonces, para entrar o recuperar la "
                "cuenta hacen falta dos de estas tres cosas: tu contraseña, el código de la app "
                "o tu clave de recuperación. En Mi cuenta ves dónde está abierta tu cuenta y "
                "cierras cada sesión, y ves tus entradas y cambios de seguridad más recientes "
                "(hasta 90 días), incluidos los intentos con contraseña incorrecta. También "
                "puedes entrar con una llave de acceso: la huella, la cara o el PIN de tu "
                "teléfono o computadora, sin escribir la contraseña. En Mi cuenta, «Protección "
                "de tu cuenta» te muestra qué tienes activado y cómo activar lo que falta.",
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
        "v_kind": "Qué se auditó",
        "v_kind_backtest": "Backtest",
        "v_kind_account": "Historial de cuenta real o demo",
        "v_kind_fund": "Historial de un fondo",
        "v_period": "Periodo de los datos",
        "v_age": "Días entre el último dato y la auditoría",
        "v_format": "Formato del archivo",
        "v_engine": "Motor",
        "v_trials_declared": "Intentos declarados",
        "v_trials_used": "Intentos usados en el Sharpe deflactado",
        "v_trials_undeclared": "sin declarar; se calcula con 1, el caso más favorable",
        "v_result_sha": "SHA-256 del resultado",
        "v_notice": "Aviso",
        "v_badge": "Sello para tu web",
        "v_badge_help": "Copia este código en tu web, Telegram o foro:",
        "access_code": "Código de acceso (opcional)",
        "access_code_help": "Si compraste un código, escríbelo y el informe nace completo.",
    },
    "en": {
        "title": f"{BRAND} · Backtest audit",
        "meta_title": f"Independent backtest audit · {BRAND}",
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
        "report_short": "As your platform saves it: HTML, XLSX, CSV or PDF, up to 10 MB.",
        "report_help": (
            "The file as it is: a MetaTrader 5 or 4 tester or history HTML report (or the "
            "XLSX MetaTrader 5 exports), a "
            "TradingView list of trades (CSV or XLSX), the trades CSV of NinjaTrader, "
            "QuantConnect, backtesting.py or vectorbt, or the CSV or Excel trade history of "
            "any other broker or exchange. It recognises the export format of "
            + PLATFORMS_EN
            + ". A PDF statement with its trade table works too: you check the columns "
            "before it measures. Up to 10 MB."
        ),
        "live": "Live or demo account statement (optional)",
        "live_help": (
            "The history of the account running the robot (MetaTrader, the CSV exported by "
            "Myfxbook, FX Blue or an MQL5 signal, or any format above). We tell you whether "
            "it behaves like the backtest and review its deposits and withdrawals. "
            "Up to 10 MB."
        ),
        "optimization": "MT5 optimisation export (XML, optional)",
        "optimization_help": (
            "Counts the configurations you tried: the deflated Sharpe uses that real number. "
            "Up to 10 MB."
        ),
        "equity": "Equity curve or return series (CSV or Excel; required without a report)",
        "equity_help": (
            "Columns: timestamp and equity (or return), as CSV, Excel text or XLSX. Also a "
            "fund's monthly returns table (a year per row, a month per column). Up to 5 MB (a "
            "platform report dropped here, up to 10 MB)."
        ),
        "initial_balance": "Starting balance (if the report does not state it)",
        "challenge": "Prop-firm challenge to simulate",
        "challenge_help": "Rules read on each firm's official site on {as_of}. "
        "The report cites the source; confirm the rules with the firm before paying for its "
        "challenge.",
        "trades": "Closed trades (CSV, optional)",
        "trades_help": (
            "entry_time, exit_time, quantity, entry_price, exit_price, side. Up to 5 MB."
        ),
        "dates_hint": (
            "Dates as year-month-day (2026-03-31) and a decimal point read best. If your file "
            "uses day/month/year, say so in the description."
        ),
        "benchmark": "Benchmark (CSV/XLSX, optional)",
        "benchmark_help": "Up to 5 MB.",
        "variants": "Variant matrix (CSV, optional)",
        "variants_help": "One return column per variant tried; enables the PBO. Up to 5 MB.",
        "trials": "How many configurations or versions were tried before choosing this one?",
        "trials_help": (
            "Configurations tried before choosing this one. Left blank, the report uses 1 (the "
            "most favourable case) and the class is at most B. If you upload the MT5 "
            "optimisation XML they are counted for you."
        ),
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
            "with the PDF, at no cost."
        ),
        "signin_create": "Create a free account",
        "signin_enter": "I have an account",
        "waitlist_title": "Get guides and news",
        "email": "E-mail",
        "join": "Join",
        "joined": "Joined. Thank you.",
        "error_title": "Could not audit",
        "back": "Back",
        "disclaimer": "Notice",
        "sample_link": "See a full sample report (synthetic data)",
        "meta_description": (
            "Statistical review of a trading strategy: inspect costs, research trials and "
            "track-record evidence with an independent backtest audit."
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
            "Create your account with your email: your first full report is free.",
            "Upload your platform's file as it is: a backtest, an account history or a return "
            "series.",
            "You see the A to D class, the charts and what each dimension means, in plain "
            "language.",
            "Each further audit is paid from your account, and your reports stay saved there.",
        ],
        "prices_title": "Pricing",
        "price_free_title": "First report",
        "price_free": (
            "Full and with the PDF when you create your account. After that, {n} free previews "
            "a month with the class, the charts and the red flags."
        ),
        "price_full_title": "Full report",
        "price_full": (
            "For the corrected version of your strategy, another robot or next month's "
            "account. From your account you compare it side by side with your previous report."
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
        "price_pack": "Pack of {n} reports: {price} ({each} each).",
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
                "works too, or a PDF statement with its trade table, whose columns you check "
                "before it measures.",
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
                "What do I get?",
                "For free, the preview: A to D class, charts, the check for "
                f"{len(FLAG_TITLES)} red flags and what each dimension means. "
                "The full report adds every figure, stress tests, risk and "
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
                "{retention} days and only the class and the hashes remain (plus what your "
                "verification page shows, if you published it). It is never published: the "
                "verification page shows the class, the dimensions, the hashes, what was "
                "audited and the data period, and only if you publish it.",
            ),
            (
                "What if I forget my password?",
                "In My account you make a recovery key and keep it. If you forget the password, "
                "your e-mail and that key let you set a new one yourself, without waiting for "
                "an e-mail. If you turned on two-step sign-in, we also ask for the code from "
                "your app. We keep only the key's fingerprint, never the key itself.",
            ),
            (
                "How well protected is my account?",
                "You can turn on two-step sign-in with an authenticator app (Google "
                "Authenticator, 1Password or another): then signing in or recovering the "
                "account takes two of these three: your password, the code from the app or "
                "your recovery key. In My account you see where your account is open and "
                "sign out each session, and you see your most recent sign-ins and security "
                "changes (up to 90 days), including wrong-password tries. You can also sign in "
                "with a passkey: your phone's or computer's fingerprint, face or PIN, without "
                'typing the password. In My account, "Your account\'s protection" shows what '
                "is on and how to turn on the rest.",
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
        "v_kind": "What was audited",
        "v_kind_backtest": "Backtest",
        "v_kind_account": "Live or demo account history",
        "v_kind_fund": "A fund's track record",
        "v_period": "Data period",
        "v_age": "Days between the last data point and the audit",
        "v_format": "File format",
        "v_engine": "Engine",
        "v_trials_declared": "Trials declared",
        "v_trials_used": "Trials used in the deflated Sharpe",
        "v_trials_undeclared": "not declared; computed at 1, the most favourable case",
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
        "nav_tools": "Herramientas",
        "nav_menu": "Menú",
        "cta": "Auditar mi archivo gratis",
        "cta_full": "Empezar con mi informe gratis",
        "cta_short": "Auditar",
        "hero_a": "Antes de pagar un reto o un robot,",
        "hero_b": "mira si es ventaja o suerte.",
        "hero_anchor": (
            "Un reto o un robot cuesta cientos de dólares. Tu primer informe completo es "
            "gratis; después, {price} por informe."
        ),
        "hero_safe": "Tu archivo nunca se publica.",
        "nav_lang": "Idioma",
        "trust": [
            ("shield", "No se conecta a tu bróker ni recomienda operaciones"),
            ("hash", "Cada informe se puede comprobar"),
            ("key", "Primer informe completo gratis con tu cuenta"),
        ],
        "mock_url": "informe · clase B",
        "mock_k": "Veredicto",
        "cta_sample": "Ver un informe de ejemplo",
        "hero_lead": (
            "Sube el backtest o el historial que ya tienes. Rigor lo pone a prueba contra "
            "costos, configuraciones probadas y las reglas de los retos de prop firm, y te da "
            "una clase de A\u00a0a\u00a0D con cada cifra explicada."
        ),
        "mock_cap": "Ilustración con datos sintéticos",
        "mock_is": "Dentro de muestra",
        "mock_oos": "Fuera de muestra",
        "mock_kpis": [
            ("0.97", "Sharpe deflactado"),
            ("120", "Intentos contados"),
            ("3.2 pb", "Costo de equilibrio"),
        ],
        "chip_trials": "Intentos reales desde el XML de MT5",
        "chip_hash": "Cada número con su evidencia",
        "platforms": "Lee el archivo que ya tienes",
        "platforms_also": "Y reconoce el formato de exportación de",
        "problem_eyebrow": "El problema",
        "problem_title": ("Un backtest bonito", "no es evidencia."),
        "problem_lead": (
            "Casi cualquier estrategia se ve bien en papel. Rigor está para que no te engañes con "
            "una curva bonita antes de arriesgar tu dinero o pagar por un robot. Estas son las "
            "tres razones por las que la mayoría no aguanta fuera del probador."
        ),
        "example_case": {
            "eyebrow": "Así lo detecta en el ejemplo",
            "title": "Sharpe de 1.8 en el probador. Clase C en Rigor.",
            "text": (
                "El informe de ejemplo es un backtest de MT5 hecho con datos sintéticos. Rigor le "
                "baja la clase por tres cosas que el probador no enseña:"
            ),
            "points": (
                "Salió de 120 configuraciones probadas; al descontarlas, su Sharpe ya no llega "
                "al umbral.",
                "Con el doble del costo de referencia termina en pérdida.",
                "Su cuenta real, de 180 operaciones, queda fuera de lo que su propio backtest "
                "haría esperar.",
            ),
            "cta": "Ver el informe del ejemplo",
        },
        "problems": [
            (
                "Sobreajuste",
                "Pruebas cien configuraciones y te quedas con la mejor. El azar, por sí solo, "
                "ya dibuja una curva preciosa.",
            ),
            (
                "Costos",
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
            "Rigor revisa tu archivo en seis puntos. Cada uno sale como Supera, Débil, No supera "
            "o No medido, con dos frases en lenguaje llano sobre qué significa para ti. Los "
            "métodos son públicos y están escritos en la metodología."
        ),
        "stats": [
            ("6", "dimensiones auditadas"),
            ("{flags}", "banderas rojas revisadas en cada archivo"),
            ("{presets}", "retos de prop firms simulables"),
            ("{platforms}", "plataformas que reconoce"),
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
                "exactamente qué es y qué no es, en español, inglés o portugués.",
            ),
            (
                "percent",
                "Frente al efectivo",
                "Restamos lo que pagaba el efectivo en las mismas fechas, en la moneda de tu "
                "cuenta si tu reporte la indica y es una de estas (pesos mexicanos, "
                "reales, euros, libras, yenes, "
                "dólares canadienses o francos suizos); si no indica moneda o está en dólares, "
                "en dólares (letras del Tesoro de EE. UU. a 3 meses); en otra moneda, esa "
                "línea no se calcula. Datos públicos oficiales. Ves el Sharpe sin lo que ya "
                "daba el efectivo y, si subes un benchmark, el alfa también.",
            ),
            (
                "chart",
                "Mercado tranquilo y agitado",
                "Cada rentabilidad se asigna según el VIX del día anterior, y cada crisis de "
                "fecha pública que cubre tu historial se mide por separado: ves si el resultado "
                "depende de un solo tipo de mercado.",
            ),
            (
                "globe",
                "En tu moneda y tras la inflación",
                "Si la cuenta está en dólares y hay tipos de cambio disponibles, ves su "
                "resultado en pesos mexicanos, reales, euros y otras cuatro monedas. "
                "Cuando hay índices de precios disponibles, ves cada moneda, incluido el "
                "dólar, después de su propia inflación. Si la cuenta ya está en una de esas "
                "monedas, ves el resultado tras su propia inflación. Tipos de cambio de FRED "
                "e índices de precios de fuentes estadísticas oficiales.",
            ),
        ],
        "how_eyebrow": "Proceso",
        "pricing_eyebrow": "Precios",
        "plan_free": "Vista previa",
        "plan_free_amount": "Gratis",
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
            "Simulación del reto que elijas de {firms}, con sus reglas publicadas",
            "Cuánto costo aguanta antes de quedar en pérdida",
            "Riesgo remuestreado a un año y el capital que pide",
            "Preguntas concretas para el vendedor del robot o el gestor",
            "PDF y, si tú quieres, página pública con sello",
        ],
        "full_more": "Ver un informe completo de ejemplo",
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
                f"{_FREE} vistas previas gratis al mes."
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
        "faq_more": "Más preguntas: precios, pagos, tu cuenta y contacto",
        "final_title": ("Antes de arriesgar dinero en una estrategia,", "mírala con lupa."),
        "final_lead": "Sube el informe y recibe la clase, las gráficas y su explicación sin costo.",
        "final_tools": "¿Aún sin archivo? Prueba las herramientas gratis, sin registro.",
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
        "nav_tools": "Free tools",
        "nav_menu": "Menu",
        "cta": "Audit my file free",
        "cta_full": "Start with my free report",
        "cta_short": "Audit",
        "hero_a": "Before you pay for a challenge or a robot,",
        "hero_b": "see whether it is edge or luck.",
        "hero_anchor": (
            "A challenge or a robot costs hundreds of dollars. Your first full report is free; "
            "after that, {price} per report."
        ),
        "hero_safe": "Your file is never published.",
        "nav_lang": "Language",
        "trust": [
            ("shield", "Never connects to your broker or recommends trades"),
            ("hash", "Every report can be checked"),
            ("key", "First full report free with your account"),
        ],
        "mock_url": "report · class B",
        "mock_k": "Verdict",
        "cta_sample": "See a sample report",
        "hero_lead": (
            "Upload the backtest or account history you already have. Rigor tests it against "
            "costs, the configurations tried and prop-firm challenge rules, and gives you an "
            "A\u00a0to\u00a0D class with every figure explained."
        ),
        "mock_cap": "Illustration with synthetic data",
        "mock_is": "In sample",
        "mock_oos": "Out of sample",
        "mock_kpis": [
            ("0.97", "Deflated Sharpe"),
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
            "Almost any strategy looks good on paper. Rigor is there so a pretty curve does not "
            "fool you before you risk your money or pay for a robot. These are the three reasons "
            "most of them do not hold up outside the tester."
        ),
        "example_case": {
            "eyebrow": "How it catches it in the sample",
            "title": "A Sharpe of 1.8 in the tester. Class C in Rigor.",
            "text": (
                "The sample report is an MT5 backtest built from synthetic data. Rigor lowers its "
                "class for three things the tester does not show:"
            ),
            "points": (
                "It came out of 120 settings tried; once they are counted, its Sharpe no longer "
                "reaches the threshold.",
                "At twice the reference cost it ends in a loss.",
                "Its live account, 180 trades, falls outside what its own backtest would lead "
                "you to expect.",
            ),
            "cta": "See the sample report",
        },
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
            "Rigor checks your file on six points. Each one comes out as Pass, Weak, Fail or Not "
            "measured, with two plain sentences on what it means for you. The methods are "
            "public and written down in the methodology."
        ),
        "stats": [
            ("6", "audited dimensions"),
            ("{flags}", "red flags checked on every file"),
            ("{presets}", "prop-firm challenges to simulate"),
            ("{platforms}", "platforms it recognises"),
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
                "exactly what it is and what it is not, in English, Spanish or Portuguese.",
            ),
            (
                "percent",
                "Against cash",
                "We subtract what cash paid over the same dates, in your account's currency "
                "when your report names it and it is one of these (Mexican "
                "pesos, reais, euros, pounds, yen, Canadian "
                "dollars or Swiss francs); if it names no currency or is in dollars, in "
                "dollars (3-month US Treasury bills); in another currency, that line is not "
                "computed. Official public data. You see the Sharpe without what cash already "
                "paid and, if you upload a benchmark, the alpha too.",
            ),
            (
                "chart",
                "Calm and agitated markets",
                "Each return is placed by the previous day's VIX, and every publicly dated "
                "crisis your history covers is measured on its own: you see whether the result "
                "depends on one kind of market.",
            ),
            (
                "globe",
                "In your currency and after inflation",
                "If the account is in dollars and exchange rates are available, you see its "
                "result in Mexican pesos, reais, euros and four more currencies. "
                "When price indexes are available, you see each currency, including the "
                "dollar, after its own inflation. If the account is already in one of those "
                "currencies, you see the result after its own inflation. Exchange rates "
                "from FRED and price indexes from official statistical sources.",
            ),
        ],
        "how_eyebrow": "Process",
        "pricing_eyebrow": "Pricing",
        "plan_free": "Preview",
        "plan_free_amount": "Free",
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
            "Simulation of the {firms} challenge you choose, with its published rules",
            "How much cost it can bear before it ends in a loss",
            "Resampled one-year risk and the capital it needs",
            "Specific questions for the robot's vendor or the manager",
            "PDF and, if you want, a public page with a badge",
        ],
        "full_more": "See a full sample report",
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
                f"{_FREE} free previews a month."
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
        "faq_more": "More questions: prices, payment, your account and contact",
        "final_title": ("Before you put money on a strategy,", "take a close look."),
        "final_lead": "Upload the report and get the class, the charts and their explanation free.",
        "final_tools": "No file yet? Try the free tools, no sign-up.",
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
# The mock's class ring says B, so its statuses must give B under verdict.overall_class:
# multiplicity passes (120 declared trials, deflated Sharpe 0.97 >= dsr_pass), and the
# weak out-of-sample stretch is the missing piece a B describes.
_MOCK_STATUSES: tuple[tuple[str, str], ...] = (
    ("statistical_significance", "PASS"),
    ("multiplicity", "PASS"),
    ("costs", "PASS"),
    ("out_of_sample", "WEAK"),
    ("data_quality", "PASS"),
    ("benchmark", "NOT_APPLICABLE"),
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _locale(locale: str) -> str:
    return locale if locale in _COPY else "es"


#: Sign-up, sign-in and "My account" per language (``account_pages.PATHS``,
#: which imports this module, so they are spelled here too).
_ACCOUNT_PATHS: dict[str, tuple[str, str, str]] = {
    "es": ("/registro", "/entrar", "/cuenta"),
    "en": ("/signup", "/login", "/account"),
    "pt": ("/pt/cadastro", "/pt/entrar", "/pt/conta"),
}


def _home(locale: str) -> str:
    return {"en": "/en", "pt": "/pt"}.get(locale, "/")


#: The upload form's own page in each language. Without an account (when uploads
#: need one) it sends the visitor to sign-up first and back here after.
AUDIT_PATHS: dict[str, str] = {"es": "/auditar", "en": "/en/audit", "pt": "/pt/auditar"}


def audit_path(locale: str) -> str:
    return AUDIT_PATHS.get(locale, AUDIT_PATHS["es"])


def _other_name(locale: str) -> str:
    return "English" if locale == "es" else "Español"


def _dimension_titles(locale: str) -> dict[str, str]:
    return DIMENSION_TITLES_PT if locale == "pt" else DIMENSION_TITLES[locale]


def _class_text(overall: str, locale: str) -> str:
    return CLASS_B_PT if locale == "pt" and overall == "B" else class_text(overall, locale)


def _badge(tag: str, locale: str) -> str:
    return f"<span class='badge {_e(tag)}'>{_e(evidence_label(tag, locale))}</span>"


def _disclaimer(locale: str) -> str:
    return localize_tags(DISCLAIMER_PT if locale == "pt" else DISCLAIMER[locale], locale)


def _method_title(locale: str) -> str:
    return str(METHOD_COPY.get(locale, METHOD_COPY["es"])["title"])


def _sample_url(locale: str) -> str:
    """The sample report in the page's language."""
    return {"es": "/ejemplo?lang=es", "pt": "/pt/exemplo"}.get(locale, "/sample?lang=en")


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


def _lang_menu(locale: str, switch_href: str, alternates: dict[str, str] | None) -> str:
    """The language switch as one small menu (current language, then the others)
    that opens without script (<details>); app.js closes it on an outside click."""
    others = _switch_links(locale, switch_href, alternates, menu=True)
    if not others:
        return ""
    return (
        f"<details class='langs'><summary aria-label='{_e(_UI[locale]['nav_lang'])}'>"
        f"{icon('globe')}<span>{locale.upper()}</span>"
        "<svg class='chev' viewBox='0 0 24 24' fill='none' stroke='currentColor' "
        "stroke-width='2' aria-hidden='true'><path d='M6 9l6 6 6-6'/></svg></summary>"
        f"<div class='langs-panel'><span aria-current='true'>{_e(LANGUAGE_NAMES[locale])}</span>"
        f"{others}</div></details>"
    )


def _preset_options(locale: str, chosen: str = DEFAULT_PRESET) -> str:
    options = []
    for key in sorted(PRESETS):
        rules = PRESETS[key]
        selected = " selected" if key == chosen else ""
        label = preset_label(rules.firm, rules.program, rules.phase, locale)
        options.append(f"<option value='{_e(key)}'{selected}>{_e(label)}</option>")
    return "".join(options)


def _compare_url(locale: str) -> str:
    from quant_trade.audit.compare import COMPARE_PATH

    return COMPARE_PATH.get(locale, COMPARE_PATH["es"])


def _nav(
    locale: str,
    switch_href: str,
    *,
    solid: bool = False,
    alternates: dict[str, str] | None = None,
) -> str:
    ui = _UI[locale]
    home = _home(locale)
    account = _ACCOUNT_PATHS.get(locale, _ACCOUNT_PATHS["es"])[2]
    links = (
        f"<a href='{home}#how'>{_e(ui['nav_how'])}</a>"
        f"<a href='{_sample_url(locale)}'>{_e(ui['nav_sample'])}</a>"
        f"<a href='{PRICING_PATH[locale]}'>{_e(ui['nav_pricing'])}</a>"
        f"<a href='{_e(guides_index_url(locale))}'>{_e(ui['nav_guides'])}</a>"
        f"<a href='{tools_url(locale)}'>{_e(ui['nav_tools'])}</a>"
        f"<a href='{home}#faq'>{_e(ui['nav_faq'])}</a>"
    )
    switch = _lang_menu(locale, switch_href, alternates)
    # Phones: the same links in a menu that opens without script (<details>).
    menu = (
        f"<details class='menu'><summary aria-label='{_e(ui['nav_menu'])}'>"
        "<span class='burger' aria-hidden='true'><i></i><i></i><i></i></span></summary>"
        f"<nav class='menu-panel' aria-label='{_e(ui['nav_menu'])}'>{links}"
        + _switch_links(locale, switch_href, alternates, menu=True)
        + f"<a href='{account}'>{_e(ui['nav_account'])}</a>"
        + f"<a class='btn btn-primary' href='{audit_path(locale)}'>{_e(ui['cta'])}</a>"
        "</nav></details>"
    )
    return (
        f"<header class='nav{' nav-solid' if solid else ''}'><div class='wrap nav-in'>"
        + logo(home)
        + f"<nav class='nav-links' aria-label='{_e(BRAND)}'>{links}</nav>"
        + f"<div class='nav-end'>{switch}<a class='lang' href='{account}'>"
        f"{_e(ui['nav_account'])}</a><a class='btn btn-sm' href='{audit_path(locale)}'>"
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
        + f"<main id='main'>{localize_text_nodes(body, locale)}</main>"
        + _footer(locale)
        + "</body></html>"
    )


def _public_meta(
    title: str, description: str, locale: str, path: str, base_url: str, image: str = ""
) -> str:
    return head_meta(
        PageMeta(
            title=title,
            description=description,
            locale=locale,
            paths=page_paths(path),
            image=image,
            image_alt=title,
        ),
        base_url=base_url,
    )


def sample_meta(locale: str, base_url: str) -> str:
    """Head tags for the sample report, the one indexable report page."""
    locale = _locale(locale)
    copy = _COPY[locale]
    title = f"{copy['sample_link']} · {copy['title']}"
    path = SAMPLE_PAGE_PATHS.get(locale, "/sample")
    return _public_meta(title, copy["sample_description"], locale, path, base_url, "sample")


def _guide_links(locale: str) -> str:
    return " · ".join(
        f"<a href='{_e(guide_url(g.slug, locale))}'>{_e(g.platform_for(locale))}</a>"
        for g in REPORT_GUIDES
    )


def _check_url(locale: str) -> str:
    """The page where anyone checks a report file was not edited."""
    from quant_trade.audit.check import CHECK_PATH

    return CHECK_PATH.get(locale, CHECK_PATH["es"])


def _footer(locale: str) -> str:
    from quant_trade.audit.faq import FAQ_COPY, FAQ_PATH

    copy = _COPY[locale]
    ui = _UI[locale]
    home = _home(locale)
    linked = link_locale(locale)
    sample = SAMPLE_PAGE_PATHS.get(locale, SAMPLE_PAGE_PATHS[linked])
    product = (
        f"<li><a href='{home}#how'>{_e(ui['nav_how'])}</a></li>"
        f"<li><a href='{_sample_url(locale)}'>{_e(ui['nav_sample'])}</a></li>"
        f"<li><a href='{tools_url(locale)}'>{_e(TOOLS_COPY[locale]['nav'])}</a></li>"
        f"<li><a href='{examples_url(locale)}'>{_e(EXAMPLES_COPY[locale]['nav'])}</a></li>"
        f"<li><a href='{reading.reading_url(locale)}'>{_e(reading.COPY[locale]['title'])}</a></li>"
        f"<li><a href='{sample}.pdf' download>{_e(ui['footer_sample_pdf'])}</a></li>"
        f"<li><a href='{PRICING_PATH[locale]}'>{_e(ui['nav_pricing'])}</a></li>"
        f"<li><a href='{_e(guides_index_url(locale))}'>{_e(ui['nav_guides'])}</a></li>"
        f"<li><a href='{_e(articles_index_url(locale))}'>"
        f"{_e(ARTICLES_COPY[locale]['eyebrow'])}</a></li>"
        f"<li><a href='{_compare_url(locale)}'>{_e(ui['nav_compare'])}</a></li>"
        f"<li><a href='{_check_url(locale)}'>{_e(ui['footer_check'])}</a></li>"
        f"<li><a href='{_e(method_url(locale))}'>{_e(_method_title(locale))}</a></li>"
        f"<li><a href='{_e(calculator_url(locale))}'>{_e(CALCULATOR_COPY[locale]['nav'])}</a></li>"
        f"<li><a href='{FAQ_PATH[locale]}'>{_e(FAQ_COPY[locale]['title'])}</a></li>"
        f"<li><a href='{institutional.REVIEW_PATHS[locale]}'>"
        f"{_e(institutional.COPY[locale]['title'])}</a></li>"
    )
    legal = (
        f"<li><a href='{_e(legal_url('terms', locale))}'>{_e(copy['terms_link'])}</a></li>"
        f"<li><a href='{_e(legal_url('privacy', locale))}'>{_e(copy['privacy_link'])}</a></li>"
        f"<li><a href='{CONTACT_PATHS[locale]}'>{_e(CONTACT_COPY[locale]['eyebrow'])}</a></li>"
    )
    return (
        "<footer class='foot'><div class='wrap'><div class='foot-grid'>"
        f"<div>{logo(home)}<p class='tagline'>{_e(TAGLINE[locale])}. {_e(ui['footer_base'])}</p>"
        f"</div><div><h2>{_e(ui['footer_product'])}</h2><ul>{product}</ul></div>"
        f"<div><h2>{_e(ui['footer_legal'])}</h2><ul>{legal}</ul></div></div>"
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
        f"<div class='mock-tags'>{_badge('MEASURED', locale)}{_badge('DECLARED', locale)}"
        f"{_badge('NOT_MEASURED', locale)}</div></div></div></div>"
        f"<div class='mock-cap'>{_e(ui['mock_cap'])}</div></div>"
    )


def _status_chip(status: str, locale: str) -> str:
    text = (STATUS_TEXT_PT if locale == "pt" else STATUS_TEXT[locale]).get(status, status)
    return f"<span class='badge {_e(status)}'>{_e(text)}</span>"


def _hero(locale: str, sample: str, *, price_usd: float = 0.0, free_mode: bool = True) -> str:
    ui = _UI[locale]
    trust = "".join(f"<li>{icon(name)}{_e(text)}</li>" for name, text in ui["trust"])
    # The anchor names the free first report and the price after it, so it needs both.
    anchor = (
        f"<p class='hero-anchor'>{_e(ui['hero_anchor'].format(price=usd(price_usd)))}</p>"
        if not free_mode and price_usd > 0 and accounts.WELCOME_FULL_REPORT
        else ""
    )
    # Text on the left, the report on the right: the first screen shows the product.
    # The words are there from the first paint; only the illustration rises in.
    return (
        "<section class='hero hero-split dark'>" + aurora() + grid_bg() + "<div class='wrap'>"
        "<div class='hero-grid'><div class='hero-copy'>"
        f"<div class='pill'><span class='dot'></span>{_e(TAGLINE[locale])}</div>"
        f"<h1 class='display'><span class='l'>{_e(ui['hero_a'])}</span>"
        f"<em class='l'>{_e(ui['hero_b'])}</em></h1>"
        f"<p class='lead'>{_e(ui['hero_lead'])}</p>"
        "<div class='hero-cta'>"
        f"<a class='btn btn-primary btn-lg' href='{audit_path(locale)}'>{_e(ui['cta'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(sample)}'>{_e(ui['cta_sample'])}{icon('arrow')}</a></div>"
        f"{anchor}<p class='hero-safe'>{_e(ui['hero_safe'])}</p>"
        f"<ul class='trust'>{trust}</ul></div>" + _mock(locale) + "</div></div></section>"
    )


#: Challenges from named firms; the generic two-step reference is not a firm's
#: challenge, so pages that say "N challenges from FTMO, ..." leave it out.
FIRM_CHALLENGES = sum(1 for rules in PRESETS.values() if rules.firm != "Generic")


def _specs(locale: str) -> str:
    """The key figures in a row, then the platforms the importers read."""
    ui = _UI[locale]
    counts = {
        "presets": FIRM_CHALLENGES,
        # Distinct platforms named on the page: the dedicated readers (minus
        # the generic "CSV") plus the exports the universal reader recognises.
        "platforms": len({*PLATFORMS, *RECOGNISED_PLATFORMS} - {"CSV"}),
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
                "si el resultado aguanta el número de intentos, costos más altos y quitarle sus "
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
                "significación, Sharpe deflactado, costos, si sigue funcionando en el periodo "
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
    # What each case uploads and gets lives on its own page; the landing keeps it short.
    for i, (name, title, pain, _upload, _get, _guide) in enumerate(words["items"]):
        page = AUDIENCE_PAGES[i]
        link = f"<a href='{_e(audience_url(page.slug, locale))}'>{_e(words['more'])}</a>"
        cards.append(
            f"<div class='card spot audience' data-reveal style='--i:{i % 2}'>"
            f"<div class='icon'>{icon(name)}</div><h3>{_e(title)}</h3><p>{_e(pain)}</p>"
            f"<p>{link}</p></div>"
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


def _tool_name(key: str, locale: str) -> str:
    """The short name a free tool already uses (menu, footer or its own nav label)."""
    if key == "calculator":
        return str(CALCULATOR_COPY[locale]["nav"])
    if key == "winrate":
        return str(winrate.COPY[locale]["nav"])
    if key == "reading":
        return reading.COPY[locale]["title"]
    return str(_UI[locale]["footer_check"])


def _tool_url(key: str, locale: str) -> str:
    if key == "calculator":
        return calculator_url(locale)
    if key == "winrate":
        return winrate.WINRATE_PATH[locale]
    if key == "reading":
        return reading.reading_url(locale)
    return _check_url(locale)


def _article_link(key: str, locale: str) -> str:
    """A link to an article, with its title in ``locale``."""
    title = ARTICLES_BY_KEY[key].text[locale].title
    return f"<a href='{_e(article_url(key, locale))}'>{_e(title)}</a>"


def _example_section(locale: str) -> str:
    """The sample report's finding, right under the first screen."""
    return (
        "<section class='section light' id='ejemplo'><div class='wrap'>"
        + _example_case(locale)
        + "</div></section>"
    )


def _example_case(locale: str) -> str:
    """One real finding from the sample report (synthetic data)."""
    words = _UI[locale]["example_case"]
    points = "".join(f"<li>{icon('check')}<span>{_e(p)}</span></li>" for p in words["points"])
    return (
        "<div class='investor' data-reveal>"
        f"<div><span class='eyebrow'><span class='dot'></span>{_e(words['eyebrow'])}</span>"
        f"<h2>{_e(words['title'])}</h2><p>{_e(words['text'])}</p>"
        f"<a class='btn btn-dark' href='{_sample_url(locale)}'>"
        f"{_e(words['cta'])}<span class='go'>{icon('arrow')}</span></a></div>"
        f"<ul class='checks'>{points}</ul></div>"
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


def _firm_names(locale: str) -> str:
    """The firms whose published challenge rules the simulator carries, in words."""
    names = sorted({rules.firm for rules in PRESETS.values() if rules.firm != "Generic"})
    joiner = {"es": " o ", "en": " or ", "pt": " ou "}[locale]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + joiner + names[-1]


def _full_items(locale: str) -> list[str]:
    """What the full report adds, as the price card lists it (``_UI['full_items']``)."""
    firms = _firm_names(locale)
    return [item.format(firms=firms) for item in _UI[locale]["full_items"]]


def _checks(items: list[str]) -> str:
    return (
        "<ul class='checks'>"
        + "".join(f"<li>{icon('check')}<span>{_e(item)}</span></li>" for item in items)
        + "</ul>"
    )


#: Billing countries as the card-payment line names them, in the order they are listed.
#: Portuguese carries its preposition and article ("no México", "na Espanha").
_CARD_MARKET_WORDS: dict[str, dict[str, str]] = {
    "MX": {"es": "México", "en": "Mexico", "pt": "no México"},
    "US": {"es": "Estados Unidos", "en": "the United States", "pt": "nos Estados Unidos"},
    "BR": {"es": "Brasil", "en": "Brazil", "pt": "no Brasil"},
    "ES": {"es": "España", "en": "Spain", "pt": "na Espanha"},
}
_CARD_MARKETS_LINE: dict[str, tuple[str, str]] = {
    "es": (" y ", "Por ahora solo en {places}."),
    "en": (" and ", "For now, in {places} only."),
    "pt": (" e ", "Por enquanto, só {places}."),
}


def card_markets_line(markets: Sequence[str], locale: str) -> str:
    """The sentence naming the countries where card payment is open, or "" for none.

    Only the countries the owner approved (``AUDIT_APPROVED_MARKETS``) are named, so
    the landing never offers card payment where Checkout would refuse it."""
    words = [_CARD_MARKET_WORDS[m][locale] for m in ("MX", "US", "BR", "ES") if m in set(markets)]
    if not words:
        return ""
    joiner, template = _CARD_MARKETS_LINE[locale]
    places = words[0] if len(words) == 1 else ", ".join(words[:-1]) + joiner + words[-1]
    return template.format(places=places)


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
    card_markets: Sequence[str] = (),
) -> str:
    ui = _UI[locale]
    head = _section_head(ui["pricing_eyebrow"], f"<h2 class='h2'>{_e(copy['prices_title'])}</h2>")
    # Five lines on the landing; the sample report shows everything a full report has.
    more = (
        f"<p class='price-more'><a href='{_sample_url(locale)}'>{_e(ui['full_more'])}"
        f"{icon('arrow')}</a></p>"
    )
    if free_mode:
        body = (
            "<div class='prices prices-one'><div class='price featured' data-reveal>"
            f"<span class='price-name'>{_e(ui['plan_full'])}</span>"
            f"<div class='price-amount'>{_e(ui['plan_free_amount'])}</div>"
            f"<p class='muted'>{_e(copy['price_free_mode'])}</p>"
            + _checks(ui["free_items"] + _full_items(locale))
            + more
            + f"<a class='btn btn-primary' href='{audit_path(locale)}'>{_e(ui['cta'])}</a>"
            + "</div></div>"
        )
    else:
        ways = []
        if card_payments:
            card = " ".join(
                p for p in (copy["pay_card"], card_markets_line(card_markets, locale)) if p
            )
            ways.append(f"<li>{icon('check')}<span>{_e(card)}</span></li>")
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
            f"<div class='price-amount'>{_e(ui['plan_free_amount'])}</div>"
            f"<p class='muted'>{_e(copy['price_free'].format(n=_FREE))}</p>"
            + f"<a class='btn btn-ghost' href='{audit_path(locale)}'>{_e(ui['cta'])}</a></div>"
            f"<div class='price featured' data-reveal style='--i:1'>"
            f"<span class='ribbon'>{_e(ui['plan_badge'])}</span>"
            f"<span class='price-name'>{_e(copy['price_full_title'])}"
            f"</span><div class='price-amount'>{_e(usd(price_usd))}"
            f"<small>{_e(ui['plan_full_note'])}</small></div>"
            f"<p class='muted'>{_e(copy['price_full'])}</p>"
            + (
                "<p class='price-pack'><strong>"
                + _e(
                    copy["price_pack"].format(
                        n=PACK_CREDITS,
                        price=usd(pack_price_usd),
                        each=usd(pack_price_usd / PACK_CREDITS),
                    )
                )
                + "</strong></p>"
                if pack_price_usd
                else ""
            )
            + _checks(_full_items(locale))
            + more
            + f"<a class='btn btn-primary' href='{audit_path(locale)}'>{_e(ui['cta_full'])}</a>"
            + "</div></div>"
            + (f"<ul class='checks pay-ways' data-reveal>{''.join(ways)}</ul>" if ways else "")
            + f"<p class='method-link' data-reveal><a href='{_e(method_url(locale))}'>"
            f"{_e(_method_title(locale))}{icon('arrow')}</a></p>"
        )
    return (
        f"<section class='section dark' id='pricing'><div class='wrap'>{head}{body}"
        f"<p class='method-link'><a href='{PRICING_PATH[locale]}'>"
        f"{_e(PRICING_COPY[locale]['detail'])}{icon('arrow')}</a></p></div></section>"
    )


def _drop(
    name: str,
    label: str,
    accept: str,
    help_html: str,
    locale: str,
    *,
    main: bool = False,
    required: bool = False,
    help_id: str = "",
) -> str:
    ui = _UI[locale]
    file_attributes = " required" if required else ""
    help_attributes = ""
    if help_id and help_html:
        file_attributes += f" aria-describedby='{_e(help_id)}'"
        help_attributes = f" id='{_e(help_id)}'"
    if main:
        formats = "".join(f"<span>{_e(p)}</span>" for p in PLATFORMS)
        return (
            f"<div class='field'><label for='f-{name}'>{_e(label)}</label>"
            f"<div class='drop drop-main'><div class='icon'>{icon('upload')}</div>"
            f"<div class='drop-title'>{_e(ui['drop_title'])}</div>"
            f"<div class='drop-sub'>{_e(ui['drop_sub'])}</div>"
            f"<div class='formats'>{formats}</div><div class='drop-file' aria-live='polite'></div>"
            f"<input id='f-{name}' type='file' name='{name}'{file_attributes} "
            f"accept='{accept}'></div>"
            f"<div class='help'{help_attributes}>{help_html}</div></div>"
        )
    return (
        f"<div class='field'><label for='f-{name}'>{_e(label)}</label>"
        f"<div class='drop'><div class='icon'>{icon('file')}</div><div class='drop-txt'>"
        f"<div class='drop-title'>{_e(ui['drop_small'])}</div>"
        f"<div class='drop-file' aria-live='polite'></div>"
        f"<input id='f-{name}' type='file' name='{name}'{file_attributes} "
        f"accept='{accept}'></div></div>"
        + (f"<div class='help'{help_attributes}>{help_html}</div>" if help_html else "")
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
    signup, signin, _ = _ACCOUNT_PATHS.get(locale, _ACCOUNT_PATHS["es"])
    return (
        f"<div class='signin-first'><p>{_e(copy['signin_first'])}</p>"
        "<div class='inline-form'>"
        f"<a class='btn btn-primary' href='{signup}'>{_e(copy['signin_create'])}</a>"
        f"<a class='btn btn-ghost' href='{signin}'>{_e(copy['signin_enter'])}</a>"
        "</div></div>"
    )


#: What the file pickers offer for a platform file: web pages (and the tables
#: brokers save as .xls), text tables, workbooks and a zip holding one export.
REPORT_ACCEPT = ".htm,.html,.csv,.txt,.tsv,.xlsx,.xls,.ods,.xml,.zip,.pdf"


def _ownership_field(locale: str, chosen: str) -> str:
    """The optional "Whose strategy is this?" field, on "I'd rather not say"
    unless the client chose another answer (kept after a refusal). It only sets
    to whom the report speaks (``audit/ownership.py``)."""
    words = OWNERSHIP_FORM[locale]
    chosen = chosen if chosen in OWNERSHIP_ROLES else ""
    options = "".join(
        f"<option value='{_e(value)}'"
        + (" selected" if value == chosen else "")
        + f">{_e(text)}</option>"
        for value, text in words["choices"].items()
    )
    return _field(words["label"], f"<select name='ownership'>{options}</select>", words["help"])


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
    carried: Mapping[str, str] | None = None,
) -> str:
    ui = _UI[locale]
    linked = link_locale(locale)
    values = carried or {}

    def value(name: str) -> str:
        return _e(values.get(name, ""))

    def checked(name: str) -> str:
        return " checked" if values.get(name, "").lower() in {"on", "yes", "true", "1"} else ""

    advanced_open = any(
        values.get(name)
        for name in (
            "cost_bps",
            "oos_start",
            "initial_balance",
            "net_of_fees",
            "description",
        )
    ) or values.get("benchmark_applicable", "yes") not in {"", "yes"}
    extras_open = extras_open or values.get("challenge", DEFAULT_PRESET) not in {
        "",
        DEFAULT_PRESET,
    }
    mapping_open = any(
        values.get(f"col_{role}") for _, roles in copy["map_groups"] for role in roles
    )
    # The report exists in Spanish, English and Portuguese: the page's own language.
    selected = {"es": "", "en": "", "pt": ""}
    selected_locale = values.get("locale", locale)
    selected[selected_locale if selected_locale in selected else linked] = " selected"
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
        f"<details class='adv map-columns'{' open' if mapping_open else ''}><summary><span>"
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
                    f"autocomplete='off' spellcheck='false' value='{value(f'col_{role}')}'>",
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
        f"<details class='adv'{' open' if advanced_open else ''}><summary><span>"
        f"{_e(ui['advanced'])} <small>· {_e(ui['advanced_note'])}</small></span>"
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
        "aria-hidden='true'><path d='M6 9l6 6 6-6'/></svg></summary><div class='adv-body'>"
        + _drop(
            "trades",
            copy["trades"],
            ".csv,text/csv",
            f"{_e(copy['trades_help'])}<br>{_e(copy['dates_hint'])}",
            locale,
        )
        + "<div class='form-grid'>"
        + _drop(
            "benchmark",
            copy["benchmark"],
            ".csv,.xlsx,text/csv",
            _e(copy["benchmark_help"]),
            locale,
        )
        + _drop("variants", copy["variants"], ".csv,text/csv", _e(copy["variants_help"]), locale)
        + _field(
            copy["cost_bps"],
            "<input type='number' name='cost_bps' min='0' step='0.1' placeholder='0' "
            f"value='{value('cost_bps')}'>",
        )
        + _field(
            copy["oos_start"],
            f"<input type='date' name='oos_start' value='{value('oos_start')}'>",
        )
        + _field(
            copy["benchmark_applicable"],
            "<select name='benchmark_applicable'>"
            + "".join(
                f"<option value='{option}'"
                + (" selected" if values.get("benchmark_applicable", "yes") == option else "")
                + f">{_e(copy[option])}</option>"
                for option in ("yes", "no")
            )
            + "</select>",
        )
        + _field(
            copy["initial_balance"],
            "<input type='number' name='initial_balance' min='0' step='0.01' "
            f"value='{value('initial_balance')}'>",
        )
        + "</div>"
        + "<label class='check'><input type='checkbox' name='net_of_fees' value='on'"
        + f"{checked('net_of_fees')}>"
        + f"<span>{_e(copy['net_of_fees'])}</span></label>"
        + _field(
            copy["description"],
            "<textarea name='description' rows='3' maxlength='2000'>"
            f"{value('description')}</textarea>",
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
        # With JavaScript the answer comes back in place (data-inplace): a refusal
        # fills upload-alert, the column menus fill map-fields, and the file stays
        # chosen. Without it the form posts as always.
        + "<form method='post' action='/audits' enctype='multipart/form-data' data-busy='busy' "
        "data-inplace>"
        + "<div id='upload-alert' role='alert' hidden></div>"
        + _drop(
            "report",
            copy["report"],
            REPORT_ACCEPT,
            report_help,
            locale,
            main=True,
        )
        + "<div id='map-fields' hidden></div>"
        + mapping
        + f"<div class='or-rule' aria-hidden='true'><span>{_e(copy['or_word'])}</span></div>"
        + _drop(
            "equity",
            copy["equity"],
            ".csv,.txt,.tsv,.xlsx,.ods,text/csv",
            f"{_e(copy['equity_help'])}<br>{_e(copy['dates_hint'])}",
            locale,
        )
        + series_fields(locale, carried=values)
        # Declared trials decide whether multiplicity can pass (verdict.assess_multiplicity),
        # so the field sits in the main form, not under the advanced options.
        + _field(
            copy["trials"],
            "<input type='number' name='trials' min='1' step='1' inputmode='numeric' "
            f"value='{value('trials')}'>",
            copy["trials_help"],
        )
        + _ownership_field(locale, values.get("ownership", ""))
        # The one-file case stays short; the second files and the challenge open on demand.
        + f"<details class='adv extras'{' open' if extras_open else ''}><summary><span>"
        f"{_e(ui['extras'])} <small>· {_e(ui['extras_note'])}</small></span>"
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
        "aria-hidden='true'><path d='M6 9l6 6 6-6'/></svg></summary><div class='adv-body'>"
        "<div class='form-grid'>"
        + _drop("optimization", copy["optimization"], ".xml", optimization_help, locale)
        + _drop("live", copy["live"], REPORT_ACCEPT, _e(copy["live_help"]), locale)
        + "</div>"
        + _field(
            copy["challenge"],
            "<select name='challenge'>"
            + _preset_options(locale, values.get("challenge", DEFAULT_PRESET))
            + "</select>",
            copy["challenge_help"].format(as_of=_plain_date(AS_OF, locale)),
        )
        + "</div></details>"
        + "<div class='form-grid'>"
        + _field(
            copy["locale"],
            f"<select name='locale'><option value='es'{selected['es']}>Español</option>"
            f"<option value='en'{selected['en']}>English</option>"
            f"<option value='pt'{selected['pt']}>Português</option></select>",
            copy.get("locale_note", ""),
        )
        + code_field
        + "</div>"
        + advanced
        + "<label class='check'><input type='checkbox' name='consent' value='on' required"
        + f"{checked('consent')}>"
        f"<span>{_e(copy['consent'].format(retention=retention_days))} "
        f"{_e(copy['consent_read'])} "
        f"<a href='{_e(legal_url('terms', locale))}'>{_e(copy['terms_link'])}</a> · "
        f"<a href='{_e(legal_url('privacy', locale))}'>{_e(copy['privacy_link'])}</a></span>"
        "</label>" + "<div class='submit-row'><button class='btn btn-primary btn-lg btn-block' "
        f"type='submit'>{_e(copy['submit'])}<span class='go'>{icon('arrow')}</span></button></div>"
        + "</form></div></div>"
        + "<div class='busy' id='busy' role='status' aria-live='polite'><div class='busy-card'>"
        f"<div class='loader'></div><h2>{_e(ui['busy_title'])}</h2>"
        f"<p class='muted'>{_e(ui['busy_sub'])}</p><ol>{busy_steps}</ol></div></div>" + "</section>"
    )


#: The landing's questions, by their place in ``_COPY[locale]['faq']`` (Portuguese has
#: one more, on the report's language): what you get, which file, what happens to it,
#: the evidence labels, what Rigor does not predict and that it never reaches a
#: broker. The others in ``_COPY[locale]['faq']`` are answered on ``FAQ_PATH``
#: (``faq.landing_only_questions``), next to the answers on prices, payment and contact.
_LANDING_FAQ: dict[str, tuple[int, ...]] = {
    "es": (2, 0, 7, 4, 5, 6),
    "en": (2, 0, 7, 4, 5, 6),
    "pt": (2, 0, 8, 5, 6, 7),
}


#: The operator's name and address under the questions, while "who is behind it"
#: (``_founder``) is not shown; the settings let each language word the address. It
#: never borrows that block's heading (``FOUNDER_COPY[locale]['title']``): without the
#: founder's photo, "who is behind it" does not appear on the page at all.
OPERATOR_LINE: dict[str, str] = {
    "es": "Responsable del servicio: {name}, {address}.",
    "en": "Service operator: {name}, {address}.",
    "pt": "Responsável pelo serviço: {name}, {address}.",
}
#: The WhatsApp line under the questions (``cfg.contact_url``), on the same terms.
ASK_LINE: dict[str, tuple[str, str]] = {
    "es": ("¿Dudas antes de subir? Escríbenos por WhatsApp; responde una persona.", "Escribir"),
    "en": ("Questions before you upload? Write to us on WhatsApp; a person answers.", "Write"),
    "pt": ("Dúvidas antes de enviar? Escreva pelo WhatsApp; responde uma pessoa.", "Escrever"),
}


def _faq_html(
    copy: dict[str, Any],
    locale: str,
    *,
    retention_days: int,
    operator: tuple[str, str] = ("", ""),
    contact_url: str = "",
) -> str:
    from quant_trade.audit.faq import FAQ_PATH

    ui = _UI[locale]
    name, address = operator
    line = OPERATOR_LINE[locale].format(name=name, address=address)
    who = f"<p class='muted faq-who'>{_e(line)}</p>" if name and address else ""
    ask, ask_link = ASK_LINE[locale]
    if contact_url:
        who += (
            f"<p class='muted faq-who'>{_e(ask)} "
            f"<a href='{_e(contact_url)}' rel='noopener'>{_e(ask_link)}</a></p>"
        )
    items = "".join(
        f"<details><summary>{_e(question)}</summary>"
        f"<p>{_e(answer.format(retention=retention_days))}</p></details>"
        for question, answer in (copy["faq"][i] for i in _LANDING_FAQ[locale])
    )
    return (
        "<section class='section dark' id='faq'><div class='wrap wrap-mid'>"
        + _section_head(ui["faq_eyebrow"], f"<h2 class='h2'>{_e(copy['faq_title'])}</h2>")
        + f"<div class='faq' data-reveal>{items}</div>"
        # What Rigor does not do stays on the page whether or not "who is behind it" shows.
        f"<p class='muted faq-not'>{_e(copy['not'])}</p>{who}"
        f"<p class='method-link'><a href='{FAQ_PATH[locale]}'>{_e(ui['faq_more'])}"
        f"{icon('arrow')}</a></p></div></section>"
    )


#: The founder's profile on X, linked from "who is behind it".
FOUNDER_X_URL = "https://x.com/SergioVallvj"
#: The founder's photo in ``static``. The founder adds it himself, and the photo is
#: his approval of the block's text: until the file is there the block is not shown.
FOUNDER_PHOTO = "fundador.jpg"
FOUNDER_COPY: dict[str, dict[str, str]] = {
    "es": {
        "title": "Quién está detrás",
        "text": (
            "Soy {name} y hago Rigor desde México. Lo construí para responder una pregunta "
            "antes de arriesgar dinero: cuánto de un buen backtest se distingue de la suerte. "
            "Si tu archivo no se lee o una cifra no te cuadra, escríbeme y te respondo yo."
        ),
        "x": "En X",
        "whatsapp": "Escribir por WhatsApp",
    },
    "en": {
        "title": "Who is behind it",
        "text": (
            "I'm {name} and I build Rigor from Mexico. I built it to answer one question "
            "before risking money: how much of a good backtest stands out from luck. If your "
            "file does not read or a figure does not add up, write to me and I will answer "
            "myself."
        ),
        "x": "On X",
        "whatsapp": "Write on WhatsApp",
    },
    "pt": {
        "title": "Quem está por trás",
        "text": (
            "Sou {name} e faço a Rigor no México. Eu a criei para responder uma pergunta antes "
            "de arriscar dinheiro: quanto de um bom backtest se distingue da sorte. Se o seu "
            "arquivo não for lido ou um número não fechar, escreva para mim e eu mesmo "
            "respondo."
        ),
        "x": "No X",
        "whatsapp": "Escrever pelo WhatsApp",
    },
}


def _founder(locale: str, *, operator: tuple[str, str], contact_url: str) -> str:
    """Who is behind Rigor, signed by the operator's name, once the founder's photo is in.

    Without ``cfg.operator_name`` or without ``static/fundador.jpg`` it returns "":
    no text, no link and no placeholder picture. What Rigor does not do
    (``_COPY['not']``) is said under the questions, so it shows either way."""
    name, address = operator
    if not name or not static_ready(FOUNDER_PHOTO):
        return ""
    words = FOUNDER_COPY[locale]
    links = (
        (f"{_e(address)} · " if address else "")
        + f"<a href='{FOUNDER_X_URL}' rel='noopener me'>{_e(words['x'])}</a>"
        f" · <a href='{CONTACT_PATHS[locale]}'>{_e(CONTACT_COPY[locale]['eyebrow'])}</a>"
        + (
            f" · <a href='{_e(contact_url)}' rel='noopener'>{_e(words['whatsapp'])}</a>"
            if contact_url
            else ""
        )
    )
    return (
        "<section class='section light' id='quien'><div class='wrap'>"
        "<div class='founder' data-reveal>"
        f"<img class='founder-photo' src='/static/{FOUNDER_PHOTO}' width='88' height='88' "
        f"alt='{_e(name)}'><div><h2>{_e(words['title'])}</h2>"
        f"<p>{_e(words['text'].format(name=name))}</p><p class='founder-links'>{links}</p>"
        "</div></div></div></section>"
    )


def _final_cta(
    copy: dict[str, Any], locale: str, sample: str, *, joined: bool, err: str = ""
) -> str:
    """The closing call. It keeps ``id='subir'`` so links shared as ``/#subir`` land here."""
    ui = _UI[locale]
    flash = (f"<div class='flash'>{_e(copy['joined'])}</div>" if joined else "") + err
    return (
        "<section class='section dark' id='subir' style='padding-top:0'><div class='wrap'>"
        "<div class='cta-band center' data-reveal style='max-width:900px'>"
        + _title_pair(ui["final_title"])
        + f"<p class='lead' style='margin-top:24px'>{_e(ui['final_lead'])}</p>"
        "<div class='hero-cta' style='justify-content:center'>"
        f"<a class='btn btn-primary btn-lg' href='{audit_path(locale)}'>{_e(ui['cta'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(sample)}'>{_e(ui['cta_sample'])}{icon('arrow')}</a></div>"
        f"<p class='final-tools'><a href='{_e(tools_url(locale))}'>"
        f"{_e(ui['final_tools'])}</a></p>"
        f"<div class='news center' id='news'><p class='label'>{_e(copy['waitlist_title'])}</p>"
        f"{flash}<form class='inline-form' method='post' action='/waitlist'>"
        f"<input type='email' name='email' required maxlength='254' autocomplete='email' "
        f"placeholder='{_e(copy['email'])}' "
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
    card_markets: Sequence[str] = (),
    email_confirmation: bool = False,
    completed_audits: int | None = None,
) -> str:
    """The public landing; the upload form lives on its own page (``upload_page``).

    It is short on purpose, for someone about to pay for a challenge or a robot: the
    first screen, the sample's finding, who it is for, how it works, the prices, who
    is behind it, six questions and the closing call. The institutional review and
    the free tools stay one link away (the footer and the closing call).

    ``extras_open``, ``signed_in`` and ``email_confirmation`` are accepted for old
    callers and not used here: the first screen no longer carries the confirmation
    note; the upload and account pages say when an address must be confirmed.
    ``operator`` (name, address): the name signs "who is behind it" (``_founder``);
    while that block is not shown, both stay in one line under the questions, and
    so does the WhatsApp link (``contact_url``)."""
    locale = _locale(locale)
    copy = _COPY[locale]
    title = copy.get("meta_title", copy["title"])
    meta = _public_meta(title, copy["meta_description"], locale, _home(locale), base_url)
    sample = _sample_url(locale)
    err = f"<div class='error' role='alert'>{_e(error)}</div>" if error else ""
    count_html = completed_count_html(completed_audits, locale)
    founder = _founder(locale, operator=operator, contact_url=contact_url)
    # ``home`` tightens the sections' spacing on this page only.
    body = (
        "<div class='home'>"
        + _hero(locale, sample, price_usd=price_usd, free_mode=free_mode)
        + ("<div class='wrap'>" + count_html + "</div>" if count_html else "")
        + _example_section(locale)
        + _audiences(locale)
        + _how_html(copy, locale)
        + _prices_html(
            copy,
            locale,
            free_mode=free_mode,
            price_usd=price_usd,
            access_codes=access_codes,
            card_payments=card_payments,
            contact_url=contact_url,
            pack_price_usd=pack_price_usd,
            card_markets=card_markets,
        )
        + founder
        # The operator's and WhatsApp lines move into "who is behind it" when it shows.
        + _faq_html(
            copy,
            locale,
            retention_days=retention_days,
            operator=("", "") if founder else operator,
            contact_url="" if founder else contact_url,
        )
        + _final_cta(copy, locale, sample, joined=joined, err=err)
        + "</div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=LANDING_PATHS)


def upload_page(
    *,
    locale: str = "es",
    free_mode: bool = True,
    price_usd: float = 0.0,
    access_codes: bool = False,
    retention_days: int = 30,
    base_url: str = "",
    extras_open: bool = False,
    signed_in: bool | None = None,
    notice: str = "",
    carried: Mapping[str, str] | None = None,
    rejection_html: str = "",
    notice_link_html: str = "",
) -> str:
    """The upload form on its own page, so the landing can stay short.

    ``signed_in=False`` in paid mode keeps the "account first" note above the fields
    (the web layer normally sends such a visitor to sign-up before this page).
    ``notice`` is one line above the fields, such as "confirmation link sent";
    ``notice_link_html`` is trusted, fixed markup after it (a link to the guides).
    ``carried`` restores only declaration fields after a refusal; file pickers and
    access codes remain empty. ``rejection_html`` is trusted, localized guidance.
    Client declarations are escaped form values, never report claims or logs."""
    locale = _locale(locale)
    copy = _COPY[locale]
    note = copy["free_note"] if free_mode else copy["paid_note"].format(price=price_usd)
    # A refusal answers a POST and is never a page of its own: it stays private
    # (noindex, nofollow) like error_page, while the empty form is public.
    meta = (
        ""
        if rejection_html
        else _public_meta(
            f"{copy['form_title']} · {BRAND}",
            copy["meta_description"],
            locale,
            audit_path(locale),
            base_url,
        )
    )
    # No page hero: the form section carries its own heading, right under a solid bar.
    body = _upload_form(
        copy,
        locale,
        note=note,
        flash=(
            f"<div class='flash'>{_e(notice)}"
            + (f" {notice_link_html}" if notice_link_html else "")
            + "</div>"
            if notice
            else ""
        ),
        err=rejection_html,
        access_codes=access_codes,
        retention_days=retention_days,
        extras_open=extras_open,
        signin_first=signed_in is False and not free_mode,
        carried=carried,
    )
    # The language switch keeps the extra boxes open.
    alternates = {
        lang: href + ("?extras=1" if extras_open else "") for lang, href in AUDIT_PATHS.items()
    }
    return _page(
        copy["form_title"], locale, body, meta_html=meta, solid_nav=True, alternates=alternates
    )


def _evidence_value(item: Any, locale: str = "es") -> str:
    """A figure and its evidence tag as HTML: "120" then the DECLARED badge."""
    if isinstance(item, dict) and "value" in item:
        value = item.get("value")
        shown = "—" if value is None else _e(f"{value:,}" if isinstance(value, int) else value)
        evidence = str(item.get("evidence", ""))
        tag = (
            f" {_badge(evidence, locale)}"
            if evidence in ("MEASURED", "DECLARED", "NOT_MEASURED")
            else ""
        )
        return f"<span class='vc'>{shown}{tag}</span>"
    return "—" if item is None else _e(str(item))


def _page_hero(
    eyebrow: str, title: str, lead: str = "", crumbs: str = "", *, dot: str = "", note: str = ""
) -> str:
    """A page's first screen; ``note`` is one more line of plain text under the lead."""
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
        # The landing's anchor style, aligned with the lead instead of centred.
        + (
            f"<p class='hero-anchor rise' style='--i:4;margin-left:0'>{_e(note)}</p>"
            if note
            else ""
        )
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
    if locale in ("es", "pt"):
        day = f"{when.day} {month} {when.year}"
    else:
        day = f"{month} {when.day}, {when.year}"
    return f"<time datetime='{_e(stamp)}'>{day} · {when:%H:%M} UTC</time>"


def _meaning_of(dimension: dict[str, Any], locale: str, kind: str = "backtest") -> str:
    """The fixed plain text of a dimension, in its undeclared-trials wording when
    the trial count was never declared: read from the dimension's inputs on a
    live result, or from the fact the kept public view stores in their place.

    ``kind`` (``report_kind``) picks the account or fund wording where one
    exists, as the private report does."""
    if "inputs" in dimension:
        undeclared = trials_undeclared(dimension.get("inputs"))
    else:
        undeclared = bool(dimension.get("undeclared"))
    return meaning(
        dimension["name"],
        dimension["status"],
        locale,
        account=kind == "account",
        fund=kind == "fund",
        undeclared=undeclared,
    )


def _data_period(result: dict[str, Any], locale: str) -> str:
    """HTML of the data period: first and last dates and the sampling frequency.

    Empty when the dates are missing (a public view kept before the page showed
    them); the frequency is left out when it is missing. No count is shown:
    the privacy policy and the terms list what this page shows and keeps
    (class, dimensions, hashes, dates, trials, engine), and the number of
    observations or of trades is not on that list."""
    inputs = result.get("inputs") or {}
    first, last = inputs.get("first_timestamp"), inputs.get("last_timestamp")
    if not first or not last:
        return ""
    words = [
        f"{_plain_date(str(first)[:10], locale)} → {_plain_date(str(last)[:10], locale)}",
        FREQUENCY_TEXT[locale].get(str(inputs.get("frequency_label")), ""),
    ]
    return " · ".join(_e(word) for word in words if word)


def _trials_used_value(item: Any, locale: str) -> str:
    """The trial count the deflated Sharpe used; an undeclared count (computed at
    1, the most favourable case) reads as a dash, its badge and why."""
    if isinstance(item, dict) and item.get("evidence") == "NOT_MEASURED":
        return (
            f"<span class='vc'>— {_badge('NOT_MEASURED', locale)}</span> "
            f"{_e(_COPY[locale]['v_trials_undeclared'])}"
        )
    return _evidence_value(item, locale)


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

    Built from an allow-list of fields: class, what was audited (a backtest,
    an account history or a fund's track record), the data period (first and
    last dates and frequency), the days between the last data point and the
    audit, dates, dimension statuses with their fixed plain-language text,
    input hashes, source format, engine, trial counts and a fixed notice. The
    description, trades (their list or their count), the number of
    observations, files and token are never read here, so they cannot leak. A
    view kept before the period was shown has no dates, and those rows are
    left out.
    """
    locale = _locale(locale)
    copy = _COPY[locale]
    ui = _UI[locale]
    verdict = result["verdict"]
    overall = str(verdict["overall"])
    # A backtest, an account history or a fund's track record: the class
    # sentence, the cards and the share text all name it the same way.
    kind = report_kind(result)
    titles = DIMENSION_TITLES.get(locale, DIMENSION_TITLES["es"])
    # The same cards as the report's "what it means for you", so a buyer
    # reads one dimension at a time on a phone.
    cards = "".join(
        f"<div class='item s-{_e(str(d['status']))}'>"
        f"<h3>{_e(titles.get(d['name'], d['name']))} {_status_chip(str(d['status']), locale)}</h3>"
        f"<p>{_e(_meaning_of(d, locale, kind))}</p></div>"
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
    # What was audited and over which dates come first: a reader needs them to
    # weigh the class. The days are calendar days from the last data point to
    # the audit date, measured from the two stored dates.
    facts = [(copy["v_kind"], _e(copy[f"v_kind_{kind}"]))]
    period = _data_period(result, locale)
    if period:
        facts.append((copy["v_period"], period))
    age = data_age_days(result)
    if age is not None:
        facts.append(
            (
                copy["v_age"],
                f"<span class='vc'>{_e(_num(age, locale, 0))} {_badge('MEASURED', locale)}</span>",
            )
        )
    details = [
        (
            copy["v_format"],
            source_name(inputs) or inputs.get("source") or "-",
        ),
        (copy["v_engine"], f"{engine.get('name', '')} {engine.get('package_version', '')}"),
    ]
    # Words read as words, figures carry their evidence badge, and only the
    # hash keeps the code style.
    detail_rows = (
        "".join(f"<tr><td>{_e(label)}</td><td>{value}</td></tr>" for label, value in facts)
        + "".join(f"<tr><td>{_e(label)}</td><td>{_e(value)}</td></tr>" for label, value in details)
        + f"<tr><td>{_e(copy['v_trials_declared'])}</td>"
        f"<td>{_evidence_value(declared.get('trials'), locale)}</td></tr>"
        f"<tr><td>{_e(copy['v_trials_used'])}</td>"
        f"<td>{_trials_used_value(trials_used, locale)}</td></tr>"
        + f"<tr><td>{_e(copy['v_result_sha'])}</td><td><code>{_e(result_sha256)}</code></td></tr>"
    )
    page_url = f"{base_url}/v/{public_id}"
    badge_url = f"{page_url}/badge.svg?lang={locale}"
    # The badge opens the page in the language it was made in (Spanish has no suffix).
    badge_link = page_url if locale == "es" else f"{page_url}?lang={locale}"
    snippet = (
        f"<a href='{badge_link}'><img src='{badge_url}' alt='{BADGE_NOTICE[locale]}' "
        "width='480' height='72'></a>"
    )
    cls_label = CLASS_WORD[locale]
    title = f"{copy['v_title']} · {cls_label} {overall}"
    audited = str(result.get("generated_at_utc", ""))
    description = copy["v_description"].format(
        cls_label=cls_label, overall=overall, date=audited[:10], notice=BADGE_NOTICE[locale]
    )
    alternates = {lang: f"/v/{public_id}?lang={lang}" for lang in CLASS_WORD}
    alternates["es"] = f"/v/{public_id}"
    # Never indexed (an unpublished page should not linger in search), but it
    # previews its class and date when the link is shared.
    meta = head_meta(
        PageMeta(
            title=title,
            description=description,
            locale=locale,
            paths=alternates,
            index=False,
            image_path=f"/v/{public_id}/card.png?lang={locale}",
            image_alt=f"{BRAND} · {cls_label} {overall}",
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
        f"<p class='verdict-text'>{_e(class_text(overall, locale, kind=kind))}</p>"
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
        "</button></div></section>"
        + share_block(
            overall=overall,
            public_id=public_id,
            locale=locale,
            kind=kind,
        )
        + "</div></div>"
    )
    return _page(
        title,
        locale,
        hero + main,
        meta_html=meta,
        alternates=alternates,
        solid_nav=True,
    )


def verification_card_svg(result: dict[str, Any], *, public_id: str, locale: str = "es") -> str:
    """A share image using a subset of the verification page's allow-list.

    Only the class, the kind of upload (backtest, account history or fund's
    track record), the data period's first and last dates, the audit date and
    the public id are read. The kind picks the class sentence drawn on the
    card, so an account is never called a backtest; the kind and the period
    go only in ``<desc>``. All other words are fixed page copy: no client
    prose, figures, trades, files or private ids. The same fields survive a
    published audit's retention purge.
    """
    locale = _locale(locale)
    copy = _COPY[locale]
    overall = str(result["verdict"]["overall"])
    kind = report_kind(result)
    audited = str(result.get("generated_at_utc", ""))[:10]
    label = f"{CLASS_WORD[locale]} {overall}"
    title = f"{BRAND} · {label}"
    notice = BADGE_NOTICE[locale]
    inputs = result.get("inputs") or {}
    first = str(inputs.get("first_timestamp") or "")[:10]
    last = str(inputs.get("last_timestamp") or "")[:10]
    period = f"{copy['v_period']}: {first} → {last}. " if first and last else ""
    description = (
        f"{copy['v_kind']}: {copy[f'v_kind_{kind}']}. {period}"
        f"{copy['v_audited']}: {audited}. ID {public_id}. {notice}"
    )
    colour = CLASS_COLOURS.get(overall, "#a3a3aa")
    width, height = OG_IMAGE_SIZE
    font = "Inter,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
    sentence = "".join(
        f"<tspan x='350' y='{260 + index * 38}'>{_e(line)}</tspan>"
        for index, line in enumerate(
            textwrap.wrap(class_text(overall, locale, kind=kind), width=47)
        )
    )
    footer = "".join(
        f"<tspan x='56' y='{548 + index * 28}'>{_e(line)}</tspan>"
        for index, line in enumerate(textwrap.wrap(notice, width=100))
    )
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img' "
        f"aria-labelledby='verification-card-title verification-card-desc' lang='{locale}'>"
        f"<title id='verification-card-title'>{_e(title)}</title>"
        f"<desc id='verification-card-desc'>{_e(description)}</desc>"
        f"<rect width='{width}' height='{height}' fill='#0b0b0d'/>"
        f"<g font-family='{font}'>"
        f"<text x='56' y='87' font-size='48' font-weight='650' fill='#f4f4f6'>{BRAND}</text>"
        f"<text x='56' y='132' font-size='26' fill='#a3a3aa'>{_e(copy['v_title'])}</text>"
        f"<rect x='56' y='186' width='240' height='228' rx='28' "
        f"fill='#141416' stroke='{colour}' stroke-width='3'/>"
        f"<text x='176' y='355' text-anchor='middle' font-size='166' font-weight='600' "
        f"fill='{colour}'>{_e(overall)}</text>"
        f"<text x='350' y='207' font-size='26' font-weight='650' "
        f"fill='{colour}'>{_e(label)}</text>"
        f"<text font-size='28' fill='#f4f4f6'>{sentence}</text>"
        f"<text x='56' y='466' font-size='21' fill='#a3a3aa'>"
        f"{_e(copy['v_audited'])}: {_e(audited)} · ID {_e(public_id)}</text>"
        "<path d='M56 506H1144' stroke='#2a2a2f'/>"
        f"<text font-size='19' fill='#a3a3aa'>{footer}</text>"
        "</g></svg>"
    )


def badge_svg(*, overall: str, public_id: str, audited_on: str, locale: str = "es") -> str:
    """The badge: class, id, date and the fixed notice. Never a return figure."""
    locale = locale if locale in BADGE_NOTICE else "es"
    title = BRAND
    label = CLASS_WORD[locale]
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


#: A short description of its own (under 160 characters) for the pages that
#: used their title or the whole notice as description.
PAGE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "terms": {
        "es": (
            "Términos del servicio de Rigor: qué es el servicio, qué no es, tus archivos, "
            "precio y pago, y ley aplicable."
        ),
        "en": (
            "Rigor terms of service: what the service is, what it is not, your files, "
            "price and payment, and governing law."
        ),
        "pt": (
            "Termos do serviço do Rigor: o que é o serviço, o que ele não é, seus arquivos, "
            "preço e pagamento, e lei aplicável."
        ),
    },
    "privacy": {
        "es": (
            "Política de privacidad de Rigor: qué guardamos, qué no guardamos, para qué, "
            "cuánto tiempo y cuáles son tus derechos."
        ),
        "en": (
            "Rigor privacy policy: what we keep, what we do not keep, what it is used for, "
            "for how long and what your rights are."
        ),
        "pt": (
            "Política de privacidade do Rigor: o que guardamos, o que não guardamos, para quê, "
            "por quanto tempo e quais são seus direitos."
        ),
    },
    "compare": {
        "es": "Compara dos de tus informes de Rigor, lado a lado, para ver qué cambió.",
        "en": "Compare two of your Rigor reports, side by side, to see what changed.",
        "pt": "Compare dois dos seus relatórios do Rigor, lado a lado, para ver o que mudou.",
    },
    "signup": {
        "es": "Crea tu cuenta de Rigor para subir tus archivos y guardar tus informes.",
        "en": "Create your Rigor account to upload your files and keep your reports.",
        "pt": "Crie sua conta no Rigor para enviar seus arquivos e guardar seus relatórios.",
    },
    "signin": {
        "es": "Entra a tu cuenta de Rigor para ver tus informes, créditos y compras.",
        "en": "Sign in to your Rigor account to see your reports, credits and purchases.",
        "pt": "Entre na sua conta do Rigor para ver seus relatórios, créditos e compras.",
    },
    "forgot": {
        "es": "Recupera el acceso a tu cuenta de Rigor y pon una contraseña nueva.",
        "en": "Get back into your Rigor account and set a new password.",
        "pt": "Recupere o acesso à sua conta do Rigor e crie uma nova senha.",
    },
}


def legal_page(
    text: LegalText, *, locale: str = "es", kind: str = "terms", base_url: str = ""
) -> str:
    """The terms or the privacy policy as one page, with a language switch."""
    locale = _locale(locale)
    copy = _COPY[locale]
    ui = _UI[locale]
    path = legal_url(kind, locale).split("?", 1)[0]
    description = PAGE_DESCRIPTIONS.get(kind, {}).get(locale) or (
        f"{text.title} · {copy['title']}. {_disclaimer(locale)}"
    )
    title = f"{text.title} · {BRAND}"
    meta = _public_meta(title, description, locale, path, base_url)
    warning = f"<div class='error'>{_e(text.warning)}</div>" if text.warning else ""
    sections = [
        (heading, "".join(f"<p>{_e(line)}</p>" for line in lines))
        for heading, lines in text.sections
    ]
    alternates = {lang: legal_url(kind, lang) for lang in ("es", "en", "pt")}
    languages = " · ".join(
        f"<a href='{_e(url)}' hreflang='{lang}'>{_e(LANGUAGE_NAMES[lang])}</a>"
        for lang, url in alternates.items()
        if lang != locale
    )
    crumbs = f"<a href='{_home(locale)}'>{_e(copy['back'])}</a><span>/</span>{languages}"
    body = (
        _page_hero(ui["legal_eyebrow"], text.title, crumbs=crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(sections, locale, lead=warning)
        + f"<p class='muted doc-foot'>{_e(copy['legal_updated'])}: {_e(text.updated)}</p>"
        "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=alternates, solid_nav=True)


#: The contact page in each language; /soporte, /support and /pt/suporte lead here.
CONTACT_PATHS: dict[str, str] = {"es": "/contacto", "en": "/en/contact", "pt": "/pt/contato"}

CONTACT_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Contacto",
        "title": "Habla con una persona",
        "lead": (
            "Dudas sobre un informe, tu cuenta o un pago: escríbenos y te respondemos por el "
            "mismo medio."
        ),
        "email": "Correo",
        "email_text": "Para dudas sobre informes, cuentas, pagos y borrado de datos.",
        "chat": "WhatsApp",
        "chat_text": "Para una pregunta corta.",
        "open": "Escribir",
        "none": "El operador todavía no ha publicado un medio de contacto.",
        "before_title": "Antes de escribir",
        "before": (
            "Si es sobre un informe, incluye su identificador (está en la dirección del informe).",
            "Nunca envíes tu contraseña, tu clave de recuperación ni los datos de tu tarjeta: "
            "nadie de Rigor te los va a pedir.",
            "Para borrar tus datos o tu cuenta, lo puedes hacer tú desde Mi cuenta; la política "
            "de privacidad explica qué se guarda.",
        ),
        "links_title": "Quizá ya está respondido",
        "faq": "Preguntas frecuentes",
        "guides": "Guías para exportar tu archivo",
        "account": "Mi cuenta",
        "privacy": "Política de privacidad",
    },
    "en": {
        "eyebrow": "Contact",
        "title": "Talk to a person",
        "lead": (
            "Questions about a report, your account or a payment: write to us and we reply "
            "the same way."
        ),
        "email": "E-mail",
        "email_text": "For questions about reports, accounts, payments and data deletion.",
        "chat": "WhatsApp",
        "chat_text": "For a short question.",
        "open": "Write",
        "none": "The operator has not published a contact channel yet.",
        "before_title": "Before you write",
        "before": (
            "If it is about a report, include its id (it is in the report's address).",
            "Never send your password, your recovery key or your card details: nobody from "
            "Rigor will ask for them.",
            "You can delete your data or your account yourself from My account; the privacy "
            "policy explains what is kept.",
        ),
        "links_title": "It may already be answered",
        "faq": "Frequent questions",
        "guides": "Guides to export your file",
        "account": "My account",
        "privacy": "Privacy policy",
    },
    "pt": {
        "eyebrow": "Contato",
        "title": "Fale com uma pessoa",
        "lead": (
            "Dúvidas sobre um relatório, a sua conta ou um pagamento: escreva para nós e "
            "respondemos pelo mesmo meio."
        ),
        "email": "E-mail",
        "email_text": "Para dúvidas sobre relatórios, contas, pagamentos e exclusão de dados.",
        "chat": "WhatsApp",
        "chat_text": "Para uma pergunta curta.",
        "open": "Escrever",
        "none": "O operador ainda não publicou um meio de contato.",
        "before_title": "Antes de escrever",
        "before": (
            "Se for sobre um relatório, inclua o identificador dele (está no endereço do "
            "relatório).",
            "Nunca envie a sua senha, a sua chave de recuperação nem os dados do seu cartão: "
            "ninguém da Rigor vai pedi-los.",
            "Você mesmo pode excluir os seus dados ou a sua conta em Minha conta; a política de "
            "privacidade explica o que é guardado.",
        ),
        "links_title": "Talvez já esteja respondido",
        "faq": "Perguntas frequentes",
        "guides": "Guias para exportar o seu arquivo",
        "account": "Minha conta",
        "privacy": "Política de privacidade",
    },
}


#: The heading of the contact cards, for screen readers.
_CONTACT_CHANNELS = {
    "es": "Cómo escribirnos",
    "en": "How to write to us",
    "pt": "Como escrever para nós",
}


def institutional_review_page(
    *,
    locale: str = "es",
    base_url: str = "",
    ref: str = "",
    received: bool = False,
    error: str = "",
) -> str:
    """Only static confirmation/error copy is returned; client fields are never echoed."""
    words = institutional.COPY[locale]
    title = words["received"] if received else words["title"]
    lead = words["next"] if received else words["lead"]
    # The tab and the search result carry the brand; the heading stays as written.
    page_title = f"{title} · {BRAND}"
    meta = (
        private_meta(page_title, locale, lead)
        if received or error
        else _public_meta(page_title, lead, locale, institutional.REVIEW_PATHS[locale], base_url)
    )
    content = (
        f"<p><a href='{_home(locale)}'>{_e(words['back'])}</a></p>"
        if received
        else (f"<p class='error' role='alert'>{_e(words[error])}</p>" if error else "")
        + f"<p>{_e(words['note'])}</p>"
        + institutional.form_html(locale, ref=ref)
        + f"<p><a href='{legal_url('privacy', locale)}'>{_e(words['privacy'])}</a></p>"
    )
    body = (
        _page_hero(words["title"], title, lead)
        + "<div class='paper page-main'><div class='wrap wrap-mid'>"
        + content
        + "</div></div>"
    )
    return _page(
        page_title,
        locale,
        body,
        meta_html=meta,
        alternates=institutional.REVIEW_PATHS,
        solid_nav=True,
    )


def contact_page(
    *, locale: str = "es", email: str = "", contact_url: str = "", base_url: str = ""
) -> str:
    """Who to write to: the operator's e-mail and chat link, both from the environment.

    Nothing is shown that the operator did not configure: no default address exists."""
    locale = _locale(locale)
    words = CONTACT_COPY[locale]
    path = CONTACT_PATHS[locale]
    page_title = f"{words['title']} · {BRAND}"
    meta = _public_meta(page_title, words["lead"], locale, path, base_url)
    cards = []
    if "@" in email and " " not in email:
        cards.append(("chat", words["email"], words["email_text"], f"mailto:{email}", email))
    if contact_url:
        cards.append(("chat", words["chat"], words["chat_text"], contact_url, words["open"]))
    channels = (
        # Read aloud only: the cards' titles are one level below it.
        f"<h2 class='sr-only'>{_e(_CONTACT_CHANNELS[locale])}</h2>"
        "<div class='cards cards-2'>"
        + "".join(
            f"<div class='card spot'><div class='icon'>{icon(name)}</div><h3>{_e(title)}</h3>"
            f"<p>{_e(text)}</p><p><a class='btn btn-dark btn-sm' href='{_e(href)}' rel='noopener'>"
            f"{_e(label)}</a></p></div>"
            for name, title, text, href, label in cards
        )
        + "</div>"
        if cards
        else f"<p class='muted'>{_e(words['none'])}</p>"
    )
    before = "".join(
        f"<li>{icon('shield')}<span>{_e(line)}</span></li>" for line in words["before"]
    )
    links = " · ".join(
        f"<a href='{_e(href)}'>{_e(label)}</a>"
        for href, label in (
            (f"{_home(locale)}#faq", words["faq"]),
            (guides_index_url(locale), words["guides"]),
            (_ACCOUNT_PATHS[locale][2], words["account"]),
            (legal_url("privacy", locale), words["privacy"]),
        )
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["lead"])
        + "<div class='paper page-main'><div class='wrap wrap-mid'>"
        + channels
        + f"<h2 class='label' style='margin-top:36px'>{_e(words['before_title'])}</h2>"
        + f"<ul class='checks'>{before}</ul>"
        + f"<h2 class='label' style='margin-top:28px'>{_e(words['links_title'])}</h2>"
        + f"<p>{links}</p></div></div>"
    )
    return _page(page_title, locale, body, meta_html=meta, alternates=CONTACT_PATHS, solid_nav=True)


def compare_page(
    content: str,
    *,
    locale: str = "es",
    lead: str = "",
    alternates: dict[str, str] | None = None,
) -> str:
    """The private page that compares two reports (``audit/compare.py`` builds ``content``)."""
    from quant_trade.audit.compare import COMPARE_CSS, COMPARE_PATH, COPY

    locale = _locale(locale)
    copy = COPY[locale]
    body = (
        _page_hero(copy["eyebrow"], copy["title"], lead or copy["lead"])
        + f"<div class='paper page-main'><div class='wrap'><style>{COMPARE_CSS}</style>"
        + content
        + "</div></div>"
    )
    # A comparison reached from Mi cuenta passes its own addresses.
    return _page(
        copy["title"],
        locale,
        body,
        meta_html=private_meta(copy["title"], locale, PAGE_DESCRIPTIONS["compare"][locale]),
        alternates=alternates or dict(COMPARE_PATH),
        solid_nav=True,
    )


def check_page(content: str, *, locale: str = "es", base_url: str = "") -> str:
    """The page that checks a report file (``audit/check.py`` builds ``content``)."""
    from quant_trade.audit.check import CHECK_CSS, CHECK_PATH, COPY, check_path

    locale = _locale(locale)
    copy = COPY[locale]
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
        alternates=dict(CHECK_PATH),
        solid_nav=True,
    )


_ERROR_TITLES = {
    "es": {"page": "Página no encontrada", "server": "Algo falló"},
    "en": {"page": "Page not found", "server": "Something went wrong"},
    "pt": {"page": "Página não encontrada", "server": "Algo falhou"},
}


#: Where an importer's message starts listing the formats it reads.
_EXPECTED_MARKERS = ("Se espera:", "Expected:", "Esperado:")
#: "...: sube la optimización del mismo robot" reads as the fix, so it gets its own line.
_ACTION = re.compile(
    r"[:;]\s+(?=(?:sube|vuelve|exp[oó]rta\w*|revisa|pide|upload|export|check|ask|re-export"
    r"|optimi[sz]e|envie|exporte\w*|confira|informe|baixe|salve|otimize)\b)",
    re.I,
)
_ACTION_LABEL = {"es": "Qué hacer:", "en": "What to do:", "pt": "O que fazer:"}


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
    title = _ERROR_TITLES[locale].get(kind, copy["error_title"])
    back = audit_path(locale) if kind == "audit" else _home(locale)
    # The bar offers the other two languages, so the page needs no third button.
    body = (
        _page_hero(ui["error_eyebrow"], title, dot="warn")
        + "<div class='paper page-main'><div class='wrap wrap-narrow'>"
        f"{_error_card(message, locale)}<div class='back-row'>"
        f"<a class='btn btn-dark' href='{_e(back)}'>{_e(copy['back'])}</a>"
        f"<a class='btn btn-ghost' href='{_e(guides_index_url(locale))}'>"
        f"{_e(GUIDES_COPY[locale]['title'])}</a></div></div></div>"
    )
    return _page(title, locale, body, alternates=LANDING_PATHS, solid_nav=True)


def method_page(*, locale: str = "es", base_url: str = "") -> str:
    """The public methodology: tests, thresholds, labels, limits and sources."""
    locale = _locale(locale)
    copy = _COPY[locale]
    words: dict[str, Any] = METHOD_COPY[locale]
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
        f"<li>{_badge(tag, locale)}<span>{_e(text)}</span></li>" for tag, text in words["evidence"]
    )
    flags = "".join(
        f"<li>{_e(titles.get(locale, titles['en']))}</li>" for titles in FLAG_TITLES.values()
    )
    refs = "".join(f"<li>{_e(ref)}</li>" for ref in references(locale))
    alternates = {lang: method_url(lang) for lang in METHOD_COPY}
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(GUIDES_COPY[locale]['back'])}</a>" + (
        _language_crumbs(alternates, locale)
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
                (words["resampling_title"], bullets(words["resampling"])),
                (words["repro_title"], bullets(words["repro"])),
                (words["limits_title"], bullets(words["limits"], "minus")),
                (words["refs_title"], f"<ol class='refs'>{refs}</ol>"),
                (words["data_title"], bullets(words["data"])),
            ],
            locale,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(_form_url(locale))}'>"
            f"{_e(GUIDES_COPY[locale]['form'])}<span class='go'>{icon('arrow')}</span></a>",
        )
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=alternates, solid_nav=True)


def _calculator_result(
    words: dict[str, Any], locale: str, parsed: CalculatorInput | str | None
) -> str:
    """The result block for the submitted numbers, an error, or nothing."""
    if parsed is None:
        return ""
    if isinstance(parsed, str):
        return f"<p class='error' role='alert'>{_e(words[parsed])}</p>"
    result = compute(parsed)
    if result["status"] != "MEASURED":
        reason = CALCULATOR_REASONS[locale].get(result["reason"], result["reason"])
        return (
            f"<p class='error' role='alert'>{_e(words['not_measured'].format(reason=reason))}</p>"
        )
    # The card's own figures and typography: a decimal comma in es and pt, a point in en.
    count = count_text(parsed.trials, locale)
    note = f"<p class='help'>{_badge('DECLARED', locale)} {_e(words['declared_note'])}</p>"
    if not result["counted"]:
        rows = "".join(
            "<tr>"
            + "".join(f"<td>{_e(cell)}</td>" for cell in what_if_figures(row, locale))
            + "</tr>"
            for row in result["what_if"]
        )
        return (
            f"<p>{_e(words['one_trial'])}</p><table><thead><tr>"
            f"<th>{_e(words['col_trials'])}</th><th>{_e(words['col_luck'])}</th>"
            f"<th>{_e(words['col_years'])}</th></tr></thead><tbody>{rows}</tbody></table>" + note
        )
    verdict = words["beats" if result["beats_luck"] else "loses"].format(n=count)
    shown = result_figures(result, locale)
    figures = (
        (words["luck"].format(n=count), shown["luck_sharpe"]),
        (words["after"], shown["sharpe_after"]),
        (words["haircut"], shown["haircut"]),
        (words["years_needed"], shown["years_needed"]),
    )
    table = "".join(
        f"<tr><th scope='row'>{_e(label)}</th><td><b>{_e(value)}</b></td></tr>"
        for label, value in figures
    )
    css = "flash" if result["beats_luck"] else "warning"
    return (
        f"<p class='{css}' data-calc-verdict>{_e(verdict)}</p>"
        f"<table class='calc-result'><tbody>{table}</tbody></table>" + note
    )


def reading_page(
    *,
    locale: str = "es",
    base_url: str = "",
    values: Mapping[str, str] | None = None,
    svg: str = "",
    error: str = "",
    image_path: str = "",
    png_enabled: bool = False,
) -> str:
    """A GET form and the existing public SVG, using only validated inputs."""
    from quant_trade.audit.owner_card import COPY as INPUT_COPY
    from quant_trade.audit.public_card import COPY as CARD_COPY
    from quant_trade.audit.sharing import COPY as SHARE_COPY

    words, card, share = reading.COPY[locale], CARD_COPY[locale], SHARE_COPY[locale]
    values = values or {}
    body = ""
    if error:
        message = words["limited"] if error == "limited" else INPUT_COPY[locale][error]
        body += f"<p class='error' role='alert'>{_e(message)}</p>"
    see_also = (
        f"<p>{_e(words['see_also'])} "
        f"<a href='{_e(calculator_url(locale))}'>{_e(CALCULATOR_COPY[locale]['nav'])}</a> · "
        f"{_article_link('cuantas-operaciones-porcentaje-aciertos', locale)} · "
        f"<a href='{_e(tools_url(locale))}'>{_e(TOOLS_COPY[locale]['nav'])}</a></p>"
    )
    body += (
        f"<p>{_e(words['note'])}</p><p>{_e(words['optional'])}</p>"
        f"<p>{_e(words['public'])}</p>{see_also}"
        f"<form method='get' action='{reading.reading_url(locale)}' class='calc-form'>"
        "<div class='form-grid'>"
    )
    for name in reading.FIELDS:
        if name in ("trades", "trials"):
            low, high, step = "1", "10000000", "1"
        elif name == "win_rate":
            low, high, step = "0", "100", "any"
        elif name == "sharpe":
            low, high, step = "-1000000", "1000000", "any"
        else:
            low, high, step = "0", "1000000", "any"
        label = INPUT_COPY[locale]["rate"] if name == "win_rate" else card[name]
        body += (
            f"<div class='field'><label for='reading-{name}'>{_e(label)} · DECLARED</label>"
            f"<input id='reading-{name}' name='{name}' type='number' min='{low}' max='{high}' "
            f"step='{step}' value='{_e(values.get(name, ''))}' autocomplete='off'></div>"
        )
    body += (
        f"</div><button class='btn btn-dark' type='submit'>{_e(words['submit'])}</button></form>"
    )
    if svg:
        url = reading.reading_url(locale, values)
        absolute_url = base_url.rstrip("/") + url
        text = words["share_text"].format(url=absolute_url)
        intent = "https://x.com/intent/post?" + urlencode({"text": text})
        png_link = ""
        if png_enabled:
            png_url = reading.READING_PATH[locale] + "/card.png?" + url.partition("?")[2]
            png_link = (
                f" <a class='btn btn-ghost' href='{_e(png_url)}' download>"
                f"{_e(words['download_png'])}</a>"
            )
        body += (
            f"<section><h2>{_e(words['result'])}</h2>"
            f"<div class='public-card-preview'>{svg}</div>"
            f"<p><a class='btn btn-ghost' href='{_e(url + '&download=svg')}' download>"
            f"{_e(words['download'])}</a>{png_link}</p></section>"
            f"<section data-public-share><h2>{_e(share['title'])}</h2>"
            "<textarea id='reading-share-link' readonly hidden rows='3' style='width:100%' "
            f"aria-label='{_e(words['copy_link'])}'>{_e(absolute_url)}</textarea>"
            f"<label for='reading-share-text'>{_e(share['copy'])}</label>"
            "<textarea id='reading-share-text' readonly rows='5' style='width:100%'>"
            f"{_e(text)}</textarea><div class='copy-row'>"
            "<button class='btn btn-ghost' type='button' data-copy='reading-share-link' "
            f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
            f"{_e(words['copy_link'])}</button>"
            "<button class='btn btn-dark' type='button' data-copy='reading-share-text' "
            f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
            f"{_e(share['copy'])}</button><a class='btn btn-ghost' href='{_e(intent)}' "
            f"rel='noopener noreferrer'>{_e(share['post'])}</a></div>"
            "<p class='muted' data-copy-status role='status' aria-live='polite'></p></section>"
        )
    # With or without a card: what only the file can show, and the way to it.
    body += (
        f"<section class='article-cta'><h2>{_e(words['beyond_title'])}</h2>"
        f"<p>{_e(words['beyond'])}</p><div class='back-row'>"
        f"<a class='btn btn-dark' href='{_e(audit_path(locale))}'>{_e(words['beyond_button'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(_sample_url(locale))}'>{_e(words['sample_link'])}"
        f"{icon('arrow')}</a>"
        f"<a class='link-more' href='{_e(guides_index_url(locale))}'>{_e(words['guides_link'])}"
        f"{icon('arrow')}</a></div></section>"
    )
    alternates = {
        lang: reading.reading_url(lang, values if svg else None) for lang in reading.READING_PATH
    }
    title = f"{words['title']} · Rigor"
    meta = head_meta(
        PageMeta(
            title=title,
            description=words["summary"],
            locale=locale,
            paths=reading.READING_PATH,
            image_path=image_path,
            image_alt=title,
        ),
        base_url=base_url,
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["summary"])
        + f"<div class='paper page-main'><div class='wrap'>{body}</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=alternates, solid_nav=True)


def _calculator_share(
    words: dict[str, Any], locale: str, value: CalculatorInput, base_url: str, image_path: str
) -> str:
    """Share buttons whose link reproduces exactly the validated inputs, tagged
    ``ref=calculadora``; the PNG link only when the card rendered."""
    share = SHARING_COPY[locale]
    url = base_url.rstrip("/") + share_url(locale, value)
    text = words["share_text"].format(url=url)
    intent = "https://x.com/intent/post?" + urlencode({"text": text})
    whatsapp = "https://wa.me/?text=" + quote(text, safe="")
    telegram = (
        "https://t.me/share/url?url="
        + quote(url, safe="")
        + "&text="
        + quote(text.removesuffix(url).rstrip(), safe="")
    )
    links = "".join(
        f"<a class='btn btn-ghost btn-sm' href='{_e(href)}' target='_blank' "
        f"rel='noopener noreferrer'>{_e(share[label])}</a>"
        for href, label in ((intent, "post"), (whatsapp, "whatsapp"), (telegram, "telegram"))
    )
    png = (
        f"<p><a class='btn btn-ghost btn-sm' href='{_e(image_path)}' download>"
        f"{_e(reading.COPY[locale]['download_png'])}</a></p>"
        if image_path
        else ""
    )
    return (
        "<div data-public-share>"
        f"<p class='help'>{_e(words['card_public'])}</p>"
        f"<label for='calculator-share-text'>{_e(share['copy'])}</label>"
        "<textarea id='calculator-share-text' readonly rows='4' style='width:100%'>"
        f"{_e(text)}</textarea><div class='copy-row'>"
        "<button class='btn btn-dark btn-sm' type='button' data-copy='calculator-share-text' "
        f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
        f"{_e(share['copy'])}</button>{links}</div>"
        "<p class='muted' data-copy-status role='status' aria-live='polite'></p>"
        f"{png}</div>"
    )


def calculator_page(
    *,
    locale: str = "es",
    base_url: str = "",
    sharpe: str | None = None,
    years: str | None = None,
    trials: str | None = None,
    periods_per_year: str | None = "252",
    image_path: str = "",
) -> str:
    """The free luck calculator: declared figures and frequency, the luck section's result.

    ``image_path`` is the result's own share card, set by the web layer only
    when the card rendered; empty keeps the site's static preview.
    """
    locale = _locale(locale)
    try:
        frequency = float(periods_per_year) if periods_per_year is not None else 252.0
    except (TypeError, ValueError):
        frequency = 252.0
    if frequency not in (252, 52, 12):
        frequency = 252.0
    words = calculator_copy(locale, frequency)
    title = f"{words['title']} · {BRAND}"
    meta = head_meta(
        PageMeta(
            title=title,
            description=words["summary"],
            locale=locale,
            paths=dict(CALCULATOR_PATH),
            image_path=image_path,
            image_alt=title,
        ),
        base_url=base_url,
    )

    def field(name: str, value: str | None, step: str) -> str:
        shown = f" value='{_e(value)}'" if value else ""
        return (
            f"<div class='field'><label for='c-{name}'>{_e(words[name])}</label>"
            f"<input type='number' id='c-{name}' name='{name}' min='0' step='{step}' "
            f"inputmode='decimal' required{shown}>"
            f"<p class='help'>{_e(words[name + '_help'])}</p></div>"
        )

    options = "".join(
        f"<option value='{periods}'{' selected' if periods == frequency else ''}>"
        f"{_e(label)}</option>"
        for periods, label in words["frequency_options"].items()
    )
    frequency_field = (
        f"<div class='field'><label for='c-periods_per_year'>{_e(words['frequency'])} "
        f"{_badge('DECLARED', locale)}</label>"
        f"<select id='c-periods_per_year' name='periods_per_year'>{options}</select>"
        f"<p class='help'>{_e(words['frequency_help'])}</p></div>"
    )
    form = (
        f"<form method='get' action='{_e(calculator_url(locale))}' class='calc-form'>"
        "<div class='form-grid'>"
        + field("sharpe", sharpe, "0.01")
        + field("years", years, "any")
        + field("trials", trials, "1")
        + frequency_field
        + f"</div><button class='btn btn-dark' type='submit'>{_e(words['submit'])}</button></form>"
    )
    parsed = read_input(sharpe, years, trials, periods_per_year)
    result = _calculator_result(words, locale, parsed)
    # Sharing only for a measured result: an empty form or an error has nothing to show.
    share = ""
    if isinstance(parsed, CalculatorInput) and compute(parsed)["status"] == "MEASURED":
        share = _calculator_share(words, locale, parsed, base_url, image_path)
    cta = (
        f"<p>{_e(words['cta'])}</p><p><a class='btn btn-dark' href='{_e(_form_url(locale))}'>"
        f"{_e(words['cta_button'])}<span class='go'>{icon('arrow')}</span></a> "
        f"<a href='{_e(_sample_url(locale))}'>{_e(words['sample_link'])}</a></p>"
        f"<p>{_e(words['read_more'])} "
        f"{_article_link('sharpe-deflactado-track-record', locale)} · "
        f"<a href='{_e(reading.reading_url(locale))}'>{_e(words['reader_link'])}</a></p>"
    )

    def bullets(items: list[str], mark: str = "check") -> str:
        return (
            f"<ul class='checks{'' if mark == 'check' else ' nots'}'>"
            + "".join(f"<li>{icon(mark)}<span>{_e(item)}</span></li>" for item in items)
            + "</ul>"
        )

    sections = [(words["form_title"], form)]
    if result:
        sections.append((words["result_title"], result))
    if share:
        sections.append((words["share_title"], share))
    sections += [
        (words["cta_title"], cta),
        (words["why_title"], bullets(words["why"])),
        (words["assumptions_title"], bullets(words["assumptions"], "minus")),
    ]
    alternates = {lang: calculator_url(lang) for lang in CALCULATOR_COPY}
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(GUIDES_COPY[locale]['back'])}</a>" + (
        _language_crumbs(alternates, locale)
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["summary"], crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            sections,
            locale,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(_form_url(locale))}'>"
            f"{_e(GUIDES_COPY[locale]['form'])}<span class='go'>{icon('arrow')}</span></a>",
        )
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=alternates, solid_nav=True)


def _winrate_result(
    claim: PublicClaim, values: Mapping[str, str], locale: str, base_url: str
) -> tuple[str, winrate.WinRateReading]:
    """The result for validated inputs: figures, comparisons, sharing and the reader's card."""
    from quant_trade.audit.public_card import COPY as CARD_COPY
    from quant_trade.audit.sharing import COPY as SHARE_COPY

    words, card, share = winrate.COPY[locale], CARD_COPY[locale], SHARE_COPY[locale]
    figures = winrate.read(claim)
    computed = f"{_badge('DECLARED', locale)} <span class='muted'>{_e(card['computed'])}</span>"
    missing = _badge("NOT_MEASURED", locale)
    if figures.interval is not None and claim.win_rate is not None and claim.trades is not None:
        interval = (
            f"<b>{_e(win_rate_interval(claim.win_rate, claim.trades, locale))}</b> {computed}"
        )
    else:
        interval = f"{missing} <span class='muted'>{_e(card['wilson_missing'])}</span>"
    if figures.breakeven is not None:
        breakeven = f"<b>{_e(_num(figures.breakeven * 100, locale, 1))} %</b> {computed}"
    else:
        breakeven = f"{missing} <span class='muted'>{_e(card['breakeven_missing'])}</span>"
    body = (
        "<table class='calc-result'><tbody>"
        f"<tr><th scope='row'>{_e(words['interval'])}</th><td>{interval}</td></tr>"
        f"<tr><th scope='row'>{_e(words['breakeven'])}</th><td>{breakeven}</td></tr>"
        "</tbody></table>"
    )
    if figures.position is not None:
        css = {"above": "flash", "below": "warning", "inside": "help"}[figures.position]
        body += f"<p class='{css}' data-winrate-position>{_e(words[figures.position])}</p>"
    # When the declared sample already clears break-even, a grid size above it (or none)
    # would read as "not yet": the position sentence already says it, so skip "needed".
    cleared_early = (
        figures.position == "above"
        and claim.trades is not None
        and (figures.trades_needed is None or figures.trades_needed > claim.trades)
    )
    if claim.win_rate is not None and figures.breakeven is not None and not cleared_early:
        if figures.never:
            needed = words["needed_never"]
        elif figures.trades_needed is None:
            needed = words["needed_none"]
        else:
            needed = words["needed"].format(
                rate=f"{_num(claim.win_rate * 100, locale, 1)} %",
                n=_num(figures.trades_needed, locale, 0),
            )
        body += f"<p data-winrate-needed>{_e(needed)}</p>"
    body += f"<p class='help'>{_badge('DECLARED', locale)} {_e(words['declared_note'])}</p>"
    if figures.position is not None:
        # The share text names the interval and the break-even: offer it only when both
        # were computed. Partial inputs keep the reader's card link below.
        absolute_url = base_url.rstrip("/") + winrate.share_url(locale, values)
        text = words["share_text"].format(url=absolute_url)
        intent = "https://x.com/intent/post?" + urlencode({"text": text})
        copy_link = reading.COPY[locale]["copy_link"]
        body += (
            f"<section data-public-share><h3>{_e(words['share_title'])}</h3>"
            "<textarea id='winrate-share-link' readonly hidden rows='3' style='width:100%' "
            f"aria-label='{_e(copy_link)}'>{_e(absolute_url)}</textarea>"
            f"<label for='winrate-share-text'>{_e(share['copy'])}</label>"
            "<textarea id='winrate-share-text' readonly rows='5' style='width:100%'>"
            f"{_e(text)}</textarea><div class='copy-row'>"
            "<button class='btn btn-ghost' type='button' data-copy='winrate-share-link' "
            f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
            f"{_e(copy_link)}</button>"
            "<button class='btn btn-dark' type='button' data-copy='winrate-share-text' "
            f"data-done='{_e(share['done'])}' data-fallback='{_e(share['fallback'])}' hidden>"
            f"{_e(share['copy'])}</button><a class='btn btn-ghost' href='{_e(intent)}' "
            f"rel='noopener noreferrer'>{_e(share['post'])}</a></div>"
            "<p class='muted' data-copy-status role='status' aria-live='polite'></p></section>"
        )
    card_url = reading.reading_url(locale, {name: values.get(name, "") for name in reading.FIELDS})
    body += f"<p><a href='{_e(card_url)}' data-winrate-card>{_e(words['card_link'])}</a></p>"
    return body, figures


def winrate_page(
    *,
    locale: str = "es",
    base_url: str = "",
    values: Mapping[str, str] | None = None,
    error: str = "",
    image_path: str = "",
) -> str:
    """The free win-rate calculator: the reader's Wilson interval and break-even rate."""
    from quant_trade.audit.owner_card import COPY as INPUT_COPY
    from quant_trade.audit.owner_card import ClaimInputError
    from quant_trade.audit.public_card import COPY as CARD_COPY
    from quant_trade.audit.public_card import breakeven_rate

    locale = _locale(locale)
    words = winrate.COPY[locale]
    shown = {name: (values or {}).get(name, "").strip() for name in winrate.FIELDS}
    claim = None
    if not error and any(shown.values()):
        try:
            claim = winrate.parse(shown, locale)
        except ClaimInputError as exc:
            error = str(exc)
    if error:
        shown = dict.fromkeys(winrate.FIELDS, "")  # never echo a rejected input

    def field(name: str, low: str, high: str, step: str) -> str:
        return (
            f"<div class='field'><label for='w-{name}'>{_e(words[name])} "
            f"{_badge('DECLARED', locale)}</label>"
            f"<input type='number' id='w-{name}' name='{name}' min='{low}' max='{high}' "
            f"step='{step}' inputmode='decimal' value='{_e(shown[name])}' autocomplete='off' "
            f"aria-describedby='w-{name}-help'>"
            f"<p class='help' id='w-{name}-help'>{_e(words[name + '_help'])}</p></div>"
        )

    form = ""
    if error:
        message = INPUT_COPY[locale].get(error, INPUT_COPY[locale]["invalid"])
        form += f"<p class='error' role='alert'>{_e(message)}</p>"
    form += (
        f"<p>{_e(words['optional'])}</p>"
        f"<form method='get' action='{_e(winrate.winrate_url(locale))}' class='calc-form'>"
        "<div class='form-grid'>"
        + field("trades", "1", "10000000", "1")
        + field("win_rate", "0", "100", "any")
        + field("target_r", "0", "1000000", "any")
        + field("stop_r", "0", "1000000", "any")
        + f"</div><button class='btn btn-dark' type='submit'>{_e(words['submit'])}</button></form>"
    )
    sections = [(words["form_title"], form)]
    if claim is not None:
        result, figures = _winrate_result(claim, shown, locale, base_url)
        sections.append((words["result_title"], result))
        if claim.win_rate is not None:
            breakeven = figures.breakeven
            above = "" if breakeven is None else f"<th scope='col'>{_e(words['col_above'])}</th>"
            rows = "".join(
                f"<tr><th scope='row'>{_e(_num(trades, locale, 0))}</th>"
                f"<td>{_e(win_rate_interval(claim.win_rate, trades, locale))}</td>"
                + (
                    ""
                    if breakeven is None
                    else f"<td>{_e(words['yes'] if low > breakeven else words['no'])}</td>"
                )
                + "</tr>"
                for trades, (low, _high) in figures.rows
            )
            sections.append(
                (
                    words["table_title"],
                    "<table class='winrate-table'><thead><tr>"
                    f"<th scope='col'>{_e(words['col_trades'])}</th>"
                    f"<th scope='col'>{_e(words['col_interval'])}</th>{above}</tr></thead>"
                    f"<tbody>{rows}</tbody></table>",
                )
            )
    be_rows = "".join(
        f"<tr><td>{_e(_num(target, locale, 1))}</td><td>{_e(_num(stop, locale, 1))}</td>"
        f"<td>{_e(_num(breakeven_rate(target, stop) * 100, locale, 1))} %</td></tr>"
        for target, stop in winrate.BREAKEVEN_EXAMPLES
    )
    sections.append(
        (
            words["be_table_title"],
            "<table class='winrate-breakeven'><thead><tr>"
            f"<th scope='col'>{_e(words['col_target'])}</th>"
            f"<th scope='col'>{_e(words['col_stop'])}</th>"
            f"<th scope='col'>{_e(words['col_breakeven'])}</th></tr></thead>"
            f"<tbody>{be_rows}</tbody></table>",
        )
    )
    how = (
        "<ul class='checks'>"
        + "".join(f"<li>{icon('check')}<span>{_e(item)}</span></li>" for item in words["how"])
        + "</ul>"
    )
    cta = (
        f"<p>{_e(words['cta'])}</p><p><a class='btn btn-dark' href='{_e(audit_path(locale))}'>"
        f"{_e(words['cta_button'])}<span class='go'>{icon('arrow')}</span></a> "
        f"<a href='{_e(_sample_url(locale))}'>{_e(words['sample_link'])}</a></p>"
    )
    article = ARTICLES_BY_KEY["cuantas-operaciones-porcentaje-aciertos"]
    audience = next(page for page in AUDIENCE_PAGES if page.slug == "retos-prop-firm")
    further = (
        (article.text[locale].title, article_url(article.key, locale)),
        (str(CALCULATOR_COPY[locale]["nav"]), calculator_url(locale)),
        (audience.text[locale].title, audience_url(audience.slug, locale)),
        (str(TOOLS_COPY[locale]["nav"]), tools_url(locale)),
    )
    read_more = (
        "<ul class='aud-others'>"
        + "".join(
            f"<li><a href='{_e(href)}'><span>{_e(label)}</span>{icon('arrow')}</a></li>"
            for label, href in further
        )
        + "</ul>"
    )
    sections += [
        (words["how_title"], how),
        (words["cta_title"], cta),
        (words["read_title"], read_more),
    ]
    title = f"{words['seo_title']} · {BRAND}"
    meta = head_meta(
        PageMeta(
            title=title,
            description=words["summary"],
            locale=locale,
            paths=dict(winrate.WINRATE_PATH),
            image_path=image_path,
            image_alt=CARD_COPY[locale]["title"] if image_path else title,
        ),
        base_url=base_url,
    ) + web_application_structured_data(
        words["nav"],
        words["summary"],
        base_url.rstrip("/") + winrate.winrate_url(locale),
        locale,
    )
    alternates = dict(winrate.WINRATE_PATH)
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(GUIDES_COPY[locale]['back'])}</a>" + (
        _language_crumbs(alternates, locale)
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["lead"], crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            sections,
            locale,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(_form_url(locale))}'>"
            f"{_e(GUIDES_COPY[locale]['form'])}<span class='go'>{icon('arrow')}</span></a>",
        )
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=alternates, solid_nav=True)


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
    """The upload form's page in ``locale``."""
    return audit_path(locale)


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
    ui = _UI[locale]
    words = GUIDES_COPY[locale]
    alternates = {lang: guides_index_url(lang) for lang in ("es", "en", "pt")}
    meta = _public_meta(
        f"{words['title']} · {BRAND}",
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
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(articles_index_url(locale))}'>"
        f"{_e(words['articles'])}{icon('arrow')}</a></div></div></div>"
    )
    return _page(
        f"{words['title']} · {BRAND}",
        locale,
        body,
        meta_html=meta,
        alternates=alternates,
        solid_nav=True,
    )


def _guide_offer(guide: Guide, locale: str, *, offer: str, email_verification: bool) -> str:
    """ "What you get" on a guide: the report's contents and the free report as the
    sign-up panel and /precios word them, the upload button, the sample report
    and the free tool that fits the guide (``guide_capabilities.GUIDE_TOOL``).

    ``offer`` is the service's (``free``, ``welcome`` or ``paid``). The free first
    report comes with the limits the upload applies to it (``web._first_look``:
    one per e-mail, browser and file, and a monthly share per network). Without
    a free report the block says the full report is paid, next to the free
    previews, and links the prices. A file that only goes next to a report (the
    optimisation XML, ``field == "optimization"``) says so, and in free mode
    drops "you only need the file".
    """
    # Lazy: account_pages imports this module.
    from quant_trade.audit.account_pages import report_contents

    words = GUIDES_COPY[locale]
    if offer == "welcome":
        contents = f"{report_contents(locale, 'welcome')} {words['free_terms']}"
    elif offer == "free":
        # The line under the button already says every report is free.
        contents = report_contents(locale, "")
    else:
        contents = words["paid_terms"].format(n=accounts.FREE_PREVIEWS_PER_MONTH)
    lines = [contents]
    note = offer_text(offer, locale, email_verification=email_verification)
    if guide.field == "optimization":
        lines.append(words["optimization_with_report"].format(upload=words["upload"]))
        if offer == "free":
            note = PRICING_COPY[locale]["free"]
    after = (
        f"<p>{_e(note)}</p>"
        if note
        else f"<p><a href='{_e(PRICING_PATH[locale])}'>{_e(_UI[locale]['nav_pricing'])}</a></p>"
    )
    tool = GUIDE_TOOL.get(guide.slug, "calculator")
    return (
        "".join(f"<p>{_e(line)}</p>" for line in lines)
        + f"<p><a class='btn btn-dark' href='{_e(_form_url(locale))}'>{_e(words['upload_this'])}"
        f"<span class='go'>{icon('arrow')}</span></a> "
        f"<a href='{_e(SAMPLE_PAGE_PATHS[locale])}'>{_e(PRICING_COPY[locale]['start_sample'])}</a>"
        f"</p>{after}"
        f"<p>{_e(words['tool'])} <a href='{_e(_tool_url(tool, locale))}'>"
        f"{_e(_tool_name(tool, locale))}</a>. {_e(TOOLS_COPY[locale][tool]['question'])}</p>"
    )


def guide_page(
    guide: Guide,
    *,
    locale: str = "es",
    base_url: str = "",
    offer: str = "free",
    email_verification: bool = False,
) -> str:
    """One platform's export guide.

    After the steps, what the report does with this file (each point from the
    code that does it, ``guide_capabilities``) and what the visitor gets, with
    the free report as ``offer`` and ``email_verification`` say: the same values
    the sign-up page receives. The title, description, heading, address and
    language links do not depend on them.
    """
    locale = _locale(locale)
    ui = _UI[locale]
    words = GUIDES_COPY[locale]
    text = guide.text[locale]
    alternates = {lang: guide_url(guide.slug, lang) for lang in ("es", "en", "pt")}
    title = f"{text.seo_title or text.title} · {BRAND}"
    meta = _public_meta(
        title, text.seo_description or text.summary, locale, guide_url(guide.slug, locale), base_url
    )
    steps = "".join(f"<li>{_e(step)}</li>" for step in text.steps)
    tips = "".join(f"<li>{icon('check')}<span>{_e(tip)}</span></li>" for tip in text.tips)
    does = "".join(
        f"<li>{icon('check')}<span>{_e(point)}</span></li>"
        for point in guide_points(guide.slug, locale)
    )
    crumbs = f"<a href='{_e(guides_index_url(locale))}'>{_e(words['all'])}</a>" + (
        _language_crumbs(alternates, locale)
    )
    sections = [
        (words["file"], f"<p>{_e(text.file)}</p>"),
        (words["steps"], f"<ol class='list-steps steps-guide'>{steps}</ol>"),
        (words["upload"], f"<p>{_e(text.upload)}</p>"),
        (words["tips"], f"<ul class='checks'>{tips}</ul>"),
    ]
    if does:
        sections.append((words["does"], f"<ul class='checks guide-does'>{does}</ul>"))
    sections.append(
        (
            words["get"],
            _guide_offer(guide, locale, offer=offer, email_verification=email_verification),
        )
    )
    body = (
        _page_hero(
            ui["guides_eyebrow"],
            text.title,
            text.summary,
            crumbs,
            note=guide_purpose(guide.slug, locale),
        )
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            sections,
            locale,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(_form_url(locale))}'>"
            f"{_e(words['upload_this'])}<span class='go'>{icon('arrow')}</span></a>",
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


def _articles_cta(locale: str) -> str:
    """The closing buttons of the article pages: the free calculator and the form."""
    words = ARTICLES_COPY[locale]
    return (
        "<div class='back-row'>"
        f"<a class='btn btn-dark' href='{_e(calculator_url(locale))}'>{_e(words['calculator'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(_form_url(locale))}'>{_e(words['report'])}"
        f"{icon('arrow')}</a></div>"
    )


def examples_page(*, locale: str = "es", base_url: str = "") -> str:
    """Public declarations with the existing card arithmetic and report CTA."""
    locale = _locale(locale)
    words = EXAMPLES_COPY[locale]
    title = f"{words['title']} · {BRAND}"
    meta = _public_meta(title, words["summary"], locale, examples_url(locale), base_url)
    crumbs = f"<a href='{_home(locale)}'>{_e(words['back'])}</a>" + _language_crumbs(
        EXAMPLES_PATH, locale
    )
    cta = CALCULATOR_COPY[locale]
    body = (
        _page_hero(words["eyebrow"], words["title"], words["intro"], crumbs)
        + "<div class='paper page-main'><div class='wrap wrap-mid'>"
        + f"<p><a class='link-more' href='{_e(reading.reading_url(locale))}'>"
        f"{_e(words['reader_link'])}{icon('arrow')}</a></p>"
        + examples_content(locale)
        + f"<section class='article-cta'><h2>{_e(cta['cta_title'])}</h2>"
        f"<p>{_e(cta['cta'])}</p><a class='btn btn-dark' href='{_form_url(locale)}'>"
        f"{_e(cta['cta_button'])}<span class='go'>{icon('arrow')}</span></a></section>"
        "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=EXAMPLES_PATH, solid_nav=True)


def tools_page(*, locale: str = "es", base_url: str = "") -> str:
    """The free tools that need no file: what each one asks for and what it gives."""
    locale = _locale(locale)
    words = TOOLS_COPY[locale]
    title = f"{words['seo_title']} · {BRAND}"
    base = base_url.rstrip("/")
    meta = _public_meta(title, words["summary"], locale, tools_url(locale), base_url)
    meta += tools_structured_data(
        [
            (_tool_name(key, locale), words[key]["question"], base + _tool_url(key, locale))
            for key in TOOL_KEYS
        ],
        locale,
    )
    tools = ""
    for key in TOOL_KEYS:
        tool = words[key]
        points = "".join(
            f"<li>{icon('check')}<span>{item}</span></li>"
            for item in (
                f"<strong>{_e(words['inputs'])}:</strong> {_e(tool['inputs'])}",
                f"<strong>{_e(words['returns'])}:</strong> {_e(tool['returns'])}",
                _e(words["no_account"]),
            )
        )
        tools += (
            f"<section class='article-cta'><h2 id='tool-{key}'>{_e(_tool_name(key, locale))}</h2>"
            f"<p>{_e(tool['question'])}</p>"
            f"<ul class='checks' style='margin-top:16px'>{points}</ul>"
            f"<div class='back-row'><a class='btn btn-dark' href='{_e(_tool_url(key, locale))}' "
            f"aria-describedby='tool-{key}'>{_e(words['open'])}"
            f"<span class='go'>{icon('arrow')}</span></a></div></section>"
        )
    report = (
        f"<section class='article-cta'><h2>{_e(words['report_title'])}</h2>"
        f"<p>{_e(words['report_text'])}</p><div class='back-row'>"
        f"<a class='btn btn-dark' href='{_e(audit_path(locale))}'>{_e(words['report_button'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(_sample_url(locale))}'>{_e(words['sample_link'])}"
        f"{icon('arrow')}</a>"
        f"<a class='link-more' href='{_e(articles_index_url(locale))}'>"
        f"{_e(words['articles_link'])}{icon('arrow')}</a></div></section>"
    )
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(GUIDES_COPY[locale]['back'])}</a>" + (
        _language_crumbs(TOOLS_PATH, locale)
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["intro"], crumbs)
        + "<div class='paper page-main'><div class='wrap wrap-mid'>"
        + tools
        + report
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=TOOLS_PATH, solid_nav=True)


def articles_index_page(*, locale: str = "es", base_url: str = "") -> str:
    """The list of articles about backtests."""
    locale = _locale(locale)
    copy = _COPY[locale]
    words = ARTICLES_COPY[locale]
    alternates = {lang: articles_index_url(lang) for lang in ("es", "en", "pt")}
    title = f"{words['title']} · {copy['title']}"
    meta = _public_meta(title, words["summary"], locale, articles_index_url(locale), base_url)
    meta += articles_faq_structured_data(locale)
    items = "".join(
        f"<li data-reveal style='--i:{i % 2}'><a href='{_e(article_url(a.key, locale))}'>"
        f"<b>{_e(a.text[locale].title)}{icon('arrow')}</b>"
        f"<span>{_e(a.text[locale].summary)}</span></a></li>"
        for i, a in enumerate(ARTICLES)
    )
    crumbs = f"<a href='{_e(_home(locale))}'>{_e(words['back'])}</a>" + _language_crumbs(
        alternates, locale
    )
    faq = "".join(
        f"<details><summary>{_e(question)}</summary><p>{_e(answer)}</p></details>"
        for question, answer in articles_index_faq(locale)
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["intro"], crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        f"<ul class='guide-list guides'>{items}</ul>"
        f"<section><h2>{_e(words['faq'])}</h2><div class='faq'>{faq}</div></section>"
        + _articles_cta(locale)
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=alternates, solid_nav=True)


def article_page(article: Article, *, locale: str = "es", base_url: str = "") -> str:
    """One article: its sections, questions, related pages and a closing call."""
    locale = _locale(locale)
    words = ARTICLES_COPY[locale]
    text = article.text[locale]
    alternates = {lang: article_url(article.key, lang) for lang in ("es", "en", "pt")}
    title = f"{text.seo_title or text.title} · {BRAND}"
    meta = _public_meta(title, text.summary, locale, article_url(article.key, locale), base_url)
    meta += article_structured_data(article, locale, base_url)
    sections = [
        (section.heading, "".join(f"<p>{_e(paragraph)}</p>" for paragraph in section.paragraphs))
        for section in text.sections
    ]
    if article.key in {"sharpe-deflactado-track-record", "bot-ia-backtest-suerte"}:
        heading, trials, years, luck, note = LUCK_TABLE_COPY[locale]
        rows = "".join(
            f"<tr><th scope='row'>DECLARED · {_num(value.trials, locale, 0)}</th>"
            f"<td>DECLARED · {value.years:g}</td>"
            f"<td>DECLARED · {_num(compute(value)['luck_sharpe']['value'], locale, 2)}</td></tr>"
            for value in LUCK_TABLE_INPUTS
        )
        table = (
            f"<p>{_e(INDEPENDENT_LUCK_EXAMPLE[locale])}</p>"
            f"<table class='article-luck'><caption>{_e(note)}</caption>"
            f"<thead><tr><th scope='col'>{_e(trials)}</th><th scope='col'>{_e(years)}</th>"
            f"<th scope='col'>{_e(luck)}</th></tr></thead><tbody>{rows}</tbody></table>"
        )
        sections.insert(4, (heading, table))
    if article.key == "cuantas-operaciones-porcentaje-aciertos":
        heading, trades, note = WIN_RATE_TABLE_COPY[locale]
        columns = "".join(
            f"<th scope='col'>DECLARED · {_num(rate * 100, locale, 0)} %</th>"
            for rate in WIN_RATE_RATES
        )
        rows = "".join(
            f"<tr><th scope='row'>DECLARED · {_num(count, locale, 0)}</th>"
            + "".join(
                f"<td>DECLARED · {_e(win_rate_interval(rate, count, locale))}</td>"
                for rate in WIN_RATE_RATES
            )
            + "</tr>"
            for count in WIN_RATE_TRADE_COUNTS
        )
        table = (
            f"<table class='article-wilson'><caption>{_e(note)}</caption>"
            f"<thead><tr><th scope='col'>{_e(trades)}</th>{columns}</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        sections.insert(2, (heading, table))
    if article.key == STREAK_ARTICLE_KEY:
        heading, rate, trades, median, rare, note = STREAK_TABLE_COPY[locale]
        rows = "".join(
            f"<tr><th scope='row'>DECLARED · {_num(row.win_rate * 100, locale, 0)} %</th>"
            f"<td>DECLARED · {_num(row.trades, locale, 0)}</td>"
            f"<td>DECLARED · {row.median_run}</td>"
            f"<td>DECLARED · {row.rare_run}</td></tr>"
            for row in STREAK_ROWS
        )
        table = (
            f"<table class='article-streaks'><caption>{_e(note)}</caption>"
            f"<thead><tr><th scope='col'>{_e(rate)}</th><th scope='col'>{_e(trades)}</th>"
            f"<th scope='col'>{_e(median)}</th><th scope='col'>{_e(rare)}</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        # Right after the section that explains the calculation, found by its title.
        after = [name for name, _body in sections].index(STREAK_TABLE_AFTER[locale])
        sections.insert(after + 1, (heading, table))
    if text.faq:
        faq = "".join(f"<h3>{_e(q)}</h3><p>{_e(a)}</p>" for q, a in text.faq)
        sections.append((words["faq"], faq))
    links = related_links(article, locale)
    if links:
        related = "".join(
            f"<li><a href='{_e(href)}'><span>{_e(label)}</span>{icon('arrow')}</a></li>"
            for label, href in links
        )
        sections.append((words["related"], f"<ul class='aud-others'>{related}</ul>"))
    crumbs = f"<a href='{_e(articles_index_url(locale))}'>{_e(words['all'])}</a>" + (
        _language_crumbs(alternates, locale)
    )
    # The article's own next step: its first link is the side button and the
    # closing button; the free first report stays among the closing links.
    steps = list(next_step_links(article, locale))
    (label, href), others = steps[0], steps[1:]
    report = (words["report"], audit_path(locale))
    if report not in steps:
        others.append(report)
    cta_title, cta_text = next_step_call(article, locale)
    closing = (
        f"<div class='back-row'><a class='btn btn-dark' href='{_e(href)}'>{_e(label)}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        + "".join(
            f"<a class='link-more' href='{_e(other_href)}'>{_e(other_label)}{icon('arrow')}</a>"
            for other_label, other_href in others
        )
        + "</div>"
    )
    body = (
        _page_hero(words["eyebrow"], text.title, text.summary, crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + _doc(
            sections,
            locale,
            lead=f"<p>{_e(text.intro)}</p>",
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(href)}'>"
            f"{_e(label)}<span class='go'>{icon('arrow')}</span></a>",
        )
        + f"<section class='article-cta'><h2>{_e(cta_title)}</h2>"
        f"<p>{_e(cta_text)}</p>{closing}</section></div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=alternates, solid_nav=True)


#: Articles each case page lists before the other cases (article keys, in order).
AUDIENCE_ARTICLES: dict[str, tuple[str, ...]] = {
    "retos-prop-firm": ("cuantos-intentos-reto-prop-firm", "rachas-perdedoras"),
    "compradores-de-robots": ("ea-sobreoptimizado", "lo-eligio-el-optimizador"),
    "copiar-senales": ("copiar-senales-mql5-myfxbook",),
}


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
    title = f"{text.seo_title or text.title} · {BRAND}"
    meta = _public_meta(
        title,
        text.seo_description or text.summary,
        locale,
        audience_url(audience.slug, locale),
        base_url,
        f"for-{audience.slug}",
    )
    sample = _sample_url(locale)
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
        f"<details><summary>{_e(q)}</summary><p>{_e(a.format(presets=FIRM_CHALLENGES))}</p></details>"
        for q, a in text.faq
    )
    others = "".join(
        f"<li><a href='{_e(audience_url(page.slug, locale))}'>"
        f"<span>{_e(page.text[locale].title)}</span>{icon('arrow')}</a></li>"
        for page in AUDIENCE_PAGES
        if page.slug != audience.slug
    )
    articles = "".join(
        f"<li><a href='{_e(article_url(key, locale))}'>"
        f"<span>{_e(ARTICLES_BY_KEY[key].text[locale].title)}</span>{icon('arrow')}</a></li>"
        for key in AUDIENCE_ARTICLES.get(audience.slug, ())
    )
    reads = [(words["read"], f"<ul class='aud-others'>{articles}</ul>")] if articles else []
    # Robot buyers land on the form with the live-account box already open.
    start = audit_path(locale) + ("?extras=1" if audience.open_extras else "")
    start_label = words["start"]
    if audience.contact_cta:
        start = institutional.REVIEW_PATHS[locale]
        start_label = institutional.COPY[locale]["title"]
    buttons = (
        "<div class='hero-cta'>"
        f"<a class='btn btn-dark' href='{_e(start)}'>{_e(start_label)}"
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
                (
                    start_label if audience.contact_cta else words["price"],
                    buttons
                    if audience.contact_cta
                    else f"<div class='aud-price'><p>{_e(price)}</p>{buttons}</div>",
                ),
                (words["faq"], f"<div class='faq'>{faq}</div>"),
                *reads,
                (words["others"], f"<ul class='aud-others'>{others}</ul>"),
            ],
            locale,
            lead=buttons,
            aside=f"<a class='btn btn-dark btn-sm toc-cta' href='{_e(start)}'>"
            f"{_e(start_label)}<span class='go'>{icon('arrow')}</span></a>",
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
    "tools_page",
    "verification_card_svg",
    "verification_page",
]
