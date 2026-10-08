"""IndexNow: tell Bing, Yandex, Seznam and Naver which public pages exist.

IndexNow (https://www.indexnow.org/documentation) lets a site announce its
pages instead of waiting for a crawl. One submission to ``api.indexnow.org``
is shared by every engine that takes part: Bing (and through it DuckDuckGo,
Yahoo and ChatGPT's search), Yandex, Seznam and Naver. Google does not take
part; Search Console covers it.

The key is public by design: the site serves it at ``/<key>.txt`` (``web.py``)
so an engine can check that whoever submits owns the host. ``INDEXNOW_KEY`` is
the default and ``AUDIT_INDEXNOW_KEY`` replaces it (``settings.py``).

Only this module talks to IndexNow, and only from ``quant-trade audit
indexnow``: the web service never submits anything. Nothing here imports the
web extra at module level, so ``settings.py`` can read the key without it.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx

#: The site's IndexNow key, served at ``/<key>.txt``. Public by design.
INDEXNOW_KEY = "f5a5a16c542ab2277bfa9656ce368b3d"
#: What the protocol allows in a key: 8 to 128 letters, digits and dashes.
KEY_PATTERN = re.compile(r"[A-Za-z0-9-]{8,128}")
#: The shared endpoint; it forwards each submission to every engine.
ENDPOINT = "https://api.indexnow.org/indexnow"
#: The protocol's limit of URLs in one POST.
MAX_URLS_PER_BATCH = 10_000
TIMEOUT_SECONDS = 10.0
DEFAULT_SITE = "https://rigorscore.com"
CONTENT_TYPE = "application/json; charset=utf-8"

#: The answers the documentation lists, as name and meaning.
STATUS_MEANINGS: dict[int, str] = {
    200: "OK: URL submitted successfully",
    202: "Accepted: URL received, key validation pending",
    400: "Bad request: invalid format",
    403: "Forbidden: key not valid (key file not found, or the key is not in it)",
    422: "Unprocessable Entity: a URL is not on the host, or the key does not match the protocol",
    429: "Too Many Requests: potential spam",
}
ACCEPTED_STATUSES: frozenset[int] = frozenset({200, 202})

_SITEMAP_LOC = "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
_UNSAFE = re.compile(r"[\s\x00-\x1f\x7f]")


def clean_key(value: str) -> str:
    """``value`` when it is a valid key, else ``INDEXNOW_KEY``."""
    key = value.strip()
    return key if KEY_PATTERN.fullmatch(key) else INDEXNOW_KEY


def key_path(key: str) -> str:
    """Where the site serves the key file: ``/<key>.txt`` at the root."""
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("the key must have 8 to 128 characters from A-Z a-z 0-9 and -")
    return f"/{key}.txt"


def site_host(site: str) -> str:
    """The host of an ``https://`` site root, e.g. ``rigorscore.com``.

    Anything else (another scheme, a path, a query, a user name) is refused."""
    try:
        parts = urlsplit(site.strip())
    except ValueError as exc:
        raise ValueError("the site must be an https address such as " + DEFAULT_SITE) from exc
    host = parts.netloc.lower()
    if (
        parts.scheme != "https"
        or not host
        or "@" in host
        or _UNSAFE.search(host)
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError("the site must be an https address such as " + DEFAULT_SITE)
    return host


def key_location(site: str, key: str) -> str:
    """The absolute address of the key file on ``site``."""
    return f"https://{site_host(site)}{key_path(key)}"


def sitemap_urls(site: str) -> list[str]:
    """The addresses ``sitemap.xml`` lists for ``site``, built here, not downloaded."""
    # Imported here: seo reaches settings, and settings imports this module.
    from quant_trade.audit.seo import sitemap_xml

    root = ElementTree.fromstring(sitemap_xml(site.strip().rstrip("/")))
    return [(loc.text or "").strip() for loc in root.iter(_SITEMAP_LOC) if loc.text]


@dataclass(frozen=True)
class Prepared:
    """The URLs that may be sent, and how many were left out."""

    urls: tuple[str, ...]
    #: Not ``https``, or on another host (``www.`` included), or malformed.
    dropped: int
    #: Repeats of a URL already kept.
    duplicates: int


def prepare(urls: Iterable[str], *, host: str) -> Prepared:
    """Keep the ``https`` URLs on ``host``, once each, in their first order."""
    host = host.strip().lower()
    kept: dict[str, None] = {}
    dropped = duplicates = 0
    for url in urls:
        if not isinstance(url, str) or _UNSAFE.search(url):
            dropped += 1
            continue
        try:
            parts = urlsplit(url)
        except ValueError:
            dropped += 1
            continue
        if parts.scheme != "https" or parts.netloc.lower() != host:
            dropped += 1
        elif url in kept:
            duplicates += 1
        else:
            kept[url] = None
    return Prepared(urls=tuple(kept), dropped=dropped, duplicates=duplicates)


def batches(urls: tuple[str, ...], size: int = MAX_URLS_PER_BATCH) -> list[tuple[str, ...]]:
    """``urls`` in consecutive groups of at most ``size``."""
    return [urls[start : start + size] for start in range(0, len(urls), size)]


def payload(urls: Iterable[str], *, host: str, key: str, key_location: str) -> dict[str, object]:
    """The JSON body of one submission, as the protocol names its fields."""
    return {"host": host, "key": key, "keyLocation": key_location, "urlList": list(urls)}


@dataclass(frozen=True)
class BatchResult:
    """What IndexNow answered for one batch."""

    urls: int
    #: The HTTP status, or ``None`` when no answer arrived.
    status: int | None
    accepted: bool
    meaning: str


@dataclass(frozen=True)
class Submission:
    """One result per batch, and the URLs left out before sending."""

    batches: tuple[BatchResult, ...]
    dropped: int
    duplicates: int

    @property
    def sent(self) -> int:
        return sum(batch.urls for batch in self.batches)

    @property
    def accepted(self) -> bool:
        return all(batch.accepted for batch in self.batches)


def meaning(status: int) -> str:
    """The documentation's name for ``status``."""
    return STATUS_MEANINGS.get(status, f"unexpected answer (HTTP {status})")


