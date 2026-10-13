"""Read-only HTTP checks of the published sitemap, public pages and share cards.

Only GET requests to the selected origin are made, without retries. A redirect
to the same origin (a sign-in screen, a trailing slash) is followed for up to
three hops and judged by its final status; a redirect to another origin is
listed, never requested. PDF links are judged by status and headers alone,
with their own longer timeout, because the site renders them on first request.
No database, app startup or filesystem writes live here.
"""

from __future__ import annotations

import math
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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
#: Same-origin redirects followed from one URL before it fails.
MAX_REDIRECTS = 3
SLOW_SECONDS = 3.0
#: The site renders a sample PDF on its first request and may first wait up to
#: ``web.PDF_WAIT_SECONDS`` (60 s) for a free render slot; 30 s more covers the
#: render. A literal, so this module never imports the web app (a test keeps
#: the two in step).
PDF_TIMEOUT_SECONDS = 90.0
MODES = ("sitemap", "links", "images", "all")
IMAGE_KINDS = frozenset({"og:image", "twitter:image"})
LINK_KINDS = frozenset({"a", "canonical", "hreflang"})
IMAGE_TYPES = frozenset({"image/png", "image/svg+xml"})
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
PDF_TYPE = "application/pdf"
#: ``RequestResult.error`` for a redirect that was not followed.
EXTERNAL_REDIRECT = "ExternalRedirect"
REDIRECT_LOOP = "RedirectLoop"
TOO_MANY_REDIRECTS = "TooManyRedirects"
INVALID_REDIRECT = "InvalidRedirect"
INVALID_URL = "[invalid URL]"
#: Marked sections a page may carry: CDATA (inline SVG) and Office's conditional
#: sections. Python's parser raised on any other ``<![...]>`` until its patch
#: releases began to read them as HTML5 does (3.11.17 and 3.12.15 on CI hand
#: them to ``unknown_decl``), so the page parser refuses them itself.
MARKED_SECTIONS = frozenset({"temp", "cdata", "ignore", "include", "rcdata", "if", "else", "endif"})
_MARKED_SECTION_NAME = re.compile(r"[a-zA-Z][-_.a-zA-Z0-9]*")


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


def _is_pdf_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def _thousands(number: int) -> str:
    return f"{number:,}".replace(",", ".")


def _plural(number: int, one: str, many: str) -> str:
    return f"{_thousands(number)} {one if number == 1 else many}"


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
class RequestResult:
    """One checked URL.

    ``status`` is the final status after same-origin redirects (``None`` when
    no response arrived); ``redirect_chain`` holds each redirect's status and
    target, including a target that was not followed. ``kind`` is ``pdf``
    (body not downloaded: ``size_bytes`` comes from ``Content-Length``),
    ``html`` or ``other``.
    """

    url: str
    status: int | None
    elapsed_seconds: float
    size_bytes: int
    content_type: str
    error: str = ""
    kind: str = "other"
    location: str = ""
    final_url: str = ""
    redirect_chain: tuple[tuple[int, str], ...] = ()

    @property
    def timed_out(self) -> bool:
        return self.status is None and self.error.endswith("Timeout")


@dataclass(frozen=True)
class Link:
    """A URL referenced as ``kind`` from every page in ``sources``."""

    url: str
    kind: str
    sources: tuple[str, ...]

    @property
    def source_count(self) -> int:
        return len(self.sources)


@dataclass(frozen=True)
class Failure:
    """One failing URL, once, with every page that references it."""

    url: str
    kind: str
    reason: str
    sources: tuple[str, ...]

    @property
    def source_count(self) -> int:
        return len(self.sources)


def _grouped_dict(item: Link | Failure, *, sources: bool) -> dict[str, object]:
    data = asdict(item)
    data["source_count"] = item.source_count
    if not sources:
        del data["sources"]
    return data


