"""The next-step articles keep translations, examples and public discovery aligned."""

from __future__ import annotations

import html
import json
import re
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
    WIN_RATE_TRADE_COUNTS,
    article_url,
    articles_index_url,
    win_rate_interval,
)
from quant_trade.audit.calculator import calculator_url, compute  # noqa: E402
from quant_trade.audit.costs import break_even_bps  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import guide_url  # noqa: E402
from quant_trade.audit.pages import article_page  # noqa: E402
from quant_trade.audit.public_card import _wilson  # noqa: E402
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


def _links(page: str) -> set[str]:
    return {html.unescape(href) for href in re.findall(r"href='([^']*)'", page)}


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
def test_wilson_table_uses_the_repository_interval_and_declared_evidence(locale: str) -> None:
    assert WIN_RATE_TRADE_COUNTS == (20, 45, 100, 300, 1000)
    assert WIN_RATE_RATES == (0.55, 0.60, 0.71)
    page = article_page(ARTICLES_BY_KEY[ARTICLE_KEYS[1]], locale=locale, base_url=BASE)
    table_match = re.search(r"<table class='article-wilson'>(.*?)</table>", page, re.S)
    assert table_match is not None
    table = table_match.group(1)
    rows = re.findall(r"<tr><th scope='row'>(.*?)</tr>", table)
    assert len(rows) == len(WIN_RATE_TRADE_COUNTS)
    declared = evidence_label("DECLARED", locale)
    for row, trades in zip(rows, WIN_RATE_TRADE_COUNTS, strict=True):
        cells = re.findall(r"(?:^|<td>)(.*?)</(?:th|td)>", row)
        assert len(cells) == 4
        trade_text = _visible(cells[0])
        assert declared in trade_text
        assert re.sub(r"\D", "", trade_text) == str(trades)
        for cell, rate in zip(cells[1:], WIN_RATE_RATES, strict=True):
            low, high = _wilson(rate, trades)
            expected = f"{low * 100:.1f}–{high * 100:.1f} %"
            if locale != "en":
                expected = expected.replace(".", ",")
            assert win_rate_interval(rate, trades, locale) == expected
            assert _visible(cell) == f"{declared} · {expected}"
    assert evidence_label("MEASURED", locale) not in _visible(table)
    expected_example = "56.5–82.2 %" if locale == "en" else "56,5–82,2 %"
    assert expected_example in _visible(table)
    assert find_claims(_visible(table)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_win_rate_reader_link_reproduces_the_declared_example(locale: str) -> None:
    page = article_page(ARTICLES_BY_KEY[ARTICLE_KEYS[1]], locale=locale, base_url=BASE)
    example_links = [
        link
        for link in _links(page)
        if urlsplit(link).path == READING_PATH[locale] and urlsplit(link).query
    ]
    assert example_links
    expected = {
        "trades": ["45"],
        "win_rate": ["71"],
        "sharpe": ["1.8"],
        "years": ["3"],
        "trials": ["100"],
    }
    assert any(
        all(parse_qs(urlsplit(link).query).get(key) == value for key, value in expected.items())
        for link in example_links
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_optimizer_article_distinguishes_trial_evidence(locale: str) -> None:
    prose = _paragraphs(ARTICLE_KEYS[2], locale)
    assert "DECLARED" in prose
    assert "MEASURED" in prose
    assert "NOT_MEASURED" in prose
    assert "XML" in prose and "HTML" in prose
    assert "100" in prose


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
    assert example.startswith("DECLARED ·")
    assert f"{expected:.2f}" in example
    assert find_claims(example) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", (ARTICLE_KEYS[0], ARTICLE_KEYS[2]))
def test_selection_example_reuses_the_declared_calculator_inputs(key: str, locale: str) -> None:
    example = INDEPENDENT_LUCK_EXAMPLE[locale]
    assert example.startswith("DECLARED ·")
    expected = compute(LUCK_EXAMPLE_INPUT)["luck_sharpe"]["value"]
    assert f"{expected:.2f}" in example
    assert example in _paragraphs(key, locale)
    page = article_page(ARTICLES_BY_KEY[key], locale=locale, base_url=BASE)
    assert localize_tags(example, locale) in _visible(page)
