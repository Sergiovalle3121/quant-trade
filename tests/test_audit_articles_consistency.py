"""The best-day article keeps its declared figures tied to the calculator and presets."""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace
from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import article_numbers as numbers  # noqa: E402
from quant_trade.audit import challenge_calc as calc  # noqa: E402
from quant_trade.audit.articles import (  # noqa: E402
    ARTICLE_PUBLICATION_DATES,
    ARTICLES_BY_KEY,
    CONSISTENCY_TABLE_COPY,
    _num,
    article_url,
    articles_index_url,
    related_links,
)
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import SAMPLE_PAGE_PATHS, article_page, audit_path  # noqa: E402
from quant_trade.audit.prop_presets import PRESETS  # noqa: E402
from quant_trade.audit.public_card import _pct  # noqa: E402
from quant_trade.audit.report import evidence_label  # noqa: E402
from quant_trade.audit.rules_table import rules_table_url  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
ARTICLE_KEY = "regla-de-consistencia-prop-firm"
LOCALES = ("es", "en", "pt")
SLUGS = {
    "es": "regla-de-consistencia-prop-firm",
    "en": "prop-firm-consistency-rule-numbers",
    "pt": "regra-de-consistencia-prop-firm",
}
# The brief's slug selects every article-specific check with pytest -k.
pytestmark = pytest.mark.parametrize("article_key", [ARTICLE_KEY])


class _Links(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.links: set[str] = set()
        self.feed(source)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "href" and value is not None:
                self.links.add(value)


def _visible(source: str) -> str:
    source = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", source, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", source)).split())


def _table(page: str, name: str) -> str:
    found = re.search(rf"<table class='article-consistency-{name}'>(.*?)</table>", page, re.S)
    assert found is not None, name
    return found.group(1)


