"""Live spread/slippage measurement across market-cap tiers (Bybit spot).

Follows the `carry/panel_backfill.py` conventions: every raw page is archived
content-addressed with an ingestion receipt; a blocked network records
``NOT_RUN_NETWORK_BLOCKED`` with the verbatim error; a malformed response
records ``NOT_RUN_PARSE_REJECTED``. Nothing is fabricated: a symbol whose
book cannot fill a notional contributes ``None`` ("not executable"), and a
tier with no measurable symbols reports zero samples, not invented bps.

The universe comes from a point-in-time CMC snapshot (see
``docs/CRYPTO_LOWCAP_DATA_SOURCES.md``); tier membership is by market cap.
Stablecoins are excluded — their pegged spreads would flatter every tier's
statistics (declared filter, listed in the manifest).
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.carry.backfill import fetch_public_bytes
from quant_trade.costs.crypto_lowcap import CALIBRATION_NOTIONALS, TIERS, tier_for_market_cap
from quant_trade.costs.orderbook import (
    half_spread_bps,
    parse_bybit_orderbook,
    round_trip_exec_cost_bps,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
    receipt_relative_path,
)

CMC_SNAPSHOT_URL = (
    "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical"
    "?date={date}&limit=5000&start={start}&convertId=2781"
)
BYBIT_SPOT_INSTRUMENTS_URL = (
    "https://api.bybit.com/v5/market/instruments-info?category=spot&limit=1000"
)
BYBIT_ORDERBOOK_URL = (
    "https://api.bybit.com/v5/market/orderbook?category=spot&symbol={symbol}&limit=200"
)

#: Pegged assets whose spreads say nothing about low-cap tradability.
STABLECOIN_SYMBOLS = frozenset(
    {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USDD", "PYUSD", "USD1", "BUSD", "GUSD"}
)

DEFAULT_SYMBOLS_PER_TIER = 12
_ADAPTER = "costs.measure.bybit_orderbooks"
_ADAPTER_VERSION = "1"


@dataclass
class SymbolMeasurement:
    symbol: str
    tier: str
    market_cap_usd: float
    half_spread_bps: float
    exec_cost_bps_by_notional: dict[float, float | None]
    raw_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "tier": self.tier,
            "market_cap_usd": self.market_cap_usd,
            "half_spread_bps": self.half_spread_bps,
            "exec_cost_bps_by_notional": {
                str(k): v for k, v in self.exec_cost_bps_by_notional.items()
            },
            "raw_sha256": self.raw_sha256,
        }


@dataclass
class TierAggregate:
    tier: str
    sample_count: int
    half_spread_bps_p50: float | None
    half_spread_bps_p75: float | None
    exec_cost_bps_by_notional_p50: dict[float, float | None]
    exec_cost_bps_by_notional_p75: dict[float, float | None]
    executable_fraction_by_notional: dict[float, float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "sample_count": self.sample_count,
            "half_spread_bps_p50": self.half_spread_bps_p50,
            "half_spread_bps_p75": self.half_spread_bps_p75,
            "exec_cost_bps_by_notional_p50": {
                str(k): v for k, v in self.exec_cost_bps_by_notional_p50.items()
            },
            "exec_cost_bps_by_notional_p75": {
                str(k): v for k, v in self.exec_cost_bps_by_notional_p75.items()
            },
            "executable_fraction_by_notional": {
                str(k): v for k, v in self.executable_fraction_by_notional.items()
            },
        }


@dataclass
class CostMeasurementResult:
    status: str  # "OK" | "NOT_RUN_NETWORK_BLOCKED" | "NOT_RUN_PARSE_REJECTED"
    snapshot_date: str
    out_dir: str
    error: str = ""
    symbols_measured: int = 0
    symbols_skipped: list[str] = field(default_factory=list)
    tiers: dict[str, TierAggregate] = field(default_factory=dict)
    measurements: list[SymbolMeasurement] = field(default_factory=list)
    manifest_sha256: str = ""
    manifest_path: str = ""
    captured_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "snapshot_date": self.snapshot_date,
            "out_dir": self.out_dir,
            "error": self.error,
            "symbols_measured": self.symbols_measured,
            "symbols_skipped": list(self.symbols_skipped),
            "tiers": {name: agg.to_dict() for name, agg in self.tiers.items()},
            "measurements": [m.to_dict() for m in self.measurements],
            "manifest_sha256": self.manifest_sha256,
            "manifest_path": self.manifest_path,
            "captured_at_utc": self.captured_at_utc,
        }


def _quantiles(values: list[float]) -> tuple[float | None, float | None]:
    """(p50, p75) with small-sample honesty: one value is its own quantiles."""
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    p50 = statistics.median(values)
    p75 = statistics.quantiles(values, n=4, method="inclusive")[2]
    return p50, p75


def _archive(
    out_dir: Path,
    *,
    endpoint: str,
    params: dict[str, Any],
    raw: bytes,
    rows: list[dict[str, Any]],
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
            provider_or_venue="bybit" if "bybit" in endpoint else "coinmarketcap",
            endpoint=endpoint.split("?")[0],
            request_parameters=params,
            http_status=200,
            captured_at_utc=captured_at_utc,
            adapter_name=_ADAPTER,
            adapter_version=_ADAPTER_VERSION,
            raw_path=receipt_relative_path(raw_file, receipts_path),
            raw_sha256=sha,
            normalized_rows_sha256=normalized_rows_sha256(rows),
            source_kind="live",
        ),
    )
    return sha


def parse_snapshot_rows(raw: bytes) -> list[dict[str, Any]]:
    """Extract (symbol, market cap, volume) rows from a CMC snapshot page."""
    payload = json.loads(raw)
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("CMC snapshot: 'data' is not a list")
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
            }
        )
    if not rows:
        raise ValueError("CMC snapshot: zero parseable rows")
    return rows


def parse_bybit_spot_bases(raw: bytes) -> set[str]:
    """Base symbols of Bybit spot USDT pairs currently trading."""
    payload = json.loads(raw)
    if payload.get("retCode") != 0:
        raise ValueError(f"bybit retCode {payload.get('retCode')}: {payload.get('retMsg')}")
    instruments = (payload.get("result") or {}).get("list") or []
    bases = {
        str(item.get("baseCoin", "")).upper()
        for item in instruments
        if item.get("quoteCoin") == "USDT" and item.get("status") == "Trading"
    }
    if not bases:
        raise ValueError("bybit instruments: zero USDT spot pairs parsed")
    return bases


def _select_tier_candidates(
    snapshot_rows: Iterable[dict[str, Any]],
    bybit_bases: set[str],
    symbols_per_tier: int,
) -> dict[str, list[dict[str, Any]]]:
    """Top-by-mcap Bybit-listed, non-stablecoin candidates per tier."""
    per_tier: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in TIERS}
    ordered = sorted(
        snapshot_rows, key=lambda row: row.get("market_cap_usd", 0.0), reverse=True
    )
    seen: set[str] = set()
    for row in ordered:
        symbol = row["symbol"]
        if symbol in seen:
            continue  # first (highest-mcap) occurrence wins; duplicates are forks
        seen.add(symbol)
        if symbol in STABLECOIN_SYMBOLS or symbol not in bybit_bases:
            continue
        tier = tier_for_market_cap(row.get("market_cap_usd", 0.0))
        if tier is None:
            continue
        bucket = per_tier[tier]
        if len(bucket) < symbols_per_tier:
            bucket.append(row)
    return per_tier


def run_cost_measurement(
    out_dir: str | Path,
    *,
    snapshot_date: str,
    fetcher: Callable[[str], bytes] | None = None,
    symbols_per_tier: int = DEFAULT_SYMBOLS_PER_TIER,
    notionals: tuple[float, ...] = CALIBRATION_NOTIONALS,
    timeout_seconds: float = 10.0,
    sleep_seconds: float = 0.0,
) -> CostMeasurementResult:
    """Measure spreads and walk-the-book costs per tier from live Bybit books.

    ``fetcher`` is injectable for tests (fixtures never become real: tests
    exercise the arithmetic; only a live run writes a manifest worth citing).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    captured = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = CostMeasurementResult(
        status="OK",
        snapshot_date=snapshot_date,
        out_dir=str(out),
        captured_at_utc=captured,
    )
    active_fetch = (
        fetcher
        if fetcher is not None
        else (lambda url: fetch_public_bytes(url, timeout_seconds=timeout_seconds))
    )

    def not_run(status: str, error: str) -> CostMeasurementResult:
        result.status = status
        result.error = error
        attempts = out / "measurement_attempts.jsonl"
        with attempts.open("a", encoding="utf-8") as handle:
            handle.write(canonical_dumps({"status": status, "error": error}) + "\n")
        return result

    # 1) Point-in-time universe snapshot (two pages cover <10k coins).
    snapshot_rows: list[dict[str, Any]] = []
    for start in (1, 5001):
        url = CMC_SNAPSHOT_URL.format(date=snapshot_date, start=start)
        try:
            raw = active_fetch(url)
        except Exception as exc:  # noqa: BLE001 - verbatim error IS the evidence
            return not_run("NOT_RUN_NETWORK_BLOCKED", f"{type(exc).__name__}: {exc}")
        try:
            page_rows = parse_snapshot_rows(raw)
        except (ValueError, KeyError) as exc:
            if start > 1:  # past the last page; a short tail is not an error
                break
            return not_run("NOT_RUN_PARSE_REJECTED", f"snapshot: {exc}")
        _archive(
            out,
            endpoint=url,
            params={"date": snapshot_date, "start": start, "limit": 5000},
            raw=raw,
            rows=page_rows,
            captured_at_utc=captured,
        )
        snapshot_rows.extend(page_rows)

    # 2) Which of those trade on Bybit spot right now.
    try:
        raw = active_fetch(BYBIT_SPOT_INSTRUMENTS_URL)
        bybit_bases = parse_bybit_spot_bases(raw)
    except ValueError as exc:
        return not_run("NOT_RUN_PARSE_REJECTED", f"instruments: {exc}")
    except Exception as exc:  # noqa: BLE001
        return not_run("NOT_RUN_NETWORK_BLOCKED", f"{type(exc).__name__}: {exc}")
    _archive(
        out,
        endpoint=BYBIT_SPOT_INSTRUMENTS_URL,
        params={"category": "spot"},
        raw=raw,
        rows=[{"base": base} for base in sorted(bybit_bases)],
        captured_at_utc=captured,
    )

    # 3) Order books per tier candidate.
    candidates = _select_tier_candidates(snapshot_rows, bybit_bases, symbols_per_tier)
    for tier_name, rows in candidates.items():
        for row in rows:
            pair = f"{row['symbol']}USDT"
            url = BYBIT_ORDERBOOK_URL.format(symbol=pair)
            try:
                raw = active_fetch(url)
            except Exception as exc:  # noqa: BLE001
                return not_run("NOT_RUN_NETWORK_BLOCKED", f"{type(exc).__name__}: {exc}")
            try:
                book = parse_bybit_orderbook(raw)
            except ValueError as exc:
                result.symbols_skipped.append(f"{pair}: {exc}")
                continue
            sha = _archive(
                out,
                endpoint=url,
                params={"symbol": pair, "limit": 200},
                raw=raw,
                rows=[{"symbol": pair, "ts": book.timestamp_ms}],
                captured_at_utc=captured,
            )
            result.measurements.append(
                SymbolMeasurement(
                    symbol=pair,
                    tier=tier_name,
                    market_cap_usd=row["market_cap_usd"],
                    half_spread_bps=half_spread_bps(book),
                    exec_cost_bps_by_notional={
                        notional: round_trip_exec_cost_bps(book, notional)
                        for notional in notionals
                    },
                    raw_sha256=sha,
                )
            )
            if sleep_seconds:
                time.sleep(sleep_seconds)

    # 4) Aggregate per tier. None (not executable) is counted, never averaged in.
    for tier_name, _, _ in TIERS:
        tier_measurements = [m for m in result.measurements if m.tier == tier_name]
        spreads = [m.half_spread_bps for m in tier_measurements]
        spread_p50, spread_p75 = _quantiles(spreads)
        p50_by_notional: dict[float, float | None] = {}
        p75_by_notional: dict[float, float | None] = {}
        executable: dict[float, float | None] = {}
        for notional in notionals:
            costs = [
                m.exec_cost_bps_by_notional[notional]
                for m in tier_measurements
                if m.exec_cost_bps_by_notional[notional] is not None
            ]
            p50, p75 = _quantiles([c for c in costs if c is not None])
            p50_by_notional[notional] = p50
            p75_by_notional[notional] = p75
            executable[notional] = (
                len(costs) / len(tier_measurements) if tier_measurements else None
            )
        result.tiers[tier_name] = TierAggregate(
            tier=tier_name,
            sample_count=len(tier_measurements),
            half_spread_bps_p50=spread_p50,
            half_spread_bps_p75=spread_p75,
            exec_cost_bps_by_notional_p50=p50_by_notional,
            exec_cost_bps_by_notional_p75=p75_by_notional,
            executable_fraction_by_notional=executable,
        )
    result.symbols_measured = len(result.measurements)

    # 5) Manifest: canonical bytes of everything above, self-hashed.
    manifest_body = canonical_dumps(result.to_dict()).encode("utf-8")
    result.manifest_sha256 = sha256_of_bytes(manifest_body)
    manifest_path = out / "measurement.json"
    manifest_path.write_bytes(manifest_body)
    result.manifest_path = str(manifest_path)
    return result


__all__ = [
    "CostMeasurementResult",
    "SymbolMeasurement",
    "TierAggregate",
    "parse_bybit_spot_bases",
    "parse_snapshot_rows",
    "run_cost_measurement",
]
