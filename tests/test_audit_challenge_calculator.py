"""The free prop-firm challenge calculator: declared figures through the report's simulator."""

from __future__ import annotations

import html
import json
import math
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
from quant_trade.audit import firmfit, funnel, seo, theme, winrate  # noqa: E402
from quant_trade.audit.analytics import simulate_challenge  # noqa: E402
from quant_trade.audit.articles import _num, article_url  # noqa: E402
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.calculator import CALCULATOR_PATH  # noqa: E402
from quant_trade.audit.challenge_pages import _phase_name  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.prop_presets import (  # noqa: E402
    PRESETS,
    THE5ERS_BOOTCAMP_URL,
    THE5ERS_HIGH_STAKES_URL,
    THE5ERS_HYPER_GROWTH_URL,
)
from quant_trade.audit.public_card import PublicClaim  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import COPY as TOOLS_COPY  # noqa: E402
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
    r"verific\w*|verified|certificad\w*|certified|garantiza\w*|guarantee\w*|garantid\w*|"
    r"rentables?|profitable|lucrativ\w*|approved)\b",
    re.IGNORECASE,
)
ALL_PATHS = [pytest.param(path, id=path) for path in calc.PAGES]
#: How a description says the tool is not the firm's.
AFFILIATION = {"es": "no afiliada", "en": "not affiliated", "pt": "não afiliada"}


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
            # A search result shows the description without the page: it says Rigor is
            # independent and not the firm's, as the lead and the rules table do.
            assert AFFILIATION[locale] in description, description
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
    # Named after a firm, the tool still reads as Rigor's in a rich result.
    assert app["publisher"] == {"@type": "Organization", "name": "Rigor"}
    assert AFFILIATION[locale] in app["description"]
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
    # The mean is the declared one, not the seed's draw of it (that was off by a
    # third of the edge, always in the trader's favour).
    assert np.mean(daily) == pytest.approx(2 * (0.55 * 0.01 - 0.45 * 0.007), abs=1e-9)
    # The binomial mix of a two-trade day, to one day in 10,000.
    wins = np.round((daily + 0.014) / 0.017).astype(int)
    for count, share in ((2, 0.55**2), (1, 2 * 0.55 * 0.45), (0, 0.45**2)):
        assert abs(np.sum(wins == count) - share * calc.SYNTHETIC_DAYS) <= 1, count
    half = calc.synthetic_daily_returns(0.55, 0.01, 0.007, 0.5)
    assert np.mean(half == 0.0) == 0.5
    # A lower win rate only turns winners into losers, day by day.
    lower = calc.synthetic_daily_returns(0.40, 0.01, 0.007, 2.0)
    assert (lower <= daily + 1e-12).all()


def _mix(win_rate: float, per_day: float) -> tuple[np.ndarray, np.ndarray]:
    """Each synthetic day's trades and winners, read back through the returns."""
    counts = calc.synthetic_daily_returns(win_rate, 1.0, -1.0, per_day)
    winners = calc.synthetic_daily_returns(win_rate, 1.0, 0.0, per_day)
    winners = np.where(winners == calc.TRADED_FLAT_DAY, 0.0, winners)
    return np.round(counts).astype(int), np.round(winners).astype(int)


@pytest.mark.parametrize(
    ("win_rate", "per_day"),
    [(0.40, 0.1), (0.55, 0.5), (0.555, 1.0), (0.50, 1.0), (0.70, 1.2345), (0.55, 2.0)]
    + [(0.45, 2.5), (0.40, 5.0), (0.60, 50.0)],
)
def test_synthetic_days_hold_the_declared_trades_and_win_rate(
    win_rate: float, per_day: float
) -> None:
    days = calc.SYNTHETIC_DAYS
    counts, winners = _mix(win_rate, per_day)
    whole = math.floor(per_day)
    total = round(per_day * days)
    assert int(counts.sum()) == total
    assert set(counts.tolist()) <= {whole, whole + 1}
    # The declared win rate to within one trade per day size: the seed's own draw
    # gave 57.9 % for a declared 55 % at one trade a day, and 46.3 % for 40 %.
    assert abs(int(winners.sum()) - win_rate * total) <= whole + 1
    win, loss = 0.008, 0.005
    daily = calc.synthetic_daily_returns(win_rate, win, loss, per_day)
    exact = (int(winners.sum()) * win - (total - int(winners.sum())) * loss) / days
    assert np.mean(daily) == pytest.approx(exact, rel=1e-9, abs=1e-15)
    declared = per_day * (win_rate * win - (1 - win_rate) * loss)
    assert abs(float(np.mean(daily)) - declared) <= (whole + 2) * (win + loss) / days


