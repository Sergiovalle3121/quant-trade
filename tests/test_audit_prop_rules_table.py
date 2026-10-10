"""The public table of prop-firm rules: every published preset, with source and date."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import challenge_calc as calc  # noqa: E402
from quant_trade.audit import rules_table as table  # noqa: E402
from quant_trade.audit import seo  # noqa: E402
from quant_trade.audit.articles import article_url  # noqa: E402
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.challenge_pages import (  # noqa: E402
    ARTICLE_KEY,
    _best_rule,
    _note_html,
    _total_rule,
    rules_table_page,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import localize  # noqa: E402
from quant_trade.audit.prop_presets import PRESETS  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import TOOLS_PATH  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
#: Words the brief keeps off the page, in the three languages; "best" may appear
#: only in "best day" / "best-day", the name of the firms' consistency rule.
FORBIDDEN = re.compile(
    r"\b(aprobar\w*|aprobad\w*|pasar|pasas?|pass|passed|passes|passing|aprovar\w*|aprovad\w*|"
    r"verific\w*|verified|certificad\w*|certified|garantiza\w*|guarantee\w*|garantid\w*|"
    r"rentables?|profitable|lucrativ\w*|approved|mejor(?:es)?\s+firmas?|"
    r"melhor(?:es)?\s+(?:empresas?|firmas?)|best\s+(?:prop\s+)?firms?)\b",
    re.IGNORECASE,
)
BEST_ALONE = re.compile(r"\bbest\b(?![ -]day)", re.IGNORECASE)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
#: Filters that name nothing: the page shows the whole table, never an error.
INVALID = {"firma": "ninguna", "perdida": "intraday", "mercado": "stocks"}


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("rules-table")
    settings = AuditSettings(database_url=f"sqlite:///{directory}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _visible(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _links(page: str) -> list[str]:
    return [html.unescape(value) for value in re.findall(r"\bhref=['\"]([^'\"]*)", page)]


def _rows(page: str) -> dict[str, str]:
    """Each table row's inner markup, by preset key."""
    return dict(re.findall(r"<tr data-rule-row='([^']+)'>(.*?)</tr>", page, re.S))


