"""Venue-native daily klines for the point-in-time universe (Bybit v5 spot).

The snapshot source says which coins existed and at what market cap. It does
not say what could actually be *traded*, and a strategy can only trade venue
prices — so every price used downstream comes from here, and snapshot prices
stay a cross-check.

The survivorship discipline of `quant_trade.data.universe` applies unchanged,
with one addition that matters more than it looks: **"the venue never listed
this coin" is a journaled outcome, not a skip.** A collector that silently drops
unlisted symbols rebuilds the survivorship bias on the venue leg after the
snapshot leg went to such trouble to avoid it — the tradable universe would
quietly become "coins Bybit lists today", which is the same poison in a
different bottle. Bybit returns ``retCode=10001 'Not supported symbols'`` for a
symbol it never listed, and full history for symbols it delisted years ago
(measured: ``SRMUSDT`` returns 2021-2024 bars), so the two cases are
distinguishable and are recorded as different outcomes.

Same four defences as the universe collector: persisted wall-clock, hash-chained
journal under a single-writer lease, gaps first-class with the verbatim error,
and a frozen policy hash. pandas-free.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quant_trade.carry.backfill import fetch_public_bytes
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

#: Frozen collection policy. Changing ANY of it makes a different dataset.
VENUE_POLICY: dict[str, Any] = {
    "venue": "bybit",
    "api": "v5",
    "endpoint": "https://api.bybit.com/v5/market/kline",
    "category": "spot",
    "interval": "D",
    "quote_asset": "USDT",
    "page_limit": 1000,
    "symbol_template": "{base}USDT",
    "normalized_fields": [
        "date",
        "start_ms",
        "open",
        "high",
        "low",
        "close",
        "volume_base",
        "turnover_quote",
    ],
    "unlisted_ret_codes": [10001],
    "filtering_at_collection": (
        "none - every requested symbol gets a journaled outcome, including "
        "'venue never listed it'"
    ),
}

VENUE_POLICY_SHA256 = sha256_of_text(canonical_dumps(VENUE_POLICY))

KLINE_URL = (
    "{endpoint}?category={category}&symbol={symbol}&interval={interval}"
    "&start={start_ms}&limit={limit}"
)

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
    symbols_requested: int = 0
    symbols_already_done: int = 0
    symbols_listed: int = 0
    symbols_not_listed: int = 0
    symbols_empty: int = 0
    rows_written: int = 0
    gap_symbols: list[str] = field(default_factory=list)
    error: str = ""
    policy_sha256: str = VENUE_POLICY_SHA256
    clock_source: str = CLOCK_SYSTEM
    provenance: str = "real"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VenueKlineError(RuntimeError):
    """Journal integrity or lease violations. Loud by design."""


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


class SymbolNotListed(Exception):
    """The venue has no such instrument — distinct from 'no bars in range'."""


def parse_kline_page(raw: bytes, *, symbol: str) -> list[dict[str, Any]]:
    """Normalize one Bybit v5 kline page, refusing to relabel someone else's bars.

    Raises ``SymbolNotListed`` when the venue reports an unknown instrument, so
    the caller can journal that as its own outcome instead of an empty result
    that looks identical to a coin that merely had no trading in the window.
    """
    payload = json.loads(raw)
    ret_code = int(payload.get("retCode", -1))
    if ret_code in VENUE_POLICY["unlisted_ret_codes"]:
        raise SymbolNotListed(f"{symbol}: retMsg={payload.get('retMsg')!r}")
    if ret_code != 0:
        raise ValueError(
            f"bybit error retCode={ret_code} retMsg={payload.get('retMsg')!r}"
        )
    result = payload.get("result") or {}
    got = str(result.get("symbol", ""))
    if got and got != symbol:
        raise ValueError(
            f"instrument identity mismatch: requested {symbol}, page carries "
            f"{got!r} - refusing to relabel klines"
        )
    rows: list[dict[str, Any]] = []
    for row in result.get("list") or []:
        entry: dict[str, Any] = {
            "date": _ms_to_date(int(row[0])),
            "start_ms": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume_base": float(row[5]),
            "turnover_quote": float(row[6]),
        }
        for name in ("open", "high", "low", "close"):
            if entry[name] <= 0:
                raise ValueError(f"non-positive {name} in kline page for {symbol}")
        if entry["volume_base"] < 0 or entry["turnover_quote"] < 0:
            raise ValueError(f"negative volume/turnover in kline page for {symbol}")
        rows.append(entry)
    rows.sort(key=lambda r: r["start_ms"])
    return rows


def _fetch_symbol_history(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    fetch: Callable[[str], bytes],
    on_page: Callable[[bytes, list[dict[str, Any]], int], None],
) -> list[dict[str, Any]]:
    """Page forward through one symbol's daily history."""
    collected: dict[int, dict[str, Any]] = {}
    cursor = start_ms
    for _ in range(MAX_PAGES_PER_SYMBOL):
        url = KLINE_URL.format(
            endpoint=VENUE_POLICY["endpoint"],
            category=VENUE_POLICY["category"],
            symbol=symbol,
            interval=VENUE_POLICY["interval"],
            start_ms=cursor,
            limit=VENUE_POLICY["page_limit"],
        )
        raw = fetch(url)
        rows = parse_kline_page(raw, symbol=symbol)
        on_page(raw, rows, cursor)
        if not rows:
            break
        fresh = [r for r in rows if r["start_ms"] not in collected and r["start_ms"] <= end_ms]
        for row in fresh:
            collected[row["start_ms"]] = row
        newest = rows[-1]["start_ms"]
        if newest >= end_ms or len(rows) < VENUE_POLICY["page_limit"]:
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
    start_date: date,
    end_date: date,
    fetcher: Callable[[str], bytes] | None = None,
    clock: Callable[[], float] | None = None,
    sleep_seconds: float = 0.0,
    timeout_seconds: float = 30.0,
    max_symbols_per_run: int | None = None,
) -> VenueKlineResult:
    """Collect daily venue klines for ``symbols`` over ``[start_date, end_date]``.

    Resumable and idempotent: symbols already journaled with a terminal outcome
    are skipped; symbols journaled only as gaps are retried.
    """
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
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
        else (lambda url: fetch_public_bytes(url, timeout_seconds=timeout_seconds))
    )
    result = VenueKlineResult(
        status="OK",
        out_dir=str(out),
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

    start_ms = int(
        datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
        .timestamp()
        * 1000
    )
    end_ms = int(
        datetime(end_date.year, end_date.month, end_date.day, tzinfo=UTC)
        .timestamp()
        * 1000
    )

    lease = _Lease(out / LEASE_FILENAME)
    lease.acquire()
    try:
        if records:
            header = records[0]
            if header.get("policy_sha256") != VENUE_POLICY_SHA256:
                result.status = "NOT_RUN_JOURNAL_INVALID"
                result.error = (
                    f"journal was started under policy {header.get('policy_sha256')!r}; "
                    f"current policy is {VENUE_POLICY_SHA256!r}. A changed policy is a "
                    "new dataset - collect into a fresh directory."
                )
                return result
            if header.get("window") != [start_date.isoformat(), end_date.isoformat()]:
                result.status = "NOT_RUN_JOURNAL_INVALID"
                result.error = (
                    f"journal covers window {header.get('window')}; this run asks for "
                    f"{[start_date.isoformat(), end_date.isoformat()]}. Symbols already "
                    "journaled were resolved against the old window, so mixing them "
                    "would misreport coverage - collect into a fresh directory."
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
                    "policy_sha256": VENUE_POLICY_SHA256,
                    "policy": VENUE_POLICY,
                    "window": [start_date.isoformat(), end_date.isoformat()],
                    "wall_clock_utc": _utc_stamp(active_clock),
                    "clock_source": clock_source,
                },
            )

        terminal = {
            r["symbol"]
            for r in records
            if r.get("type") == "symbol" and r.get("outcome") in
            (OUTCOME_LISTED, OUTCOME_NOT_LISTED, OUTCOME_EMPTY)
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
                raw: bytes,
                rows: list[dict[str, Any]],
                cursor: int,
                _symbol: str = symbol,
                _shas: list[str] = raw_shas,
            ) -> None:
                nonlocal page_count
                page_count += 1
                sha = sha256_of_bytes(raw)
                raw_dir = out / "raw"
                raw_dir.mkdir(exist_ok=True)
                raw_file = raw_dir / f"{sha}.json"
                if not raw_file.exists():
                    raw_file.write_bytes(raw)
                append_receipt(
                    out / "receipts.jsonl",
                    IngestionReceipt(
                        provider_or_venue="bybit",
                        endpoint=str(VENUE_POLICY["endpoint"]),
                        request_parameters={"symbol": _symbol, "start": cursor},
                        http_status=200,
                        captured_at_utc=_utc_stamp(active_clock),
                        adapter_name="data.venue_klines.bybit_v5_spot",
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
    "OUTCOME_EMPTY",
    "OUTCOME_LISTED",
    "OUTCOME_NOT_LISTED",
    "VENUE_POLICY",
    "VENUE_POLICY_SHA256",
    "SymbolNotListed",
    "VenueKlineError",
    "VenueKlineResult",
    "collect_venue_klines",
    "parse_kline_page",
]
