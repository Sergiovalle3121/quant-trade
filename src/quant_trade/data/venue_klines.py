"""Venue-native daily klines for the point-in-time universe (Bybit v5, Binance).

The snapshot source says which coins existed and at what market cap. It does
not say what could actually be *traded*, and a strategy can only trade venue
prices — so every price used downstream comes from here, and snapshot prices
stay a cross-check.

The survivorship discipline of `quant_trade.data.universe` applies unchanged,
with one addition that matters more than it looks: **"the venue never listed
this coin" is a journaled outcome, not a skip.** A collector that silently drops
unlisted symbols rebuilds the survivorship bias on the venue leg after the
snapshot leg went to such trouble to avoid it — the tradable universe would
quietly become "coins the venue lists today", which is the same poison in a
different bottle. Both venues distinguish the cases and so does this module
(all measured 2026-08-11):

- Bybit answers ``retCode=10001 'Not supported symbols'`` over HTTP 200 for an
  instrument it never listed, and serves full history for ones it delisted
  years ago (``SRMUSDT`` → 2021-10-22..2024-11-22).
- Binance answers HTTP 400 ``{"code":-1121,"msg":"Invalid symbol."}``, and also
  serves delisted history (``BCCUSDT`` → 2017-11-11..2018-11-20).

Two venues because they disagree, and the disagreement is data. Bybit spot
starts 2021-07-05; Binance reaches back to 2017-08-17. The same coin can die on
different dates at each venue (``SRMUSDT`` ends 2022-11-28 on Binance but runs
to 2024-11-22 on Bybit) — one venue delisting is not the coin dying, and a
single-venue panel cannot tell those apart.

Each venue is its own dataset directory under its own frozen policy hash. They
are never merged here; composing them is a downstream decision that has to be
declared, because the measured cost model was calibrated on Bybit books only.

Same four defences as the universe collector: persisted wall-clock, hash-chained
journal under a single-writer lease, gaps first-class with the verbatim error,
and a frozen policy hash. pandas-free.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quant_trade.carry.backfill import USER_AGENT
from quant_trade.data.universe import (
    CLOCK_INJECTED,
    CLOCK_SYSTEM,
    LEASE_STALE_SECONDS,
    UniverseCollectorError,
    read_journal,
    verify_journal_chain,
)
from quant_trade.evidence.canonical_json import (
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

SCHEMA_VERSION = 1

MS_PER_DAY = 86_400_000

VENUE_BYBIT = "bybit"
VENUE_BINANCE = "binance"

#: Frozen per-venue collection policies. Changing ANY field makes a different
#: dataset: the hash is sealed into the journal header and re-verified on
#: resume. Normalized output is identical across venues so downstream code
#: never branches on provenance by accident.
VENUE_POLICIES: dict[str, dict[str, Any]] = {
    VENUE_BYBIT: {
        "venue": VENUE_BYBIT,
        "api": "v5",
        "endpoint": "https://api.bybit.com/v5/market/kline",
        "url_template": (
            "{endpoint}?category=spot&symbol={symbol}&interval=D"
            "&start={start_ms}&limit={limit}"
        ),
        "market": "spot",
        "interval": "1d",
        "quote_asset": "USDT",
        "page_limit": 1000,
        "symbol_template": "{base}USDT",
        "page_order": "newest_first",
        "not_listed_signal": "http 200 with retCode 10001",
        "earliest_known_bar": "2021-07-05",
    },
    VENUE_BINANCE: {
        "venue": VENUE_BINANCE,
        "api": "v3",
        "endpoint": "https://api.binance.com/api/v3/klines",
        "url_template": (
            "{endpoint}?symbol={symbol}&interval=1d&startTime={start_ms}&limit={limit}"
        ),
        "market": "spot",
        "interval": "1d",
        "quote_asset": "USDT",
        "page_limit": 1000,
        "symbol_template": "{base}USDT",
        "page_order": "oldest_first",
        "not_listed_signal": "http 400 with code -1121",
        "earliest_known_bar": "2017-08-17",
    },
}

#: Fields every venue normalizes to, whatever its wire format.
NORMALIZED_FIELDS = (
    "date",
    "start_ms",
    "open",
    "high",
    "low",
    "close",
    "volume_base",
    "turnover_quote",
)

VENUE_POLICY_SHA256: dict[str, str] = {
    venue: sha256_of_text(canonical_dumps(policy))
    for venue, policy in VENUE_POLICIES.items()
}

JOURNAL_FILENAME = "journal.jsonl"
LEASE_FILENAME = "journal.lease"
#: Abort after this many consecutive network failures: a dead network should
#: cost one gap record per symbol until it is obviously down, not thousands.
CONSECUTIVE_FAILURE_ABORT = 5
#: Refuse to loop forever if the venue stops advancing the cursor.
MAX_PAGES_PER_SYMBOL = 40

OUTCOME_LISTED = "listed"
OUTCOME_NOT_LISTED = "not_listed"
OUTCOME_EMPTY = "listed_but_no_bars_in_range"


@dataclass
class VenueKlineResult:
    status: str  # "OK" | "PARTIAL" | "NOT_RUN_NETWORK_BLOCKED" | "NOT_RUN_JOURNAL_INVALID"
    out_dir: str
    venue: str = ""
    symbols_requested: int = 0
    symbols_already_done: int = 0
    symbols_listed: int = 0
    symbols_not_listed: int = 0
    symbols_empty: int = 0
    rows_written: int = 0
    gap_symbols: list[str] = field(default_factory=list)
    error: str = ""
    policy_sha256: str = ""
    clock_source: str = CLOCK_SYSTEM
    provenance: str = "real"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VenueKlineError(RuntimeError):
    """Journal integrity or lease violations. Loud by design."""


class SymbolNotListed(Exception):
    """The venue has no such instrument — distinct from 'no bars in range'."""


@dataclass(frozen=True)
class HttpResponse:
    """An HTTP outcome, including error bodies.

    Venues signal "no such instrument" in the body of a 4xx as often as in a
    200, so the body of a failed response is evidence and must survive rather
    than be swallowed by an exception.
    """

    status: int
    body: bytes


def fetch_with_status(url: str, *, timeout_seconds: float = 30.0) -> HttpResponse:
    """GET a public endpoint, returning error bodies instead of raising on 4xx/5xx."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(int(response.status), bytes(response.read()))
    except urllib.error.HTTPError as exc:
        return HttpResponse(int(exc.code), bytes(exc.read()))


