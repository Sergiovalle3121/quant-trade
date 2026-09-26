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
    "Politis, D. N. y Romano, J. P. (1994). The Stationary Bootstrap. Journal of the "
    "American Statistical Association 89(428).",
)


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
            "¿Aguanta los costes de operar?",
            "Cada operación recalculada a 1x, 2x y 3x el coste, y el coste de equilibrio.",
            f"Sigue en positivo a {t.cost_pass_multiplier:.0f}x el coste de referencia.",
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
            "Tipos de cambio, tasas y precios de EE. UU., cierres de mercados y otras tasas de "
            "efectivo: FRED, Banco de la Reserva Federal de St. Louis.",
            "Precios al consumidor del euro y de Suiza: Eurostat.",
            "Precios al consumidor del Reino Unido: Office for National Statistics, bajo la "
            "Open Government Licence v3.0.",
            "Precios al consumidor de Canadá: Banco de Canadá (IPC de Statistics Canada); estos "
            "datos están disponibles gratis en bankofcanada.ca.",
            "Precios al consumidor de Brasil: Banco Central do Brasil (IPCA del IBGE).",
            "Todos se leen al generar el informe y no cambian la clase.",
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
            "Exchange rates, US rates and prices, market closes and other cash rates: FRED, "
            "Federal Reserve Bank of St. Louis.",
            "Consumer prices for the euro and Switzerland: Eurostat.",
            "Consumer prices for the United Kingdom: Office for National Statistics, licensed "
            "under the Open Government Licence v3.0.",
            "Consumer prices for Canada: Bank of Canada (Statistics Canada's CPI); this data is "
            "available free of charge at bankofcanada.ca.",
            "Consumer prices for Brazil: Banco Central do Brasil (IBGE's IPCA).",
            "All are read when the report is made and none changes the class.",
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
            "Cotações, taxas e preços dos EUA, fechamentos de mercados e outras taxas de caixa: "
            "FRED, Federal Reserve Bank of St. Louis.",
            "Preços ao consumidor do euro e da Suíça: Eurostat.",
            "Preços ao consumidor do Reino Unido: Office for National Statistics, sob a Open "
            "Government Licence v3.0.",
            "Preços ao consumidor do Canadá: Banco do Canadá (IPC da Statistics Canada); esses "
            "dados estão disponíveis grátis em bankofcanada.ca.",
            "Preços ao consumidor do Brasil: Banco Central do Brasil (IPCA do IBGE).",
            "Todos são lidos ao gerar o relatório e nenhum muda a classe.",
        ],
    },
}


__all__ = ["COPY", "METHOD_PATH", "REFERENCES", "dimension_rows", "method_url"]
