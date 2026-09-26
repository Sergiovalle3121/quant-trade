"""One public page per kind of visitor: who it is for, what hurts, what to
upload, what Rigor checks and what it does not do.

A stranger who arrives from a search ("¿mi backtest está sobreajustado?",
"is this prop firm challenge realistic?", "check a fund's track record")
lands on the page written for their case instead of the generic landing.
Each page exists in Spanish, English and Portuguese, is listed in the sitemap and names
only features that are live. The test suite runs the profit-claim guard over
every page.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_trade.audit.accounts import FREE_PREVIEWS_PER_MONTH


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
    #: Spanish path segment; ``slug_en`` and ``slug_pt`` are the English and
    #: Portuguese ones.
    slug: str
    slug_en: str
    icon: str
    text: dict[str, AudienceText]
    #: The start button opens the form's "Añadir más archivos" box (robot buyers
    #: bring the live account and the optimisation XML).
    open_extras: bool = False
    slug_pt: str = ""

    def slug_for(self, locale: str) -> str:
        if locale == "pt":
            return self.slug_pt or self.slug
        return self.slug_en if locale == "en" else self.slug


#: A page lives at ``<base>/<slug>`` in each language.
AUDIENCE_BASE: dict[str, str] = {"es": "/para", "en": "/for", "pt": "/pt/para"}

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
    "Robinhood",
    "tastytrade",
    "eToro",
    "XTB",
    "DEGIRO",
    "Trading 212",
    "Revolut",
    "cTrader",
    "Sierra Chart",
    "Rithmic",
    "Binance",
    "Kraken",
    "Coinbase",
    "KuCoin",
)


def platform_list(locale: str) -> str:
    """The recognised platforms as one phrase ("A, B y C" / "A, B and C" / "A, B e C")."""
    joiner = {"es": " y ", "pt": " e "}.get(locale, " and ")
    return ", ".join(RECOGNISED_PLATFORMS[:-1]) + joiner + RECOGNISED_PLATFORMS[-1]


PLATFORMS_ES = platform_list("es")
PLATFORMS_EN = platform_list("en")
PLATFORMS_PT = platform_list("pt")

AUDIENCE_COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Para quién es",
        "pains": "El problema",
        "uploads": "Qué subes",
        "checks": "Qué revisa Rigor",
        "limits": "Qué no hace",
        "price": "Precio",
        "price_text": (
            "Tu primer informe completo es gratis al crear tu cuenta. Después, la vista previa "
            f"es gratis ({FREE_PREVIEWS_PER_MONTH} al mes) y no pide tarjeta: clase de A a D, "
            "gráficas, "
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
            "Your first full report is free when you create your account. After that the "
            f"preview is free ({FREE_PREVIEWS_PER_MONTH} a month) and needs no card: A to D "
            "class, charts, red flags "
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
    "pt": {
        "eyebrow": "Para quem é",
        "pains": "O problema",
        "uploads": "O que você envia",
        "checks": "O que o Rigor revisa",
        "limits": "O que não faz",
        "price": "Preço",
        "price_text": (
            "O seu primeiro relatório completo é grátis ao criar a sua conta. Depois, a prévia "
            f"é grátis ({FREE_PREVIEWS_PER_MONTH} por mês) e não pede cartão: classe de A a D, "
            "gráficos, bandeiras vermelhas e o que cada dimensão significa. O relatório "
            "completo custa USD {price:.0f} (USD {pack:.0f} o pacote de 3). Se o relatório ler "
            "mal o seu arquivo e não conseguirmos corrigir, devolvemos o valor."
        ),
        "faq": "Perguntas",
        "start": "Começar grátis",
        "sample": "Ver um relatório de exemplo (em inglês)",
        "guide": "Como exportar",
        "others": "Outros casos",
        "home": "Início",
    },
}

AUDIENCE_PAGES: tuple[Audience, ...] = (
    Audience(
        slug="compradores-de-robots",
        slug_en="robot-buyers",
        slug_pt="compradores-de-robos",
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
            "pt": AudienceText(
                title="Antes de comprar um robô de trading, revise o backtest dele",
                summary=(
                    "Envie o relatório do testador do MetaTrader que o vendedor mostra e "
                    "descubra se a curva é evidência ou o resultado de testar centenas de "
                    "configurações."
                ),
                pains=(
                    "O vendedor mostra uma curva quase reta e um fator de lucro alto, e você não "
                    "sabe quantas configurações ele testou até encontrá-la.",
                    "Muitos robôs ficam bonitos no testador e falham na conta real por custos, "
                    "slippage ou dados de baixa qualidade.",
                    "Um histórico do Myfxbook pode ser inflado com depósitos ou esconder perdas "
                    "abertas que ainda não foram fechadas.",
                ),
                uploads=(
                    (
                        "O relatório HTML do testador do MetaTrader 5 ou 4, do jeito que o "
                        "testador o salva.",
                        "mt5",
                    ),
                    (
                        "Se o vendedor fornecer, o XML de otimização: ele conta as configurações "
                        "que foram testadas.",
                        "mt5-optimization",
                    ),
                    (
                        "Se houver uma conta real ou demo rodando o robô, o histórico dela no "
                        "MetaTrader, Myfxbook, FX Blue ou sinal da MQL5.",
                        "cuenta-proveedor",
                    ),
                ),
                checks=(
                    (
                        "Número de tentativas",
                        "O Sharpe deflacionado desconta as configurações testadas; com o XML, "
                        "esse número é medido em vez de suposto.",
                    ),
                    (
                        "Pico isolado ou platô?",
                        "Se mover um parâmetro um passo derruba o resultado, a configuração foi "
                        "ajustada ao ruído do histórico.",
                    ),
                    (
                        "Com que dados o teste foi feito",
                        "O modelo de ticks e a qualidade do histórico do testador: um teste com "
                        "preços de abertura não diz o mesmo que um com ticks reais.",
                    ),
                    (
                        "Testes de estresse",
                        "O resultado sem as suas melhores operações e meses, e o que acontece "
                        "com o dobro e o triplo dos custos.",
                    ),
                    (
                        "Backtest frente à conta real",
                        "Se a conta do vendedor se comporta como milhares de histórias "
                        "reamostradas do seu próprio backtest.",
                    ),
                    (
                        "Perguntas para o vendedor",
                        "Uma lista de perguntas concretas tiradas do que o arquivo não responde.",
                    ),
                ),
                limits=(
                    "Não confere as operações com a corretora: audita o arquivo que você envia.",
                    "Não recomenda comprar ou não um robô, e não prevê resultados.",
                ),
                faq=(
                    (
                        "E se o vendedor não me der o relatório?",
                        "Peça o relatório HTML do testador e, se houve otimização, o XML de "
                        "otimização. Um vendedor que não pode mostrar nenhum dos dois já está "
                        "dando uma resposta.",
                    ),
                    (
                        "Classe A quer dizer que o robô vai funcionar?",
                        "Não. A classe mede quantas perguntas estatísticas o arquivo responde. O "
                        "futuro depende do mercado, dos custos reais e de como se opera.",
                    ),
                ),
            ),
        },
    ),
    Audience(
        slug="traders-acciones-futuros-cripto",
        slug_en="stock-futures-crypto-traders",
        slug_pt="traders-acoes-futuros-cripto",
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
            "pt": AudienceText(
                title="A sua estratégia de ações, futuros ou cripto tem uma vantagem real?",
                summary=(
                    "Envie a lista de operações do TradingView, NinjaTrader, QuantConnect, "
                    "backtesting.py ou vectorbt, ou a sua curva de equity, e meça se a sua "
                    "vantagem sobrevive ao número de tentativas, aos custos e ao período "
                    "recente."
                ),
                pains=(
                    "Você testou dezenas de variantes até uma ficar boa, e já não sabe se "
                    "encontrou uma vantagem ou a sorte de testar tantas.",
                    "Comissão, spread, funding e slippage comem as vantagens pequenas, sobretudo "
                    "em cripto e em futuros pequenos.",
                    "Uma estratégia que funcionou anos atrás pode ter parado de funcionar.",
                ),
                uploads=(
                    ("A lista de operações do TradingView (CSV ou XLSX).", "tradingview"),
                    ("O CSV de operações do NinjaTrader 8.", "ninjatrader"),
                    ("As operações do QuantConnect.", "quantconnect"),
                    ("As operações do backtesting.py ou do vectorbt.", "backtesting-py"),
                    (
                        "O histórico de operações da sua corretora ou exchange em CSV ou Excel. "
                        "O Rigor reconhece o formato de exportação de "
                        + PLATFORMS_PT
                        + "; de qualquer outra corretora ou diário, as colunas são reconhecidas "
                        "pelo nome.",
                        "csv-universal",
                    ),
                    (
                        "Ou a sua curva de equity ou série de retornos em CSV ou Excel (diária, "
                        "semanal ou mensal), de qualquer mercado.",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Significância estatística",
                        "Se o seu Sharpe se distingue de zero, dados o tamanho, a assimetria e a "
                        "curtose do histórico.",
                    ),
                    (
                        "Número de tentativas",
                        "Quanto sobrevive depois de descontar as variantes que você testou.",
                    ),
                    (
                        "Custos",
                        "O que acontece com 1x, 2x e 3x o custo de operação, e o custo de "
                        "equilíbrio.",
                    ),
                    (
                        "Continua funcionando no período recente?",
                        "O último terço do histórico frente ao resto.",
                    ),
                    (
                        "Funciona em cada instrumento?",
                        "Operações, resultado líquido e taxa de acerto por símbolo, quando o "
                        "arquivo tem vários.",
                    ),
                    (
                        "Quanto capital pede",
                        "O capital que cada limite de perda exige, reamostrando um ano das suas "
                        "operações.",
                    ),
                ),
                limits=(
                    "Nunca se conecta à sua corretora ou exchange: audita o arquivo que você "
                    "envia.",
                    "Não recomenda operar e não prevê resultados.",
                ),
                faq=(
                    (
                        "Serve para cripto?",
                        "Sim. O Rigor não depende do mercado: mede o histórico que você envia. "
                        "Uma exportação do TradingView ou uma curva de equity da sua carteira "
                        "cripto serve igual a uma de ações.",
                    ),
                    (
                        "E se eu só tiver uma curva de equity?",
                        "Ela é auditada do mesmo jeito. Sem a lista de operações, os custos "
                        "ficam NOT_MEASURED e o relatório diz qual arquivo os mediria.",
                    ),
                ),
            ),
        },
    ),
    Audience(
        slug="retos-prop-firm",
        slug_en="prop-firm-challenges",
        slug_pt="desafios-prop-firm",
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
                    "Puedes pasar el reto y que el retiro se frene por la regla del mejor día "
                    "(consistencia) de la firma.",
                ),
                uploads=(
                    ("Tu informe de MetaTrader 5 o 4.", "mt5"),
                    ("Tu lista de operaciones de TradingView.", "tradingview"),
                    ("Tu CSV de NinjaTrader 8 (futuros).", "ninjatrader"),
                    (
                        "O el historial de operaciones de tu plataforma en CSV o Excel: Rigor "
                        "reconoce el formato de Tradovate, TopstepX, Rithmic, cTrader y Sierra "
                        "Chart, entre otros.",
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
                        "¿Con qué firma encaja tu historial?",
                        "Tu mismo historial con las reglas publicadas de cada firma, de más a "
                        "menos probabilidad de pasar, y si la regla del mejor día frenaría el "
                        "retiro. Compara reglas; no recomienda comprar ningún reto.",
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
                    "You can pass the challenge and still have the payout held up by the "
                    "firm's best-day (consistency) rule.",
                ),
                uploads=(
                    ("Your MetaTrader 5 or 4 report.", "mt5"),
                    ("Your TradingView list of trades.", "tradingview"),
                    ("Your NinjaTrader 8 CSV (futures).", "ninjatrader"),
                    (
                        "Or your platform's trade history as CSV or Excel: Rigor recognises the "
                        "format of Tradovate, TopstepX, Rithmic, cTrader and Sierra Chart, among "
                        "others.",
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
                        "Which firm does your history fit?",
                        "Your same history under each firm's published rules, from most to "
                        "least likely to pass, and whether the best-day rule would hold up the "
                        "payout. It compares rules; it does not recommend buying a challenge.",
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
            "pt": AudienceText(
                title="Antes de pagar um desafio de prop firm, simule-o com o seu histórico",
                summary=(
                    "Envie o seu backtest ou histórico e veja com que frequência você "
                    "tocaria o limite de perda diária ou total nos desafios da FTMO, "
                    "FundedNext, The5ers e Topstep, reamostrando as suas próprias operações."
                ),
                pains=(
                    "Você paga o desafio, uma sequência ruim toca a perda diária e você paga de "
                    "novo.",
                    "A sua estratégia pode ser sólida e mesmo assim não caber nas regras de "
                    "perda diária, perda total e prazo de um desafio.",
                    "Cada firma muda as suas regras, e compará-las não é fácil.",
                    "Você pode cumprir o desafio e mesmo assim ter o saque retido pela regra do "
                    "melhor dia (consistência) da firma.",
                ),
                uploads=(
                    ("O seu relatório do MetaTrader 5 ou 4.", "mt5"),
                    ("A sua lista de operações do TradingView.", "tradingview"),
                    ("O seu CSV do NinjaTrader 8 (futuros).", "ninjatrader"),
                    (
                        "Ou o histórico de operações da sua plataforma em CSV ou Excel: o Rigor "
                        "reconhece o formato do Tradovate, TopstepX, Rithmic, cTrader e Sierra "
                        "Chart, entre outros.",
                        "csv-universal",
                    ),
                    (
                        "Depois, no formulário, abra 'Adicionar mais arquivos' e escolha o "
                        "desafio a simular.",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Simulador de desafios",
                        "Reamostra o seu histórico milhares de vezes e conta com que frequência "
                        "a perda diária ou a perda total seria tocada, ou a meta não seria "
                        "alcançada no prazo.",
                    ),
                    (
                        "Com qual firma o seu histórico combina?",
                        "O mesmo histórico sob as regras publicadas de cada firma, da mais à "
                        "menos provável de cumprir, e se a regra do melhor dia reteria o saque. "
                        "Compara regras; não recomenda comprar um desafio.",
                    ),
                    (
                        "Regras com fonte e data",
                        "Cada desafio cita o site oficial da firma e a data em que as regras "
                        "foram lidas.",
                    ),
                    (
                        "Quanto capital pede e com que tamanho",
                        "O capital que a sua estratégia exige com limites de perda de 10, 20, 30 "
                        "e 50 %.",
                    ),
                    (
                        "Risco reamostrado em um ano",
                        "A queda provável da sua estratégia em um ano, com as suposições "
                        "escritas ao lado.",
                    ),
                    (
                        "Como se comporta quando perde",
                        "Se você segura as operações perdedoras por mais tempo ou volta a entrar "
                        "logo depois de uma perda.",
                    ),
                ),
                limits=(
                    "São estimativas com as suposições escritas, não uma previsão do desafio.",
                    "Confirme sempre as regras com a firma antes de pagar o desafio.",
                ),
                faq=(
                    (
                        "Quais firmas e desafios estão incluídos?",
                        "{presets} desafios da FTMO, FundedNext, The5ers e Topstep, mais um "
                        "genérico de duas fases. O formulário mostra a data em que as regras "
                        "foram lidas.",
                    ),
                    (
                        "Ele me diz se vou conseguir a conta?",
                        "Não. Diz com que frequência, repetindo o seu próprio histórico em outra "
                        "ordem, os limites do desafio seriam tocados. Mede o risco da sua "
                        "estratégia frente a essas regras.",
                    ),
                ),
            ),
        },
    ),
    Audience(
        slug="inversores-gestores-fondos",
        slug_en="investors-managers-funds",
        slug_pt="investidores-gestores-fundos",
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
            "pt": AudienceText(
                title="Antes de investir com um gestor, um sinal ou um fundo, revise o histórico",
                summary=(
                    "Envie o histórico da conta ou a série de retornos para separar o "
                    "resultado das operações dos depósitos, comparar a conta com o backtest "
                    "e medir se o histórico é evidência ou sorte."
                ),
                pains=(
                    "A porcentagem que mostram pode vir de depósitos e recargas, não das "
                    "operações.",
                    "Um histórico curto, ou com poucos meses muito bons, pode parecer um "
                    "histórico sólido.",
                    "O que o backtest mostra e o que a conta real faz nem sempre se parecem.",
                ),
                uploads=(
                    (
                        "O histórico da conta: o relatório do MetaTrader ou o CSV que o "
                        "Myfxbook, o FX Blue ou o sinal da MQL5 exportam.",
                        "cuenta-proveedor",
                    ),
                    (
                        "Ou a série de retornos (diária, semanal ou mensal) em CSV ou Excel, com "
                        "colunas de data e retorno.",
                        "",
                    ),
                    (
                        "Ou a tabela de rentabilidades mensais da lâmina, como está: uma linha "
                        "por ano e uma coluna por mês, em CSV ou Excel.",
                        "",
                    ),
                    ("Se houver, o backtest, para comparar com a conta.", "mt5"),
                ),
                checks=(
                    (
                        "O dinheiro real na conta",
                        "Depósitos e saques separados do resultado das operações; um aviso "
                        "quando a porcentagem é inflada por recargas ou há perdas ainda abertas.",
                    ),
                    (
                        "Backtest frente à conta real",
                        "A conta frente a milhares de histórias reamostradas do backtest, e "
                        "operação por operação nas mesmas datas.",
                    ),
                    (
                        "Significância estatística",
                        "Se o histórico se destaca do acaso, dado o seu tamanho.",
                    ),
                    ("Testes de estresse", "O resultado sem os seus melhores meses e operações."),
                    (
                        "Continua funcionando no período recente?",
                        "O último terço do histórico frente ao resto.",
                    ),
                    (
                        "O que quem investe num fundo revisaria",
                        "Com 24 meses ou mais: calendário ano por mês, retorno anual composto, "
                        "volatilidade, pior mês, queda mais funda, tempo para se recuperar e "
                        "duas verificações de retornos suavizados.",
                    ),
                    (
                        "Perguntas para o gestor",
                        "O que perguntar, a partir do que o arquivo dele não responde.",
                    ),
                ),
                limits=(
                    "Nunca se conecta à corretora dele nem ao seu dinheiro: audita o arquivo que "
                    "você envia.",
                    "Não diz se você deve investir; dá os números para decidir.",
                ),
                faq=(
                    (
                        "E se eu só tiver os retornos mensais?",
                        "Envie-os como série de retornos em CSV ou Excel, ou envie a tabela da "
                        "lâmina como está (uma linha por ano, meses como colunas, em português, "
                        "inglês, espanhol ou de 1 a 12). Se o total de um ano não bater com os "
                        "seus meses, o relatório diz isso. Com retornos mensais um histórico "
                        "curto tem poucos dados, e o relatório diz isso em vez de esconder.",
                    ),
                    (
                        "Como peço o histórico?",
                        "O guia da conta do fornecedor explica o que pedir no MetaTrader, "
                        "Myfxbook, FX Blue e sinais da MQL5.",
                    ),
                ),
            ),
        },
    ),
    # Last, so the landing's four cards keep pointing at the first four pages.
    Audience(
        slug="copiar-senales",
        slug_en="signal-copiers",
        slug_pt="copiar-sinais",
        icon="copy",
        text={
            "es": AudienceText(
                title="Antes de copiar una señal, mira el riesgo que no enseña",
                summary=(
                    "Sube el historial de la cuenta que vas a copiar y mira lo que su "
                    "porcentaje no dice: martingala, rejilla, operaciones sin stop, pérdidas "
                    "abiertas y depósitos."
                ),
                pains=(
                    "La señal enseña un porcentaje de acierto altísimo, y no ves si detrás hay "
                    "martingala, rejilla u operaciones sin stop.",
                    "Una cuenta puede subir durante meses de forma suave y perder casi todo en "
                    "una sola racha; la curva de saldo no enseña las pérdidas abiertas.",
                    "El porcentaje de ganancia puede venir de depósitos, y una captura de "
                    "pantalla no deja ver nada de esto.",
                ),
                uploads=(
                    (
                        "El historial de la cuenta que copias: el informe de MetaTrader o el CSV "
                        "que exporta Myfxbook, FX Blue o su señal de MQL5.",
                        "cuenta-proveedor",
                    ),
                    (
                        "O el historial de operaciones de su bróker en CSV o Excel, por ejemplo "
                        "el de eToro.",
                        "csv-universal",
                    ),
                ),
                checks=(
                    (
                        "Martingala y rejilla",
                        "Si el tamaño crece después de perder, o si se abren más posiciones "
                        "para promediar una pérdida.",
                    ),
                    (
                        "Sin stop de pérdida",
                        "Si las pérdidas más grandes son muchas veces la pérdida típica, una "
                        "señal de operaciones sin stop.",
                    ),
                    (
                        "Muchos aciertos pequeños y pérdidas grandes",
                        "Un porcentaje de acierto alto con pérdidas que se comen muchas "
                        "ganancias de golpe.",
                    ),
                    (
                        "Pérdidas abiertas que no se ven",
                        "Aviso cuando hay muchas posiciones abiertas a la vez, cuando la curva "
                        "no muestra su pérdida flotante y cuando al final quedan posiciones sin "
                        "cerrar.",
                    ),
                    (
                        "El dinero real de la cuenta",
                        "Depósitos y retiros separados del resultado de operar; aviso si el "
                        "porcentaje se infla con recargas o si se deposita en plena pérdida.",
                    ),
                    (
                        "Preguntas para el proveedor",
                        "Qué pedirle antes de copiar, a partir de lo que su historial no responde.",
                    ),
                ),
                limits=(
                    "No se conecta a la cuenta del proveedor ni copia operaciones: audita el "
                    "archivo que subes.",
                    "No te dice si copiar o no, y no predice resultados.",
                ),
                faq=(
                    (
                        "¿Y si la señal solo enseña capturas en Telegram?",
                        "Una captura no se puede auditar. Pide el historial exportado de la "
                        "cuenta (MetaTrader, Myfxbook, FX Blue o señal de MQL5); quien no puede "
                        "darlo ya te está dando una respuesta.",
                    ),
                    (
                        "¿Un historial sin banderas rojas es seguro de copiar?",
                        "No. El informe dice qué riesgos se ven en el pasado de esa cuenta. El "
                        "futuro depende del mercado, del tamaño que uses y de cómo lo copies.",
                    ),
                ),
            ),
            "en": AudienceText(
                title="Before you copy a signal, see the risk it does not show",
                summary=(
                    "Upload the history of the account you want to copy and see what its "
                    "percentage does not say: martingale, grids, trades without a stop, open "
                    "losses and deposits."
                ),
                pains=(
                    "The signal shows a very high win rate, and you cannot see whether "
                    "martingale, a grid or trades without a stop sit behind it.",
                    "An account can rise smoothly for months and lose almost everything in "
                    "one run; the balance curve does not show open losses.",
                    "The percentage gain can come from deposits, and a screenshot shows none "
                    "of this.",
                ),
                uploads=(
                    (
                        "The history of the account you copy: the MetaTrader report or the CSV "
                        "that Myfxbook, FX Blue or its MQL5 signal exports.",
                        "cuenta-proveedor",
                    ),
                    (
                        "Or the broker's trade history in CSV or Excel, for example eToro's.",
                        "csv-universal",
                    ),
                ),
                checks=(
                    (
                        "Martingale and grids",
                        "Whether the size grows after a loss, or more positions are opened to "
                        "average a loss down.",
                    ),
                    (
                        "No stop loss",
                        "Whether the largest losses are many times the typical loss, a sign of "
                        "trades without a stop.",
                    ),
                    (
                        "Many small wins and large losses",
                        "A high win rate with losses that wipe out many wins at once.",
                    ),
                    (
                        "Open losses you cannot see",
                        "A warning when many positions are open at once, when the curve does "
                        "not show their floating loss and when positions are still open at the "
                        "end.",
                    ),
                    (
                        "The real money in the account",
                        "Deposits and withdrawals separated from the trading result; a warning "
                        "if top-ups inflate the percentage or money is deposited in a deep "
                        "drawdown.",
                    ),
                    (
                        "Questions for the provider",
                        "What to ask before copying, drawn from what the history does not answer.",
                    ),
                ),
                limits=(
                    "It does not connect to the provider's account or copy trades: it audits "
                    "the file you upload.",
                    "It does not tell you whether to copy, and it does not predict results.",
                ),
                faq=(
                    (
                        "What if the signal only shows screenshots on Telegram?",
                        "A screenshot cannot be audited. Ask for the account's exported history "
                        "(MetaTrader, Myfxbook, FX Blue or MQL5 signal); a provider who cannot "
                        "give it is already giving you an answer.",
                    ),
                    (
                        "Is a history without red flags safe to copy?",
                        "No. The report says which risks show in that account's past. The "
                        "future depends on the market, the size you use and how you copy it.",
                    ),
                ),
            ),
            "pt": AudienceText(
                title="Antes de copiar um sinal, veja o risco que ele não mostra",
                summary=(
                    "Envie o histórico da conta que você quer copiar e veja o que a "
                    "porcentagem dela não diz: martingale, grades, operações sem stop, "
                    "perdas abertas e depósitos."
                ),
                pains=(
                    "O sinal mostra uma taxa de acerto muito alta, e você não vê se por trás há "
                    "martingale, uma grade ou operações sem stop.",
                    "Uma conta pode subir suave por meses e perder quase tudo de uma vez; a "
                    "curva de saldo não mostra as perdas abertas.",
                    "O ganho em porcentagem pode vir de depósitos, e um print não mostra nada "
                    "disso.",
                ),
                uploads=(
                    (
                        "O histórico da conta que você copia: o relatório do MetaTrader ou o CSV "
                        "que o Myfxbook, o FX Blue ou o sinal da MQL5 exportam.",
                        "cuenta-proveedor",
                    ),
                    (
                        "Ou o histórico de operações da corretora em CSV ou Excel, por exemplo o "
                        "do eToro.",
                        "csv-universal",
                    ),
                ),
                checks=(
                    (
                        "Martingale e grades",
                        "Se o tamanho cresce depois de uma perda, ou se abrem mais posições para "
                        "fazer preço médio de uma perda.",
                    ),
                    (
                        "Sem stop loss",
                        "Se as maiores perdas são muitas vezes a perda típica, sinal de "
                        "operações sem stop.",
                    ),
                    (
                        "Muitos ganhos pequenos e perdas grandes",
                        "Uma taxa de acerto alta com perdas que apagam muitos ganhos de uma vez.",
                    ),
                    (
                        "Perdas abertas que você não vê",
                        "Um aviso quando há muitas posições abertas ao mesmo tempo, quando a "
                        "curva não mostra a perda flutuante delas e quando ainda há posições "
                        "abertas no final.",
                    ),
                    (
                        "O dinheiro real na conta",
                        "Depósitos e saques separados do resultado das operações; um aviso se as "
                        "recargas inflam a porcentagem ou se entra dinheiro num drawdown "
                        "profundo.",
                    ),
                    (
                        "Perguntas para o fornecedor",
                        "O que perguntar antes de copiar, tirado do que o histórico não responde.",
                    ),
                ),
                limits=(
                    "Não se conecta à conta do fornecedor nem copia operações: audita o arquivo "
                    "que você envia.",
                    "Não diz se você deve copiar, e não prevê resultados.",
                ),
                faq=(
                    (
                        "E se o sinal só mostra prints no Telegram?",
                        "Um print não pode ser auditado. Peça o histórico exportado da conta "
                        "(MetaTrader, Myfxbook, FX Blue ou sinal da MQL5); um fornecedor que não "
                        "pode dá-lo já está dando uma resposta.",
                    ),
                    (
                        "Um histórico sem bandeiras vermelhas é seguro para copiar?",
                        "Não. O relatório diz quais riscos aparecem no passado dessa conta. O "
                        "futuro depende do mercado, do tamanho que você usa e de como você "
                        "copia.",
                    ),
                ),
            ),
        },
    ),
    Audience(
        slug="inversores-particulares",
        slug_en="retail-investors",
        slug_pt="investidores-pessoa-fisica",
        icon="globe",
        text={
            "es": AudienceText(
                title="Si inviertes por tu cuenta con DEGIRO, Trading 212, IBKR o XTB, revisa "
                "tu historial",
                summary=(
                    "Sube el historial de tu bróker o la evolución de tu cartera y mira si tu "
                    "resultado se distingue del azar, cuánto pesan las comisiones y cómo le fue "
                    "en caídas conocidas del mercado."
                ),
                pains=(
                    "Tu bróker te enseña cuánto subió tu cartera, pero no si eso se distingue "
                    "del azar ni cómo queda frente a un índice.",
                    "Las comisiones y el cambio de moneda se comen parte del resultado y no se "
                    "ven en una sola cifra.",
                    "Unas pocas operaciones o unos pocos meses muy buenos pueden sostener todo "
                    "el historial.",
                ),
                uploads=(
                    (
                        "El historial de operaciones de tu bróker en CSV o Excel: DEGIRO "
                        "(Transacciones), Trading 212 (historial), Interactive Brokers (Flex "
                        "Query o Activity Statement) o XTB (historial de posiciones cerradas).",
                        "csv-universal",
                    ),
                    (
                        "O la evolución de tu cartera: su valor o su rentabilidad por fecha "
                        "(diaria, semanal o mensual), en CSV o Excel.",
                        "",
                    ),
                    (
                        "Si quieres compararte con un índice, su serie en CSV en «Opciones "
                        "avanzadas» (Benchmark).",
                        "",
                    ),
                ),
                checks=(
                    (
                        "¿Se distingue del azar?",
                        "Si tu resultado se distingue de cero dada la longitud y la volatilidad "
                        "de tu historial.",
                    ),
                    (
                        "Frente al índice",
                        "Si subes la serie de un índice, tu resultado frente a él en las mismas "
                        "fechas.",
                    ),
                    (
                        "Lo que pesan las comisiones",
                        "Con tus operaciones y sus costes, qué queda con el doble y el triple "
                        "de comisiones.",
                    ),
                    (
                        "Tus mejores operaciones y meses",
                        "El resultado sin ellos, para ver si todo depende de unos pocos.",
                    ),
                    (
                        "Caídas conocidas del mercado",
                        "Cómo le fue a tu historial en 2008, en marzo de 2020 o en 2022, si tus "
                        "fechas cubren esas caídas completas.",
                    ),
                    (
                        "¿Sigue igual en el periodo reciente?",
                        "El último tercio del historial frente al resto.",
                    ),
                ),
                limits=(
                    "Con el historial de operaciones solo cuenta lo que ya vendiste: las "
                    "posiciones abiertas y los dividendos quedan fuera, y el informe lo dice. "
                    "Para verlo todo, sube la evolución de tu cartera.",
                    "No se conecta a tu bróker, no te dice qué comprar y no predice resultados.",
                ),
                faq=(
                    (
                        "Solo compro y mantengo, ¿me sirve?",
                        "Sí, con la evolución de tu cartera (su valor o su rentabilidad por "
                        "mes). Con el historial de operaciones solo verías lo que vendiste.",
                    ),
                    (
                        "¿Necesita la contraseña de mi bróker?",
                        "No. Solo el archivo que exportas tú; Rigor no se conecta a ningún bróker.",
                    ),
                ),
            ),
            "en": AudienceText(
                title="If you invest on your own with DEGIRO, Trading 212, IBKR or XTB, check "
                "your history",
                summary=(
                    "Upload your broker's history or your portfolio's value over time and see "
                    "whether your result stands out from luck, how much the fees weigh and how "
                    "it did through well-known market falls."
                ),
                pains=(
                    "Your broker shows how much your portfolio grew, but not whether that "
                    "stands out from luck or how it compares with an index.",
                    "Fees and currency conversion eat part of the result and do not show in a "
                    "single figure.",
                    "A few very good trades or months can carry the whole history.",
                ),
                uploads=(
                    (
                        "Your broker's trade history in CSV or Excel: DEGIRO (Transactions), "
                        "Trading 212 (history), Interactive Brokers (Flex Query or Activity "
                        "Statement) or XTB (closed position history).",
                        "csv-universal",
                    ),
                    (
                        "Or your portfolio over time: its value or its return by date (daily, "
                        "weekly or monthly), in CSV or Excel.",
                        "",
                    ),
                    (
                        "To compare yourself with an index, its series as a CSV under "
                        "'Advanced options' (Benchmark).",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Does it stand out from luck?",
                        "Whether your result is distinguishable from zero given the length and "
                        "volatility of your history.",
                    ),
                    (
                        "Against the index",
                        "If you upload an index series, your result against it over the same "
                        "dates.",
                    ),
                    (
                        "What the fees weigh",
                        "With your trades and their costs, what is left at double and triple fees.",
                    ),
                    (
                        "Your best trades and months",
                        "The result without them, to see whether everything rests on a few.",
                    ),
                    (
                        "Well-known market falls",
                        "How your history did in 2008, in March 2020 or in 2022, when your "
                        "dates cover those falls in full.",
                    ),
                    (
                        "Is it the same in the recent period?",
                        "The last third of the history against the rest.",
                    ),
                ),
                limits=(
                    "With the trade history it only counts what you already sold: open "
                    "positions and dividends are left out, and the report says so. To see "
                    "everything, upload your portfolio over time.",
                    "It does not connect to your broker, does not tell you what to buy and "
                    "does not predict results.",
                ),
                faq=(
                    (
                        "I only buy and hold. Does it work for me?",
                        "Yes, with your portfolio over time (its value or its return by "
                        "month). With the trade history you would only see what you sold.",
                    ),
                    (
                        "Does it need my broker password?",
                        "No. Only the file you export yourself; Rigor does not connect to any "
                        "broker.",
                    ),
                ),
            ),
            "pt": AudienceText(
                title=(
                    "Se você investe por conta própria com DEGIRO, Trading 212, IBKR ou XTB, "
                    "revise o seu histórico"
                ),
                summary=(
                    "Envie o histórico da sua corretora ou o valor da sua carteira ao longo "
                    "do tempo e veja se o seu resultado se destaca da sorte, quanto pesam as "
                    "taxas e como se saiu em quedas conhecidas do mercado."
                ),
                pains=(
                    "A sua corretora mostra quanto a sua carteira cresceu, mas não se isso se "
                    "destaca da sorte nem como se compara com um índice.",
                    "Taxas e conversão de moeda comem parte do resultado e não aparecem num "
                    "único número.",
                    "Poucas operações ou meses muito bons podem carregar o histórico inteiro.",
                ),
                uploads=(
                    (
                        "O histórico de operações da sua corretora em CSV ou Excel: DEGIRO "
                        "(Transações), Trading 212 (histórico), Interactive Brokers (Flex Query "
                        "ou Activity Statement) ou XTB (histórico de posições fechadas).",
                        "csv-universal",
                    ),
                    (
                        "Ou a sua carteira ao longo do tempo: o valor ou o retorno por data "
                        "(diário, semanal ou mensal), em CSV ou Excel.",
                        "",
                    ),
                    (
                        "Para se comparar com um índice, a série dele em CSV em 'Opções "
                        "avançadas' (Benchmark).",
                        "",
                    ),
                ),
                checks=(
                    (
                        "Destaca-se da sorte?",
                        "Se o seu resultado se distingue de zero, dados o tamanho e a "
                        "volatilidade do seu histórico.",
                    ),
                    (
                        "Frente ao índice",
                        "Se você enviar a série de um índice, o seu resultado frente a ele nas "
                        "mesmas datas.",
                    ),
                    (
                        "O que pesam as taxas",
                        "Com as suas operações e os seus custos, o que sobra com o dobro e o "
                        "triplo das taxas.",
                    ),
                    (
                        "As suas melhores operações e meses",
                        "O resultado sem eles, para ver se tudo se apoia em poucos.",
                    ),
                    (
                        "Quedas conhecidas do mercado",
                        "Como o seu histórico se saiu em 2008, em março de 2020 ou em 2022, "
                        "quando as suas datas cobrem essas quedas por inteiro.",
                    ),
                    ("É igual no período recente?", "O último terço do histórico frente ao resto."),
                ),
                limits=(
                    "Com o histórico de operações só conta o que você já vendeu: posições "
                    "abertas e dividendos ficam de fora, e o relatório diz isso. Para ver tudo, "
                    "envie a sua carteira ao longo do tempo.",
                    "Não se conecta à sua corretora, não diz o que comprar e não prevê resultados.",
                ),
                faq=(
                    (
                        "Eu só compro e mantenho. Serve para mim?",
                        "Sim, com a sua carteira ao longo do tempo (o valor ou o retorno por "
                        "mês). Com o histórico de operações você só veria o que vendeu.",
                    ),
                    (
                        "Precisa da senha da minha corretora?",
                        "Não. Só o arquivo que você mesmo exporta; o Rigor não se conecta a "
                        "nenhuma corretora.",
                    ),
                ),
            ),
        },
    ),
)

AUDIENCES_BY_PATH: dict[str, dict[str, Audience]] = {
    locale: {page.slug_for(locale): page for page in AUDIENCE_PAGES}
    for locale in ("es", "en", "pt")
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
    "PLATFORMS_PT",
    "RECOGNISED_PLATFORMS",
    "Audience",
    "AudienceText",
    "audience_url",
    "platform_list",
]
