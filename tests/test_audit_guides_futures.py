"""Documented export guides: Tradovate, TopstepX, Sierra Chart and cTrader.

Each guide's steps come from the platform's own help pages, named on the page
under the steps with the day they were read (``Guide.sources``,
``Guide.read_on``). None of those pages publishes the file's headers, so each
file is read by its column names (``audit/universal.py``): a synthetic fixture
per file shape goes through the importer here, and the shapes the importer
refuses (a single time column, the Trades tab with its default BP/EP markers)
are refused the way the guide warns. The pages link the challenge calculator
and the rules table (plus its futures firms for the three futures guides),
carry their publication date in the sitemap, and promise nothing. Rithmic's
R | Trader Pro has no guide: its official pages describe no export
(``docs/AUDIT_SAAS.md``).
"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.challenge_calc import challenge_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guide_capabilities import GUIDE_FORMATS, GUIDE_TOOL  # noqa: E402
from quant_trade.audit.guides import (  # noqa: E402
    GUIDES_BY_SLUG,
    GUIDES_COPY,
    guide_url,
    guides_index_url,
)
from quant_trade.audit.importers import (  # noqa: E402
    UNIVERSAL_FILLS_CSV,
    UNIVERSAL_TRADES_CSV,
    ReportFormatError,
    import_report,
)
from quant_trade.audit.mapping import MAPPABLE_CODES  # noqa: E402
from quant_trade.audit.rules_table import FILTER_MARKET, rules_table_url  # noqa: E402
from quant_trade.audit.seo import GUIDES_PUBLISHED, SITE_UPDATED, page_lastmod  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
FUTURES_GUIDES = ("tradovate", "topstepx", "sierra-chart")
SOURCED_GUIDES = (*FUTURES_GUIDES, "ctrader")
#: The official host each guide's sources live on: the platform's own help.
OFFICIAL_HOSTS = {
    "tradovate": "support.tradovate.com",
    "topstepx": "help.topstep.com",
    "sierra-chart": "www.sierrachart.com",
    "ctrader": "help.ctrader.com",
}
NOT_AFFILIATED = {
    "es": "Rigor no está afiliado",
    "en": "Rigor is not affiliated",
    "pt": "O Rigor não é afiliado",
}
#: Word stems no guide may use in any sentence (the brief's list, in the three
#: languages), beyond what the guard's own patterns refuse in context.
FORBIDDEN_STEMS = ("verific", "certific", "aprob", "aprov", "garant", "rentab", "lucrativ")
#: The file shapes each guide's steps produce, with the synthetic fixture that
#: has the columns the guide names, the mapping the guide says the form needs
#: (``None`` when the file is read as it is) and what the importer reads.
FILE_SHAPES = [
    pytest.param(
        "ctrader",
        "ctrader_history_columns.csv",
        {"profit": "Gross (currency)"},
        UNIVERSAL_TRADES_CSV,
        ["long", "long", "short"],
        [50.0, -50.0, -10.0],
        id="ctrader-history-columns-synthetic",
    ),
    pytest.param(
        "tradovate",
        "tradovate_performance.csv",
        None,
        UNIVERSAL_TRADES_CSV,
        ["long", "short", "long", "long"],
        [20.0, 6.0, -20.0, 200.0],
        id="tradovate-performance",
    ),
    pytest.param(
        "tradovate",
        "tradovate_orders.csv",
        None,
        UNIVERSAL_FILLS_CSV,
        ["long", "short"],
        [200.0, 20.0],
        id="tradovate-orders",
    ),
    pytest.param(
        "topstepx",
        "topstepx_trades.csv",
        None,
        UNIVERSAL_TRADES_CSV,
        ["long", "short", "long"],
        [40.0, 20.0, -200.0],
        id="topstepx-trades",
    ),
    pytest.param(
        "sierra-chart",
        "sierra_chart_trade_activity.txt",
        None,
        UNIVERSAL_FILLS_CSV,
        ["long", "short"],
        [100.0, 20.0],
        id="sierra-chart-trade-activity",
    ),
    pytest.param(
        "sierra-chart",
        "sierra_chart_trades.txt",
        None,
        UNIVERSAL_TRADES_CSV,
        ["long", "short"],
        [100.0, 20.0],
        id="sierra-chart-trades",
    ),
]


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, base_url=BASE
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _section(page: str, heading: str) -> str:
    """One doc section of a guide: from its heading to the next one or the article's end."""
    start = page.index(f">{html.escape(heading, quote=True)}</h2>")
    ends = [i for i in (page.find("<h2 ", start), page.find("</article>", start)) if i > 0]
    return page[start : min(ends)]