def test_the_seed_only_shuffles_the_days(monkeypatch: pytest.MonkeyPatch) -> None:
    # Edge zero: 50 % at 1 % against 1 %. The seed's own draw had made it +0,05 % a
    # day, and the page said 58 % for a target that a fair walk reaches about 31 %.
    value = _parse({"win_rate": "50", "avg_win": "1", "avg_loss": "1", "per_day": "1"})
    page = calc.run_program(value, value.win_rate)
    assert np.mean(page.daily) == pytest.approx(0.0, abs=1e-15)
    chance = float(page.outcome["pass"]["value"])
    assert chance == pytest.approx(0.31, abs=0.05)
    for seed in (1, 2, 3):
        monkeypatch.setattr(calc, "SEED", seed)
        other = calc.run_program(value, value.win_rate)
        # The same days in another order, and about the same figure.
        assert np.array_equal(np.sort(other.daily), np.sort(page.daily))
        assert float(other.outcome["pass"]["value"]) == pytest.approx(chance, abs=0.05), seed


def test_days_that_net_zero_still_count_as_trading_days() -> None:
    # 1:1 and two trades a day: a win and a loss net exactly zero on about half the days.
    value = _parse(
        {
            "win_rate": "60",
            "avg_win": "2",
            "avg_loss": "2",
            "per_day": "2",
            "program": "fundednext-stellar-2step-phase1",
        }
    )
    daily = calc.synthetic_daily_returns(value.win_rate, value.win, value.loss, value.per_day)
    flat = daily == calc.TRADED_FLAT_DAY
    assert 0.4 < float(np.mean(flat)) < 0.55
    # Every day had trades, so the simulator (which counts a day with a return that
    # is not zero) counts every one, at every size of the sizing table.
    assert np.count_nonzero(daily) == calc.SYNTHETIC_DAYS
    assert np.count_nonzero(daily * min(calc.SIZES)) == calc.SYNTHETIC_DAYS
    assert np.all(1.0 + daily[flat] == 1.0)  # and the balance does not move
    rules = PRESETS[value.program]
    counted = simulate_challenge(daily, rules, samples=calc.SAMPLES, seed=calc.SEED)
    uncounted = simulate_challenge(
        np.where(flat, 0.0, daily), rules, samples=calc.SAMPLES, seed=calc.SEED
    )
    days = counted["days_to_target"]
    assert days["p25"]["value"] >= rules.min_trading_days
    assert days["p50"]["value"] < uncounted["days_to_target"]["p50"]["value"]
    assert calc.compute(value).declared.phases[0][1]["days_to_target"] == days


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
    # At 99.999 % not one of the 10,000 trades loses: every synthetic day is the
    # same and cannot be resampled.
    params = {"win_rate": "99.999", "avg_win": "0.5", "avg_loss": "0.5", "per_day": "1"}
    days = calc.synthetic_daily_returns(0.99999, 0.005, 0.005, 1.0)
    assert float(np.std(days)) == 0.0
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


# -- what the page says about the rules it shows ----------------------------------


