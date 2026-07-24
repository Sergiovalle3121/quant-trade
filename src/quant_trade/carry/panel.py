"""HistoricalCarryPanel: synchronized, point-in-time market history for carry.

The panel joins — per instrument, per bar — spot OHLCV, perp OHLCV,
mark-price and index-price klines, and settled funding events, all sourced
from raw pages preserved content-addressed with ingestion receipts. It is the
bridge that lets a funding BACKFILL actually power research (V6-F): quotes
come from klines, funding accrues only at exact settlement instants, and the
signal series exposes the most recent SETTLED rate known at each bar — polls
never drive anything here.

Honesty rules:
- rows exist only where every essential series has a bar (gaps are detected
  and reported, never forward-filled);
- the spot close is a labelled PROXY for tradeable bid/ask — the panel
  carries ``spread_source="proxy_ohlcv_close"`` so no one calls it an
  observed spread;
- provenance comes from the receipts of the raw pages, resolved by
  :mod:`quant_trade.evidence.receipts` — fixture-built panels are TEST_ONLY.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.carry.instruments import (
    canonical_instrument_id,
    instrument_metadata,
    parse_symbol,
)
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    sha256_of_bytes,
)

#: Official public kline endpoints (documented, unauthenticated).
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_MARK_KLINE_URL = "https://api.bybit.com/v5/market/mark-price-kline"
BYBIT_INDEX_KLINE_URL = "https://api.bybit.com/v5/market/index-price-kline"

KLINE_KINDS = ("spot", "perp", "mark", "index")


def parse_bybit_kline_page(
    raw: bytes, *, symbol: str, kind: str
) -> list[dict[str, Any]]:
    """Pure parser for one Bybit v5 kline page (any of the four kinds)."""
    if kind not in KLINE_KINDS:
        raise ValueError(f"kind must be one of {KLINE_KINDS}")
    payload = json.loads(raw.decode("utf-8"))
    if int(payload.get("retCode", -1)) != 0:
        raise ValueError(
            f"bybit error response retCode={payload.get('retCode')} "
            f"retMsg={payload.get('retMsg')!r}"
        )
    base, _quote = parse_symbol(symbol)
    expected = f"{base}USDT"
    got = str(payload.get("result", {}).get("symbol", ""))
    if got != expected:
        raise ValueError(
            f"instrument identity mismatch: requested {expected}, page carries "
            f"{got!r} — refusing to relabel klines"
        )
    rows = payload.get("result", {}).get("list", []) or []
    out: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "start_ms": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
        }
        if kind in ("spot", "perp") and len(row) >= 6:
            entry["volume"] = float(row[5])
        for name in ("open", "high", "low", "close"):
            if entry[name] <= 0:
                raise ValueError(f"non-positive {name} in {kind} kline page")
        out.append(entry)
    out.sort(key=lambda r: r["start_ms"])
    return out


@dataclass
class PanelAudit:
    rows: int = 0
    settlements: int = 0
    expected_bars: int = 0
    missing_bars: int = 0
    gap_ranges: list[str] = field(default_factory=list)
    coverage_ratio: float = 0.0
    provenance: str = "unverified_legacy"
    time_range_start: str = ""
    time_range_end: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.problems and self.rows > 0 and self.missing_bars == 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["is_clean"] = self.is_clean
        return d


def _iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000.0))


def build_carry_panel(
    *,
    venue: str,
    symbol: str,
    spot: list[dict[str, Any]],
    perp: list[dict[str, Any]],
    mark: list[dict[str, Any]],
    index: list[dict[str, Any]],
    settlements: list[dict[str, Any]],
    interval_minutes: int = 60,
) -> tuple[list[dict[str, Any]], PanelAudit]:
    """Join the four kline series + settlements into point-in-time panel rows.

    A row exists ONLY at bars where all four series have data — nothing is
    forward-filled. Settled funding is attached to its exact settlement
    instant (`funding_settlements` per row lists events in ``(prev, t]``).
    """
    meta = instrument_metadata(venue, symbol)
    by_kind = {"spot": spot, "perp": perp, "mark": mark, "index": index}
    indexed = {
        kind: {row["start_ms"]: row for row in rows} for kind, rows in by_kind.items()
    }
    all_ts = sorted(set.intersection(*(set(m) for m in indexed.values())))
    union_ts = sorted(set.union(*(set(m) for m in indexed.values())))
    audit = PanelAudit()
    if not all_ts:
        audit.problems.append("no bar has all four series present")
        return [], audit

    step_ms = interval_minutes * 60_000
    expected = range(all_ts[0], all_ts[-1] + step_ms, step_ms)
    expected_set = set(expected)
    missing = sorted(expected_set - set(all_ts))
    audit.expected_bars = len(expected_set)
    audit.missing_bars = len(missing)
    audit.gap_ranges = [_iso(ms) for ms in missing[:20]]
    audit.coverage_ratio = (
        1.0 - len(missing) / len(expected_set) if expected_set else 0.0
    )
    if set(union_ts) - expected_set:
        audit.problems.append("bars exist outside the expected interval grid")

    settle_sorted = sorted(
        (
            {
                "settled_at_ms": int(s["settled_at_ms"]),
                "rate": float(s["rate"]),
            }
            for s in settlements
        ),
        key=lambda s: s["settled_at_ms"],
    )
    rows: list[dict[str, Any]] = []
    prev_ts: int | None = None
    for ts in all_ts:
        in_bar = [
            s
            for s in settle_sorted
            if (prev_ts is None or s["settled_at_ms"] > prev_ts)
            and s["settled_at_ms"] <= ts
        ]
        last_known = [s for s in settle_sorted if s["settled_at_ms"] <= ts]
        rows.append(
            {
                "timestamp_utc": _iso(ts),
                "start_ms": ts,
                "venue": venue,
                "symbol": parse_symbol(symbol)[0],
                "perpetual_instrument_id": canonical_instrument_id(venue, symbol),
                "spot_open": indexed["spot"][ts]["open"],
                "spot_high": indexed["spot"][ts]["high"],
                "spot_low": indexed["spot"][ts]["low"],
                "spot_close": indexed["spot"][ts]["close"],
                "spot_volume": indexed["spot"][ts].get("volume"),
                "perp_close": indexed["perp"][ts]["close"],
                "perp_volume": indexed["perp"][ts].get("volume"),
                "mark_close": indexed["mark"][ts]["close"],
                "index_close": indexed["index"][ts]["close"],
                "basis": indexed["mark"][ts]["close"] - indexed["index"][ts]["close"],
                "funding_settlements": in_bar,
                "last_settled_rate": last_known[-1]["rate"] if last_known else None,
                "funding_interval_hours": float(meta["funding_interval_hours"]),
                "spread_source": "proxy_ohlcv_close",  # NOT an observed spread
            }
        )
        prev_ts = ts
    audit.rows = len(rows)
    audit.settlements = len(settle_sorted)
    audit.time_range_start = rows[0]["timestamp_utc"]
    audit.time_range_end = rows[-1]["timestamp_utc"]
    return rows, audit


def write_panel(panel_dir: str | Path, rows: list[dict[str, Any]], audit: PanelAudit) -> Path:
    out = Path(panel_dir)
    out.mkdir(parents=True, exist_ok=True)
    panel_path = out / "panel.jsonl"
    payload = "".join(canonical_dumps(r) + "\n" for r in rows)
    panel_path.write_text(payload, encoding="utf-8")
    atomic_write_json(
        out / "panel_manifest.json",
        {
            "artifact": "HISTORICAL_CARRY_PANEL",
            "schema_version": 1,
            "rows": len(rows),
            "byte_sha256": sha256_of_bytes(payload.encode("utf-8")),
            "audit": audit.to_dict(),
        },
    )
    return panel_path


def load_panel(panel_dir: str | Path) -> list[dict[str, Any]]:
    panel_path = Path(panel_dir) / "panel.jsonl"
    if not panel_path.exists():
        raise ValueError(f"panel not found: {panel_path}")
    return [
        json.loads(line)
        for line in panel_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def panel_to_research_inputs(
    rows: list[dict[str, Any]], *, provenance: str
) -> tuple[list[dict[str, Any]], list[tuple[str, float]], list[float]]:
    """Panel rows → (snapshot records, settlements, settlement-driven signal).

    The signal series is the most recent SETTLED rate known at each bar —
    the pre-registered semantics (last N settlements), never a poll average.
    """
    snapshots: list[dict[str, Any]] = []
    settlements: list[tuple[str, float]] = []
    signal: list[float] = []
    seen: set[int] = set()
    for row in rows:
        snapshots.append(
            {
                "symbol": row["symbol"],
                "exchange": row["venue"],
                "captured_at_utc": row["timestamp_utc"],
                "spot_price": float(row["spot_close"]),
                "perp_mark_price": float(row["mark_close"]),
                "perp_index_price": float(row["index_close"]),
                "realized_funding_rate": float(row["last_settled_rate"] or 0.0),
                "funding_interval_hours": float(row["funding_interval_hours"]),
                "data_source": provenance,
                "source_name": "historical_carry_panel",
            }
        )
        signal.append(float(row["last_settled_rate"] or 0.0))
        for s in row.get("funding_settlements", []):
            ms = int(s["settled_at_ms"])
            if ms not in seen:
                seen.add(ms)
                settlements.append((_iso(ms), float(s["rate"])))
    return snapshots, settlements, signal
