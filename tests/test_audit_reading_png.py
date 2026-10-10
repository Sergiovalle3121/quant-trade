"""Reader link previews stay anonymous, bounded by the reader limit and memory-only."""

from __future__ import annotations

import builtins
import html
import re
import socket
import struct
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import raster, reading  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import spanish  # noqa: E402
from quant_trade.audit.public_card import public_card_svg  # noqa: E402
from quant_trade.audit.reading_png import _social_svg  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
FIGURES = {
    "trades": "45",
    "win_rate": "71.12345678901234",
    "profit_factor": "3.2400",
    "sharpe": "1.8",
    "years": "3",
    "trials": "1000",
    "target_r": "1",
    "stop_r": "1",
}
MOCK_PNG = b"mocked server-generated PNG"


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(raster, "card_png", lambda svg: MOCK_PNG)
    return _client(tmp_path, monkeypatch)


def _meta(page: str, name: str) -> str:
    found = re.search(
        rf"<meta (?:property|name)=['\"]{re.escape(name)}['\"] content=['\"]([^'\"]*)",
        page,
    )
    assert found is not None, name
    return html.unescape(found.group(1))


@pytest.mark.parametrize("locale", LOCALES)
def test_png_route_has_public_cache_headers_without_referral_cookie(
    client: TestClient, locale: str
) -> None:
    response = client.get(
        reading.READING_PATH[locale] + "/card.png", params={**FIGURES, "ref": "lectura"}
    )
    assert response.status_code == 200
    assert response.content == MOCK_PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert "content-disposition" not in response.headers
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("locale", LOCALES)
def test_png_card_uses_the_languages_decimal_mark_but_its_address_keeps_the_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    rendered: list[str] = []

    def capture(svg: str) -> bytes:
        rendered.append(svg)
        return MOCK_PNG

    monkeypatch.setattr(raster, "card_png", capture)
    client = _client(tmp_path, monkeypatch)
    figures = {**FIGURES, "win_rate": "71"}
    path = reading.READING_PATH[locale]
    response = client.get(path + "/card.png", params=figures)
    assert response.status_code == 200
    assert response.content == MOCK_PNG
    assert len(rendered) == 1
    # The rasterised SVG is what the picture shows: the card in the page's typography.
    text = " ".join(ET.fromstring(rendered[0]).itertext())
    mark, other = (".", ",") if locale == "en" else (",", ".")
    assert f"56{mark}5 % – 82{mark}2 %" in text
    assert f"71{mark}0 %" in text and f"3{mark}24" in text
    assert f"56{other}5 %" not in text and f"3{other}24" not in text
    page = client.get(path, params=figures)
    image = urlsplit(_meta(page.text, "og:image"))
    assert image.path == path + "/card.png"
    assert parse_qs(image.query) == {name: [value] for name, value in figures.items()}


@pytest.mark.parametrize("locale", LOCALES)
def test_valid_page_previews_exact_figures_and_excludes_other_query_fields(
    client: TestClient, locale: str
) -> None:
    path = reading.READING_PATH[locale]
    response = client.get(
        path,
        params={
            **FIGURES,
            "sharpe": " 1.8 ",
            "ref": "lectura",
            "source_handle": "<script>untrusted</script>",
            "source_url": "https://someone-else.example/",
            "locale": "fr",
            "lang": "fr",
        },
    )
    assert response.status_code == 200
    image_url = _meta(response.text, "og:image")
    image = urlsplit(image_url)
    assert image.scheme + "://" + image.netloc == BASE
    assert image.path == path + "/card.png"
    assert parse_qs(image.query, keep_blank_values=True) == {
        name: [value] for name, value in FIGURES.items()
    }
    assert _meta(response.text, "twitter:image") == image_url
    assert _meta(response.text, "twitter:card") == "summary_large_image"
    assert _meta(response.text, "og:image:width") == "1200"
    assert _meta(response.text, "og:image:height") == "630"
    assert client.get(image_url).content == MOCK_PNG
    assert "someone-else.example" not in response.text
    assert "<script>untrusted" not in response.text


@pytest.mark.parametrize("locale", LOCALES)
def test_form_keeps_static_image_and_empty_figures_have_reproducible_preview(
    client: TestClient, locale: str
) -> None:
    path = reading.READING_PATH[locale]
    for params in ({}, {"ref": "lectura"}):
        form = client.get(path, params=params)
        assert form.status_code == 200
        assert _meta(form.text, "og:image") == f"{BASE}/static/og-{locale}.png"
    values = {name: "" for name in FIGURES}
    page = client.get(path, params=values)
    assert page.status_code == 200
    image_url = _meta(page.text, "og:image")
    assert urlsplit(image_url).path == path + "/card.png"
    assert parse_qs(urlsplit(image_url).query, keep_blank_values=True) == {
        name: [""] for name in FIGURES
    }
    assert client.get(image_url).content == MOCK_PNG


@pytest.mark.parametrize("locale", LOCALES)
def test_invalid_png_parameters_return_empty_404(client: TestClient, locale: str) -> None:
    invalid = (
        ("trades", "0"),
        ("trades", "3.5"),
        ("trades", "10000001"),
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
        ("download", ""),
        ("download", "png"),
    )
    path = reading.READING_PATH[locale] + "/card.png"
    for params in ({}, {"ref": "lectura"}, *({**FIGURES, k: v} for k, v in invalid)):
        response = client.get(path, params=params)
        assert response.status_code == 404, params
        assert response.content == b""
    for field in (*FIGURES, "download"):
        params = [*FIGURES.items(), (field, "svg"), (field, "svg")]
        response = client.get(path, params=params)
        assert response.status_code == 404, field
        assert response.content == b""


