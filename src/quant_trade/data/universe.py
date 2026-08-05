"""Point-in-time universe collector for low/mid-cap crypto.

Collects one CMC historical snapshot per day — which coins existed, at what
market cap, rank and volume, on that date — implementing the four defences of
`docs/COLLECTOR_INTEGRITY_PATTERN.md` plus the Defect E rule:

1. **Persisted wall-clock**: every journal record carries ``wall_clock_utc``
   and ``clock_source`` at write time. An injected clock marks the journal
   ``test_only`` forever; replaying archived pages advances counts, never
   elapsed time.
2. **Hash-chained journal**: every record carries ``previous_sha256`` over
   the predecessor's canonical bytes; ``verify_journal_chain`` re-walks from
   the genesis header on every resume. One writer at a time, enforced by a
   lease file that fails loudly.
3. **Gaps are first-class**: a snapshot date that could not be fetched is a
   ``gap`` record carrying the verbatim error. Missing days are never
   interpolated; coverage is recomputed downstream from the journal, and a
   gap date is retried on the next run without erasing its gap record.
4. **Frozen policy hash**: the collection policy (endpoint, pagination,
   normalization) is hashed into the header; resuming under a different
   policy is refused — a changed policy is a new dataset, not a continuation.

Defect E: this module never reports its own freshness or coverage as truth;
`quant_trade.data.quality.universe` recomputes both from the journal and the
day files.

The module is deliberately pandas-free so acquisition can run on machines
where pandas is unavailable; validation (pandas) lives in the quality package.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from quant_trade.carry.backfill import fetch_public_bytes
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes, sha256_of_text
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
    receipt_relative_path,
)

SCHEMA_VERSION = 1

#: The frozen collection policy. Changing ANY of this makes a different
#: dataset: the hash is sealed into the journal header and re-verified on
#: resume (the collector-side twin of research/preregistration.py).
UNIVERSE_POLICY: dict[str, Any] = {
    "source": "coinmarketcap-data-api",
    "endpoint": "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical",
    "convert_id": 2781,
    "page_limit": 5000,
    "page_starts": [1, 5001],
    "normalized_fields": [
        "cmc_id",
        "symbol",
        "name",
        "cmc_rank",
        "market_cap_usd",
        "volume24h_usd",
        "circulating_supply",
    ],
    "filtering_at_collection": "none - the full snapshot is archived; screens are downstream",
}

UNIVERSE_POLICY_SHA256 = sha256_of_text(canonical_dumps(UNIVERSE_POLICY))

SNAPSHOT_URL = (
    "{endpoint}?date={date}&limit={limit}&start={start}&convertId={convert}"
)

JOURNAL_FILENAME = "journal.jsonl"
LEASE_FILENAME = "journal.lease"
#: A lease heartbeat older than this belongs to a dead writer.
LEASE_STALE_SECONDS = 900.0
#: Abort a run after this many consecutive fetch failures: a dead network is
#: one gap record per day only until it is obviously down, not thousands.
CONSECUTIVE_FAILURE_ABORT = 5

CLOCK_SYSTEM = "system"
CLOCK_INJECTED = "injected_test"


class UniverseCollectorError(RuntimeError):
    """Journal integrity or lease violations. Loud by design."""


@dataclass
class UniverseCollectionResult:
    status: str  # "OK" | "PARTIAL" | "NOT_RUN_NETWORK_BLOCKED" | "NOT_RUN_JOURNAL_INVALID"
    out_dir: str
    days_requested: int = 0
    days_already_done: int = 0
    days_collected: int = 0
    gap_dates: list[str] = field(default_factory=list)
    error: str = ""
    policy_sha256: str = UNIVERSE_POLICY_SHA256
    clock_source: str = CLOCK_SYSTEM
    provenance: str = "real"

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def _utc_stamp(clock: Callable[[], float]) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))


def _record_sha(record: dict[str, Any]) -> str:
    return sha256_of_text(canonical_dumps(record))


def read_journal(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.exists():
        return []
    records = []
    with journal_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def verify_journal_chain(records: list[dict[str, Any]]) -> None:
    """Re-walk the whole chain; any edit, deletion or reorder breaks it."""
    if not records:
        return
    if records[0].get("type") != "header":
        raise UniverseCollectorError("journal does not start with a header record")
    if records[0].get("previous_sha256") != "":
        raise UniverseCollectorError("genesis record must have empty previous_sha256")
    for index in range(1, len(records)):
        expected = _record_sha(records[index - 1])
        found = records[index].get("previous_sha256")
        if found != expected:
            raise UniverseCollectorError(
                f"journal chain broken at record {index}: "
                f"previous_sha256={found!r} expected {expected!r}"
            )


def _append_record(
    journal_path: Path, records: list[dict[str, Any]], record: dict[str, Any]
) -> None:
    record["previous_sha256"] = _record_sha(records[-1]) if records else ""
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")
    records.append(record)


class _Lease:
    """Single-writer lease. Two interleaved writers would break the chain in
    ways indistinguishable from tampering, so the second writer fails loudly."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self) -> None:
        if self.path.exists():
            try:
                stamped = float(self.path.read_text(encoding="utf-8").split(":")[1])
            except (IndexError, ValueError):
                stamped = 0.0
            age = time.time() - stamped
            if age < LEASE_STALE_SECONDS:
                raise UniverseCollectorError(
                    f"another writer holds the lease ({self.path}, heartbeat {age:.0f}s old); "
                    "refusing to interleave the journal"
                )
        self.path.write_text(f"{os.getpid()}:{time.time()}", encoding="utf-8")

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()