def _figures(text: str, locale: str) -> list[float]:
    """Every number in ``text``, read with the language's marks (2.000 is two thousand in es)."""
    thousands, decimal = (",", ".") if locale == "en" else (".", ",")
    text = re.sub(rf"(?<=\d){re.escape(thousands)}(?=\d{{3}}\b)", "", text)
    return [
        round(float(found.replace(decimal, ".")), 6)
        for found in re.findall(rf"\d+(?:{re.escape(decimal)}\d+)?", text)
    ]


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("firm", list(calc.FIRMS))
def test_every_figure_in_an_answer_is_in_the_presets(firm: str, locale: str) -> None:
    """A figure in an answer is a preset's field, a figure its notes state, the
    simulator's horizon or a Topstep size: if a preset changes, the answer follows
    or this fails. Every answer that cites a rule carries the date it was read."""
    keys = [key for program in calc.firm_programs(firm) for key in firmfit.program_keys(program)]
    allowed = {float(calc.horizon(key)) for key in keys}
    for key in keys:
        rules = PRESETS[key]
        for name in ("profit_target", "max_daily_loss", "max_total_loss", "best_day_limit"):
            share = getattr(rules, name)
            if share is not None:
                allowed.add(round(share * 100, 6))
        allowed |= {float(rules.min_trading_days), float(calc.phase_count(key))}
        account = calc.account_size(key)
        if account is not None:
            allowed |= {account, round(account * rules.max_total_loss, 6)}
        for note in rules.notes:
            allowed.update(_figures(note, "en"))
    as_of = PRESETS[keys[0]].as_of
    names = sorted(
        {PRESETS[key].program for key in keys} | {PRESETS[key].firm for key in keys},
        key=len,
        reverse=True,
    )
    for question, answer in calc.firm_faq(firm, locale):
        text = answer.replace(as_of, " ")
        for name in names:
            text = text.replace(name, " ")
        text = re.sub(r"\b\d-Step\b|\b(?:fase|phase) \d\b", " ", text)
        figures = _figures(text, locale)
        assert set(figures) <= allowed, (question, set(figures) - allowed)
        if figures:
            assert as_of in answer, question


@pytest.mark.parametrize("locale", LOCALES)
def test_answers_agree_with_the_rules_on_the_same_page(site: TestClient, locale: str) -> None:
    # FTMO's daily loss: the 2-Step's and the 1-Step's, each from its preset.
    daily = calc.firm_faq("ftmo", locale)[2][1]
    for key in ("ftmo-2step-phase1", "ftmo-1step"):
        assert calc.daily_clause(key, locale) in daily, key
    # Hyper Growth has a daily limit that pauses the day: the answer says it is not
    # simulated, and never that the program has none.
    hyper = calc.firm_faq("the5ers", locale)[1][1]
    assert calc.rules_sentence("the5ers-hyper-growth", locale) in hyper
    assert "3 %" in hyper
    none = {"es": "sin límite", "en": "no daily", "pt": "sem limite"}[locale]
    assert none not in calc.rules_sentence("the5ers-hyper-growth", locale)
    # The result row of a program without a simulated daily limit is about the
    # calculator, never about the firm's rules.
    words = calc.COPY[locale]
    for claim in ("no tiene", "have no", "não têm", "has no"):
        assert claim not in words["no_daily"]
    page = site.get(
        calc.challenge_url(locale, "topstep"), params={**PCT, "program": "topstep-50k-combine"}
    ).text
    assert words["no_daily"] in _row(page, "daily")
    # The FAQPage carries the same answers as the page.
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    faq = next(json.loads(b) for b in blocks if json.loads(b).get("@type") == "FAQPage")
    answers = [entry["acceptedAnswer"]["text"] for entry in faq["mainEntity"]]
    assert answers == [answer for _, answer in calc.firm_faq("topstep", locale)]


def test_the_horizon_is_the_simulators() -> None:
    for key in ("ftmo-2step-phase1", "fundednext-stellar-2step-phase1", "topstep-50k-combine"):
        daily = calc.synthetic_daily_returns(0.55, 0.01, 0.008, 1.0)
        method = simulate_challenge(daily, PRESETS[key], samples=10, seed=1)["method"]
        assert calc.horizon(key) == method["horizon_business_days"]
    for locale in LOCALES:
        deadline = calc.firm_faq("fundednext", locale)[3][1]
        assert str(calc.horizon("fundednext-stellar-2step-phase1")) in deadline


