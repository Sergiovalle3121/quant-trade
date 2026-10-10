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


# -- review of 2026-10-10: notes, wording and order --------------------------------


def _notes(key: str) -> str:
    return " ".join(PRESETS[key].notes)


def test_notes_say_what_the_cited_pages_say() -> None:
    from quant_trade.audit.prop_presets import (
        ALPHA_EA_URL,
        ALPHA_NEWS_URL,
        E8_OVERVIEW_URL,
        MAVEN_FAQ_URL,
    )

    alpha = [k for k in NEW_KEYS if PRESETS[k].firm == "Alpha Capital Group"]
    for key in alpha:
        notes = _notes(key)
        # Alpha's EA article prohibits EAs that open trades on their own.
        assert ALPHA_EA_URL in notes and "open trades on their own are prohibited" in notes
        # The plan pages state a 5-minute news window; the news article says the
        # evaluation is free: a note names the article and says the page differs.
        assert "unrestricted" not in notes
        if PRESETS[key].program != "Alpha Swing":
            assert ALPHA_NEWS_URL in notes and "the plan page states the window" in notes
    # E8 Signature: no time limit and one closed trade every 60 days; EAs not on futures.
    signature = _notes("e8-signature-100k")
    assert "no time limit stated" not in signature and "every 60 days" in signature
    assert "not on Futures" in signature
    assert f"Expert advisors are not allowed ({E8_OVERVIEW_URL})." in PRESETS["e8-zero-100k"].notes
    # Maven: a trade risking more than the 3-Step's 2 % is prohibited all-in trading.
    maven = _notes("maven-3step-step")
    assert "risking more than 2 %" in maven and MAVEN_FAQ_URL in maven
    # FXIFY: the account page's name and the program's, together.
    for key in ("fxify-2phase-classic-phase1", "fxify-2phase-classic-phase2"):
        assert "2 Phase Static (Two Phase Classic)" in _notes(key)
    for locale in LOCALES:
        answer = calc.firm_faq("fxify", locale)[0][1]
        assert "(2 Phase Static)" in answer, answer


@pytest.mark.parametrize("locale", LOCALES)
def test_phases_with_the_same_target_say_it_is_per_phase(locale: str) -> None:
    each = {
        "es": "objetivo de 6 % en cada una de las 2 fases",
        "en": "a target of 6 % in each of the 2 phases",
        "pt": "meta de 6 % em cada uma das 2 fases",
    }[locale]
    for key in ("alpha-pro-6-phase1", "fundingpips-2step-pro-phase1"):
        assert calc.rules_sentence(key, locale).startswith(each), key
    # The Alpha FAQ (and its FAQPage) no longer reads as if Alpha Pro 6% had one phase.
    assert each in calc.firm_faq("alpha-capital-group", locale)[0][1]


@pytest.mark.parametrize("locale", LOCALES)
def test_a_program_without_a_daily_limit_says_so(site: TestClient, locale: str) -> None:
    for key in calc.NO_DAILY_LIMIT:
        assert PRESETS[key].max_daily_loss is None, key
    none = {"es": "sin límite de pérdida diaria", "en": "no daily loss limit"}.get(
        locale, "sem limite de perda diária"
    )
    for key in ("e8-signature-100k", "e8-zero-100k"):
        assert calc.daily_clause(key, locale) == none
    # Topstep's optional limit is still "not simulated", not "none".
    assert calc.daily_clause("topstep-50k-combine", locale) != none
    page = _visible(_main(site.get(calc.challenge_url(locale, "e8-markets")).text))
    # Neither the table cell nor the FAQ's rules sentence says "not simulated".
    assert calc.COPY[locale]["daily_none"] not in page
    assert calc._RULE_WORDS[locale]["daily_none"] not in page
    assert calc.COPY[locale]["daily_no_limit"] in page


