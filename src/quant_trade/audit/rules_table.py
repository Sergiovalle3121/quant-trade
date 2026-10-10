"""The public table of prop-firm rules: every published preset, phase by phase,
with its source and the day it was read, as data for the page
(``challenge_pages.rules_table_page``).

No figure here is typed by hand: each row is a ``prop_presets`` preset, and the
counts the texts name are counted from the presets. The filters are links with
a query (no JavaScript); an unknown value shows the whole table instead of an
error, and the page's canonical address is always the one without a query.
Rigor is not affiliated with any firm; the page says so, links each firm's own
page and recommends buying nothing.

Constants and pure functions only. ``seo`` imports this module for the sitemap,
so it imports neither ``seo`` nor ``pages``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from quant_trade.audit import challenge_calc as calc
from quant_trade.audit import firmfit
from quant_trade.audit.prop_presets import PRESETS, TOTAL_LOSS_TYPES, ChallengeRules

#: The page's path in each language.
RULES_TABLE_PATH: dict[str, str] = {
    "es": "/reglas-prop-firm",
    "en": "/en/prop-firm-rules",
    "pt": "/pt/regras-prop-firm",
}
#: The day the table was published; its sitemap date is this or a later
#: reading of a preset (``rules_table_lastmod``).
RULES_TABLE_PUBLISHED = "2026-10-10"

#: The query fields of the filters, the same in every language so one link
#: works on every translation: a firm (``challenge_calc.FIRMS`` key), a type of
#: maximum loss (``prop_presets.TOTAL_LOSS_TYPES``) and a market.
FILTER_FIRM = "firma"
FILTER_LOSS = "perdida"
FILTER_MARKET = "mercado"
FILTER_FIELDS: tuple[str, ...] = (FILTER_FIRM, FILTER_LOSS, FILTER_MARKET)
#: The markets a visitor can filter by: the forex programs and the futures ones.
MARKET_FILTERS: tuple[str, ...] = ("fx", "futures")


def _locale(locale: str) -> str:
    return locale if locale in RULES_TABLE_PATH else "es"


def rules_table_url(locale: str) -> str:
    return RULES_TABLE_PATH[_locale(locale)]


def rules_table_paths() -> dict[str, str]:
    """The page in every language, for canonical, hreflang and the sitemap."""
    return dict(RULES_TABLE_PATH)


@dataclass(frozen=True)
class Filters:
    """What the query asked for, after dropping what it cannot mean."""

    firm: str = ""
    loss: str = ""
    market: str = ""

    @property
    def active(self) -> bool:
        return bool(self.firm or self.loss or self.market)

    def values(self) -> dict[str, str]:
        """The query's fields, as ``parse_filters`` reads them back."""
        return {FILTER_FIRM: self.firm, FILTER_LOSS: self.loss, FILTER_MARKET: self.market}

    def query(self) -> str:
        """``?firma=ftmo&mercado=fx``, or "" when nothing is filtered."""
        chosen = {name: value for name, value in self.values().items() if value}
        return "?" + urlencode(chosen) if chosen else ""

    def with_(self, **changes: str) -> Filters:
        """The same filters with one of them set or cleared ("")."""
        values = {"firm": self.firm, "loss": self.loss, "market": self.market, **changes}
        return Filters(**values)


def parse_filters(values: Mapping[str, str]) -> Filters:
    """The filters a query names. A value that names nothing is ignored, so a
    wrong or old link still shows the whole table."""
    firm = str(values.get(FILTER_FIRM, "") or "").strip()
    loss = str(values.get(FILTER_LOSS, "") or "").strip()
    market = str(values.get(FILTER_MARKET, "") or "").strip()
    return Filters(
        firm=firm if firm in calc.FIRMS else "",
        loss=loss if loss in TOTAL_LOSS_TYPES else "",
        market=market if market in MARKET_FILTERS else "",
    )


