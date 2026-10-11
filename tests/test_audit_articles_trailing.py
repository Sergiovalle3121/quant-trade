"""Trailing drawdown article: dated rules and declared calculator examples."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import replace
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
    TRAILING_TABLE_COPY,
    _num,
    article_url,
    articles_index_url,
    related_links,
    trailing_outcome_note,
)
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import localize  # noqa: E402
from quant_trade.audit.pages import article_page  # noqa: E402
from quant_trade.audit.prop_presets import PRESETS, TOTAL_LOSS_TYPES  # noqa: E402
from quant_trade.audit.report import evidence_label, localize_tags  # noqa: E402
from quant_trade.audit.rules_table import loss_names, rules_table_url  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
KEY = "drawdown-trailing-eod-intradia"
LOCALES = ("es", "en", "pt")
SLUGS = {
    "es": "drawdown-trailing-eod-intradia",
    "en": "trailing-drawdown-eod-vs-intraday",
    "pt": "drawdown-trailing-eod-intradiario",
}
pytestmark = pytest.mark.parametrize("article_key", [KEY])


def _visible(source: str) -> str:
    source = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", source, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", source)).split())


def _links(source: str) -> set[str]:
    return {html.unescape(link) for link in re.findall(r"href=['\"]([^'\"]+)['\"]", source)}


def _table(page: str, name: str) -> str:
    found = re.search(rf"<table class='article-trailing-{name}'>(.*?)</table>", page, re.S)
    assert found is not None, name
    return found.group(1)


def _rows(table: str, attribute: str) -> dict[str, str]:
    return dict(re.findall(rf"<tr {attribute}='([^']+)'>(.*?)</tr>", table, re.S))


def _cells(row: str) -> list[str]:
    return [_visible(cell) for cell in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", row, re.S)]


def _share(value: float, locale: str) -> str:
    return f"{evidence_label('DECLARED', locale)} · {_num(value * 100, locale, 2)} %"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    folder = tmp_path_factory.mktemp("trailing-article")
    settings = AuditSettings(database_url=f"sqlite:///{folder}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize("locale", LOCALES)
def test_trailing_article_locales_metadata_guard_and_affiliation(
    article_key: str, client: TestClient, locale: str
) -> None:
    article = ARTICLES_BY_KEY[article_key]
    assert article.slug == SLUGS
    words = article.text[locale]
    assert 40 <= len(words.summary) < 160
    stored = [words.title, words.summary, words.intro, words.seo_title or words.title]
    stored += [
        text for section in words.sections for text in (section.heading, *section.paragraphs)
    ]
    stored += [text for pair in words.faq for text in pair]
    path = article_url(KEY, locale)
    response = client.get(path)
    assert response.status_code == 200
    page = response.text
    assert f"<html lang='{locale}'>" in page
    assert f"rel='canonical' href='{BASE}{path}'" in page
    for other in LOCALES:
        assert f"hreflang='{other}' href='{BASE}{article_url(KEY, other)}'" in page
    for text in [*stored, page, _visible(page)]:
        assert find_claims(text) == [], (locale, text)
    prose = re.search(r"<article class='prose'>(.*?)</article>", page, re.S)
    assert prose is not None
    article_text = " ".join((*stored, _visible(prose.group(1)))).casefold()
    forbidden = (
        r"\b(?:verificad\w*|verified|certific\w*|garanti\w*|guarante\w*|rentab\w*|rentáv\w*"
        r"|profitable|aprob\w*|aprova\w*|approv\w*|pasar|pass(?:es|ed|ing)?)\b"
    )
    assert re.search(forbidden, article_text) is None
    for phrase in ("mejor firma", "best firm", "melhor empresa", "melhor firma"):
        assert phrase not in article_text
    affiliation = {
        "es": "Rigor no está afiliado",
        "en": "Rigor is not affiliated",
        "pt": "O Rigor não é afiliado",
    }
    assert affiliation[locale].casefold() in article_text
    assert {"es": "flotante", "en": "floating", "pt": "flutuante"}[locale] in article_text
    assert any(term in article_text for term in ("intradí", "intradi", "intraday"))
    assert "preset" not in article_text
    for text in stored:
        for code in re.finditer(r"(?:NOT_MEASURED|MEASURED|DECLARED)", text):
            assert code.start() == 0 and text.startswith(f"{code.group()} · "), text
    detail = json.loads(
        re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)[0]
    )
    assert detail["@type"] == "Article"
    assert detail["headline"] == words.title
    assert detail["inLanguage"] == locale
    assert detail["datePublished"] == detail["dateModified"] == "2026-10-11"
    assert ARTICLE_PUBLICATION_DATES[KEY] == "2026-10-11"


def test_trailing_examples_use_identical_declared_inputs_and_recompute(article_key: str) -> None:
    assert article_key in ARTICLES_BY_KEY
    inputs = numbers.TRAILING_INPUTS
    assert len(inputs) == 3
    base = inputs[0]
    assert (base.win_rate_pct, base.unit, base.avg_win, base.avg_loss, base.risk, base.per_day) == (
        50.0,
        "r",
        1.5,
        1.0,
        0.5,
        3.0,
    )
    assert {PRESETS[value.program].total_loss_type for value in inputs} == set(TOTAL_LOSS_TYPES)
    assert all(replace(value, program=base.program) == base for value in inputs)
    examples = numbers.trailing_examples()
    calc.compute.cache_clear()
    for value, item in zip(inputs, examples, strict=True):
        reading = calc.compute(value)
        assert item.inputs == value
        assert item.evidence == "DECLARED"
        outcome = reading.declared.outcome
        for attribute, field in (
            ("target", "pass"),
            ("daily_limit", "fail_daily_loss"),
            ("total_limit", "fail_total_loss"),
            ("unfinished", "unfinished"),
        ):
            assert getattr(item, attribute) == outcome[field]["value"]
        assert item.target + item.total_limit + item.daily_limit + item.unfinished == pytest.approx(
            1
        )
        assert len(reading.declared.phases) == 1
        method = reading.declared.phases[0][1]["method"]
        assert item.horizon == method["horizon_business_days"]
        assert item.samples == calc.SAMPLES == method["samples"]
        assert item.synthetic_days == calc.SYNTHETIC_DAYS == method["observations"]
        assert item.seed == calc.SEED == method["seed"]
        assert item.block_size == method["expected_block_size"]
    # The assumptions paragraph says "up to N business days in these programs": one
    # horizon shared by every row, read per program rather than from the first one.
    horizons = {item.horizon for item in examples}
    assert horizons == {calc.horizon(value.program) for value in inputs}
    assert len(horizons) == 1
    for locale in LOCALES:
        words = ARTICLES_BY_KEY[article_key].text[locale]
        cases = next(s for s in words.sections if s.heading == TRAILING_TABLE_COPY[locale]["cases"])
        assert f" {_num(max(horizons), locale, 0)} " in cases.paragraphs[0]
        assert f"{_num(calc.SAMPLES, locale, 0)} " in cases.paragraphs[0]


@pytest.mark.parametrize("locale", LOCALES)
def test_trailing_case_table_prints_calculator_outcomes_as_declared(
    article_key: str, locale: str
) -> None:
    page = article_page(ARTICLES_BY_KEY[article_key], locale=locale, base_url=BASE)
    table = _table(page, "cases")
    rows = _rows(table, "data-case")
    assert list(rows) == [value.program for value in numbers.TRAILING_INPUTS]
    for value in numbers.TRAILING_INPUTS:
        preset = PRESETS[value.program]
        outcome = calc.compute(value).declared.outcome
        cells = _cells(rows[value.program])
        assert preset.firm in cells[0] and preset.program in cells[0]
        daily = (
            TRAILING_TABLE_COPY[locale]["no_daily"]
            if preset.max_daily_loss is None
            else _share(outcome["fail_daily_loss"]["value"], locale)
        )
        assert cells[1:] == [
            loss_names(locale)[preset.total_loss_type],
            _share(preset.profit_target, locale),
            _share(outcome["pass"]["value"], locale),
            _share(outcome["fail_total_loss"]["value"], locale),
            daily,
            _share(outcome["unfinished"]["value"], locale),
        ]
        assert f"{rules_table_url(locale)}?perdida={preset.total_loss_type}" in _links(
            rows[value.program]
        )
    assert any(PRESETS[value.program].max_daily_loss is None for value in numbers.TRAILING_INPUTS)
    assert evidence_label("MEASURED", locale) not in _visible(table)
    assert find_claims(_visible(table)) == []
    # The note is a paragraph before the scrolling region, not a <caption> as wide as
    # the table, and it says why the daily column cannot fire: the worst synthetic day
    # (per_day losses) stays below the lowest simulated daily limit of these programs.
    assert "<caption>" not in page
    note = trailing_outcome_note(locale)
    assert note.startswith(TRAILING_TABLE_COPY[locale]["outcome_note"])
    assert (
        f"<p>{html.escape(localize_tags(note, locale))}</p><div class='tscroll ruin-scroll'" in page
    )
    base = numbers.TRAILING_INPUTS[0]
    limits = [
        limit
        for value in numbers.TRAILING_INPUTS
        if (limit := PRESETS[value.program].max_daily_loss) is not None
    ]
    assert base.loss * base.per_day < min(limits)
    assert f" {_num(base.loss * base.per_day * 100, locale, 1)} %" in note
    assert f"({_num(min(limits) * 100, locale, 0)} %)" in note
    assert find_claims(note) == []
    rules_note = TRAILING_TABLE_COPY[locale]["rules_note"]
    rules_note = html.escape(localize_tags(rules_note, locale))
    assert f"<p>{rules_note}</p><div class='tscroll ruin-scroll'" in page


@pytest.mark.parametrize("locale", LOCALES)
def test_trailing_rules_match_dated_sourced_preset_figures(article_key: str, locale: str) -> None:
    page = article_page(ARTICLES_BY_KEY[article_key], locale=locale, base_url=BASE)
    table = _table(page, "rules")
    rows = _rows(table, "data-preset")
    rules = numbers.trailing_rules()
    assert list(rows) == list(numbers.TRAILING_RULE_KEYS) == [row.key for row in rules]
    counts = Counter(row.loss_type for row in rules)
    assert set(counts) == set(TOTAL_LOSS_TYPES)
    assert all(2 <= count <= 3 for count in counts.values())
    for row in rules:
        preset = PRESETS[row.key]
        assert (row.firm, row.program, row.limit, row.loss_type, row.source_url, row.as_of) == (
            preset.firm,
            preset.program,
            preset.max_total_loss,
            preset.total_loss_type,
            preset.source_url,
            preset.as_of,
        )
        assert row.notes == preset.notes
        cells = _cells(rows[row.key])
        assert row.firm in cells[0] and row.program in cells[0]
        assert cells[1:3] == [loss_names(locale)[row.loss_type], _share(row.limit, locale)]
        assert row.as_of in cells[3]
        assert row.source_url in _links(rows[row.key])
        assert f"{rules_table_url(locale)}?perdida={row.loss_type}" in _links(rows[row.key])
        assert (
            f"<a href='{html.escape(row.source_url, quote=True)}' rel='noopener nofollow'>"
            in rows[row.key]
        )
        assert f"<time datetime='{row.as_of}'>{row.as_of}</time>" in rows[row.key]
        assert find_claims(_visible(rows[row.key])) == []
    words = ARTICLES_BY_KEY[article_key].text[locale]
    section = next(s for s in words.sections if s.heading == TRAILING_TABLE_COPY[locale]["rules"])
    bridge = section.paragraphs[-1]
    for kind in TOTAL_LOSS_TYPES:
        assert loss_names(locale)[kind] in bridge
    assert {"es": "estático", "en": "static", "pt": "estático"}[locale] in bridge
    assert bridge in _visible(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_trailing_caveats_quote_localized_notes_without_a_fictional_intraday_model(
    article_key: str, locale: str
) -> None:
    page = article_page(ARTICLES_BY_KEY[article_key], locale=locale, base_url=BASE)
    caveats = numbers.trailing_caveats()
    assert caveats
    wordings = [re.sub(r"\(https?://[^)]+\)", "", row.note) for row in caveats]
    assert len(set(wordings)) == len(wordings)
    assert {row.key for row in caveats} <= set(numbers.TRAILING_RULE_KEYS)
    intro = TRAILING_TABLE_COPY[locale]["notes_note"]
    assert f"<p>{html.escape(intro)}</p><div class='article-trailing-notes'>" in page
    assert {"es": "el artículo", "en": "the article", "pt": "o artigo"}[locale] in intro
    for row in caveats:
        preset = PRESETS[row.key]
        assert row.note in preset.notes
        assert (row.firm, row.program, row.source_url, row.as_of) == (
            preset.firm,
            preset.program,
            preset.source_url,
            preset.as_of,
        )
        assert _visible(localize(row.note, locale)) in _visible(page)
    intraday = [row for row in caveats if "trails the intraday high" in row.note]
    assert len(intraday) == 1
    assert intraday[0].key == "myfundedfutures-rapid-50k"
    assert "Only the evaluation is simulated; in the Sim Funded stage" in intraday[0].note
    assert PRESETS[intraday[0].key].total_loss_type == "trailing_eod"
    assert set(TOTAL_LOSS_TYPES) == {"static", "trailing_eod", "trailing_eod_lock"}


@pytest.mark.parametrize("locale", LOCALES)
def test_trailing_links_and_sitemap_expose_the_article(
    article_key: str, client: TestClient, locale: str
) -> None:
    article = ARTICLES_BY_KEY[article_key]
    page = client.get(article_url(KEY, locale)).text
    expected = {
        calc.challenge_url(locale),
        rules_table_url(locale),
        audience_url("retos-prop-firm", locale),
        article_url("regla-de-consistencia-prop-firm", locale),
        article_url("riesgo-de-ruina-intervalo-de-confianza", locale),
    }
    assert expected <= {href for _label, href in related_links(article, locale)}
    filtered = {f"{rules_table_url(locale)}?perdida={kind}" for kind in TOTAL_LOSS_TYPES}
    assert expected | filtered <= _links(page)
    for target in expected | filtered:
        assert client.get(target).status_code == 200, target
    path = article_url(KEY, locale)
    assert path in _links(client.get(articles_index_url(locale)).text)
    root = ElementTree.fromstring(client.get("/sitemap.xml").content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    dates = {
        item.findtext("s:loc", namespaces=namespace): item.findtext(
            "s:lastmod", namespaces=namespace
        )
        for item in root.findall("s:url", namespace)
    }
    assert dates[BASE + path] == dates[BASE + articles_index_url(locale)] == "2026-10-11"
