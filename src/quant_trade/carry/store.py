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

#: Event semantics. A poll is a QUOTE observation — it never settles funding.
#: - "poll" / "backfill": quote observation (prices + the currently QUOTED
#:   funding rate, which is informational/predictive, never a payment);
#: - "funding_settlement": a settled funding payment. Its
#:   ``exchange_timestamp_utc`` IS the funding settlement time, so the dedup
#:   key (venue|symbol|funding_time|funding_settlement) collapses re-captures;
#: - "funding_prediction": an explicit forecast; never enters realized P&L;
#: - "open_interest": an OI observation.
EVENT_TYPES = ("poll", "backfill", "funding_settlement", "funding_prediction", "open_interest")
QUOTE_EVENTS = ("poll", "backfill")


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
    source_event: str = "poll"
    source_name: str = "unknown"
    raw_sha256: str = ""  # hash of the preserved raw response
    perp_last: float | None = None  # last trade; NEVER a substitute for mark
    spot_instrument_id: str = ""
    perpetual_instrument_id: str = ""
    contract_type: str = "linear_perpetual"
    quote_asset: str = "USDT"
    settlement_asset: str = ""
    schema_version: int = 2

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
        if self.source_event not in EVENT_TYPES:
            raise ValueError(f"source_event must be one of {EVENT_TYPES}")
        if self.contract_type not in ("linear_perpetual", "inverse_perpetual"):
            raise ValueError("contract_type must be linear_perpetual or inverse_perpetual")
        if self.perp_last is not None and (
            not math.isfinite(self.perp_last) or self.perp_last <= 0
        ):
            raise ValueError("perp_last must be finite and > 0 when provided")

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

    An exclusive ``flock`` on a sidecar lock file serialises concurrent
    collectors: the read-known-keys + append sequence is atomic with respect
    to any other process/thread honouring the same lock, so two simultaneous
    collectors can neither duplicate nor interleave records. Lines are written
    in one buffered write followed by flush+fsync.
    """
    import fcntl

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_path = p.with_suffix(p.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
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
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return AppendResult(
        appended=len(fresh),
        deduplicated=len(observations) - len(fresh),
        path=str(p),
    )


def verify_raw_payload(record: dict[str, Any], raw_bytes: bytes) -> bool:
    """True iff the preserved raw payload still hashes to the record's raw_sha256.

    A record whose raw evidence no longer matches is invalid — one flipped byte
    breaks the chain.
    """
    import hashlib

    expected = str(record.get("raw_sha256", "")).strip()
    if not expected:
        return False
    return hashlib.sha256(raw_bytes).hexdigest() == expected


def extract_settlement_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Settled funding events only, deduped by (venue|symbol|funding_time), sorted.

    Polls and predictions never appear here: this is the ONLY input from which
    realized funding P&L may accrue.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in records:
        if str(r.get("source_event", "poll")) != "funding_settlement":
            continue
        key = f"{r.get('venue')}|{r.get('symbol')}|{r.get('exchange_timestamp_utc')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda r: str(r.get("exchange_timestamp_utc", "")))
    return out


def observations_to_snapshot_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bridge QUOTE observations to the CarrySnapshot record schema.

    Only quote events (poll/backfill) become price snapshots; settlement and
    prediction events are excluded here — settlements feed P&L exclusively via
    :func:`extract_settlement_events`. The quoted funding rate carried on each
    snapshot is SIGNAL input (the rate currently quoted), never a payment.
    """
    out: list[dict[str, Any]] = []
    for r in records:
        if str(r.get("source_event", "poll")) not in QUOTE_EVENTS:
            continue
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
