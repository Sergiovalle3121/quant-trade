"""The free tools page, its place in the menu and landing, and the guessed addresses."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import (  # noqa: E402
    calculator,
    challenge_calc,
    public_card,
    reading,
    ruin_calc,
    rules_table,
    seo,
    tools_examples,
    winrate,
)
from quant_trade.audit.articles import (  # noqa: E402
    article_url,
    articles_index_url,
    win_rate_interval,
)
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.calculator import calculator_url  # noqa: E402
from quant_trade.audit.examples import EXAMPLES_PATH  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import guides_index_url  # noqa: E402
from quant_trade.audit.i18n import localize  # noqa: E402
from quant_trade.audit.pages import _sample_url, audit_path, landing  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import COPY, TOOL_KEYS, TOOLS_PATH, tools_url  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.audit.winrate import WINRATE_PATH  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
#: The figures of tests/test_audit_public_reading.py.
FIGURES = {
    "trades": "45",
    "win_rate": "71",
    "profit_factor": "3.24",
    "sharpe": "1.8",
    "years": "3",
    "trials": "1000",
    "target_r": "1",
    "stop_r": "1",
}
#: Addresses people guess, each with the page it now forwards to (task 11).
GUESSED = (
    ("/en/calculator", "/calculator"),
    ("/reading", "/en/reading"),
    ("/en/methodology", "/methodology"),
    ("/en/articles", "/articles"),
    ("/en/guides", "/guides"),
    ("/en/sample", "/sample"),
    ("/en/check", "/check"),
    ("/faq", "/en/faq"),
    ("/examples", "/en/examples"),
    ("/tools", "/en/tools"),
    ("/pt/tools", "/pt/ferramentas"),
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _hrefs(page: str) -> set[str]:
    return {html.unescape(value) for value in re.findall(r"\bhref=['\"]([^'\"]*)", page)}


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _visible_text(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _texts(value: object) -> Iterator[str]:
    """Every string in a copy entry, however it is nested."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _texts(item)


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_hub_is_public_in_every_language(client: TestClient, locale: str) -> None:
    path = TOOLS_PATH[locale]
    assert dict(TOOLS_PATH) in seo.PUBLIC_PAGES
    response = client.get(path)
    assert response.status_code == 200
    text = response.text
    assert f"<html lang='{locale}'>" in text
    assert text.count("<h1") == 1
    assert "<meta name='robots' content='index, follow'>" in text
    assert f"<link rel='canonical' href='{BASE}{path}'>" in text
    for lang, alternate in TOOLS_PATH.items():
        assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{alternate}'>" in text
    assert f"<link rel='alternate' hreflang='x-default' href='{BASE}{TOOLS_PATH['es']}'>" in text
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", text, re.S)
    assert blocks
    data = [json.loads(block) for block in blocks]
    tools = next(item for item in data if item.get("@type") == "ItemList")
    apps = [element["item"] for element in tools["itemListElement"]]
    # One entry per tool on the page: the luck calculator, the win-rate, challenge and
    # ruin calculators (added after this page shipped), the figure reader and the check.
    assert len(apps) == len(TOOL_KEYS) == 6
    for app in apps:
        assert app["@type"] == "WebApplication"
        assert app["isAccessibleForFree"] is True
        assert app["inLanguage"] == locale
        assert app["offers"] == {"@type": "Offer", "price": "0", "priceCurrency": "USD"}
        assert app["url"].startswith(BASE + "/")
    raw = "".join(blocks)
    assert "WebApplication" in raw and '"isAccessibleForFree": true' in raw
    assert find_claims(html.unescape(text)) == []
    for item in _texts(COPY[locale]):
        assert find_claims(item) == [], item


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_hub_links_every_free_tool(client: TestClient, locale: str) -> None:
    hrefs = _hrefs(_main(client.get(TOOLS_PATH[locale]).text))
    assert calculator_url(locale) in hrefs
    assert WINRATE_PATH[locale] in hrefs
    assert reading.READING_PATH[locale] in hrefs
    assert seo.CHECK_PATH[locale] in hrefs
    assert audit_path(locale) in hrefs
    assert articles_index_url(locale) in hrefs
    assert _sample_url(locale) in hrefs


def test_tools_hub_metadata_is_unique_and_in_bounds() -> None:
    from quant_trade.audit.pages import tools_page

    titles = set()
    for locale in LOCALES:
        page = tools_page(locale=locale, base_url=BASE)
        title = re.search(r"<title>(.*?)</title>", page).group(1)  # type: ignore[union-attr]
        description = re.search(  # type: ignore[union-attr]
            r"<meta name='description' content='([^']*)'>", page
        ).group(1)
        assert 15 <= len(html.unescape(title)) <= 65, title
        assert 50 <= len(html.unescape(description)) <= 160, description
        titles.add(title)
    assert len(titles) == 3


