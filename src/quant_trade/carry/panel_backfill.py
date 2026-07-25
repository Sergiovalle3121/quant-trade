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
) -> str:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sha = sha256_of_bytes(raw)
    raw_file = raw_dir / f"{sha}.json"
    if not raw_file.exists():
        raw_file.write_bytes(raw)
    append_receipt(
        out_dir / "receipts.jsonl",
        IngestionReceipt(
            provider_or_venue=venue,
            endpoint=endpoint,
            request_parameters=params,
            http_status=200,
            captured_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            adapter_name="carry.panel_backfill.bybit",
            adapter_version="1",
            raw_path=str(raw_file),
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
        status="OK", venue=venue, symbol=symbol.upper(), panel_dir=str(out),
        provenance=source_kind,
    )
    active_fetch = fetcher if fetcher is not None else (
        lambda u: fetch_public_bytes(u, timeout_seconds=timeout_seconds)
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
                    return log_not_run(
                        "NOT_RUN_NETWORK_BLOCKED", f"{type(exc).__name__}: {exc}"
                    )
            try:
                page_rows = parse_bybit_kline_page(raw, symbol=symbol, kind=kind)
            except (ValueError, KeyError) as exc:
                return log_not_run(
                    "NOT_RUN_PARSE_REJECTED", f"{kind}: {type(exc).__name__}: {exc}"
                )
            sha = _archive_page(
                out,
                venue=venue,
                endpoint=url.split("?")[0],
                params={"kind": kind, "end": end_cursor, "interval": interval},
                raw=raw,
                rows=page_rows,
                source_kind=source_kind,
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

    # funding history (settlements) — same receipt discipline
    if fixture_pages is not None:
        funding_raw = Path(fixture_pages["funding"]).read_bytes()
    else:
        try:
            funding_raw = active_fetch(build_backfill_url(venue, symbol, 200))
        except Exception as exc:  # noqa: BLE001
            return log_not_run("NOT_RUN_NETWORK_BLOCKED", f"{type(exc).__name__}: {exc}")
    try:
        funding_events = parse_bybit_funding_history(
            funding_raw, symbol=symbol, captured_at_utc=captured
        )
    except (ValueError, KeyError) as exc:
        return log_not_run("NOT_RUN_PARSE_REJECTED", f"funding: {type(exc).__name__}: {exc}")
    _archive_page(
        out,
        venue=venue,
        endpoint=build_backfill_url(venue, symbol, 200).split("?")[0],
        params={"kind": "funding"},
        raw=funding_raw,
        rows=[e.to_dict() for e in funding_events],
        source_kind=source_kind,
    )
    import calendar

    settlements = [
        {
            "settled_at_ms": int(
                calendar.timegm(
                    time.strptime(e.exchange_timestamp_utc, "%Y-%m-%dT%H:%M:%SZ")
                )
            )
            * 1000,
            "rate": e.realized_funding_rate,
        }
        for e in funding_events
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
    )
    write_panel(out, panel_rows, audit)
    result.panel_rows = len(panel_rows)
    result.audit = audit.to_dict()
    return result


__all__ = ["PanelBackfillResult", "run_panel_backfill", "PanelAudit"]