def _new_client() -> httpx.Client:
    import httpx

    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)


def _send(client: httpx.Client, body: dict[str, object], count: int) -> BatchResult:
    import httpx

    try:
        response = client.post(
            ENDPOINT,
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": CONTENT_TYPE},
        )
    except (httpx.HTTPError, OSError) as exc:
        # Only the kind of failure: its message may repeat the request.
        reason = f"network error ({type(exc).__name__}), no answer received"
        return BatchResult(urls=count, status=None, accepted=False, meaning=reason)
    status = response.status_code
    return BatchResult(
        urls=count, status=status, accepted=status in ACCEPTED_STATUSES, meaning=meaning(status)
    )


def submit(
    urls: Iterable[str],
    *,
    host: str,
    key: str,
    key_location: str,
    client: httpx.Client | None = None,
) -> Submission:
    """POST ``urls`` to IndexNow in batches of at most ``MAX_URLS_PER_BATCH``.

    Only ``https`` URLs on ``host`` are sent, each once; the others are counted
    in ``dropped``. 200 and 202 count as accepted; any other answer, and a
    network failure, is an error named by ``meaning``. ``client`` is closed only
    when this function opened it.
    """
    host = host.strip().lower()
    if not host or _UNSAFE.search(host) or "/" in host or "@" in host:
        raise ValueError("host must be a bare host name such as rigorscore.com")
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("the key must have 8 to 128 characters from A-Z a-z 0-9 and -")
    location = urlsplit(key_location)
    if location.scheme != "https" or location.netloc.lower() != host:
        raise ValueError("keyLocation must be an https address on the same host")
    prepared = prepare(urls, host=host)
    groups = batches(prepared.urls)
    results: list[BatchResult] = []
    if groups:
        own = client is None
        http = _new_client() if client is None else client
        try:
            for group in groups:
                body = payload(group, host=host, key=key, key_location=key_location)
                results.append(_send(http, body, len(group)))
        finally:
            if own:
                http.close()
    return Submission(
        batches=tuple(results), dropped=prepared.dropped, duplicates=prepared.duplicates
    )


__all__ = [
    "ACCEPTED_STATUSES",
    "CONTENT_TYPE",
    "DEFAULT_SITE",
    "ENDPOINT",
    "INDEXNOW_KEY",
    "KEY_PATTERN",
    "MAX_URLS_PER_BATCH",
    "STATUS_MEANINGS",
    "TIMEOUT_SECONDS",
    "BatchResult",
    "Prepared",
    "Submission",
    "batches",
    "clean_key",
    "key_location",
    "key_path",
    "meaning",
    "payload",
    "prepare",
    "site_host",
    "sitemap_urls",
    "submit",
]
