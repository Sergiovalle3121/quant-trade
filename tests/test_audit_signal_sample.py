"""The second public sample: a made-up signal, for whoever is about to copy one.

Its Myfxbook export comes from a fixed seed (``sample.SIGNAL_SEED``) and is read
by the production importer; every flag on its page comes from the current
engine, never from the page. Its three addresses (es/en/pt) follow /ejemplo:
the same route code, cache, synthetic-data notice, sign-up band, PDF route and
indexing, with the buyer's role declared. The pages that rank for signal
copiers, the account-export guides and the first sample link to it, and the
sitemap lists it with its own date. Every page is read over HTTP with
``TestClient``; nothing reaches the network.
"""

from __future__ import annotations

import csv
import html
import io
import re
import socket
from collections.abc import Iterator
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account, ownership, web  # noqa: E402
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.check import COPY as CHECK_COPY  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guide_capabilities import CAPABILITIES, GUIDE_FORMATS  # noqa: E402
from quant_trade.audit.guides import GUIDES, GUIDES_COPY, guide_url  # noqa: E402
from quant_trade.audit.importers import MYFXBOOK_CSV, import_report  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    AUDIT_PATHS,
    SAMPLE_PAGE_PATHS,
    SIGNAL_SAMPLE_BANNER,
    SIGNAL_SAMPLE_COPY,
    SIGNAL_SAMPLE_GUIDES,
)
from quant_trade.audit.pricing import PRICING_COPY  # noqa: E402
from quant_trade.audit.redflags import (  # noqa: E402
    GRID_FAIL_SHARE,
    HIGH_WINRATE,
    MARTINGALE_FAIL_INCREASE_SHARE,
    NO_STOP_LOSS_MULTIPLE,
    flag_title,
)
from quant_trade.audit.report import (  # noqa: E402
    SAMPLE_CTA_COPY,
    SAMPLE_CTA_CSS,
    render,
    sample_cta_band,
)
from quant_trade.audit.sample import (  # noqa: E402
    SIGNAL_DEPOSIT,
    SIGNAL_END,
    SIGNAL_FILENAME,
    SIGNAL_START,
    SIGNAL_SYMBOLS,
    SIGNAL_TOP_UP,
    SIGNAL_WITHDRAWAL,
    sample_result,
    signal_sample_result,
    synthetic_signal_statement,
)
from quant_trade.audit.seo import (  # noqa: E402
    CHECK_PATH,
    PUBLIC_PAGES,
    SIGNAL_SAMPLE_PATHS,
    SIGNAL_SAMPLE_PUBLISHED,
    page_lastmod,
    robots_txt,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402

LOCALES = ("es", "en", "pt")
BASE = "https://rigor.example"
#: The synthetic-data words of the notice, as /ejemplo says them.
SYNTHETIC = {"es": "datos sintéticos", "en": "synthetic data", "pt": "dados sintéticos"}
#: The open loss, in the words of the flag that reports it (FLOATING_LOSS_AT_END).
OPEN_LOSS = {"es": "pérdida abierta", "en": "open loss", "pt": "perda aberta"}
#: Endorsement and result words the new copy must never use, in any language.
ENDORSEMENT = re.compile(
    r"verifica|certifica|aprobad|aprovad|garant|rentab|rentáve|lucrativ|profitab|guarante"
    r"|certified|approved|verified",
    re.I,
)
#: The flags a copier needs to see on this account, and the level they come out
#: at with the current engine. None of them reaches FAIL, for reasons the data
#: and the thresholds give (``test_the_flags_that_stay_at_warn_say_why``).
EXPECTED_FLAGS = {
    "MARTINGALE_SIZING": "WARN",
    "GRID_AVERAGING": "WARN",
    "DEPOSIT_DURING_DRAWDOWN": "WARN",
    "FLOATING_LOSS_AT_END": "WARN",
    "GAIN_INFLATED_BY_FLOWS": "WARN",
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Only loopback: TestClient talks to the app in process."""
    original = socket.getaddrinfo

    def local_only(host: str, *args: Any, **kwargs: Any) -> Any:
        assert host in {"localhost", "127.0.0.1", "::1"}, host
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local_only)
    monkeypatch.setattr(
        "quant_trade.audit.market._download",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no market download")),
    )
    yield


@pytest.fixture
def pdf_pages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A stand-in PDF renderer: the page it was given, and a few fixed bytes per sample."""
    seen: list[str] = []

    def fake_pdf(page: str, **kwargs: Any) -> bytes:
        seen.append(page)
        return f"%PDF-1.4\n% rigor {kwargs.get('audit_id')} {kwargs.get('locale')}\n".encode()

    monkeypatch.setattr(web.pdf_lib, "available", lambda: True)
    monkeypatch.setattr(web.pdf_lib, "report_pdf", fake_pdf)
    return seen


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        base_url=BASE,
        free_mode=False,
        access_codes=True,
    )
    return TestClient(web.create_app(settings, make_store(settings.database_url)))


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _hrefs(fragment: str) -> list[str]:
    return [html.unescape(href) for href in re.findall(r"href='([^']*)'", fragment)]


def _between(page: str, start: str, end: str) -> str:
    assert start in page, start
    return page.split(start, 1)[1].split(end, 1)[0]


@cache
def _signal(locale: str = "es") -> dict[str, Any]:
    """The signal sample's result as stored (the flags do not depend on the resampling)."""
    return signal_sample_result(locale, bootstrap_samples=60).model_dump(mode="json")


# -- 1. The synthetic export -----------------------------------------------------------


def test_the_export_is_a_myfxbook_csv_the_importer_reads_as_it_is() -> None:
    data = synthetic_signal_statement()
    # The seed is fixed: the same bytes on every call and every process.
    assert data == synthetic_signal_statement()
    text = data.decode("utf-8")
    assert text.startswith("Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots")
    assert "\nOpen Trades\n" in text
    imported = import_report(data, SIGNAL_FILENAME)
    assert imported.source_format == MYFXBOOK_CSV
    assert not any("dropped" in warning for warning in imported.warnings)
    # About twelve months of a grid on two pairs.
    assert sorted(set(imported.symbols)) == sorted(SIGNAL_SYMBOLS)
    first = min(trade.entry_time for trade in imported.trades.trades)
    last = max(trade.exit_time for trade in imported.trades.trades)
    assert first.date().isoformat() >= SIGNAL_START and last.date().isoformat() <= SIGNAL_END
    assert (last - first).days >= 350
    assert len(imported.trades.trades) > 300
    # The first deposit, the top-up and the withdrawal, as Myfxbook lists them.
    amounts = [amount for _, amount in imported.cash_flows]
    assert amounts == [SIGNAL_DEPOSIT, SIGNAL_TOP_UP, -SIGNAL_WITHDRAWAL]
    # The positions still open: a floating loss the balance does not carry.
    assert float(imported.metadata["declared_floating_pnl"]) < 0
    # The file prints no balance: none is listed as declared by the platform.
    assert "declared_balance" not in imported.metadata


def test_the_report_declares_the_buyer_and_raises_the_flags_a_copier_needs() -> None:
    data = _signal()
    assert data["declared"]["ownership"]["value"] == "buyer"
    assert data["declared"]["ownership"]["evidence"] == "DECLARED"
    assert ownership.role_of(data) == ownership.BUYER
    assert data["inputs"]["source_format"] == MYFXBOOK_CSV
    raised = {flag["code"]: flag["severity"] for flag in data["red_flags"]}
    for code, severity in EXPECTED_FLAGS.items():
        assert raised.get(code) == severity, (code, raised)
    # The account figures behind them, as the report measures them.
    review = data["account"]
    assert review["status"] == "MEASURED"
    top_up = review["deposit_list"][0]
    assert top_up["top_up"] and top_up["amount"]["value"] == SIGNAL_TOP_UP
    assert top_up["drawdown"]["value"] <= -account.TOP_UP_DRAWDOWN
    assert review["floating_share"]["value"] <= -account.FLOATING_WARN
    assert review["floating_share"]["evidence"] == "DECLARED"
    # The percentage says the account grew; the money says trading lost.
    assert review["percent_gain"]["value"] >= account.INFLATED_MIN_GAIN
    assert review["trading_result"]["value"] <= 0
    # Besides those, the engine sees what any grid shows on a closed-trade curve.
    assert {"MANY_CONCURRENT_POSITIONS", "HIDDEN_FLOATING_DRAWDOWN"} <= set(raised)


def test_the_flags_that_stay_at_warn_or_do_not_come_out_say_why() -> None:
    """None of the expected flags is missing. What does not come out, and why."""
    raised = {flag["code"]: flag for flag in _signal()["red_flags"]}
    # MARTINGALE_SIZING stays at WARN: FAIL also needs most trades after a loss to be
    # larger than the losing trade, and the losing trade is a stopped basket's
    # largest entry, so the doubled next basket starts below it.
    assert raised["MARTINGALE_SIZING"]["value"] >= 1.6
    assert MARTINGALE_FAIL_INCREASE_SHARE > 0.5
    # GRID_AVERAGING stays at WARN: just under the FAIL share of trades added
    # against the position.
    assert raised["GRID_AVERAGING"]["value"] < GRID_FAIL_SHARE
    # FLOATING_LOSS_AT_END stays at WARN: the open loss is under the FAIL share of
    # the balance (account.FLOATING_FAIL).
    assert raised["FLOATING_LOSS_AT_END"]["value"] > -account.FLOATING_FAIL
    # Not raised: NEGATIVE_PAYOFF_HIGH_WINRATE (the win rate stays under
    # HIGH_WINRATE: in most baskets that add entries the first entry closes at a
    # loss, and every entry of a stopped basket does; a basket of one entry closes
    # in profit) and NO_STOP_EVIDENCE (the robot has a stop past its sixth entry,
    # so the worst loss stays under NO_STOP_LOSS_MULTIPLE times the average loss).
    imported = import_report(synthetic_signal_statement(), SIGNAL_FILENAME)
    pnl = [trade.pnl for trade in imported.trades.trades]
    losses = [-value for value in pnl if value < 0]
    assert sum(value > 0 for value in pnl) / len(pnl) <= HIGH_WINRATE
    baskets = _baskets()
    assert sum(len(basket) for basket in baskets) == len(pnl)
    added = [basket for basket in baskets if len(basket) > 1]
    first_lost = [basket for basket in added if basket[0] < 0]
    stopped = [basket for basket in added if max(basket) < 0]
    # Most of the baskets that add entries, not most of the baskets.
    assert len(added) < 2 * len(first_lost) < len(baskets)
    assert stopped and all(basket[0] > 0 for basket in baskets if len(basket) == 1)
    assert max(losses) / (sum(losses) / len(losses)) < NO_STOP_LOSS_MULTIPLE
    assert "NEGATIVE_PAYOFF_HIGH_WINRATE" not in raised
    assert "NO_STOP_EVIDENCE" not in raised


def _baskets() -> list[list[float]]:
    """The export's closed trades by basket (same close date and symbol), read with
    the csv module: each basket's results in the order its entries opened."""
    text = synthetic_signal_statement().decode("utf-8").split("\nOpen Trades", 1)[0]
    baskets: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row["Action"] in ("Buy", "Sell"):
            key = (row["Close Date"], row["Symbol"])
            baskets.setdefault(key, []).append((int(row["Ticket"]), float(row["Profit"])))
    return [[profit for _, profit in sorted(entries)] for entries in baskets.values()]


# -- 2. The three pages ----------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_each_page_answers_with_the_notice_the_role_and_no_claims(
    tmp_path: Path, locale: str, pdf_pages: list[str]
) -> None:
    client = _client(tmp_path)
    path = SIGNAL_SAMPLE_PATHS[locale]
    response = client.get(path)
    assert response.status_code == 200
    page = response.text
    shown = _visible(page)
    assert f"<html lang='{locale}'>" in page
    # The notice: first what the signal is, then the synthetic-data notice of /ejemplo.
    notice = SIGNAL_SAMPLE_BANNER[locale]
    assert f"<div class='notice'>{html.escape(notice, quote=True)}" in page
    first = notice.split(". ")[0]
    assert any(word in first for word in ("inventad", "made-up")) and SYNTHETIC[locale] in notice
    hero = _between(page, "<section class='report-hero'>", "</section>")
    order = [hero.index(mark) for mark in ("<div class='notice'>", "sample-cta no-print", "<h1")]
    assert order == sorted(order)
    # The role declared: a strategy the client bought or is about to buy or copy.
    assert ownership.choice_label("buyer", locale) in shown
    # Indexed as the first sample, with its own address in each language.
    assert "<meta name='robots' content='index, follow'>" in page
    assert f"<link rel='canonical' href='{BASE}{path}'>" in page
    for lang, other in SIGNAL_SAMPLE_PATHS.items():
        assert f"<link rel='alternate' hreflang='{lang}' href='{BASE}{other}'>" in page
    words = SIGNAL_SAMPLE_COPY[locale]
    assert f"<meta property='og:description' content='{html.escape(words['description'])}'" in page
    # The band names the account exports that give this report.
    band = _between(page, "<div class='sample-cta no-print'>", "</div>")
    assert _hrefs(band) == [
        AUDIT_PATHS[locale],
        guide_url("myfxbook", locale),
        guide_url("mql5-signal", locale),
        guide_url("fxblue", locale),
    ]
    links = _between(page, "<nav class='report-languages'", "</nav>")
    assert _hrefs(links) == [SIGNAL_SAMPLE_PATHS[lang] for lang in LOCALES if lang != locale]
    assert f" · {web.SIGNAL_SAMPLE_PDF_NAMES[locale]}</title>" in page
    assert find_claims(page) == [] and find_claims(shown) == []
    assert find_claims(html.unescape(page)) == []
    for href in _hrefs(band) + _hrefs(links):
        assert client.get(href).status_code == 200, href


