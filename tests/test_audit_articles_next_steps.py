"""The next-step articles keep translations, examples and public discovery aligned."""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.articles import (  # noqa: E402
    ARTICLES_BY_KEY,
    COST_EXAMPLE_TRADE,
    INDEPENDENT_LUCK_EXAMPLE,
    LUCK_EXAMPLE_INPUT,
    WIN_RATE_RATES,
    WIN_RATE_TABLE_COPY,
    WIN_RATE_TRADE_COUNTS,
    _num,
    article_url,
    articles_index_url,
    win_rate_interval,
)
from quant_trade.audit.calculator import calculator_url, compute  # noqa: E402
from quant_trade.audit.costs import break_even_bps  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import guide_url  # noqa: E402
from quant_trade.audit.pages import article_page  # noqa: E402
from quant_trade.audit.public_card import _pct, _wilson  # noqa: E402
from quant_trade.audit.reading import READING_PATH  # noqa: E402
from quant_trade.audit.report import evidence_label, localize_tags  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
ARTICLE_KEYS = (
    "que-hacer-despues-del-backtest",
    "cuantas-operaciones-porcentaje-aciertos",
    "lo-eligio-el-optimizador",
)


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


class _LinkParser(HTMLParser):
    """Every ``href`` (in ``links``) and ``src`` (in ``sources``), entities unescaped."""

    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()
        self.sources: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "src" and value is not None:
                self.sources.add(value)
            if name == "href" and value is not None:
                # The site's embedded favicon is a local asset, not an outgoing link.
                if (
                    tag == "link"
                    and dict(attrs).get("rel") == "icon"
                    and value.startswith("data:image/svg+xml,")
                ):
                    continue
                self.links.add(value)


def _parsed(page: str) -> _LinkParser:
    parser = _LinkParser()
    parser.feed(page)
    parser.close()
    return parser


def _links(page: str) -> set[str]:
    return _parsed(page).links


def _prose(page: str) -> str:
    """The visible article body: sections, inserted tables, questions and related links."""
    match = re.search(r"<article class='prose'>(.*?)</article>", page, re.S)
    assert match is not None
    return _visible(match.group(1))


def _interval_bounds(text: str) -> tuple[float, float]:
    """Read rounded proportions despite the reader and table's different typography."""
    match = re.search(r"(\d+[.,]\d+)\s*%?\s*–\s*(\d+[.,]\d+)\s*%", text)
    assert match is not None, text
    return float(match[1].replace(",", ".")) / 100, float(match[2].replace(",", ".")) / 100


def _paragraphs(key: str, locale: str) -> str:
    words = ARTICLES_BY_KEY[key].text[locale]
    return " ".join([words.intro, *(p for s in words.sections for p in s.paragraphs)])


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", ARTICLE_KEYS)
def test_next_step_copy_metadata_structured_data_and_guard(key: str, locale: str) -> None:
    article = ARTICLES_BY_KEY[key]
    words = article.text[locale]
    assert 1 <= len(words.title) <= 60
    assert 1 <= len(words.summary) <= 155
    source_texts = [words.title, words.summary, words.intro, words.seo_title or words.title]
    for section in words.sections:
        source_texts.extend([section.heading, *section.paragraphs])
    source_texts.extend(text for pair in words.faq for text in pair)
    for source_text in source_texts:
        assert find_claims(source_text) == [], (key, locale, source_text)

    page = article_page(article, locale=locale, base_url=BASE)
    title = re.search(r"<title>([^<]+)</title>", page)
    assert title is not None
    assert len(html.unescape(title.group(1))) <= 60
    assert find_claims(_visible(page)) == []
    assert find_claims(html.unescape(page)) == []
    assert f"<meta name='description' content='{html.escape(words.summary, quote=True)}'>" in page
    assert f"rel='canonical' href='{BASE}{article_url(key, locale)}'" in page
    for other in LOCALES:
        assert f"hreflang='{other}' href='{BASE}{article_url(key, other)}'" in page

    detail, breadcrumbs = [
        json.loads(block)
        for block in re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    ]
    assert detail["@type"] == "Article"
    assert detail["headline"] == words.title
    assert detail["inLanguage"] == locale
    assert detail["datePublished"] == detail["dateModified"] == "2026-10-08"
    assert detail["mainEntityOfPage"] == BASE + article_url(key, locale)
    assert breadcrumbs["@type"] == "BreadcrumbList"
    assert breadcrumbs["itemListElement"][-1]["item"] == BASE + article_url(key, locale)

    links = _links(page)
    assert READING_PATH[locale] in links
    assert calculator_url(locale) in links
    assert any(link.startswith(guide_url("mt5", locale).rsplit("/", 1)[0] + "/") for link in links)
    if key == "lo-eligio-el-optimizador":
        assert guide_url("mt5-optimization", locale) in links
    if key == "que-hacer-despues-del-backtest":
        platforms = (
            "mt4",
            "mt5",
            "mt5-optimization",
            "tradingview",
            "ninjatrader",
            "quantconnect",
            "backtesting-py",
            "vectorbt",
            "csv-universal",
            "myfxbook",
            "fxblue",
        )
        assert {guide_url(platform, locale) for platform in platforms} <= links


