"""The Monte Carlo and losing-streak articles: computed figures, links and the method page."""

from __future__ import annotations

import html
import inspect
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.etree import ElementTree

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import article_numbers as numbers  # noqa: E402
from quant_trade.audit.analytics import (  # noqa: E402
    DEFAULT_BLOCK_SIZE,
    SHUFFLE_SAMPLES,
    SHUFFLE_SEED,
    drawdown_risk,
    shuffled_drawdown,
)
from quant_trade.audit.articles import (  # noqa: E402
    ARTICLE_PUBLICATION_DATES,
    ARTICLES_BY_KEY,
    ARTICLES_COPY,
    MONTE_CARLO_EXAMPLE,
    MONTE_CARLO_REPORT,
    MONTE_CARLO_SEARCH_EXAMPLE,
    STREAK_METHOD,
    STREAK_READING,
    STREAK_REPORT,
    STREAK_STAKES,
    STREAK_TABLE_AFTER,
    STREAK_TABLE_COPY,
    _num,
    article_url,
    articles_index_url,
)
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.calculator import calculator_url  # noqa: E402
from quant_trade.audit.engine import RISK_SAMPLES, run_audit  # noqa: E402
from quant_trade.audit.faq import faq_items  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.method import COPY as METHOD_COPY  # noqa: E402
from quant_trade.audit.method import METHOD_PATH  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    AUDIENCE_ARTICLES,
    SAMPLE_PAGE_PATHS,
    article_page,
    audit_path,
    method_page,
)
from quant_trade.audit.prop_presets import PRESETS  # noqa: E402
from quant_trade.audit.public_card import _pct  # noqa: E402
from quant_trade.audit.report import evidence_label  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.streaks import (  # noqa: E402
    CLUSTERED,
    EXACT_MAX_TRADES,
    MIN_TRADES,
    RARE,
    longest_run_tail,
    loss_streak_review,
)
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.audit.winrate import WINRATE_PATH  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
MONTE_CARLO = "monte-carlo-backtest"
STREAKS = "rachas-perdedoras"
KEYS = (MONTE_CARLO, STREAKS)
#: The table as the brief asks for it and as ``longest_run_tail`` gives it:
#: (win rate, trades) -> (median longest losing run, one-in-twenty run).
PINNED_STREAKS = {
    (0.45, 100): (6, 11),
    (0.45, 200): (8, 12),
    (0.45, 500): (9, 13),
    (0.50, 100): (6, 9),
    (0.50, 200): (7, 10),
    (0.50, 500): (8, 12),
    (0.55, 100): (5, 8),
    (0.55, 200): (6, 9),
    (0.55, 500): (7, 10),
    (0.60, 100): (4, 7),
    (0.60, 200): (5, 8),
    (0.60, 500): (6, 9),
}