def _texts(slug: str, locale: str) -> list[str]:
    text = GUIDES_BY_SLUG[slug].text[locale]
    return [
        text.title,
        text.summary,
        text.seo_description,
        text.file,
        text.upload,
        *text.steps,
        *text.tips,
    ]


@pytest.mark.parametrize("slug", SOURCED_GUIDES)
def test_every_sourced_guide_names_its_official_sources_and_promises_nothing(slug: str) -> None:
    guide = GUIDES_BY_SLUG[slug]
    assert set(guide.text) == set(LOCALES)
    assert guide.field == "report" and GUIDE_TOOL[slug] == "challenge"
    # One address in every language: the platform's name is the slug.
    assert all(guide.slug_for(locale) == slug for locale in LOCALES)
    assert guide.sources, slug
    for title, url in guide.sources:
        assert title.strip(), slug
        assert url.startswith(f"https://{OFFICIAL_HOSTS[slug]}/"), (slug, url)
    assert date.fromisoformat(guide.read_on).isoformat() == guide.read_on
    for locale in LOCALES:
        tips = " ".join(guide.text[locale].tips)
        assert NOT_AFFILIATED[locale] in tips, (slug, locale)
        # The index card prints the summary: no longer than the other guides'.
        assert len(guide.text[locale].summary) <= 130, (slug, locale)
        for piece in _texts(slug, locale):
            assert find_claims(piece) == [], (slug, locale, piece)
            lowered = piece.lower()
            for stem in FORBIDDEN_STEMS:
                assert stem not in lowered, (slug, locale, stem, piece)
            assert not re.search(r"\bpass(?:ed|es|ing)?\b", lowered), (slug, locale, piece)


@pytest.mark.parametrize(("slug", "name", "columns", "expected", "sides", "pnls"), FILE_SHAPES)
def test_each_file_shape_the_guide_describes_is_read_by_the_importer(
    slug: str,
    name: str,
    columns: dict[str, str] | None,
    expected: str,
    sides: list[str],
    pnls: list[float],
) -> None:
    data = (FIXTURES / name).read_bytes()
    assert b"\r" not in data, name
    report = import_report(data, name, initial_balance=50_000, columns=columns)
    assert report.source_format == expected
    assert expected in GUIDE_FORMATS[slug], (slug, expected)
    assert report.trades.sides == sides
    assert [round(trade.pnl, 2) for trade in report.trades.trades] == pnls
    assert report.initial_balance == 50_000
    assert all(find_claims(warning) == [] for warning in report.warnings)


def test_the_sierra_chart_guide_names_every_column_the_importer_reads() -> None:
    guide = GUIDES_BY_SLUG["sierra-chart"]
    for name, columns in (
        ("sierra_chart_trade_activity.txt", None),
        ("sierra_chart_trades.txt", None),
    ):
        report = import_report((FIXTURES / name).read_bytes(), name, columns=columns)
        read = {value for key, value in report.metadata.items() if key.startswith("column_")}
        assert read, name
        for locale in LOCALES:
            for column in read:
                assert column in guide.text[locale].file, (name, locale, column)
    # The two help centres publish no headers, and the guides say so instead of
    # listing headers they could not check.
    for slug, phrases in (
        (
            "tradovate",
            {
                "es": "no publica las cabeceras",
                "en": "does not publish the CSV headers",
                "pt": "não publica os cabeçalhos",
            },
        ),
        (
            "topstepx",
            {
                "es": "no publica las cabeceras",
                "en": "does not publish the file's headers",
                "pt": "não publica os cabeçalhos",
            },
        ),
    ):
        for locale, phrase in phrases.items():
            assert phrase in GUIDES_BY_SLUG[slug].text[locale].file, (slug, locale)


def test_a_topstepx_file_with_one_time_column_is_refused_as_the_guide_warns() -> None:
    # The fields the help centre attributes to the Trades tab on screen, with one
    # "Time": the importer cannot tell when each trade opened.
    data = (
        b"Symbol,Size,Time,Entry Price,Exit Price,P&L,Fees\n"
        b"MNQZ6,2,10/01/2026 09:13:23,21000,21010,40,0.74\n"
        b"MNQZ6,1,10/02/2026 10:00:00,21010,21000,-20,0.37\n"
    )
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "trades.csv")
    assert "opening time" in str(refused.value)
    # Naming the column on the form does not help: this refusal is not one the
    # mapping page is offered for, so the guide says the file is refused instead
    # of promising a mapping.
    assert refused.value.code == "universal_close_time_only"
    assert refused.value.code not in MAPPABLE_CODES
    for columns in ({"entry_time": "Time"}, {"exit_time": "Time"}):
        with pytest.raises(ReportFormatError) as again:
            import_report(data, "trades.csv", columns=columns)
        assert again.value.code == refused.value.code, columns
    for locale, phrase, refuses, no_fix in (
        ("es", "una sola columna de hora", "el informe lo rechaza", "no lo arregla"),
        ("en", "a single time column", "the report refuses it", "does not fix that"),
        ("pt", "uma só coluna de hora", "o relatório o recusa", "não resolve"),
    ):
        tips = " ".join(GUIDES_BY_SLUG["topstepx"].text[locale].tips)
        assert phrase in tips and refuses in tips and no_fix in tips, locale


