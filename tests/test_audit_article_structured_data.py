"""Editorial JSON-LD stays valid, matches visible text and escapes raw script text."""

from __future__ import annotations

import html
import json
from dataclasses import replace
from datetime import date
from html.parser import HTMLParser
from typing import Any

import pytest

from quant_trade.audit.articles import (
    ARTICLE_PUBLICATION_DATES,
    ARTICLES,
    ARTICLES_BY_KEY,
    ARTICLES_COPY,
    INDEX_FAQ_SOURCES,
    Article,
    article_url,
    articles_index_faq,
    articles_index_url,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import article_page, articles_index_page
from quant_trade.audit.seo import article_structured_data

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
ARTICLE_FIELDS = {
    "@context",
    "@type",
    "headline",
    "datePublished",
    "dateModified",
    "inLanguage",
    "author",
    "publisher",
    "mainEntityOfPage",
}


class _Page(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self.canonical: str | None = None
        self._script: dict[str, str | None] | None = None
        self._script_text: list[str] = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script":
            self._script = attributes
            self._script_text = []
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonical = attributes.get("href")

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script, "".join(self._script_text)))
            self._script = None

    def structured_data(self) -> list[dict[str, Any]]:
        # Script contents are raw HTML text: entities must not be unescaped.
        return [
            json.loads(payload)
            for attrs, payload in self.scripts
            if attrs.get("type") == "application/ld+json"
        ]


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("article", ARTICLES, ids=lambda article: article.key)
def test_article_json_matches_editorial_fields_and_canonical(article: Article, locale: str) -> None:
    source = article_page(article, locale=locale, base_url=BASE)
    document = _Page(source)
    detail, breadcrumb = document.structured_data()
    assert set(detail) == ARTICLE_FIELDS
    assert detail["@context"] == "https://schema.org"
    assert detail["@type"] == "Article"
    assert detail["headline"] == article.text[locale].title
    assert detail["datePublished"] == ARTICLE_PUBLICATION_DATES[article.key]
    assert detail["dateModified"] == ARTICLE_PUBLICATION_DATES[article.key]
    assert date.fromisoformat(detail["datePublished"]).isoformat() == detail["datePublished"]
    assert detail["inLanguage"] == locale
    assert detail["author"] == {"@type": "Person", "name": "Sergio Valle"}
    assert detail["publisher"] == {"@type": "Organization", "name": "Rigor"}
    assert (
        detail["mainEntityOfPage"] == document.canonical == BASE + article_url(article.key, locale)
    )
    assert html.escape(detail["headline"], quote=True) in source
    assert find_claims(detail["headline"]) == []

    assert set(breadcrumb) == {"@context", "@type", "itemListElement"}
    assert breadcrumb["@context"] == "https://schema.org"
    assert breadcrumb["@type"] == "BreadcrumbList"
    home = {"es": "/", "en": "/en", "pt": "/pt"}[locale]
    expected = (
        ({"es": "Inicio", "en": "Home", "pt": "Início"}[locale], home),
        (ARTICLES_COPY[locale]["eyebrow"], articles_index_url(locale)),
        (article.text[locale].title, article_url(article.key, locale)),
    )
    assert len(breadcrumb["itemListElement"]) == len(expected)
    for position, (item, (name, path)) in enumerate(
        zip(breadcrumb["itemListElement"], expected, strict=True), start=1
    ):
        assert set(item) == {"@type", "position", "name", "item"}
        assert item == {
            "@type": "ListItem",
            "position": position,
            "name": name,
            "item": BASE + path,
        }
        assert find_claims(item["name"]) == []
    for attrs, _payload in document.scripts:
        if attrs.get("type") == "application/ld+json":
            assert set(attrs) == {"type"}


@pytest.mark.parametrize("locale", LOCALES)
def test_index_faq_reuses_four_existing_answers_visibly_and_in_json(locale: str) -> None:
    source = articles_index_page(locale=locale, base_url=BASE)
    (faq,) = _Page(source).structured_data()
    assert set(faq) == {"@context", "@type", "mainEntity"}
    assert faq["@context"] == "https://schema.org"
    assert faq["@type"] == "FAQPage"
    assert len(faq["mainEntity"]) == 4
    assert {key for key, _index in INDEX_FAQ_SOURCES} <= {
        "ea-sobreoptimizado",
        "backtest-costos-reales",
        "leer-informe-probador-mt5",
    }
    expected = tuple(
        ARTICLES_BY_KEY[key].text[locale].faq[index] for key, index in INDEX_FAQ_SOURCES
    )
    assert articles_index_faq(locale) == expected
    assert len(set(expected)) == 4
    for item, (question, answer) in zip(faq["mainEntity"], expected, strict=True):
        assert set(item) == {"@type", "name", "acceptedAnswer"}
        assert item["@type"] == "Question"
        assert item["name"] == question
        assert item["acceptedAnswer"] == {"@type": "Answer", "text": answer}
        assert (
            f"<summary>{html.escape(question, quote=True)}</summary>"
            f"<p>{html.escape(answer, quote=True)}</p>"
        ) in source
        assert find_claims(question) == []
        assert find_claims(answer) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_script_closing_text_round_trips_without_adding_a_script(locale: str) -> None:
    article = ARTICLES[0]
    title = "Review </script><script>window.__injected=1</script> & \"quotes\" 'single' \u2028end"
    base = "https://audit.example/?tag=</script><script>window.__base=1</script>&q=\"'"
    text = replace(
        article.text[locale],
        title=title,
        summary="PRIVATE_SUMMARY_NOT_FOR_JSON",
        intro="PRIVATE_INTRO_NOT_FOR_JSON",
    )
    changed = replace(article, text={**article.text, locale: text})
    structured = article_structured_data(changed, locale, base)
    parsed = _Page(structured)
    assert len(parsed.scripts) == 2
    assert all(attrs == {"type": "application/ld+json"} for attrs, _payload in parsed.scripts)
    detail, breadcrumb = parsed.structured_data()
    assert detail["headline"] == title
    assert detail["mainEntityOfPage"] == base + article_url(article.key, locale)
    assert breadcrumb["itemListElement"][-1]["name"] == title
    assert breadcrumb["itemListElement"][-1]["item"] == detail["mainEntityOfPage"]
    assert "PRIVATE_SUMMARY_NOT_FOR_JSON" not in structured
    assert "PRIVATE_INTRO_NOT_FOR_JSON" not in structured
    assert "\\u2028" in structured
    assert "&quot;" not in structured
    for _attrs, payload in parsed.scripts:
        assert "<" not in payload and ">" not in payload and "&" not in payload

    source = article_page(changed, locale=locale, base_url=base)
    page = _Page(source)
    original = _Page(article_page(article, locale=locale, base_url=BASE))
    assert len(page.scripts) == len(original.scripts)
    assert page.canonical == detail["mainEntityOfPage"]
    assert html.escape(title, quote=True) in source
    assert all("window.__" not in payload for attrs, payload in page.scripts if not attrs)
    assert page.structured_data() == parsed.structured_data()
