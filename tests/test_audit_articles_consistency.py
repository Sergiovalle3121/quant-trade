"""The best-day article keeps its declared figures tied to the calculator and presets."""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace
from decimal import Decimal
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
from quant_trade.audit.report import evidence_label  # noqa: E402
from quant_trade.audit.rules_table import COPY as RULES_COPY  # noqa: E402
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


def _share(value: float, locale: str) -> str:
    """A table share with two decimals: the precision at which the rows add up."""
    return f"{_num(value * 100, locale, 2)} %"


def _decimal(cell: str) -> Decimal:
    """The number inside a rendered share cell such as ``Declarado · 81,35 %``."""
    return Decimal(cell.rsplit(" · ", 1)[-1].rstrip(" %").replace(",", "."))


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
    # The site's words, not the code's: the reader never meets "presets".
    assert "preset" not in article_text, locale
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
    # The rules table by its nav label, like the calculator and the other tools.
    assert (RULES_COPY[locale]["nav"], rules_table_url(locale)) in related_links(article, locale)
    assert expected_related | {audit_path(locale), SAMPLE_PAGE_PATHS[locale]} <= _Links(page).links
    path = article_url(article_key, locale)
    # The pages a reader of prop-firm challenges already visits link back to it.
    for inbound in (
        article_url("cuantos-intentos-reto-prop-firm", locale),
        audience_url("retos-prop-firm", locale),
    ):
        linking = client.get(inbound)
        assert linking.status_code == 200 and path in _Links(linking.text).links, inbound
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
        assert item.maximum_initial_day_loss == -min(reading.declared.daily)
    # The programs note: Builder's daily limit stays out of reach, so both rows coincide.
    with_rule, without_rule = numbers.consistency_examples()
    builder = PRESETS[without_rule.inputs.program]
    assert builder.max_daily_loss is not None and builder.daily_loss_basis == "initial_balance"
    assert without_rule.maximum_initial_day_loss < builder.max_daily_loss
    assert without_rule.daily_limit == 0.0
    for attribute in ("target", "daily_limit", "total_limit", "unfinished", "median_days"):
        assert getattr(with_rule, attribute) == getattr(without_rule, attribute), attribute
    # The sensitivity note: each variation keeps every synthetic day under the cap.
    base_row, *variation_rows = numbers.consistency_variations()
    cap = base_row.target_rule_cap
    assert cap is not None and base_row.maximum_initial_day_gain > cap
    for row in variation_rows:
        growth = 1 + PRESETS[row.inputs.program].profit_target
        assert row.maximum_initial_day_gain * growth <= cap
        assert row.within_best_day == row.target


@pytest.mark.parametrize("locale", LOCALES)
def test_consistency_tables_print_calculator_figures_as_declared(
    article_key: str, locale: str
) -> None:
    page = article_page(ARTICLES_BY_KEY[article_key], locale=locale, base_url=BASE)
    declared = evidence_label("DECLARED", locale)
    visible = _visible(page)
    example, without_rule = numbers.consistency_examples()
    assert example.target_rule_cap is not None
    for value in (example.target_rule_cap, example.maximum_initial_day_gain):
        assert f"{_num(value * 100, locale, 2)} %" in visible
    # The programs note prints Builder's daily limit and the worst synthetic day.
    builder = PRESETS[without_rule.inputs.program]
    assert builder.max_daily_loss is not None
    assert f"({_num(builder.max_daily_loss * 100, locale, 0)} %" in visible
    assert f"{_num(without_rule.maximum_initial_day_loss * 100, locale, 2)} %" in visible
    # The sensitivity note names each variation's largest day beside the cap.
    for row in numbers.consistency_variations()[1:]:
        assert f"{_num(row.maximum_initial_day_gain * 100, locale, 2)} %" in visible
    # The sensitivity table has its own caption, not a copy of the cases caption.
    notes = CONSISTENCY_TABLE_COPY[locale]
    sensitivity = _visible(_table(page, "sensitivity"))
    assert notes["sensitivity_note"].split(" · ", 1)[1] in sensitivity
    assert notes["outcome_note"].split(" · ", 1)[1] not in sensitivity
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
                else f"{declared} · {_share(item.within_best_day, locale)}"
            )
            assert item.median_days is not None
            expected_cells = [
                f"{declared} · {_share(item.target, locale)}",
                within,
                f"{declared} · {_share(item.daily_limit + item.total_limit, locale)}",
                f"{declared} · {_share(item.unfinished, locale)}",
                f"{declared} · {_num(item.median_days, locale, 0)}",
            ]
            # The three outcomes printed add up to 100 % exactly at two decimals.
            assert sum(_decimal(expected_cells[i]) for i in (0, 2, 3)) == 100
            if name == "sensitivity":
                assert item.inputs.risk is not None
                expected_cells = [
                    f"{declared} · {_num(item.inputs.per_day, locale, 0)}",
                    f"{declared} · {_num(item.inputs.risk, locale, 2)} %",
                    f"{declared} · {_share(item.maximum_initial_day_gain, locale)}",
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
            preset.best_day_source_url or preset.source_url,
            preset.as_of,
        )
        if preset.best_day_source_url is not None:
            # The firm's page about the rule itself, not the program's general source.
            assert "consisten" in row.source_url.casefold(), row.key
        rendered = _visible(rows[row.key])
        assert row.firm in rendered and row.program in rendered
        declared = evidence_label("DECLARED", locale)
        assert f"{declared} · {_num(row.limit * 100, locale, 0)} %" in rendered
        assert CONSISTENCY_TABLE_COPY[locale][row.basis] in rendered
        assert row.as_of in rendered
        assert row.source_url in _Links(rows[row.key]).links
        # Nofollow like every other source link of the site, the firm's page named as
        # the calculator names it, and the reading date beside the link, not inside it.
        anchor = f"<a href='{html.escape(row.source_url, quote=True)}' rel='noopener nofollow'>"
        assert anchor in rows[row.key]
        assert calc.COPY[locale]["source_link"].format(firm=row.firm) in rendered
        assert f"<time datetime='{row.as_of}'>{row.as_of}</time>" in rows[row.key]
        assert f"{declared} · {row.as_of}" not in rendered
        assert find_claims(rendered) == []