def test_the_sierra_chart_trades_tab_with_bp_ep_markers_is_refused_as_the_guide_warns() -> None:
    # Saved as Sierra Chart displays it by default, every Trades row carries the
    # BP (Begin Position) and EP (End Position) suffixes after its date-times and
    # the importer reads no closed trade: the guide says to turn them off first.
    rows = (FIXTURES / "sierra_chart_trades.txt").read_text(encoding="utf-8").splitlines()
    marked = [rows[0]]
    for row in rows[1:]:
        cells = row.split("\t")
        cells[2] += " BP"
        cells[3] += " EP"
        marked.append("\t".join(cells))
    data = ("\n".join(marked) + "\n").encode("utf-8")
    with pytest.raises(ReportFormatError):
        import_report(data, "Trades.txt")
    for locale in LOCALES:
        steps = " ".join(GUIDES_BY_SLUG["sierra-chart"].text[locale].steps)
        assert "Edit >> Include Begin/End Indicators in Trades List" in steps, locale
        assert " BP " in steps and " EP" in steps, locale


def test_the_sierra_chart_trades_tab_is_read_by_its_column_names_as_the_guide_says() -> None:
    # The Trades tab names its size "Trade Quantity" (its other quantity columns
    # are the maximum open and closed quantities); the importer knows that name,
    # so the file needs no mapping and the guide asks for none.
    data = (FIXTURES / "sierra_chart_trades.txt").read_bytes()
    report = import_report(data, "Trades.txt")
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert report.metadata["column_quantity"] == "Trade Quantity"
    assert report.metadata["column_entry_time"] == "Entry Date Time"
    assert report.metadata["column_exit_time"] == "Exit Date Time"
    for locale in LOCALES:
        tips = " ".join(GUIDES_BY_SLUG["sierra-chart"].text[locale].tips)
        assert "Trade Quantity" in tips, locale
        assert "formulario que Trade" not in tips and "say on the form" not in tips, locale


