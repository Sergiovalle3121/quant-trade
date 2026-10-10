"""Retail articles preserve the shared renderer and disclose computed examples."""

from __future__ import annotations

import html
import json
import re

import pytest

from quant_trade.audit.articles import ARTICLES_BY_KEY, LUCK_TABLE_INPUTS, article_url
from quant_trade.audit.calculator import compute
from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import article_page
from quant_trade.audit.prop_presets import get_preset
from quant_trade.audit.reading import READING_PATH
from quant_trade.audit.report import evidence_label
from quant_trade.audit.retail_numbers import (
    COIN_NORMAL_TAIL,
    COIN_NULL_WIN_RATE,
    COIN_THRESHOLD_WIN_RATE,
    COIN_TRADE_COUNT,
    PROP_RISKS,
    PROP_STREAK_LENGTH,
    PROP_WIN_RATES,
    SIGNAL_DECLARED_WIN_RATE,
    declared_attempt_example,
    normal_coin_tail_probability,
)

RETAIL_KEYS = (
    "cuantos-intentos-reto-prop-firm",
    "copiar-senales-mql5-myfxbook",
    "bot-ia-backtest-suerte",
)
BASE = "https://audit.example"


def _visible(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _paragraphs(key: str, locale: str) -> list[str]:
    return [p for section in ARTICLES_BY_KEY[key].text[locale].sections for p in section.paragraphs]


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize("key", RETAIL_KEYS)
def test_retail_article_length_guard_and_structured_data(key: str, locale: str) -> None:
    article = ARTICLES_BY_KEY[key]
    words = article.text[locale]
    body = [words.intro, *_paragraphs(key, locale), *[text for pair in words.faq for text in pair]]
    assert 700 <= len(" ".join(body).split()) <= 1100
    page = article_page(article, locale=locale, base_url=BASE)
    prose = re.search(r"<article class='prose'>(.*?)</article>", page, re.S)
    assert prose
    assert 700 <= len(_visible(prose.group(1)).split()) <= 1100
    assert find_claims(page) == []
    blocks = [
        json.loads(s)
        for s in re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    ]
    detail, breadcrumbs = blocks
    assert detail["@type"] == "Article"
    assert detail["headline"] == words.title
    assert detail["datePublished"] == "2026-10-07"
    assert detail["mainEntityOfPage"] == BASE + article_url(key, locale)
    assert breadcrumbs["@type"] == "BreadcrumbList"
    assert breadcrumbs["itemListElement"][-1]["item"] == BASE + article_url(key, locale)


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_prop_examples_follow_preset_and_declared_arithmetic(locale: str) -> None:
    paragraphs = _paragraphs(RETAIL_KEYS[0], locale)
    rules = get_preset("generic-2step-phase1")
    preset = paragraphs[0]
    # Plain words for where the generic rules come from: no evidence label, no
    # internal file path.
    assert not preset.startswith("DECLARED")
    for field in (rules.profit_target, rules.max_total_loss, rules.max_daily_loss):
        assert f"{field:.0%}" in preset
    assert str(rules.min_trading_days) in preset
    assert rules.as_of in preset and rules.source_url not in preset
    assert {"es": "dos fases", "en": "two-step", "pt": "duas fases"}[locale] in preset
    examples = paragraphs[4]
    assert not examples.startswith("DECLARED")
    for win_rate in PROP_WIN_RATES:
        assert f"{win_rate:.0%}" in examples
        for risk in PROP_RISKS:
            value = declared_attempt_example(win_rate, risk)
            assert f"{risk:.1%}" in examples
            assert f"{value.expected_attempts:.2f}" in examples
    streak = paragraphs[6]
    assert not streak.startswith("DECLARED")
    assert str(PROP_STREAK_LENGTH) in streak
    for win_rate in PROP_WIN_RATES:
        assert f"{(1 - win_rate) ** PROP_STREAK_LENGTH:.1%}" in streak
    for risk in PROP_RISKS:
        assert f"{PROP_STREAK_LENGTH * risk:.1%}" in streak


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_signal_normal_example_is_derived_and_labeled(locale: str) -> None:
    paragraphs = _paragraphs(RETAIL_KEYS[1], locale)
    assert not any(p.startswith("DECLARED") for p in paragraphs)
    declared = " ".join(paragraphs)
    tail = normal_coin_tail_probability(
        COIN_TRADE_COUNT, COIN_NULL_WIN_RATE, COIN_THRESHOLD_WIN_RATE
    )
    assert tail == COIN_NORMAL_TAIL
    for value in (SIGNAL_DECLARED_WIN_RATE, COIN_NULL_WIN_RATE, COIN_THRESHOLD_WIN_RATE, tail):
        assert f"{value:.0%}" in declared
    assert str(COIN_TRADE_COUNT) in declared


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_ai_article_reuses_calculator_table_and_public_reader(locale: str) -> None:
    page = article_page(ARTICLES_BY_KEY[RETAIL_KEYS[2]], locale=locale, base_url=BASE)
    table = re.search(r"<table class='article-luck'>(.*?)</table>", page, re.S)
    assert table
    rows = re.findall(r"<tr><th scope='row'>(.*?)</tr>", table.group(1))
    assert len(rows) == len(LUCK_TABLE_INPUTS) == 9
    for row, inputs in zip(rows, LUCK_TABLE_INPUTS, strict=True):
        label = evidence_label("DECLARED", locale)
        value = compute(inputs)["luck_sharpe"]["value"]
        trials, luck = f"{inputs.trials:,}", f"{value:.2f}"
        if locale != "en":
            trials, luck = trials.replace(",", "."), luck.replace(".", ",")
        assert _visible(row).split() == [
            label,
            "·",
            trials,
            label,
            "·",
            f"{inputs.years:g}",
            label,
            "·",
            luck,
        ]
    assert f"href='{READING_PATH[locale]}'" in page
    costs = next(p for p in _paragraphs(RETAIL_KEYS[2], locale) if "2x" in p)
    assert not costs.startswith("DECLARED") and "NOT_MEASURED" in costs
