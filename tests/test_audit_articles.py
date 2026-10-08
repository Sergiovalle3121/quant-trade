"""Articles about backtests: three languages, metadata, the guard, the sitemap
and the redirect of a slug from another language."""

from __future__ import annotations

import html
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.articles import (  # noqa: E402
    ARTICLES,
    ARTICLES_BY_SLUG,
    ARTICLES_COPY,
    ARTICLES_DATA,
    ARTICLES_PATH,
    INDEPENDENT_LUCK_EXAMPLE,
    LUCK_EXAMPLE_INPUT,
    LUCK_TABLE_INPUTS,
    Article,
    article_url,
    articles_index_url,
    find_article,
    related_links,
)
from quant_trade.audit.calculator import CalculatorInput, calculator_url, compute  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import GUIDES_COPY, guides_index_url  # noqa: E402
from quant_trade.audit.pages import CONTACT_PATHS, article_page, audit_path  # noqa: E402
from quant_trade.audit.redflags import FLAG_TITLES  # noqa: E402
from quant_trade.audit.report import evidence_label, localize_tags  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.theme import STYLE as THEME_CSS  # noqa: E402
from quant_trade.audit.web import ENGLISH_ROOTS, create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
#: Spanish words that must not appear on a Portuguese page.
SPANISH_ON_PT = ("Sube ", "archivo", "Precios", "Empezar", "cuenta gratis", "informe", "artículo")
#: Every shape ``ARTICLES_DATA`` entries must have, so a pasted article fails
#: here and not on a page.
DATA_KEYS = {"key", "slug", "title", "summary", "intro", "sections", "faq", "related"}


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _meta(text: str, key: str) -> str | None:
    match = re.search(rf"<meta (?:name|property)='{re.escape(key)}' content='([^']*)'>", text)
    return html.unescape(match.group(1)) if match else None


def _canonical(text: str) -> str | None:
    match = re.search(r"<link rel='canonical' href='([^']*)'>", text)
    return html.unescape(match.group(1)) if match else None


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _texts(article: Article, locale: str) -> list[str]:
    text = article.text[locale]
    words = [text.title, text.summary, text.intro]
    if text.seo_title is not None:
        words.append(text.seo_title)
    for section in text.sections:
        words += [section.heading, *section.paragraphs]
    for question, answer in text.faq:
        words += [question, answer]
    return words


def test_the_data_has_the_shape_the_writer_pastes() -> None:
    assert [entry["key"] for entry in ARTICLES_DATA] == [
        "ea-sobreoptimizado",
        "backtest-costos-reales",
        "leer-informe-probador-mt5",
        "auditoria-independiente-backtest",
        "sharpe-deflactado-track-record",
        "auditar-cartera-modelo-senales",
        "cuantos-intentos-reto-prop-firm",
        "copiar-senales-mql5-myfxbook",
        "bot-ia-backtest-suerte",
        "que-hacer-despues-del-backtest",
        "cuantas-operaciones-porcentaje-aciertos",
        "lo-eligio-el-optimizador",
    ]
    for entry in ARTICLES_DATA:
        assert DATA_KEYS <= set(entry) <= DATA_KEYS | {"seo_title"}, entry["key"]
        assert set(entry.get("seo_title", {})) <= set(LOCALES), entry["key"]
        for field in ("slug", "title", "summary", "intro", "sections", "faq"):
            assert set(entry[field]) == set(LOCALES), (entry["key"], field)
        for locale in LOCALES:
            for section in entry["sections"][locale]:
                assert set(section) == {"heading", "paragraphs"}
            for item in entry["faq"][locale]:
                assert set(item) == {"q", "a"}
        for link in entry["related"]:
            assert link["kind"] in {
                "calculator",
                "guide",
                "audience",
                "method",
                "contact",
                "samples",
                "reading",
            }
            assert ("slug" in link) == (link["kind"] in {"guide", "audience"})