def _utc_stamp(clock: Callable[[], float]) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))


def _record_sha(record: dict[str, Any]) -> str:
    return sha256_of_text(canonical_dumps(record))


def _append_record(
    journal_path: Path, records: list[dict[str, Any]], record: dict[str, Any]
) -> None:
    record["previous_sha256"] = _record_sha(records[-1]) if records else ""
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")
    records.append(record)


def _ms_to_date(start_ms: int) -> str:
    return datetime.fromtimestamp(start_ms / 1000.0, UTC).date().isoformat()


class _Lease:
    """Single-writer lease; a second writer fails loudly rather than
    interleaving the journal into something indistinguishable from tampering."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self) -> None:
        if self.path.exists():
            try:
                stamped = float(self.path.read_text(encoding="utf-8").split(":")[1])
            except (IndexError, ValueError):
                stamped = 0.0
            if time.time() - stamped < LEASE_STALE_SECONDS:
                raise VenueKlineError(
                    f"another writer holds the lease ({self.path}); "
                    "refusing to interleave the journal"
                )
        self.path.write_text(f"{os.getpid()}:{time.time()}", encoding="utf-8")

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()


def _row_from_fields(
    start_ms: int, o: str, h: str, low: str, c: str, base: str, quote: str, symbol: str
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "date": _ms_to_date(start_ms),
        "start_ms": start_ms,
        "open": float(o),
        "high": float(h),
        "low": float(low),
        "close": float(c),
        "volume_base": float(base),
        "turnover_quote": float(quote),
    }
    for name in ("open", "high", "low", "close"):
        if entry[name] <= 0:
            raise ValueError(f"non-positive {name} in kline page for {symbol}")
    if entry["volume_base"] < 0 or entry["turnover_quote"] < 0:
        raise ValueError(f"negative volume/turnover in kline page for {symbol}")
    return entry


def _parse_bybit(response: HttpResponse, symbol: str) -> list[dict[str, Any]]:
    if response.status != 200:
        raise ValueError(f"bybit http {response.status}: {response.body[:200]!r}")
    payload = json.loads(response.body)
    ret_code = int(payload.get("retCode", -1))
    if ret_code == 10001:
        raise SymbolNotListed(f"{symbol}: retMsg={payload.get('retMsg')!r}")
    if ret_code != 0:
        raise ValueError(f"bybit retCode={ret_code} retMsg={payload.get('retMsg')!r}")
    result = payload.get("result") or {}
    got = str(result.get("symbol", ""))
    if got and got != symbol:
        raise ValueError(
            f"instrument identity mismatch: requested {symbol}, page carries "
            f"{got!r} - refusing to relabel klines"
        )
    return [
        _row_from_fields(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], symbol)
        for r in result.get("list") or []
    ]


def _parse_binance(response: HttpResponse, symbol: str) -> list[dict[str, Any]]:
    if response.status != 200:
        try:
            payload = json.loads(response.body)
        except (ValueError, TypeError):
            payload = {}
        if int(payload.get("code", 0)) == -1121:
            raise SymbolNotListed(f"{symbol}: msg={payload.get('msg')!r}")
        raise ValueError(f"binance http {response.status}: {response.body[:200]!r}")
    payload = json.loads(response.body)
    if not isinstance(payload, list):
        raise ValueError(f"binance page is not a list: {response.body[:200]!r}")
    # [openTime, open, high, low, close, volume, closeTime, quoteAssetVolume, ...]
    return [
        _row_from_fields(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[7], symbol)
        for r in payload
    ]


_PARSERS: dict[str, Callable[[HttpResponse, str], list[dict[str, Any]]]] = {
    VENUE_BYBIT: _parse_bybit,
    VENUE_BINANCE: _parse_binance,
}


def parse_kline_page(
    response: HttpResponse, *, symbol: str, venue: str
) -> list[dict[str, Any]]:
    """Normalize one venue page, refusing to relabel someone else's bars.

    Raises ``SymbolNotListed`` when the venue reports an unknown instrument, so
    the caller can journal that as its own outcome instead of an empty result
    that looks identical to a coin that merely had no trading in the window.
    """
    if venue not in _PARSERS:
        raise ValueError(f"unknown venue {venue!r}; known: {sorted(_PARSERS)}")
    rows = _PARSERS[venue](response, symbol)
    rows.sort(key=lambda r: r["start_ms"])
    return rows


def _fetch_symbol_history(
    symbol: str,
    *,
    venue: str,
    start_ms: int,
    end_ms: int,
    fetch: Callable[[str], HttpResponse],
    on_page: Callable[[HttpResponse, list[dict[str, Any]], int], None],
) -> list[dict[str, Any]]:
    """Page forward through one symbol's daily history."""
    policy = VENUE_POLICIES[venue]
    limit = int(policy["page_limit"])
    collected: dict[int, dict[str, Any]] = {}
    cursor = start_ms
    for _ in range(MAX_PAGES_PER_SYMBOL):
        url = str(policy["url_template"]).format(
            endpoint=policy["endpoint"], symbol=symbol, start_ms=cursor, limit=limit
        )
        response = fetch(url)
        # Archive and receipt the page BEFORE interpreting it. "The venue never
        # listed this coin" is the single most consequential exclusion in the
        # pipeline — it deletes the coin from the tradable universe — so the
        # bytes behind that verdict have to survive as evidence exactly like the
        # bytes behind a successful fetch. Parsing first would archive every
        # page except the ones that justify an exclusion.
        try:
            rows = parse_kline_page(response, symbol=symbol, venue=venue)
        except SymbolNotListed:
            on_page(response, [], cursor)
            raise
        on_page(response, rows, cursor)
        if not rows:
            break
        for row in rows:
            if row["start_ms"] not in collected and row["start_ms"] <= end_ms:
                collected[row["start_ms"]] = row
        newest = rows[-1]["start_ms"]
        if newest >= end_ms or len(rows) < limit:
            break
        next_cursor = newest + MS_PER_DAY
        if next_cursor <= cursor:
            # The venue stopped advancing; looping would fabricate progress.
            break
        cursor = next_cursor
    return [collected[key] for key in sorted(collected)]