@dataclass(frozen=True)
class Row:
    """One preset of the table: a program's phase, with the firm's page segment."""

    rules: ChallengeRules
    firm: str
    #: The program's first preset, the key its calculator page offers.
    program: str
    #: How many presets the program has: with one, the phase is not shown.
    siblings: int

    @property
    def key(self) -> str:
        return self.rules.key


FIRM_SLUGS: dict[str, str] = {name: slug for slug, name in calc.FIRMS.items()}


def rows() -> tuple[Row, ...]:
    """Every published program, phase by phase, in the presets' own order."""
    out: list[Row] = []
    for program in calc.PROGRAMS:
        keys = firmfit.program_keys(program)
        for key in keys:
            rules = PRESETS[key]
            out.append(
                Row(rules=rules, firm=FIRM_SLUGS[rules.firm], program=program, siblings=len(keys))
            )
    return tuple(out)


ROWS: tuple[Row, ...] = rows()


def matches(row: Row, filters: Filters) -> bool:
    """Whether a row stays under ``filters``. A program whose pages do not state
    its markets matches no market filter, and the page says so."""
    if filters.firm and row.firm != filters.firm:
        return False
    if filters.loss and row.rules.total_loss_type != filters.loss:
        return False
    return not filters.market or filters.market in (row.rules.markets or ())


def filtered_rows(filters: Filters) -> tuple[Row, ...]:
    return tuple(row for row in ROWS if matches(row, filters))


def latest_as_of() -> str:
    """The most recent reading date of the table's presets: its modification date."""
    return max(row.rules.as_of for row in ROWS)


def rules_table_lastmod() -> str:
    """The page's sitemap date: its publication, or a later reading of a preset,
    so the sitemap and the ``Dataset``'s ``dateModified`` never fall out of step."""
    return max(RULES_TABLE_PUBLISHED, latest_as_of())


def firm_rows(firm: str) -> tuple[Row, ...]:
    return tuple(row for row in ROWS if row.firm == firm)


def firm_programs(firm: str) -> tuple[str, ...]:
    """The program keys of a firm (each program's first preset)."""
    return tuple(dict.fromkeys(row.program for row in firm_rows(firm)))


def counts() -> dict[str, int]:
    """The figures the texts name, counted from the presets, never typed."""
    programs = {row.program for row in ROWS}
    firms = {row.firm for row in ROWS}
    first = [PRESETS[program] for program in dict.fromkeys(row.program for row in ROWS)]
    return {
        "rows": len(ROWS),
        "programs": len(programs),
        "firms": len(firms),
        "daily_initial": sum(1 for r in first if r.daily_loss_basis == "initial_balance"),
        "daily_day": sum(1 for r in first if r.daily_loss_basis == "start_of_day"),
        "daily_none": sum(1 for r in first if r.max_daily_loss is None),
        "static": sum(1 for r in first if r.total_loss_type == "static"),
        "trailing": sum(1 for r in first if r.total_loss_type == "trailing_eod"),
        "lock": sum(1 for r in first if r.total_loss_type == "trailing_eod_lock"),
        "best_day": sum(1 for r in first if r.best_day_limit is not None),
        "markets_unknown": sum(1 for r in first if r.markets is None),
    }


#: The calculator's wording of each type of maximum loss (``calc.COPY`` key by
#: ``prop_presets.TOTAL_LOSS_TYPES`` value).
_LOSS_WORDS: dict[str, str] = {
    "static": "total_static",
    "trailing_eod": "total_trailing",
    "trailing_eod_lock": "total_lock",
}


def loss_names(locale: str) -> dict[str, str]:
    """Each type of maximum loss worded exactly as the table's cells word it: the
    calculator's own text without its figure, so the filter chips, the cells and
    the questions never name the same rule three ways."""
    words = calc.COPY[_locale(locale)]
    return {kind: str(words[key]).removeprefix("{value}, ") for kind, key in _LOSS_WORDS.items()}


