"""Sparse, hash-bound evidence for venue market events.

Klines do not prove why an instrument stopped producing bars.  Halts and
delistings therefore travel in a separate ledger whose rows cite explicit
source bytes.  The ledger never manufactures OHLC values; consumers join its
event timestamps to the venue-open calendar causally.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.data.crypto_panel import (
    MARKET_EVENT_DELISTED,
    MARKET_EVENT_DELISTING_ANNOUNCED,
    MARKET_EVENT_DELISTING_CONFIRMED,
    MARKET_EVENT_HALT,
    MARKET_EVENT_LISTING_ENDED_CONFIRMED,
)
from quant_trade.evidence.canonical_json import (
    atomic_write_text,
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)

MARKET_EVENT_LEDGER_SCHEMA_VERSION = 1
EVIDENCED_MARKET_EVENTS = frozenset(
    {
        MARKET_EVENT_HALT,
        MARKET_EVENT_DELISTING_ANNOUNCED,
        MARKET_EVENT_DELISTING_CONFIRMED,
        MARKET_EVENT_LISTING_ENDED_CONFIRMED,
        MARKET_EVENT_DELISTED,
    }
)


class CryptoMarketEventError(ValueError):
    """Raised when event evidence is ambiguous, non-causal, or tampered."""


def _utc_timestamp(value: Any, field_name: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed) or not isinstance(parsed, pd.Timestamp):
        raise CryptoMarketEventError(f"{field_name} must be an explicit UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CryptoMarketEventError(f"{field_name} must be an explicit UTC timestamp")
    return parsed.tz_convert("UTC")


@dataclass(frozen=True)
class MarketEventEvidence:
    """One explicit venue event tied to independently hashable source bytes."""

    instrument_id: str
    venue: str
    event: str
    effective_at_utc: str
    observed_at_utc: str
    source: str
    source_sha256: str
    terminal_recovery_price: float | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"CMC:[1-9][0-9]*", self.instrument_id):
            raise CryptoMarketEventError("instrument_id must use stable CMC:<positive id>")
        if self.venue.strip().lower() != self.venue or not self.venue:
            raise CryptoMarketEventError("venue must be a canonical lower-case value")
        if self.event not in EVIDENCED_MARKET_EVENTS:
            raise CryptoMarketEventError(f"unsupported evidenced market event {self.event!r}")
        effective = _utc_timestamp(self.effective_at_utc, "effective_at_utc")
        observed = _utc_timestamp(self.observed_at_utc, "observed_at_utc")
        if observed > effective:
            raise CryptoMarketEventError(
                "observed_at_utc must be no later than effective_at_utc for causal use"
            )
        if not self.source.strip():
            raise CryptoMarketEventError("source is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise CryptoMarketEventError("source_sha256 must be a lower-case SHA-256")
        if self.terminal_recovery_price is not None and self.terminal_recovery_price <= 0:
            raise CryptoMarketEventError("terminal_recovery_price must be positive when present")
        terminal = self.event in {
            MARKET_EVENT_DELISTING_CONFIRMED,
            MARKET_EVENT_LISTING_ENDED_CONFIRMED,
            MARKET_EVENT_DELISTED,
        }
        if self.terminal_recovery_price is not None and not terminal:
            raise CryptoMarketEventError(
                "terminal_recovery_price is allowed only for a confirmed terminal event"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketEventLedger:
    """Deterministic sparse event component suitable for a dataset manifest."""

    events: tuple[MarketEventEvidence, ...]
    schema_version: int = MARKET_EVENT_LEDGER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MARKET_EVENT_LEDGER_SCHEMA_VERSION:
            raise CryptoMarketEventError(
                f"market-event schema_version must be {MARKET_EVENT_LEDGER_SCHEMA_VERSION}"
            )
        ordered = tuple(
            sorted(
                self.events,
                key=lambda item: (
                    item.effective_at_utc,
                    item.instrument_id,
                    item.event,
                    item.source_sha256,
                ),
            )
        )
        if ordered != self.events:
            object.__setattr__(self, "events", ordered)
        keys = [(event.effective_at_utc, event.instrument_id, event.event) for event in self.events]
        if len(keys) != len(set(keys)):
            raise CryptoMarketEventError(
                "duplicate effective_at_utc/instrument_id/event evidence is ambiguous"
            )

    @classmethod
    def from_events(cls, events: Iterable[MarketEventEvidence]) -> MarketEventLedger:
        return cls(tuple(events))

    def sealed_content(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "events": [event.to_dict() for event in self.events],
        }

    def digest(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.sealed_content(), "digest": self.digest()}

    def to_frame(self) -> pd.DataFrame:
        columns = [
            "timestamp",
            "instrument_id",
            "symbol",
            "venue",
            "market_event",
            "observed_at_utc",
            "source",
            "source_sha256",
            "terminal_recovery_price",
        ]
        rows = [
            {
                "timestamp": _utc_timestamp(event.effective_at_utc, "effective_at_utc"),
                "instrument_id": event.instrument_id,
                "symbol": event.instrument_id,
                "venue": event.venue,
                "market_event": event.event,
                "observed_at_utc": _utc_timestamp(event.observed_at_utc, "observed_at_utc"),
                "source": event.source,
                "source_sha256": event.source_sha256,
                "terminal_recovery_price": event.terminal_recovery_price,
            }
            for event in self.events
        ]
        return pd.DataFrame(rows, columns=columns)


def write_market_event_ledger(
    path: str | Path,
    ledger: MarketEventLedger,
    *,
    overwrite: bool = False,
) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise CryptoMarketEventError(
            f"market-event ledger already exists at {destination}; use a new version"
        )
    # Canonical bytes make the manifest component hash portable and stable.
    return atomic_write_text(destination, canonical_dumps(ledger.to_dict()))


def load_market_event_ledger(
    path: str | Path,
    *,
    expected_component_sha256: str | None = None,
) -> MarketEventLedger:
    source = Path(path)
    if expected_component_sha256 is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_component_sha256):
            raise CryptoMarketEventError("expected_component_sha256 must be a lower-case SHA-256")
        observed_component = sha256_of_file(source)
        if not hmac.compare_digest(observed_component, expected_component_sha256):
            raise CryptoMarketEventError("market-event component byte hash mismatch")
    payload = load_json(source)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "events", "digest"}:
        raise CryptoMarketEventError("market-event ledger has an invalid top-level schema")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise CryptoMarketEventError("market-event ledger events must be a JSON array")
    try:
        events = tuple(MarketEventEvidence(**row) for row in raw_events if isinstance(row, dict))
    except TypeError as exc:
        raise CryptoMarketEventError(f"malformed market-event evidence: {exc}") from exc
    if len(events) != len(raw_events):
        raise CryptoMarketEventError("every market-event entry must be a JSON object")
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise CryptoMarketEventError("market-event schema_version must be an integer")
    ledger = MarketEventLedger(events=events, schema_version=schema_version)
    claimed = payload.get("digest")
    if not isinstance(claimed, str) or not hmac.compare_digest(claimed, ledger.digest()):
        raise CryptoMarketEventError("market-event ledger embedded digest mismatch")
    return ledger


__all__ = [
    "EVIDENCED_MARKET_EVENTS",
    "MARKET_EVENT_LEDGER_SCHEMA_VERSION",
    "CryptoMarketEventError",
    "MarketEventEvidence",
    "MarketEventLedger",
    "load_market_event_ledger",
    "write_market_event_ledger",
]
