"""Build a causal crypto panel from point-in-time universe and venue klines.

Two datasets have to be joined and they do not share an identity. The universe
knows coins by ``cmc_id``, which is stable across renames. The venues know only
tickers, and 6,208 tickers in the full history are carried by more than one
coin (624 inside the study window). Joining on the ticker welds unrelated price
histories together — the exact failure `docs/CRYPTO_LOWCAP_ANTIBIAS_PLAN.md`
names as a survivorship sub-poison.

The obvious defence, dropping every ambiguous ticker, is worse than the
disease. Ticker reuse happens *because* a coin died and its symbol was
recycled, so ambiguous tickers over-represent dead coins, and excluding them
would quietly delete deaths from the panel — reintroducing survivorship bias
while appearing to guard against it. Instead the binding is resolved per date
against evidence: the snapshot carries market cap and circulating supply, whose
ratio is an implied price, and the venue carries a close. A venue bar is
assigned to the coin whose implied price it matches. When no coin matches, the
bar is recorded ``unbound`` and excluded from that date only, never silently
attributed.

The venue is selected before any bars are inspected.  A row's stable identity
is the source id (``CMC:<cmc_id>``); ticker and venue symbol are metadata only.
Universe membership controls whether a position may be opened, never whether a
real venue mark is retained.  This distinction lets an existing holding remain
valued after it leaves the rank or market-cap band without pretending it is
still eligible for a new purchase.

The screens are all declared and all reported: what entered the panel, what was
excluded, and by which rule. pandas is used only to shape the final frame; the
streaming join over the day files is plain Python so it can run anywhere.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

DEFAULT_VENUE = "bybit"
MIN_MARKET_CAP_USD = 10_000_000.0
MAX_MARKET_CAP_USD = 1_000_000_000.0

DATA_STATUS_VALID = "VALID"
DATA_STATUS_DEGRADED = "DEGRADED"
DATA_STATUS_MISSING = "MISSING"
DATA_STATUS_INVALID = "INVALID"
DATA_STATUSES = frozenset(
    {
        DATA_STATUS_VALID,
        DATA_STATUS_DEGRADED,
        DATA_STATUS_MISSING,
        DATA_STATUS_INVALID,
    }
)
MARKET_EVENT_NONE = "NONE"
MARKET_EVENT_GAP = "GAP"
MARKET_EVENT_RENAME = "RENAME"
MARKET_EVENT_RANK_EXIT = "RANK_EXIT"
MARKET_EVENT_RANK_REENTRY = "RANK_REENTRY"
MARKET_EVENT_HALT = "HALT"
MARKET_EVENT_DELISTING_ANNOUNCED = "DELISTING_ANNOUNCED"
MARKET_EVENT_DELISTING_CONFIRMED = "DELISTING_CONFIRMED"
MARKET_EVENT_LISTING_ENDED_CONFIRMED = "LISTING_ENDED_CONFIRMED"
MARKET_EVENT_DELISTED = "DELISTED"
MARKET_EVENTS = frozenset(
    {
        MARKET_EVENT_NONE,
        MARKET_EVENT_GAP,
        MARKET_EVENT_RENAME,
        MARKET_EVENT_RANK_EXIT,
        MARKET_EVENT_RANK_REENTRY,
        MARKET_EVENT_HALT,
        MARKET_EVENT_DELISTING_ANNOUNCED,
        MARKET_EVENT_DELISTING_CONFIRMED,
        MARKET_EVENT_LISTING_ENDED_CONFIRMED,
        MARKET_EVENT_DELISTED,
    }
)

#: Relative gap allowed between a venue close and the snapshot-implied price
#: before the two are judged to describe different assets. Wide on purpose:
#: snapshot prices are cross-venue volume-weighted averages taken at a
#: different instant than a daily close, so a tight band would reject correct
#: bindings. It only has to separate "the same coin" from "a different coin",
#: and different coins sharing a ticker differ by orders of magnitude far more
#: often than by tens of percent. ASSUMPTION class, declared.
PRICE_AGREEMENT_TOLERANCE = 0.50

#: A coin needs this many bound bars before it can be held. Fewer and its
#: identity rests on too little evidence to trade on. ASSUMPTION, declared.
MIN_BOUND_BARS = 20

#: Stablecoins are excluded by declared filter, not by a returns-based screen
#: (which would be a look-ahead). The list is the tickers seen in the panel's
#: own top ranks; it is deliberately explicit rather than pattern-matched.
STABLECOIN_SYMBOLS = frozenset(
    {
        "USDT",
        "USDC",
        "BUSD",
        "DAI",
        "TUSD",
        "USDP",
        "PAX",
        "GUSD",
        "FRAX",
        "LUSD",
        "SUSD",
        "USDD",
        "FDUSD",
        "PYUSD",
        "USDE",
        "EURT",
        "EURS",
        "USTC",
        "UST",
        "USDJ",
        "HUSD",
        "USDN",
        "MIM",
        "ALUSD",
        "CUSD",
        "USDX",
    }
)


@dataclass(frozen=True, order=True)
class InstrumentId:
    """Stable CoinMarketCap identity, independent of every ticker spelling."""

    cmc_id: int

    def __post_init__(self) -> None:
        if self.cmc_id <= 0:
            raise ValueError("cmc_id must be positive")

    @property
    def value(self) -> str:
        return f"CMC:{self.cmc_id}"

    def __str__(self) -> str:
        return self.value


def normalise_data_status(value: Any) -> str:
    """Return one declared panel status, rejecting implicit truthy values."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("data_status must be a declared non-empty string")
    status = value.strip().upper()
    if status not in DATA_STATUSES:
        raise ValueError(f"unsupported data_status {value!r}")
    return status