def test_the_pages_link_the_calculator_the_rules_table_and_the_futures_firms(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    seen: dict[str, int] = {}
    for slug in FUTURES_GUIDES:
        guide = GUIDES_BY_SLUG[slug]
        for locale in LOCALES:
            response = client.get(guide_url(slug, locale))
            assert response.status_code == 200, (slug, locale)
            page = response.text
            words = GUIDES_COPY[locale]
            get = _section(page, words["get"])
            futures = f"{rules_table_url(locale)}?{FILTER_MARKET}=futures"
            for href in (challenge_url(locale), rules_table_url(locale), futures):
                assert f"href='{html.escape(href, quote=True)}'" in get, (slug, locale, href)
                if href not in seen:
                    seen[href] = client.get(href).status_code
                assert seen[href] == 200, href
            assert "<p data-guide-rules>" in get
            assert html.escape(words["futures_firms"], quote=True) in get
            # The official pages the steps come from, under the steps, with the day.
            steps = _section(page, words["steps"])
            assert "class='muted guide-sources'" in steps, (slug, locale)
            # "Sources:" before several links, "Source:" before one.
            label = words["sources" if len(guide.sources) > 1 else "source"]
            assert f"guide-sources'>{html.escape(label, quote=True)} <a " in steps
            if len(guide.sources) > 1:
                assert f"'>{html.escape(words['source'], quote=True)} <a " not in steps
            for title, url in guide.sources:
                link = (
                    f"<a href='{html.escape(url, quote=True)}' rel='noopener noreferrer'>"
                    f"{html.escape(title, quote=True)}</a>"
                )
                assert link in steps, (slug, locale, title)
            assert guide.read_on[:4] in steps
            assert find_claims(page) == [], (slug, locale)
    # A guide with another tool prints neither line.
    other = client.get(guide_url("zerodha", "es")).text
    assert "data-guide-rules" not in other and "guide-sources" not in other
    # The index names the three platforms in every language.
    for locale in LOCALES:
        index = client.get(guides_index_url(locale)).text
        for slug in FUTURES_GUIDES:
            assert f"href='{guide_url(slug, locale)}'" in index, (slug, locale)
            assert html.escape(GUIDES_BY_SLUG[slug].platform, quote=True) in index


def test_the_sitemap_dates_the_futures_guides_on_their_publication(tmp_path: Path) -> None:
    assert set(GUIDES_PUBLISHED) == set(SOURCED_GUIDES)
    for slug, published in GUIDES_PUBLISHED.items():
        assert date.fromisoformat(published).isoformat() == published
        assert published >= SITE_UPDATED
        for locale in LOCALES:
            assert page_lastmod(guide_url(slug, locale)) == published, (slug, locale)
    assert page_lastmod(guide_url("zerodha", "es")) == SITE_UPDATED
    response = _client(tmp_path).get("/sitemap.xml")
    assert response.status_code == 200
    root = ElementTree.fromstring(response.content)
    lastmod = {
        url.findtext("s:loc", namespaces=SITEMAP_NS): url.findtext(
            "s:lastmod", namespaces=SITEMAP_NS
        )
        for url in root.findall("s:url", SITEMAP_NS)
    }
    for slug, published in GUIDES_PUBLISHED.items():
        for locale in LOCALES:
            assert lastmod[BASE + guide_url(slug, locale)] == published, (slug, locale)


@pytest.mark.parametrize("locale", LOCALES)
def test_ctrader_each_step_links_its_official_source(tmp_path: Path, locale: str) -> None:
    guide = GUIDES_BY_SLUG["ctrader"]
    assert guide.read_on == "2026-10-11"
    assert len(guide.step_sources) == len(guide.text[locale].steps) == 8
    assert all(source in guide.sources for source in guide.step_sources)
    page = _client(tmp_path).get(guide_url("ctrader", locale)).text
    steps = _section(page, GUIDES_COPY[locale]["steps"])
    items = re.findall(r"<li>(.*?)</li>", steps, flags=re.S)
    assert len(items) == len(guide.step_sources)
    for item, step, (title, url) in zip(
        items, guide.text[locale].steps, guide.step_sources, strict=True
    ):
        assert html.escape(step, quote=True) in item
        assert "class='muted guide-step-source'" in item
        assert (
            f"<a href='{url}' rel='noopener noreferrer'>{html.escape(title, quote=True)}</a>"
            in item
        )
    assert find_claims(page) == []


@pytest.mark.parametrize(
    ("locale", "csv_gap", "filter_gap", "zone_gap", "mobile_gap", "affiliation"),
    (
        (
            "es",
            "no la cabecera exacta del CSV",
            "no dice si Statement respeta",
            "no especifica la zona horaria",
            "no documenta exportación",
            "Rigor no está afiliado a cTrader ni a Spotware",
        ),
        (
            "en",
            "not the exact CSV headers",
            "does not say whether Statement follows",
            "does not specify the exported file's time zone",
            "does not document export",
            "Rigor is not affiliated with cTrader or Spotware",
        ),
        (
            "pt",
            "não o cabeçalho exato do CSV",
            "não diz se Statement respeita",
            "não especifica o fuso horário",
            "não documenta exportação",
            "O Rigor não é afiliado ao cTrader nem à Spotware",
        ),
    ),
)
def test_ctrader_distinguishes_documented_export_from_its_unknowns(
    locale: str, csv_gap: str, filter_gap: str, zone_gap: str, mobile_gap: str, affiliation: str
) -> None:
    text = GUIDES_BY_SLUG["ctrader"].text[locale]
    steps = " ".join(text.steps)
    tips = " ".join(text.tips)
    assert csv_gap in text.file
    assert filter_gap in steps and zone_gap in steps
    assert mobile_gap in tips and affiliation in tips
    assert all(name in text.file for name in ("Desktop", "Web", "Mac", "HTML", ".xlsx"))
    assert "Mobile" in tips and "Current time" in steps
    assert "prop firm" in tips or "prop-firm" in tips
    assert "NOT_MEASURED" in tips
    # These are History labels in a synthetic fixture, not a promised CSV header.
    report = import_report(
        (FIXTURES / "ctrader_history_columns.csv").read_bytes(),
        "ctrader_history_columns.csv",
        columns={"profit": "Gross (currency)"},
    )
    read = {value for key, value in report.metadata.items() if key.startswith("column_")}
    assert read
    for column in read:
        assert column in text.upload
    assert "profit" in text.upload and "Net" in text.upload and "Pips" in text.upload
