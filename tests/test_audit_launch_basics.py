"""Launch basics: the icon files, which pages search engines may list, the
language of an error page and the address tags of the contact and legal pages."""

from __future__ import annotations

import fnmatch
import html
import importlib.util
import re
import struct
import tomllib
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, mail, seo  # noqa: E402
from quant_trade.audit.compare import COMPARE_PATH  # noqa: E402
from quant_trade.audit.pages import CONTACT_PATHS  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.theme import ICON_PATHS, STATIC_CACHE_CONTROL, STATIC_DIR  # noqa: E402
from quant_trade.audit.web import (  # noqa: E402
    CONTENT_SECURITY_POLICY,
    ENGLISH_ROOTS,
    MESSAGES,
    create_app,
    request_body_limit,
)

BASE = "https://audit.example"
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
LEGAL_AND_CONTACT = (
    {"es": "/terminos", "en": "/terms", "pt": "/pt/termos"},
    {"es": "/privacidad", "en": "/privacy", "pt": "/pt/privacidade"},
    dict(CONTACT_PATHS),
)


def _app(tmp_path: Path, **overrides: object):  # type: ignore[no-untyped-def]
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        **{"base_url": BASE, **overrides},  # type: ignore[arg-type]
    )
    return create_app(settings, make_store(settings.database_url))


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    return TestClient(_app(tmp_path, **overrides))


def _meta(text: str, key: str) -> str | None:
    match = re.search(rf"<meta (?:name|property)='{re.escape(key)}' content='([^']*)'>", text)
    return html.unescape(match.group(1)) if match else None


def _canonical(text: str) -> str | None:
    match = re.search(r"<link rel='canonical' href='([^']*)'>", text)
    return html.unescape(match.group(1)) if match else None


def test_the_icon_is_a_real_file_browsers_can_keep(tmp_path: Path) -> None:
    client = _client(tmp_path)
    icon = client.get("/favicon.ico")
    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/x-icon"
    assert icon.headers["cache-control"] == STATIC_CACHE_CONTROL
    assert icon.headers["x-content-type-options"] == "nosniff"
    assert "x-robots-tag" not in icon.headers
    reserved, kind, count = struct.unpack("<HHH", icon.content[:6])
    assert (reserved, kind, count) == (0, 1, 3)
    sizes = []
    for i in range(count):
        entry = icon.content[6 + 16 * i : 22 + 16 * i]
        width, height, _, _, planes, bits, length, offset = struct.unpack("<BBBBHHII", entry)
        assert width == height and (planes, bits) == (1, 32)
        # Each image is a bitmap header of 40 bytes, twice as tall (colour and mask).
        header = struct.unpack("<Iii", icon.content[offset : offset + 12])
        assert header == (40, width, 2 * height)
        assert offset + length <= len(icon.content)
        sizes.append(width)
    assert sizes == [16, 32, 48]

    touch = client.get("/apple-touch-icon.png")
    assert touch.status_code == 200
    assert touch.headers["content-type"] == "image/png"
    assert touch.headers["cache-control"] == STATIC_CACHE_CONTROL
    assert touch.content[:8] == b"\x89PNG\r\n\x1a\n" and touch.content[12:16] == b"IHDR"
    assert struct.unpack(">II", touch.content[16:24]) == (180, 180)

    head = client.head("/favicon.ico")
    assert head.status_code == 200 and head.headers["content-type"] == "image/x-icon"
    # Served from the allow-list: the files are the ones in static/.
    for path, name in ICON_PATHS.items():
        assert client.get(path).content == (STATIC_DIR / name).read_bytes()
        assert client.get(f"/static/{name}").status_code == 200


