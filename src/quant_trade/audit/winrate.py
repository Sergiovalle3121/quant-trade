"""The free win-rate calculator: the reader's Wilson interval and break-even rate.

No new statistics: the interval is ``public_card._wilson`` and the break-even
win rate is ``public_card.breakeven_rate``, the same functions the figure
reader uses. Inputs go through the reader's parser (and so the owner's
bounds and error codes); every input is DECLARED and nothing is stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

from quant_trade.audit import reading
from quant_trade.audit.public_card import PublicClaim, _wilson, breakeven_rate

WINRATE_PATH: dict[str, str] = {
    "es": "/calculadora-aciertos",
    "en": "/en/win-rate-calculator",
    "pt": "/pt/calculadora-taxa-de-acerto",
}
FIELDS = ("trades", "win_rate", "target_r", "stop_r")
#: Sample sizes tried for "from how many trades does the interval clear break-even".
TRADE_GRID = (20, 30, 50, 100, 200, 300, 500, 1000, 2000, 5000, 10000)
#: Sample sizes of the table that shows how the interval narrows.
TABLE_TRADES = (30, 100, 300, 1000)
#: (target R, stop R) pairs for the break-even table shown on every visit.
BREAKEVEN_EXAMPLES = ((1.0, 1.0), (1.5, 1.0), (2.0, 1.0), (3.0, 1.0), (1.0, 2.0))
#: The funnel tag carried by a shared result (``funnel.REF_TAGS``).
SHARE_REF = "aciertos"

COPY: dict[str, dict[str, Any]] = {
    "es": {
        "nav": "Calculadora de % de aciertos",
        "eyebrow": "Calculadora gratis",
        "title": "¿Tu % de aciertos es real o es la muestra?",
        "seo_title": "Calculadora de % de aciertos: intervalo y equilibrio",
        "summary": (
            "¿Tu % de aciertos es real o es la muestra? Intervalo de confianza al 95 % y % de "
            "aciertos de equilibrio según tu objetivo y stop. Gratis."
        ),
        "lead": (
            "Escribe tus operaciones, tu % de aciertos, tu objetivo y tu stop: calculamos el "
            "intervalo de confianza al 95 % y el % de aciertos de equilibrio. Sin registro."
        ),
        "form_title": "Tus cifras",
        "trades": "Operaciones",
        "trades_help": "Cuántas operaciones cerradas tiene la muestra. Por ejemplo 40.",
        "win_rate": "% de aciertos",
        "win_rate_help": "El porcentaje de operaciones ganadoras. Por ejemplo 60.",
        "target_r": "Objetivo (R)",
        "target_r_help": (
            "Cuánto ganas cuando aciertas, en múltiplos del riesgo. Por ejemplo 1.5."
        ),
        "stop_r": "Stop (R)",
        "stop_r_help": "Cuánto pierdes cuando fallas, en múltiplos del riesgo. Normalmente 1.",
        "optional": "Deja vacío lo que no conoces: aparecerá como NOT_MEASURED.",
        "submit": "Calcular",
        "result_title": "Resultado",
        "interval": "Intervalo de confianza al 95 % (Wilson)",
        "breakeven": "% de aciertos de equilibrio antes de costes",
        "above": (
            "Con estas cifras declaradas, todo el intervalo al 95 % queda por encima del % de "
            "aciertos de equilibrio antes de costes. No mide costes, deslizamiento ni si las "
            "operaciones son independientes."
        ),
        "below": (
            "Todo el intervalo al 95 % queda por debajo del equilibrio antes de costes: con "
            "este objetivo y este stop, la muestra declarada no llega al equilibrio."
        ),
        "inside": (
            "El equilibrio cae dentro del intervalo al 95 %: con estas operaciones, la muestra "
            "no distingue tu % de aciertos del de equilibrio."
        ),
        "needed": (
            "Con el {rate} declarado, el límite inferior del intervalo supera el equilibrio a "
            "partir de {n} operaciones (probamos 20, 30, 50, 100, 200, 300, 500, 1.000, 2.000, "
            "5.000 y 10.000)."
        ),
        "needed_never": (
            "Con un % de aciertos declarado igual o inferior al equilibrio, ninguna cantidad de "
            "operaciones pone el intervalo por encima."
        ),
        "needed_none": (
            "Ni con 10.000 operaciones el límite inferior del intervalo supera el equilibrio."
        ),
        "declared_note": (
            "Las cifras de entrada son declaradas y los resultados se calculan a partir de "
            "ellas. Esta lectura no es una auditoría."
        ),
        "table_title": "Cómo se estrecha el intervalo con más operaciones",
        "col_trades": "Operaciones",
        "col_interval": "Intervalo al 95 %",
        "col_above": "¿Por encima del equilibrio?",
        "yes": "Sí",
        "no": "No",
        "be_table_title": "% de aciertos de equilibrio según riesgo/beneficio",
        "col_target": "Objetivo (R)",
        "col_stop": "Stop (R)",
        "col_breakeven": "Aciertos de equilibrio",
        "how_title": "Qué calcula y qué supone",
        "how": [
            "El intervalo de Wilson al 95 % da el rango de % de aciertos compatible con tu "
            "muestra si las operaciones son independientes. Con pocas operaciones es ancho.",
            "El % de aciertos de equilibrio es stop ÷ (objetivo + stop): con ese % y "
            "operaciones que terminan en el objetivo o en el stop, lo ganado y lo perdido se "
            "compensan antes de costes.",
            "Un porcentaje redondeado se trata como proporción; no reconstruimos cuántas "
            "operaciones ganaron.",
            "No mide costes, deslizamiento, rachas ni si la regla se fijó antes de ver los "
            "resultados.",
        ],
        "cta_title": "Con tu archivo, las cifras son medidas",
        "cta": (
            "El informe mide tus operaciones reales: el % de aciertos con su intervalo, el "
            "coste de equilibrio, dentro y fuera de muestra y la calidad de datos. El primer "
            "informe completo es gratis con cuenta."
        ),
        "cta_button": "Auditar mi archivo",
        "sample_link": "Ver un informe de ejemplo",
        "share_title": "Compartir este resultado",
        "share_text": (
            "Mi % de aciertos declarado, con su intervalo al 95 % y el equilibrio de mi "
            "objetivo y stop, calculado con Rigor. No es una auditoría. {url}"
        ),
        "card_link": "Crear la tarjeta para compartir con estas cifras",
        "read_title": "Para seguir",
    },
    "en": {
        "nav": "Win rate calculator",
        "eyebrow": "Free calculator",
        "title": "Is your win rate real, or just the sample?",
        "seo_title": "Win rate calculator: confidence interval and break-even",
        "summary": (
            "Is your win rate real or just the sample? 95 % confidence interval and break-even "
            "win rate for your target and stop. Free, no signup."
        ),
        "lead": (
            "Enter your trades, win rate, target and stop: we compute the 95 % confidence "
            "interval and the break-even win rate. No signup."
        ),
        "form_title": "Your figures",
        "trades": "Trades",
        "trades_help": "How many closed trades the sample has. For example 40.",
        "win_rate": "Win rate (%)",
        "win_rate_help": "The share of winning trades. For example 60.",
        "target_r": "Target (R)",
        "target_r_help": "What you win when right, in multiples of risk. For example 1.5.",
        "stop_r": "Stop (R)",
        "stop_r_help": "What you lose when wrong, in multiples of risk. Usually 1.",
        "optional": "Leave what you do not know empty: it will appear as NOT_MEASURED.",
        "submit": "Calculate",
        "result_title": "Result",
        "interval": "95 % confidence interval (Wilson)",
        "breakeven": "Break-even win rate before costs",
        "above": (
            "With these declared figures, the whole 95 % interval sits above the break-even "
            "win rate before costs. Costs, slippage and whether trades are independent are not "
            "measured."
        ),
        "below": (
            "The whole 95 % interval sits below break-even before costs: with this target and "
            "stop, the declared sample does not reach break-even."
        ),
        "inside": (
            "Break-even falls inside the 95 % interval: with these trades, the sample cannot "
            "tell your win rate apart from break-even."
        ),
        "needed": (
            "With the declared {rate}, the lower end of the interval clears break-even from {n} "
            "trades (we try 20, 30, 50, 100, 200, 300, 500, 1,000, 2,000, 5,000 and 10,000)."
        ),
        "needed_never": (
            "With a declared win rate at or below break-even, no number of trades puts the "
            "interval above it."
        ),
        "needed_none": (
            "Even with 10,000 trades the lower end of the interval does not clear break-even."
        ),
        "declared_note": (
            "The input figures are declared and the results are computed from them. This "
            "reading is not an audit."
        ),
        "table_title": "How the interval narrows with more trades",
        "col_trades": "Trades",
        "col_interval": "95 % interval",
        "col_above": "Above break-even?",
        "yes": "Yes",
        "no": "No",
        "be_table_title": "Break-even win rate by risk/reward",
        "col_target": "Target (R)",
        "col_stop": "Stop (R)",
        "col_breakeven": "Break-even win rate",
        "how_title": "What it computes and assumes",
        "how": [
            "The Wilson 95 % interval is the range of win rates compatible with your sample if "
            "trades are independent. With few trades it is wide.",
            "The break-even win rate is stop ÷ (target + stop): at that rate, with trades that "
            "end at the target or the stop, wins and losses cancel out before costs.",
            "A rounded percentage is treated as a proportion; we do not rebuild how many trades "
            "won.",
            "It does not measure costs, slippage, streaks or whether the rule was fixed before "
            "seeing the results.",
        ],
        "cta_title": "With your file, the figures are measured",
        "cta": (
            "The report measures your real trades: the win rate with its interval, break-even "
            "cost, in-sample versus out-of-sample and data quality. Your first full report is "
            "free with an account."
        ),
        "cta_button": "Audit my file",
        "sample_link": "See a sample report",
        "share_title": "Share this result",
        "share_text": (
            "My declared win rate, with its 95 % interval and the break-even for my target and "
            "stop, computed with Rigor. This is not an audit. {url}"
        ),
        "card_link": "Create the shareable card with these figures",
        "read_title": "Keep reading",
    },
    "pt": {
        "nav": "Calculadora de taxa de acerto",
        "eyebrow": "Calculadora grátis",
        "title": "Sua taxa de acerto é real ou é a amostra?",
        "seo_title": "Calculadora de taxa de acerto: intervalo e equilíbrio",
        "summary": (
            "Sua taxa de acerto é real ou é a amostra? Intervalo de confiança de 95 % e taxa de "
            "equilíbrio para o seu alvo e stop. Grátis."
        ),
        "lead": (
            "Digite suas operações, sua taxa de acerto, seu alvo e seu stop: calculamos o "
            "intervalo de confiança de 95 % e a taxa de acerto de equilíbrio. Sem cadastro."
        ),
        "form_title": "Seus números",
        "trades": "Operações",
        "trades_help": "Quantas operações fechadas a amostra tem. Por exemplo 40.",
        "win_rate": "Taxa de acerto (%)",
        "win_rate_help": "A porcentagem de operações vencedoras. Por exemplo 60.",
        "target_r": "Alvo (R)",
        "target_r_help": (
            "Quanto você ganha quando acerta, em múltiplos do risco. Por exemplo 1.5."
        ),
        "stop_r": "Stop (R)",
        "stop_r_help": "Quanto você perde quando erra, em múltiplos do risco. Normalmente 1.",
        "optional": "Deixe vazio o que não sabe: aparecerá como NOT_MEASURED.",
        "submit": "Calcular",
        "result_title": "Resultado",
        "interval": "Intervalo de confiança de 95 % (Wilson)",
        "breakeven": "Taxa de acerto de equilíbrio antes dos custos",
        "above": (
            "Com esses números declarados, todo o intervalo de 95 % fica acima da taxa de "
            "acerto de equilíbrio antes dos custos. Não mede custos, slippage nem se as "
            "operações são independentes."
        ),
        "below": (
            "Todo o intervalo de 95 % fica abaixo do equilíbrio antes dos custos: com este alvo "
            "e este stop, a amostra declarada não chega ao equilíbrio."
        ),
        "inside": (
            "O equilíbrio cai dentro do intervalo de 95 %: com essas operações, a amostra não "
            "distingue a sua taxa de acerto da de equilíbrio."
        ),
        "needed": (
            "Com os {rate} declarados, o limite inferior do intervalo supera o equilíbrio a "
            "partir de {n} operações (testamos 20, 30, 50, 100, 200, 300, 500, 1.000, 2.000, "
            "5.000 e 10.000)."
        ),
        "needed_never": (
            "Com uma taxa de acerto declarada igual ou abaixo do equilíbrio, nenhuma quantidade "
            "de operações coloca o intervalo acima dele."
        ),
        "needed_none": (
            "Nem com 10.000 operações o limite inferior do intervalo supera o equilíbrio."
        ),
        "declared_note": (
            "Os números de entrada são declarados e os resultados são calculados a partir "
            "deles. Esta leitura não é uma auditoria."
        ),
        "table_title": "Como o intervalo se estreita com mais operações",
        "col_trades": "Operações",
        "col_interval": "Intervalo de 95 %",
        "col_above": "Acima do equilíbrio?",
        "yes": "Sim",
        "no": "Não",
        "be_table_title": "Taxa de acerto de equilíbrio por risco/retorno",
        "col_target": "Alvo (R)",
        "col_stop": "Stop (R)",
        "col_breakeven": "Taxa de acerto de equilíbrio",
        "how_title": "O que calcula e o que supõe",
        "how": [
            "O intervalo de Wilson de 95 % é a faixa de taxas de acerto compatível com a sua "
            "amostra se as operações forem independentes. Com poucas operações, é larga.",
            "A taxa de acerto de equilíbrio é stop ÷ (alvo + stop): com essa taxa e operações "
            "que terminam no alvo ou no stop, ganhos e perdas se compensam antes dos custos.",
            "Uma porcentagem arredondada é tratada como proporção; não reconstruímos quantas "
            "operações ganharam.",
            "Não mede custos, slippage, sequências de perdas nem se a regra foi fixada antes "
            "de ver os resultados.",
        ],
        "cta_title": "Com o seu arquivo, os números são medidos",
        "cta": (
            "O relatório mede as suas operações reais: a taxa de acerto com o intervalo, o "
            "custo de equilíbrio, dentro e fora da amostra e a qualidade dos dados. O seu "
            "primeiro relatório completo é grátis com conta."
        ),
        "cta_button": "Auditar meu arquivo",
        "sample_link": "Ver um relatório de exemplo",
        "share_title": "Compartilhar este resultado",
        "share_text": (
            "Minha taxa de acerto declarada, com o intervalo de 95 % e o equilíbrio do meu "
            "alvo e stop, calculada com o Rigor. Não é uma auditoria. {url}"
        ),
        "card_link": "Criar o cartão para compartilhar com esses números",
        "read_title": "Para continuar",
    },
}


@dataclass(frozen=True)
class WinRateReading:
    """What the page shows, every figure from ``_wilson`` or ``breakeven_rate``."""

    #: Wilson's 95 % interval for the declared rate and trade count.
    interval: tuple[float, float] | None
    #: The break-even win rate for the declared target and stop, before costs.
    breakeven: float | None
    #: Where the whole interval sits against break-even.
    position: Literal["above", "below", "inside"] | None
    #: The first size in ``TRADE_GRID`` whose lower bound clears break-even.
    trades_needed: int | None
    #: The declared rate is at or below break-even: no sample size clears it.
    never: bool
    #: ``(trades, interval)`` for each size in ``TABLE_TRADES``.
    rows: tuple[tuple[int, tuple[float, float]], ...]


def winrate_url(locale: str) -> str:
    return WINRATE_PATH.get(locale, WINRATE_PATH["es"])


def parse(values: Mapping[str, str], locale: str) -> PublicClaim:
    """The reader's parser on the four fields: same bounds and ``ClaimInputError`` codes."""
    return reading.claim_from_query({name: values.get(name, "") for name in FIELDS}, locale)


