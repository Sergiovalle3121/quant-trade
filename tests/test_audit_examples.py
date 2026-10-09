"""Public examples preserve declarations, calculator inputs, evidence and SEO."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.calculator import (  # noqa: E402
    COPY as CALCULATOR_COPY,
)
from quant_trade.audit.calculator import CalculatorInput, compute, parse_input  # noqa: E402
from quant_trade.audit.examples import (  # noqa: E402
    EXAMPLES,
    EXAMPLES_COPY,
    EXAMPLES_PATH,
    SHORT_HISTORY_WEEKS,
    WEEKS_PER_YEAR,
    example_calculator_url,
    examples_content,
    examples_url,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import audit_path  # noqa: E402
from quant_trade.audit.public_card import _num  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES, sitemap_xml  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
SVG_NS = {"s": "http://www.w3.org/2000/svg"}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _cards(body: str) -> list[ET.Element]:
    return [ET.fromstring(svg) for svg in re.findall(r"<svg\b.*?</svg>", body, flags=re.S)]


def _visible(body: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", body))


def test_examples_keep_the_exact_declarations_without_inventing_missing_inputs() -> None:
    first, short, many = EXAMPLES
    assert (
        first.claim.trades,
        first.claim.win_rate,
        first.claim.profit_factor,
        first.claim.target_r,
        first.claim.stop_r,
    ) == (45, 0.71, 3.24, 1, 1)
    assert first.calculator_input() is None
    assert first.claim.years is None  # Development time is not backtest history.
    assert short.calculator_input() == CalculatorInput(1.9, 9 / 52, 1)
    assert many.calculator_input() == CalculatorInput(1.8, 3, 1000)
    assert SHORT_HISTORY_WEEKS == 9 and WEEKS_PER_YEAR == 52
    assert EXAMPLES_PATH == {
        "es": "/ejemplos",
        "en": "/en/examples",
        "pt": "/pt/exemplos",
    }


@pytest.mark.parametrize("locale", LOCALES)
def test_three_inline_cards_have_evidence_no_class_and_unique_accessible_ids(locale: str) -> None:
    body = examples_content(locale)
    cards = _cards(body)
    assert len(cards) == 3
    assert body.count("class='example-reading'") == 6
    assert find_claims(body) == []
    assert find_claims(" ".join(EXAMPLES_COPY[locale].values())) == []
    ids = []
    for card in cards:
        assert card.attrib["role"] == "img"
        assert "width:100%;height:auto" in card.attrib["style"]
        text = " ".join(card.itertext())
        assert EXAMPLES_COPY[locale]["source"] in text
        assert not re.search(r"\b(?:clase|class|classe)\s+[A-D]\b", text, re.I)
        assert not any(node.text in ("A", "B", "C", "D") for node in card.iter())
        local_ids = [node.attrib["id"] for node in card.iter() if "id" in node.attrib]
        assert set(card.attrib["aria-labelledby"].split()) == set(local_ids)
        ids.extend(local_ids)
        for node in card.iter():
            assert node.tag.rsplit("}", 1)[-1] in {"svg", "title", "desc", "rect", "text", "g"}
            assert not any(name.lower().startswith("on") for name in node.attrib)
            if "data-evidence" in node.attrib:
                assert node.attrib["data-evidence"] in {"DECLARED", "NOT_MEASURED"}
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("locale", LOCALES)
def test_calculator_links_use_the_card_inputs_and_never_fill_missing_figures(
    locale: str, client: TestClient
) -> None:
    body = examples_content(locale)
    for index, example in enumerate(EXAMPLES):
        href = example_calculator_url(example, locale)
        assert html.escape(href) in body
        query = parse_qs(urlsplit(href).query)
        assert query.pop("ref") == ["ejemplos"]
        response = client.get(href)
        assert response.status_code == 200
        if index == 0:
            assert query == {}
            continue
        parsed = parse_input(*(query[name][0] for name in ("sharpe", "years", "trials")))
        assert parsed == example.calculator_input()
        assert isinstance(parsed, CalculatorInput)
        result = compute(parsed)
        assert result["status"] == "MEASURED"
        if not result["counted"]:
            assert html.escape(CALCULATOR_COPY[locale]["one_trial"]) in response.text
            continue
        luck_text = f"{result['luck_sharpe']['value']:.2f}"
        after_text = f"{result['sharpe_after']['value']:.2f}"
        # The card, its reading lines and the calculator page they link to use the page's
        # decimal mark: a comma in es and pt, a point in en.
        luck_shown = _num(result["luck_sharpe"]["value"], locale, 2)
        after_shown = _num(result["sharpe_after"]["value"], locale, 2)
        assert luck_shown == (luck_text if locale == "en" else luck_text.replace(".", ","))
        card = _cards(body)[index]
        luck = card.find(".//s:g[@data-reading='luck']", SVG_NS)
        assert luck is not None
        assert f"≈ {luck_shown}" in " ".join(luck.itertext())
        assert luck_shown in body and after_shown in body
        assert f"<b>{luck_shown}</b>" in response.text
        assert f"<b>{after_shown}</b>" in response.text
        if locale != "en":
            assert f"<b>{luck_text}</b>" not in response.text
            assert f"<b>{after_text}</b>" not in response.text


@pytest.mark.parametrize("locale", LOCALES)
def test_cards_and_reading_lines_use_the_pages_decimal_mark(
    locale: str, client: TestClient
) -> None:
    """A decimal comma in es and pt, a point in en: in each card and in the lines below it."""
    page = client.get(examples_url(locale)).text
    mark, other = (".", ",") if locale == "en" else (",", ".")
    pattern = r"<svg\b[^>]*xml:lang=.*?</svg>"
    cards = [ET.fromstring(svg) for svg in re.findall(pattern, page, re.S)]
    assert len(cards) == 3
    first = " ".join(cards[0].itertext())
    assert f"71{mark}0 %" in first and f"3{mark}24" in first
    assert f"56{mark}5 % – 82{mark}2 %" in first
    assert f"56{other}5 %" not in first and f"3{other}24" not in first
    lines = _visible(" ".join(re.findall(r"<p class='example-reading'>.*?</p>", page, re.S)))
    # Nine weeks are 0.17 years in the site's format, never the raw 0.173077.
    years = f"{SHORT_HISTORY_WEEKS / WEEKS_PER_YEAR:.2f}"
    assert years.replace(".", mark) in lines
    raw = f"{SHORT_HISTORY_WEEKS / WEEKS_PER_YEAR:.6f}"
    assert raw not in page and raw.replace(".", mark) not in page
    many = compute(CalculatorInput(1.8, 3, 1000))
    luck = f"{many['luck_sharpe']['value']:.2f}"
    assert luck.replace(".", mark) in lines
    if locale != "en":
        assert years not in lines and luck not in lines


@pytest.mark.parametrize("locale", LOCALES)
def test_public_page_is_localized_indexable_and_ends_with_the_existing_free_report_cta(
    locale: str, client: TestClient
) -> None:
    response = client.get(examples_url(locale))
    assert response.status_code == 200
    page = response.text
    assert "x-robots-tag" not in response.headers
    assert f"<html lang='{locale}'>" in page
    assert f"<link rel='canonical' href='{BASE}{examples_url(locale)}'>" in page
    assert "<meta name='robots' content='index, follow'>" in page
    assert (
        f"<meta name='description' content='{html.escape(EXAMPLES_COPY[locale]['summary'])}'>"
        in page
    )
    assert "property='og:title'" in page
    assert "name='twitter:card'" in page
    for lang, path in EXAMPLES_PATH.items():
        assert f"hreflang='{lang}' href='{BASE}{path}'" in page
        if lang != locale:
            assert f"href='{path}'" in page
    assert f"hreflang='x-default' href='{BASE}{EXAMPLES_PATH['es']}'" in page
    assert page.count("class='article-cta public-example'") == 3
    assert html.escape(CALCULATOR_COPY[locale]["cta"]) in page
    assert f"href='{audit_path(locale)}'" in page
    assert find_claims(page) == []
    assert find_claims(_visible(page)) == []
    if locale == "pt":
        for spanish in ("Sube ", "archivo", "Empezar", "informe"):
            assert spanish not in _visible(page)


def test_sitemap_lists_every_example_language_with_all_alternates() -> None:
    assert EXAMPLES_PATH in PUBLIC_PAGES
    root = ET.fromstring(sitemap_xml(BASE))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "h": "http://www.w3.org/1999/xhtml"}
    urls = {node.findtext("s:loc", namespaces=ns): node for node in root.findall("s:url", ns)}
    for path in EXAMPLES_PATH.values():
        assert BASE + path in urls
        alternates = {
            link.attrib["hreflang"]: link.attrib["href"]
            for link in urls[BASE + path].findall("h:link", ns)
        }
        assert alternates == {
            **{lang: BASE + value for lang, value in EXAMPLES_PATH.items()},
            "x-default": BASE + EXAMPLES_PATH["es"],
        }