@dataclass(frozen=True)
class SmokeReport:
    site: str
    only: str
    requests: tuple[RequestResult, ...]
    references: tuple[Link, ...]
    external: tuple[Link, ...]
    failures: tuple[Failure, ...]
    #: Distinct mailto:, tel:, javascript: and other non-HTTP targets skipped.
    non_http: int = 0

    @property
    def ok(self) -> bool:
        """No real failure: followed same-origin redirects and slowness only inform."""
        return not self.failures

    def slow_requests(self, *, pdf: bool) -> tuple[RequestResult, ...]:
        """Answered requests slower than 3 s, slowest first; timeouts are failures."""
        return tuple(
            sorted(
                (
                    item
                    for item in self.requests
                    if item.status is not None
                    and item.elapsed_seconds > SLOW_SECONDS
                    and (item.kind == "pdf") == pdf
                ),
                key=lambda item: (-item.elapsed_seconds, item.url),
            )
        )

    @property
    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.requests),
            "ok": sum(item.status == 200 for item in self.requests),
            "non_200": sum(item.status != 200 for item in self.requests),
            "redirects": sum(bool(item.redirect_chain) for item in self.requests),
            "slow": len(self.slow_requests(pdf=False)),
            "slow_pdf": len(self.slow_requests(pdf=True)),
            "timeouts": sum(item.timed_out for item in self.requests),
            "broken_images": len({f.url for f in self.failures if f.kind in IMAGE_KINDS}),
            "broken_links": len({f.url for f in self.failures if f.kind in LINK_KINDS}),
        }

    def to_dict(self, *, full: bool = False) -> dict[str, object]:
        """The JSON report. References list each URL once with its page count;
        ``full`` adds every referring page (failures always carry them)."""
        return {
            "site": self.site,
            "only": self.only,
            "ok": self.ok,
            "summary": self.summary,
            "failures": [_grouped_dict(item, sources=True) for item in self.failures],
            "requests": [asdict(item) for item in self.requests],
            "references": [_grouped_dict(item, sources=full) for item in self.references],
            "external": [_grouped_dict(item, sources=full) for item in self.external],
            "non_http_skipped": self.non_http,
        }


def format_report(report: SmokeReport, *, verbose: bool = False) -> list[str]:
    """Console lines: failures, slow responses, external links, then the summary."""

    def where(source: str) -> str:
        return source[len(report.site) :] if source.startswith(report.site + "/") else source

    lines: list[str] = []
    for failure in report.failures:
        shown = ", ".join(where(source) for source in failure.sources[:3])
        if failure.source_count > 3:
            shown = f"p. ej. {shown}, …"
        pages = _plural(failure.source_count, "página", "páginas")
        lines.append(
            f"FALLO [{failure.kind}] {failure.url}: {failure.reason} — en {pages} ({shown})"
        )
    for item in report.slow_requests(pdf=False):
        lines.append(f"Lenta: {item.url} — {item.elapsed_seconds:.2f} s")
    for item in report.slow_requests(pdf=True):
        lines.append(f"PDF lento: {item.url} — {item.elapsed_seconds:.2f} s")
    if verbose:
        for item in report.requests:
            if item.redirect_chain and not item.error:
                lines.append(
                    f"Redirección {item.redirect_chain[0][0]}: {item.url} → {item.final_url}"
                    f" (HTTP {item.status})"
                )
    external: dict[str, set[str]] = {}
    for link in report.external:
        external.setdefault(link.url, set()).update(link.sources)
    references = sum(link.source_count for link in report.external)
    lines.append(
        f"Externos: {_plural(len(external), 'URL', 'URL')} en "
        f"{_plural(references, 'enlace', 'enlaces')} (no comprobados)"
    )
    if verbose:
        for url in sorted(external):
            pages = _plural(len(external[url]), "página", "páginas")
            lines.append(f"  Externo: {url} — en {pages}")
    counts = report.summary
    lines.append(
        f"Resumen RigorSmoke: total={counts['total']}, 200={counts['ok']}, "
        f"no-200={counts['non_200']}, redirecciones={counts['redirects']}, "
        f"lentas={counts['slow']}, PDF lentos={counts['slow_pdf']}, "
        f"timeouts={counts['timeouts']}, imágenes rotas={counts['broken_images']}, "
        f"enlaces rotos={counts['broken_links']}"
    )
    return lines


