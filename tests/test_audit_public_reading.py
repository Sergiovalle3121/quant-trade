"""Public declared-figure cards stay reproducible, anonymous and memory-only."""

from __future__ import annotations

import html
import re
import socket
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel, owner_card, raster, reading  # noqa: E402
from quant_trade.audit.examples import EXAMPLES_PATH  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import spanish  # noqa: E402
from quant_trade.audit.public_card import PublicClaim, public_card_svg  # noqa: E402
from quant_trade.audit.report import evidence_label  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
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


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _visible(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _card(page: str) -> str:
    cards = [svg for svg in re.findall(r"<svg\b.*?</svg>", page, flags=re.S) if "xml:lang=" in svg]
    assert len(cards) == 1
    return cards[0]


def _share(page: str) -> str:
    found = re.search(
        r"<textarea\b[^>]*\bid=['\"]reading-share-text['\"][^>]*>(.*?)</textarea>",
        page,
        flags=re.S,
    )
    assert found is not None
    return html.unescape(found.group(1))


def _links(page: str) -> list[str]:
    return [html.unescape(value) for value in re.findall(r"\bhref=['\"]([^'\"]*)", page)]


@pytest.mark.parametrize("locale", LOCALES)
def test_public_form_and_result_are_localized_and_guard_clean(
    client: TestClient, locale: str
) -> None:
    path = reading.READING_PATH[locale]
    empty = client.get(path)
    assert empty.status_code == 200
    assert f"<html lang='{locale}'>" in empty.text
    assert reading.COPY[locale]["title"] in _visible(empty.text)
    assert "class='public-card-preview'" not in empty.text
    assert re.search(r"<form\b[^>]*method=['\"]get['\"]", empty.text)
    for field in FIGURES:
        assert re.search(rf"\bname=['\"]{field}['\"]", empty.text)
    for field in ("source_handle", "source_url", "locale", "lang"):
        assert not re.search(rf"\bname=['\"]{field}['\"]", empty.text)
    assert find_claims(_visible(empty.text)) == []
    for key, value in reading.COPY[locale].items():
        assert find_claims(value) == [], key

    filled = client.get(path, params=FIGURES)
    assert filled.status_code == 200
    assert "class='public-card-preview'" in filled.text
    assert find_claims(_visible(filled.text)) == []
    svg = _card(filled.text)
    root = ET.fromstring(svg)
    assert root.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == locale
    text = " ".join(root.itertext())
    assert reading.COPY[locale]["attribution"] in text
    mark = "." if locale == "en" else ","
    assert f"71{mark}0 %" in text and f"3{mark}24" in text
    assert evidence_label("DECLARED", locale) in text
    assert evidence_label("NOT_MEASURED", locale) in text
    assert re.search(r"\bMEASURED\b", text) is None
    assert not re.search(r"\b(?:clase|class|classe)\s+[A-D]\b", text, re.I)
    assert not any(node.text in ("A", "B", "C", "D") for node in root.iter())
    for node in root.iter():
        assert node.tag.rsplit("}", 1)[-1] in {"svg", "title", "desc", "rect", "text", "g"}
        assert not any(name.lower().startswith("on") for name in node.attrib)
        if "data-evidence" in node.attrib:
            assert node.attrib["data-evidence"] in {"DECLARED", "NOT_MEASURED"}


@pytest.mark.parametrize("locale", LOCALES)
def test_card_figures_use_the_languages_decimal_mark_and_the_link_keeps_the_point(
    client: TestClient, locale: str
) -> None:
    """Spanish and Portuguese read 56,5 %; English 56.5 %. The values and the shared
    address are the same in every language: its parameters keep the point."""
    response = client.get(reading.READING_PATH[locale], params=FIGURES)
    assert response.status_code == 200
    text = " ".join(ET.fromstring(_card(response.text)).itertext())
    mark, other = (".", ",") if locale == "en" else (",", ".")
    for figure in ("71{}0 %", "3{}24", "1{}8", "56{}5 % – 82{}2 %", "50{}0 %"):
        assert figure.format(mark, mark) in text, figure
    for figure in ("71{}0 %", "3{}24", "56{}5 % – 82{}2 %"):
        assert figure.format(other, other) not in text, figure
    assert find_claims(text) == []
    link = _share(response.text).split()[-1]
    assert urlsplit(link).path == reading.READING_PATH[locale]
    assert parse_qs(urlsplit(link).query) == {
        **{name: [value] for name, value in FIGURES.items()},
        "ref": ["lectura"],
    }


@pytest.mark.parametrize("locale", LOCALES)
def test_download_reuses_public_claim_and_cannot_attribute_to_someone_else(
    client: TestClient, locale: str
) -> None:
    expected = PublicClaim(
        source_handle=reading.COPY[locale]["attribution"],
        source_url="",
        trades=45,
        win_rate=0.71,
        profit_factor=3.24,
        sharpe=1.8,
        years=3,
        trials=1000,
        target_r=1,
        stop_r=1,
        locale=locale,  # type: ignore[arg-type]
    )
    malicious = {
        "source_handle": "<script>rentable</script>",
        "source_url": "https://someone-else.example/certified",
        "locale": "fr",
        "lang": "en" if locale != "en" else "pt",
    }
    path = reading.READING_PATH[locale]
    download = client.get(path, params={**FIGURES, **malicious, "download": "svg"})
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" in download.headers["content-disposition"]
    assert ".svg" in download.headers["content-disposition"]
    assert download.text == public_card_svg(expected)
    assert find_claims(download.text) == []
    page = client.get(path, params={**FIGURES, **malicious})
    assert page.status_code == 200
    assert f"<html lang='{locale}'>" in page.text
    assert "someone-else.example" not in page.text
    assert "rentable" not in page.text
    assert "certified" not in page.text
    download_links = [link for link in _links(page.text) if "download=svg" in link]
    assert len(download_links) == 1
    assert client.get(download_links[0]).text == download.text


@pytest.mark.parametrize("locale", LOCALES)
def test_share_text_reproduces_the_same_card_and_x_payload(client: TestClient, locale: str) -> None:
    answer = client.get(reading.READING_PATH[locale], params=FIGURES)
    share = _share(answer.text)
    assert find_claims(share) == []
    assert "Rigor" in share
    urls = re.findall(r"https://\S+", share)
    assert len(urls) == 1
    shared = urlsplit(urls[0])
    assert shared.netloc == urlsplit(BASE).netloc
    assert shared.path == reading.READING_PATH[locale]
    query = parse_qs(shared.query, keep_blank_values=True)
    assert query.pop("ref") == ["lectura"]
    assert set(query) == set(FIGURES)
    for key, value in FIGURES.items():
        assert float(query[key][0]) == float(value)
    repeated = client.get(urls[0])
    assert repeated.status_code == 200
    assert _card(repeated.text) == _card(answer.text)
    assert client.cookies.get(funnel.REF_COOKIE) == "lectura"
    assert re.search(r"data-copy=['\"]#?reading-share-text['\"]", answer.text)
    x_links = [
        link for link in _links(answer.text) if link.startswith("https://x.com/intent/post?")
    ]
    assert len(x_links) == 1
    assert parse_qs(urlsplit(x_links[0]).query) == {"text": [share]}
    # No figure can be introduced by suggested copy outside the reproducible URL.
    numeric = r"(?<!\w)[+-]?\d+(?:[.,]\d+)?"
    assert set(re.findall(numeric, share.replace(urls[0], ""))) <= set(
        re.findall(numeric, _visible(_card(answer.text)))
    )


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("png_enabled", [True, False])
def test_copy_link_and_downloads_preserve_exact_public_parameters(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, locale: str, png_enabled: bool
) -> None:
    monkeypatch.setattr(owner_card, "png_available", lambda: png_enabled)
    monkeypatch.setattr(raster, "card_png", lambda svg: b"mock PNG")
    figures = {**FIGURES, "win_rate": "71.12345678901234", "profit_factor": "3.2400", "years": ""}
    path = reading.READING_PATH[locale]
    form = client.get(path)
    assert "reading-share-link" not in form.text
    assert reading.COPY[locale]["download_png"] not in _visible(form.text)
    page = client.get(path, params={**figures, "ref": "ignored", "source_handle": "ignored"})
    assert page.status_code == 200
    field = re.search(
        r"<textarea\b([^>]*\bid=['\"]reading-share-link['\"][^>]*)>(.*?)</textarea>",
        page.text,
        flags=re.S,
    )
    assert field is not None
    assert "readonly" in field.group(1) and "hidden" in field.group(1)
    copied = html.unescape(field.group(2))
    parsed = urlsplit(copied)
    assert parsed.scheme + "://" + parsed.netloc == BASE
    assert parsed.path == path
    expected = {name: [value] for name, value in {**figures, "ref": "lectura"}.items()}
    assert parse_qs(parsed.query, keep_blank_values=True) == expected
    assert re.search(
        r"<button\b[^>]*\bdata-copy=['\"]reading-share-link['\"][^>]*>"
        + re.escape(reading.COPY[locale]["copy_link"])
        + r"</button>",
        page.text,
    )
    repeated = client.get(copied)
    assert repeated.status_code == 200
    assert _card(repeated.text) == _card(page.text)
    assert reading.COPY[locale]["download"] in _visible(page.text)
    png_links = [link for link in _links(page.text) if urlsplit(link).path == path + "/card.png"]
    if png_enabled:
        assert len(png_links) == 1
        assert parse_qs(urlsplit(png_links[0]).query, keep_blank_values=True) == expected
        assert re.search(
            r"<a\b[^>]*\bdownload[^>]*>" + reading.COPY[locale]["download_png"] + r"</a>",
            page.text,
        )
        assert client.get(png_links[0]).content == b"mock PNG"
    else:
        assert png_links == []
        assert reading.COPY[locale]["download_png"] not in _visible(page.text)
    assert find_claims(_visible(page.text)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_missing_figures_remain_missing_after_sharing(client: TestClient, locale: str) -> None:
    page = client.get(reading.READING_PATH[locale], params={key: "" for key in FIGURES})
    assert page.status_code == 200
    svg = _card(page.text)
    root = ET.fromstring(svg)
    groups = [node for node in root.iter() if "data-evidence" in node.attrib]
    assert groups
    assert all(node.attrib["data-evidence"] == "NOT_MEASURED" for node in groups)
    assert find_claims(_visible(page.text)) == []
    shared = re.search(r"https://\S+", _share(page.text))
    assert shared is not None
    repeated = client.get(shared.group(0))
    assert repeated.status_code == 200
    assert _card(repeated.text) == svg


@pytest.mark.parametrize("locale", LOCALES)
def test_invalid_numbers_return_clear_localized_errors_never_server_errors(
    client: TestClient, locale: str
) -> None:
    invalid = (
        ("trades", "0"),
        ("trades", "3.5"),
        ("trades", "10000001"),
        ("trials", "10000001"),
        ("trials", "true"),
        ("win_rate", "101"),
        ("win_rate", "-1"),
        ("win_rate", "NaN"),
        ("sharpe", "inf"),
        ("sharpe", "-inf"),
        ("sharpe", "1000001"),
        ("years", "0"),
        ("years", "1e999"),
        ("profit_factor", "-1"),
        ("profit_factor", "1" * 41),
        ("target_r", "0"),
        ("stop_r", "-1"),
        ("sharpe", "1\x00"),
        ("sharpe", "<script>alert(1)</script>"),
    )
    for field, value in invalid:
        answer = client.get(reading.READING_PATH[locale], params={**FIGURES, field: value})
        assert answer.status_code == 400, (field, value)
        assert "class='public-card-preview'" not in answer.text
        assert find_claims(_visible(answer.text)) == []
        assert any(
            owner_card.COPY[locale][key] in _visible(answer.text)
            for key in ("counts", "figures", "rate_error", "positive", "factor", "invalid")
        ), (field, value)
        assert "<script>alert" not in answer.text


@pytest.mark.parametrize("field", FIGURES)
def test_duplicate_numeric_fields_are_rejected(client: TestClient, field: str) -> None:
    answer = client.get("/lectura", params=[*FIGURES.items(), (field, "2")])
    assert answer.status_code == 400
    assert "class='public-card-preview'" not in answer.text
    assert find_claims(_visible(answer.text)) == []


def test_new_english_notes_have_explicit_spanish_rules() -> None:
    for key in ("note", "optional", "public", "limited"):
        assert spanish(reading.COPY["en"][key]) == reading.COPY["es"][key]


@pytest.mark.parametrize("download", ["", "png", "PNG", "<script>"])
def test_only_svg_download_is_supported(client: TestClient, download: str) -> None:
    response = client.get("/lectura", params={**FIGURES, "download": download})
    assert response.status_code == 400
    assert "content-disposition" not in response.headers
    assert "class='public-card-preview'" not in response.text
    assert find_claims(_visible(response.text)) == []


def test_limit_is_per_ip_expires_and_does_not_trust_spoofed_forwarding(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = datetime(2026, 10, 7, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)

    assert client.app.state.settings.trusted_proxy_hops == 0
    monkeypatch.setattr("quant_trade.audit.web.datetime", Clock)
    monkeypatch.setattr(reading, "MAX_REQUESTS_PER_HOUR", 2)
    first = TestClient(client.app, client=("192.0.2.1", 50000))
    second = TestClient(client.app, client=("192.0.2.2", 50000))
    assert first.get("/lectura", params=FIGURES).status_code == 200
    assert first.get("/en/reading", params=FIGURES).status_code == 200
    blocked = first.get("/lectura", params=FIGURES, headers={"X-Forwarded-For": "192.0.2.99"})
    assert blocked.status_code == 429
    assert second.get("/lectura", params=FIGURES).status_code == 200
    current += timedelta(hours=1, seconds=1)
    assert first.get("/lectura", params=FIGURES).status_code == 200


def test_sixty_per_hour_limit_covers_invalid_downloads_and_all_languages(
    client: TestClient,
) -> None:
    # Opening the form, even with a campaign tag, does not spend the generation limit.
    for _ in range(61):
        assert client.get("/lectura", params={"ref": "lectura"}).status_code == 200
    for index in range(60):
        path = reading.READING_PATH[LOCALES[index % len(LOCALES)]]
        if index % 3 == 0:
            params = {**FIGURES, "sharpe": "nan"}
            expected_status = 400
        else:
            params = {**FIGURES, **({"download": "svg"} if index % 3 == 1 else {})}
            expected_status = 200
        assert client.get(path, params=params).status_code == expected_status
    for locale in LOCALES:
        blocked = client.get(reading.READING_PATH[locale], params=FIGURES)
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "3600"
        assert reading.COPY[locale]["limited"] in _visible(blocked.text)
        assert find_claims(_visible(blocked.text)) == []
    assert client.get("/lectura").status_code == 200


@pytest.mark.parametrize("locale", LOCALES)
def test_public_metadata_footer_and_sitemap_include_all_languages(
    client: TestClient, locale: str
) -> None:
    assert dict(reading.READING_PATH) in PUBLIC_PAGES
    assert "lectura" in funnel.REF_TAGS
    path = reading.READING_PATH[locale]
    response = client.get(path)
    assert "x-robots-tag" not in response.headers
    assert f"<link rel='canonical' href='{BASE}{path}'>" in response.text
    assert "<meta name='robots' content='index, follow'>" in response.text
    for lang, alternate in reading.READING_PATH.items():
        assert f"hreflang='{lang}' href='{BASE}{alternate}'" in response.text
    footer = response.text.split("<footer", 1)[1].split("</footer>", 1)[0]
    assert path in _links(footer)
    assert EXAMPLES_PATH[locale] in _links(footer)
    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "h": "http://www.w3.org/1999/xhtml"}
    root = ET.fromstring(sitemap.text)
    nodes = {node.findtext("s:loc", namespaces=ns): node for node in root.findall("s:url", ns)}
    assert BASE + path in nodes
    alternates = {
        link.attrib["hreflang"]: link.attrib["href"]
        for link in nodes[BASE + path].findall("h:link", ns)
    }
    assert alternates == {
        **{lang: BASE + value for lang, value in reading.READING_PATH.items()},
        "x-default": BASE + reading.READING_PATH["es"],
    }


def test_generation_does_not_use_network_database_or_create_files(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Public reading must not fetch or use the database")

    store = client.app.state.store
    monkeypatch.setattr(store.engine, "begin", forbidden)
    monkeypatch.setattr(store.engine, "connect", forbidden)
    # A visit to a free tool is counted in memory (privacy policy): day, language and tag only.
    counted: list[dict[str, str]] = []
    monkeypatch.setattr(client.app.state.visits, "add", lambda **kw: counted.append(kw))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    for locale in LOCALES:
        for download in ({}, {"download": "svg"}):
            response = client.get(
                reading.READING_PATH[locale],
                params={**FIGURES, **download, "ref": "lectura"},
            )
            assert response.status_code == 200
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert all(set(visit) == {"day", "locale", "ref"} for visit in counted)
    assert not {value for visit in counted for value in visit.values()} & set(FIGURES.values())
