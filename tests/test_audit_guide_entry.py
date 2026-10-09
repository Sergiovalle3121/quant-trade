"""Export guides as the way in to the free report.

Every guide, in every language, says under its heading what the file is for,
lists what the report does with that file type (each point backed by the code
that does it, ``audit/guide_capabilities.py``) and what the visitor gets, with
the free report worded as the configuration offers it. What the guides already
rank with (title, description, heading, address, language links and the
structured data) stays as main rendered it: ``tests/golden/guide_seo_main_027c500.json``
was written from main at 027c500 before this change, by rendering every guide
with ``pages.guide_page(guide, locale=..., base_url=BASE)``.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_tracking_exports import MQL5_HISTORY, _fxblue  # noqa: E402

from quant_trade.audit import accounts  # noqa: E402
from quant_trade.audit.account import ACCOUNT_FORMATS  # noqa: E402
from quant_trade.audit.account_pages import COPY as ACCOUNT_COPY  # noqa: E402
from quant_trade.audit.engine import _SUMMARY_BALANCE_FORMATS  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guide_capabilities import (  # noqa: E402
    CAPABILITIES,
    GUIDE_CAPABILITIES,
    GUIDE_FORMATS,
    GUIDE_PURPOSE,
    GUIDE_TOOL,
    NO_BALANCE_FORMATS,
    PRINTED_BALANCE_FORMATS,
    capability_text,
    field_value,
    guide_points,
    resolve,
)
from quant_trade.audit.guides import GUIDES, GUIDES_COPY, guide_url  # noqa: E402
from quant_trade.audit.importers import (  # noqa: E402
    MT5_OPTIMIZATION_XML,
    REPORT_FORMATS,
    UNIVERSAL_FILLS_CSV,
    import_report,
    parse_optimization,
)
from quant_trade.audit.pages import (  # noqa: E402
    ACCOUNT_GUIDES,
    AUDIT_PATHS,
    SAMPLE_PAGE_PATHS,
    guide_page,
)
from quant_trade.audit.pricing import PRICING_COPY, PRICING_PATH, offer_text  # noqa: E402
from quant_trade.audit.report import localize_tags  # noqa: E402
from quant_trade.audit.sample import synthetic_live_statement  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
GOLDEN = Path(__file__).parent / "golden" / "guide_seo_main_027c500.json"
FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
ZERODHA = (
    b"symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,"
    b"trade_id,order_id,order_execution_time\n"
    b"INFY,INE009A01021,2024-01-02,NSE,EQ,EQ,buy,false,10,1500,1001,2001,2024-01-02T09:30:00\n"
    b"INFY,INE009A01021,2024-01-02,NSE,EQ,EQ,sell,false,10,1550,1002,2002,2024-01-02T14:30:00\n"
)


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url=BASE,
        **overrides,  # type: ignore[arg-type]
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _visible(markup: str) -> str:
    markup = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", markup, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _section(page: str, heading: str) -> str:
    """One doc section of a guide: from its heading to the next one or the article's end."""
    start = page.index(f">{html.escape(heading, quote=True)}</h2>")
    ends = [i for i in (page.find("<h2 ", start), page.find("</article>", start)) if i > 0]
    return page[start : min(ends)]


def _new_blocks(page: str, locale: str) -> str:
    words = GUIDES_COPY[locale]
    return _section(page, words["does"]) + _section(page, words["get"])


def _hrefs(markup: str) -> list[str]:
    return [html.unescape(href) for href in re.findall(r"href='([^']*)'", markup)]


def _pages(client: TestClient) -> Iterator[tuple[str, str, str]]:
    for guide in GUIDES:
        for locale in LOCALES:
            response = client.get(guide_url(guide.slug, locale))
            assert response.status_code == 200, (guide.slug, locale)
            yield guide.slug, locale, response.text