def exit_line(report: SmokeReport) -> str:
    """The console's last line, naming the exit status."""
    if report.ok:
        return "Salida 0: sin fallos"
    return f"Salida 1: {_plural(len(report.failures), 'fallo', 'fallos')}"


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

    def unknown_decl(self, data: str) -> None:
        """Refuse ``<![broken]>`` on every Python, as older parsers did."""
        name = _MARKED_SECTION_NAME.match(data)
        if name is None or name.group(0).lower() not in MARKED_SECTIONS:
            raise ValueError(f"unknown marked section {data[:40]!r}")


@dataclass
class _Fetched:
    result: RequestResult
    #: The final 200 response with its body read; ``None`` for PDFs, errors,
    #: other statuses and unfollowed redirects.
    response: httpx.Response | None


def _new_client(concurrency: int, timeout: float) -> httpx.Client:
    import httpx

    return httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    )


def _content_length(response: httpx.Response) -> int:
    value = response.headers.get("content-length", "").strip()
    return int(value) if value.isascii() and value.isdigit() else 0


def _fetch(
    client: httpx.Client,
    url: str,
    origin: tuple[str, str | None, int | None],
    timeout: float,
    pdf_timeout: float,
) -> _Fetched:
    """GET ``url``, following same-origin redirects; a PDF's body is never read."""
    import httpx

    start = time.perf_counter()
    current = url
    visited = {url}
    chain: list[tuple[int, str]] = []
    status: int | None = None
    content_type = ""
    size = 0
    error = ""
    kept: httpx.Response | None = None
    while True:
        try:
            with client.stream(
                "GET",
                current,
                headers={"User-Agent": USER_AGENT},
                timeout=pdf_timeout if _is_pdf_url(current) else timeout,
                follow_redirects=False,
            ) as response:
                status = response.status_code
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                redirect = response.is_redirect
                location = response.headers.get("location", "")
                if not redirect and content_type == PDF_TYPE:
                    # Status and headers are enough; the stream closes unread.
                    size = _content_length(response)
                elif not redirect:
                    response.read()
                    size, kept = len(response.content), response
        except (httpx.HTTPError, OSError) as exc:
            status, content_type, error = None, "", type(exc).__name__
            break
        if not redirect:
            break
        try:
            target = _normalize(urljoin(current, location))
        except (ValueError, httpx.InvalidURL):
            # Do not reflect a malformed Location that could carry credentials.
            chain.append((status, INVALID_URL))
            error = INVALID_REDIRECT
            break
        chain.append((status, target))
        if _origin(target) != origin:
            error = EXTERNAL_REDIRECT
        elif target in visited:
            error = REDIRECT_LOOP
        elif len(chain) > MAX_REDIRECTS:
            error = TOO_MANY_REDIRECTS
        if error:
            break
        visited.add(target)
        current = target
    if content_type == PDF_TYPE or _is_pdf_url(current):
        kind = "pdf"
    elif content_type in HTML_TYPES:
        kind = "html"
    else:
        kind = "other"
    result = RequestResult(
        url=url,
        status=status,
        elapsed_seconds=time.perf_counter() - start,
        size_bytes=size,
        content_type=content_type,
        error=error,
        kind=kind,
        location=chain[0][1] if chain else "",
        final_url=current,
        redirect_chain=tuple(chain),
    )
    return _Fetched(result, kept if status == 200 and not error else None)


def _problem(result: RequestResult) -> str:
    """Why a request fails however it was referenced ("" when it does not)."""
    if result.status is None:
        return f"Sin respuesta: {result.error}"
    if result.error == EXTERNAL_REDIRECT:
        return (
            f"HTTP {result.status}: redirección a otro origen, no seguida "
            f"({result.redirect_chain[-1][1]})"
        )
    if result.error == REDIRECT_LOOP:
        return f"HTTP {result.status}: redirección en bucle"
    if result.error == TOO_MANY_REDIRECTS:
        return f"HTTP {result.status}: más de {MAX_REDIRECTS} redirecciones seguidas"
    if result.error == INVALID_REDIRECT:
        return f"HTTP {result.status}: redirección con Location inválido"
    if result.status != 200:
        if result.redirect_chain:
            return f"HTTP {result.status} tras redirección a {result.final_url}"
        return f"HTTP {result.status}"
    return ""


