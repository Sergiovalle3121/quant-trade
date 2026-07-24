"""Deterministic scenario matrix for the dynamic mining cash-flow projection.

Produces NPV *bands* by running the projection under a fixed set of price /
difficulty / energy paths. These are deterministic scenarios (inputs, not
forecasts), so the band is justified without a fitted stochastic model — the
prompt's "probability/simulation bands only if justified" bar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from quant_trade.mining.cashflow import (
    MiningProjection,
    ProjectionAssumptions,
    project_mining_cashflow,
)
from quant_trade.mining.market import MiningMarketData
from quant_trade.mining.models import MiningRig


@dataclass(frozen=True)
class ProjectionScenario:
    name: str
    price_multiplier: float = 1.0
    monthly_difficulty_growth_rate: float | None = None
    annual_price_drift: float | None = None
    annual_energy_inflation: float | None = None
    description: str = ""

    def apply(self, base: ProjectionAssumptions) -> ProjectionAssumptions:
        overrides: dict[str, Any] = {
            "price_multiplier": base.price_multiplier * self.price_multiplier
        }
        if self.monthly_difficulty_growth_rate is not None:
            overrides["monthly_difficulty_growth_rate"] = self.monthly_difficulty_growth_rate
        if self.annual_price_drift is not None:
            overrides["annual_price_drift"] = self.annual_price_drift
        if self.annual_energy_inflation is not None:
            overrides["annual_energy_inflation"] = self.annual_energy_inflation
        return replace(base, **overrides)


@dataclass
class ScenarioProjection:
    scenario: str
    description: str
    npv_usd: float
    irr_annual_rate: float | None
    decision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_projection_scenarios() -> tuple[ProjectionScenario, ...]:
    return (
        ProjectionScenario("base", description="unshocked base assumptions"),
        ProjectionScenario(
            "bull", price_multiplier=1.4, monthly_difficulty_growth_rate=0.01,
            annual_price_drift=0.10, description="price up, slower difficulty growth",
        ),
        ProjectionScenario(
            "bear", price_multiplier=0.7, monthly_difficulty_growth_rate=0.05,
            annual_price_drift=-0.10, description="price down, faster difficulty growth",
        ),
        ProjectionScenario(
            "price_crash", price_multiplier=0.45, description="sharp price drawdown",
        ),
        ProjectionScenario(
            "difficulty_spike", monthly_difficulty_growth_rate=0.08,
            description="aggressive difficulty growth",
        ),
        ProjectionScenario(
            "energy_shock", annual_energy_inflation=0.30, description="electricity cost spike",
        ),
    )


def project_scenarios(
    rig: MiningRig,
    market: MiningMarketData,
    base: ProjectionAssumptions,
    scenarios: tuple[ProjectionScenario, ...] | None = None,
) -> list[tuple[ProjectionScenario, MiningProjection]]:
    selected = scenarios or default_projection_scenarios()
    return [(s, project_mining_cashflow(rig, market, s.apply(base))) for s in selected]


def scenario_projection_rows(
    results: list[tuple[ProjectionScenario, MiningProjection]]
) -> list[ScenarioProjection]:
    return [
        ScenarioProjection(
            scenario=s.name,
            description=s.description,
            npv_usd=p.npv_usd,
            irr_annual_rate=p.irr_annual_rate,
            decision="GO" if p.npv_usd > 0 else "NO-GO",
        )
        for s, p in results
    ]


def npv_band(results: list[tuple[ProjectionScenario, MiningProjection]]) -> dict[str, float]:
    """Min / median / max NPV across the deterministic scenario matrix."""
    npvs = sorted(p.npv_usd for _s, p in results)
    if not npvs:
        raise ValueError("no scenario results")
    n = len(npvs)
    median = npvs[n // 2] if n % 2 == 1 else (npvs[n // 2 - 1] + npvs[n // 2]) / 2
    go_count = sum(1 for v in npvs if v > 0)
    return {
        "min_npv_usd": npvs[0],
        "median_npv_usd": median,
        "max_npv_usd": npvs[-1],
        "scenarios": float(n),
        "go_scenarios": float(go_count),
    }