def test_every_article_exists_in_every_language_and_passes_the_guard() -> None:
    assert ARTICLES_PATH == {"es": "/articulos", "en": "/articles", "pt": "/pt/artigos"}
    slugs = {article.key: article.slug for article in ARTICLES}
    assert slugs == {
        "ea-sobreoptimizado": {
            "es": "ea-sobreoptimizado",
            "en": "overfitted-expert-advisor",
            "pt": "ea-sobreajustado",
        },
        "backtest-costos-reales": {
            "es": "backtest-costos-reales",
            "en": "backtest-real-costs",
            "pt": "backtest-custos-reais",
        },
        "leer-informe-probador-mt5": {
            "es": "leer-informe-probador-mt5",
            "en": "read-mt5-strategy-tester-report",
            "pt": "ler-relatorio-testador-mt5",
        },
        "auditoria-independiente-backtest": {
            "es": "auditoria-independiente-backtest",
            "en": "independent-backtest-audit",
            "pt": "auditoria-independente-backtest",
        },
        "sharpe-deflactado-track-record": {
            "es": "sharpe-deflactado-track-record",
            "en": "deflated-sharpe-ratio-track-record",
            "pt": "sharpe-deflacionado-historico",
        },
        "auditar-cartera-modelo-senales": {
            "es": "auditar-cartera-modelo-senales",
            "en": "audit-model-portfolio-signal-track-record",
            "pt": "auditar-carteira-modelo-sinais",
        },
        "cuantos-intentos-reto-prop-firm": {
            "es": "cuantos-intentos-reto-prop-firm",
            "en": "how-many-prop-firm-challenge-attempts",
            "pt": "quantas-tentativas-desafio-prop-firm",
        },
        "copiar-senales-mql5-myfxbook": {
            "es": "copiar-senales-mql5-myfxbook",
            "en": "copying-mql5-myfxbook-signals",
            "pt": "copiar-sinais-mql5-myfxbook",
        },
        "bot-ia-backtest-suerte": {
            "es": "bot-ia-backtest-suerte",
            "en": "ai-trading-bot-backtest-luck",
            "pt": "bot-ia-backtest-sorte",
        },
        "que-hacer-despues-del-backtest": {
            "es": "que-hacer-despues-del-backtest",
            "en": "what-to-do-after-a-backtest",
            "pt": "o-que-fazer-depois-do-backtest",
        },
        "cuantas-operaciones-porcentaje-aciertos": {
            "es": "cuantas-operaciones-porcentaje-aciertos",
            "en": "how-many-trades-to-trust-a-win-rate",
            "pt": "quantas-operacoes-taxa-de-acerto",
        },
        "lo-eligio-el-optimizador": {
            "es": "lo-eligio-el-optimizador",
            "en": "did-the-optimizer-pick-your-result",
            "pt": "o-otimizador-escolheu-o-resultado",
        },
    }
    for article in ARTICLES:
        assert set(article.text) == set(LOCALES)
        for locale in LOCALES:
            text = article.text[locale]
            assert text.sections and text.faq, (article.key, locale)
            assert 40 <= len(text.summary) < 160, (article.key, locale)
            for words in _texts(article, locale):
                assert find_claims(words) == [], (article.key, locale, words)
            # Every related page resolves to a title and a path in this language.
            links = related_links(article, locale)
            assert len(links) == len(article.related)
            for label, href in links:
                assert label and href.startswith("/"), (article.key, locale, href)
                assert (locale == "pt") == href.startswith("/pt/"), (article.key, locale, href)
    for locale, copy in ARTICLES_COPY.items():
        assert set(copy) == set(ARTICLES_COPY["es"]), locale
        for words in copy.values():
            assert find_claims(words) == [], (locale, words)


def test_an_unknown_related_kind_or_slug_is_refused() -> None:
    for link, message in (
        ({"kind": "shop"}, "unknown related kind"),
        ({"kind": "guide", "slug": "nope"}, "unknown guide"),
        ({"kind": "guide"}, "unknown guide"),
        ({"kind": "audience", "slug": "nadie"}, "unknown audience page"),
    ):
        bad = {**ARTICLES_DATA[0], "related": [link]}
        with pytest.raises(ValueError, match=message):
            Article.from_dict(bad)


def test_the_red_flag_count_in_the_mt5_article_follows_the_catalog() -> None:
    article = next(a for a in ARTICLES if a.key == "leer-informe-probador-mt5")
    for locale in LOCALES:
        assert f" {len(FLAG_TITLES)} " in " ".join(_texts(article, locale)), locale