def parse_snapshot_page(raw: bytes) -> list[dict[str, Any]]:
    """Normalize one CMC snapshot page to the policy's declared fields."""
    payload = json.loads(raw)
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("snapshot page: 'data' is not a list")
    rows: list[dict[str, Any]] = []
    for entry in data:
        quotes = entry.get("quotes") or []
        if not quotes:
            continue
        quote = quotes[0]
        rows.append(
            {
                "cmc_id": entry.get("id"),
                "symbol": str(entry.get("symbol", "")).upper(),
                "name": entry.get("name", ""),
                "cmc_rank": entry.get("cmcRank"),
                "market_cap_usd": float(quote.get("marketCap") or 0.0),
                "volume24h_usd": float(quote.get("volume24h") or 0.0),
                "circulating_supply": float(entry.get("circulatingSupply") or 0.0),
            }
        )
    return rows


def _dates_in_range(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def collect_universe(
    out_dir: str | Path,
    *,
    start_date: date,
    end_date: date,
    fetcher: Callable[[str], bytes] | None = None,
    clock: Callable[[], float] | None = None,
    sleep_seconds: float = 0.0,
    timeout_seconds: float = 15.0,
    max_days_per_run: int | None = None,
) -> UniverseCollectionResult:
    """Collect daily point-in-time snapshots over ``[start_date, end_date]``.

    Resumable and idempotent: dates already journaled as ``day`` records are
    skipped; dates journaled only as ``gap`` records are retried. An injected
    ``clock`` (tests) marks the journal ``test_only`` permanently.
    """
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    days_dir = out / "days"
    days_dir.mkdir(exist_ok=True)
    journal_path = out / JOURNAL_FILENAME
    clock_source = CLOCK_SYSTEM if clock is None else CLOCK_INJECTED
    active_clock = clock if clock is not None else time.time
    active_fetch = (
        fetcher
        if fetcher is not None
        else (lambda url: fetch_public_bytes(url, timeout_seconds=timeout_seconds))
    )
    result = UniverseCollectionResult(
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

    lease = _Lease(out / LEASE_FILENAME)
    lease.acquire()
    try:
        if records:
            header = records[0]
            if header.get("policy_sha256") != UNIVERSE_POLICY_SHA256:
                result.status = "NOT_RUN_JOURNAL_INVALID"
                result.error = (
                    "journal was started under policy "
                    f"{header.get('policy_sha256')!r}; current policy is "
                    f"{UNIVERSE_POLICY_SHA256!r}. A changed policy is a new "
                    "dataset - collect into a fresh directory."
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
                    "policy_sha256": UNIVERSE_POLICY_SHA256,
                    "policy": UNIVERSE_POLICY,
                    "wall_clock_utc": _utc_stamp(active_clock),
                    "clock_source": clock_source,
                },
            )

        done_dates = {r["date"] for r in records if r.get("type") == "day"}
        requested = _dates_in_range(start_date, end_date)
        result.days_requested = len(requested)
        result.days_already_done = sum(1 for d in requested if d.isoformat() in done_dates)

        consecutive_failures = 0
        collected = 0
        for day in requested:
            day_iso = day.isoformat()
            if day_iso in done_dates:
                continue
            if max_days_per_run is not None and collected >= max_days_per_run:
                result.status = "PARTIAL"
                break
            day_rows: list[dict[str, Any]] = []
            raw_shas: list[str] = []
            failure: str | None = None
            for start in UNIVERSE_POLICY["page_starts"]:
                url = SNAPSHOT_URL.format(
                    endpoint=UNIVERSE_POLICY["endpoint"],
                    date=day_iso,
                    limit=UNIVERSE_POLICY["page_limit"],
                    start=start,
                    convert=UNIVERSE_POLICY["convert_id"],
                )
                try:
                    raw = active_fetch(url)
                except Exception as exc:  # noqa: BLE001 - verbatim error IS the evidence
                    failure = f"NOT_RUN_NETWORK_BLOCKED: {type(exc).__name__}: {exc}"
                    break
                try:
                    page_rows = parse_snapshot_page(raw)
                except (ValueError, KeyError) as exc:
                    if start > 1:
                        break  # short tail past the last page is not an error
                    failure = f"NOT_RUN_PARSE_REJECTED: {exc}"
                    break
                if not page_rows and start > 1:
                    break
                sha = sha256_of_bytes(raw)
                raw_dir = out / "raw"
                raw_dir.mkdir(exist_ok=True)
                raw_file = raw_dir / f"{sha}.json"
                if not raw_file.exists():
                    raw_file.write_bytes(raw)
                append_receipt(
                    out / "receipts.jsonl",
                    IngestionReceipt(
                        provider_or_venue="coinmarketcap",
                        endpoint=UNIVERSE_POLICY["endpoint"],
                        request_parameters={"date": day_iso, "start": start},
                        http_status=200,
                        captured_at_utc=_utc_stamp(active_clock),
                        adapter_name="data.universe.cmc_snapshots",
                        adapter_version=str(SCHEMA_VERSION),
                        raw_path=receipt_relative_path(raw_file, out / "receipts.jsonl"),
                        raw_sha256=sha,
                        normalized_rows_sha256=normalized_rows_sha256(page_rows),
                        source_kind="fixture" if fetcher is not None else "live",
                    ),
                )
                raw_shas.append(sha)
                day_rows.extend(page_rows)
                if len(page_rows) < UNIVERSE_POLICY["page_limit"]:
                    break  # short page: no further pages exist
            if failure is not None:
                _append_record(
                    journal_path,
                    records,
                    {
                        "type": "gap",
                        "date": day_iso,
                        "error": failure,
                        "wall_clock_utc": _utc_stamp(active_clock),
                        "clock_source": clock_source,
                    },
                )
                result.gap_dates.append(day_iso)
                consecutive_failures += 1
                if consecutive_failures >= CONSECUTIVE_FAILURE_ABORT:
                    result.status = "NOT_RUN_NETWORK_BLOCKED"
                    result.error = (
                        f"{consecutive_failures} consecutive failures, last: {failure}"
                    )
                    break
                continue
            consecutive_failures = 0
            if not day_rows:
                _append_record(
                    journal_path,
                    records,
                    {
                        "type": "gap",
                        "date": day_iso,
                        "error": "NOT_RUN_PARSE_REJECTED: zero rows for the day",
                        "wall_clock_utc": _utc_stamp(active_clock),
                        "clock_source": clock_source,
                    },
                )
                result.gap_dates.append(day_iso)
                continue
            day_file = days_dir / f"{day_iso}.jsonl"
            with day_file.open("w", encoding="utf-8") as handle:
                for row in day_rows:
                    handle.write(canonical_dumps(row) + "\n")
            _append_record(
                journal_path,
                records,
                {
                    "type": "day",
                    "date": day_iso,
                    "row_count": len(day_rows),
                    "raw_sha256s": raw_shas,
                    "day_file_sha256": sha256_of_bytes(day_file.read_bytes()),
                    "wall_clock_utc": _utc_stamp(active_clock),
                    "clock_source": clock_source,
                },
            )
            collected += 1
            if sleep_seconds:
                time.sleep(sleep_seconds)
        result.days_collected = collected
        if result.status == "OK" and result.gap_dates:
            result.status = "PARTIAL"
        return result
    finally:
        lease.release()


__all__ = [
    "CLOCK_INJECTED",
    "CLOCK_SYSTEM",
    "UNIVERSE_POLICY",
    "UNIVERSE_POLICY_SHA256",
    "UniverseCollectionResult",
    "UniverseCollectorError",
    "collect_universe",
    "parse_snapshot_page",
    "read_journal",
    "verify_journal_chain",
]
