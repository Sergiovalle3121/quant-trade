"""Append-only, deduplicated store for point-in-time funding observations.

Real funding history is built one observation at a time over days or weeks.
The store is a JSONL file: one canonical-JSON record per line, append-only,
idempotent on a (venue, symbol, exchange_timestamp, source_event) key so a
re-run of the collector can never double-count, and corrupt lines are
quarantined — surfaced with line numbers, never silently dropped.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps


@dataclass(frozen=True)
class FundingObservation:
    """One point-in-time, read-only market observation of a spot/perp pair."""

    venue: str
    symbol: str
    captured_at_utc: str  # local wall clock at capture
    exchange_timestamp_utc: str  # the venue's own event/publish time
    spot_bid: float
    spot_ask: float
    perp_bid: float
    perp_ask: float
    perp_mark: float
    perp_index: float
    realized_funding_rate: float
    funding_interval_hours: float = 8.0
    next_funding_time_utc: str | None = None
    predicted_funding_rate: float | None = None
    open_interest: float | None = None
    source_event: str = "poll"  # e.g. "poll" | "funding_settlement" | "backfill"
    source_name: str = "unknown"
    raw_sha256: str = ""  # hash of the preserved raw response
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.venue.strip() or not self.symbol.strip():
            raise ValueError("venue and symbol are required")
        if not self.captured_at_utc.strip() or not self.exchange_timestamp_utc.strip():
            raise ValueError("captured_at_utc and exchange_timestamp_utc are required")
        for name in ("spot_bid", "spot_ask", "perp_bid", "perp_ask", "perp_mark", "perp_index"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and > 0")
        if self.spot_bid > self.spot_ask:
            raise ValueError("spot_bid cannot exceed spot_ask")
        if self.perp_bid > self.perp_ask:
            raise ValueError("perp_bid cannot exceed perp_ask")
        if not math.isfinite(self.realized_funding_rate):
            raise ValueError("realized_funding_rate must be finite")
        if self.funding_interval_hours <= 0:
            raise ValueError("funding_interval_hours must be > 0")

    @property
    def dedup_key(self) -> str:
        return f"{self.venue}|{self.symbol}|{self.exchange_timestamp_utc}|{self.source_event}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoreReadResult:
    records: list[dict[str, Any]]
    quarantined: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class AppendResult:
    appended: int
    deduplicated: int
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_store(path: str | Path) -> StoreReadResult:
    """Read all observations; quarantine (never drop) invalid lines."""
    p = Path(path)
    if not p.exists():
        return StoreReadResult(records=[])
    records: list[dict[str, Any]] = []
    quarantined: list[tuple[int, str]] = []
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            quarantined.append((i, raw))
            continue
        if isinstance(parsed, dict) and parsed.get("venue") and parsed.get("symbol"):
            records.append(parsed)
        else:
            quarantined.append((i, raw))
    return StoreReadResult(records=records, quarantined=quarantined)


def existing_dedup_keys(path: str | Path) -> set[str]:
    keys: set[str] = set()
    for record in read_store(path).records:
        keys.add(
            f"{record.get('venue')}|{record.get('symbol')}|"
            f"{record.get('exchange_timestamp_utc')}|{record.get('source_event', 'poll')}"
        )
    return keys


def append_observations(
    path: str | Path, observations: list[FundingObservation]
) -> AppendResult:
    """Idempotently append observations (existing dedup keys are skipped).

    Lines are written in one buffered write followed by flush+fsync so a crash
    cannot interleave partial lines from this batch with other content.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    known = existing_dedup_keys(p)
    fresh: list[FundingObservation] = []
    seen_batch: set[str] = set()
    for obs in observations:
        key = obs.dedup_key
        if key in known or key in seen_batch:
            continue
        seen_batch.add(key)
        fresh.append(obs)
    if fresh:
        payload = "".join(canonical_dumps(o.to_dict()) + "\n" for o in fresh)
        with p.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    return AppendResult(
        appended=len(fresh),
        deduplicated=len(observations) - len(fresh),
        path=str(p),
    )


def observations_to_snapshot_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bridge collected observations to the CarrySnapshot record schema.

    Mid prices become the spot/perp prices; provenance is preserved. The
    output feeds ``load_snapshots_from_records`` and the campaign runner.
    """
    out: list[dict[str, Any]] = []
    for r in records:
        spot_mid = (float(r["spot_bid"]) + float(r["spot_ask"])) / 2.0
        out.append(
            {
                "symbol": r["symbol"],
                "exchange": r["venue"],
                "captured_at_utc": r["exchange_timestamp_utc"],
                "spot_price": spot_mid,
                "perp_mark_price": float(r["perp_mark"]),
                "perp_index_price": float(r.get("perp_index", spot_mid)),
                "realized_funding_rate": float(r["realized_funding_rate"]),
                "funding_interval_hours": float(r.get("funding_interval_hours", 8.0)),
                "predicted_funding_rate": r.get("predicted_funding_rate"),
                "data_source": "real",
                "source_name": str(r.get("source_name", "collector")),
            }
        )
    return out
