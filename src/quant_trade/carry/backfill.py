"""Historical funding backfill from PUBLIC venue endpoints (read-only).

Bybit and OKX publish settled funding history on unauthenticated endpoints.
This module fetches that history, preserves the raw response bytes
content-addressed, and appends ``funding_settlement`` events to the JSONL
store — the ONLY event type from which realized funding P&L may accrue.

Discipline:
- fetch (network) and parse (pure) are separate functions, so the full parse
  path is testable offline against canned raw bytes;
- the venue's own symbol in the response must match the requested instrument
  — a mismatch fails closed, records are never relabelled;
- every attempt (success or failure) is appended to a ``backfill_attempts``
  log with the exact URL and the verbatim error, so a blocked network yields
  a verifiable NOT_RUN instead of silence;
- no API keys are read or required; nothing here submits orders.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.carry.store import (
    AppendResult,
    FundingObservation,
    append_observations,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes

#: Official public endpoints (documented, unauthenticated, read-only).
BYBIT_FUNDING_HISTORY_URL = "https://api.bybit.com/v5/market/funding/history"
OKX_FUNDING_HISTORY_URL = "https://www.okx.com/api/v5/public/funding-rate-history"

SUPPORTED_VENUES = ("bybit", "okx")
USER_AGENT = "quant-trade-carry-backfill/1.0 (read-only research)"


def bybit_perp_instrument(symbol: str) -> str:
    return f"{symbol.upper()}USDT"


def okx_perp_instrument(symbol: str) -> str:
    return f"{symbol.upper()}-USDT-SWAP"


def build_backfill_url(venue: str, symbol: str, limit: int) -> str:
    if venue == "bybit":
        return (
            f"{BYBIT_FUNDING_HISTORY_URL}?category=linear"
            f"&symbol={bybit_perp_instrument(symbol)}&limit={min(limit, 200)}"
        )
    if venue == "okx":
        return (
            f"{OKX_FUNDING_HISTORY_URL}?instId={okx_perp_instrument(symbol)}"
            f"&limit={min(limit, 100)}"
        )
    raise ValueError(f"unsupported venue {venue!r}; supported: {SUPPORTED_VENUES}")


def _iso_from_ms(ms: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000.0))


def _derive_interval_hours(times_ms: list[float]) -> float:
    """Median spacing between settlements, in hours; 8.0 when underdetermined."""
    if len(times_ms) < 2:
        return 8.0
    ordered = sorted(times_ms)
    diffs = sorted(
        abs(b - a) / 3_600_000.0
        for a, b in zip(ordered[:-1], ordered[1:], strict=True)
    )
    median = diffs[len(diffs) // 2]
    return median if median > 0 else 8.0


def parse_bybit_funding_history(
    raw: bytes, *, symbol: str, captured_at_utc: str, source_name: str = "bybit:v5"
) -> list[FundingObservation]:
    """Pure parser for Bybit v5 ``/market/funding/history`` raw bytes."""
    payload = json.loads(raw.decode("utf-8"))
    if int(payload.get("retCode", -1)) != 0:
        raise ValueError(
            f"bybit error response retCode={payload.get('retCode')} "
            f"retMsg={payload.get('retMsg')!r}"
        )
    expected = bybit_perp_instrument(symbol)
    raw_sha = sha256_of_bytes(raw)
    rows = payload.get("result", {}).get("list", []) or []
    times_ms = [float(r["fundingRateTimestamp"]) for r in rows]
    interval = _derive_interval_hours(times_ms)
    out: list[FundingObservation] = []
    for row in rows:
        got = str(row.get("symbol", ""))
        if got != expected:
            raise ValueError(
                f"instrument identity mismatch: requested {expected}, response "
                f"carries {got!r} — refusing to relabel records"
            )
        out.append(
            FundingObservation(
                venue="bybit",
                symbol=symbol.upper(),
                captured_at_utc=captured_at_utc,
                exchange_timestamp_utc=_iso_from_ms(float(row["fundingRateTimestamp"])),
                realized_funding_rate=float(row["fundingRate"]),
                funding_interval_hours=interval,
                source_event="funding_settlement",
                source_name=source_name,
                raw_sha256=raw_sha,
                perpetual_instrument_id=f"bybit:{expected}",
                contract_type="linear_perpetual",
                quote_asset="USDT",
                settlement_asset="USDT",
            )
        )
    return out


def parse_okx_funding_history(
    raw: bytes, *, symbol: str, captured_at_utc: str, source_name: str = "okx:v5"
) -> list[FundingObservation]:
    """Pure parser for OKX v5 ``/public/funding-rate-history`` raw bytes.

    OKX reports both ``fundingRate`` (announced) and ``realizedRate``
    (settled); the settled value wins whenever it is present.
    """
    payload = json.loads(raw.decode("utf-8"))
    if str(payload.get("code", "")) != "0":
        raise ValueError(
            f"okx error response code={payload.get('code')!r} "
            f"msg={payload.get('msg')!r}"
        )
    expected = okx_perp_instrument(symbol)
    raw_sha = sha256_of_bytes(raw)
    rows = payload.get("data", []) or []
    times_ms = [float(r["fundingTime"]) for r in rows]
    interval = _derive_interval_hours(times_ms)
    out: list[FundingObservation] = []
    for row in rows:
        got = str(row.get("instId", ""))
        if got != expected:
            raise ValueError(
                f"instrument identity mismatch: requested {expected}, response "
                f"carries {got!r} — refusing to relabel records"
            )
        realized = str(row.get("realizedRate", "") or "").strip()
        rate = float(realized) if realized else float(row["fundingRate"])
        out.append(
            FundingObservation(
                venue="okx",
                symbol=symbol.upper(),
                captured_at_utc=captured_at_utc,
                exchange_timestamp_utc=_iso_from_ms(float(row["fundingTime"])),
                realized_funding_rate=rate,
                funding_interval_hours=interval,
                source_event="funding_settlement",
                source_name=source_name,
                raw_sha256=raw_sha,
                perpetual_instrument_id=f"okx:{expected}",
                contract_type="linear_perpetual",
                quote_asset="USDT",
                settlement_asset="USDT",
            )
        )
    return out


_PARSERS: dict[str, Callable[..., list[FundingObservation]]] = {
    "bybit": parse_bybit_funding_history,
    "okx": parse_okx_funding_history,
}


def fetch_public_bytes(url: str, *, timeout_seconds: float = 10.0) -> bytes:
    """GET a public endpoint. No keys, no headers beyond a research UA."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return bytes(response.read())