def test_the_pages_are_built_once_and_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []

    def counted(locale: str, **kwargs: Any) -> Any:
        built.append(locale)
        return signal_sample_result(locale, bootstrap_samples=60, **kwargs)

    monkeypatch.setattr(web, "signal_sample_result", counted)
    client = _client(tmp_path)
    first = client.get(SIGNAL_SAMPLE_PATHS["en"]).text
    assert client.get(SIGNAL_SAMPLE_PATHS["en"]).text == first
    assert built == ["en"]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_signal_sample_has_its_pdf_by_the_same_route(
    tmp_path: Path, locale: str, pdf_pages: list[str]
) -> None:
    client = _client(tmp_path)
    page = client.get(SIGNAL_SAMPLE_PATHS[locale]).text
    pdf = web.SIGNAL_SAMPLE_PDF_PATHS[locale]
    assert pdf == f"{SIGNAL_SAMPLE_PATHS[locale]}.pdf"
    block = _between(page, "<section class='rsec no-print sample-check'>", "</section>")
    assert _hrefs(block) == [pdf, CHECK_PATH[locale]]
    download = client.get(pdf)
    assert download.status_code == 200 and download.content.startswith(b"%PDF")
    name = web.SIGNAL_SAMPLE_PDF_NAMES[locale]
    assert download.headers["content-disposition"] == f'attachment; filename="rigor-{name}.pdf"'
    # The PDF carries the notice and none of the page's sign-up additions.
    assert pdf_pages and html.escape(SIGNAL_SAMPLE_BANNER[locale], quote=True) in pdf_pages[-1]
    assert "sample-cta" not in pdf_pages[-1] and "sample-check" not in pdf_pages[-1]
    # /comprobar answers that it is Rigor's sample report, unchanged.
    checked = client.post(
        CHECK_PATH[locale],
        files={"report": (f"rigor-{name}.pdf", download.content, "application/pdf")},
        data={"lang": locale},
    )
    assert checked.status_code == 200
    assert CHECK_COPY[locale]["sample"] in html.unescape(checked.text)