def test_the_resolver_finds_a_slug_from_any_language() -> None:
    article = ARTICLES[0]
    assert find_article("ea-sobreoptimizado", "es") == (article, "es")
    assert find_article("overfitted-expert-advisor", "es") == (article, "en")
    assert find_article("ea-sobreajustado", "en") == (article, "pt")
    assert find_article("nope", "pt") is None
    assert article_url("ea-sobreoptimizado", "en") == "/articles/overfitted-expert-advisor"
    assert article_url("ea-sobreoptimizado", "pt") == "/pt/artigos/ea-sobreajustado"
    for locale in LOCALES:
        assert len(ARTICLES_BY_SLUG[locale]) == len(ARTICLES)


def test_article_pages_render_with_metadata_and_a_language_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for locale in LOCALES:
        others = [lang for lang in LOCALES if lang != locale]
        index = client.get(articles_index_url(locale))
        assert index.status_code == 200
        assert f"<html lang='{locale}'>" in index.text
        assert _meta(index.text, "description") == ARTICLES_COPY[locale]["summary"]
        assert _meta(index.text, "robots") == "index, follow"
        assert _canonical(index.text) == BASE + articles_index_url(locale)
        assert find_claims(index.text) == []
        for other in others:
            assert f"hreflang='{other}' href='{BASE}{articles_index_url(other)}'" in index.text
        for article in ARTICLES:
            assert f"href='{article_url(article.key, locale)}'" in index.text
            page = client.get(article_url(article.key, locale))
            assert page.status_code == 200
            text = page.text
            assert "x-robots-tag" not in page.headers
            assert f"<html lang='{locale}'>" in text
            assert html.escape(article.text[locale].title, quote=True) in text
            seo_title = article.text[locale].seo_title or article.text[locale].title
            assert f"<title>{html.escape(seo_title, quote=True)} · Rigor</title>" in text
            assert _meta(text, "description") == article.text[locale].summary
            assert _meta(text, "robots") == "index, follow"
            assert _canonical(text) == BASE + article_url(article.key, locale)
            assert "hreflang='x-default'" in text
            for other in others:
                assert f"hreflang='{other}' href='{BASE}{article_url(article.key, other)}'" in text
                assert f"href='{article_url(article.key, other)}'" in text  # the switch
            for section in article.text[locale].sections:
                assert html.escape(section.heading, quote=True) in text
            for question, _answer in article.text[locale].faq:
                assert f"<h3>{html.escape(question, quote=True)}</h3>" in text
            for _label, href in related_links(article, locale):
                assert f"href='{html.escape(href, quote=True)}'" in text, (
                    article.key,
                    locale,
                    href,
                )
            # The closing call: the free calculator and the form, no promise.
            assert f"href='{calculator_url(locale)}'" in text
            assert f"href='{audit_path(locale)}'" in text
            assert html.escape(ARTICLES_COPY[locale]["calculator"], quote=True) in text
            assert html.escape(ARTICLES_COPY[locale]["report"], quote=True) in text
            assert "<section class='article-cta'><h2>" in text
            assert find_claims(text) == []
    assert ".article-cta{" in THEME_CSS and ".article-cta h2{" in THEME_CSS


def test_portuguese_article_pages_have_no_spanish_left(tmp_path: Path) -> None:
    client = _client(tmp_path)
    paths = [articles_index_url("pt")] + [article_url(a.key, "pt") for a in ARTICLES]
    for path in paths:
        text = _text(client.get(path).text)
        for spanish in SPANISH_ON_PT:
            assert spanish not in text, (path, spanish)
    for article in ARTICLES:
        for words in _texts(article, "pt"):
            for spanish in SPANISH_ON_PT:
                assert spanish not in words, (article.key, spanish)