@dataclass
class BackfillResult:
    status: str  # "OK" | "NOT_RUN_NETWORK_BLOCKED" | "NOT_RUN_PARSE_REJECTED"
    venue: str
    symbol: str
    url: str
    events_parsed: int = 0
    appended: int = 0
    deduplicated: int = 0
    raw_sha256: str = ""
    raw_path: str = ""
    store_path: str = ""
    error: str = ""
    attempts_log: str = ""
    provenance: str = "live"  # "live" | "fixture"
    captured_at_utc: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _log_attempt(log_path: Path, result: BackfillResult) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(result.to_dict()) + "\n")


def run_backfill(
    venue: str,
    symbol: str,
    output_path: str | Path,
    *,
    limit: int = 200,
    raw_dir: str | Path | None = None,
    fixture_path: str | Path | None = None,
    timeout_seconds: float = 10.0,
    fetcher: Callable[[str], bytes] | None = None,
) -> BackfillResult:
    """One backfill pass; append settled funding events to the store.

    ``fixture_path`` replays canned raw bytes offline (provenance is marked
    ``fixture`` and the source name prefixed, so downstream tooling can never
    mistake it for live capture). A blocked or failing network yields a
    ``NOT_RUN_NETWORK_BLOCKED`` result whose verbatim error is appended to the
    attempts log next to the store — verifiable, never silent.
    """
    if venue not in SUPPORTED_VENUES:
        raise ValueError(f"unsupported venue {venue!r}; supported: {SUPPORTED_VENUES}")
    store = Path(output_path)
    attempts = store.parent / "backfill_attempts.jsonl"
    url = build_backfill_url(venue, symbol, limit)
    captured = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    provenance = "fixture" if fixture_path is not None else "live"
    source_name = (
        f"fixture:{Path(fixture_path).name}" if fixture_path is not None else f"{venue}:public"
    )

    result = BackfillResult(
        status="OK",
        venue=venue,
        symbol=symbol.upper(),
        url=url,
        store_path=str(store),
        attempts_log=str(attempts),
        provenance=provenance,
        captured_at_utc=captured,
    )

    if fixture_path is not None:
        raw = Path(fixture_path).read_bytes()
    else:
        active_fetcher = fetcher if fetcher is not None else (
            lambda u: fetch_public_bytes(u, timeout_seconds=timeout_seconds)
        )
        try:
            raw = active_fetcher(url)
        except Exception as exc:  # noqa: BLE001 - the verbatim error IS the evidence
            result.status = "NOT_RUN_NETWORK_BLOCKED"
            result.error = f"{type(exc).__name__}: {exc}"
            _log_attempt(attempts, result)
            return result

    try:
        observations = _PARSERS[venue](
            raw, symbol=symbol, captured_at_utc=captured, source_name=source_name
        )
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        result.status = "NOT_RUN_PARSE_REJECTED"
        result.error = f"{type(exc).__name__}: {exc}"
        _log_attempt(attempts, result)
        return result

    result.raw_sha256 = sha256_of_bytes(raw)
    raw_root = Path(raw_dir) if raw_dir is not None else store.parent / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_file = raw_root / f"{result.raw_sha256}.json"
    if not raw_file.exists():
        raw_file.write_bytes(raw)
    result.raw_path = str(raw_file)

    appended: AppendResult = append_observations(store, observations)
    result.events_parsed = len(observations)
    result.appended = appended.appended
    result.deduplicated = appended.deduplicated
    _log_attempt(attempts, result)
    return result
