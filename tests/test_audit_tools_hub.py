"""The free tools page, its place in the menu and landing, and the guessed addresses."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import reading, seo  # noqa: E402
from quant_trade.audit.articles import article_url, articles_index_url  # noqa: E402
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.calculator import calculator_url  # noqa: E402
from quant_trade.audit.examples import EXAMPLES_PATH  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import guides_index_url  # noqa: E402
from quant_trade.audit.pages import _sample_url, audit_path, landing  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import COPY, TOOL_KEYS, TOOLS_PATH, tools_url  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.audit.winrate import WINRATE_PATH  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
#: The figures of tests/test_audit_public_reading.py.
FIGURES = {
    "trades": "45",
    "win_rate": "71",
    "profit_factor": "3.24",
    "sharpe": "1.8",
    "years": "3",
    "trials": "1000",
    "target_r": "1",
    "stop_r": "1",
}
#: Addresses people guess, each with the page it now forwards to (task 11).
GUESSED = (
    ("/en/calculator", "/calculator"),
    ("/reading", "/en/reading"),
    ("/en/methodology", "/methodology"),
    ("/en/articles", "/articles"),
    ("/en/guides", "/guides"),
    ("/en/sample", "/sample"),
    ("/en/check", "/check"),
    ("/faq", "/en/faq"),
    ("/examples", "/en/examples"),
    ("/tools", "/en/tools"),
    ("/pt/tools", "/pt/ferramentas"),
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _hrefs(page: str) -> set[str]:
    return {html.unescape(value) for value in re.findall(r"\bhref=['\"]([^'\"]*)", page)}


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _texts(value: object) -> Iterator[str]:
    """Every string in a copy entry, however it is nested."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _texts(item)


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_hub_is_public_in_every_language(client: TestClient, locale: str) -> None:
    path = TOOLS_PATH[locale]
    assert dict(TOOLS_PATH) in seo.PUBLIC_PAGES
    response = client.get(path)
    assert response.status_code == 200
    text = response.text
    assert f"<html lang='{locale}'>" in text
    assert text.count("<h1") == 1
    assert "<meta name='robots' content='index, follow'>" in text
    assert f"<link rel='canonical' href='{BASE}{path}'>" in text
    for lang, alternate in TOOLS_PATH.items():
        assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{alternate}'>" in text
    assert f"<link rel='alternate' hreflang='x-default' href='{BASE}{TOOLS_PATH['es']}'>" in text
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", text, re.S)
    assert blocks
    data = [json.loads(block) for block in blocks]
    tools = next(item for item in data if item.get("@type") == "ItemList")
    apps = [element["item"] for element in tools["itemListElement"]]
    # One entry per tool on the page: the luck calculator, the win-rate calculator
    # (added after this page shipped), the figure reader and the report check.
    assert len(apps) == len(TOOL_KEYS) == 4
    for app in apps:
        assert app["@type"] == "WebApplication"
        assert app["isAccessibleForFree"] is True
        assert app["inLanguage"] == locale
        assert app["offers"] == {"@type": "Offer", "price": "0", "priceCurrency": "USD"}
        assert app["url"].startswith(BASE + "/")
    raw = "".join(blocks)
    assert "WebApplication" in raw and '"isAccessibleForFree": true' in raw
    assert find_claims(html.unescape(text)) == []
    for item in _texts(COPY[locale]):
        assert find_claims(item) == [], item


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_hub_links_every_free_tool(client: TestClient, locale: str) -> None:
    hrefs = _hrefs(_main(client.get(TOOLS_PATH[locale]).text))
    assert calculator_url(locale) in hrefs
    assert WINRATE_PATH[locale] in hrefs
    assert reading.READING_PATH[locale] in hrefs
    assert seo.CHECK_PATH[locale] in hrefs
    assert audit_path(locale) in hrefs
    assert articles_index_url(locale) in hrefs
    assert _sample_url(locale) in hrefs


def test_tools_hub_metadata_is_unique_and_in_bounds() -> None:
    from quant_trade.audit.pages import tools_page

    titles = set()
    for locale in LOCALES:
        page = tools_page(locale=locale, base_url=BASE)
        title = re.search(r"<title>(.*?)</title>", page).group(1)  # type: ignore[union-attr]
        description = re.search(  # type: ignore[union-attr]
            r"<meta name='description' content='([^']*)'>", page
        ).group(1)
        assert 15 <= len(html.unescape(title)) <= 65, title
        assert 50 <= len(html.unescape(description)) <= 160, description
        titles.add(title)
    assert len(titles) == 3


