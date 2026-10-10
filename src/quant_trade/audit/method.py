"""The public methodology page: what the audit tests, with which threshold,
and what it does not do.

A buyer who cannot tell a rigorous audit from a scoring gimmick decides on
trust signals: an independent operator, a published method, reproducible
numbers. Everything on this page that is a number comes from the code the
reports run (``verdict.DEFAULT_THRESHOLDS``, ``redflags.FLAG_TITLES``,
``report.CLASS_LADDER``), so the page cannot drift from the reports. The
text passes the profit-claim guard in Spanish, English and Portuguese (tested).
"""

from __future__ import annotations

from quant_trade.audit.redflags import FLAG_TITLES
from quant_trade.audit.verdict import DEFAULT_THRESHOLDS, Thresholds

#: The page's path in each language.
METHOD_PATH: dict[str, str] = {
    "es": "/metodologia",
    "en": "/methodology",
    "pt": "/pt/metodologia",
}

#: Published sources of the estimators the audit applies.
REFERENCES: tuple[str, ...] = (
    "Bailey, D. H. y López de Prado, M. (2012). The Sharpe Ratio Efficient Frontier. "
    "Journal of Risk 15(2).",
    "Bailey, D. H. y López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for "
    "Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio "
    "Management 40(5).",
    "Bailey, D. H., Borwein, J., López de Prado, M. y Zhu, Q. J. (2017). The Probability "
    "of Backtest Overfitting. Journal of Computational Finance 20(4).",
    # The haircut after the search (luck.py), the Sharpe corrected for autocorrelation
    # (engine.autocorrelation_adjusted_sharpe) and the test for a change in the mean
    # (breaks.py): the report names all three next to their figures.
    "Harvey, C. R. y Liu, Y. (2015). Backtesting. Journal of Portfolio Management 42(1).",
    "Lo, A. W. (2002). The Statistics of Sharpe Ratios. Financial Analysts Journal 58(4).",
    "Ploberger, W. y Krämer, W. (1992). The CUSUM Test with OLS Residuals. Econometrica 60(2).",
    "Politis, D. N. y Romano, J. P. (1994). The Stationary Bootstrap. Journal of the "
    "American Statistical Association 89(428).",
)


