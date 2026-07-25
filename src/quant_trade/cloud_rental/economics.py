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
from math import ceil
from typing import Any

from quant_trade.cloud_rental.market import algorithm_unit, native_hashrate_units
from quant_trade.cloud_rental.models import BenchmarkEvidence, ComputeQuote, RentalType

MAX_RENTAL_HORIZON_HOURS = 24.0 * 92  # ~one quarter; rental flows are cancelable


def _rate(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class RevenueAssumptions:
    """Point-in-time revenue and availability inputs.

    ``hashprice_usd_per_th_day`` remains as a V6 compatibility alias. The
    value is interpreted in the benchmark algorithm's registered native unit;
    new callers should use ``hashprice_usd_per_unit_day``.
    """

    hashprice_usd_per_th_day: float | None = None
    hashprice_usd_per_unit_day: float | None = None
    pool_fee_rate: float = 0.01
    utilization: float = 0.95
    interruption_rate_per_hour: float = 0.0  # spot/preemptible reclaim frequency
    checkpoint_overhead_fraction: float = 0.05  # useful time lost per interruption cycle
    availability_rate: float = 1.0
    boot_seconds: float = 0.0
    restart_seconds: float = 0.0
    revenue_scenario_multipliers: tuple[float, ...] = (
        0.70,
        0.85,
        1.00,
        1.10,
        1.20,
    )

    def __post_init__(self) -> None:
        values = [
            value
            for value in (
                self.hashprice_usd_per_th_day,
                self.hashprice_usd_per_unit_day,
            )
            if value is not None
        ]
        if len(values) != 1:
            raise ValueError("provide exactly one hashprice field")
        if not math.isfinite(values[0]) or values[0] < 0:
            raise ValueError("hashprice must be >= 0")
        _rate("pool_fee_rate", self.pool_fee_rate)
        _rate("utilization", self.utilization)
        _rate("interruption_rate_per_hour", self.interruption_rate_per_hour)
        _rate("checkpoint_overhead_fraction", self.checkpoint_overhead_fraction)
        _rate("availability_rate", self.availability_rate)
        for name in ("boot_seconds", "restart_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and >= 0")
        if not self.revenue_scenario_multipliers:
            raise ValueError("revenue_scenario_multipliers must not be empty")
        if any(
            not math.isfinite(value) or value < 0 for value in self.revenue_scenario_multipliers
        ):
            raise ValueError("revenue scenario multipliers must be finite and >= 0")

    @property
    def hashprice_per_native_unit_day(self) -> float:
        if self.hashprice_usd_per_unit_day is not None:
            return self.hashprice_usd_per_unit_day
        assert self.hashprice_usd_per_th_day is not None
        return self.hashprice_usd_per_th_day


@dataclass
class RentalEconomics:
    rental_type: str
    provider: str
    sku: str
    purchase_model: str
    horizon_hours: float
    budget_ceiling_usd: float
    algorithm_id: str
    native_hashrate_unit: str
    native_hashrate_units: float
    hashrate_th: float | None
    useful_hour_fraction: float
    useful_hours: float
    billed_hours: float
    revenue_per_useful_hour_usd: float
    all_in_cost_per_hour_usd: float
    margin_per_hour_usd: float
    margin_per_hour_2x_costs_usd: float
    margin_per_hour_3x_costs_usd: float
    break_even_hourly_price_usd: float
    break_even_rental_rate_usd_per_hour: float
    horizon_net_usd: float
    net_profit_usd: float
    horizon_cost_usd: float
    return_on_committed_capital: float | None
    p05_net_profit_usd: float
    p50_net_profit_usd: float
    p95_net_profit_usd: float
    probability_of_loss: float
    cvar95_loss_usd: float
    confidence_lower_bound_usd: float
    shutdown_threshold_hashprice_usd_per_unit_day: float | None
    within_budget: bool
    economically_positive: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


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
    if quote.rental_type is not RentalType.COMPUTE_RENTAL:
        raise ValueError(
            "compute_rental_economics only accepts COMPUTE_RENTAL; "
            "marketplace and managed-lease economics require separate engines"
        )

    unit = algorithm_unit(benchmark.algorithm)
    native_units = float(native_hashrate_units(benchmark.algorithm, benchmark.hashrate_hs))
    hashprice = revenue.hashprice_per_native_unit_day
    requested_seconds = horizon_hours * 3600.0
    billable_seconds = max(requested_seconds, float(quote.minimum_billing_seconds))
    billable_seconds = (
        ceil(billable_seconds / quote.billing_granularity_seconds)
        * quote.billing_granularity_seconds
    )
    billed_hours = billable_seconds / 3600.0

    expected_interruptions = horizon_hours * revenue.interruption_rate_per_hour
    downtime_hours = (
        revenue.boot_seconds + expected_interruptions * revenue.restart_seconds
    ) / 3600.0
    interruption_loss = min(
        1.0, revenue.interruption_rate_per_hour * revenue.checkpoint_overhead_fraction
    )
    useful_hours = (
        max(0.0, horizon_hours - downtime_hours)
        * revenue.availability_rate
        * revenue.utilization
        * (1.0 - interruption_loss)
    )
    useful_fraction = useful_hours / horizon_hours
    gross_per_hashing_hour = native_units * hashprice / 24.0
    net_revenue_total = (
        gross_per_hashing_hour
        * useful_hours
        * (1.0 - revenue.pool_fee_rate)
        * (1.0 - benchmark.reject_rate)
    )
    net_revenue_per_hour = net_revenue_total / horizon_hours

    base_price_usd = quote.price_per_hour * quote.fx_rate_to_usd * (1.0 + quote.vat_rate)
    all_in_cost = base_price_usd + quote.all_extras_per_hour_usd

    horizon_cost = all_in_cost * billed_hours
    horizon_net = net_revenue_total - horizon_cost
    horizon_net_2x = net_revenue_total - 2.0 * horizon_cost
    horizon_net_3x = net_revenue_total - 3.0 * horizon_cost
    margin_1x = horizon_net / horizon_hours
    margin_2x = horizon_net_2x / horizon_hours
    margin_3x = horizon_net_3x / horizon_hours
    scenario_profits = [
        net_revenue_total * multiplier - horizon_cost
        for multiplier in revenue.revenue_scenario_multipliers
    ]
    p05 = _percentile(scenario_profits, 0.05)
    p50 = _percentile(scenario_profits, 0.50)
    p95 = _percentile(scenario_profits, 0.95)
    probability_of_loss = sum(value < 0 for value in scenario_profits) / len(scenario_profits)
    tail_count = max(1, ceil(len(scenario_profits) * 0.05))
    worst_tail = sorted(scenario_profits)[:tail_count]
    cvar95_loss = max(0.0, -sum(worst_tail) / len(worst_tail))
    break_even_rental_rate = max(
        0.0,
        (net_revenue_total / billed_hours - quote.all_extras_per_hour_usd)
        / (quote.fx_rate_to_usd * (1.0 + quote.vat_rate)),
    )
    revenue_per_hashprice = (
        native_units
        / 24.0
        * useful_hours
        * (1.0 - revenue.pool_fee_rate)
        * (1.0 - benchmark.reject_rate)
    )
    shutdown_threshold = horizon_cost / revenue_per_hashprice if revenue_per_hashprice > 0 else None
    notes: list[str] = []
    if quote.purchase_model.value in ("spot", "preemptible"):
        notes.append(
            "spot/preemptible capacity can be reclaimed at any time; interruption "
            "loss is modeled, availability is not guaranteed"
        )
    notes.append("rental flows are cancelable; no multi-year NPV applies")
    notes.append(
        f"billing applies a {quote.minimum_billing_seconds}s minimum and "
        f"{quote.billing_granularity_seconds}s granularity"
    )

    return RentalEconomics(
        rental_type=str(quote.rental_type),
        provider=str(quote.provider),
        sku=quote.sku,
        purchase_model=str(quote.purchase_model),
        horizon_hours=horizon_hours,
        budget_ceiling_usd=budget_ceiling_usd,
        algorithm_id=benchmark.algorithm,
        native_hashrate_unit=str(unit["native_unit"]),
        native_hashrate_units=native_units,
        hashrate_th=native_units if benchmark.algorithm.casefold() == "sha256" else None,
        useful_hour_fraction=useful_fraction,
        useful_hours=useful_hours,
        billed_hours=billed_hours,
        revenue_per_useful_hour_usd=net_revenue_per_hour,
        all_in_cost_per_hour_usd=all_in_cost,
        margin_per_hour_usd=margin_1x,
        margin_per_hour_2x_costs_usd=margin_2x,
        margin_per_hour_3x_costs_usd=margin_3x,
        break_even_hourly_price_usd=break_even_rental_rate,
        break_even_rental_rate_usd_per_hour=break_even_rental_rate,
        horizon_net_usd=horizon_net,
        net_profit_usd=horizon_net,
        horizon_cost_usd=horizon_cost,
        return_on_committed_capital=(horizon_net / horizon_cost if horizon_cost > 0 else None),
        p05_net_profit_usd=p05,
        p50_net_profit_usd=p50,
        p95_net_profit_usd=p95,
        probability_of_loss=probability_of_loss,
        cvar95_loss_usd=cvar95_loss,
        confidence_lower_bound_usd=p05,
        shutdown_threshold_hashprice_usd_per_unit_day=shutdown_threshold,
        within_budget=horizon_cost <= budget_ceiling_usd,
        economically_positive=margin_1x > 0 and margin_2x > 0 and p05 > 0,
        notes=notes,
    )
