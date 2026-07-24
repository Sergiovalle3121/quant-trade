"""Rental economics: cancelable hourly flows, never owned-hardware NPV.

A Spot/preemptible instance is not an ASIC on a shelf: it can be interrupted,
it bills by the hour, and walking away costs nothing beyond the hours used. So
the unit of account is the USEFUL compute hour — revenue per useful hour vs
all-in rented cost per useful hour — over a short, cancelable horizon bounded
by an explicit budget ceiling. There is deliberately no multi-year NPV here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from quant_trade.cloud_rental.models import BenchmarkEvidence, ComputeQuote

MAX_RENTAL_HORIZON_HOURS = 24.0 * 92  # ~one quarter; rental flows are cancelable


def _rate(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class RevenueAssumptions:
    """Point-in-time revenue inputs (policy inputs, not forecasts)."""

    hashprice_usd_per_th_day: float
    pool_fee_rate: float = 0.01
    utilization: float = 0.95
    interruption_rate_per_hour: float = 0.0  # spot/preemptible reclaim frequency
    checkpoint_overhead_fraction: float = 0.05  # useful time lost per interruption cycle

    def __post_init__(self) -> None:
        if self.hashprice_usd_per_th_day < 0:
            raise ValueError("hashprice must be >= 0")
        _rate("pool_fee_rate", self.pool_fee_rate)
        _rate("utilization", self.utilization)
        _rate("interruption_rate_per_hour", self.interruption_rate_per_hour)
        _rate("checkpoint_overhead_fraction", self.checkpoint_overhead_fraction)


@dataclass
class RentalEconomics:
    provider: str
    sku: str
    purchase_model: str
    horizon_hours: float
    budget_ceiling_usd: float
    hashrate_th: float
    useful_hour_fraction: float
    revenue_per_useful_hour_usd: float
    all_in_cost_per_hour_usd: float
    margin_per_hour_usd: float
    margin_per_hour_2x_costs_usd: float
    margin_per_hour_3x_costs_usd: float
    break_even_hourly_price_usd: float
    horizon_net_usd: float
    horizon_cost_usd: float
    within_budget: bool
    economically_positive: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_rental_economics(
    quote: ComputeQuote,
    benchmark: BenchmarkEvidence,
    revenue: RevenueAssumptions,
    *,
    horizon_hours: float = 24.0 * 30,
    budget_ceiling_usd: float = 1000.0,
) -> RentalEconomics:
    """Hourly margin of renting this SKU to hash, from measured evidence only."""
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be > 0")
    if horizon_hours > MAX_RENTAL_HORIZON_HOURS:
        raise ValueError(
            f"horizon_hours {horizon_hours:.0f} exceeds the cancelable-rental cap "
            f"{MAX_RENTAL_HORIZON_HOURS:.0f}; do not project rented capacity like "
            "owned hardware"
        )
    if budget_ceiling_usd <= 0:
        raise ValueError("budget_ceiling_usd must be > 0")

    hashrate_th = benchmark.hashrate_hs / 1e12
    interruption_loss = min(
        1.0, revenue.interruption_rate_per_hour * revenue.checkpoint_overhead_fraction
    )
    useful_fraction = revenue.utilization * (1.0 - interruption_loss)
    gross_per_useful_hour = hashrate_th * revenue.hashprice_usd_per_th_day / 24.0
    net_revenue_per_hour = (
        gross_per_useful_hour
        * useful_fraction
        * (1.0 - revenue.pool_fee_rate)
        * (1.0 - benchmark.reject_rate)
    )

    base_price_usd = quote.price_per_hour * quote.fx_rate_to_usd * (1.0 + quote.vat_rate)
    all_in_cost = base_price_usd + quote.all_extras_per_hour_usd

    margin_1x = net_revenue_per_hour - all_in_cost
    margin_2x = net_revenue_per_hour - 2.0 * all_in_cost
    margin_3x = net_revenue_per_hour - 3.0 * all_in_cost
    horizon_cost = all_in_cost * horizon_hours
    horizon_net = margin_1x * horizon_hours
    notes: list[str] = []
    if quote.purchase_model.value in ("spot", "preemptible"):
        notes.append(
            "spot/preemptible capacity can be reclaimed at any time; interruption "
            "loss is modeled, availability is not guaranteed"
        )
    notes.append("rental flows are cancelable; no multi-year NPV applies")

    return RentalEconomics(
        provider=str(quote.provider),
        sku=quote.sku,
        purchase_model=str(quote.purchase_model),
        horizon_hours=horizon_hours,
        budget_ceiling_usd=budget_ceiling_usd,
        hashrate_th=hashrate_th,
        useful_hour_fraction=useful_fraction,
        revenue_per_useful_hour_usd=net_revenue_per_hour,
        all_in_cost_per_hour_usd=all_in_cost,
        margin_per_hour_usd=margin_1x,
        margin_per_hour_2x_costs_usd=margin_2x,
        margin_per_hour_3x_costs_usd=margin_3x,
        break_even_hourly_price_usd=net_revenue_per_hour,
        horizon_net_usd=horizon_net,
        horizon_cost_usd=horizon_cost,
        within_budget=horizon_cost <= budget_ceiling_usd,
        economically_positive=margin_1x > 0 and margin_2x > 0,
        notes=notes,
    )
