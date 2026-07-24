"""Point-in-time funding collector: one safe capture per invocation.

The collector reads public market state for configured venue/symbol pairs and
appends observations to the JSONL store. It is strictly read-only: adapters
expose a single ``observe`` verb, carry no API keys, and define no
create/cancel/order methods (a test asserts this). There is no daemon here —
scheduling repeated captures is the operator's choice (cron, systemd timer),
and tests only ever run single iterations against canned fixtures.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from quant_trade.carry.store import AppendResult, FundingObservation, append_observations
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text


class FundingObservationAdapter(Protocol):
    """Read-only observation source. MUST NOT expose any trading verbs."""

    def observe(self, venue: str, symbol: str) -> FundingObservation:
        ...


@dataclass(frozen=True)
class CollectorConfig:
    pairs: tuple[tuple[str, str], ...]  # (venue, symbol)
    output_path: str
    adapter: str = "fake"  # "fake" | "ccxt"
    fixture_path: str | None = None
    timeout_seconds: float = 10.0
    max_retries: int = 2
    user_agent: str = "quant-trade-carry-collector/1.0 (read-only research)"

    def __post_init__(self) -> None:
        if not self.pairs:
            raise ValueError("collector needs at least one (venue, symbol) pair")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")


def load_collector_config(path: str | Path) -> CollectorConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    pairs = tuple(
        (str(p["venue"]), str(p["symbol"])) for p in payload.get("pairs", [])
    )
    return CollectorConfig(
        pairs=pairs,
        output_path=str(payload.get("output_path", "data/carry/funding_history.jsonl")),
        adapter=str(payload.get("adapter", "fake")),
        fixture_path=payload.get("fixture_path"),
        timeout_seconds=float(payload.get("timeout_seconds", 10.0)),
        max_retries=int(payload.get("max_retries", 2)),
    )


@dataclass
class CollectionSummary:
    captured: int
    appended: int
    deduplicated: int
    errors: list[str] = field(default_factory=list)
    output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FixtureFundingAdapter:
    """Offline adapter serving canned observations from a JSON fixture.

    Fixture format: {"observations": [{...FundingObservation fields...}, ...]}.
    Used by tests and dry runs; involves no network.
    """

    def __init__(self, fixture_path: str | Path) -> None:
        from quant_trade.evidence.canonical_json import load_json

        payload = load_json(fixture_path)
        records = payload["observations"] if isinstance(payload, dict) else payload
        self._by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            self._by_pair[(str(record["venue"]), str(record["symbol"]))] = record

    def observe(self, venue: str, symbol: str) -> FundingObservation:
        record = self._by_pair.get((venue, symbol))
        if record is None:
            raise ValueError(f"fixture has no observation for {venue}:{symbol}")
        known = {f for f in FundingObservation.__dataclass_fields__}
        return FundingObservation(**{k: v for k, v in record.items() if k in known})


class CcxtFundingAdapter:
    """Public-endpoint ccxt observation adapter (lazy import; never trades).

    Reads spot ticker, perp ticker, and the funding rate; preserves the raw
    responses' hash for lineage. No API keys are read or required, and no
    order/cancel/withdraw method exists on this class.
    """

    def __init__(self, timeout_seconds: float, user_agent: str) -> None:
        self._timeout_ms = int(timeout_seconds * 1000)
        self._user_agent = user_agent

    def observe(self, venue: str, symbol: str) -> FundingObservation:
        import ccxt  # lazy: requires the `crypto` extra

        client = getattr(ccxt, venue)(
            {"enableRateLimit": True, "timeout": self._timeout_ms}
        )
        client.userAgent = self._user_agent
        spot_symbol = f"{symbol}/USDT"
        perp_symbol = f"{symbol}/USDT:USDT"
        spot = client.fetch_ticker(spot_symbol)
        perp = client.fetch_ticker(perp_symbol)
        funding = client.fetch_funding_rate(perp_symbol)
        raw_sha = sha256_of_text(
            canonical_dumps({"spot": spot, "perp": perp, "funding": funding})
        )
        captured = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        exchange_ms = funding.get("timestamp") or perp.get("timestamp")
        exchange_ts = (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exchange_ms / 1000.0))
            if exchange_ms
            else captured
        )
        return FundingObservation(
            venue=venue,
            symbol=symbol,
            captured_at_utc=captured,
            exchange_timestamp_utc=exchange_ts,
            spot_bid=float(spot.get("bid") or spot["last"]),
            spot_ask=float(spot.get("ask") or spot["last"]),
            perp_bid=float(perp.get("bid") or perp["last"]),
            perp_ask=float(perp.get("ask") or perp["last"]),
            perp_mark=float(perp["last"]),
            perp_index=float(funding.get("indexPrice") or spot["last"]),
            realized_funding_rate=float(funding["fundingRate"]),
            next_funding_time_utc=str(funding.get("fundingDatetime") or "") or None,
            predicted_funding_rate=None,
            open_interest=None,
            source_event="poll",
            source_name=f"ccxt:{venue}",
            raw_sha256=raw_sha,
        )


def build_adapter(config: CollectorConfig) -> FundingObservationAdapter:
    if config.adapter == "fake":
        if not config.fixture_path:
            raise ValueError("fake adapter requires fixture_path")
        return FixtureFundingAdapter(config.fixture_path)
    if config.adapter == "ccxt":
        return CcxtFundingAdapter(config.timeout_seconds, config.user_agent)
    raise ValueError(f"unknown adapter {config.adapter!r}; use 'fake' or 'ccxt'")


def collect_once(
    config: CollectorConfig, adapter: FundingObservationAdapter | None = None
) -> CollectionSummary:
    """One capture pass over the configured pairs. Never loops, never trades."""
    active = adapter if adapter is not None else build_adapter(config)
    observations: list[FundingObservation] = []
    errors: list[str] = []
    for venue, symbol in config.pairs:
        last_error: str | None = None
        for _attempt in range(config.max_retries + 1):
            try:
                observations.append(active.observe(venue, symbol))
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - bounded retry, then recorded
                last_error = f"{venue}:{symbol}: {exc}"
        if last_error is not None:
            errors.append(last_error)
    result: AppendResult = append_observations(config.output_path, observations)
    return CollectionSummary(
        captured=len(observations),
        appended=result.appended,
        deduplicated=result.deduplicated,
        errors=errors,
        output_path=result.path,
    )
