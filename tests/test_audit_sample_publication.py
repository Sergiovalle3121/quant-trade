"""The public page, badge and card of each public sample, seen before paying.

``/v/ejemplo`` (the backtest sample) and ``/v/ejemplo-senal`` (the signal sample)
are the pages a real publication of each sample's report gets: the same routes,
functions and caching as ``/v/{public_id}``, from the view a retention purge
keeps, with the synthetic-data notice on top. Nothing is written to the
database, no real public id can be either one, and the report's publish block,
the FAQ, the page for funds and signal providers and both samples link to them.
Every page is read over HTTP with ``TestClient``; nothing reaches the network.
"""

from __future__ import annotations

import html
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import web  # noqa: E402
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.check import COPY as CHECK_COPY  # noqa: E402
from quant_trade.audit.faq import FAQ_PATH  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import SAMPLE_PAGE_PATHS, VERIFICATION_NOTICE  # noqa: E402
from quant_trade.audit.report import (  # noqa: E402
    render,
    sample_cta_band,
    sample_public_line,
    to_json,
)
from quant_trade.audit.sample import SAMPLE_NOW, sample_result, signal_sample_result  # noqa: E402
from quant_trade.audit.sample_publication import (  # noqa: E402
    PUBLIC_ID_LENGTH,
    PUBLIC_PAGE_LINK,
    PUBLIC_PAGES_LINE,
    SAMPLE_BAND_LINK,
    SAMPLE_PUBLIC_IDS,
    SAMPLE_PUBLICATION_LOCALE,
    SAMPLE_PUBLICATION_NOTICE,
    SAMPLE_REPORT_LINK,
    public_pages_line,
    sample_notice_html,
    sample_public_id,
    sample_public_path,
)
from quant_trade.audit.schema import AuditResult  # noqa: E402
from quant_trade.audit.seo import CHECK_PATH, SIGNAL_SAMPLE_PATHS  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402

LOCALES = ("es", "en", "pt")
BASE = "https://rigor.example"
#: The synthetic-data words of the notice, as the sample reports say them.
SYNTHETIC = {"es": "datos sintéticos", "en": "synthetic data", "pt": "dados sintéticos"}
#: Endorsement and result words the new copy must never use, in any language.
ENDORSEMENT = re.compile(
    r"verifica|certifica|aprobad|aprovad|garant|rentab|rentáve|lucrativ|profitab|guarante"
    r"|certified|approved|verified",
    re.I,
)
#: Each sample's full report, per language.
REPORTS = {"backtest": SAMPLE_PAGE_PATHS, "signal": SIGNAL_SAMPLE_PATHS}
#: The badge and both cards, with their content type.
IMAGES = (("badge.svg", "image/svg+xml"), ("card.svg", "image/svg+xml"), ("card.png", "image/png"))
#: The page for funds and signal providers, the one audience page that sells publishing.
PROVIDERS = "gestoras-y-senales"


@cache
def _built(kind: str, locale: str) -> AuditResult:
    """A sample's result with a smaller resampling (the class and flags do not depend
    on it), built once for the whole module."""
    build = signal_sample_result if kind == "signal" else sample_result
    return build(locale, bootstrap_samples=60)


def _fake(kind: str) -> Callable[..., AuditResult]:
    def build(locale: str = "es", *, market: Any = None, **_: Any) -> AuditResult:
        assert market is None  # no public series in tests
        return _built(kind, locale)

    return build


@pytest.fixture(autouse=True)
def _fast_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "sample_result", _fake("backtest"))
    monkeypatch.setattr(web, "signal_sample_result", _fake("signal"))


def _app(tmp_path: Path, **overrides: Any) -> tuple[TestClient, Any, Path]:
    database = tmp_path / "audit.db"
    settings = AuditSettings(
        database_url=f"sqlite:///{database.as_posix()}",
        base_url=BASE,
        **({"free_mode": False, "access_codes": True} | overrides),
    )
    store = make_store(settings.database_url)
    return TestClient(web.create_app(settings, store)), store, database


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _hrefs(fragment: str) -> list[str]:
    return [html.unescape(href) for href in re.findall(r"href='([^']*)'", fragment)]