class _Links(HTMLParser):
    """Every ``href`` and ``src``, entities unescaped."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name not in {"href", "src"} or value is None:
                continue
            # The site's embedded favicon is a local asset, not an outgoing link.
            if tag == "link" and value.startswith("data:image/svg+xml,"):
                continue
            self.links.append(value)


def _links(page: str) -> list[str]:
    parser = _Links()
    parser.feed(page)
    parser.close()
    return parser.links


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _prose_html(page: str) -> str:
    match = re.search(r"<article class='prose'>(.*?)</article>", page, re.S)
    assert match is not None
    return match.group(1)


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _stored(key: str, locale: str) -> list[str]:
    words = ARTICLES_BY_KEY[key].text[locale]
    texts = [words.title, words.summary, words.intro, words.seo_title or words.title]
    for section in words.sections:
        texts += [section.heading, *section.paragraphs]
    for question, answer in words.faq:
        texts += [question, answer]
    return texts


def _paragraphs(key: str, locale: str) -> list[str]:
    return [p for s in ARTICLES_BY_KEY[key].text[locale].sections for p in s.paragraphs]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    folder = tmp_path_factory.mktemp("articles")
    settings = AuditSettings(database_url=f"sqlite:///{folder}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", KEYS)
def test_metadata_structured_data_and_guard(key: str, locale: str) -> None:
    article = ARTICLES_BY_KEY[key]
    words = article.text[locale]
    assert 1 <= len(words.title) <= 60
    assert 40 <= len(words.summary) <= 155
    for text in _stored(key, locale):
        assert find_claims(text) == [], (key, locale, text)
    page = article_page(article, locale=locale, base_url=BASE)
    title = re.search(r"<title>([^<]+)</title>", page)
    assert title is not None and len(html.unescape(title.group(1))) <= 60
    assert find_claims(_visible(page)) == []
    assert find_claims(html.unescape(page)) == []
    # No promise, pass or endorsement wording in the article itself, in any language.
    lowered = " ".join(_stored(key, locale) + [_visible(_prose_html(page))]).lower()
    for stem in ("aprob", "aprova", "garant", "guarant", "rentable", "rentáve", "lucrativ"):
        assert stem not in lowered, (key, locale, stem)
    for stem in ("profitable", "verificad", "verified", "certific", "approv", "pass the"):
        assert stem not in lowered, (key, locale, stem)
    assert f"rel='canonical' href='{BASE}{article_url(key, locale)}'" in page
    detail, crumbs = [
        json.loads(block)
        for block in re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    ]
    assert detail["@type"] == "Article" and detail["headline"] == words.title
    assert detail["inLanguage"] == locale
    assert detail["datePublished"] == detail["dateModified"] == "2026-10-08"
    assert ARTICLE_PUBLICATION_DATES[key] == "2026-10-08"
    assert crumbs["@type"] == "BreadcrumbList"
    assert crumbs["itemListElement"][-1]["item"] == BASE + article_url(key, locale)


@pytest.mark.parametrize("locale", LOCALES)
def test_streak_table_cells_equal_longest_run_tail(locale: str) -> None:
    assert numbers.STREAK_WIN_RATES == (0.45, 0.50, 0.55, 0.60)
    assert numbers.STREAK_TRADE_COUNTS == (100, 200, 500)
    assert numbers.STREAK_MEDIAN == 0.5 and numbers.STREAK_RARE == RARE == 0.05
    page = article_page(ARTICLES_BY_KEY[STREAKS], locale=locale, base_url=BASE)
    table = re.search(r"<table class='article-streaks'>(.*?)</table>", page, re.S)
    assert table is not None
    rows = re.findall(r"<tr><th scope='row'>(.*?)</tr>", table.group(1))
    assert len(rows) == len(PINNED_STREAKS) == 12
    declared = evidence_label("DECLARED", locale)
    seen = []
    for row in rows:
        cells = [_visible(cell).strip() for cell in re.findall(r"(?:^|<td>)(.*?)</(?:th|td)>", row)]
        assert len(cells) == 4
        assert all(cell.startswith(f"{declared} · ") for cell in cells)
        rate_text, trades_text, median_text, rare_text = (
            cell.removeprefix(f"{declared} · ") for cell in cells
        )
        win_rate = int(rate_text.removesuffix(" %")) / 100
        trades = int(trades_text)
        # The cell, computed again here with the engine function: the longest k
        # whose P(longest losing run >= k) is still at least 0.5, and at least 0.05.
        tail = longest_run_tail(trades, 1.0 - win_rate, 60)
        assert tail[-1] < RARE
        median = int(np.max(np.nonzero(tail >= 0.5)[0]))
        rare = int(np.max(np.nonzero(tail >= RARE)[0]))
        assert (int(median_text), int(rare_text)) == (median, rare)
        assert PINNED_STREAKS[(win_rate, trades)] == (median, rare)
        assert numbers.streak_for(win_rate, trades).median_run == median
        assert numbers.streak_for(win_rate, trades).rare_run == rare
        assert numbers.streak_for(win_rate, trades).rare_chance == tail[rare] >= RARE
        seen.append((win_rate, trades))
    assert seen == list(PINNED_STREAKS)
    assert evidence_label("MEASURED", locale) not in _visible(table.group(1))
    caption = STREAK_TABLE_COPY[locale][5]
    assert caption.startswith("DECLARED ·") and "longest_run_tail" in caption
    assert find_claims(_visible(table.group(1))) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_streak_table_follows_the_calculation_section_by_its_title(locale: str) -> None:
    page = article_page(ARTICLES_BY_KEY[STREAKS], locale=locale, base_url=BASE)
    headings = [
        (match.start(), _visible(match.group(1)).strip())
        for match in re.finditer(r"<h2\b[^>]*>(.*?)</h2>", page, re.S)
    ]
    titles = [text for _, text in headings]
    after = STREAK_TABLE_AFTER[locale]
    assert titles.count(after) == 1, titles
    index = titles.index(after)
    assert headings[index + 1][1] == STREAK_TABLE_COPY[locale][0]
    table = re.search(r"<table class='article-streaks'>", page)
    assert table is not None
    assert headings[index + 1][0] < table.start() < headings[index + 2][0]
    # The explanation the table follows names the engine function and the assumption.
    assert STREAK_METHOD[locale] in _paragraphs(STREAKS, locale)
    # Running text carries no evidence label: that belongs in the table.
    assert not STREAK_METHOD[locale].startswith("DECLARED")
    assert "longest_run_tail" in STREAK_METHOD[locale]


@pytest.mark.parametrize("locale", LOCALES)
def test_streak_prose_reads_the_computed_rows(locale: str) -> None:
    paragraphs = _paragraphs(STREAKS, locale)
    reading, stakes = STREAK_READING[locale], STREAK_STAKES[locale]
    assert reading in paragraphs and stakes in paragraphs
    assert not reading.startswith("DECLARED") and not stakes.startswith("DECLARED")
    example = numbers.streak_for(*numbers.STREAK_EXAMPLE)
    assert (example.median_run, example.rare_run) == (7, 10)
    # The 1-in-20 streak is the longest one chance gives at least that often; for
    # this row it comes in about 9 histories in 100, and the prose prints that figure.
    chance = longest_run_tail(200, 0.5, 60)[10]
    assert round(chance, 4) == 0.0899 and example.rare_chance == chance
    printed = _pct(chance, locale)
    assert printed == {"es": "9,0 %", "en": "9.0 %", "pt": "9,0 %"}[locale]
    assert reading.count(printed) == 1 and stakes.count(printed) == 1
    at_least = {"es": "al menos 1 de cada 20", "en": "at least 1 history in 20"}
    assert at_least.get(locale, "pelo menos 1 em cada 20") in reading
    for exact in ("en 1 de cada 20 historiales", "in 1 history in 20 ", "em 1 em cada 20 hist"):
        assert exact not in reading and exact not in stakes
    high, low = numbers.streak_for(0.60, 200), numbers.streak_for(0.45, 200)
    short, long = numbers.streak_for(0.50, 100), numbers.streak_for(0.50, 500)
    prose = reading.replace(printed, "")
    figures = [int(value) for value in re.findall(r"\b\d+\b", prose)]
    # Each row's figures in the order the paragraph reads them.
    assert figures == [
        50,
        200,
        example.median_run,
        example.rare_run,
        1,
        20,
        60,
        high.median_run,
        high.rare_run,
        45,
        low.median_run,
        low.rare_run,
        50,
        100,
        500,
        short.median_run,
        long.median_run,
    ]
    # k losses at a fixed stake of the initial balance take k stakes.
    for risk in numbers.STREAK_RISKS:
        assert f"{_num(risk * 100, locale, 1)} %" in stakes
        assert f"{_num(example.rare_run * risk * 100, locale, 1)} %" in stakes
    intro = ARTICLES_BY_KEY[STREAKS].text[locale].intro
    assert intro.startswith(f"{example.rare_run} ")


def test_streak_report_paragraphs_follow_the_engine() -> None:
    # The report's "clustered" warning and the table share the one-in-twenty cut.
    assert CLUSTERED == RARE
    for locale in LOCALES:
        first, second = STREAK_REPORT[locale]
        assert _num(EXACT_MAX_TRADES, locale, 0) in first and "loss_streak_review" in first
        assert f" {MIN_TRADES} " in second and "NOT_MEASURED" in second
        assert (first, second) == tuple(_paragraphs(STREAKS, locale)[-3:-1])
    # Above EXACT_MAX_TRADES the report uses the table's recurrence: same cuts, same runs.
    trades = EXACT_MAX_TRADES + 1
    pnl = [-1.0 if i % 2 == 0 else 1.0 for i in range(trades)]
    review = loss_streak_review(pnl)
    loss_rate = sum(value < 0 for value in pnl) / trades
    row = numbers.streak_row(1.0 - loss_rate, trades)
    assert review["losing_run_chance"]["value"] == row.median_run
    assert review["losing_run_rare"]["value"] == row.rare_run


def test_monte_carlo_example_is_reproducible_from_its_seeds() -> None:
    # The settings the report runs with.
    assert numbers.MC_RISK_SAMPLES == RISK_SAMPLES
    assert inspect.signature(run_audit).parameters["seed"].default == numbers.MC_RISK_SEED
    assert (numbers.MC_SHUFFLE_SEED, numbers.MC_SHUFFLE_SAMPLES) == (SHUFFLE_SEED, SHUFFLE_SAMPLES)
    # The synthetic backtest, drawn again here from its documented seed and parameters.
    returns = np.random.default_rng(20261008).normal(0.0005, 0.01, 500)
    assert np.array_equal(returns, numbers.synthetic_series())
    first = drawdown_risk(returns, periods_per_year=252, samples=2000, seed=12345)
    again = drawdown_risk(returns, periods_per_year=252, samples=2000, seed=12345)
    assert first == again
    assert numbers.risk_summary(first) == numbers.MC_RISK
    assert shuffled_drawdown(returns) == shuffled_drawdown(returns)
    assert numbers.shuffle_summary(returns) == numbers.MC_SHUFFLE
    assert numbers.MC_RISK.block == DEFAULT_BLOCK_SIZE and float(numbers.MC_RISK.block).is_integer()
    assert (numbers.MC_RISK.samples, numbers.MC_RISK.horizon) == (2000, 252)
    # The search: 100 zero-mean series, the best final result kept.
    search = np.random.default_rng(20261009).normal(0.0, 0.01, (100, 250))
    best = search[int(np.argmax(np.prod(1.0 + search, axis=1)))]
    assert np.array_equal(best, numbers.search_best_series())
    assert numbers.risk_summary(numbers.resampled_risk(best)) == numbers.MC_SEARCH_RISK
    reference = np.random.default_rng(20261010).normal(0.0, 0.01, 5000)
    assert numbers.risk_summary(numbers.resampled_risk(reference)) == numbers.MC_REFERENCE_RISK
    # The figures the article prints, pinned to one decimal of a percentage.
    shown = {
        "observed": numbers.MC_SHUFFLE.observed,
        "low": numbers.MC_SHUFFLE.low,
        "median": numbers.MC_SHUFFLE.median,
        "high": numbers.MC_SHUFFLE.high,
        "risk_median": numbers.MC_RISK.median,
        "risk_p95": numbers.MC_RISK.p95,
        "risk_10": numbers.MC_RISK.at_least,
        "risk_20": numbers.MC_RISK.at_least_deep,
        "search_median": numbers.MC_SEARCH_RISK.median,
        "search_10": numbers.MC_SEARCH_RISK.at_least,
        "reference_median": numbers.MC_REFERENCE_RISK.median,
        "reference_10": numbers.MC_REFERENCE_RISK.at_least,
    }
    assert {name: round(value * 100, 1) for name, value in shown.items()} == {
        "observed": 12.2,
        "low": 7.5,
        "median": 10.6,
        "high": 16.2,
        "risk_median": 8.5,
        "risk_p95": 15.5,
        "risk_10": 32.9,
        "risk_20": 0.8,
        "search_median": 7.4,
        "search_10": 15.6,
        "reference_median": 14.8,
        "reference_10": 83.4,
    }
    # What the selection paragraph says: the chosen series looks milder than its generator.
    assert numbers.MC_SEARCH_RISK.median < numbers.MC_REFERENCE_RISK.median
    assert numbers.MC_SEARCH_RISK.at_least < numbers.MC_REFERENCE_RISK.at_least


@pytest.mark.parametrize("locale", LOCALES)
def test_monte_carlo_prose_prints_the_computed_figures(locale: str) -> None:
    paragraphs = _paragraphs(MONTE_CARLO, locale)
    example = MONTE_CARLO_EXAMPLE[locale]
    search = MONTE_CARLO_SEARCH_EXAMPLE[locale]
    assert all(paragraph in paragraphs for paragraph in (*example, search))
    assert not any(text.startswith("DECLARED") for text in (*example, search))
    for value in (
        numbers.MC_SHUFFLE.observed,
        numbers.MC_SHUFFLE.low,
        numbers.MC_SHUFFLE.median,
        numbers.MC_SHUFFLE.high,
    ):
        assert _pct(value, locale) in example[0]
    for value in (
        numbers.MC_RISK.median,
        numbers.MC_RISK.p95,
        numbers.MC_RISK.at_least,
        numbers.MC_RISK.at_least_deep,
    ):
        assert _pct(value, locale) in example[1]
    for value in (
        numbers.MC_SEARCH_RISK.median,
        numbers.MC_SEARCH_RISK.at_least,
        numbers.MC_REFERENCE_RISK.median,
        numbers.MC_REFERENCE_RISK.at_least,
    ):
        assert _pct(value, locale) in search
    for seed in (numbers.MC_SERIES_SEED, numbers.MC_SHUFFLE_SEED):
        assert str(seed) in example[0]
    assert str(numbers.MC_RISK_SEED) in example[1]
    for seed in (numbers.MC_SEARCH_SEED, numbers.MC_REFERENCE_SEED):
        assert str(seed) in search
    for name in ("shuffled_drawdown", "drawdown_risk"):
        assert name in " ".join(example)
    report = MONTE_CARLO_REPORT[locale]
    assert report in paragraphs and "drawdown_risk" in report
    assert _num(DEFAULT_BLOCK_SIZE, locale, 0) in report


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", KEYS)
def test_figures_use_the_language_decimal_separator(key: str, locale: str) -> None:
    prose = _visible(_prose_html(article_page(ARTICLES_BY_KEY[key], locale=locale)))
    # One or two decimals are editorial figures; a group of three digits is a thousand.
    wrong = r"\b\d+,\d{1,2}\b" if locale == "en" else r"\b\d+\.\d{1,2}\b"
    assert re.findall(wrong, prose) == []
    expected = {
        MONTE_CARLO: ("12.2 %", "1,000", "2,000", "5,000"),
        STREAKS: ("0.05", "1.0 %", "5,000"),
    }[key]
    for figure in expected:
        assert (figure if locale == "en" else figure.translate(str.maketrans(",.", ".,"))) in prose


EXPECTED_LINKS = {
    MONTE_CARLO: lambda locale: {
        SAMPLE_PAGE_PATHS[locale],
        calculator_url(locale),
        WINRATE_PATH[locale],
        audit_path(locale),
        METHOD_PATH[locale],
        article_url("sharpe-deflactado-track-record", locale),
        article_url("que-hacer-despues-del-backtest", locale),
        article_url(STREAKS, locale),
    },
    STREAKS: lambda locale: {
        audience_url("retos-prop-firm", locale),
        article_url("cuantos-intentos-reto-prop-firm", locale),
        WINRATE_PATH[locale],
        audit_path(locale),
        # Its next step is the win-rate calculator, not the luck calculator.
        article_url(MONTE_CARLO, locale),
    },
}


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", KEYS)
def test_internal_links_resolve_and_none_leave_the_site(
    client: TestClient, key: str, locale: str
) -> None:
    response = client.get(article_url(key, locale))
    assert response.status_code == 200
    assert f"<html lang='{locale}'>" in response.text
    own_host = urlsplit(BASE).hostname
    for link in _links(response.text):
        target = urlsplit(link)
        relative = not target.scheme and not target.netloc
        assert relative or (target.scheme == "https" and target.hostname == own_host), link
    main = {link for link in _links(_main(response.text)) if not link.startswith("#")}
    assert EXPECTED_LINKS[key](locale) <= main
    for link in sorted(main):
        assert client.get(link).status_code == 200, (key, locale, link)


def test_index_sitemap_and_case_page_list_the_new_articles(client: TestClient) -> None:
    root = ElementTree.fromstring(client.get("/sitemap.xml").content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    dated = {
        url.findtext("s:loc", namespaces=namespace): url.findtext("s:lastmod", namespaces=namespace)
        for url in root.findall("s:url", namespace)
    }
    assert len(dated) == len(root.findall("s:url", namespace))
    for locale in LOCALES:
        index = client.get(articles_index_url(locale)).text
        case = client.get(audience_url("retos-prop-firm", locale)).text
        for key in KEYS:
            path = article_url(key, locale)
            assert f"href='{path}'" in index
            assert dated[BASE + path] == ARTICLE_PUBLICATION_DATES[key] == "2026-10-08"
        assert f"href='{article_url(STREAKS, locale)}'" in _main(case)
        description = ARTICLES_COPY[locale]["summary"]
        assert "Monte Carlo" in description and len(description) <= 155
        assert find_claims(description) == []
    assert STREAKS in AUDIENCE_ARTICLES["retos-prop-firm"]


#: The section as each page must show it, written out: ``METHOD_COPY`` itself
#: is rewritten for "pt" by ``report_pt.install`` once ``report`` is imported.
RESAMPLING_TEXTS = {
    "es": ("Remuestreo y Monte Carlo", "Varias cifras del informe salen de simulaciones"),
    "en": ("Resampling and Monte Carlo", "Several figures in the report come from Monte Carlo"),
    "pt": ("Reamostragem e Monte Carlo", "Vários números do relatório saem de simulações"),
}


@pytest.mark.parametrize("locale", LOCALES)
def test_method_page_names_monte_carlo_where_it_explains_resampling(locale: str) -> None:
    page = method_page(locale=locale, base_url=BASE)
    text = _visible(_main(page))
    assert "Monte Carlo" in text
    title, opening = RESAMPLING_TEXTS[locale]
    assert f">{html.escape(title, quote=True)}<" in page
    assert opening in text
    for other, (other_title, other_opening) in RESAMPLING_TEXTS.items():
        if other != locale:
            assert other_title not in text and other_opening not in text, other
    assert find_claims(text) == []
    if locale == "pt":
        assert not any(word in text for word in ("archivo", "informe", "Sube "))


def test_portuguese_method_copy_installed_by_the_report_covers_every_key() -> None:
    # ``report_pt.install`` replaces the method page's "pt" texts with its own,
    # over the English: a key it lacks would read in English on /pt/metodologia.
    from quant_trade.audit import report_pt

    assert set(report_pt.REPORT["METHOD_COPY"]) == set(METHOD_COPY["en"])
    english = METHOD_COPY["en"]
    assert [key for key in english if METHOD_COPY["pt"][key] == english[key]] == []


@pytest.mark.parametrize("locale", LOCALES)
def test_faq_answers_whether_rigor_runs_a_monte_carlo(locale: str) -> None:
    pairs = faq_items(AuditSettings(), locale)
    matches = [(q, a) for q, a in pairs if "Monte Carlo" in q]
    assert len(matches) == 1
    question, answer = matches[0]
    assert find_claims(question) == [] and find_claims(answer) == []
    assert "Sharpe" in answer


@pytest.mark.parametrize("locale", LOCALES)
def test_the_prop_firm_section_names_no_firm(locale: str) -> None:
    firms = {rules.firm for rules in PRESETS.values()} - {"Generic"}
    stored = " ".join(_stored(STREAKS, locale))
    for firm in firms:
        assert firm not in stored, firm


@pytest.mark.parametrize("key", KEYS)
def test_english_prose_uses_british_spelling(key: str) -> None:
    prose = " ".join(_stored(key, "en"))
    american = (
        r"\b(?:optimiz\w*|favor\w*|analyz\w*|center\w*|summariz\w*|behavior\w*|organiz\w*"
        r"|recogniz\w*|color\w*|modeling|labeled)\b"
    )
    assert re.search(american, prose, re.I) is None


def test_portuguese_copy_has_no_spanish_words() -> None:
    for key in KEYS:
        for text in _stored(key, "pt"):
            for spanish in ("archivo", "informe", "artículo", "Sube ", "Precios", "racha"):
                assert spanish not in text, (key, spanish)
    for item in METHOD_COPY["pt"]["resampling"]:
        assert "informe" not in item and "archivo" not in item


def test_the_example_paths_exist_in_the_sitemap_pages() -> None:
    from quant_trade.audit.seo import PUBLIC_PAGES

    assert dict(SAMPLE_PAGE_PATHS) in list(PUBLIC_PAGES)
    for key in KEYS:
        assert {lang: article_url(key, lang) for lang in LOCALES} in list(PUBLIC_PAGES)
