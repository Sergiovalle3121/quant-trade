"""Domain models for research-only cash-and-carry / funding economics.

Nothing here places an order or touches a live venue. A cash-and-carry position
is two legs — **long spot** and **short perpetual** of the same underlying — held
delta-neutral to harvest funding (and, for dated futures, basis convergence).

Causality rule baked into the schema: the funding a strategy can *act on* at
time ``t`` is the last **realized** funding published at or before ``t``. A
separate ``predicted_funding_rate`` field exists for models that forecast, but it
is never populated from future realized funding, and the two are never merged.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and >= 0")


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")


@dataclass(frozen=True)
class CarrySnapshot:
    """A point-in-time, causal observation of one spot/perp pair on one venue.

    ``realized_funding_rate`` is the most recent *published* funding rate known
    at ``captured_at_utc`` (per funding interval, e.g. per 8h). It is the only
    funding a signal may use at ``t``. ``predicted_funding_rate`` is an optional,
    clearly separated forecast and must never be sourced from future realized
    funding.
    """

    symbol: str
    exchange: str
    captured_at_utc: str
    spot_price: float
    perp_mark_price: float
    perp_index_price: float
    realized_funding_rate: float  # per funding interval, known at capture time
    funding_interval_hours: float = 8.0
    predicted_funding_rate: float | None = None
    contract_multiplier: float = 1.0
    maintenance_margin_rate: float = 0.005
    taker_fee_bps: float = 5.0
    borrow_available: bool = True
    borrow_rate_annual: float = 0.0
    data_source: str = "synthetic"  # "synthetic" | "real"
    staleness_seconds: float = 0.0
    source_name: str = "fixture"

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.exchange.strip():
            raise ValueError("symbol and exchange must be non-empty")
        _positive("spot_price", self.spot_price)
        _positive("perp_mark_price", self.perp_mark_price)
        _positive("perp_index_price", self.perp_index_price)
        _finite("realized_funding_rate", self.realized_funding_rate)
        _positive("funding_interval_hours", self.funding_interval_hours)
        if self.predicted_funding_rate is not None:
            _finite("predicted_funding_rate", self.predicted_funding_rate)
        _positive("contract_multiplier", self.contract_multiplier)
        if not 0 <= self.maintenance_margin_rate < 1:
            raise ValueError("maintenance_margin_rate must be in [0, 1)")
        _non_negative("taker_fee_bps", self.taker_fee_bps)
        _finite("borrow_rate_annual", self.borrow_rate_annual)
        _non_negative("staleness_seconds", self.staleness_seconds)
        if self.data_source not in ("synthetic", "real"):
            raise ValueError("data_source must be 'synthetic' or 'real'")

    @property
    def funding_intervals_per_year(self) -> float:
        return 24.0 / self.funding_interval_hours * 365.0

    @property
    def basis(self) -> float:
        """Perp mark minus spot, as a fraction of spot (signed)."""
        return (self.perp_mark_price - self.spot_price) / self.spot_price

    @property
    def annualized_realized_funding(self) -> float:
        """Realized funding annualized — long-spot/short-perp receives this when
        funding is positive."""
        return self.realized_funding_rate * self.funding_intervals_per_year

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CarryCostModel:
    """All costs, in the units noted. Nothing is assumed to be free."""

    # per-fill frictions (basis points of notional), charged on each of the four
    # fills of a round trip: enter spot, enter perp, exit spot, exit perp.
    half_spread_bps: float = 2.0
    slippage_bps: float = 1.0
    market_impact_bps: float = 1.0
    # annual carrying-cost rates (fraction of notional per year)
    spot_custody_cost_annual: float = 0.0
    perp_margin_cost_annual: float = 0.0
    # one-time frictions amortized over the holding period (fraction of notional)
    conversion_withdrawal_cost: float = 0.0

    def __post_init__(self) -> None:
        for name in ("half_spread_bps", "slippage_bps", "market_impact_bps"):
            _non_negative(name, getattr(self, name))
        for name in (
            "spot_custody_cost_annual",
            "perp_margin_cost_annual",
            "conversion_withdrawal_cost",
        ):
            _non_negative(name, getattr(self, name))


@dataclass(frozen=True)
class CarryPosition:
    """The intended two-leg position."""

    notional_usd: float
    holding_days: float
    perp_leverage: float = 1.0
    daily_volatility: float = 0.02  # of the underlying, for the liquidation proxy

    def __post_init__(self) -> None:
        _positive("notional_usd", self.notional_usd)
        _positive("holding_days", self.holding_days)
        _positive("perp_leverage", self.perp_leverage)
        _non_negative("daily_volatility", self.daily_volatility)


@dataclass(frozen=True)
class CarryPolicy:
    """Fail-closed risk gates for a research decision (no live trading)."""

    min_net_annual_carry: float = 0.05
    min_carry_after_2x_costs: float = 0.02
    min_carry_after_3x_costs: float = 0.0
    max_abs_basis: float = 0.02
    max_liquidation_probability: float = 0.01
    min_liquidation_distance: float = 0.10
    max_exchange_exposure_fraction: float = 0.5
    max_unhedged_notional_fraction: float = 0.05
    max_staleness_seconds: float = 120.0
    funding_reversion_haircut: float = 0.5  # discount applied to expected funding
    min_fill_rate: float = 0.9

    def __post_init__(self) -> None:
        _finite("min_net_annual_carry", self.min_net_annual_carry)
        if not 0 <= self.funding_reversion_haircut <= 1:
            raise ValueError("funding_reversion_haircut must be in [0, 1]")
        if self.max_abs_basis < 0:
            raise ValueError("max_abs_basis must be >= 0")
        if not 0 <= self.min_fill_rate <= 1:
            raise ValueError("min_fill_rate must be in [0, 1]")


@dataclass(frozen=True)
class CarryEvaluation:
    """Result of evaluating one snapshot/position under a policy."""

    symbol: str
    exchange: str
    decision: str  # "GO" | "NO-GO"
    reasons: tuple[str, ...]
    data_source: str
    gross_annual_carry: float
    expected_annual_carry: float  # after reversion haircut
    annual_transaction_cost: float
    annual_carry_cost: float
    net_annual_carry: float
    net_annual_carry_2x_costs: float
    net_annual_carry_3x_costs: float
    basis: float
    liquidation_distance: float
    liquidation_probability_proxy: float
    break_even_holding_days: float | None
    break_even_funding_rate: float | None
    delta_after_hedge: float
    field_notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