def _between(page: str, start: str, end: str) -> str:
    assert start in page, start
    return page.split(start, 1)[1].split(end, 1)[0]


def _publish_real(store: Any, audit_id: str, result: AuditResult) -> str:
    """A real publication of ``result``, audited and published at the sample's date,
    stored as an upload stores it (the report's JSON, ``report.to_json``)."""
    data = result.model_dump(mode="json")
    store.create_audit(
        audit_id=audit_id,
        created_at=SAMPLE_NOW,
        token_hash="0" * 64,
        client_ip="",
        declared_json="{}",
        result_json=to_json(result),
        report_html="",
        overall_class=str(data["verdict"]["overall"]),
        digests={},
        equity_csv=None,
    )
    return str(store.publish(audit_id, at=SAMPLE_NOW).public_id)


def _dump(database: Path) -> list[str]:
    connection = sqlite3.connect(database)
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


# -- 1. The pages ------------------------------------------------------------------------


def test_the_six_pages_answer_in_every_language_with_the_synthetic_data_notice(
    tmp_path: Path,
) -> None:
    client, _, _ = _app(tmp_path)
    for kind, public_id in SAMPLE_PUBLIC_IDS.items():
        for locale in LOCALES:
            response = client.get(f"/v/{public_id}?lang={locale}")
            assert response.status_code == 200, (public_id, locale)
            page = response.text
            assert f"<html lang='{locale}'>" in page
            # The notice, once, on top: above the page's title.
            notice = sample_notice_html(public_id, locale)
            assert notice and page.count(notice) == 1
            assert page.index(notice) < page.index("<h1")
            assert SYNTHETIC[locale] in SAMPLE_PUBLICATION_NOTICE[kind][locale]
            assert html.escape(SAMPLE_PUBLICATION_NOTICE[kind][locale], quote=True) in page
            # Its link opens the sample's full report.
            report = REPORTS[kind][locale]
            assert _hrefs(notice) == [report]
            assert client.get(report).status_code == 200
            # The page itself: the fixed notice of every public page, its badge and card.
            assert html.escape(VERIFICATION_NOTICE[locale], quote=True) in page
            assert f"/v/{public_id}/badge.svg?lang={locale}" in page
            assert f"/v/{public_id}/card.svg?lang={locale}" in page
            # Never indexed and never cached, as a real /v.
            assert "<meta name='robots' content='noindex, nofollow'>" in page
            assert response.headers["cache-control"] == "no-store"
            assert "x-robots-tag" not in response.headers
            assert find_claims(html.unescape(page)) == [] and find_claims(_visible(page)) == []
        # Spanish without ?lang=, as a real /v.
        plain = client.get(f"/v/{public_id}")
        assert plain.status_code == 200
        assert plain.text == client.get(f"/v/{public_id}?lang=es").text
    # The two samples are two pages, and an unknown id is still 404.
    assert client.get("/v/ejemplo").text != client.get("/v/ejemplo-senal").text
    assert client.get("/v/ejemplo-sena").status_code == 404
    assert client.get("/v/Ejemplo").status_code == 404


