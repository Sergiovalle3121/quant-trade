"""Anonymous public declarations, using the card and calculator's own arithmetic.

These are illustrative readings of public figures, not uploaded files or audits.
Nine weeks is converted using an explicit 52-week year; a development period is
never substituted for a backtest's missing history.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlencode

from quant_trade.audit.calculator import CalculatorInput, calculator_url, compute
from quant_trade.audit.public_card import PublicClaim, public_card_svg

EXAMPLES_PATH = {"es": "/ejemplos", "en": "/en/examples", "pt": "/pt/exemplos"}
WEEKS_PER_YEAR = 52
SHORT_HISTORY_WEEKS = 9


@dataclass(frozen=True)
class PublicExample:
    key: str
    claim: PublicClaim

    def calculator_input(self) -> CalculatorInput | None:
        """Only prefill a calculator when all of its inputs were declared."""
        claim = self.claim
        if claim.sharpe is None or claim.years is None or claim.trials is None:
            return None
        return CalculatorInput(claim.sharpe, claim.years, claim.trials)


EXAMPLES = (
    PublicExample(
        "ai-search",
        PublicClaim(trades=45, win_rate=0.71, profit_factor=3.24, target_r=1, stop_r=1),
    ),
    PublicExample(
        "short-history",
        PublicClaim(sharpe=1.9, years=SHORT_HISTORY_WEEKS / WEEKS_PER_YEAR, trials=1),
    ),
    PublicExample("many-trials", PublicClaim(sharpe=1.8, years=3, trials=1000)),
)

EXAMPLES_COPY = {
    "es": {
        "nav": "Cifras públicas",
        "eyebrow": "Ejemplos de lectura",
        "title": "Qué falta detrás de unas cifras públicas",
        "summary": (
            "Aciertos, Sharpe e intentos de búsqueda: ejemplos anónimos con cifras declaradas, "
            "supuestos explícitos y la misma cuenta de la calculadora."
        ),
        "intro": (
            "Estas tarjetas contextualizan declaraciones públicas. No tenemos los archivos: "
            "no son auditorías y no tienen clase de auditoría."
        ),
        "source": "Post público, octubre de 2026",
        "back": "Inicio",
        "calculator": "Explorar en la calculadora",
        "ai-search_title": "Una estrategia atribuida a IA",
        "ai-search_line1": (
            "DECLARED · La publicación atribuye la búsqueda a IA en tres semanas. "
            "Ese plazo de desarrollo no indica cuánto historial cubre el backtest."
        ),
        "ai-search_line2": (
            "NOT_MEASURED · Sin archivo no podemos reconciliar el profit factor, los aciertos "
            "y las salidas. Faltan Sharpe, años e intentos para la calculadora."
        ),
        "short-history_title": "Un historial corto para concluir",
        "short-history_line1": (
            "DECLARED · {weeks} semanas fuera de muestra; conversión aproximada a "
            "{years:.6f} años bajo el supuesto de {weeks_per_year} semanas por año."
        ),
        "short-history_line2": (
            "NOT_MEASURED · Una sola configuración no tiene búsqueda que descontar; "
            "eso no demuestra estabilidad ni confirma la separación fuera de muestra."
        ),
        "many-trials_title": "Elegir entre muchas configuraciones",
        "many-trials_line1": (
            "DECLARED · Calculado con esas cifras: Sharpe esperado por suerte {luck:.2f}; "
            "Sharpe después del descuento {after:.2f}, bajo los supuestos de la calculadora."
        ),
        "many-trials_line2": (
            "NOT_MEASURED · Elegir el mejor resultado de una búsqueda requiere tener en "
            "cuenta los intentos. Faltan el archivo, los costos y el tramo fuera de muestra."
        ),
    },
    "en": {
        "nav": "Public figures",
        "eyebrow": "Reading examples",
        "title": "Trading strategy review: public examples",
        "summary": (
            "Examples for a statistical review of a trading strategy: declared Sharpe ratios, "
            "research attempts and missing evidence, with explicit assumptions."
        ),
        "intro": (
            "These cards put public declarations in context. We do not have the files: "
            "these are not audits and have no audit class."
        ),
        "source": "Public post, October 2026",
        "back": "Home",
        "calculator": "Explore in the calculator",
        "ai-search_title": "A strategy attributed to AI",
        "ai-search_line1": (
            "DECLARED · The post attributes the search to AI over three weeks. "
            "That development period does not say how much history the backtest covers."
        ),
        "ai-search_line2": (
            "NOT_MEASURED · Without the file we cannot reconcile profit factor, win rate "
            "and exits. Sharpe, years and attempts are missing for the calculator."
        ),
        "short-history_title": "A short history to draw conclusions from",
        "short-history_line1": (
            "DECLARED · {weeks} weeks out of sample; approximately {years:.6f} years "
            "assuming {weeks_per_year} weeks per year."
        ),
        "short-history_line2": (
            "NOT_MEASURED · A single configuration has no search to discount; "
            "that does not establish stability or confirm the out-of-sample separation."
        ),
        "many-trials_title": "Picking among many configurations",
        "many-trials_line1": (
            "DECLARED · Computed from those figures: expected Sharpe from luck {luck:.2f}; "
            "Sharpe after the haircut {after:.2f}, under the calculator's assumptions."
        ),
        "many-trials_line2": (
            "NOT_MEASURED · Picking the best result of a search requires accounting for "
            "the attempts. The file, costs and out-of-sample segment are missing."
        ),
    },
    "pt": {
        "nav": "Números públicos",
        "eyebrow": "Exemplos de leitura",
        "title": "O que falta por trás de números públicos",
        "summary": (
            "Acertos, Sharpe e tentativas de busca: exemplos anônimos com números declarados, "
            "suposições explícitas e a mesma conta da calculadora."
        ),
        "intro": (
            "Estes cartões contextualizam declarações públicas. Não temos os arquivos: "
            "não são auditorias e não têm classe de auditoria."
        ),
        "source": "Post público, outubro de 2026",
        "back": "Início",
        "calculator": "Explorar na calculadora",
        "ai-search_title": "Uma estratégia atribuída à IA",
        "ai-search_line1": (
            "DECLARED · O post atribui a busca à IA em três semanas. "
            "Esse prazo de desenvolvimento não diz quanto histórico o backtest cobre."
        ),
        "ai-search_line2": (
            "NOT_MEASURED · Sem o arquivo não podemos conciliar profit factor, acertos "
            "e saídas. Faltam Sharpe, anos e tentativas para a calculadora."
        ),
        "short-history_title": "Um histórico curto para concluir",
        "short-history_line1": (
            "DECLARED · {weeks} semanas fora da amostra; conversão aproximada para "
            "{years:.6f} anos supondo {weeks_per_year} semanas por ano."
        ),
        "short-history_line2": (
            "NOT_MEASURED · Uma só configuração não tem busca a descontar; "
            "isso não demonstra estabilidade nem confirma a separação fora da amostra."
        ),
        "many-trials_title": "Escolher entre muitas configurações",
        "many-trials_line1": (
            "DECLARED · Calculado com esses números: Sharpe esperado por sorte {luck:.2f}; "
            "Sharpe após o desconto {after:.2f}, sob as suposições da calculadora."
        ),
        "many-trials_line2": (
            "NOT_MEASURED · Escolher o melhor resultado de uma busca exige considerar "
            "as tentativas. Faltam o arquivo, os custos e o trecho fora da amostra."
        ),
    },
}


def examples_url(locale: str) -> str:
    return EXAMPLES_PATH.get(locale, EXAMPLES_PATH["es"])


def example_calculator_url(example: PublicExample, locale: str) -> str:
    values = example.calculator_input()
    params: dict[str, str | float | int] = {"ref": "ejemplos"}
    if values is not None:
        params.update(sharpe=values.sharpe, years=values.years, trials=values.trials)
    return calculator_url(locale) + "?" + urlencode(params)


def examples_content(locale: str = "es") -> str:
    """Three escaped, responsive inline cards and two reading lines per case."""
    lang: Literal["es", "en", "pt"] = "en" if locale == "en" else "pt" if locale == "pt" else "es"
    words = EXAMPLES_COPY[lang]
    parts = []
    for example in EXAMPLES:
        claim = replace(example.claim, locale=lang, source_handle=words["source"])
        svg = public_card_svg(claim)
        # A standalone card's title/desc ids need a unique scope when embedded.
        for name in ("title", "desc"):
            svg = svg.replace(f'id="{name}"', f'id="{example.key}-{name}"')
        svg = svg.replace(
            'aria-labelledby="title desc"',
            f'aria-labelledby="{example.key}-title {example.key}-desc"',
        ).replace("<svg ", '<svg style="display:block;width:100%;height:auto" ', 1)
        values: dict[str, float | int] = {}
        if example.key == "short-history":
            values = {
                "weeks": SHORT_HISTORY_WEEKS,
                "years": SHORT_HISTORY_WEEKS / WEEKS_PER_YEAR,
                "weeks_per_year": WEEKS_PER_YEAR,
            }
        elif example.key == "many-trials":
            inputs = example.calculator_input()
            assert inputs is not None
            result = compute(inputs)
            values = {
                "luck": result["luck_sharpe"]["value"],
                "after": result["sharpe_after"]["value"],
            }
        readings = "".join(
            "<p class='example-reading'>"
            f"{html.escape(words[example.key + line].format(**values))}</p>"
            for line in ("_line1", "_line2")
        )
        parts.append(
            f"<section class='article-cta public-example' data-example='{example.key}'>"
            f"<h2>{html.escape(words[example.key + '_title'])}</h2>{svg}{readings}"
            f"<p><a class='link-more' href='{html.escape(example_calculator_url(example, lang))}'>"
            f"{html.escape(words['calculator'])}</a></p></section>"
        )
    return "".join(parts)