class _Crawler:
    def __init__(self, site: str, only: str, timeout: float, pdf_timeout: float) -> None:
        self.site = site
        self.origin = _origin(site)
        self.only = only
        self.timeout = timeout
        self.pdf_timeout = pdf_timeout
        self.references: dict[tuple[str, str], set[str]] = {}
        self.external: dict[tuple[str, str], set[str]] = {}
        self.problems: dict[tuple[str, str, str], set[str]] = {}
        self.over_limit: dict[str, set[str]] = {}
        self.non_http: set[str] = set()
        self.results: dict[str, RequestResult] = {}
        self.urls: set[str] = set()
        self.pages: set[str] = set()
        self.sitemaps: set[str] = set()
        self.queue: deque[str] = deque()
        #: 200 bodies not parsed yet: their URL may still gain the role (page
        #: or sitemap) that their content needs. Parsed bodies are dropped.
        self.bodies: dict[str, httpx.Response] = {}
        self.ready: deque[str] = deque()

    def fail(self, url: str, kind: str, reason: str, *sources: str) -> None:
        self.problems.setdefault((url, kind, reason), set()).update(sources)

    def add(self, source: str, raw: str, kind: str, *, base: str | None = None) -> None:
        import httpx

        try:
            url = urljoin(base or source, raw.strip())
            if urlsplit(url).scheme.lower() not in ("http", "https"):
                # mailto:, tel:, javascript:… are neither requested nor external.
                self.non_http.add(url)
                return
            url = _normalize(url)
        except (ValueError, httpx.InvalidURL):
            # Avoid reflecting malformed URLs that could contain credentials.
            self.fail(INVALID_URL, kind, "URL inválida", source)
            return
        if _origin(url) != self.origin:
            self.external.setdefault((url, kind), set()).add(source)
            return
        if url not in self.urls:
            if len(self.urls) >= MAX_URLS:
                self.over_limit.setdefault(url, set()).add(source)
                return
            self.urls.add(url)
            self.queue.append(url)
        self.references.setdefault((url, kind), set()).add(source)
        if kind == "sitemap":
            self.sitemaps.add(url)
        elif kind not in IMAGE_KINDS:
            self.pages.add(url)
        if url in self.bodies:
            self.ready.append(url)

    def settle(self, url: str, fetched: _Fetched) -> None:
        result = fetched.result
        self.results[url] = result
        if result.error == EXTERNAL_REDIRECT:
            target = result.redirect_chain[-1][1]
            self.external.setdefault((target, "redirect"), set()).add(result.final_url)
        response = fetched.response
        # Only a 200 is parsed (never a 404 page); images and PDFs never are.
        if response is None or result.content_type in IMAGE_TYPES:
            return
        if result.final_url != url and result.final_url in self.urls:
            return  # The redirect target is parsed under its own URL.
        html = result.content_type in HTML_TYPES
        if self.only == "sitemap" and html and url not in self.sitemaps:
            return
        self.bodies[url] = response
        self.ready.append(url)

    def parse(self, url: str) -> None:
        response = self.bodies.get(url)
        if response is None:
            return
        result = self.results[url]
        if url in self.sitemaps:
            del self.bodies[url]
            self.read_sitemap(result.final_url, response)
        elif url in self.pages and result.content_type in HTML_TYPES and self.only != "sitemap":
            del self.bodies[url]
            self.read_page(result.final_url, response)

    def read_sitemap(self, url: str, response: httpx.Response) -> None:
        try:
            root = ET.fromstring(response.content)
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
                    self.fail(url, "sitemap", "Entrada sin loc válido", url)
                    continue
                self.add(url, locations[0].text or "", "page" if name == "urlset" else "sitemap")
        except (ET.ParseError, ValueError, LookupError):
            self.fail(url, "sitemap", "Sitemap inválido o vacío", url)

    def read_page(self, url: str, response: httpx.Response) -> None:
        parser = _PageParser()
        try:
            parser.feed(response.text)
        except (AssertionError, ValueError):
            self.fail(url, "html", "HTML inválido", url)
            return
        try:
            base = urljoin(url, parser.base) if parser.base is not None else url
        except ValueError:
            self.fail(INVALID_URL, "base", "Base HTML inválida", url)
            return
        for kind, raw in parser.references:
            if (
                self.only == "all"
                or (self.only == "images" and kind in IMAGE_KINDS)
                or (self.only == "links" and kind in LINK_KINDS)
            ):
                self.add(url, raw, kind, base=base)

    def crawl(self, client: httpx.Client, concurrency: int) -> SmokeReport:
        self.add(self.site + "/", "/sitemap.xml", "sitemap")
        for page in seo.PUBLIC_PAGES:
            for path in page.values():
                self.add("PUBLIC_PAGES", path, "page", base=self.site + "/")
        # A work queue, not waves: each page is parsed as soon as it arrives and
        # its new links start while slower requests (a PDF render) still run.
        running: dict[Future[_Fetched], str] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while True:
                while self.ready:
                    self.parse(self.ready.popleft())
                while self.queue and len(running) < concurrency:
                    url = self.queue.popleft()
                    future = pool.submit(
                        _fetch, client, url, self.origin, self.timeout, self.pdf_timeout
                    )
                    running[future] = url
                if not running:
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=running.__getitem__):
                    self.settle(running.pop(future), future.result())
        self.bodies.clear()
        return self._report()

    def _report(self) -> SmokeReport:
        for (url, kind), sources in self.references.items():
            result = self.results[url]
            reason = _problem(result)
            if not reason and kind in IMAGE_KINDS and result.content_type not in IMAGE_TYPES:
                reason = f"Tipo de imagen inválido: {result.content_type or '(sin Content-Type)'}"
            if reason:
                self.fail(url, kind, reason, *sources)
        if self.over_limit:
            # One failure for the whole overflow, naming the first URL left out.
            self.fail(
                min(self.over_limit),
                "limit",
                f"Límite de {_thousands(MAX_URLS)} URLs alcanzado: "
                f"{_plural(len(self.over_limit), 'URL', 'URL')} sin comprobar; "
                "comprobación incompleta",
                *set().union(*self.over_limit.values()),
            )

        def grouped(groups: dict[tuple[str, str], set[str]]) -> tuple[Link, ...]:
            return tuple(
                Link(url, kind, tuple(sorted(sources)))
                for (url, kind), sources in sorted(groups.items())
            )

        return SmokeReport(
            site=self.site,
            only=self.only,
            requests=tuple(self.results[url] for url in sorted(self.results)),
            references=grouped(self.references),
            external=grouped(self.external),
            failures=tuple(
                Failure(url, kind, reason, tuple(sorted(sources)))
                for (url, kind, reason), sources in sorted(self.problems.items())
            ),
            non_http=len(self.non_http),
        )