@pytest.mark.parametrize("purged", [False, True], ids=["kept", "purged"])
def test_each_page_is_the_page_a_real_publication_of_the_same_report_gets(
    tmp_path: Path, purged: bool
) -> None:
    """The same report published for real, before and after the purge keeps only its
    view: the sample's page is that page with the notice on top, its badge and its
    cards the same images, and only the id differs."""
    client, store, _ = _app(tmp_path)
    real = {
        kind: _publish_real(store, f"real-{kind}", _built(kind, SAMPLE_PUBLICATION_LOCALE))
        for kind in SAMPLE_PUBLIC_IDS
    }
    if purged:
        far = datetime(2100, 1, 1, tzinfo=UTC)
        assert store.purge_expired(far, retention_days=1) == 2
        assert all(store.get_audit(f"real-{kind}").result_json is None for kind in real)
    for kind, public_id in SAMPLE_PUBLIC_IDS.items():
        real_id = real[kind]
        assert len(real_id) == PUBLIC_ID_LENGTH
        for locale in LOCALES:
            sample_page = client.get(f"/v/{public_id}?lang={locale}").text
            real_page = client.get(f"/v/{real_id}?lang={locale}").text
            # A real page never carries the notice.
            assert "sample-publication" not in real_page
            notice = sample_notice_html(public_id, locale)
            assert sample_page.replace(notice, "", 1) == real_page.replace(real_id, public_id)
            for name, kind_of_image in IMAGES:
                mine = client.get(f"/v/{public_id}/{name}?lang={locale}")
                theirs = client.get(f"/v/{real_id}/{name}?lang={locale}")
                assert mine.status_code == theirs.status_code == 200, (public_id, name)
                assert mine.headers["content-type"] == theirs.headers["content-type"]
                assert mine.headers["content-type"].startswith(kind_of_image)
                assert mine.headers["cache-control"] == theirs.headers["cache-control"]
                if name.endswith(".svg"):
                    assert mine.text == theirs.text.replace(real_id, public_id)
                else:
                    assert mine.content == theirs.content


def test_badge_and_cards_answer_with_their_content_type_and_cache(tmp_path: Path) -> None:
    client, _, _ = _app(tmp_path)
    for kind, public_id in SAMPLE_PUBLIC_IDS.items():
        for locale in LOCALES:
            for name, content_type in IMAGES:
                response = client.get(f"/v/{public_id}/{name}?lang={locale}")
                assert response.status_code == 200, (public_id, name, locale)
                assert response.headers["content-type"].startswith(content_type)
                # Images are cached like a real publication's (``web.no_store``).
                assert response.headers["cache-control"] == web.PUBLIC_CACHE_CONTROL
                if name.endswith(".svg"):
                    svg = response.text
                    assert svg.startswith("<svg") and "<script" not in svg
                    assert find_claims(html.unescape(svg)) == []
                else:
                    assert response.content.startswith(b"\x89PNG")
        # The badge shows the sample's class, its id and its date, never a figure.
        badge = client.get(f"/v/{public_id}/badge.svg").text
        overall = _built(kind, SAMPLE_PUBLICATION_LOCALE).model_dump(mode="json")["verdict"]
        assert public_id in badge and SAMPLE_NOW.date().isoformat() in badge
        assert f">{overall['overall']}<" in badge


def test_nothing_is_written_to_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, database = _app(tmp_path)
    assert client.get("/").status_code == 200  # whatever any first visit does
    before = _dump(database)
    calls: list[str] = []
    for name in ("get_publication", "publish", "get_audit", "publication_view"):
        original = getattr(store, name)

        def spy(*args: Any, _name: str = name, _original: Any = original, **kwargs: Any) -> Any:
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(store, name, spy)
    for public_id in SAMPLE_PUBLIC_IDS.values():
        for locale in LOCALES:
            assert client.get(f"/v/{public_id}?lang={locale}").status_code == 200
            for name, _ in IMAGES:
                assert client.get(f"/v/{public_id}/{name}?lang={locale}").status_code == 200
    # Answered from the samples alone: nothing looked up, nothing stored.
    assert calls == []
    assert _dump(database) == before
    assert all(store.get_publication(public_id) is None for public_id in SAMPLE_PUBLIC_IDS.values())


def test_a_real_public_id_cannot_be_a_reserved_one(tmp_path: Path) -> None:
    client, store, _ = _app(tmp_path)
    result = _built("signal", SAMPLE_PUBLICATION_LOCALE)
    ids = {_publish_real(store, f"audit-{index}", result) for index in range(40)}
    # ``Store.publish`` draws secrets.token_urlsafe(9): 12 characters, always.
    assert len(ids) == 40
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{12}", public_id) for public_id in ids)
    assert PUBLIC_ID_LENGTH == 12
    for reserved in SAMPLE_PUBLIC_IDS.values():
        assert len(reserved) != PUBLIC_ID_LENGTH
        assert re.fullmatch(r"[A-Za-z0-9_-]{12}", reserved) is None
        assert reserved not in ids
    # Even a row stored under a reserved id (by hand, outside ``publish``) could not
    # take its place: /v answers the sample before any lookup.
    before = {public_id: client.get(f"/v/{public_id}").text for public_id in ids}
    samples = {
        public_id: client.get(f"/v/{public_id}").text for public_id in SAMPLE_PUBLIC_IDS.values()
    }
    for index, reserved in enumerate(SAMPLE_PUBLIC_IDS.values()):
        _publish_real(store, f"intruder-{index}", result)
        with store.engine.begin() as connection:
            connection.execute(
                store.publications.update()
                .where(store.publications.c.audit_id == f"intruder-{index}")
                .values(public_id=reserved)
            )
        assert store.get_publication(reserved) is not None
    for reserved, page in samples.items():
        assert client.get(f"/v/{reserved}").text == page
    assert {public_id: client.get(f"/v/{public_id}").text for public_id in ids} == before


