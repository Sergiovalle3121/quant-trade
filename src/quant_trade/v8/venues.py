"""Official public endpoints and pure parsers for Bybit and OKX.

Every URL here is an **official, documented, unauthenticated** market-data
endpoint of the venue itself. No mirror, no scraper, no third-party
redistributor, no proxy that would evade a regional restriction: if a domain
is blocked, the blocked domain is recorded as evidence and the run stops.

Fetching and parsing are deliberately separate. A parser takes raw response
bytes and returns normalized rows — so the whole parse path is exercised
offline against recorded bytes, and the bytes that a test replays are the same
bytes a live run would have archived.

Parser discipline shared by both venues:

- the venue's own instrument identifier in the response must equal the one we
  requested; a mismatch raises instead of relabelling records;
- only **closed** bars are emitted (OKX marks them with ``confirm``; Bybit is
  bounded by the caller's window), because an in-progress bar's close is a
  future value;
- funding rows carry the *settled* rate. OKX publishes both ``fundingRate``
  (announced in advance) and ``realizedRate`` (what actually settled); the
  realized value wins and the choice is recorded per row;
- timestamps stay integer milliseconds since the UNIX epoch, UTC. No local
  timezone ever enters the pipeline.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from quant_trade.carry.instruments import parse_symbol

#: Parser version. Bump on any change that alters normalized row bytes; it
#: rides in every receipt so a re-parse mismatch is attributable.
PARSER_VERSION = "v8.1"

# --- official documented endpoints -------------------------------------------
BYBIT_HOST = "https://api.bybit.com"
BYBIT_KLINE_URL = f"{BYBIT_HOST}/v5/market/kline"
BYBIT_MARK_KLINE_URL = f"{BYBIT_HOST}/v5/market/mark-price-kline"
BYBIT_INDEX_KLINE_URL = f"{BYBIT_HOST}/v5/market/index-price-kline"
BYBIT_FUNDING_URL = f"{BYBIT_HOST}/v5/market/funding/history"
BYBIT_INSTRUMENTS_URL = f"{BYBIT_HOST}/v5/market/instruments-info"
BYBIT_TIME_URL = f"{BYBIT_HOST}/v5/market/time"

OKX_HOST = "https://www.okx.com"
OKX_CANDLES_URL = f"{OKX_HOST}/api/v5/market/history-candles"
OKX_MARK_CANDLES_URL = f"{OKX_HOST}/api/v5/market/history-mark-price-candles"
OKX_INDEX_CANDLES_URL = f"{OKX_HOST}/api/v5/market/history-index-candles"
OKX_FUNDING_URL = f"{OKX_HOST}/api/v5/public/funding-rate-history"
OKX_INSTRUMENTS_URL = f"{OKX_HOST}/api/v5/public/instruments"
OKX_TIME_URL = f"{OKX_HOST}/api/v5/public/time"

#: Series a complete carry panel needs from each venue.
SERIES_KINDS = ("spot", "perp", "mark", "index", "funding")

SUPPORTED_VENUES = ("bybit", "okx")

#: Documented public rate limits (requests per second) used to pace the
#: engine. Deliberately below the published ceiling: this is read-only
#: research traffic and must never look like an attack.
VENUE_RATE_LIMIT_RPS = {"bybit": 5.0, "okx": 4.0}


class IdentityMismatch(ValueError):
    """The response describes a different instrument than the one requested."""


class VenueErrorResponse(ValueError):
    """The venue answered with an application-level error envelope."""


# --- native instrument spellings ---------------------------------------------


def bybit_spot_symbol(symbol: str) -> str:
    base, quote = parse_symbol(symbol)
    return f"{base}{quote}"


def bybit_perp_symbol(symbol: str) -> str:
    base, quote = parse_symbol(symbol)
    return f"{base}{quote}"


def okx_spot_inst_id(symbol: str) -> str:
    base, quote = parse_symbol(symbol)
    return f"{base}-{quote}"


def okx_perp_inst_id(symbol: str) -> str:
    base, quote = parse_symbol(symbol)
    return f"{base}-{quote}-SWAP"


def okx_index_inst_id(symbol: str) -> str:
    """OKX index candles are keyed by the *index* id, e.g. ``BTC-USDT``."""
    return okx_spot_inst_id(symbol)


#: Bybit kline ``interval`` values, keyed by minutes.
_BYBIT_INTERVALS = {1: "1", 3: "3", 5: "5", 15: "15", 30: "30", 60: "60", 240: "240", 1440: "D"}
#: OKX ``bar`` values, keyed by minutes.
_OKX_BARS = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1H", 240: "4H", 1440: "1D"}


def bybit_interval(interval_minutes: int) -> str:
    try:
        return _BYBIT_INTERVALS[interval_minutes]
    except KeyError as exc:
        raise ValueError(
            f"bybit does not publish a {interval_minutes}m kline; "
            f"supported: {sorted(_BYBIT_INTERVALS)}"
        ) from exc


def okx_bar(interval_minutes: int) -> str:
    try:
        return _OKX_BARS[interval_minutes]
    except KeyError as exc:
        raise ValueError(
            f"okx does not publish a {interval_minutes}m bar; supported: {sorted(_OKX_BARS)}"
        ) from exc


# --- Bybit parsers ------------------------------------------------------------


def _bybit_envelope(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise VenueErrorResponse("bybit response is not a JSON object")
    if int(payload.get("retCode", -1)) != 0:
        raise VenueErrorResponse(
            f"bybit retCode={payload.get('retCode')} retMsg={payload.get('retMsg')!r}"
        )
    return payload


def parse_bybit_kline(raw: bytes, *, symbol: str, kind: str) -> list[dict[str, Any]]:
    """Parse one Bybit v5 kline page (spot / linear / mark / index)."""
    payload = _bybit_envelope(raw)
    result = payload.get("result", {}) or {}
    expected = bybit_spot_symbol(symbol) if kind == "spot" else bybit_perp_symbol(symbol)
    got = str(result.get("symbol", ""))
    if got != expected:
        raise IdentityMismatch(
            f"requested {expected}, page carries {got!r} — refusing to relabel klines"
        )
    rows: list[dict[str, Any]] = []
    for entry in result.get("list", []) or []:
        row: dict[str, Any] = {
            "start_ms": int(entry[0]),
            "open": float(entry[1]),
            "high": float(entry[2]),
            "low": float(entry[3]),
            "close": float(entry[4]),
        }
        if kind in ("spot", "perp") and len(entry) >= 6:
            row["volume"] = float(entry[5])
        if len(entry) >= 7 and kind in ("spot", "perp"):
            row["quote_volume"] = float(entry[6])
        _validate_ohlc(row, venue="bybit", kind=kind)
        rows.append(row)
    rows.sort(key=lambda r: r["start_ms"])
    return rows


def parse_bybit_funding(raw: bytes, *, symbol: str, **_: Any) -> list[dict[str, Any]]:
    """Parse one Bybit v5 ``/market/funding/history`` page (settled rates)."""
    payload = _bybit_envelope(raw)
    expected = bybit_perp_symbol(symbol)
    rows: list[dict[str, Any]] = []
    for entry in payload.get("result", {}).get("list", []) or []:
        got = str(entry.get("symbol", ""))
        if got != expected:
            raise IdentityMismatch(
                f"requested {expected}, funding row carries {got!r} — refusing to relabel"
            )
        rows.append(
            {
                "settled_at_ms": int(entry["fundingRateTimestamp"]),
                "rate": float(entry["fundingRate"]),
                # Bybit's funding history endpoint publishes the rate that was
                # actually applied at settlement; there is no separate
                # announced/realized pair to choose between.
                "rate_field": "fundingRate",
                "instrument": got,
            }
        )
    rows.sort(key=lambda r: r["settled_at_ms"])
    return rows


def parse_bybit_instruments(raw: bytes, *, symbol: str) -> list[dict[str, Any]]:
    """Parse ``/v5/market/instruments-info`` into contract metadata rows."""
    payload = _bybit_envelope(raw)
    expected = bybit_perp_symbol(symbol)
    rows: list[dict[str, Any]] = []
    for entry in payload.get("result", {}).get("list", []) or []:
        got = str(entry.get("symbol", ""))
        if got != expected:
            raise IdentityMismatch(f"requested {expected}, instrument carries {got!r}")
        lot = entry.get("lotSizeFilter", {}) or {}
        price = entry.get("priceFilter", {}) or {}
        rows.append(
            {
                "instrument": got,
                "status": str(entry.get("status", "")),
                "contract_type": str(entry.get("contractType", "")),
                "quote_asset": str(entry.get("quoteCoin", "")),
                "settle_asset": str(entry.get("settleCoin", "")),
                "launch_time_ms": int(entry.get("launchTime", 0) or 0),
                "funding_interval_minutes": int(entry.get("fundingInterval", 0) or 0),
                "min_order_qty": str(lot.get("minOrderQty", "")),
                "qty_step": str(lot.get("qtyStep", "")),
                "tick_size": str(price.get("tickSize", "")),
            }
        )
    return rows


def parse_bybit_server_time(raw: bytes) -> int:
    """Server clock in ms from ``/v5/market/time`` (recorded in receipts)."""
    payload = _bybit_envelope(raw)
    return int(float(payload["result"]["timeNano"]) / 1e6)


# --- OKX parsers --------------------------------------------------------------


def _okx_envelope(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise VenueErrorResponse("okx response is not a JSON object")
    if str(payload.get("code", "")) != "0":
        raise VenueErrorResponse(f"okx code={payload.get('code')!r} msg={payload.get('msg')!r}")
    return payload


def parse_okx_candles(raw: bytes, *, symbol: str, kind: str) -> list[dict[str, Any]]:
    """Parse one OKX v5 candle page.

    OKX candle payloads are bare arrays that do **not** echo the ``instId``,
    so identity cannot be asserted from the body. The requested ``instId``
    therefore rides in the ingestion receipt's request parameters instead, and
    :func:`series_identity_verifiable` reports the difference honestly rather
    than pretending the body was checked.

    The trailing ``confirm`` flag is ``"1"`` for a closed bar and ``"0"``
    while it is still forming. Only closed bars are emitted: an unconfirmed
    close is a value that has not happened yet.
    """
    payload = _okx_envelope(raw)
    rows: list[dict[str, Any]] = []
    for entry in payload.get("data", []) or []:
        if str(entry[-1]) != "1":
            continue  # bar still forming — its close is not yet a fact
        row: dict[str, Any] = {
            "start_ms": int(entry[0]),
            "open": float(entry[1]),
            "high": float(entry[2]),
            "low": float(entry[3]),
            "close": float(entry[4]),
        }
        if kind in ("spot", "perp") and len(entry) >= 7:
            row["volume"] = float(entry[5])
            row["quote_volume"] = float(entry[7]) if len(entry) >= 9 else float(entry[6])
        _validate_ohlc(row, venue="okx", kind=kind)
        rows.append(row)
    rows.sort(key=lambda r: r["start_ms"])
    return rows


def parse_okx_funding(raw: bytes, *, symbol: str, **_: Any) -> list[dict[str, Any]]:
    """Parse one OKX ``/public/funding-rate-history`` page.

    ``realizedRate`` is what the venue actually settled; ``fundingRate`` is
    the value announced ahead of the settlement. The settled value wins, and
    which field supplied each row is recorded so a downstream audit can prove
    no announced rate leaked into realized P&L.
    """
    payload = _okx_envelope(raw)
    expected = okx_perp_inst_id(symbol)
    rows: list[dict[str, Any]] = []
    for entry in payload.get("data", []) or []:
        got = str(entry.get("instId", ""))
        if got != expected:
            raise IdentityMismatch(
                f"requested {expected}, funding row carries {got!r} — refusing to relabel"
            )
        realized = str(entry.get("realizedRate", "") or "").strip()
        if realized:
            rate, field = float(realized), "realizedRate"
        else:
            rate, field = float(entry["fundingRate"]), "fundingRate"
        rows.append(
            {
                "settled_at_ms": int(entry["fundingTime"]),
                "rate": rate,
                "rate_field": field,
                "instrument": got,
            }
        )
    rows.sort(key=lambda r: r["settled_at_ms"])
    return rows


def parse_okx_instruments(raw: bytes, *, symbol: str) -> list[dict[str, Any]]:
    """Parse ``/api/v5/public/instruments`` into contract metadata rows."""
    payload = _okx_envelope(raw)
    expected = okx_perp_inst_id(symbol)
    rows: list[dict[str, Any]] = []
    for entry in payload.get("data", []) or []:
        got = str(entry.get("instId", ""))
        if got != expected:
            raise IdentityMismatch(f"requested {expected}, instrument carries {got!r}")
        rows.append(
            {
                "instrument": got,
                "status": str(entry.get("state", "")),
                "contract_type": str(entry.get("ctType", "")),
                "quote_asset": str(entry.get("quoteCcy", "") or entry.get("settleCcy", "")),
                "settle_asset": str(entry.get("settleCcy", "")),
                "launch_time_ms": int(entry.get("listTime", 0) or 0),
                "contract_value": str(entry.get("ctVal", "")),
                "contract_value_asset": str(entry.get("ctValCcy", "")),
                "min_order_qty": str(entry.get("minSz", "")),
                "tick_size": str(entry.get("tickSz", "")),
                "lot_size": str(entry.get("lotSz", "")),
            }
        )
    return rows


def parse_okx_server_time(raw: bytes) -> int:
    payload = _okx_envelope(raw)
    return int(payload["data"][0]["ts"])


def _validate_ohlc(row: dict[str, Any], *, venue: str, kind: str) -> None:
    for name in ("open", "high", "low", "close"):
        value = float(row[name])
        if not value > 0:
            raise ValueError(f"{venue}:{kind} bar has non-positive {name}={value}")
    if not row["low"] <= row["high"]:
        raise ValueError(f"{venue}:{kind} bar has low > high")
    if not (row["low"] <= row["open"] <= row["high"] and row["low"] <= row["close"] <= row["high"]):
        raise ValueError(f"{venue}:{kind} bar has open/close outside [low, high]")


# --- series registry ----------------------------------------------------------


@dataclass(frozen=True)
class SeriesSpec:
    """One paginated evidence series on one venue.

    ``build_url`` produces the official URL for a page ending at ``cursor_ms``
    (both venues paginate *backwards* from a timestamp, which is what makes a
    deterministic walk to a lower bound possible). ``parse`` is pure.
    """

    venue: str
    kind: str
    endpoint: str
    page_limit: int
    timestamp_field: str  # "start_ms" for klines, "settled_at_ms" for funding
    identity_verifiable: bool
    build_url: Callable[..., str]
    parse: Callable[..., list[dict[str, Any]]]

    def native_instrument(self, symbol: str) -> str:
        if self.venue == "bybit":
            return bybit_spot_symbol(symbol) if self.kind == "spot" else bybit_perp_symbol(symbol)
        if self.kind == "spot":
            return okx_spot_inst_id(symbol)
        if self.kind == "index":
            return okx_index_inst_id(symbol)
        return okx_perp_inst_id(symbol)


def _bybit_kline_url(*, symbol: str, kind: str, cursor_ms: int, interval_minutes: int) -> str:
    category = "spot" if kind == "spot" else "linear"
    url = {
        "spot": BYBIT_KLINE_URL,
        "perp": BYBIT_KLINE_URL,
        "mark": BYBIT_MARK_KLINE_URL,
        "index": BYBIT_INDEX_KLINE_URL,
    }[kind]
    native = bybit_spot_symbol(symbol) if kind == "spot" else bybit_perp_symbol(symbol)
    return (
        f"{url}?category={category}&symbol={native}"
        f"&interval={bybit_interval(interval_minutes)}&end={cursor_ms}&limit=1000"
    )


def _bybit_funding_url(*, symbol: str, cursor_ms: int, **_: Any) -> str:
    return (
        f"{BYBIT_FUNDING_URL}?category=linear&symbol={bybit_perp_symbol(symbol)}"
        f"&endTime={cursor_ms}&limit=200"
    )


def _okx_candles_url(*, symbol: str, kind: str, cursor_ms: int, interval_minutes: int) -> str:
    url = {
        "spot": OKX_CANDLES_URL,
        "perp": OKX_CANDLES_URL,
        "mark": OKX_MARK_CANDLES_URL,
        "index": OKX_INDEX_CANDLES_URL,
    }[kind]
    if kind == "spot":
        inst = okx_spot_inst_id(symbol)
    elif kind == "index":
        inst = okx_index_inst_id(symbol)
    else:
        inst = okx_perp_inst_id(symbol)
    # OKX ``after`` returns records strictly OLDER than the given timestamp,
    # which is the backwards walk the engine performs — but "strictly" would
    # drop the bar sitting exactly on the cursor, so the cursor is nudged by
    # 1 ms to make the window inclusive of ``cursor_ms`` itself.
    return f"{url}?instId={inst}&bar={okx_bar(interval_minutes)}&after={cursor_ms + 1}&limit=100"


def _okx_funding_url(*, symbol: str, cursor_ms: int, **_: Any) -> str:
    return f"{OKX_FUNDING_URL}?instId={okx_perp_inst_id(symbol)}&after={cursor_ms + 1}&limit=100"


def _series(venue: str, kind: str) -> SeriesSpec:
    if venue == "bybit":
        if kind == "funding":
            return SeriesSpec(
                venue="bybit",
                kind="funding",
                endpoint=BYBIT_FUNDING_URL,
                page_limit=200,
                timestamp_field="settled_at_ms",
                identity_verifiable=True,
                build_url=_bybit_funding_url,
                parse=parse_bybit_funding,
            )
        return SeriesSpec(
            venue="bybit",
            kind=kind,
            endpoint={
                "spot": BYBIT_KLINE_URL,
                "perp": BYBIT_KLINE_URL,
                "mark": BYBIT_MARK_KLINE_URL,
                "index": BYBIT_INDEX_KLINE_URL,
            }[kind],
            page_limit=1000,
            timestamp_field="start_ms",
            identity_verifiable=True,
            build_url=_bybit_kline_url,
            parse=parse_bybit_kline,
        )
    if kind == "funding":
        return SeriesSpec(
            venue="okx",
            kind="funding",
            endpoint=OKX_FUNDING_URL,
            page_limit=100,
            timestamp_field="settled_at_ms",
            identity_verifiable=True,
            build_url=_okx_funding_url,
            parse=parse_okx_funding,
        )
    return SeriesSpec(
        venue="okx",
        kind=kind,
        endpoint={
            "spot": OKX_CANDLES_URL,
            "perp": OKX_CANDLES_URL,
            "mark": OKX_MARK_CANDLES_URL,
            "index": OKX_INDEX_CANDLES_URL,
        }[kind],
        page_limit=100,
        timestamp_field="start_ms",
        identity_verifiable=False,  # OKX candle bodies do not echo instId
        build_url=_okx_candles_url,
        parse=parse_okx_candles,
    )


def series_spec(venue: str, kind: str) -> SeriesSpec:
    """Look up one venue/series pair; fails closed on anything unsupported."""
    v = venue.strip().lower()
    if v not in SUPPORTED_VENUES:
        raise ValueError(f"unsupported venue {venue!r}; supported: {SUPPORTED_VENUES}")
    if kind not in SERIES_KINDS:
        raise ValueError(f"unsupported series {kind!r}; supported: {SERIES_KINDS}")
    return _series(v, kind)


def series_identity_verifiable(venue: str, kind: str) -> bool:
    return series_spec(venue, kind).identity_verifiable


def instruments_url(venue: str, symbol: str) -> str:
    if venue == "bybit":
        return f"{BYBIT_INSTRUMENTS_URL}?category=linear&symbol={bybit_perp_symbol(symbol)}"
    return f"{OKX_INSTRUMENTS_URL}?instType=SWAP&instId={okx_perp_inst_id(symbol)}"


def server_time_url(venue: str) -> str:
    return BYBIT_TIME_URL if venue == "bybit" else OKX_TIME_URL


def parse_instruments(venue: str, raw: bytes, *, symbol: str) -> list[dict[str, Any]]:
    if venue == "bybit":
        return parse_bybit_instruments(raw, symbol=symbol)
    return parse_okx_instruments(raw, symbol=symbol)


def parse_server_time(venue: str, raw: bytes) -> int:
    return parse_bybit_server_time(raw) if venue == "bybit" else parse_okx_server_time(raw)


__all__ = [
    "PARSER_VERSION",
    "SERIES_KINDS",
    "SUPPORTED_VENUES",
    "VENUE_RATE_LIMIT_RPS",
    "IdentityMismatch",
    "SeriesSpec",
    "VenueErrorResponse",
    "bybit_perp_symbol",
    "bybit_spot_symbol",
    "instruments_url",
    "okx_index_inst_id",
    "okx_perp_inst_id",
    "okx_spot_inst_id",
    "parse_bybit_funding",
    "parse_bybit_instruments",
    "parse_bybit_kline",
    "parse_instruments",
    "parse_okx_candles",
    "parse_okx_funding",
    "parse_okx_instruments",
    "parse_server_time",
    "series_identity_verifiable",
    "series_spec",
    "server_time_url",
]
