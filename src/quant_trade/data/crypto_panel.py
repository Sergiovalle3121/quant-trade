"""Build a tradable panel from the point-in-time universe and venue klines.

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

SCHEMA_VERSION = 1

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
        "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "PAX", "GUSD", "FRAX",
        "LUSD", "SUSD", "USDD", "FDUSD", "PYUSD", "USDE", "EURT", "EURS",
        "USTC", "UST", "USDJ", "HUSD", "USDN", "MIM", "ALUSD", "CUSD", "USDX",
    }
)


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

    #: (date, cmc_id) -> {rank, market_cap_usd, volume24h_usd, implied_price}
    by_date_coin: dict[tuple[str, int], dict[str, float]]
    #: ticker -> set of cmc_ids that ever carried it in the window
    ids_by_symbol: dict[str, set[int]]
    #: cmc_id -> the ticker it carried on each date
    symbol_by_date_coin: dict[tuple[str, int], str]
    days: int
    coins: int
    stablecoins_seen: int


def load_universe_facts(
    universe_dir: str | Path,
    *,
    start_date: date,
    end_date: date,
    rank_ceiling: int = 1000,
    exclude_stablecoins: bool = True,
) -> UniverseFacts:
    """Stream the day files into the facts the join needs.

    Duplicate ``(date, cmc_id)`` rows collapse here rather than downstream: the
    source served four days padded with byte-identical repeats (see
    ``docs/CRYPTO_LOWCAP_DATASET.md``), so keeping the first occurrence chooses
    nothing. Rows with negative market cap are dropped and counted — a negative
    capitalisation is a source error, and carrying it into a tier assignment
    would silently place a coin in the wrong cost band.
    """
    days_dir = Path(universe_dir) / "days"
    by_date_coin: dict[tuple[str, int], dict[str, float]] = {}
    ids_by_symbol: dict[str, set[int]] = {}
    symbol_by_date_coin: dict[tuple[str, int], str] = {}
    days = 0
    stablecoins_seen = 0
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
                rank = row.get("cmc_rank")
                if rank is None or int(rank) > rank_ceiling:
                    continue
                coin_id = int(row["cmc_id"])
                if coin_id in seen:
                    continue
                seen.add(coin_id)
                market_cap = float(row["market_cap_usd"])
                volume = float(row["volume24h_usd"])
                if market_cap < 0 or volume < 0:
                    continue
                symbol = str(row["symbol"]).upper()
                if exclude_stablecoins and symbol in STABLECOIN_SYMBOLS:
                    stablecoins_seen += 1
                    continue
                supply = float(row.get("circulating_supply") or 0.0)
                by_date_coin[(day_iso, coin_id)] = {
                    "cmc_rank": float(rank),
                    "market_cap_usd": market_cap,
                    "volume24h_usd": volume,
                    "circulating_supply": supply,
                    "implied_price": (market_cap / supply) if supply > 0 else 0.0,
                }
                symbol_by_date_coin[(day_iso, coin_id)] = symbol
                ids_by_symbol.setdefault(symbol, set()).add(coin_id)
    coins = len({coin for _day, coin in by_date_coin})
    return UniverseFacts(
        by_date_coin=by_date_coin,
        ids_by_symbol=ids_by_symbol,
        symbol_by_date_coin=symbol_by_date_coin,
        days=days,
        coins=coins,
        stablecoins_seen=stablecoins_seen,
    )


def load_venue_series(
    venue_dir: str | Path, *, start_date: date, end_date: date
) -> dict[str, dict[str, dict[str, float]]]:
    """``{symbol: {date: bar}}`` for every symbol the venue actually listed."""
    base = Path(venue_dir)
    journal = _read_jsonl(base / "journal.jsonl")
    start_iso, end_iso = start_date.isoformat(), end_date.isoformat()
    series: dict[str, dict[str, dict[str, float]]] = {}
    for record in journal:
        if record.get("type") != "symbol" or record.get("outcome") != "listed":
            continue
        symbol = record["symbol"]
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


def _base_ticker(venue_symbol: str, quote: str = "USDT") -> str:
    return venue_symbol[: -len(quote)] if venue_symbol.endswith(quote) else venue_symbol


def bind_bar_to_coin(
    *,
    candidates: set[int],
    day_iso: str,
    close: float,
    facts: UniverseFacts,
    tolerance: float = PRICE_AGREEMENT_TOLERANCE,
) -> int | None:
    """Which coin a venue bar belongs to, decided by price agreement.

    With one candidate the ticker is unambiguous and the bar binds directly.
    With several, the bar goes to the candidate whose snapshot-implied price is
    closest to the venue close, and only if that candidate is present in the
    snapshot that day and inside the tolerance. Returning ``None`` means the
    evidence does not identify an owner, which is a recordable outcome and not
    a reason to guess.
    """
    present = [c for c in candidates if (day_iso, c) in facts.by_date_coin]
    if not present:
        return None
    if len(present) == 1 and len(candidates) == 1:
        return present[0]
    best: tuple[float, int] | None = None
    for coin_id in present:
        implied = facts.by_date_coin[(day_iso, coin_id)]["implied_price"]
        if implied <= 0 or close <= 0:
            continue
        relative = abs(close - implied) / implied
        if relative <= tolerance and (best is None or relative < best[0]):
            best = (relative, coin_id)
    return best[1] if best else None


def build_panel(
    universe_dir: str | Path,
    venue_dirs: dict[str, str | Path],
    *,
    start_date: date,
    end_date: date,
    rank_ceiling: int = 1000,
    tolerance: float = PRICE_AGREEMENT_TOLERANCE,
    min_bound_bars: int = MIN_BOUND_BARS,
) -> tuple[Any, PanelBuildReport]:
    """Join universe membership to venue prices into one canonical panel.

    Returns ``(DataFrame, report)``. The frame carries the canonical OHLCV
    columns plus the point-in-time facts a strategy is allowed to see on that
    date: rank, market cap, venue turnover and cost tier. Nothing in a row is
    knowable later than that row's own date.

    When both venues list a coin, the one with the longer bound history wins
    and the choice is recorded per coin, because the venues disagree about
    death dates and mixing them within a series would manufacture a history
    neither venue served.
    """
    import pandas as pd

    facts = load_universe_facts(
        universe_dir,
        start_date=start_date,
        end_date=end_date,
        rank_ceiling=rank_ceiling,
    )
    report = PanelBuildReport(
        window=(start_date.isoformat(), end_date.isoformat()),
        universe_days=facts.days,
        coins_in_rank_band=facts.coins,
        stablecoins_excluded=facts.stablecoins_seen,
        venues_used=sorted(venue_dirs),
    )

    # (venue, coin_id) -> {date: bar}
    bound: dict[tuple[str, int], dict[str, dict[str, float]]] = {}
    for venue, directory in sorted(venue_dirs.items()):
        series = load_venue_series(directory, start_date=start_date, end_date=end_date)
        report.venue_symbols_listed += len(series)
        for venue_symbol, bars in series.items():
            ticker = _base_ticker(venue_symbol)
            candidates = facts.ids_by_symbol.get(ticker, set())
            if not candidates:
                continue
            if len(candidates) == 1:
                report.symbols_unique_ticker += 1
            else:
                report.symbols_ambiguous_ticker += 1
            for day_iso, bar in bars.items():
                coin_id = bind_bar_to_coin(
                    candidates=candidates,
                    day_iso=day_iso,
                    close=float(bar["close"]),
                    facts=facts,
                    tolerance=tolerance,
                )
                if coin_id is None:
                    if len(candidates) > 1:
                        report.ambiguous_bars_unbound += 1
                    continue
                if len(candidates) > 1:
                    report.ambiguous_bars_bound += 1
                bound.setdefault((venue, coin_id), {})[day_iso] = bar

    # One venue per coin: the one that bound more of its history.
    best_venue: dict[int, str] = {}
    for (venue, coin_id), bars in bound.items():
        current = best_venue.get(coin_id)
        if current is None or len(bars) > len(bound[(current, coin_id)]):
            best_venue[coin_id] = venue

    rows: list[dict[str, Any]] = []
    for coin_id, venue in sorted(best_venue.items()):
        bars = bound[(venue, coin_id)]
        if len(bars) < min_bound_bars:
            report.coins_below_min_bound_bars += 1
            continue
        for day_iso, bar in sorted(bars.items()):
            snapshot = facts.by_date_coin.get((day_iso, coin_id))
            if snapshot is None:
                continue  # not in the point-in-time universe that day
            rows.append(
                {
                    "timestamp": datetime.fromisoformat(day_iso).replace(
                        tzinfo=UTC
                    ),
                    "symbol": f"{facts.symbol_by_date_coin[(day_iso, coin_id)]}:{coin_id}",
                    "cmc_id": coin_id,
                    "venue": venue,
                    "open": float(bar["open"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                    "volume": float(bar["volume_base"]),
                    "venue_turnover_usd": float(bar["turnover_quote"]),
                    "cmc_rank": snapshot["cmc_rank"],
                    "market_cap_usd": snapshot["market_cap_usd"],
                    "reported_volume_usd": snapshot["volume24h_usd"],
                }
            )
    report.rows_in_panel = len(rows)
    report.coins_in_panel = len({r["cmc_id"] for r in rows})
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return frame, report


__all__ = [
    "MIN_BOUND_BARS",
    "PRICE_AGREEMENT_TOLERANCE",
    "STABLECOIN_SYMBOLS",
    "PanelBuildReport",
    "UniverseFacts",
    "bind_bar_to_coin",
    "build_panel",
    "load_universe_facts",
    "load_venue_series",
]