@pytest.mark.parametrize("kind", list(SAMPLE_PUBLIC_IDS))
def test_the_check_page_answers_a_sample_pdf_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """/comprobar still answers a sample's PDF as the sample, without a public page,
    once the sample's page has been seen: the page records nothing."""
    monkeypatch.setattr(web.pdf_lib, "available", lambda: True)
    monkeypatch.setattr(
        web.pdf_lib,
        "report_pdf",
        lambda page, **kwargs: f"%PDF-1.4 rigor {kwargs.get('audit_id')}".encode(),
    )
    client, _, _ = _app(tmp_path)
    assert client.get(f"/v/{SAMPLE_PUBLIC_IDS[kind]}").status_code == 200
    pdf = (web.SIGNAL_SAMPLE_PDF_PATHS if kind == "signal" else web.SAMPLE_PDF_PATHS)["es"]
    download = client.get(pdf)
    assert download.status_code == 200
    checked = client.post(
        CHECK_PATH["es"],
        files={"report": ("rigor.pdf", download.content, "application/pdf")},
        data={"lang": "es"},
    )
    assert checked.status_code == 200
    answer = html.unescape(checked.text)
    assert CHECK_COPY["es"]["found_title"] in answer and CHECK_COPY["es"]["sample"] in answer
    box = _between(checked.text, "<div class='chk-result", "<p class='chk-scope'>")
    assert "/v/" not in box and html.escape(CHECK_COPY["es"]["public"]) not in box


# -- 2. The links to them -----------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_publish_block_links_the_sample_of_the_same_kind(locale: str) -> None:
    """Under the publish help: an account history is shown the signal's page, a
    backtest the backtest's; nothing else in the block changes."""
    for kind, public_id in SAMPLE_PUBLIC_IDS.items():
        result = _built(kind, locale)
        page, _ = render(
            result, watermark=False, locale=locale, publish_url="/audits/x/publish?token=t"
        )
        block = _between(page, "<form class='publish' method='post'", "</form>")
        link = sample_public_path(public_id, locale)
        assert _hrefs(block) == [link]
        assert f">{html.escape(PUBLIC_PAGE_LINK[locale])}</a>" in block
        expected = "account" if kind == "signal" else "backtest"
        assert sample_public_id(expected) == public_id
        # Published already: the share block instead, without the line.
        published, _ = render(result, watermark=False, locale=locale, public_id="abcdefghijkl")
        assert link not in published


@pytest.mark.parametrize("locale", LOCALES)
def test_an_uploaded_report_links_the_public_page_that_resolves(
    tmp_path: Path, locale: str
) -> None:
    client, _, _ = _app(tmp_path, free_mode=True, access_codes=False, bootstrap_samples=100)
    client = signed_in(client)
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    data = {"trials": "3", "consent": "on", "locale": locale}
    location = client.post("/audits", files=files, data=data, follow_redirects=False)
    report = client.get(location.headers["location"]).text
    block = _between(report, "<form class='publish' method='post'", "</form>")
    (link,) = (href for href in _hrefs(block) if href.startswith("/v/"))
    assert link in {
        sample_public_path(public_id, locale) for public_id in SAMPLE_PUBLIC_IDS.values()
    }
    response = client.get(link)
    assert response.status_code == 200
    assert "sample-publication" in response.text