#: The prop-firm challenge simulator's section of the page, from
#: ``analytics.simulate_challenge`` and its ``CHALLENGE_ASSUMPTIONS`` and the
#: report's own notes beside the simulator (source, date, open losses). It has
#: no new figure. Its own table, not ``COPY``: ``report_pt`` installs the
#: Portuguese ``COPY`` over the English one, which would show this in English.
CHALLENGE_SECTION: dict[str, tuple[str, list[str]]] = {
    "es": (
        "Simulador de retos de prop firm",
        [
            "Remuestrea tu historial en bloques de días consecutivos (bootstrap "
            "estacionario) y recorre miles de caminos diarios por las reglas de una fase "
            "del reto.",
            "Cada camino se revisa en cada cierre diario, en este orden: la pérdida diaria, "
            "la pérdida total y el objetivo, que solo cuenta con los días mínimos operados. "
            "Cada día con retorno distinto de cero cuenta como día operado.",
            "Las reglas de cada firma son las publicadas en su web oficial: el informe cita "
            "la fuente y la fecha en que se leyeron, y pueden haber cambiado después. Las "
            "reglas genéricas son una referencia típica de las evaluaciones en dos fases, "
            "no las de ninguna firma.",
            "Con cierres diarios no se ve el drawdown flotante dentro del día, y un balance "
            "de operaciones cerradas no ve las pérdidas de las operaciones abiertas: una "
            "firma que cuenta la pérdida diaria con posiciones abiertas puede cortar un "
            "camino que aquí sigue en marcha. Por eso la estimación es optimista frente a "
            "los límites diarios y totales; si tu plataforma imprime un drawdown con "
            "operaciones abiertas mayor que el límite total, el informe lo avisa junto al "
            "simulador.",
            "Es una estimación remuestreada del historial aportado, no una predicción, y "
            "supone que el futuro se parece al historial. No cambia la clase.",
        ],
    ),
    "en": (
        "Prop-firm challenge simulator",
        [
            "It resamples your history in blocks of consecutive days (stationary bootstrap) "
            "and walks thousands of daily paths through the rules of one challenge phase.",
            "Each path is checked at every daily close, in this order: the daily loss, the "
            "total loss and the target, which only counts once the minimum trading days are "
            "reached. Every day with a non-zero return counts as a trading day.",
            "Each firm's rules are those posted on its official website: the report cites "
            "the source and the date they were read, and they may have changed since. The "
            "generic rules are a reference typical of two-step evaluations, not any one "
            "firm's terms.",
            "Daily closes cannot see floating drawdown within the day, and a closed-trade "
            "balance cannot see the losses of open trades: a firm that counts the daily loss "
            "with open positions can stop a path that is still running here. That is why the "
            "estimate is optimistic against the daily and total limits; when your platform "
            "prints an open-trade drawdown beyond the total limit, the report says so next "
            "to the simulator.",
            "It is a resampled estimate from the supplied history, not a prediction, and it "
            "assumes the future resembles the history. It does not change the class.",
        ],
    ),
    "pt": (
        "Simulador de desafios de prop firm",
        [
            "Reamostra o seu histórico em blocos de dias consecutivos (bootstrap "
            "estacionário) e percorre milhares de caminhos diários pelas regras de uma fase "
            "do desafio.",
            "Cada caminho é revisado em cada fechamento diário, nesta ordem: a perda "
            "diária, a perda total e o objetivo, que só conta depois dos dias mínimos "
            "operados. Cada dia com retorno diferente de zero conta como dia operado.",
            "As regras de cada mesa são as publicadas no site oficial dela: o relatório cita "
            "a fonte e a data em que foram lidas, e elas podem ter mudado depois. As regras "
            "genéricas são uma referência típica das avaliações em duas fases, não as de "
            "nenhuma mesa.",
            "Com fechamentos diários não se vê o drawdown flutuante dentro do dia, e um saldo "
            "de operações fechadas não vê as perdas das operações abertas: uma mesa que conta "
            "a perda diária com posições abertas pode encerrar um caminho que aqui continua. "
            "Por isso a estimativa é otimista frente aos limites diários e totais; quando a "
            "sua plataforma imprime um drawdown com operações abertas além do limite total, "
            "o relatório avisa junto ao simulador.",
            "É uma estimativa reamostrada do histórico fornecido, não uma previsão, e supõe "
            "que o futuro se parece com o histórico. Não muda a classe.",
        ],
    ),
}


#: The references join their authors with the Spanish "y"; each page uses its own word.
_REFERENCE_AND: dict[str, str] = {"es": "y", "en": "and", "pt": "e"}


def references(locale: str) -> tuple[str, ...]:
    """The sources with the authors joined in the page's language."""
    word = _REFERENCE_AND.get(locale, "y")
    return tuple(ref.replace(" y ", f" {word} ") for ref in REFERENCES)


def method_url(locale: str) -> str:
    return METHOD_PATH.get(locale, METHOD_PATH["es"])


