"""The free prop-firm challenge calculator: declared figures through the report's simulator."""

from __future__ import annotations

import html
import json
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import challenge_calc as calc  # noqa: E402
from quant_trade.audit import firmfit, funnel, seo, winrate  # noqa: E402
from quant_trade.audit.analytics import simulate_challenge  # noqa: E402
from quant_trade.audit.articles import _num, article_url  # noqa: E402
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.prop_presets import PRESETS  # noqa: E402
from quant_trade.audit.public_card import PublicClaim  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import TOOL_KEYS, TOOLS_PATH  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}
#: A declared FTMO 2-Step in R, with the trades behind the win rate and a fee.
FIGURES = {
    "win_rate": "45",
    "unit": "r",
    "avg_win": "1.5",
    "avg_loss": "1",
    "risk": "1",
    "per_day": "2",
    "trades": "60",
    "program": "ftmo-2step-phase1",
    "fee": "155",
}
#: The same in % of the balance, without the optional fields.
PCT = {"win_rate": "52", "avg_win": "0.9", "avg_loss": "0.6", "per_day": "1.5"}
#: Words the brief keeps off these pages, in the three languages.
FORBIDDEN = re.compile(
    r"\b(aprobar\w*|aprobad\w*|pasar|pasas?|pass|passed|passes|passing|aprovar\w*|aprovad\w*|"
    r"verificad\w*|verified|certificad\w*|certified|garantiza\w*|guarantee\w*|garantid\w*|"
    r"rentables?|profitable|lucrativ\w*|approved)\b",
    re.IGNORECASE,
)
ALL_PATHS = [pytest.param(path, id=path) for path in calc.PAGES]


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("challenge")
    settings = AuditSettings(database_url=f"sqlite:///{directory}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _fresh(tmp_path: Path, **headers: str) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)), headers=headers)


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _visible(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _links(page: str) -> list[str]:
    return [html.unescape(value) for value in re.findall(r"\bhref=['\"]([^'\"]*)", page)]


def _result(page: str) -> str:
    found = re.search(r"<table class='calc-result' data-challenge-result>.*?</table>", page, re.S)
    assert found is not None
    return found.group(0)


def _row(page: str, key: str) -> str:
    found = re.search(rf"<tr data-row='{key}'>(.*?)</tr>", _result(page), re.S)
    assert found is not None, key
    return _visible(found.group(1))


def _textarea(page: str, ident: str) -> str:
    found = re.search(rf"<textarea\b[^>]*\bid='{ident}'[^>]*>(.*?)</textarea>", page, re.S)
    assert found is not None, ident
    return html.unescape(found.group(1))


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def _parse(values: dict[str, str], firm: str = "") -> calc.ChallengeInput:
    parsed = calc.parse(values, firm)
    assert parsed.errors == () and parsed.value is not None, parsed.errors
    return parsed.value


# -- the pages ---------------------------------------------------------------


@pytest.mark.parametrize("path", ALL_PATHS)
def test_every_page_answers_in_its_language_and_is_clean(site: TestClient, path: str) -> None:
    locale, firm = calc.PAGES[path]
    for params in ({}, FIGURES if not firm or firm == "ftmo" else PCT):
        response = site.get(path, params=params)
        assert response.status_code == 200, (path, params)
        page = response.text
        assert f"<html lang='{locale}'>" in page
        assert page.count("<h1") == 1
        assert "<meta name='robots' content='index, follow'>" in page
        assert f"<link rel='canonical' href='{BASE}{path}'>" in page
        for lang, other in calc.page_paths(firm).items():
            assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{other}'>" in page
        default = calc.page_paths(firm)["es"]
        assert f"<link rel='alternate' hreflang='x-default' href='{BASE}{default}'>" in page
        assert find_claims(html.unescape(page)) == []
        visible = _visible(_main(page))
        assert find_claims(visible) == []
        assert FORBIDDEN.findall(visible) == [], (path, FORBIDDEN.findall(visible))
        # The calculator is a form that works with GET and without script.
        assert f"<form method='get' action='{path}' class='calc-form'>" in page
        if params:
            assert "data-challenge-result" in page


@pytest.mark.parametrize("locale", LOCALES)
def test_copy_passes_the_guard_and_the_brief_words(locale: str) -> None:
    texts = _strings(calc.COPY[locale])
    for firm in calc.FIRMS:
        texts += _strings(calc.FIRM_COPY[firm][locale])
        texts += [text for pair in calc.firm_faq(firm, locale) for text in pair]
    for key in calc.PROGRAMS:
        texts.append(calc.rules_sentence(key, locale))
    for text in texts:
        assert find_claims(text) == [], text
        assert FORBIDDEN.findall(text) == [], text
    if locale == "pt":
        for text in texts:
            for word in ("informe", "archivo", "Sube "):
                assert word not in text, (word, text)


def test_firm_pages_are_the_firms_with_a_published_preset() -> None:
    published = {rules.firm for rules in PRESETS.values() if rules.source_url.startswith("https")}
    assert set(calc.FIRMS.values()) == published
    assert set(calc.PROGRAMS) == {firmfit.program_keys(key)[0] for key in PRESETS} - {
        "generic-2step-phase1"
    }
    for firm, name in calc.FIRMS.items():
        assert calc.firm_programs(firm)
        assert all(PRESETS[key].firm == name for key in calc.firm_programs(firm))


def test_metadata_is_own_and_within_bounds() -> None:
    from quant_trade.audit.challenge_pages import challenge_page

    for locale in LOCALES:
        titles, descriptions = set(), set()
        for firm in ("", *calc.FIRMS):
            page = challenge_page(locale=locale, firm=firm, base_url=BASE)
            title = html.unescape(re.search(r"<title>(.*?)</title>", page).group(1))  # type: ignore[union-attr]
            description = html.unescape(
                re.search(r"<meta name='description' content='([^']*)'>", page).group(1)  # type: ignore[union-attr]
            )
            assert 15 <= len(title) <= 65 and title.endswith(" · Rigor"), title
            assert 50 <= len(description) <= 160, (len(description), description)
            titles.add(title)
            descriptions.add(description)
        assert len(titles) == len(descriptions) == 1 + len(calc.FIRMS)


@pytest.mark.parametrize("path", ALL_PATHS)
def test_structured_data_is_a_free_web_application(site: TestClient, path: str) -> None:
    locale, firm = calc.PAGES[path]
    page = site.get(path).text
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    data = [json.loads(block) for block in blocks]
    app = next(item for item in data if item.get("@type") == "WebApplication")
    assert app["url"] == BASE + path
    assert app["inLanguage"] == locale
    assert app["isAccessibleForFree"] is True
    assert app["offers"] == {"@type": "Offer", "price": "0", "priceCurrency": "USD"}
    faq = [item for item in data if item.get("@type") == "FAQPage"]
    if not firm:
        assert faq == []
        return
    # The firm page's questions, the same ones the page shows, answered from the presets.
    questions = calc.firm_faq(firm, locale)
    assert 3 <= len(questions) <= 4
    assert [entry["name"] for entry in faq[0]["mainEntity"]] == [q for q, _ in questions]
    for question, answer in questions:
        assert f"<h3>{html.escape(question)}</h3><p>{html.escape(answer)}</p>" in page


@pytest.mark.parametrize("path", ALL_PATHS)
def test_rules_table_has_source_date_and_no_affiliation(site: TestClient, path: str) -> None:
    locale, firm = calc.PAGES[path]
    page = site.get(path).text
    programs = calc.firm_programs(firm) if firm else calc.PROGRAMS[:1]
    for program in programs:
        for key in firmfit.program_keys(program):
            rules = PRESETS[key]
            assert f"href='{rules.source_url}' rel='noopener nofollow'" in page
            assert rules.as_of in _visible(page)
            assert calc._pct(rules.profit_target, locale) in _visible(page)
    assert html.escape(calc.COPY[locale]["not_affiliated"]) in page
    assert "data-challenge-affiliation" in page
    if firm:
        # A page with content of its own: every program of the firm, phase by phase.
        rows = re.search(r"<table class='challenge-rules'>.*?</table>", page, re.S)
        assert rows is not None
        expected = sum(len(firmfit.program_keys(p)) for p in calc.firm_programs(firm))
        assert rows.group(0).count("<tr><th scope='row'>") == expected


def test_topstep_answers_name_the_preset_dollars() -> None:
    answer = dict(calc.firm_faq("topstep", "en"))[
        "What is the maximum loss of each Trading Combine?"
    ]
    for key in calc.firm_programs("topstep"):
        account = calc.account_size(key)
        assert account is not None
        assert f"USD {PRESETS[key].max_total_loss * account:,.0f}" in answer
    assert "USD 2.000" in calc.firm_faq("topstep", "es")[0][1]


# -- the figures -------------------------------------------------------------


def test_figures_are_simulate_challenge_on_the_preset_rules(site: TestClient) -> None:
    value = _parse(FIGURES)
    assert value.win == pytest.approx(0.015) and value.loss == pytest.approx(0.01)
    daily = calc.synthetic_daily_returns(value.win_rate, value.win, value.loss, value.per_day)
    assert len(daily) == calc.SYNTHETIC_DAYS
    reading = calc.compute(value)
    assert [key for key, _ in reading.declared.phases] == firmfit.program_keys(value.program)
    for key, result in reading.declared.phases:
        direct = simulate_challenge(daily, PRESETS[key], samples=calc.SAMPLES, seed=calc.SEED)
        assert result["probability"] == direct["probability"], key
        assert result["rules"] == PRESETS[key].to_dict()
        assert result["method"]["samples"] == calc.SAMPLES
    program = firmfit.program_outcomes(daily, value.program, samples=calc.SAMPLES, seed=calc.SEED)
    for name in ("pass", "fail_daily_loss", "fail_total_loss", "unfinished"):
        assert reading.declared.outcome[name]["value"] == pytest.approx(program[name]["value"])
    total = sum(
        float(reading.declared.outcome[name]["value"])
        for name in ("pass", "fail_daily_loss", "fail_total_loss", "unfinished")
    )
    assert total == pytest.approx(1.0)
    for locale in LOCALES:
        page = site.get(calc.challenge_url(locale), params=FIGURES).text
        shown = _row(page, "pass")
        expected = f"{_num(float(program['pass']['value']) * 100, locale, 1)} %"
        assert expected in shown, (locale, shown)
        assert f"{_num(float(program['fail_total_loss']['value']) * 100, locale, 1)} %" in (
            _row(page, "total")
        )
        assert "badge DECLARED" in _result(page)


def test_synthetic_days_follow_the_declared_figures() -> None:
    daily = calc.synthetic_daily_returns(0.55, 0.01, 0.007, 2.0)
    # Two trades a day: two wins, one of each or two losses, nothing else.
    assert set(np.round(daily, 10)) <= {0.02, 0.003, -0.014}
    assert np.mean(daily) == pytest.approx(2 * (0.55 * 0.01 - 0.45 * 0.007), abs=1.5e-3)
    half = calc.synthetic_daily_returns(0.55, 0.01, 0.007, 0.5)
    assert np.mean(half == 0.0) == pytest.approx(0.5, abs=0.05)
    # A lower win rate only turns winners into losers, day by day.
    lower = calc.synthetic_daily_returns(0.40, 0.01, 0.007, 2.0)
    assert (lower <= daily + 1e-12).all()


def test_the_query_reproduces_the_result(site: TestClient, tmp_path: Path) -> None:
    first = site.get(calc.challenge_url("es"), params=FIGURES).text
    shared = _textarea(first, "challenge-share-link")
    assert shared.startswith(f"{BASE}{calc.challenge_url('es')}?")
    assert parse_qs(urlsplit(shared).query)["ref"] == ["reto"]
    assert "reto" in funnel.REF_TAGS
    assert _textarea(first, "challenge-share-text").endswith(shared)
    # The same figures in a new process (no cache): the seed gives the same table.
    calc.compute.cache_clear()
    again = _fresh(tmp_path).get(shared.removeprefix(BASE)).text
    assert _result(again) == _result(first)
    # "1.5" and "1.50" are one input, one link and one result.
    padded = site.get(calc.challenge_url("es"), params={**FIGURES, "avg_win": "1.50"}).text
    assert _textarea(padded, "challenge-share-link") == shared
    assert _result(padded) == _result(first)


def test_decimal_commas_and_spaces_read_as_the_same_numbers(site: TestClient) -> None:
    point = _parse({"win_rate": "55.5", "avg_win": "0.8", "avg_loss": "0.6", "per_day": "1.5"})
    for typed in (
        {"win_rate": "55,5", "avg_win": "0,8", "avg_loss": "0,6", "per_day": "1,5"},
        {"win_rate": " 55,5 ", "avg_win": " 0,8", "avg_loss": "0,6 ", "per_day": "1,5"},
        {"win_rate": "55,5 %", "avg_win": "0.8", "avg_loss": "0,60", "per_day": "1.50"},
    ):
        assert _parse(typed) == point, typed
    # Fees and trade counts take a thousands mark; a count never takes a fraction.
    for fee in ("1080", "1.080", "1,080", "1 080", "1 080", "1.080,00", "1,080.00"):
        assert _parse({**PCT, "fee": fee}).fee == 1080.0, fee
    assert _parse({**PCT, "fee": "155,5"}).fee == 155.5
    assert _parse({**PCT, "trades": "1.000"}).trades == 1000
    assert calc.parse({**PCT, "trades": "40,5"}).errors == ("trades",)
    response = site.get(
        calc.challenge_url("es"),
        params={"win_rate": "55,5", "avg_win": "0,8", "avg_loss": "0 ,6", "per_day": "1,5"},
    )
    assert response.status_code == 200
    plain = site.get(
        calc.challenge_url("es"), params={k: str(v) for k, v in calc.share_values(point).items()}
    )
    assert _result(response.text) == _result(plain.text)


@pytest.mark.parametrize("locale", LOCALES)
def test_invalid_inputs_give_a_clear_message_and_never_a_500(site: TestClient, locale: str) -> None:
    words = calc.COPY[locale]
    cases = (
        ({**FIGURES, "win_rate": "0"}, "win_rate"),
        ({**FIGURES, "win_rate": "100"}, "win_rate"),
        ({**FIGURES, "win_rate": "150"}, "win_rate"),
        ({**FIGURES, "win_rate": "-5"}, "win_rate"),
        ({**FIGURES, "avg_loss": "0"}, "avg_loss"),
        ({**PCT, "avg_loss": "0,0"}, "avg_loss"),
        ({**PCT, "avg_win": "80"}, "avg_win"),
        ({**FIGURES, "avg_win": "abc"}, "number"),
        ({**FIGURES, "win_rate": "nan"}, "number"),
        ({**FIGURES, "win_rate": "1e5"}, "number"),
        ({**FIGURES, "per_day": "0"}, "per_day"),
        ({**FIGURES, "risk": "25"}, "risk"),
        ({**FIGURES, "risk": ""}, "missing"),
        ({"win_rate": "55"}, "missing"),
        ({**FIGURES, "trades": "40,5"}, "trades"),
        ({**FIGURES, "trades": "0"}, "trades"),
        ({**FIGURES, "fee": "-1"}, "fee"),
        ({**FIGURES, "unit": "lots"}, "unit"),
        ({**FIGURES, "program": "generic-2step-phase1"}, "program"),
        ({**FIGURES, "program": "../etc"}, "program"),
    )
    path = calc.challenge_url(locale)
    for params, code in cases:
        response = site.get(path, params=params)
        assert response.status_code == 400, (params, response.status_code)
        text = _visible(response.text)
        assert words[f"error_{code}"] in text, (params, code)
        assert "<p class='error' role='alert'>" in response.text
        assert "data-challenge-result" not in response.text
        assert find_claims(text) == []
    # A rejected value is never written back into the form; valid ones are.
    page = site.get(path, params={**FIGURES, "win_rate": "150"}).text
    assert "value='150'" not in page
    assert "id='r-avg_win' name='avg_win'" in page and "value='1.5'" in page
    # A field sent twice is refused, as in the win-rate calculator.
    twice = site.get(path, params=[*FIGURES.items(), ("win_rate", "50")])
    assert twice.status_code == 400
    assert words["error_invalid"] in _visible(twice.text)
    # A firm page takes only its own programs.
    other = site.get(
        calc.challenge_url(locale, "ftmo"), params={**PCT, "program": "topstep-50k-combine"}
    )
    assert other.status_code == 400
    assert words["error_program"] in _visible(other.text)


def test_identical_synthetic_days_are_not_measured(site: TestClient) -> None:
    # Every trade wins at 99.99 %: every synthetic day is the same and cannot be resampled.
    params = {"win_rate": "99.99", "avg_win": "0.5", "avg_loss": "0.5", "per_day": "1"}
    days = calc.synthetic_daily_returns(0.9999, 0.005, 0.005, 1.0)
    assert float(np.std(days)) == 0.0  # the seed's 1,000 draws are all winners
    response = site.get(calc.challenge_url("es"), params=params)
    assert response.status_code == 200
    assert calc.COPY["es"]["identical_days"] in _visible(response.text)
    assert "data-challenge-result" not in response.text


def test_lower_bound_reuses_the_win_rate_calculator(site: TestClient) -> None:
    value = _parse(FIGURES)
    reading = calc.compute(value)
    expected = winrate.read(PublicClaim(trades=60, win_rate=0.45)).interval
    assert reading.interval == expected and expected is not None
    assert reading.lower is not None and reading.lower.win_rate == expected[0]
    lower_pass = float(reading.lower.outcome["pass"]["value"])
    assert lower_pass < float(reading.declared.outcome["pass"]["value"])
    for locale in LOCALES:
        page = site.get(calc.challenge_url(locale), params=FIGURES).text
        text = _visible(page)
        assert f"{_num(expected[0] * 100, locale, 1)} %" in text
        assert f"{_num(lower_pass * 100, locale, 1)} %" in text
        found = re.search(r"<a href='([^']*)' data-challenge-winrate>", page)
        assert found is not None
        link = html.unescape(found.group(1))
        assert urlsplit(link).path == winrate.WINRATE_PATH[locale]
        assert parse_qs(urlsplit(link).query) == {"trades": ["60"], "win_rate": ["45"]}
        assert site.get(link).status_code == 200
    # Without the trades, the lower bound is not measured and the page says why.
    page = site.get(calc.challenge_url("es"), params=PCT).text
    assert "data-challenge-lower-missing" in page
    assert calc.COPY["es"]["lower_missing"] in _visible(page)
    assert winrate.WINRATE_PATH["es"] in _links(page)


def test_sizes_follow_the_report_logic() -> None:
    value = _parse(FIGURES)
    reading = calc.compute(value)
    assert [size for size, _ in reading.sizes] == list(calc.SIZES) == [0.5, 1.0, 2.0]
    daily = reading.declared.daily
    for size, outcome in reading.sizes:
        if size == 1.0:
            assert outcome is reading.declared.outcome
            continue
        direct = firmfit.program_outcomes(
            daily * size, value.program, samples=calc.SAMPLES, seed=calc.SEED
        )
        assert outcome["pass"]["value"] == pytest.approx(direct["pass"]["value"])
    chances = [float(outcome["pass"]["value"]) for _, outcome in reading.sizes]
    assert chances[0] > chances[1] > chances[2]


def test_fee_gives_attempts_and_cost_per_account(site: TestClient) -> None:
    value = _parse(FIGURES)
    reading = calc.compute(value)
    chance = float(reading.declared.outcome["pass"]["value"])
    assert reading.attempts == pytest.approx(1 / chance)
    assert reading.cost == pytest.approx(155 / chance)
    page = site.get(calc.challenge_url("es"), params=FIGURES).text
    assert f"USD {_num(155 / chance, 'es', 0)}" in _row(page, "cost")
    assert _num(1 / chance, "es", 1) in _row(page, "attempts")
    assert "USD 155" in _row(page, "fee")
    words = calc.COPY["es"]
    assert words["fee_note"] in _visible(page)
    # Without a fee the cost is not measured, and nothing invents one.
    without = site.get(calc.challenge_url("es"), params=PCT).text
    assert words["no_fee"] in _row(without, "cost")
    assert "badge NOT_MEASURED" in _result(without)


# -- links, sitemap, counters --------------------------------------------------


def test_sitemap_lists_every_page_with_todays_date(site: TestClient) -> None:
    for firm in ("", *calc.FIRMS):
        assert calc.page_paths(firm) in seo.PUBLIC_PAGES
        for path in calc.page_paths(firm).values():
            assert seo.page_lastmod(path) == seo.CHALLENGE_PUBLISHED == "2026-10-10"
    response = site.get("/sitemap.xml")
    assert response.status_code == 200
    root = ElementTree.fromstring(response.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    dates = {
        url.findtext("s:loc", namespaces=ns): url.findtext("s:lastmod", namespaces=ns)
        for url in root.findall("s:url", ns)
    }
    for path in calc.PAGES:
        assert dates[BASE + path] == "2026-10-10", path


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_case_page_and_article_link_the_calculator(site: TestClient, locale: str) -> None:
    path = calc.challenge_url(locale)
    assert "challenge" in TOOL_KEYS
    hub = site.get(TOOLS_PATH[locale]).text
    assert path in _links(_main(hub)) and "id='tool-challenge'" in hub
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", hub, re.S)
    tools = next(json.loads(b) for b in blocks if json.loads(b).get("@type") == "ItemList")
    assert BASE + path in [element["item"]["url"] for element in tools["itemListElement"]]
    case = site.get(audience_url("retos-prop-firm", locale)).text
    assert path in _links(_main(case)) and "data-audience-tool" in case
    article = site.get(article_url("cuantos-intentos-reto-prop-firm", locale)).text
    assert path in _links(_main(article)) and "data-challenge-calculator" in article
    for page in (hub, case, article):
        assert find_claims(html.unescape(page)) == []
    # Each page links the others, the win-rate calculator, the article and the case page.
    for firm in ("", *calc.FIRMS):
        links = _links(_main(site.get(calc.challenge_url(locale, firm)).text))
        for other in ("", *calc.FIRMS):
            if other != firm:
                assert calc.challenge_url(locale, other) in links, (firm, other)
        assert winrate.WINRATE_PATH[locale] in links
        assert article_url("cuantos-intentos-reto-prop-firm", locale) in links
        assert audience_url("retos-prop-firm", locale) in links


def test_no_database_network_or_files(
    site: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("The challenge calculator must not fetch, use the database or write files")

    store = site.app.state.store
    monkeypatch.setattr(store.engine, "begin", forbidden)
    monkeypatch.setattr(store.engine, "connect", forbidden)
    # A visit goes to the in-memory counter only (``test_visits_count_in_the_memory_counter``):
    # writing it is the background flush's job, never the request's.
    flushed: list[object] = []
    visits = site.app.state.visits
    monkeypatch.setattr(visits, "flush", lambda *a, **k: flushed.append(a))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("quant_trade.audit.market._download", forbidden)
    calc.compute.cache_clear()
    before = sorted(tmp_path.rglob("*"))
    for locale in LOCALES:
        for firm, params in (("", FIGURES), ("topstep", {**PCT, "fee": "49"})):
            response = site.get(calc.challenge_url(locale, firm), params={**params, "ref": "reto"})
            assert response.status_code == 200
    assert sorted(tmp_path.rglob("*")) == before
    assert flushed == []


def test_visits_count_in_the_memory_counter(tmp_path: Path) -> None:
    client = _fresh(tmp_path, **BROWSER)

    def browser() -> TestClient:
        return TestClient(client.app, headers=BROWSER)

    tagged = browser().get(calc.challenge_url("es") + "?ref=reto")
    assert tagged.cookies.get(funnel.REF_COOKIE) == "reto"
    assert browser().get(calc.challenge_url("en", "ftmo")).status_code == 200
    assert browser().get(calc.challenge_url("pt", "topstep"), params=PCT).status_code == 200
    client.app.state.visits.flush()
    day = funnel.day_of(datetime.now(UTC))
    rows = client.app.state.store.funnel_events(day)["visits"]
    counts = {(locale, ref): count for _, locale, ref, count in rows}
    assert counts == {("es", "reto"): 1, ("en", ""): 1, ("pt", ""): 1}


def test_computations_per_address_are_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calc, "REQUESTS_PER_HOUR", 2)
    client = _fresh(tmp_path)
    path = calc.challenge_url("es")
    assert client.get(path, params=PCT).status_code == 200
    assert client.get(path, params=FIGURES).status_code == 200
    calls: list[object] = []
    monkeypatch.setattr(calc, "compute", lambda value: calls.append(value))
    limited = client.get(path, params=PCT)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"
    assert calc.COPY["es"]["limited"] in _visible(limited.text)
    assert "data-challenge-result" not in limited.text and calls == []
    # The empty form and an error never compute, so they are never refused.
    assert client.get(path).status_code == 200
    assert client.get(path, params={**PCT, "win_rate": "150"}).status_code == 400