def test_the_icon_address_takes_nothing_from_the_request(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, name in ICON_PATHS.items():
        for query in ("icon_name=app.js", "name=app.js", "icon_name=nope"):
            response = client.get(f"{path}?{query}")
            assert response.status_code == 200, (path, query)
            assert response.content == (STATIC_DIR / name).read_bytes(), (path, query)
    assert client.get("/favicon.ico?icon_name=app.js").headers["content-type"] == "image/x-icon"


def test_a_short_address_forwards_to_its_own_page_only(tmp_path: Path) -> None:
    client = _client(tmp_path)
    elsewhere = "https://elsewhere.example/"
    for alias, target in (
        ("/soporte", "/contacto"),
        ("/contact", "/en/contact"),
        ("/support", "/en/contact"),
        ("/pt/suporte", "/pt/contato"),
        ("/precios", "/#pricing"),
        ("/pricing", "/en#pricing"),
        ("/pt/precos", "/pt#pricing"),
        ("/en/terms", "/terms?lang=en"),
        ("/pt/privacy", "/pt/privacidade"),
    ):
        for name in ("contact_path", "landing_path", "legal_path", "target", "next"):
            response = client.get(alias, params={name: elsewhere}, follow_redirects=False)
            assert response.status_code == 301, (alias, name)
            assert response.headers["location"] == target, (alias, name)


def test_the_icon_file_is_what_the_tool_draws() -> None:
    tool = Path(__file__).resolve().parents[1] / "tools" / "make_favicon.py"
    spec = importlib.util.spec_from_file_location("make_favicon", tool)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The bitmap is not compressed, so the bytes are the same on every machine.
    assert module.ico_bytes() == (STATIC_DIR / "favicon.ico").read_bytes()
    corner, centre = module.render(32)[0][0], module.render(16)[8][2]
    assert corner == (0, 0, 0, 0) and centre == (*module.BACKGROUND, 255)


def test_the_icon_files_are_packaged_with_the_service() -> None:
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(project.read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["quant_trade.audit"]
    for name in ICON_PATHS.values():
        assert any(fnmatch.fnmatch(f"static/{name}", pattern) for pattern in patterns), name


def test_pages_link_the_icons_within_the_content_policy(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert "img-src 'self' data:" in CONTENT_SECURITY_POLICY
    for path in ("/", "/en", "/pt", "/contacto", "/terms", "/pt/exemplo", "/nope"):
        text = client.get(path).text
        assert "<link rel='icon' href='/favicon.ico' sizes='16x16 32x32 48x48'>" in text, path
        assert (
            "<link rel='apple-touch-icon' sizes='180x180' href='/apple-touch-icon.png'>" in text
        ), path
        # The inline mark stays for the browsers that take it.
        assert "<link rel='icon' type='image/svg+xml' href=\"data:image/svg+xml," in text, path


def test_the_old_address_forwards_the_icons_to_the_domain(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path), base_url="https://rigor.up.railway.app")
    for path in ICON_PATHS:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"] == BASE + path


def test_the_portuguese_contact_page_is_public_and_the_account_stays_private(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    contact = client.get("/pt/contato")
    assert contact.status_code == 200
    assert "x-robots-tag" not in contact.headers
    assert _meta(contact.text, "robots") == "index, follow"
    for private in ("/pt/conta", "/pt/conta/datos", "/pt/conta?x=1", "/pt/entrar"):
        response = client.get(private, follow_redirects=False)
        assert response.headers.get("x-robots-tag") == seo.NOINDEX, private

    assert not seo.is_private_path("/pt/contato")
    assert seo.is_private_path("/pt/conta") and seo.is_private_path("/pt/conta/datos")
    assert seo.is_private_path("/audits/abc") and seo.is_private_path("/health")
    assert not seo.is_private_path("/") and not seo.is_private_path("/pt")

    lines = client.get("/robots.txt").text.splitlines()
    assert "Allow: /pt/contato" in lines
    assert "Disallow: /pt/conta" in lines
    # The longer rule wins, and it also comes first for a crawler that reads in order.
    assert lines.index("Allow: /pt/contato") < lines.index("Disallow: /pt/conta")
    assert len("/pt/contato") > len("/pt/conta")
    assert [line for line in lines if line.startswith("Allow: ")] == [
        "Allow: /pt/contato",
        "Allow: /",
    ]
    for path in seo.DISALLOWED_PATHS:
        assert f"Disallow: {path}" in lines, path


def test_no_other_route_is_caught_by_a_private_prefix(tmp_path: Path) -> None:
    app = _app(tmp_path)
    routes = sorted({route.path for route in app.routes if hasattr(route, "path")})
    assert "/pt/contato" in routes and "/pt/conta" in routes
    caught = [
        path
        for path in routes
        if path.startswith(seo.DISALLOWED_PATHS) and not seo.is_private_path(path)
    ]
    assert caught == ["/pt/contato"]
    public = {path for pair in seo.PUBLIC_PAGES for path in pair.values()}
    assert not [path for path in public if seo.is_private_path(path)]


def test_comparison_and_confirmation_pages_carry_the_noindex_header(tmp_path: Path) -> None:
    confirm = {mail.PATHS[locale]["verify"] for locale in mail.PATHS}
    assert set(seo.NOINDEX_PATHS) == set(COMPARE_PATH.values()) | confirm
    client = _client(tmp_path)
    robots = client.get("/robots.txt").text.splitlines()
    for path in COMPARE_PATH.values():
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("x-robots-tag") == seo.NOINDEX, path
        assert _meta(response.text, "robots") == seo.NOINDEX, path
    for path in sorted(confirm):
        response = client.get(path, follow_redirects=False)
        assert response.headers.get("x-robots-tag") == seo.NOINDEX, path
    for path in seo.NOINDEX_PATHS:
        # Not closed in robots.txt: a crawler has to reach the page to read the header.
        assert f"Disallow: {path}" not in robots, path
    # The public check page next to them stays listed.
    assert "x-robots-tag" not in client.get("/comprobar").headers


@pytest.mark.parametrize(
    ("path", "locale"),
    [
        ("/no-existe", "es"),
        ("/guias/no-existe", "es"),
        ("/para/no-existe", "es"),
        ("/en/nothing", "en"),
        ("/en/audit/nothing", "en"),
        ("/guides/nothing", "en"),
        ("/for/nothing", "en"),
        ("/sample/nothing", "en"),
        ("/terms/nothing", "en"),
        ("/privacy/nothing", "en"),
        ("/check/nothing", "en"),
        ("/methodology/nothing", "en"),
        ("/login/nothing", "en"),
        ("/signup/nothing", "en"),
        ("/account/nothing", "en"),
        ("/pt/nada", "pt"),
        ("/pt/guias/nada", "pt"),
        # Under a short address that forwards to a page: the language of that page.
        ("/support/nothing", "en"),
        ("/contact/nothing", "en"),
        ("/pricing/nothing", "en"),
        ("/soporte/nada", "es"),
        ("/precios/nada", "es"),
        # The query still decides.
        ("/en/nothing?lang=es", "es"),
        ("/guides/nothing?lang=pt", "pt"),
        ("/no-existe?lang=en", "en"),
        ("/pt/nada?lang=es", "es"),
    ],
)
def test_a_missing_page_answers_in_the_language_of_its_address(
    tmp_path: Path, path: str, locale: str
) -> None:
    response = _client(tmp_path).get(path)
    assert response.status_code == 404
    assert f"<html lang='{locale}'>" in response.text
    # An unknown address is a missing page; an unknown guide or case uses the
    # route's own 404 sentence. Either way in the language of the address.
    sentences = [MESSAGES[key][locale] for key in ("page_missing", "not_found")]
    assert any(html.escape(text, quote=True) in response.text for text in sentences)
    assert response.headers["x-robots-tag"] == seo.NOINDEX


def test_the_english_addresses_come_from_the_route_tables() -> None:
    expected = {"en", "guides", "for", "sample", "terms", "privacy", "check", "login", "signup"}
    assert expected <= ENGLISH_ROOTS
    for english in account_pages.PATHS["en"].values():
        assert english.split("/")[1] in ENGLISH_ROOTS
    # Nothing Spanish or Portuguese, and not the addresses with no language.
    for other in ("", "pt", "guias", "para", "ejemplo", "entrar", "cuenta", "audits", "v"):
        assert other not in ENGLISH_ROOTS, other


def test_other_errors_follow_the_address_too(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, locale in (("/en/contact", "en"), ("/contacto", "es"), ("/pt/contato", "pt")):
        response = client.post(path)
        assert response.status_code == 405
        assert f"<html lang='{locale}'>" in response.text


@pytest.mark.parametrize(
    ("path", "locale"),
    [
        ("/entrar", "es"),
        ("/login", "en"),
        ("/en/contact", "en"),
        ("/pt/entrar", "pt"),
        ("/login?lang=pt", "pt"),
        ("/pt/entrar?lang=es", "es"),
    ],
)
def test_a_body_over_the_limit_is_refused_in_the_language_of_the_address(
    tmp_path: Path, path: str, locale: str
) -> None:
    client = _client(tmp_path, max_upload_bytes=1024)
    body = b"x" * (request_body_limit(1024) + 1)
    response = client.post(path, content=body, headers={"content-type": "text/plain"})
    assert response.status_code == 413
    assert f"<html lang='{locale}'>" in response.text
    assert response.headers["x-robots-tag"] == seo.NOINDEX


def test_contact_and_portuguese_legal_pages_have_address_tags_and_are_in_the_sitemap(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    root = ElementTree.fromstring(client.get("/sitemap.xml").content)
    locs = [loc.text for loc in root.findall("s:url/s:loc", SITEMAP_NS)]
    assert len(locs) == len(set(locs))
    for pair in LEGAL_AND_CONTACT:
        assert pair in seo.PUBLIC_PAGES
        for locale, path in pair.items():
            assert BASE + path in locs, path
            response = client.get(path)
            assert response.status_code == 200, path
            assert "x-robots-tag" not in response.headers, path
            text = response.text
            assert f"<html lang='{locale}'>" in text, path
            assert _meta(text, "robots") == "index, follow", path
            assert _canonical(text) == BASE + path, path
            assert _meta(text, "og:url") == BASE + path, path
            for other, other_path in pair.items():
                link = f"<link rel='alternate' hreflang='{other}' href='{BASE}{other_path}'>"
                assert link in text, (path, other)
            default = f"<link rel='alternate' hreflang='x-default' href='{BASE}{pair['es']}'>"
            assert default in text, path


def test_the_sample_title_uses_the_word_of_its_language(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, word in (("/ejemplo", "ejemplo"), ("/sample", "sample"), ("/pt/exemplo", "exemplo")):
        text = client.get(path).text
        title = re.search(r"<title>([^<]+)</title>", text)
        assert title is not None, path
        assert title.group(1).endswith(f" · {word}"), (path, title.group(1))
        if word != "sample":
            assert "sample" not in title.group(1), path
        assert text.count("<title>") == 1