@pytest.mark.parametrize("locale", LOCALES)
def test_each_source_and_note_names_its_program(site: TestClient, locale: str) -> None:
    page = site.get(calc.challenge_url(locale, "the5ers")).text
    sources = re.findall(r"<p class='help' data-challenge-source>(.*?)</p>", page)
    assert len(sources) == len({_visible(line) for line in sources}) == 3
    for url, key in (
        (THE5ERS_HIGH_STAKES_URL, "the5ers-high-stakes-step1"),
        (THE5ERS_HYPER_GROWTH_URL, "the5ers-hyper-growth"),
        (THE5ERS_BOOTCAMP_URL, "the5ers-bootcamp-step"),
    ):
        line = next(line for line in sources if f"href='{url}'" in line)
        assert PRESETS[key].program in _visible(line) and PRESETS[key].as_of in line
    # The notes come under one heading per program, each with its own.
    groups = re.findall(
        r"<h3>([^<]*)</h3><ul class='checks nots challenge-notes' data-challenge-notes>(.*?)</ul>",
        page,
        re.S,
    )
    assert [title for title, _ in groups] == [
        html.escape(calc.COPY[locale]["notes_title"].format(program=f"The5ers · {name}"))
        for name in ("High Stakes", "Hyper Growth", "Bootcamp")
    ]
    from quant_trade.audit.i18n import localize

    hyper = localize(PRESETS["the5ers-hyper-growth"].notes[0], locale)
    assert html.escape(hyper) in groups[1][1] and html.escape(hyper) not in groups[0][1]
    # FTMO's 5 % daily note sits with the 2-Step, not next to the 1-Step's 3 %.
    ftmo = site.get(calc.challenge_url(locale, "ftmo")).text
    titles = re.findall(r"<h3>([^<]*)</h3><ul class='checks nots challenge-notes'", ftmo)
    assert len(titles) == 2 and "2-Step" in titles[0] and "1-Step" in titles[1]
    daily_note = html.escape(localize(PRESETS["ftmo-2step-phase1"].notes[0], locale))
    one_step = ftmo.split(titles[1], 1)[1].split("</ul>", 1)[0]
    assert daily_note in ftmo and daily_note not in one_step


@pytest.mark.parametrize("path", ALL_PATHS)
def test_note_addresses_are_short_links(site: TestClient, path: str) -> None:
    page = site.get(path).text
    notes = re.findall(r"<ul class='checks nots challenge-notes'.*?</ul>", page, re.S)
    assert notes
    for block in notes:
        visible = _visible(block)
        assert "https://" not in visible and ".com/" not in visible, visible
    if calc.PAGES[path][1] == "topstep":
        consistency = "https://help.topstep.com/en/articles/8284208-what-is-the-consistency-target"
        assert consistency in _links(page)
    # A long word in a note wraps instead of pushing the list past a phone's edge.
    assert ".checks li span{min-width:0;overflow-wrap:anywhere}" in theme.SECTIONS


def test_numbered_phases_are_not_the_firms_english_names(site: TestClient) -> None:
    assert _phase_name(PRESETS["ftmo-2step-phase2"], "es") == "fase 2"
    assert _phase_name(PRESETS["ftmo-2step-phase1"], "pt") == "fase 1"
    assert _phase_name(PRESETS["ftmo-2step-phase1"], "en") == "phase 1"
    assert _phase_name(PRESETS["the5ers-bootcamp-step"], "es") == "cada una de las fases 1-3"
    for locale in LOCALES:
        for firm in ("", "ftmo"):
            page = site.get(calc.challenge_url(locale, firm), params=FIGURES).text
            assert "Verification" not in page and "(FTMO Challenge)" not in page


