"""Export guides as the way in to the free report.

Every guide, in every language, says under its heading what the file is for,
lists what the report does with that file type (each point backed by the code
that does it, ``audit/guide_capabilities.py``) and what the visitor gets, with
the free report worded as the configuration offers it. What the guides already
rank with (title, description, heading, address, language links and the
structured data) stays as main rendered it: ``tests/golden/guide_seo_main_027c500.json``
was written from main at 027c500 before this change, by rendering every guide
with ``pages.guide_page(guide, locale=..., base_url=BASE)``.

Only the indexed parts of each frozen ``head_meta`` are compared (``<title>``,
the description, ``og:title``, ``og:description``, ``og:url``, the canonical
link and the hreflang links, see ``_INDEXED_HEAD``), with the H1 and the
JSON-LD, so a change to the head every page shares (theme colour, image,
robots) does not touch this test, and a guide added later is simply not in the
golden. To freeze a deliberate change to those parts, write the file again the
same way from the commit that makes it, under a name with that commit's hash:
``{"<slug>:<locale>": {"path": guide_url(slug, locale), "head_meta": the page
before "<style>", "h1": [...], "json_ld": [...]}}``.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_forward import _back  # noqa: E402
from test_audit_forward import _export as _forward_export  # noqa: E402
from test_audit_tracking_exports import MQL5_HISTORY, _fxblue, _myfxbook  # noqa: E402

from quant_trade.audit import accounts, decay  # noqa: E402
from quant_trade.audit.account import ACCOUNT_FORMATS, account_review  # noqa: E402
from quant_trade.audit.account_pages import COPY as ACCOUNT_COPY  # noqa: E402
from quant_trade.audit.account_pages import report_contents  # noqa: E402
from quant_trade.audit.engine import (  # noqa: E402
    _NO_PRINTED_BALANCE_REASON,
    _SUMMARY_BALANCE_FORMATS,
    MEASURED,
    _reconciliation,
    trial_count,
)
from quant_trade.audit.forward import NOT_FORWARD, forward_review, is_forward  # noqa: E402
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
    CAPITAL_FROM_PERCENT_MIN,
    MT5_OPTIMIZATION_XML,
    MYFXBOOK_CSV,
    REPORT_FORMATS,
    UNIVERSAL_FILLS_CSV,
    OptimizationSummary,
    ReportFormatError,
    _capital_from_percent,
    import_report,
    optimization_mismatch,
    parse_optimization,
)
from quant_trade.audit.pages import (  # noqa: E402
    _COPY,
    ACCOUNT_GUIDES,
    AUDIT_PATHS,
    SAMPLE_PAGE_PATHS,
    guide_page,
)
from quant_trade.audit.plateau import FORWARD_EXPORT, METRICS, parameter_stability  # noqa: E402
from quant_trade.audit.pricing import PRICING_COPY, PRICING_PATH, offer_text  # noqa: E402
from quant_trade.audit.report import localize_tags  # noqa: E402
from quant_trade.audit.sample import synthetic_live_statement  # noqa: E402
from quant_trade.audit.schema import DeclaredMetadata, build_inputs, parse_equity_csv  # noqa: E402
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
    assert field_value("number:importers:CAPITAL_FROM_PERCENT_MIN", "es") == "1"
    assert [field_value("parts:decay:RECENT_SHARE", locale) for locale in LOCALES] == [
        "tres",
        "three",
        "três",
    ]
    # The form's own labels, without "(recommended)" or "(optional)".
    assert field_value("form:report", "es") == "Informe de tu plataforma"
    assert field_value("form:live", "en") == "Live or demo account statement"
    for locale in LOCALES:
        assert field_value("form:report", locale) in _COPY[locale]["report"]
    with pytest.raises(KeyError):
        field_value("flag:NO_SUCH_FLAG", "es")
    with pytest.raises(AttributeError):
        resolve("engine:no_such_function")


def test_a_guide_only_lists_points_about_its_own_files() -> None:
    for slug, keys in GUIDE_CAPABILITIES.items():
        for key in keys:
            assert CAPABILITIES[key].formats & GUIDE_FORMATS[slug], (slug, key)
    # Account points are about account histories only, as the engine defines them.
    for key in ("account_money", "top_up", "history_money", "floating_end", "myfxbook_floating"):
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
        if fmt in CAPABILITIES["myfxbook_floating"].formats:
            # The sample's export holds an "Open Trades" block and a deposit.
            assert {"declared_floating_pnl", "declared_balance"} <= set(imported.metadata), name
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
    texts += [GUIDES_COPY[locale]["free_terms"] for locale in LOCALES]
    texts += [
        GUIDES_COPY[locale]["paid_terms"].format(n=accounts.FREE_PREVIEWS_PER_MONTH)
        for locale in LOCALES
    ]
    texts += [
        GUIDES_COPY[locale]["optimization_with_report"].format(upload=GUIDES_COPY[locale]["upload"])
        for locale in LOCALES
    ]
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


#: What a search engine reads from a guide's head. The rest of the head is the
#: one every page shares (theme colour, image, robots), not the guide's.
_INDEXED_HEAD = (
    r"<title>.*?</title>",
    r"<meta name='description' content='[^']*'>",
    r"<meta property='og:(?:title|description|url)' content='[^']*'>",
    r"<link rel='canonical' href='[^']*'>",
    r"<link rel='alternate' hreflang='[^']*' href='[^']*'>",
)
_PARTS = ("head", "h1", "json_ld")


def _indexed_head(markup: str) -> list[str]:
    head = markup.split("</head>", 1)[0]
    return [found for pattern in _INDEXED_HEAD for found in re.findall(pattern, head, flags=re.S)]


def _snapshot(page: str) -> dict[str, object]:
    return {
        "head": _indexed_head(page),
        "h1": re.findall(r"<h1[^>]*>.*?</h1>", page, flags=re.S),
        "json_ld": re.findall(
            r"<script type=.application/ld\+json.>.*?</script>", page, flags=re.S
        ),
    }


def _frozen(entry: dict[str, object]) -> dict[str, object]:
    head = _indexed_head(str(entry["head_meta"]))
    return {"head": head, "h1": entry["h1"], "json_ld": entry["json_ld"]}


def test_title_description_heading_address_and_languages_stay_as_on_main(
    tmp_path: Path,
) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    # A guide added after the golden is not in it; one in it cannot vanish unnoticed.
    assert set(golden) <= {f"{guide.slug}:{locale}" for guide in GUIDES for locale in LOCALES}
    indexed = ("<title>", "name='description'", "og:url", "canonical", "hreflang='x-default'")
    for key, entry in golden.items():
        head = " ".join(_indexed_head(str(entry["head_meta"])))
        for part in indexed:
            assert part in head, (key, part)
    client = _client(tmp_path)
    checked = 0
    for slug, locale, page in _pages(client):
        if f"{slug}:{locale}" not in golden:
            continue
        entry = golden[f"{slug}:{locale}"]
        assert guide_url(slug, locale) == entry["path"]
        current, frozen = _snapshot(page), _frozen(entry)
        for part in _PARTS:
            assert current[part] == frozen[part], (slug, locale, part)
        checked += 1
    assert checked == len(golden)
    # Whatever the offer, the indexed parts do not move.
    for guide in GUIDES:
        for locale in LOCALES:
            if f"{guide.slug}:{locale}" not in golden:
                continue
            frozen = _frozen(golden[f"{guide.slug}:{locale}"])
            for offer, verification in (("welcome", True), ("paid", False), ("free", True)):
                page = guide_page(
                    guide,
                    locale=locale,
                    base_url=BASE,
                    offer=offer,
                    email_verification=verification,
                )
                current = _snapshot(page)
                for part in _PARTS:
                    assert current[part] == frozen[part], (guide.slug, locale, offer, part)


def _offer_block(client: TestClient, locale: str = "es", slug: str = "mt5") -> str:
    page = client.get(guide_url(slug, locale)).text
    return _section(page, GUIDES_COPY[locale]["get"])


def _has(block: str, text: str) -> bool:
    return html.escape(text, quote=True) in block


@pytest.mark.parametrize("locale", LOCALES)
def test_the_free_report_line_follows_the_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    pricing = PRICING_COPY[locale]
    account = ACCOUNT_COPY[locale]
    words = GUIDES_COPY[locale]
    has = _has

    (tmp_path / "free").mkdir()
    free = _offer_block(_client(tmp_path / "free"), locale)
    assert has(free, pricing["start_text_free"])
    assert not has(free, account["next_free_welcome"]) and not has(free, pricing["start_text"])
    assert not has(free, words["free_terms"])

    (tmp_path / "welcome").mkdir()
    welcome = _offer_block(_client(tmp_path / "welcome", free_mode=False), locale)
    assert has(welcome, account["next_free_welcome"]) and has(welcome, pricing["start_text"])
    assert not has(welcome, pricing["email_note"]) and not has(welcome, pricing["start_text_free"])
    # "The first one is free" comes with the limits the upload applies to it.
    first_free = f"{account['next_free_welcome']} {words['free_terms']}"
    assert has(welcome, first_free)

    (tmp_path / "verify").mkdir()
    verify = _offer_block(
        _client(tmp_path / "verify", free_mode=False, email_verification_required=True), locale
    )
    assert has(verify, offer_text("welcome", locale, email_verification=True))
    assert has(verify, pricing["email_note"]) and has(verify, first_free)

    monkeypatch.setattr(accounts, "WELCOME_FULL_REPORT", False)
    (tmp_path / "paid").mkdir()
    paid = _offer_block(_client(tmp_path / "paid", free_mode=False), locale)
    for text in (
        pricing["start_text"],
        pricing["start_text_free"],
        account["next_free_welcome"],
        account["next_free_all"],
        words["free_terms"],
        # Without a free report, "You get ... and the PDF" would not hold: a preview.
        report_contents(locale, ""),
    ):
        assert not has(paid, text), text
    assert has(paid, words["paid_terms"].format(n=accounts.FREE_PREVIEWS_PER_MONTH))
    assert f"href='{PRICING_PATH[locale]}'" in paid
    assert len({free, welcome, verify, paid}) == 4
    for block in (free, welcome, verify, paid):
        assert find_claims(_visible(block)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_optimisation_guide_says_the_xml_goes_with_a_report(
    tmp_path: Path, locale: str
) -> None:
    words = GUIDES_COPY[locale]
    pricing = PRICING_COPY[locale]
    with_report = words["optimization_with_report"].format(upload=words["upload"])
    # The XML alone is refused as the report: it only goes next to one.
    with pytest.raises(ReportFormatError):
        import_report((FIXTURES / "mt5_optimization.xml").read_bytes(), "ReportOptimizer.xml")
    (tmp_path / "free").mkdir()
    client = _client(tmp_path / "free")
    free = _offer_block(client, locale, "mt5-optimization")
    assert _has(free, with_report) and _has(free, pricing["free"])
    assert not _has(free, pricing["start_text_free"])  # "you only need the file"
    assert not _has(_offer_block(client, locale, "mt5"), with_report)
    # The section the sentence points to is on the page.
    page = client.get(guide_url("mt5-optimization", locale)).text
    assert f">{html.escape(words['upload'], quote=True)}</h2>" in page
    (tmp_path / "welcome").mkdir()
    welcome = _offer_block(
        _client(tmp_path / "welcome", free_mode=False), locale, "mt5-optimization"
    )
    assert _has(welcome, with_report) and _has(welcome, pricing["start_text"])
    assert find_claims(_visible(free + welcome)) == []


def test_vectorbt_variants_in_the_csv_count_as_trials_as_the_guide_says() -> None:
    lines = (FIXTURES / "vectorbt_trades.csv").read_text(encoding="utf-8").splitlines()
    other = [line.replace("BTC-USD", "ETH-USD") for line in lines[1:]]
    data = ("\n".join([*lines, *other]) + "\n").encode("utf-8")
    inputs = build_inputs(
        None,
        DeclaredMetadata(trials_declared=False),
        report_bytes=data,
        report_filename="trades.csv",
    )
    assert inputs.report_variants == 2
    assert trial_count(inputs)[:2] == (2, MEASURED)
    guide = next(guide for guide in GUIDES if guide.slug == "vectorbt")
    for locale in LOCALES:
        tips = " ".join(guide.text[locale].tips)
        # The tip says what the code does: the variants count, the matrix adds the PBO.
        assert "PBO" in tips, locale
        assert "PBO" in capability_text("variants_matrix", locale), locale


def test_myfxbook_floating_needs_the_open_trades_block_and_a_deposit() -> None:
    data = _myfxbook().decode("utf-8")

    def review(text: str) -> dict[str, Any]:
        imported = import_report(text.encode("utf-8"), "statement.csv")
        assert imported.source_format == MYFXBOOK_CSV
        result, _ = account_review(
            source_format=imported.source_format,
            cash_flows=imported.cash_flows,
            trades=imported.trades,
            frame=parse_equity_csv(imported.equity_csv, what="report").frame,
            metadata=imported.metadata,
        )
        return result

    assert review(data)["floating_share"]["evidence"] == "DECLARED"
    # Without the "Open Trades" block there is no floating result to read.
    closed_only = review(data.split("\nOpen Trades", 1)[0] + "\n")
    assert closed_only["floating_pnl"]["evidence"] == "NOT_MEASURED"
    # Without a deposit or withdrawal the balance it compares with is not stated.
    flows = (",Deposit,", ",Withdrawal,")
    no_flows = "\n".join(line for line in data.splitlines() if not any(f in line for f in flows))
    flowless = review(no_flows + "\n")
    assert flowless["floating_pnl"]["evidence"] == "DECLARED"
    assert flowless["floating_share"]["evidence"] == "NOT_MEASURED"
    myfxbook = next(guide for guide in GUIDES if guide.slug == "myfxbook")
    for locale in LOCALES:
        assert "Open Trades" in capability_text("myfxbook_floating", locale), locale
        assert "Open Trades" in " ".join(myfxbook.text[locale].tips), locale


def test_the_plateau_and_the_forward_check_need_different_exports() -> None:
    main = parse_optimization((FIXTURES / "mt5_optimization.xml").read_bytes())
    forward = parse_optimization(_forward_export(_back))
    assert not is_forward(main.table) and is_forward(forward.table)
    plateau_on_forward, _ = parameter_stability(
        forward.table, forward.parameters, report_inputs=None
    )
    assert plateau_on_forward == {"status": "NOT_MEASURED", "reason": FORWARD_EXPORT}
    forward_on_main, _ = forward_review(main.table, main.parameters, report_inputs=None)
    assert forward_on_main == {"status": "NOT_MEASURED", "reason": NOT_FORWARD}
    measured, _ = forward_review(forward.table, forward.parameters, report_inputs=None)
    assert measured["status"] == "MEASURED"
    # The plateau reads the Profit column only, as the point says.
    assert METRICS == ("Profit",)
    for locale in LOCALES:
        assert "Profit" in capability_text("plateau", locale)
        assert field_value("label:plateau", locale) in capability_text("forward", locale)


def test_the_same_test_check_only_compares_what_both_files_state() -> None:
    summary = OptimizationSummary(
        source_format=MT5_OPTIMIZATION_XML,
        passes=25,
        parameters=["FastMA", "SlowMA"],
        warnings=[],
        expert="MyEA",
        symbol="EURUSD",
        timeframe="H1",
    )
    same = {"strategy": "MyEA", "symbol": "EURUSD.m", "period": "H1 (2024.01.01 - 2024.06.30)"}

    def differs(report: dict[str, str]) -> str | None:
        found = optimization_mismatch(summary, report)
        return found[0] if found else None

    # One input in common is enough, and the values are not compared.
    assert differs({**same, "input_names": "FastMA,Lots"}) is None
    assert differs({}) is None  # a report that states nothing
    assert differs({**same, "input_names": "Lots,Risk"}) == "inputs"
    assert differs({**same, "strategy": "Other"}) == "robot"
    assert differs({**same, "period": "M5"}) == "timeframe"


def test_futures_point_values_only_without_a_result_or_multiplier_column() -> None:
    header = "Account,B/S,Contract,avgPrice,filledQty,Fill Time"
    rows = [
        "ACC1,Buy,FDAXZ6,24000.0,1,09/21/2026 09:30:00",
        "ACC1,Sell,FDAXZ6,24010.0,1,09/21/2026 09:45:00",
    ]
    priced = import_report(("\n".join([header, *rows]) + "\n").encode(), "fills.csv")
    assert [round(t.pnl, 2) for t in priced.trades.trades] == [250.0]
    assert any("point value: FDAX x25 EUR" in warning for warning in priced.warnings)
    sized = import_report(
        ("\n".join([f"{header},Multiplier", *(f"{row},5" for row in rows)]) + "\n").encode(),
        "fills.csv",
    )
    assert [round(t.pnl, 2) for t in sized.trades.trades] == [50.0]
    assert not any("point value:" in warning for warning in sized.warnings)
    for locale in LOCALES:
        assert "ESZ6" in capability_text("futures_point", locale)


def test_no_printed_balance_only_when_the_csv_is_the_main_report() -> None:
    alone = build_inputs(
        None, DeclaredMetadata(), report_bytes=_myfxbook(), report_filename="statement.csv"
    )
    assert _reconciliation(alone)[0]["reason"] == _NO_PRINTED_BALANCE_REASON
    # Next to a backtest, the reconciliation is the backtest's own.
    paired = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=(FIXTURES / "mt5_tester.html").read_bytes(),
        report_filename="mt5_tester.html",
        live_bytes=_myfxbook(),
        live_filename="statement.csv",
    )
    recon, _ = _reconciliation(paired)
    assert recon.get("reason") != _NO_PRINTED_BALANCE_REASON
    assert recon["status"] in {"MATCH", "CONTRADICTION"}
    for locale in LOCALES:
        assert field_value("form:report", locale) in capability_text("no_printed_balance", locale)
        assert field_value("form:live", locale) in capability_text("live_compare", locale)


def test_the_figures_in_the_points_follow_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    # The starting capital is only worked out from a percentage of at least the constant.
    assert _capital_from_percent(100.0, CAPITAL_FROM_PERCENT_MIN * 0.99) is None
    assert _capital_from_percent(100.0, CAPITAL_FROM_PERCENT_MIN) == pytest.approx(
        100.0 / (CAPITAL_FROM_PERCENT_MIN / 100.0)
    )
    monkeypatch.setattr(decay, "RECENT_SHARE", 1 / 4)
    assert field_value("parts:decay:RECENT_SHARE", "es") == "cuatro"
    # A share that cuts no whole number of parts refuses rather than says "three".
    monkeypatch.setattr(decay, "RECENT_SHARE", 0.3)
    with pytest.raises(ValueError):
        capability_text("recent_fade", "es")
