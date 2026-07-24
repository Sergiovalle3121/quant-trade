"""Read-only mining market snapshots with two independent revenue methods.

A snapshot is a point-in-time, attributable observation of network conditions.
Revenue can be derived two ways that should agree:

- **direct hashprice** — a published USD/TH/day quote from a data provider.
- **bottom-up** — rebuilt from block subsidy + transaction-fee revenue, blocks
  per day, network hashrate, and coin price.

When the two diverge by more than a threshold, that is a data-quality alert, not
a silent averaging. Snapshots fail closed when stale. Nothing here connects to a
pool, a miner, or a wallet; live access (if ever added) sits behind an adapter
with a timeout, bounded retries, and attribution, and fixtures carry no keys.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

_SECONDS_PER_TH = 1e12


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")


def _non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and >= 0")


@dataclass(frozen=True)
class MiningMarketData:
    """Attributable network snapshot; hash units are H/s throughout."""

    coin: str
    algorithm: str
    coin_price_usd: float
    network_hashrate_hs: float
    difficulty: float
    block_subsidy_coin: float
    tx_fee_revenue_coin_per_block: float
    blocks_per_day: float
    captured_at_utc: str
    source_name: str
    source_url: str = ""
    pool_fee_rate: float = 0.0
    direct_hashprice_usd_per_th_day: float | None = None
    max_age_seconds: float = 3600.0
    staleness_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.coin.strip() or not self.algorithm.strip():
            raise ValueError("coin and algorithm must be non-empty")
        if not self.source_name.strip():
            raise ValueError("source_name is required for attribution")
        _positive("coin_price_usd", self.coin_price_usd)
        _positive("network_hashrate_hs", self.network_hashrate_hs)
        _positive("difficulty", self.difficulty)
        _positive("block_subsidy_coin", self.block_subsidy_coin)
        _non_negative("tx_fee_revenue_coin_per_block", self.tx_fee_revenue_coin_per_block)
        _positive("blocks_per_day", self.blocks_per_day)
        _non_negative("staleness_seconds", self.staleness_seconds)
        _positive("max_age_seconds", self.max_age_seconds)
        if not 0 <= self.pool_fee_rate <= 1:
            raise ValueError("pool_fee_rate must be in [0, 1]")
        if self.direct_hashprice_usd_per_th_day is not None:
            _non_negative("direct_hashprice_usd_per_th_day", self.direct_hashprice_usd_per_th_day)

    @property
    def is_stale(self) -> bool:
        return self.staleness_seconds > self.max_age_seconds

    @property
    def network_hashrate_th(self) -> float:
        return self.network_hashrate_hs / _SECONDS_PER_TH

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bottom_up_hashprice(data: MiningMarketData) -> float:
    """USD per TH/day rebuilt from subsidy + tx fees + difficulty/hashrate."""
    coin_per_block = data.block_subsidy_coin + data.tx_fee_revenue_coin_per_block
    coin_per_th_day = coin_per_block * data.blocks_per_day / data.network_hashrate_th
    return coin_per_th_day * data.coin_price_usd


def direct_hashprice(data: MiningMarketData) -> float | None:
    """The provider's published USD/TH/day, if any."""
    return data.direct_hashprice_usd_per_th_day


@dataclass(frozen=True)
class HashpriceComparison:
    bottom_up_usd_per_th_day: float
    direct_usd_per_th_day: float | None
    relative_divergence: float | None
    diverges: bool
    alert: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_hashprice(
    data: MiningMarketData, *, max_relative_divergence: float = 0.10
) -> HashpriceComparison:
    """Compare the two revenue methods; flag divergence instead of averaging."""
    bottom = bottom_up_hashprice(data)
    direct = direct_hashprice(data)
    if direct is None:
        return HashpriceComparison(bottom, None, None, False, None)
    denom = max(abs(bottom), 1e-12)
    divergence = abs(direct - bottom) / denom
    diverges = divergence > max_relative_divergence
    alert = (
        f"hashprice methods diverge {divergence:.1%} (> {max_relative_divergence:.0%}): "
        f"direct={direct:.4f} vs bottom-up={bottom:.4f} USD/TH/day"
        if diverges
        else None
    )
    return HashpriceComparison(bottom, direct, divergence, diverges, alert)


# --- read-only data access ------------------------------------------------

REQUIRED_FIELDS = (
    "coin",
    "algorithm",
    "coin_price_usd",
    "network_hashrate_hs",
    "difficulty",
    "block_subsidy_coin",
    "tx_fee_revenue_coin_per_block",
    "blocks_per_day",
    "captured_at_utc",
    "source_name",
)


class MiningMarketAdapter(Protocol):
    """Read-only market-data source. Implementations MUST NOT control hardware."""

    def fetch(self, coin: str) -> MiningMarketData:
        ...


def validate_market_record(record: dict[str, Any]) -> list[str]:
    errors = [f"missing required field: {f}" for f in REQUIRED_FIELDS if f not in record]
    if "source_name" in record and not str(record["source_name"]).strip():
        errors.append("source_name must be non-empty for attribution")
    return errors


def load_market_from_record(record: dict[str, Any]) -> MiningMarketData:
    problems = validate_market_record(record)
    if problems:
        raise ValueError("invalid market record: " + "; ".join(problems))
    known = {f for f in MiningMarketData.__dataclass_fields__}
    return MiningMarketData(**{k: v for k, v in record.items() if k in known})


def load_market_from_json(path: str | Path) -> MiningMarketData:
    return load_market_from_record(json.loads(Path(path).read_text(encoding="utf-8")))


def require_fresh(data: MiningMarketData) -> MiningMarketData:
    """Fail closed on a stale snapshot before it feeds any economic decision."""
    if data.is_stale:
        raise ValueError(
            f"market snapshot from {data.source_name} is stale "
            f"({data.staleness_seconds:.0f}s > {data.max_age_seconds:.0f}s)"
        )
    return data


class FakeMiningMarketAdapter:
    """Deterministic offline adapter for tests; returns a fixed snapshot."""

    def __init__(self, data: MiningMarketData) -> None:
        self._data = data

    def fetch(self, coin: str) -> MiningMarketData:
        if coin.casefold() != self._data.coin.casefold():
            raise ValueError(f"no snapshot for {coin!r}")
        return self._data


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
