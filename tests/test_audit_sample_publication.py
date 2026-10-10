"""The public page, badge and card of each public sample, seen before paying.

``/v/ejemplo`` (the backtest sample) and ``/v/ejemplo-senal`` (the signal sample)
are the pages a real publication of each sample's report gets: the same routes,
functions and caching as ``/v/{public_id}``, from the view a retention purge
keeps, with the synthetic-data notice on top. Only what would pass a sample off
as someone's audit is said its own way: its title and link preview, its share
text and tag, its badge code's words and its publication date. Nothing is
written to the database, no real public id can be either one, and the report's
publish block, the FAQ, the page for funds and signal providers and both
samples link to them. Every page is read over HTTP with ``TestClient``; nothing
reaches the network.
"""

from __future__ import annotations

import html
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel, web  # noqa: E402
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.check import COPY as CHECK_COPY  # noqa: E402
from quant_trade.audit.faq import BADGE_QUESTION, FAQ_PATH  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    _COPY,
    _UI,
    SAMPLE_PAGE_PATHS,
    VERIFICATION_NOTICE,
    _utc_time,
)
from quant_trade.audit.report import (  # noqa: E402
    LABELS,
    render,
    report_kind,
    sample_cta_band,
    sample_public_line,
    to_json,
)
from quant_trade.audit.sample import SAMPLE_NOW, sample_result, signal_sample_result  # noqa: E402
from quant_trade.audit.sample_publication import (  # noqa: E402
    PUBLIC_ID_LENGTH,
    PUBLIC_PAGE_LINK,
    PUBLIC_PAGES_LINE,
    SAMPLE_BADGE_HELP,
    SAMPLE_BAND_LINK,
    SAMPLE_META_LEAD,
    SAMPLE_PAGES_PUBLISHED,
    SAMPLE_PUBLIC_IDS,
    SAMPLE_PUBLICATION_LOCALE,
    SAMPLE_PUBLICATION_NOTICE,
    SAMPLE_REPORT_LINK,
    SAMPLE_SHARE_REF,
    SAMPLE_SHARE_TEXT,
    SAMPLE_SHOWN_IDS,
    SAMPLE_SPANISH_SOURCE,
    SAMPLE_TITLE_WORD,
    public_pages_line,
    sample_notice_html,
    sample_page,
    sample_public_id,
    sample_public_path,
)
from quant_trade.audit.schema import AuditResult  # noqa: E402
from quant_trade.audit.seo import (  # noqa: E402
    CHECK_PATH,
    SIGNAL_SAMPLE_PATHS,
    SIGNAL_SAMPLE_PUBLISHED,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.sharing import COPY as SHARE_COPY  # noqa: E402
from quant_trade.audit.sharing import share_block  # noqa: E402
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
#: The day the sample pages were published, as a real publication's moment.
PUBLISHED_AT = datetime.combine(
    date.fromisoformat(SAMPLE_PAGES_PUBLISHED), datetime.min.time(), UTC
)
#: First-person share words of a real publication, never on a sample's page.
FIRST_PERSON = re.compile(r"\b(Audité|I audited|Auditei)\b")


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
    """A real publication of ``result``, audited at the sample's date and published
    the day the sample pages were, stored as an upload stores it (the report's JSON,
    ``report.to_json``)."""
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
    return str(store.publish(audit_id, at=PUBLISHED_AT).public_id)


def _dump(database: Path) -> list[str]:
    connection = sqlite3.connect(database)
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


def _swap(page: str, old: str, new: str, count: int | None = None) -> str:
    """``page`` with ``old`` replaced by ``new``, checking how often it appears."""
    found = page.count(old)
    assert found and (count is None or found == count), (old, found)
    return page.replace(old, new)


def _as_sample(page: str, *, public_id: str, kind: str, locale: str, published: str) -> str:
    """A real publication's page (its id already the sample's) with exactly the words a
    sample's page says its own way, and nothing else: the notice on top, "Sample" in
    front of the title and the link preview, the sample's publication day, the
    identifier its report shows, the words over the badge code without its copy button,
    and the share text and tag."""
    from quant_trade.audit.pages import BADGE_NOTICE, CLASS_WORD

    copy, ui, e = _COPY[locale], _UI[locale], html.escape
    data = _built(kind, SAMPLE_PUBLICATION_LOCALE).model_dump(mode="json")
    overall = str(data["verdict"]["overall"])
    title = f"{copy['v_title']} · {CLASS_WORD[locale]} {overall}"
    description = copy["v_description"].format(
        cls_label=CLASS_WORD[locale],
        overall=overall,
        date=str(data["generated_at_utc"])[:10],
        notice=BADGE_NOTICE[locale],
    )
    page = _swap(page, e(title), e(f"{SAMPLE_TITLE_WORD[locale]} · {title}"))
    page = _swap(page, e(description), e(f"{SAMPLE_META_LEAD[locale]} · {description}"))
    page = _swap(
        page,
        _utc_time(published, locale),
        _utc_time(SAMPLE_PAGES_PUBLISHED, locale),
        1,
    )
    eyebrow = "<div class='eyebrow rise'>"
    page = _swap(page, eyebrow, sample_notice_html(public_id, locale) + eyebrow, 1)
    # The report's word and value, not the code of a publication's page.
    page = _swap(
        page,
        f"<b>{e(ui['v_id'])}</b><span>{e(public_id)}</span>",
        f"<b>{e(LABELS[locale]['audit_id'])}</b><span>{e(SAMPLE_SHOWN_IDS[kind][locale])}</span>",
        1,
    )
    page = _swap(page, e(copy["v_badge_help"]), e(SAMPLE_BADGE_HELP[locale]), 1)
    page = _swap(
        page,
        "<div class='copy-row'><button class='btn btn-dark btn-sm' type='button' "
        f"data-copy='badge-code' data-done='{e(ui['v_copied'])}' hidden>{e(ui['v_copy'])}"
        "</button></div>",
        "",
        1,
    )
    shared = {"overall": overall, "public_id": public_id, "locale": locale}
    return _swap(
        page,
        share_block(**shared, kind=report_kind(data)),
        share_block(**shared, template=SAMPLE_SHARE_TEXT[locale], ref=SAMPLE_SHARE_REF),
        1,
    )


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
            # Its link opens the sample's full report the page is made from: the
            # Spanish one, which the other languages name.
            report = REPORTS[kind][SAMPLE_PUBLICATION_LOCALE]
            assert _hrefs(notice) == [report]
            assert client.get(report).status_code == 200
            assert (SAMPLE_SPANISH_SOURCE[locale] == "") is (locale == SAMPLE_PUBLICATION_LOCALE)
            assert html.escape(SAMPLE_SPANISH_SOURCE[locale], quote=True) in notice
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
    """The same report published for real the same day, before and after the purge
    keeps only its view: the sample's page is that page with only the sample's own
    words (``_as_sample``), its badge and its cards the same images, and only the id
    differs."""
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
        published = store.get_publication(real_id).created_at
        for locale in LOCALES:
            mine = client.get(f"/v/{public_id}?lang={locale}").text
            real_page = client.get(f"/v/{real_id}?lang={locale}").text
            # A real page never carries the sample's words.
            assert "sample-publication" not in real_page
            assert f"ref={SAMPLE_SHARE_REF}" not in real_page
            assert SAMPLE_BADGE_HELP[locale] not in html.unescape(real_page)
            assert mine == _as_sample(
                real_page.replace(real_id, public_id),
                public_id=public_id,
                kind=kind,
                locale=locale,
                published=published,
            )
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
                    # The PNG is drawn from that SVG, id included, so with a real
                    # renderer (CI) the bytes differ by the id; without one both are
                    # the site's generic card. Either way: same kind of image, same size.
                    assert mine.content[:8] == theirs.content[:8] == b"\x89PNG\r\n\x1a\n"
                    assert mine.content[16:24] == theirs.content[16:24]  # IHDR width, height


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


def _hash_row(page: str, locale: str) -> str:
    """The result's SHA-256 a public page shows in its details."""
    label = html.escape(_COPY[locale]["v_result_sha"])
    found = re.findall(rf"<tr><td>{re.escape(label)}</td><td><code>([0-9a-f]{{64}})</code>", page)
    assert len(found) == 1, locale
    return found[0]


def _report_hash(page: str) -> str:
    """The result's SHA-256 at the foot of a full report."""
    found = re.findall(r"<p class='rf-sha'><span>[^<]*</span><code>([0-9a-f]{64})</code>", page)
    assert len(found) == 1
    return found[0]


def test_each_page_shows_the_hash_of_the_report_its_notice_links(tmp_path: Path) -> None:
    """One publication, one hash: in every language the page shows the hash of the
    Spanish report it is made from, its notice links that report, and in English and
    Portuguese (whose reports are other results) it says so, from the band too."""
    client, _, _ = _app(tmp_path)
    for kind, public_id in SAMPLE_PUBLIC_IDS.items():
        for locale in LOCALES:
            page = client.get(f"/v/{public_id}?lang={locale}").text
            shown = _hash_row(page, locale)
            (linked,) = _hrefs(sample_notice_html(public_id, locale))
            assert _report_hash(client.get(linked).text) == shown, (public_id, locale)
            # The reader's own report: the very one in Spanish, another result otherwise,
            # and then the notice and the band name the Spanish version.
            own = client.get(REPORTS[kind][locale]).text
            assert (_report_hash(own) == shown) is (locale == SAMPLE_PUBLICATION_LOCALE)
            spanish = {"es": "", "en": "Spanish", "pt": "espanhol"}[locale]
            assert spanish in SAMPLE_SPANISH_SOURCE[locale]
            assert spanish in SAMPLE_BAND_LINK[locale]
            if spanish:
                assert html.escape(SAMPLE_SPANISH_SOURCE[locale], quote=True) in page
                assert spanish in SAMPLE_REPORT_LINK[locale]
            (band,) = _hrefs(sample_public_line(locale, kind))
            assert band == sample_public_path(public_id, locale)
            assert html.escape(SAMPLE_BAND_LINK[locale]) in own


def test_a_sample_page_never_passes_for_someones_audit(tmp_path: Path) -> None:
    """Its tab title and link preview say it is a sample, its share text is not in the
    first person and counts under its own tag, and its badge code is the sample's,
    without a copy button. A real page keeps all of them."""
    client, _, _ = _app(tmp_path)
    assert SAMPLE_SHARE_REF in funnel.REF_TAGS and SAMPLE_SHARE_REF != "share"
    assert funnel.clean_ref(SAMPLE_SHARE_REF) == SAMPLE_SHARE_REF
    for public_id in SAMPLE_PUBLIC_IDS.values():
        for locale in LOCALES:
            page = client.get(f"/v/{public_id}?lang={locale}").text
            head = page.split("</head>", 1)[0]
            word, lead = SAMPLE_TITLE_WORD[locale], SAMPLE_META_LEAD[locale]
            (title,) = re.findall(r"<title>([^<]*)</title>", head)
            assert html.unescape(title).startswith(f"{word} · ")
            previews = re.findall(
                r"<meta (?:property|name)='(og:title|og:description)' content='([^']*)'", head
            )
            assert {name for name, _ in previews} == {"og:title", "og:description"}, previews
            for name, content in previews:
                start = f"{word} · " if name == "og:title" else f"{lead} · "
                assert html.unescape(content).startswith(start), (name, content)
            block = _between(page, "data-public-share>", "</section>")
            text = html.unescape(_between(block, "<textarea", "</textarea>").split(">", 1)[1])
            url = f"https://rigorscore.com/v/{public_id}?ref={SAMPLE_SHARE_REF}"
            url += "" if locale == "es" else f"&lang={locale}"
            assert text == SAMPLE_SHARE_TEXT[locale].format(url=url)
            assert FIRST_PERSON.search(html.unescape(block)) is None
            assert "ref=share" not in block and f"ref%3D{SAMPLE_SHARE_REF}" in block
            # The badge and its code are shown, as the sample's, with nothing to copy.
            assert "<pre><code id='badge-code'>" in page
            assert "data-copy='badge-code'" not in page
            assert html.escape(SAMPLE_BADGE_HELP[locale]) in page
            assert html.escape(_COPY[locale]["v_badge_help"]) not in page
            assert find_claims(text) == [] and find_claims(SAMPLE_BADGE_HELP[locale]) == []
        # Any other id: the page a publication gets, with its own words.
        assert sample_page("abcdefghijkl", "es") is None
    # The same words a real publication's page always had.
    for locale in LOCALES:
        words = share_block(overall="C", public_id="abcdefghijkl", locale=locale)
        assert "ref=share" in words and FIRST_PERSON.search(html.unescape(words))
        assert html.escape(SHARE_COPY[locale]["text"].split("{")[0]) in words


def test_each_page_is_dated_the_day_it_was_published(tmp_path: Path) -> None:
    """ "Published" is the day the sample pages came out, never the audit's date (the
    sample's fixed clock, which the audit date and the badge keep), and a bare date
    shows no made-up time of day."""
    assert SAMPLE_PAGES_PUBLISHED >= SIGNAL_SAMPLE_PUBLISHED > SAMPLE_NOW.date().isoformat()
    assert len(SAMPLE_PAGES_PUBLISHED) == len("2026-10-09")
    day = _utc_time(SAMPLE_PAGES_PUBLISHED, "es")
    assert day == f"<time datetime='{SAMPLE_PAGES_PUBLISHED}'>9 oct 2026</time>", day
    assert _utc_time("2026-10-09T18:30:00+00:00", "es").endswith("· 18:30 UTC</time>")
    client, _, _ = _app(tmp_path)
    for kind, public_id in SAMPLE_PUBLIC_IDS.items():
        audited = str(
            _built(kind, SAMPLE_PUBLICATION_LOCALE).model_dump(mode="json")["generated_at_utc"]
        )
        for locale in LOCALES:
            page = client.get(f"/v/{public_id}?lang={locale}").text
            facts = _between(page, "<div class='v-facts'>", "</div></div></div>")
            published = html.escape(_COPY[locale]["v_published"])
            assert (
                f"<b>{published}</b><span>{_utc_time(SAMPLE_PAGES_PUBLISHED, locale)}</span>"
                in facts
            )
            audit = html.escape(_COPY[locale]["v_audited"])
            assert f"<b>{audit}</b><span>{_utc_time(audited, locale)}</span>" in facts
            assert _utc_time(audited, locale) != _utc_time(SAMPLE_PAGES_PUBLISHED, locale)
        badge = client.get(f"/v/{public_id}/badge.svg").text
        assert audited[:10] in badge and SAMPLE_PAGES_PUBLISHED not in badge


def test_each_sample_audit_runs_once_for_its_report_its_pdf_and_its_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/v/ejemplo reads the Spanish result /ejemplo already built (and the other way
    round), as its PDF does: one run per sample and language, not one per page."""
    calls: list[tuple[str, str]] = []

    def counted(kind: str) -> Callable[..., AuditResult]:
        def build(locale: str = "es", *, market: Any = None, **_: Any) -> AuditResult:
            calls.append((kind, locale))
            return _built(kind, locale)

        return build

    monkeypatch.setattr(web, "sample_result", counted("backtest"))
    monkeypatch.setattr(web, "signal_sample_result", counted("signal"))
    monkeypatch.setattr(web.pdf_lib, "available", lambda: True)
    monkeypatch.setattr(web.pdf_lib, "report_pdf", lambda page, **kwargs: b"%PDF-1.4 rigor")
    client, _, _ = _app(tmp_path)
    paths = {
        "backtest": (SAMPLE_PAGE_PATHS["es"], web.SAMPLE_PDF_PATHS["es"]),
        "signal": (SIGNAL_SAMPLE_PATHS["es"], web.SIGNAL_SAMPLE_PDF_PATHS["es"]),
    }
    for kind, public_id in SAMPLE_PUBLIC_IDS.items():
        report, pdf = paths[kind]
        # The backtest's report first, the signal's public page first.
        first = [report, f"/v/{public_id}"] if kind == "backtest" else [f"/v/{public_id}", report]
        for path in [*first, pdf] + [f"/v/{public_id}/{name}" for name, _ in IMAGES]:
            assert client.get(path).status_code == 200, path
        for locale in LOCALES:
            assert client.get(f"/v/{public_id}?lang={locale}").status_code == 200
        assert calls.count((kind, SAMPLE_PUBLICATION_LOCALE)) == 1, calls
    # Another language is another run, once.
    assert client.get(SAMPLE_PAGE_PATHS["en"]).status_code == 200
    assert client.get(web.SAMPLE_PDF_PATHS["en"]).status_code == 200
    assert calls.count(("backtest", "en")) == 1
    assert len(calls) == 3


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
    """Under the publish help: an account history or a fund's track record (a real
    history, drawn on its own card) is shown the signal's page, a backtest the
    backtest's; nothing else in the block changes."""
    fund = _built("backtest", locale).model_copy(update={"fund": {"track_record": True}})
    cases = [(_built(kind, locale), public_id) for kind, public_id in SAMPLE_PUBLIC_IDS.items()]
    cases.append((fund, SAMPLE_PUBLIC_IDS["signal"]))
    kinds = []
    for result, public_id in cases:
        kind = report_kind(result.model_dump(mode="json"))
        kinds.append(kind)
        assert sample_public_id(kind) == public_id, kind
        page, _ = render(
            result, watermark=False, locale=locale, publish_url="/audits/x/publish?token=t"
        )
        block = _between(page, "<form class='publish' method='post'", "</form>")
        link = sample_public_path(public_id, locale)
        assert _hrefs(block) == [link]
        assert f">{html.escape(PUBLIC_PAGE_LINK[locale])}</a>" in block
        # Published already: the share block instead, without the line.
        published, _ = render(result, watermark=False, locale=locale, public_id="abcdefghijkl")
        assert link not in published
    assert kinds == ["backtest", "account", "fund"]


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
def test_the_faq_publishing_and_badge_answers_link_both_pages(tmp_path: Path, locale: str) -> None:
    client, _, _ = _app(tmp_path)
    page = client.get(FAQ_PATH[locale]).text
    line = public_pages_line(locale, css="faq-example")
    assert page.count(line) == 2
    # Inside the publishing question and the badge question, right after each answer.
    questions = []
    for part in page.split(line)[:-1]:
        question = part.rsplit("<details>", 1)[1]
        assert "</details>" not in question
        questions.append(html.unescape(_between(question, "<summary>", "</summary>")))
    assert any(word in questions[0] for word in ("publica", "publish", "publico"))
    assert questions[1] == BADGE_QUESTION[locale]
    # The badge question is the landing's own, answered on this page.
    assert BADGE_QUESTION[locale] in [question for question, _ in _COPY[locale]["faq"]]
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
    words = (
        PUBLIC_PAGE_LINK,
        SAMPLE_BAND_LINK,
        SAMPLE_REPORT_LINK,
        PUBLIC_PAGES_LINE,
        SAMPLE_SPANISH_SOURCE,
        SAMPLE_TITLE_WORD,
        SAMPLE_META_LEAD,
        SAMPLE_SHARE_TEXT,
        SAMPLE_BADGE_HELP,
    )
    for copy in words:
        assert set(copy) == set(LOCALES)
        assert len({str(copy[locale]) for locale in LOCALES}) == 3
    for kind in SAMPLE_PUBLIC_IDS:
        assert set(SAMPLE_PUBLICATION_NOTICE[kind]) == set(LOCALES)
        texts += SAMPLE_PUBLICATION_NOTICE[kind].values()
    for locale in LOCALES:
        texts += [str(copy[locale]) for copy in words if not isinstance(copy[locale], dict)]
        texts += PUBLIC_PAGES_LINE[locale].values()
        # The sample's words say it is a sample, with synthetic data, never "I audited".
        assert SYNTHETIC[locale] in SAMPLE_META_LEAD[locale]
        assert SYNTHETIC[locale] in SAMPLE_SHARE_TEXT[locale]
        assert SAMPLE_SHARE_TEXT[locale].endswith("{url}")
        assert FIRST_PERSON.search(SAMPLE_SHARE_TEXT[locale]) is None
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