def test_every_guide_has_a_purpose_a_tool_and_two_to_four_points() -> None:
    slugs = {guide.slug for guide in GUIDES}
    for table in (GUIDE_CAPABILITIES, GUIDE_FORMATS, GUIDE_PURPOSE, GUIDE_TOOL):
        assert set(table) == slugs
    for slug, keys in GUIDE_CAPABILITIES.items():
        assert 2 <= len(keys) <= 4, slug
        assert len(set(keys)) == len(keys), slug
        assert set(keys) <= set(CAPABILITIES), slug
        assert set(GUIDE_PURPOSE[slug]) == set(LOCALES), slug
        assert GUIDE_TOOL[slug] in {"calculator", "winrate"}, slug
    # Every point is used by some guide: none is kept around unchecked.
    assert {key for keys in GUIDE_CAPABILITIES.values() for key in keys} == set(CAPABILITIES)


def test_every_point_names_code_and_keys_that_exist() -> None:
    known_formats = {*REPORT_FORMATS, MT5_OPTIMIZATION_XML}
    for key, capability in CAPABILITIES.items():
        assert capability.sources, key
        for source in capability.sources:
            assert ":" in source, (key, source)
            assert resolve(source) is not None, (key, source)
        assert capability.formats and capability.formats <= known_formats, key
        assert set(capability.text) == set(LOCALES), key
        names = {
            locale: set(re.findall(r"\{(\w+)\}", capability.text[locale])) for locale in LOCALES
        }
        assert names["es"] == names["en"] == names["pt"] == set(capability.fields), key
        for locale in LOCALES:
            for spec in capability.fields.values():
                assert field_value(spec, locale).strip(), (key, spec, locale)
            text = capability_text(key, locale)
            assert "{" not in text and "}" not in text, (key, locale)
            assert find_claims(text) == [], (key, locale, text)
    # The figures and names come from the code, in the page's typography.
    assert field_value("pct:account:TOP_UP_DRAWDOWN", "es") == "20 %"
    assert field_value("times:costs:DEFAULT_MULTIPLIERS", "en") == "0, 1, 2 and 3"
    assert field_value("number:costs:REFERENCE_BPS_OVER_REPORTED_FEES", "es") == "0,5"
    assert field_value("number:costs:REFERENCE_BPS_OVER_REPORTED_FEES", "en") == "0.5"
    assert field_value("label:account", "pt") == "O dinheiro real da conta"
    with pytest.raises(KeyError):
        field_value("flag:NO_SUCH_FLAG", "es")
    with pytest.raises(AttributeError):
        resolve("engine:no_such_function")


def test_a_guide_only_lists_points_about_its_own_files() -> None:
    for slug, keys in GUIDE_CAPABILITIES.items():
        for key in keys:
            assert CAPABILITIES[key].formats & GUIDE_FORMATS[slug], (slug, key)
    # Account points are about account histories only, as the engine defines them.
    for key in ("account_money", "top_up", "history_money", "floating_end"):
        assert CAPABILITIES[key].formats <= ACCOUNT_FORMATS, key
    # A file with no printed balance never promises the balance comparison.
    assert not NO_BALANCE_FORMATS & PRINTED_BALANCE_FORMATS
    assert not NO_BALANCE_FORMATS & _SUMMARY_BALANCE_FORMATS
    for key in ("balance_rebuilt", "mt5_history_balance", "mt4_tester_balance"):
        assert CAPABILITIES[key].formats <= PRINTED_BALANCE_FORMATS, key
    for slug, formats in GUIDE_FORMATS.items():
        if formats <= NO_BALANCE_FORMATS:
            assert "no_printed_balance" in GUIDE_CAPABILITIES[slug], slug
            assert not {"balance_rebuilt", "mt5_history_balance"} & set(GUIDE_CAPABILITIES[slug])


def _samples() -> list[tuple[str, bytes, str]]:
    files = [
        ("mt5", "mt5_tester.html"),
        ("mt5", "mt5_history.html"),
        ("cuenta-proveedor", "mt5_history.html"),
        ("cuenta-proveedor", "mt4_statement.htm"),
        ("mt4", "mt4_tester.htm"),
        ("mt4", "mt4_statement.htm"),
        ("tradingview", "tradingview_g1.csv"),
        ("ninjatrader", "ninjatrader.csv"),
        ("quantconnect", "quantconnect_trades.csv"),
        ("backtesting-py", "backtestingpy_trades.csv"),
        ("vectorbt", "vectorbt_trades.csv"),
    ]
    samples = [(slug, (FIXTURES / name).read_bytes(), name) for slug, name in files]
    samples += [
        ("myfxbook", synthetic_live_statement(), "statement.csv"),
        ("mql5-signal", MQL5_HISTORY, "signal.csv"),
        ("fxblue", _fxblue(), "fxblue.csv"),
        ("zerodha", ZERODHA, "tradebook.csv"),
        ("csv-universal", ZERODHA, "fills.csv"),
    ]
    return samples


