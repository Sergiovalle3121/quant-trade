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

_KNOWN_QUOTES = ("USDT", "USDC", "USD")


def parse_symbol(symbol: str) -> tuple[str, str]:
    """Normalize any symbol spelling to (base, quote).

    Accepts the venue-native spellings ("BTCUSDT", "BTC-USDT-SWAP"), the ccxt
    unified form ("BTC/USDT:USDT"), and the bare canonical base ("BTC").
    """
    s = symbol.strip().upper()
    if not s:
        raise ValueError("symbol is required")
    if "/" in s:  # ccxt unified BASE/QUOTE[:SETTLE]
        base, rest = s.split("/", 1)
        quote = rest.split(":", 1)[0]
        return base, quote
    if ":" in s:  # canonical ids round-trip: "venue:BASE-QUOTE:linear-perp|spot"
        parts = s.split(":")
        if len(parts) == 3 and parts[2] in ("LINEAR-PERP", "SPOT"):
            s = parts[1]
    if s.endswith("-SWAP"):  # okx native BASE-QUOTE-SWAP
        parts = s.split("-")
        if len(parts) == 3:
            return parts[0], parts[1]
    if "-" in s:  # plain BASE-QUOTE
        parts = s.split("-")
        if len(parts) == 2 and parts[1] in _KNOWN_QUOTES:
            return parts[0], parts[1]
    for quote in _KNOWN_QUOTES:  # concatenated native (bybit/binance)
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)], quote
    return s, "USDT"  # bare canonical base


def canonical_instrument_id(venue: str, symbol: str) -> str:
    """ONE canonical id per economic pair, whatever the adapter's spelling.

    The backfill's ``bybit:BTCUSDT`` and the ccxt collector's
    ``BTC/USDT:USDT`` are the SAME perpetual — deriving different ids per
    adapter split one instrument into two and made its history unusable.
    """
    if not venue.strip():
        raise ValueError("venue is required")
    base, quote = parse_symbol(symbol)
    return f"{venue.strip().lower()}:{base}-{quote}:linear-perp"


def canonical_spot_id(venue: str, symbol: str) -> str:
    base, quote = parse_symbol(symbol)
    return f"{venue.strip().lower()}:{base}-{quote}:spot"


#: Static seed metadata from public venue documentation (funding interval and
#: native spellings). A live InstrumentCatalog refresh can extend this; the
#: seed keeps identities canonical offline.
INSTRUMENT_SEED_METADATA: dict[tuple[str, str], dict[str, Any]] = {
    ("bybit", "BTC"): {
        "native_spot_symbol": "BTCUSDT",
        "native_perp_symbol": "BTCUSDT",
        "funding_interval_hours": 8.0,
        "contract_type": "linear_perpetual",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
    },
    ("bybit", "ETH"): {
        "native_spot_symbol": "ETHUSDT",
        "native_perp_symbol": "ETHUSDT",
        "funding_interval_hours": 8.0,
        "contract_type": "linear_perpetual",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
    },
    ("okx", "BTC"): {
        "native_spot_symbol": "BTC-USDT",
        "native_perp_symbol": "BTC-USDT-SWAP",
        "funding_interval_hours": 8.0,
        "contract_type": "linear_perpetual",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
    },
    ("okx", "ETH"): {
        "native_spot_symbol": "ETH-USDT",
        "native_perp_symbol": "ETH-USDT-SWAP",
        "funding_interval_hours": 8.0,
        "contract_type": "linear_perpetual",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
    },
}


def instrument_metadata(venue: str, symbol: str) -> dict[str, Any]:
    """Seed metadata for a canonical pair; fails closed on unknown pairs."""
    base, _ = parse_symbol(symbol)
    meta = INSTRUMENT_SEED_METADATA.get((venue.strip().lower(), base))
    if meta is None:
        raise ValueError(
            f"no instrument metadata for {venue}:{base}; refusing to guess "
            "funding interval or contract terms"
        )
    return dict(meta)


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
        # every spelling — venue-native, ccxt unified, canonical, bare base —
        # normalizes through the canonical id, so one economic pair can never
        # split into per-adapter identities (V6-E)
        spot_raw = str(record.get("spot_instrument_id") or symbol)
        perp_raw = str(record.get("perpetual_instrument_id") or symbol)
        return cls(
            venue=venue,
            canonical_symbol=parse_symbol(symbol)[0] if symbol else symbol,
            spot_instrument_id=canonical_spot_id(venue, spot_raw) if venue else spot_raw,
            perpetual_instrument_id=(
                canonical_instrument_id(venue, perp_raw) if venue else perp_raw
            ),
            contract_type=str(record.get("contract_type") or "linear_perpetual"),
            quote_asset=quote,
            settlement_asset=str(record.get("settlement_asset") or quote),
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