#: The markets as the page names them (``prop_presets.MARKETS``).
MARKET_WORDS: dict[str, dict[str, str]] = {
    "es": {
        "fx": "forex",
        "metals": "metales",
        "indices": "índices",
        "energy": "energía",
        "crypto": "cripto",
        "futures": "futuros",
    },
    "en": {
        "fx": "forex",
        "metals": "metals",
        "indices": "indices",
        "energy": "energy",
        "crypto": "crypto",
        "futures": "futures",
    },
    "pt": {
        "fx": "forex",
        "metals": "metais",
        "indices": "índices",
        "energy": "energia",
        "crypto": "cripto",
        "futures": "futuros",
    },
}


COPY: dict[str, dict[str, Any]] = {
    "es": {
        "nav": "Tabla de reglas de prop firms",
        "eyebrow": "Reglas publicadas, con fuente y fecha",
        "title": "Comparativa de reglas de prop firms, programa por programa, con fuente y fecha",
        "seo_title": "Comparativa de reglas de prop firms con fuente y fecha",
        "summary": (
            "Comparativa de reglas de {firms} prop firms: objetivo, pérdida diaria y total, "
            "días, plazo y regla del mejor día, con fuente y fecha. Sin afiliación ni cupones."
        ),
        "lead": (
            "Una fila por programa y fase, transcrita de la página de cada firma el día que se "
            "indica y tal como la usa la calculadora de Rigor; cuando una firma vende varias "
            "variantes de una regla, las notas del programa, en su calculadora, dicen cuál es "
            "la de la fila. Rigor no está afiliado a ninguna firma, no cobra comisiones ni "
            "recomienda comprar ningún reto."
        ),
        "filters_title": "Filtrar la tabla",
        "filters_help": "Cada filtro es un enlace; no hace falta JavaScript.",
        "filter_firm": "Firma",
        "filter_loss": "Pérdida total",
        "filter_market": "Mercado",
        "all": "Todas",
        "all_markets": "Todos",
        "showing": "Se muestran {n} de {total} filas.",
        "show_all": "Ver la tabla completa",
        "market_note": (
            "Un programa cuya página leída no dice qué mercados ofrece no aparece con este "
            "filtro; aparece en la tabla completa con «no indicado»."
        ),
        "empty": "Ninguna fila coincide con estos filtros.",
        "table_title": "La tabla",
        "col_firm": "Firma",
        "col_program": "Programa y fase",
        "col_target": "Objetivo",
        "col_daily": "Pérdida diaria y su base",
        "col_total": "Pérdida total y su tipo",
        "col_days": "Días mínimos",
        "col_time": "Plazo",
        "col_best": "Regla del mejor día",
        "col_markets": "Mercados",
        "col_source": "Fuente",
        "col_as_of": "Leída el",
        "markets_unknown": "no indicado",
        "markets_read": "leídos el {date}",
        "daily_untranscribed": "no transcrita: ver las notas en la calculadora de la firma",
        "source_link": "página de {firm}",
        "table_note": (
            "Las cifras son las que cada página publicaba el día indicado, en la lectura más "
            "estricta cuando una página se contradice; cada firma puede haberlas cambiado."
        ),
        "firms_title": "Las firmas, una a una",
        "firm_programs": "{count} {source}: {programs}.",
        "firm_count": "{n} programas transcritos",
        "firm_count_one": "Un programa transcrito",
        "firm_page": "de la página de {firm}, leída el {date}",
        "firm_pages": "de las páginas de {firm}, leídas el {date}",
        "firm_page_dates": "de la página de {firm}, leída entre el {first} y el {last}",
        "firm_pages_dates": "de las páginas de {firm}, leídas entre el {first} y el {last}",
        "firm_rows": "Solo las filas de esta firma",
        "firm_calculator": "Calculadora del reto {firm}",
        "not_affiliated": (
            "Rigor no está afiliado a ninguna firma; las reglas cambian, comprueba la página "
            "oficial antes de decidir nada."
        ),
        "blind_title": "Lo que esta tabla no ve",
        "blind": (
            "Los límites que se mueven dentro del día (trailing intradía) y las pérdidas "
            "abiertas: la tabla tiene la cifra, no cuándo se mide.",
            "Las restricciones de noticias, de robots, de fin de semana o de horario.",
            "Las reglas de pago de la cuenta financiada: reparto, primer retiro, consistencia "
            "después de la evaluación.",
            "Los tamaños de cuenta de cada firma y sus diferencias; las cifras en dólares son "
            "las de la cuenta que la página nombra.",
            "Las cuotas, los descuentos, los reembolsos y los reinicios.",
        ),
        "no_buy": (
            "Esta tabla compara reglas publicadas; no dice qué reto comprar ni si conviene "
            "comprar alguno."
        ),
        "faq_title": "Preguntas frecuentes",
        "faq": (
            (
                "¿Qué es una pérdida total que sigue al cierre diario (trailing EOD)?",
                "Es un límite que sube con el mayor balance de cierre del día: cada cierre más "
                "alto mueve el balance mínimo hacia arriba, y la cuenta termina si lo toca. En "
                "la columna «{col_total}» aparece como «{trailing_label}»; cuando además se "
                "detiene al llegar al balance inicial, «{lock_label}». {trailing} programas de "
                "la tabla lo usan y {lock} más lo usan con el tope.",
            ),
            (
                "¿Qué es la regla del mejor día?",
                "Una regla de consistencia: la ganancia del mejor día no puede superar una parte "
                "del objetivo, o de la ganancia de los días positivos, según la firma. En la "
                "tabla, la columna «Regla del mejor día» muestra ese porcentaje y su base; "
                "{best_day} programas la tienen en la evaluación.",
            ),
            (
                "¿Desde qué base se mide la pérdida diaria?",
                "Depende de la firma: {daily_initial} programas la miden como un porcentaje del "
                "balance inicial, {daily_day} como un porcentaje del balance al empezar el día "
                "y {daily_none} no tienen una cifra transcrita, porque su página no pone límite "
                "diario en la evaluación o porque es opcional o solo pausa el día. La columna "
                "«Pérdida diaria y su base» lo dice fila por fila.",
            ),
            (
                "¿Por qué hay programas y firmas que no están?",
                "Solo están los programas cuyas reglas caben en los tipos que el simulador de "
                "Rigor entiende; cuando la lectura es una aproximación, las notas del programa, "
                "en su calculadora, dicen si es más estricta o más optimista que la regla de la "
                "firma: {programs} programas de {firms} firmas. Quedan fuera, por ejemplo, los "
                "que miden la pérdida máxima sobre el máximo intradía o limitan la ganancia "
                "diaria, y cualquier firma que no hemos transcrito todavía.",
            ),
        ),
        "read_title": "Para seguir",
        "audience_line": "Las reglas de cada firma, con fuente y fecha:",
    },
    "en": {
        "nav": "Prop firm rules table",
        "eyebrow": "Published rules, with source and date",
        "title": "Prop firm rules comparison, program by program, with source and date",
        "seo_title": "Prop firm rules comparison with source and date",
        "summary": (
            "Prop firm rules comparison for {firms} firms: target, daily and total loss, days, "
            "time limit and best-day rule, with source and date. No affiliation, no coupons."
        ),
        "lead": (
            "One row per program and phase, transcribed from each firm's page on the day "
            "shown and as Rigor's calculator uses it; when a firm sells several variants of a "
            "rule, the program's notes, on its calculator, say which one the row shows. Rigor "
            "is not affiliated with any firm, earns no commission and does not recommend "
            "buying any challenge."
        ),
        "filters_title": "Filter the table",
        "filters_help": "Every filter is a link; no JavaScript needed.",
        "filter_firm": "Firm",
        "filter_loss": "Total loss",
        "filter_market": "Market",
        "all": "All",
        "all_markets": "All",
        "showing": "Showing {n} of {total} rows.",
        "show_all": "See the whole table",
        "market_note": (
            "A program whose pages do not say which markets it offers is not shown under this "
            "filter; the whole table lists it as “not stated”."
        ),
        "empty": "No row matches these filters.",
        "table_title": "The table",
        "col_firm": "Firm",
        "col_program": "Program and phase",
        "col_target": "Target",
        "col_daily": "Daily loss and its basis",
        "col_total": "Total loss and its type",
        "col_days": "Minimum days",
        "col_time": "Time limit",
        "col_best": "Best-day rule",
        "col_markets": "Markets",
        "col_source": "Source",
        "col_as_of": "Read on",
        "markets_unknown": "not stated",
        "markets_read": "read on {date}",
        "daily_untranscribed": "not transcribed: see the notes on the firm's calculator",
        "source_link": "{firm} page",
        "table_note": (
            "The figures are what each page published on the day shown, in the stricter "
            "reading where a page contradicts itself; every firm may have changed them since."
        ),
        "firms_title": "The firms, one by one",
        "firm_programs": "{count} {source}: {programs}.",
        "firm_count": "{n} programs transcribed",
        "firm_count_one": "One program transcribed",
        "firm_page": "from the {firm} page, read on {date}",
        "firm_pages": "from the {firm} pages, read on {date}",
        "firm_page_dates": "from the {firm} page, read between {first} and {last}",
        "firm_pages_dates": "from the {firm} pages, read between {first} and {last}",
        "firm_rows": "Only this firm's rows",
        "firm_calculator": "{firm} challenge calculator",
        "not_affiliated": (
            "Rigor is not affiliated with any firm; rules change, check the official page "
            "before deciding anything."
        ),
        "blind_title": "What this table does not see",
        "blind": (
            "Limits that move within the day (intraday trailing) and open losses: the table "
            "has the figure, not when it is measured.",
            "News, robot, weekend and trading-hour restrictions.",
            "The funded account's payout rules: split, first withdrawal, consistency after "
            "the evaluation.",
            "Each firm's account sizes and their differences; the dollar figures are those of "
            "the account the page names.",
            "Fees, discounts, refunds and resets.",
        ),
        "no_buy": (
            "This table compares published rules; it does not say which challenge to buy, or "
            "whether to buy one at all."
        ),
        "faq_title": "Frequently asked questions",
        "faq": (
            (
                "What is a total loss that trails the daily close (trailing EOD)?",
                "A limit that rises with the highest end-of-day balance: every higher close "
                "moves the minimum balance up, and the account ends if the balance touches it. "
                "The “{col_total}” column reads “{trailing_label}”; when it also stops rising "
                "at the initial balance, “{lock_label}”. {trailing} programs in the table use "
                "it and {lock} more use it with the lock.",
            ),
            (
                "What is the best-day rule?",
                "A consistency rule: the best day's gain may not exceed a share of the target, "
                "or of the positive days' gain, depending on the firm. In the table, the "
                "“Best-day rule” column shows that share and its basis; {best_day} "
                "programs have one in the evaluation.",
            ),
            (
                "From which basis is the daily loss measured?",
                "It depends on the firm: {daily_initial} programs measure it as a share of the "
                "initial balance, {daily_day} as a share of the start-of-day balance, and "
                "{daily_none} have no transcribed figure, because their page sets no daily "
                "limit in the evaluation or because it is optional or only pauses the day. The "
                "“Daily loss and its basis” column says so row by row.",
            ),
            (
                "Why are some programs and firms missing?",
                "Only the programs whose rules fit the types Rigor's simulator understands are "
                "here; where the reading is an approximation, the program's notes, on its "
                "calculator, say whether it is stricter or more optimistic than the firm's "
                "rule: {programs} programs from {firms} firms. Left out are, for example, "
                "those that measure the maximum loss from the intraday high or cap the daily "
                "gain, and any firm we have not transcribed yet.",
            ),
        ),
        "read_title": "Keep reading",
        "audience_line": "Each firm's rules, with source and date:",
    },
    "pt": {
        "nav": "Tabela de regras de prop firms",
        "eyebrow": "Regras publicadas, com fonte e data",
        "title": "Comparativo de regras de prop firms, programa por programa, com fonte e data",
        "seo_title": "Comparativo de regras de prop firms com fonte e data",
        "summary": (
            "Comparativo de regras de {firms} prop firms: meta, perda diária e total, dias, "
            "prazo e regra do melhor dia, com fonte e data. Sem afiliação nem cupons."
        ),
        "lead": (
            "Uma linha por programa e fase, transcrita da página de cada empresa no dia "
            "indicado e tal como a calculadora do Rigor a usa; quando uma empresa vende várias "
            "variantes de uma regra, as notas do programa, na calculadora dela, dizem qual é a "
            "da linha. O Rigor não é afiliado a nenhuma empresa, não recebe comissão e não "
            "recomenda comprar nenhum desafio."
        ),
        "filters_title": "Filtrar a tabela",
        "filters_help": "Cada filtro é um link; não precisa de JavaScript.",
        "filter_firm": "Empresa",
        "filter_loss": "Perda total",
        "filter_market": "Mercado",
        "all": "Todas",
        "all_markets": "Todos",
        "showing": "Mostrando {n} de {total} linhas.",
        "show_all": "Ver a tabela completa",
        "market_note": (
            "Um programa cuja página lida não diz quais mercados oferece não aparece com este "
            "filtro; aparece na tabela completa como «não indicado»."
        ),
        "empty": "Nenhuma linha corresponde a estes filtros.",
        "table_title": "A tabela",
        "col_firm": "Empresa",
        "col_program": "Programa e fase",
        "col_target": "Meta",
        "col_daily": "Perda diária e a sua base",
        "col_total": "Perda total e o seu tipo",
        "col_days": "Dias mínimos",
        "col_time": "Prazo",
        "col_best": "Regra do melhor dia",
        "col_markets": "Mercados",
        "col_source": "Fonte",
        "col_as_of": "Lida em",
        "markets_unknown": "não indicado",
        "markets_read": "lidos em {date}",
        "daily_untranscribed": "não transcrita: ver as notas na calculadora da empresa",
        "source_link": "página da {firm}",
        "table_note": (
            "Os números são os que cada página publicava no dia indicado, na leitura mais "
            "estrita quando uma página se contradiz; cada empresa pode tê-los mudado."
        ),
        "firms_title": "As empresas, uma a uma",
        "firm_programs": "{count} {source}: {programs}.",
        "firm_count": "{n} programas transcritos",
        "firm_count_one": "Um programa transcrito",
        "firm_page": "da página da {firm}, lida em {date}",
        "firm_pages": "das páginas da {firm}, lidas em {date}",
        "firm_page_dates": "da página da {firm}, lida entre {first} e {last}",
        "firm_pages_dates": "das páginas da {firm}, lidas entre {first} e {last}",
        "firm_rows": "Só as linhas desta empresa",
        "firm_calculator": "Calculadora do desafio {firm}",
        "not_affiliated": (
            "O Rigor não é afiliado a nenhuma empresa; as regras mudam, confira a página "
            "oficial antes de decidir qualquer coisa."
        ),
        "blind_title": "O que esta tabela não vê",
        "blind": (
            "Os limites que se movem dentro do dia (trailing intradiário) e as perdas abertas: "
            "a tabela tem o número, não quando ele é medido.",
            "As restrições de notícias, de robôs, de fim de semana ou de horário.",
            "As regras de pagamento da conta financiada: divisão, primeiro saque, "
            "consistência depois da avaliação.",
            "Os tamanhos de conta de cada empresa e as suas diferenças; os valores em dólares "
            "são os da conta que a página nomeia.",
            "As taxas, os descontos, os reembolsos e os reinícios.",
        ),
        "no_buy": (
            "Esta tabela compara regras publicadas; não diz qual desafio comprar nem se vale a "
            "pena comprar algum."
        ),
        "faq_title": "Perguntas frequentes",
        "faq": (
            (
                "O que é uma perda total que acompanha o fechamento diário (trailing EOD)?",
                "É um limite que sobe com o maior saldo de fechamento do dia: cada fechamento "
                "mais alto move o saldo mínimo para cima, e a conta termina se o saldo o tocar. "
                "Na coluna «{col_total}» aparece como «{trailing_label}»; quando também para "
                "ao chegar ao saldo inicial, «{lock_label}». {trailing} programas da tabela o "
                "usam e {lock} outros o usam com a trava.",
            ),
            (
                "O que é a regra do melhor dia?",
                "Uma regra de consistência: o ganho do melhor dia não pode superar uma parte da "
                "meta, ou do ganho dos dias positivos, conforme a empresa. Na tabela, a coluna "
                "«Regra do melhor dia» mostra essa porcentagem e a sua base; {best_day} "
                "programas a têm na avaliação.",
            ),
            (
                "A partir de que base a perda diária é medida?",
                "Depende da empresa: {daily_initial} programas a medem como uma porcentagem do "
                "saldo inicial, {daily_day} como uma porcentagem do saldo no início do dia e "
                "{daily_none} não têm um número transcrito, porque a página não põe limite "
                "diário na avaliação ou porque ele é opcional ou só pausa o dia. A coluna «Perda "
                "diária e a sua base» diz isso linha por linha.",
            ),
            (
                "Por que há programas e empresas que não estão?",
                "Só estão os programas cujas regras cabem nos tipos que o simulador do Rigor "
                "entende; quando a leitura é uma aproximação, as notas do programa, na "
                "calculadora dele, dizem se ela é mais estrita ou mais otimista que a regra da "
                "empresa: {programs} programas de {firms} empresas. Ficam de fora, por exemplo, "
                "os que medem a perda máxima sobre a máxima intradiária ou limitam o ganho "
                "diário, e qualquer empresa que ainda não transcrevemos.",
            ),
        ),
        "read_title": "Para continuar",
        "audience_line": "As regras de cada empresa, com fonte e data:",
    },
}


