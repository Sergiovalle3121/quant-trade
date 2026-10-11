"""Read-only HTTP checks of the published sitemap, public pages and share cards.

Only GET requests to the selected origin are allowed. Redirects are reported,
never followed; no retries, database, app startup or filesystem writes live here.
"""

from __future__ import annotations

import math
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from quant_trade.audit import seo

if TYPE_CHECKING:
    import httpx

USER_AGENT = "RigorSmoke/1.0"
MAX_CONCURRENCY = 4
MAX_URLS = 10_000
SLOW_SECONDS = 3.0
MODES = ("sitemap", "links", "images", "all")
IMAGE_KINDS = frozenset({"og:image", "twitter:image"})
LINK_KINDS = frozenset({"a", "canonical", "hreflang"})
IMAGE_TYPES = frozenset({"image/png", "image/svg+xml"})
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def _normalize(url: str) -> str:
    """HTTP cache key: no fragment or credentials; retain path and query."""
    import httpx

    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("expected an absolute HTTP(S) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL credentials are not allowed")
    # Accessing port also rejects malformed/out-of-range ports.
    _ = parts.port
    parsed = httpx.URL(url).copy_with(fragment=None)
    return str(parsed.copy_with(raw_path=parsed.raw_path))


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parts = urlsplit(url)
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, port


def validate_site(site: str) -> str:
    """Accept an HTTP(S) origin, including localhost, ports and IPv6."""
    import httpx

    try:
        parts = urlsplit(site)
        if (
            any(char.isspace() or ord(char) < 32 for char in site)
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("expected a site root")
        return _normalize(site).rstrip("/")
    except (ValueError, httpx.InvalidURL) as exc:
        # httpx.InvalidURL is not a ValueError. Do not echo URL credentials.
        raise ValueError("--site must be an HTTP(S) site root without credentials") from exc


@dataclass(frozen=True)
class Reference:
    source: str
    url: str
    kind: str


@dataclass(frozen=True)
class RequestResult:
    url: str
    status: int | None
    elapsed_seconds: float
    size_bytes: int
    content_type: str
    error: str = ""


@dataclass(frozen=True)
class Failure:
    source: str
    url: str
    kind: str
    reason: str


@dataclass(frozen=True)
class SmokeReport:
    site: str
    only: str
    requests: tuple[RequestResult, ...]
    references: tuple[Reference, ...]
    external: tuple[Reference, ...]
    failures: tuple[Failure, ...]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.requests),
            "ok": sum(item.status == 200 for item in self.requests),
            "non_200": sum(item.status != 200 for item in self.requests),
            "slow": sum(item.elapsed_seconds > SLOW_SECONDS for item in self.requests),
            "broken_images": len({f.url for f in self.failures if f.kind in IMAGE_KINDS}),
            "broken_links": len({f.url for f in self.failures if f.kind in LINK_KINDS}),
        }

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "summary": self.summary, "ok": self.ok}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []
        self.base: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        href = values.get("href")
        if tag == "base" and href is not None and self.base is None:
            self.base = href
        if tag == "a" and href is not None:
            self.references.append(("a", href))
        if tag == "link" and href is not None:
            rel = (values.get("rel") or "").lower().split()
            if "canonical" in rel:
                self.references.append(("canonical", href))
            if values.get("hreflang"):
                self.references.append(("hreflang", href))
        if tag == "meta":
            name = (values.get("property") or values.get("name") or "").lower()
            if name in IMAGE_KINDS:
                self.references.append((name, values.get("content") or ""))


@dataclass
class _Fetched:
    result: RequestResult
    response: httpx.Response | None


def _new_client(concurrency: int, timeout: float) -> httpx.Client:
    import httpx

    return httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    )


def _fetch(client: httpx.Client, url: str, timeout: float) -> _Fetched:
    import httpx

    start = time.perf_counter()
    try:
        response = client.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=False
        )
    except (httpx.HTTPError, OSError) as exc:
        return _Fetched(
            RequestResult(url, None, time.perf_counter() - start, 0, "", type(exc).__name__),
            None,
        )
    return _Fetched(
        RequestResult(
            url,
            response.status_code,
            time.perf_counter() - start,
            len(response.content),
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower(),
        ),
        response,
    )