def run_smoke(
    site: str,
    *,
    concurrency: int = 4,
    timeout: float = 20.0,
    pdf_timeout: float | None = None,
    only: str = "all",
    client: httpx.Client | None = None,
) -> SmokeReport:
    """Check each URL once. A supplied client is borrowed, never closed.

    Fails: a final status other than 200, no response, a redirect leaving the
    origin, looping or exceeding three hops, an image without a PNG/SVG MIME
    type, a malformed sitemap or HTML page, or the URL limit. Followed
    same-origin redirects and slow responses (> 3 s) are informational.
    ``.pdf`` URLs wait ``pdf_timeout`` (default: the larger of ``timeout``
    and 90 s).
    """
    site = validate_site(site)
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError("--concurrency must be between 1 and 4")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("--timeout must be finite and positive")
    if pdf_timeout is None:
        pdf_timeout = max(timeout, PDF_TIMEOUT_SECONDS)
    elif not math.isfinite(pdf_timeout) or pdf_timeout <= 0:
        raise ValueError("--pdf-timeout must be finite and positive")
    if only not in MODES:
        raise ValueError("--only must be sitemap, links, images or all")
    crawler = _Crawler(site, only, timeout, pdf_timeout)
    if client is not None:
        return crawler.crawl(client, concurrency)
    with _new_client(concurrency, timeout) as owned:
        return crawler.crawl(owned, concurrency)
