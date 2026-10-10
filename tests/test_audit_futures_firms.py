"""The futures firms read on 2026-10-10: Take Profit Trader, MyFundedFutures,
Tradeify, Bulenox, Earn2Trade, Alpha Futures and Lucid Trading, in the presets,
the calculator pages and the report's firm table. Offline."""

from __future__ import annotations

import html
import re
from dataclasses import fields
from datetime import UTC, datetime

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import challenge_calc as calc  # noqa: E402
from quant_trade.audit import firmfit, seo  # noqa: E402
from quant_trade.audit.challenge_futures import FUTURES_FIRMS  # noqa: E402
from quant_trade.audit.engine import run_audit  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import _render, localize, untranslated  # noqa: E402
from quant_trade.audit.prop_presets import (  # noqa: E402
    ACCOUNT_SIZES,
    FUTURES_AS_OF,
    PRESETS,
    ChallengeRules,
)
from quant_trade.audit.report import render_html  # noqa: E402
from quant_trade.audit.sample import _sample_report, sample_result  # noqa: E402
from quant_trade.audit.schema import DeclaredMetadata, build_inputs  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 10, 10, tzinfo=UTC)
FIRM_NAMES = set(FUTURES_FIRMS.values())
KEYS = [key for key, rules in PRESETS.items() if rules.firm in FIRM_NAMES]
#: Each program's dollars as its page states them: account, target, daily loss
#: limit simulated (None when none is) and maximum loss.
DOLLARS: dict[str, tuple[int, int, int | None, int]] = {
    "take-profit-trader-test-50k": (50_000, 3_000, None, 2_000),
    "myfundedfutures-rapid-eod-50k": (50_000, 3_000, None, 2_000),
    "myfundedfutures-rapid-50k": (50_000, 3_000, None, 2_000),
    "myfundedfutures-pro-50k": (50_000, 3_000, None, 2_000),
    "myfundedfutures-builder-50k": (50_000, 3_000, 1_000, 2_000),
    "tradeify-select-50k": (50_000, 3_000, None, 2_000),
    "tradeify-growth-50k": (50_000, 3_000, 1_250, 2_000),
    "bulenox-qualification-eod-50k": (50_000, 3_000, 1_100, 2_500),
    "bulenox-momentum-eod-50k": (50_000, 3_000, 1_200, 2_250),
    "earn2trade-tcp-25k": (25_000, 1_750, 550, 1_500),
    "earn2trade-gauntlet-mini-50k": (50_000, 3_000, 1_100, 2_000),
    "alpha-futures-zero-50k": (50_000, 3_000, 1_000, 2_000),
    "alpha-futures-standard-50k": (50_000, 3_000, None, 2_000),
    "alpha-futures-advanced-50k": (50_000, 4_000, None, 1_750),
    "lucid-pro-50k": (50_000, 3_000, None, 2_000),
}
#: The words the brief keeps off these pages, in the three languages.
FORBIDDEN = re.compile(
    r"\b(aprobar\w*|aprobad\w*|pasar|pasas?|passar\w*|pass|passed|passes|passing|aprovar\w*|"
    r"aprovad\w*|verific\w*|verified|certificad\w*|certified|garantiza\w*|guarantee\w*|"
    r"garantid\w*|rentables?|profitable|lucrativ\w*|approved)\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("futures")
    settings = AuditSettings(database_url=f"sqlite:///{directory}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


# -- the presets ---------------------------------------------------------------


@pytest.mark.parametrize("key", KEYS)
def test_every_futures_preset_validates_and_cites_its_page(key: str) -> None:
    rules = PRESETS[key]
    # Built again from its own fields, __post_init__ accepts it.
    assert ChallengeRules(**{f.name: getattr(rules, f.name) for f in fields(rules)}) == rules
    assert rules.as_of == rules.markets_as_of == FUTURES_AS_OF == "2026-10-10"
    assert rules.phase == "1" and firmfit.program_keys(key) == [key]
    for url in (rules.source_url, rules.markets_source):
        assert url is not None and url.startswith("https://")
        # A page's address is in every href: none may carry a word the guard refuses.
        assert find_claims(url) == [] and FORBIDDEN.findall(url) == [], url
    assert rules.markets == ("futures",)
    assert rules.notes
    for note in rules.notes:
        assert find_claims(note) == [] and FORBIDDEN.findall(note) == [], note
        for locale in ("es", "pt"):
            translated = _render(note, locale)
            assert translated is not None and translated != note, (locale, note)
            assert find_claims(translated) == [] and FORBIDDEN.findall(translated) == []


def test_the_futures_firms_are_exactly_these_programs() -> None:
    programs = {(PRESETS[k].firm, PRESETS[k].program) for k in KEYS}
    assert programs == {
        ("Take Profit Trader", "Trading Test 50K"),
        ("MyFundedFutures", "Rapid EOD 50K"),
        ("MyFundedFutures", "Rapid 50K"),
        ("MyFundedFutures", "Pro 50K"),
        ("MyFundedFutures", "Builder 50K"),
        ("Tradeify", "Select 50K"),
        ("Tradeify", "Growth 50K"),
        ("Bulenox", "Qualification EOD 50K"),
        ("Bulenox", "Momentum EOD 50K"),
        ("Earn2Trade", "Trader Career Path 25K"),
        ("Earn2Trade", "Gauntlet Mini 50K"),
        ("Alpha Futures", "Zero 50K"),
        ("Alpha Futures", "Standard 50K"),
        ("Alpha Futures", "Advanced 50K"),
        ("Lucid Trading", "LucidPro 50K"),
    }
    assert set(KEYS) == set(DOLLARS)
    # The pages come after the firms already there, in the presets' order.
    assert list(calc.FIRMS)[-len(FUTURES_FIRMS) :] == list(FUTURES_FIRMS)
    assert tuple(calc.FIRMS.values()) == calc.FIRM_NAMES
    # Left out, with the reason in docs/AUDIT_SAAS.md: Studio (limited release),
    # Bulenox's intraday trailing option, Tradeify Lightning and the funded-only plans.
    names = " | ".join(PRESETS[k].program for k in KEYS)
    for program in ("Studio", "Lightning", "Option 1", "Fast Track", "LucidFlex", "LucidDirect"):
        assert program not in names, program
    assert "Elite Trader Funding" not in calc.FIRM_NAMES
    assert "Apex Trader Funding" not in calc.FIRM_NAMES


@pytest.mark.parametrize("key", KEYS)
def test_the_shares_are_the_dollars_the_pages_state(key: str) -> None:
    account, target, daily, loss = DOLLARS[key]
    rules = PRESETS[key]
    assert ACCOUNT_SIZES[key] == float(account)
    assert rules.program.endswith(f"{account // 1000}K")
    assert rules.profit_target * account == pytest.approx(target)
    assert rules.max_total_loss * account == pytest.approx(loss)
    if daily is None:
        assert rules.max_daily_loss is None and rules.daily_loss_basis == "none"
    else:
        # A dollar amount below the day's starting balance: the start-of-day floor
        # less a share of the initial balance.
        assert rules.daily_loss_basis == "initial_balance"
        assert rules.max_daily_loss is not None
        assert rules.max_daily_loss * account == pytest.approx(daily)
    # The note says the same dollars, as the page writes them.
    stated = rules.notes[0]
    for amount in (account, target, loss, *(() if daily is None else (daily,))):
        assert f"USD {amount:,}" in stated, (key, amount)


def test_the_stricter_readings_are_the_ones_simulated() -> None:
    kinds = {key: PRESETS[key].total_loss_type for key in KEYS}
    # The floor locks exactly at the starting balance: the simulator's own lock.
    locked = {key for key, kind in kinds.items() if kind == "trailing_eod_lock"}
    assert locked == {
        "take-profit-trader-test-50k",
        "earn2trade-tcp-25k",
        "earn2trade-gauntlet-mini-50k",
        "alpha-futures-zero-50k",
        "alpha-futures-standard-50k",
        "alpha-futures-advanced-50k",
    }
    # A lock at the starting balance plus USD 100, no lock in the evaluation, or a
    # page that names none: trailing without a lock, never more lenient.
    for key in set(KEYS) - locked:
        assert kinds[key] == "trailing_eod", key
    for key in ("myfundedfutures-builder-50k", "lucid-pro-50k"):
        assert any("plus USD 100" in note and "stricter" in note for note in PRESETS[key].notes)
    # Every best-day rule of the total profit is checked against the target (never larger).
    for key in KEYS:
        rules = PRESETS[key]
        assert rules.best_day_basis in (None, "profit_target"), key
    # Tradeify Growth: its evaluation has no consistency rule; the 35 % one is the
    # Sim Funded payouts' (consistency article), so no best day is checked.
    growth = PRESETS["tradeify-growth-50k"]
    assert growth.best_day_limit is None and growth.best_day_basis is None
    assert any("35 %" in note and "Sim Funded payouts" in note for note in growth.notes)
    # Bulenox Qualification: the 30-day access, not the FAQ's "as long as you need".
    assert PRESETS["bulenox-qualification-eod-50k"].time_limit_days == 30
    assert calc.horizon("bulenox-qualification-eod-50k") < calc.SIMULATOR_MAX_DAYS
    # A daily limit that only pauses the day is simulated as one that ends the path.
    soft = {
        "myfundedfutures-builder-50k",
        "tradeify-growth-50k",
        "bulenox-qualification-eod-50k",
        "bulenox-momentum-eod-50k",
        "alpha-futures-zero-50k",
    }
    for key in soft:
        assert PRESETS[key].max_daily_loss is not None
        assert any("which is stricter" in note for note in PRESETS[key].notes)
    # Earn2Trade's daily limit is a hard one; LucidPro is simulated with its limit off.
    assert PRESETS["earn2trade-tcp-25k"].max_daily_loss == pytest.approx(0.022)
    assert PRESETS["lucid-pro-50k"].max_daily_loss is None


def test_the_rules_an_automated_strategy_cannot_trade_are_said() -> None:
    for key in ("take-profit-trader-test-50k", *(k for k in KEYS if k.startswith("alpha-"))):
        notes = " ".join(PRESETS[key].notes)
        assert "prohibited" in notes and ("bots" in notes or "automated" in notes), key
    # Every program closes each position the same day.
    for key in KEYS:
        notes = " ".join(PRESETS[key].notes).lower()
        assert "overnight" in notes or "intraday only" in notes, key


@pytest.mark.parametrize("locale", LOCALES)
def test_a_program_whose_page_says_none_has_no_daily_limit(locale: str) -> None:
    none = calc._RULE_WORDS[locale]["daily_no_limit"]
    unstated = calc._RULE_WORDS[locale]["daily_none"]
    for key in (
        "myfundedfutures-rapid-eod-50k",
        "myfundedfutures-rapid-50k",
        "myfundedfutures-pro-50k",
        "tradeify-select-50k",
        "alpha-futures-standard-50k",
        "alpha-futures-advanced-50k",
    ):
        assert key in calc.NO_DAILY_LIMIT and calc.daily_clause(key, locale) == none
    # Take Profit Trader's pages list none without saying so; LucidPro sells one as
    # an option: both read "not simulated", never "none".
    for key in ("take-profit-trader-test-50k", "lucid-pro-50k"):
        assert key not in calc.NO_DAILY_LIMIT and calc.daily_clause(key, locale) == unstated


def test_each_note_cites_the_page_that_states_it() -> None:
    """Whoever opens a note's source finds the rule there."""
    notes = {key: " ".join(PRESETS[key].notes) for key in KEYS}
    assert "10468320-rules-consistency-rule" in notes["tradeify-growth-50k"]
    assert "14369021" not in notes["tradeify-growth-50k"]
    for key in (k for k in KEYS if k.startswith("alpha-futures-")):
        # The monthly fee's article says nothing about inactivity; its own one does.
        time = next(note for note in PRESETS[key].notes if "10 trading days" in note)
        assert time.index("9492068-monthly-subscription") < time.index("10 trading days")
        assert time.index("10 trading days") < time.index("12757982-inactivity-rule")
    for article in (
        "16226068-lucidpro-customization",
        "11404742-prohibited-microscalping",
        "11404736-prohibited-high-frequency-trading",
        "11404734-prohibited-hedging",
        "11404728-other-trading-activities",
    ):
        assert article in notes["lucid-pro-50k"], article
    assert "help-center/qualification#reset" in notes["bulenox-qualification-eod-50k"]
    for locale in LOCALES:
        deadline = calc.firm_faq("bulenox", locale)[1][1]
        center = {"es": "centro de ayuda", "en": "help center", "pt": "central de ajuda"}
        assert center[locale] in deadline


def test_what_daily_closes_cannot_see_is_said_with_the_stricter_side() -> None:
    # Bulenox Qualification: its daily limit counts open P&L and the page says it can be
    # watched in real time, so only the maximum-loss floor is left unstated there.
    floors = "whether the floors are also checked"
    floor = "whether the maximum-loss floor is also checked"
    qualification = PRESETS["bulenox-qualification-eod-50k"].notes
    assert not any(floors in note for note in qualification)
    assert any(floor in note for note in qualification)
    assert any(floors in note for note in PRESETS["bulenox-momentum-eod-50k"].notes)
    # Alpha Futures Zero: the Daily Loss Guard counts open P&L within the day.
    guard = next(n for n in PRESETS["alpha-futures-zero-50k"].notes if "Daily Loss Guard" in n)
    assert "stricter" in guard and "optimistic" in guard
    for locale, optimistic, once in (
        ("es", "optimista", "sin plazo"),
        ("en", "optimistic", "no time limit"),
        ("pt", "otimista", "sem prazo"),
    ):
        assert optimistic in calc.firm_faq("alpha-futures", locale)[2][1]
        # LucidPro: "never" holds on daily closes only; within the day it may not.
        lucid = calc.firm_faq("lucid-trading", locale)
        assert optimistic in lucid[1][1]
        assert lucid[0][1].count(once) == 1


# -- the pages -------------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("firm", list(FUTURES_FIRMS))
def test_each_futures_firm_page_answers_with_its_rules(
    site: TestClient, firm: str, locale: str
) -> None:
    path = calc.challenge_url(locale, firm)
    response = site.get(path)
    assert response.status_code == 200, path
    page = response.text
    assert f"<html lang='{locale}'>" in page
    assert f"<link rel='canonical' href='{BASE}{path}'>" in page
    for lang, other in calc.page_paths(firm).items():
        assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{other}'>" in page
    visible = _visible(_main(page))
    assert find_claims(visible) == [] and find_claims(html.unescape(page)) == []
    assert FORBIDDEN.findall(visible) == [], FORBIDDEN.findall(visible)
    assert calc.COPY[locale]["not_affiliated"] in visible
    assert FUTURES_AS_OF in visible
    keys = [k for program in calc.firm_programs(firm) for k in firmfit.program_keys(program)]
    assert {PRESETS[key].firm for key in keys} == {FUTURES_FIRMS[firm]}
    for key in keys:
        assert f"href='{PRESETS[key].source_url}'" in page
        # Each note, in the page's language.
        for note in PRESETS[key].notes:
            assert html.escape(localize(note, locale).split(" (https://", 1)[0]) in page
    faq = calc.firm_faq(firm, locale)
    assert 3 <= len(faq) <= 4
    for question, answer in faq:
        assert html.escape(question) in page and html.escape(answer) in page
        assert "{" not in answer and FORBIDDEN.findall(answer) == []
    # A figure computed for each program of the firm.
    figures = {"win_rate": "52", "avg_win": "0.9", "avg_loss": "0.6", "per_day": "1.5"}
    for program in calc.firm_programs(firm):
        computed = site.get(path, params={**figures, "program": program})
        assert computed.status_code == 200 and "data-challenge-result" in computed.text
        assert FORBIDDEN.findall(_visible(_main(computed.text))) == []


def test_the_futures_pages_are_in_the_sitemap_and_linked_from_the_calculator(
    site: TestClient,
) -> None:
    sitemap = site.get("/sitemap.xml").text
    for firm in FUTURES_FIRMS:
        assert calc.page_paths(firm) in seo.PUBLIC_PAGES
        for path in calc.page_paths(firm).values():
            assert f"<loc>{BASE}{path}</loc>" in sitemap
    for locale in LOCALES:
        main = site.get(calc.challenge_url(locale)).text
        for firm in FUTURES_FIRMS:
            assert f"href='{calc.challenge_url(locale, firm)}'" in main


@pytest.mark.parametrize("locale", LOCALES)
def test_the_answers_name_the_presets_dollars(locale: str) -> None:
    def usd(amount: float) -> str:
        text = f"{amount:,.0f}"
        return "USD " + (text if locale == "en" else text.replace(",", "."))

    # The programs whose answers spell out the target in dollars.
    for firm, key, question in (
        ("take-profit-trader", "take-profit-trader-test-50k", 0),
        ("earn2trade", "earn2trade-tcp-25k", 0),
        ("earn2trade", "earn2trade-gauntlet-mini-50k", 1),
        ("lucid-trading", "lucid-pro-50k", 0),
    ):
        rules, account = PRESETS[key], ACCOUNT_SIZES[key]
        answer = calc.firm_faq(firm, locale)[question][1]
        assert calc.rules_sentence(key, locale) in answer
        for amount in (account, rules.profit_target * account, rules.max_total_loss * account):
            assert usd(amount) in answer, (key, amount, answer)
    # The firms with several programs list each one's maximum loss in dollars.
    for firm in ("tradeify", "bulenox", "alpha-futures"):
        answers = " ".join(answer for _, answer in calc.firm_faq(firm, locale))
        for key in calc.firm_programs(firm):
            loss = PRESETS[key].max_total_loss * ACCOUNT_SIZES[key]
            assert f"{PRESETS[key].program}, {usd(loss)}" in answers, (firm, key)
    # Bulenox: the 30 days the preset uses, and the business days the simulator walks.
    deadline = calc.firm_faq("bulenox", locale)[1][1]
    assert str(calc.horizon("bulenox-qualification-eod-50k")) in deadline
    assert "30" in deadline


# -- the report's firm table -----------------------------------------------------


def test_the_sample_report_lists_the_futures_firms_without_figures() -> None:
    result = sample_result("es", bootstrap_samples=50)
    assert result.challenge is not None
    fit = result.challenge["firm_fit"]
    assert fit["status"] == "MEASURED"
    rows = {(row["firm"], row["program"]): row for row in fit["firms"]}
    for key in KEYS:
        rules = PRESETS[key]
        row = rows[(rules.firm, rules.program)]
        assert row["source_url"] == rules.source_url and row["as_of"] == rules.as_of
        # The public sample trades forex: a futures-only program is listed, not simulated.
        assert "pass" not in row and row["market"]["allowed"] == ["futures"]
        assert row["market"]["source_url"] == rules.markets_source
    assert untranslated(result.model_dump(mode="json")) == []


def test_a_futures_history_simulates_every_futures_program() -> None:
    daily = np.random.default_rng(3).normal(0.0012, 0.008, 400)
    fit = firmfit.firm_fit(daily, samples=200, seed=7, symbols=["NQZ4", "ESH5"])
    rows = {tuple(row["keys"]): row for row in fit["firms"]}
    for key in KEYS:
        row = rows[(key,)]
        assert row["pass"]["evidence"] == "MEASURED" and "market" not in row, key
        assert row["rules"][0]["max_total_loss"] == PRESETS[key].max_total_loss
        if PRESETS[key].best_day_limit is not None:
            assert row["pass_within_best_day"]["evidence"] == "MEASURED", key


@pytest.mark.parametrize("key", ["tradeify-growth-50k", "lucid-pro-50k"])
def test_a_report_on_a_futures_program_reads_in_every_language(key: str) -> None:
    declared = DeclaredMetadata(
        trials=120, cost_bps_per_side=1.0, oos_start="2024-06-03", challenge=key
    )
    inputs = build_inputs(
        None,
        declared,
        report_bytes=_sample_report(),
        report_filename="SyntheticSampleEA.html",
        now=NOW,
    )
    result = run_audit(
        inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=300
    )
    assert result.challenge is not None
    assert result.challenge["rules"]["key"] == key
    data = result.model_dump(mode="json")
    for locale in ("es", "pt"):
        assert untranslated(data, locale) == [], locale
    for locale in LOCALES:
        page = render_html(result, watermark=False, locale=locale)
        text = _visible(page)
        assert find_claims(text) == [] and find_claims(html.unescape(page)) == []
        first = localize(PRESETS[key].notes[0], locale)
        assert html.escape(first) in page, (locale, first)
