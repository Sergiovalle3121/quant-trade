"""Immutable instrument identity: P&L never crosses instrument boundaries.

A carry return series is only meaningful within ONE economic identity — one
venue, one canonical symbol, one spot instrument, one perpetual contract, one
quote/settlement asset, one funding interval. Mixing identities in a single
series turns cross-instrument price differences (BTC→ETH, Binance→OKX) into
fictitious basis P&L. Everything here fails closed on mixture; consolidation
across identities happens only in the explicit opportunity allocator, never by
concatenation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quant_trade.carry.quality import parse_utc

MAX_CLOCK_SKEW_SECONDS = 120.0


@dataclass(frozen=True)
class InstrumentIdentity:
    venue: str
    canonical_symbol: str
    spot_instrument_id: str
    perpetual_instrument_id: str
    contract_type: str  # "linear_perpetual" | "inverse_perpetual"
    quote_asset: str
    settlement_asset: str
    funding_interval_hours: float

    def __post_init__(self) -> None:
        if not self.venue.strip() or not self.canonical_symbol.strip():
            raise ValueError("venue and canonical_symbol are required")
        if self.contract_type not in ("linear_perpetual", "inverse_perpetual"):
            raise ValueError("contract_type must be linear_perpetual or inverse_perpetual")
        if self.funding_interval_hours <= 0:
            raise ValueError("funding_interval_hours must be > 0")

    @property
    def key(self) -> str:
        return "|".join(
            [
                self.venue,
                self.canonical_symbol,
                self.spot_instrument_id,
                self.perpetual_instrument_id,
                self.contract_type,
                self.quote_asset,
                self.settlement_asset,
                f"{self.funding_interval_hours:g}h",
            ]
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> InstrumentIdentity:
        """Derive the identity from a stored record.

        Explicit fields win; defaults are derived ONLY from the record's own
        venue/symbol (never inferred from neighbouring records).
        """
        venue = str(record.get("venue", "")).strip()
        symbol = str(record.get("symbol", "")).strip()
        quote = str(record.get("quote_asset", "USDT")).strip()
        return cls(
            venue=venue,
            canonical_symbol=symbol,
            spot_instrument_id=str(record.get("spot_instrument_id") or f"{symbol}/{quote}"),
            perpetual_instrument_id=str(
                record.get("perpetual_instrument_id") or f"{symbol}/{quote}:{quote}"
            ),
            contract_type=str(record.get("contract_type", "linear_perpetual")),
            quote_asset=quote,
            settlement_asset=str(record.get("settlement_asset", quote)),
            funding_interval_hours=float(record.get("funding_interval_hours", 8.0)),
        )


def group_by_identity(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(InstrumentIdentity.from_record(record).key, []).append(record)
    return grouped


def require_single_identity(records: list[dict[str, Any]]) -> InstrumentIdentity:
    """Fail closed unless every record shares one full economic identity."""
    if not records:
        raise ValueError("no records to evaluate")
    grouped = group_by_identity(records)
    if len(grouped) > 1:
        keys = ", ".join(sorted(grouped))
        raise ValueError(
            f"mixed instrument identities in one series: [{keys}]. A return series "
            "never crosses instruments; run one campaign per identity (the "
            "opportunity scanner is the explicit allocator)"
        )
    return InstrumentIdentity.from_record(records[0])


def check_clock_skew(record: dict[str, Any]) -> str | None:
    """Return a problem string when capture and venue clocks diverge too far.

    Only QUOTE events are checked: a quote's exchange timestamp should be
    near-simultaneous with capture, so a large gap means a broken clock or a
    stale response. Backfilled settlements and predictions legitimately carry
    a HISTORICAL exchange timestamp far from capture time — skew between the
    two is expected there, not diagnostic.
    """
    if str(record.get("source_event", "poll")) != "poll":
        return None
    try:
        captured = parse_utc(str(record.get("captured_at_utc", "")))
        exchange = parse_utc(str(record.get("exchange_timestamp_utc", "")))
    except ValueError as exc:
        return f"unparseable timestamps: {exc}"
    skew = abs((captured - exchange).total_seconds())
    if skew > MAX_CLOCK_SKEW_SECONDS:
        return (
            f"clock skew {skew:.0f}s exceeds {MAX_CLOCK_SKEW_SECONDS:.0f}s between "
            "captured_at and exchange timestamp"
        )
    return None
