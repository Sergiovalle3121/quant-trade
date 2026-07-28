"""Resumable, idempotent, rate-limited evidence backfill.

One invocation walks every series a carry panel needs — spot bars, perp bars,
mark bars, index bars and settled funding — backwards from ``until`` to
``since``, one official page at a time, and preserves what it saw:

* **raw bytes, content-addressed.** ``raw/<sha256>.json`` is the archive; a
  page whose bytes are already on disk is never re-downloaded.
* **one ingestion receipt per page**, hash-chained, carrying the exact URL,
  the request parameters, the venue's own server clock, the SHA-256 of the
  bytes, the SHA-256 of the normalized rows and the parser version.
* **an attempt log with every failure verbatim.** A blocked network produces
  ``NOT_RUN_NETWORK_BLOCKED`` plus the exact transport error and the blocked
  host — a verifiable negative result, never silence.

Resume and idempotency come from the same mechanism: each request is keyed by
its canonical parameters, and the key→bytes mapping is persisted. Re-running
after an interruption replays the archived pages (no network, no duplicate
receipts) and continues from the first page that was never fetched.

Nothing here authenticates, signs, trades, or moves funds. Every endpoint is
public and unauthenticated, and no credential is read from the environment.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    sha256_of_bytes,
    sha256_of_text,
)
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
    receipt_relative_path,
)
from quant_trade.v8.venues import (
    PARSER_VERSION,
    SERIES_KINDS,
    VENUE_RATE_LIMIT_RPS,
    IdentityMismatch,
    SeriesSpec,
    VenueErrorResponse,
    instruments_url,
    parse_instruments,
    parse_server_time,
    series_spec,
    server_time_url,
)

USER_AGENT = "quant-trade-v8-evidence/1.0 (read-only research; no trading)"

#: Runaway backstop. 730 days of hourly bars needs ~18 Bybit pages (1000 bars)
#: or ~176 OKX pages (100 bars) per series; 4000 leaves generous headroom
#: without ever becoming an unbounded loop.
MAX_PAGES_PER_SERIES = 4000

#: Statuses a series/backfill run can end in.
STATUS_OK = "OK"
STATUS_NETWORK_BLOCKED = "NOT_RUN_NETWORK_BLOCKED"
STATUS_PARSE_REJECTED = "NOT_RUN_PARSE_REJECTED"
STATUS_VENUE_ERROR = "NOT_RUN_VENUE_ERROR"


class Fetcher(Protocol):
    """Transport seam. Implementations must not add credentials."""

    def __call__(self, url: str) -> tuple[int, bytes, dict[str, str]]: ...


def http_get(url: str, *, timeout_seconds: float = 20.0) -> tuple[int, bytes, dict[str, str]]:
    """GET a public endpoint. No keys, no cookies, only a research UA."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        headers = {k.lower(): v for k, v in response.headers.items()}
        return int(response.status), bytes(response.read()), headers


