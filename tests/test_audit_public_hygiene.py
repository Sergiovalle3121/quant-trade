"""Offline SEO and accessibility crawl of every indexed public translation."""

from __future__ import annotations

import html
import json
import socket
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from httpx import Response  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.seo import LOCALES, PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE_URL = "https://hygiene.example"
PUBLIC_URLS = [
    (locale, path) for translations in PUBLIC_PAGES for locale, path in translations.items()
]
PAGE_CASES = [pytest.param(locale, path, id=path) for locale, path in PUBLIC_URLS]
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class PublicHTML(HTMLParser):
    """Read rendered markup, including decoded attribute and title entities."""

    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=True)
        self.languages: list[str | None] = []
        self.headings: list[int] = []
        self.titles: list[str] = []
        self.descriptions: list[str] = []
        self.canonicals: list[str] = []
        self.alternates: list[tuple[str, str]] = []
        self.images: list[dict[str, str | None]] = []
        self.hrefs: list[str] = []
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self._in_head = False
        self._in_title = False
        self._in_script = False
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        if href.startswith("/"):
            self.hrefs.append(href)
        if tag == "head":
            self._in_head = True
        elif tag == "html":
            self.languages.append(attributes.get("lang"))
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append(int(tag[1]))
        elif tag == "title" and self._in_head:
            self.titles.append("")
            self._in_title = True
        elif (
            tag == "meta"
            and self._in_head
            and (attributes.get("name") or "").lower() == "description"
        ):
            self.descriptions.append(attributes.get("content") or "")
        elif tag == "link" and self._in_head:
            relations = (attributes.get("rel") or "").lower().split()
            if "canonical" in relations:
                self.canonicals.append(href)
            if "alternate" in relations and "hreflang" in attributes:
                self.alternates.append((attributes.get("hreflang") or "", href))
        elif tag == "img":
            self.images.append(attributes)
        elif tag == "script":
            self.scripts.append((attributes, ""))
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        elif tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.titles[-1] += data
        if self._in_script:
            attributes, content = self.scripts[-1]
            self.scripts[-1] = (attributes, content + data)


@dataclass
class PublicSite:
    client: TestClient
    responses: dict[str, Response] = field(default_factory=dict)
    pages: dict[str, PublicHTML] = field(default_factory=dict)

    def get(self, href: str) -> Response:
        url = urldefrag(urljoin(BASE_URL, href))[0]
        assert urlsplit(url).netloc == urlsplit(BASE_URL).netloc, href
        assert urlsplit(url).scheme == "https", href
        if url not in self.responses:
            self.responses[url] = self.client.get(url, follow_redirects=False)
        return self.responses[url]


@pytest.fixture(scope="module")
def public_site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PublicSite]:
    directory = tmp_path_factory.mktemp("public-hygiene")
    settings = AuditSettings(database_url=f"sqlite:///{directory}/audit.db", base_url=BASE_URL)
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def local_connect(connection: socket.socket, address: object) -> None:
        # Windows/anyio use loopback socket pairs for their event loop.
        assert isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}, address
        return original_connect(connection, address)

    def local_getaddrinfo(host: str, *args: object, **kwargs: object) -> list:
        assert host in {"localhost", "127.0.0.1", "::1"}, host
        return original_getaddrinfo(host, *args, **kwargs)

    def local_connect_ex(connection: socket.socket, address: object) -> int:
        assert isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}, address
        return original_connect_ex(connection, address)

    def refuse_download(*args: object, **kwargs: object) -> str:
        raise AssertionError("The public hygiene crawl must never download market data")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", local_connect)
        patch.setattr(socket.socket, "connect_ex", local_connect_ex)
        patch.setattr(socket, "getaddrinfo", local_getaddrinfo)
        patch.setattr("quant_trade.audit.market._download", refuse_download)
        # Exercise the linked PDF route, but leave native PDF rendering to its own suite.
        patch.setattr("quant_trade.audit.web.pdf_lib.report_pdf", lambda *a, **kw: b"%PDF-1.4\n")
        store = make_store(settings.database_url)
        client = TestClient(create_app(settings, store), base_url=BASE_URL)
        # Do not enter TestClient's lifespan: this crawl needs no worker threads.
        site = PublicSite(client)
        try:
            for _, path in PUBLIC_URLS:
                site.pages[path] = PublicHTML(site.get(path).text)
            yield site
        finally:
            client.close()
            store.engine.dispose()


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_response_and_language(public_site: PublicSite, locale: str, path: str) -> None:
    assert public_site.get(path).status_code == 200
    assert public_site.pages[path].languages == [locale]


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_heading_hierarchy(public_site: PublicSite, locale: str, path: str) -> None:
    headings = public_site.pages[path].headings
    assert headings.count(1) == 1, headings
    previous = 0
    for heading in headings:
        assert heading <= previous + 1, f"{path}: h{previous} jumps to h{heading}"
        previous = heading


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_metadata_lengths(public_site: PublicSite, locale: str, path: str) -> None:
    page = public_site.pages[path]
    assert len(page.titles) == len(page.descriptions) == 1
    title, description = page.titles[0].strip(), page.descriptions[0].strip()
    assert 15 <= len(title) <= 65, f"{len(title)} characters: {title}"
    assert 50 <= len(description) <= 160, f"{len(description)} characters: {description}"