@pytest.mark.parametrize("locale", LOCALES)
def test_renderer_failure_leaves_page_available_with_static_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    monkeypatch.setattr(raster, "card_png", lambda svg: None)
    client = _client(tmp_path, monkeypatch)
    path = reading.READING_PATH[locale]
    page = client.get(path, params=FIGURES)
    assert page.status_code == 200
    assert "class='public-card-preview'" in page.text
    assert _meta(page.text, "og:image") == f"{BASE}/static/og-{locale}.png"
    response = client.get(path + "/card.png", params=FIGURES)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == reading.COPY[locale]["png_unavailable"]
    assert find_claims(response.text) == []
    assert "public" not in response.headers.get("cache-control", "")
    # A temporary render failure cannot poison the cache until a process restart.
    monkeypatch.setattr(raster, "card_png", lambda svg: MOCK_PNG)
    assert client.get(path + "/card.png", params=FIGURES).content == MOCK_PNG


@pytest.mark.parametrize("locale", LOCALES)
def test_missing_cairosvg_import_returns_503_and_keeps_page_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    original_import = builtins.__import__

    def without_cairo(name: str, *args: object, **kwargs: object) -> object:
        if name == "cairosvg":
            raise ImportError("optional CairoSVG is absent")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_cairo)
    client = _client(tmp_path, monkeypatch)
    path = reading.READING_PATH[locale]
    response = client.get(path + "/card.png", params=FIGURES)
    assert response.status_code == 503
    page = client.get(path, params=FIGURES)
    assert page.status_code == 200
    assert _meta(page.text, "og:image") == BASE + f"/static/og-{locale}.png"
    assert reading.COPY[locale]["download"] in page.text
    assert reading.COPY[locale]["download_png"] not in page.text
    assert "data-copy='reading-share-link'" in page.text
    assert reading.COPY[locale]["copy_link"] in page.text


def test_new_png_notice_has_a_spanish_translation_and_passes_guard() -> None:
    assert spanish(reading.COPY["en"]["png_unavailable"]) == reading.COPY["es"]["png_unavailable"]
    for locale in LOCALES:
        assert find_claims(reading.COPY[locale]["png_unavailable"]) == []


def test_pages_svg_and_cached_png_share_the_limit_before_serving_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reading, "MAX_REQUESTS_PER_HOUR", 3)
    assert client.get("/lectura/card.png", params=FIGURES).status_code == 200
    assert client.get("/en/reading", params=FIGURES).status_code == 200
    assert client.get("/pt/leitura", params={**FIGURES, "download": "svg"}).status_code == 200
    for locale in LOCALES:
        blocked = client.get(reading.READING_PATH[locale] + "/card.png", params=FIGURES)
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "3600"
        assert reading.COPY[locale]["limited"] in html.unescape(blocked.text)
        assert find_claims(blocked.text) == []
    second_ip = TestClient(client.app, client=("192.0.2.2", 50000))
    assert second_ip.get("/lectura/card.png", params=FIGURES).status_code == 200
    assert client.get("/lectura").status_code == 200


def test_invalid_png_requests_consume_the_shared_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reading, "MAX_REQUESTS_PER_HOUR", 2)
    for locale in LOCALES[:2]:
        response = client.get(
            reading.READING_PATH[locale] + "/card.png", params={**FIGURES, "trades": "0"}
        )
        assert response.status_code == 404
    assert client.get("/pt/leitura", params=FIGURES).status_code == 429


def test_png_and_preview_generation_do_not_use_database_network_or_files(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Reader PNG must not use the database, network or files")

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
        path = reading.READING_PATH[locale]
        assert client.get(path, params=FIGURES).status_code == 200
        response = client.get(path + "/card.png", params={**FIGURES, "ref": "lectura"})
        assert response.status_code == 200
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert all(set(visit) == {"day", "locale", "ref"} for visit in counted)
    assert not {value for visit in counted for value in visit.values()} & set(FIGURES.values())


@pytest.mark.parametrize("locale", LOCALES)
def test_real_cairo_route_returns_png_with_og_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    try:
        pytest.importorskip("cairosvg")
    except OSError as exc:
        pytest.skip(f"CairoSVG native library is unavailable: {exc}")
    client = _client(tmp_path, monkeypatch)
    response = client.get(reading.READING_PATH[locale] + "/card.png", params=FIGURES)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.content[12:16] == b"IHDR"
    assert struct.unpack(">II", response.content[16:24]) == (1200, 630)
    svg = public_card_svg(reading.claim_from_query(FIGURES, locale))
    ns = {"s": "http://www.w3.org/2000/svg"}
    root = ET.fromstring(_social_svg(svg))
    card = root.find("s:svg", ns)
    assert card is not None
    footer = next(
        node
        for node in card.findall("s:text", ns)
        if node.text == "rigorscore.com" + reading.READING_PATH[locale]
    )
    scale = float(card.attrib["height"]) / float(card.attrib["viewBox"].split()[3])
    footer_bottom = float(card.attrib["y"]) + scale * (
        float(footer.attrib["y"]) + float(footer.attrib["font-size"])
    )
    assert 0 < footer_bottom < float(root.attrib["height"])