def dimension_rows(locale: str, t: Thresholds = DEFAULT_THRESHOLDS) -> list[tuple[str, str, str]]:
    """``(question, what is measured, what it takes to pass)`` per dimension."""
    if locale == "pt":
        return [
            (
                "O resultado se distingue do acaso?",
                "Sharpe probabilístico (tamanho, assimetria e curtose) e bootstrap "
                "estacionário por blocos dos retornos.",
                f"PSR ≥ {t.psr_pass:.2f} e o percentil 5 do Sharpe do bootstrap acima de zero; "
                f"fraco a partir de PSR {t.psr_weak:.2f}.",
            ),
            (
                "Aguenta o número de tentativas?",
                "Sharpe deflacionado com o maior número entre as tentativas declaradas, as "
                "variantes enviadas e as passagens de otimização do MT5; PBO por validação "
                "cruzada combinatória quando você envia variantes.",
                f"DSR ≥ {t.dsr_pass:.2f} e PBO abaixo de {t.pbo_max:.2f}; fraco a partir de DSR "
                f"{t.dsr_weak:.2f}.",
            ),
            (
                "Aguenta os custos de operar?",
                "Cada operação recalculada com 1x, 2x e 3x o custo, e o custo de equilíbrio.",
                f"Continua positivo com {t.cost_pass_multiplier:.0f}x o custo de referência.",
            ),
            (
                "O trecho fora da amostra se sustenta?",
                "Sharpe depois do início fora da amostra que você declara e a sua distância "
                "do Sharpe dentro da amostra.",
                f"Sharpe fora da amostra ≥ {t.oos_sharpe_pass:.1f} e uma distância de no "
                f"máximo {t.oos_gap_max:.1f}.",
            ),
            (
                "Os dados estão sãos?",
                f"{len(FLAG_TITLES)} bandeiras vermelhas: duplicados, saltos, valores "
                "congelados, martingale, grade, depósitos, modelagem do backtest e mais.",
                "Nenhuma bandeira. Uma bandeira grave reprova a dimensão; um aviso a deixa "
                "como fraca.",
            ),
            (
                "Supera o que você poderia ter tido sem fazer nada?",
                "Excesso de retorno, razão de drawdown e razão de informação frente ao "
                "benchmark que você enviar.",
                f"Excesso de retorno e razão de informação positivos, com um drawdown de no "
                f"máximo {t.benchmark_drawdown_ratio_max:.0f}x o do benchmark.",
            ),
        ]
    if locale == "en":
        return [
            (
                "Is the result distinguishable from chance?",
                "Probabilistic Sharpe ratio (length, skew and kurtosis) and a stationary "
                "block bootstrap of the returns.",
                f"PSR ≥ {t.psr_pass:.2f} and the bootstrap's 5th percentile Sharpe above zero; "
                f"weak from PSR {t.psr_weak:.2f}.",
            ),
            (
                "Does it survive the number of trials?",
                "Deflated Sharpe ratio at the largest of the declared trials, the uploaded "
                "variants and the MT5 optimisation passes; PBO by combinatorial cross-validation "
                "when variants are uploaded.",
                f"DSR ≥ {t.dsr_pass:.2f} and PBO below {t.pbo_max:.2f}; weak from DSR "
                f"{t.dsr_weak:.2f}.",
            ),
            (
                "Does it survive trading costs?",
                "Every trade re-costed at 1x, 2x and 3x the cost, and the break-even cost.",
                f"Still positive at {t.cost_pass_multiplier:.0f}x the reference cost.",
            ),
            (
                "Does the out-of-sample stretch hold?",
                "Sharpe after the out-of-sample start you declare, and its gap to the in-sample "
                "Sharpe.",
                f"Out-of-sample Sharpe ≥ {t.oos_sharpe_pass:.1f} and a gap of at most "
                f"{t.oos_gap_max:.1f}.",
            ),
            (
                "Is the data sound?",
                f"{len(FLAG_TITLES)} red flags: duplicates, spikes, frozen marks, martingale, "
                "grid, deposits, backtest modelling and more.",
                "No red flag. A serious flag fails the dimension; a warning makes it weak.",
            ),
            (
                "Does it beat what you could have held instead?",
                "Excess return, drawdown ratio and information ratio against the benchmark you "
                "upload.",
                f"Positive excess return and information ratio, with a drawdown at most "
                f"{t.benchmark_drawdown_ratio_max:.0f}x the benchmark's.",
            ),
        ]
    return [
        (
            "¿Se distingue el resultado del azar?",
            "Sharpe probabilístico (longitud, asimetría y curtosis) y bootstrap estacionario "
            "por bloques de los retornos.",
            f"PSR ≥ {t.psr_pass:.2f} y el percentil 5 del Sharpe del bootstrap por encima de "
            f"cero; débil desde PSR {t.psr_weak:.2f}.",
        ),
        (
            "¿Aguanta el número de intentos?",
            "Sharpe deflactado con el mayor número entre los intentos declarados, las "
            "variantes subidas y las pasadas de optimización de MT5; PBO por validación "
            "cruzada combinatoria cuando subes variantes.",
            f"DSR ≥ {t.dsr_pass:.2f} y PBO por debajo de {t.pbo_max:.2f}; débil desde DSR "
            f"{t.dsr_weak:.2f}.",
        ),
        (
            "¿Aguanta los costos de operar?",
            "Cada operación recalculada a 1x, 2x y 3x el costo, y el costo de equilibrio.",
            f"Sigue en positivo a {t.cost_pass_multiplier:.0f}x el costo de referencia.",
        ),
        (
            "¿Aguanta el tramo fuera de muestra?",
            "Sharpe después del inicio fuera de muestra que declaras y su distancia al "
            "Sharpe dentro de muestra.",
            f"Sharpe fuera de muestra ≥ {t.oos_sharpe_pass:.1f} y una distancia de "
            f"{t.oos_gap_max:.1f} como máximo.",
        ),
        (
            "¿Los datos están sanos?",
            f"{len(FLAG_TITLES)} banderas rojas: duplicados, saltos, valores congelados, "
            "martingala, rejilla, depósitos, modelado del backtest y más.",
            "Ninguna bandera. Una bandera grave hace que no supere; un aviso la deja en débil.",
        ),
        (
            "¿Supera a lo que podrías haber tenido sin hacer nada?",
            "Exceso de retorno, ratio de drawdown y ratio de información frente al benchmark "
            "que subas.",
            f"Exceso de retorno y ratio de información positivos, con un drawdown de como "
            f"mucho {t.benchmark_drawdown_ratio_max:.0f}x el del benchmark.",
        ),
    ]