def test_landing_shows_the_free_tools_band() -> None:
    for locale in LOCALES:
        main = _main(landing(locale=locale))
        hrefs = _hrefs(main)
        assert calculator_url(locale) in hrefs
        assert reading.READING_PATH[locale] in hrefs
        assert tools_url(locale) in hrefs
        assert COPY[locale]["band_lead"] in html.unescape(main)
        assert find_claims(html.unescape(main)) == []


@pytest.mark.parametrize(("alias", "target"), GUESSED)
def test_guessed_addresses_forward_301(client: TestClient, alias: str, target: str) -> None:
    response = client.get(alias, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == target
    assert client.get(target).status_code == 200


def test_guessed_addresses_keep_only_the_query_they_should(client: TestClient) -> None:
    calculator = client.get("/en/calculator?sharpe=1.8&years=3&trials=100", follow_redirects=False)
    assert calculator.status_code == 301
    assert calculator.headers["location"] == "/calculator?sharpe=1.8&years=3&trials=100"
    reader = client.get("/reading?trades=45", follow_redirects=False)
    assert reader.status_code == 301
    assert reader.headers["location"] == "/en/reading?trades=45"
    faq = client.get("/faq?x=1", follow_redirects=False)
    assert faq.status_code == 301
    assert faq.headers["location"] == "/en/faq"
    # The path is fixed: a query cannot send the visitor to another site.
    odd = client.get("/reading?next=https://elsewhere.example", follow_redirects=False)
    assert odd.headers["location"].startswith("/en/reading?")


@pytest.mark.parametrize("locale", LOCALES)
def test_reader_has_content_links_and_the_report_step(client: TestClient, locale: str) -> None:
    words = reading.COPY[locale]
    path = reading.READING_PATH[locale]
    empty = client.get(path)
    assert empty.status_code == 200
    hrefs = _hrefs(empty.text)
    for expected in (
        calculator_url(locale),
        article_url("cuantas-operaciones-porcentaje-aciertos", locale),
        tools_url(locale),
        audit_path(locale),
        _sample_url(locale),
        guides_index_url(locale),
    ):
        assert expected in hrefs, expected
    assert html.escape(words["beyond_title"], quote=True) in empty.text
    assert find_claims(html.unescape(empty.text)) == []
    filled = client.get(path, params=FIGURES)
    assert filled.status_code == 200
    text = filled.text
    beyond = html.escape(words["beyond_title"], quote=True)
    assert text.index(beyond) > text.index("data-public-share")
    assert find_claims(html.unescape(text)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_calculator_links_the_deflated_sharpe_article_and_the_reader(
    client: TestClient, locale: str
) -> None:
    page = client.get(calculator_url(locale))
    assert page.status_code == 200
    hrefs = _hrefs(page.text)
    assert article_url("sharpe-deflactado-track-record", locale) in hrefs
    assert reading.READING_PATH[locale] in _hrefs(_main(page.text))
    assert find_claims(html.unescape(page.text)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_examples_link_the_reader(client: TestClient, locale: str) -> None:
    page = client.get(EXAMPLES_PATH[locale])
    assert page.status_code == 200
    assert reading.READING_PATH[locale] in _hrefs(_main(page.text))
    assert find_claims(html.unescape(page.text)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_prop_firm_profile_and_article_link_each_other(client: TestClient, locale: str) -> None:
    profile = audience_url("retos-prop-firm", locale)
    article = article_url("cuantos-intentos-reto-prop-firm", locale)
    profile_page = client.get(profile)
    article_page = client.get(article)
    assert profile_page.status_code == article_page.status_code == 200
    assert article in _hrefs(_main(profile_page.text))
    assert profile in _hrefs(_main(article_page.text))


@pytest.mark.parametrize("locale", LOCALES)
def test_every_listed_case_article_exists(client: TestClient, locale: str) -> None:
    from quant_trade.audit.pages import AUDIENCE_ARTICLES

    for slug, keys in AUDIENCE_ARTICLES.items():
        page = client.get(audience_url(slug, locale))
        assert page.status_code == 200
        hrefs = _hrefs(_main(page.text))
        for key in keys:
            assert article_url(key, locale) in hrefs
            assert client.get(article_url(key, locale)).status_code == 200
