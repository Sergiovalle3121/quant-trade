"""Dynamic, per-period mining cash-flow projection.

The V1 NPV discounted a single *constant* daily cash flow over the whole horizon
even though the policy carried a non-zero difficulty growth rate — a 3-year NPV
was therefore materially overstated. This module projects each day explicitly:
difficulty grows, subsidy halves on schedule, price drifts (or is stressed),
uptime and hashrate degrade, energy inflates, and repair/replacement CAPEX lands
on its day. NPV/IRR/payback are computed over that *varying* series.

Nothing here mines a hash or controls hardware.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.mining.market import MiningMarketData
from quant_trade.mining.models import MiningRig

_DAYS_PER_MONTH = 30.0
_DAYS_PER_YEAR = 365.0


def _rate(name: str, value: float) -> None:
    if not math.isfinite(value) or value < -1:
        raise ValueError(f"{name} must be finite and > -1")


@dataclass(frozen=True)
class ProjectionAssumptions:
    """Time-varying drivers for a mining cash-flow projection."""

    horizon_days: int = 1095
    annual_discount_rate: float = 0.12
    monthly_difficulty_growth_rate: float = 0.02
    halving_day_indices: tuple[int, ...] = ()
    annual_price_drift: float = 0.0
    price_multiplier: float = 1.0
    tx_fee_multiplier: float = 1.0
    annual_uptime_degradation: float = 0.0
    annual_hashrate_degradation: float = 0.0
    annual_energy_inflation: float = 0.0
    electricity_usd_per_kwh: float = 0.06
    tax_rate: float = 0.0
    pool_fee_rate: float | None = None  # override the market's pool fee if set
    capex_events: tuple[tuple[int, float], ...] = ()  # (day_index, usd)
    residual_value_usd: float | None = None

    def __post_init__(self) -> None:
        if self.horizon_days <= 0:
            raise ValueError("horizon_days must be > 0")
        _rate("monthly_difficulty_growth_rate", self.monthly_difficulty_growth_rate)
        _rate("annual_price_drift", self.annual_price_drift)
        for name in (
            "annual_uptime_degradation",
            "annual_hashrate_degradation",
            "annual_energy_inflation",
        ):
            _rate(name, getattr(self, name))
        if not 0 <= self.tax_rate <= 1:
            raise ValueError("tax_rate must be in [0, 1]")
        if self.electricity_usd_per_kwh < 0:
            raise ValueError("electricity_usd_per_kwh must be >= 0")
        for day, _amount in self.capex_events:
            if day < 0 or day >= self.horizon_days:
                raise ValueError("capex_events must fall within the horizon")


@dataclass
class MiningProjection:
    horizon_days: int
    initial_capex_usd: float
    total_coin_mined: float
    total_revenue_usd: float
    total_cost_usd: float
    cash_profit_usd: float
    accounting_profit_usd: float
    npv_usd: float
    irr_annual_rate: float | None
    discounted_payback_days: int | None
    production_cost_usd_per_coin: float | None
    break_even_electricity_usd_per_kwh: float | None
    break_even_coin_price_usd: float | None
    monthly_series: list[dict[str, float]]
    constant_flow_npv_usd: float
    npv_overstatement_vs_constant: float
    daily_series: list[dict[str, float]] = field(default_factory=list)

    def to_dict(self, include_daily: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if not include_daily:
            d.pop("daily_series", None)
        return d


def _daily_from_annual(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / _DAYS_PER_YEAR) - 1.0


def _daily_from_monthly(monthly_rate: float) -> float:
    return (1.0 + monthly_rate) ** (1.0 / _DAYS_PER_MONTH) - 1.0


def _npv_of(cashflows: list[float], daily_rate: float, initial_capex: float,
            residual: float, horizon: int) -> float:
    value = -initial_capex + residual / (1.0 + daily_rate) ** horizon
    for day, cf in enumerate(cashflows):
        value += cf / (1.0 + daily_rate) ** (day + 1)
    return value


def _irr(
    cashflows: list[float], initial_capex: float, residual: float, horizon: int
) -> float | None:
    if initial_capex <= 0 or sum(cashflows) + residual <= initial_capex:
        return None

    def f(daily_rate: float) -> float:
        return _npv_of(cashflows, daily_rate, initial_capex, residual, horizon)

    low, high = -0.9, 1.0
    if f(low) <= 0:
        return None
    while f(high) > 0 and high < 10.0:
        high *= 1.5
    if f(high) > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        if f(mid) > 0:
            low = mid
        else:
            high = mid
    daily = (low + high) / 2
    return (1.0 + daily) ** _DAYS_PER_YEAR - 1.0


def project_mining_cashflow(
    rig: MiningRig, market: MiningMarketData, assumptions: ProjectionAssumptions
) -> MiningProjection:
    """Project a rig/coin pair day by day and discount the varying cash flow."""
    if rig.algorithm.casefold() != market.algorithm.casefold():
        raise ValueError("incompatible rig/market algorithms")

    horizon = assumptions.horizon_days
    daily_diff_growth = _daily_from_monthly(assumptions.monthly_difficulty_growth_rate)
    daily_disc = _daily_from_annual(assumptions.annual_discount_rate)
    pool_fee = (
        assumptions.pool_fee_rate if assumptions.pool_fee_rate is not None else market.pool_fee_rate
    )
    residual = (
        assumptions.residual_value_usd
        if assumptions.residual_value_usd is not None
        else rig.residual_value_usd
    )
    capex_by_day: dict[int, float] = {}
    for day, amount in assumptions.capex_events:
        capex_by_day[day] = capex_by_day.get(day, 0.0) + amount

    subsidy0 = market.block_subsidy_coin
    txfee0 = market.tx_fee_revenue_coin_per_block * assumptions.tx_fee_multiplier
    price0 = market.coin_price_usd * assumptions.price_multiplier
    depreciation_daily = (rig.total_capex_usd - residual) / rig.useful_life_days

    cashflows: list[float] = []
    daily_series: list[dict[str, float]] = []
    total_coin = total_rev = total_cost = accounting = 0.0

    for d in range(horizon):
        halvings = sum(1 for h in assumptions.halving_day_indices if h <= d)
        subsidy_d = subsidy0 * (0.5**halvings)
        coin_per_block_d = subsidy_d + txfee0
        difficulty_mult = (1.0 + daily_diff_growth) ** d
        uptime_decay = (1.0 - assumptions.annual_uptime_degradation) ** (d / _DAYS_PER_YEAR)
        uptime_d = min(1.0, max(0.0, rig.uptime_rate * uptime_decay))
        hashrate_factor = (1.0 - assumptions.annual_hashrate_degradation) ** (d / _DAYS_PER_YEAR)
        price_d = price0 * (1.0 + assumptions.annual_price_drift) ** (d / _DAYS_PER_YEAR)

        coin_d = (
            (rig.hashrate_hs * hashrate_factor)
            / (market.network_hashrate_hs * difficulty_mult)
            * coin_per_block_d
            * market.blocks_per_day
            * uptime_d
            * (1.0 - rig.stale_reject_rate)
        )
        gross_d = coin_d * price_d
        pool_fee_d = gross_d * pool_fee
        energy_kwh = rig.power_watts / 1000.0 * 24.0 * uptime_d * rig.pue
        elec_rate_d = assumptions.electricity_usd_per_kwh * (
            1.0 + assumptions.annual_energy_inflation
        ) ** (d / _DAYS_PER_YEAR)
        electricity_d = 0.0 if rig.electricity_included else energy_kwh * elec_rate_d
        other_d = (
            rig.daily_operating_cost_usd
            + rig.daily_maintenance_cost_usd
            + rig.monthly_demand_charge_usd / _DAYS_PER_MONTH
            + rig.infrastructure_hourly_cost_usd * 24.0 * uptime_d
        )
        pre_tax_d = gross_d - pool_fee_d - electricity_d - other_d
        tax_d = max(0.0, pre_tax_d) * assumptions.tax_rate
        capex_d = capex_by_day.get(d, 0.0)
        net_cash_d = pre_tax_d - tax_d - capex_d
        cashflows.append(net_cash_d)

        total_coin += coin_d
        total_rev += gross_d
        total_cost += pool_fee_d + electricity_d + other_d + tax_d + capex_d
        accounting += pre_tax_d - tax_d - depreciation_daily
        daily_series.append(
            {
                "day": float(d),
                "coin_mined": coin_d,
                "coin_price_usd": price_d,
                "gross_revenue_usd": gross_d,
                "electricity_usd": electricity_d,
                "net_cash_usd": net_cash_d,
            }
        )

    npv = _npv_of(cashflows, daily_disc, rig.total_capex_usd, residual, horizon)
    irr = _irr(cashflows, rig.total_capex_usd, residual, horizon)

    discounted_payback: int | None = None
    cumulative = -rig.total_capex_usd
    for d, cf in enumerate(cashflows):
        cumulative += cf / (1.0 + daily_disc) ** (d + 1)
        if cumulative >= 0:
            discounted_payback = d + 1
            break

    production_cost = total_cost / total_coin if total_coin > 0 else None

    # Break-evens evaluated at day-0 conditions (documented simplification).
    day0 = daily_series[0]
    energy_kwh0 = rig.power_watts / 1000.0 * 24.0 * rig.uptime_rate * rig.pue
    non_energy0 = (
        day0["gross_revenue_usd"] * pool_fee
        + rig.daily_operating_cost_usd
        + rig.daily_maintenance_cost_usd
        + rig.monthly_demand_charge_usd / _DAYS_PER_MONTH
    )
    break_even_elec = (
        max(0.0, (day0["gross_revenue_usd"] - non_energy0) / energy_kwh0)
        if energy_kwh0 > 0 and not rig.electricity_included
        else None
    )
    coin0 = daily_series[0]["coin_mined"]
    fixed0 = (
        (0.0 if rig.electricity_included else energy_kwh0 * assumptions.electricity_usd_per_kwh)
        + rig.daily_operating_cost_usd
        + rig.daily_maintenance_cost_usd
        + rig.monthly_demand_charge_usd / _DAYS_PER_MONTH
    )
    break_even_price = fixed0 / (coin0 * (1.0 - pool_fee)) if coin0 > 0 and pool_fee < 1 else None

    # Constant-flow NPV (the V1 method) for an explicit overstatement comparison.
    level_flow = cashflows[0]
    if abs(daily_disc) < 1e-15:
        annuity = level_flow * horizon
    else:
        annuity = level_flow * (1 - (1 + daily_disc) ** (-horizon)) / daily_disc
    constant_npv = -rig.total_capex_usd + annuity + residual / (1 + daily_disc) ** horizon

    monthly_series = _monthly_aggregate(daily_series)

    return MiningProjection(
        horizon_days=horizon,
        initial_capex_usd=rig.total_capex_usd,
        total_coin_mined=total_coin,
        total_revenue_usd=total_rev,
        total_cost_usd=total_cost,
        cash_profit_usd=sum(cashflows),
        accounting_profit_usd=accounting,
        npv_usd=npv,
        irr_annual_rate=irr,
        discounted_payback_days=discounted_payback,
        production_cost_usd_per_coin=production_cost,
        break_even_electricity_usd_per_kwh=break_even_elec,
        break_even_coin_price_usd=break_even_price,
        monthly_series=monthly_series,
        constant_flow_npv_usd=constant_npv,
        npv_overstatement_vs_constant=constant_npv - npv,
        daily_series=daily_series,
    )


def _monthly_aggregate(daily: list[dict[str, float]]) -> list[dict[str, float]]:
    months: list[dict[str, float]] = []
    for i in range(0, len(daily), int(_DAYS_PER_MONTH)):
        chunk = daily[i : i + int(_DAYS_PER_MONTH)]
        months.append(
            {
                "month": float(i // int(_DAYS_PER_MONTH)),
                "coin_mined": sum(x["coin_mined"] for x in chunk),
                "gross_revenue_usd": sum(x["gross_revenue_usd"] for x in chunk),
                "net_cash_usd": sum(x["net_cash_usd"] for x in chunk),
            }
        )
    return months