class _Crawler:
    def __init__(self, site: str, only: str) -> None:
        self.site = site
        self.only = only
        self.references: dict[Reference, None] = {}
        self.external: dict[Reference, None] = {}
        self.failures: list[Failure] = []
        self.cache: dict[str, _Fetched] = {}
        self.pages: set[str] = set()
        self.sitemaps: set[str] = set()
        self.urls: set[str] = set()

    def add(self, source: str, raw: str, kind: str, *, base: str | None = None) -> None:
        import httpx

        try:
            url = urljoin(base or source, raw.strip())
            if urlsplit(url).scheme.lower() not in ("http", "https"):
                self.external[Reference(source, url, kind)] = None
                return
            url = _normalize(url)
        except (ValueError, httpx.InvalidURL):
            # Avoid reflecting malformed URLs that could contain credentials.
            self.failures.append(Failure(source, "[invalid URL]", kind, "URL inválida"))
            return
        ref = Reference(source, url, kind)
        if _origin(url) != _origin(self.site):
            self.external[ref] = None
            return
        if url not in self.urls and len(self.urls) >= MAX_URLS:
            self.failures.append(
                Failure(source, url, kind, f"Límite de {MAX_URLS} URLs; comprobación incompleta")
            )
            return
        self.urls.add(url)
        self.references[ref] = None
        if kind == "sitemap":
            self.sitemaps.add(url)
        elif kind not in IMAGE_KINDS:
            self.pages.add(url)

    def read_sitemap(self, url: str) -> None:
        fetched = self.cache[url]
        if fetched.result.status != 200 or fetched.response is None:
            return
        try:
            root = ET.fromstring(fetched.response.content)
            name = root.tag.rsplit("}", 1)[-1]
            if name not in ("urlset", "sitemapindex"):
                raise ValueError("not a sitemap")
            entry_name = "url" if name == "urlset" else "sitemap"
            entries = [child for child in root if child.tag.rsplit("}", 1)[-1] == entry_name]
            if not entries:
                raise ValueError("empty sitemap")
            for entry in entries:
                locations = [node for node in entry if node.tag.rsplit("}", 1)[-1] == "loc"]
                if len(locations) != 1 or not (locations[0].text or "").strip():
                    self.failures.append(Failure(url, url, "sitemap", "Entrada sin loc válido"))
                    continue
                self.add(url, locations[0].text or "", "page" if name == "urlset" else "sitemap")
        except (ET.ParseError, ValueError, LookupError):
            self.failures.append(Failure(url, url, "sitemap", "Sitemap inválido o vacío"))

    def read_page(self, url: str) -> None:
        fetched = self.cache[url]
        if (
            self.only == "sitemap"
            or fetched.result.content_type not in HTML_TYPES
            or fetched.response is None
        ):
            return
        parser = _PageParser()
        try:
            parser.feed(fetched.response.text)
        except (AssertionError, ValueError):
            self.failures.append(Failure(url, url, "html", "HTML inválido"))
            return
        try:
            base = urljoin(url, parser.base) if parser.base is not None else url
        except ValueError:
            self.failures.append(Failure(url, "[invalid URL]", "base", "Base HTML inválida"))
            return
        for kind, raw in parser.references:
            if (
                self.only == "all"
                or (self.only == "images" and kind in IMAGE_KINDS)
                or (self.only == "links" and kind in LINK_KINDS)
            ):
                self.add(url, raw, kind, base=base)

    def crawl(self, client: httpx.Client, concurrency: int, timeout: float) -> SmokeReport:
        import httpx

        self.add(self.site + "/", "/sitemap.xml", "sitemap")
        for page in seo.PUBLIC_PAGES:
            for path in page.values():
                self.add("PUBLIC_PAGES", path, "page", base=self.site + "/")
        parsed_maps: set[str] = set()
        parsed_pages: set[str] = set()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while True:
                pending = sorted({ref.url for ref in self.references} - self.cache.keys())
                for fetched in pool.map(lambda url: _fetch(client, url, timeout), pending):
                    self.cache[fetched.result.url] = fetched
                    response = fetched.response
                    if response is not None and response.is_redirect:
                        location = response.headers.get("location", "")
                        # Expose an external redirect target without requesting it.
                        try:
                            target = _normalize(urljoin(fetched.result.url, location))
                            if _origin(target) != _origin(self.site):
                                ref = Reference(fetched.result.url, target, "redirect")
                                self.external[ref] = None
                        except (ValueError, httpx.InvalidURL):
                            pass
                maps = self.sitemaps - parsed_maps
                pages = self.pages - parsed_pages
                if not pending and not maps and not pages:
                    break
                for url in sorted(maps):
                    self.read_sitemap(url)
                    parsed_maps.add(url)
                # New sitemap entries are fetched in the next iteration.
                for url in sorted(pages):
                    self.read_page(url)
                    parsed_pages.add(url)
        for ref in self.references:
            result = self.cache[ref.url].result
            reason = ""
            if result.status != 200:
                reason = (
                    f"HTTP {result.status}" if result.status else f"Sin respuesta: {result.error}"
                )
            elif ref.kind in IMAGE_KINDS and result.content_type not in IMAGE_TYPES:
                reason = f"Tipo de imagen inválido: {result.content_type or '(sin Content-Type)'}"
            if reason:
                self.failures.append(Failure(ref.source, ref.url, ref.kind, reason))
        return SmokeReport(
            self.site,
            self.only,
            tuple(self.cache[url].result for url in sorted(self.cache)),
            tuple(sorted(self.references, key=lambda ref: (ref.source, ref.url, ref.kind))),
            tuple(sorted(self.external, key=lambda ref: (ref.source, ref.url, ref.kind))),
            tuple(sorted(set(self.failures), key=lambda f: (f.source, f.url, f.kind, f.reason))),
        )


def run_smoke(
    site: str,
    *,
    concurrency: int = 4,
    timeout: float = 20.0,
    only: str = "all",
    client: httpx.Client | None = None,
) -> SmokeReport:
    """Check each URL once. A supplied client is borrowed, never closed.

    Slow responses (> 3 seconds) are informational. All non-200 responses,
    transport errors, malformed sitemaps and incorrect image MIME types fail.
    """
    site = validate_site(site)
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError("--concurrency must be between 1 and 4")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("--timeout must be finite and positive")
    if only not in MODES:
        raise ValueError("--only must be sitemap, links, images or all")
    crawler = _Crawler(site, only)
    if client is not None:
        return crawler.crawl(client, concurrency, timeout)
    with _new_client(concurrency, timeout) as owned:
        return crawler.crawl(owned, concurrency, timeout)