class RateLimiter:
    """Minimum-interval pacer. Read-only research traffic stays polite."""

    def __init__(
        self,
        requests_per_second: float,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        self._min_interval = 1.0 / requests_per_second
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._last: float | None = None
        self.waits = 0

    def acquire(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                self.waits += 1
                self._sleep(wait)
                now = self._clock()
        self._last = now


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff for transport and rate-limit failures."""

    max_attempts: int = 4
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be > 0")

    def delay_for(self, attempt: int) -> float:
        """Deterministic backoff: 2s, 4s, 8s, 16s… capped. No jitter, so a
        replayed run produces the same attempt log."""
        return min(self.base_delay_seconds * (2 ** max(0, attempt - 1)), self.max_delay_seconds)


@dataclass(frozen=True)
class BackfillRequest:
    venue: str
    symbol: str
    since_ms: int
    until_ms: int
    interval_minutes: int = 60
    kinds: tuple[str, ...] = SERIES_KINDS

    def __post_init__(self) -> None:
        if self.until_ms <= self.since_ms:
            raise ValueError("until_ms must be after since_ms")
        if self.interval_minutes <= 0:
            raise ValueError("interval_minutes must be > 0")
        unknown = [k for k in self.kinds if k not in SERIES_KINDS]
        if unknown:
            raise ValueError(f"unknown series {unknown}; supported: {SERIES_KINDS}")

    @property
    def span_days(self) -> float:
        return (self.until_ms - self.since_ms) / 86_400_000.0


@dataclass
class SeriesResult:
    kind: str
    status: str = STATUS_OK
    pages_fetched: int = 0
    pages_replayed: int = 0
    rows: int = 0
    oldest_ms: int | None = None
    newest_ms: int | None = None
    reached_lower_bound: bool = False
    conflicting_duplicates: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BackfillResult:
    status: str
    venue: str
    symbol: str
    since_ms: int
    until_ms: int
    interval_minutes: int
    evidence_dir: str
    series: dict[str, SeriesResult] = field(default_factory=dict)
    settlements: int = 0
    server_time_ms: int | None = None
    instrument_metadata: list[dict[str, Any]] = field(default_factory=list)
    blocked_hosts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    attempts: int = 0
    started_at_utc: str = ""
    finished_at_utc: str = ""
    provenance: str = "live"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["series"] = {k: v.to_dict() for k, v in self.series.items()}
        return payload


def _iso(ms: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000.0))


def evidence_dir_for(root: str | Path, venue: str, symbol: str) -> Path:
    from quant_trade.carry.instruments import parse_symbol

    base, quote = parse_symbol(symbol)
    return Path(root) / f"{venue.lower()}_{base.lower()}_{quote.lower()}"


def _request_key(
    *, venue: str, kind: str, symbol: str, cursor_ms: int, interval_minutes: int
) -> str:
    return sha256_of_text(
        canonical_dumps(
            {
                "venue": venue,
                "kind": kind,
                "symbol": symbol.upper(),
                "cursor_ms": cursor_ms,
                "interval_minutes": interval_minutes,
                "parser_version": PARSER_VERSION,
            }
        )
    )


class PageArchive:
    """Content-addressed page store + request→bytes index (the resume state).

    Two files back it: ``raw/<sha>.json`` for the bytes, and an append-only
    ``pages_index.jsonl`` mapping a canonical request key to the SHA it
    produced. Both are rewritten idempotently, so an interrupted run resumes
    without a duplicate download or a duplicate receipt.
    """

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.raw_dir = self.dir / "raw"
        self.index_path = self.dir / "pages_index.jsonl"
        self._index: dict[str, dict[str, Any]] = {}
        if self.index_path.exists():
            for line in self.index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                import json

                record = json.loads(line)
                self._index[str(record["request_key"])] = record

    def lookup(self, request_key: str) -> bytes | None:
        record = self._index.get(request_key)
        if record is None:
            return None
        raw_file = self.raw_dir / f"{record['raw_sha256']}.json"
        if not raw_file.exists():
            return None
        raw = raw_file.read_bytes()
        if sha256_of_bytes(raw) != record["raw_sha256"]:
            raise ValueError(
                f"archived page {raw_file} no longer hashes to "
                f"{record['raw_sha256']}: the evidence store is corrupt"
            )
        return raw

    def store(self, request_key: str, url: str, raw: bytes, *, captured_at_utc: str) -> str:
        sha = sha256_of_bytes(raw)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        raw_file = self.raw_dir / f"{sha}.json"
        if not raw_file.exists():
            raw_file.write_bytes(raw)
        if request_key not in self._index:
            record = {
                "request_key": request_key,
                "url": url,
                "raw_sha256": sha,
                "captured_at_utc": captured_at_utc,
                "bytes": len(raw),
            }
            self._index[request_key] = record
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with self.index_path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_dumps(record) + "\n")
        return sha

    @property
    def known_pages(self) -> int:
        return len(self._index)


def _append_attempt(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")


def _host_of(url: str) -> str:
    return urlsplit(url).netloc


class _Session:
    """Fetch + retry + rate-limit + archive + receipt, in one place."""

    def __init__(
        self,
        *,
        directory: Path,
        venue: str,
        fetcher: Fetcher,
        limiter: RateLimiter,
        retry: RetryPolicy,
        sleeper: Callable[[float], None],
        source_kind: str,
        captured_at_utc: str,
    ) -> None:
        self.dir = directory
        self.venue = venue
        self.fetch = fetcher
        self.limiter = limiter
        self.retry = retry
        self.sleep = sleeper
        self.source_kind = source_kind
        self.captured_at_utc = captured_at_utc
        self.archive = PageArchive(directory)
        self.attempts_path = directory / "attempts.jsonl"
        self.receipts_path = directory / "receipts.jsonl"
        self.attempts = 0
        self.blocked_hosts: list[str] = []
        self.server_time_ms: int | None = None

    def get(self, url: str, request_key: str) -> tuple[bytes, bool]:
        """Return ``(raw, replayed)``; raises the last transport error."""
        cached = self.archive.lookup(request_key)
        if cached is not None:
            return cached, True
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            self.limiter.acquire()
            self.attempts += 1
            try:
                status, raw, _headers = self.fetch(url)
            except Exception as exc:  # noqa: BLE001 — the verbatim error IS evidence
                last_error = exc
                _append_attempt(
                    self.attempts_path,
                    {
                        "url": url,
                        "attempt": attempt,
                        "outcome": "transport_error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "host": _host_of(url),
                        "captured_at_utc": self.captured_at_utc,
                    },
                )
                host = _host_of(url)
                if host not in self.blocked_hosts:
                    self.blocked_hosts.append(host)
                if attempt < self.retry.max_attempts:
                    self.sleep(self.retry.delay_for(attempt))
                continue
            if status == 429 or status >= 500:
                last_error = RuntimeError(f"HTTP {status} from {_host_of(url)}")
                _append_attempt(
                    self.attempts_path,
                    {
                        "url": url,
                        "attempt": attempt,
                        "outcome": "http_error",
                        "http_status": status,
                        "host": _host_of(url),
                        "captured_at_utc": self.captured_at_utc,
                    },
                )
                if attempt < self.retry.max_attempts:
                    self.sleep(self.retry.delay_for(attempt))
                continue
            if status != 200:
                raise RuntimeError(f"HTTP {status} from {url}")
            self.archive.store(request_key, url, raw, captured_at_utc=self.captured_at_utc)
            _append_attempt(
                self.attempts_path,
                {
                    "url": url,
                    "attempt": attempt,
                    "outcome": "ok",
                    "http_status": status,
                    "raw_sha256": sha256_of_bytes(raw),
                    "bytes": len(raw),
                    "captured_at_utc": self.captured_at_utc,
                },
            )
            return raw, False
        assert last_error is not None
        raise last_error

    def write_receipt(
        self,
        *,
        url: str,
        params: dict[str, Any],
        raw: bytes,
        rows: list[dict[str, Any]],
        adapter: str,
    ) -> None:
        sha = sha256_of_bytes(raw)
        raw_file = self.archive.raw_dir / f"{sha}.json"
        append_receipt(
            self.receipts_path,
            IngestionReceipt(
                provider_or_venue=self.venue,
                endpoint=url,
                request_parameters=params,
                http_status=200,
                captured_at_utc=self.captured_at_utc,
                adapter_name=adapter,
                adapter_version=PARSER_VERSION,
                raw_path=receipt_relative_path(raw_file, self.receipts_path),
                raw_sha256=sha,
                normalized_rows_sha256=normalized_rows_sha256(rows),
                source_kind=self.source_kind,
                server_timestamp_utc=(
                    _iso(self.server_time_ms) if self.server_time_ms is not None else ""
                ),
            ),
        )


def _walk_series(
    session: _Session, spec: SeriesSpec, request: BackfillRequest
) -> tuple[SeriesResult, dict[int, dict[str, Any]]]:
    """Paginate one series backwards to ``since_ms``, deduplicating by stamp."""
    result = SeriesResult(kind=spec.kind)
    rows_by_ts: dict[int, dict[str, Any]] = {}
    seen_pages: set[str] = set()
    cursor = request.until_ms
    ts_field = spec.timestamp_field

    for _page in range(MAX_PAGES_PER_SERIES):
        url = spec.build_url(
            symbol=request.symbol,
            kind=spec.kind,
            cursor_ms=cursor,
            interval_minutes=request.interval_minutes,
        )
        key = _request_key(
            venue=spec.venue,
            kind=spec.kind,
            symbol=request.symbol,
            cursor_ms=cursor,
            interval_minutes=request.interval_minutes,
        )
        try:
            raw, replayed = session.get(url, key)
        except Exception as exc:  # noqa: BLE001 — verbatim error IS the evidence
            result.status = STATUS_NETWORK_BLOCKED
            result.error = f"{type(exc).__name__}: {exc}"
            return result, rows_by_ts

        try:
            page_rows = spec.parse(raw, symbol=request.symbol, kind=spec.kind)
        except (IdentityMismatch, VenueErrorResponse) as exc:
            result.status = (
                STATUS_PARSE_REJECTED if isinstance(exc, IdentityMismatch) else STATUS_VENUE_ERROR
            )
            result.error = f"{type(exc).__name__}: {exc}"
            return result, rows_by_ts
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            result.status = STATUS_PARSE_REJECTED
            result.error = f"{type(exc).__name__}: {exc}"
            return result, rows_by_ts

        session.write_receipt(
            url=url,
            params={
                "venue": spec.venue,
                "kind": spec.kind,
                "instrument": spec.native_instrument(request.symbol),
                "cursor_ms": cursor,
                "interval_minutes": request.interval_minutes,
                "limit": spec.page_limit,
                "identity_verified_in_body": spec.identity_verifiable,
            },
            raw=raw,
            rows=page_rows,
            adapter=f"v8.backfill.{spec.venue}.{spec.kind}",
        )
        if replayed:
            result.pages_replayed += 1
        else:
            result.pages_fetched += 1

        sha = sha256_of_bytes(raw)
        if not page_rows:
            break
        for row in page_rows:
            stamp = int(row[ts_field])
            if not request.since_ms <= stamp <= request.until_ms:
                continue
            previous = rows_by_ts.get(stamp)
            if previous is not None and previous != row:
                result.conflicting_duplicates += 1
                result.status = STATUS_PARSE_REJECTED
                result.error = (
                    f"conflicting duplicate at {_iso(stamp)}: "
                    f"{canonical_dumps(previous)} vs {canonical_dumps(row)}"
                )
                return result, rows_by_ts
            rows_by_ts[stamp] = row
        oldest = min(int(r[ts_field]) for r in page_rows)
        if sha in seen_pages:
            break  # the venue is repeating a page: pagination is exhausted
        seen_pages.add(sha)
        if oldest <= request.since_ms:
            result.reached_lower_bound = True
            break
        next_cursor = oldest - 1
        if next_cursor >= cursor:
            break  # cursor is not advancing; stop rather than loop forever
        cursor = next_cursor

    result.rows = len(rows_by_ts)
    if rows_by_ts:
        result.oldest_ms = min(rows_by_ts)
        result.newest_ms = max(rows_by_ts)
        if result.oldest_ms <= request.since_ms + request.interval_minutes * 60_000:
            result.reached_lower_bound = True
    return result, rows_by_ts


def run_backfill(
    request: BackfillRequest,
    evidence_root: str | Path,
    *,
    fetcher: Fetcher | None = None,
    retry: RetryPolicy | None = None,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    source_kind: str = "live",
    captured_at_utc: str | None = None,
) -> BackfillResult:
    """Backfill every requested series and persist the evidence.

    ``source_kind`` is the provenance label written into every receipt.
    ``"live"`` is the only value that can ever resolve to REAL; replaying
    recorded bytes in a test passes ``"recorded_test_response"``, which is
    TEST_ONLY forever and cannot promote a strategy.
    """
    directory = evidence_dir_for(evidence_root, request.venue, request.symbol)
    directory.mkdir(parents=True, exist_ok=True)
    started = captured_at_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sleep = sleeper or time.sleep
    session = _Session(
        directory=directory,
        venue=request.venue,
        fetcher=fetcher or (lambda url: http_get(url)),
        limiter=RateLimiter(VENUE_RATE_LIMIT_RPS[request.venue], clock=clock, sleeper=sleeper),
        retry=retry or RetryPolicy(),
        sleeper=sleep,
        source_kind=source_kind,
        captured_at_utc=started,
    )
    result = BackfillResult(
        status=STATUS_OK,
        venue=request.venue,
        symbol=request.symbol.upper(),
        since_ms=request.since_ms,
        until_ms=request.until_ms,
        interval_minutes=request.interval_minutes,
        evidence_dir=str(directory),
        started_at_utc=started,
        provenance="live" if source_kind == "live" else "test_only",
    )

    # The venue's own clock, recorded once and stamped into every receipt.
    time_url = server_time_url(request.venue)
    try:
        raw_time, _ = session.get(
            time_url,
            _request_key(
                venue=request.venue,
                kind="server_time",
                symbol=request.symbol,
                cursor_ms=0,
                interval_minutes=0,
            ),
        )
        session.server_time_ms = parse_server_time(request.venue, raw_time)
        result.server_time_ms = session.server_time_ms
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"server_time: {type(exc).__name__}: {exc}")

    # Instrument metadata (contract terms, funding interval, listing date).
    inst_url = instruments_url(request.venue, request.symbol)
    try:
        raw_inst, _ = session.get(
            inst_url,
            _request_key(
                venue=request.venue,
                kind="instruments",
                symbol=request.symbol,
                cursor_ms=0,
                interval_minutes=0,
            ),
        )
        rows = parse_instruments(request.venue, raw_inst, symbol=request.symbol)
        session.write_receipt(
            url=inst_url,
            params={
                "venue": request.venue,
                "kind": "instruments",
                "instrument": request.symbol.upper(),
            },
            raw=raw_inst,
            rows=rows,
            adapter=f"v8.backfill.{request.venue}.instruments",
        )
        result.instrument_metadata = rows
        atomic_write_json(directory / "instrument_metadata.json", rows)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"instruments: {type(exc).__name__}: {exc}")

    series_dir = directory / "series"
    series_dir.mkdir(parents=True, exist_ok=True)
    for kind in request.kinds:
        spec = series_spec(request.venue, kind)
        series_result, rows_by_ts = _walk_series(session, spec, request)
        result.series[kind] = series_result
        if rows_by_ts:
            ordered = [rows_by_ts[k] for k in sorted(rows_by_ts)]
            (series_dir / f"{kind}.jsonl").write_text(
                "".join(canonical_dumps(r) + "\n" for r in ordered), encoding="utf-8"
            )
        if series_result.status != STATUS_OK:
            result.status = series_result.status
            result.errors.append(f"{kind}: {series_result.error}")
        if kind == "funding":
            result.settlements = series_result.rows

    result.attempts = session.attempts
    result.blocked_hosts = list(session.blocked_hosts)
    result.finished_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if result.status == STATUS_OK and any(s.status != STATUS_OK for s in result.series.values()):
        result.status = STATUS_PARSE_REJECTED
    atomic_write_json(directory / "backfill_result.json", result.to_dict())
    _append_attempt(directory / "runs.jsonl", result.to_dict())
    return result


__all__ = [
    "MAX_PAGES_PER_SERIES",
    "STATUS_NETWORK_BLOCKED",
    "STATUS_OK",
    "STATUS_PARSE_REJECTED",
    "STATUS_VENUE_ERROR",
    "BackfillRequest",
    "BackfillResult",
    "Fetcher",
    "PageArchive",
    "RateLimiter",
    "RetryPolicy",
    "SeriesResult",
    "evidence_dir_for",
    "http_get",
    "run_backfill",
]