def _cells(row: str) -> list[str]:
    return [_visible(cell) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def _json_ld(page: str) -> list[dict]:
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


def test_the_table_has_exactly_the_published_presets_phase_by_phase() -> None:
    published = [key for key, rules in PRESETS.items() if rules.source_url.startswith("https://")]
    assert [row.key for row in table.ROWS] == published
    assert "generic-2step-phase1" not in {row.key for row in table.ROWS}
    assert {row.firm for row in table.ROWS} == set(calc.FIRMS)
    assert table.latest_as_of() == max(PRESETS[key].as_of for key in published)
    counted = table.counts()
    assert counted["rows"] == len(published)
    assert counted["firms"] == len(calc.FIRMS)
    assert counted["programs"] == len(calc.PROGRAMS)
    assert counted["static"] + counted["trailing"] + counted["lock"] == counted["programs"]
    assert (
        counted["daily_initial"] + counted["daily_day"] + counted["daily_none"]
        == counted["programs"]
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_page_is_public_with_and_without_filters(site: TestClient, locale: str) -> None:
    path = table.rules_table_url(locale)
    assert table.rules_table_paths() in seo.PUBLIC_PAGES
    whole = site.get(path)
    assert whole.status_code == 200
    assert f"<html lang='{locale}'>" in whole.text
    assert len(_rows(whole.text)) == len(table.ROWS)
    assert "data-rules-showing" not in whole.text
    for query in (
        {"firma": "ftmo"},
        {"perdida": "trailing_eod_lock"},
        {"mercado": "futures"},
        {"firma": "topstep", "perdida": "trailing_eod_lock", "mercado": "futures"},
    ):
        response = site.get(path, params=query)
        assert response.status_code == 200, query
        assert "data-rules-showing" in response.text
        # The canonical and the alternates never carry the query.
        assert f"<link rel='canonical' href='{BASE}{path}'>" in response.text
        for lang, other in table.rules_table_paths().items():
            assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{other}'>" in response.text
    wrong = site.get(path, params=INVALID)
    assert wrong.status_code == 200
    assert len(_rows(wrong.text)) == len(table.ROWS)
    assert "data-rules-showing" not in wrong.text
    repeated = site.get(f"{path}?firma=ftmo&firma=topstep")
    assert repeated.status_code == 200


@pytest.mark.parametrize("locale", LOCALES)
def test_every_row_is_its_preset(site: TestClient, locale: str) -> None:
    page = site.get(table.rules_table_url(locale)).text
    rows = _rows(page)
    assert list(rows) == [row.key for row in table.ROWS]
    words = table.COPY[locale]
    cwords = calc.COPY[locale]
    for row in table.ROWS:
        rules = row.rules
        inner = rows[rules.key]
        cells = _cells(inner)
        assert len(cells) == 11, rules.key
        assert cells[0] == rules.firm
        assert f"href='{calc.challenge_url(locale, row.firm)}'" in inner
        assert localize(rules.program, locale) in cells[1]
        assert "Verification" not in cells[1]
        # The figures, each read back from the preset, never from a text.
        assert cells[2] == calc._pct(rules.profit_target, locale)
        assert float(NUMBER.search(cells[2]).group(0).replace(",", ".")) == pytest.approx(  # type: ignore[union-attr]
            rules.profit_target * 100
        )
        if rules.max_daily_loss is None:
            expected = (
                cwords["daily_no_limit"]
                if rules.key in calc.NO_DAILY_LIMIT
                else words["daily_untranscribed"]
            )
            assert cells[3] == expected, rules.key
        else:
            assert cells[3].startswith(calc._pct(rules.max_daily_loss, locale)), rules.key
            basis = "daily_day" if rules.daily_loss_basis == "start_of_day" else "daily_initial"
            assert cells[3] == cwords[basis].format(value=calc._pct(rules.max_daily_loss, locale))
        assert cells[4] == _total_rule(rules, locale)
        assert cells[4].startswith(calc._pct(rules.max_total_loss, locale))
        kind = {"trailing_eod": "total_trailing", "trailing_eod_lock": "total_lock"}.get(
            rules.total_loss_type, "total_static"
        )
        assert cwords[kind].format(value=calc._pct(rules.max_total_loss, locale)) in cells[4]
        assert cells[5] == str(rules.min_trading_days)
        if rules.time_limit_days:
            assert cells[6] == cwords["time_days"].format(n=rules.time_limit_days)
        else:
            assert cells[6] == cwords["time_none"]
        assert cells[7] == _best_rule(rules, locale)
        if rules.best_day_limit is not None:
            assert calc._pct(rules.best_day_limit, locale) in cells[7]
        else:
            assert cells[7] == cwords["best_none"]
        if rules.markets:
            assert cells[8] == table.market_words(rules.markets, locale)
            assert f"href='{html.escape(rules.markets_source or '')}'" in inner
        else:
            assert cells[8] == words["markets_unknown"]
        assert f"href='{html.escape(rules.source_url)}'" in inner
        assert cells[9] == words["source_link"].format(firm=rules.firm)
        assert cells[10] == rules.as_of
        assert f"<time datetime='{rules.as_of}'>" in inner


def _figures_from_presets(locale: str) -> set[str]:
    """Every number the presets can put on the page, as the page writes it."""
    allowed: set[str] = set()
    for row in table.ROWS:
        rules = row.rules
        for share in (
            rules.profit_target,
            rules.max_daily_loss,
            rules.max_total_loss,
            rules.best_day_limit,
        ):
            if share is not None:
                allowed.update(NUMBER.findall(calc._pct(share, locale)))
        allowed.add(str(rules.min_trading_days))
        if rules.time_limit_days:
            allowed.add(str(rules.time_limit_days))
        account = calc.account_size(rules.key)
        if account is not None:
            allowed.update(NUMBER.findall(calc._amount(account, locale)))
            allowed.update(NUMBER.findall(calc._amount(rules.max_total_loss * account, locale)))
        for text in (rules.program, rules.phase, rules.as_of, rules.markets_as_of or ""):
            allowed.update(NUMBER.findall(localize(text, locale)))
        allowed.update(NUMBER.findall(localize(rules.notes[0], locale)))
    allowed.update(str(value) for value in table.counts().values())
    return allowed


@pytest.mark.parametrize("locale", LOCALES)
def test_no_figure_on_the_page_is_typed_by_hand(site: TestClient, locale: str) -> None:
    for text in _strings(table.COPY[locale]):
        assert not re.search(r"\d", text), text
    allowed = _figures_from_presets(locale)
    for query in ({}, {"firma": "ftmo"}, {"mercado": "futures"}):
        page = site.get(table.rules_table_url(locale), params=query).text
        # The notes link their pages by host; an address's digits are not figures.
        main = re.sub(r"<a [^>]*>[^<]*</a>", " ", _main(page))
        seen = set(NUMBER.findall(_visible(main)))
        shown = {str(len(table.filtered_rows(table.parse_filters(query))))}
        assert seen <= allowed | shown, sorted(seen - allowed - shown)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_page_passes_the_guard_and_keeps_the_forbidden_words_out(
    site: TestClient, locale: str
) -> None:
    for query in ({}, {"firma": "ftmo"}, {"perdida": "static"}, {"mercado": "fx"}):
        page = site.get(table.rules_table_url(locale), params=query).text
        text = html.unescape(page)
        assert find_claims(text) == []
        visible = _visible(_main(page))
        assert FORBIDDEN.findall(visible) == [], FORBIDDEN.findall(visible)
        assert BEST_ALONE.findall(visible) == [], BEST_ALONE.findall(visible)
        for block in _json_ld(page):
            for string in _strings(block):
                assert find_claims(string) == [], string
                assert FORBIDDEN.findall(string) == [], string
    for text in _strings(table.COPY[locale]):
        assert find_claims(text) == [], text
        assert FORBIDDEN.findall(text) == [], text
    assert "no está afiliado" in table.COPY["es"]["not_affiliated"]
    assert "not affiliated" in table.COPY["en"]["not_affiliated"]
    assert "não é afiliado" in table.COPY["pt"]["not_affiliated"]


@pytest.mark.parametrize("locale", LOCALES)
def test_filters_narrow_the_rows_and_keep_each_other(site: TestClient, locale: str) -> None:
    path = table.rules_table_url(locale)
    ftmo = site.get(path, params={"firma": "ftmo"}).text
    assert set(_rows(ftmo)) == {row.key for row in table.ROWS if row.firm == "ftmo"}
    static = _rows(site.get(path, params={"perdida": "static"}).text)
    assert set(static) == {r.key for r in table.ROWS if r.rules.total_loss_type == "static"}
    futures = _rows(site.get(path, params={"mercado": "futures"}).text)
    assert set(futures) == {r.key for r in table.ROWS if "futures" in (r.rules.markets or ())}
    assert futures and len(futures) < len(table.ROWS)
    both = _rows(site.get(path, params={"firma": "topstep", "mercado": "futures"}).text)
    assert set(both) == {r.key for r in table.ROWS if r.firm == "topstep"}
    # The chips of one filter keep the others; the chosen one is marked.
    chips = re.findall(r"<a href='([^']*)'( aria-current='true')? data-filter='(\w+)'", ftmo)
    assert chips
    for href, current, field in chips:
        parsed = urlsplit(html.unescape(href))
        assert parsed.path == path
        query = parse_qs(parsed.query)
        if field != "firm" or current:
            assert query.get("firma") == ["ftmo"], href
    marked = [(field, href) for href, current, field in chips if current]
    assert [field for field, _ in marked] == ["firm", "loss", "market"]
    assert parse_qs(urlsplit(html.unescape(marked[1][1])).query) == {"firma": ["ftmo"]}
    # The whole table's chips carry no query at all, and nothing says "showing".
    whole = site.get(path).text
    for href, _current, _field in re.findall(
        r"<a href='([^']*)'( aria-current='true')? data-filter='(\w+)'", whole
    ):
        assert html.unescape(href).startswith(path)
    assert table.COPY[locale]["showing"].format(n=len(_rows(ftmo)), total=len(table.ROWS)) in (
        html.unescape(ftmo)
    )
    # A market filter says that programs whose pages state no markets are not shown.
    assert "data-rules-market-note" in site.get(path, params={"mercado": "fx"}).text
    assert "data-rules-market-note" not in ftmo
    # A combination with no row says so and offers the whole table, with a 200.
    none = site.get(path, params={"firma": "ftmo", "mercado": "futures"})
    assert none.status_code == 200
    assert "data-rules-empty" in none.text and _rows(none.text) == {}
    assert f"href='{path}'" in none.text


def test_the_filters_parse_only_what_names_something() -> None:
    assert table.parse_filters({}) == table.Filters()
    assert table.parse_filters(INVALID) == table.Filters()
    chosen = table.parse_filters({"firma": "ftmo", "perdida": "static", "mercado": "fx"})
    assert chosen == table.Filters(firm="ftmo", loss="static", market="fx")
    assert chosen.query() == "?firma=ftmo&perdida=static&mercado=fx"
    assert chosen.with_(firm="").query() == "?perdida=static&mercado=fx"
    assert table.Filters().query() == ""
    assert not table.Filters().active and chosen.active


def test_sitemap_lists_the_table_with_its_date(site: TestClient) -> None:
    sitemap = site.get("/sitemap.xml")
    assert sitemap.status_code == 200
    root = ElementTree.fromstring(sitemap.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    dates = {
        url.findtext("s:loc", namespaces=ns): url.findtext("s:lastmod", namespaces=ns)
        for url in root.findall("s:url", ns)
    }
    for path in table.rules_table_paths().values():
        assert dates[BASE + path] == table.RULES_TABLE_PUBLISHED, path
        assert seo.page_lastmod(path) == table.RULES_TABLE_PUBLISHED


@pytest.mark.parametrize("locale", LOCALES)
def test_structured_data_is_a_dataset_and_four_questions_of_fact(
    site: TestClient, locale: str
) -> None:
    page = site.get(table.rules_table_url(locale)).text
    blocks = {block["@type"]: block for block in _json_ld(page)}
    dataset = blocks["Dataset"]
    assert dataset["dateModified"] == table.latest_as_of()
    assert dataset["url"] == BASE + table.rules_table_url(locale)
    assert dataset["inLanguage"] == locale
    assert dataset["publisher"]["name"] == seo.BRAND
    assert dataset["name"] == table.COPY[locale]["title"]
    faq = blocks["FAQPage"]["mainEntity"]
    assert len(faq) == 4
    expected = table.faq(locale)
    assert [item["name"] for item in faq] == [question for question, _ in expected]
    assert [item["acceptedAnswer"]["text"] for item in faq] == [answer for _, answer in expected]
    visible = _visible(_main(page))
    for question, answer in expected:
        assert question in visible and answer in visible
        assert "{" not in answer


@pytest.mark.parametrize("locale", LOCALES)
def test_each_firm_has_two_sentences_from_its_presets_and_its_links(
    site: TestClient, locale: str
) -> None:
    page = site.get(table.rules_table_url(locale)).text
    main = _main(page)
    words = table.COPY[locale]
    for slug, name in calc.FIRMS.items():
        found = re.search(
            rf"<div class='rules-firm' id='firma-{slug}' data-rules-firm='{slug}'>(.*?)</div>",
            main,
            re.S,
        )
        assert found is not None, slug
        block = found.group(1)
        assert f"<h3>{html.escape(name)}</h3>" in block
        programs = table.firm_programs(slug)
        assert programs == tuple(calc.firm_programs(slug))
        text = _visible(block)
        for key in programs:
            assert localize(PRESETS[key].program, locale) in text, key
        assert PRESETS[programs[0]].as_of in text
        # The first note of its first program, its addresses as short links by host.
        note = _note_html(localize(PRESETS[programs[0]].notes[0], locale), locale)
        assert f"<p data-firm-note>{note}</p>" in block, slug
        assert f"href='{calc.challenge_url(locale, slug)}' data-firm-calculator" in block
        assert words["firm_calculator"].format(firm=name) in text
        assert f"href='{table.rules_table_url(locale)}?firma={slug}'" in block
    assert "data-rules-affiliation" in main
    assert "data-rules-no-buy" in main
    for item in words["blind"]:
        assert html.escape(item) in main


@pytest.mark.parametrize("locale", LOCALES)
def test_the_table_is_linked_from_the_tools_calculator_firm_pages_and_the_case_page(
    site: TestClient, locale: str
) -> None:
    path = table.rules_table_url(locale)
    hub = site.get(TOOLS_PATH[locale]).text
    assert path in _links(_main(hub)) and "data-rules-table" in hub
    for firm in ("", *calc.FIRMS):
        calculator = site.get(calc.challenge_url(locale, firm)).text
        assert path in _links(_main(calculator)), firm
    case = site.get(audience_url("retos-prop-firm", locale)).text
    assert path in _links(_main(case)) and "data-audience-rules" in case
    # And the table links back: the calculator, the article, the case and the hub.
    page = site.get(path).text
    links = _links(_main(page))
    assert calc.challenge_url(locale) in links
    assert article_url(ARTICLE_KEY, locale) in links
    assert audience_url("retos-prop-firm", locale) in links
    assert TOOLS_PATH[locale] in links
    for firm in calc.FIRMS:
        assert calc.challenge_url(locale, firm) in links


def test_metadata_is_unique_per_language_and_in_bounds() -> None:
    titles: set[str] = set()
    for locale in LOCALES:
        page = rules_table_page(locale=locale, base_url=BASE)
        title = html.unescape(re.search(r"<title>(.*?)</title>", page).group(1))  # type: ignore[union-attr]
        description = html.unescape(
            re.search(r"<meta name='description' content='([^']*)'>", page).group(1)  # type: ignore[union-attr]
        )
        assert 15 <= len(title) <= 65, title
        assert 50 <= len(description) <= 160, description
        assert seo.BRAND in title
        assert str(table.counts()["firms"]) in description
        titles.add(title)
    assert len(titles) == 3


def test_a_page_without_a_base_url_renders(tmp_path: Path) -> None:
    page = rules_table_page(locale="es")
    assert "og:image" not in page
    assert len(_rows(page)) == len(table.ROWS)
    assert rules_table_page(locale="xx").count("<html lang='es'>") == 1