COPY: dict[str, dict[str, object]] = {
    "es": {
        "eyebrow": "Metodología",
        "title": "Cómo auditamos",
        "summary": (
            "Qué prueba Rigor, con qué umbral y con qué fuentes, qué quiere decir cada "
            "etiqueta y qué no hace. Las cifras de esta página son las mismas que usa el motor."
        ),
        "independence_title": "Independencia",
        "independence": [
            "Rigor no vende robots, señales, cursos ni cuentas de fondeo, y sus páginas no "
            "llevan enlaces de afiliado.",
            "El precio del informe es el mismo sea cual sea la clase que salga: no cobramos "
            "más por una clase mejor.",
            "No operamos, no custodiamos dinero ni claves y no nos conectamos a ningún bróker.",
        ],
        "dims_title": "Seis preguntas, un umbral cada una",
        "col_pass": "Qué hace falta para superar",
        "ladder_title": "Cómo sale la clase de A a D",
        "evidence_title": "Qué quiere decir cada etiqueta",
        "evidence": [
            ("MEASURED", "Lo calculamos nosotros a partir de tu archivo."),
            ("DECLARED", "Lo dijiste tú o lo dice tu plataforma; no lo podemos comprobar."),
            ("NOT_MEASURED", "Faltaban datos para medirlo, y el informe dice cuáles."),
        ],
        "flags_title": "Las banderas rojas que revisamos",
        "resampling_title": "Remuestreo y Monte Carlo",
        "resampling": [
            "Varias cifras del informe salen de simulaciones de Monte Carlo: miles de sorteos "
            "sobre el historial que subes, resumidos en percentiles y probabilidades.",
            "Prueba de azar: un bootstrap estacionario por bloques de los retornos da el "
            "percentil 5 del Sharpe que pide la primera pregunta.",
            "Riesgo remuestreado a un año: historias de un año armadas con bloques de los "
            "retornos (bootstrap estacionario) dan la caída máxima mediana, la de 1 de cada 20 "
            "y la probabilidad de cada caída.",
            "Órdenes al azar: los mismos retornos barajados, con el mismo Sharpe y el mismo "
            "resultado final, dicen si la peor caída del archivo es habitual para ellos. Con "
            "operaciones, la racha perdedora más larga se compara con la de las mismas "
            "operaciones en orden al azar, calculada de forma exacta.",
            "Un Monte Carlo supone que el orden del historial es intercambiable y remuestrea lo "
            "que este contiene: no corrige el sobreajuste ni la búsqueda de configuraciones, que "
            "miden el Sharpe deflactado, el PBO y el tramo fuera de muestra. El riesgo "
            "remuestreado, los órdenes al azar y las rachas no cambian la clase.",
        ],
        "repro_title": "Reproducible",
        "repro": [
            "Cada archivo queda identificado por su huella SHA-256 en el informe.",
            "El remuestreo usa una semilla fija que el informe imprime: el mismo archivo con "
            "las mismas declaraciones da los mismos números.",
            "El informe imprime la versión del motor que lo generó.",
        ],
        "limits_title": "Lo que no hace",
        "limits": [
            "No predice resultados futuros: mide la evidencia que hay en los datos que subes.",
            "Lee los archivos tal como llegan; no los comprueba con el bróker.",
            "No recomienda comprar, vender, copiar ni invertir en nada.",
            "Un informe no es una opinión legal, fiscal ni de inversión.",
        ],
        "refs_title": "Fuentes",
        "data_title": "Datos públicos que usamos",
        "data": [
            "Tipos de cambio de la Reserva Federal, letra del Tesoro y precios al consumidor de "
            "EE. UU.: FRED, Banco de la Reserva Federal de St. Louis. El VIX es de Cboe Global "
            "Markets, vía FRED.",
            "Tasa a un día del euro (€STR, vía FRED) y, antes de octubre de 2019, la tasa de "
            "las operaciones principales de financiación del BCE (la tasa fija o, en las "
            "subastas a tipo variable, la tasa mínima de puja) hasta octubre de 2008 y la tasa "
            "de la facilidad de depósito del BCE después. Fuente: estadísticas del BCE; estos "
            "datos están disponibles gratis en el sitio web del BCE (ecb.europa.eu).",
            "Tasa a un día de la libra (vía FRED): SONIA data licensed under the Open Government "
            "Licence v3.0 and copyright the Governor and Company of the Bank of England.",
            "Tasa a un día de Canadá (CORRA): Banco de Canadá; la convertimos a rendimiento "
            "anual, y estos datos están disponibles gratis en bankofcanada.ca.",
            "Tasa Selic mensual de Brasil: Banco Central do Brasil, serie 4189, bajo la Open "
            "Database License (ODbL).",
            "Tasas de política monetaria de México, Japón, Suiza, Australia, Nueva Zelanda, "
            "India, Sudáfrica, Corea del Sur, Suecia, Noruega, Dinamarca, Polonia, Chequia, "
            "Hungría, Rumanía, Islandia, Turquía, Israel, Arabia Saudita, Indonesia, Tailandia, "
            "Malasia, Chile, Colombia y Perú. Fuente: BIS (Banco de Pagos Internacionales). Son "
            "las tasas oficiales de cada banco central, no tasas de mercado.",
            "Precios al consumidor de la zona del euro y de Suiza: Eurostat.",
            "Precios al consumidor del Reino Unido: Office for National Statistics, bajo la "
            "Open Government Licence v3.0.",
            "Precios al consumidor de Canadá: Banco de Canadá (IPC de Statistics Canada); estos "
            "datos están disponibles gratis en bankofcanada.ca.",
            "Precios al consumidor de Brasil: Banco Central do Brasil (IPCA del IBGE).",
            "Precios al consumidor de México. Fuente: INEGI, Índice Nacional de Precios al "
            "Consumidor (INPC); lo usamos para descontar la inflación de los saldos.",
            "Precios al consumidor de Japón: elaborado a partir del Índice de Precios al "
            "Consumidor (Statistics Bureau, Ministry of Internal Affairs and Communications), "
            "vía e-Stat.",
            "Todos se leen al generar el informe y no cambian la clase.",
            "No mostramos cierres del S&P 500, del Nasdaq 100 ni de bitcoin: ninguna fuente "
            "pública permite reutilizarlos en un informe de pago. Las cifras de caídas "
            "históricas de la tabla de crisis son hechos fijos, no datos que leamos.",
        ],
    },
    "en": {
        "eyebrow": "Methodology",
        "title": "How we audit",
        "summary": (
            "What Rigor tests, with which threshold and which sources, what each label means "
            "and what it does not do. The figures on this page are the ones the engine uses."
        ),
        "independence_title": "Independence",
        "independence": [
            "Rigor sells no robots, signals, courses or funded accounts, and its pages carry no "
            "affiliate links.",
            "The report costs the same whatever class it gets: a better class never costs more.",
            "We do not trade, hold money or keys, or connect to any broker.",
        ],
        "dims_title": "Six questions, one threshold each",
        "col_pass": "What it takes to pass",
        "ladder_title": "How the A to D class is set",
        "evidence_title": "What each label means",
        "evidence": [
            ("MEASURED", "We computed it from your file."),
            ("DECLARED", "You or your platform stated it; we cannot check it."),
            ("NOT_MEASURED", "Data to measure it was missing, and the report says which."),
        ],
        "flags_title": "The red flags we check",
        "resampling_title": "Resampling and Monte Carlo",
        "resampling": [
            "Several figures in the report come from Monte Carlo simulations: thousands of draws "
            "on the history you upload, summarised as percentiles and probabilities.",
            "Test against chance: a stationary block bootstrap of the returns gives the 5th "
            "percentile Sharpe the first question requires.",
            "Resampled one-year risk: one-year histories built from blocks of the returns "
            "(stationary bootstrap) give the median maximum drawdown, the 1-in-20 one and the "
            "probability of each fall.",
            "Random orders: the same returns shuffled, with the same Sharpe and final result, "
            "show whether the file's worst fall is usual for them. With trades, the longest "
            "losing streak is compared with that of the same trades in random order, computed "
            "exactly.",
            "A Monte Carlo assumes the history's order is exchangeable and resamples what the "
            "history contains: it does not correct overfitting or the search for configurations, "
            "which deflated Sharpe, PBO and the out-of-sample stretch measure. The resampled "
            "risk, the random orders and the streaks do not change the class.",
        ],
        "repro_title": "Reproducible",
        "repro": [
            "Every file is identified in the report by its SHA-256 fingerprint.",
            "Resampling uses a fixed seed the report prints: the same file with the same "
            "declarations gives the same numbers.",
            "The report prints the engine version that produced it.",
        ],
        "limits_title": "What it does not do",
        "limits": [
            "It does not predict future results: it measures the evidence in the data you upload.",
            "It reads the files as they arrive; it does not check them with the broker.",
            "It does not recommend buying, selling, copying or investing in anything.",
            "A report is not legal, tax or investment advice.",
        ],
        "refs_title": "Sources",
        "data_title": "Public data we use",
        "data": [
            "The Federal Reserve's exchange rates, the US Treasury bill and US consumer prices: "
            "FRED, Federal Reserve Bank of St. Louis. The VIX is Cboe Global Markets', through "
            "FRED.",
            "The euro overnight rate (€STR, through FRED) and, before October 2019, the ECB's "
            "main refinancing operations rate (the fixed rate or, in the variable-rate "
            "tenders, the minimum bid rate) until October 2008 and the ECB's deposit facility "
            "rate after. Source: ECB statistics; this data is available free of "
            "charge on the ECB's website (ecb.europa.eu).",
            "The sterling overnight rate (through FRED): SONIA data licensed under the Open "
            "Government Licence v3.0 and copyright the Governor and Company of the Bank of "
            "England.",
            "Canada's overnight rate (CORRA): Bank of Canada; we convert it to an annual yield, "
            "and this data is available free of charge at bankofcanada.ca.",
            "Brazil's monthly Selic rate: Banco Central do Brasil, series 4189, under the Open "
            "Database License (ODbL).",
            "Policy rates of Mexico, Japan, Switzerland, Australia, New Zealand, India, South "
            "Africa, South Korea, Sweden, Norway, Denmark, Poland, Czechia, Hungary, Romania, "
            "Iceland, Türkiye, Israel, Saudi Arabia, Indonesia, Thailand, Malaysia, Chile, "
            "Colombia and Peru. Source: BIS (Bank for International Settlements). They are each "
            "central bank's official rate, not market rates.",
            "Consumer prices for the euro area and Switzerland: Eurostat.",
            "Consumer prices for the United Kingdom: Office for National Statistics, licensed "
            "under the Open Government Licence v3.0.",
            "Consumer prices for Canada: Bank of Canada (Statistics Canada's CPI); this data is "
            "available free of charge at bankofcanada.ca.",
            "Consumer prices for Brazil: Banco Central do Brasil (IBGE's IPCA).",
            "Consumer prices for Mexico. Source: INEGI, Índice Nacional de Precios al "
            "Consumidor (INPC); we use it to take inflation out of the balances.",
            "Consumer prices for Japan: created by editing the Consumer Price Index "
            "(Statistics Bureau, Ministry of Internal Affairs and Communications), through "
            "e-Stat.",
            "All are read when the report is made and none changes the class.",
            "We show no S&P 500, Nasdaq 100 or bitcoin closes: no public source allows their "
            "reuse in a paid report. The historical falls in the crisis table are fixed facts, "
            "not data we read.",
        ],
    },
    "pt": {
        "eyebrow": "Metodologia",
        "title": "Como auditamos",
        "summary": (
            "O que o Rigor testa, com qual limite e com quais fontes, o que cada etiqueta "
            "quer dizer e o que ele não faz. Os números desta página são os mesmos que o "
            "motor usa."
        ),
        "independence_title": "Independência",
        "independence": [
            "O Rigor não vende robôs, sinais, cursos nem contas de mesa proprietária, e as "
            "suas páginas não têm links de afiliado.",
            "O preço do relatório é o mesmo qualquer que seja a classe: uma classe melhor "
            "nunca custa mais.",
            "Não operamos, não guardamos dinheiro nem chaves e não nos conectamos a nenhuma "
            "corretora.",
        ],
        "dims_title": "Seis perguntas, um limite cada uma",
        "col_pass": "O que é preciso para passar",
        "ladder_title": "Como sai a classe de A a D",
        "evidence_title": "O que cada etiqueta quer dizer",
        "evidence": [
            ("MEASURED", "Nós calculamos a partir do seu arquivo."),
            ("DECLARED", "Você ou a sua plataforma afirmou; não podemos conferir."),
            ("NOT_MEASURED", "Faltavam dados para medir, e o relatório diz quais."),
        ],
        "flags_title": "As bandeiras vermelhas que revisamos",
        "resampling_title": "Reamostragem e Monte Carlo",
        "resampling": [
            "Vários números do relatório saem de simulações de Monte Carlo: milhares de sorteios "
            "sobre o histórico que você envia, resumidos em percentis e probabilidades.",
            "Teste contra o acaso: um bootstrap estacionário por blocos dos retornos dá o "
            "percentil 5 do Sharpe que a primeira pergunta exige.",
            "Risco reamostrado em um ano: históricos de um ano montados com blocos dos retornos "
            "(bootstrap estacionário) dão a queda máxima mediana, a de 1 em cada 20 e a "
            "probabilidade de cada queda.",
            "Ordens aleatórias: os mesmos retornos embaralhados, com o mesmo Sharpe e o mesmo "
            "resultado final, mostram se a pior queda do arquivo é habitual para eles. Com "
            "operações, a maior sequência de perdas é comparada com a das mesmas operações em "
            "ordem aleatória, calculada de forma exata.",
            "Um Monte Carlo supõe que a ordem do histórico é intercambiável e reamostra o que "
            "ele contém: não corrige o sobreajuste nem a busca de configurações, que o Sharpe "
            "deflacionado, o PBO e o trecho fora da amostra medem. O risco reamostrado, as "
            "ordens aleatórias e as sequências não mudam a classe.",
        ],
        "repro_title": "Reproduzível",
        "repro": [
            "Cada arquivo fica identificado no relatório pela sua impressão digital SHA-256.",
            "A reamostragem usa uma semente fixa que o relatório imprime: o mesmo arquivo com "
            "as mesmas declarações dá os mesmos números.",
            "O relatório imprime a versão do motor que o gerou.",
        ],
        "limits_title": "O que ele não faz",
        "limits": [
            "Não prevê resultados futuros: mede a evidência que há nos dados que você envia.",
            "Lê os arquivos como chegam; não os confere com a corretora.",
            "Não recomenda comprar, vender, copiar nem investir em nada.",
            "Um relatório não é aconselhamento jurídico, fiscal nem de investimento.",
        ],
        "refs_title": "Fontes",
        "data_title": "Dados públicos que usamos",
        "data": [
            "Cotações do Federal Reserve, letra do Tesouro e preços ao consumidor dos EUA: "
            "FRED, Federal Reserve Bank of St. Louis. O VIX é da Cboe Global Markets, via FRED.",
            "Taxa de um dia do euro (€STR, via FRED) e, antes de outubro de 2019, a taxa da "
            "facilidade de depósito do BCE. Fonte: estatísticas do BCE; esses dados estão "
            "disponíveis grátis no site do BCE (ecb.europa.eu).",
            "Taxa de um dia da libra (via FRED): SONIA data licensed under the Open Government "
            "Licence v3.0 and copyright the Governor and Company of the Bank of England.",
            "Taxa de um dia do Canadá (CORRA): Banco do Canadá; nós a convertemos em rendimento "
            "anual, e esses dados estão disponíveis grátis em bankofcanada.ca.",
            "Taxa Selic mensal do Brasil: Banco Central do Brasil, série 4189, sob a Open "
            "Database License (ODbL).",
            "Taxas de política monetária do México, do Japão, da Suíça, da Austrália, da Nova "
            "Zelândia, da Índia, da África do Sul, da Coreia do Sul, da Suécia, da Noruega, da "
            "Dinamarca, da Polônia, da Tchéquia, da Hungria, da Romênia, da Islândia, da "
            "Turquia, de Israel, da Arábia Saudita, da Indonésia, da Tailândia, da Malásia, do "
            "Chile, da Colômbia e do Peru. Fonte: BIS (Banco de Compensações Internacionais). "
            "São as taxas oficiais de cada banco central, não taxas de mercado.",
            "Preços ao consumidor da zona do euro e da Suíça: Eurostat.",
            "Preços ao consumidor do Reino Unido: Office for National Statistics, sob a Open "
            "Government Licence v3.0.",
            "Preços ao consumidor do Canadá: Banco do Canadá (IPC da Statistics Canada); esses "
            "dados estão disponíveis grátis em bankofcanada.ca.",
            "Preços ao consumidor do Brasil: Banco Central do Brasil (IPCA do IBGE).",
            "Preços ao consumidor do México. Fonte: INEGI, Índice Nacional de Precios al "
            "Consumidor (INPC); usamos para descontar a inflação dos saldos.",
            "Preços ao consumidor do Japão: elaborado a partir do Índice de Preços ao "
            "Consumidor (Statistics Bureau, Ministry of Internal Affairs and Communications), "
            "via e-Stat.",
            "Todos são lidos ao gerar o relatório e nenhum muda a classe.",
            "Não mostramos fechamentos do S&P 500, do Nasdaq 100 nem do bitcoin: nenhuma fonte "
            "pública permite reutilizá-los em um relatório pago. As quedas históricas da tabela "
            "de crises são fatos fixos, não dados que lemos.",
        ],
    },
}


__all__ = [
    "CHALLENGE_SECTION",
    "COPY",
    "METHOD_PATH",
    "REFERENCES",
    "dimension_rows",
    "method_url",
    "references",
]