def parse_market_events(value: Any) -> frozenset[str]:
    """Parse a possibly composite event without losing terminal semantics."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("market_event must be a declared non-empty string")
    raw_tokens = value.split("|")
    tokens = [token.strip().upper() for token in raw_tokens]
    if any(not token for token in tokens):
        raise ValueError(f"market_event contains an empty component: {value!r}")
    if len(tokens) != len(set(tokens)):
        raise ValueError(f"market_event contains duplicate components: {value!r}")
    unknown = sorted(set(tokens).difference(MARKET_EVENTS))
    if unknown:
        raise ValueError(f"unsupported market_event components: {unknown}")
    if MARKET_EVENT_NONE in tokens and len(tokens) != 1:
        raise ValueError("NONE cannot be combined with another market_event")
    return frozenset(tokens)


def normalise_market_event(value: Any) -> str:
    """Return the canonical upper-case spelling of an event expression."""

    tokens = parse_market_events(value)
    if tokens == {MARKET_EVENT_NONE}:
        return MARKET_EVENT_NONE
    # Preserve the producer's causal event ordering while normalising spelling.
    return "|".join(token.strip().upper() for token in str(value).split("|"))


def combine_market_events(*values: str) -> str:
    """Combine derived and evidenced events without erasing either meaning."""

    combined: list[str] = []
    for value in values:
        for token in str(value).split("|"):
            event = token.strip().upper()
            if event == MARKET_EVENT_NONE:
                continue
            if event not in combined:
                combined.append(event)
    return normalise_market_event("|".join(combined) if combined else MARKET_EVENT_NONE)


def overlay_market_events(
    panel: Any,
    market_events: Any,
    *,
    expected_venue: str = DEFAULT_VENUE,
) -> tuple[Any, Any]:
    """Overlay evidence that coincides with a bar and retain sparse event rows.

    Returns ``(panel_with_bar_events, sparse_events)``.  An event without a
    venue bar is deliberately not converted into OHLC; callers pass the sparse
    frame separately to the evaluator.
    """

    import pandas as pd

    if hasattr(market_events, "to_frame"):
        events = market_events.to_frame()
    elif isinstance(market_events, pd.DataFrame):
        events = market_events.copy()
    else:
        raise ValueError("market_events must be a DataFrame or MarketEventLedger")
    required = {"timestamp", "instrument_id", "venue", "market_event"}
    missing = sorted(required.difference(events.columns))
    if missing:
        raise ValueError(f"market_events missing required columns: {missing}")
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True, errors="coerce")
    if events["timestamp"].isna().any():
        raise ValueError("market_events contain invalid timestamps")
    events["instrument_id"] = events["instrument_id"].astype(str)
    if not events["instrument_id"].str.fullmatch(r"CMC:[1-9][0-9]*").all():
        raise ValueError("market_events require stable CMC:<positive id> identities")
    if {str(value).lower() for value in events["venue"].unique()} != {expected_venue.lower()}:
        raise ValueError(f"market_events must contain only venue={expected_venue!r}")
    events["market_event"] = events["market_event"].map(normalise_market_event)

    frame = panel.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    identity_column = "instrument_id" if "instrument_id" in frame else "symbol"
    row_keys = set(zip(frame["timestamp"], frame[identity_column].astype(str), strict=False))
    coincident = events.apply(
        lambda row: (row["timestamp"], row["instrument_id"]) in row_keys,
        axis=1,
    )
    on_bar = events[coincident]
    for row in on_bar.itertuples(index=False):
        evidenced_event = row.market_event
        mask = frame["timestamp"].eq(row.timestamp) & frame[identity_column].astype(str).eq(
            row.instrument_id
        )
        frame.loc[mask, "market_event"] = frame.loc[mask, "market_event"].map(
            lambda current, event=evidenced_event: combine_market_events(current, event)
        )
        if (
            hasattr(row, "terminal_recovery_price")
            and row.terminal_recovery_price is not None
            and not pd.isna(row.terminal_recovery_price)
        ):
            if "terminal_recovery_price" not in frame:
                frame["terminal_recovery_price"] = None
            frame.loc[mask, "terminal_recovery_price"] = float(row.terminal_recovery_price)
    sparse = events[~coincident].reset_index(drop=True)
    return frame, sparse


@dataclass(frozen=True)
class PanelRow:
    """One immutable point-in-time panel observation."""

    timestamp: datetime
    symbol: str
    instrument_id: str
    cmc_id: int
    ticker: str
    venue: str
    venue_symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    mark_price: float
    eligible_to_open: bool
    tradable: bool
    data_status: str
    market_event: str
    bound_bar_number: int
    first_venue_bar_at: datetime
    left_censored: bool
    universe_age_days: int
    venue_turnover_usd: float
    cmc_rank: float | None
    market_cap_usd: float
    reported_volume_usd: float
    circulating_supply: float
    in_rank_band: bool
    in_market_cap_band: bool

    def __post_init__(self) -> None:
        expected = str(InstrumentId(self.cmc_id))
        if self.instrument_id != expected or self.symbol != expected:
            raise ValueError(f"panel identity must be {expected}")
        if not self.ticker or not self.venue or not self.venue_symbol:
            raise ValueError("ticker, venue, and venue_symbol are required metadata")
        if min(self.open, self.high, self.low, self.close, self.mark_price) <= 0:
            raise ValueError("panel prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be >= open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be <= open, close, and high")
        if self.mark_price != self.close:
            raise ValueError("daily panel mark_price must equal the bound venue close")
        if (
            min(
                self.volume,
                self.venue_turnover_usd,
                self.market_cap_usd,
                self.reported_volume_usd,
                self.circulating_supply,
            )
            < 0
        ):
            raise ValueError("panel volumes, supply, and market cap must be non-negative")
        boolean_fields = (
            "eligible_to_open",
            "tradable",
            "left_censored",
            "in_rank_band",
            "in_market_cap_band",
        )
        if any(type(getattr(self, name)) is not bool for name in boolean_fields):
            raise ValueError(f"panel boolean fields must be actual bool values: {boolean_fields}")
        if self.eligible_to_open and not self.tradable:
            raise ValueError("an eligible open must also be tradable")
        if self.bound_bar_number < 1 or self.universe_age_days < 1:
            raise ValueError("bar number and universe age must be positive")
        if normalise_data_status(self.data_status) != self.data_status:
            raise ValueError("data_status must use its canonical spelling")
        if normalise_market_event(self.market_event) != self.market_event:
            raise ValueError("market_event must use its canonical spelling")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PanelBuildReport:
    """What entered the panel and what did not, by rule."""

    window: tuple[str, str] = ("", "")
    universe_days: int = 0
    coins_in_rank_band: int = 0
    venue_symbols_listed: int = 0
    symbols_unique_ticker: int = 0
    symbols_ambiguous_ticker: int = 0
    ambiguous_bars_bound: int = 0
    ambiguous_bars_unbound: int = 0
    stablecoins_excluded: int = 0
    coins_below_min_bound_bars: int = 0
    coins_in_panel: int = 0
    rows_in_panel: int = 0
    duplicate_rows_dropped: int = 0
    negative_value_rows_dropped: int = 0
    price_disagreement_bars_unbound: int = 0
    multiple_plausible_bars_unbound: int = 0
    warmup_rows_ineligible: int = 0
    rows_outside_open_universe: int = 0
    selected_venue: str = ""
    venues_used: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _dates(start: date, end: date) -> list[str]:
    span = (end - start).days
    return [(start + timedelta(days=i)).isoformat() for i in range(span + 1)]


@dataclass
class UniverseFacts:
    """Per (date, coin) snapshot facts, keyed for the join."""

    #: (date, cmc_id) -> point-in-time facts and declared membership flags
    by_date_coin: dict[tuple[str, int], dict[str, Any]]
    #: ticker -> set of cmc_ids that ever carried it in the window
    ids_by_symbol: dict[str, set[int]]
    #: cmc_id -> the ticker it carried on each date
    symbol_by_date_coin: dict[tuple[str, int], str]
    #: (ticker, cmc_id) -> first date that mapping had been observed
    first_symbol_date: dict[tuple[str, int], str]
    #: cmc_id -> first snapshot date observed inside the requested window
    first_observed_date: dict[int, str]
    days: int
    coins: int
    stablecoins_seen: int


def load_universe_facts(
    universe_dir: str | Path,
    *,
    start_date: date,
    end_date: date,
    rank_ceiling: int = 1000,
    market_cap_floor_usd: float = MIN_MARKET_CAP_USD,
    market_cap_ceiling_usd: float = MAX_MARKET_CAP_USD,
    exclude_stablecoins: bool = True,
    keep_coin_ids: set[int] | None = None,
) -> UniverseFacts:
    """Stream the day files into the facts the join needs.

    ``keep_coin_ids`` is an identity/memory filter, not a membership filter.
    Once an id is retained, its snapshots remain available outside the rank
    and market-cap bands. Membership stays explicit so leaving the open
    universe blocks a new position without erasing a real venue mark.

    The filter is by coin id and NOT by ticker on purpose. Filtering by ticker
    silently drops the dates on which a coin carried a different symbol, so a
    renamed coin loses part of its history — a survivorship-shaped hole opened
    by an optimisation. ``coin_ids_for_tickers`` resolves the ids first.

    Duplicate ``(date, cmc_id)`` rows collapse here rather than downstream: the
    source served four days padded with byte-identical repeats (see
    ``docs/CRYPTO_LOWCAP_DATASET.md``), so keeping the first occurrence chooses
    nothing. Rows with negative market cap are dropped and counted — a negative
    capitalisation is a source error, and carrying it into a tier assignment
    would silently place a coin in the wrong cost band.
    """
    if rank_ceiling < 1:
        raise ValueError("rank_ceiling must be >= 1")
    if market_cap_floor_usd < 0 or market_cap_ceiling_usd <= market_cap_floor_usd:
        raise ValueError("market-cap bounds must satisfy 0 <= floor < ceiling")

    days_dir = Path(universe_dir) / "days"
    by_date_coin: dict[tuple[str, int], dict[str, Any]] = {}
    ids_by_symbol: dict[str, set[int]] = {}
    symbol_by_date_coin: dict[tuple[str, int], str] = {}
    first_symbol_date: dict[tuple[str, int], str] = {}
    first_observed_date: dict[int, str] = {}
    days = 0
    stablecoins_seen = 0
    coins_in_band: set[int] = set()
    for day_iso in _dates(start_date, end_date):
        day_file = days_dir / f"{day_iso}.jsonl"
        if not day_file.exists():
            continue
        days += 1
        seen: set[int] = set()
        with day_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                coin_id = int(row["cmc_id"])
                if coin_id in seen:
                    continue
                seen.add(coin_id)
                rank_raw = row.get("cmc_rank")
                rank = float(rank_raw) if rank_raw is not None else None
                market_cap = float(row["market_cap_usd"])
                volume = float(row["volume24h_usd"])
                if market_cap < 0 or volume < 0:
                    continue
                symbol = str(row["symbol"]).upper()
                stablecoin_excluded = exclude_stablecoins and symbol in STABLECOIN_SYMBOLS
                if stablecoin_excluded:
                    stablecoins_seen += 1
                in_rank_band = rank is not None and rank <= rank_ceiling
                if in_rank_band and not stablecoin_excluded:
                    coins_in_band.add(coin_id)
                if keep_coin_ids is not None and coin_id not in keep_coin_ids:
                    continue
                supply = float(row.get("circulating_supply") or 0.0)
                in_market_cap_band = market_cap_floor_usd <= market_cap <= market_cap_ceiling_usd
                by_date_coin[(day_iso, coin_id)] = {
                    "cmc_rank": rank,
                    "market_cap_usd": market_cap,
                    "volume24h_usd": volume,
                    "circulating_supply": supply,
                    "implied_price": (market_cap / supply) if supply > 0 else 0.0,
                    "in_rank_band": in_rank_band,
                    "in_market_cap_band": in_market_cap_band,
                    "stablecoin_excluded": stablecoin_excluded,
                    "universe_eligible": (
                        in_rank_band and in_market_cap_band and not stablecoin_excluded
                    ),
                }
                symbol_by_date_coin[(day_iso, coin_id)] = symbol
                ids_by_symbol.setdefault(symbol, set()).add(coin_id)
                first_symbol_date.setdefault((symbol, coin_id), day_iso)
                first_observed_date.setdefault(coin_id, day_iso)
    coins = len(coins_in_band)
    return UniverseFacts(
        by_date_coin=by_date_coin,
        ids_by_symbol=ids_by_symbol,
        symbol_by_date_coin=symbol_by_date_coin,
        first_symbol_date=first_symbol_date,
        first_observed_date=first_observed_date,
        days=days,
        coins=coins,
        stablecoins_seen=stablecoins_seen,
    )


def coin_ids_for_tickers(
    universe_dir: str | Path,
    tickers: set[str],
    *,
    start_date: date,
    end_date: date,
    rank_ceiling: int = 1000,
) -> set[int]:
    """Every coin id that ever carried one of ``tickers`` in the window.

    A light pass that keeps only id/ticker pairs. Discovery deliberately does
    not apply the rank ceiling: otherwise extending the end date until a coin
    first enters the band would make that coin appear retrospectively.
    """
    if rank_ceiling < 1:
        raise ValueError("rank_ceiling must be >= 1")
    days_dir = Path(universe_dir) / "days"
    found: set[int] = set()
    for day_iso in _dates(start_date, end_date):
        day_file = days_dir / f"{day_iso}.jsonl"
        if not day_file.exists():
            continue
        with day_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if str(row["symbol"]).upper() in tickers:
                    found.add(int(row["cmc_id"]))
    return found


def load_venue_series(
    venue_dir: str | Path,
    *,
    start_date: date,
    end_date: date,
    expected_venue: str | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """``{symbol: {date: bar}}`` for every symbol the venue actually listed."""
    base = Path(venue_dir)
    journal = _read_jsonl(base / "journal.jsonl")
    if expected_venue is not None:
        header = next((record for record in journal if record.get("type") == "header"), None)
        recorded = str((header or {}).get("venue", "")).lower()
        if recorded != expected_venue.lower():
            raise ValueError(
                f"venue journal identifies {recorded or 'UNKNOWN'}, expected {expected_venue}"
            )
    start_iso, end_iso = start_date.isoformat(), end_date.isoformat()
    series: dict[str, dict[str, dict[str, float]]] = {}
    for record in journal:
        if record.get("type") != "symbol" or record.get("outcome") != "listed":
            continue
        symbol = str(record["symbol"]).upper()
        path = base / "series" / f"{symbol}.jsonl"
        if not path.exists():
            continue
        bars: dict[str, dict[str, float]] = {}
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                bar = json.loads(line)
                if start_iso <= bar["date"] <= end_iso:
                    bars[bar["date"]] = bar
        if bars:
            series[symbol] = bars
    return series


def _venue_history_bounds(
    venue_dir: str | Path,
) -> tuple[str | None, dict[str, str]]:
    """Return collection boundary and per-symbol first raw venue bar.

    The journal records both facts independently of the requested panel slice.
    That distinction is what lets H4 tell a listing first observed after the
    collection boundary from a history already alive when collection began.
    Missing provenance is treated conservatively by the caller.
    """

    base = Path(venue_dir)
    journal = _read_jsonl(base / "journal.jsonl")
    header = next((record for record in journal if record.get("type") == "header"), {})
    window = header.get("window")
    collection_start: str | None = None
    if isinstance(window, list) and len(window) == 2 and isinstance(window[0], str):
        try:
            collection_start = date.fromisoformat(window[0]).isoformat()
        except ValueError:
            collection_start = None

    first_dates: dict[str, str] = {}
    for record in journal:
        if record.get("type") != "symbol" or record.get("outcome") != "listed":
            continue
        symbol = str(record.get("symbol", "")).upper()
        first_date = record.get("first_date")
        if not symbol or not isinstance(first_date, str):
            continue
        try:
            first_dates[symbol] = date.fromisoformat(first_date).isoformat()
        except ValueError:
            continue
    return collection_start, first_dates


def _base_ticker(venue_symbol: str, quote: str = "USDT") -> str:
    return venue_symbol[: -len(quote)] if venue_symbol.endswith(quote) else venue_symbol


def _known_candidates(
    candidates: set[int], *, ticker: str | None, day_iso: str, facts: UniverseFacts
) -> list[int]:
    """Candidates whose ticker mapping was already observable on ``day_iso``."""
    if ticker is None:
        return sorted(candidates)
    return sorted(
        coin_id
        for coin_id in candidates
        if facts.first_symbol_date.get((ticker, coin_id), "9999-12-31") <= day_iso
    )


def _plausible_candidates(
    *,
    candidates: set[int],
    ticker: str | None,
    day_iso: str,
    close: float,
    facts: UniverseFacts,
    tolerance: float,
) -> list[int]:
    plausible: list[int] = []
    for coin_id in _known_candidates(candidates, ticker=ticker, day_iso=day_iso, facts=facts):
        snapshot = facts.by_date_coin.get((day_iso, coin_id))
        if snapshot is None:
            continue
        implied = float(snapshot["implied_price"])
        if implied <= 0 or close <= 0:
            continue
        relative = abs(close - implied) / implied
        if relative <= tolerance:
            plausible.append(coin_id)
    return plausible


def bind_bar_to_coin(
    *,
    candidates: set[int],
    day_iso: str,
    close: float,
    facts: UniverseFacts,
    tolerance: float = PRICE_AGREEMENT_TOLERANCE,
    ticker: str | None = None,
) -> int | None:
    """Which coin a venue bar belongs to, decided by price agreement.

    Every binding, including an apparently unique ticker, must agree with the
    snapshot-implied price.  Exactly one candidate must be plausible; choosing
    the closest of two plausible owners would turn uncertainty into false
    precision.  ``ticker`` additionally prevents a mapping first seen in the
    future from changing an earlier prefix.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    plausible = _plausible_candidates(
        candidates=candidates,
        ticker=ticker,
        day_iso=day_iso,
        close=close,
        facts=facts,
        tolerance=tolerance,
    )
    return plausible[0] if len(plausible) == 1 else None