def read(claim: PublicClaim) -> WinRateReading:
    """The interval, break-even and comparisons, from the reader's functions only."""
    rate = claim.win_rate
    interval = None
    if rate is not None and claim.trades is not None:
        interval = _wilson(rate, claim.trades)
    breakeven = None
    if claim.target_r is not None and claim.stop_r is not None:
        breakeven = breakeven_rate(claim.target_r, claim.stop_r)
    position: Literal["above", "below", "inside"] | None = None
    if interval is not None and breakeven is not None:
        low, high = interval
        position = "above" if low > breakeven else "below" if high < breakeven else "inside"
    never = rate is not None and breakeven is not None and rate <= breakeven
    trades_needed = None
    if rate is not None and breakeven is not None and not never:
        trades_needed = next((n for n in TRADE_GRID if _wilson(rate, n)[0] > breakeven), None)
    rows = tuple((n, _wilson(rate, n)) for n in TABLE_TRADES) if rate is not None else ()
    return WinRateReading(
        interval=interval,
        breakeven=breakeven,
        position=position,
        trades_needed=trades_needed,
        never=never,
        rows=rows,
    )


def share_url(locale: str, values: Mapping[str, str]) -> str:
    """The validated strings as they arrived, like ``reading.reading_url``, tagged."""
    query = {name: values.get(name, "").strip() for name in FIELDS}
    return WINRATE_PATH[locale] + "?" + urlencode({**query, "ref": SHARE_REF})


__all__ = [
    "BREAKEVEN_EXAMPLES",
    "COPY",
    "FIELDS",
    "SHARE_REF",
    "TABLE_TRADES",
    "TRADE_GRID",
    "WINRATE_PATH",
    "WinRateReading",
    "parse",
    "read",
    "share_url",
    "winrate_url",
]
