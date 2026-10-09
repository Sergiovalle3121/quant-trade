"""Articles about backtests, for readers who arrive from a search engine.

One article per topic, in Spanish, English and Portuguese, at ``/articulos``,
``/articles`` and ``/pt/artigos``. The copy lives in ``ARTICLES_DATA`` as
plain dictionaries so a writer can replace it without touching the code; the
pages are public and indexable, and the test suite runs the profit-claim
guard over every one of them in every language. An article explains what to
look at in a backtest and links the free calculator, a guide, an audience page
or the method; it never says that a strategy makes or will make money.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quant_trade.audit import winrate
from quant_trade.audit.analytics import DEFAULT_BLOCK_SIZE, DRAWDOWN_THRESHOLDS
from quant_trade.audit.article_numbers import (
    MC_DEEP_THRESHOLD,
    MC_REFERENCE_DAYS,
    MC_REFERENCE_RISK,
    MC_REFERENCE_SEED,
    MC_RISK,
    MC_RISK_SEED,
    MC_SEARCH_DAYS,
    MC_SEARCH_RISK,
    MC_SEARCH_SEED,
    MC_SEARCH_SERIES,
    MC_SERIES_DAYS,
    MC_SERIES_MEAN,
    MC_SERIES_SD,
    MC_SERIES_SEED,
    MC_SHUFFLE,
    MC_SHUFFLE_SEED,
    MC_THRESHOLD,
    STREAK_EXAMPLE,
    STREAK_MEDIAN,
    STREAK_RARE,
    STREAK_RISKS,
    STREAK_TRADE_COUNTS,
    STREAK_WIN_RATES,
    streak_for,
)
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url
from quant_trade.audit.calculator import CALCULATOR_PATH, PERIODS_PER_YEAR, CalculatorInput, compute
from quant_trade.audit.calculator import COPY as CALCULATOR_COPY
from quant_trade.audit.costs import break_even_bps
from quant_trade.audit.examples import EXAMPLES_COPY, EXAMPLES_PATH
from quant_trade.audit.guides import GUIDES_BY_SLUG, guide_url
from quant_trade.audit.method import COPY as METHOD_COPY
from quant_trade.audit.method import METHOD_PATH
from quant_trade.audit.public_card import _num, _pct, _wilson
from quant_trade.audit.reading import COPY as READING_COPY
from quant_trade.audit.reading import READING_PATH, reading_url
from quant_trade.audit.retail_numbers import (
    COIN_NORMAL_TAIL,
    COIN_NULL_WIN_RATE,
    COIN_THRESHOLD_WIN_RATE,
    COIN_TRADE_COUNT,
    PROP_ATTEMPT_EXAMPLES,
    PROP_RISKS,
    PROP_RULES,
    PROP_STREAK_LENGTH,
    PROP_WIN_RATES,
    SIGNAL_DECLARED_WIN_RATE,
)
from quant_trade.audit.streaks import CLUSTERED, EXACT_MAX_TRADES, MIN_TRADES
from quant_trade.core.models import Trade

LOCALES: tuple[str, ...] = ("es", "en", "pt")

#: The pages an article may point to: the free calculator, an export guide
#: (by its Spanish slug), an audience page (by its Spanish slug), another article
#: (by its stable key), the method, the win-rate calculator or the sample report
#: (``sample``, the full report on synthetic data; ``samples`` is the page of
#: public figures).
RELATED_KINDS: frozenset[str] = frozenset(
    {
        "calculator",
        "guide",
        "audience",
        "method",
        "contact",
        "samples",
        "sample",
        "reading",
        "article",
        "winrate",
    }
)


#: Illustrative declarations, never measurements of a client's file. The same
#: calculator supplies the prose example and every cell of the comparison table.
LUCK_EXAMPLE_INPUT = CalculatorInput(sharpe=1.8, years=3, trials=100)
LUCK_TABLE_INPUTS = tuple(
    CalculatorInput(sharpe=LUCK_EXAMPLE_INPUT.sharpe, years=years, trials=trials)
    for trials in (10, 100, 1000)
    for years in (1, 3, 5)
)
_EXAMPLE_LUCK = compute(LUCK_EXAMPLE_INPUT)["luck_sharpe"]["value"]
INDEPENDENT_LUCK_EXAMPLE = {
    "es": (
        f"DECLARED · Supongamos {LUCK_EXAMPLE_INPUT.trials} variantes independientes y "
        f"{LUCK_EXAMPLE_INPUT.years:g} años de rendimientos diarios, con "
        f"{PERIODS_PER_YEAR:g} periodos al año y un Sharpe anual declarado de "
        f"{_num(LUCK_EXAMPLE_INPUT.sharpe, 'es', 1)}. La calculadora sitúa el Sharpe esperado "
        f"de la mejor variante sin habilidad en {_num(_EXAMPLE_LUCK, 'es', 2)}. "
        "Es una cuenta bajo supuestos de "
        "asimetría nula y colas normales, no una medición de una cartera."
    ),
    "en": (
        f"DECLARED · Assume {LUCK_EXAMPLE_INPUT.trials} independent variants and "
        f"{LUCK_EXAMPLE_INPUT.years:g} years of daily returns, with "
        f"{PERIODS_PER_YEAR:g} periods per year and a declared annual Sharpe of "
        f"{_num(LUCK_EXAMPLE_INPUT.sharpe, 'en', 1)}. The calculator puts the expected Sharpe "
        f"of the best unskilled variant at {_num(_EXAMPLE_LUCK, 'en', 2)}. "
        "This calculation assumes no skew and "
        "normal tails; it is not a measurement of a portfolio."
    ),
    "pt": (
        f"DECLARED · Suponha {LUCK_EXAMPLE_INPUT.trials} variantes independentes e "
        f"{LUCK_EXAMPLE_INPUT.years:g} anos de retornos diários, com "
        f"{PERIODS_PER_YEAR:g} períodos por ano e Sharpe anual declarado de "
        f"{_num(LUCK_EXAMPLE_INPUT.sharpe, 'pt', 1)}. A calculadora situa o Sharpe esperado "
        f"da melhor variante sem habilidade em {_num(_EXAMPLE_LUCK, 'pt', 2)}. "
        "É uma conta sob suposições de "
        "assimetria nula e caudas normais, não uma medição de uma carteira."
    ),
}

LUCK_TABLE_COPY = {
    "es": (
        "Sharpe esperado por suerte",
        "Intentos",
        "Años",
        "Sharpe por suerte",
        "DECLARED · Entradas ilustrativas y resultados calculados; no son datos de un archivo.",
    ),
    "en": (
        "Expected Sharpe from luck",
        "Trials",
        "Years",
        "Sharpe from luck",
        "DECLARED · Illustrative inputs and computed results; these are not file measurements.",
    ),
    "pt": (
        "Sharpe esperado por sorte",
        "Tentativas",
        "Anos",
        "Sharpe por sorte",
        "DECLARED · Entradas ilustrativas e resultados calculados; não são dados de um arquivo.",
    ),
}

#: Declared teaching examples, computed with the public reader and cost engine.
#: Rates can be rounded declarations; do not infer an integer count of wins.
WIN_RATE_TRADE_COUNTS = (20, 45, 100, 300, 1000)
WIN_RATE_RATES = (0.55, 0.60, 0.71)
WIN_RATE_EXAMPLE_VALUES = {
    "trades": "45",
    "win_rate": "71",
    "sharpe": "1.8",
    "years": "3",
    "trials": "100",
}


def win_rate_interval(rate: float, trades: int, locale: str) -> str:
    """The reader's Wilson interval, formatted for an editorial table."""
    low, high = _wilson(rate, trades)
    return f"{_num(low * 100, locale, 1)}–{_num(high * 100, locale, 1)} %"


WIN_RATE_TABLE_COPY = {
    "es": (
        "Tabla: cuánto cambia el intervalo con la muestra",
        "Operaciones",
        "DECLARED · Intervalos Wilson al 95 % calculados con la función del lector de Rigor. "
        "Entradas ilustrativas, posiblemente redondeadas; operaciones independientes y una "
        "regla fijada antes de observar los resultados. No son mediciones de un archivo.",
    ),
    "en": (
        "Table: how the interval changes with sample size",
        "Trades",
        "DECLARED · Wilson 95 % intervals calculated with Rigor's reader function. "
        "Illustrative, possibly rounded inputs; independent trades and a rule fixed before "
        "observing the results. These are not file measurements.",
    ),
    "pt": (
        "Tabela: como o intervalo muda com a amostra",
        "Operações",
        "DECLARED · Intervalos Wilson de 95 % calculados com a função do leitor do Rigor. "
        "Entradas ilustrativas, possivelmente arredondadas; operações independentes e uma "
        "regra fixada antes de observar os resultados. Não são medições de um arquivo.",
    ),
}

COST_EXAMPLE_TRADE = Trade(
    entry_time=datetime(2026, 1, 1),
    exit_time=datetime(2026, 1, 2),
    entry_price=100.0,
    exit_price=101.0,
    quantity=1.0,
    pnl=1.0,
    return_pct=0.01,
)
_COST_EXAMPLE_BPS = break_even_bps([COST_EXAMPLE_TRADE], ["long"], reported_costs=[0.0])
assert _COST_EXAMPLE_BPS is not None


def _whole_pct(value: float, locale: str) -> str:
    """A declared rate written as a whole percentage: 45 %."""
    return f"{_num(value * 100, locale, 0)} %"


def _stake_pct(value: float, locale: str) -> str:
    """A declared stake or its sum with one decimal: 0,5 % in es and pt, 0.5 % in en."""
    return f"{_num(value * 100, locale, 1)} %"


#: The Monte Carlo article's worked figures. Every number is computed in
#: ``article_numbers`` with ``analytics.shuffled_drawdown`` and
#: ``analytics.drawdown_risk`` on synthetic series fixed by their seeds.
MONTE_CARLO_ARTICLE_KEY = "monte-carlo-backtest"
_MC_DAYS = {locale: _num(MC_SERIES_DAYS, locale, 0) for locale in LOCALES}
_MC_MEAN = {locale: _num(MC_SERIES_MEAN * 100, locale, 2) for locale in LOCALES}
_MC_SD = {locale: _num(MC_SERIES_SD * 100, locale, 0) for locale in LOCALES}
_MC_LEVEL = {locale: _whole_pct(MC_THRESHOLD, locale) for locale in LOCALES}
_MC_DEEP = {locale: _whole_pct(MC_DEEP_THRESHOLD, locale) for locale in LOCALES}


def _mc(locale: str, value: float) -> str:
    return _pct(value, locale)


MONTE_CARLO_EXAMPLE: dict[str, tuple[str, str, str]] = {
    "es": (
        f"DECLARED · Una serie sintética de {_MC_DAYS['es']} rendimientos diarios, generada con "
        f"NumPy con semilla {MC_SERIES_SEED}, media de {_MC_MEAN['es']} % y desviación de "
        f"{_MC_SD['es']} % al día. En el orden generado, su caída máxima es de "
        f"{_mc('es', MC_SHUFFLE.observed)}. Con shuffled_drawdown, "
        f"{_num(MC_SHUFFLE.samples, 'es', 0)} órdenes al azar de los mismos rendimientos con "
        f"semilla {MC_SHUFFLE_SEED}, la peor caída va de {_mc('es', MC_SHUFFLE.low)} a "
        f"{_mc('es', MC_SHUFFLE.high)} en 9 de cada 10 órdenes, con una mediana de "
        f"{_mc('es', MC_SHUFFLE.median)}.",
        f"DECLARED · Con drawdown_risk, el bootstrap estacionario del informe "
        f"({_num(MC_RISK.samples, 'es', 0)} historias de {_num(MC_RISK.horizon, 'es', 0)} días, "
        f"bloque esperado de {_num(MC_RISK.block, 'es', 0)} días y semilla {MC_RISK_SEED}), la "
        f"caída máxima a un año tiene una mediana de {_mc('es', MC_RISK.median)} y llega a "
        f"{_mc('es', MC_RISK.p95)} en 1 de cada 20 historias. El "
        f"{_mc('es', MC_RISK.at_least)} de las historias cae al menos un {_MC_LEVEL['es']} y el "
        f"{_mc('es', MC_RISK.at_least_deep)}, al menos un {_MC_DEEP['es']}.",
        f"Las dos cifras miden cosas distintas: la primera recorre los {_MC_DAYS['es']} días de "
        "la serie; la segunda, un año. Ninguna es una medición de una estrategia ni una "
        "previsión. El código del artículo fija la semilla y los parámetros, así que el mismo "
        "cálculo da siempre estas cifras.",
    ),
    "en": (
        f"DECLARED · A synthetic series of {_MC_DAYS['en']} daily returns, drawn with NumPy from "
        f"seed {MC_SERIES_SEED}, with a mean of {_MC_MEAN['en']} % and a standard deviation of "
        f"{_MC_SD['en']} % a day. In the order drawn, its maximum drawdown is "
        f"{_mc('en', MC_SHUFFLE.observed)}. With shuffled_drawdown, "
        f"{_num(MC_SHUFFLE.samples, 'en', 0)} random orders of the same returns from seed "
        f"{MC_SHUFFLE_SEED}, the worst fall runs from {_mc('en', MC_SHUFFLE.low)} to "
        f"{_mc('en', MC_SHUFFLE.high)} in 9 orders out of 10, with a median of "
        f"{_mc('en', MC_SHUFFLE.median)}.",
        f"DECLARED · With drawdown_risk, the report's stationary bootstrap "
        f"({_num(MC_RISK.samples, 'en', 0)} histories of {_num(MC_RISK.horizon, 'en', 0)} days, "
        f"an expected block of {_num(MC_RISK.block, 'en', 0)} days and seed {MC_RISK_SEED}), the "
        f"one-year maximum drawdown has a median of {_mc('en', MC_RISK.median)} and reaches "
        f"{_mc('en', MC_RISK.p95)} in 1 history in 20. In all, "
        f"{_mc('en', MC_RISK.at_least)} of the histories fall at least {_MC_LEVEL['en']} and "
        f"{_mc('en', MC_RISK.at_least_deep)} at least {_MC_DEEP['en']}.",
        f"The two figures measure different things: the first covers the series' "
        f"{_MC_DAYS['en']} days; the second, one year. Neither is a measurement of a strategy "
        "or a forecast. The article's code fixes the seed and the parameters, so the same "
        "calculation always gives these figures.",
    ),
    "pt": (
        f"DECLARED · Uma série sintética de {_MC_DAYS['pt']} retornos diários, gerada com NumPy "
        f"com semente {MC_SERIES_SEED}, média de {_MC_MEAN['pt']} % e desvio de "
        f"{_MC_SD['pt']} % ao dia. Na ordem gerada, sua queda máxima é de "
        f"{_mc('pt', MC_SHUFFLE.observed)}. Com shuffled_drawdown, "
        f"{_num(MC_SHUFFLE.samples, 'pt', 0)} ordens aleatórias dos mesmos retornos com "
        f"semente {MC_SHUFFLE_SEED}, a pior queda vai de {_mc('pt', MC_SHUFFLE.low)} a "
        f"{_mc('pt', MC_SHUFFLE.high)} em 9 de cada 10 ordens, com mediana de "
        f"{_mc('pt', MC_SHUFFLE.median)}.",
        f"DECLARED · Com drawdown_risk, o bootstrap estacionário do relatório "
        f"({_num(MC_RISK.samples, 'pt', 0)} históricos de {_num(MC_RISK.horizon, 'pt', 0)} "
        f"dias, bloco esperado de {_num(MC_RISK.block, 'pt', 0)} dias e semente "
        f"{MC_RISK_SEED}), a queda máxima em um ano tem mediana de {_mc('pt', MC_RISK.median)} "
        f"e chega a {_mc('pt', MC_RISK.p95)} em 1 em cada 20 históricos. Ao todo, "
        f"{_mc('pt', MC_RISK.at_least)} dos históricos caem pelo menos {_MC_LEVEL['pt']} e "
        f"{_mc('pt', MC_RISK.at_least_deep)}, pelo menos {_MC_DEEP['pt']}.",
        f"Os dois números medem coisas diferentes: o primeiro percorre os {_MC_DAYS['pt']} dias "
        "da série; o segundo, um ano. Nenhum é uma medição de uma estratégia nem uma previsão. "
        "O código do artigo fixa a semente e os parâmetros, então o mesmo cálculo sempre dá "
        "esses números.",
    ),
}

MONTE_CARLO_SEARCH_EXAMPLE: dict[str, str] = {
    "es": (
        f"DECLARED · Generamos {MC_SEARCH_SERIES} series sintéticas de {MC_SEARCH_DAYS} "
        f"rendimientos diarios con media cero y desviación de {_MC_SD['es']} % (semilla "
        f"{MC_SEARCH_SEED}) y nos quedamos con la de mayor resultado final. Con drawdown_risk y "
        "los mismos parámetros, su caída máxima a un año tiene una mediana de "
        f"{_mc('es', MC_SEARCH_RISK.median)} y el {_mc('es', MC_SEARCH_RISK.at_least)} de las "
        f"historias cae al menos un {_MC_LEVEL['es']}. Otros "
        f"{_num(MC_REFERENCE_DAYS, 'es', 0)} días del mismo generador (semilla "
        f"{MC_REFERENCE_SEED}) dan una mediana de {_mc('es', MC_REFERENCE_RISK.median)} y un "
        f"{_mc('es', MC_REFERENCE_RISK.at_least)} de historias con una caída de al menos un "
        f"{_MC_LEVEL['es']}. Ninguna serie tenía ventaja: la diferencia la pone la selección."
    ),
    "en": (
        f"DECLARED · We drew {MC_SEARCH_SERIES} synthetic series of {MC_SEARCH_DAYS} daily "
        f"returns with zero mean and a standard deviation of {_MC_SD['en']} % (seed "
        f"{MC_SEARCH_SEED}) and kept the one with the highest final result. With drawdown_risk "
        "and the same parameters, its one-year maximum drawdown has a median of "
        f"{_mc('en', MC_SEARCH_RISK.median)}, and {_mc('en', MC_SEARCH_RISK.at_least)} of the "
        f"histories fall at least {_MC_LEVEL['en']}. Another "
        f"{_num(MC_REFERENCE_DAYS, 'en', 0)} days from the same generator (seed "
        f"{MC_REFERENCE_SEED}) give a median of {_mc('en', MC_REFERENCE_RISK.median)}, with "
        f"{_mc('en', MC_REFERENCE_RISK.at_least)} of histories falling at least "
        f"{_MC_LEVEL['en']}. No series had an edge: the difference comes from the selection."
    ),
    "pt": (
        f"DECLARED · Geramos {MC_SEARCH_SERIES} séries sintéticas de {MC_SEARCH_DAYS} retornos "
        f"diários com média zero e desvio de {_MC_SD['pt']} % (semente {MC_SEARCH_SEED}) e "
        "ficamos com a de maior resultado final. Com drawdown_risk e os mesmos parâmetros, sua "
        f"queda máxima em um ano tem mediana de {_mc('pt', MC_SEARCH_RISK.median)}, e "
        f"{_mc('pt', MC_SEARCH_RISK.at_least)} dos históricos caem pelo menos "
        f"{_MC_LEVEL['pt']}. Outros {_num(MC_REFERENCE_DAYS, 'pt', 0)} dias do mesmo gerador "
        f"(semente {MC_REFERENCE_SEED}) dão mediana de {_mc('pt', MC_REFERENCE_RISK.median)}, "
        f"com {_mc('pt', MC_REFERENCE_RISK.at_least)} dos históricos caindo pelo menos "
        f"{_MC_LEVEL['pt']}. Nenhuma série tinha vantagem: a diferença vem da seleção."
    ),
}


def _threshold_list(locale: str) -> str:
    """The report's drawdown thresholds as a phrase: 10, 20, 30 o 50 %."""
    values = [_num(t * 100, locale, 0) for t in DRAWDOWN_THRESHOLDS]
    word = {"es": "o", "en": "or", "pt": "ou"}[locale]
    return f"{', '.join(values[:-1])} {word} {values[-1]} %"


_BLOCK = {locale: _num(DEFAULT_BLOCK_SIZE, locale, 0) for locale in LOCALES}

#: What the report computes, named after the engine's functions.
MONTE_CARLO_REPORT: dict[str, str] = {
    "es": (
        "El informe llama a esto riesgo remuestreado a un año. La función drawdown_risk arma "
        "miles de historias de un año con bloques de los rendimientos de tu archivo, con un "
        f"bootstrap estacionario cuyo bloque esperado parte de {_BLOCK['es']} periodos y se "
        "alarga cuando los rendimientos se agrupan. Muestra la caída máxima mediana, la de 1 de "
        "cada 20 y la de 1 de cada 100, la probabilidad de caer al menos un "
        f"{_threshold_list('es')} y los periodos seguidos bajo el máximo. La semilla es fija y "
        "el informe la imprime."
    ),
    "en": (
        "The report calls this resampled one-year risk. The drawdown_risk function builds "
        "thousands of one-year histories from blocks of your file's returns, with a stationary "
        f"bootstrap whose expected block starts at {_BLOCK['en']} periods and grows when "
        "returns cluster. It shows the median maximum drawdown, the one reached 1 time in 20 "
        f"and 1 time in 100, the probability of falling at least {_threshold_list('en')} and "
        "the consecutive periods below the peak. The seed is fixed and the report prints it."
    ),
    "pt": (
        "O relatório chama isso de risco reamostrado em um ano. A função drawdown_risk monta "
        "milhares de históricos de um ano com blocos dos retornos do seu arquivo, com um "
        f"bootstrap estacionário cujo bloco esperado parte de {_BLOCK['pt']} períodos e aumenta "
        "quando os retornos se agrupam. Mostra a queda máxima mediana, a de 1 em cada 20 e a "
        f"de 1 em cada 100, a probabilidade de cair pelo menos {_threshold_list('pt')} e os "
        "períodos seguidos abaixo do máximo. A semente é fixa e o relatório a imprime."
    ),
}

#: The losing-streak article: the table's words, the section it follows (by its
#: title in each language) and the paragraphs that read figures out of it.
#: Every number comes from ``article_numbers`` (``streaks.longest_run_tail``).
STREAK_ARTICLE_KEY = "rachas-perdedoras"
STREAK_TABLE_AFTER: dict[str, str] = {
    "es": "Cómo se calculó la tabla",
    "en": "How the table was calculated",
    "pt": "Como a tabela foi calculada",
}
_ONE_IN = round(1 / STREAK_RARE)
_CLUSTERED_ONE_IN = round(1 / CLUSTERED)
STREAK_TABLE_COPY: dict[str, tuple[str, str, str, str, str, str]] = {
    "es": (
        "Tabla: racha perdedora más larga por azar",
        "Aciertos",
        "Operaciones",
        "Racha mediana",
        f"Racha de 1 de cada {_ONE_IN}",
        "DECLARED · Calculado con longest_run_tail del motor de Rigor: operaciones "
        "independientes y la misma probabilidad de perder en cada una. Entradas ilustrativas; "
        "no son mediciones de un archivo.",
    ),
    "en": (
        "Table: longest losing streak from chance",
        "Win rate",
        "Trades",
        "Median streak",
        f"1-in-{_ONE_IN} streak",
        "DECLARED · Calculated with longest_run_tail from Rigor's engine: independent trades "
        "with the same probability of losing on each. Illustrative inputs; these are not file "
        "measurements.",
    ),
    "pt": (
        "Tabela: maior sequência de perdas por acaso",
        "Acerto",
        "Operações",
        "Sequência mediana",
        f"Sequência de 1 em cada {_ONE_IN}",
        "DECLARED · Calculado com longest_run_tail do motor do Rigor: operações independentes "
        "e a mesma probabilidade de perder em cada uma. Entradas ilustrativas; não são "
        "medições de um arquivo.",
    ),
}

_STREAK = streak_for(*STREAK_EXAMPLE)
_STREAK_HIGH = streak_for(STREAK_WIN_RATES[-1], STREAK_EXAMPLE[1])
_STREAK_LOW = streak_for(STREAK_WIN_RATES[0], STREAK_EXAMPLE[1])
_STREAK_SHORT = streak_for(STREAK_EXAMPLE[0], STREAK_TRADE_COUNTS[0])
_STREAK_LONG = streak_for(STREAK_EXAMPLE[0], STREAK_TRADE_COUNTS[-1])


def _rate(row_rate: float, locale: str) -> str:
    return _whole_pct(row_rate, locale)


STREAK_METHOD: dict[str, str] = {
    "es": (
        "DECLARED · Supuesto: operaciones independientes y la misma probabilidad de perder en "
        "cada una, igual a uno menos el porcentaje de aciertos. La función longest_run_tail del "
        "motor de Rigor calcula de forma exacta, con la recurrencia de Feller, la probabilidad "
        "de que la racha perdedora más larga llegue al menos a cada longitud. La racha mediana "
        "es la mayor longitud con probabilidad de al menos "
        f"{_num(STREAK_MEDIAN, 'es', 1)}; la de 1 de cada {_ONE_IN}, la mayor con probabilidad "
        f"de al menos {_num(STREAK_RARE, 'es', 2)}."
    ),
    "en": (
        "DECLARED · Assumption: independent trades with the same probability of losing on "
        "each, equal to one minus the win rate. The longest_run_tail function in Rigor's "
        "engine computes exactly, with Feller's recurrence, the probability that the longest "
        "losing streak reaches at least each length. The median streak is the longest length "
        f"with a probability of at least {_num(STREAK_MEDIAN, 'en', 1)}; the 1-in-{_ONE_IN} "
        f"streak, the longest with a probability of at least {_num(STREAK_RARE, 'en', 2)}."
    ),
    "pt": (
        "DECLARED · Suposição: operações independentes e a mesma probabilidade de perder em "
        "cada uma, igual a um menos a taxa de acerto. A função longest_run_tail do motor do "
        "Rigor calcula de forma exata, com a recorrência de Feller, a probabilidade de a maior "
        "sequência de perdas chegar pelo menos a cada comprimento. A sequência mediana é o "
        f"maior comprimento com probabilidade de pelo menos {_num(STREAK_MEDIAN, 'pt', 1)}; a "
        f"de 1 em cada {_ONE_IN}, o maior com probabilidade de pelo menos "
        f"{_num(STREAK_RARE, 'pt', 2)}."
    ),
}

STREAK_READING: dict[str, str] = {
    "es": (
        f"DECLARED · Con {_rate(_STREAK.win_rate, 'es')} de aciertos y {_STREAK.trades} "
        f"operaciones, la racha más larga llega a {_STREAK.median_run} pérdidas en al menos la "
        f"mitad de los historiales y a {_STREAK.rare_run} en 1 de cada {_ONE_IN}. Con "
        f"{_rate(_STREAK_HIGH.win_rate, 'es')} de aciertos y las mismas operaciones, las cifras "
        f"son {_STREAK_HIGH.median_run} y {_STREAK_HIGH.rare_run}; con "
        f"{_rate(_STREAK_LOW.win_rate, 'es')}, {_STREAK_LOW.median_run} y "
        f"{_STREAK_LOW.rare_run}. Con {_rate(_STREAK.win_rate, 'es')} de aciertos, pasar de "
        f"{_STREAK_SHORT.trades} a {_STREAK_LONG.trades} operaciones lleva la racha mediana de "
        f"{_STREAK_SHORT.median_run} a {_STREAK_LONG.median_run}."
    ),
    "en": (
        f"DECLARED · At a {_rate(_STREAK.win_rate, 'en')} win rate and {_STREAK.trades} "
        f"trades, the longest streak reaches {_STREAK.median_run} losses in at least half of "
        f"the histories and {_STREAK.rare_run} in 1 history in {_ONE_IN}. At "
        f"{_rate(_STREAK_HIGH.win_rate, 'en')} and the same trades, the figures are "
        f"{_STREAK_HIGH.median_run} and {_STREAK_HIGH.rare_run}; at "
        f"{_rate(_STREAK_LOW.win_rate, 'en')}, {_STREAK_LOW.median_run} and "
        f"{_STREAK_LOW.rare_run}. At a {_rate(_STREAK.win_rate, 'en')} win rate, going from "
        f"{_STREAK_SHORT.trades} to {_STREAK_LONG.trades} trades moves the median streak from "
        f"{_STREAK_SHORT.median_run} to {_STREAK_LONG.median_run}."
    ),
    "pt": (
        f"DECLARED · Com {_rate(_STREAK.win_rate, 'pt')} de acerto e {_STREAK.trades} "
        f"operações, a maior sequência chega a {_STREAK.median_run} perdas em pelo menos "
        f"metade dos históricos e a {_STREAK.rare_run} em 1 em cada {_ONE_IN}. Com "
        f"{_rate(_STREAK_HIGH.win_rate, 'pt')} de acerto e as mesmas operações, os números são "
        f"{_STREAK_HIGH.median_run} e {_STREAK_HIGH.rare_run}; com "
        f"{_rate(_STREAK_LOW.win_rate, 'pt')}, {_STREAK_LOW.median_run} e "
        f"{_STREAK_LOW.rare_run}. Com {_rate(_STREAK.win_rate, 'pt')} de acerto, passar de "
        f"{_STREAK_SHORT.trades} para {_STREAK_LONG.trades} operações leva a sequência mediana "
        f"de {_STREAK_SHORT.median_run} para {_STREAK_LONG.median_run}."
    ),
}

#: A fixed loss per trade against the initial balance: k losses take k stakes.
_SMALL, _LARGE = sorted(STREAK_RISKS)
STREAK_STAKES: dict[str, str] = {
    "es": (
        f"DECLARED · Con un riesgo de {_stake_pct(_LARGE, 'es')} por operación, la racha de 1 "
        f"de cada {_ONE_IN} de la fila de {_rate(_STREAK.win_rate, 'es')} y {_STREAK.trades} "
        f"operaciones resta {_stake_pct(_STREAK.rare_run * _LARGE, 'es')} del saldo inicial; "
        f"con {_stake_pct(_SMALL, 'es')}, resta {_stake_pct(_STREAK.rare_run * _SMALL, 'es')}. "
        "Si el límite total de tu reto queda por debajo de esa cifra, una racha que el azar da "
        f"en 1 de cada {_ONE_IN} historiales termina el intento."
    ),
    "en": (
        f"DECLARED · At a risk of {_stake_pct(_LARGE, 'en')} per trade, the 1-in-{_ONE_IN} "
        f"streak of the {_rate(_STREAK.win_rate, 'en')} and {_STREAK.trades}-trade row takes "
        f"{_stake_pct(_STREAK.rare_run * _LARGE, 'en')} of the initial balance; at "
        f"{_stake_pct(_SMALL, 'en')}, it takes {_stake_pct(_STREAK.rare_run * _SMALL, 'en')}. "
        "If your challenge's total limit is below that figure, a streak that chance gives in "
        f"1 history in {_ONE_IN} ends the attempt."
    ),
    "pt": (
        f"DECLARED · Com risco de {_stake_pct(_LARGE, 'pt')} por operação, a sequência de 1 em "
        f"cada {_ONE_IN} da linha de {_rate(_STREAK.win_rate, 'pt')} e {_STREAK.trades} "
        f"operações tira {_stake_pct(_STREAK.rare_run * _LARGE, 'pt')} do saldo inicial; com "
        f"{_stake_pct(_SMALL, 'pt')}, tira {_stake_pct(_STREAK.rare_run * _SMALL, 'pt')}. Se o "
        "limite total do seu desafio fica abaixo desse número, uma sequência que o acaso dá em "
        f"1 em cada {_ONE_IN} históricos encerra a tentativa."
    ),
}

#: What ``streaks.loss_streak_review`` reports, with its own limits.
STREAK_REPORT: dict[str, tuple[str, str]] = {
    "es": (
        "Con un historial de operaciones cerradas, el informe compara tu racha perdedora más "
        "larga con la que da el azar con tu propia proporción de pérdidas. Hasta "
        f"{_num(EXACT_MAX_TRADES, 'es', 0)} operaciones, la función loss_streak_review usa de "
        "forma exacta tus mismas operaciones en orden al azar: reparte tus pérdidas entre todas "
        "las posiciones posibles. Por encima, usa la recurrencia de la tabla. Muestra la racha "
        f"máxima normal por azar, la de 1 de cada {_ONE_IN} y la probabilidad de una racha al "
        "menos tan larga como la tuya.",
        f"Si esa probabilidad queda por debajo de 1 de cada {_CLUSTERED_ONE_IN}, el informe "
        "avisa de que las perdedoras llegaron más juntas de lo que explica el azar, algo que "
        "suele indicar pérdidas que dependen del tipo de mercado o posiciones abiertas a la "
        f"vez. Hacen falta al menos {MIN_TRADES} operaciones cerradas, con perdedoras y no "
        "perdedoras; si no, la cifra queda como NOT_MEASURED. Nada de esto cambia la clase ni "
        "anticipa la próxima racha.",
    ),
    "en": (
        "With a history of closed trades, the report compares your longest losing streak with "
        "the one chance gives at your own share of losses. Up to "
        f"{_num(EXACT_MAX_TRADES, 'en', 0)} trades, the loss_streak_review function uses your "
        "same trades in random order, exactly: it spreads your losses over every possible "
        "position. Above that, it uses the table's recurrence. It shows the typical longest "
        f"losing run by chance, the 1-in-{_ONE_IN} one and the chance of a streak at least as "
        "long as yours.",
        f"If that chance falls below 1 in {_CLUSTERED_ONE_IN}, the report notes that the "
        "losing trades came closer together than chance explains, which often points to "
        "losses that depend on the type of market or to positions open at the same time. It "
        f"needs at least {MIN_TRADES} closed trades, with losing and non-losing ones; "
        "otherwise the figure stays NOT_MEASURED. None of this changes the class or "
        "anticipates the next streak.",
    ),
    "pt": (
        "Com um histórico de operações fechadas, o relatório compara a sua maior sequência de "
        "perdas com a que o acaso dá com a sua própria proporção de perdas. Até "
        f"{_num(EXACT_MAX_TRADES, 'pt', 0)} operações, a função loss_streak_review usa de "
        "forma exata as suas mesmas operações em ordem aleatória: distribui as suas perdas "
        "entre todas as posições possíveis. Acima disso, usa a recorrência da tabela. Mostra a "
        f"maior sequência normal por acaso, a de 1 em cada {_ONE_IN} e a probabilidade de uma "
        "sequência pelo menos tão longa quanto a sua.",
        f"Se essa probabilidade fica abaixo de 1 em cada {_CLUSTERED_ONE_IN}, o relatório avisa "
        "que as perdedoras chegaram mais juntas do que o acaso explica, o que costuma indicar "
        "perdas que dependem do tipo de mercado ou posições abertas ao mesmo tempo. São "
        f"necessárias pelo menos {MIN_TRADES} operações fechadas, com perdedoras e não "
        "perdedoras; senão, o número fica como NOT_MEASURED. Nada disso muda a classe nem "
        "antecipa a próxima sequência.",
    ),
}


#: Editorial dates, not generated at request time. Existing prose was published
#: on 2026-10-05; the institutional articles are dated to this brief.
ARTICLE_PUBLICATION_DATES = {
    "ea-sobreoptimizado": "2026-10-05",
    "backtest-costos-reales": "2026-10-05",
    "leer-informe-probador-mt5": "2026-10-05",
    "auditoria-independiente-backtest": "2026-10-07",
    "sharpe-deflactado-track-record": "2026-10-07",
    "auditar-cartera-modelo-senales": "2026-10-07",
    "cuantos-intentos-reto-prop-firm": "2026-10-07",
    "copiar-senales-mql5-myfxbook": "2026-10-07",
    "bot-ia-backtest-suerte": "2026-10-07",
    "que-hacer-despues-del-backtest": "2026-10-08",
    "cuantas-operaciones-porcentaje-aciertos": "2026-10-08",
    "lo-eligio-el-optimizador": "2026-10-08",
    "monte-carlo-backtest": "2026-10-08",
    "rachas-perdedoras": "2026-10-08",
}


@dataclass(frozen=True)
class ArticleSection:
    heading: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class ArticleText:
    title: str
    #: One sentence for the index and the page's meta description.
    summary: str
    #: The opening paragraph, before the first heading.
    intro: str
    sections: tuple[ArticleSection, ...]
    #: Question and answer pairs, shown after the sections.
    faq: tuple[tuple[str, str], ...]
    #: Optional compact metadata title; the full editorial heading stays intact.
    seo_title: str | None = None


@dataclass(frozen=True)
class Article:
    #: The stable name used in code and tests (the Spanish slug, as a rule).
    key: str
    #: The path segment per language.
    slug: dict[str, str]
    text: dict[str, ArticleText]
    #: Links shown under the article, see ``RELATED_KINDS``.
    related: tuple[dict[str, str], ...]

    def slug_for(self, locale: str) -> str:
        return self.slug.get(locale, self.slug["es"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Article:
        """An article from the plain-dictionary shape of ``ARTICLES_DATA``."""
        text = {
            locale: ArticleText(
                title=str(data["title"][locale]),
                summary=str(data["summary"][locale]),
                intro=str(data["intro"][locale]),
                sections=tuple(
                    ArticleSection(
                        heading=str(section["heading"]),
                        paragraphs=tuple(str(p) for p in section["paragraphs"]),
                    )
                    for section in data["sections"][locale]
                ),
                faq=tuple((str(item["q"]), str(item["a"])) for item in data["faq"][locale]),
                seo_title=data.get("seo_title", {}).get(locale),
            )
            for locale in LOCALES
        }
        related = tuple(
            {str(k): str(v) for k, v in link.items()} for link in data.get("related", ())
        )
        audience_slugs = {page.slug for page in AUDIENCE_PAGES}
        article_keys = {article["key"] for article in ARTICLES_DATA}
        for link in related:
            if link.get("kind") not in RELATED_KINDS:
                raise ValueError(f"article {data['key']}: unknown related kind {link!r}")
            if link["kind"] == "guide" and link.get("slug") not in GUIDES_BY_SLUG:
                raise ValueError(f"article {data['key']}: unknown guide {link!r}")
            if link["kind"] == "audience" and link.get("slug") not in audience_slugs:
                raise ValueError(f"article {data['key']}: unknown audience page {link!r}")
            if link["kind"] == "article" and link.get("key") not in article_keys:
                raise ValueError(f"article {data['key']}: unknown article {link!r}")
        return cls(
            key=str(data["key"]),
            slug={locale: str(data["slug"][locale]) for locale in LOCALES},
            text=text,
            related=related,
        )


#: Index and page paths per language. An article lives at ``<index>/<slug>``.
ARTICLES_PATH: dict[str, str] = {"es": "/articulos", "en": "/articles", "pt": "/pt/artigos"}

#: The words the index and every article page share. ``summary`` is the index's meta
#: description: keep it naming the topics the articles cover, without a promise.
ARTICLES_COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Artículos",
        "title": "Artículos sobre backtests",
        "summary": (
            "Artículos sobre backtests: costos, MT5, Sharpe deflactado, Monte Carlo, rachas, prop "
            "firms, señales, bots con IA, % de aciertos y optimizador."
        ),
        "intro": "Lecturas cortas sobre qué mirar en un backtest antes de confiar en él.",
        "related": "Relacionado",
        "faq": "Preguntas frecuentes",
        "calculator": "Probar la calculadora gratis",
        "report": "Pedir mi primer informe gratis",
        "cta_title": "Ponlo a prueba",
        "cta_text": (
            "La calculadora de suerte es gratis y no pide registro. Con tu cuenta, el primer "
            "informe completo también es gratis."
        ),
        "all": "Todos los artículos",
        "back": "Volver al inicio",
    },
    "en": {
        "eyebrow": "Articles",
        "title": "Articles about backtests",
        "summary": (
            "Articles about backtests: costs, MT5, deflated Sharpe, Monte Carlo, losing streaks, "
            "prop firms, signals, AI bots, win rate and the optimiser."
        ),
        "intro": "Short reads on what to look at in a backtest before you trust it.",
        "related": "Related",
        "faq": "FAQ",
        "calculator": "Try the free calculator",
        "report": "Get my free first report",
        "cta_title": "Put it to the test",
        "cta_text": (
            "The luck calculator is free and needs no sign-up. With an account, your first "
            "full report is free too."
        ),
        "all": "All articles",
        "back": "Back to the home page",
    },
    "pt": {
        "eyebrow": "Artigos",
        "title": "Artigos sobre backtests",
        "summary": (
            "Artigos sobre backtests: custos, MT5, Sharpe deflacionado, Monte Carlo, sequências "
            "de perdas, prop firms, sinais, robôs com IA, acerto e otimizador."
        ),
        "intro": "Leituras curtas sobre o que observar num backtest antes de confiar nele.",
        "related": "Relacionado",
        "faq": "Perguntas frequentes",
        "calculator": "Experimentar a calculadora grátis",
        "report": "Pedir o meu primeiro relatório grátis",
        "cta_title": "Coloque à prova",
        "cta_text": (
            "A calculadora de sorte é grátis e não pede cadastro. Com a sua conta, o primeiro "
            "relatório completo também é grátis."
        ),
        "all": "Todos os artigos",
        "back": "Voltar ao início",
    },
}

#: The articles, as plain dictionaries. This is the block a writer replaces:
#: one entry per article, every text in the three languages, in exactly this
#: shape. Every text is plain prose: no HTML, no links, no promise of results.
ARTICLES_DATA: tuple[dict[str, Any], ...] = (
    {
        "key": "ea-sobreoptimizado",
        "slug": {
            "es": "ea-sobreoptimizado",
            "en": "overfitted-expert-advisor",
            "pt": "ea-sobreajustado",
        },
        "title": {
            "es": "Cómo saber si un EA está sobreoptimizado antes de comprarlo",
            "en": "How to tell if an expert advisor is overfitted before you buy",
            "pt": "Como saber se um EA está sobreajustado antes de comprar",
        },
        "seo_title": {
            "es": "Cómo saber si un EA está sobreoptimizado antes de comprar",
            "en": "How to spot an overfitted expert advisor before you buy",
        },
        "summary": {
            "es": (
                "Qué hace el optimizador de MT5, por qué la mejor de muchas configuraciones luce "
                "bien por suerte y cómo medirlo en el XML antes de pagar por un robot."
            ),
            "en": (
                "What the MT5 optimiser does, why the best of many configurations looks good by "
                "luck, and how to measure it in the XML before paying for a robot."
            ),
            "pt": (
                "O que o otimizador do MT5 faz, por que a melhor de muitas configurações parece "
                "boa por sorte e como medir isso no XML antes de pagar por um robô."
            ),
        },
        "intro": {
            "es": (
                "Un EA está sobreoptimizado cuando sus parámetros se ajustaron tanto al pasado que "
                "el resultado del backtest ya no dice nada sobre el futuro. La señal más clara es "
                "un Sharpe alto que no sobrevive a tres pruebas: descontar el número de "
                "configuraciones que probó el optimizador, duplicar los costos y correr el robot "
                "en un tramo de datos que nadie tocó. Aquí ves cómo hacer cada prueba con el "
                "reporte del tester y el XML de optimización que ya tienes."
            ),
            "en": (
                "An expert advisor is overfitted when its parameters were tuned so tightly to past "
                "data that the backtest result no longer says anything about the future. The "
                "clearest sign is a high Sharpe that fails three tests: discount it by the number "
                "of configurations the optimiser tried, double the costs, and run the robot on a "
                "stretch of data nobody touched. Here is how to run each test with the tester "
                "report and the optimisation XML you already have."
            ),
            "pt": (
                "Um expert advisor está sobreajustado quando seus parâmetros foram ajustados tão "
                "de perto ao passado que o resultado do backtest já não diz nada sobre o futuro. O "
                "sinal mais claro é um Sharpe alto que não sobrevive a três testes: descontar o "
                "número de configurações que o otimizador testou, dobrar os custos e rodar o robô "
                "em um trecho de dados que ninguém tocou. Aqui você vê como fazer cada teste com o "
                "relatório do tester e o XML de otimização que já tem."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Qué hace el optimizador",
                    "paragraphs": [
                        (
                            "El optimizador de MT4 y MT5 recorre miles de combinaciones de "
                            "parámetros y guarda el resultado de cada una. Un rango de 1 a 50 en "
                            "el periodo de una media móvil y otro de 1 a 100 en el stop ya da "
                            "cinco mil combinaciones. El optimizador no entiende el mercado: solo "
                            "mide qué combinación habría dado el mejor resultado en ese historial "
                            "exacto."
                        ),
                        (
                            "Ese historial incluye ruido: movimientos que no se van a repetir. "
                            "Cuando pruebas suficientes combinaciones, alguna encaja con el ruido "
                            "por casualidad y queda primera en la tabla. El vendedor publica esa "
                            "fila y tú solo ves esa."
                        ),
                    ],
                },
                {
                    "heading": "Por qué la mejor de muchas luce bien por suerte",
                    "paragraphs": [
                        (
                            "Puedes ponerle número a ese efecto. Con tres años de retornos diarios "
                            "y ninguna ventaja real, la mejor de 10 configuraciones muestra un "
                            "Sharpe cercano a 0.9. La mejor de 100 llega a 1.5, la mejor de 200 a "
                            "1.6 y la mejor de 1,000 a 1.9. Nada de eso es habilidad: es el "
                            "resultado esperado de elegir el máximo."
                        ),
                        (
                            "El historial corto empeora todo. Con un año de datos, la mejor de 200 "
                            "configuraciones ronda un Sharpe de 2.8; con dos años, la mejor de 500 "
                            "ronda 2.2. Con cinco años, la mejor de 50 baja a 1.0."
                        ),
                    ],
                },
                {
                    "heading": "Pico aislado o meseta",
                    "paragraphs": [
                        (
                            "Abre el XML de optimización y ordena las pasadas por resultado. Toma "
                            "la configuración elegida y mira a sus vecinas: la misma con un "
                            "parámetro un paso arriba o abajo, todo lo demás igual. Si el stop "
                            "pasa de 40 a 45 y el resultado cae a la mitad, estás parado en un "
                            "pico aislado."
                        ),
                        (
                            "Una estrategia que capta algo real se sostiene en una meseta: las "
                            "vecinas conservan la mayor parte del resultado. Cuenta cuántas "
                            "vecinas siguen en positivo y qué parte del resultado conserva su "
                            "mediana; esa cifra te dice más que la curva de capital."
                        ),
                    ],
                },
                {
                    "heading": "Costos al doble",
                    "paragraphs": [
                        (
                            "Muchos robots viven de operaciones pequeñas y frecuentes, donde el "
                            "costo pesa más que la señal. Vuelve a correr el backtest con el doble "
                            "del costo por operación que declara el vendedor. Si el resultado se "
                            "vuelve negativo, el EA no tenía margen, solo costos optimistas."
                        ),
                        (
                            "Haz la misma prueba con el triple y anota en qué costo el resultado "
                            "llega a cero. Ese costo de equilibrio es el número que debes comparar "
                            "con el spread real de tu bróker en las horas en que el robot opera, "
                            "no con el promedio del día."
                        ),
                    ],
                },
                {
                    "heading": "Un tramo que nunca tocaste",
                    "paragraphs": [
                        (
                            "Antes de optimizar, separa el último tramo del historial y no lo "
                            "abras hasta el final. El optimizador no debe verlo, y tú tampoco. "
                            "Cuando tengas la configuración final, córrela una sola vez en ese "
                            "tramo y compara el Sharpe con el del tramo de optimización."
                        ),
                        (
                            "Si vuelves al optimizador después de ver el resultado y ajustas algo, "
                            "el tramo ya está contaminado y cuenta como una pasada más. Un tramo "
                            "fuera de muestra sirve una vez. Por eso importa que el vendedor diga "
                            "qué fechas usó para optimizar y cuáles no."
                        ),
                    ],
                },
                {
                    "heading": "Qué preguntar al vendedor",
                    "paragraphs": [
                        (
                            "Pregunta cuántas pasadas corrió el optimizador en total, no solo "
                            "cuántas versiones publicó. Pide el XML de optimización completo, no "
                            "la captura de pantalla de la mejor fila. Pregunta qué fechas quedaron "
                            "fuera de la optimización y qué costo por operación usó el backtest."
                        ),
                        (
                            "Pide también el reporte del Strategy Tester con los parámetros "
                            "impresos, para comprobar que coinciden con la pasada que te vende. "
                            "Sin esas cuatro respuestas no tienes forma de medir lo que compras."
                        ),
                    ],
                },
                {
                    "heading": "Cómo medirlo en el XML real",
                    "paragraphs": [
                        (
                            "El XML de optimización de MT5 guarda cada pasada con sus parámetros y "
                            "su resultado, así que el número de configuraciones probadas pasa a "
                            "ser un dato medido, no una declaración. Con ese número y los años del "
                            "backtest, la calculadora de Rigor te dice qué Sharpe daría la pura "
                            "suerte y cuánto queda después del descuento. Es gratis y no pide "
                            "registro."
                        ),
                        (
                            "Si subes el reporte y el XML a una auditoría, Rigor cuenta las "
                            "configuraciones probadas, calcula el Sharpe deflactado, vuelve a "
                            "correr los costos a 1x, 2x y 3x con su costo de equilibrio y revisa "
                            "el tramo fuera de muestra que declares. Cada número sale etiquetado "
                            "como Medido, Declarado o No medido, para que sepas qué viene del "
                            "archivo y qué viene del vendedor."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "What the optimiser does",
                    "paragraphs": [
                        (
                            "The MT4 and MT5 optimiser walks through thousands of parameter "
                            "combinations and stores the result of each one. A range of 1 to 50 on "
                            "a moving-average period and 1 to 100 on the stop already gives five "
                            "thousand combinations. The optimiser knows nothing about the market: "
                            "it only measures which combination would have done best on that exact "
                            "history."
                        ),
                        (
                            "That history contains noise: moves that will not repeat. Try enough "
                            "combinations and one of them fits the noise by chance and lands at "
                            "the top of the table. The vendor publishes that row and you only see "
                            "that one."
                        ),
                    ],
                },
                {
                    "heading": "Why the best of many looks good by luck",
                    "paragraphs": [
                        (
                            "You can put a number on that effect. With three years of daily "
                            "returns and no real edge, the best of 10 configurations shows a "
                            "Sharpe near 0.9. The best of 100 reaches 1.5, the best of 200 reaches "
                            "1.6 and the best of 1,000 reaches 1.9. None of that is skill: it is "
                            "the expected result of picking the maximum."
                        ),
                        (
                            "A short history makes everything worse. With one year of data, the "
                            "best of 200 configurations sits near a Sharpe of 2.8; with two years, "
                            "the best of 500 sits near 2.2. With five years, the best of 50 drops "
                            "to 1.0."
                        ),
                    ],
                },
                {
                    "heading": "Isolated peak or plateau",
                    "paragraphs": [
                        (
                            "Open the optimisation XML and sort the passes by result. Take the "
                            "chosen configuration and look at its neighbours: the same settings "
                            "with one parameter one step up or down, everything else unchanged. If "
                            "the stop goes from 40 to 45 and the result halves, you are standing "
                            "on an isolated peak."
                        ),
                        (
                            "A strategy that captures something real sits on a plateau: the "
                            "neighbours keep most of the result. Count how many neighbours stay "
                            "positive and what share of the result their median keeps; that figure "
                            "tells you more than the equity curve."
                        ),
                    ],
                },
                {
                    "heading": "Costs at 2x",
                    "paragraphs": [
                        (
                            "Many robots live on small, frequent trades, where cost weighs more "
                            "than the signal. Run the backtest again with twice the per-trade cost "
                            "the vendor declares. If the result turns negative, the EA had no "
                            "margin, only optimistic costs."
                        ),
                        (
                            "Do the same test at three times the cost and note at which cost the "
                            "result reaches zero. That break-even cost is the number to compare "
                            "with your broker's real spread during the hours the robot trades, not "
                            "with the daily average."
                        ),
                    ],
                },
                {
                    "heading": "A holdout you never touched",
                    "paragraphs": [
                        (
                            "Before optimising, set aside the last stretch of history and do not "
                            "open it until the end. The optimiser must not see it, and neither "
                            "should you. Once you have the final configuration, run it once on "
                            "that stretch and compare the Sharpe with the one from the "
                            "optimisation stretch."
                        ),
                        (
                            "If you go back to the optimiser after seeing the result and adjust "
                            "something, the stretch is contaminated and counts as one more pass. "
                            "An out-of-sample stretch works once. That is why it matters that the "
                            "vendor states which dates were used to optimise and which were not."
                        ),
                    ],
                },
                {
                    "heading": "What to ask the vendor",
                    "paragraphs": [
                        (
                            "Ask how many passes the optimiser ran in total, not only how many "
                            "versions were published. Ask for the complete optimisation XML, not a "
                            "screenshot of the best row. Ask which dates were left out of the "
                            "optimisation and what per-trade cost the backtest used."
                        ),
                        (
                            "Also ask for the Strategy Tester report with the parameters printed "
                            "on it, to check that they match the pass being sold to you. Without "
                            "those four answers you have no way to measure what you are buying."
                        ),
                    ],
                },
                {
                    "heading": "How to measure it on the real optimisation XML",
                    "paragraphs": [
                        (
                            "The MT5 optimisation XML stores every pass with its parameters and "
                            "its result, so the number of configurations tried becomes a measured "
                            "figure, not a declaration. With that number and the backtest's years, "
                            "Rigor's calculator tells you what Sharpe luck alone would give and "
                            "how much is left after the discount. It is free and asks for no "
                            "signup."
                        ),
                        (
                            "If you upload the report and the XML for an audit, Rigor counts the "
                            "configurations tried, computes the deflated Sharpe, reruns the costs "
                            "at 1x, 2x and 3x with the break-even cost, and checks the "
                            "out-of-sample stretch you declare. Every number comes tagged "
                            "Measured, Declared or Not measured, so you know what comes from the "
                            "file and what comes from the vendor."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "O que o otimizador faz",
                    "paragraphs": [
                        (
                            "O otimizador do MT4 e do MT5 percorre milhares de combinações de "
                            "parâmetros e guarda o resultado de cada uma. Um intervalo de 1 a 50 "
                            "no período de uma média móvel e outro de 1 a 100 no stop já dá cinco "
                            "mil combinações. O otimizador não entende o mercado: ele só mede qual "
                            "combinação teria dado o melhor resultado naquele histórico exato."
                        ),
                        (
                            "Esse histórico contém ruído: movimentos que não vão se repetir. "
                            "Quando você testa combinações suficientes, alguma encaixa no ruído "
                            "por acaso e fica em primeiro na tabela. O vendedor publica essa linha "
                            "e você só vê essa."
                        ),
                    ],
                },
                {
                    "heading": "Por que a melhor de muitas parece boa por sorte",
                    "paragraphs": [
                        (
                            "Dá para colocar um número nesse efeito. Com três anos de retornos "
                            "diários e nenhuma vantagem real, a melhor de 10 configurações mostra "
                            "um Sharpe perto de 0.9. A melhor de 100 chega a 1.5, a melhor de 200 "
                            "a 1.6 e a melhor de mil a 1.9. Nada disso é habilidade: é o resultado "
                            "esperado de escolher o máximo."
                        ),
                        (
                            "Um histórico curto piora tudo. Com um ano de dados, a melhor de 200 "
                            "configurações fica perto de um Sharpe de 2.8; com dois anos, a melhor "
                            "de 500 fica perto de 2.2. Com cinco anos, a melhor de 50 cai para "
                            "1.0."
                        ),
                    ],
                },
                {
                    "heading": "Pico isolado ou platô",
                    "paragraphs": [
                        (
                            "Abra o XML de otimização e ordene as passagens pelo resultado. Pegue "
                            "a configuração escolhida e olhe as vizinhas: a mesma com um parâmetro "
                            "um passo acima ou abaixo, todo o resto igual. Se o stop vai de 40 "
                            "para 45 e o resultado cai pela metade, você está em cima de um pico "
                            "isolado."
                        ),
                        (
                            "Uma estratégia que capta algo real se sustenta em um platô: as "
                            "vizinhas conservam a maior parte do resultado. Conte quantas vizinhas "
                            "continuam positivas e que parte do resultado a mediana delas "
                            "conserva; esse número diz mais do que a curva de capital."
                        ),
                    ],
                },
                {
                    "heading": "Custos em dobro",
                    "paragraphs": [
                        (
                            "Muitos robôs vivem de operações pequenas e frequentes, em que o custo "
                            "pesa mais do que o sinal. Rode o backtest de novo com o dobro do "
                            "custo por operação que o vendedor declara. Se o resultado fica "
                            "negativo, o EA não tinha margem, só custos otimistas."
                        ),
                        (
                            "Faça o mesmo teste com o triplo e anote em qual custo o resultado "
                            "chega a zero. Esse custo de equilíbrio é o número que você deve "
                            "comparar com o spread real da sua corretora nas horas em que o robô "
                            "opera, não com a média do dia."
                        ),
                    ],
                },
                {
                    "heading": "Um trecho que você nunca tocou",
                    "paragraphs": [
                        (
                            "Antes de otimizar, separe o último trecho do histórico e não o abra "
                            "até o final. O otimizador não deve vê-lo, e você também não. Quando "
                            "tiver a configuração final, rode-a uma única vez nesse trecho e "
                            "compare o Sharpe com o do trecho de otimização."
                        ),
                        (
                            "Se você volta ao otimizador depois de ver o resultado e ajusta algo, "
                            "o trecho já está contaminado e conta como mais uma passagem. Um "
                            "trecho fora da amostra serve uma vez. Por isso importa que o vendedor "
                            "diga quais datas usou para otimizar e quais não."
                        ),
                    ],
                },
                {
                    "heading": "O que perguntar ao vendedor",
                    "paragraphs": [
                        (
                            "Pergunte quantas passagens o otimizador rodou no total, não só "
                            "quantas versões foram publicadas. Peça o XML de otimização completo, "
                            "não a captura de tela da melhor linha. Pergunte quais datas ficaram "
                            "fora da otimização e qual custo por operação o backtest usou."
                        ),
                        (
                            "Peça também o relatório do Strategy Tester com os parâmetros "
                            "impressos, para conferir se batem com a passagem que ele vende. Sem "
                            "essas quatro respostas você não tem como medir o que compra."
                        ),
                    ],
                },
                {
                    "heading": "Como medir isso no XML real",
                    "paragraphs": [
                        (
                            "O XML de otimização do MT5 guarda cada passagem com seus parâmetros e "
                            "seu resultado, e o número de configurações testadas vira um dado "
                            "medido, não uma declaração. Com esse número e os anos do backtest, a "
                            "calculadora do Rigor diz qual Sharpe a pura sorte daria e quanto "
                            "sobra depois do desconto. É gratuita e não pede cadastro."
                        ),
                        (
                            "Se você envia o relatório e o XML para uma auditoria, o Rigor conta "
                            "as configurações testadas, calcula o Sharpe deflacionado, roda de "
                            "novo os custos a 1x, 2x e 3x com o custo de equilíbrio e revisa o "
                            "trecho fora da amostra que você declarar. Cada número sai marcado "
                            "como Medido, Declarado ou Não medido, para você saber o que vem do "
                            "arquivo e o que vem do vendedor."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Cuántos años de datos necesito para confiar en un Sharpe de 1.8?",
                    "a": (
                        "Depende de cuántas configuraciones se probaron. Con 1,000 intentos hacen "
                        "falta unos 3.3 años de retornos diarios para que la pura suerte quede por "
                        "debajo de 1.8. Con menos historial, ese Sharpe cabe dentro de lo que "
                        "explica el azar."
                    ),
                },
                {
                    "q": "¿Un forward test de MT5 sustituye al tramo que nunca tocaste?",
                    "a": (
                        "Solo si lo corriste una vez y no volviste a optimizar después de verlo. "
                        "Si el vendedor repitió el ciclo varias veces hasta que el forward se vio "
                        "bien, el forward es otra configuración más, elegida por su resultado."
                    ),
                },
                {
                    "q": "¿La optimización genética cambia algo?",
                    "a": (
                        "Sí: el algoritmo genético no prueba todas las vecinas de la configuración "
                        "elegida, así que al XML pueden faltarle las pasadas que muestran la "
                        "meseta. Cuando falten, corre una optimización completa en un rango "
                        "estrecho alrededor de la configuración final."
                    ),
                },
            ],
            "en": [
                {
                    "q": "How many years of data do I need to trust a Sharpe of 1.8?",
                    "a": (
                        "It depends on how many configurations were tried. With 1,000 tries, about "
                        "3.3 years of daily returns are needed for luck alone to fall below 1.8. "
                        "With less history, that Sharpe fits inside what chance explains."
                    ),
                },
                {
                    "q": "Does an MT5 forward test replace the holdout you never touched?",
                    "a": (
                        "Only if you ran it once and did not optimise again after seeing it. If "
                        "the vendor repeated the cycle several times until the forward looked "
                        "good, the forward is one more configuration, chosen for its result."
                    ),
                },
                {
                    "q": "Does genetic optimisation change anything?",
                    "a": (
                        "Yes: the genetic algorithm does not try every neighbour of the chosen "
                        "configuration, so the XML may lack the passes that show the plateau. When "
                        "they are missing, run a complete optimisation over a narrow range around "
                        "the final configuration."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "Quantos anos de dados eu preciso para confiar em um Sharpe de 1.8?",
                    "a": (
                        "Depende de quantas configurações foram testadas. Com mil tentativas, são "
                        "necessários cerca de 3.3 anos de retornos diários para que a pura sorte "
                        "fique abaixo de 1.8. Com menos histórico, esse Sharpe cabe dentro do que "
                        "o acaso explica."
                    ),
                },
                {
                    "q": "Um forward test do MT5 substitui o trecho que você nunca tocou?",
                    "a": (
                        "Só se você o rodou uma vez e não otimizou de novo depois de vê-lo. Se o "
                        "vendedor repetiu o ciclo várias vezes até o forward parecer bom, o "
                        "forward é só mais uma configuração, escolhida pelo resultado."
                    ),
                },
                {
                    "q": "A otimização genética muda alguma coisa?",
                    "a": (
                        "Sim: o algoritmo genético não testa todas as vizinhas da configuração "
                        "escolhida, então podem faltar no XML as passagens que mostram o platô. "
                        "Quando faltarem, rode uma otimização completa em um intervalo estreito ao "
                        "redor da configuração final."
                    ),
                },
            ],
        },
        "related": [
            {
                "kind": "calculator",
            },
            {
                "kind": "guide",
                "slug": "mt5-optimization",
            },
            {
                "kind": "audience",
                "slug": "compradores-de-robots",
            },
        ],
    },
    {
        "key": "backtest-costos-reales",
        "slug": {
            "es": "backtest-costos-reales",
            "en": "backtest-real-costs",
            "pt": "backtest-custos-reais",
        },
        "title": {
            "es": "Backtest con costos reales: spread, comisión, slippage y swap",
            "en": "Backtest with real costs: spread, commission, slippage and swap",
            "pt": "Backtest com custos reais: spread, comissão, slippage e swap",
        },
        "seo_title": {
            "es": "Backtest, costos reales: spread, comisión, slippage, swap",
            "en": "Backtest real costs: spread, commission, slippage, swap",
            "pt": "Backtest, custos reais: spread, comissão, slippage, swap",
        },
        "summary": {
            "es": (
                "Qué costos descuenta un backtest serio, por qué el costo cero favorece al corto "
                "plazo y cómo estimar tu costo real con tu estado de cuenta."
            ),
            "en": (
                "Which costs a serious backtest deducts, why zero cost flatters short-term "
                "strategies and how to estimate your real cost from a broker statement."
            ),
            "pt": (
                "Quais custos um backtest sério desconta, por que o custo zero favorece o curto "
                "prazo e como estimar o seu custo real com o extrato da corretora."
            ),
        },
        "intro": {
            "es": (
                "Un backtest con costos reales descuenta en cada operación el spread, la comisión, "
                "el deslizamiento y el swap que tu bróker te cobraría de verdad, en lugar del "
                "costo cero o el spread fijo que el probador trae por defecto. La diferencia pesa "
                "más cuanto más corto es el plazo: una estrategia que captura pocos puntos por "
                "operación luce bien a costo cero y puede quedar en negativo con el spread real. "
                "La prueba que resuelve la duda es correr el mismo backtest a 1x, 2x y 3x el costo "
                "por operación y anotar en qué costo el resultado llega a cero. Ese costo de "
                "equilibrio es el número que debes reportar."
            ),
            "en": (
                "A backtest with real costs deducts from every trade the spread, commission, "
                "slippage and swap your broker would actually charge, instead of the zero cost or "
                "fixed spread the tester uses by default. The difference weighs more the shorter "
                "the holding time: a strategy that captures a few points per trade looks fine at "
                "zero cost and can turn negative with the real spread. The test that settles it is "
                "to run the same backtest at 1x, 2x and 3x the per-trade cost and note at which "
                "cost the result reaches zero. That break-even cost is the number to report."
            ),
            "pt": (
                "Um backtest com custos reais desconta de cada operação o spread, a comissão, o "
                "slippage e o swap que a sua corretora cobraria de verdade, em vez do custo zero "
                "ou do spread fixo que o testador usa por padrão. A diferença pesa mais quanto "
                "mais curto é o prazo: uma estratégia que captura poucos pontos por operação "
                "parece boa a custo zero e pode ficar negativa com o spread real. O teste que "
                "resolve a dúvida é rodar o mesmo backtest a 1x, 2x e 3x o custo por operação e "
                "anotar em qual custo o resultado chega a zero. Esse custo de equilíbrio é o "
                "número que você deve reportar."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Los cuatro costos que paga cada operación",
                    "paragraphs": [
                        (
                            "El spread es la diferencia entre el precio de compra y el de venta "
                            "cuando abres: lo pagas al entrar, cambia según la hora y se dispara "
                            "con las noticias. La comisión es un monto fijo por lote o por "
                            "operación que cobran los brókers ECN."
                        ),
                        (
                            "El deslizamiento (slippage) es la diferencia entre el precio que "
                            "pediste y el que te ejecutaron; aparece cuando el mercado se mueve "
                            "antes de la ejecución, sobre todo en los stops. El swap es lo que "
                            "pagas o recibes por mantener una posición de un día a otro."
                        ),
                    ],
                },
                {
                    "heading": "Por qué el costo cero favorece al corto plazo",
                    "paragraphs": [
                        (
                            "El costo se cobra por operación y la ventaja se mide en puntos por "
                            "operación. Una estrategia que mantiene posiciones durante días "
                            "captura muchos puntos en cada una; un scalper que busca pocos puntos "
                            "paga el mismo spread por un movimiento mucho menor."
                        ),
                        (
                            "El segundo efecto es el número de operaciones: cuantas más al año, "
                            "más veces pagas el costo. Si la línea de costos del reporte dice "
                            "cero, el resultado es bruto, no neto."
                        ),
                    ],
                },
                {
                    "heading": "Qué cambia al correrlo a 1x, 2x y 3x",
                    "paragraphs": [
                        (
                            "Corre el backtest con el costo por operación que estimaste (1x), con "
                            "el doble (2x) y con el triple (3x). Anota el resultado neto, el "
                            "drawdown máximo y el Sharpe de cada corrida. Una estrategia con "
                            "margen sigue en positivo a 2x; una frágil se vuelve negativa antes."
                        ),
                        (
                            "El 2x y el 3x existen porque el costo real no es constante: el spread "
                            "se abre con las noticias, el deslizamiento crece con la volatilidad y "
                            "el bróker puede cambiar sus condiciones. Esas corridas miden cuánto "
                            "margen tienes antes de que el costo alcance a la señal."
                        ),
                    ],
                },
                {
                    "heading": "El costo de equilibrio: un solo número para reportar",
                    "paragraphs": [
                        (
                            "Busca el costo por operación con el que el resultado neto llega a "
                            "cero: interpola entre 1x, 2x y 3x, o repite el backtest con costos "
                            "intermedios hasta cruzar el cero. Ese es el costo de equilibrio, en "
                            "la misma unidad que tu costo: puntos, pips o moneda de la cuenta."
                        ),
                        (
                            "Repórtalo junto al costo real: si el costo de equilibrio triplica tu "
                            "costo real, hay espacio para un spread peor; si apenas lo supera, el "
                            "resultado depende de que el bróker no cambie nada. Rigor mide esto en "
                            "cada auditoría: el resultado a 1x, 2x y 3x y el costo de equilibrio, "
                            "etiquetados como Medido, Declarado o No medido."
                        ),
                    ],
                },
                {
                    "heading": "Cómo estimar tu costo con el estado de cuenta",
                    "paragraphs": [
                        (
                            "Abre el historial de la cuenta en MT5 o el estado de cuenta mensual y "
                            "suma, sobre las operaciones cerradas, las columnas de comisión y "
                            "swap. Divide entre el número de operaciones cerradas: esa es la parte "
                            "fija de tu costo. Si comisión y swap suman 600 en 300 operaciones, "
                            "esa parte es 2 por operación."
                        ),
                        (
                            "El spread y el deslizamiento van dentro del precio de ejecución. Para "
                            "el spread, anota la diferencia entre compra y venta en las horas en "
                            "que opera tu estrategia y toma la mediana de varios días. Para el "
                            "deslizamiento, compara el precio pedido con el ejecutado en tu "
                            "historial de órdenes, sobre todo en los stops. Suma ambos a la parte "
                            "fija: ese es tu costo 1x."
                        ),
                    ],
                },
                {
                    "heading": "Tres trampas típicas",
                    "paragraphs": [
                        (
                            "Spread fijo en un mercado de spread variable. Un spread fijo medido "
                            "en horas tranquilas subestima el costo de una estrategia que opera en "
                            "la apertura o con noticias. Usa el spread histórico si tus datos lo "
                            "traen."
                        ),
                        (
                            "Sin deslizamiento en los stops. El probador ejecuta el stop loss en "
                            "el nivel exacto; en una cuenta real es una orden a mercado que se "
                            "ejecuta donde hay liquidez. Con stops cortos y muchas salidas por "
                            "stop, la pérdida por operación queda subestimada. Agrega "
                            "deslizamiento a cada stop."
                        ),
                        (
                            "Ignorar el swap en posiciones nocturnas. Una estrategia que mantiene "
                            "posiciones durante días o semanas paga swap cada noche, y en algunos "
                            "instrumentos suma más que el spread. Comprueba que el swap del "
                            "probador coincide con el de tu bróker."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "The four costs every trade pays",
                    "paragraphs": [
                        (
                            "The spread is the gap between the buy and sell price when you open: "
                            "you pay it on entry, it changes with the hour and it widens on news. "
                            "Commission is a fixed amount per lot or per trade that ECN brokers "
                            "charge."
                        ),
                        (
                            "Slippage is the difference between the price you asked for and the "
                            "price you were filled at; it appears when the market moves before the "
                            "fill, especially on stops. Swap is what you pay or receive for "
                            "holding a position from one day to the next."
                        ),
                    ],
                },
                {
                    "heading": "Why zero cost flatters short-term strategies",
                    "paragraphs": [
                        (
                            "Cost is charged per trade and the edge is measured in points per "
                            "trade. A strategy that holds positions for days captures many points "
                            "in each one; a scalper aiming for a few points pays the same spread "
                            "for a much smaller move."
                        ),
                        (
                            "The second effect is the number of trades: the more per year, the "
                            "more often you pay the cost. If the report's cost line reads zero, "
                            "the result is gross, not net."
                        ),
                    ],
                },
                {
                    "heading": "What changes at 1x, 2x and 3x",
                    "paragraphs": [
                        (
                            "Run the backtest with the per-trade cost you estimated (1x), with "
                            "double (2x) and with triple (3x). Note the net result, the maximum "
                            "drawdown and the Sharpe of each run. A strategy with margin stays "
                            "positive at 2x; a fragile one turns negative sooner."
                        ),
                        (
                            "The 2x and 3x runs exist because the real cost is not constant: the "
                            "spread widens on news, slippage grows with volatility and the "
                            "broker can change its conditions. Those runs measure how much margin "
                            "you have before the cost catches up with the signal."
                        ),
                    ],
                },
                {
                    "heading": "The break-even cost: one number to report",
                    "paragraphs": [
                        (
                            "Look for the per-trade cost at which the net result reaches zero: "
                            "interpolate between 1x, 2x and 3x, or repeat the backtest with "
                            "intermediate costs until it crosses zero. That is the break-even "
                            "cost, in the same unit as your cost: points, pips or account "
                            "currency."
                        ),
                        (
                            "Report it next to the real cost: if the break-even cost is three "
                            "times your real cost, there is room for a worse spread; if it is "
                            "barely above it, the result depends on the broker changing nothing. "
                            "Rigor measures this in every audit: the result at 1x, 2x and 3x and "
                            "the break-even cost, tagged Measured, Declared or Not measured."
                        ),
                    ],
                },
                {
                    "heading": "How to estimate your cost from a broker statement",
                    "paragraphs": [
                        (
                            "Open the account history in MT5 or the broker's monthly statement and "
                            "add up, over closed trades, the commission and swap columns. Divide "
                            "by the number of closed trades: that is the fixed part of your cost. "
                            "If commission and swap add up to 600 over 300 trades, that part is 2 "
                            "per trade."
                        ),
                        (
                            "Spread and slippage sit inside the fill price. For the spread, note "
                            "the gap between buy and sell during the hours your strategy trades "
                            "and take the median over several days. For slippage, compare the "
                            "requested price with the filled price in your order history, "
                            "especially on stops. Add both to the fixed part: that is your 1x cost."
                        ),
                    ],
                },
                {
                    "heading": "Three typical traps",
                    "paragraphs": [
                        (
                            "A fixed spread in a variable-spread market. A fixed spread measured "
                            "in quiet hours understates the cost of a strategy that trades at the "
                            "open or on news. Use the historical spread if your data carries it."
                        ),
                        (
                            "No slippage on stops. The tester fills the stop loss at the exact "
                            "level; in a real account it is a market order that fills where there "
                            "is liquidity. With tight stops and many stop exits, the loss per "
                            "trade is understated. Add slippage to every stop."
                        ),
                        (
                            "Ignoring swap on overnight positions. A strategy that holds positions "
                            "for days or weeks pays swap every night, and on some instruments it "
                            "adds up to more than the spread. Check that the tester's swap matches "
                            "your broker's."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Os quatro custos que cada operação paga",
                    "paragraphs": [
                        (
                            "O spread é a diferença entre o preço de compra e o de venda quando "
                            "você abre: você o paga na entrada, ele muda conforme a hora e dispara "
                            "com as notícias. A comissão é um valor fixo por lote ou por operação "
                            "que as corretoras ECN cobram."
                        ),
                        (
                            "O slippage é a diferença entre o preço que você pediu e o preço em "
                            "que foi executado; ele aparece quando o mercado se move antes da "
                            "execução, sobretudo nos stops. O swap é o que você paga ou recebe por "
                            "manter uma posição de um dia para o outro."
                        ),
                    ],
                },
                {
                    "heading": "Por que o custo zero favorece o curto prazo",
                    "paragraphs": [
                        (
                            "O custo é cobrado por operação e a vantagem se mede em pontos por "
                            "operação. Uma estratégia que mantém posições por dias captura muitos "
                            "pontos em cada uma; um scalper que busca poucos pontos paga o mesmo "
                            "spread por um movimento bem menor."
                        ),
                        (
                            "O segundo efeito é o número de operações: quanto mais por ano, mais "
                            "vezes você paga o custo. Se a linha de custos do relatório diz zero, "
                            "o resultado é bruto, não líquido."
                        ),
                    ],
                },
                {
                    "heading": "O que muda ao rodar a 1x, 2x e 3x",
                    "paragraphs": [
                        (
                            "Rode o backtest com o custo por operação que você estimou (1x), com o "
                            "dobro (2x) e com o triplo (3x). Anote o resultado líquido, o drawdown "
                            "máximo e o Sharpe de cada rodada. Uma estratégia com margem continua "
                            "positiva a 2x; uma frágil fica negativa antes."
                        ),
                        (
                            "O 2x e o 3x existem porque o custo real não é constante: o spread se "
                            "abre com as notícias, o slippage cresce com a volatilidade e a "
                            "corretora pode mudar as condições. Essas rodadas medem quanta margem "
                            "você tem antes que o custo alcance o sinal."
                        ),
                    ],
                },
                {
                    "heading": "O custo de equilíbrio: um único número para reportar",
                    "paragraphs": [
                        (
                            "Procure o custo por operação com o qual o resultado líquido chega a "
                            "zero: interpole entre 1x, 2x e 3x, ou repita o backtest com custos "
                            "intermediários até cruzar o zero. Esse é o custo de equilíbrio, na "
                            "mesma unidade do seu custo: pontos, pips ou moeda da conta."
                        ),
                        (
                            "Reporte-o ao lado do custo real: se o custo de equilíbrio for o "
                            "triplo do seu custo real, há espaço para um spread pior; se ficar só "
                            "um pouco acima, o resultado depende de a corretora não mudar nada. O "
                            "Rigor mede isso em cada auditoria: o resultado a 1x, 2x e 3x e o "
                            "custo de equilíbrio, marcados como Medido, Declarado ou Não medido."
                        ),
                    ],
                },
                {
                    "heading": "Como estimar o seu custo com o extrato da corretora",
                    "paragraphs": [
                        (
                            "Abra o histórico da conta no MT5 ou o extrato mensal da corretora e "
                            "some, sobre as operações fechadas, as colunas de comissão e swap. "
                            "Divida pelo número de operações fechadas: essa é a parte fixa do seu "
                            "custo. Se comissão e swap somam 600 em 300 operações, essa parte é 2 "
                            "por operação."
                        ),
                        (
                            "Spread e slippage ficam dentro do preço de execução. Para o spread, "
                            "anote a diferença entre compra e venda nas horas em que a sua "
                            "estratégia opera e pegue a mediana de vários dias. Para o slippage, "
                            "compare o preço pedido com o executado no seu histórico de ordens, "
                            "sobretudo nos stops. Some os dois à parte fixa: esse é o seu custo "
                            "1x."
                        ),
                    ],
                },
                {
                    "heading": "Três armadilhas típicas",
                    "paragraphs": [
                        (
                            "Spread fixo em um mercado de spread variável. Um spread fixo medido "
                            "em horas calmas subestima o custo de uma estratégia que opera na "
                            "abertura ou com notícias. Use o spread histórico se os seus dados o "
                            "trouxerem."
                        ),
                        (
                            "Sem slippage nos stops. O testador executa o stop loss no nível "
                            "exato; em uma conta real ele é uma ordem a mercado executada onde há "
                            "liquidez. Com stops curtos e muitas saídas por stop, a perda por "
                            "operação fica subestimada. Acrescente slippage a cada stop."
                        ),
                        (
                            "Ignorar o swap em posições overnight. Uma estratégia que mantém "
                            "posições por dias ou semanas paga swap toda noite, e em alguns "
                            "instrumentos ele soma mais do que o spread. Confira se o swap do "
                            "testador bate com o da sua corretora."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Qué costo uso si voy a operar en un reto de prop firm?",
                    "a": (
                        "El del reto, no el de tu bróker: la cuenta del reto tiene su propia "
                        "comisión por lote y su propio spread. Pide esas condiciones a la firma, "
                        "corre el backtest con ellas y compara el costo de equilibrio con ese "
                        "costo. Las reglas de pérdida diaria hacen más relevante la corrida a 2x."
                    ),
                },
                {
                    "q": "¿El spread del backtest de MT5 es el real?",
                    "a": (
                        "Depende de los datos. MT5 guarda el spread por barra solo cuando el "
                        "bróker lo entrega; si tus datos vinieron sin spread, el probador usa el "
                        "spread fijo que configuraste o el actual. El reporte del probador indica "
                        "qué spread usó."
                    ),
                },
                {
                    "q": "¿Un resultado positivo a 3x significa que la estrategia es sólida?",
                    "a": (
                        "Solo que el resultado tiene margen frente al costo. No dice cuántas "
                        "configuraciones se probaron ni cuántos años cubre el historial: con tres "
                        "años de retornos diarios y ninguna ventaja real, la mejor de 100 "
                        "configuraciones muestra un Sharpe cercano a 1.5 solo por suerte. La "
                        "calculadora de Rigor te da ese número con tus datos, gratis y sin "
                        "registro."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Which cost do I use if I am going to trade a prop-firm challenge?",
                    "a": (
                        "The challenge's, not your broker's: the challenge account has its own "
                        "commission per lot and its own spread. Ask the firm for those conditions, "
                        "run the backtest with them and compare the break-even cost against that "
                        "cost. The daily-loss rules make the 2x run more relevant."
                    ),
                },
                {
                    "q": "Is the spread in an MT5 backtest the real one?",
                    "a": (
                        "It depends on the data. MT5 stores the spread per bar only when the "
                        "broker delivers it; if your data came without spread, the tester uses the "
                        "fixed spread you configured or the current one. The tester report states "
                        "which spread it used."
                    ),
                },
                {
                    "q": "Does a positive result at 3x mean the strategy is solid?",
                    "a": (
                        "Only that the result has margin against cost. It says nothing about how "
                        "many configurations were tried or how many years the history covers: with "
                        "three years of daily returns and no real edge, the best of 100 "
                        "configurations shows a Sharpe near 1.5 by luck alone. Rigor's calculator "
                        "gives you that number with your own data, free and with no signup."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "Qual custo eu uso se vou operar em um desafio de prop firm?",
                    "a": (
                        "O do desafio, não o da sua corretora: a conta do desafio tem a sua "
                        "própria comissão por lote e o seu próprio spread. Peça essas condições à "
                        "empresa, rode o backtest com elas e compare o custo de equilíbrio com "
                        "esse custo. As regras de perda diária tornam a rodada a 2x mais "
                        "relevante."
                    ),
                },
                {
                    "q": "O spread do backtest no MT5 é o real?",
                    "a": (
                        "Depende dos dados. O MT5 guarda o spread por barra só quando a corretora "
                        "o entrega; se os seus dados vieram sem spread, o testador usa o spread "
                        "fixo que você configurou ou o atual. O relatório do testador informa qual "
                        "spread usou."
                    ),
                },
                {
                    "q": "Um resultado positivo a 3x significa que a estratégia é sólida?",
                    "a": (
                        "Só que o resultado tem margem diante do custo. Não diz quantas "
                        "configurações foram testadas nem quantos anos o histórico cobre: com três "
                        "anos de retornos diários e nenhuma vantagem real, a melhor de 100 "
                        "configurações mostra um Sharpe perto de 1.5 só por sorte. A calculadora "
                        "do Rigor dá esse número com os seus dados, de graça e sem cadastro."
                    ),
                },
            ],
        },
        "related": [
            {
                "kind": "calculator",
            },
            {
                "kind": "guide",
                "slug": "mt5",
            },
            {
                "kind": "audience",
                "slug": "retos-prop-firm",
            },
            {
                "kind": "method",
            },
        ],
    },
    {
        "key": "leer-informe-probador-mt5",
        "slug": {
            "es": "leer-informe-probador-mt5",
            "en": "read-mt5-strategy-tester-report",
            "pt": "ler-relatorio-testador-mt5",
        },
        "title": {
            "es": "Cómo leer el informe del probador de MT5 y lo que no te dice",
            "en": "How to read the MT5 Strategy Tester report (and what it omits)",
            "pt": "Como ler o relatório do testador do MT5 e o que ele não diz",
        },
        "seo_title": {
            "es": "Cómo leer el informe del probador MT5 y qué omite",
            "en": "How to read the MT5 Strategy Tester report and its gaps",
            "pt": "Como ler o relatório do testador MT5 e suas omissões",
        },
        "summary": {
            "es": (
                "Qué significa cada número del informe del probador de estrategias de MT5, cuáles "
                "se leen mal, qué omite el informe y qué agregar antes de confiar en él."
            ),
            "en": (
                "What each number in the MT5 Strategy Tester report means, which ones are easy to "
                "misread, what the report leaves out and what to add before trusting it."
            ),
            "pt": (
                "O que significa cada número do relatório do testador do MT5, quais se leem mal, o "
                "que o relatório omite e o que acrescentar antes de confiar nele."
            ),
        },
        "intro": {
            "es": (
                "El informe del probador de estrategias de MT5 resume una sola corrida: cuántas "
                "operaciones hizo el robot, la relación entre lo que sumaron las operaciones "
                "positivas y lo que restaron las negativas (factor de beneficio), el resultado "
                "neto promedio por operación (beneficio esperado), cuánto cayó la cuenta desde su "
                "máximo (drawdown) y un Sharpe que el propio probador calcula. Esos cinco números "
                "se leen en un minuto. Lo que el informe no trae importa casi más: no dice cuántas "
                "configuraciones probaste antes de esta, qué costos supuso, si los datos tenían "
                "huecos ni si alguna parte del periodo quedó fuera de la optimización. Este "
                "artículo explica cada número, los que se malinterpretan y qué agregar antes de "
                "confiar en el resultado."
            ),
            "en": (
                "The MT5 Strategy Tester report summarises a single run: how many trades the robot "
                "made, the ratio between what the positive trades added and what the negative ones "
                "took away (profit factor), the average net result per trade (expected payoff), "
                "how far the account fell from its peak (drawdown) and a Sharpe the tester "
                "computes itself. Those five numbers take a minute to read. What the report leaves "
                "out matters almost more: it does not say how many configurations you tried before "
                "this one, which costs it assumed, whether the data had holes, or whether any part "
                "of the period was kept out of the optimisation. This article explains each "
                "number, the ones that get misread and what to add before trusting the result."
            ),
            "pt": (
                "O relatório do testador de estratégias do MT5 resume uma única rodada: quantas "
                "operações o robô fez, a relação entre o que as operações positivas somaram e o "
                "que as negativas tiraram (fator de lucro), o resultado líquido médio por operação "
                "(lucro esperado), quanto a conta caiu desde o pico (drawdown) e um Sharpe que o "
                "próprio testador calcula. Esses cinco números se leem em um minuto. O que o "
                "relatório deixa de fora importa quase mais: ele não diz quantas configurações "
                "você testou antes desta, quais custos assumiu, se os dados tinham buracos, nem se "
                "alguma parte do período ficou fora da otimização. Este artigo explica cada "
                "número, os que são mal interpretados e o que acrescentar antes de confiar no "
                "resultado."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Qué trae el informe y de dónde sale",
                    "paragraphs": [
                        (
                            "El informe se guarda desde la pestaña Backtest: clic derecho, "
                            "Informe, HTML u Open XML (en versiones antiguas, Guardar como "
                            "informe). Arriba va el encabezado con experto, símbolo, periodo, "
                            "parámetros, depósito inicial y apalancamiento; abajo, los resultados "
                            "y la curva de balance y equidad."
                        ),
                        (
                            "Todo describe una sola corrida, con una sola configuración, sobre un "
                            "solo rango de fechas. La guía para exportar el informe de MT5 muestra "
                            "el archivo exacto paso a paso."
                        ),
                    ],
                },
                {
                    "heading": "Los cinco números que debes mirar primero",
                    "paragraphs": [
                        (
                            "Total de operaciones: cuántas veces entró y salió el robot. Con "
                            "pocas, los demás números dependen de dos o tres resultados grandes. "
                            "Anota también los años que cubre el periodo."
                        ),
                        (
                            "Factor de beneficio: la suma de las operaciones positivas entre la "
                            "suma de las negativas. Beneficio esperado (expected payoff): el "
                            "resultado neto entre el número de operaciones, en la moneda de la "
                            "cuenta; crece con el lote aunque la estrategia sea la misma."
                        ),
                        (
                            "Drawdown: hay reducción del balance y de la equidad, cada una "
                            "absoluta, máxima y relativa. Para una cuenta real o un reto mira la "
                            "máxima de la equidad, que incluye las pérdidas flotantes. El quinto, "
                            "el Sharpe, va en la siguiente sección."
                        ),
                    ],
                },
                {
                    "heading": "Los números que se leen mal con facilidad",
                    "paragraphs": [
                        (
                            "El porcentaje de operaciones positivas engaña solo. Un grid o una "
                            "martingala cierra casi todo en positivo y guarda la pérdida en una "
                            "sola operación grande: compara la operación de mayor pérdida con el "
                            "beneficio promedio por operación. Si una negativa borra docenas de "
                            "positivas, el porcentaje no sirve."
                        ),
                        (
                            "El Sharpe del informe no indica qué retornos usó ni si está "
                            "anualizado, así que no es comparable con un Sharpe calculado sobre "
                            "retornos diarios, como el de la calculadora de Rigor. Sirve para "
                            "comparar corridas en el mismo probador, nada más."
                        ),
                    ],
                },
                {
                    "heading": "Modo de ticks y calidad del modelado",
                    "paragraphs": [
                        (
                            "MT5 tiene cuatro modos de ticks: cada tick, cada tick basado en ticks "
                            "reales, OHLC de 1 minuto y solo precios de apertura. Sin ticks "
                            "reales, el probador fabrica el recorrido del precio dentro de cada "
                            "minuto a partir de las barras, y los stops se ejecutan sobre ese "
                            "camino inventado. Con ticks reales rellena con ticks generados donde "
                            "faltan; el informe muestra el total, no cuáles eran reales."
                        ),
                        (
                            "OHLC de 1 minuto y solo apertura sirven para explorar, no para el "
                            "informe final: no ven el precio dentro de la barra ni saben si el "
                            "stop o el take profit se tocó primero. Para compartir usa ticks "
                            "reales y anota el modo."
                        ),
                    ],
                },
                {
                    "heading": "Lo que el informe nunca dice",
                    "paragraphs": [
                        (
                            "Cuántas configuraciones probaste. El informe describe la última "
                            "corrida; las anteriores quedan en el XML de optimización. Con tres "
                            "años de retornos diarios y sin ninguna ventaja real, la mejor de 10 "
                            "configuraciones muestra un Sharpe de alrededor de 0.9 solo por "
                            "suerte; la mejor de 100, 1.5; la mejor de 1,000, 1.9."
                        ),
                        (
                            "Qué costos supuso ni con qué datos. No hay línea de costos: el spread "
                            "fue el del ajuste, la comisión la del servidor del bróker y el "
                            "deslizamiento solo el retraso de ejecución que configuraras. Tampoco "
                            "revisa barras duplicadas, precios congelados, huecos ni picos."
                        ),
                        (
                            "Si hubo fuera de muestra. Nada indica que el periodo se haya "
                            "dividido: si elegiste los parámetros mirando estas mismas fechas, el "
                            "resultado es dentro de muestra, por bueno que se vea."
                        ),
                    ],
                },
                {
                    "heading": "Qué agregar antes de confiar en él",
                    "paragraphs": [
                        (
                            "Primero, escribe lo que el informe omite: pases de la optimización, "
                            "modo de ticks, spread y comisión, y fechas optimizadas. Exporta el "
                            "XML de optimización junto con el informe; la guía de la optimización "
                            "de MT5 explica cómo."
                        ),
                        (
                            "Segundo, repite la corrida final con ticks reales y con el doble y el "
                            "triple del costo por operación; anota en qué costo el resultado neto "
                            "llega a cero. Tercero, córrela sobre fechas que no usaste para "
                            "optimizar y reporta ese resultado aparte, aunque sea peor."
                        ),
                        (
                            "Cuarto, compara el Sharpe con lo que la suerte daría con tus años y "
                            "tus intentos: la calculadora de Rigor es gratuita y sin registro. "
                            "Rigor lee ambos archivos y mide, entre otras cosas, la significancia "
                            "del Sharpe, las configuraciones probadas, el resultado a 1x, 2x y 3x "
                            "costos y 35 banderas rojas de datos, cada uno etiquetado como Medido, "
                            "Declarado o No medido."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "What the report contains and where it comes from",
                    "paragraphs": [
                        (
                            "The report is saved from the Backtest tab: right-click, Report, HTML "
                            "or Open XML (older builds: Save as Report). At the top is the header "
                            "with expert, symbol, period, inputs, initial deposit and leverage; "
                            "below it, the results and the balance and equity curve."
                        ),
                        (
                            "Everything describes one run, with one configuration, over one date "
                            "range. The guide on exporting the MT5 report shows the exact file "
                            "step by step."
                        ),
                    ],
                },
                {
                    "heading": "The five numbers to look at first",
                    "paragraphs": [
                        (
                            "Total Trades: how many times the robot entered and exited. With few, "
                            "the other numbers hang on two or three large results. Note the years "
                            "the period covers too."
                        ),
                        (
                            "Profit Factor: the sum of the positive trades divided by the sum of "
                            "the negative ones. Expected Payoff: the net result divided by the "
                            "number of trades, in the account currency; it grows with the lot even "
                            "though the strategy is the same."
                        ),
                        (
                            "Drawdown: there is balance drawdown and equity drawdown, each "
                            "absolute, maximal and relative. For a real account or a challenge "
                            "look at the maximal equity one, which includes floating losses. The "
                            "fifth, the Sharpe, gets the next section."
                        ),
                    ],
                },
                {
                    "heading": "The numbers that are easy to misread",
                    "paragraphs": [
                        (
                            "The percentage of winning trades misleads on its own. A grid or a "
                            "martingale closes almost everything in the positive and stores the "
                            "loss in one large trade: compare the largest loss trade with the "
                            "average profit trade. If one negative trade wipes out dozens of "
                            "positive ones, the percentage is useless."
                        ),
                        (
                            "The report's Sharpe does not say which returns it used or whether it "
                            "is annualised, so it is not comparable with a Sharpe computed on "
                            "daily returns, like the one in Rigor's calculator. It is only useful "
                            "for comparing runs in the same tester."
                        ),
                    ],
                },
                {
                    "heading": "Tick mode and modelling quality",
                    "paragraphs": [
                        (
                            "MT5 has four tick modes: every tick, every tick based on real ticks, "
                            "1 minute OHLC and open prices only. Without real ticks, the tester "
                            "fabricates the price path inside each minute from the bars, and the "
                            "stops are filled on that invented path. With real ticks it fills in "
                            "generated ones where they are missing; the report shows the total, "
                            "not which were real."
                        ),
                        (
                            "1 minute OHLC and open prices only are for exploring, not for the "
                            "final report: they do not see the price inside the bar or know "
                            "whether the stop or the take profit was touched first. For sharing, "
                            "use real ticks and note the mode."
                        ),
                    ],
                },
                {
                    "heading": "What the report never says",
                    "paragraphs": [
                        (
                            "How many configurations you tried. The report describes the last run; "
                            "the earlier ones stay in the optimisation XML. With three years of "
                            "daily returns and no real edge, the best of 10 configurations shows a "
                            "Sharpe of about 0.9 by luck alone; the best of 100, 1.5; the best of "
                            "1,000, 1.9."
                        ),
                        (
                            "Which costs it assumed, or on what data. There is no cost line: the "
                            "spread was the setting, the commission the broker server's and the "
                            "slippage only the execution delay you configured. It does not check "
                            "duplicate bars, frozen prices, gaps or spikes either."
                        ),
                        (
                            "Whether there was an out-of-sample. Nothing shows that the period was "
                            "split: if you chose the parameters while looking at these same dates, "
                            "the result is in-sample, however good it looks."
                        ),
                    ],
                },
                {
                    "heading": "What to add before trusting it",
                    "paragraphs": [
                        (
                            "First, write down what the report omits: optimisation passes, tick "
                            "mode, spread and commission, and the dates optimised. Export the "
                            "optimisation XML together with the report; the guide on the MT5 "
                            "optimisation explains how."
                        ),
                        (
                            "Second, repeat the final run with real ticks and with double and "
                            "triple the cost per trade; note at which cost the net result reaches "
                            "zero. Third, run it on dates you did not use to optimise and report "
                            "that result separately, even if it is worse."
                        ),
                        (
                            "Fourth, compare the Sharpe with what luck would give with your years "
                            "and your tries: Rigor's calculator is free and needs no signup. Rigor "
                            "reads both files and measures, among other things, the significance "
                            "of the Sharpe, the configurations tried, the result at 1x, 2x and 3x "
                            "costs and 35 data red flags, each tagged Measured, Declared or Not "
                            "measured."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "O que o relatório traz e de onde ele sai",
                    "paragraphs": [
                        (
                            "O relatório é salvo na aba Backtest: clique com o botão direito, "
                            "Report, HTML ou Open XML (versões antigas: Save as Report). No topo "
                            "vem o cabeçalho com expert, símbolo, período, parâmetros, depósito "
                            "inicial e alavancagem; abaixo, os resultados e a curva de saldo e "
                            "patrimônio."
                        ),
                        (
                            "Tudo descreve uma única rodada, com uma única configuração, sobre um "
                            "único intervalo de datas. O guia para exportar o relatório do MT5 "
                            "mostra o arquivo exato passo a passo."
                        ),
                    ],
                },
                {
                    "heading": "Os cinco números para olhar primeiro",
                    "paragraphs": [
                        (
                            "Total de operações: quantas vezes o robô entrou e saiu. Com poucas, "
                            "os outros números dependem de dois ou três resultados grandes. Anote "
                            "também quantos anos o período cobre."
                        ),
                        (
                            "Fator de lucro: a soma das operações positivas dividida pela soma das "
                            "negativas. Lucro esperado (expected payoff): o resultado líquido "
                            "dividido pelo número de operações, na moeda da conta; cresce com o "
                            "lote mesmo que a estratégia seja a mesma."
                        ),
                        (
                            "Drawdown: há redução do saldo e do patrimônio, cada uma absoluta, "
                            "máxima e relativa. Para uma conta real ou um desafio olhe a máxima do "
                            "patrimônio, que inclui as perdas flutuantes. O quinto, o Sharpe, fica "
                            "para a próxima seção."
                        ),
                    ],
                },
                {
                    "heading": "Os números que se leem mal com facilidade",
                    "paragraphs": [
                        (
                            "O percentual de operações positivas engana sozinho. Um grid ou um "
                            "martingale fecha quase tudo no positivo e guarda a perda em uma única "
                            "operação grande: compare a operação de maior perda com o lucro médio "
                            "por operação. Se uma negativa apaga dezenas de positivas, o "
                            "percentual não serve."
                        ),
                        (
                            "O Sharpe do relatório não indica quais retornos usou nem se está "
                            "anualizado, então não é comparável com um Sharpe calculado sobre "
                            "retornos diários, como o da calculadora do Rigor. Ele serve para "
                            "comparar rodadas no mesmo testador, nada mais."
                        ),
                    ],
                },
                {
                    "heading": "Modo de ticks e qualidade da modelagem",
                    "paragraphs": [
                        (
                            "O MT5 tem quatro modos de ticks: cada tick, cada tick com base em "
                            "ticks reais, OHLC de 1 minuto e só preços de abertura. Sem ticks "
                            "reais, o testador fabrica o caminho do preço dentro de cada minuto a "
                            "partir das barras, e os stops são executados sobre esse caminho "
                            "inventado. Com ticks reais ele preenche com ticks gerados onde "
                            "faltam; o relatório mostra o total, não quais eram reais."
                        ),
                        (
                            "OHLC de 1 minuto e só abertura servem para explorar, não para o "
                            "relatório final: eles não veem o preço dentro da barra nem sabem se o "
                            "stop ou o take profit foi tocado primeiro. Para compartilhar, use "
                            "ticks reais e anote o modo."
                        ),
                    ],
                },
                {
                    "heading": "O que o relatório nunca diz",
                    "paragraphs": [
                        (
                            "Quantas configurações você testou. O relatório descreve a última "
                            "rodada; as anteriores ficam no XML de otimização. Com três anos de "
                            "retornos diários e nenhuma vantagem real, a melhor de 10 "
                            "configurações mostra um Sharpe de cerca de 0.9 só por sorte; a melhor "
                            "de 100, 1.5; a melhor de mil, 1.9."
                        ),
                        (
                            "Quais custos assumiu, nem com quais dados. Não há linha de custos: o "
                            "spread foi o da configuração, a comissão a do servidor da corretora e "
                            "o slippage só o atraso de execução que você definiu. Ele também não "
                            "confere barras duplicadas, preços congelados, buracos nem picos."
                        ),
                        (
                            "Se houve fora da amostra. Nada mostra que o período foi dividido: se "
                            "você escolheu os parâmetros olhando essas mesmas datas, o resultado é "
                            "dentro da amostra, por melhor que pareça."
                        ),
                    ],
                },
                {
                    "heading": "O que acrescentar antes de confiar nele",
                    "paragraphs": [
                        (
                            "Primeiro, escreva o que o relatório omite: passagens da otimização, "
                            "modo de ticks, spread e comissão, e datas otimizadas. Exporte o XML "
                            "de otimização junto com o relatório; o guia da otimização do MT5 "
                            "explica como."
                        ),
                        (
                            "Segundo, repita a rodada final com ticks reais e com o dobro e o "
                            "triplo do custo por operação; anote em qual custo o resultado líquido "
                            "chega a zero. Terceiro, rode-a em datas que você não usou para "
                            "otimizar e reporte esse resultado à parte, mesmo que seja pior."
                        ),
                        (
                            "Quarto, compare o Sharpe com o que a sorte daria com os seus anos e "
                            "as suas tentativas: a calculadora do Rigor é gratuita e não pede "
                            "cadastro. O Rigor lê os dois arquivos e mede, entre outras coisas, a "
                            "significância do Sharpe, as configurações testadas, o resultado a 1x, "
                            "2x e 3x custos e 35 sinais de alerta nos dados, cada um marcado como "
                            "Medido, Declarado ou Não medido."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Un Sharpe de 2 en el informe del probador es bueno?",
                    "a": (
                        "Depende de cuántas configuraciones probaste y de cuántos años cubre el "
                        "periodo: con dos años y 500 intentos, la mejor configuración sin ventaja "
                        "real muestra alrededor de 2.2 solo por suerte; con un año y 200 intentos, "
                        "alrededor de 2.8."
                    ),
                },
                {
                    "q": "¿Qué significa Calidad del historial 100%?",
                    "a": (
                        "Que no faltaron barras de un minuto y que ninguna tenía volumen 1 con "
                        "precios distintos, lo único que MT5 cuenta como dato incorrecto. No dice "
                        "si esas barras traen precios congelados, picos falsos o duplicados, ni si "
                        "los ticks de cada minuto eran reales o generados."
                    ),
                },
                {
                    "q": "¿Cuántas operaciones necesita el informe para ser confiable?",
                    "a": (
                        "El informe no lo responde: depende de los años cubiertos y de los "
                        "intentos previos, no solo del conteo. Con 1,000 intentos hacen falta unos "
                        "3.3 años de datos para que la suerte sola quede por debajo de un Sharpe "
                        "de 1.8. Pon tus años y tus intentos en la calculadora."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Is a Sharpe of 2 in the tester report good?",
                    "a": (
                        "It depends on how many configurations you tried and how many years the "
                        "period covers: with two years and 500 tries, the best configuration with "
                        "no real edge shows about 2.2 by luck alone; with one year and 200 tries, "
                        "about 2.8."
                    ),
                },
                {
                    "q": "What does History Quality 100% mean?",
                    "a": (
                        "That no one-minute bars were missing and none had a volume of 1 with "
                        "differing OHLC, the only thing MT5 counts as incorrect data. It does not "
                        "say whether those bars carry frozen prices, false spikes or duplicates, "
                        "or whether the ticks in each minute were real or generated."
                    ),
                },
                {
                    "q": "How many trades does the report need to be reliable?",
                    "a": (
                        "The report does not answer that: it depends on the years covered and the "
                        "tries before it, not only on the count. With 1,000 tries, about 3.3 years "
                        "of data are needed for luck alone to fall under a Sharpe of 1.8. Put your "
                        "years and your tries into the calculator."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "Um Sharpe de 2 no relatório do testador é bom?",
                    "a": (
                        "Depende de quantas configurações você testou e de quantos anos o período "
                        "cobre: com dois anos e 500 tentativas, a melhor configuração sem vantagem "
                        "real mostra cerca de 2.2 só por sorte; com um ano e 200 tentativas, cerca "
                        "de 2.8."
                    ),
                },
                {
                    "q": "O que significa Qualidade do histórico 100%?",
                    "a": (
                        "Que não faltaram barras de um minuto e nenhuma tinha volume 1 com preços "
                        "diferentes, a única coisa que o MT5 conta como dado incorreto. Não diz se "
                        "essas barras trazem preços congelados, picos falsos ou duplicatas, nem se "
                        "os ticks de cada minuto eram reais ou gerados."
                    ),
                },
                {
                    "q": "Quantas operações o relatório precisa para ser confiável?",
                    "a": (
                        "O relatório não responde isso: depende dos anos cobertos e das tentativas "
                        "anteriores, não só da contagem. Com mil tentativas, são necessários cerca "
                        "de 3.3 anos de dados para que a sorte sozinha fique abaixo de um Sharpe "
                        "de 1.8. Coloque os seus anos e as suas tentativas na calculadora."
                    ),
                },
            ],
        },
        "related": [
            {
                "kind": "guide",
                "slug": "mt5",
            },
            {
                "kind": "guide",
                "slug": "mt5-optimization",
            },
            {
                "kind": "calculator",
            },
            {
                "kind": "method",
            },
        ],
    },
    {
        "key": "auditoria-independiente-backtest",
        "slug": {
            "es": "auditoria-independiente-backtest",
            "en": "independent-backtest-audit",
            "pt": "auditoria-independente-backtest",
        },
        "title": {
            "es": "Auditoría independiente de un backtest: qué revisa que una réplica no",
            "en": "Independent backtest audit: scope and evidence",
            "pt": (
                "Auditoria independente de um backtest: o que uma revisão estatística examina "
                "além da réplica"
            ),
        },
        "seo_title": {
            "es": "Auditoría independiente de backtest: más allá de replicar",
            "pt": "Auditoria independente de backtest: além da réplica",
        },
        "summary": {
            "es": (
                "Qué examina una revisión estadística de un backtest, cómo trata la selección "
                "de variantes y qué distingue los datos medidos de las declaraciones."
            ),
            "en": (
                "What a statistical review of a trading strategy examines: variant selection, "
                "costs and the difference between measured and declared evidence."
            ),
            "pt": (
                "O que uma revisão estatística de um backtest examina, como trata a seleção de "
                "variantes e por que uma medição difere de uma declaração."
            ),
        },
        "intro": {
            "es": (
                "Una réplica pregunta si las mismas reglas, datos y supuestos reproducen una "
                "trayectoria. Una auditoría estadística pregunta qué evidencia contiene esa "
                "trayectoria una vez consideradas la incertidumbre, la selección y la "
                "información que falta. Son trabajos complementarios. Una réplica puede "
                "reproducir exactamente una elección ajustada al historial; una revisión "
                "estadística puede detectar debilidades sin reconstruir la lógica que produjo "
                "las operaciones. Rigor analiza los archivos entregados y las declaraciones que "
                "los acompañan. Ese alcance importa cuando una gestora compara investigaciones "
                "o un proveedor prepara la documentación de una señal para otra persona."
            ),
            "en": (
                "A replication asks whether the same rules, data and assumptions reproduce a "
                "track record. A statistical audit asks what evidence that record contains "
                "after accounting for uncertainty, selection and missing information. These are "
                "complementary tasks. Replication can reproduce a choice fitted to historical "
                "data exactly; statistical review can identify weaknesses without rebuilding "
                "the logic behind the trades. Rigor analyses the supplied files and the "
                "declarations that accompany them. That scope matters when a fund compares "
                "research projects or a signal provider prepares a record for someone else's "
                "review."
            ),
            "pt": (
                "Uma réplica pergunta se as mesmas regras, dados e premissas reproduzem uma "
                "trajetória. Uma auditoria estatística pergunta que evidência essa trajetória "
                "contém depois de considerar incerteza, seleção e informação ausente. São "
                "trabalhos complementares. Uma réplica pode reproduzir exatamente uma escolha "
                "ajustada ao histórico; uma revisão estatística pode identificar fragilidades "
                "sem reconstruir a lógica que gerou as operações. O Rigor analisa os arquivos "
                "enviados e as declarações que os acompanham. Esse escopo importa quando uma "
                "gestora compara pesquisas ou um fornecedor prepara a documentação de um sinal "
                "para outra pessoa."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Qué significa independiente en esta revisión",
                    "paragraphs": [
                        (
                            "La independencia empieza por separar el análisis del producto "
                            "evaluado. Rigor no vende robots ni señales, y el precio del "
                            "informe no depende de la clase obtenida. Su metodología publica "
                            "las preguntas, las reglas de evaluación y las limitaciones. Esto "
                            "permite discutir una conclusión concreta y el archivo que la "
                            "sostiene. No convierte al auditor en observador de todo el proceso "
                            "de investigación: los ensayos descartados, las modificaciones "
                            "anteriores y las decisiones no registradas pueden quedar fuera de "
                            "los materiales entregados."
                        ),
                    ],
                },
                {
                    "heading": "Evidencia estadística frente al azar",
                    "paragraphs": [
                        (
                            "La primera comprobación estudia cuánto respaldo tiene el Sharpe "
                            "observado. El Sharpe probabilístico considera la longitud de la "
                            "serie, la asimetría y la curtosis. El informe también examina "
                            "dependencia temporal y remuestrea bloques de retornos mediante "
                            "bootstrap estacionario. Los bloques conservan parte de la "
                            "estructura local que se perdería al mezclar observaciones "
                            "aisladas. El resultado sigue dependiendo de la muestra recibida y "
                            "del método. Una serie corta, irregular o dominada por episodios "
                            "concretos exige leer la incertidumbre junto con la cifra "
                            "principal; repetir el cálculo no elimina esa incertidumbre."
                        ),
                    ],
                },
                {
                    "heading": "Selección entre variantes",
                    "paragraphs": [
                        (
                            "La siguiente pregunta es cuántas oportunidades hubo de encontrar "
                            "una curva llamativa. El Sharpe deflactado compara el resultado con "
                            "una referencia que aumenta al considerar más intentos. Rigor "
                            "utiliza el mayor conteo entre la declaración y la evidencia de "
                            "variantes o pasadas de optimización entregadas. Cuando hay una "
                            "matriz de variantes, puede estudiar además el sobreajuste mediante "
                            "validación cruzada combinatoria. La curva ganadora aislada no "
                            "cuenta la historia de las alternativas descartadas."
                        ),
                        (
                            f"{INDEPENDENT_LUCK_EXAMPLE['es']} "
                            "La calculadora ilustra la selección bajo sus supuestos; no mide "
                            "una estrategia del lector. La independencia entre intentos es una "
                            "simplificación: variantes parecidas pueden compartir gran parte de "
                            "su comportamiento. Tampoco permite reconstruir búsquedas "
                            "anteriores que nadie documentó."
                        ),
                    ],
                },
                {
                    "heading": "Sensibilidad a los costos",
                    "paragraphs": [
                        (
                            "La comprobación de costos recalcula operaciones con distintos "
                            "niveles de fricción y estudia el costo de equilibrio. Necesita "
                            "detalles de operaciones y supuestos identificables. Una curva neta "
                            "por sí sola no permite separar comisión, diferencial y "
                            "deslizamiento ni deducir cómo cambiarían con otro volumen. Si "
                            "faltan las operaciones, esta parte puede quedar sin medir aunque "
                            "otras estadísticas sí se calculen. La diferencia es relevante para "
                            "una réplica: reproducir la misma hipótesis de costos confirma "
                            "coherencia del cálculo, pero deja abierta la sensibilidad a "
                            "hipótesis diferentes."
                        ),
                    ],
                },
                {
                    "heading": "Comportamiento fuera de muestra",
                    "paragraphs": [
                        (
                            "El informe compara el tramo posterior a la fecha declarada como "
                            "inicio fuera de muestra con el tramo anterior. Examina su Sharpe y "
                            "la distancia entre ambos. La fecha es una declaración del cliente; "
                            "el archivo por sí solo no demuestra que se eligiera antes de "
                            "conocer los resultados. Cambiar reglas después de mirar ese tramo "
                            "altera su interpretación aunque las fechas sigan intactas. Si "
                            "falta la fecha o los tramos no contienen datos suficientes, el "
                            "informe indica la limitación en lugar de fabricar una comparación."
                        ),
                    ],
                },
                {
                    "heading": "Calidad de los datos",
                    "paragraphs": [
                        (
                            "Otra dimensión busca señales de problemas en los materiales: "
                            "duplicados, saltos, valores congelados, depósitos y patrones "
                            "asociados a martingala o rejilla, entre otros. Una bandera "
                            "requiere examinar la causa y el contexto; no reconstruye "
                            "automáticamente el historial original. La ausencia de banderas "
                            "tampoco establece la procedencia del archivo. Rigor lee lo "
                            "entregado y no contrasta registros con un bróker. Para una "
                            "gestora, conservar el export original y explicar transformaciones "
                            "facilita responder a observaciones concretas sin confundir "
                            "limpieza estadística con autenticidad de origen."
                        ),
                    ],
                },
                {
                    "heading": "Comparación con un benchmark",
                    "paragraphs": [
                        (
                            "La revisión compara la serie con el benchmark entregado mediante "
                            "exceso de retorno, relación entre drawdowns y ratio de "
                            "información. Las fechas deben solaparse lo suficiente para "
                            "sostener la comparación. Elegir una referencia pertinente sigue "
                            "siendo una decisión de investigación que conviene documentar: "
                            "comparar con una exposición distinta puede responder otra "
                            "pregunta. Sin el benchmark o sin un solapamiento suficiente, no se "
                            "puede inferir la comparación a partir del nombre de la estrategia. "
                            "La dimensión recoge esa ausencia y no la sustituye por una "
                            "expectativa."
                        ),
                    ],
                },
                {
                    "heading": "Medido, declarado y pendiente de datos",
                    "paragraphs": [
                        (
                            "MEASURED, o Medido, significa que el informe calculó el dato desde "
                            "el archivo recibido. DECLARED, o Declarado, identifica lo que "
                            "indicó el cliente o su plataforma y que el análisis no puede "
                            "comprobar. NOT_MEASURED indica información insuficiente para esa "
                            "medición. Estas etiquetas se aplican a cada dato: un Sharpe "
                            "calculado puede coexistir con un número de intentos declarado. "
                            "Medir una operación matemática no convierte sus premisas en hechos "
                            "observados. Al compartir el informe, conserva las etiquetas y las "
                            "limitaciones junto a las conclusiones, también cuando el resultado "
                            "complique la presentación inicial."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "What independent means in this review",
                    "paragraphs": [
                        (
                            "Independence starts with separating the analysis from the product "
                            "being examined. Rigor sells no robots or signals, and the report "
                            "price does not depend on the resulting class. Its methodology "
                            "publishes the questions, assessment rules and limitations. That "
                            "makes it possible to discuss a particular conclusion and the file "
                            "supporting it. It does not make the reviewer an observer of the "
                            "entire research process: discarded experiments, earlier changes "
                            "and unrecorded decisions can remain outside the materials "
                            "supplied. Documenting those gaps is part of reading the review."
                        ),
                    ],
                },
                {
                    "heading": "Statistical evidence against chance",
                    "paragraphs": [
                        (
                            "The first check examines the support for the observed Sharpe "
                            "ratio. The probabilistic Sharpe ratio accounts for record length, "
                            "skewness and kurtosis. The report also examines serial dependence "
                            "and resamples return blocks with a stationary bootstrap. Blocks "
                            "preserve some local structure that shuffling isolated observations "
                            "would discard. The result still depends on the supplied sample and "
                            "the method. A short, irregular record or a record dominated by "
                            "particular episodes calls for reading uncertainty alongside the "
                            "headline figure. Repeating the same calculation does not remove "
                            "that uncertainty or add observations."
                        ),
                    ],
                },
                {
                    "heading": "Selection across variants",
                    "paragraphs": [
                        (
                            "The next question is how many opportunities existed to find an "
                            "attractive curve. The deflated Sharpe ratio compares the result "
                            "with a reference that rises as more trials are considered. Rigor "
                            "uses the largest count supported by the declaration, uploaded "
                            "variants or optimisation passes. With a variants matrix, it can "
                            "also examine overfitting through combinatorial cross-validation. "
                            "The winning curve alone does not describe the discarded "
                            "alternatives or the decisions that selected it for publication."
                        ),
                        (
                            f"{INDEPENDENT_LUCK_EXAMPLE['en']} "
                            "The calculator illustrates selection under its assumptions; it "
                            "does not measure the reader's strategy. Independence across trials "
                            "is a simplification: similar variants can share much of their "
                            "behaviour. Nor can this example reconstruct earlier searches that "
                            "nobody documented."
                        ),
                    ],
                },
                {
                    "heading": "Sensitivity to trading costs",
                    "paragraphs": [
                        (
                            "The cost check recalculates trades at different friction levels "
                            "and examines the break-even cost. It requires trade details and "
                            "identifiable assumptions. A net return curve alone cannot separate "
                            "commission, spread and slippage or establish how they would change "
                            "at another size. If trades are missing, this section can remain "
                            "unmeasured even when other statistics are available. The "
                            "distinction matters for replication: reproducing the same cost "
                            "assumption establishes consistency of the calculation, while "
                            "sensitivity to different assumptions remains a separate question. "
                            "Cost labels should accompany any comparison between records."
                        ),
                    ],
                },
                {
                    "heading": "Behaviour outside the fitting sample",
                    "paragraphs": [
                        (
                            "The report compares the period after the declared out-of-sample "
                            "start with the preceding period. It examines their Sharpe ratios "
                            "and the gap between them. The date is a client declaration; the "
                            "file alone cannot establish that it was chosen before the results "
                            "were seen. Changing rules after looking at that period changes its "
                            "interpretation even when the dates remain intact. If the date is "
                            "missing or either part lacks enough observations, the report "
                            "identifies the limitation instead of constructing a comparison "
                            "from an unsuitable split."
                        ),
                    ],
                },
                {
                    "heading": "Data quality",
                    "paragraphs": [
                        (
                            "Another dimension looks for problems in the materials: duplicates, "
                            "spikes, frozen marks, deposits and patterns associated with "
                            "martingale or grid behaviour, among others. A flag calls for "
                            "examining its cause and context; it does not automatically "
                            "reconstruct the original history. The absence of flags does not "
                            "establish the file's provenance either. Rigor reads what is "
                            "supplied and does not reconcile records with a broker. Keeping the "
                            "original export and explaining transformations helps a fund "
                            "respond to specific observations without confusing statistical "
                            "cleanliness with evidence of origin."
                        ),
                    ],
                },
                {
                    "heading": "Comparison with a benchmark",
                    "paragraphs": [
                        (
                            "The review compares the record with the supplied benchmark using "
                            "excess return, the drawdown ratio and the information ratio. Dates "
                            "must overlap sufficiently to support that comparison. Choosing a "
                            "relevant reference remains a research decision worth documenting: "
                            "comparison with a different exposure may answer a different "
                            "question. Without the benchmark or sufficient overlap, the "
                            "comparison cannot be inferred from the strategy name. The "
                            "dimension records the missing evidence instead of replacing it "
                            "with an expectation. A benchmark comparison describes the supplied "
                            "period, including its particular market conditions."
                        ),
                    ],
                },
                {
                    "heading": "Measured, declared and awaiting data",
                    "paragraphs": [
                        (
                            "MEASURED means the report computed a value from the supplied file. "
                            "DECLARED identifies something stated by the client or platform "
                            "that the analysis cannot establish. NOT_MEASURED indicates "
                            "insufficient information for that measurement. These labels apply "
                            "to individual values: a computed Sharpe can sit alongside a "
                            "declared trial count. Measuring a mathematical operation does not "
                            "turn its premises into observed facts. When sharing the report, "
                            "keep the labels and limitations next to the conclusions, including "
                            "when a finding makes the original presentation harder to support "
                            "or leaves a question unresolved."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "O que significa independente nesta revisão",
                    "paragraphs": [
                        (
                            "A independência começa por separar a análise do produto examinado. "
                            "O Rigor não vende robôs nem sinais, e o preço do relatório não "
                            "depende da classe obtida. Sua metodologia publica as perguntas, as "
                            "regras de avaliação e as limitações. Isso permite discutir uma "
                            "conclusão específica e o arquivo que a sustenta. Não transforma o "
                            "auditor em observador de todo o processo de pesquisa: testes "
                            "descartados, alterações anteriores e decisões sem registro podem "
                            "ficar fora dos materiais enviados. Documentar essas lacunas faz "
                            "parte da leitura."
                        ),
                    ],
                },
                {
                    "heading": "Evidência estatística diante do acaso",
                    "paragraphs": [
                        (
                            "A primeira análise examina o suporte para o Sharpe observado. O "
                            "Sharpe probabilístico considera o comprimento da série, a "
                            "assimetria e a curtose. O relatório também examina dependência "
                            "temporal e reamostra blocos de retornos por bootstrap "
                            "estacionário. Os blocos preservam parte da estrutura local que "
                            "seria perdida ao embaralhar observações isoladas. O resultado "
                            "continua dependente da amostra recebida e do método. Uma série "
                            "curta, irregular ou dominada por episódios específicos exige ler a "
                            "incerteza junto com o número principal. Repetir o cálculo não "
                            "elimina essa incerteza nem acrescenta observações."
                        ),
                    ],
                },
                {
                    "heading": "Seleção entre variantes",
                    "paragraphs": [
                        (
                            "A pergunta seguinte é quantas oportunidades existiram para "
                            "encontrar uma curva chamativa. O Sharpe deflacionado compara o "
                            "resultado com uma referência que aumenta ao considerar mais "
                            "tentativas. O Rigor usa a maior contagem entre a declaração e a "
                            "evidência de variantes ou passagens de otimização enviadas. Quando "
                            "existe uma matriz de variantes, também pode examinar sobreajuste "
                            "por validação cruzada combinatória. A curva vencedora isolada não "
                            "descreve as alternativas descartadas nem as decisões que a "
                            "selecionaram para publicação."
                        ),
                        (
                            f"{INDEPENDENT_LUCK_EXAMPLE['pt']} "
                            "A calculadora ilustra a seleção sob suas premissas; não mede uma "
                            "estratégia do leitor. A independência entre tentativas é uma "
                            "simplificação: variantes semelhantes podem compartilhar boa parte "
                            "do comportamento. O exemplo também não reconstrói buscas "
                            "anteriores que ninguém documentou."
                        ),
                    ],
                },
                {
                    "heading": "Sensibilidade aos custos",
                    "paragraphs": [
                        (
                            "A análise de custos recalcula operações com diferentes níveis de "
                            "fricção e examina o custo de equilíbrio. Ela exige detalhes das "
                            "operações e premissas identificáveis. Uma curva líquida isolada "
                            "não separa comissão, spread e slippage nem estabelece como "
                            "mudariam com outro volume. Sem as operações, essa seção pode ficar "
                            "sem medição mesmo quando outras estatísticas estão disponíveis. A "
                            "distinção importa para a réplica: reproduzir a mesma hipótese de "
                            "custos estabelece consistência do cálculo, enquanto a "
                            "sensibilidade a outras hipóteses continua sendo uma pergunta "
                            "separada. Os rótulos dos custos devem acompanhar as comparações."
                        ),
                    ],
                },
                {
                    "heading": "Comportamento fora da amostra",
                    "paragraphs": [
                        (
                            "O relatório compara o período posterior à data declarada como "
                            "início fora da amostra com o período anterior. Examina seu Sharpe "
                            "e a distância entre ambos. A data é uma declaração do cliente; o "
                            "arquivo sozinho não demonstra que foi escolhida antes de conhecer "
                            "os resultados. Alterar regras depois de observar aquele período "
                            "muda sua interpretação mesmo quando as datas continuam intactas. "
                            "Se falta a data ou algum trecho tem observações insuficientes, o "
                            "relatório identifica a limitação em vez de construir uma "
                            "comparação a partir de uma divisão inadequada."
                        ),
                    ],
                },
                {
                    "heading": "Qualidade dos dados",
                    "paragraphs": [
                        (
                            "Outra dimensão procura problemas nos materiais: duplicados, "
                            "saltos, valores congelados, depósitos e padrões associados a "
                            "martingale ou grade, entre outros. Uma bandeira exige examinar sua "
                            "causa e seu contexto; não reconstrói automaticamente o histórico "
                            "original. A ausência de bandeiras também não estabelece a origem "
                            "do arquivo. O Rigor lê o material enviado e não confere registros "
                            "com uma corretora. Preservar a exportação original e explicar "
                            "transformações ajuda uma gestora a responder a observações "
                            "específicas sem confundir limpeza estatística com evidência de "
                            "origem."
                        ),
                    ],
                },
                {
                    "heading": "Comparação com um benchmark",
                    "paragraphs": [
                        (
                            "A revisão compara a série com o benchmark enviado usando excesso "
                            "de retorno, razão de drawdown e razão de informação. As datas "
                            "precisam coincidir o suficiente para sustentar a comparação. "
                            "Escolher uma referência pertinente continua sendo uma decisão de "
                            "pesquisa que merece documentação: comparar com uma exposição "
                            "diferente pode responder a outra pergunta. Sem o benchmark ou sem "
                            "sobreposição suficiente, não se pode deduzir a comparação pelo "
                            "nome da estratégia. A dimensão registra a informação ausente em "
                            "vez de substituí-la por uma expectativa sobre o comportamento do "
                            "modelo."
                        ),
                    ],
                },
                {
                    "heading": "Medido, declarado e sem dados suficientes",
                    "paragraphs": [
                        (
                            "MEASURED, ou Medido, significa que o relatório calculou o valor a "
                            "partir do arquivo recebido. DECLARED, ou Declarado, identifica "
                            "algo informado pelo cliente ou pela plataforma que a análise não "
                            "pode comprovar. NOT_MEASURED indica informação insuficiente para "
                            "aquela medição. As etiquetas se aplicam a cada valor: um Sharpe "
                            "calculado pode aparecer junto de uma contagem de tentativas "
                            "declarada. Medir uma operação matemática não transforma suas "
                            "premissas em fatos observados. Ao compartilhar o relatório, "
                            "preserve as etiquetas e limitações junto das conclusões, inclusive "
                            "quando uma observação dificulta sustentar a apresentação inicial."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿La revisión reconstruye la estrategia?",
                    "a": (
                        "No. Analiza los archivos recibidos y las declaraciones asociadas. "
                        "Reconstruir la señal o repetir el backtest requiere reglas, código y "
                        "datos que esta revisión no reconstruye."
                    ),
                },
                {
                    "q": "¿Un dato medido describe resultados futuros?",
                    "a": (
                        "No. Describe un cálculo sobre el material entregado. Las dependencias, "
                        "los supuestos y la información ausente siguen limitando su "
                        "interpretación; el informe no recomienda comprar, vender ni invertir."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Does the review rebuild the strategy?",
                    "a": (
                        "No. It analyses the received files and associated declarations. "
                        "Rebuilding the signal or repeating the backtest requires rules, code "
                        "and data that this review does not reconstruct."
                    ),
                },
                {
                    "q": "Does a measured value describe future results?",
                    "a": (
                        "No. It describes a calculation on the supplied material. Dependencies, "
                        "assumptions and missing information still limit its interpretation; "
                        "the report does not recommend buying, selling or investing."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "A revisão reconstrói a estratégia?",
                    "a": (
                        "Não. Analisa os arquivos recebidos e as declarações associadas. "
                        "Reconstruir o sinal ou repetir o backtest exige regras, código e dados "
                        "que esta revisão não reconstrói."
                    ),
                },
                {
                    "q": "Um valor medido descreve resultados futuros?",
                    "a": (
                        "Não. Descreve um cálculo sobre o material enviado. Dependências, "
                        "premissas e informação ausente continuam limitando sua interpretação; "
                        "o relatório não recomenda comprar, vender ou investir."
                    ),
                },
            ],
        },
        "related": [
            {
                "kind": "calculator",
            },
            {
                "kind": "method",
            },
            {
                "kind": "audience",
                "slug": "inversores-gestores-fondos",
            },
        ],
    },
    {
        "key": "sharpe-deflactado-track-record",
        "slug": {
            "es": "sharpe-deflactado-track-record",
            "en": "deflated-sharpe-ratio-track-record",
            "pt": "sharpe-deflacionado-historico",
        },
        "title": {
            "es": "Sharpe deflactado, explicado para quienes publican historiales",
            "en": "Deflated Sharpe ratio for track records",
            "pt": "Sharpe deflacionado, explicado para quem publica históricos",
        },
        "seo_title": {
            "es": "Sharpe deflactado para quienes publican historiales",
            "pt": "Sharpe deflacionado para quem publica históricos",
        },
        "summary": {
            "es": (
                "Cómo cambia la lectura del Sharpe al contar los intentos, qué calcula Rigor "
                "y dónde limita el supuesto de independencia."
            ),
            "en": (
                "How the deflated Sharpe ratio accounts for research attempts, which inputs "
                "Rigor uses and where assumptions about independent trials limit the result."
            ),
            "pt": (
                "Como contar as tentativas muda a leitura do Sharpe, o que o Rigor calcula e "
                "onde o pressuposto de independência limita a análise."
            ),
        },
        "intro": {
            "es": (
                "Un historial publicado suele mostrar la versión que sobrevivió a la "
                "investigación. El lector ve su Sharpe, pero rara vez ve las configuraciones "
                "descartadas, las ventanas cambiadas o los universos que se probaron antes de "
                "elegirla. El Sharpe deflactado aborda esa selección: pregunta cuánto "
                "respaldo estadístico conserva el Sharpe observado frente a una referencia "
                "que incorpora la búsqueda. El cálculo describe la evidencia del historial "
                "disponible; no establece cómo se comportará el modelo después de publicarlo."
            ),
            "en": (
                "A published track record usually shows the version that survived the "
                "research process. Readers see its Sharpe ratio, but rarely see the discarded "
                "settings, revised windows or alternative universes tried before it was "
                "selected. The deflated Sharpe ratio addresses that selection: it asks how "
                "much statistical support the observed Sharpe retains against a benchmark "
                "that accounts for the search. The calculation describes evidence in the "
                "available history; it does not establish how the model will behave after "
                "publication."
            ),
            "pt": (
                "Um histórico publicado costuma mostrar a versão que sobreviveu à pesquisa. O "
                "leitor vê seu Sharpe, mas raramente vê as configurações descartadas, as "
                "janelas alteradas ou os universos testados antes da escolha. O Sharpe "
                "deflacionado aborda essa seleção: pergunta quanto respaldo estatístico o "
                "Sharpe observado conserva diante de uma referência que incorpora a busca. O "
                "cálculo descreve a evidência do histórico disponível; não estabelece como o "
                "modelo se comportará depois da publicação."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Qué mide el Sharpe deflactado",
                    "paragraphs": [
                        (
                            "El Sharpe resume el rendimiento medio en relación con su "
                            "dispersión. Su estimación tiene incertidumbre: depende de cuánto "
                            "historial existe, de la asimetría y de las colas de la "
                            "distribución. El Sharpe probabilístico evalúa el observado "
                            "frente a una referencia. El Sharpe deflactado, o DSR, utiliza "
                            "como referencia el máximo Sharpe esperado entre intentos sin "
                            "ventaja, considerando cuántos se hicieron y la dispersión de sus "
                            "estimaciones."
                        ),
                        (
                            "El DSR se expresa como una probabilidad estadística bajo esos "
                            "supuestos, no como un Sharpe anual ajustado. Tampoco es la "
                            "probabilidad de que el próximo periodo sea positivo."
                        ),
                    ],
                },
                {
                    "heading": "El registro de intentos forma parte del resultado",
                    "paragraphs": [
                        (
                            "Cada cambio considerado al escoger la versión final puede "
                            "ampliar la búsqueda: parámetros, reglas de entrada, filtros, "
                            "instrumentos y fechas. Guardar solo el archivo elegido oculta "
                            "ese contexto. Conserve el registro del optimizador, las "
                            "variantes descartadas y la fecha en que fijó el criterio de "
                            "selección."
                        ),
                        (
                            "Rigor utiliza el mayor conteo entre la declaración y los conteos "
                            "que aportan los archivos compatibles. Si el total proviene de "
                            "una estimación del autor, conserva su condición de Declarado. "
                            "Contar columnas o pasadas del archivo aporta evidencia Medida "
                            "sobre ese archivo, aunque no prueba que nunca existieran ensayos "
                            "anteriores."
                        ),
                    ],
                },
                {
                    "heading": "La calculadora expresa la búsqueda en unidades de Sharpe",
                    "paragraphs": [
                        (
                            "La calculadora pública comparte el cálculo de suerte del "
                            "informe. Muestra el Sharpe esperado de la mejor configuración "
                            "sin ventaja, el Sharpe restante después de una corrección de "
                            "Bonferroni y la duración de historial en que esa referencia "
                            "quedaría por debajo del Sharpe introducido. Son medidas "
                            "relacionadas con la selección; ninguna de ellas es la "
                            "probabilidad DSR."
                        ),
                        (
                            "La corrección de Bonferroni ajusta el valor p por el número de "
                            "intentos y lo transforma de nuevo a unidades de Sharpe. La "
                            "duración calculada mantiene los supuestos y el Sharpe del "
                            "escenario: no es un plazo que baste esperar para resolver la "
                            "incertidumbre."
                        ),
                    ],
                },
                {
                    "heading": "Cómo leer la tabla de escenarios",
                    "paragraphs": [
                        (
                            "La tabla combina distintos conteos de intentos y duraciones, "
                            "manteniendo el Sharpe supuesto. Sus entradas y resultados se "
                            "etiquetan como Declarado: son escenarios de la calculadora, no "
                            "mediciones de una cartera. La cifra de cada celda corresponde al "
                            "Sharpe esperado por suerte, no a un DSR ni al rendimiento de una "
                            "estrategia."
                        ),
                        (
                            "Compare primero una duración fija al aumentar la búsqueda. "
                            "Después, mantenga el conteo y cambie la duración. Así separa el "
                            "efecto de seleccionar entre más variantes del efecto de estimar "
                            "con más historial. Un escenario describe la relación bajo "
                            "supuestos diarios y normales; no sustituye la distribución que "
                            "tendría el archivo de un cliente."
                        ),
                    ],
                },
                {
                    "heading": "Dónde limita la independencia",
                    "paragraphs": [
                        (
                            "La referencia de máximo esperado trata los intentos como "
                            "independientes. En una búsqueda real, configuraciones cercanas "
                            "suelen compartir señales, posiciones y rendimientos. El conteo "
                            "bruto y el número efectivo de intentos independientes pueden "
                            "diferir. No reduzca el conteo hasta obtener una lectura deseada: "
                            "describa la dependencia y muestre la sensibilidad a otros "
                            "conteos. La calculadora no estima esa correlación a partir de "
                            "los campos que recibe."
                        ),
                        (
                            "También puede haber dependencia entre rendimientos consecutivos "
                            "del mismo historial. Eso afecta la información que aporta cada "
                            "observación y es distinto de la correlación entre variantes. El "
                            "informe incorpora ajustes de dependencia en su análisis "
                            "estadístico; aun así, la calidad de los datos y la "
                            "representación del proceso de búsqueda siguen limitando la "
                            "interpretación."
                        ),
                    ],
                },
                {
                    "heading": "Medido y Declarado responden a preguntas diferentes",
                    "paragraphs": [
                        (
                            "Medido identifica una cantidad obtenida del archivo entregado o "
                            "un cálculo sobre él. Declarado identifica información "
                            "suministrada por el autor que el archivo no establece. No medido "
                            "señala que falta evidencia para realizar una comprobación. Una "
                            "estadística calculada puede depender de un conteo declarado; por "
                            "eso hay que leer las etiquetas de los insumos junto con el "
                            "resultado."
                        ),
                        (
                            "En la calculadora no hay archivo: el Sharpe, la duración y el "
                            "conteo son supuestos aportados por quien la usa. En el informe, "
                            "la serie permite medir momentos y revisar su estructura "
                            "temporal. Esa diferencia de evidencia explica por qué una "
                            "ilustración pública y un análisis de datos reales pueden arrojar "
                            "lecturas diferentes."
                        ),
                    ],
                },
                {
                    "heading": "Qué publicar junto al historial",
                    "paragraphs": [
                        (
                            "Presente el periodo analizado, la frecuencia, el tratamiento de "
                            "costos y la separación entre investigación y evaluación fuera de "
                            "muestra. Añada cómo obtuvo el conteo de intentos y qué parte de "
                            "la búsqueda no pudo reconstruir."
                        ),
                        (
                            "El lector necesita esas condiciones para interpretar el DSR. Un "
                            "resultado favorable en multiplicidad deja pendientes la calidad "
                            "de datos, la exposición, los costos y la estabilidad temporal. "
                            "Vincule la metodología y entregue las limitaciones con el mismo "
                            "historial que muestra al comité. La revisión estadística aporta "
                            "preguntas documentadas; no reemplaza la decisión de inversión."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "What the deflated Sharpe ratio measures",
                    "paragraphs": [
                        (
                            "The Sharpe ratio summarizes average return relative to its "
                            "dispersion. Its estimate is uncertain: the uncertainty depends "
                            "on history length, skewness and the tails of the return "
                            "distribution. The probabilistic Sharpe ratio evaluates the "
                            "observed estimate against a benchmark. The deflated Sharpe "
                            "ratio, or DSR, uses the expected maximum Sharpe among unskilled "
                            "attempts as that benchmark, accounting for how many attempts "
                            "were made and how dispersed their estimates are."
                        ),
                        (
                            "DSR is expressed as a statistical probability under those "
                            "assumptions, not as an adjusted annual Sharpe ratio. It is also "
                            "not the probability that the next period will be positive."
                        ),
                    ],
                },
                {
                    "heading": "The research ledger belongs with the result",
                    "paragraphs": [
                        (
                            "Each choice considered when selecting the final version can "
                            "extend the search: parameters, entry rules, filters, instruments "
                            "and dates. Keeping only the selected file hides that context. "
                            "Retain the optimizer log, discarded variants and the date when "
                            "you fixed the selection criterion."
                        ),
                        (
                            "Rigor uses the largest count among the declaration and counts "
                            "supported by compatible files. If the total comes from the "
                            "author's estimate, it remains Declared. Counting columns or "
                            "optimizer passes provides Measured evidence about that file, "
                            "although it does not establish that no earlier experiments "
                            "existed."
                        ),
                    ],
                },
                {
                    "heading": "The calculator expresses the search in Sharpe units",
                    "paragraphs": [
                        (
                            "The public calculator shares the report's luck calculation. It "
                            "shows the expected Sharpe of the best unskilled configuration, "
                            "the Sharpe remaining after a Bonferroni correction and the "
                            "history length at which that benchmark would fall below the "
                            "entered Sharpe. These quantities concern selection; none of them "
                            "is the DSR probability."
                        ),
                        (
                            "The Bonferroni correction adjusts the p-value for the number of "
                            "attempts and converts it back into Sharpe units. The calculated "
                            "history length holds the scenario's assumptions and Sharpe "
                            "constant: it is not a waiting period that resolves uncertainty. "
                            "Changing the history, costs or research search requires "
                            "reassessing the evidence."
                        ),
                    ],
                },
                {
                    "heading": "How to read the scenario table",
                    "paragraphs": [
                        (
                            "The table combines different trial counts and history lengths "
                            "while holding the assumed Sharpe constant. Its inputs and "
                            "outputs are labelled Declared: they are calculator scenarios, "
                            "not measurements of a portfolio. Each cell reports the expected "
                            "luck Sharpe, not a DSR or a strategy's return."
                        ),
                        (
                            "First compare a fixed history length as the search expands. Then "
                            "hold the trial count constant and change the length. This "
                            "separates the effect of selecting among more variants from the "
                            "effect of estimating with more history. A scenario describes "
                            "that relationship under daily, normal-return assumptions; it "
                            "does not substitute for the distribution in a client's file."
                        ),
                    ],
                },
                {
                    "heading": "Where independence becomes a limitation",
                    "paragraphs": [
                        (
                            "The expected-maximum benchmark treats attempts as independent. "
                            "In a research search, nearby configurations often share signals, "
                            "positions and returns. The raw count and the effective number of "
                            "independent attempts can differ. Do not reduce the count until "
                            "the reading looks desirable: describe the dependence and show "
                            "sensitivity to other counts. The calculator does not estimate "
                            "that correlation from the fields it receives."
                        ),
                        (
                            "Consecutive returns within the same history can also be "
                            "dependent. That affects how much information each observation "
                            "contributes and is distinct from correlation between variants. "
                            "The report incorporates dependence adjustments into its "
                            "statistical analysis; even so, data quality and how faithfully "
                            "the search process is represented continue to limit "
                            "interpretation."
                        ),
                    ],
                },
                {
                    "heading": "Measured and Declared answer different questions",
                    "paragraphs": [
                        (
                            "Measured identifies a quantity obtained from the supplied file "
                            "or a calculation using it. Declared identifies information "
                            "supplied by the author that the file does not establish. Not "
                            "measured indicates missing evidence for a check. A calculated "
                            "statistic can depend on a declared trial count, so read the "
                            "labels on the inputs alongside the result."
                        ),
                        (
                            "The calculator has no file: Sharpe, duration and trial count are "
                            "assumptions supplied by its user. In the report, the series "
                            "allows return moments to be measured and its time structure to "
                            "be examined. That difference in evidence explains why a public "
                            "illustration and an analysis of actual data can produce "
                            "different readings."
                        ),
                    ],
                },
                {
                    "heading": "What to publish alongside the track record",
                    "paragraphs": [
                        (
                            "State the period examined, observation frequency, cost treatment "
                            "and separation between research and out-of-sample evaluation. "
                            "Add how the trial count was obtained and which part of the "
                            "search you could not reconstruct. If a variants matrix exists, "
                            "retain its dates and the relationship between each column and "
                            "the version tested."
                        ),
                        (
                            "Readers need those conditions to interpret DSR. A favorable "
                            "multiplicity result still leaves data quality, exposure, costs "
                            "and stability over time to examine. Link the methodology and "
                            "deliver the limitations with the same history you show the "
                            "committee. Statistical review contributes documented questions; "
                            "it does not replace the investment decision or settle whether "
                            "the proposed implementation matches the supplied series."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "O que mede o Sharpe deflacionado",
                    "paragraphs": [
                        (
                            "O Sharpe resume o retorno médio em relação à sua dispersão. Sua "
                            "estimativa tem incerteza: ela depende da duração do histórico, "
                            "da assimetria e das caudas da distribuição. O Sharpe "
                            "probabilístico avalia a estimativa observada diante de uma "
                            "referência. O Sharpe deflacionado, ou DSR, usa como referência o "
                            "máximo Sharpe esperado entre tentativas sem vantagem, "
                            "considerando quantas foram feitas e a dispersão das estimativas."
                        ),
                        (
                            "O DSR é expresso como uma probabilidade estatística sob esses "
                            "pressupostos, não como um Sharpe anual ajustado. Também não é a "
                            "probabilidade de o próximo período ser positivo."
                        ),
                    ],
                },
                {
                    "heading": "O registro de tentativas acompanha o resultado",
                    "paragraphs": [
                        (
                            "Cada escolha considerada ao selecionar a versão final pode "
                            "ampliar a busca: parâmetros, regras de entrada, filtros, "
                            "instrumentos e datas. Guardar apenas o arquivo escolhido esconde "
                            "esse contexto. Conserve o registro do otimizador, as variantes "
                            "descartadas e a data em que fixou o critério de seleção."
                        ),
                        (
                            "O Rigor usa a maior contagem entre a declaração e as contagens "
                            "sustentadas pelos arquivos compatíveis. Se o total vem de uma "
                            "estimativa do autor, permanece Declarado. Contar colunas ou "
                            "passagens fornece evidência Medida sobre aquele arquivo, embora "
                            "não estabeleça que nunca existiram experimentos anteriores."
                        ),
                    ],
                },
                {
                    "heading": "A calculadora expressa a busca em unidades de Sharpe",
                    "paragraphs": [
                        (
                            "A calculadora pública compartilha o cálculo de sorte do "
                            "relatório. Ela mostra o Sharpe esperado da melhor configuração "
                            "sem vantagem, o Sharpe restante depois da correção de Bonferroni "
                            "e a duração do histórico em que essa referência ficaria abaixo "
                            "do Sharpe informado. Essas medidas tratam da seleção; nenhuma "
                            "delas é a probabilidade DSR."
                        ),
                        (
                            "A correção de Bonferroni ajusta o valor p pelo número de "
                            "tentativas e o transforma novamente em unidades de Sharpe. A "
                            "duração calculada mantém os pressupostos e o Sharpe do cenário: "
                            "não é um prazo de espera que resolve a incerteza. Alterar o "
                            "histórico, os custos ou a busca exige reavaliar a evidência."
                        ),
                    ],
                },
                {
                    "heading": "Como ler a tabela de cenários",
                    "paragraphs": [
                        (
                            "A tabela combina diferentes contagens de tentativas e durações, "
                            "mantendo o Sharpe pressuposto. Suas entradas e seus resultados "
                            "recebem a etiqueta Declarado: são cenários da calculadora, não "
                            "medições de uma carteira. Cada célula apresenta o Sharpe "
                            "esperado por sorte, não um DSR nem o retorno de uma estratégia."
                        ),
                        (
                            "Compare primeiro uma duração fixa enquanto a busca aumenta. "
                            "Depois mantenha a contagem e altere a duração. Assim você separa "
                            "o efeito de selecionar entre mais variantes do efeito de estimar "
                            "com mais histórico. Um cenário descreve essa relação sob "
                            "pressupostos de retornos diários e normais; não substitui a "
                            "distribuição que existiria no arquivo de um cliente."
                        ),
                    ],
                },
                {
                    "heading": "Onde a independência limita a leitura",
                    "paragraphs": [
                        (
                            "A referência de máximo esperado trata as tentativas como "
                            "independentes. Na pesquisa, configurações próximas costumam "
                            "compartilhar sinais, posições e retornos. A contagem bruta e o "
                            "número efetivo de tentativas independentes podem diferir. Não "
                            "reduza a contagem até obter uma leitura desejada: descreva a "
                            "dependência e apresente sensibilidade a outras contagens. A "
                            "calculadora não estima essa correlação com os campos recebidos."
                        ),
                        (
                            "Também pode haver dependência entre retornos consecutivos do "
                            "mesmo histórico. Isso afeta a informação que cada observação "
                            "oferece e é diferente da correlação entre variantes. O relatório "
                            "incorpora ajustes de dependência na análise estatística; ainda "
                            "assim, a qualidade dos dados e a representação do processo de "
                            "busca continuam limitando a interpretação."
                        ),
                    ],
                },
                {
                    "heading": "Medido e Declarado respondem a perguntas diferentes",
                    "paragraphs": [
                        (
                            "Medido identifica uma quantidade obtida do arquivo entregue ou "
                            "um cálculo feito com ele. Declarado identifica informação "
                            "fornecida pelo autor que o arquivo não estabelece. Não medido "
                            "indica falta de evidência para uma análise. Uma estatística "
                            "calculada pode depender de uma contagem declarada; portanto, "
                            "leia as etiquetas das entradas junto com o resultado."
                        ),
                        (
                            "Na calculadora não há arquivo: Sharpe, duração e contagem são "
                            "pressupostos fornecidos pelo usuário. No relatório, a série "
                            "permite medir os momentos dos retornos e examinar a estrutura "
                            "temporal. Essa diferença de evidência explica por que uma "
                            "ilustração pública e uma análise de dados reais podem produzir "
                            "leituras diferentes."
                        ),
                    ],
                },
                {
                    "heading": "O que publicar junto com o histórico",
                    "paragraphs": [
                        (
                            "Informe o período analisado, a frequência, o tratamento dos "
                            "custos e a separação entre pesquisa e avaliação fora da amostra. "
                            "Acrescente como obteve a contagem de tentativas e qual parte da "
                            "busca não conseguiu reconstruir. Se houver uma matriz de "
                            "variantes, preserve suas datas e a relação entre cada coluna e a "
                            "versão testada."
                        ),
                        (
                            "O leitor precisa dessas condições para interpretar o DSR. Um "
                            "resultado favorável em multiplicidade ainda deixa questões sobre "
                            "qualidade dos dados, exposição, custos e estabilidade ao longo "
                            "do tempo. Inclua a metodologia e entregue as limitações com o "
                            "mesmo histórico apresentado ao comitê. A revisão estatística "
                            "contribui com perguntas documentadas; não substitui a decisão de "
                            "investimento nem determina se a implementação proposta "
                            "corresponde à série entregue."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿El Sharpe restante de la calculadora es el DSR?",
                    "a": (
                        "No. Es un Sharpe después de una corrección de Bonferroni. El DSR es "
                        "una probabilidad estadística frente a una referencia de selección; "
                        "son cantidades diferentes."
                    ),
                },
                {
                    "q": "¿Qué hago si desconozco el número de intentos?",
                    "a": (
                        "Declare la incertidumbre y presente escenarios con otros conteos. "
                        "Reúna registros y variantes antes de interpretar la cifra como una "
                        "descripción de toda la investigación."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Is the calculator's remaining Sharpe the DSR?",
                    "a": (
                        "No. It is a Sharpe after a Bonferroni correction. DSR is a "
                        "statistical probability against a selection benchmark; these are "
                        "different quantities."
                    ),
                },
                {
                    "q": "What if the number of attempts is unknown?",
                    "a": (
                        "Declare that uncertainty and present scenarios with other counts. "
                        "Gather logs and variants before interpreting the figure as a "
                        "description of the entire research process."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "O Sharpe restante da calculadora é o DSR?",
                    "a": (
                        "Não. É um Sharpe após uma correção de Bonferroni. O DSR é uma "
                        "probabilidade estatística diante de uma referência de seleção; são "
                        "quantidades diferentes."
                    ),
                },
                {
                    "q": "O que fazer se o número de tentativas for desconhecido?",
                    "a": (
                        "Declare a incerteza e apresente cenários com outras contagens. Reúna "
                        "registros e variantes antes de interpretar a cifra como uma "
                        "descrição de toda a pesquisa."
                    ),
                },
            ],
        },
        "related": [
            {
                "kind": "calculator",
            },
            {
                "kind": "method",
            },
        ],
    },
    {
        "key": "auditar-cartera-modelo-senales",
        "slug": {
            "es": "auditar-cartera-modelo-senales",
            "en": "audit-model-portfolio-signal-track-record",
            "pt": "auditar-carteira-modelo-sinais",
        },
        "title": {
            "es": (
                "Cómo auditar una cartera modelo o un historial de señales antes de presentarlo a "
                "inversores"
            ),
            "en": "Independent backtest audit: portfolios and signals",
            "pt": (
                "Como auditar uma carteira modelo ou um histórico de sinais antes de apresentá-lo "
                "a investidores"
            ),
        },
        "seo_title": {
            "es": "Cómo auditar carteras modelo o señales para inversores",
            "pt": "Como auditar carteiras modelo ou sinais para investidores",
        },
        "summary": {
            "es": (
                "Qué serie de rendimientos entregar, cómo documentar costos y benchmark, y qué "
                "puede responder una revisión estadística del archivo."
            ),
            "en": (
                "Prepare a model portfolio or signal history for an independent backtest audit: "
                "gross and net return series, costs, benchmark and research attempts."
            ),
            "pt": (
                "Qual série de retornos enviar, como documentar custos e benchmark e o que uma "
                "revisão estatística do arquivo pode responder."
            ),
        },
        "intro": {
            "es": (
                "Antes de presentar una cartera modelo o un historial de señales, conviene saber "
                "qué "
                "preguntas soporta el archivo que acompaña a la curva. Un historial puede "
                "describir "
                "una simulación, una cartera teórica publicada o una cuenta con operaciones. Esas "
                "fuentes no son intercambiables, aunque sus gráficos se parezcan. Una revisión "
                "estadística examina los rendimientos aportados y distingue lo calculado de lo "
                "declarado. No reconstruye el proceso de inversión ni transforma una simulación en "
                "operaciones observadas. La preparación empieza por delimitar qué representa cada "
                "periodo y qué información falta para interpretar el conjunto."
            ),
            "en": (
                "Before presenting a model portfolio or signal track record, establish which "
                "questions the file behind the chart can support. A record may describe a "
                "simulation, a published theoretical portfolio or an account containing trades. "
                "Those sources are not interchangeable, even when their charts look similar. A "
                "statistical review examines the supplied returns and distinguishes calculations "
                "from declarations. It does not reconstruct the investment process or turn a "
                "simulation into observed transactions. Preparation starts by defining what each "
                "period represents and which information is missing from the interpretation of "
                "the complete history."
            ),
            "pt": (
                "Antes de apresentar uma carteira modelo ou um histórico de sinais, convém saber "
                "quais perguntas o arquivo por trás da curva permite responder. Um histórico pode "
                "descrever uma simulação, uma carteira teórica publicada ou uma conta com "
                "operações. Essas fontes não são intercambiáveis, mesmo quando seus gráficos "
                "parecem semelhantes. Uma revisão estatística examina os retornos fornecidos e "
                "distingue o que foi calculado do que foi declarado. Não reconstrói o processo "
                "de investimento nem transforma uma simulação em operações observadas. A "
                "preparação começa por delimitar o significado de cada período e as informações "
                "que faltam para interpretar o conjunto."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Delimita el historial que quieres revisar",
                    "paragraphs": [
                        (
                            "Anota si la serie corresponde a una cartera modelo, a señales "
                            "publicadas "
                            "o al registro exportado de una cuenta. Describe la moneda, el "
                            "calendario "
                            "y la frecuencia, junto con las fechas en que cambió el proceso. Si el "
                            "historial une etapas simuladas y observadas, conserva esa separación "
                            "en la documentación. Un cambio de universo, de regla de rebalanceo o "
                            "de tratamiento de dividendos puede alterar la interpretación aunque "
                            "la curva permanezca continua."
                        ),
                        (
                            "Conserva el archivo de origen y una explicación de las "
                            "transformaciones "
                            "que hiciste antes de enviarlo. Si calculaste rendimientos a partir "
                            "del valor de una cartera, explica cómo trataste aportaciones y "
                            "retiradas. Una subida causada por una aportación no representa un "
                            "rendimiento de la estrategia. La revisión del archivo no descubre "
                            "por sí sola movimientos que nunca se incluyeron."
                        ),
                    ],
                },
                {
                    "heading": "Entrega rendimientos por periodo, con fechas",
                    "paragraphs": [
                        (
                            "Para una cartera sin listado de operaciones, prepara una serie "
                            "fechada de rendimientos por periodo o del valor de la cartera. El "
                            "formulario admite CSV o Excel. Usa encabezados claros, conserva la "
                            "frecuencia original y distingue retornos por periodo de cifras "
                            "acumuladas. Explica la unidad empleada, incluido si los rendimientos "
                            "están expresados como decimales o porcentajes. No rellenes huecos "
                            "para que la curva parezca continua: documenta por qué faltan."
                        ),
                        (
                            "Si entregas operaciones, el lector universal necesita columnas "
                            "que permitan interpretarlas: fechas de entrada y salida, cantidad "
                            "y precios para operaciones cerradas, o fecha, cantidad, precio y "
                            "sentido para ejecuciones. La guía de exportación explica el mapeo. "
                            "Ese archivo responde preguntas distintas de una serie agregada. "
                            "No presupongas que un historial de cierres incluye posiciones "
                            "abiertas, distribuciones o todos los gastos de la cartera."
                        ),
                    ],
                },
                {
                    "heading": "Separa bruto, neto y benchmark",
                    "paragraphs": [
                        (
                            "Identifica qué versión de rendimientos entregas: bruta o neta. "
                            "Conserva ambas por separado cuando existan y enumera comisiones, "
                            "gastos y supuestos de deslizamiento aplicados. Que una etiqueta "
                            "diga neto no permite medir los costos que faltan. La declaración "
                            "de rendimientos de un fondo netos de comisiones tiene un alcance "
                            "concreto en el formulario; no sustituye el desglose de ejecución "
                            "de una señal. Tampoco supone una comparación automática entre "
                            "las versiones bruta y neta."
                        ),
                        (
                            "Aporta el benchmark como serie fechada en CSV en Opciones avanzadas. "
                            "Documenta moneda, frecuencia y tratamiento de distribuciones, y "
                            "explica por qué sirve de referencia. La comparación usa las fechas "
                            "compatibles disponibles, no una cifra de portada de otro periodo. "
                            "Un benchmark elegido después de mirar el resultado también forma "
                            "parte de las decisiones de investigación que conviene revelar."
                        ),
                    ],
                },
                {
                    "heading": "Qué preguntas puede responder el informe",
                    "paragraphs": [
                        (
                            "Con datos suficientes, el informe examina la incertidumbre "
                            "estadística, la concentración del resultado en los mejores "
                            "periodos y las diferencias del tramo reciente frente al resto. "
                            "La selección entre variantes importa: aporta el número de "
                            "intentos y su procedencia para contextualizar el Sharpe deflactado. "
                            "Si ese recuento procede de tu explicación, sigue siendo una "
                            "declaración, aunque el cálculo que lo utiliza sea reproducible."
                        ),
                        (
                            "Las etiquetas MEDIDO, DECLARADO y NO MEDIDO ayudan a leer esa "
                            "frontera. MEDIDO identifica un cálculo sobre los datos aportados; "
                            "DECLARADO identifica información del autor; NO MEDIDO indica "
                            "evidencia insuficiente para una comprobación. La comparación "
                            "con un benchmark depende de su serie y las pruebas de costos "
                            "dependen del detalle disponible. Una sección ausente no debe "
                            "interpretarse como una conclusión favorable sobre ella."
                        ),
                    ],
                },
                {
                    "heading": "Qué no responde sin el archivo",
                    "paragraphs": [
                        (
                            "Una captura o una rentabilidad acumulada no permite reconstruir "
                            "el orden de los rendimientos, sus huecos ni la dependencia entre "
                            "periodos. Sin la serie, Rigor no puede concluir si ese historial "
                            "resiste las comprobaciones estadísticas. Sin operaciones y "
                            "costos, tampoco puede medir todos los efectos de ejecución. "
                            "Los límites deben acompañar al resultado cuando se comparte."
                        ),
                        (
                            "Incluso con el archivo, la auditoría no demuestra que una señal "
                            "se publicara antes de cada movimiento, que una cuenta pertenezca "
                            "a quien la presenta o que todos los intentos descartados estén "
                            "declarados. No reconstruye el código, no recomienda asignaciones "
                            "y no promete resultados futuros. La revisión estadística del "
                            "material recibido tiene un alcance distinto de una revisión "
                            "operativa, jurídica o de titularidad."
                        ),
                    ],
                },
                {
                    "heading": "Prepara la conversación y revisa un ejemplo",
                    "paragraphs": [
                        (
                            "Usa el contacto enlazado al final para describir la fuente, la "
                            "frecuencia y los archivos disponibles antes de delimitar la "
                            "revisión. No hace falta incluir credenciales ni código de "
                            "acceso. La página de ejemplos muestra la estructura de un "
                            "informe con datos sintéticos: sirve para anticipar el formato, "
                            "no para inferir una conclusión sobre tu cartera. Cuando "
                            "presentes el informe, conserva junto a él el periodo analizado, "
                            "las declaraciones y los apartados sin medir."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "Define the record under review",
                    "paragraphs": [
                        (
                            "State whether the series represents a model portfolio, published "
                            "signals or an account export. Describe the currency, calendar and "
                            "frequency, together with dates when the process changed. If the "
                            "history joins simulated and observed stages, preserve that "
                            "distinction in the documentation. A change in the investment "
                            "universe, rebalance rule or treatment of distributions can alter "
                            "the interpretation even when the chart remains continuous."
                        ),
                        (
                            "Keep the original file and an explanation of any transformations "
                            "you made before supplying it. If returns were calculated from "
                            "portfolio values, explain the treatment of contributions and "
                            "withdrawals. A rise caused by an external contribution is not "
                            "a strategy return. Reviewing the file cannot independently "
                            "discover movements that were never included in the supplied "
                            "record or recover a valuation policy that was not documented."
                        ),
                    ],
                },
                {
                    "heading": "Supply dated returns for each period",
                    "paragraphs": [
                        (
                            "For a portfolio without a trade list, prepare dated period "
                            "returns or portfolio values. The upload form accepts CSV or "
                            "Excel. Use clear column headings, preserve the original "
                            "frequency and distinguish period returns from cumulative "
                            "figures. Explain the units, including whether returns are "
                            "expressed as decimals or percentages. Do not fill gaps just "
                            "to make the curve look continuous: document why they are missing."
                        ),
                        (
                            "For trades, the universal reader needs columns that make the "
                            "records interpretable: entry and exit times, quantity and "
                            "prices for closed trades, or time, quantity, price and "
                            "direction for fills. The export guide explains column mapping. "
                            "That file answers different questions from an aggregated "
                            "return series. Do not assume a list of closed trades includes "
                            "open positions, distributions or every expense incurred by "
                            "the portfolio throughout its history."
                        ),
                    ],
                },
                {
                    "heading": "Separate gross, net and benchmark series",
                    "paragraphs": [
                        (
                            "Identify which return version you supply: gross or net. Keep "
                            "both separately when available and list the fees, expenses "
                            "and slippage assumptions applied. A net label does not "
                            "measure missing costs. The declaration that a fund's returns "
                            "are net of fees has a specific scope in the upload form; "
                            "it does not replace the execution cost breakdown for a "
                            "signal. Nor does supplying these descriptions imply an "
                            "automatic comparison between gross and net versions."
                        ),
                        (
                            "Supply the benchmark as a dated CSV series under Advanced "
                            "options. Document its currency, frequency and distribution "
                            "treatment, and explain why it is an appropriate reference. "
                            "The comparison uses the compatible dates available, not "
                            "a headline figure covering a different period. Choosing a "
                            "benchmark after inspecting the result is also a research "
                            "decision that belongs in the accompanying account of the process."
                        ),
                    ],
                },
                {
                    "heading": "What the report can answer",
                    "paragraphs": [
                        (
                            "Where sufficient data are available, the report examines "
                            "statistical uncertainty, concentration in the best periods "
                            "and differences between the recent segment and the rest. "
                            "Selection among variants matters: supply the number of "
                            "research attempts and its source to contextualise the "
                            "deflated Sharpe. If that count comes from your explanation, "
                            "it remains a declaration even when the calculation using "
                            "it can be reproduced from the recorded inputs."
                        ),
                        (
                            "The labels MEASURED, DECLARED and NOT MEASURED explain that "
                            "boundary. MEASURED identifies a calculation on the supplied "
                            "data; DECLARED identifies information supplied by the author; "
                            "NOT MEASURED indicates insufficient evidence for a check. "
                            "Benchmark comparison depends on the benchmark series, while "
                            "cost tests depend on the detail available. An absent section "
                            "should not be interpreted as a favourable conclusion about "
                            "the question that section would otherwise address."
                        ),
                    ],
                },
                {
                    "heading": "What cannot be answered without the file",
                    "paragraphs": [
                        (
                            "A screenshot or cumulative return does not establish the "
                            "ordering of returns, gaps in the history or dependence "
                            "between periods. Without the series, Rigor cannot conclude "
                            "whether that record withstands the statistical checks. "
                            "Without trades and costs, it cannot measure every execution "
                            "effect either. These limits should accompany the result "
                            "whenever it is shared with someone who did not supply the data."
                        ),
                        (
                            "Even with the file, the audit does not establish that a "
                            "signal was published before each market move, that an "
                            "account belongs to its presenter or that every discarded "
                            "attempt was disclosed. It does not reconstruct the code, "
                            "recommend allocations or promise future results. A "
                            "statistical review of received material has a different "
                            "scope from an operational, legal or ownership review. "
                            "Those questions require their own evidence and procedures."
                        ),
                    ],
                },
                {
                    "heading": "Prepare the conversation and inspect an example",
                    "paragraphs": [
                        (
                            "Use the contact link below to describe the source, frequency "
                            "and available files before defining the review. Credentials "
                            "and access codes are not needed for that conversation. "
                            "The examples page shows the structure of a report made "
                            "with synthetic data: it helps you understand the format, "
                            "not infer a conclusion about your portfolio. When you "
                            "present your own report, keep the analysed period, "
                            "declarations and unmeasured sections alongside it so "
                            "the reader can see the limits of the supporting evidence."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Delimite o histórico que será revisado",
                    "paragraphs": [
                        (
                            "Informe se a série corresponde a uma carteira modelo, a "
                            "sinais publicados ou ao registro exportado de uma conta. "
                            "Descreva moeda, calendário e frequência, junto com as "
                            "datas em que o processo mudou. Se o histórico reúne "
                            "etapas simuladas e observadas, preserve essa separação "
                            "na documentação. Uma mudança de universo, regra de "
                            "rebalanceamento ou tratamento de dividendos pode alterar "
                            "a interpretação mesmo que a curva permaneça contínua."
                        ),
                        (
                            "Guarde o arquivo de origem e uma explicação das "
                            "transformações feitas antes do envio. Se calculou "
                            "retornos a partir do valor da carteira, explique "
                            "como tratou aportes e retiradas. Uma alta causada "
                            "por um aporte não representa retorno da estratégia. "
                            "A revisão do arquivo não descobre sozinha movimentos "
                            "que nunca foram incluídos nem recupera uma política "
                            "de avaliação que não foi documentada."
                        ),
                    ],
                },
                {
                    "heading": "Envie retornos por período, com datas",
                    "paragraphs": [
                        (
                            "Para uma carteira sem lista de operações, prepare uma "
                            "série datada de retornos por período ou do valor da "
                            "carteira. O formulário aceita CSV ou Excel. Use nomes "
                            "claros nas colunas, preserve a frequência original e "
                            "distinga retornos por período de valores acumulados. "
                            "Explique a unidade utilizada, incluindo se os retornos "
                            "estão em decimais ou percentuais. Não preencha lacunas "
                            "para a curva parecer contínua: documente o motivo delas."
                        ),
                        (
                            "Se enviar operações, o leitor universal precisa de "
                            "colunas que permitam interpretá-las: datas de entrada "
                            "e saída, quantidade e preços para operações fechadas, "
                            "ou data, quantidade, preço e sentido para execuções. "
                            "O guia de exportação explica o mapeamento. Esse "
                            "arquivo responde a perguntas diferentes de uma "
                            "série agregada. Não suponha que um histórico de "
                            "fechamentos inclua posições abertas, distribuições "
                            "ou todas as despesas da carteira."
                        ),
                    ],
                },
                {
                    "heading": "Separe bruto, líquido e benchmark",
                    "paragraphs": [
                        (
                            "Identifique qual versão de retornos está enviando: "
                            "bruta ou líquida. Guarde ambas separadamente quando "
                            "existirem e liste taxas, despesas e hipóteses de "
                            "slippage aplicadas. Uma etiqueta dizendo líquido "
                            "não permite medir custos ausentes. A declaração "
                            "de retornos de um fundo líquidos de taxas tem "
                            "um alcance específico no formulário; não substitui "
                            "o detalhamento de execução de um sinal. Também "
                            "não significa uma comparação automática entre "
                            "as versões bruta e líquida."
                        ),
                        (
                            "Forneça o benchmark como série datada em CSV nas "
                            "Opções avançadas. Documente moeda, frequência e "
                            "tratamento de distribuições, explicando por que "
                            "ele serve como referência. A comparação usa "
                            "as datas compatíveis disponíveis, não um valor "
                            "de destaque referente a outro período. Um "
                            "benchmark escolhido depois de observar o "
                            "resultado também faz parte das decisões "
                            "de pesquisa que convém revelar."
                        ),
                    ],
                },
                {
                    "heading": "Quais perguntas o relatório pode responder",
                    "paragraphs": [
                        (
                            "Com dados suficientes, o relatório examina a "
                            "incerteza estatística, a concentração do resultado "
                            "nos melhores períodos e as diferenças entre o "
                            "trecho recente e o restante. A seleção entre "
                            "variantes importa: indique o número de tentativas "
                            "e sua origem para contextualizar o Sharpe "
                            "deflacionado. Se a contagem vem da sua "
                            "explicação, continua sendo uma declaração, "
                            "mesmo que o cálculo que a utiliza seja reproduzível."
                        ),
                        (
                            "As etiquetas MEDIDO, DECLARADO e NÃO MEDIDO "
                            "ajudam a interpretar essa fronteira. MEDIDO "
                            "identifica um cálculo sobre os dados fornecidos; "
                            "DECLARADO identifica informação do autor; NÃO "
                            "MEDIDO indica evidência insuficiente para uma "
                            "checagem. A comparação com um benchmark depende "
                            "da sua série, e os testes de custos dependem "
                            "do detalhe disponível. Uma seção ausente não "
                            "deve ser interpretada como uma conclusão "
                            "favorável sobre a questão que ela abordaria."
                        ),
                    ],
                },
                {
                    "heading": "O que não responde sem o arquivo",
                    "paragraphs": [
                        (
                            "Uma captura de tela ou um retorno acumulado "
                            "não permite reconstruir a ordem dos retornos, "
                            "as lacunas ou a dependência entre períodos. "
                            "Sem a série, o Rigor não pode concluir se "
                            "aquele histórico resiste às checagens "
                            "estatísticas. Sem operações e custos, também "
                            "não pode medir todos os efeitos da execução. "
                            "Esses limites devem acompanhar o resultado "
                            "sempre que ele for compartilhado."
                        ),
                        (
                            "Mesmo com o arquivo, a auditoria não demonstra "
                            "que um sinal foi publicado antes de cada "
                            "movimento do mercado, que uma conta pertence "
                            "a quem a apresenta ou que todas as tentativas "
                            "descartadas foram declaradas. Não reconstrói "
                            "o código, não recomenda alocações e não "
                            "promete resultados futuros. A revisão "
                            "estatística do material recebido tem um "
                            "alcance diferente de uma revisão operacional, "
                            "jurídica ou de titularidade."
                        ),
                    ],
                },
                {
                    "heading": "Prepare a conversa e examine um exemplo",
                    "paragraphs": [
                        (
                            "Use o contato ao final para descrever a "
                            "origem, a frequência e os arquivos disponíveis "
                            "antes de delimitar a revisão. Não é necessário "
                            "incluir credenciais ou códigos de acesso. A "
                            "página de exemplos mostra a estrutura de um "
                            "relatório com dados sintéticos: serve para "
                            "antecipar o formato, não para inferir uma "
                            "conclusão sobre sua carteira. Ao apresentar "
                            "o relatório, preserve junto dele o período "
                            "analisado, as declarações e as seções sem "
                            "medir, para que o leitor compreenda o "
                            "alcance das evidências disponíveis."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Puedo empezar sin entregar el código de la señal?",
                    "a": (
                        "Sí. La auditoría estadística parte del archivo de rendimientos o de "
                        "operaciones. El código y la lógica de la señal no se reconstruyen."
                    ),
                },
                {
                    "q": "¿El ejemplo permite anticipar la clase de mi historial?",
                    "a": (
                        "No. El ejemplo usa datos sintéticos para mostrar el formato. La clase y "
                        "los límites de tu informe dependen del material que aportes."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Can we start without supplying the signal's code?",
                    "a": (
                        "Yes. The statistical audit starts from a return or trade file. It does "
                        "not reconstruct the code or the signal's logic."
                    ),
                },
                {
                    "q": "Can the example predict the class of our record?",
                    "a": (
                        "No. The example uses synthetic data to show the format. Your report's "
                        "class and limits depend on the material you supply."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "Posso começar sem fornecer o código do sinal?",
                    "a": (
                        "Sim. A auditoria estatística parte do arquivo de retornos ou operações. "
                        "O código e a lógica do sinal não são reconstruídos."
                    ),
                },
                {
                    "q": "O exemplo permite antecipar a classe do meu histórico?",
                    "a": (
                        "Não. O exemplo usa dados sintéticos para mostrar o formato. A classe e "
                        "os limites do seu relatório dependem do material fornecido."
                    ),
                },
            ],
        },
        "related": [
            {"kind": "contact"},
            {"kind": "samples"},
            {"kind": "audience", "slug": "gestoras-y-senales"},
        ],
    },
    {
        "key": "cuantos-intentos-reto-prop-firm",
        "slug": {
            "es": "cuantos-intentos-reto-prop-firm",
            "en": "how-many-prop-firm-challenge-attempts",
            "pt": "quantas-tentativas-desafio-prop-firm",
        },
        "title": {
            "es": "Cuántos intentos de un reto de prop firm sugiere tu propio historial",
            "en": "How many prop-firm challenge attempts your own history suggests",
            "pt": "Quantas tentativas de um desafio de prop firm seu histórico sugere",
        },
        "seo_title": {
            "es": "Cuántos intentos de prop firm sugiere tu historial",
            "en": "How many prop-firm attempts your history suggests",
            "pt": "Quantas tentativas de prop firm seu histórico sugere",
        },
        "summary": {
            "es": (
                "Cómo leer un rango de intentos bajo supuestos de acierto y riesgo, y "
                "por qué tu historial importa más que una captura del backtest."
            ),
            "en": (
                "How to read an attempt range under declared win-rate and risk "
                "assumptions, and why your history matters more than a backtest "
                "screenshot."
            ),
            "pt": (
                "Como ler uma faixa de tentativas sob hipóteses de acerto e risco, e "
                "por que seu histórico importa mais que uma captura do backtest."
            ),
        },
        "intro": {
            "es": (
                "La tarifa de un reto no describe cuánto podría costar repetirlo. Para "
                "ordenar esa pregunta necesitas las reglas, la distribución de "
                "resultados y el tamaño de cada pérdida. Un porcentaje de aciertos "
                "aislado no contiene esa información. Aquí usamos un ejemplo declarado "
                "para explicar la cuenta de intentos y sus límites. No es una "
                "previsión personal ni una simulación de tu cuenta. El paso útil "
                "consiste en sustituir los supuestos por un historial completo y "
                "conservar también las partes que contradicen la idea inicial."
            ),
            "en": (
                "A challenge fee does not describe what repeated attempts might cost. "
                "To organize that question, you need the rules, the distribution of "
                "outcomes and the size of each loss. A win rate alone does not contain "
                "that information. This article uses a declared example to explain "
                "attempt counts and their limits. It is not a personal forecast or a "
                "simulation of your account. The useful next step is to replace "
                "assumptions with a complete history, including the parts that "
                "contradict the original idea."
            ),
            "pt": (
                "A taxa de um desafio não descreve quanto sua repetição poderia "
                "custar. Para organizar essa pergunta, você precisa das regras, da "
                "distribuição dos resultados e do tamanho de cada perda. Uma taxa de "
                "acerto isolada não contém essas informações. Aqui usamos um exemplo "
                "declarado para explicar a conta de tentativas e seus limites. Não é "
                "uma previsão pessoal nem uma simulação da sua conta. O passo útil é "
                "substituir as hipóteses por um histórico completo, preservando também "
                "os trechos que contradizem a ideia inicial."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Empieza por las reglas y su fecha",
                    "paragraphs": [
                        (
                            "DECLARED · El preset genérico del repositorio fija un objetivo de "
                            f"{PROP_RULES.profit_target:.0%}, una pérdida total máxima de "
                            f"{PROP_RULES.max_total_loss:.0%}, un límite diario de "
                            f"{PROP_RULES.max_daily_loss:.0%} y un mínimo de "
                            f"{PROP_RULES.min_trading_days} días con actividad. No tiene plazo "
                            f"máximo. Su fecha es {PROP_RULES.as_of} y su fuente es "
                            f"{PROP_RULES.source_url}. Es una referencia didáctica, no las "
                            "condiciones actuales de una firma. El suelo de pérdida total es "
                            "estático y se refiere al saldo inicial."
                        ),
                        (
                            "Las reglas de un contrato pueden definir el día de otra manera, "
                            "incluir posiciones abiertas o mover el suelo cuando sube el saldo. "
                            "Antes de interpretar cualquier cifra, identifica exactamente qué "
                            "saldo, horario y fase describe. Cambiar una de esas definiciones "
                            "cambia la pregunta. Un preset fechado ayuda a reconocer el supuesto "
                            "utilizado; no sustituye la lectura de las condiciones vigentes."
                        ),
                    ],
                },
                {
                    "heading": "Una cuenta sencilla, separada del simulador",
                    "paragraphs": [
                        (
                            "DECLARED · El ejemplo supone una operación independiente por día, con "
                            "pérdidas y ganancias del mismo tamaño respecto al saldo inicial, sin "
                            "costos y sin límite temporal. Cada intento comienza de nuevo con "
                            "idénticas condiciones. Se detiene al tocar el objetivo o el suelo de "
                            "pérdida; tratar el contacto con el suelo como final es conservador "
                            "respecto al simulador, que distingue tocar de rebasar el límite. La "
                            "trayectoria más corta del ejemplo ya cumple los días mínimos."
                        ),
                        (
                            "Esta cuenta de barreras es una explicación editorial, no una salida "
                            "de la calculadora de Sharpe ni del informe. No incorpora las fases "
                            "posteriores, las restricciones de noticias, el comportamiento dentro "
                            "del día ni cambios de tamaño. Si llamamos p a la probabilidad del "
                            "objetivo bajo estos supuestos, la media de intentos independientes es "
                            "el inverso de p. Una media no señala cuándo terminaría una persona "
                            "concreta."
                        ),
                    ],
                },
                {
                    "heading": "Dos tasas de acierto y dos tamaños de riesgo",
                    "paragraphs": [
                        (
                            f"DECLARED · Con acierto de {PROP_WIN_RATES[0]:.0%}, el riesgo de "
                            f"{PROP_RISKS[0]:.1%} por operación produce una media de "
                            f"{PROP_ATTEMPT_EXAMPLES[0].expected_attempts:.2f} intentos; con "
                            f"riesgo de {PROP_RISKS[1]:.1%}, la media es "
                            f"{PROP_ATTEMPT_EXAMPLES[1].expected_attempts:.2f}. El rango entre "
                            f"esos escenarios es {PROP_ATTEMPT_EXAMPLES[1].expected_attempts:.2f}–"
                            f"{PROP_ATTEMPT_EXAMPLES[0].expected_attempts:.2f} intentos. Con "
                            f"acierto de {PROP_WIN_RATES[1]:.0%}, los mismos riesgos producen "
                            f"{PROP_ATTEMPT_EXAMPLES[2].expected_attempts:.2f} y "
                            f"{PROP_ATTEMPT_EXAMPLES[3].expected_attempts:.2f}, respectivamente: "
                            f"rango {PROP_ATTEMPT_EXAMPLES[2].expected_attempts:.2f}–"
                            f"{PROP_ATTEMPT_EXAMPLES[3].expected_attempts:.2f}."
                        ),
                        (
                            "Estos rangos comparan supuestos; no son intervalos de confianza ni "
                            "límites del número de intentos. El escenario con deriva desfavorable "
                            "puede acercarse al objetivo con mayor frecuencia al aumentar el "
                            "tamaño, pero también consume antes el margen de pérdida. Esa "
                            "peculiaridad del modelo no constituye una recomendación de riesgo. Si "
                            "cambias la relación entre el tamaño de ganancias y pérdidas, estas "
                            "cifras dejan de describir el problema."
                        ),
                    ],
                },
                {
                    "heading": "La racha que suele quedar fuera de la captura",
                    "paragraphs": [
                        (
                            f"DECLARED · Una racha ilustrativa de {PROP_STREAK_LENGTH} pérdidas "
                            f"consume {PROP_STREAK_LENGTH * PROP_RISKS[0]:.1%} o "
                            f"{PROP_STREAK_LENGTH * PROP_RISKS[1]:.1%} del saldo inicial con los "
                            "riesgos anteriores. Son operaciones en días distintos. Para una "
                            "ventana fijada de antemano, su probabilidad es "
                            f"{((1 - PROP_WIN_RATES[0]) ** PROP_STREAK_LENGTH):.1%} o "
                            f"{((1 - PROP_WIN_RATES[1]) ** PROP_STREAK_LENGTH):.1%}, según la "
                            "tasa de acierto. No es la probabilidad de encontrar esa racha en "
                            "cualquier lugar del historial."
                        ),
                        (
                            "Llamarla típica requiere observar tus secuencias reales. El "
                            "agrupamiento de pérdidas puede volver frágil la hipótesis de "
                            "independencia. Revisa la peor racha, el tiempo de recuperación y las "
                            "operaciones que quedaron abiertas entre sesiones. Un límite diario no "
                            "es intercambiable con un límite total: varias pérdidas concentradas "
                            "en la misma sesión plantean un problema que este ejemplo diario no "
                            "modela."
                        ),
                    ],
                },
                {
                    "heading": "Por qué pesa más el historial real",
                    "paragraphs": [
                        (
                            "Un registro de operaciones realmente realizadas conserva costos, "
                            "horarios, interrupciones y decisiones que un backtest idealizado "
                            "puede omitir. Para esta pregunta interesan especialmente la secuencia "
                            "de pérdidas y la diferencia entre riesgo planeado y observado. "
                            "Solicita fechas, importes, depósitos, retiros y posiciones abiertas; "
                            "separa movimientos de caja del resultado de operar. La evidencia "
                            "mejora cuando permite reconstruir el recorrido, no solo su punto "
                            "final."
                        ),
                        (
                            "Tampoco un historial real elimina la incertidumbre. Puede abarcar un "
                            "solo régimen, omitir cuentas cerradas o haber sido seleccionado "
                            "después de comparar muchas cuentas. Un archivo describe lo que "
                            "contiene y necesita contexto. Si el tamaño cambió durante una racha "
                            "adversa, una frecuencia global de aciertos esconderá precisamente el "
                            "comportamiento que intentas estudiar."
                        ),
                    ],
                },
                {
                    "heading": "Qué llevar al informe gratis",
                    "paragraphs": [
                        (
                            "Conserva el archivo completo, las reglas fechadas y la lista de "
                            "variantes descartadas. Distingue lo medido en el archivo de lo "
                            "declarado por su autor y de aquello que falta. Rigor analiza la "
                            "evidencia aportada y puede mostrar límites del historial; no "
                            "sustituye el contrato ni observa la ejecución futura. La calculadora "
                            "de suerte permite explorar otra pregunta: cuánto podría explicar la "
                            "búsqueda de configuraciones en el Sharpe publicado."
                        ),
                        (
                            "Antes de multiplicar una media de intentos por una tarifa, identifica "
                            "descuentos, reinicios y condiciones que no están representados. El "
                            "costo esperado depende de esos supuestos y no es un presupuesto "
                            "máximo. Empieza por el primer informe completo gratis con tu cuenta "
                            "para revisar el archivo y sus faltantes, conservando cualquier "
                            "resultado desfavorable en la comparación."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "Start with the rules and their date",
                    "paragraphs": [
                        (
                            "DECLARED · The repository's generic preset sets a target of "
                            f"{PROP_RULES.profit_target:.0%}, maximum total loss of "
                            f"{PROP_RULES.max_total_loss:.0%}, daily loss limit of "
                            f"{PROP_RULES.max_daily_loss:.0%}, and at least "
                            f"{PROP_RULES.min_trading_days} active days. It has no deadline. Its "
                            f"date is {PROP_RULES.as_of} and its source is {PROP_RULES.source_url}"
                            ". This is a teaching reference, not any firm's current terms. The "
                            "total loss floor is static and relates to the initial balance."
                        ),
                        (
                            "A contract might define the trading day differently, include open "
                            "positions or move the floor as the balance rises. Before interpreting "
                            "a number, identify exactly which balance, time zone and phase it "
                            "describes. Changing any of those definitions changes the question. A "
                            "dated preset makes the assumption traceable; it does not replace "
                            "reading the current contract or checking how its limits are applied."
                        ),
                    ],
                },
                {
                    "heading": "A simple calculation, separate from the simulator",
                    "paragraphs": [
                        (
                            "DECLARED · This example assumes an independent trade each day, equal "
                            "win and loss amounts relative to the initial balance, no costs and "
                            "unlimited time. Each attempt restarts under identical conditions. It "
                            "stops upon touching either the target or loss floor; ending a path at "
                            "contact with the floor is conservative relative to the simulator, "
                            "which distinguishes touching from breaching that limit. Even the "
                            "shortest target path in the example satisfies the minimum trading "
                            "days."
                        ),
                        (
                            "This barrier calculation is an editorial explanation, not output from "
                            "the Sharpe calculator or a report. It leaves out later phases, news "
                            "restrictions, events within the day and changes in position size. If "
                            "p denotes the probability of reaching the target under these "
                            "assumptions, the mean count of independent attempts is its "
                            "reciprocal. A mean does not identify when a particular person's "
                            "attempts would end."
                        ),
                    ],
                },
                {
                    "heading": "Two win rates and two risk sizes",
                    "paragraphs": [
                        (
                            f"DECLARED · At a {PROP_WIN_RATES[0]:.0%} win rate, risk of "
                            f"{PROP_RISKS[0]:.1%} per trade gives a mean of "
                            f"{PROP_ATTEMPT_EXAMPLES[0].expected_attempts:.2f} attempts; at "
                            f"{PROP_RISKS[1]:.1%} risk, the mean is "
                            f"{PROP_ATTEMPT_EXAMPLES[1].expected_attempts:.2f}. The range across "
                            f"these scenarios is {PROP_ATTEMPT_EXAMPLES[1].expected_attempts:.2f}–"
                            f"{PROP_ATTEMPT_EXAMPLES[0].expected_attempts:.2f} attempts. At a "
                            f"{PROP_WIN_RATES[1]:.0%} win rate, those same risk sizes give "
                            f"{PROP_ATTEMPT_EXAMPLES[2].expected_attempts:.2f} and "
                            f"{PROP_ATTEMPT_EXAMPLES[3].expected_attempts:.2f}, respectively: a "
                            f"range of {PROP_ATTEMPT_EXAMPLES[2].expected_attempts:.2f}–"
                            f"{PROP_ATTEMPT_EXAMPLES[3].expected_attempts:.2f}."
                        ),
                        (
                            "These ranges compare assumptions; they are neither confidence "
                            "intervals nor limits on the number of attempts. A path with "
                            "unfavorable drift can reach the upper barrier more frequently with "
                            "larger steps, while also using up its loss allowance faster. That "
                            "feature of this model is not a recommendation about position size. "
                            "Change the relationship between win and loss amounts and these "
                            "figures no longer describe the problem you are studying."
                        ),
                    ],
                },
                {
                    "heading": "The losing streak a screenshot leaves out",
                    "paragraphs": [
                        (
                            f"DECLARED · An illustrative streak of {PROP_STREAK_LENGTH} losses "
                            f"consumes {PROP_STREAK_LENGTH * PROP_RISKS[0]:.1%} or "
                            f"{PROP_STREAK_LENGTH * PROP_RISKS[1]:.1%} of initial balance at the "
                            "risk sizes above. Those trades occur on separate days. In a window "
                            "fixed beforehand, its probability is "
                            f"{((1 - PROP_WIN_RATES[0]) ** PROP_STREAK_LENGTH):.1%} or "
                            f"{((1 - PROP_WIN_RATES[1]) ** PROP_STREAK_LENGTH):.1%}, depending on "
                            "the win rate. This is not the probability of finding the streak "
                            "somewhere in an entire history."
                        ),
                        (
                            "Calling a streak typical requires looking at actual sequences. "
                            "Clustering losses can undermine the independence assumption. Examine "
                            "the worst streak, the recovery period and positions held across "
                            "sessions. A daily limit is not interchangeable with a total limit: "
                            "losses concentrated within the same session raise a question that "
                            "this daily example does not model. The ordering matters even when the "
                            "overall win count stays unchanged."
                        ),
                    ],
                },
                {
                    "heading": "Why actual trading history carries more information",
                    "paragraphs": [
                        (
                            "A record of trades that actually occurred retains costs, timestamps, "
                            "interruptions and decisions that an idealized backtest might omit. "
                            "The loss sequence and the gap between planned and observed risk are "
                            "especially relevant here. Ask for dates, amounts, deposits, "
                            "withdrawals and open positions; separate cash movements from trading "
                            "outcomes. Evidence becomes more useful when it lets you reconstruct "
                            "the path instead of looking only at its endpoint."
                        ),
                        (
                            "An actual history still leaves uncertainty. It may cover only one "
                            "market regime, leave out closed accounts or have been selected after "
                            "comparing many accounts. A file describes its contents and needs "
                            "context. If position sizes changed during an adverse streak, an "
                            "overall win rate can conceal the very behavior you need to examine. "
                            "Preserve the inconvenient periods when preparing the export."
                        ),
                    ],
                },
                {
                    "heading": "What to bring to the free report",
                    "paragraphs": [
                        (
                            "Keep the complete file, dated rules and a list of discarded variants. "
                            "Distinguish what is measured in the file from what its author "
                            "declares and what remains missing. Rigor analyzes supplied evidence "
                            "and can expose limitations of the history; it does not replace the "
                            "contract or observe future execution. The luck calculator addresses a "
                            "different question: how much searching across configurations might "
                            "explain the published Sharpe."
                        ),
                        (
                            "Before multiplying an attempt average by a fee, identify discounts, "
                            "resets and conditions that are absent from the model. An expected "
                            "cost depends on those assumptions and is not a maximum budget. Start "
                            "with the free first full report available with your account to review "
                            "the file and its missing evidence, keeping unfavorable findings "
                            "visible alongside the rest of the comparison."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Comece pelas regras e sua data",
                    "paragraphs": [
                        (
                            "DECLARED · O preset genérico do repositório fixa um objetivo de "
                            f"{PROP_RULES.profit_target:.0%}, perda total máxima de "
                            f"{PROP_RULES.max_total_loss:.0%}, limite diário de "
                            f"{PROP_RULES.max_daily_loss:.0%} e mínimo de "
                            f"{PROP_RULES.min_trading_days} dias com atividade. Não há prazo "
                            f"máximo. Sua data é {PROP_RULES.as_of} e sua fonte é "
                            f"{PROP_RULES.source_url}. É uma referência didática, não as "
                            "condições atuais de uma empresa. O piso de perda total é estático e "
                            "se refere ao saldo inicial."
                        ),
                        (
                            "As regras de um contrato podem definir o dia de outra forma, incluir "
                            "posições abertas ou mover o piso quando o saldo sobe. Antes de "
                            "interpretar qualquer número, identifique exatamente qual saldo, "
                            "horário e fase ele descreve. Mudar uma dessas definições muda a "
                            "pergunta. Um preset datado ajuda a reconhecer a hipótese utilizada; "
                            "não substitui a leitura das condições vigentes nem o exame de sua "
                            "aplicação."
                        ),
                    ],
                },
                {
                    "heading": "Uma conta simples, separada do simulador",
                    "paragraphs": [
                        (
                            "DECLARED · O exemplo supõe uma operação independente por dia, perdas "
                            "e ganhos do mesmo tamanho em relação ao saldo inicial, sem custos e "
                            "sem limite de tempo. Cada tentativa recomeça em condições idênticas. "
                            "Ela termina ao tocar o objetivo ou o piso de perda; encerrar no "
                            "contato com o piso é conservador em relação ao simulador, que "
                            "distingue tocar de ultrapassar o limite. A trajetória mais curta do "
                            "exemplo já cumpre o mínimo de dias."
                        ),
                        (
                            "Esta conta de barreiras é uma explicação editorial, não um resultado "
                            "da calculadora de Sharpe nem do relatório. Ela não incorpora fases "
                            "posteriores, restrições de notícias, acontecimentos dentro do dia ou "
                            "mudanças de tamanho. Se p representa a probabilidade do objetivo sob "
                            "essas hipóteses, a média de tentativas independentes é o inverso de "
                            "p. Uma média não indica quando terminariam as tentativas de uma "
                            "pessoa específica."
                        ),
                    ],
                },
                {
                    "heading": "Duas taxas de acerto e dois tamanhos de risco",
                    "paragraphs": [
                        (
                            f"DECLARED · Com acerto de {PROP_WIN_RATES[0]:.0%}, o risco de "
                            f"{PROP_RISKS[0]:.1%} por operação produz uma média de "
                            f"{PROP_ATTEMPT_EXAMPLES[0].expected_attempts:.2f} tentativas; com "
                            f"risco de {PROP_RISKS[1]:.1%}, a média é "
                            f"{PROP_ATTEMPT_EXAMPLES[1].expected_attempts:.2f}. A faixa entre "
                            f"esses cenários é {PROP_ATTEMPT_EXAMPLES[1].expected_attempts:.2f}–"
                            f"{PROP_ATTEMPT_EXAMPLES[0].expected_attempts:.2f} tentativas. Com "
                            f"acerto de {PROP_WIN_RATES[1]:.0%}, os mesmos riscos produzem "
                            f"{PROP_ATTEMPT_EXAMPLES[2].expected_attempts:.2f} e "
                            f"{PROP_ATTEMPT_EXAMPLES[3].expected_attempts:.2f}, respectivamente: "
                            f"faixa {PROP_ATTEMPT_EXAMPLES[2].expected_attempts:.2f}–"
                            f"{PROP_ATTEMPT_EXAMPLES[3].expected_attempts:.2f}."
                        ),
                        (
                            "Essas faixas comparam hipóteses; não são intervalos de confiança nem "
                            "limites para o número de tentativas. Um cenário de tendência "
                            "desfavorável pode atingir o objetivo com maior frequência ao aumentar "
                            "o tamanho, mas também consome antes a margem de perda. Essa "
                            "particularidade do modelo não constitui recomendação de risco. Se "
                            "mudar a relação entre os valores dos ganhos e das perdas, esses "
                            "números deixam de descrever o problema."
                        ),
                    ],
                },
                {
                    "heading": "A sequência de perdas ausente na captura",
                    "paragraphs": [
                        (
                            f"DECLARED · Uma sequência ilustrativa de {PROP_STREAK_LENGTH} perdas "
                            f"consome {PROP_STREAK_LENGTH * PROP_RISKS[0]:.1%} ou "
                            f"{PROP_STREAK_LENGTH * PROP_RISKS[1]:.1%} do saldo inicial com os "
                            "riscos anteriores. São operações em dias diferentes. Para uma "
                            "janela fixada de antemão, sua probabilidade é "
                            f"{((1 - PROP_WIN_RATES[0]) ** PROP_STREAK_LENGTH):.1%} ou "
                            f"{((1 - PROP_WIN_RATES[1]) ** PROP_STREAK_LENGTH):.1%}, conforme a "
                            "taxa de acerto. Não é a probabilidade de encontrar a sequência em "
                            "qualquer parte do histórico."
                        ),
                        (
                            "Chamá-la de típica exige observar suas sequências reais. O "
                            "agrupamento de perdas pode enfraquecer a hipótese de independência. "
                            "Examine a pior sequência, o tempo de recuperação e as posições "
                            "abertas entre sessões. Um limite diário não equivale a um limite "
                            "total: várias perdas concentradas na mesma sessão representam um "
                            "problema que este exemplo diário não modela. A ordem importa mesmo "
                            "sem mudar o total de acertos."
                        ),
                    ],
                },
                {
                    "heading": "Por que o histórico real traz mais informação",
                    "paragraphs": [
                        (
                            "Um registro de operações realmente realizadas preserva custos, "
                            "horários, interrupções e decisões que um backtest idealizado pode "
                            "omitir. Para esta pergunta, interessam especialmente a sequência das "
                            "perdas e a diferença entre risco planejado e observado. Peça datas, "
                            "valores, depósitos, retiradas e posições abertas; separe movimentos "
                            "de caixa dos resultados das operações. A evidência melhora quando "
                            "permite reconstruir o percurso, não apenas seu ponto final."
                        ),
                        (
                            "Um histórico real também deixa incertezas. Pode abranger apenas um "
                            "regime de mercado, omitir contas encerradas ou ter sido selecionado "
                            "depois de comparar várias contas. Um arquivo descreve seu conteúdo e "
                            "precisa de contexto. Se o tamanho mudou durante uma sequência "
                            "adversa, uma taxa global de acerto esconderá justamente o "
                            "comportamento que você procura estudar. Preserve os períodos "
                            "inconvenientes ao preparar a exportação."
                        ),
                    ],
                },
                {
                    "heading": "O que levar ao relatório grátis",
                    "paragraphs": [
                        (
                            "Guarde o arquivo completo, as regras datadas e a lista de variantes "
                            "descartadas. Diferencie o que foi medido no arquivo, o que foi "
                            "declarado pelo autor e aquilo que falta. O Rigor analisa a evidência "
                            "fornecida e pode mostrar limites do histórico; não substitui o "
                            "contrato nem observa a execução futura. A calculadora de sorte "
                            "explora outra pergunta: quanto a busca entre configurações poderia "
                            "explicar do Sharpe publicado."
                        ),
                        (
                            "Antes de multiplicar uma média de tentativas por uma taxa, "
                            "identifique descontos, reinícios e condições ausentes no modelo. O "
                            "custo esperado depende dessas hipóteses e não representa um orçamento "
                            "máximo. Comece pelo primeiro relatório completo grátis com sua conta "
                            "para examinar o arquivo e suas lacunas, mantendo qualquer resultado "
                            "desfavorável visível junto com o restante da comparação."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Puedo convertir este rango en un presupuesto personal?",
                    "a": (
                        "No. Es una comparación de supuestos declarados con intentos "
                        "independientes. Faltan tus datos, costos y condiciones completas; una "
                        "media no limita cuántas repeticiones podrían ocurrir."
                    ),
                }
            ],
            "en": [
                {
                    "q": "Can I turn this range into a personal budget?",
                    "a": (
                        "No. It compares declared assumptions with independent attempts. Your "
                        "data, costs and full conditions are missing; an average does not cap "
                        "how many repetitions could occur."
                    ),
                }
            ],
            "pt": [
                {
                    "q": "Posso transformar essa faixa em um orçamento pessoal?",
                    "a": (
                        "Não. Ela compara hipóteses declaradas com tentativas independentes. "
                        "Faltam seus dados, custos e condições completas; uma média não limita "
                        "quantas repetições poderiam ocorrer."
                    ),
                }
            ],
        },
        "related": [
            {"kind": "winrate"},
            {"kind": "calculator"},
            {"kind": "method"},
            {"kind": "samples"},
            {"kind": "audience", "slug": "retos-prop-firm"},
        ],
    },
    {
        "key": "copiar-senales-mql5-myfxbook",
        "slug": {
            "es": "copiar-senales-mql5-myfxbook",
            "en": "copying-mql5-myfxbook-signals",
            "pt": "copiar-sinais-mql5-myfxbook",
        },
        "title": {
            "es": "Copiar señales de MQL5 o Myfxbook: qué mirar antes de pagar",
            "en": "Copying MQL5 or Myfxbook signals: what to check before paying",
            "pt": "Copiar sinais da MQL5 ou do Myfxbook: o que olhar antes de pagar",
        },
        "seo_title": {
            "es": "Copiar señales MQL5 o Myfxbook: qué mirar antes de pagar",
            "en": "Copying MQL5 or Myfxbook signals: checks before paying",
            "pt": "Copiar sinais MQL5 ou Myfxbook: o que ver antes de pagar",
        },
        "summary": {
            "es": (
                "Aciertos, pérdidas abiertas, costos y tamaño de muestra: cómo leer el historial "
                "de una señal y qué puede revisar Rigor en el archivo."
            ),
            "en": (
                "Win rates, open losses, costs and sample size: how to read a signal's history and "
                "what Rigor can review in the file."
            ),
            "pt": (
                "Acertos, perdas abertas, custos e tamanho da amostra: como ler o histórico de um "
                "sinal e o que o Rigor pode revisar no arquivo."
            ),
        },
        "intro": {
            "es": (
                "Antes de pagar por copiar una señal de MQL5 o Myfxbook, conviene convertir su "
                "presentación en preguntas que un archivo pueda responder. Una curva suave, una "
                "racha reciente y un porcentaje de aciertos resumen cosas distintas. Ninguno "
                "muestra por sí solo cuánto se arriesgó para obtener ese historial. El punto de "
                "partida es pedir las operaciones exportadas, las fechas que cubren y una curva "
                "que incluya posiciones abiertas. Así puedes separar lo que se observa de lo "
                "que cuenta el proveedor y de lo que todavía falta por medir."
            ),
            "en": (
                "Before paying to copy an MQL5 or Myfxbook signal, turn its presentation into "
                "questions that a file can answer. A smooth curve, a recent streak and a win "
                "percentage summarise different things. None shows, by itself, how much risk "
                "produced that history. Start by requesting exported trades, the dates they cover "
                "and a curve that includes open positions. That lets you separate observations "
                "from the provider's account of events and from questions that still lack data. "
                "The purpose is to understand the evidence behind the signal, including its gaps."
            ),
            "pt": (
                "Antes de pagar para copiar um sinal da MQL5 ou do Myfxbook, transforme a "
                "apresentação em perguntas que um arquivo possa responder. Uma curva suave, uma "
                "sequência recente e uma porcentagem de acertos resumem coisas diferentes. "
                "Nenhum deles mostra sozinho quanto risco produziu aquele histórico. Comece "
                "pedindo as operações exportadas, as datas cobertas e uma curva que inclua "
                "posições abertas. Assim você separa observações, informações do fornecedor e "
                "perguntas para as quais ainda faltam dados. O objetivo é entender a evidência "
                "por trás do sinal, inclusive suas lacunas."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Una tasa de acierto no describe el tamaño de las pérdidas",
                    "paragraphs": [
                        (
                            "DECLARED · Imagina una señal que anuncia "
                            f"{SIGNAL_DECLARED_WIN_RATE:.0%} "
                            "de aciertos y poco drawdown. Es un ejemplo declarado, no una medición "
                            "de MQL5, Myfxbook ni una cuenta concreta. El porcentaje cuenta "
                            "cuántas "
                            "operaciones terminaron positivas; no compara el tamaño de sus "
                            "resultados. Muchas salidas pequeñas pueden convivir con pérdidas "
                            "grandes. Hace falta ver la distribución completa, los costos y cuánto "
                            "tiempo permanecieron abiertas las posiciones que terminaron perdiendo."
                        ),
                        (
                            "También importa cómo se define una operación. Un conjunto de entradas "
                            "sobre el mismo movimiento puede inflar el recuento sin añadir "
                            "observaciones independientes. Agrupa mentalmente esas entradas por "
                            "episodio y pregunta si comparten salida, exposición y dirección. Una "
                            "captura con el porcentaje agregado no responde eso. Conserva el "
                            "archivo original para que los cambios de tamaño y las secuencias "
                            "sigan visibles al revisar el historial."
                        ),
                    ],
                },
                {
                    "heading": "La moneda: una referencia pequeña y explícita",
                    "paragraphs": [
                        (
                            f"DECLARED · Supón {COIN_TRADE_COUNT} operaciones independientes, cada "
                            f"una con probabilidad de acierto {COIN_NULL_WIN_RATE:.0%}, como una "
                            f"moneda equilibrada. Alcanzar al menos {COIN_THRESHOLD_WIN_RATE:.0%} "
                            "de aciertos tiene una probabilidad aproximada de "
                            f"{COIN_NORMAL_TAIL:.2%}, redondeada a {COIN_NORMAL_TAIL:.0%}, bajo "
                            "una "
                            "aproximación normal con corrección de continuidad. La corrección "
                            "desplaza la frontera medio acierto porque el recuento es discreto. "
                            "Es la probabilidad de observar ese umbral o más dentro del modelo; "
                            "no es la probabilidad de que una señal concreta sea azar."
                        ),
                        (
                            "La cuenta mantiene fijos el tamaño de muestra y el umbral antes de "
                            "mirar los resultados. Si eliges la señal después de recorrer un "
                            "catálogo, escoges también entre muchos historiales. Los destacados "
                            "pueden incluir extremos que aparecen por selección. Y una moneda "
                            "ignora cuánto se pierde al fallar: este ejemplo trata del número de "
                            "aciertos, no del resultado económico de copiar."
                        ),
                    ],
                },
                {
                    "heading": "Cuántas operaciones hacen falta depende de la pregunta",
                    "paragraphs": [
                        (
                            "No hay un mínimo universal de operaciones que convierta una señal "
                            "en evidencia suficiente. Primero define qué diferencia frente a "
                            "la moneda quieres detectar, qué incertidumbre toleras y cómo vas "
                            "a tratar los intentos anteriores. Después considera dependencia, "
                            "cambios de tamaño y duración del historial. Muchas operaciones "
                            "concentradas en el mismo movimiento contienen menos información "
                            "que el recuento bruto sugiere."
                        ),
                        (
                            "Un historial que abarca distintos periodos ayuda a observar "
                            "comportamientos que una ventana favorable oculta. Separa el tramo "
                            "usado para escoger la señal de un tramo posterior que no decidiera "
                            "esa elección. Conserva también las fechas en que cambió el sistema. "
                            "Si el proveedor modifica las reglas tras cada retroceso, el conjunto "
                            "mezcla decisiones distintas y no representa un experimento estable."
                        ),
                    ],
                },
                {
                    "heading": "Poco drawdown: pide la curva que cuenta posiciones abiertas",
                    "paragraphs": [
                        (
                            "La curva de saldo registra cierres; la curva de equity incorpora "
                            "el valor de posiciones abiertas cuando está disponible. Un sistema "
                            "puede cerrar pequeñas operaciones positivas y mantener una pérdida "
                            "abierta durante mucho tiempo. Por eso un drawdown reducido en saldo "
                            "no describe toda la exposición. Comprueba qué curva recibió Rigor "
                            "y si sus fechas cubren las operaciones."
                        ),
                        (
                            "Con solo operaciones cerradas, el drawdown flotante dentro de ellas "
                            "queda NOT_MEASURED. Un dato que aparece en el resumen de la "
                            "plataforma puede seguir DECLARED si el archivo no permite "
                            "reconstruirlo. Los depósitos y retiros necesitan su propia lectura: "
                            "una entrada de capital cambia el saldo, pero no es una operación. "
                            "Pregunta además qué posiciones seguían abiertas al terminar el "
                            "archivo."
                        ),
                    ],
                },
                {
                    "heading": "Qué revisa Rigor en el archivo de una señal",
                    "paragraphs": [
                        (
                            "Con el historial adecuado, Rigor busca patrones como aumentar el "
                            "tamaño después de perder, acumular entradas para promediar una "
                            "pérdida y concentrar el resultado en pocas operaciones. Revisa "
                            "pérdidas grandes frente a la pérdida típica, exposición simultánea, "
                            "movimientos de dinero y posiciones pendientes al final. Son "
                            "hallazgos sobre los datos aportados; su ausencia no prueba que el "
                            "riesgo esté ausente fuera de ese archivo."
                        ),
                        (
                            "Cuando hay operaciones y costos utilizables, el informe muestra "
                            "la sensibilidad a mayores costos. También distingue métricas "
                            "calculadas del archivo, MEASURED, información aportada, DECLARED, "
                            "y lo que no se pudo medir, NOT_MEASURED. Esta separación ayuda a "
                            "formular la siguiente pregunta al proveedor. Rigor no entra en su "
                            "cuenta, no copia órdenes y no decide si debes contratar la señal."
                        ),
                    ],
                },
                {
                    "heading": "Prepara una revisión que otra persona pueda repetir",
                    "paragraphs": [
                        (
                            "Pide la exportación completa, identifica si procede de una cuenta "
                            "real o demo según su documentación y anota el intervalo solicitado. "
                            "Guarda por separado las explicaciones del proveedor, las comisiones "
                            "desglosadas y las limitaciones de la curva. El historial de origen "
                            "tampoco representa tus propias ejecuciones: latencia, tamaños y "
                            "costos pueden diferir. El informe gratis permite empezar por las "
                            "preguntas que el archivo puede contestar y dejar las demás visibles."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "A win rate does not describe the size of losses",
                    "paragraphs": [
                        (
                            "DECLARED · Imagine a signal advertising a "
                            f"{SIGNAL_DECLARED_WIN_RATE:.0%} "
                            "win rate and little drawdown. This is a declared example, not a "
                            "measurement of MQL5, Myfxbook or any particular account. The "
                            "percentage counts trades that ended positive; it does not compare "
                            "the size of their outcomes. Many small exits can coexist with large "
                            "losses. You need the full distribution, trading costs and the time "
                            "that positions which eventually lost remained open."
                        ),
                        (
                            "The definition of a trade also matters. A group of entries into the "
                            "same market move can increase the count without adding independent "
                            "observations. Consider those entries as episodes and ask whether "
                            "they share exits, exposure and direction. A screenshot of the "
                            "aggregate percentage cannot answer that. Keep the original export "
                            "so position changes and sequences remain visible when reviewing "
                            "the history with someone else."
                        ),
                    ],
                },
                {
                    "heading": "The coin: a small, explicit reference model",
                    "paragraphs": [
                        (
                            f"DECLARED · Assume {COIN_TRADE_COUNT} independent trades, each with "
                            f"a {COIN_NULL_WIN_RATE:.0%} chance of a win, like a fair coin. "
                            f"Reaching a win rate of at least {COIN_THRESHOLD_WIN_RATE:.0%} has an "
                            f"approximate probability of {COIN_NORMAL_TAIL:.2%}, rounded to "
                            f"{COIN_NORMAL_TAIL:.0%}, using a normal approximation with continuity "
                            "correction. The correction moves the boundary by half a win because "
                            "the count is discrete. This is the probability of observing that "
                            "threshold or more within the model; it is not the probability that "
                            "a particular signal is explained by chance."
                        ),
                        (
                            "The calculation fixes the sample size and threshold before looking "
                            "at outcomes. If you pick a signal after browsing a catalogue, you "
                            "also select among many histories. The highlights may include "
                            "extremes that appear through selection. A coin also ignores the "
                            "amount lost when a trade fails: this example concerns the count "
                            "of wins, not the financial result of copying a strategy."
                        ),
                    ],
                },
                {
                    "heading": "The number of trades depends on the question",
                    "paragraphs": [
                        (
                            "There is no universal minimum trade count that makes a signal's "
                            "evidence sufficient. Define the difference from the coin you want "
                            "to detect, the uncertainty you can tolerate and how previous "
                            "attempts enter the analysis. Then consider dependence, changes in "
                            "position size and the history's duration. Many trades concentrated "
                            "in the same market move contain less information than their raw "
                            "count suggests. The model's assumptions matter as much as its sample."
                        ),
                        (
                            "A history covering different periods helps reveal behaviour that "
                            "a favourable window hides. Separate the period used to choose the "
                            "signal from a later period that did not influence that choice. "
                            "Keep dates of system changes too. If the provider changes the "
                            "rules after each setback, the combined record mixes different "
                            "decisions instead of describing a stable experiment. Extra rows "
                            "alone do not resolve that problem."
                        ),
                    ],
                },
                {
                    "heading": "Little drawdown: request a curve that includes open positions",
                    "paragraphs": [
                        (
                            "A balance curve records closed outcomes; an equity curve includes "
                            "the value of open positions when available. A system can close "
                            "small positive trades while keeping a losing position open for "
                            "a long time. A shallow balance drawdown therefore does not describe "
                            "all exposure. Check which curve Rigor received and whether its "
                            "dates cover the trades. The labels attached to those curves are "
                            "part of understanding the result."
                        ),
                        (
                            "With closed trades alone, floating drawdown within them remains "
                            "NOT_MEASURED. A figure printed in the platform summary can remain "
                            "DECLARED if the file cannot reconstruct it. Deposits and withdrawals "
                            "need their own treatment: incoming capital changes the balance "
                            "but is not a trade. Also ask which positions were still open at "
                            "the end of the export and whether the report describes that gap."
                        ),
                    ],
                },
                {
                    "heading": "What Rigor reviews in a signal's file",
                    "paragraphs": [
                        (
                            "With suitable history, Rigor looks for patterns such as increasing "
                            "size after losses, adding entries to average down a losing position "
                            "and concentrating results in a few trades. It reviews large losses "
                            "relative to the typical loss, simultaneous exposure, cash movements "
                            "and positions left open at the end. These are findings about "
                            "supplied data; their absence does not establish that risk is absent "
                            "outside the file or outside the period it covers."
                        ),
                        (
                            "When usable trades and costs are available, the report shows "
                            "sensitivity to higher trading costs. It also separates file-derived "
                            "metrics, MEASURED, supplied information, DECLARED, and questions "
                            "that could not be measured, NOT_MEASURED. That separation helps "
                            "formulate the next question for the provider. Rigor does not enter "
                            "the provider's account, copy orders or decide whether you should "
                            "subscribe to the signal. Its scope is the uploaded evidence."
                        ),
                    ],
                },
                {
                    "heading": "Prepare a review someone else can repeat",
                    "paragraphs": [
                        (
                            "Request the complete export, identify whether its documentation "
                            "describes a live or demo account and record the requested interval. "
                            "Keep provider explanations, itemised fees and curve limitations "
                            "separately. The source account's history does not describe your "
                            "own executions: latency, sizes and costs can differ. The free "
                            "report lets you start with questions the file can answer and "
                            "keep unanswered questions visible, with a clear distinction "
                            "between an observation and an assumption."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "A taxa de acerto não descreve o tamanho das perdas",
                    "paragraphs": [
                        (
                            "DECLARED · Imagine um sinal anunciando "
                            f"{SIGNAL_DECLARED_WIN_RATE:.0%} "
                            "de acertos e pouco drawdown. É um exemplo declarado, não uma "
                            "medição da MQL5, do Myfxbook ou de alguma conta específica. A "
                            "porcentagem conta operações que terminaram positivas; não compara "
                            "o tamanho dos resultados. Muitas saídas pequenas podem coexistir "
                            "com perdas grandes. É preciso ver a distribuição completa, os "
                            "custos e quanto tempo ficaram abertas as posições que terminaram "
                            "com perda."
                        ),
                        (
                            "Também importa como cada operação é definida. Um grupo de entradas "
                            "sobre o mesmo movimento pode aumentar a contagem sem acrescentar "
                            "observações independentes. Considere essas entradas como episódios "
                            "e pergunte se compartilham saída, exposição e direção. Uma captura "
                            "com a porcentagem agregada não responde isso. Preserve o arquivo "
                            "original para que mudanças de tamanho e sequências continuem "
                            "visíveis quando outra pessoa revisar o histórico."
                        ),
                    ],
                },
                {
                    "heading": "A moeda: uma referência pequena e explícita",
                    "paragraphs": [
                        (
                            f"DECLARED · Suponha {COIN_TRADE_COUNT} operações independentes, cada "
                            f"uma com probabilidade de acerto de {COIN_NULL_WIN_RATE:.0%}, como "
                            "uma "
                            f"moeda equilibrada. Alcançar pelo menos {COIN_THRESHOLD_WIN_RATE:.0%} "
                            "de acertos tem probabilidade aproximada de "
                            f"{COIN_NORMAL_TAIL:.2%}, arredondada para {COIN_NORMAL_TAIL:.0%}, "
                            "pela "
                            "aproximação normal com correção de continuidade. A correção move "
                            "a fronteira em meio acerto porque a contagem é discreta. É a "
                            "probabilidade de observar aquele limite ou mais dentro do modelo; "
                            "não é a probabilidade de um sinal específico ser explicado pelo acaso."
                        ),
                        (
                            "A conta fixa o tamanho da amostra e o limite antes de olhar "
                            "os resultados. Se você escolhe o sinal depois de percorrer um "
                            "catálogo, também seleciona entre muitos históricos. Os destaques "
                            "podem incluir extremos que aparecem pela seleção. Uma moeda "
                            "também ignora quanto se perde ao errar: o exemplo trata do "
                            "número de acertos, não do resultado financeiro de copiar uma "
                            "estratégia."
                        ),
                    ],
                },
                {
                    "heading": "Quantas operações são necessárias depende da pergunta",
                    "paragraphs": [
                        (
                            "Não existe uma quantidade mínima universal de operações que torne "
                            "a evidência de um sinal suficiente. Defina qual diferença em "
                            "relação à moeda você quer detectar, quanta incerteza tolera e "
                            "como tratar as tentativas anteriores. Depois considere dependência, "
                            "mudanças no tamanho das posições e duração do histórico. Muitas "
                            "operações concentradas no mesmo movimento contêm menos informação "
                            "do que a contagem bruta sugere. As suposições também precisam de "
                            "atenção."
                        ),
                        (
                            "Um histórico que abrange períodos diferentes ajuda a observar "
                            "comportamentos que uma janela favorável esconde. Separe o trecho "
                            "usado para escolher o sinal de um período posterior que não "
                            "influenciou essa escolha. Guarde também as datas de mudanças no "
                            "sistema. Se o fornecedor altera as regras depois de cada recuo, "
                            "o conjunto mistura decisões diferentes e não representa um "
                            "experimento estável. Mais linhas, sozinhas, não resolvem esse "
                            "problema."
                        ),
                    ],
                },
                {
                    "heading": "Pouco drawdown: peça uma curva que inclua posições abertas",
                    "paragraphs": [
                        (
                            "A curva de saldo registra encerramentos; a curva de equity inclui "
                            "o valor das posições abertas quando disponível. Um sistema pode "
                            "fechar operações pequenas positivas e manter uma perda aberta "
                            "durante muito tempo. Um drawdown reduzido no saldo, portanto, "
                            "não descreve toda a exposição. Confira qual curva o Rigor "
                            "recebeu e se as datas cobrem as operações. Entender o significado "
                            "da curva faz parte da leitura do resultado."
                        ),
                        (
                            "Com apenas operações fechadas, o drawdown flutuante dentro delas "
                            "fica NOT_MEASURED. Um dado do resumo da plataforma pode continuar "
                            "DECLARED se o arquivo não permite reconstruí-lo. Depósitos e "
                            "saques precisam de tratamento próprio: uma entrada de capital "
                            "altera o saldo, mas não é uma operação. Pergunte também quais "
                            "posições ainda estavam abertas no fim da exportação e se o "
                            "relatório descreve essa lacuna."
                        ),
                    ],
                },
                {
                    "heading": "O que o Rigor revisa no arquivo de um sinal",
                    "paragraphs": [
                        (
                            "Com o histórico adequado, o Rigor procura padrões como aumentar "
                            "o tamanho após perdas, acumular entradas para reduzir o preço "
                            "médio de uma posição em perda e concentrar resultados em poucas "
                            "operações. Revisa perdas grandes diante da perda típica, exposição "
                            "simultânea, movimentações de dinheiro e posições abertas no final. "
                            "São observações sobre os dados enviados; a ausência de um alerta "
                            "não demonstra ausência de risco fora daquele arquivo."
                        ),
                        (
                            "Quando existem operações e custos utilizáveis, o relatório mostra "
                            "a sensibilidade a custos maiores. Também separa métricas calculadas "
                            "do arquivo, MEASURED, informações fornecidas, DECLARED, e perguntas "
                            "que não puderam ser medidas, NOT_MEASURED. Essa separação ajuda "
                            "a formular a próxima pergunta ao fornecedor. O Rigor não entra "
                            "na conta dele, não copia ordens e não decide se você deve "
                            "contratar o sinal. Seu escopo é a evidência enviada."
                        ),
                    ],
                },
                {
                    "heading": "Prepare uma revisão que outra pessoa consiga repetir",
                    "paragraphs": [
                        (
                            "Peça a exportação completa, identifique se a documentação descreve "
                            "uma conta real ou demo e anote o intervalo solicitado. Guarde "
                            "separadamente as explicações do fornecedor, as taxas discriminadas "
                            "e as limitações da curva. O histórico de origem também não "
                            "representa suas próprias execuções: latência, tamanhos e custos "
                            "podem ser diferentes. O relatório grátis permite começar pelas "
                            "perguntas que o arquivo consegue responder e manter as demais "
                            "visíveis, separando uma observação de uma suposição."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Basta una captura del ranking?",
                    "a": (
                        "No permite reconstruir las operaciones ni las pérdidas abiertas. Pide la "
                        "exportación y conserva las fechas y limitaciones del archivo."
                    ),
                },
                {
                    "q": "¿El informe decide si debo copiar?",
                    "a": (
                        "No. Describe la evidencia del historial que subes y las preguntas que "
                        "siguen abiertas. La decisión no forma parte de la auditoría."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Is a ranking screenshot enough?",
                    "a": (
                        "It cannot reconstruct trades or open losses. Request the export and keep "
                        "the file's dates and limitations alongside it."
                    ),
                },
                {
                    "q": "Does the report decide whether I should copy?",
                    "a": (
                        "No. It describes evidence in the uploaded history and questions that "
                        "remain open. That decision is outside the audit's scope."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "Uma captura do ranking é suficiente?",
                    "a": (
                        "Ela não permite reconstruir operações nem perdas abertas. Peça a "
                        "exportação e preserve as datas e limitações do arquivo."
                    ),
                },
                {
                    "q": "O relatório decide se devo copiar?",
                    "a": (
                        "Não. Ele descreve a evidência do histórico enviado e as perguntas que "
                        "continuam abertas. Essa decisão fica fora do escopo da auditoria."
                    ),
                },
            ],
        },
        "related": [
            {"kind": "guide", "slug": "cuenta-proveedor"},
            {"kind": "guide", "slug": "mql5-signal"},
            {"kind": "guide", "slug": "myfxbook"},
            {"kind": "audience", "slug": "copiar-senales"},
            {"kind": "method"},
            {"kind": "calculator"},
        ],
    },
    {
        "key": "bot-ia-backtest-suerte",
        "slug": {
            "es": "bot-ia-backtest-suerte",
            "en": "ai-trading-bot-backtest-luck",
            "pt": "bot-ia-backtest-sorte",
        },
        "title": {
            "es": "Hice un bot con IA en 30 minutos: cómo saber si el backtest es suerte",
            "en": (
                "I built a trading bot with AI in 30 minutes: how to tell if the backtest is luck"
            ),
            "pt": "Fiz um robô com IA em 30 minutos: como saber se o backtest é sorte",
        },
        "seo_title": {
            "es": "Hice un bot con IA en 30 min: ¿es suerte el backtest?",
            "en": "I built an AI bot in 30 min: is the backtest luck?",
            "pt": "Fiz um robô com IA em 30 min: o backtest é sorte?",
        },
        "summary": {
            "es": (
                "Un bot generado rápido también acumula intentos. Cuenta las variantes, compara el "
                "Sharpe con la calculadora y revisa el efecto de los costos."
            ),
            "en": (
                "A quickly generated bot still accumulates trials. Count its variants, compare "
                "Sharpe"
                " with the calculator and inspect the effect of trading costs."
            ),
            "pt": (
                "Um robô gerado depressa também acumula tentativas. Conte as variantes, compare o "
                "Sharpe na calculadora e examine o efeito dos custos."
            ),
        },
        "intro": {
            "es": (
                "DECLARED · Los treinta minutos del título describen una situación ilustrativa, no "
                "un"
                " desarrollo cronometrado por Rigor. Un hilo viral muestra el mensaje enviado a un "
                "agente, el código y una curva ascendente. Lo que suele faltar es el recorrido "
                "entre "
                "esas imágenes: instrucciones descartadas, filtros añadidos y cambios de mercado "
                "después de mirar el resultado. Crear código rápido no crea evidencia nueva. Antes "
                "de"
                " interpretar la curva, hace falta reconstruir cuántas oportunidades tuvo el "
                "proceso "
                "de encontrar una coincidencia favorable en el mismo pasado."
            ),
            "en": (
                "DECLARED · The thirty minutes in the title describe an illustrative situation, "
                "not "
                "development timed by Rigor. A viral thread shows a prompt, generated code and an "
                "upward curve. What often disappears is the path between those images: discarded "
                "instructions, added filters and changes of market after inspecting a result. "
                "Producing code quickly does not produce fresh evidence. Before interpreting the "
                "curve, reconstruct how many opportunities the process had to discover a favorable "
                "coincidence in the same history. The coding tool cannot recover that missing "
                "record "
                "for you."
            ),
            "pt": (
                "DECLARED · Os trinta minutos do título descrevem uma situação ilustrativa, não um "
                "desenvolvimento cronometrado pelo Rigor. Um tópico viral mostra a instrução "
                "enviada "
                "ao agente, o código e uma curva ascendente. O que costuma desaparecer é o caminho "
                "entre essas imagens: instruções descartadas, filtros acrescentados e mudanças de "
                "mercado depois de olhar o resultado. Produzir código depressa não produz "
                "evidência "
                "nova. Antes de interpretar a curva, reconstrua quantas oportunidades o processo "
                "teve"
                " de encontrar uma coincidência favorável no mesmo passado. A ferramenta não "
                "recupera"
                " sozinha esse registro."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Cuenta la búsqueda completa",
                    "paragraphs": [
                        (
                            "Cada vez que el agente prueba una regla y recibe el resultado, esa "
                            "información puede orientar el siguiente cambio. Cambiar el indicador, "
                            "la"
                            " salida, el horario o el activo pertenece a la búsqueda aunque el "
                            "archivo final conserve el mismo nombre. También cuentan las versiones "
                            "que no llegaron al hilo. El número de mensajes del chat no equivale "
                            "al "
                            "número de configuraciones: una instrucción puede lanzar muchas "
                            "combinaciones, y una corrección de sintaxis puede no cambiar ninguna "
                            "regla."
                        ),
                        (
                            "Conserva el registro del optimizador, las versiones y el criterio "
                            "usado "
                            "para elegir. Si falta parte del recorrido, declara esa ausencia. Un "
                            "recuento parcial no debe presentarse como el total medido."
                        ),
                    ],
                },
                {
                    "heading": "Compara contra una búsqueda sin habilidad",
                    "paragraphs": [
                        (
                            "La calculadora pública recibe el Sharpe anual, la duración y el "
                            "número "
                            "de configuraciones. Compara el resultado declarado con el Sharpe "
                            "esperado de la mejor variante de una búsqueda sin habilidad bajo sus "
                            "supuestos. Esa referencia no describe una cuenta concreta. Tampoco es "
                            "la"
                            " probabilidad de que el bot funcione después. Resume cuánto puede "
                            "elevar"
                            " el máximo observado el simple hecho de seleccionar entre "
                            "alternativas."
                        ),
                        (
                            "La tabla usa entradas declaradas y rendimientos diarios con colas "
                            "normales. Mantiene el mismo Sharpe de entrada al cambiar duración e "
                            "intentos. Las variantes parecidas no son independientes: conserva esa "
                            "limitación al interpretar el cálculo, sin convertirla en permiso para "
                            "borrar intentos."
                        ),
                    ],
                },
                {
                    "heading": "Lee la tabla antes de celebrar la curva",
                    "paragraphs": [
                        (
                            "La tabla cruza tamaños de búsqueda con duraciones del historial. Cada "
                            "fila vuelve a llamar a la calculadora; ninguna celda procede de una "
                            "captura viral. Al aumentar la búsqueda aumenta la referencia de "
                            "suerte, "
                            "mientras que ampliar el historial suele reducir su dispersión. Eso "
                            "explica por qué una curva seleccionada después de muchas pruebas "
                            "exige "
                            "más contexto que una regla definida de antemano."
                        ),
                        (
                            "Los años no son intercambiables con las operaciones. Muchas entradas "
                            "concentradas en el mismo episodio pueden aportar poca diversidad. "
                            "Revisa"
                            " la cobertura temporal, las pausas y los cambios de régimen, además "
                            "del "
                            "total de filas."
                        ),
                    ],
                },
                {
                    "heading": "Somete los costos al doble",
                    "paragraphs": [
                        (
                            "DECLARED · La prueba a 2x es un escenario: duplica los supuestos de "
                            "costos y compara el resultado con la ejecución base. Documenta "
                            "comisión,"
                            " spread, deslizamiento y financiación cuando correspondan. Evita "
                            "descontar otra vez un costo que ya figure dentro de la serie neta. Si "
                            "solo tienes rendimientos agregados y desconoces las operaciones o sus "
                            "gastos, ese efecto queda NOT_MEASURED; no rellenes el vacío con una "
                            "cifra cómoda."
                        ),
                        (
                            "Rigor revisa la sensibilidad a costos cuando el archivo aporta la "
                            "información necesaria. Observa cuánto cambia la lectura y qué parte "
                            "sigue sin medirse. Un escenario de costos no reproduce todas las "
                            "condiciones de ejecución de una plataforma."
                        ),
                    ],
                },
                {
                    "heading": "Separa desarrollo y evaluación",
                    "paragraphs": [
                        (
                            "Reserva un tramo que el agente no haya visto y define antes qué "
                            "compararás. Si modificas la estrategia tras conocer ese resultado, el "
                            "tramo ya influyó en el desarrollo. Guárdalo en el registro de "
                            "búsqueda y"
                            " explica el cambio. Repetir el ciclo hasta obtener una curva "
                            "atractiva "
                            "no recupera la independencia perdida."
                        ),
                        (
                            "Inspecciona además si los precios usados estaban disponibles al "
                            "decidir,"
                            " cómo se ajustaron los datos y si el universo conserva instrumentos "
                            "desaparecidos. Un error de fechas puede dominar cualquier corrección "
                            "estadística. Pide al agente que explique decisiones y supuestos; el "
                            "tono"
                            " seguro de su respuesta no sustituye una prueba reproducible."
                        ),
                    ],
                },
                {
                    "heading": "Lleva el archivo a la lectura pública",
                    "paragraphs": [
                        (
                            "El lector público enlazado permite empezar por cifras declaradas. La "
                            "calculadora ayuda a explorar otros tamaños de búsqueda. Para revisar "
                            "la "
                            "evidencia del historial, conserva el archivo original y acompáñalo de "
                            "los intentos conocidos, la frecuencia y los costos. Una imagen del "
                            "saldo"
                            " no contiene esa trazabilidad."
                        ),
                        (
                            "En el informe, MEASURED identifica lo calculado con los archivos, "
                            "DECLARED lo aportado por ti y NOT_MEASURED lo que no pudo evaluarse. "
                            "El "
                            "primer informe completo gratis usa el mismo acceso que los demás "
                            "artículos. Su lectura puede señalar ausencias o debilidades del "
                            "backtest; no decide por ti ni conecta el bot a una cuenta."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "Count the complete search",
                    "paragraphs": [
                        (
                            "Whenever the agent tests a rule and receives a result, that "
                            "information "
                            "can guide its next change. Switching the indicator, exit, session or "
                            "market belongs to the search even if the final file keeps its "
                            "original "
                            "name. Versions omitted from the thread count too. Chat messages are "
                            "not "
                            "a configuration count: an instruction can launch many combinations, "
                            "while a syntax correction may leave every trading rule unchanged."
                        ),
                        (
                            "Keep optimizer logs, saved versions and the selection criterion. If "
                            "part"
                            " of the search is missing, declare that gap. A partial count should "
                            "not "
                            "appear as a measured total simply because it is the only count "
                            "available."
                        ),
                    ],
                },
                {
                    "heading": "Compare against a search without skill",
                    "paragraphs": [
                        (
                            "The public calculator takes annual Sharpe, history length and "
                            "configuration count. It compares the declared result with the "
                            "expected "
                            "Sharpe of the best unskilled variant under its assumptions. This "
                            "reference does not describe a particular account. It is not the "
                            "probability that the bot will work later. It summarizes how selecting "
                            "among alternatives can lift the largest observed result even without "
                            "skill."
                        ),
                        (
                            "The table uses declared inputs and daily returns with normal tails. "
                            "It "
                            "holds the input Sharpe constant while varying duration and trials. "
                            "Similar variants are not independent: keep that limitation visible "
                            "without using it as permission to erase attempted configurations from "
                            "the record."
                        ),
                    ],
                },
                {
                    "heading": "Read the table before celebrating the curve",
                    "paragraphs": [
                        (
                            "The table crosses search sizes with history lengths. Every row calls "
                            "the"
                            " calculator again; no cell comes from a viral screenshot. A larger "
                            "search raises the luck reference, while a longer history generally "
                            "narrows its dispersion. This helps explain why a curve selected after "
                            "extensive testing needs more context than a rule specified "
                            "beforehand. "
                            "It does not establish a universal threshold for accepting a strategy."
                        ),
                        (
                            "Years and trades are different quantities. Many entries clustered in "
                            "the"
                            " same market episode may offer little variety. Inspect calendar "
                            "coverage, inactive stretches and changing conditions as well as the "
                            "number of rows in the exported file."
                        ),
                    ],
                },
                {
                    "heading": "Stress costs at twice the baseline",
                    "paragraphs": [
                        (
                            "DECLARED · The 2x cost test is a scenario: double the cost "
                            "assumptions "
                            "and compare with the baseline calculation. Record commission, spread, "
                            "slippage and financing where relevant. Avoid subtracting a cost again "
                            "if"
                            " it is already included in net returns. If only aggregate returns are "
                            "available and trades or expenses are unknown, that effect remains "
                            "NOT_MEASURED. A convenient guess does not fill the evidence gap."
                        ),
                        (
                            "Rigor examines cost sensitivity when the uploaded file contains the "
                            "necessary information. Inspect the change and identify what remains "
                            "unmeasured. A cost scenario cannot reproduce every execution "
                            "condition "
                            "on a platform, including the timing of fills during a disruption."
                        ),
                    ],
                },
                {
                    "heading": "Separate development from evaluation",
                    "paragraphs": [
                        (
                            "Reserve a period the agent has not seen and specify the comparison "
                            "beforehand. If you change the strategy after observing that result, "
                            "the "
                            "period has influenced development. Keep it in the search record and "
                            "explain the change. Repeating this cycle until an attractive curve "
                            "appears does not restore the lost independence. An untouched period "
                            "matters because it limits feedback into selection."
                        ),
                        (
                            "Also inspect whether the prices were available at decision time, how "
                            "adjustments were applied and whether the universe retains "
                            "discontinued "
                            "instruments. A timestamp error can dominate any statistical "
                            "correction. "
                            "Ask the agent to explain choices and assumptions; a confident "
                            "explanation cannot replace a reproducible check of the underlying "
                            "data."
                        ),
                    ],
                },
                {
                    "heading": "Take the evidence to the public reader",
                    "paragraphs": [
                        (
                            "The linked public reader provides a starting point with declared "
                            "figures. The calculator helps explore other search sizes. To examine "
                            "the"
                            " history itself, preserve the original file alongside the known "
                            "attempts, frequency and costs. A balance screenshot does not contain "
                            "this record, and a narrative cannot reconstruct missing observations."
                        ),
                        (
                            "In a report, MEASURED marks calculations from files, DECLARED marks "
                            "information you supplied, and NOT_MEASURED marks what could not be "
                            "evaluated. The free first full report uses the same access as the "
                            "other "
                            "articles. Its findings can identify missing evidence or weaknesses in "
                            "a "
                            "backtest; they do not make a decision for you or connect the bot to "
                            "an "
                            "account."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Conte a busca completa",
                    "paragraphs": [
                        (
                            "Sempre que o agente testa uma regra e recebe o resultado, essa "
                            "informação pode orientar a mudança seguinte. Trocar indicador, saída, "
                            "horário ou mercado faz parte da busca mesmo quando o arquivo final "
                            "mantém o nome original. As versões omitidas do tópico também contam. "
                            "Mensagens do chat não equivalem a configurações: uma instrução pode "
                            "lançar muitas combinações, enquanto uma correção de sintaxe pode não "
                            "alterar regra alguma."
                        ),
                        (
                            "Guarde os registros do otimizador, as versões e o critério de "
                            "escolha. "
                            "Se parte do percurso estiver ausente, declare essa falta. Uma "
                            "contagem "
                            "parcial não deve aparecer como total medido apenas porque é a única "
                            "disponível."
                        ),
                    ],
                },
                {
                    "heading": "Compare com uma busca sem habilidade",
                    "paragraphs": [
                        (
                            "A calculadora pública recebe Sharpe anual, duração do histórico e "
                            "quantidade de configurações. Ela compara o resultado declarado com o "
                            "Sharpe esperado da melhor variante sem habilidade sob suas "
                            "suposições. "
                            "Essa referência não descreve uma conta concreta. Também não é a "
                            "probabilidade de o robô funcionar depois. Ela resume quanto a seleção "
                            "entre alternativas pode elevar o maior resultado observado."
                        ),
                        (
                            "A tabela usa entradas declaradas e retornos diários com caudas "
                            "normais. "
                            "Mantém o Sharpe de entrada ao variar duração e tentativas. Variantes "
                            "semelhantes não são independentes: mantenha essa limitação visível, "
                            "sem "
                            "transformá-la em permissão para apagar configurações que foram "
                            "testadas."
                            " O registro deve explicar o processo de seleção."
                        ),
                    ],
                },
                {
                    "heading": "Leia a tabela antes de celebrar a curva",
                    "paragraphs": [
                        (
                            "A tabela cruza tamanhos de busca com durações do histórico. Cada "
                            "linha "
                            "chama novamente a calculadora; nenhuma célula vem de uma captura "
                            "viral. "
                            "Aumentar a busca eleva a referência de sorte, enquanto ampliar o "
                            "histórico costuma reduzir sua dispersão. Isso ajuda a explicar por "
                            "que "
                            "uma curva escolhida depois de muitos testes exige mais contexto que "
                            "uma "
                            "regra definida antes da análise."
                        ),
                        (
                            "Anos e operações são quantidades diferentes. Muitas entradas "
                            "concentradas no mesmo episódio podem oferecer pouca diversidade. "
                            "Examine"
                            " a cobertura temporal, os intervalos sem atividade e as mudanças de "
                            "condições, além do total de linhas. O calendário faz parte da "
                            "interpretação, não apenas da apresentação."
                        ),
                    ],
                },
                {
                    "heading": "Examine os custos em dobro",
                    "paragraphs": [
                        (
                            "DECLARED · O teste a 2x é um cenário: dobre as suposições de custos e "
                            "compare com o cálculo base. Documente comissão, spread, deslizamento "
                            "e "
                            "financiamento quando aplicáveis. Evite descontar novamente um custo "
                            "já "
                            "incluído nos retornos líquidos. Se houver apenas retornos agregados e "
                            "as"
                            " operações ou despesas forem desconhecidas, esse efeito fica "
                            "NOT_MEASURED. Uma estimativa conveniente não preenche a falta de "
                            "evidência."
                        ),
                        (
                            "O Rigor examina a sensibilidade a custos quando o arquivo enviado "
                            "contém"
                            " as informações necessárias. Observe a mudança e identifique o que "
                            "continua sem medição. Um cenário de custos não reproduz todas as "
                            "condições de execução de uma plataforma, inclusive atrasos em "
                            "momentos "
                            "de interrupção."
                        ),
                    ],
                },
                {
                    "heading": "Separe desenvolvimento e avaliação",
                    "paragraphs": [
                        (
                            "Reserve um período que o agente ainda não tenha visto e defina antes "
                            "a "
                            "comparação. Se alterar a estratégia depois de observar esse "
                            "resultado, o"
                            " período já influenciou o desenvolvimento. Mantenha isso no registro "
                            "da "
                            "busca e explique a mudança. Repetir o ciclo até obter uma curva "
                            "atraente"
                            " não recupera a independência perdida. Um trecho intocado limita a "
                            "informação que volta para a escolha."
                        ),
                        (
                            "Examine também se os preços estavam disponíveis no momento da "
                            "decisão, "
                            "como os dados foram ajustados e se o universo conserva instrumentos "
                            "que "
                            "desapareceram. Um erro de datas pode dominar qualquer correção "
                            "estatística. Peça ao agente explicações sobre escolhas e suposições; "
                            "uma"
                            " resposta confiante não substitui uma checagem reproduzível dos dados."
                        ),
                    ],
                },
                {
                    "heading": "Leve a evidência ao leitor público",
                    "paragraphs": [
                        (
                            "O leitor público relacionado permite começar por números declarados. "
                            "A "
                            "calculadora ajuda a explorar outros tamanhos de busca. Para examinar "
                            "o "
                            "histórico, preserve o arquivo original junto com as tentativas "
                            "conhecidas, a frequência e os custos. Uma imagem do saldo não contém "
                            "esse registro, e uma narrativa não recupera observações ausentes."
                        ),
                        (
                            "No relatório, MEASURED identifica cálculos com os arquivos, DECLARED "
                            "identifica o que você informou e NOT_MEASURED identifica o que não "
                            "pôde "
                            "ser avaliado. O primeiro relatório completo gratuito usa o mesmo "
                            "acesso "
                            "dos demais artigos. A leitura pode apontar ausências ou fragilidades "
                            "do "
                            "backtest; não decide por você nem conecta o robô a uma conta."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿La IA cambia cómo se interpreta el backtest?",
                    "a": (
                        "Cambia la velocidad de exploración, pero siguen importando los datos "
                        "disponibles al decidir, los costos y las variantes descartadas. Si el "
                        "agente"
                        " recibió resultados anteriores, registra ese recorrido. El archivo "
                        "elegido "
                        "por sí solo no revela toda la búsqueda."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Does AI change how a backtest should be read?",
                    "a": (
                        "It changes the speed of exploration, but data available at decision time, "
                        "costs and discarded variants still matter. If the agent received earlier "
                        "results, record that process. The selected file alone cannot reveal the "
                        "entire search or show which alternatives influenced its selection."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "A IA muda como interpretar um backtest?",
                    "a": (
                        "Ela muda a velocidade de exploração, mas continuam relevantes os dados "
                        "disponíveis ao decidir, os custos e as variantes descartadas. Se o agente "
                        "recebeu resultados anteriores, registre esse percurso. O arquivo "
                        "escolhido "
                        "sozinho não revela toda a busca nem mostra quais alternativas "
                        "influenciaram "
                        "a escolha."
                    ),
                },
            ],
        },
        "related": [
            {
                "kind": "reading",
            },
            {
                "kind": "calculator",
            },
            {
                "kind": "method",
            },
        ],
    },
)

ARTICLES_DATA += (
    {
        "key": "que-hacer-despues-del-backtest",
        "slug": {
            "es": "que-hacer-despues-del-backtest",
            "en": "what-to-do-after-a-backtest",
            "pt": "o-que-fazer-depois-do-backtest",
        },
        "title": {
            "es": "Qué hacer después del backtest: seis comprobaciones",
            "en": "What to do after a backtest: six checks",
            "pt": "O que fazer depois do backtest: seis checagens",
        },
        "summary": {
            "es": (
                "Seis comprobaciones para poner un backtest en contexto, con "
                "ejemplos calculados y los archivos que necesitas exportar."
            ),
            "en": (
                "Six checks to put a backtest in context, with calculated examples"
                " and the files you need to export."
            ),
            "pt": (
                "Seis checagens para colocar um backtest em contexto, com exemplos"
                " calculados e os arquivos que você precisa exportar."
            ),
        },
        "intro": {
            "es": (
                "Ya tienes una curva que te convence. El siguiente paso es "
                "conservar el archivo y preguntar qué explica ese resultado. Estas"
                " seis comprobaciones ordenan la revisión: no basta con acumular "
                "operaciones ni con mirar el saldo final. Empieza por la "
                "incertidumbre, reconstruye la búsqueda y después examina costos, "
                "separación temporal, datos y referencia."
            ),
            "en": (
                "You have a curve that looks convincing. The next step is to "
                "preserve the file and ask what explains that result. These six "
                "checks organise the review: accumulating trades or looking at the"
                " ending balance is not enough. Start with uncertainty, "
                "reconstruct the search, then examine costs, time separation, data"
                " and a benchmark."
            ),
            "pt": (
                "Você já tem uma curva que parece convincente. O próximo passo é "
                "preservar o arquivo e perguntar o que explica esse resultado. "
                "Estas seis checagens organizam a revisão: acumular operações ou "
                "olhar o saldo final não basta. Comece pela incerteza, reconstrua "
                "a busca e depois examine custos, separação temporal, dados e "
                "referência."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Significancia: mira la incertidumbre",
                    "paragraphs": [
                        (
                            "Un porcentaje de aciertos es una estimación. Su precisión depende"
                            " del tamaño de la muestra y de si las operaciones aportan "
                            "observaciones independientes. Varias entradas sobre el mismo "
                            "movimiento pueden compartir el mismo riesgo. Un intervalo "
                            "estrecho tampoco describe cuánto se pierde cuando la operación "
                            "sale mal."
                        ),
                        (
                            "DECLARED · Ejemplo ilustrativo: 45 operaciones y 71 % de aciertos"
                            " declarado, quizá redondeado. La función Wilson del lector de "
                            "Rigor calcula un intervalo al 95 % de "
                            f"{win_rate_interval(0.71, 45, 'es')}. No procede de un archivo de "
                            "cliente. No es una prueba de significancia del resultado "
                            "monetario ni una previsión de la siguiente operación."
                        ),
                        (
                            "Para los rendimientos, el informe examina el Sharpe "
                            "probabilístico: incorpora tamaño de muestra, asimetría y colas. "
                            "Cuando dispone de la serie, también evalúa dependencia temporal y"
                            " remuestrea por bloques. Revisa estas pruebas y sus límites, no "
                            "solo el porcentaje de aciertos."
                        ),
                    ],
                },
                {
                    "heading": "Configuraciones probadas: reconstruye la búsqueda",
                    "paragraphs": [
                        (
                            "Anota las combinaciones de parámetros, versiones descartadas y "
                            "cambios de activo o periodo que influyeron en la elección. Si "
                            "solo conservas la variante elegida, falta el contexto que permite"
                            " evaluar la selección. Cuenta también las pruebas manuales; no "
                            "conviertas un número desconocido en una única prueba."
                        ),
                        (
                            "El artículo enlazado sobre el Sharpe deflactado desarrolla el "
                            "ejemplo de suerte y los supuestos de la calculadora. Ese ejemplo "
                            "calcula el Sharpe esperado por suerte, no la probabilidad de que "
                            "tu estrategia funcione. Declara la búsqueda completa y conserva "
                            "sus pasadas para contrastar esa declaración."
                        ),
                    ],
                },
                {
                    "heading": "Costo de equilibrio: mide el margen restante",
                    "paragraphs": [
                        (
                            "El costo de equilibrio indica qué costo adicional por lado "
                            "llevaría el resultado agregado del archivo a cero. Se calcula "
                            "sobre precios, cantidades y costos ya cargados. Distingue "
                            "comisión, spread incorporado en los precios y deslizamiento "
                            "adicional: sumar otra vez una comisión ya descontada cambia la "
                            "pregunta."
                        ),
                        (
                            "DECLARED · Ejemplo sintético separado: una compra de 1 unidad a "
                            "100 y cierre a 101, sin comisiones reportadas. La función "
                            "break_even_bps de Rigor calcula "
                            f"{_num(_COST_EXAMPLE_BPS, 'es', 2)} puntos básicos por lado de "
                            "costo adicional hasta el equilibrio. Se "
                            "aplica al nominal de entrada y salida; no es una tarifa observada"
                            " ni un supuesto adecuado para todos los mercados."
                        ),
                    ],
                },
                {
                    "heading": "Dentro y fuera de muestra: conserva la frontera",
                    "paragraphs": [
                        (
                            "Guarda las fechas usadas para elegir los parámetros y las "
                            "reservadas para evaluarlos. Un tramo fuera de muestra debe "
                            "permanecer ajeno a esa elección. Si lo consultas y ajustas la "
                            "estrategia, ya influyó en el desarrollo: cambia su etiqueta y "
                            "reserva evidencia nueva antes de repetir la evaluación."
                        ),
                        (
                            "Exporta la serie temporal y registra las decisiones junto con la "
                            "frontera. Una caída fuera de muestra merece explicación, aunque "
                            "el total agregado resulte atractivo. NOT_MEASURED corresponde a "
                            "una comparación que no puede hacerse con los archivos; una fecha "
                            "escrita en un formulario no demuestra que el tramo estuviera "
                            "intacto."
                        ),
                    ],
                },
                {
                    "heading": "Calidad de datos: comprueba qué sabía la estrategia",
                    "paragraphs": [
                        (
                            "Revisa huecos, duplicados, zona horaria, ajustes y precios "
                            "disponibles al decidir. Conserva la fuente, el rango temporal y "
                            "la versión de datos. Examina si el universo mantiene instrumentos"
                            " que desaparecieron y si alguna señal utiliza información "
                            "posterior al momento de entrada."
                        ),
                        (
                            "El historial de operaciones permite detectar algunos problemas, "
                            "pero no reconstruye por sí solo los datos originales ni la lógica"
                            " de señales. Documenta lo que falta como NOT_MEASURED. Un campo "
                            "de calidad del probador no resuelve todas estas preguntas."
                        ),
                    ],
                },
                {
                    "heading": "Referencia: compara la misma pregunta",
                    "paragraphs": [
                        (
                            "Elige una referencia pertinente antes de mirar cuál favorece al "
                            "sistema. Compara sobre las mismas fechas, moneda, frecuencia y "
                            "supuestos de costos. Una exposición simple al mercado puede "
                            "explicar parte de una curva; sin una referencia alineada no sabes"
                            " cuánto aporta la regla elegida."
                        ),
                        (
                            "Conserva la serie de la referencia y explica por qué es "
                            "relevante. Si no está disponible, la comparación queda "
                            "NOT_MEASURED. No sustituyas una serie ausente por una cifra "
                            "recordada ni compares ventanas distintas como si fueran "
                            "equivalentes."
                        ),
                    ],
                },
                {
                    "heading": "Qué archivo exportar de cada plataforma",
                    "paragraphs": [
                        (
                            "MT4 y MT5: guarda el informe HTML completo del probador, con sus "
                            "operaciones. Para una búsqueda de MT5, añade el XML de Excel 2003"
                            " con las pasadas del optimizador. El informe de la variante "
                            "elegida y la tabla de pasadas responden a preguntas distintas; "
                            "los enlaces de exportación están al final."
                        ),
                        (
                            "TradingView: exporta el CSV de la lista de operaciones del "
                            "probador de estrategias. NinjaTrader: exporta la tabla Trades de "
                            "Strategy Analyzer a CSV. Desde Python, prepara el CSV con el "
                            "esquema de la guía. Si también revisas un historial, Myfxbook "
                            "permite CSV y FX Blue CSV; identifica que se trata de una cuenta "
                            "y no de un backtest."
                        ),
                        (
                            "Conserva además parámetros, costos, fechas de separación, "
                            "referencia y procedencia de los datos como contexto. No todo lo "
                            "que falta cabe en el archivo de operaciones. MEASURED identifica "
                            "cálculos sobre los archivos, DECLARED tus aportaciones y "
                            "NOT_MEASURED lo que no pudo evaluarse."
                        ),
                        (
                            "QuantConnect: descarga Trades en CSV, no Orders. En "
                            "backtesting.py exporta stats._trades.to_csv('trades.csv'); en "
                            "vectorbt, pf.trades.records_readable.to_csv('trades.csv'). Si hay"
                            " varias columnas de estrategias, identifica la seleccionada y "
                            "declara las demás variantes. Las guías enlazadas explican cada "
                            "formato."
                        ),
                    ],
                },
                {
                    "heading": "Empieza por las cifras que ya tienes",
                    "paragraphs": [
                        (
                            "El lector de cifras y la calculadora de suerte no piden cuenta. "
                            "Sirven para explorar declaraciones y supuestos; no asignan una "
                            "clase de auditoría. Para revisar el archivo y sus ausencias, el "
                            "primer informe completo es gratis con cuenta. La revisión "
                            "describe evidencia histórica y no decide una operación por ti."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "Significance: look at uncertainty",
                    "paragraphs": [
                        (
                            "A win rate is an estimate. Its precision depends on sample size "
                            "and whether trades contribute independent observations. Several "
                            "entries on the same market move may share the same risk. A narrow"
                            " interval also says nothing about how much is lost when a trade "
                            "goes wrong."
                        ),
                        (
                            "DECLARED · Illustrative example: 45 trades and a declared, "
                            "possibly rounded, 71 % win rate. Rigor's reader Wilson function "
                            f"calculates a 95 % interval of {win_rate_interval(0.71, 45, 'en')}"
                            ". This does not come from a client file. It is not a significance"
                            " test of the monetary result or a forecast of the next trade."
                        ),
                        (
                            "For returns, the report examines probabilistic Sharpe, "
                            "incorporating sample size, skewness and tails. When the series is"
                            " available, it also assesses time dependence and uses block "
                            "resampling. Review these tests and their limits alongside the win"
                            " rate."
                        ),
                    ],
                },
                {
                    "heading": "Configurations tried: reconstruct the search",
                    "paragraphs": [
                        (
                            "Record parameter combinations, discarded versions and changes of "
                            "asset or period that influenced the choice. Keeping only the "
                            "selected variant loses the context needed to assess selection. "
                            "Include manual experiments too; do not turn an unknown count into"
                            " a single trial."
                        ),
                        (
                            "The linked article on deflated Sharpe develops the luck example "
                            "and the calculator's assumptions. That example calculates "
                            "expected Sharpe from luck, not the probability that your strategy"
                            " will work. Declare the whole search and preserve its passes to "
                            "compare with that declaration."
                        ),
                    ],
                },
                {
                    "heading": "Break-even cost: measure the remaining margin",
                    "paragraphs": [
                        (
                            "Break-even cost is the additional cost per side that would bring "
                            "the file's aggregate result to zero. It uses prices, quantities "
                            "and costs already charged. Distinguish commission, spread "
                            "embedded in prices and additional slippage: adding a commission "
                            "already deducted changes the question."
                        ),
                        (
                            "DECLARED · Separate synthetic example: buy 1 unit at 100 and "
                            "close at 101, with no reported commissions. Rigor's "
                            "break_even_bps function calculates "
                            f"{_num(_COST_EXAMPLE_BPS, 'en', 2)} basis points per side of "
                            "additional cost to break even. This applies to"
                            " entry and exit notional; it is neither an observed fee nor an "
                            "appropriate assumption for every market."
                        ),
                    ],
                },
                {
                    "heading": "In and out of sample: preserve the boundary",
                    "paragraphs": [
                        (
                            "Save the dates used to select parameters and those reserved for "
                            "evaluation. An out-of-sample segment must remain separate from "
                            "that choice. If you inspect it and adjust the strategy, it has "
                            "influenced development: relabel it and reserve fresh evidence "
                            "before evaluating again."
                        ),
                        (
                            "Export the time series and record decisions alongside the "
                            "boundary. A deterioration out of sample deserves explanation even"
                            " when the aggregate looks attractive. NOT_MEASURED applies when "
                            "the files cannot support the comparison; a date typed into a form"
                            " does not demonstrate that the segment remained untouched."
                        ),
                    ],
                },
                {
                    "heading": "Data quality: check what the strategy knew",
                    "paragraphs": [
                        (
                            "Review gaps, duplicates, time zones, adjustments and prices "
                            "available at decision time. Preserve the source, date range and "
                            "data version. Check whether the universe retains instruments that"
                            " disappeared and whether any signal uses information arriving "
                            "after entry."
                        ),
                        (
                            "The trade history can reveal some problems, but it cannot by "
                            "itself reconstruct the original data or signal logic. Document "
                            "what is missing as NOT_MEASURED. A tester quality field does not "
                            "resolve all these questions."
                        ),
                    ],
                },
                {
                    "heading": "Benchmark: compare the same question",
                    "paragraphs": [
                        (
                            "Choose a relevant benchmark before looking at which one favours "
                            "the system. Compare the same dates, currency, frequency and cost "
                            "assumptions. Simple market exposure may explain part of a curve; "
                            "without an aligned benchmark you cannot tell how much the chosen "
                            "rule contributes."
                        ),
                        (
                            "Keep the benchmark series and explain its relevance. If it is "
                            "unavailable, the comparison stays NOT_MEASURED. Do not replace a "
                            "missing series with a remembered figure or compare different "
                            "windows as though they were equivalent."
                        ),
                    ],
                },
                {
                    "heading": "Which file to export from each platform",
                    "paragraphs": [
                        (
                            "MT4 and MT5: save the complete tester HTML report, including "
                            "trades. For an MT5 search, add the Excel 2003 XML optimiser "
                            "passes. The selected variant's report and the passes table answer"
                            " different questions; export guides are linked below."
                        ),
                        (
                            "TradingView: export the strategy tester's list of trades as CSV. "
                            "NinjaTrader: export the Strategy Analyzer Trades table as CSV. "
                            "From Python, prepare the CSV using the guide's schema. If you are"
                            " also reviewing an account history, Myfxbook offers CSV and FX "
                            "Blue CSV; identify it as an account history rather than a "
                            "backtest."
                        ),
                        (
                            "Also preserve parameters, costs, split dates, the benchmark and "
                            "data provenance as context. Not everything missing fits in the "
                            "trade file. MEASURED identifies calculations from files, DECLARED"
                            " your inputs and NOT_MEASURED what could not be assessed."
                        ),
                        (
                            "QuantConnect: download Trades as CSV, not Orders. In "
                            "backtesting.py export stats._trades.to_csv('trades.csv'); in "
                            "vectorbt, pf.trades.records_readable.to_csv('trades.csv'). If "
                            "there are several strategy columns, identify the selected one and"
                            " declare the other variants. The linked guides explain each "
                            "format."
                        ),
                    ],
                },
                {
                    "heading": "Start with the figures you already have",
                    "paragraphs": [
                        (
                            "The figure reader and luck calculator need no account. They "
                            "explore declarations and assumptions; they do not assign an audit"
                            " class. To examine the file and its gaps, your first full report "
                            "is free with an account. The review describes historical evidence"
                            " and does not decide a trade for you."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Significância: observe a incerteza",
                    "paragraphs": [
                        (
                            "Uma taxa de acerto é uma estimativa. Sua precisão depende do "
                            "tamanho da amostra e de as operações fornecerem observações "
                            "independentes. Várias entradas no mesmo movimento podem "
                            "compartilhar o mesmo risco. Um intervalo estreito também não "
                            "descreve quanto se perde quando a operação dá errado."
                        ),
                        (
                            "DECLARED · Exemplo ilustrativo: 45 operações e taxa de acerto "
                            "declarada de 71 %, talvez arredondada. A função Wilson do leitor "
                            "do Rigor calcula um intervalo de 95 % de "
                            f"{win_rate_interval(0.71, 45, 'pt')}. Isso não vem de um arquivo "
                            "de cliente. Não é um teste de significância do resultado "
                            "monetário nem uma previsão da próxima operação."
                        ),
                        (
                            "Para os retornos, o relatório examina o Sharpe probabilístico, "
                            "considerando tamanho da amostra, assimetria e caudas. Quando a "
                            "série está disponível, também avalia dependência temporal e faz "
                            "reamostragem em blocos. Revise esses testes e seus limites junto "
                            "da taxa de acerto."
                        ),
                    ],
                },
                {
                    "heading": "Configurações testadas: reconstrua a busca",
                    "paragraphs": [
                        (
                            "Registre combinações de parâmetros, versões descartadas e "
                            "mudanças de ativo ou período que influenciaram a escolha. Guardar"
                            " apenas a variante escolhida perde o contexto necessário para "
                            "avaliar a seleção. Inclua os testes manuais; não transforme uma "
                            "contagem desconhecida em uma única tentativa."
                        ),
                        (
                            "O artigo vinculado sobre o Sharpe deflacionado desenvolve o "
                            "exemplo de sorte e as suposições da calculadora. Esse exemplo "
                            "calcula o Sharpe esperado por sorte, não a probabilidade de a "
                            "estratégia funcionar. Declare toda a busca e preserve suas "
                            "passagens para comparar com essa declaração."
                        ),
                    ],
                },
                {
                    "heading": "Custo de equilíbrio: meça a margem restante",
                    "paragraphs": [
                        (
                            "O custo de equilíbrio indica o custo adicional por lado que "
                            "levaria o resultado agregado do arquivo a zero. O cálculo usa "
                            "preços, quantidades e custos já cobrados. Diferencie comissão, "
                            "spread incorporado nos preços e deslizamento adicional: somar "
                            "novamente uma comissão já descontada muda a pergunta."
                        ),
                        (
                            "DECLARED · Exemplo sintético separado: compra de 1 unidade a 100 "
                            "e fechamento a 101, sem comissões reportadas. A função "
                            f"break_even_bps do Rigor calcula {_num(_COST_EXAMPLE_BPS, 'pt', 2)} "
                            "pontos-base por lado de custo adicional até o equilíbrio. Isso se"
                            " aplica ao valor nominal de entrada e saída; não é uma tarifa "
                            "observada nem uma suposição adequada para todos os mercados."
                        ),
                    ],
                },
                {
                    "heading": "Dentro e fora da amostra: preserve a fronteira",
                    "paragraphs": [
                        (
                            "Guarde as datas usadas para escolher os parâmetros e as "
                            "reservadas para avaliá-los. Um trecho fora da amostra deve "
                            "permanecer separado dessa escolha. Se você o consulta e ajusta a "
                            "estratégia, ele já influenciou o desenvolvimento: mude sua "
                            "identificação e reserve evidência nova antes de avaliar "
                            "novamente."
                        ),
                        (
                            "Exporte a série temporal e registre as decisões junto da "
                            "fronteira. Uma queda fora da amostra merece explicação, mesmo que"
                            " o total pareça atraente. NOT_MEASURED corresponde a uma "
                            "comparação que os arquivos não permitem; uma data escrita no "
                            "formulário não demonstra que o trecho permaneceu intocado."
                        ),
                    ],
                },
                {
                    "heading": "Qualidade dos dados: confira o que a estratégia sabia",
                    "paragraphs": [
                        (
                            "Revise lacunas, duplicatas, fuso horário, ajustes e preços "
                            "disponíveis ao decidir. Preserve a fonte, o intervalo temporal e "
                            "a versão dos dados. Examine se o universo mantém instrumentos que"
                            " desapareceram e se algum sinal usa informação posterior ao "
                            "momento de entrada."
                        ),
                        (
                            "O histórico de operações permite detectar alguns problemas, mas "
                            "não reconstrói sozinho os dados originais nem a lógica dos "
                            "sinais. Documente o que falta como NOT_MEASURED. Um campo de "
                            "qualidade do testador não resolve todas essas perguntas."
                        ),
                    ],
                },
                {
                    "heading": "Referência: compare a mesma pergunta",
                    "paragraphs": [
                        (
                            "Escolha uma referência pertinente antes de observar qual favorece"
                            " o sistema. Compare as mesmas datas, moeda, frequência e "
                            "suposições de custos. Uma exposição simples ao mercado pode "
                            "explicar parte da curva; sem uma referência alinhada não se sabe "
                            "quanto a regra escolhida acrescenta."
                        ),
                        (
                            "Guarde a série de referência e explique sua relevância. Se ela "
                            "não estiver disponível, a comparação fica NOT_MEASURED. Não "
                            "substitua uma série ausente por um número lembrado nem compare "
                            "janelas diferentes como se fossem equivalentes."
                        ),
                    ],
                },
                {
                    "heading": "Qual arquivo exportar de cada plataforma",
                    "paragraphs": [
                        (
                            "MT4 e MT5: salve o relatório HTML completo do testador, com as "
                            "operações. Para uma busca no MT5, acrescente o XML de Excel 2003 "
                            "com as passagens do otimizador. O relatório da variante escolhida"
                            " e a tabela de passagens respondem a perguntas diferentes; os "
                            "guias de exportação estão abaixo."
                        ),
                        (
                            "TradingView: exporte o CSV da lista de operações do testador de "
                            "estratégias. NinjaTrader: exporte a tabela Trades do Strategy "
                            "Analyzer para CSV. No Python, prepare o CSV com o esquema do "
                            "guia. Se também estiver revisando um histórico de conta, Myfxbook"
                            " oferece CSV e FX Blue CSV; identifique que é uma conta, não um "
                            "backtest."
                        ),
                        (
                            "Preserve também parâmetros, custos, datas de separação, "
                            "referência e origem dos dados como contexto. Nem tudo o que falta"
                            " cabe no arquivo de operações. MEASURED identifica cálculos com "
                            "os arquivos, DECLARED suas contribuições e NOT_MEASURED o que não"
                            " pôde ser avaliado."
                        ),
                        (
                            "QuantConnect: baixe Trades em CSV, não Orders. No backtesting.py "
                            "exporte stats._trades.to_csv('trades.csv'); no vectorbt, "
                            "pf.trades.records_readable.to_csv('trades.csv'). Se houver várias"
                            " colunas de estratégias, identifique a selecionada e declare as "
                            "outras variantes. Os guias vinculados explicam cada formato."
                        ),
                    ],
                },
                {
                    "heading": "Comece pelos números que você já tem",
                    "paragraphs": [
                        (
                            "O leitor de números e a calculadora de sorte não exigem conta. "
                            "Eles exploram declarações e suposições; não atribuem uma classe "
                            "de auditoria. Para examinar o arquivo e suas lacunas, o primeiro "
                            "relatório completo é grátis com conta. A revisão descreve "
                            "evidência histórica e não decide uma operação por você."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Basta con que la curva siga subiendo?",
                    "a": (
                        "No. Conserva operaciones y contexto para revisar las seis "
                        "comprobaciones. Una captura del saldo no contiene las variantes "
                        "descartadas ni la separación temporal de la investigación."
                    ),
                }
            ],
            "en": [
                {
                    "q": "Is a rising curve enough?",
                    "a": (
                        "No. Preserve trades and context for all six checks. A balance "
                        "screenshot contains neither the discarded variants nor the "
                        "research's time separation."
                    ),
                }
            ],
            "pt": [
                {
                    "q": "Uma curva que continua subindo basta?",
                    "a": (
                        "Não. Preserve operações e contexto para as seis checagens. Uma "
                        "captura do saldo não contém as variantes descartadas nem a "
                        "separação temporal da pesquisa."
                    ),
                }
            ],
        },
        "related": [
            {"kind": "reading"},
            {"kind": "calculator"},
            {"kind": "guide", "slug": "mt4"},
            {"kind": "guide", "slug": "mt5"},
            {"kind": "guide", "slug": "mt5-optimization"},
            {"kind": "guide", "slug": "tradingview"},
            {"kind": "guide", "slug": "ninjatrader"},
            {"kind": "guide", "slug": "quantconnect"},
            {"kind": "guide", "slug": "backtesting-py"},
            {"kind": "guide", "slug": "vectorbt"},
            {"kind": "guide", "slug": "csv-universal"},
            {"kind": "guide", "slug": "myfxbook"},
            {"kind": "guide", "slug": "fxblue"},
            {"kind": "article", "key": "sharpe-deflactado-track-record"},
        ],
    },
)

ARTICLES_DATA += (
    {
        "key": "cuantas-operaciones-porcentaje-aciertos",
        "slug": {
            "es": "cuantas-operaciones-porcentaje-aciertos",
            "en": "how-many-trades-to-trust-a-win-rate",
            "pt": "quantas-operacoes-taxa-de-acerto",
        },
        "title": {
            "es": "Cuántas operaciones para fiarse de los aciertos",
            "en": "How many trades to trust a win rate?",
            "pt": "Quantas operações para confiar na taxa de acerto?",
        },
        "summary": {
            "es": (
                "Compara intervalos Wilson según operaciones y porcentaje de "
                "aciertos. Tabla calculada, supuestos y efecto de elegir la mejor "
                "configuración."
            ),
            "en": (
                "Compare Wilson intervals by trade count and win rate. A "
                "calculated table, its assumptions and the effect of selecting the"
                " best configuration."
            ),
            "pt": (
                "Compare intervalos Wilson por operações e taxa de acerto. Tabela "
                "calculada, suposições e efeito de escolher a melhor configuração."
            ),
        },
        "intro": {
            "es": (
                "No existe un número de operaciones que convierta un porcentaje en"
                " una respuesta definitiva. La pregunta útil es cuánto margen de "
                "incertidumbre toleras, qué población representan esas operaciones"
                " y cómo elegiste la regla. Wilson permite expresar esa "
                "incertidumbre sin tratar el porcentaje observado como si fuera "
                "exacto."
            ),
            "en": (
                "There is no trade count that turns a percentage into a definitive"
                " answer. The useful questions are how much uncertainty you can "
                "tolerate, what population those trades represent and how you "
                "chose the rule. Wilson expresses that uncertainty without "
                "treating the observed percentage as exact."
            ),
            "pt": (
                "Não existe um número de operações que transforme uma porcentagem "
                "em resposta definitiva. As perguntas úteis são quanta incerteza "
                "você tolera, que população essas operações representam e como "
                "escolheu a regra. Wilson expressa essa incerteza sem tratar a "
                "porcentagem observada como exata."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Qué dice el intervalo de Wilson",
                    "paragraphs": [
                        (
                            "El intervalo rodea la tasa estimada con un margen que se reduce "
                            "al aumentar la muestra. Wilson también desplaza su centro "
                            "respecto del porcentaje observado, sobre todo en muestras "
                            "pequeñas o tasas extremas. No es simplemente sumar y restar el "
                            "mismo margen al porcentaje publicado."
                        ),
                        (
                            "DECLARED · La tabla usa un nivel de confianza del 95 %. Bajo el "
                            "modelo de operaciones independientes con una probabilidad de "
                            "acierto estable, el procedimiento cubriría esa probabilidad en "
                            "aproximadamente el 95 % de muchas muestras repetidas. No atribuye"
                            " esa probabilidad a un resultado futuro ni sustituye la revisión "
                            "del proceso de selección."
                        ),
                    ],
                },
                {
                    "heading": "Cómo se calculó la tabla",
                    "paragraphs": [
                        (
                            "DECLARED · Todas las celdas se calculan al generar el artículo "
                            "con la misma función Wilson del lector de cifras de Rigor: 20, "
                            "45, 100, 300 y 1.000 operaciones, con tasas declaradas de 55 %, "
                            "60 % y 71 %. Son ejemplos matemáticos, no mediciones de un "
                            "historial."
                        ),
                        (
                            "El lector utiliza la proporción declarada sin reconstruir una "
                            "cantidad entera de aciertos. Algunas combinaciones de la tabla no"
                            " corresponden a un conteo entero: representan porcentajes "
                            "ilustrativos o redondeados. Para analizar un archivo, conserva el"
                            " conteo original, las operaciones y las reglas con que se "
                            "clasificaron."
                        ),
                    ],
                },
                {
                    "heading": "Cómo leer una fila sin convertirla en una meta",
                    "paragraphs": [
                        (
                            "DECLARED · Con 45 operaciones al 71 %, el intervalo calculado es "
                            f"{win_rate_interval(0.71, 45, 'es')}. Con 1.000 operaciones al "
                            f"mismo porcentaje es {win_rate_interval(0.71, 1000, 'es')}. El "
                            "intervalo se estrecha bajo los mismos supuestos; no demuestra que"
                            " la estrategia conserve esa tasa cuando cambien las condiciones."
                        ),
                        (
                            "Elige la precisión que necesitas antes de seguir acumulando "
                            "datos. Consultar el intervalo después de cada operación y "
                            "detenerte cuando parece favorable introduce otra selección que "
                            "esta tabla no corrige. Decide por adelantado cuándo revisar, qué "
                            "reglas permanecen fijas y qué harás si el resultado es "
                            "inconcluso."
                        ),
                    ],
                },
                {
                    "heading": "La mejor de muchas configuraciones cambia la lectura",
                    "paragraphs": [
                        (
                            "DECLARED · Supón que publicas la mejor de 100 configuraciones "
                            "probadas sobre el mismo historial. La elección favorece "
                            "porcentajes que recibieron una desviación favorable por azar. Es "
                            "un supuesto de búsqueda, no una medición de cuántas variantes se "
                            "probaron realmente."
                        ),
                        (
                            "Manteniendo la tasa y el número de operaciones, Wilson devuelve "
                            "los mismos extremos: no desplaza automáticamente el intervalo por"
                            " haber seleccionado la mejor variante. Lo que cambia es su "
                            "interpretación. La cobertura nominal para una regla fijada "
                            "previamente no se traslada sin más a una regla elegida después de"
                            " comparar resultados."
                        ),
                        (
                            "Declara la búsqueda, conserva las variantes descartadas y reserva"
                            " datos que no participen en la elección. La calculadora de suerte"
                            " explora la selección mediante Sharpe; no es una corrección del "
                            "intervalo Wilson ni convierte un porcentaje seleccionado en "
                            "evidencia independiente."
                        ),
                    ],
                },
                {
                    "heading": "Más operaciones no resuelven toda la incertidumbre",
                    "paragraphs": [
                        (
                            "Operaciones solapadas, señales compartidas y periodos de mercado "
                            "concentrados pueden reducir la información independiente. La "
                            "tabla no ajusta por dependencia ni por cambios de régimen. "
                            "Dividir una misma posición en entradas pequeñas no equivale a "
                            "reunir nuevas observaciones independientes."
                        ),
                        (
                            "La tasa de aciertos tampoco mide el tamaño de pérdidas y "
                            "aciertos, costos, caídas o exposición. Examina esos aspectos por "
                            "separado. Un intervalo estrecho puede describir con precisión una"
                            " cifra que no responde a la pregunta económica que quieres "
                            "estudiar."
                        ),
                    ],
                },
                {
                    "heading": "Reproduce el ejemplo en el lector",
                    "paragraphs": [
                        (
                            "DECLARED · El enlace de ejemplo abre el lector con 45 "
                            "operaciones, 71 % de aciertos, Sharpe anual de "
                            f"{_num(LUCK_EXAMPLE_INPUT.sharpe, 'es', 1)}, 3 años y 100 "
                            "configuraciones. Los campos de Sharpe, años e intentos sirven "
                            "para la lectura de suerte; no cambian Wilson. Son entradas "
                            "ilustrativas, no datos medidos."
                        ),
                        (
                            "Abre el ejemplo en el lector de cifras enlazado y cambia "
                            "operaciones y porcentaje para ver cómo se mueve el intervalo bajo "
                            "estos supuestos."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "What the Wilson interval says",
                    "paragraphs": [
                        (
                            "The interval surrounds the estimated rate with a margin that "
                            "shrinks as the sample grows. Wilson also moves its centre "
                            "relative to the observed percentage, especially for small samples"
                            " or extreme rates. It is not simply adding and subtracting the "
                            "same margin from the published percentage."
                        ),
                        (
                            "DECLARED · The table uses a 95 % confidence level. Under a model "
                            "of independent trades with a stable win probability, the "
                            "procedure would cover that probability in approximately 95 % of "
                            "many repeated samples. It does not assign that probability to a "
                            "future outcome or replace a review of the selection process."
                        ),
                    ],
                },
                {
                    "heading": "How the table was calculated",
                    "paragraphs": [
                        (
                            "DECLARED · Every cell is calculated when generating the article "
                            "with the same Wilson function used by Rigor's figure reader: 20, "
                            "45, 100, 300 and 1,000 trades, with declared rates of 55 %, 60 % "
                            "and 71 %. These are mathematical examples, not measurements of a "
                            "track record."
                        ),
                        (
                            "The reader uses the declared proportion without reconstructing an"
                            " integer win count. Some table combinations do not correspond to "
                            "a whole number of wins: they represent illustrative or rounded "
                            "percentages. When analysing a file, preserve the original counts,"
                            " trades and rules used to classify them."
                        ),
                    ],
                },
                {
                    "heading": "How to read a row without turning it into a target",
                    "paragraphs": [
                        (
                            "DECLARED · With 45 trades at 71 %, the calculated interval is "
                            f"{win_rate_interval(0.71, 45, 'en')}. With 1,000 trades at the "
                            f"same percentage it is {win_rate_interval(0.71, 1000, 'en')}. The "
                            "interval narrows under the same assumptions; it does not "
                            "demonstrate that the strategy will retain that rate when "
                            "conditions change."
                        ),
                        (
                            "Choose the precision you need before accumulating more data. "
                            "Checking the interval after every trade and stopping when it "
                            "looks favourable introduces another selection that this table "
                            "does not correct. Decide in advance when to review, which rules "
                            "stay fixed and what to do if the result is inconclusive."
                        ),
                    ],
                },
                {
                    "heading": "The best of many configurations changes the reading",
                    "paragraphs": [
                        (
                            "DECLARED · Suppose you publish the best of 100 configurations "
                            "tried on the same history. Selection favours percentages that "
                            "received a favourable random deviation. This is a search "
                            "assumption, not a measurement of how many variants were actually "
                            "tried."
                        ),
                        (
                            "Holding the rate and trade count fixed, Wilson returns the same "
                            "endpoints: it does not automatically shift the interval because "
                            "the best variant was selected. What changes is its "
                            "interpretation. Nominal coverage for a rule fixed beforehand does"
                            " not simply transfer to a rule chosen after comparing results."
                        ),
                        (
                            "Declare the search, keep discarded variants and reserve data that"
                            " played no part in selection. The luck calculator explores "
                            "selection through Sharpe; it does not correct the Wilson interval"
                            " or turn a selected percentage into independent evidence."
                        ),
                    ],
                },
                {
                    "heading": "More trades do not resolve every uncertainty",
                    "paragraphs": [
                        (
                            "Overlapping trades, shared signals and concentrated market "
                            "periods can reduce independent information. The table does not "
                            "adjust for dependence or regime changes. Splitting one position "
                            "into smaller entries is not equivalent to collecting new "
                            "independent observations."
                        ),
                        (
                            "Win rate also does not measure the size of wins and losses, "
                            "costs, drawdowns or exposure. Examine these separately. A narrow "
                            "interval can precisely describe a figure that does not answer the"
                            " economic question you want to study."
                        ),
                    ],
                },
                {
                    "heading": "Reproduce the example in the reader",
                    "paragraphs": [
                        (
                            "DECLARED · The example link opens the reader with 45 trades, a 71"
                            " % win rate, annual Sharpe of "
                            f"{_num(LUCK_EXAMPLE_INPUT.sharpe, 'en', 1)}, 3 years and 100 "
                            "configurations. Sharpe, years and trial count feed the luck "
                            "reading; they do not change Wilson. These are illustrative "
                            "inputs, not measured data."
                        ),
                        (
                            "Open the example in the linked figure reader and change the trade "
                            "count and win rate to see how the interval moves under these "
                            "assumptions."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "O que diz o intervalo de Wilson",
                    "paragraphs": [
                        (
                            "O intervalo cerca a taxa estimada com uma margem que diminui "
                            "conforme a amostra cresce. Wilson também desloca seu centro em "
                            "relação à porcentagem observada, sobretudo em amostras pequenas "
                            "ou taxas extremas. Não é simplesmente somar e subtrair a mesma "
                            "margem da porcentagem publicada."
                        ),
                        (
                            "DECLARED · A tabela usa um nível de confiança de 95 %. Sob um "
                            "modelo de operações independentes com probabilidade de acerto "
                            "estável, o procedimento cobriria essa probabilidade em "
                            "aproximadamente 95 % de muitas amostras repetidas. Ele não "
                            "atribui essa probabilidade a um resultado futuro nem substitui a "
                            "revisão do processo de seleção."
                        ),
                    ],
                },
                {
                    "heading": "Como a tabela foi calculada",
                    "paragraphs": [
                        (
                            "DECLARED · Todas as células são calculadas ao gerar o artigo com "
                            "a mesma função Wilson do leitor de números do Rigor: 20, 45, 100,"
                            " 300 e 1.000 operações, com taxas declaradas de 55 %, 60 % e 71 "
                            "%. São exemplos matemáticos, não medições de um histórico."
                        ),
                        (
                            "O leitor usa a proporção declarada sem reconstruir uma quantidade"
                            " inteira de acertos. Algumas combinações da tabela não "
                            "correspondem a uma contagem inteira: representam porcentagens "
                            "ilustrativas ou arredondadas. Ao analisar um arquivo, preserve a "
                            "contagem original, as operações e as regras usadas para "
                            "classificá-las."
                        ),
                    ],
                },
                {
                    "heading": "Como ler uma linha sem transformá-la em meta",
                    "paragraphs": [
                        (
                            "DECLARED · Com 45 operações a 71 %, o intervalo calculado é "
                            f"{win_rate_interval(0.71, 45, 'pt')}. Com 1.000 operações à mesma "
                            f"porcentagem, ele é {win_rate_interval(0.71, 1000, 'pt')}. O "
                            "intervalo fica mais estreito sob as mesmas suposições; isso não "
                            "demonstra que a estratégia conservará a taxa quando as condições "
                            "mudarem."
                        ),
                        (
                            "Escolha a precisão necessária antes de acumular mais dados. "
                            "Consultar o intervalo após cada operação e parar quando parece "
                            "favorável introduz outra seleção que esta tabela não corrige. "
                            "Decida antecipadamente quando revisar, quais regras permanecem "
                            "fixas e o que fazer se o resultado for inconclusivo."
                        ),
                    ],
                },
                {
                    "heading": "A melhor de muitas configurações muda a leitura",
                    "paragraphs": [
                        (
                            "DECLARED · Suponha que você publique a melhor de 100 "
                            "configurações testadas no mesmo histórico. A escolha favorece "
                            "porcentagens que receberam um desvio favorável por acaso. É uma "
                            "suposição de busca, não uma medição de quantas variantes foram "
                            "realmente testadas."
                        ),
                        (
                            "Mantendo a taxa e o número de operações, Wilson retorna os mesmos"
                            " limites: ele não desloca automaticamente o intervalo porque a "
                            "melhor variante foi selecionada. O que muda é a interpretação. A "
                            "cobertura nominal para uma regra fixada previamente não se "
                            "transfere simplesmente para uma regra escolhida após comparar "
                            "resultados."
                        ),
                        (
                            "Declare a busca, guarde as variantes descartadas e reserve dados "
                            "que não participaram da escolha. A calculadora de sorte explora a"
                            " seleção por meio do Sharpe; ela não corrige o intervalo Wilson "
                            "nem transforma uma porcentagem selecionada em evidência "
                            "independente."
                        ),
                    ],
                },
                {
                    "heading": "Mais operações não resolvem toda a incerteza",
                    "paragraphs": [
                        (
                            "Operações sobrepostas, sinais compartilhados e períodos de "
                            "mercado concentrados podem reduzir a informação independente. A "
                            "tabela não ajusta dependência nem mudanças de regime. Dividir a "
                            "mesma posição em entradas menores não equivale a reunir novas "
                            "observações independentes."
                        ),
                        (
                            "A taxa de acerto também não mede o tamanho das perdas e acertos, "
                            "custos, quedas ou exposição. Examine esses aspectos "
                            "separadamente. Um intervalo estreito pode descrever com precisão "
                            "um número que não responde à pergunta econômica que você quer "
                            "estudar."
                        ),
                    ],
                },
                {
                    "heading": "Reproduza o exemplo no leitor",
                    "paragraphs": [
                        (
                            "DECLARED · O link de exemplo abre o leitor com 45 operações, 71 %"
                            " de acertos, Sharpe anual de "
                            f"{_num(LUCK_EXAMPLE_INPUT.sharpe, 'pt', 1)}, 3 anos e 100 "
                            "configurações. Os "
                            "campos de Sharpe, anos e tentativas alimentam a leitura de sorte;"
                            " não alteram Wilson. São entradas ilustrativas, não dados "
                            "medidos."
                        ),
                        (
                            "Abra o exemplo no leitor de números vinculado e altere operações "
                            "e porcentagem para ver como o intervalo se move sob essas "
                            "suposições."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Una muestra grande elimina el sesgo de selección?",
                    "a": (
                        "No. La tabla describe incertidumbre bajo sus supuestos. La "
                        "dependencia entre operaciones, la selección de variantes y los "
                        "cambios de mercado necesitan una revisión propia, aunque el "
                        "intervalo sea estrecho."
                    ),
                }
            ],
            "en": [
                {
                    "q": "Does a large sample eliminate selection bias?",
                    "a": (
                        "No. The table describes uncertainty under its assumptions. Trade "
                        "dependence, variant selection and changing markets need their own"
                        " review, even when the interval is narrow."
                    ),
                }
            ],
            "pt": [
                {
                    "q": "Uma amostra grande elimina o viés de seleção?",
                    "a": (
                        "Não. A tabela descreve incerteza sob suas suposições. Dependência"
                        " entre operações, seleção de variantes e mudanças de mercado "
                        "precisam de revisão própria, mesmo com um intervalo estreito."
                    ),
                }
            ],
        },
        "related": [
            {"kind": "winrate"},
            {"kind": "reading"},
            {"kind": "reading", "example": "win-rate"},
            {"kind": "calculator"},
            {"kind": "guide", "slug": "csv-universal"},
            {"kind": "guide", "slug": "mt5"},
        ],
    },
)

ARTICLES_DATA += (
    {
        "key": "lo-eligio-el-optimizador",
        "slug": {
            "es": "lo-eligio-el-optimizador",
            "en": "did-the-optimizer-pick-your-result",
            "pt": "o-otimizador-escolheu-o-resultado",
        },
        "title": {
            "es": "¿El resultado lo eligió el optimizador?",
            "en": "Did the optimiser pick your result?",
            "pt": "O otimizador escolheu o seu resultado?",
        },
        "summary": {
            "es": (
                "Cuenta las configuraciones probadas, exporta las pasadas de MT5 y"
                " entiende cómo el Sharpe deflactado influye en la clase del "
                "informe."
            ),
            "en": (
                "Count the configurations tried, export MT5 passes and understand "
                "how deflated Sharpe affects the report's class."
            ),
            "pt": (
                "Conte as configurações testadas, exporte as passadas do MT5 e "
                "entenda como o Sharpe deflacionado influencia a classe do "
                "relatório."
            ),
        },
        "intro": {
            "es": (
                "El informe de la configuración elegida cuenta cómo terminó esa "
                "prueba. Para saber cuánto influyó la selección, necesitas también"
                " el recorrido que la precedió. Reúne las pasadas, el criterio "
                "usado para ordenarlas y las variantes que probaste fuera del "
                "optimizador. Después compara el Sharpe con una referencia que "
                "tenga en cuenta esa búsqueda."
            ),
            "en": (
                "The chosen configuration's report tells you how that test ended. "
                "To examine the influence of selection, you also need the search "
                "that preceded it. Collect the passes, the criterion used to rank "
                "them and variants tested outside the optimiser. Then compare "
                "Sharpe with a reference that takes that search into account."
            ),
            "pt": (
                "O relatório da configuração escolhida mostra como aquele teste "
                "terminou. Para examinar a influência da seleção, você também "
                "precisa do percurso anterior. Reúna as passadas, o critério usado"
                " para ordená-las e as variantes testadas fora do otimizador. "
                "Depois compare o Sharpe com uma referência que considere essa "
                "busca."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Reconstruye qué se pudo elegir",
                    "paragraphs": [
                        (
                            "Una configuración es una combinación de decisiones que llegó a "
                            "evaluarse: parámetros, reglas de entrada y salida, mercado, "
                            "horario o periodo. Si miraste el resultado para elegir entre "
                            "alternativas, esa comparación forma parte de la búsqueda. Cuenta "
                            "también los ajustes manuales y las ejecuciones anteriores que "
                            "influyeron en la selección final; el nombre del archivo no resume"
                            " el recorrido."
                        ),
                        (
                            "Conserva un registro de las alternativas, sus fechas y el "
                            "criterio de elección. Las combinaciones que nunca ejecutaste no "
                            "son pasadas observadas. Si la búsqueda fue genética, el espacio "
                            "teórico de combinaciones y las pasadas ejecutadas son cantidades "
                            "distintas. Si faltan registros, identifica el alcance de la "
                            "cuenta disponible y declara los intentos adicionales conocidos."
                        ),
                    ],
                },
                {
                    "heading": "Lee el Sharpe junto a la selección",
                    "paragraphs": [
                        (
                            "Elegir el mayor resultado de una búsqueda favorece valores "
                            "elevados por fluctuación. El Sharpe deflactado compara el Sharpe "
                            "observado con una referencia que aumenta al considerar más "
                            "intentos. En el informe utiliza la longitud del historial, la "
                            "asimetría y las colas de los rendimientos. No responde a la "
                            "probabilidad de obtener un resultado futuro ni identifica por sí "
                            "solo la causa de una curva."
                        ),
                        (
                            "La calculadora pública permite explorar la referencia de suerte "
                            "con cifras declaradas. Sus supuestos de frecuencia, colas "
                            "normales y ausencia de asimetría simplifican el problema. "
                            "Configuraciones cercanas pueden estar correlacionadas; esa "
                            "dependencia limita la interpretación y no justifica borrar "
                            "variantes del registro. Con los archivos, el informe puede "
                            "examinar información que una cifra de Sharpe aislada no contiene."
                        ),
                        (
                            "Consulta el ejemplo de suerte y sus límites en el artículo "
                            "enlazado sobre el Sharpe deflactado."
                        ),
                    ],
                },
                {
                    "heading": "Exporta las pasadas completas de MT5",
                    "paragraphs": [
                        (
                            "Al terminar la optimización, abre Resultados de optimización en "
                            "el Probador de estrategias. Haz clic derecho en la tabla y elige "
                            "Exportar a XML (MS Office Excel). Conserva el XML de Excel 2003 "
                            "con todas las pasadas, incluidas las que descartaste. La guía de "
                            "exportación enlazada explica el archivo y el campo donde subirlo."
                        ),
                        (
                            "Ejecuta después una prueba simple con los parámetros elegidos y "
                            "guarda su informe HTML. Sube el XML en «Exportación de "
                            "optimización de MT5», dentro de «Añadir más archivos», junto con "
                            "el HTML en «Informe de tu plataforma». El XML contiene resúmenes "
                            "por pasada, no las operaciones del resultado seleccionado: los "
                            "archivos aportan piezas diferentes."
                        ),
                    ],
                },
                {
                    "heading": "Distingue lo declarado de lo contado",
                    "paragraphs": [
                        (
                            "DECLARED identifica el número de intentos que escribes. MEASURED "
                            "identifica los que cuentan los archivos: pasadas del XML, "
                            "columnas de una matriz de variantes o variantes presentes en un "
                            "informe. Rigor usa la mayor cuenta disponible entre la "
                            "declaración y esos archivos; una declaración menor no reduce el "
                            "número documentado. El alcance sigue limitado a lo aportado."
                        ),
                        (
                            "NOT_MEASURED identifica la falta de una cuenta cuando no la "
                            "declaras ni aparece en los archivos. En ese caso el cálculo asume"
                            " un solo intento, el caso más favorable, y muestra la limitación."
                            " No confunde ese supuesto con una búsqueda medida. Si probaste "
                            "variantes fuera del XML, añádelas a la declaración y conserva el "
                            "registro que explica el total."
                        ),
                    ],
                },
                {
                    "heading": "Qué puede cambiar en la clase",
                    "paragraphs": [
                        (
                            "Con la cuenta ausente, una multiplicidad que parece suficiente "
                            "bajo el supuesto más favorable sigue como NOT_MEASURED y la clase"
                            " no puede superar B. Declarar la cuenta elimina esa ausencia "
                            "concreta, pero puede reducir el Sharpe deflactado. No existe una "
                            "subida automática de clase por completar el campo o añadir el "
                            "XML."
                        ),
                        (
                            "Si la multiplicidad queda débil o falla, la clase resulta C salvo"
                            " que otras condiciones exijan D. Llegar a A exige además "
                            "satisfacer las reglas de significancia, costos, fuera de muestra,"
                            " calidad de datos y referencia. El método enlazado explica el "
                            "conjunto. La clase resume la evidencia aportada y sus límites; no"
                            " describe resultados futuros."
                        ),
                    ],
                },
                {
                    "heading": "Conserva las pasadas y el informe",
                    "paragraphs": [
                        (
                            "Sigue la guía enlazada para exportar el XML de optimización de "
                            "MetaTrader 5 y conserva todas las pasadas junto al informe de la "
                            "configuración elegida."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "Reconstruct what could be selected",
                    "paragraphs": [
                        (
                            "A configuration is a combination of decisions that was evaluated:"
                            " parameters, entry and exit rules, market, trading hours or "
                            "period. If you inspected the result to choose between "
                            "alternatives, that comparison belongs to the search. Count manual"
                            " changes and earlier runs that influenced the final selection "
                            "too; a filename does not describe that process."
                        ),
                        (
                            "Keep a record of alternatives, dates and the selection criterion."
                            " Combinations never executed are not observed passes. In a "
                            "genetic search, the theoretical space of combinations and the "
                            "passes actually executed are different quantities. If records are"
                            " missing, identify the scope of the available count and declare "
                            "additional attempts you know about."
                        ),
                    ],
                },
                {
                    "heading": "Read Sharpe alongside the selection process",
                    "paragraphs": [
                        (
                            "Selecting the highest result from a search favours values lifted "
                            "by fluctuation. Deflated Sharpe compares the observed Sharpe with"
                            " a reference that rises as more attempts are considered. In the "
                            "report it uses history length, return skewness and tails. It does"
                            " not describe the probability of a future outcome or identify the"
                            " cause of a curve on its own."
                        ),
                        (
                            "The public calculator lets you explore the luck reference with "
                            "declared figures. Its assumptions about frequency, normal tails "
                            "and no skew simplify the problem. Nearby configurations may be "
                            "correlated; that dependence limits interpretation and does not "
                            "justify deleting variants from the record. With the files, the "
                            "report can examine information that a standalone Sharpe figure "
                            "lacks."
                        ),
                        (
                            "See the luck example and its limits in the linked article on "
                            "deflated Sharpe."
                        ),
                    ],
                },
                {
                    "heading": "Export the complete MT5 passes",
                    "paragraphs": [
                        (
                            "When optimisation finishes, open Optimization Results in the "
                            "Strategy Tester. Right-click the table and choose Export to XML "
                            "(MS Office Excel). Keep the Excel 2003 XML with all passes, "
                            "including the ones you discarded. The linked export guide "
                            "explains the file and its upload field."
                        ),
                        (
                            "Then run a single test with the chosen parameters and save its "
                            "HTML report. Upload the XML under 'MT5 optimisation export', "
                            "inside 'Add more files', alongside the HTML under 'Your platform "
                            "report'. The XML contains summaries per pass, not the selected "
                            "result's trades: the files supply different pieces of evidence."
                        ),
                    ],
                },
                {
                    "heading": "Separate declared counts from file counts",
                    "paragraphs": [
                        (
                            "DECLARED identifies the attempt count you enter. MEASURED "
                            "identifies counts from files: XML passes, columns in a variants "
                            "matrix or variants present in a report. Rigor uses the largest "
                            "available count across the declaration and those files; a lower "
                            "declaration cannot reduce the documented count. Its scope still "
                            "depends on what you provide."
                        ),
                        (
                            "NOT_MEASURED identifies a missing count when neither your "
                            "declaration nor the files supplies one. The calculation then "
                            "assumes a single attempt, the most favourable case, and shows the "
                            "limitation. It does not treat that assumption as a measured "
                            "search. If you tested variants outside the XML, include them in "
                            "your declaration and keep the record explaining the total."
                        ),
                    ],
                },
                {
                    "heading": "What can change in the class",
                    "paragraphs": [
                        (
                            "With no count, multiplicity that looks sufficient under the most "
                            "favourable assumption stays NOT_MEASURED and the class cannot "
                            "exceed B. Declaring the count removes that particular gap, but "
                            "may reduce deflated Sharpe. Completing the field or adding the "
                            "XML does not automatically raise the class."
                        ),
                        (
                            "If multiplicity is weak or fails, the class is C unless other "
                            "conditions require D. Reaching A also requires satisfying the "
                            "rules for significance, costs, out-of-sample evidence, data "
                            "quality and the benchmark. The linked method explains the "
                            "combined rules. The class summarises the supplied evidence and "
                            "its limits; it does not describe future results."
                        ),
                    ],
                },
                {
                    "heading": "Keep the passes and the report",
                    "paragraphs": [
                        (
                            "Follow the linked guide to exporting the MetaTrader 5 optimisation"
                            " XML and keep every pass alongside the chosen configuration's "
                            "report."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Reconstrua o que podia ser escolhido",
                    "paragraphs": [
                        (
                            "Uma configuração é uma combinação de decisões que chegou a ser "
                            "avaliada: parâmetros, regras de entrada e saída, mercado, horário"
                            " ou período. Se você examinou o resultado para escolher entre "
                            "alternativas, essa comparação faz parte da busca. Conte também os"
                            " ajustes manuais e as execuções anteriores que influenciaram a "
                            "seleção final; o nome do arquivo não resume o percurso."
                        ),
                        (
                            "Mantenha um registro das alternativas, datas e critério de "
                            "escolha. Combinações nunca executadas não são passadas "
                            "observadas. Numa busca genética, o espaço teórico de combinações "
                            "e as passadas executadas são quantidades diferentes. Se faltam "
                            "registros, identifique o alcance da contagem disponível e declare"
                            " as tentativas adicionais conhecidas."
                        ),
                    ],
                },
                {
                    "heading": "Leia o Sharpe junto com o processo de seleção",
                    "paragraphs": [
                        (
                            "Escolher o maior resultado de uma busca favorece valores elevados"
                            " por flutuação. O Sharpe deflacionado compara o Sharpe observado "
                            "com uma referência que sobe ao considerar mais tentativas. No "
                            "relatório, usa a duração do histórico, a assimetria e as caudas "
                            "dos retornos. Não descreve a probabilidade de um resultado futuro"
                            " nem identifica sozinho a causa de uma curva."
                        ),
                        (
                            "A calculadora pública permite explorar a referência de sorte com "
                            "números declarados. Suas suposições de frequência, caudas normais"
                            " e ausência de assimetria simplificam o problema. Configurações "
                            "próximas podem estar correlacionadas; essa dependência limita a "
                            "interpretação e não justifica apagar variantes do registro. Com "
                            "os arquivos, o relatório pode examinar informações que um Sharpe "
                            "isolado não contém."
                        ),
                        (
                            "Consulte o exemplo de sorte e seus limites no artigo vinculado "
                            "sobre o Sharpe deflacionado."
                        ),
                    ],
                },
                {
                    "heading": "Exporte todas as passadas do MT5",
                    "paragraphs": [
                        (
                            "Quando a otimização terminar, abra Optimization Results no "
                            "Strategy Tester. Clique com o botão direito na tabela e escolha "
                            "Export to XML (MS Office Excel). Guarde o XML do Excel 2003 com "
                            "todas as passadas, inclusive as descartadas. O guia de exportação"
                            " relacionado explica o arquivo e o campo de envio."
                        ),
                        (
                            "Depois execute um teste único com os parâmetros escolhidos e "
                            "salve seu relatório HTML. Envie o XML em 'Exportação de "
                            "otimização do MT5', dentro de 'Adicionar mais arquivos', junto "
                            "com o HTML em 'Relatório da sua plataforma'. O XML contém resumos"
                            " por passada, não as operações do resultado selecionado: os "
                            "arquivos fornecem evidências diferentes."
                        ),
                    ],
                },
                {
                    "heading": "Distinga o declarado do contado nos arquivos",
                    "paragraphs": [
                        (
                            "DECLARED identifica a quantidade de tentativas que você informa. "
                            "MEASURED identifica o que os arquivos contam: passadas do XML, "
                            "colunas de uma matriz de variantes ou variantes presentes num "
                            "relatório. O Rigor usa a maior contagem disponível entre a "
                            "declaração e esses arquivos; uma declaração menor não reduz a "
                            "quantidade documentada. O alcance continua limitado ao material "
                            "fornecido."
                        ),
                        (
                            "NOT_MEASURED identifica a ausência de contagem quando você não a "
                            "declara e ela não aparece nos arquivos. Nesse caso, o cálculo "
                            "supõe uma única tentativa, o caso mais favorável, e mostra a "
                            "limitação. Não trata essa suposição como busca medida. Se testou "
                            "variantes fora do XML, inclua-as na declaração e guarde o "
                            "registro que explica o total."
                        ),
                    ],
                },
                {
                    "heading": "O que pode mudar na classe",
                    "paragraphs": [
                        (
                            "Sem a contagem, uma multiplicidade que parece suficiente sob a "
                            "suposição mais favorável continua como NOT_MEASURED e a classe "
                            "não pode superar B. Declarar a quantidade elimina essa ausência "
                            "específica, mas pode reduzir o Sharpe deflacionado. Preencher o "
                            "campo ou adicionar o XML não eleva automaticamente a classe."
                        ),
                        (
                            "Se a multiplicidade fica fraca ou falha, a classe é C, salvo se "
                            "outras condições exigirem D. Chegar a A também exige satisfazer "
                            "as regras de significância, custos, fora da amostra, qualidade "
                            "dos dados e referência. O método relacionado explica o conjunto. "
                            "A classe resume a evidência fornecida e seus limites; não "
                            "descreve resultados futuros."
                        ),
                    ],
                },
                {
                    "heading": "Preserve as passadas e o relatório",
                    "paragraphs": [
                        (
                            "Siga o guia vinculado para exportar o XML de otimização do "
                            "MetaTrader 5 e preserve todas as passadas junto ao relatório da "
                            "configuração escolhida."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿El XML permite calcular todo el sobreajuste?",
                    "a": (
                        "No. Cuenta las pasadas incluidas, pero sus resúmenes no contienen"
                        " series alineadas de cada variante. Para calcular PBO hace falta "
                        "una matriz de rendimientos de variantes; el XML no la sustituye. "
                        "Tampoco reconstruye búsquedas que no aportaste."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Does the XML measure every aspect of overfitting?",
                    "a": (
                        "No. It counts included passes, but its summaries do not contain "
                        "aligned series for every variant. Computing PBO requires a matrix"
                        " of variant returns; the XML does not replace it. Nor can it "
                        "reconstruct searches you did not supply."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "O XML mede todos os aspectos do sobreajuste?",
                    "a": (
                        "Não. Conta as passadas incluídas, mas seus resumos não contêm "
                        "séries alinhadas de cada variante. Calcular PBO exige uma matriz "
                        "de retornos das variantes; o XML não a substitui. Também não "
                        "reconstrói buscas que você não forneceu."
                    ),
                },
            ],
        },
        "related": [
            {"kind": "reading"},
            {"kind": "calculator"},
            {"kind": "guide", "slug": "mt5-optimization"},
            {"kind": "guide", "slug": "mt5"},
            {"kind": "method"},
            {"kind": "article", "key": "sharpe-deflactado-track-record"},
        ],
    },
)

ARTICLES_DATA += (
    {
        "key": MONTE_CARLO_ARTICLE_KEY,
        "slug": {
            "es": "monte-carlo-backtest",
            "en": "monte-carlo-backtest-what-it-shows",
            "pt": "monte-carlo-backtest-o-que-mostra",
        },
        "title": {
            "es": "Monte Carlo de un backtest: qué te dice y qué no",
            "en": "Monte Carlo on a backtest: what it can and cannot tell you",
            "pt": "Monte Carlo de um backtest: o que mostra e o que não mostra",
        },
        "seo_title": {
            "en": "Backtest Monte Carlo: what it can and cannot tell",
            "pt": "Monte Carlo do backtest: o que mostra e o que não",
        },
        "summary": {
            "es": (
                "Qué responde un Monte Carlo de un backtest, por qué no corrige el sobreajuste y "
                "qué muestra el informe como riesgo remuestreado, con un ejemplo calculado."
            ),
            "en": (
                "What a Monte Carlo of a backtest answers, why it does not correct overfitting "
                "and what the report shows as resampled risk, with a computed example."
            ),
            "pt": (
                "O que um Monte Carlo de backtest responde, por que não corrige o sobreajuste e "
                "o que o relatório mostra como risco reamostrado, com um exemplo calculado."
            ),
        },
        "intro": {
            "es": (
                "Un Monte Carlo de un backtest reordena o remuestrea los resultados del "
                "historial miles de veces y mira cuánto cambian las caídas. Sirve para ver la "
                "dispersión del riesgo que un solo orden de operaciones esconde. No es una "
                "segunda prueba de la estrategia: trabaja con los mismos datos, con su suerte y "
                "con sus sesgos. Aquí ves qué responde, qué no responde y qué calcula el informe "
                "de Rigor, con un ejemplo sintético que se reproduce con su semilla."
            ),
            "en": (
                "A Monte Carlo of a backtest reorders or resamples the history's results "
                "thousands of times and looks at how much the falls change. It shows the spread "
                "of risk that a single order of trades hides. It is not a second test of the "
                "strategy: it works with the same data, with its luck and with its biases. Here "
                "is what it answers, what it does not answer and what Rigor's report computes, "
                "with a synthetic example you can reproduce from its seed."
            ),
            "pt": (
                "Um Monte Carlo de um backtest reordena ou reamostra os resultados do histórico "
                "milhares de vezes e observa quanto mudam as quedas. Serve para ver a dispersão "
                "do risco que uma única ordem de operações esconde. Não é um segundo teste da "
                "estratégia: trabalha com os mesmos dados, com a sua sorte e com os seus vieses. "
                "Aqui você vê o que ele responde, o que não responde e o que o relatório do "
                "Rigor calcula, com um exemplo sintético que se reproduz com a sua semente."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Qué es remuestrear operaciones o una curva",
                    "paragraphs": [
                        (
                            "Un backtest entrega una secuencia: operaciones cerradas o "
                            "rendimientos por periodo de la curva de capital. Remuestrear es "
                            "construir historias nuevas con esas mismas piezas. Barajar cambia "
                            "solo el orden y conserva cada resultado. El bootstrap sortea piezas "
                            "con reemplazo, así que una historia puede repetir unas y omitir "
                            "otras. El bootstrap estacionario sortea bloques de periodos "
                            "consecutivos, de longitud aleatoria, para conservar parte de la "
                            "dependencia entre días cercanos."
                        ),
                        (
                            "Cada método repite el sorteo miles de veces y resume lo que sale: la "
                            "caída máxima mediana, la que aparece en 1 de cada 20 historias o la "
                            "proporción de historias que cae más de un umbral. El nombre Monte "
                            "Carlo se refiere a ese uso de sorteos repetidos. No añade "
                            "información que el historial no tenga; ordena la que ya tiene."
                        ),
                    ],
                },
                {
                    "heading": "Qué responde: la dispersión si el orden es intercambiable",
                    "paragraphs": [
                        (
                            "La caída máxima de un backtest depende del orden en que llegaron las "
                            "pérdidas. Con los mismos resultados, otro orden habría dado una "
                            "caída más leve o más profunda, y una racha perdedora más corta o más "
                            "larga. Un Monte Carlo responde a esa pregunta concreta: qué rango de "
                            "caídas y rachas producen estos resultados si el orden es "
                            "intercambiable, es decir, si cualquier orden era igual de probable."
                        ),
                        (
                            "Ese supuesto marca el límite de la respuesta. Si las pérdidas "
                            "dependen del régimen de mercado, de posiciones abiertas a la vez o "
                            "de cambios de tamaño, el orden no es intercambiable y barajar lo "
                            "disimula. El bootstrap por bloques conserva la dependencia dentro de "
                            "cada bloque, pero no reconstruye regímenes que el historial no "
                            "contiene."
                        ),
                    ],
                },
                {
                    "heading": "Un ejemplo calculado con su semilla",
                    "paragraphs": list(MONTE_CARLO_EXAMPLE["es"]),
                },
                {
                    "heading": "Qué no responde: el sobreajuste y la búsqueda",
                    "paragraphs": [
                        (
                            "Un Monte Carlo no distingue un resultado con ventaja de uno elegido "
                            "por suerte entre muchos. Remuestrea lo que hay: si lo que hay es el "
                            "mejor de cien intentos, remuestrea esa suerte. Tampoco dice cómo se "
                            "comportaría la estrategia con datos que no vio, ni descuenta los "
                            "costos que el backtest omitió."
                        ),
                        (
                            "Para la búsqueda de configuraciones existe otra herramienta: el "
                            "Sharpe deflactado compara el Sharpe observado con el que darían por "
                            "azar los intentos realizados. Para el ajuste al pasado, un tramo "
                            "fuera de muestra fijado antes de mirar los resultados. El artículo "
                            "enlazado sobre el Sharpe deflactado y el de qué hacer después del "
                            "backtest explican las dos; la calculadora de suerte enlazada hace "
                            "la primera cuenta con cifras declaradas."
                        ),
                    ],
                },
                {
                    "heading": "Por qué el Monte Carlo de un backtest optimizado hereda su sesgo",
                    "paragraphs": [
                        (
                            "El optimizador elige la configuración cuyo historial salió mejor. "
                            "Por esa misma selección, el historial tiene más rachas favorables y "
                            "caídas más leves que las del proceso que lo generó. El remuestreo "
                            "parte de esos mismos rendimientos, así que sus historias heredan la "
                            "media inflada y las caídas suavizadas. Un abanico de curvas "
                            "estrecho y ascendente puede ser solo la huella de la elección."
                        ),
                        MONTE_CARLO_SEARCH_EXAMPLE["es"],
                    ],
                },
                {
                    "heading": "Qué calcula el informe de Rigor",
                    "paragraphs": [
                        MONTE_CARLO_REPORT["es"],
                        (
                            "Al lado, shuffled_drawdown compara la peor caída del archivo con la "
                            "de los mismos rendimientos en órdenes al azar, que conservan el "
                            "Sharpe, la volatilidad y el resultado final. Si la caída del "
                            "archivo es más leve que en casi todos los órdenes, las pérdidas se "
                            "siguieron menos de lo que daría el azar, como en una curva "
                            "suavizada; si es más profunda, llegaron en rachas. Con operaciones "
                            "cerradas, loss_streak_review hace la misma comparación con la racha "
                            "perdedora más larga, y el simulador de retos recorre historias "
                            "remuestreadas igual con las reglas de cada reto."
                        ),
                        (
                            "Un remuestreo sí entra en la clase: el percentil 5 del Sharpe en un "
                            "bootstrap estacionario forma parte de la prueba de azar. El riesgo "
                            "remuestreado, los órdenes al azar y las rachas son informativos y no "
                            "cambian la clase. Todos describen el historial aportado; ninguno es "
                            "una predicción."
                        ),
                    ],
                },
                {
                    "heading": "Míralo en el informe de ejemplo",
                    "paragraphs": [
                        (
                            "Abre el informe de ejemplo enlazado para ver el riesgo remuestreado "
                            "con datos sintéticos y compáralo después con el de tu propio archivo."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "What resampling trades or a curve means",
                    "paragraphs": [
                        (
                            "A backtest delivers a sequence: closed trades or per-period returns "
                            "of the equity curve. Resampling builds new histories from those same "
                            "pieces. Shuffling changes only the order and keeps every result. The "
                            "bootstrap draws pieces with replacement, so a history can repeat "
                            "some and leave out others. The stationary bootstrap draws blocks of "
                            "consecutive periods, of random length, to keep part of the "
                            "dependence between nearby days."
                        ),
                        (
                            "Each method repeats the draw thousands of times and summarises what "
                            "comes out: the median maximum drawdown, the one reached in 1 history "
                            "in 20, or the share of histories that fall further than a threshold. "
                            "The name Monte Carlo refers to that use of repeated draws. It adds no "
                            "information the history lacks; it organises what is already there."
                        ),
                    ],
                },
                {
                    "heading": "What it answers: the spread if the order is exchangeable",
                    "paragraphs": [
                        (
                            "A backtest's maximum drawdown depends on the order in which the "
                            "losses arrived. With the same results, another order would have "
                            "given a milder or a deeper fall, and a shorter or longer losing "
                            "streak. A Monte Carlo answers that specific question: what range of "
                            "falls and streaks these results produce if the order is "
                            "exchangeable, that is, if any order was equally likely."
                        ),
                        (
                            "That assumption is the limit of the answer. If losses depend on the "
                            "market regime, on positions open at the same time or on changes in "
                            "size, the order is not exchangeable and shuffling hides it. The "
                            "block bootstrap keeps the dependence inside each block, but it "
                            "cannot rebuild regimes the history does not contain."
                        ),
                    ],
                },
                {
                    "heading": "A computed example with its seed",
                    "paragraphs": list(MONTE_CARLO_EXAMPLE["en"]),
                },
                {
                    "heading": "What it does not answer: overfitting and the search",
                    "paragraphs": [
                        (
                            "A Monte Carlo cannot tell a result with an edge from one picked by "
                            "luck among many. It resamples what is there: if what is there is "
                            "the best of a hundred attempts, it resamples that luck. Nor does it "
                            "say how the strategy would behave on data it never saw, or deduct "
                            "costs the backtest left out."
                        ),
                        (
                            "The search for configurations has another tool: deflated Sharpe "
                            "compares the observed Sharpe with the one chance would give across "
                            "the attempts made. Fitting to the past calls for an out-of-sample "
                            "stretch fixed before looking at the results. The linked articles on "
                            "deflated Sharpe and on what to do after a backtest explain both; the "
                            "linked luck calculator does the first calculation with declared "
                            "figures."
                        ),
                    ],
                },
                {
                    "heading": "Why the Monte Carlo of an optimised backtest inherits its bias",
                    "paragraphs": [
                        (
                            "The optimiser picks the configuration whose history came out best. "
                            "Because of that selection, the history has more favourable streaks "
                            "and milder falls than the process that produced it. Resampling "
                            "starts from those same returns, so its histories inherit the "
                            "inflated mean and the smoothed falls. A narrow, rising fan of curves "
                            "can be nothing more than the trace of the choice."
                        ),
                        MONTE_CARLO_SEARCH_EXAMPLE["en"],
                    ],
                },
                {
                    "heading": "What Rigor's report computes",
                    "paragraphs": [
                        MONTE_CARLO_REPORT["en"],
                        (
                            "Next to it, shuffled_drawdown compares the file's worst fall with "
                            "that of the same returns in random orders, which keep the Sharpe, "
                            "the volatility and the final result. If the file's fall is milder "
                            "than in nearly every order, losses followed losses less often than "
                            "chance would give, as in a smoothed curve; if it is deeper, they "
                            "came in streaks. With closed trades, loss_streak_review makes the "
                            "same comparison for the longest losing streak, and the challenge "
                            "simulator walks histories resampled the same way through each "
                            "challenge's rules."
                        ),
                        (
                            "One resampling does count towards the class: the 5th percentile of "
                            "the Sharpe in a stationary bootstrap is part of the test against "
                            "chance. The resampled risk, the random orders and the streaks are "
                            "informational and do not change the class. All of them describe the "
                            "supplied history; none is a prediction."
                        ),
                    ],
                },
                {
                    "heading": "See it in the sample report",
                    "paragraphs": [
                        (
                            "Open the linked sample report to see resampled risk on synthetic "
                            "data, then compare it with the one from your own file."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "O que é reamostrar operações ou uma curva",
                    "paragraphs": [
                        (
                            "Um backtest entrega uma sequência: operações fechadas ou retornos "
                            "por período da curva de capital. Reamostrar é construir históricos "
                            "novos com essas mesmas peças. Embaralhar muda apenas a ordem e "
                            "mantém cada resultado. O bootstrap sorteia peças com reposição, de "
                            "modo que um histórico pode repetir umas e omitir outras. O "
                            "bootstrap estacionário sorteia blocos de períodos consecutivos, de "
                            "comprimento aleatório, para conservar parte da dependência entre "
                            "dias próximos."
                        ),
                        (
                            "Cada método repete o sorteio milhares de vezes e resume o resultado: "
                            "a queda máxima mediana, a que aparece em 1 em cada 20 históricos ou "
                            "a proporção de históricos que cai mais que um limite. O nome Monte "
                            "Carlo se refere a esse uso de sorteios repetidos. Não acrescenta "
                            "informação que o histórico não tenha; organiza a que já existe."
                        ),
                    ],
                },
                {
                    "heading": "O que responde: a dispersão se a ordem for intercambiável",
                    "paragraphs": [
                        (
                            "A queda máxima de um backtest depende da ordem em que as perdas "
                            "chegaram. Com os mesmos resultados, outra ordem teria dado uma queda "
                            "mais leve ou mais profunda, e uma sequência de perdas mais curta ou "
                            "mais longa. Um Monte Carlo responde a essa pergunta concreta: que "
                            "faixa de quedas e sequências esses resultados produzem se a ordem "
                            "for intercambiável, isto é, se qualquer ordem era igualmente "
                            "provável."
                        ),
                        (
                            "Essa suposição marca o limite da resposta. Se as perdas dependem do "
                            "regime de mercado, de posições abertas ao mesmo tempo ou de "
                            "mudanças de tamanho, a ordem não é intercambiável e embaralhar "
                            "disfarça isso. O bootstrap por blocos conserva a dependência dentro "
                            "de cada bloco, mas não reconstrói regimes que o histórico não "
                            "contém."
                        ),
                    ],
                },
                {
                    "heading": "Um exemplo calculado com a sua semente",
                    "paragraphs": list(MONTE_CARLO_EXAMPLE["pt"]),
                },
                {
                    "heading": "O que não responde: o sobreajuste e a busca",
                    "paragraphs": [
                        (
                            "Um Monte Carlo não distingue um resultado com vantagem de um "
                            "escolhido por sorte entre muitos. Reamostra o que existe: se o que "
                            "existe é o melhor de cem tentativas, reamostra essa sorte. Também "
                            "não diz como a estratégia se comportaria com dados que não viu, nem "
                            "desconta os custos que o backtest omitiu."
                        ),
                        (
                            "Para a busca de configurações existe outra ferramenta: o Sharpe "
                            "deflacionado compara o Sharpe observado com o que as tentativas "
                            "feitas dariam por acaso. Para o ajuste ao passado, um trecho fora da "
                            "amostra fixado antes de olhar os resultados. Os artigos vinculados "
                            "sobre o Sharpe deflacionado e sobre o que fazer depois do backtest "
                            "explicam os dois; a calculadora de sorte vinculada faz a primeira "
                            "conta com números declarados."
                        ),
                    ],
                },
                {
                    "heading": "Por que o Monte Carlo de um backtest otimizado herda o seu viés",
                    "paragraphs": [
                        (
                            "O otimizador escolhe a configuração cujo histórico saiu melhor. Por "
                            "causa dessa seleção, o histórico tem mais sequências favoráveis e "
                            "quedas mais leves que as do processo que o gerou. A reamostragem "
                            "parte desses mesmos retornos, então seus históricos herdam a média "
                            "inflada e as quedas suavizadas. Um leque de curvas estreito e "
                            "ascendente pode ser apenas a marca da escolha."
                        ),
                        MONTE_CARLO_SEARCH_EXAMPLE["pt"],
                    ],
                },
                {
                    "heading": "O que o relatório do Rigor calcula",
                    "paragraphs": [
                        MONTE_CARLO_REPORT["pt"],
                        (
                            "Ao lado, shuffled_drawdown compara a pior queda do arquivo com a dos "
                            "mesmos retornos em ordens aleatórias, que mantêm o Sharpe, a "
                            "volatilidade e o resultado final. Se a queda do arquivo é mais leve "
                            "que em quase todas as ordens, as perdas se seguiram menos do que o "
                            "acaso daria, como numa curva suavizada; se é mais profunda, "
                            "chegaram em sequências. Com operações fechadas, loss_streak_review "
                            "faz a mesma comparação com a maior sequência de perdas, e o "
                            "simulador de desafios percorre históricos reamostrados da mesma "
                            "forma com as regras de cada desafio."
                        ),
                        (
                            "Uma reamostragem entra na classe: o percentil 5 do Sharpe num "
                            "bootstrap estacionário faz parte do teste contra o acaso. O risco "
                            "reamostrado, as ordens aleatórias e as sequências são informativos "
                            "e não mudam a classe. Todos descrevem o histórico fornecido; nenhum "
                            "é uma previsão."
                        ),
                    ],
                },
                {
                    "heading": "Veja no relatório de exemplo",
                    "paragraphs": [
                        (
                            "Abra o relatório de exemplo vinculado para ver o risco reamostrado "
                            "com dados sintéticos e depois compare com o do seu próprio arquivo."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Un Monte Carlo favorable descarta el sobreajuste?",
                    "a": (
                        "No. Remuestrea el historial que ya existe; si ese historial salió de "
                        "elegir la mejor de muchas configuraciones, el remuestreo conserva el "
                        "sesgo. Para la búsqueda sirve el Sharpe deflactado y, para el ajuste al "
                        "pasado, un tramo fuera de muestra fijado antes de mirar."
                    ),
                },
                {
                    "q": "¿Cuántas simulaciones hacen falta?",
                    "a": (
                        "Más simulaciones afinan los percentiles, pero no cambian lo que se "
                        "remuestrea. El informe usa miles de historias con una semilla fija para "
                        "que el mismo archivo dé los mismos números. El límite principal es la "
                        "longitud y la representatividad del historial, no el número de sorteos."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Does a favourable Monte Carlo rule out overfitting?",
                    "a": (
                        "No. It resamples the history that already exists; if that history came "
                        "from picking the best of many configurations, resampling keeps the "
                        "bias. Deflated Sharpe addresses the search, and an out-of-sample "
                        "stretch fixed before looking addresses fitting to the past."
                    ),
                },
                {
                    "q": "How many simulations are needed?",
                    "a": (
                        "More simulations sharpen the percentiles but do not change what is "
                        "resampled. The report uses thousands of histories with a fixed seed so "
                        "the same file gives the same numbers. The main limit is the length and "
                        "representativeness of the history, not the number of draws."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "Um Monte Carlo favorável descarta o sobreajuste?",
                    "a": (
                        "Não. Reamostra o histórico que já existe; se esse histórico saiu da "
                        "escolha da melhor de muitas configurações, a reamostragem conserva o "
                        "viés. Para a busca serve o Sharpe deflacionado e, para o ajuste ao "
                        "passado, um trecho fora da amostra fixado antes de olhar."
                    ),
                },
                {
                    "q": "Quantas simulações são necessárias?",
                    "a": (
                        "Mais simulações refinam os percentis, mas não mudam o que é "
                        "reamostrado. O relatório usa milhares de históricos com semente fixa "
                        "para que o mesmo arquivo dê os mesmos números. O limite principal é a "
                        "duração e a representatividade do histórico, não o número de sorteios."
                    ),
                },
            ],
        },
        "related": [
            {"kind": "sample"},
            {"kind": "calculator"},
            {"kind": "winrate"},
            {"kind": "article", "key": "sharpe-deflactado-track-record"},
            {"kind": "article", "key": "que-hacer-despues-del-backtest"},
            {"kind": "article", "key": STREAK_ARTICLE_KEY},
            {"kind": "method"},
        ],
    },
    {
        "key": STREAK_ARTICLE_KEY,
        "slug": {
            "es": "rachas-perdedoras",
            "en": "losing-streaks-how-many-are-normal",
            "pt": "sequencias-de-perdas",
        },
        "title": {
            "es": "Rachas perdedoras: cuántas pérdidas seguidas son normales",
            "en": "Losing streaks: how many losses in a row are normal",
            "pt": "Sequências de perdas: quantas seguidas são normais",
        },
        "seo_title": {
            "es": "Rachas perdedoras: cuántas seguidas son normales",
        },
        "summary": {
            "es": (
                "Tabla calculada de la racha perdedora más larga según el % de aciertos y las "
                "operaciones, y por qué un límite de pérdida la vuelve decisiva en un reto."
            ),
            "en": (
                "A computed table of the longest losing streak by win rate and trade count, and "
                "why a loss limit makes an ordinary streak decisive in a challenge."
            ),
            "pt": (
                "Tabela calculada da maior sequência de perdas por taxa de acerto e número de "
                "operações, e por que um limite de perda a torna decisiva num desafio."
            ),
        },
        "intro": {
            "es": (
                f"{_STREAK.rare_run} pérdidas seguidas parecen la señal de que algo se rompió. A "
                "veces lo son; a menudo son lo que el azar da a un sistema con un porcentaje de "
                "aciertos corriente y suficientes operaciones. La pregunta útil no es si una "
                "racha duele, sino si es más larga de lo que darían tu porcentaje de aciertos y "
                "tu número de operaciones. Aquí tienes una tabla calculada con la función del "
                "motor de Rigor, el supuesto que la sostiene y lo que cambia cuando hay un "
                "límite de pérdida."
            ),
            "en": (
                f"{_STREAK.rare_run} losses in a row look like a sign that something broke. "
                "Sometimes they are; often they are what chance gives a system with an ordinary "
                "win rate and enough trades. The useful question is not whether a streak hurts "
                "but whether it is longer than your win rate and trade count would give. Here is "
                "a table computed with Rigor's engine function, the assumption behind it and "
                "what changes when there is a loss limit."
            ),
            "pt": (
                f"{_STREAK.rare_run} perdas seguidas parecem o sinal de que algo quebrou. Às "
                "vezes são; muitas vezes são o que o acaso dá a um sistema com uma taxa de "
                "acerto comum e operações suficientes. A pergunta útil não é se uma sequência "
                "dói, mas se ela é mais longa do que a sua taxa de acerto e o seu número de "
                "operações dariam. Aqui está uma tabela calculada com a função do motor do "
                "Rigor, a suposição que a sustenta e o que muda quando há um limite de perda."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Qué cuenta la tabla",
                    "paragraphs": [
                        (
                            "La racha perdedora más larga de un historial es el mayor número de "
                            "operaciones perdedoras seguidas. Depende de dos cosas: con qué "
                            "frecuencia pierde cada operación y cuántas operaciones hay. Con más "
                            "operaciones hay más ocasiones de que varias pérdidas coincidan, así "
                            "que la racha más larga crece aunque el sistema no cambie."
                        ),
                        (
                            "La tabla da dos cifras por fila. La racha mediana es la más larga "
                            "que aparece en al menos la mitad de los historiales de ese tamaño. "
                            f"La racha de 1 de cada {_ONE_IN} es la más larga que aparece en al "
                            f"menos 1 de cada {_ONE_IN} historiales: menos habitual, pero todavía "
                            "dentro de lo que da el azar."
                        ),
                    ],
                },
                {
                    "heading": STREAK_TABLE_AFTER["es"],
                    "paragraphs": [
                        STREAK_METHOD["es"],
                        (
                            "No hay sorteos ni semillas: el resultado es exacto para ese "
                            "supuesto. Si tus pérdidas dependen unas de otras, porque llegan "
                            "juntas en ciertos mercados o porque abres varias posiciones a la "
                            "vez, las rachas reales pueden ser más largas que las de la tabla."
                        ),
                    ],
                },
                {
                    "heading": "Cómo leer la tabla",
                    "paragraphs": [
                        STREAK_READING["es"],
                        (
                            f"Una racha que no supera la cifra de 1 de cada {_ONE_IN} de tu fila "
                            "no indica por sí sola un cambio en el sistema. Una racha bastante "
                            "más larga sí merece una explicación: dependencia entre operaciones, "
                            "un cambio de régimen o un cambio de reglas. Que tu racha quepa en la "
                            "tabla tampoco dice que el sistema tenga ventaja: la tabla solo "
                            "describe el azar con ese porcentaje de aciertos. Si tu porcentaje "
                            "sale de pocas operaciones, también tiene un margen amplio, y la "
                            "calculadora de % de aciertos enlazada lo muestra."
                        ),
                    ],
                },
                {
                    "heading": "Por qué un límite de pérdida vuelve decisiva una racha normal",
                    "paragraphs": [
                        (
                            "En un reto de prop firm la racha no solo se soporta: se mide contra "
                            "un límite. Si cada pérdida resta un porcentaje fijo del saldo "
                            "inicial, una racha de k pérdidas resta k veces ese porcentaje, sin "
                            "contar costos."
                        ),
                        STREAK_STAKES["es"],
                        (
                            "El límite diario actúa antes: varias pérdidas en la misma sesión "
                            "pueden tocarlo aunque la racha completa quepa en el límite total. "
                            "Por eso importa cuántas operaciones abres por día y si varias pueden "
                            "perder a la vez. Las reglas cambian entre firmas y con el tiempo; "
                            "léelas en las condiciones vigentes de tu reto y compáralas con las "
                            "rachas de tu propio historial, no con las de una captura del "
                            "backtest. La página enlazada para retos de prop firm y el artículo "
                            "sobre cuántos intentos sugiere tu historial explican el resto de la "
                            "cuenta."
                        ),
                    ],
                },
                {
                    "heading": "Qué mide el informe con tus operaciones",
                    "paragraphs": list(STREAK_REPORT["es"]),
                },
                {
                    "heading": "Busca tu fila",
                    "paragraphs": [
                        (
                            "Abre la calculadora de % de aciertos enlazada para ver el margen de "
                            "tu porcentaje y busca después tu fila en la tabla."
                        ),
                    ],
                },
            ],
            "en": [
                {
                    "heading": "What the table counts",
                    "paragraphs": [
                        (
                            "The longest losing streak in a history is the largest number of "
                            "losing trades in a row. It depends on two things: how often each "
                            "trade loses and how many trades there are. More trades give more "
                            "chances for several losses to line up, so the longest streak grows "
                            "even when the system does not change."
                        ),
                        (
                            "The table gives two figures per row. The median streak is the "
                            "longest one reached in at least half of the histories of that size. "
                            f"The 1-in-{_ONE_IN} streak is the longest one reached in at least 1 "
                            f"history in {_ONE_IN}: less common, but still within what chance "
                            "gives."
                        ),
                    ],
                },
                {
                    "heading": STREAK_TABLE_AFTER["en"],
                    "paragraphs": [
                        STREAK_METHOD["en"],
                        (
                            "There are no draws and no seeds: the result is exact under that "
                            "assumption. If your losses depend on each other, because they come "
                            "together in certain markets or because you open several positions "
                            "at once, real streaks can be longer than the table's."
                        ),
                    ],
                },
                {
                    "heading": "How to read the table",
                    "paragraphs": [
                        STREAK_READING["en"],
                        (
                            f"A streak that does not exceed your row's 1-in-{_ONE_IN} figure does "
                            "not, on its own, point to a change in the system. A clearly longer "
                            "one does deserve an explanation: dependence between trades, a "
                            "change of regime or a change of rules. A streak that fits the table "
                            "does not show an edge either: the table only describes chance at "
                            "that win rate. If your win rate comes from few trades it also has a "
                            "wide margin, and the linked win-rate calculator shows it."
                        ),
                    ],
                },
                {
                    "heading": "Why a loss limit makes an ordinary streak decisive",
                    "paragraphs": [
                        (
                            "In a prop-firm challenge a streak is not only endured: it is "
                            "measured against a limit. If each loss takes a fixed percentage of "
                            "the initial balance, a streak of k losses takes k times that "
                            "percentage, before costs."
                        ),
                        STREAK_STAKES["en"],
                        (
                            "The daily limit acts sooner: several losses in the same session can "
                            "touch it even when the whole streak fits within the total limit. "
                            "That is why it matters how many trades you open per day and whether "
                            "several can lose at once. Rules differ between firms and change over "
                            "time; read them in your challenge's current terms and compare them "
                            "with the streaks in your own history, not those in a backtest "
                            "screenshot. The linked page for prop-firm challenges and the article "
                            "on how many attempts your history suggests explain the rest of the "
                            "calculation."
                        ),
                    ],
                },
                {
                    "heading": "What the report measures with your trades",
                    "paragraphs": list(STREAK_REPORT["en"]),
                },
                {
                    "heading": "Find your row",
                    "paragraphs": [
                        (
                            "Open the linked win-rate calculator to see the margin on your win "
                            "rate, then find your row in the table."
                        ),
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "O que a tabela conta",
                    "paragraphs": [
                        (
                            "A maior sequência de perdas de um histórico é o maior número de "
                            "operações perdedoras seguidas. Depende de duas coisas: com que "
                            "frequência cada operação perde e quantas operações existem. Com mais "
                            "operações há mais ocasiões para várias perdas coincidirem, então a "
                            "maior sequência cresce mesmo que o sistema não mude."
                        ),
                        (
                            "A tabela dá dois números por linha. A sequência mediana é a mais "
                            "longa que aparece em pelo menos metade dos históricos desse "
                            f"tamanho. A sequência de 1 em cada {_ONE_IN} é a mais longa que "
                            f"aparece em pelo menos 1 em cada {_ONE_IN} históricos: menos comum, "
                            "mas ainda dentro do que o acaso dá."
                        ),
                    ],
                },
                {
                    "heading": STREAK_TABLE_AFTER["pt"],
                    "paragraphs": [
                        STREAK_METHOD["pt"],
                        (
                            "Não há sorteios nem sementes: o resultado é exato para essa "
                            "suposição. Se as suas perdas dependem umas das outras, porque chegam "
                            "juntas em certos mercados ou porque você abre várias posições ao "
                            "mesmo tempo, as sequências reais podem ser mais longas que as da "
                            "tabela."
                        ),
                    ],
                },
                {
                    "heading": "Como ler a tabela",
                    "paragraphs": [
                        STREAK_READING["pt"],
                        (
                            f"Uma sequência que não passa do número de 1 em cada {_ONE_IN} da sua "
                            "linha não indica, por si só, uma mudança no sistema. Uma sequência "
                            "bem mais longa merece uma explicação: dependência entre operações, "
                            "mudança de regime ou de regras. Que a sua sequência caiba na tabela "
                            "também não mostra que o sistema tem vantagem: a tabela só descreve "
                            "o acaso com essa taxa de acerto. Se a sua taxa vem de poucas "
                            "operações, ela também tem uma margem ampla, e a calculadora de taxa "
                            "de acerto vinculada mostra isso."
                        ),
                    ],
                },
                {
                    "heading": "Por que um limite de perda torna decisiva uma sequência normal",
                    "paragraphs": [
                        (
                            "Num desafio de prop firm a sequência não é só suportada: ela é "
                            "medida contra um limite. Se cada perda tira uma porcentagem fixa do "
                            "saldo inicial, uma sequência de k perdas tira k vezes essa "
                            "porcentagem, sem contar custos."
                        ),
                        STREAK_STAKES["pt"],
                        (
                            "O limite diário age antes: várias perdas na mesma sessão podem "
                            "tocá-lo mesmo que a sequência inteira caiba no limite total. Por "
                            "isso importa quantas operações você abre por dia e se várias podem "
                            "perder ao mesmo tempo. As regras mudam entre empresas e com o tempo; "
                            "leia-as nas condições vigentes do seu desafio e compare com as "
                            "sequências do seu próprio histórico, não com as de uma captura do "
                            "backtest. A página vinculada para desafios de prop firm e o artigo "
                            "sobre quantas tentativas o seu histórico sugere explicam o resto da "
                            "conta."
                        ),
                    ],
                },
                {
                    "heading": "O que o relatório mede com as suas operações",
                    "paragraphs": list(STREAK_REPORT["pt"]),
                },
                {
                    "heading": "Encontre a sua linha",
                    "paragraphs": [
                        (
                            "Abra a calculadora de taxa de acerto vinculada para ver a margem da "
                            "sua taxa e depois encontre a sua linha na tabela."
                        ),
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿La tabla vale para cualquier estrategia?",
                    "a": (
                        "Vale para el supuesto que declara: operaciones independientes con la "
                        "misma probabilidad de perder. Si tu estrategia cambia el tamaño tras una "
                        "pérdida, abre varias posiciones correlacionadas o pierde más en ciertos "
                        "mercados, las rachas reales pueden alargarse. El informe compara tu "
                        "racha con tus propias operaciones en orden al azar."
                    ),
                },
                {
                    "q": "¿Una racha más larga que la de la tabla prueba que algo cambió?",
                    "a": (
                        "No lo prueba. Es una razón para revisar la dependencia entre "
                        "operaciones, un cambio de régimen o de reglas. Con pocas operaciones, "
                        "el porcentaje de aciertos con el que lees la tabla también tiene un "
                        "margen amplio, y una fila vecina puede describir mejor tu historial."
                    ),
                },
            ],
            "en": [
                {
                    "q": "Does the table apply to any strategy?",
                    "a": (
                        "It applies to the assumption it declares: independent trades with the "
                        "same probability of losing. If your strategy changes size after a loss, "
                        "opens several correlated positions or loses more in certain markets, "
                        "real streaks can get longer. The report compares your streak with your "
                        "own trades in random order."
                    ),
                },
                {
                    "q": "Does a streak longer than the table's prove that something changed?",
                    "a": (
                        "It does not prove it. It is a reason to review dependence between "
                        "trades, a change of regime or of rules. With few trades, the win rate "
                        "you read the table with also has a wide margin, and a neighbouring row "
                        "may describe your history better."
                    ),
                },
            ],
            "pt": [
                {
                    "q": "A tabela vale para qualquer estratégia?",
                    "a": (
                        "Vale para a suposição que declara: operações independentes com a mesma "
                        "probabilidade de perder. Se a sua estratégia muda o tamanho depois de "
                        "uma perda, abre várias posições correlacionadas ou perde mais em certos "
                        "mercados, as sequências reais podem ficar mais longas. O relatório "
                        "compara a sua sequência com as suas próprias operações em ordem "
                        "aleatória."
                    ),
                },
                {
                    "q": "Uma sequência mais longa que a da tabela prova que algo mudou?",
                    "a": (
                        "Não prova. É um motivo para revisar a dependência entre operações, uma "
                        "mudança de regime ou de regras. Com poucas operações, a taxa de acerto "
                        "com que você lê a tabela também tem uma margem ampla, e uma linha "
                        "vizinha pode descrever melhor o seu histórico."
                    ),
                },
            ],
        },
        "related": [
            {"kind": "audience", "slug": "retos-prop-firm"},
            {"kind": "article", "key": "cuantos-intentos-reto-prop-firm"},
            {"kind": "winrate"},
            {"kind": "article", "key": MONTE_CARLO_ARTICLE_KEY},
            {"kind": "method"},
        ],
    },
)

ARTICLES: tuple[Article, ...] = tuple(Article.from_dict(data) for data in ARTICLES_DATA)
ARTICLES_BY_KEY: dict[str, Article] = {article.key: article for article in ARTICLES}
#: Reuse published answers verbatim; the index renders these same pairs visibly.
INDEX_FAQ_SOURCES = (
    ("ea-sobreoptimizado", 1),
    ("ea-sobreoptimizado", 2),
    ("backtest-costos-reales", 1),
    ("backtest-costos-reales", 0),
)
#: Articles by their path segment in each language.
ARTICLES_BY_SLUG: dict[str, dict[str, Article]] = {
    locale: {article.slug_for(locale): article for article in ARTICLES} for locale in LOCALES
}


def articles_index_url(locale: str) -> str:
    return ARTICLES_PATH.get(locale, ARTICLES_PATH["es"])


def articles_index_faq(locale: str) -> tuple[tuple[str, str], ...]:
    return tuple(ARTICLES_BY_KEY[key].text[locale].faq[index] for key, index in INDEX_FAQ_SOURCES)


def article_url(key: str, locale: str) -> str:
    """The article's path in ``locale``; ``key`` is its stable key."""
    article = ARTICLES_BY_KEY.get(key)
    return f"{articles_index_url(locale)}/{article.slug_for(locale) if article else key}"


def find_article(slug: str, locale: str) -> tuple[Article, str] | None:
    """The article at ``slug`` and the language that slug belongs to.

    ``locale`` is tried first; a slug from another language comes back with
    that language, so the route can move it to the address of its own."""
    found = ARTICLES_BY_SLUG[locale].get(slug)
    if found is not None:
        return found, locale
    for lang in LOCALES:
        if lang != locale and (found := ARTICLES_BY_SLUG[lang].get(slug)) is not None:
            return found, lang
    return None


#: The label of the ``sample`` related link: the full report built from synthetic data.
SAMPLE_REPORT_LABEL: dict[str, str] = {
    "es": "Ver el informe de ejemplo (datos sintéticos)",
    "en": "See the sample report (synthetic data)",
    "pt": "Ver o relatório de exemplo (dados sintéticos)",
}


def related_links(article: Article, locale: str) -> tuple[tuple[str, str], ...]:
    """The article's related pages as (title, path) in ``locale``."""
    links: list[tuple[str, str]] = []
    for link in article.related:
        kind = link["kind"]
        if kind == "calculator":
            links.append((str(CALCULATOR_COPY[locale]["title"]), CALCULATOR_PATH[locale]))
        elif kind == "method":
            links.append((str(METHOD_COPY[locale]["title"]), METHOD_PATH[locale]))
        elif kind == "guide":
            guide = GUIDES_BY_SLUG[link["slug"]]
            links.append((guide.text[locale].title, guide_url(guide.slug, locale)))
        elif kind == "article":
            related_article = ARTICLES_BY_KEY[link["key"]]
            links.append((related_article.text[locale].title, article_url(link["key"], locale)))
        elif kind == "contact":
            # Imported here to avoid the pages -> articles import cycle.
            from quant_trade.audit.pages import CONTACT_COPY, CONTACT_PATHS

            links.append((CONTACT_COPY[locale]["eyebrow"], CONTACT_PATHS[locale]))
        elif kind == "samples":
            links.append((EXAMPLES_COPY[locale]["title"], EXAMPLES_PATH[locale]))
        elif kind == "sample":
            # Imported here to avoid the pages -> articles import cycle.
            from quant_trade.audit.pages import SAMPLE_PAGE_PATHS

            links.append((SAMPLE_REPORT_LABEL[locale], SAMPLE_PAGE_PATHS[locale]))
        elif kind == "winrate":
            links.append((winrate.COPY[locale]["nav"], winrate.WINRATE_PATH[locale]))
        elif kind == "reading":
            if link.get("example") == "win-rate":
                label = {
                    "es": "Abrir el ejemplo en el lector de cifras",
                    "en": "Open the example in the figure reader",
                    "pt": "Abrir o exemplo no leitor de números",
                }[locale]
                links.append((label, reading_url(locale, WIN_RATE_EXAMPLE_VALUES)))
            else:
                links.append((READING_COPY[locale]["title"], READING_PATH[locale]))
        else:
            page = next(p for p in AUDIENCE_PAGES if p.slug == link["slug"])
            links.append((page.text[locale].title, audience_url(page.slug, locale)))
    return tuple(links)


__all__ = [
    "ARTICLES",
    "ARTICLES_BY_KEY",
    "ARTICLES_BY_SLUG",
    "ARTICLES_COPY",
    "ARTICLES_DATA",
    "ARTICLES_PATH",
    "RELATED_KINDS",
    "Article",
    "ArticleSection",
    "ArticleText",
    "article_url",
    "articles_index_url",
    "find_article",
    "related_links",
]
