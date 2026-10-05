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
from typing import Any

from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url
from quant_trade.audit.calculator import CALCULATOR_PATH
from quant_trade.audit.calculator import COPY as CALCULATOR_COPY
from quant_trade.audit.guides import GUIDES_BY_SLUG, guide_url
from quant_trade.audit.method import COPY as METHOD_COPY
from quant_trade.audit.method import METHOD_PATH

LOCALES: tuple[str, ...] = ("es", "en", "pt")

#: The pages an article may point to: the free calculator, an export guide
#: (by its Spanish slug), an audience page (by its Spanish slug) or the method.
RELATED_KINDS: frozenset[str] = frozenset({"calculator", "guide", "audience", "method"})


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
            )
            for locale in LOCALES
        }
        related = tuple(
            {str(k): str(v) for k, v in link.items()} for link in data.get("related", ())
        )
        for link in related:
            if link.get("kind") not in RELATED_KINDS:
                raise ValueError(f"article {data['key']}: unknown related kind {link!r}")
        return cls(
            key=str(data["key"]),
            slug={locale: str(data["slug"][locale]) for locale in LOCALES},
            text=text,
            related=related,
        )


#: Index and page paths per language. An article lives at ``<index>/<slug>``.
ARTICLES_PATH: dict[str, str] = {"es": "/articulos", "en": "/articles", "pt": "/pt/artigos"}