# -- the declared figures, as declared ------------------------------------------


def test_the_declared_fee_keeps_its_cents(site: TestClient) -> None:
    for fee, shown in (
        ("29,99", "USD 29,99"),
        ("0.01", "USD 0,01"),
        ("1.5", "USD 1,50"),
        ("1.080", "USD 1.080"),
        ("155", "USD 155"),
    ):
        page = site.get(calc.challenge_url("es"), params={**PCT, "fee": fee}).text
        row = _row(page, "fee")
        assert shown in row and f"{shown}," not in row, (fee, row)
    value = _parse({**PCT, "fee": "29.99"})
    reading = calc.compute(value)
    assert reading.cost is not None
    page = site.get(calc.challenge_url("en"), params={**PCT, "fee": "29.99"}).text
    assert "USD 29.99" in _row(page, "fee")
    assert f"USD {_num(reading.cost, 'en', 2)}" in _row(page, "cost")


def test_tiny_figures_round_trip_through_the_link(site: TestClient) -> None:
    typed = {
        "win_rate": "55",
        "avg_win": "0,00005",
        "avg_loss": "0,00004",
        "per_day": "2,5",
        "program": "ftmo-2step-phase1",
        "fee": "99",
    }
    value = _parse(typed)
    shared = calc.share_values(value)
    assert shared["avg_win"] == "0.00005" and shared["avg_loss"] == "0.00004"
    assert _parse(shared) == value
    for number in (5e-05, 1e-05, 4e-07, 0.1, 1 / 3, 123.456, 1e-20):
        text = calc._text(number)
        assert "e" not in text.lower() and float(text) == number, text
    first = site.get(calc.challenge_url("es"), params=typed)
    assert first.status_code == 200
    assert "value='0.00005'" in first.text and "value='5e-05'" not in first.text
    link = _textarea(first.text, "challenge-share-link")
    again = site.get(link.removeprefix(BASE))
    assert again.status_code == 200, _visible(again.text)[:200]
    assert _result(again.text) == _result(first.text)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_lower_bound_carries_its_label(site: TestClient, locale: str) -> None:
    page = site.get(calc.challenge_url(locale), params=FIGURES).text
    interval = winrate.read(PublicClaim(trades=60, win_rate=0.45)).interval
    assert interval is not None
    low = html.escape(f"{_num(interval[0] * 100, locale, 1)} %")
    sentence = re.search(r"<p data-challenge-lower>(.*?)</p>", page, re.S)
    assert sentence is not None
    assert f"<b>{low}</b> <span class='badge DECLARED'>" in sentence.group(1)
    head = re.search(r"<table class='challenge-lower'><thead>(.*?)</thead>", page, re.S)
    assert head is not None and head.group(1).count("badge DECLARED") == 2
    assert calc.COPY[locale]["lower_computed"] in _visible(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_what_the_page_keeps_is_said_exactly(site: TestClient, locale: str) -> None:
    # The figures travel in the GET query, so the access log may hold them: the
    # page says so instead of "we do not store what you type". The luck
    # calculator said the same and says this now.
    log = {"es": "registro de acceso", "en": "access log", "pt": "registro de acesso"}[locale]
    for path in (calc.challenge_url(locale), CALCULATOR_PATH[locale]):
        visible = _visible(site.get(path).text)
        assert log in visible, path
        for old in ("No guardamos lo que escribes", "We do not store what you type"):
            assert old not in visible
        assert "Não guardamos o que você digita" not in visible


def test_tools_page_description_keeps_its_warnings() -> None:
    for locale, words in (
        ("es", ("Cifras declaradas", "ninguna es una auditoría")),
        ("en", ("Declared figures", "none is an audit")),
        ("pt", ("Números declarados", "nenhuma é uma auditoria")),
    ):
        summary = TOOLS_COPY[locale]["summary"]
        assert all(word in summary for word in words), summary
        assert 50 <= len(summary) <= 160
