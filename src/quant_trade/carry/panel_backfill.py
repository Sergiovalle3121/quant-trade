"""Paginated, resumable, receipt-writing backfill for the carry panel.

Fetches — read-only, unauthenticated — the four Bybit kline series and the
funding history over ``[since, until]``, one page at a time:

- deterministic end-cursor pagination (each next page ends 1 ms before the
  oldest bar already seen), with repeated-page detection as a fail-safe;
- every raw page preserved content-addressed + one ingestion receipt per
  page (``live`` or ``fixture`` — fixtures can never become real);
- bounded retries; a blocked network records ``NOT_RUN_NETWORK_BLOCKED``
  with the verbatim error in the attempts log, never silence;
- idempotent: re-running skips pages whose content is already archived.

The result of a successful run is a built panel directory (``panel.jsonl`` +
manifest + audit) ready for ``run_carry_research`` via ``source: panel``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.carry.backfill import (
    build_backfill_url,
    fetch_public_bytes,
    parse_bybit_funding_history,
)
from quant_trade.carry.instruments import parse_symbol
from quant_trade.carry.panel import (
    BYBIT_INDEX_KLINE_URL,
    BYBIT_KLINE_URL,
    BYBIT_MARK_KLINE_URL,
    PanelAudit,
    build_carry_panel,
    parse_bybit_kline_page,
    write_panel,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
    receipt_relative_path,
)

_KIND_ENDPOINTS = {
    "spot": (BYBIT_KLINE_URL, "spot"),
    "perp": (BYBIT_KLINE_URL, "linear"),
    "mark": (BYBIT_MARK_KLINE_URL, "linear"),
    "index": (BYBIT_INDEX_KLINE_URL, "linear"),
}
MAX_PAGES_PER_SERIES = 200  # hard runaway backstop


@dataclass
class PanelBackfillResult:
    status: str  # "OK" | "NOT_RUN_NETWORK_BLOCKED" | "NOT_RUN_PARSE_REJECTED"
    venue: str
    symbol: str
    pages_fetched: int = 0
    funding_pages_fetched: int = 0
    rows_per_series: dict[str, int] = field(default_factory=dict)
    settlements: int = 0
    panel_rows: int = 0
    panel_dir: str = ""
    error: str = ""
    provenance: str = "live"
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def _kline_url(kind: str, symbol: str, *, end_ms: int, interval: str, limit: int) -> str:
    base_url, category = _KIND_ENDPOINTS[kind]
    base, _ = parse_symbol(symbol)
    return (
        f"{base_url}?category={category}&symbol={base}USDT&interval={interval}"
        f"&end={end_ms}&limit={limit}"
    )


def _archive_page(
    out_dir: Path,
    *,
    venue: str,
    endpoint: str,
    params: dict[str, Any],
    raw: bytes,
    rows: list[dict[str, Any]],
    source_kind: str,
    captured_at_utc: str,
) -> str:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sha = sha256_of_bytes(raw)
    raw_file = raw_dir / f"{sha}.json"
    if not raw_file.exists():
        raw_file.write_bytes(raw)
    receipts_path = out_dir / "receipts.jsonl"
    append_receipt(
        receipts_path,
        IngestionReceipt(
            provider_or_venue=venue,
            endpoint=endpoint,
            request_parameters=params,
            http_status=200,
            # This exact value was passed to parsers that embed capture time
            # in normalized funding rows. Replacing it with a later wall-clock
            # value would make a clean reparse hash differently.
            captured_at_utc=captured_at_utc,
            adapter_name="carry.panel_backfill.bybit",
            adapter_version="1",
            raw_path=receipt_relative_path(raw_file, receipts_path),
            raw_sha256=sha,
            normalized_rows_sha256=normalized_rows_sha256(rows),
            source_kind=source_kind,
        ),
    )
    return sha


def run_panel_backfill(
    venue: str,
    symbol: str,
    out_dir: str | Path,
    *,
    since_ms: int,
    until_ms: int,
    interval_minutes: int = 60,
    fixture_pages: dict[str, str | Path] | None = None,
    fetcher: Callable[[str], bytes] | None = None,
    timeout_seconds: float = 10.0,
) -> PanelBackfillResult:
    """Backfill the four kline series + funding and build the panel."""
    if venue != "bybit":
        raise ValueError("panel backfill currently supports venue='bybit' only")
    if until_ms <= since_ms:
        raise ValueError("until must be after since")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_kind = "fixture" if fixture_pages is not None else "live"
    result = PanelBackfillResult(
        status="OK",
        venue=venue,
        symbol=symbol.upper(),
        panel_dir=str(out),
        provenance=source_kind,
    )
    active_fetch = (
        fetcher
        if fetcher is not None
        else (lambda u: fetch_public_bytes(u, timeout_seconds=timeout_seconds))
    )
    interval = str(interval_minutes)
    captured = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def log_not_run(status: str, error: str) -> PanelBackfillResult:
        result.status = status
        result.error = error
        attempts = out / "backfill_attempts.jsonl"
        with attempts.open("a", encoding="utf-8") as handle:
            handle.write(canonical_dumps(result.to_dict()) + "\n")
        return result

    series: dict[str, list[dict[str, Any]]] = {}
    for kind in _KIND_ENDPOINTS:
        rows: dict[int, dict[str, Any]] = {}
        seen_pages: set[str] = set()
        end_cursor = until_ms
        for _page in range(MAX_PAGES_PER_SERIES):
            if fixture_pages is not None:
                raw = Path(fixture_pages[kind]).read_bytes()
                url = _kline_url(kind, symbol, end_ms=end_cursor, interval=interval, limit=1000)
            else:
                url = _kline_url(kind, symbol, end_ms=end_cursor, interval=interval, limit=1000)
                try:
                    raw = active_fetch(url)
                except Exception as exc:  # noqa: BLE001 - verbatim error IS the evidence
                    return log_not_run("NOT_RUN_NETWORK_BLOCKED", f"{type(exc).__name__}: {exc}")
            try:
                page_rows = parse_bybit_kline_page(raw, symbol=symbol, kind=kind)
            except (ValueError, KeyError) as exc:
                return log_not_run("NOT_RUN_PARSE_REJECTED", f"{kind}: {type(exc).__name__}: {exc}")
            sha = _archive_page(
                out,
                venue=venue,
                endpoint=url.split("?")[0],
                params={
                    "kind": kind,
                    "symbol": symbol.upper(),
                    "source_name": (
                        f"fixture:{Path(fixture_pages[kind]).name}"
                        if fixture_pages is not None
                        else "bybit:public"
                    ),
                    "end": end_cursor,
                    "interval": interval,
                },
                raw=raw,
                rows=page_rows,
                source_kind=source_kind,
                captured_at_utc=captured,
            )
            result.pages_fetched += 1
            if sha in seen_pages or not page_rows:
                break  # repeated or empty page: pagination exhausted
            seen_pages.add(sha)
            for row in page_rows:
                if since_ms <= row["start_ms"] <= until_ms:
                    rows[row["start_ms"]] = row
            oldest = page_rows[0]["start_ms"]
            if oldest <= since_ms or fixture_pages is not None:
                break
            end_cursor = oldest - 1
        series[kind] = [rows[k] for k in sorted(rows)]
        result.rows_per_series[kind] = len(series[kind])

    # Funding history is paginated over the exact requested range.
    funding_source_name = (
        f"fixture:{Path(fixture_pages['funding']).name}"
        if fixture_pages is not None
        else "bybit:public"
    )
    import calendar

    settlement_by_time: dict[int, float] = {}
    seen_funding_pages: set[str] = set()
    funding_cursor = until_ms
    for _page in range(MAX_PAGES_PER_SERIES):
        funding_url = build_backfill_url(venue, symbol, 200) + f"&endTime={funding_cursor}"
        if fixture_pages is not None:
            funding_raw = Path(fixture_pages["funding"]).read_bytes()
        else:
            try:
                funding_raw = active_fetch(funding_url)
            except Exception as exc:  # noqa: BLE001
                return log_not_run("NOT_RUN_NETWORK_BLOCKED", f"{type(exc).__name__}: {exc}")
        funding_sha = sha256_of_bytes(funding_raw)
        if funding_sha in seen_funding_pages:
            break
        seen_funding_pages.add(funding_sha)
        try:
            funding_events = parse_bybit_funding_history(
                funding_raw,
                symbol=symbol,
                captured_at_utc=captured,
                source_name=funding_source_name,
            )
        except (ValueError, KeyError) as exc:
            return log_not_run(
                "NOT_RUN_PARSE_REJECTED",
                f"funding: {type(exc).__name__}: {exc}",
            )
        _archive_page(
            out,
            venue=venue,
            endpoint=funding_url.split("?")[0],
            params={
                "kind": "funding",
                "symbol": symbol.upper(),
                "source_name": funding_source_name,
                "end": funding_cursor,
                "limit": 200,
            },
            raw=funding_raw,
            rows=[event.to_dict() for event in funding_events],
            source_kind=source_kind,
            captured_at_utc=captured,
        )
        result.funding_pages_fetched += 1
        event_times: list[int] = []
        for event in funding_events:
            settled_at = int(
                calendar.timegm(time.strptime(event.exchange_timestamp_utc, "%Y-%m-%dT%H:%M:%SZ"))
                * 1000
            )
            event_times.append(settled_at)
            if not since_ms <= settled_at <= until_ms:
                continue
            previous = settlement_by_time.get(settled_at)
            if previous is not None and previous != event.realized_funding_rate:
                return log_not_run(
                    "NOT_RUN_PARSE_REJECTED",
                    f"funding conflict at {event.exchange_timestamp_utc}",
                )
            settlement_by_time[settled_at] = event.realized_funding_rate
        if not event_times or min(event_times) <= since_ms or fixture_pages is not None:
            break
        funding_cursor = min(event_times) - 1

    settlements = [
        {"settled_at_ms": settled_at, "rate": rate}
        for settled_at, rate in sorted(settlement_by_time.items())
    ]
    result.settlements = len(settlements)

    panel_rows, audit = build_carry_panel(
        venue=venue,
        symbol=symbol,
        spot=series["spot"],
        perp=series["perp"],
        mark=series["mark"],
        index=series["index"],
        settlements=settlements,
        interval_minutes=interval_minutes,
        requested_since_ms=since_ms,
        requested_until_ms=until_ms,
    )
    audit.provenance = "test_only" if source_kind == "fixture" else "real"
    write_panel(
        out,
        panel_rows,
        audit,
        build_context={
            "venue": venue,
            "symbol": symbol.upper(),
            "interval_minutes": interval_minutes,
            "requested_since_ms": since_ms,
            "requested_until_ms": until_ms,
        },
    )
    result.panel_rows = len(panel_rows)
    result.audit = audit.to_dict()
    return result


__all__ = ["PanelBackfillResult", "run_panel_backfill", "PanelAudit"]