#: The words the index and every article page share.
ARTICLES_COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Artículos",
        "title": "Artículos sobre backtests",
        "summary": (
            "Artículos cortos sobre backtests: sobreoptimización, costos reales y cómo leer "
            "el informe del probador de estrategias. Sin registro."
        ),
        "intro": "Lecturas cortas sobre qué mirar en un backtest antes de fiarte de él.",
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
            "Short articles about backtests: overfitting, real costs and how to read the "
            "strategy tester report. No sign-up needed."
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
            "Artigos curtos sobre backtests: sobreajuste, custos reais e como ler o relatório "
            "do testador de estratégias. Sem cadastro."
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
#: shape. The texts below are placeholders that keep the pages short and neutral.
ARTICLES_DATA: tuple[dict[str, Any], ...] = (
    {
        "key": "ea-sobreoptimizado",
        "slug": {
            "es": "ea-sobreoptimizado",
            "en": "overfitted-expert-advisor",
            "pt": "ea-sobreajustado",
        },
        "title": {
            "es": "EA sobreoptimizado: cómo reconocerlo en un backtest",
            "en": "Overfitted expert advisor: how to spot it in a backtest",
            "pt": "EA sobreajustado: como reconhecê-lo num backtest",
        },
        "summary": {
            "es": (
                "Qué señales deja un robot ajustado al pasado en su backtest y qué pruebas "
                "separan una ventaja de la suerte."
            ),
            "en": (
                "The marks a robot fitted to the past leaves in its backtest, and which tests "
                "separate an edge from luck."
            ),
            "pt": (
                "Que sinais um robô ajustado ao passado deixa no seu backtest e que testes "
                "separam uma vantagem da sorte."
            ),
        },
        "intro": {
            "es": (
                "Un robot puede ajustarse tanto al pasado que su curva de capital describe la "
                "historia en lugar de una regla. Este artículo explica dónde se nota."
            ),
            "en": (
                "A robot can be fitted so closely to the past that its equity curve describes "
                "history rather than a rule. This article explains where it shows."
            ),
            "pt": (
                "Um robô pode ajustar-se tanto ao passado que a sua curva de capital descreve a "
                "história em vez de uma regra. Este artigo explica onde isso aparece."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Las señales en el backtest",
                    "paragraphs": [
                        "Muchos parámetros, pocas operaciones y un resultado que cambia mucho "
                        "al mover un parámetro un paso son las tres señales más comunes.",
                    ],
                },
                {
                    "heading": "Cómo comprobarlo",
                    "paragraphs": [
                        "Cuenta cuántas configuraciones probaste y repite el backtest en un "
                        "periodo que no usaste para ajustar. La calculadora de suerte muestra "
                        "cuánto del Sharpe explica el número de intentos.",
                    ],
                },
            ],
            "en": [
                {
                    "heading": "The marks in the backtest",
                    "paragraphs": [
                        "Many parameters, few trades and a result that moves a lot when one "
                        "parameter moves one step are the three most common marks.",
                    ],
                },
                {
                    "heading": "How to check",
                    "paragraphs": [
                        "Count how many configurations you tried and repeat the backtest on a "
                        "period you did not use for tuning. The luck calculator shows how much "
                        "of the Sharpe the number of trials explains.",
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Os sinais no backtest",
                    "paragraphs": [
                        "Muitos parâmetros, poucas operações e um resultado que muda muito ao "
                        "mover um parâmetro um passo são os três sinais mais comuns.",
                    ],
                },
                {
                    "heading": "Como verificar",
                    "paragraphs": [
                        "Conte quantas configurações você testou e repita o backtest num "
                        "período que não usou para ajustar. A calculadora de sorte mostra "
                        "quanto do Sharpe o número de tentativas explica.",
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Cuántos intentos son demasiados?",
                    "a": "No hay un número fijo: depende de los años del backtest y del Sharpe. "
                    "La calculadora lo muestra para tu caso.",
                },
            ],
            "en": [
                {
                    "q": "How many trials are too many?",
                    "a": "There is no fixed number: it depends on the years the backtest covers "
                    "and on the Sharpe. The calculator shows it for your case.",
                },
            ],
            "pt": [
                {
                    "q": "Quantas tentativas são demais?",
                    "a": "Não há um número fixo: depende dos anos do backtest e do Sharpe. A "
                    "calculadora mostra isso para o seu caso.",
                },
            ],
        },
        "related": [
            {"kind": "calculator"},
            {"kind": "guide", "slug": "mt5-optimization"},
            {"kind": "audience", "slug": "compradores-de-robots"},
            {"kind": "method"},
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
            "es": "Backtest con costos reales: spread, comisión y slippage",
            "en": "Backtest with real costs: spread, commission and slippage",
            "pt": "Backtest com custos reais: spread, comissão e slippage",
        },
        "summary": {
            "es": (
                "Qué costos suele omitir un backtest y cómo ver si el resultado se sostiene "
                "cuando se cobran."
            ),
            "en": (
                "Which costs a backtest tends to leave out, and how to see whether the result "
                "holds once they are charged."
            ),
            "pt": (
                "Que custos um backtest costuma omitir e como ver se o resultado se sustenta "
                "quando eles são cobrados."
            ),
        },
        "intro": {
            "es": (
                "Un backtest sin costos describe un mercado que no existe. Este artículo repasa "
                "los tres costos que más cambian un resultado."
            ),
            "en": (
                "A backtest without costs describes a market that does not exist. This article "
                "goes over the three costs that change a result the most."
            ),
            "pt": (
                "Um backtest sem custos descreve um mercado que não existe. Este artigo revê os "
                "três custos que mais mudam um resultado."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Spread, comisión y slippage",
                    "paragraphs": [
                        "El spread se paga en cada entrada, la comisión en cada operación y el "
                        "slippage cuando el precio se mueve entre la orden y el relleno.",
                    ],
                },
                {
                    "heading": "Qué mirar",
                    "paragraphs": [
                        "Compara el resultado con los costos al doble y al triple. Si el "
                        "backtest no resiste ese cambio, el margen era el propio costo.",
                    ],
                },
            ],
            "en": [
                {
                    "heading": "Spread, commission and slippage",
                    "paragraphs": [
                        "The spread is paid on every entry, the commission on every trade and "
                        "slippage when the price moves between the order and the fill.",
                    ],
                },
                {
                    "heading": "What to look at",
                    "paragraphs": [
                        "Compare the result with costs doubled and tripled. If the backtest "
                        "does not survive that change, the margin was the cost itself.",
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Spread, comissão e slippage",
                    "paragraphs": [
                        "O spread é pago em cada entrada, a comissão em cada operação e o "
                        "slippage quando o preço se move entre a ordem e a execução.",
                    ],
                },
                {
                    "heading": "O que observar",
                    "paragraphs": [
                        "Compare o resultado com os custos em dobro e em triplo. Se o backtest "
                        "não resiste a essa mudança, a margem era o próprio custo.",
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿El informe de MT5 incluye los costos?",
                    "a": "Incluye la comisión y el swap que tenía la cuenta del probador; el "
                    "slippage no, salvo que lo simules.",
                },
            ],
            "en": [
                {
                    "q": "Does the MT5 report include costs?",
                    "a": "It includes the commission and swap of the tester account; slippage "
                    "only if you simulate it.",
                },
            ],
            "pt": [
                {
                    "q": "O relatório do MT5 inclui os custos?",
                    "a": "Inclui a comissão e o swap da conta do testador; o slippage não, a "
                    "menos que você o simule.",
                },
            ],
        },
        "related": [
            {"kind": "method"},
            {"kind": "guide", "slug": "mt5"},
            {"kind": "audience", "slug": "traders-acciones-futuros-cripto"},
            {"kind": "calculator"},
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
            "es": "Cómo leer el informe del probador de estrategias de MT5",
            "en": "How to read the MT5 strategy tester report",
            "pt": "Como ler o relatório do testador de estratégias do MT5",
        },
        "summary": {
            "es": (
                "Qué significa cada cifra del informe del probador de MetaTrader 5 y cuáles "
                "conviene mirar primero."
            ),
            "en": (
                "What each figure of the MetaTrader 5 tester report means, and which ones to "
                "look at first."
            ),
            "pt": (
                "O que significa cada número do relatório do testador do MetaTrader 5 e quais "
                "convém olhar primeiro."
            ),
        },
        "intro": {
            "es": (
                "El informe del probador trae decenas de cifras. Este artículo explica las que "
                "más pesan y las que suelen leerse mal."
            ),
            "en": (
                "The tester report carries dozens of figures. This article explains the ones "
                "that weigh most and the ones that are often misread."
            ),
            "pt": (
                "O relatório do testador traz dezenas de números. Este artigo explica os que "
                "mais pesam e os que costumam ser mal lidos."
            ),
        },
        "sections": {
            "es": [
                {
                    "heading": "Las cifras que más pesan",
                    "paragraphs": [
                        "El número de operaciones, el drawdown máximo y el factor de beneficio "
                        "dicen más que el saldo final.",
                    ],
                },
                {
                    "heading": "Las que suelen leerse mal",
                    "paragraphs": [
                        "Un porcentaje de aciertos alto con pocas operaciones no dice nada por "
                        "sí solo, y el drawdown relativo depende del saldo inicial.",
                    ],
                },
            ],
            "en": [
                {
                    "heading": "The figures that weigh most",
                    "paragraphs": [
                        "The number of trades, the maximum drawdown and the profit factor say "
                        "more than the final balance.",
                    ],
                },
                {
                    "heading": "The ones often misread",
                    "paragraphs": [
                        "A high win rate with few trades says nothing on its own, and the "
                        "relative drawdown depends on the starting balance.",
                    ],
                },
            ],
            "pt": [
                {
                    "heading": "Os números que mais pesam",
                    "paragraphs": [
                        "O número de operações, o drawdown máximo e o fator de lucro dizem mais "
                        "do que o saldo final.",
                    ],
                },
                {
                    "heading": "Os que costumam ser mal lidos",
                    "paragraphs": [
                        "Uma taxa de acerto alta com poucas operações não diz nada por si só, e "
                        "o drawdown relativo depende do saldo inicial.",
                    ],
                },
            ],
        },
        "faq": {
            "es": [
                {
                    "q": "¿Qué archivo subo a la auditoría?",
                    "a": "El informe HTML o XLSX que guarda el probador, sin convertirlo. La "
                    "guía de MT5 muestra el menú.",
                },
            ],
            "en": [
                {
                    "q": "Which file do I upload to the audit?",
                    "a": "The HTML or XLSX report the tester saves, with no conversion. The MT5 "
                    "guide shows the menu.",
                },
            ],
            "pt": [
                {
                    "q": "Que arquivo envio para a auditoria?",
                    "a": "O relatório HTML ou XLSX que o testador salva, sem convertê-lo. O guia "
                    "do MT5 mostra o menu.",
                },
            ],
        },
        "related": [
            {"kind": "guide", "slug": "mt5"},
            {"kind": "guide", "slug": "mt5-optimization"},
            {"kind": "calculator"},
            {"kind": "method"},
        ],
    },
)

ARTICLES: tuple[Article, ...] = tuple(Article.from_dict(data) for data in ARTICLES_DATA)
ARTICLES_BY_KEY: dict[str, Article] = {article.key: article for article in ARTICLES}
#: Articles by their path segment in each language.
ARTICLES_BY_SLUG: dict[str, dict[str, Article]] = {
    locale: {article.slug_for(locale): article for article in ARTICLES} for locale in LOCALES
}


def articles_index_url(locale: str) -> str:
    return ARTICLES_PATH.get(locale, ARTICLES_PATH["es"])


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