@pytest.mark.parametrize("locale", LOCALES)
def test_the_faq_publishing_answer_links_both_pages(tmp_path: Path, locale: str) -> None:
    client, _, _ = _app(tmp_path)
    page = client.get(FAQ_PATH[locale]).text
    line = public_pages_line(locale, css="faq-example")
    assert page.count(line) == 1
    # Inside the publishing question, right after its answer.
    question = page[: page.index(line)].rsplit("<details>", 1)[1]
    assert any(word in question for word in ("publica", "publish", "publico"))
    assert "</details>" not in question
    links = _hrefs(line)
    assert links == [
        sample_public_path(public_id, locale) for public_id in SAMPLE_PUBLIC_IDS.values()
    ]
    for link in links:
        assert client.get(link).status_code == 200
    assert find_claims(_visible(page)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_page_for_providers_links_both_pages(tmp_path: Path, locale: str) -> None:
    client, _, _ = _app(tmp_path)
    line = public_pages_line(locale, css="aud-example")
    for audience in AUDIENCE_PAGES:
        page = client.get(audience_url(audience.slug, locale)).text
        # Only the page that sells publishing a history to clients carries it.
        assert (line in page) is (audience.slug == PROVIDERS), audience.slug
        assert audience.public_example is (audience.slug == PROVIDERS)
    page = client.get(audience_url(PROVIDERS, locale)).text
    # In the lead, under the first buttons, before the first section.
    assert page.index("<div class='hero-cta'>") < page.index(line) < page.index("<h2 id='s1'>")
    for link in _hrefs(line):
        assert client.get(link).status_code == 200
    assert find_claims(_visible(page)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_both_samples_link_their_own_public_page_from_their_band(
    tmp_path: Path, locale: str
) -> None:
    client, _, _ = _app(tmp_path)
    for kind, paths in REPORTS.items():
        line = sample_public_line(locale, kind)
        assert _hrefs(line) == [sample_public_path(SAMPLE_PUBLIC_IDS[kind], locale)]
        for offer in ("welcome", "free", "paid"):
            assert sample_cta_band(locale, offer, kind).count(line) == 1
        page = client.get(paths[locale]).text
        band = _between(page, "<div class='sample-cta no-print'>", "</div>")
        assert band.count(line) == 1
        (link,) = _hrefs(line)
        response = client.get(link)
        assert response.status_code == 200
        # The page it opens is the one of this very sample.
        assert sample_notice_html(SAMPLE_PUBLIC_IDS[kind], locale) in response.text


# -- 3. The words ---------------------------------------------------------------------------


def test_the_new_words_exist_in_three_languages_and_pass_the_guard() -> None:
    texts: list[str] = []
    for copy in (PUBLIC_PAGE_LINK, SAMPLE_BAND_LINK, SAMPLE_REPORT_LINK, PUBLIC_PAGES_LINE):
        assert set(copy) == set(LOCALES)
        assert len({str(copy[locale]) for locale in LOCALES}) == 3
    for kind in SAMPLE_PUBLIC_IDS:
        assert set(SAMPLE_PUBLICATION_NOTICE[kind]) == set(LOCALES)
        texts += SAMPLE_PUBLICATION_NOTICE[kind].values()
    for locale in LOCALES:
        texts += [PUBLIC_PAGE_LINK[locale], SAMPLE_BAND_LINK[locale], SAMPLE_REPORT_LINK[locale]]
        texts += PUBLIC_PAGES_LINE[locale].values()
        texts.append(_visible(public_pages_line(locale)))
        for public_id in SAMPLE_PUBLIC_IDS.values():
            texts.append(_visible(sample_notice_html(public_id, locale)))
    for text in texts:
        assert find_claims(text) == [], text
        assert ENDORSEMENT.search(text) is None, text
    # The signal's notice says the signal is made up, as its sample report does.
    assert all(
        any(word in SAMPLE_PUBLICATION_NOTICE["signal"][locale] for word in ("inventad", "made-up"))
        for locale in LOCALES
    )
    # Any other id gets no notice: a publication's page stays as it is.
    assert sample_notice_html("abcdefghijkl", "es") == ""