def _rows(table: str, attribute: str) -> dict[str, str]:
    return dict(re.findall(rf"<tr {attribute}='([^']+)'>(.*?)</tr>", table, re.S))


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    folder = tmp_path_factory.mktemp("consistency-article")
    settings = AuditSettings(database_url=f"sqlite:///{folder}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize("locale", LOCALES)
def test_consistency_article_metadata_guard_and_language(
    article_key: str, locale: str, client: TestClient
) -> None:
    article = ARTICLES_BY_KEY[article_key]
    assert article.slug == SLUGS
    words = article.text[locale]
    assert 40 <= len(words.summary) <= 155
    source_texts = [words.title, words.summary, words.intro, words.seo_title or words.title]
    source_texts += [
        text for section in words.sections for text in (section.heading, *section.paragraphs)
    ]
    source_texts += [text for pair in words.faq for text in pair]
    response = client.get(article_url(article_key, locale))
    assert response.status_code == 200
    page = response.text
    assert f"<html lang='{locale}'>" in page
    assert f"rel='canonical' href='{BASE}{article_url(article_key, locale)}'" in page
    for other in LOCALES:
        assert f"hreflang='{other}' href='{BASE}{article_url(article_key, other)}'" in page
    for text in [*source_texts, _visible(page), html.unescape(page)]:
        assert find_claims(text) == [], (locale, text)
    prose = re.search(r"<article class='prose'>(.*?)</article>", page, re.S)
    assert prose is not None
    article_text = _visible(prose.group(1)).casefold()
    assert re.search(r"\b(?:pasar|aprobar|pass|passed|aprovar)\b", article_text) is None
    for forbidden in ("verificad", "verified", "certific", "garant", "guarant", "rentable"):
        assert forbidden not in article_text, (locale, forbidden)
    affiliation = {
        "es": "Rigor no está afiliado a ninguna firma",
        "en": "Rigor is not affiliated with any firm",
        "pt": "O Rigor não é afiliado a nenhuma empresa",
    }
    assert affiliation[locale].casefold() in article_text
    assert any(term in article_text for term in ("intradí", "intradi", "intraday"))
    assert {"es": "flotante", "en": "floating", "pt": "flutuante"}[locale] in article_text
    detail, _breadcrumb = [
        json.loads(block)
        for block in re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    ]
    assert detail["headline"] == words.title
    assert detail["datePublished"] == detail["dateModified"] == "2026-10-11"
    assert ARTICLE_PUBLICATION_DATES[article_key] == "2026-10-11"


@pytest.mark.parametrize("locale", LOCALES)
def test_consistency_article_links_discovery_and_lastmod(
    article_key: str, locale: str, client: TestClient
) -> None:
    article = ARTICLES_BY_KEY[article_key]
    page = article_page(article, locale=locale, base_url=BASE)
    expected_related = {
        calc.challenge_url(locale),
        rules_table_url(locale),
        audience_url("retos-prop-firm", locale),
        article_url("cuantos-intentos-reto-prop-firm", locale),
    }
    assert expected_related <= {url for _, url in related_links(article, locale)}
    assert expected_related | {audit_path(locale), SAMPLE_PAGE_PATHS[locale]} <= _Links(page).links
    path = article_url(article_key, locale)
    index = client.get(articles_index_url(locale))
    assert index.status_code == 200 and path in _Links(index.text).links
    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    dated = {
        url.findtext("s:loc", namespaces=namespace): url.findtext("s:lastmod", namespaces=namespace)
        for url in ElementTree.fromstring(sitemap.content).findall("s:url", namespace)
    }
    assert dated[BASE + path] == dated[BASE + articles_index_url(locale)] == "2026-10-11"


def test_consistency_cases_and_sensitivity_match_compute(article_key: str) -> None:
    assert article_key in ARTICLES_BY_KEY
    base, without_rule = numbers.CONSISTENCY_INPUTS
    assert (base.win_rate_pct, base.unit, base.avg_win, base.avg_loss, base.risk, base.per_day) == (
        50.0,
        "r",
        1.5,
        1.0,
        0.5,
        3.0,
    )
    assert PRESETS[base.program].best_day_limit == 0.30
    assert PRESETS[without_rule.program].best_day_limit is None
    assert replace(without_rule, program=base.program) == base
    variations = numbers.CONSISTENCY_VARIATION_INPUTS
    assert variations == (
        base,
        replace(base, per_day=1.0),
        replace(base, risk=0.25),
    )
    for item in (*numbers.consistency_examples(), *numbers.consistency_variations()):
        reading = calc.compute(item.inputs)
        outcome = reading.declared.outcome
        assert item.evidence == "DECLARED"
        for attribute, field in (
            ("target", "pass"),
            ("daily_limit", "fail_daily_loss"),
            ("total_limit", "fail_total_loss"),
            ("unfinished", "unfinished"),
        ):
            assert getattr(item, attribute) == outcome[field]["value"]
        best_day = outcome.get("pass_within_best_day")
        assert item.within_best_day == (None if best_day is None else best_day["value"])
        assert item.target + item.daily_limit + item.total_limit + item.unfinished == pytest.approx(
            1
        )
        if item.within_best_day is not None:
            assert 0 <= item.within_best_day <= item.target
        phase = reading.declared.phases[0][1]
        assert item.median_days == phase["days_to_target"]["p50"]["value"]
        assert item.horizon == phase["method"]["horizon_business_days"]
        assert item.samples == calc.SAMPLES
        assert item.synthetic_days == calc.SYNTHETIC_DAYS == phase["method"]["observations"]
        assert item.seed == calc.SEED == phase["method"]["seed"]
        assert item.block_size == phase["method"]["expected_block_size"]
        preset = PRESETS[item.inputs.program]
        cap = (
            preset.profit_target * preset.best_day_limit
            if preset.best_day_basis == "profit_target" and preset.best_day_limit is not None
            else None
        )
        assert item.target_rule_cap == cap
        assert item.maximum_initial_day_gain == max(reading.declared.daily)


@pytest.mark.parametrize("locale", LOCALES)
def test_consistency_tables_print_calculator_figures_as_declared(
    article_key: str, locale: str
) -> None:
    page = article_page(ARTICLES_BY_KEY[article_key], locale=locale, base_url=BASE)
    declared = evidence_label("DECLARED", locale)
    example = numbers.consistency_examples()[0]
    assert example.target_rule_cap is not None
    for value in (example.target_rule_cap, example.maximum_initial_day_gain):
        assert f"{_num(value * 100, locale, 2)} %" in _visible(page)
    for name, examples in (
        ("cases", numbers.consistency_examples()),
        ("sensitivity", numbers.consistency_variations()),
    ):
        table = _table(page, name)
        rows = _rows(table, "data-case")
        expected_keys = (
            [item.inputs.program for item in examples]
            if name == "cases"
            else [str(index) for index in range(len(examples))]
        )
        assert list(rows) == expected_keys
        for key, item in zip(expected_keys, examples, strict=True):
            cells = [
                _visible(cell)
                for cell in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", rows[key], re.S)
            ]
            within = (
                {"es": "Sin regla", "en": "No rule", "pt": "Sem regra"}[locale]
                if item.within_best_day is None
                else f"{declared} · {_pct(item.within_best_day, locale)}"
            )
            assert item.median_days is not None
            expected_cells = [
                f"{declared} · {_pct(item.target, locale)}",
                within,
                f"{declared} · {_pct(item.daily_limit + item.total_limit, locale)}",
                f"{declared} · {_pct(item.unfinished, locale)}",
                f"{declared} · {_num(item.median_days, locale, 0)}",
            ]
            if name == "sensitivity":
                assert item.inputs.risk is not None
                expected_cells = [
                    f"{declared} · {_num(item.inputs.per_day, locale, 0)}",
                    f"{declared} · {_num(item.inputs.risk, locale, 2)} %",
                    *expected_cells,
                ]
                assert cells == expected_cells
            else:
                preset = PRESETS[item.inputs.program]
                assert preset.firm in cells[0] and preset.program in cells[0]
                assert cells[1:] == expected_cells
        assert evidence_label("MEASURED", locale) not in _visible(table)
        assert find_claims(_visible(table)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_consistency_rules_are_complete_sourced_presets(article_key: str, locale: str) -> None:
    page = article_page(ARTICLES_BY_KEY[article_key], locale=locale, base_url=BASE)
    table = _table(page, "rules")
    rows = _rows(table, "data-preset")
    rules = numbers.consistency_rules()
    expected = [
        preset
        for preset in PRESETS.values()
        if preset.source_url.startswith("https://") and preset.best_day_limit is not None
    ]
    assert list(rows) == [preset.key for preset in expected] == [row.key for row in rules]
    for row, preset in zip(rules, expected, strict=True):
        assert (row.firm, row.program, row.limit, row.basis, row.source_url, row.as_of) == (
            preset.firm,
            preset.program,
            preset.best_day_limit,
            preset.best_day_basis,
            preset.source_url,
            preset.as_of,
        )
        rendered = _visible(rows[row.key])
        assert row.firm in rendered and row.program in rendered
        declared = evidence_label("DECLARED", locale)
        assert f"{declared} · {_num(row.limit * 100, locale, 0)} %" in rendered
        assert CONSISTENCY_TABLE_COPY[locale][row.basis] in rendered
        assert row.as_of in rendered
        assert row.source_url in _Links(rows[row.key]).links
        assert find_claims(rendered) == []