def summary(locale: str) -> str:
    """The page's description, with the number of firms counted from the presets."""
    return str(COPY[_locale(locale)]["summary"]).format(firms=counts()["firms"])


def faq(locale: str) -> tuple[tuple[str, str], ...]:
    """The four questions of fact: their counts filled from the presets and the
    rule types named exactly as the table's cells name them."""
    locale = _locale(locale)
    labels = loss_names(locale)
    fields: dict[str, Any] = {
        **counts(),
        "col_total": COPY[locale]["col_total"],
        "trailing_label": labels["trailing_eod"],
        "lock_label": labels["trailing_eod_lock"],
    }
    return tuple((question, answer.format(**fields)) for question, answer in COPY[locale]["faq"])


def market_words(markets: tuple[str, ...] | None, locale: str) -> str:
    """The markets a preset states, in the page's language; "" when it states none."""
    if not markets:
        return ""
    words = MARKET_WORDS[_locale(locale)]
    return ", ".join(words[market] for market in markets)


__all__ = [
    "COPY",
    "FILTER_FIELDS",
    "FILTER_FIRM",
    "FILTER_LOSS",
    "FILTER_MARKET",
    "FIRM_SLUGS",
    "MARKET_FILTERS",
    "MARKET_WORDS",
    "ROWS",
    "RULES_TABLE_PATH",
    "RULES_TABLE_PUBLISHED",
    "Filters",
    "Row",
    "counts",
    "faq",
    "filtered_rows",
    "firm_programs",
    "firm_rows",
    "latest_as_of",
    "loss_names",
    "market_words",
    "matches",
    "parse_filters",
    "rows",
    "rules_table_lastmod",
    "rules_table_paths",
    "rules_table_url",
    "summary",
]
