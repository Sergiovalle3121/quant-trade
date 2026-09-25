"""One public page per kind of visitor: who it is for, what hurts, what to
upload, what Rigor checks and what it does not do.

A stranger who arrives from a search ("¿mi backtest está sobreajustado?",
"is this prop firm challenge realistic?", "check a fund's track record")
lands on the page written for their case instead of the generic landing.
Each page exists in Spanish and English, is listed in the sitemap and names
only features that are live. The test suite runs the profit-claim guard over
every page.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudienceText:
    #: The page's ``<h1>`` and the start of its ``<title>``.
    title: str
    #: One sentence for the hero and the meta description.
    summary: str
    #: What this visitor is worried about, in their own terms.
    pains: tuple[str, ...]
    #: What to upload: (text, export-guide slug or "").
    uploads: tuple[tuple[str, str], ...]
    #: What Rigor checks for them: (title, text), each a live report section.
    checks: tuple[tuple[str, str], ...]
    #: What it does not do, so nobody pays for the wrong thing.
    limits: tuple[str, ...]
    faq: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Audience:
    #: Spanish path segment; ``slug_en`` is the English one.
    slug: str
    slug_en: str
    icon: str
    text: dict[str, AudienceText]
    #: The start button opens the form's "Añadir más archivos" box (robot buyers
    #: bring the live account and the optimisation XML).
    open_extras: bool = False

    def slug_for(self, locale: str) -> str:
        return self.slug_en if locale == "en" else self.slug


#: A page lives at ``<base>/<slug>`` in each language.
AUDIENCE_BASE: dict[str, str] = {"es": "/para", "en": "/for"}

#: Export formats the universal reader recognises by their published column
#: layout (``audit/universal.py``). Named as "recognised", never as "tried":
#: each was built from the platform's documentation and synthetic rows.
RECOGNISED_PLATFORMS: tuple[str, ...] = (
    "Interactive Brokers",
    "Tradovate",
    "TopstepX",
    "thinkorswim",
    "TradeStation",
    "Charles Schwab",
    "Fidelity",
    "E*TRADE",
    "Webull",
    "tastytrade",
    "eToro",
    "cTrader",
    "Sierra Chart",
    "Binance",
    "Kraken",
    "Coinbase",
)


def platform_list(locale: str) -> str:
    """The recognised platforms as one phrase ("A, B y C" / "A, B and C")."""
    joiner = " y " if locale == "es" else " and "
    return ", ".join(RECOGNISED_PLATFORMS[:-1]) + joiner + RECOGNISED_PLATFORMS[-1]


PLATFORMS_ES = platform_list("es")
PLATFORMS_EN = platform_list("en")

AUDIENCE_COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Para quién es",
        "pains": "El problema",
        "uploads": "Qué subes",
        "checks": "Qué revisa Rigor",
        "limits": "Qué no hace",
        "price": "Precio",
        "price_text": (
            "La vista previa es gratis y no pide cuenta ni tarjeta: clase de A a D, gráficas, "
            "banderas rojas y qué significa cada dimensión. El informe completo cuesta "
            "USD {price:.0f} (USD {pack:.0f} el paquete de 3). Si el informe lee mal tu archivo "
            "y no podemos corregirlo, te devolvemos el importe."
        ),
        "faq": "Preguntas",
        "start": "Empezar gratis",
        "sample": "Ver un informe de ejemplo",
        "guide": "Cómo exportarlo",
        "others": "Otros casos",
        "home": "Inicio",
    },
    "en": {
        "eyebrow": "Who it is for",
        "pains": "The problem",
        "uploads": "What you upload",
        "checks": "What Rigor checks",
        "limits": "What it does not do",
        "price": "Price",
        "price_text": (
            "The preview is free and needs no account or card: A to D class, charts, red flags "
            "and what each dimension means. The full report is USD {price:.0f} (USD {pack:.0f} "
            "for a pack of 3). If the report misreads your file and we cannot fix it, we refund "
            "you."
        ),
        "faq": "Questions",
        "start": "Start free",
        "sample": "See a sample report",
        "guide": "How to export it",
        "others": "Other cases",
        "home": "Home",
    },
}

AUDIENCE_PAGES: tuple[Audience, ...] = (
    Audience(
        slug="compradores-de-robots",
        slug_en="robot-buyers",
        icon="layers",
        open_extras=True,
        text={
            "es": AudienceText(
                title="Antes de comprar un robot de trading, revisa su backtest",
                summary=(
                    "Sube el informe del probador de MetaTrader que te enseña el vendedor y "
                    "descubre si su curva es evidencia o el resultado de probar cientos de "
                    "configuraciones."
                ),
                pains=(
                    "El vendedor enseña una curva casi recta y un factor de beneficio alto, y "
                    "no sabes cuántas configuraciones probó hasta encontrarla.",
                    "Muchos robots se ven bien en el probador y fallan en real por costes, "
                    "deslizamiento o datos de baja calidad.",
                    "Un historial de Myfxbook puede inflarse con depósitos o esconder pérdidas "
                    "abiertas que aún no se cerraron.",
                ),
                uploads=(
                    (
                        "El informe HTML del probador de MetaTrader 5 o 4, tal como lo guarda "
                        "el probador.",
                        "mt5",
                    ),
                    (
                        "Si el vendedor te lo da, el XML de optimización: cuenta las "
                        "configuraciones que probó.",
                        "mt5-optimization",
                    ),
                    (
                        "Si tiene cuenta real o demo con el robot, su historial de MetaTrader, "
                        "Myfxbook, FX Blue o señal de MQL5.",
                        "cuenta-proveedor",
                    ),
                ),
                checks=(
                    (
                        "Número de intentos",
                        "El Sharpe deflactado descuenta las configuraciones probadas; con el "
                        "XML, ese número se mide en lugar de suponerse.",
                    ),
                    (
                        "¿Pico aislado o meseta?",
                        "Si al mover un parámetro un paso el resultado se hunde, la "
                        "configuración se ajustó al ruido del historial.",
                    ),
                    (
                        "Con qué datos se hizo la prueba",
                        "Modelo de ticks y calidad del historial del probador: una prueba con "
                        "precios de apertura no dice lo mismo que una con ticks reales.",
                    ),
                    (
                        "Pruebas de estrés",
                        "El resultado sin sus mejores operaciones y meses, y qué pasa con el "
                        "doble y el triple de costes.",
                    ),
                    (
                        "Backtest frente a cuenta real",
                        "Si la cuenta del vendedor se comporta como miles de historias "
                        "remuestreadas de su propio backtest.",
                    ),
                    (
                        "Preguntas para el vendedor",
                        "Una lista de preguntas concretas que salen de lo que el archivo no "
                        "responde.",
                    ),
                ),
                limits=(
                    "No comprueba las operaciones con el bróker: audita el archivo que subes.",
                    "No recomienda comprar ni dejar de comprar un robot, y no predice resultados.",
                ),
                faq=(
                    (
                        "¿Y si el vendedor no me da el informe?",
                        "Pídele el informe HTML del probador y, si lo optimizó, el XML de "
                        "optimización. Un vendedor que no puede enseñar ninguno de los dos ya "
                        "te está dando una respuesta.",
                    ),
                    (
                        "¿Una clase A significa que el robot funcionará?",
                        "No. La clase mide cuántas preguntas estadísticas responde el archivo. "
                        "El futuro depende del mercado, de los costes reales y de cómo se opere.",
                    ),
                ),
            ),
            "en": AudienceText(
                title="Before you buy a trading robot, check its backtest",
                summary=(
                    "Upload the MetaTrader tester report the vendor shows you and find out "
                    "whether the curve is evidence or the result of trying hundreds of settings."
                ),
                pains=(
                    "The vendor shows an almost straight curve and a high profit factor, and "
                    "you cannot tell how many settings were tried to find it.",
                    "Many robots look good in the tester and fail live through costs, slippage "
                    "or poor data.",
                    "A Myfxbook history can be inflated by deposits or hide open losses that "
                    "were never closed.",
                ),
                uploads=(
                    (
                        "The MetaTrader 5 or 4 tester HTML report, exactly as the tester saves it.",
                        "mt5",
                    ),
                    (
                        "If the vendor gives it to you, the optimisation XML: it counts the "
                        "settings that were tried.",
                        "mt5-optimization",
                    ),
                    (
                        "If there is a live or demo account running the robot, its MetaTrader, "
                        "Myfxbook, FX Blue or MQL5 signal history.",
                        "cuenta-proveedor",
                    ),
                ),
                checks=(
                    (
                        "Number of trials",
                        "The deflated Sharpe discounts the settings tried; with the XML, that "
                        "number is measured instead of assumed.",
                    ),
                    (
                        "Isolated peak or plateau?",
                        "If moving one parameter one step makes the result collapse, the "
                        "setting was fitted to the noise of the history.",
                    ),
                    (
                        "What data the test used",
                        "The tester's tick model and history quality: a test on open prices "
                        "does not say the same as one on real ticks.",
                    ),
                    (
                        "Stress tests",
                        "The result without its best trades and months, and what happens at "
                        "double and triple costs.",
                    ),
                    (
                        "Backtest against the live account",
                        "Whether the vendor's account behaves like thousands of resampled "
                        "histories of its own backtest.",
                    ),
                    (
                        "Questions for the vendor",
                        "A list of specific questions drawn from what the file does not answer.",
                    ),
                ),
                limits=(
                    "It does not check the trades with the broker: it audits the file you upload.",
                    "It does not recommend buying or not buying a robot, and it does not "
                    "predict results.",
                ),
                faq=(
                    (
                        "What if the vendor will not give me the report?",
                        "Ask for the tester HTML report and, if it was optimised, the "
                        "optimisation XML. A vendor who cannot show either is already giving "
                        "you an answer.",
                    ),
                    (
                        "Does class A mean the robot will work?",
                        "No. The class measures how many statistical questions the file "
                        "answers. The future depends on the market, real costs and how it is "
                        "traded.",
                    ),
                ),
            ),
        },
    ),
    Audience(
        slug="traders-acciones-futuros-cripto",
        slug_en="stock-futures-crypto-traders",
        icon="chart",
        text={
            "es": AudienceText(
                title="¿Tu estrategia de acciones, futuros o cripto tiene ventaja real?",
                summary=(
                    "Sube la lista de operaciones de TradingView, NinjaTrader, QuantConnect, "
                    "backtesting.py o vectorbt, o tu curva de equity, y mide si tu ventaja "
                    "resiste el número de intentos, los costes y el periodo reciente."
                ),
                pains=(
                    "Probaste decenas de variantes hasta dar con una que se ve bien, y ya no "
                    "sabes si encontraste una ventaja o la suerte de haber probado tanto.",
                    "Comisiones, spread, financiación y deslizamiento se comen las ventajas "
                    "finas, sobre todo en cripto y en futuros pequeños.",
                    "Una estrategia que funcionó hace años puede haber dejado de hacerlo.",
                ),
                uploads=(
                    ("La lista de operaciones de TradingView (CSV o XLSX).", "tradingview"),
                    ("El CSV de operaciones de NinjaTrader 8.", "ninjatrader"),
                    ("Las operaciones de QuantConnect.", "quantconnect"),
                    ("Las operaciones de backtesting.py o vectorbt.", "backtesting-py"),
                    (
                        "El historial de operaciones de tu bróker o exchange en CSV o Excel. "
                        "Rigor reconoce el formato de exportación de "
                        + PLATFORMS_ES
                        + "; de cualquier otro bróker o diario, las columnas se reconocen por "
                        "su nombre.",
                        "csv-universal",
                    ),
                    (
                        "O tu curva de equity o serie de retornos en CSV o Excel (diaria, "
                        "semanal o mensual), de cualquier mercado.",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Significación estadística",
                        "Si tu Sharpe se distingue de cero dada la longitud, la asimetría y "
                        "la curtosis del historial.",
                    ),
                    (
                        "Número de intentos",
                        "Cuánto sobrevive después de descontar las variantes que probaste.",
                    ),
                    (
                        "Costes",
                        "Qué pasa a 1x, 2x y 3x el coste de operación, y el coste de equilibrio.",
                    ),
                    (
                        "¿Sigue funcionando en el periodo reciente?",
                        "El último tercio del historial frente al resto.",
                    ),
                    (
                        "¿Funciona en cada instrumento?",
                        "Operaciones, resultado neto y aciertos por símbolo, cuando el archivo "
                        "trae varios.",
                    ),
                    (
                        "Qué capital necesita",
                        "El capital que pide cada límite de pérdida, remuestreando un año de "
                        "tus operaciones.",
                    ),
                ),
                limits=(
                    "No se conecta a tu bróker ni a tu exchange: audita el archivo que subes.",
                    "No recomienda operar ni predice resultados.",
                ),
                faq=(
                    (
                        "¿Sirve para cripto?",
                        "Sí. Rigor no depende del mercado: mide el historial que subes. Una "
                        "exportación de TradingView o una curva de equity de tu cartera cripto "
                        "sirven igual que una de acciones.",
                    ),
                    (
                        "¿Qué pasa si solo tengo una curva de equity?",
                        "Se audita igual. Sin la lista de operaciones, los costes quedan como "
                        "NOT_MEASURED y el informe te dice qué archivo los mediría.",
                    ),
                ),
            ),
            "en": AudienceText(
                title="Does your stock, futures or crypto strategy have a real edge?",
                summary=(
                    "Upload your TradingView, NinjaTrader, QuantConnect, backtesting.py or "
                    "vectorbt list of trades, or your equity curve, and measure whether your "
                    "edge survives the number of trials, costs and the recent period."
                ),
                pains=(
                    "You tried dozens of variants until one looked good, and you no longer "
                    "know whether you found an edge or the luck of trying so many.",
                    "Commission, spread, funding and slippage eat thin edges, especially in "
                    "crypto and small futures.",
                    "A strategy that worked years ago may have stopped working.",
                ),
                uploads=(
                    ("The TradingView list of trades (CSV or XLSX).", "tradingview"),
                    ("The NinjaTrader 8 trades CSV.", "ninjatrader"),
                    ("The QuantConnect trades.", "quantconnect"),
                    ("The backtesting.py or vectorbt trades.", "backtesting-py"),
                    (
                        "Your broker's or exchange's trade history as CSV or Excel. Rigor "
                        "recognises the export format of "
                        + PLATFORMS_EN
                        + "; from any other broker or journal, the columns are recognised by "
                        "their names.",
                        "csv-universal",
                    ),
                    (
                        "Or your equity curve or return series as CSV or Excel (daily, weekly or "
                        "monthly), from any market.",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Statistical significance",
                        "Whether your Sharpe is distinguishable from zero given the history's "
                        "length, skew and kurtosis.",
                    ),
                    (
                        "Number of trials",
                        "How much survives after discounting the variants you tried.",
                    ),
                    (
                        "Costs",
                        "What happens at 1x, 2x and 3x the trading cost, and the break-even cost.",
                    ),
                    (
                        "Does it still work in the recent period?",
                        "The last third of the history against the rest.",
                    ),
                    (
                        "Does it work on each instrument?",
                        "Trades, net result and hit rate per symbol, when the file holds several.",
                    ),
                    (
                        "How much capital it needs",
                        "The capital each loss limit calls for, resampling one year of your "
                        "trades.",
                    ),
                ),
                limits=(
                    "It never connects to your broker or exchange: it audits the file you upload.",
                    "It does not recommend trading and does not predict results.",
                ),
                faq=(
                    (
                        "Does it work for crypto?",
                        "Yes. Rigor does not depend on the market: it measures the history you "
                        "upload. A TradingView export or an equity curve of your crypto "
                        "portfolio works the same as a stock one.",
                    ),
                    (
                        "What if I only have an equity curve?",
                        "It is audited all the same. Without the list of trades, costs are "
                        "NOT_MEASURED and the report tells you which file would measure them.",
                    ),
                ),
            ),
        },
    ),
    Audience(
        slug="retos-prop-firm",
        slug_en="prop-firm-challenges",
        icon="target",
        text={
            "es": AudienceText(
                title="Antes de pagar un reto de prop firm, simúlalo con tu historial",
                summary=(
                    "Sube tu backtest o tu historial y mira con qué frecuencia tocarías la "
                    "pérdida diaria o la total en retos de FTMO, FundedNext, The5ers y "
                    "Topstep, remuestreando tus propias operaciones."
                ),
                pains=(
                    "Pagas el reto, una mala racha toca la pérdida diaria y vuelves a pagar.",
                    "Tu estrategia puede ser buena y aun así no encajar en las reglas de "
                    "pérdida diaria, pérdida total y plazo de un reto concreto.",
                    "Cada firma cambia sus reglas, y no siempre es fácil compararlas.",
                ),
                uploads=(
                    ("Tu informe de MetaTrader 5 o 4.", "mt5"),
                    ("Tu lista de operaciones de TradingView.", "tradingview"),
                    ("Tu CSV de NinjaTrader 8 (futuros).", "ninjatrader"),
                    (
                        "O el historial de operaciones de tu plataforma en CSV o Excel: Rigor "
                        "reconoce el formato de Tradovate, TopstepX y Sierra Chart, entre otros.",
                        "csv-universal",
                    ),
                    (
                        "Y en el formulario, en «Añadir más archivos», eliges el reto que "
                        "quieres simular.",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Simulador de reto",
                        "Remuestrea tu historial miles de veces y cuenta con qué frecuencia se "
                        "tocaría la pérdida diaria, la total, o no se llegaría al objetivo a "
                        "tiempo.",
                    ),
                    (
                        "Reglas con fuente y fecha",
                        "Cada reto cita la web oficial de la firma y la fecha en que se leyeron "
                        "sus reglas.",
                    ),
                    (
                        "Qué capital necesita y a qué tamaño",
                        "El capital que pide tu estrategia para límites de pérdida del 10, 20, "
                        "30 y 50 %.",
                    ),
                    (
                        "Riesgo remuestreado a un año",
                        "La caída probable de tu estrategia en un año, con sus supuestos "
                        "escritos al lado.",
                    ),
                    (
                        "Cómo se comporta al perder",
                        "Si alargas las operaciones perdedoras o vuelves a entrar enseguida "
                        "después de una pérdida.",
                    ),
                ),
                limits=(
                    "Son estimaciones con sus supuestos escritos, no una predicción del reto.",
                    "Confirma siempre las reglas con la firma antes de pagar su reto.",
                ),
                faq=(
                    (
                        "¿Qué firmas y retos incluye?",
                        "{presets} retos de FTMO, FundedNext, The5ers y Topstep, más un reto "
                        "genérico de dos fases. El formulario muestra la fecha en que se "
                        "leyeron las reglas.",
                    ),
                    (
                        "¿Me dice si conseguiré la cuenta?",
                        "No. Te dice con qué frecuencia, repitiendo tu propio historial en "
                        "otro orden, se tocarían los límites del reto. Es una medida del "
                        "riesgo de tu estrategia frente a esas reglas.",
                    ),
                ),
            ),
            "en": AudienceText(
                title="Before you pay for a prop-firm challenge, simulate it with your history",
                summary=(
                    "Upload your backtest or history and see how often you would hit the daily "
                    "or total loss limit in FTMO, FundedNext, The5ers and Topstep challenges, "
                    "resampling your own trades."
                ),
                pains=(
                    "You pay for the challenge, one bad streak hits the daily loss limit and "
                    "you pay again.",
                    "Your strategy can be sound and still not fit a given challenge's daily "
                    "loss, total loss and time rules.",
                    "Every firm changes its rules, and comparing them is not easy.",
                ),
                uploads=(
                    ("Your MetaTrader 5 or 4 report.", "mt5"),
                    ("Your TradingView list of trades.", "tradingview"),
                    ("Your NinjaTrader 8 CSV (futures).", "ninjatrader"),
                    (
                        "Or your platform's trade history as CSV or Excel: Rigor recognises the "
                        "format of Tradovate, TopstepX and Sierra Chart, among others.",
                        "csv-universal",
                    ),
                    (
                        "Then, on the form, open 'Add more files' and pick the challenge to "
                        "simulate.",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Challenge simulator",
                        "Resamples your history thousands of times and counts how often the "
                        "daily loss, the total loss would be hit, or the target not reached in "
                        "time.",
                    ),
                    (
                        "Rules with source and date",
                        "Every challenge cites the firm's official site and the date its rules "
                        "were read.",
                    ),
                    (
                        "How much capital it needs and at what size",
                        "The capital your strategy calls for at 10, 20, 30 and 50 % loss limits.",
                    ),
                    (
                        "Resampled one-year risk",
                        "Your strategy's likely fall over a year, with its assumptions written "
                        "next to it.",
                    ),
                    (
                        "How it behaves when losing",
                        "Whether you hold losing trades longer or re-enter right after a loss.",
                    ),
                ),
                limits=(
                    "These are estimates with their assumptions written down, not a forecast "
                    "of the challenge.",
                    "Always confirm the rules with the firm before paying for its challenge.",
                ),
                faq=(
                    (
                        "Which firms and challenges are included?",
                        "{presets} FTMO, FundedNext, The5ers and Topstep challenges, plus a "
                        "generic two-phase one. The form shows the date the rules were read.",
                    ),
                    (
                        "Does it tell me whether I will get the account?",
                        "No. It tells you how often, replaying your own history in another "
                        "order, the challenge's limits would be hit. It measures your "
                        "strategy's risk against those rules.",
                    ),
                ),
            ),
        },
    ),
    Audience(
        slug="inversores-gestores-fondos",
        slug_en="investors-managers-funds",
        icon="eye",
        text={
            "es": AudienceText(
                title="Antes de invertir con un gestor, una señal o un fondo, revisa su historial",
                summary=(
                    "Sube el historial de su cuenta o su serie de retornos y separa el "
                    "resultado de operar de los depósitos, compara la cuenta con su backtest "
                    "y mide si el historial es evidencia o suerte."
                ),
                pains=(
                    "El porcentaje que te enseñan puede venir de depósitos y recargas, no de "
                    "operar.",
                    "Un historial corto o con pocos meses muy buenos puede parecer una "
                    "trayectoria sólida.",
                    "Lo que muestra el backtest y lo que hace la cuenta real no siempre se "
                    "parecen.",
                ),
                uploads=(
                    (
                        "El historial de su cuenta: el informe de MetaTrader o el CSV que "
                        "exporta Myfxbook, FX Blue o su señal de MQL5.",
                        "cuenta-proveedor",
                    ),
                    (
                        "O su serie de retornos (diaria, semanal o mensual) en CSV o Excel, con "
                        "columnas de fecha y retorno.",
                        "",
                    ),
                    (
                        "O la tabla de rentabilidades mensuales de su ficha (factsheet), tal "
                        "cual: una fila por año y una columna por mes, en CSV o Excel.",
                        "",
                    ),
                    ("Si lo tiene, su backtest, para compararlo con la cuenta.", "mt5"),
                ),
                checks=(
                    (
                        "El dinero real de la cuenta",
                        "Depósitos y retiros separados del resultado de operar; aviso si el "
                        "porcentaje se infla con recargas o si quedan pérdidas abiertas.",
                    ),
                    (
                        "Backtest frente a cuenta real",
                        "La cuenta frente a miles de historias remuestreadas de su backtest, y "
                        "operación por operación en las mismas fechas.",
                    ),
                    (
                        "Significación estadística",
                        "Si el historial se distingue del azar dada su longitud.",
                    ),
                    (
                        "Pruebas de estrés",
                        "El resultado sin sus mejores meses y operaciones.",
                    ),
                    (
                        "¿Sigue funcionando en el periodo reciente?",
                        "El último tercio del historial frente al resto.",
                    ),
                    (
                        "Lo que revisaría quien invierte en un fondo",
                        "Con 24 meses o más: calendario año por mes, rentabilidad anual "
                        "compuesta, volatilidad, peor mes, caída más profunda, tiempo en "
                        "recuperarse y dos pruebas de retornos suavizados.",
                    ),
                    (
                        "Preguntas para el gestor",
                        "Qué pedirle, a partir de lo que su archivo no responde.",
                    ),
                ),
                limits=(
                    "No se conecta a su bróker ni a tu dinero: audita el archivo que subes.",
                    "No te dice si invertir o no; te da los números para que decidas.",
                ),
                faq=(
                    (
                        "¿Y si solo tengo sus retornos mensuales?",
                        "Súbelos como serie de retornos en CSV o Excel, o sube la tabla de "
                        "su ficha tal cual (año por fila, meses en columnas, en español, "
                        "inglés u otro idioma, o del 1 al 12). Si el total de un año no "
                        "cuadra con sus meses, el informe lo avisa. Con retornos mensuales, "
                        "un historial corto tiene pocos datos, y el informe lo dice en lugar "
                        "de disimularlo.",
                    ),
                    (
                        "¿Cómo le pido el historial?",
                        "La guía de la cuenta de un proveedor explica qué pedir en MetaTrader, "
                        "Myfxbook, FX Blue y señales de MQL5.",
                    ),
                ),
            ),
            "en": AudienceText(
                title="Before you invest with a manager, a signal or a fund, check the history",
                summary=(
                    "Upload their account history or return series to separate trading "
                    "results from deposits, compare the account with its backtest and measure "
                    "whether the history is evidence or luck."
                ),
                pains=(
                    "The percentage you are shown may come from deposits and top-ups, not from "
                    "trading.",
                    "A short history, or one with a few very good months, can look like a "
                    "solid track record.",
                    "What the backtest shows and what the live account does are not always alike.",
                ),
                uploads=(
                    (
                        "Their account history: the MetaTrader report or the CSV exported by "
                        "Myfxbook, FX Blue or their MQL5 signal.",
                        "cuenta-proveedor",
                    ),
                    (
                        "Or their return series (daily, weekly or monthly) as CSV or Excel, "
                        "with date and return columns.",
                        "",
                    ),
                    (
                        "Or the monthly returns table from their factsheet, as it is: one row "
                        "per year and one column per month, as CSV or Excel.",
                        "",
                    ),
                    ("If they have one, their backtest, to compare with the account.", "mt5"),
                ),
                checks=(
                    (
                        "The real money in the account",
                        "Deposits and withdrawals kept apart from trading results; a warning "
                        "when the percentage is inflated by top-ups or losses are still open.",
                    ),
                    (
                        "Backtest against the live account",
                        "The account against thousands of resampled histories of its backtest, "
                        "and trade by trade on the same dates.",
                    ),
                    (
                        "Statistical significance",
                        "Whether the history stands out from chance given its length.",
                    ),
                    (
                        "Stress tests",
                        "The result without its best months and trades.",
                    ),
                    (
                        "Does it still work in the recent period?",
                        "The last third of the history against the rest.",
                    ),
                    (
                        "What someone investing in a fund would check",
                        "With 24 months or more: a year-by-month calendar, compound annual "
                        "return, volatility, worst month, deepest fall, time to recover and "
                        "two checks for smoothed returns.",
                    ),
                    (
                        "Questions for the manager",
                        "What to ask them, based on what their file does not answer.",
                    ),
                ),
                limits=(
                    "It never connects to their broker or your money: it audits the file you "
                    "upload.",
                    "It does not tell you whether to invest; it gives you the numbers to decide.",
                ),
                faq=(
                    (
                        "What if I only have their monthly returns?",
                        "Upload them as a return series in CSV or Excel, or upload their "
                        "factsheet table as it is (a row per year, months as columns, in "
                        "English, Spanish or another language, or 1 to 12). If a year's total "
                        "does not match its months, the report says so. With monthly returns a "
                        "short history holds few data points, and the report says so instead "
                        "of hiding it.",
                    ),
                    (
                        "How do I ask for the history?",
                        "The provider's account guide explains what to ask for in MetaTrader, "
                        "Myfxbook, FX Blue and MQL5 signals.",
                    ),
                ),
            ),
        },
    ),
)

AUDIENCES_BY_PATH: dict[str, dict[str, Audience]] = {
    locale: {page.slug_for(locale): page for page in AUDIENCE_PAGES} for locale in ("es", "en")
}


def audience_url(slug: str, locale: str) -> str:
    """The page's path in ``locale``; ``slug`` is its Spanish slug."""
    page = next((p for p in AUDIENCE_PAGES if p.slug == slug), None)
    return f"{AUDIENCE_BASE[locale]}/{page.slug_for(locale) if page else slug}"


__all__ = [
    "AUDIENCES_BY_PATH",
    "AUDIENCE_BASE",
    "AUDIENCE_COPY",
    "AUDIENCE_PAGES",
    "PLATFORMS_EN",
    "PLATFORMS_ES",
    "RECOGNISED_PLATFORMS",
    "Audience",
    "AudienceText",
    "audience_url",
    "platform_list",
]
