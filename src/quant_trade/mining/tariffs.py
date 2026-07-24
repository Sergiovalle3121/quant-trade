"""Electricity tariff modelling for mining economics.

Supports flat, time-of-use (peak/off-peak), demand charges, taxes/surcharges,
PUE, curtailment, and all-inclusive hosting. Deliberately *not* hardcoded to any
single utility: a real tariff (e.g. a Mexican CFE bill) must be captured into a
config and validated, not baked into code. `cfe_receipt_template()` shows the
fields a real bill provides.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

_HOURS_PER_DAY = 24.0
_DAYS_PER_MONTH = 30.0


def _non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and >= 0")


@dataclass(frozen=True)
class ElectricityTariff:
    """A configurable tariff. Provide either flat, TOU, or all-inclusive rates."""

    flat_rate_usd_per_kwh: float | None = None
    peak_rate_usd_per_kwh: float | None = None
    offpeak_rate_usd_per_kwh: float | None = None
    peak_hours_per_day: float = 0.0
    demand_charge_usd_per_kw_month: float = 0.0
    tax_surcharge_rate: float = 0.0
    pue: float = 1.0
    curtailment_hours_per_day: float = 0.0
    hosting_all_inclusive_usd_per_kwh: float | None = None
    max_contracted_demand_kw: float | None = None
    currency: str = "USD"

    def __post_init__(self) -> None:
        for name in (
            "peak_hours_per_day",
            "demand_charge_usd_per_kw_month",
            "tax_surcharge_rate",
            "curtailment_hours_per_day",
        ):
            _non_negative(name, getattr(self, name))
        if self.pue < 1 or not math.isfinite(self.pue):
            raise ValueError("pue must be finite and >= 1")
        if self.peak_hours_per_day > _HOURS_PER_DAY:
            raise ValueError("peak_hours_per_day cannot exceed 24")
        if self.curtailment_hours_per_day > _HOURS_PER_DAY:
            raise ValueError("curtailment_hours_per_day cannot exceed 24")
        has_tou = (
            self.peak_rate_usd_per_kwh is not None
            and self.offpeak_rate_usd_per_kwh is not None
        )
        has_energy = (
            self.flat_rate_usd_per_kwh is not None
            or has_tou
            or self.hosting_all_inclusive_usd_per_kwh is not None
        )
        if not has_energy:
            raise ValueError("provide flat, TOU, or all-inclusive energy rates")

    def blended_energy_rate(self) -> float:
        """Effective $/kWh including PUE and taxes (excludes demand charge)."""
        if self.hosting_all_inclusive_usd_per_kwh is not None:
            base = self.hosting_all_inclusive_usd_per_kwh
        elif self.flat_rate_usd_per_kwh is not None:
            base = self.flat_rate_usd_per_kwh
        else:
            assert self.peak_rate_usd_per_kwh is not None
            assert self.offpeak_rate_usd_per_kwh is not None
            peak_frac = self.peak_hours_per_day / _HOURS_PER_DAY
            base = (
                peak_frac * self.peak_rate_usd_per_kwh
                + (1 - peak_frac) * self.offpeak_rate_usd_per_kwh
            )
        return base * self.pue * (1.0 + self.tax_surcharge_rate)

    def effective_uptime(self, requested_uptime: float) -> float:
        """Uptime after curtailment hours are removed."""
        available = max(0.0, 1.0 - self.curtailment_hours_per_day / _HOURS_PER_DAY)
        return min(requested_uptime, available)

    def monthly_cost(self, load_kw: float, requested_uptime: float = 1.0) -> dict[str, float]:
        """Monthly energy + demand cost for a steady ``load_kw`` draw."""
        _non_negative("load_kw", load_kw)
        if self.max_contracted_demand_kw is not None and load_kw > self.max_contracted_demand_kw:
            raise ValueError("load exceeds max contracted demand")
        uptime = self.effective_uptime(requested_uptime)
        kwh = load_kw * _HOURS_PER_DAY * uptime * _DAYS_PER_MONTH
        energy_cost = kwh * self.blended_energy_rate()
        demand_cost = load_kw * self.demand_charge_usd_per_kw_month
        return {
            "kwh": kwh,
            "energy_cost_usd": energy_cost,
            "demand_charge_usd": demand_cost,
            "total_usd": energy_cost + demand_cost,
            "effective_uptime": uptime,
            "blended_rate_usd_per_kwh": self.blended_energy_rate(),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cfe_receipt_template() -> dict[str, Any]:
    """Fields to transcribe from a real CFE bill into a tariff config.

    These are placeholders, NOT a real tariff — a real bill's numbers must be
    entered per-site. Presenting a hardcoded rate as universal would be wrong.
    """
    return {
        "billing_period": "YYYY-MM",
        "tariff_class": "e.g. GDMTH / DIST / PDBT",
        "peak_rate_usd_per_kwh": None,
        "offpeak_rate_usd_per_kwh": None,
        "peak_hours_per_day": None,
        "demand_charge_usd_per_kw_month": None,
        "tax_surcharge_rate": None,
        "max_contracted_demand_kw": None,
        "usd_mxn_rate_used": None,
        "source": "scanned CFE receipt",
    }