@pytest.mark.parametrize("locale", LOCALES)
def test_public_metadata_is_unique_per_language(public_site: PublicSite, locale: str) -> None:
    for attribute in ("titles", "descriptions"):
        owners: dict[str, list[str]] = {}
        for language, path in PUBLIC_URLS:
            if language == locale:
                for text in getattr(public_site.pages[path], attribute):
                    owners.setdefault(" ".join(text.split()).casefold(), []).append(path)
        duplicates = {text: paths for text, paths in owners.items() if len(paths) > 1}
        assert not duplicates, (attribute, duplicates)


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_canonical_and_reciprocal_alternates(
    public_site: PublicSite, locale: str, path: str
) -> None:
    page = public_site.pages[path]
    assert page.canonicals == [BASE_URL + path]
    translations = next(paths for paths in PUBLIC_PAGES if paths.get(locale) == path)
    expected = {language: BASE_URL + target for language, target in translations.items()}
    expected["x-default"] = BASE_URL + translations["es"]
    assert len(page.alternates) == len(expected)
    assert dict(page.alternates) == expected
    for target in expected.values():
        assert public_site.get(target).status_code == 200
        other = public_site.pages[urlsplit(target).path]
        assert dict(other.alternates).get(locale) == BASE_URL + path


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_images_have_alt(public_site: PublicSite, locale: str, path: str) -> None:
    for attributes in public_site.pages[path].images:
        assert attributes.get("alt") is not None, attributes
        assert (attributes.get("alt") or "").strip() or attributes.get("role") == "presentation", (
            attributes
        )


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_internal_links_resolve(public_site: PublicSite, locale: str, path: str) -> None:
    for href in sorted(set(public_site.pages[path].hrefs)):
        response = public_site.get(href)
        assert response.status_code not in {404, 500}, (href, response.status_code)
        if 300 <= response.status_code < 400:
            assert "location" in response.headers, href
            target = urljoin(str(response.url), response.headers["location"])
            redirected = public_site.get(target)
            assert redirected.status_code not in {404, 500}, (href, target, redirected.status_code)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-JSON constant: {value}")


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_scripts_are_same_origin_and_json_ld_is_valid(
    public_site: PublicSite, locale: str, path: str
) -> None:
    for attributes, content in public_site.pages[path].scripts:
        if "src" in attributes:
            source = attributes.get("src") or ""
            assert source.strip(), attributes
            # The shared UI intentionally loads /static/app.js; third parties are forbidden.
            response = public_site.get(urljoin(BASE_URL + path, source))
            assert response.status_code == 200, source
        if (attributes.get("type") or "").lower() == "application/ld+json":
            json.loads(content, parse_constant=_reject_json_constant)


@pytest.mark.parametrize(("locale", "path"), PAGE_CASES)
def test_public_text_passes_profit_claim_guard(
    public_site: PublicSite, locale: str, path: str
) -> None:
    assert find_claims(html.unescape(public_site.get(path).text)) == []


def test_sitemap_matches_all_public_translations(public_site: PublicSite) -> None:
    assert all(set(translations) == set(LOCALES) for translations in PUBLIC_PAGES)
    paths = [path for _, path in PUBLIC_URLS]
    assert len(paths) == len(set(paths)), "PUBLIC_PAGES contains a duplicate URL"
    response = public_site.get("/sitemap.xml")
    assert response.status_code == 200
    root = ElementTree.fromstring(response.content)
    urls = [location.text for location in root.findall("s:url/s:loc", SITEMAP_NS)]
    assert len(urls) == len(set(urls)), "The sitemap contains a duplicate URL"
    assert set(urls) == {BASE_URL + path for path in paths}
    for url in urls:
        assert url is not None
        assert public_site.get(url).status_code == 200, url
