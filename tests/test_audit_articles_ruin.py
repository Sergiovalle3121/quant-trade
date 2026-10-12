"""Risk-of-ruin article: declared examples follow the calculator and Wilson reader."""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import article_numbers as numbers  # noqa: E402
from quant_trade.audit import ruin_calc, winrate  # noqa: E402
from quant_trade.audit.articles import (  # noqa: E402
    ARTICLE_PUBLICATION_DATES,
    ARTICLES_BY_KEY,
    ARTICLES_COPY,
    RUIN_TABLE_COPY,
    _num,
    article_url,
    articles_index_url,
    next_step_links,
    related_links,
)
from quant_trade.audit.challenge_calc import challenge_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import SAMPLE_PAGE_PATHS, article_page, audit_path  # noqa: E402
from quant_trade.audit.public_card import PublicClaim  # noqa: E402
from quant_trade.audit.report import evidence_label  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
KEY = "riesgo-de-ruina-intervalo-de-confianza"
LOCALES = ("es", "en", "pt")
SLUGS = {
    "es": "riesgo-de-ruina-intervalo-de-confianza",
    "en": "risk-of-ruin-confidence-interval",
    "pt": "risco-de-ruina-intervalo-de-confianca",
}


def _visible(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def _links(page: str) -> set[str]:
    return {html.unescape(link) for link in re.findall(r"href=['\"]([^'\"]+)['\"]", page)}


def _percent(value: float, locale: str) -> str:
    """One decimal: the rounding of the calculator the article names as its source."""
    return f"{_num(value * 100, locale, 1)} %"


def _expectancy(value: float, locale: str) -> str:
    """Two decimals with the sign, as the calculator page shows an expectancy."""
    return ruin_calc._signed(value, f"{_num(value, locale, 2)} R")


def _meta(page: str, name: str) -> str | None:
    match = re.search(rf"<meta name='{name}' content='([^']*)'", page)
    return html.unescape(match.group(1)) if match else None


def _stored(locale: str) -> str:
    words = ARTICLES_BY_KEY[KEY].text[locale]
    texts = [words.title, words.summary, words.intro, words.seo_title or words.title]
    for section in words.sections:
        texts.extend((section.heading, *section.paragraphs))
    for question, answer in words.faq:
        texts.extend((question, answer))
    return " ".join(texts)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    folder = tmp_path_factory.mktemp("article-ruin")
    settings = AuditSettings(database_url=f"sqlite:///{folder}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def test_ruin_examples_recompute_from_the_calculator_and_wilson() -> None:
    assert numbers.RUIN_RISK_PCT == 1.0
    assert numbers.RUIN_THRESHOLD_PCT == 30.0
    assert numbers.RUIN_HORIZON == 500
    assert [
        (value.win_rate_pct, value.trades, value.avg_win, value.avg_loss)
        for value in numbers.RUIN_INPUTS
    ] == [(55.0, 60, 1.0, 1.0), (55.0, 300, 1.0, 1.0), (45.0, 100, 2.0, 1.0)]
    # Clear memoisation so the comparison reruns the paths instead of returning
    # the same reading cached when article_numbers was imported.
    ruin_calc.compute.cache_clear()
    for value, reading in zip(numbers.RUIN_INPUTS, numbers.RUIN_READINGS, strict=True):
        assert (value.unit, value.risk, value.ruin_pct, value.horizon) == ("r", 1.0, 30.0, 500)
        assert reading == ruin_calc.compute(value)
        interval = winrate.read(PublicClaim(trades=value.trades, win_rate=value.win_rate)).interval
        assert reading.interval == interval
        assert interval is not None and reading.lower is not None
        assert reading.lower.win_rate == interval[0]
        expected_lower = ruin_calc.compute(
            replace(value, win_rate_pct=interval[0] * 100, trades=None)
        ).declared
        assert reading.lower.expectancy_r == pytest.approx(expected_lower.expectancy_r)
        assert reading.lower.ruin == expected_lower.ruin
    first, second, third = numbers.RUIN_READINGS
    assert first.declared == second.declared
    assert first.lower is not None and second.lower is not None and third.lower is not None
    assert first.lower.ruin > second.lower.ruin > second.declared.ruin
    assert third.declared.expectancy_r == pytest.approx(0.35)
    # The prose names the count behind the third row's zero, not a rounded share.
    assert third.declared.ruin == 0.0
    assert numbers.RUIN_THIRD_CASE_RUINED_PATHS == 0
    assert first.lower.ruin * ruin_calc.SAMPLES == pytest.approx(3955)


@pytest.mark.parametrize("locale", LOCALES)
def test_ruin_table_cells_equal_engine_results_and_keep_declared_evidence(locale: str) -> None:
    page = article_page(ARTICLES_BY_KEY[KEY], locale=locale, base_url=BASE)
    table = re.search(r"<table class='article-ruin'>(.*?)</table>", page, re.S)
    assert table is not None
    # The note precedes the scrolling region as a paragraph, so a phone shows it
    # whole; the region stays keyboard-reachable and the table has no caption.
    declared = evidence_label("DECLARED", locale)
    note = html.escape(RUIN_TABLE_COPY[locale][-1].replace("DECLARED", declared), quote=True)
    assert f"<p>{note}</p><div class='tscroll ruin-scroll' role='region' tabindex='0' " in page
    assert "<caption>" not in table.group(1)
    rows = re.findall(r"<tr><th scope='row'>(.*?)</tr>", table.group(1), re.S)
    assert len(rows) == 3
    for row, value in zip(rows, numbers.RUIN_INPUTS, strict=True):
        reading = ruin_calc.compute(value)
        assert reading.lower is not None
        assert value.trades is not None
        expected = (
            _percent(value.win_rate, locale),
            _num(value.trades, locale, 0),
            f"{_num(value.avg_win, locale, 1)}R/{_num(value.avg_loss, locale, 1)}R",
            _expectancy(reading.declared.expectancy_r, locale),
            _percent(reading.declared.ruin, locale),
            _percent(reading.lower.win_rate, locale),
            _expectancy(reading.lower.expectancy_r, locale),
            _percent(reading.lower.ruin, locale),
        )
        cells = [_visible(cell) for cell in re.findall(r"(?:^|<td>)(.*?)</(?:th|td)>", row)]
        assert cells == [f"{declared} · {value}" for value in expected]
    assert evidence_label("MEASURED", locale) not in _visible(table.group(1))
    assert find_claims(_visible(table.group(1))) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_ruin_table_shows_the_figures_the_linked_calculator_shows(
    client: TestClient, locale: str
) -> None:
    """A reader who opens the calculator with a row's inputs meets the same
    rounded figures: one decimal for every probability, a signed expectancy.
    A two-decimal table would show 0.15 % where the calculator shows 0.1 %."""
    page = _visible(article_page(ARTICLES_BY_KEY[KEY], locale=locale, base_url=BASE))
    for value in numbers.RUIN_INPUTS:
        reading = ruin_calc.compute(value)
        assert reading.lower is not None
        calculator = _visible(client.get(ruin_calc.share_url(locale, value)).text)
        for shown in (
            _percent(value.win_rate, locale),
            _expectancy(reading.declared.expectancy_r, locale),
            _percent(reading.declared.ruin, locale),
            _percent(reading.lower.win_rate, locale),
            _expectancy(reading.lower.expectancy_r, locale),
            _percent(reading.lower.ruin, locale),
        ):
            assert shown in page, shown
            assert shown in calculator, shown


def test_ruin_sample_sizes_follow_winrate_reader_and_distinguish_its_grid() -> None:
    claim = PublicClaim(trades=60, win_rate=0.55, target_r=1.0, stop_r=1.0)
    expected = winrate.read(claim)
    assert expected == numbers.RUIN_WINRATE_READING
    assert expected.breakeven == 0.5
    assert expected.trades_needed == 500
    assert numbers.RUIN_MIN_TRADES == 385
    assert numbers.RUIN_EXACT_RATE_TRADES == 400
    for trades in range(1, numbers.RUIN_MIN_TRADES + 1):
        reading = winrate.read(replace(claim, trades=trades))
        assert reading.interval is not None
        assert (reading.interval[0] > 0.5) == (trades == numbers.RUIN_MIN_TRADES)
    for trades in range(20, numbers.RUIN_EXACT_RATE_TRADES + 1, 20):
        reading = winrate.read(replace(claim, trades=trades))
        assert reading.interval is not None
        assert (reading.interval[0] > 0.5) == (trades == numbers.RUIN_EXACT_RATE_TRADES)


@pytest.mark.parametrize("locale", LOCALES)
def test_ruin_article_serves_localised_metadata_and_safe_prose(
    client: TestClient, locale: str
) -> None:
    article = ARTICLES_BY_KEY[KEY]
    assert article.slug == SLUGS
    path = article_url(KEY, locale)
    response = client.get(path)
    assert response.status_code == 200
    assert f"<html lang='{locale}'>" in response.text
    assert f"rel='canonical' href='{BASE}{path}'" in response.text
    for other in LOCALES:
        assert f"hreflang='{other}' href='{BASE}{article_url(KEY, other)}'" in response.text
    detail = json.loads(
        re.findall(r"<script type='application/ld\+json'>(.*?)</script>", response.text, re.S)[0]
    )
    assert detail["@type"] == "Article"
    assert detail["inLanguage"] == locale
    assert detail["datePublished"] == detail["dateModified"] == "2026-10-11"
    assert ARTICLE_PUBLICATION_DATES[KEY] == "2026-10-11"
    assert find_claims(_stored(locale)) == []
    assert find_claims(response.text) == []
    prose_match = re.search(r"<article class='prose'>(.*?)</article>", response.text, re.S)
    assert prose_match is not None
    prose = " ".join((_stored(locale), _visible(prose_match.group(1)))).lower()
    forbidden = (
        r"\b(?:verificad\w*|verified|certific\w*|garanti\w*|guarante\w*|rentab\w*|rentáv\w*"
        r"|profitable|aprob\w*|aprova\w*|approv\w*|pasar|pass(?:es|ed|ing)?)\b"
    )
    assert re.search(forbidden, prose) is None


@pytest.mark.parametrize("locale", LOCALES)
def test_ruin_links_reach_calculators_history_upload_and_example(
    client: TestClient, locale: str
) -> None:
    article = ARTICLES_BY_KEY[KEY]
    page = client.get(article_url(KEY, locale)).text
    expected = {
        ruin_calc.ruin_url(locale),
        winrate.winrate_url(locale),
        article_url("rachas-perdedoras", locale),
        challenge_url(locale),
        SAMPLE_PAGE_PATHS[locale],
    }
    assert {href for _label, href in related_links(article, locale)} == expected
    # The next step: the ruin calculator opened with the first declared case; the
    # form stays among the closing links.
    ((_label, step),) = next_step_links(article, locale)
    assert urlsplit(step).path == ruin_calc.ruin_url(locale)
    assert parse_qs(urlsplit(step).query) == {
        name: [value] for name, value in ruin_calc.share_values(numbers.RUIN_INPUTS[0]).items()
    }
    assert expected | {audit_path(locale), step} <= _links(page)
    for target in expected | {audit_path(locale)}:
        assert client.get(target).status_code == 200, target
    for link in _links(page):
        parsed = urlsplit(link)
        assert not parsed.netloc or parsed.netloc == "audit.example", link


@pytest.mark.parametrize("locale", LOCALES)
def test_ruin_article_is_in_index_and_sitemap_with_its_publication_date(
    client: TestClient, locale: str
) -> None:
    path = article_url(KEY, locale)
    index = client.get(articles_index_url(locale)).text
    assert path in _links(index)
    # The index description names the new topic, within the length the SEO test keeps.
    description = _meta(index, "description")
    assert description == ARTICLES_COPY[locale]["summary"]
    assert {"es": "riesgo de ruina", "en": "risk of ruin", "pt": "ruína"}[locale] in description
    assert len(description) <= 160, len(description)
    root = ElementTree.fromstring(client.get("/sitemap.xml").content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    dates = {
        item.findtext("s:loc", namespaces=namespace): item.findtext(
            "s:lastmod", namespaces=namespace
        )
        for item in root.findall("s:url", namespace)
    }
    assert dates[BASE + path] == "2026-10-11"
    assert dates[BASE + articles_index_url(locale)] == "2026-10-11"