# -- 3. The links to it ----------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_signal_copiers_main_button_opens_the_signal_sample(tmp_path: Path, locale: str) -> None:
    client = _client(tmp_path)
    page = client.get(audience_url("copiar-senales", locale)).text
    signal = SIGNAL_SAMPLE_PATHS[locale]
    words = SIGNAL_SAMPLE_COPY[locale]
    lead = _between(page, "<div class='hero-cta'>", "</div>")
    assert lead.startswith(f"<a class='btn btn-dark' href='{signal}'>{html.escape(words['link'])}")
    # Starting is still there, right after it, and in the price section and the index.
    assert f"<a class='link-more' href='{AUDIT_PATHS[locale]}'>" in lead
    price = _between(page, "<div class='aud-price'>", "</div></div>")
    assert f"<a class='btn btn-dark' href='{AUDIT_PATHS[locale]}'>" in price
    assert f"<a class='link-more' href='{signal}'>" in price
    assert f"class='btn btn-dark btn-sm toc-cta' href='{AUDIT_PATHS[locale]}'" in page
    assert find_claims(page) == []
    assert client.get(signal).status_code == 200
    # The other cases keep their start button first and the first sample.
    for audience in AUDIENCE_PAGES:
        if audience.sample == "signal" or audience.contact_cta:
            continue
        other = client.get(audience_url(audience.slug, locale)).text
        first_button = _between(other, "<div class='hero-cta'>", "</div>")
        assert first_button.startswith(f"<a class='btn btn-dark' href='{AUDIT_PATHS[locale]}")
        assert signal not in other


