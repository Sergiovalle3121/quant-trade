"""Tool previews use a finite, anonymous in-memory catalogue in every language."""

from __future__ import annotations

import builtins
import html
import re
import socket
import struct
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import (  # noqa: E402
    challenge_calc,
    raster,
    ruin_calc,
    rules_table,
    tool_cards,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import spanish  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tool_cards import (  # noqa: E402
    FAILURE_TTL,
    TOOL_KINDS,
    ToolPNGCache,
    tool_card_svg,
    tool_image_path,
)
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
CARDS = (
    ("calculadora-reto", ""),
    *(("calculadora-reto", firm) for firm in challenge_calc.FIRMS),
    ("calculadora-ruina", ""),
    ("reglas-prop-firm", ""),
)
MOCK_PNG = b"server-generated tool PNG"
FORBIDDEN = re.compile(
    r"\b(aprobar\w*|aprobad\w*|pasar|pasas?|pass|passed|passes|passing|aprovar\w*|aprovad\w*|"
    r"verific\w*|verified|certificad\w*|certified|garantiza\w*|guarantee\w*|garantid\w*|"
    r"rentables?|profitable|lucrativ\w*|approved)\b",
    re.IGNORECASE,
)
AFFILIATION = {
    "es": "Rigor no está afiliado",
    "en": "Rigor is not affiliated",
    "pt": "A Rigor não é afiliada",
}


class _Clock:
    """A manual monotonic clock for the cache's short memory of failures."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _image_path(kind: str, locale: str, firm: str = "") -> str:
    prefix = "" if locale == "es" else f"/{locale}"
    suffix = f"-{firm}" if firm else ""
    return f"{prefix}/og/{kind}{suffix}.png"


def _page_path(kind: str, locale: str, firm: str = "") -> str:
    if kind == "calculadora-reto":
        return challenge_calc.challenge_url(locale, firm)
    if kind == "calculadora-ruina":
        return ruin_calc.RUIN_PATH[locale]
    return rules_table.RULES_TABLE_PATH[locale]


def _meta(page: str, name: str) -> str:
    found = re.search(
        rf"<meta (?:property|name)=['\"]{re.escape(name)}['\"] content=['\"]([^'\"]*)",
        page,
    )
    assert found is not None, name
    return html.unescape(found.group(1))


def _assert_png(png: bytes) -> None:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert png[12:16] == b"IHDR"
    assert struct.unpack(">II", png[16:24]) == (1200, 630)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _forbid_external_io(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Tool OG requests must not use the database or network")

    monkeypatch.setattr(client.app.state.store.engine, "begin", forbidden)
    monkeypatch.setattr(client.app.state.store.engine, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture(scope="module")
def shared_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        client = _client(tmp_path_factory.mktemp("tool-og"), monkeypatch)
        yield client
        client.close()
        client.app.state.store.engine.dispose()


@pytest.fixture
def client(shared_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _forbid_external_io(shared_client, monkeypatch)
    return shared_client


@pytest.mark.parametrize("locale", LOCALES)
def test_og_catalogue_has_stable_paths_and_safe_localized_svg(locale: str) -> None:
    assert len(challenge_calc.FIRMS) == 16
    assert TOOL_KINDS == ("calculadora-reto", "calculadora-ruina", "reglas-prop-firm")
    assert len(CARDS) * len(LOCALES) == 57
    for kind, firm in CARDS:
        assert tool_image_path(kind, locale, firm) == _image_path(kind, locale, firm)
        svg = tool_card_svg(kind, locale, firm)
        root = ET.fromstring(svg)
        assert root.attrib["width"] == "1200"
        assert root.attrib["height"] == "630"
        assert root.attrib["viewBox"] == "0 0 1200 630"
        assert root.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == locale
        assert root.attrib["role"] == "img"
        text = " ".join(" ".join(root.itertext()).split())
        assert find_claims(text) == [], (kind, locale, firm)
        assert FORBIDDEN.search(text) is None, (kind, locale, firm)
        assert "<image" not in svg and "href=" not in svg and "@import" not in svg
        if firm:
            assert challenge_calc.FIRMS[firm] in text
            assert AFFILIATION[locale] in text
        elif kind == "calculadora-reto" and locale == "es":
            assert "Calculadora de reto de prop firm" in text
            assert "16 firmas, reglas con fuente y fecha" in text


def test_og_english_notices_have_their_spanish_rules() -> None:
    notices = (
        ("calculadora-reto", "", "Research tool · Not a forecast"),
        ("reglas-prop-firm", "", "Consult each firm's current rules"),
        ("calculadora-reto", "ftmo", "Rigor is not affiliated"),
    )
    for kind, firm, notice in notices:
        english = " ".join(ET.fromstring(tool_card_svg(kind, "en", firm)).itertext())
        translated = " ".join(ET.fromstring(tool_card_svg(kind, "es", firm)).itertext())
        assert notice in english
        spanish_notice = spanish(notice)
        assert spanish_notice is not None and spanish_notice != notice
        assert spanish_notice in translated


@pytest.mark.parametrize("locale", LOCALES)
def test_og_every_route_returns_its_real_png_at_social_dimensions(
    client: TestClient, locale: str
) -> None:
    try:
        pytest.importorskip("cairosvg")
    except OSError as exc:
        pytest.skip(f"CairoSVG native library is unavailable: {exc}")
    default = client.get(f"/static/og-{locale}.png").content
    for kind, firm in CARDS:
        path = _image_path(kind, locale, firm)
        response = client.get(path, params={"ref": "reto"})
        assert response.status_code == 200, path
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "public, max-age=86400"
        assert "set-cookie" not in response.headers
        assert "content-disposition" not in response.headers
        _assert_png(response.content)
        # A working route cannot silently satisfy this test with the fallback.
        assert response.content != default, path
        assert response.content == raster.card_png(tool_card_svg(kind, locale, firm)), path


@pytest.mark.parametrize("locale", LOCALES)
def test_og_every_page_points_both_previews_to_its_own_card(
    client: TestClient, locale: str
) -> None:
    for kind, firm in CARDS:
        path = _page_path(kind, locale, firm)
        page = client.get(path, headers={"User-Agent": "Twitterbot/1.0"})
        assert page.status_code == 200, path
        image = BASE + _image_path(kind, locale, firm)
        assert _meta(page.text, "og:image") == image, path
        assert _meta(page.text, "twitter:image") == image, path
        assert _meta(page.text, "twitter:card") == "summary_large_image"
        assert _meta(page.text, "og:image:width") == "1200"
        assert _meta(page.text, "og:image:height") == "630"
        assert f"<link rel='canonical' href='{BASE}{path}'>" in page.text


def test_og_cache_is_bounded_by_the_catalogue_and_reuses_successful_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered: list[str] = []

    def render(svg: str) -> bytes:
        rendered.append(svg)
        return MOCK_PNG

    monkeypatch.setattr(raster, "card_png", render)
    cache = ToolPNGCache()
    for _ in range(2):
        for locale in LOCALES:
            for kind, firm in CARDS:
                assert cache.get(kind, locale, firm) is MOCK_PNG
    assert len(rendered) == 57
    assert len(cache) == 57
    for kind, locale, firm in (
        ("unknown", "es", ""),
        ("calculadora-reto", "fr", ""),
        ("calculadora-reto", "es", "unknown"),
        ("calculadora-ruina", "es", "ftmo"),
        ("reglas-prop-firm", "es", "ftmo"),
        ("calculadora-reto", "es", "<svg onload='alert(1)'>"),
    ):
        with pytest.raises(ValueError):
            cache.get(kind, locale, firm)
    assert len(cache) == len(rendered) == 57


def test_og_queries_do_not_render_new_cards_write_files_or_set_cookies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered: list[str] = []

    def render(svg: str) -> bytes:
        rendered.append(svg)
        return MOCK_PNG

    monkeypatch.setattr(raster, "card_png", render)
    client = _client(tmp_path, monkeypatch)
    _forbid_external_io(client, monkeypatch)
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Tool OG requests must not count visits or read image files")

    monkeypatch.setattr(client.app.state.visits, "add", forbidden)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    with monkeypatch.context() as no_files:
        no_files.setattr(Path, "read_bytes", forbidden)
        for locale in LOCALES:
            for kind, firm in CARDS:
                path = _image_path(kind, locale, firm)
                for params in (
                    {},
                    {"ref": "reto", "lang": "fr", "firm": "unknown", "win_rate": "99"},
                    {"text": "<script>alert(1)</script>", "source_url": "https://invalid.test"},
                ):
                    response = client.get(path, params=params)
                    assert response.status_code == 200, path
                    assert response.content == MOCK_PNG
                    assert "set-cookie" not in response.headers
    after = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert after == before
    assert len(rendered) == 57
    client.close()
    client.app.state.store.engine.dispose()


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("failure", ("missing_import", "conversion_error"))
def test_og_renderer_failure_serves_default_from_memory_and_can_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str, failure: str
) -> None:
    clock = _Clock()
    monkeypatch.setattr(tool_cards, "ToolPNGCache", lambda: ToolPNGCache(clock=clock))
    client = _client(tmp_path, monkeypatch)
    default = client.get(f"/static/og-{locale}.png").content
    _assert_png(default)
    _forbid_external_io(client, monkeypatch)
    original_import = builtins.__import__

    def without_cairo(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "cairosvg":
            raise ImportError("optional CairoSVG is absent")
        return original_import(name, globals, locals, fromlist, level)

    def failed_conversion(*args: object, **kwargs: object) -> bytes:
        raise RuntimeError("optional CairoSVG conversion failed")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("The fallback must already be in memory")

    attempts: list[str] = []
    real_card_png = raster.card_png

    def counted(svg: str) -> bytes | None:
        attempts.append(svg)
        return real_card_png(svg)

    with monkeypatch.context() as renderer_failure:
        renderer_failure.setattr(raster, "card_png", counted)
        if failure == "missing_import":
            renderer_failure.setattr(builtins, "__import__", without_cairo)
        else:
            try:
                cairo = pytest.importorskip("cairosvg")
            except OSError as exc:
                pytest.skip(f"CairoSVG native library is unavailable: {exc}")
            renderer_failure.setattr(cairo, "svg2png", failed_conversion)
        renderer_failure.setattr(Path, "read_bytes", forbidden)
        for kind, firm in CARDS:
            path = _image_path(kind, locale, firm)
            response = client.get(path, params={"ref": "reto"}, follow_redirects=False)
            assert response.status_code == 200, path
            assert response.headers["content-type"] == "image/png"
            assert response.content == default
            assert response.headers["cache-control"] == "no-store"
            assert "set-cookie" not in response.headers
            page = client.get(_page_path(kind, locale, firm))
            assert page.status_code == 200
            assert _meta(page.text, "og:image") == BASE + path
            assert _meta(page.text, "twitter:image") == BASE + path
    # One failed attempt covers the whole window; the rest never retry the import.
    assert len(attempts) == 1
    monkeypatch.setattr(raster, "card_png", lambda svg: MOCK_PNG)
    remembered = client.get(_image_path("calculadora-ruina", locale))
    assert remembered.content == default
    assert remembered.headers["cache-control"] == "no-store"
    clock.now += FAILURE_TTL
    for kind, firm in CARDS:
        recovered = client.get(_image_path(kind, locale, firm))
        assert recovered.status_code == 200
        assert recovered.content == MOCK_PNG
        assert recovered.headers["cache-control"] == "public, max-age=86400"
    client.close()
    client.app.state.store.engine.dispose()


@pytest.mark.parametrize("locale", LOCALES)
def test_og_unknown_names_are_not_dynamic_renderer_inputs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    def forbidden(svg: str) -> bytes:
        raise AssertionError("An unknown OG name must never reach the renderer")

    monkeypatch.setattr(raster, "card_png", forbidden)
    for kind, firm in (
        ("unknown", ""),
        ("calculadora-reto", "unknown"),
        ("calculadora-ruina", "ftmo"),
        ("reglas-prop-firm", "ftmo"),
    ):
        response = client.get(_image_path(kind, locale, firm))
        assert response.status_code == 404


def test_og_failed_render_is_remembered_briefly_then_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    outcomes: list[bytes | None] = [None]
    attempts: list[str] = []

    def render(svg: str) -> bytes | None:
        attempts.append(svg)
        return outcomes[-1]

    monkeypatch.setattr(raster, "card_png", render)
    cache = ToolPNGCache(clock=clock)
    for locale in LOCALES:
        for kind, firm in CARDS:
            assert cache.get(kind, locale, firm) is None
    assert len(attempts) == 1
    assert len(cache) == 0
    clock.now += FAILURE_TTL / 2
    assert cache.get("calculadora-ruina", "es") is None
    assert len(attempts) == 1
    clock.now += FAILURE_TTL / 2
    assert cache.get("calculadora-ruina", "es") is None
    assert len(attempts) == 2
    # Recovery needs no reset: once the window elapses, a working renderer is used.
    outcomes.append(MOCK_PNG)
    clock.now += FAILURE_TTL
    assert cache.get("calculadora-ruina", "es") is MOCK_PNG
    assert len(attempts) == 3
    assert len(cache) == 1
    # A success forgets the failure, and cached cards never depend on the memory.
    outcomes.append(None)
    assert cache.get("reglas-prop-firm", "en") is None
    assert cache.get("calculadora-ruina", "es") is MOCK_PNG
    assert len(attempts) == 4
    with pytest.raises(ValueError):
        ToolPNGCache(failure_ttl=-1.0)
    retry_always = ToolPNGCache(failure_ttl=0.0, clock=clock)
    assert retry_always.get("calculadora-reto", "pt") is None
    assert retry_always.get("calculadora-reto", "pt", "ftmo") is None
    assert len(attempts) == 6


def test_og_catalogue_wording_is_checked_when_the_app_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    monkeypatch.setattr(tool_cards, "find_claims", lambda text: [{"pattern": "x"}])
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    store = make_store(settings.database_url)
    try:
        with pytest.raises(ValueError, match="unsupported wording"):
            create_app(settings, store)
    finally:
        store.engine.dispose()


def test_og_guard_disagreement_at_request_time_serves_default_not_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    defaults = {locale: client.get(f"/static/og-{locale}.png").content for locale in LOCALES}
    _forbid_external_io(client, monkeypatch)

    def forbidden(svg: str) -> bytes:
        raise AssertionError("Rejected wording must never reach the renderer")

    with monkeypatch.context() as guard_hit:
        guard_hit.setattr(tool_cards, "find_claims", lambda text: [{"pattern": "x"}])
        guard_hit.setattr(raster, "card_png", forbidden)
        for locale in LOCALES:
            for kind, firm in CARDS:
                path = _image_path(kind, locale, firm)
                response = client.get(path, params={"ref": "reto"})
                assert response.status_code == 200, path
                assert response.headers["content-type"] == "image/png"
                assert response.content == defaults[locale]
                assert response.headers["cache-control"] == "no-store"
                assert "set-cookie" not in response.headers
    monkeypatch.setattr(raster, "card_png", lambda svg: MOCK_PNG)
    recovered = client.get(_image_path("calculadora-ruina", "es"))
    assert recovered.status_code == 200
    assert recovered.content == MOCK_PNG
    assert recovered.headers["cache-control"] == "public, max-age=86400"
    client.close()
    client.app.state.store.engine.dispose()