def test_the_guide_formats_and_the_balance_points_match_what_the_importers_do() -> None:
    for slug, data, name in _samples():
        imported = import_report(data, name)
        fmt = imported.source_format
        assert fmt in GUIDE_FORMATS[slug], (slug, name, fmt)
        # The balance points: a running balance on the rows, or none to compare with.
        printed = "reported_final_balance" in imported.metadata
        if fmt in PRINTED_BALANCE_FORMATS:
            assert printed, name
        if fmt in NO_BALANCE_FORMATS:
            assert not printed, name
        if fmt in CAPABILITIES["floating_end"].formats:
            assert "declared_floating_pnl" in imported.metadata, name
    assert import_report(ZERODHA, "tradebook.csv").source_format == UNIVERSAL_FILLS_CSV
    optimisation = parse_optimization((FIXTURES / "mt5_optimization.xml").read_bytes())
    assert optimisation.source_format == MT5_OPTIMIZATION_XML and optimisation.passes >= 1


def test_every_guide_page_answers_with_the_new_blocks(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for slug, locale, page in _pages(client):
        words = GUIDES_COPY[locale]
        purpose = GUIDE_PURPOSE[slug][locale]
        start = page.index("<section class='page-hero'>")
        hero = page[start : page.index("</section>", start)]
        assert f">{html.escape(purpose, quote=True)}</p>" in hero, (slug, locale)
        assert hero.index("</h1>") < hero.index(html.escape(purpose, quote=True))
        does = _section(page, words["does"])
        points = guide_points(slug, locale)
        assert does.count("<li>") == len(points), (slug, locale)
        for point in points:
            assert localize_tags(html.escape(point, quote=True), locale) in does, (slug, point)
        get = _section(page, words["get"])
        assert html.escape(words["upload_this"], quote=True) in get
        assert f"<a class='btn btn-dark' href='{AUDIT_PATHS[locale]}'>" in get
        assert f"href='{SAMPLE_PAGE_PATHS[locale]}'" in get
        # The guide's own index lists the two new sections.
        assert page.count("<li><a href='#s") == page.count("<h2 id='s") == 6
        assert find_claims(page) == [], (slug, locale)
        assert find_claims(_visible(page)) == [], (slug, locale)


def test_every_new_text_passes_the_guard() -> None:
    texts = [text for purposes in GUIDE_PURPOSE.values() for text in purposes.values()]
    texts += [capability_text(key, locale) for key in CAPABILITIES for locale in LOCALES]
    texts += [GUIDES_COPY[locale][key] for locale in LOCALES for key in ("does", "get", "tool")]
    texts += [GUIDES_COPY[locale]["upload_this"] for locale in LOCALES]
    for text in texts:
        assert text.strip() and find_claims(text) == [], text
        assert "verific" not in text.lower() and "certific" not in text.lower(), text
        assert "aprob" not in text.lower() and "garant" not in text.lower(), text
        assert "rentable" not in text.lower(), text


def test_new_internal_links_answer_200_and_none_is_external(tmp_path: Path) -> None:
    client = _client(tmp_path)
    seen: dict[str, int] = {}
    for slug, locale, page in _pages(client):
        links = _hrefs(_new_blocks(page, locale))
        start = page.index("<aside class='toc'")
        aside = page[start : page.index("</aside>", start)]
        links += _hrefs(aside)
        assert links, slug
        for link in links:
            if link.startswith("#"):
                continue
            assert link.startswith("/") and not link.startswith("//"), (slug, link)
            if link not in seen:
                seen[link] = client.get(link).status_code
            assert seen[link] == 200, (slug, locale, link)
    tools = {"/calculadora", "/calculator", "/pt/calculadora", "/calculadora-aciertos"}
    assert tools & set(seen)


def test_the_tool_fits_the_guide(tmp_path: Path) -> None:
    for slug in ACCOUNT_GUIDES | {"robinhood", "zerodha", "csv-universal"}:
        assert GUIDE_TOOL[slug] == "winrate", slug
    for slug in ("mt5", "mt5-optimization", "tradingview"):
        assert GUIDE_TOOL[slug] == "calculator", slug
    client = _client(tmp_path)
    for slug, locale, page in (
        ("myfxbook", "es", client.get(guide_url("myfxbook", "es")).text),
        ("mt5-optimization", "en", client.get(guide_url("mt5-optimization", "en")).text),
    ):
        get = _section(page, GUIDES_COPY[locale]["get"])
        wanted = {"winrate": "/calculadora-aciertos", "calculator": "/calculator"}[GUIDE_TOOL[slug]]
        assert f"href='{wanted}'" in get, slug


def _snapshot(page: str) -> dict[str, object]:
    head = page.split("</head>", 1)[0]
    return {
        "head_meta": head.split("<style>", 1)[0],
        "h1": re.findall(r"<h1[^>]*>.*?</h1>", page, flags=re.S),
        "json_ld": re.findall(
            r"<script type=.application/ld\+json.>.*?</script>", page, flags=re.S
        ),
    }


def test_title_description_heading_address_and_languages_stay_as_on_main(
    tmp_path: Path,
) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(golden) == len(GUIDES) * len(LOCALES)
    client = _client(tmp_path)
    for slug, locale, page in _pages(client):
        frozen = golden[f"{slug}:{locale}"]
        assert guide_url(slug, locale) == frozen["path"]
        current = _snapshot(page)
        for part in ("head_meta", "h1", "json_ld"):
            assert current[part] == frozen[part], (slug, locale, part)
    # Whatever the offer, the indexed parts do not move.
    for guide in GUIDES:
        for locale in LOCALES:
            frozen = golden[f"{guide.slug}:{locale}"]
            for offer, verification in (("welcome", True), ("paid", False), ("free", True)):
                page = guide_page(
                    guide,
                    locale=locale,
                    base_url=BASE,
                    offer=offer,
                    email_verification=verification,
                )
                current = _snapshot(page)
                for part in ("head_meta", "h1", "json_ld"):
                    assert current[part] == frozen[part], (guide.slug, locale, offer, part)


def _offer_block(client: TestClient, locale: str = "es") -> str:
    page = client.get(guide_url("mt5-optimization", locale)).text
    return _section(page, GUIDES_COPY[locale]["get"])


@pytest.mark.parametrize("locale", LOCALES)
def test_the_free_report_line_follows_the_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    pricing = PRICING_COPY[locale]
    account = ACCOUNT_COPY[locale]

    def has(block: str, text: str) -> bool:
        return html.escape(text, quote=True) in block

    (tmp_path / "free").mkdir()
    free = _offer_block(_client(tmp_path / "free"), locale)
    assert has(free, pricing["start_text_free"])
    assert not has(free, account["next_free_welcome"]) and not has(free, pricing["start_text"])

    (tmp_path / "welcome").mkdir()
    welcome = _offer_block(_client(tmp_path / "welcome", free_mode=False), locale)
    assert has(welcome, account["next_free_welcome"]) and has(welcome, pricing["start_text"])
    assert not has(welcome, pricing["email_note"]) and not has(welcome, pricing["start_text_free"])

    (tmp_path / "verify").mkdir()
    verify = _offer_block(
        _client(tmp_path / "verify", free_mode=False, email_verification_required=True), locale
    )
    assert has(verify, offer_text("welcome", locale, email_verification=True))
    assert has(verify, pricing["email_note"])

    monkeypatch.setattr(accounts, "WELCOME_FULL_REPORT", False)
    (tmp_path / "paid").mkdir()
    paid = _offer_block(_client(tmp_path / "paid", free_mode=False), locale)
    for text in (
        pricing["start_text"],
        pricing["start_text_free"],
        account["next_free_welcome"],
        account["next_free_all"],
    ):
        assert not has(paid, text), text
    assert f"href='{PRICING_PATH[locale]}'" in paid
    assert len({free, welcome, verify, paid}) == 4
    for block in (free, welcome, verify, paid):
        assert find_claims(_visible(block)) == []