def test_a_slug_from_another_language_moves_and_an_unknown_one_is_missing(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    for path, target in (
        ("/articles/ea-sobreoptimizado", "/articles/overfitted-expert-advisor"),
        ("/articulos/overfitted-expert-advisor", "/articulos/ea-sobreoptimizado"),
        ("/pt/artigos/backtest-costos-reales", "/pt/artigos/backtest-custos-reais"),
        ("/articulos/ler-relatorio-testador-mt5", "/articulos/leer-informe-probador-mt5"),
    ):
        moved = client.get(path, follow_redirects=False)
        assert moved.status_code == 301 and moved.headers["location"] == target, path
    for path, locale in (
        ("/articulos/nada", "es"),
        ("/articles/nope", "en"),
        ("/pt/artigos/x", "pt"),
    ):
        missing = client.get(path)
        assert missing.status_code == 404, path
        assert f"<html lang='{locale}'>" in missing.text
        assert missing.headers["x-robots-tag"] == "noindex, nofollow"


def test_the_sitemap_and_the_route_tables_list_every_article(tmp_path: Path) -> None:
    assert {lang: articles_index_url(lang) for lang in LOCALES} in PUBLIC_PAGES
    for article in ARTICLES:
        assert {lang: article_url(article.key, lang) for lang in LOCALES} in PUBLIC_PAGES
    assert "articles" in ENGLISH_ROOTS and "articulos" not in ENGLISH_ROOTS
    root = ElementTree.fromstring(_client(tmp_path).get("/sitemap.xml").content)
    locs = {loc.text for loc in root.findall("s:url/s:loc", SITEMAP_NS)}
    for locale in LOCALES:
        assert BASE + articles_index_url(locale) in locs
        for article in ARTICLES:
            assert BASE + article_url(article.key, locale) in locs, (article.key, locale)


def test_the_guides_index_links_the_articles(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for locale in LOCALES:
        page = client.get(guides_index_url(locale)).text
        assert f"href='{articles_index_url(locale)}'" in page, locale
        assert html.escape(GUIDES_COPY[locale]["articles"], quote=True) in page


@pytest.mark.parametrize("locale", LOCALES)
def test_institutional_articles_length_and_calculator_evidence(locale: str) -> None:
    from quant_trade.audit.examples import EXAMPLES_PATH

    institutional = [
        next(article for article in ARTICLES if article.key == key)
        for key in (
            "auditoria-independiente-backtest",
            "sharpe-deflactado-track-record",
            "auditar-cartera-modelo-senales",
        )
    ]
    for article in institutional:
        text = article.text[locale]
        body = [text.intro]
        for section in text.sections:
            body += [section.heading, *section.paragraphs]
        body += [words for pair in text.faq for words in pair]
        assert 700 <= len(" ".join(body).split()) <= 1100, (article.key, locale)
        assert find_claims(" ".join(body)) == []
        rendered = article_page(article, locale=locale, base_url=BASE)
        prose = re.search(r"<article class='prose'>(.*?)</article>", rendered, re.S)
        assert prose is not None
        # Include the calculator table and its explanation, not just stored prose.
        assert 700 <= len(_text(prose.group(1)).split()) <= 1100, (article.key, locale)

    example = INDEPENDENT_LUCK_EXAMPLE[locale]
    assert example.startswith("DECLARED ·")
    expected = compute(LUCK_EXAMPLE_INPUT)["luck_sharpe"]["value"]
    assert f"{expected:.2f}" in example
    independent = article_page(institutional[0], locale=locale, base_url=BASE)
    assert html.escape(localize_tags(example, locale), quote=True) in independent

    assert {(v.trials, v.years) for v in LUCK_TABLE_INPUTS} == {
        (trials, years) for trials in (10, 100, 1000) for years in (1, 3, 5)
    }
    sharpe_page = article_page(institutional[1], locale=locale, base_url=BASE)
    table = re.search(r"<table class='article-luck'>(.*?)</table>", sharpe_page, re.S)
    assert table is not None
    rows = re.findall(r"<tr><th scope='row'>(.*?)</tr>", table.group(1))
    assert len(rows) == 9
    declared = evidence_label("DECLARED", locale)
    for row, value in zip(rows, LUCK_TABLE_INPUTS, strict=True):
        expected = compute(CalculatorInput(1.8, value.years, value.trials))["luck_sharpe"]["value"]
        assert _text(row).split() == [
            declared,
            "·",
            f"{value.trials:,}",
            declared,
            "·",
            f"{value.years:g}",
            declared,
            "·",
            f"{expected:.2f}",
        ]
    assert find_claims(_text(table.group(1))) == []
    assert evidence_label("MEASURED", locale) not in table.group(1)

    portfolio = article_page(institutional[2], locale=locale, base_url=BASE)
    assert f"href='{CONTACT_PATHS[locale]}'" in portfolio
    assert f"href='{EXAMPLES_PATH[locale]}'" in portfolio