def collect_venue_klines(
    out_dir: str | Path,
    symbols: Iterable[str],
    *,
    venue: str = VENUE_BYBIT,
    start_date: date,
    end_date: date,
    fetcher: Callable[[str], HttpResponse] | None = None,
    clock: Callable[[], float] | None = None,
    sleep_seconds: float = 0.0,
    timeout_seconds: float = 30.0,
    max_symbols_per_run: int | None = None,
) -> VenueKlineResult:
    """Collect daily venue klines for ``symbols`` over ``[start_date, end_date]``.

    Resumable and idempotent: symbols already journaled with a terminal outcome
    are skipped; symbols journaled only as gaps are retried.
    """
    if venue not in VENUE_POLICIES:
        raise ValueError(f"unknown venue {venue!r}; known: {sorted(VENUE_POLICIES)}")
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    policy_sha = VENUE_POLICY_SHA256[venue]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    series_dir = out / "series"
    series_dir.mkdir(exist_ok=True)
    journal_path = out / JOURNAL_FILENAME
    clock_source = CLOCK_SYSTEM if clock is None else CLOCK_INJECTED
    active_clock = clock if clock is not None else time.time
    active_fetch = (
        fetcher
        if fetcher is not None
        else (lambda url: fetch_with_status(url, timeout_seconds=timeout_seconds))
    )
    result = VenueKlineResult(
        status="OK",
        out_dir=str(out),
        venue=venue,
        policy_sha256=policy_sha,
        clock_source=clock_source,
        provenance="test_only" if clock_source == CLOCK_INJECTED else "real",
    )

    records = read_journal(journal_path)
    try:
        verify_journal_chain(records)
    except UniverseCollectorError as exc:
        result.status = "NOT_RUN_JOURNAL_INVALID"
        result.error = str(exc)
        return result

    def _epoch_ms(day: date) -> int:
        return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)

    start_ms = _epoch_ms(start_date)
    end_ms = _epoch_ms(end_date)

    lease = _Lease(out / LEASE_FILENAME)
    lease.acquire()
    try:
        window = [start_date.isoformat(), end_date.isoformat()]
        if records:
            header = records[0]
            if header.get("policy_sha256") != policy_sha:
                result.status = "NOT_RUN_JOURNAL_INVALID"
                result.error = (
                    f"journal was started under policy {header.get('policy_sha256')!r} "
                    f"(venue {header.get('venue')!r}); this run carries {policy_sha!r} "
                    f"(venue {venue!r}). A changed policy is a new dataset - collect "
                    "into a fresh directory."
                )
                return result
            if header.get("window") != window:
                result.status = "NOT_RUN_JOURNAL_INVALID"
                result.error = (
                    f"journal covers window {header.get('window')}; this run asks for "
                    f"{window}. Symbols already journaled were resolved against the old "
                    "window, so mixing them would misreport coverage - collect into a "
                    "fresh directory."
                )
                return result
            if header.get("clock_source") == CLOCK_INJECTED:
                result.provenance = "test_only"  # an injected past is forever
        else:
            _append_record(
                journal_path,
                records,
                {
                    "type": "header",
                    "schema_version": SCHEMA_VERSION,
                    "venue": venue,
                    "policy_sha256": policy_sha,
                    "policy": VENUE_POLICIES[venue],
                    "normalized_fields": list(NORMALIZED_FIELDS),
                    "window": window,
                    "wall_clock_utc": _utc_stamp(active_clock),
                    "clock_source": clock_source,
                },
            )

        terminal = {
            r["symbol"]
            for r in records
            if r.get("type") == "symbol"
            and r.get("outcome") in (OUTCOME_LISTED, OUTCOME_NOT_LISTED, OUTCOME_EMPTY)
        }
        requested = list(dict.fromkeys(str(s).upper() for s in symbols))
        result.symbols_requested = len(requested)
        result.symbols_already_done = sum(1 for s in requested if s in terminal)

        consecutive_failures = 0
        processed = 0
        for symbol in requested:
            if symbol in terminal:
                continue
            if max_symbols_per_run is not None and processed >= max_symbols_per_run:
                result.status = "PARTIAL"
                break
            raw_shas: list[str] = []
            page_count = 0

            def on_page(
                response: HttpResponse,
                rows: list[dict[str, Any]],
                cursor: int,
                _symbol: str = symbol,
                _shas: list[str] = raw_shas,
            ) -> None:
                nonlocal page_count
                page_count += 1
                sha = sha256_of_bytes(response.body)
                raw_dir = out / "raw"
                raw_dir.mkdir(exist_ok=True)
                raw_file = raw_dir / f"{sha}.json"
                if not raw_file.exists():
                    raw_file.write_bytes(response.body)
                append_receipt(
                    out / "receipts.jsonl",
                    IngestionReceipt(
                        provider_or_venue=venue,
                        endpoint=str(VENUE_POLICIES[venue]["endpoint"]),
                        request_parameters={"symbol": _symbol, "start_ms": cursor},
                        http_status=response.status,
                        captured_at_utc=_utc_stamp(active_clock),
                        adapter_name=f"data.venue_klines.{venue}_spot",
                        adapter_version=str(SCHEMA_VERSION),
                        raw_path=receipt_relative_path(raw_file, out / "receipts.jsonl"),
                        raw_sha256=sha,
                        normalized_rows_sha256=normalized_rows_sha256(rows),
                        source_kind="fixture" if fetcher is not None else "live",
                    ),
                )
                _shas.append(sha)

            outcome: str
            rows: list[dict[str, Any]] = []
            failure: str | None = None
            try:
                rows = _fetch_symbol_history(
                    symbol,
                    venue=venue,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    fetch=active_fetch,
                    on_page=on_page,
                )
                outcome = OUTCOME_LISTED if rows else OUTCOME_EMPTY
            except SymbolNotListed:
                outcome = OUTCOME_NOT_LISTED
            except ValueError as exc:
                failure = f"NOT_RUN_PARSE_REJECTED: {exc}"
                outcome = "gap"
            except Exception as exc:  # noqa: BLE001 - the verbatim error IS the evidence
                failure = f"NOT_RUN_NETWORK_BLOCKED: {type(exc).__name__}: {exc}"
                outcome = "gap"

            if failure is not None:
                _append_record(
                    journal_path,
                    records,
                    {
                        "type": "gap",
                        "symbol": symbol,
                        "error": failure,
                        "wall_clock_utc": _utc_stamp(active_clock),
                        "clock_source": clock_source,
                    },
                )
                result.gap_symbols.append(symbol)
                consecutive_failures += 1
                if consecutive_failures >= CONSECUTIVE_FAILURE_ABORT:
                    result.status = "NOT_RUN_NETWORK_BLOCKED"
                    result.error = (
                        f"{consecutive_failures} consecutive failures, last: {failure}"
                    )
                    break
                continue
            consecutive_failures = 0

            record: dict[str, Any] = {
                "type": "symbol",
                "symbol": symbol,
                "outcome": outcome,
                "row_count": len(rows),
                "pages_fetched": page_count,
                "raw_sha256s": raw_shas,
                "wall_clock_utc": _utc_stamp(active_clock),
                "clock_source": clock_source,
            }
            if rows:
                series_file = series_dir / f"{symbol}.jsonl"
                with series_file.open("w", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(canonical_dumps(row) + "\n")
                record["first_date"] = rows[0]["date"]
                record["last_date"] = rows[-1]["date"]
                record["series_file_sha256"] = sha256_of_bytes(series_file.read_bytes())
                result.rows_written += len(rows)
                result.symbols_listed += 1
            elif outcome == OUTCOME_NOT_LISTED:
                result.symbols_not_listed += 1
            else:
                result.symbols_empty += 1
            _append_record(journal_path, records, record)
            processed += 1
            if sleep_seconds:
                time.sleep(sleep_seconds)

        if result.status == "OK" and result.gap_symbols:
            result.status = "PARTIAL"
        return result
    finally:
        lease.release()


__all__ = [
    "MS_PER_DAY",
    "NORMALIZED_FIELDS",
    "OUTCOME_EMPTY",
    "OUTCOME_LISTED",
    "OUTCOME_NOT_LISTED",
    "VENUE_BINANCE",
    "VENUE_BYBIT",
    "VENUE_POLICIES",
    "VENUE_POLICY_SHA256",
    "HttpResponse",
    "SymbolNotListed",
    "VenueKlineError",
    "VenueKlineResult",
    "collect_venue_klines",
    "fetch_with_status",
    "parse_kline_page",
]