@pytest.mark.parametrize("locale", LOCALES)
def test_firm_answers_match_the_calculator_on_the_same_page(locale: str) -> None:
    # Alpha: the calculator counts every day with trades (TRADED_FLAT_DAY), as the
    # page's own "what it computes" section says; the report is the one that may count more.
    day = calc.firm_faq("alpha-capital-group", locale)[3][1]
    with_trades = {
        "es": "todo día con operaciones",
        "en": "every day with trades",
        "pt": "todo dia com operações",
    }[locale]
    assert with_trades in day
    # Maven: the 2-Step's rule is missing from the simulator; the 1-Step's maximum
    # loss is what a daily figure cannot see. Two reasons, said apart.
    maven = calc.firm_faq("maven-trading", locale)[1][1]
    simulator = {"es": "el simulador no tiene", "en": "the simulator does not have"}.get(
        locale, "o simulador não tem"
    )
    assert simulator in maven
    assert maven.count(NEW_FIRMS_AS_OF) == 2


def test_no_question_needs_the_one_before_it() -> None:
    """A FAQPage question shows alone in a search result: "¿Y Alpha Swing?" says
    nothing there."""
    elliptic = re.compile(r"^(¿Y |And |What about |E o |E a )")
    for firm in calc.FIRMS:
        for locale in LOCALES:
            for question, _answer in calc.firm_faq(firm, locale):
                assert not elliptic.match(question), (firm, locale, question)


def test_the_firm_lists_come_from_one_helper() -> None:
    assert tuple(calc.FIRMS.values()) == calc.FIRM_NAMES
    assert calc.OTHER_FIRMS == len(calc.FIRMS) - len(calc.NAMED_FIRMS) >= 2
    for locale in LOCALES:
        for name in calc.NAMED_FIRMS:
            assert name in calc.COPY[locale]["summary"]
        assert f" {calc.OTHER_FIRMS} " in calc.COPY[locale]["summary"]
        assert len(calc.COPY[locale]["summary"]) <= 160
    from quant_trade.audit.pages import _full_items

    for locale, conjunction in (("es", "o"), ("en", "or"), ("pt", "ou")):
        assert calc.firm_names(locale, "or") in _full_items(locale)[0]
        assert calc.firm_names(locale, "or").endswith(f" {conjunction} Maven Trading")


@pytest.mark.parametrize("locale", LOCALES)
def test_the_prop_firm_page_describes_every_firm_it_counts(site: TestClient, locale: str) -> None:
    page = site.get(audience_url("retos-prop-firm", locale)).text
    match = re.search(r"<meta name='description' content='([^']*)'>", page)
    assert match is not None
    description = html.unescape(match.group(1))
    assert calc.firms_short(locale) in description and len(description) <= 160
    for prefix in ("og", "twitter"):
        tag = rf"<meta (?:name|property)='{prefix}:description' content='([^']*)'>"
        found = re.search(tag, page)
        assert found is not None and html.unescape(found.group(1)) == description
    assert "{" not in _visible(_main(page))


def test_no_public_page_lists_only_the_first_four_firms(site: TestClient) -> None:
    """The four firms read first, closed as a list ("The5ers y Topstep"), would read
    as every firm the simulator carries: no public page says that any more."""
    closed = re.compile(r"The5ers,? (o|y|or|and|ou|e) Topstep")
    for pair in seo.PUBLIC_PAGES:
        for path in pair.values():
            response = site.get(path)
            assert response.status_code == 200, path
            text = " ".join(html.unescape(response.text).split())
            found = closed.search(text)
            assert found is None, (path, text[max(0, found.start() - 80) : found.end()])


def test_rows_that_read_the_same_figure_go_by_name() -> None:
    assert firmfit.shown_share(0.88191) == firmfit.shown_share(0.87963375) == 0.88
    assert firmfit.shown_share(0.995) == firmfit.shown_share(0.99) == 0.99
    assert firmfit.shown_share(0.004) == 0.01 and firmfit.shown_share(0.0) == 0.0
    result = sample_result("es", bootstrap_samples=50)
    assert result.challenge is not None
    rows = [row for row in result.challenge["firm_fit"]["firms"] if row.get("pass")]
    order = [
        (
            -firmfit.shown_share((row.get("pass_within_best_day") or row["pass"])["value"]),
            row["firm"],
            row["program"],
        )
        for row in rows
    ]
    assert order == sorted(order)