def build_panel(
    universe_dir: str | Path,
    venue_dirs: dict[str, str | Path],
    *,
    start_date: date,
    end_date: date,
    venue: str = DEFAULT_VENUE,
    rank_ceiling: int = 1000,
    market_cap_floor_usd: float = MIN_MARKET_CAP_USD,
    market_cap_ceiling_usd: float = MAX_MARKET_CAP_USD,
    tolerance: float = PRICE_AGREEMENT_TOLERANCE,
    min_bound_bars: int = MIN_BOUND_BARS,
) -> tuple[Any, PanelBuildReport]:
    """Join membership to one ex-ante venue into a causal canonical panel.

    Returns ``(DataFrame, report)``. The frame carries canonical OHLCV plus
    point-in-time membership and identity metadata. ``venue`` is selected
    before any history is loaded; alternate directories
    are never inspected.  All bound bars remain in the frame.  The causal
    warm-up and point-in-time universe screens affect ``eligible_to_open`` only,
    never whether a historical mark is retained.
    """
    import pandas as pd

    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if min_bound_bars < 1:
        raise ValueError("min_bound_bars must be >= 1")
    selected_venue = venue.strip().lower()
    normalized_dirs = {name.strip().lower(): path for name, path in venue_dirs.items()}
    if selected_venue not in normalized_dirs:
        raise ValueError(
            f"selected venue {selected_venue!r} is absent; available={sorted(normalized_dirs)}"
        )

    # No alternate journal or series is read. Its future coverage therefore
    # cannot influence this panel.
    selected_venue_dir = normalized_dirs[selected_venue]
    venue_series = load_venue_series(
        selected_venue_dir,
        start_date=start_date,
        end_date=end_date,
        expected_venue=selected_venue,
    )
    venue_collection_start, venue_symbol_first_dates = _venue_history_bounds(selected_venue_dir)
    listed_tickers = {_base_ticker(symbol) for symbol in venue_series}

    tradable_ids = coin_ids_for_tickers(
        universe_dir,
        listed_tickers,
        start_date=start_date,
        end_date=end_date,
        rank_ceiling=rank_ceiling,
    )
    facts = load_universe_facts(
        universe_dir,
        start_date=start_date,
        end_date=end_date,
        rank_ceiling=rank_ceiling,
        market_cap_floor_usd=market_cap_floor_usd,
        market_cap_ceiling_usd=market_cap_ceiling_usd,
        keep_coin_ids=tradable_ids,
    )
    report = PanelBuildReport(
        window=(start_date.isoformat(), end_date.isoformat()),
        universe_days=facts.days,
        coins_in_rank_band=facts.coins,
        stablecoins_excluded=facts.stablecoins_seen,
        selected_venue=selected_venue,
        venues_used=[selected_venue],
        notes=["terminal venue bars are not interpreted as confirmed delistings"],
    )

    # coin_id -> date -> (venue_symbol, bar). A rename can leave both venue
    # spellings active on one day, so collisions are resolved from same-day
    # metadata only and never from future history length.
    bound: dict[int, dict[str, tuple[str, dict[str, Any]]]] = {}
    report.venue_symbols_listed = len(venue_series)
    for venue_symbol, venue_bars in sorted(venue_series.items()):
        ticker = _base_ticker(venue_symbol)
        candidates = facts.ids_by_symbol.get(ticker, set())
        if not candidates:
            continue
        if len(candidates) == 1:
            report.symbols_unique_ticker += 1
        else:
            report.symbols_ambiguous_ticker += 1
        for day_iso, bar in sorted(venue_bars.items()):
            known = _known_candidates(candidates, ticker=ticker, day_iso=day_iso, facts=facts)
            plausible = _plausible_candidates(
                candidates=candidates,
                ticker=ticker,
                day_iso=day_iso,
                close=float(bar["close"]),
                facts=facts,
                tolerance=tolerance,
            )
            if len(plausible) != 1:
                if len(known) > 1:
                    report.ambiguous_bars_unbound += 1
                if len(plausible) > 1:
                    report.multiple_plausible_bars_unbound += 1
                else:
                    report.price_disagreement_bars_unbound += 1
                continue
            coin_id = plausible[0]
            if len(known) > 1:
                report.ambiguous_bars_bound += 1
            coin_bars = bound.setdefault(coin_id, {})
            existing = coin_bars.get(day_iso)
            if existing is not None:
                report.duplicate_rows_dropped += 1
                daily_ticker = facts.symbol_by_date_coin[(day_iso, coin_id)]
                old_symbol = existing[0]
                old_score = (_base_ticker(old_symbol) != daily_ticker, old_symbol)
                new_score = (_base_ticker(venue_symbol) != daily_ticker, venue_symbol)
                if new_score >= old_score:
                    continue
            coin_bars[day_iso] = (venue_symbol, bar)

    rows: list[dict[str, Any]] = []
    for coin_id, coin_bars_by_day in sorted(bound.items()):
        if len(coin_bars_by_day) < min_bound_bars:
            report.coins_below_min_bound_bars += 1
        first_bound_day = min(coin_bars_by_day)
        first_observed_day = facts.first_observed_date[coin_id]
        first_bound_symbol = coin_bars_by_day[first_bound_day][0]
        raw_symbol_first_day = venue_symbol_first_dates.get(first_bound_symbol)
        # The stable identity's history is observed only when the venue symbol
        # through which it was first bound appears after the collection boundary
        # and that first raw bar is the first bar causally bound to this CMC id.
        # A later rename must never rewrite this provenance using the renamed
        # symbol's older raw history.  Anything else is conservative
        # left-censoring (including missing journal provenance and a reused
        # initial ticker whose older raw history belonged to another coin).
        history_origin_observed = (
            venue_collection_start is not None
            and raw_symbol_first_day is not None
            and raw_symbol_first_day > venue_collection_start
            and raw_symbol_first_day == first_bound_day
        )
        previous_day: str | None = None
        previous_ticker: str | None = None
        previous_in_rank_band: bool | None = None
        ordered_bars = sorted(coin_bars_by_day.items())
        for bound_bar_number, (day_iso, bound_bar) in enumerate(ordered_bars, start=1):
            venue_symbol, bar = bound_bar
            snapshot = facts.by_date_coin[(day_iso, coin_id)]
            ticker = facts.symbol_by_date_coin[(day_iso, coin_id)]
            universe_eligible = bool(snapshot["universe_eligible"])
            warmup_complete = bound_bar_number >= min_bound_bars
            eligible_to_open = universe_eligible and warmup_complete
            if universe_eligible and not warmup_complete:
                report.warmup_rows_ineligible += 1
            if not universe_eligible:
                report.rows_outside_open_universe += 1

            events: list[str] = []
            if previous_day is not None:
                gap_days = (date.fromisoformat(day_iso) - date.fromisoformat(previous_day)).days
                if gap_days > 1:
                    events.append(MARKET_EVENT_GAP)
                if ticker != previous_ticker:
                    events.append(MARKET_EVENT_RENAME)
                in_rank_band = bool(snapshot["in_rank_band"])
                if previous_in_rank_band and not in_rank_band:
                    events.append(MARKET_EVENT_RANK_EXIT)
                elif previous_in_rank_band is False and in_rank_band:
                    events.append(MARKET_EVENT_RANK_REENTRY)
            market_event = "|".join(events) if events else MARKET_EVENT_NONE
            timestamp = datetime.fromisoformat(day_iso).replace(tzinfo=UTC)
            close = float(bar["close"])
            instrument_id = str(InstrumentId(coin_id))
            rows.append(
                PanelRow(
                    timestamp=timestamp,
                    symbol=instrument_id,
                    instrument_id=instrument_id,
                    cmc_id=coin_id,
                    ticker=ticker,
                    venue=selected_venue,
                    venue_symbol=venue_symbol,
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=close,
                    volume=float(bar["volume_base"]),
                    mark_price=close,
                    eligible_to_open=eligible_to_open,
                    tradable=True,
                    data_status=DATA_STATUS_VALID,
                    market_event=market_event,
                    bound_bar_number=bound_bar_number,
                    first_venue_bar_at=datetime.fromisoformat(first_bound_day).replace(tzinfo=UTC),
                    left_censored=not history_origin_observed,
                    universe_age_days=(
                        date.fromisoformat(day_iso) - date.fromisoformat(first_observed_day)
                    ).days
                    + 1,
                    venue_turnover_usd=float(bar["turnover_quote"]),
                    cmc_rank=snapshot["cmc_rank"],
                    market_cap_usd=snapshot["market_cap_usd"],
                    reported_volume_usd=snapshot["volume24h_usd"],
                    circulating_supply=snapshot["circulating_supply"],
                    in_rank_band=bool(snapshot["in_rank_band"]),
                    in_market_cap_band=bool(snapshot["in_market_cap_band"]),
                ).to_dict()
            )
            previous_day = day_iso
            previous_ticker = ticker
            previous_in_rank_band = bool(snapshot["in_rank_band"])
    report.rows_in_panel = len(rows)
    report.coins_in_panel = len({r["cmc_id"] for r in rows})
    columns = [
        "timestamp",
        "symbol",
        "instrument_id",
        "cmc_id",
        "ticker",
        "venue",
        "venue_symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "mark_price",
        "eligible_to_open",
        "tradable",
        "data_status",
        "market_event",
        "bound_bar_number",
        "first_venue_bar_at",
        "left_censored",
        "universe_age_days",
        "venue_turnover_usd",
        "cmc_rank",
        "market_cap_usd",
        "reported_volume_usd",
        "circulating_supply",
        "in_rank_band",
        "in_market_cap_band",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame = frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return frame, report


__all__ = [
    "DATA_STATUSES",
    "DATA_STATUS_DEGRADED",
    "DATA_STATUS_INVALID",
    "DATA_STATUS_MISSING",
    "DATA_STATUS_VALID",
    "DEFAULT_VENUE",
    "InstrumentId",
    "MARKET_EVENTS",
    "MARKET_EVENT_DELISTED",
    "MARKET_EVENT_DELISTING_ANNOUNCED",
    "MARKET_EVENT_DELISTING_CONFIRMED",
    "MARKET_EVENT_GAP",
    "MARKET_EVENT_HALT",
    "MARKET_EVENT_LISTING_ENDED_CONFIRMED",
    "MARKET_EVENT_NONE",
    "MARKET_EVENT_RANK_EXIT",
    "MARKET_EVENT_RANK_REENTRY",
    "MARKET_EVENT_RENAME",
    "MAX_MARKET_CAP_USD",
    "MIN_MARKET_CAP_USD",
    "MIN_BOUND_BARS",
    "PanelRow",
    "PRICE_AGREEMENT_TOLERANCE",
    "STABLECOIN_SYMBOLS",
    "PanelBuildReport",
    "UniverseFacts",
    "bind_bar_to_coin",
    "build_panel",
    "combine_market_events",
    "coin_ids_for_tickers",
    "load_universe_facts",
    "load_venue_series",
    "normalise_data_status",
    "normalise_market_event",
    "overlay_market_events",
    "parse_market_events",
]