def test_next_step_articles_are_reachable_from_indexes_and_sitemap(client: TestClient) -> None:
    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    root = ElementTree.fromstring(sitemap.content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = {loc.text for loc in root.findall("s:url/s:loc", namespace)}
    for locale in LOCALES:
        index = client.get(articles_index_url(locale))
        assert index.status_code == 200
        for key in ARTICLE_KEYS:
            path = article_url(key, locale)
            assert path in _links(index.text)
            assert BASE + path in locations
            response = client.get(path)
            assert response.status_code == 200
            assert f"<html lang='{locale}'>" in response.text


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", ARTICLE_KEYS)
def test_next_step_articles_link_only_to_the_site(
    client: TestClient, key: str, locale: str
) -> None:
    # The nine pages as served: every href and src is relative or on the site's own host.
    response = client.get(article_url(key, locale))
    assert response.status_code == 200
    parsed = _parsed(response.text)
    own_host = urlsplit(BASE).hostname
    assert parsed.links
    for link in parsed.links | parsed.sources:
        target = urlsplit(link)
        relative = not target.scheme and not target.netloc
        assert relative or (target.scheme == "https" and target.hostname == own_host), (
            key,
            locale,
            link,
        )


@pytest.mark.parametrize("locale", LOCALES)
def test_wilson_table_uses_the_repository_interval_and_declared_evidence(locale: str) -> None:
    assert WIN_RATE_TRADE_COUNTS == (20, 45, 100, 300, 1000)
    assert WIN_RATE_RATES == (0.55, 0.60, 0.71)
    page = article_page(ARTICLES_BY_KEY[ARTICLE_KEYS[1]], locale=locale, base_url=BASE)
    table_match = re.search(r"<table class='article-wilson'>(.*?)</table>", page, re.S)
    assert table_match is not None
    table = table_match.group(1)
    headers = re.findall(r"<th scope='col'>(.*?)</th>", table)
    assert [_visible(header) for header in headers[1:]] == [
        f"{evidence_label('DECLARED', locale)} · {rate} %" for rate in (55, 60, 71)
    ]
    rows = re.findall(r"<tr><th scope='row'>(.*?)</tr>", table)
    assert len(rows) == len(WIN_RATE_TRADE_COUNTS)
    declared = evidence_label("DECLARED", locale)
    thousand = "1,000" if locale == "en" else "1.000"
    for row, trades in zip(rows, WIN_RATE_TRADE_COUNTS, strict=True):
        cells = re.findall(r"(?:^|<td>)(.*?)</(?:th|td)>", row)
        assert len(cells) == 4
        trade_text = _visible(cells[0])
        assert trade_text == f"{declared} · {thousand if trades == 1000 else trades}"
        for cell, rate in zip(cells[1:], WIN_RATE_RATES, strict=True):
            interval = win_rate_interval(rate, trades, locale)
            # One decimal percentage point rounds each bound by at most 0.0005.
            assert _interval_bounds(interval) == pytest.approx(_wilson(rate, trades), abs=0.0005)
            assert _visible(cell) == f"{declared} · {interval}"
            separator = r"\." if locale == "en" else ","
            assert re.fullmatch(rf"\d+{separator}\d–\d+{separator}\d %", interval)
    assert evidence_label("MEASURED", locale) not in _visible(table)
    # The worked example, pinned: the reader's own Wilson function rounds to 56.5-82.2 %.
    low, high = _wilson(0.71, 45)
    assert (round(low * 100, 1), round(high * 100, 1)) == (56.5, 82.2)
    expected_example = "56.5–82.2 %" if locale == "en" else "56,5–82,2 %"
    assert win_rate_interval(0.71, 45, locale) == expected_example
    assert expected_example in _visible(table)
    assert find_claims(_visible(table)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_wilson_table_follows_the_calculation_section(locale: str) -> None:
    heading = {
        "es": "Cómo se calculó la tabla",
        "en": "How the table was calculated",
        "pt": "Como a tabela foi calculada",
    }[locale]
    page = article_page(ARTICLES_BY_KEY[ARTICLE_KEYS[1]], locale=locale, base_url=BASE)
    sections = ARTICLES_BY_KEY[ARTICLE_KEYS[1]].text[locale].sections
    assert heading in [section.heading for section in sections]
    headings = [
        (match.start(), _visible(match.group(1)).strip())
        for match in re.finditer(r"<h2\b[^>]*>(.*?)</h2>", page, re.S)
    ]
    titles = [text for _, text in headings]
    assert titles.count(heading) == 1, titles
    index = titles.index(heading)
    # The table is its own section, and that section comes immediately after the explanation.
    assert headings[index + 1][1] == WIN_RATE_TABLE_COPY[locale][0]
    table = re.search(r"<table class='article-wilson'>", page)
    assert table is not None
    assert headings[index + 1][0] < table.start() < headings[index + 2][0]


@pytest.mark.parametrize("locale", LOCALES)
def test_win_rate_reader_link_reproduces_the_declared_example(
    client: TestClient, locale: str
) -> None:
    page = article_page(ARTICLES_BY_KEY[ARTICLE_KEYS[1]], locale=locale, base_url=BASE)
    example_links = [
        link
        for link in _links(page)
        if urlsplit(link).path == READING_PATH[locale] and urlsplit(link).query
    ]
    assert len(example_links) == 1
    expected = {
        "ref": ["lectura"],
        "trades": ["45"],
        "win_rate": ["71"],
        "sharpe": ["1.8"],
        "years": ["3"],
        "trials": ["100"],
    }
    link = example_links[0]
    assert parse_qs(urlsplit(link).query) == expected
    response = client.get(link)
    assert response.status_code == 200
    reading = re.search(r'<g data-reading="wilson"[^>]*>(.*?)</g>', response.text, re.S)
    assert reading is not None
    table = re.search(r"<table class='article-wilson'>(.*?)</table>", page, re.S)
    assert table is not None
    expected_interval = "56.5–82.2 %" if locale == "en" else "56,5–82,2 %"
    assert expected_interval in _visible(table.group(1))
    # The reader's card prints each bound through public_card._pct in the article's
    # typography: a decimal comma in es and pt, a point in en. Same bounds, same separator.
    reader_text = _visible(reading.group(1))
    low, high = _wilson(0.71, 45)
    assert f"{_pct(low, locale)} – {_pct(high, locale)}" in reader_text
    assert ("56.5 % – 82.2 %" if locale == "en" else "56,5 % – 82,2 %") in reader_text
    assert ("56,5" if locale == "en" else "56.5") not in reader_text
    assert _interval_bounds(reader_text) == _interval_bounds(expected_interval)


@pytest.mark.parametrize("locale", LOCALES)
def test_optimizer_article_distinguishes_trial_evidence(locale: str) -> None:
    prose = _paragraphs(ARTICLE_KEYS[2], locale)
    phrases = {
        "es": (
            "DECLARED identifica el número de intentos que escribes.",
            "MEASURED identifica los que cuentan los archivos: pasadas del XML, "
            "columnas de una matriz de variantes o variantes presentes en un informe.",
            "Rigor usa la mayor cuenta disponible entre la declaración y esos archivos; "
            "una declaración menor no reduce el número documentado.",
            "NOT_MEASURED identifica la falta de una cuenta cuando no la declaras "
            "ni aparece en los archivos.",
            "En ese caso el cálculo asume un solo intento, el caso más favorable, "
            "y muestra la limitación.",
            "Ejecuta después una prueba simple con los parámetros elegidos y guarda "
            "su informe HTML.",
            "El XML contiene resúmenes por pasada, no las operaciones del resultado "
            "seleccionado: los archivos aportan piezas diferentes.",
        ),
        "en": (
            "DECLARED identifies the attempt count you enter.",
            "MEASURED identifies counts from files: XML passes, columns in a variants "
            "matrix or variants present in a report.",
            "Rigor uses the largest available count across the declaration and those files; "
            "a lower declaration cannot reduce the documented count.",
            "NOT_MEASURED identifies a missing count when neither your declaration "
            "nor the files supplies one.",
            "The calculation then assumes a single attempt, the most favourable case, "
            "and shows the limitation.",
            "Then run a single test with the chosen parameters and save its HTML report.",
            "The XML contains summaries per pass, not the selected result's trades: "
            "the files supply different pieces of evidence.",
        ),
        "pt": (
            "DECLARED identifica a quantidade de tentativas que você informa.",
            "MEASURED identifica o que os arquivos contam: passadas do XML, "
            "colunas de uma matriz de variantes ou variantes presentes num relatório.",
            "O Rigor usa a maior contagem disponível entre a declaração e esses arquivos; "
            "uma declaração menor não reduz a quantidade documentada.",
            "NOT_MEASURED identifica a ausência de contagem quando você não a declara "
            "e ela não aparece nos arquivos.",
            "Nesse caso, o cálculo supõe uma única tentativa, o caso mais favorável, "
            "e mostra a limitação.",
            "Depois execute um teste único com os parâmetros escolhidos e salve "
            "seu relatório HTML.",
            "O XML contém resumos por passada, não as operações do resultado selecionado: "
            "os arquivos fornecem evidências diferentes.",
        ),
    }
    for phrase in phrases[locale]:
        assert phrase in prose


@pytest.mark.parametrize("key", ARTICLE_KEYS)
def test_next_step_english_prose_uses_british_spelling(key: str) -> None:
    words = ARTICLES_BY_KEY[key].text["en"]
    prose = " ".join(
        [words.title, words.summary, words.seo_title or words.title, _paragraphs(key, "en")]
        + [section.heading for section in words.sections]
        + [text for pair in words.faq for text in pair]
    )
    # Product menu names retain their exact spelling so readers can find them.
    prose = prose.replace("Optimization Results", "").replace("Strategy Analyzer", "")
    american = (
        r"\b(?:optimiz\w*|favor\w*|analyz\w*|center\w*|summariz\w*|behavior\w*|organiz\w*"
        r"|recogniz\w*|color\w*|modeling|labeled)\b"
    )
    assert re.search(american, prose, re.I) is None


def test_optimizer_english_title_preserves_the_published_slug() -> None:
    words = ARTICLES_BY_KEY[ARTICLE_KEYS[2]].text["en"]
    assert words.title == "Did the optimiser pick your result?"
    assert article_url(ARTICLE_KEYS[2], "en") == "/articles/did-the-optimizer-pick-your-result"


@pytest.mark.parametrize("locale", LOCALES)
def test_after_backtest_cost_example_is_computed_and_declared(locale: str) -> None:
    trade = COST_EXAMPLE_TRADE
    assert (trade.quantity, trade.entry_price, trade.exit_price) == (1.0, 100.0, 101.0)
    assert (trade.pnl, trade.return_pct) == (1.0, 0.01)
    expected = break_even_bps([trade], ["long"], reported_costs=[0.0])
    assert expected is not None
    assert f"{expected:.2f}" == "49.75"
    words = ARTICLES_BY_KEY[ARTICLE_KEYS[0]].text[locale]
    example = next(
        paragraph
        for section in words.sections
        for paragraph in section.paragraphs
        if "break_even_bps" in paragraph
    )
    # Running text carries no evidence label; the example says it is one itself.
    assert not example.startswith("DECLARED")
    assert ("49.75" if locale == "en" else "49,75") in example
    assert find_claims(example) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_shared_luck_example_is_computed_and_localized(locale: str) -> None:
    example = INDEPENDENT_LUCK_EXAMPLE[locale]
    assert not example.startswith("DECLARED")
    expected = compute(LUCK_EXAMPLE_INPUT)["luck_sharpe"]["value"]
    assert round(expected, 2) == 1.47
    assert ("1.47" if locale == "en" else "1,47") in example
    assert ("1.8" if locale == "en" else "1,8") in example
    assert find_claims(example) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", (ARTICLE_KEYS[0], ARTICLE_KEYS[2]))
def test_selection_example_links_to_the_deflated_sharpe_article(key: str, locale: str) -> None:
    prose = _paragraphs(key, locale)
    assert INDEPENDENT_LUCK_EXAMPLE[locale] not in prose
    citation = {
        "es": "artículo enlazado sobre el Sharpe deflactado",
        "en": "linked article on deflated Sharpe",
        "pt": "artigo vinculado sobre o Sharpe deflacionado",
    }[locale]
    assert citation in prose
    page = article_page(ARTICLES_BY_KEY[key], locale=locale, base_url=BASE)
    assert article_url("sharpe-deflactado-track-record", locale) in _links(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_deflated_sharpe_link_resolves_to_the_luck_example(client: TestClient, locale: str) -> None:
    target = article_url("sharpe-deflactado-track-record", locale)
    for key in (ARTICLE_KEYS[0], ARTICLE_KEYS[2]):
        page = client.get(article_url(key, locale))
        assert page.status_code == 200
        assert target in _links(page.text)
    response = client.get(target)
    assert response.status_code == 200
    assert f"<html lang='{locale}'>" in response.text
    # The example the two new articles cite is printed, computed, on the linked page.
    example = localize_tags(INDEPENDENT_LUCK_EXAMPLE[locale], locale)
    assert html.escape(example, quote=True) in response.text


def test_editorial_numbers_swap_both_separators_outside_english() -> None:
    assert _num(1000, "en", 0) == "1,000"
    assert _num(1000, "es", 0) == _num(1000, "pt", 0) == "1.000"
    assert _num(1234.5, "en", 1) == "1,234.5"
    assert _num(1234.5, "es", 1) == _num(1234.5, "pt", 1) == "1.234,5"
    assert _num(49.746, "es", 2) == "49,75"


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", ARTICLE_KEYS)
def test_next_step_figures_use_the_language_decimal_separator(key: str, locale: str) -> None:
    prose = _prose(article_page(ARTICLES_BY_KEY[key], locale=locale, base_url=BASE))
    # One or two decimals are editorial figures; a group of three digits is a thousand.
    wrong = r"\b\d+,\d{1,2}\b" if locale == "en" else r"\b\d+\.\d{1,2}\b"
    assert re.findall(wrong, prose) == []
    expected: tuple[str, ...] = ()
    if key == ARTICLE_KEYS[0]:
        expected = ("49.75", "56.5–82.2 %") if locale == "en" else ("49,75", "56,5–82,2 %")
    elif key == ARTICLE_KEYS[1]:
        expected = ("1.8", "56.5–82.2 %") if locale == "en" else ("1,8", "56,5–82,2 %")
    for figure in expected:
        assert figure in prose


CLOSINGS = {
    ARTICLE_KEYS[1]: {
        "es": (
            "Abre el ejemplo en el lector de cifras enlazado y cambia operaciones y porcentaje "
            "para ver cómo se mueve el intervalo bajo estos supuestos."
        ),
        "en": (
            "Open the example in the linked figure reader and change the trade count and win "
            "rate to see how the interval moves under these assumptions."
        ),
        "pt": (
            "Abra o exemplo no leitor de números vinculado e altere operações e porcentagem "
            "para ver como o intervalo se move sob essas suposições."
        ),
    },
    ARTICLE_KEYS[2]: {
        "es": (
            "Sigue la guía enlazada para exportar el XML de optimización de MetaTrader 5 y "
            "conserva todas las pasadas junto al informe de la configuración elegida."
        ),
        "en": (
            "Follow the linked guide to exporting the MetaTrader 5 optimisation XML and keep "
            "every pass alongside the chosen configuration's report."
        ),
        "pt": (
            "Siga o guia vinculado para exportar o XML de otimização do MetaTrader 5 e preserve "
            "todas as passadas junto ao relatório da configuração escolhida."
        ),
    },
}
ACCOUNT_OFFER = {
    "es": ("no piden cuenta", "el primer informe completo es gratis con cuenta"),
    "en": ("need no account", "your first full report is free with an account"),
    "pt": ("não exigem conta", "o primeiro relatório completo é grátis com conta"),
}


@pytest.mark.parametrize("locale", LOCALES)
def test_only_the_first_article_closes_with_the_account_offer(locale: str) -> None:
    first = " ".join(ARTICLES_BY_KEY[ARTICLE_KEYS[0]].text[locale].sections[-1].paragraphs)
    for phrase in ACCOUNT_OFFER[locale]:
        assert phrase in first
    for key in ARTICLE_KEYS[1:]:
        words = ARTICLES_BY_KEY[key].text[locale]
        stored = " ".join([_paragraphs(key, locale)] + [a for _, a in words.faq]).lower()
        for phrase in ACCOUNT_OFFER[locale]:
            assert phrase not in stored, (key, phrase)
        assert not re.search(r"\b(?:gratis|free|grátis)\b", stored), key
        # A closing of its own: one sentence that points to a linked page.
        closing = words.sections[-1].paragraphs[-1]
        assert closing == CLOSINGS[key][locale]
        assert closing.count(".") == 1 and closing.endswith(".")
        assert find_claims(closing) == []
    assert {"kind": "reading", "example": "win-rate"} in ARTICLES_BY_KEY[ARTICLE_KEYS[1]].related
    assert {"kind": "guide", "slug": "mt5-optimization"} in ARTICLES_BY_KEY[ARTICLE_KEYS[2]].related
