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
        audience_slugs = {page.slug for page in AUDIENCE_PAGES}
        for link in related:
            if link.get("kind") not in RELATED_KINDS:
                raise ValueError(f"article {data['key']}: unknown related kind {link!r}")
            if link["kind"] == "guide" and link.get("slug") not in GUIDES_BY_SLUG:
                raise ValueError(f"article {data['key']}: unknown guide {link!r}")
            if link["kind"] == "audience" and link.get("slug") not in audience_slugs:
                raise ValueError(f"article {data['key']}: unknown audience page {link!r}")
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
            "Short articles about backtests: overfitting, real costs and how to read the strategy "
            "tester report. No sign-up needed to read them."
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