def _get_section(page: str, locale: str) -> str:
    heading = f">{html.escape(GUIDES_COPY[locale]['get'], quote=True)}</h2>"
    start = page.index(heading)
    ends = [i for i in (page.find("<h2 ", start), page.find("</article>", start)) if i > 0]
    return page[start : min(ends)]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_account_export_guides_link_it_in_what_you_get(tmp_path: Path, locale: str) -> None:
    client = _client(tmp_path)
    signal = SIGNAL_SAMPLE_PATHS[locale]
    words = SIGNAL_SAMPLE_COPY[locale]
    assert {"myfxbook", "mql5-signal", "fxblue"} == set(SIGNAL_SAMPLE_GUIDES)
    for guide in GUIDES:
        get = _get_section(client.get(guide_url(guide.slug, locale)).text, locale)
        # Every guide keeps the first sample.
        assert f"href='{SAMPLE_PAGE_PATHS[locale]}'" in get
        sample = html.escape(PRICING_COPY[locale]["start_sample"])
        if guide.slug in SIGNAL_SAMPLE_GUIDES:
            assert f"{sample}</a> · <a href='{signal}'>{html.escape(words['link'])}</a>" in get
            assert find_claims(get) == []
        else:
            assert signal not in get
    assert client.get(signal).status_code == 200


