"""Domain models for conservative crypto-mining economics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")


def _non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and >= 0")


def _rate(name: str, value: float, *, allow_zero: bool = True) -> None:
    lower_ok = value >= 0 if allow_zero else value > 0
    if not math.isfinite(value) or not lower_ok or value > 1:
        boundary = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must be finite and in {boundary}")


@dataclass(frozen=True)
class MiningRig:
    """Owned hardware or an explicitly authorized cloud worker."""

    name: str
    algorithm: str
    hashrate_hs: float
    power_watts: float
    hardware_cost_usd: float = 0.0
    useful_life_days: float = 1095.0
    uptime_rate: float = 0.95
    temperature_c: float | None = None
    infrastructure_hourly_cost_usd: float = 0.0
    electricity_included: bool = False
    daily_operating_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.algorithm.strip():
            raise ValueError("rig name and algorithm must be non-empty")
        _positive("hashrate_hs", self.hashrate_hs)
        _positive("power_watts", self.power_watts)
        _non_negative("hardware_cost_usd", self.hardware_cost_usd)
        _positive("useful_life_days", self.useful_life_days)
        _rate("uptime_rate", self.uptime_rate, allow_zero=False)
        _non_negative(
            "infrastructure_hourly_cost_usd", self.infrastructure_hourly_cost_usd
        )
        _non_negative("daily_operating_cost_usd", self.daily_operating_cost_usd)
        if self.temperature_c is not None and not math.isfinite(self.temperature_c):
            raise ValueError("temperature_c must be finite when provided")


@dataclass(frozen=True)
class MiningMarketSnapshot:
    """Point-in-time market/network inputs; values must use the same hash unit."""

    coin: str
    algorithm: str
    coin_price_usd: float
    network_hashrate_hs: float
    block_reward_coin: float
    blocks_per_day: float
    pool_fee_rate: float = 0.01
    source: str = "manual"
    captured_at_utc: str = ""

    def __post_init__(self) -> None:
        if not self.coin.strip() or not self.algorithm.strip():
            raise ValueError("coin and algorithm must be non-empty")
        _positive("coin_price_usd", self.coin_price_usd)
        _positive("network_hashrate_hs", self.network_hashrate_hs)
        _positive("block_reward_coin", self.block_reward_coin)
        _positive("blocks_per_day", self.blocks_per_day)
        _rate("pool_fee_rate", self.pool_fee_rate)


@dataclass(frozen=True)
class MiningPolicy:
    """Fail-closed profitability, stress, thermal, and cloud cost policy."""

    electricity_usd_per_kwh: float
    min_daily_profit_usd: float = 1.0
    min_margin_rate: float = 0.10
    price_haircut_rate: float = 0.25
    monthly_difficulty_growth_rate: float = 0.05
    stress_horizon_days: int = 30
    max_temperature_c: float = 80.0
    require_temperature: bool = True
    max_cloud_hourly_cost_usd: float = 10.0

    def __post_init__(self) -> None:
        _non_negative("electricity_usd_per_kwh", self.electricity_usd_per_kwh)
        _non_negative("min_daily_profit_usd", self.min_daily_profit_usd)
        _rate("min_margin_rate", self.min_margin_rate)
        _rate("price_haircut_rate", self.price_haircut_rate)
        _non_negative("monthly_difficulty_growth_rate", self.monthly_difficulty_growth_rate)
        if self.stress_horizon_days <= 0:
            raise ValueError("stress_horizon_days must be > 0")
        _positive("max_temperature_c", self.max_temperature_c)
        _non_negative("max_cloud_hourly_cost_usd", self.max_cloud_hourly_cost_usd)


@dataclass(frozen=True)
class MiningEvaluation:
    rig: str
    coin: str
    decision: str
    reasons: tuple[str, ...]
    expected_coin_per_day: float
    gross_revenue_usd: float
    pool_fee_usd: float
    electricity_cost_usd: float
    infrastructure_cost_usd: float
    operating_cost_usd: float
    depreciation_usd: float
    net_profit_usd: float
    stressed_net_profit_usd: float
    net_margin_rate: float
    break_even_electricity_usd_per_kwh: float | None
    annualized_hardware_roi_rate: float | None
    payback_days: float | None
    authorized_to_start_miner: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