def test_landing_links_the_free_tools_from_its_closing_call() -> None:
    # The tools band left the short landing; one line under the closing call leads
    # to the hub, and the menu and the footer keep their links.
    for locale in LOCALES:
        page = landing(locale=locale)
        main = _main(page)
        closing = main.split("id='subir'", 1)[1]
        assert tools_url(locale) in _hrefs(closing)
        assert tools_url(locale) in _hrefs(page.split("</main>", 1)[1])
        assert COPY[locale]["band_lead"] not in html.unescape(main)
        assert find_claims(html.unescape(main)) == []


@pytest.mark.parametrize(("alias", "target"), GUESSED)
def test_guessed_addresses_forward_301(client: TestClient, alias: str, target: str) -> None:
    response = client.get(alias, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == target
    assert client.get(target).status_code == 200


def test_guessed_addresses_keep_only_the_query_they_should(client: TestClient) -> None:
    calculator = client.get("/en/calculator?sharpe=1.8&years=3&trials=100", follow_redirects=False)
    assert calculator.status_code == 301
    assert calculator.headers["location"] == "/calculator?sharpe=1.8&years=3&trials=100"
    reader = client.get("/reading?trades=45", follow_redirects=False)
    assert reader.status_code == 301
    assert reader.headers["location"] == "/en/reading?trades=45"
    faq = client.get("/faq?x=1", follow_redirects=False)
    assert faq.status_code == 301
    assert faq.headers["location"] == "/en/faq"
    # The path is fixed: a query cannot send the visitor to another site.
    odd = client.get("/reading?next=https://elsewhere.example", follow_redirects=False)
    assert odd.headers["location"].startswith("/en/reading?")


@pytest.mark.parametrize("locale", LOCALES)
def test_reader_has_content_links_and_the_report_step(client: TestClient, locale: str) -> None:
    words = reading.COPY[locale]
    path = reading.READING_PATH[locale]
    empty = client.get(path)
    assert empty.status_code == 200
    hrefs = _hrefs(empty.text)
    for expected in (
        calculator_url(locale),
        article_url("cuantas-operaciones-porcentaje-aciertos", locale),
        tools_url(locale),
        audit_path(locale),
        _sample_url(locale),
        guides_index_url(locale),
    ):
        assert expected in hrefs, expected
    assert html.escape(words["beyond_title"], quote=True) in empty.text
    assert find_claims(html.unescape(empty.text)) == []
    filled = client.get(path, params=FIGURES)
    assert filled.status_code == 200
    text = filled.text
    beyond = html.escape(words["beyond_title"], quote=True)
    assert text.index(beyond) > text.index("data-public-share")
    assert find_claims(html.unescape(text)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_sample_report_footer_links_the_free_tools(client: TestClient, locale: str) -> None:
    response = client.get(_sample_url(locale))
    assert response.status_code == 200
    page = response.text
    foot = page[page.index("<div class='report-foot'>") :]
    links = foot[foot.index("<nav class='rf-links'>") : foot.index("</nav>")]
    # A link, so hidden when the report is printed, in the report's own language.
    link = f"<a class='no-print' href='{tools_url(locale)}'>{html.escape(COPY[locale]['nav'])}</a>"
    assert link in links
    assert page.count(f"href='{tools_url(locale)}'") >= 1
    assert client.get(tools_url(locale)).status_code == 200
    assert find_claims(_visible_text(links)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_calculator_links_the_deflated_sharpe_article_and_the_reader(
    client: TestClient, locale: str
) -> None:
    page = client.get(calculator_url(locale))
    assert page.status_code == 200
    hrefs = _hrefs(page.text)
    assert article_url("sharpe-deflactado-track-record", locale) in hrefs
    assert reading.READING_PATH[locale] in _hrefs(_main(page.text))
    assert find_claims(html.unescape(page.text)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_examples_link_the_reader(client: TestClient, locale: str) -> None:
    page = client.get(EXAMPLES_PATH[locale])
    assert page.status_code == 200
    assert reading.READING_PATH[locale] in _hrefs(_main(page.text))
    assert find_claims(html.unescape(page.text)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_prop_firm_profile_and_article_link_each_other(client: TestClient, locale: str) -> None:
    profile = audience_url("retos-prop-firm", locale)
    article = article_url("cuantos-intentos-reto-prop-firm", locale)
    profile_page = client.get(profile)
    article_page = client.get(article)
    assert profile_page.status_code == article_page.status_code == 200
    assert article in _hrefs(_main(profile_page.text))
    assert profile in _hrefs(_main(article_page.text))


@pytest.mark.parametrize("locale", LOCALES)
def test_every_listed_case_article_exists(client: TestClient, locale: str) -> None:
    from quant_trade.audit.pages import AUDIENCE_ARTICLES

    for slug, keys in AUDIENCE_ARTICLES.items():
        page = client.get(audience_url(slug, locale))
        assert page.status_code == 200
        hrefs = _hrefs(_main(page.text))
        for key in keys:
            assert article_url(key, locale) in hrefs
            assert client.get(article_url(key, locale)).status_code == 200


def _example_paragraph(page: str, key: str) -> str:
    found = re.search(rf"<p\b[^>]*data-tool-example='{key}'[^>]*>(.*?)</p>", page, re.S)
    assert found is not None, key
    return found.group(1)


def _example_link(page: str, key: str) -> str:
    found = re.search(rf"<a\b[^>]*data-tool-example-link='{key}'[^>]*>.*?</a>", page, re.S)
    assert found is not None, key
    links = _hrefs(found.group(0))
    assert len(links) == 1
    return links.pop()


def _number(value: float, locale: str, decimals: int = 1) -> str:
    text = f"{value:.{decimals}f}"
    return text if locale == "en" else text.replace(".", ",")


def _percent(value: float, locale: str) -> str:
    return f"{_number(value * 100, locale)} %"


def _table(page: str, attributes: str) -> str:
    found = re.search(rf"<table {attributes}>.*?</table>", page, re.S)
    assert found is not None, attributes
    return _visible_text(found.group(0))


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_examples_have_declared_evidence_and_localized_links(
    client: TestClient, locale: str
) -> None:
    assert TOOL_KEYS == ("calculator", "winrate", "challenge", "ruin", "reading", "check")
    examples = tools_examples.examples(locale)
    assert set(examples) == {*TOOL_KEYS, "rules_table"}
    page = client.get(tools_url(locale)).text
    main = _main(page)
    forbidden = re.compile(
        r"\b(?:verificado|certificado|garantiza|rentable|aprobar|pasar|pass)\b", re.I
    )
    for key, example in examples.items():
        paragraph = _example_paragraph(main, key)
        visible = _visible_text(paragraph)
        assert example.evidence == "DECLARED"
        assert "badge DECLARED" in paragraph
        assert example.text in visible
        assert COPY[locale]["example"] in visible
        if key != "check":
            assert COPY[locale]["example_evidence"] in visible
        assert _example_link(main, key) == example.url
        assert find_claims(visible) == []
        assert forbidden.search(visible) is None
        assert main.count(f"data-tool-example='{key}'") == 1
        assert main.count(f"data-tool-example-link='{key}'") == 1
    assert main.count(COPY[locale]["example_open"]) == len(examples)


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_luck_example_recalculates_from_its_link(client: TestClient, locale: str) -> None:
    example = tools_examples.examples(locale)["calculator"]
    assert example.url == calculator.share_url(locale, tools_examples.CALCULATOR_INPUT)
    values = dict(parse_qsl(urlsplit(example.url).query))
    value = calculator.read_input(
        values.get("sharpe"),
        values.get("years"),
        values.get("trials"),
        values.get("periods_per_year"),
    )
    assert value == tools_examples.CALCULATOR_INPUT
    assert isinstance(value, calculator.CalculatorInput)
    result = calculator.compute(value)
    expected = _number(result["luck_sharpe"]["value"], locale, 2)
    assert expected in example.text
    response = client.get(example.url)
    assert response.status_code == 200
    assert expected in _table(response.text, "class='calc-result'")
    assert "data-calc-verdict" in response.text


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_winrate_example_recalculates_from_its_link(client: TestClient, locale: str) -> None:
    example = tools_examples.examples(locale)["winrate"]
    assert example.url == winrate.share_url(locale, tools_examples.WINRATE_VALUES)
    values = dict(parse_qsl(urlsplit(example.url).query))
    claim = winrate.parse(values, locale)
    assert claim == winrate.parse(tools_examples.WINRATE_VALUES, locale)
    interval = winrate.read(claim).interval
    assert interval is not None
    response = client.get(example.url)
    assert response.status_code == 200
    result = _table(response.text, "class='calc-result'")
    for bound in interval:
        expected = _percent(bound, locale)
        assert expected in example.text
    # The destination's editorial interval places one percent sign after both bounds.
    assert claim.win_rate is not None and claim.trades is not None
    assert win_rate_interval(claim.win_rate, claim.trades, locale) in result


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_challenge_example_recalculates_from_its_link(
    client: TestClient, locale: str
) -> None:
    example = tools_examples.examples(locale)["challenge"]
    assert example.url == challenge_calc.share_url(locale, tools_examples.CHALLENGE_INPUT)
    values = dict(parse_qsl(urlsplit(example.url).query))
    parsed = challenge_calc.parse(values)
    assert parsed.value == tools_examples.CHALLENGE_INPUT
    assert parsed.value is not None
    result = challenge_calc.compute(parsed.value)
    expected = _percent(result.declared.outcome["pass"]["value"], locale)
    assert expected in example.text
    response = client.get(example.url)
    assert response.status_code == 200
    assert expected in _table(response.text, "class='calc-result' data-challenge-result")


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_ruin_example_recalculates_both_rates_from_its_link(
    client: TestClient, locale: str
) -> None:
    example = tools_examples.examples(locale)["ruin"]
    assert example.url == ruin_calc.share_url(locale, tools_examples.RUIN_INPUT)
    values = dict(parse_qsl(urlsplit(example.url).query))
    parsed = ruin_calc.parse(values)
    assert parsed.value == tools_examples.RUIN_INPUT
    assert parsed.value is not None
    result = ruin_calc.compute(parsed.value)
    assert result.lower is not None
    assert result.interval is not None
    response = client.get(example.url)
    assert response.status_code == 200
    declared = _percent(result.declared.ruin, locale)
    lower = _percent(result.lower.ruin, locale)
    assert declared in example.text
    assert lower in example.text
    assert _percent(result.lower.win_rate, locale) in example.text
    assert declared in _table(response.text, "class='calc-result' data-ruin-result")
    assert lower in _table(response.text, "class='ruin-lower'")


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_reader_example_recalculates_from_its_link(client: TestClient, locale: str) -> None:
    example = tools_examples.examples(locale)["reading"]
    assert example.url == reading.reading_url(locale, tools_examples.READING_VALUES)
    values = dict(parse_qsl(urlsplit(example.url).query))
    claim = reading.claim_from_query(values, locale)
    assert claim == reading.claim_from_query(tools_examples.READING_VALUES, locale)
    response = client.get(example.url)
    assert response.status_code == 200
    found = re.search(r"<div class='public-card-preview'>(.*?)</div>", response.text, re.S)
    assert found is not None
    result = _visible_text(found.group(1))
    for key, value, _note in public_card._readings(claim):
        if key in ("wilson", "luck", "breakeven"):
            assert value is not None
            assert value in example.text
            assert value in result


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_rules_example_counts_programs_and_most_recent_source(
    client: TestClient, locale: str
) -> None:
    example = tools_examples.examples(locale)["rules_table"]
    rows = rules_table.rows()
    firms = len({row.firm for row in rows})
    programs = len({row.program for row in rows})
    latest = max(row.rules.as_of for row in rows)
    assert f"{firms} " in example.text
    assert f"{programs} " in example.text
    assert latest in example.text
    assert example.url == rules_table.rules_table_url(locale)
    response = client.get(example.url)
    assert response.status_code == 200
    assert latest in _visible_text(_main(response.text))
    for row in rows:
        assert row.rules.source_url in _hrefs(response.text)
    hub = client.get(tools_url(locale)).text
    assert f"href='{example.url}' data-rules-table" in hub


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_check_example_opens_the_file_form_without_fabricating_a_result(
    client: TestClient, locale: str
) -> None:
    # Check accepts a local file by POST, so its example cannot preload a file in a GET URL.
    example = tools_examples.examples(locale)["check"]
    assert example.url == seo.CHECK_PATH[locale]
    assert urlsplit(example.url).query == ""
    response = client.get(example.url)
    assert response.status_code == 200
    main = _main(response.text)
    assert "method='post'" in main
    assert "type='file' name='report'" in main
    assert "class='chk-result" not in main


@pytest.mark.parametrize("locale", LOCALES)
def test_tools_examples_do_not_add_results_to_structured_data(
    client: TestClient, locale: str
) -> None:
    page = client.get(tools_url(locale)).text
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    data = [json.loads(block) for block in blocks]
    assert [item["@type"] for item in data] == ["ItemList"]
    items = data[0]["itemListElement"]
    assert len(items) == len(TOOL_KEYS)
    for key, entry in zip(TOOL_KEYS, items, strict=True):
        item = entry["item"]
        assert item["description"] == COPY[locale][key]["question"]
        assert urlsplit(item["url"]).query == ""
        assert set(item) == {
            "@type",
            "name",
            "description",
            "url",
            "applicationCategory",
            "operatingSystem",
            "isAccessibleForFree",
            "inLanguage",
            "offers",
            "publisher",
        }
    for example in tools_examples.examples(locale).values():
        assert example.text not in "".join(blocks)


def test_tools_example_notes_have_explicit_spanish_translations() -> None:
    assert localize(COPY["en"]["example_evidence"], "es") == COPY["es"]["example_evidence"]
    assert (
        localize(tools_examples.examples("en")["check"].text, "es")
        == tools_examples.examples("es")["check"].text
    )