@pytest.mark.parametrize("locale", LOCALES)
def test_the_first_sample_only_gains_the_link_to_the_signal_sample(
    tmp_path: Path, locale: str
) -> None:
    words = SAMPLE_CTA_COPY[locale]
    signal = SIGNAL_SAMPLE_PATHS[locale]
    link = (
        f"<p class='sample-cta-files'>{html.escape(words['other_signal'])} "
        f"<a href='{signal}'>{html.escape(words['other_signal_link'])}</a>.</p>"
    )
    for offer in ("welcome", "free", "paid"):
        band = sample_cta_band(locale, offer)
        assert band.count(link) == 1 and band.endswith(f"{link}</div>")
        # Without the new line the band is the one /ejemplo had.
        before = (
            f"<div class='sample-cta no-print'><style>{SAMPLE_CTA_CSS}</style>"
            f"<p><b>{html.escape(words['lead_' + offer])}</b></p>"
            f"<a class='btn btn-primary btn-sm' href='{AUDIT_PATHS[locale]}'>"
            f"{html.escape(words['button_' + offer])}</a>"
            f"<p class='sample-cta-files'>{html.escape(words['files'])} "
            f"<a href='{guide_url('mt5', locale)}'>{html.escape(words['mt5'])}</a> "
            f"{html.escape(words['joint'])} <a href='{guide_url('mt5-optimization', locale)}'>"
            f"{html.escape(words['optimization'])}</a>.</p></div>"
        )
        assert band.replace(link, "", 1) == before
    # The first sample renders as before: its kind is the default one.
    result = sample_result(locale, bootstrap_samples=60)
    default, _ = render(result, watermark=False, locale=locale, sample_cta=True)
    backtest, _ = render(
        result, watermark=False, locale=locale, sample_cta=True, sample_kind="backtest"
    )
    assert default == backtest and link in default
    # Over HTTP: the link is there, resolves, and nothing of the signal sample leaks in.
    client = _client(tmp_path)
    page = client.get(SAMPLE_PAGE_PATHS[locale]).text
    band = _between(page, "<div class='sample-cta no-print'>", "</div>")
    assert _hrefs(band)[-1] == signal
    assert html.escape(SIGNAL_SAMPLE_BANNER[locale], quote=True) not in page
    assert guide_url("myfxbook", locale) not in band
    for text in (words["other_signal"], words["other_signal_link"]):
        assert find_claims(text) == [] and ENDORSEMENT.search(text) is None
    assert client.get(signal).status_code == 200


