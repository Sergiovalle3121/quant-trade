"""The free risk-of-ruin calculator: declared figures, fixed-size paths, Wilson's lower end."""

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

from quant_trade.audit import challenge_calc, funnel, seo, winrate  # noqa: E402
from quant_trade.audit import ruin_calc as calc  # noqa: E402
from quant_trade.audit.articles import ARTICLES_BY_KEY, article_url, related_links  # noqa: E402
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import audit_path  # noqa: E402
from quant_trade.audit.public_card import PublicClaim, _num, _wilson  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.streaks import RARE, longest_run_tail  # noqa: E402
from quant_trade.audit.tools_hub import COPY as TOOLS_COPY  # noqa: E402
from quant_trade.audit.tools_hub import TOOL_KEYS, TOOLS_PATH, tools_url  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}
#: Declared figures in R, with the trades behind the win rate; threshold and horizon by default.
FIGURES = {
    "win_rate": "45",
    "unit": "r",
    "avg_win": "1.5",
    "avg_loss": "1",
    "risk": "1",
    "trades": "60",
}
#: The same in % of the balance, with a challenge's threshold and a short horizon.
PCT = {"win_rate": "52", "avg_win": "0.9", "avg_loss": "0.6", "ruin": "30", "horizon": "300"}
#: The classic case: a win equal to a loss, 1 % each, a threshold of ten losses, a long horizon.
EQUAL = {"win_rate": "55", "avg_win": "1", "avg_loss": "1", "ruin": "10", "horizon": "3000"}
#: Words the brief keeps off this page, in the three languages.
FORBIDDEN = re.compile(
    r"\b(aprobar\w*|aprobad\w*|pasar|pasas?|pass|passed|passes|passing|aprovar\w*|aprovad\w*|"
    r"verific\w*|verified|certificad\w*|certified|garantiza\w*|guarantee\w*|garantid\w*|"
    r"rentables?|profitable|lucrativ\w*|approved|nunca|never|jamais|segur[ao]s?|certa)\b",
    re.IGNORECASE,
)
ALL_PATHS = [pytest.param(path, id=path) for path in calc.RUIN_PATH.values()]


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("ruin")
    settings = AuditSettings(database_url=f"sqlite:///{directory}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _fresh(tmp_path: Path, **headers: str) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)), headers=headers)


def _locale_of(path: str) -> str:
    return next(locale for locale, own in calc.RUIN_PATH.items() if own == path)


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _visible(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _links(page: str) -> list[str]:
    return [html.unescape(value) for value in re.findall(r"\bhref=['\"]([^'\"]*)", page)]


def _result(page: str) -> str:
    found = re.search(r"<table class='calc-result' data-ruin-result>.*?</table>", page, re.S)
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


def _json_ld(page: str) -> list[dict[str, object]]:
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    return [json.loads(block) for block in blocks]


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def _parse(values: dict[str, str]) -> calc.RuinInput:
    parsed = calc.parse(values)
    assert parsed.errors == () and parsed.value is not None, parsed.errors
    return parsed.value


def _percent(value: float, locale: str) -> str:
    return f"{_num(value * 100, locale, 1)} %"


# -- the page ------------------------------------------------------------------


@pytest.mark.parametrize("path", ALL_PATHS)
def test_every_page_answers_in_its_language_and_is_clean(site: TestClient, path: str) -> None:
    locale = _locale_of(path)
    for params in ({}, FIGURES, PCT):
        response = site.get(path, params=params)
        assert response.status_code == 200, (path, params)
        page = response.text
        assert f"<html lang='{locale}'>" in page
        assert page.count("<h1") == 1
        assert "<meta name='robots' content='index, follow'>" in page
        assert f"<link rel='canonical' href='{BASE}{path}'>" in page
        for lang, other in calc.RUIN_PATH.items():
            assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{other}'>" in page
        default = calc.RUIN_PATH["es"]
        assert f"<link rel='alternate' hreflang='x-default' href='{BASE}{default}'>" in page
        assert find_claims(html.unescape(page)) == []
        visible = _visible(_main(page))
        assert find_claims(visible) == []
        assert FORBIDDEN.findall(visible) == [], (path, FORBIDDEN.findall(visible))
        # The calculator is a form that works with GET and without script.
        assert f"<form method='get' action='{path}' class='calc-form'>" in page
        # Everything is declared or computed from the declared: nothing is measured.
        assert "badge MEASURED" not in page
        if params:
            assert "data-ruin-result" in page
            assert "badge DECLARED" in _result(page)
        else:
            # The empty form carries the defaults: half the balance, 500 trades.
            assert "id='ru-ruin' name='ruin'" in page and "value='50'" in page
            assert "id='ru-horizon' name='horizon'" in page and "value='500'" in page


@pytest.mark.parametrize("locale", LOCALES)
def test_copy_passes_the_guard_and_the_brief_words(locale: str) -> None:
    texts = _strings(calc.COPY[locale]) + [text for pair in calc.faq(locale) for text in pair]
    texts += _strings(TOOLS_COPY[locale]["ruin"]) + [funnel.REF_TAGS[calc.SHARE_REF]]
    for text in texts:
        assert find_claims(text) == [], text
        assert FORBIDDEN.findall(text) == [], (text, FORBIDDEN.findall(text))
    if locale == "pt":
        for text in texts:
            for word in ("informe", "archivo", "Sube "):
                assert word not in text, (word, text)


def test_metadata_is_own_and_within_bounds() -> None:
    from quant_trade.audit.challenge_pages import challenge_page
    from quant_trade.audit.pages import winrate_page
    from quant_trade.audit.ruin_pages import ruin_page

    for locale in LOCALES:
        page = ruin_page(locale=locale, base_url=BASE)
        title = html.unescape(re.search(r"<title>(.*?)</title>", page).group(1))  # type: ignore[union-attr]
        description = html.unescape(
            re.search(r"<meta name='description' content='([^']*)'>", page).group(1)  # type: ignore[union-attr]
        )
        assert 15 <= len(title) <= 65 and title.endswith(" · Rigor"), title
        assert 50 <= len(description) <= 160, (len(description), description)
        assert find_claims(title) == [] and find_claims(description) == []
        # Its own words, not the other calculators'.
        for other in (
            winrate_page(locale=locale, base_url=BASE),
            challenge_page(locale=locale, base_url=BASE),
        ):
            assert f"<title>{html.escape(title)}</title>" not in other
            assert html.escape(description, quote=True) not in other


@pytest.mark.parametrize("path", ALL_PATHS)
def test_structured_data_is_a_free_web_application_with_the_pages_questions(
    site: TestClient, path: str
) -> None:
    locale = _locale_of(path)
    page = site.get(path).text
    data = _json_ld(page)
    app = next(item for item in data if item.get("@type") == "WebApplication")
    assert app["url"] == BASE + path
    assert app["inLanguage"] == locale
    assert app["isAccessibleForFree"] is True
    assert app["offers"] == {"@type": "Offer", "price": "0", "priceCurrency": "USD"}
    assert app["publisher"] == {"@type": "Organization", "name": "Rigor"}
    assert app["name"] == calc.COPY[locale]["nav"]
    faq = next(item for item in data if item.get("@type") == "FAQPage")
    questions = calc.faq(locale)
    assert len(questions) == 3
    entries = faq["mainEntity"]
    assert isinstance(entries, list)
    assert [entry["name"] for entry in entries] == [q for q, _ in questions]
    for question, answer in questions:
        assert f"<h3>{html.escape(question)}</h3><p>{html.escape(answer)}</p>" in page
    # The worked figure in the answers is Wilson's lower end, computed, not typed.
    low = _percent(_wilson(*calc.FAQ_EXAMPLE)[0], locale)
    assert low in questions[1][1] and "60" in questions[1][1]


# -- the figures ---------------------------------------------------------------


def test_expectancy_in_r_and_in_percent_of_the_balance(site: TestClient) -> None:
    value = _parse(FIGURES)
    assert value.win == pytest.approx(0.015) and value.loss == pytest.approx(0.01)
    run = calc.compute(value).declared
    assert run.expectancy_r == pytest.approx(0.45 * 1.5 - 0.55 * 1.0)
    assert run.expectancy_share == pytest.approx(0.45 * 0.015 - 0.55 * 0.01)
    pct = _parse(PCT)
    run_pct = calc.compute(pct).declared
    assert run_pct.expectancy_share == pytest.approx(0.52 * 0.009 - 0.48 * 0.006)
    # In % of the balance, one R is the average loss.
    assert run_pct.expectancy_r == pytest.approx(run_pct.expectancy_share / 0.006)
    for locale in LOCALES:
        page = site.get(calc.ruin_url(locale), params=FIGURES).text
        assert f"+{_num(run.expectancy_r, locale, 2)} R" in _row(page, "expectancy_r")
        assert f"+{_num(run.expectancy_share * 100, locale, 2)} %" in _row(page, "expectancy_pct")
        assert calc.COPY[locale]["r_is_loss"] not in _visible(page)
        pct_page = site.get(calc.ruin_url(locale), params=PCT).text
        assert calc.COPY[locale]["r_is_loss"] in _visible(pct_page)
    # A negative expectancy keeps its sign.
    losing = calc.compute(_parse({**PCT, "win_rate": "30"})).declared
    assert losing.expectancy_r < 0
    page = site.get(calc.ruin_url("en"), params={**PCT, "win_rate": "30"}).text
    assert f"{_num(losing.expectancy_r, 'en', 2)} R" in _row(page, "expectancy_r")
    assert "+-" not in _row(page, "expectancy_r")


def test_paths_are_fixed_size_and_a_lower_rate_only_turns_winners_into_losers() -> None:
    sure = calc.simulate(1.0, 0.01, 0.01, 300, samples=50, seed=3)
    assert np.all(sure.lowest == 1.0) and np.all(sure.drawdown == 0.0)
    lost = calc.simulate(0.0, 0.01, 0.01, 300, samples=50, seed=3)
    assert np.allclose(lost.lowest, 1.0 - 3.0)
    assert np.all(lost.drawdown == 1.0)  # the fall is clipped at the whole balance
    assert calc.ruin_share(lost, 0.5) == 1.0 and calc.ruin_share(sure, 0.01) == 0.0
    higher = calc.simulate(0.55, 0.012, 0.01, 800, samples=300, seed=7)
    lower = calc.simulate(0.45, 0.012, 0.01, 800, samples=300, seed=7)
    # The same seed, the same uniforms: every path at the lower rate is at or below its twin.
    assert np.all(lower.lowest <= higher.lowest + calc.TOUCH)
    assert np.all(lower.drawdown >= higher.drawdown - calc.TOUCH)
    assert np.all((higher.drawdown >= 0.0) & (higher.drawdown <= 1.0))
    # Blocks are a memory detail: the same paths whatever their width.
    assert len(higher.lowest) == 300


def test_touching_the_threshold_counts_a_sum_that_lands_a_hair_off() -> None:
    # Twenty losses of 1 % land on 0.80 in floating point, not exactly on it.
    twenty = calc.simulate(0.0, 0.01, 0.01, 20, samples=4, seed=1)
    assert np.all(np.isclose(twenty.lowest, 0.8))
    assert calc.ruin_share(twenty, 0.2) == 1.0
    nineteen = calc.simulate(0.0, 0.01, 0.01, 19, samples=4, seed=1)
    assert calc.ruin_share(nineteen, 0.2) == 0.0


def test_closed_formula_matches_the_simulation_when_wins_equal_losses(site: TestClient) -> None:
    value = _parse(EQUAL)
    assert value.equal_sizes
    run = calc.compute(value).declared
    classic = (0.45 / 0.55) ** 10
    assert run.classic == pytest.approx(classic)
    assert calc.classic_ruin(0.55, 10) == pytest.approx(classic)
    # Within 3,000 trades nearly every path that touches ten losses below has done so.
    assert run.ruin == pytest.approx(classic, abs=0.02)
    # With no edge or a negative one the formula gives 1; the paths agree within the horizon.
    assert calc.classic_ruin(0.5, 10) == 1.0 and calc.classic_ruin(0.4, 3) == 1.0
    negative = calc.compute(_parse({**EQUAL, "win_rate": "45", "ruin": "20"})).declared
    assert negative.classic == 1.0 and negative.ruin >= 0.99
    # The formula applies to equal sizes only; otherwise the row says so.
    unequal = calc.compute(_parse(FIGURES)).declared
    assert unequal.classic is None
    for locale in LOCALES:
        page = site.get(calc.ruin_url(locale), params=EQUAL).text
        assert _percent(classic, locale) in _row(page, "classic")
        assert "badge DECLARED" in _row_html(page, "classic")
        assert "data-ruin-classic" in page
        other = site.get(calc.ruin_url(locale), params=FIGURES).text
        assert calc.COPY[locale]["no_classic"] in _row(other, "classic")
        assert "badge NOT_MEASURED" in _row_html(other, "classic")
        assert "data-ruin-classic" not in other


def _row_html(page: str, key: str) -> str:
    found = re.search(rf"<tr data-row='{key}'>(.*?)</tr>", _result(page), re.S)
    assert found is not None, key
    return found.group(1)


def test_shortcut_thresholds_come_from_the_same_paths(site: TestClient) -> None:
    value = _parse(PCT)
    run = calc.compute(value).declared
    assert [pct for pct, _ in run.shortcuts] == list(calc.RUIN_SHORTCUTS) == [20.0, 30.0, 50.0]
    paths = calc.simulate(value.win_rate, value.win, value.loss, value.horizon)
    for pct, share in run.shortcuts:
        assert share == calc.ruin_share(paths, pct / 100.0)
    shares = [share for _, share in run.shortcuts]
    assert shares[0] >= shares[1] >= shares[2]
    # The declared threshold is one of them here, so the table and the row agree.
    assert dict(run.shortcuts)[30.0] == run.ruin
    for locale in LOCALES:
        page = site.get(calc.ruin_url(locale), params=PCT).text
        table = re.search(r"<table class='ruin-thresholds'.*?</table>", page, re.S)
        assert table is not None
        text = _visible(table.group(0))
        for pct, share in run.shortcuts:
            assert _percent(pct / 100.0, locale) in text and _percent(share, locale) in text
        assert _percent(run.ruin, locale) in _row(page, "ruin")
        assert "300" in _row(page, "ruin")


def test_drawdown_quantiles_are_the_horizons(site: TestClient) -> None:
    value = _parse(FIGURES)
    run = calc.compute(value).declared
    paths = calc.simulate(value.win_rate, value.win, value.loss, value.horizon)
    assert run.drawdown_p50 == float(np.percentile(paths.drawdown, 50))
    assert run.drawdown_p95 == float(np.percentile(paths.drawdown, 95))
    assert 0.0 < run.drawdown_p50 <= run.drawdown_p95 <= 1.0
    page = site.get(calc.ruin_url("es"), params=FIGURES).text
    assert _percent(run.drawdown_p50, "es") in _row(page, "dd_median")
    assert _percent(run.drawdown_p95, "es") in _row(page, "dd_p95")


@pytest.mark.parametrize(("horizon", "win_rate"), [(500, 0.45), (1000, 0.55), (50, 0.9)])
def test_streak_is_the_engines_longest_run_tail(horizon: int, win_rate: float) -> None:
    tail = longest_run_tail(horizon, 1.0 - win_rate, horizon)
    median = int(np.max(np.nonzero(tail >= 0.5)[0]))
    rare = int(np.max(np.nonzero(tail >= RARE)[0]))
    assert calc.losing_streaks(horizon, win_rate) == (median, rare)
    assert 1 <= median <= rare < horizon


def test_streak_rows_show_the_engines_figures(site: TestClient) -> None:
    value = _parse(FIGURES)
    run = calc.compute(value).declared
    assert (run.streak_median, run.streak_rare) == calc.losing_streaks(500, 0.45)
    for locale in LOCALES:
        page = site.get(calc.ruin_url(locale), params=FIGURES).text
        words = calc.COPY[locale]
        assert words["trades_unit"].format(n=run.streak_median) in _row(page, "streak")
        assert words["trades_unit"].format(n=run.streak_rare) in _row(page, "streak_rare")


def test_the_query_reproduces_the_result(site: TestClient, tmp_path: Path) -> None:
    first = site.get(calc.ruin_url("es"), params=FIGURES).text
    shared = _textarea(first, "ruin-share-link")
    assert shared.startswith(f"{BASE}{calc.ruin_url('es')}?")
    query = parse_qs(urlsplit(shared).query)
    assert query["ref"] == ["ruina"] and query["ruin"] == ["50"] and query["horizon"] == ["500"]
    assert "ruina" in funnel.REF_TAGS
    assert _textarea(first, "ruin-share-text").endswith(shared)
    # The same figures in a new process (no cache): the seed gives the same table.
    calc.compute.cache_clear()
    again = _fresh(tmp_path).get(shared.removeprefix(BASE)).text
    assert _result(again) == _result(first)
    # "1.5" and "1.50" are one input, one link and one result, and one cached reading.
    padded = site.get(calc.ruin_url("es"), params={**FIGURES, "avg_win": "1.50"}).text
    assert _textarea(padded, "ruin-share-link") == shared
    assert _result(padded) == _result(first)
    value = _parse(FIGURES)
    assert calc.compute(value) is calc.compute(_parse({**FIGURES, "avg_win": "1.50"}))


def test_decimal_commas_spaces_and_nbsp_read_as_the_same_numbers(site: TestClient) -> None:
    point = _parse({"win_rate": "55.5", "avg_win": "0.8", "avg_loss": "0.6", "ruin": "12.5"})
    for typed in (
        {"win_rate": "55,5", "avg_win": "0,8", "avg_loss": "0,6", "ruin": "12,5"},
        {"win_rate": " 55,5 ", "avg_win": " 0,8", "avg_loss": "0,6 ", "ruin": "12,50"},
        {"win_rate": "55,5 %", "avg_win": "0.8", "avg_loss": "0,60", "ruin": "12.5"},
    ):
        assert _parse(typed) == point, typed
    assert _parse({**PCT, "trades": "1.000"}).trades == 1000
    assert _parse({**PCT, "horizon": "1.000"}).horizon == 1000
    assert _parse({**PCT, "horizon": "2 000"}).horizon == 2000
    response = site.get(
        calc.ruin_url("es"),
        params={"win_rate": "55,5", "avg_win": "0,8", "avg_loss": "0 ,6", "ruin": "12,5"},
    )
    assert response.status_code == 200
    plain = site.get(calc.ruin_url("es"), params=calc.share_values(point))
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
        ({**FIGURES, "win_rate": "inf"}, "number"),
        ({**FIGURES, "win_rate": "-inf"}, "number"),
        ({**FIGURES, "win_rate": "1e5"}, "number"),
        ({**FIGURES, "ruin": "1e2"}, "number"),
        ({**FIGURES, "risk": "25"}, "risk"),
        ({**FIGURES, "risk": ""}, "missing"),
        ({"win_rate": "55"}, "missing"),
        ({"ruin": "20"}, "missing"),
        ({**FIGURES, "trades": "40,5"}, "trades"),
        ({**FIGURES, "trades": "0"}, "trades"),
        ({**FIGURES, "ruin": "0"}, "ruin"),
        ({**FIGURES, "ruin": "100"}, "ruin"),
        ({**FIGURES, "ruin": "-10"}, "ruin"),
        ({**FIGURES, "horizon": "0"}, "horizon"),
        ({**FIGURES, "horizon": "9"}, "horizon"),
        ({**FIGURES, "horizon": "5001"}, "horizon"),
        ({**FIGURES, "horizon": "4,5"}, "horizon"),
        ({**FIGURES, "horizon": "abc"}, "horizon"),
        ({**FIGURES, "unit": "lots"}, "unit"),
    )
    path = calc.ruin_url(locale)
    for params, code in cases:
        response = site.get(path, params=params)
        assert response.status_code == 400, (params, response.status_code)
        text = _visible(response.text)
        assert words[f"error_{code}"] in text, (params, code)
        assert "<p class='error' role='alert'>" in response.text
        assert "data-ruin-result" not in response.text
        assert find_claims(text) == []
    # A rejected value is never written back into the form; valid ones are.
    page = site.get(path, params={**FIGURES, "ruin": "150"}).text
    assert "value='150'" not in page
    assert "id='ru-avg_win' name='avg_win'" in page and "value='1.5'" in page
    # A field sent twice is refused, as in the other calculators.
    twice = site.get(path, params=[*FIGURES.items(), ("win_rate", "50")])
    assert twice.status_code == 400
    assert words["error_invalid"] in _visible(twice.text)


def test_lower_bound_reuses_the_win_rate_calculator(site: TestClient) -> None:
    value = _parse(FIGURES)
    reading = calc.compute(value)
    expected = winrate.read(PublicClaim(trades=60, win_rate=0.45)).interval
    assert reading.interval == expected and expected is not None
    assert reading.lower is not None and reading.lower.win_rate == expected[0]
    assert reading.lower.ruin >= reading.declared.ruin
    assert reading.lower.expectancy_r < reading.declared.expectancy_r
    assert reading.lower.drawdown_p50 >= reading.declared.drawdown_p50
    assert reading.lower.streak_median >= reading.declared.streak_median
    for locale in LOCALES:
        page = site.get(calc.ruin_url(locale), params=FIGURES).text
        text = _visible(page)
        words = calc.COPY[locale]
        assert "data-ruin-lower" in page
        sentence = words["lower_text"].format(
            n=60,
            rate=_percent(0.45, locale),
            low=_percent(expected[0], locale),
            ruin=_percent(reading.declared.ruin, locale),
            ruin_low=_percent(reading.lower.ruin, locale),
        )
        # The first mention of the lower end carries the Declared label, so the sentence
        # is checked around it.
        before, after = sentence.split(_percent(expected[0], locale), 1)
        assert _visible(before) in text and _visible(after) in text, locale
        lower = re.search(r"<table class='ruin-lower'>.*?</table>", page, re.S)
        assert lower is not None
        assert _percent(reading.lower.ruin, locale) in _visible(lower.group(0))
        found = re.search(r"<a href='([^']*)' data-ruin-winrate>", page)
        assert found is not None
        link = html.unescape(found.group(1))
        assert urlsplit(link).path == winrate.WINRATE_PATH[locale]
        assert parse_qs(urlsplit(link).query) == {"trades": ["60"], "win_rate": ["45"]}
        assert site.get(link).status_code == 200
    # Without the trades, the lower bound is not measured and the page says why.
    page = site.get(calc.ruin_url("es"), params=PCT).text
    assert calc.compute(_parse(PCT)).lower is None
    assert "data-ruin-lower-missing" in page
    assert calc.COPY["es"]["lower_missing"] in _visible(page)
    assert winrate.WINRATE_PATH["es"] in _links(page)


# -- links, sitemap, counters --------------------------------------------------


def test_sitemap_lists_the_page_with_todays_date(site: TestClient) -> None:
    assert dict(calc.RUIN_PATH) in seo.PUBLIC_PAGES
    for path in calc.RUIN_PATH.values():
        assert seo.page_lastmod(path) == seo.RUIN_PUBLISHED == "2026-10-10"
    response = site.get("/sitemap.xml")
    assert response.status_code == 200
    root = ElementTree.fromstring(response.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    dates = {
        url.findtext("s:loc", namespaces=ns): url.findtext("s:lastmod", namespaces=ns)
        for url in root.findall("s:url", ns)
    }
    for path in calc.RUIN_PATH.values():
        assert dates[BASE + path] == "2026-10-10", path


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_calculators_and_streak_article_link_the_calculator(
    site: TestClient, locale: str
) -> None:
    path = calc.ruin_url(locale)
    assert TOOL_KEYS.index("ruin") == 3
    hub = site.get(TOOLS_PATH[locale]).text
    assert path in _links(_main(hub)) and "id='tool-ruin'" in hub
    tools = next(item for item in _json_ld(hub) if item.get("@type") == "ItemList")
    elements = tools["itemListElement"]
    assert isinstance(elements, list)
    assert BASE + path in [element["item"]["url"] for element in elements]
    assert elements[3]["item"]["name"] == calc.COPY[locale]["nav"]
    rate = site.get(winrate.WINRATE_PATH[locale]).text
    assert path in _links(_main(rate))
    challenge = site.get(challenge_calc.challenge_url(locale)).text
    assert path in _links(_main(challenge))
    streaks = ARTICLES_BY_KEY["rachas-perdedoras"]
    assert (calc.COPY[locale]["nav"], path) in related_links(streaks, locale)
    article = site.get(article_url(streaks.key, locale)).text
    assert path in _links(_main(article))
    for page in (hub, rate, challenge, article):
        assert find_claims(html.unescape(page)) == []
    # The page links the other calculators, the articles, the case page and the hub.
    links = _links(_main(site.get(path).text))
    for expected in (
        winrate.WINRATE_PATH[locale],
        challenge_calc.challenge_url(locale),
        article_url("rachas-perdedoras", locale),
        article_url("cuantas-operaciones-porcentaje-aciertos", locale),
        audience_url("retos-prop-firm", locale),
        tools_url(locale),
        audit_path(locale),
    ):
        assert expected in links, expected


def test_no_database_network_or_files(
    site: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("The ruin calculator must not fetch, use the database or write files")

    store = site.app.state.store
    monkeypatch.setattr(store.engine, "begin", forbidden)
    monkeypatch.setattr(store.engine, "connect", forbidden)
    flushed: list[object] = []
    visits = site.app.state.visits
    monkeypatch.setattr(visits, "flush", lambda *a, **k: flushed.append(a))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("quant_trade.audit.market._download", forbidden)
    calc.compute.cache_clear()
    before = sorted(tmp_path.rglob("*"))
    for locale in LOCALES:
        for params in (FIGURES, PCT, EQUAL):
            response = site.get(calc.ruin_url(locale), params={**params, "ref": "ruina"})
            assert response.status_code == 200
    assert sorted(tmp_path.rglob("*")) == before
    assert flushed == []


def test_visits_count_in_the_memory_counter(tmp_path: Path) -> None:
    client = _fresh(tmp_path, **BROWSER)

    def browser() -> TestClient:
        return TestClient(client.app, headers=BROWSER)

    tagged = browser().get(calc.ruin_url("es") + "?ref=ruina")
    assert tagged.cookies.get(funnel.REF_COOKIE) == "ruina"
    assert browser().get(calc.ruin_url("en")).status_code == 200
    assert browser().get(calc.ruin_url("pt"), params=PCT).status_code == 200
    client.app.state.visits.flush()
    day = funnel.day_of(datetime.now(UTC))
    rows = client.app.state.store.funnel_events(day)["visits"]
    counts = {(locale, ref): count for _, locale, ref, count in rows}
    assert counts == {("es", "ruina"): 1, ("en", ""): 1, ("pt", ""): 1}


def test_computations_per_address_are_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calc, "REQUESTS_PER_HOUR", 2)
    client = _fresh(tmp_path)
    path = calc.ruin_url("es")
    assert client.get(path, params=PCT).status_code == 200
    assert client.get(path, params=FIGURES).status_code == 200
    calls: list[object] = []
    monkeypatch.setattr(calc, "compute", lambda value: calls.append(value))
    limited = client.get(path, params=PCT)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"
    assert calc.COPY["es"]["limited"] in _visible(limited.text)
    assert "data-ruin-result" not in limited.text and calls == []
    # The empty form and an error never compute, so they are never refused.
    assert client.get(path).status_code == 200
    assert client.get(path, params={**PCT, "win_rate": "150"}).status_code == 400
