"""The firms read on 2026-10-10: FundingPips, Alpha Capital Group, E8 Markets,
FXIFY and Maven Trading, in the presets, the calculator pages and the report's
firm table. Offline."""

from __future__ import annotations

import html
import re
from dataclasses import fields

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import challenge_calc as calc  # noqa: E402
from quant_trade.audit import firmfit, seo  # noqa: E402
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import _render, untranslated  # noqa: E402
from quant_trade.audit.pages import _plain_date, upload_page  # noqa: E402
from quant_trade.audit.prop_presets import (  # noqa: E402
    ACCOUNT_SIZES,
    AS_OF,
    NEW_FIRMS_AS_OF,
    PRESETS,
    ChallengeRules,
)
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
#: The new firm pages: path segment and the firm's name in the presets.
NEW_FIRMS = {
    "fundingpips": "FundingPips",
    "alpha-capital-group": "Alpha Capital Group",
    "e8-markets": "E8 Markets",
    "fxify": "FXIFY",
    "maven-trading": "Maven Trading",
}
NEW_KEYS = [key for key, rules in PRESETS.items() if rules.firm in NEW_FIRMS.values()]
#: The words the brief keeps off these pages, in the three languages.
FORBIDDEN = re.compile(
    r"\b(aprobar\w*|pasar|pasas?|pass|passed|passes|passing|aprovar\w*|verific\w*|verified|"
    r"certificad\w*|certified|garantiza\w*|guarantee\w*|rentables?|profitable)\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("firms")
    settings = AuditSettings(database_url=f"sqlite:///{directory}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _main(page: str) -> str:
    """The page's own content, without the site's navigation and footer."""
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


# -- the presets ---------------------------------------------------------------


@pytest.mark.parametrize("key", NEW_KEYS)
def test_every_new_preset_validates_and_cites_its_page(key: str) -> None:
    rules = PRESETS[key]
    # Built again from its own fields, __post_init__ accepts it.
    assert ChallengeRules(**{f.name: getattr(rules, f.name) for f in fields(rules)}) == rules
    assert rules.as_of == NEW_FIRMS_AS_OF == "2026-10-10"
    assert rules.source_url.startswith("https://")
    assert rules.notes and all(find_claims(note) == [] for note in rules.notes)
    # Every note and every phase name reads in Spanish and Portuguese.
    for text in (*rules.notes, rules.phase):
        if not text.isdigit():
            assert _render(text, "es") is not None, text
            assert _render(text, "pt") is not None, text


def test_the_new_firms_are_exactly_the_five_with_their_programs() -> None:
    programs = {(PRESETS[k].firm, PRESETS[k].program) for k in NEW_KEYS}
    assert programs == {
        ("FundingPips", "2-Step Standard"),
        ("FundingPips", "2-Step Pro"),
        ("FundingPips", "2-Step Flex"),
        ("FundingPips", "1-Step Flex"),
        ("Alpha Capital Group", "Alpha Pro 8%"),
        ("Alpha Capital Group", "Alpha Pro 10%"),
        ("Alpha Capital Group", "Alpha Pro 6%"),
        ("Alpha Capital Group", "Alpha Swing"),
        ("E8 Markets", "Signature 100K"),
        ("E8 Markets", "Zero 100K"),
        ("FXIFY", "Two Phase Classic"),
        ("FXIFY", "Three Phase"),
        ("Maven Trading", "3-Step"),
    }
    assert {calc.FIRMS[slug] for slug in NEW_FIRMS} == set(NEW_FIRMS.values())


def test_programs_the_simulator_cannot_take_stricter_are_left_out() -> None:
    """A maximum loss trailing a high reached within the day, a daily profit cap
    and a minimum of days that each close with a set gain have no stricter
    approximation on daily closes: those programs have no preset."""
    names = " | ".join(PRESETS[k].program for k in NEW_KEYS)
    for program in (
        "One Phase",
        "Two Phase Standard",
        "Two Phase Pro",
        "Lightning",
        "Alpha One",
        "E8 One",
        "E8 Pro",
        "1-Step Model",
    ):
        assert program not in names, program
    maven = {PRESETS[k].program for k in NEW_KEYS if PRESETS[k].firm == "Maven Trading"}
    assert maven == {"3-Step"}
    # What is in fits the simulator's types: static floors, or the end-of-day
    # trailing E8 Markets publishes (Zero 100K without the lock, the stricter reading).
    for key in NEW_KEYS:
        rules = PRESETS[key]
        expected = {"e8-signature-100k": "trailing_eod_lock", "e8-zero-100k": "trailing_eod"}
        assert rules.total_loss_type == expected.get(key, "static"), key


def test_the_stricter_readings_are_the_ones_simulated() -> None:
    # FXIFY Classic: its page says 4 minimum days, the general rules 5.
    for key in ("fxify-2phase-classic-phase1", "fxify-2phase-classic-phase2"):
        assert PRESETS[key].min_trading_days == 5
        assert any("uses 5 (stricter)" in note for note in PRESETS[key].notes)
    # E8 Zero: 40 % of the total profit, checked against the target (never larger at the pass).
    zero = PRESETS["e8-zero-100k"]
    assert (zero.best_day_limit, zero.best_day_basis) == (0.40, "profit_target")
    # FundingPips Flex: the 80 % split, the one whose minimum is plain trading days.
    assert PRESETS["fundingpips-2step-flex-phase1"].min_trading_days == 1
    # One minimum day reads in the singular.
    for locale, one, many in (
        ("es", "mínimo 1 día de trading", "1 días"),
        ("en", "at least 1 trading day", "1 trading days"),
        ("pt", "mínimo de 1 dia de trading", "1 dias"),
    ):
        sentence = calc.rules_sentence("fundingpips-2step-flex-phase1", locale)
        assert one in sentence and many not in sentence, sentence
    # Three identical phases count three times in the firm table and the calculator.
    for key in ("fxify-3phase-step", "maven-3step-step"):
        assert firmfit.REPEATS[key] == 3 == calc.phase_count(key)


def test_e8_limits_are_the_dollars_its_pages_state() -> None:
    for key, target, loss in (
        ("e8-signature-100k", 6_000, 3_000),
        ("e8-zero-100k", 6_500, 3_000),
    ):
        account = ACCOUNT_SIZES[key]
        assert account == 100_000.0
        assert PRESETS[key].profit_target * account == pytest.approx(target)
        assert PRESETS[key].max_total_loss * account == pytest.approx(loss)
    for locale, dollars in (("es", "USD 3.000"), ("en", "USD 3,000"), ("pt", "USD 3.000")):
        answer = calc.firm_faq("e8-markets", locale)[0][1]
        assert answer.count(dollars) == 2, answer


# -- the pages -------------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("firm", list(NEW_FIRMS))
def test_each_new_firm_page_answers_with_its_rules(
    site: TestClient, firm: str, locale: str
) -> None:
    path = calc.challenge_url(locale, firm)
    response = site.get(path)
    assert response.status_code == 200, path
    page = response.text
    assert f"<link rel='canonical' href='{BASE}{path}'>" in page
    for lang, other in calc.page_paths(firm).items():
        assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{other}'>" in page
    visible = _visible(_main(page))
    assert find_claims(visible) == [] and find_claims(html.unescape(page)) == []
    assert FORBIDDEN.findall(visible) == [], FORBIDDEN.findall(visible)
    assert calc.COPY[locale]["not_affiliated"] in visible
    assert NEW_FIRMS_AS_OF in visible
    for key in [k for program in calc.firm_programs(firm) for k in firmfit.program_keys(program)]:
        assert f"href='{PRESETS[key].source_url}'" in page
    for question, answer in calc.firm_faq(firm, locale):
        assert html.escape(question) in page and html.escape(answer) in page
    # A figure computed for a declared program of the firm, too.
    program = calc.firm_programs(firm)[0]
    figures = {"win_rate": "52", "avg_win": "0.9", "avg_loss": "0.6", "per_day": "1.5"}
    computed = site.get(path, params={**figures, "program": program})
    assert computed.status_code == 200 and "data-challenge-result" in computed.text
    assert FORBIDDEN.findall(_visible(_main(computed.text))) == []


def test_the_new_pages_are_in_the_sitemap_and_linked_from_the_calculator(
    site: TestClient,
) -> None:
    sitemap = site.get("/sitemap.xml").text
    for firm in NEW_FIRMS:
        assert calc.page_paths(firm) in seo.PUBLIC_PAGES
        for path in calc.page_paths(firm).values():
            assert f"<loc>{BASE}{path}</loc>" in sitemap
    for locale in LOCALES:
        main = site.get(calc.challenge_url(locale)).text
        for firm in NEW_FIRMS:
            assert f"href='{calc.challenge_url(locale, firm)}'" in main


def test_the_upload_form_says_when_each_firm_was_read() -> None:
    for locale, words in (
        ("es", "entre el {first} y el {last}"),
        ("en", "between {first} and {last}"),
        ("pt", "entre {first} e {last}"),
    ):
        page = html.unescape(upload_page(locale=locale))
        first, last = _plain_date(AS_OF, locale), _plain_date(NEW_FIRMS_AS_OF, locale)
        assert words.format(first=first, last=last) in page


@pytest.mark.parametrize("locale", LOCALES)
def test_the_prop_firm_page_names_every_firm_it_counts(site: TestClient, locale: str) -> None:
    text = _visible(site.get(audience_url("retos-prop-firm", locale)).text)
    for name in ("FTMO", "Topstep", *NEW_FIRMS.values()):
        assert name in text, name
    assert find_claims(text) == []


# -- the report's firm table -----------------------------------------------------


def test_the_sample_report_compares_the_new_firms() -> None:
    result = sample_result("es", bootstrap_samples=50)
    assert result.challenge is not None
    fit = result.challenge["firm_fit"]
    assert fit["status"] == "MEASURED"
    rows = {(row["firm"], row["program"]): row for row in fit["firms"]}
    for key in NEW_KEYS:
        rules = PRESETS[key]
        row = rows[(rules.firm, rules.program)]
        assert row["source_url"] == rules.source_url and row["as_of"] == rules.as_of
        if rules.markets == ("futures",):
            # The public sample trades forex: a futures-only program is listed, not simulated.
            assert "pass" not in row and row["market"]["allowed"] == ["futures"]
        else:
            assert row["pass"]["evidence"] == "MEASURED", key
    three = rows[("FXIFY", "Three Phase")]
    assert three["phases"] == 3
    assert untranslated(result.model_dump(mode="json")) == []