@pytest.mark.parametrize("locale", LOCALES)
def test_the_band_promises_the_open_loss_only_with_the_export_that_lists_it(
    locale: str,
) -> None:
    """Of the three exports the band names, only Myfxbook's lists the open positions
    (its "Open Trades" block): the band says what the other two leave out."""
    open_loss = OPEN_LOSS[locale]
    assert flag_title("FLOATING_LOSS_AT_END", locale).lower().startswith(open_loss)
    reads_open = frozenset[str]().union(
        *(
            capability.formats
            for capability in CAPABILITIES.values()
            if capability.fields.get("flag") == "flag:FLOATING_LOSS_AT_END"
        )
    )
    with_open = {slug for slug in SIGNAL_SAMPLE_GUIDES if GUIDE_FORMATS[slug] & reads_open}
    assert with_open == {"myfxbook"}
    others = [guide_url(slug, locale) for slug in ("mql5-signal", "fxblue")]
    for offer in ("welcome", "free", "paid"):
        band = sample_cta_band(locale, offer, kind="signal")
        files = _between(band, "<p class='sample-cta-files'>", "</p>")
        # The sentence with Myfxbook names only it; the next one names the other two
        # and says the open loss is what their report leaves out.
        first, rest = files.split(f"href='{guide_url('myfxbook', locale)}'>", 1)[1].split(". ", 1)
        assert not any(href in first for href in others)
        assert all(href in rest for href in others)
        assert open_loss in html.unescape(rest)
        assert find_claims(html.unescape(files)) == []
    # The guides' link to the sample promises no flag; its description, which names
    # the open loss, says the export is Myfxbook's.
    words = SIGNAL_SAMPLE_COPY[locale]
    assert open_loss not in words["link"].lower()
    assert open_loss in words["description"] and "Myfxbook" in words["description"]


# -- 4. The sitemap --------------------------------------------------------------------


def test_the_sitemap_lists_three_more_urls_with_their_own_date(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sitemap = client.get("/sitemap.xml").text
    others = sum(len(pair) for pair in PUBLIC_PAGES if pair != SIGNAL_SAMPLE_PATHS)
    assert sitemap.count("<url>") == others + 3
    assert SIGNAL_SAMPLE_PATHS in PUBLIC_PAGES
    datetime.strptime(SIGNAL_SAMPLE_PUBLISHED, "%Y-%m-%d")
    for path in SIGNAL_SAMPLE_PATHS.values():
        assert page_lastmod(path) == SIGNAL_SAMPLE_PUBLISHED
        assert f"<loc>{BASE}{path}</loc><lastmod>{SIGNAL_SAMPLE_PUBLISHED}</lastmod>" in sitemap
    # The first sample keeps its own date and place.
    for path in SAMPLE_PAGE_PATHS.values():
        assert f"<loc>{BASE}{path}</loc><lastmod>{page_lastmod(path)}</lastmod>" in sitemap
    robots = robots_txt(BASE)
    assert not any(f"Disallow: {path}" in robots for path in SIGNAL_SAMPLE_PATHS.values())


def test_every_new_text_passes_the_guard_and_promises_nothing() -> None:
    keys = ("other_signal", "other_signal_link", "signal_files", "myfxbook", "mql5", "fxblue")
    for locale in LOCALES:
        texts = [
            SIGNAL_SAMPLE_BANNER[locale],
            *SIGNAL_SAMPLE_COPY[locale].values(),
            *(SAMPLE_CTA_COPY[locale][key] for key in keys),
        ]
        for text in texts:
            assert find_claims(text) == [], text
            assert ENDORSEMENT.search(text) is None, text
            # No figure in the copy (a name like MQL5 is not one): every number on
            # the page comes from the report.
            assert not re.search(r"(?<![A-Za-z])\d", text), text
        if locale == "pt":
            assert not any("informe" in text or "archivo" in text for text in texts)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_platform_block_holds_only_what_the_file_states(tmp_path: Path, locale: str) -> None:
    """Myfxbook prints no balance. The balance chain Rigor re-adds is its own
    check (Measured), apart from what the platform states (Declared)."""
    from quant_trade.audit.report import LABELS, RIGOR_CHECKED_METADATA, platform_label

    text = _visible(_client(tmp_path).get(SIGNAL_SAMPLE_PATHS[locale]).text)
    labels = LABELS[locale]
    declared = _between(text, labels["platform"], labels["platform_checked"])
    checked = text.split(labels["platform_checked"], 1)[1][:400]
    for key in RIGOR_CHECKED_METADATA:
        name = platform_label(key, locale)
        assert name not in declared, key
        assert name in checked, key
    assert find_claims(declared) == [] and find_claims(checked) == []
