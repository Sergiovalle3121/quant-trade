"""Deterministic stress scenarios for mining economics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any

from quant_trade.mining.models import (
    MiningEvaluation,
    MiningMarketSnapshot,
    MiningPolicy,
    MiningRig,
)
from quant_trade.mining.profitability import evaluate_mining


def _positive_multiplier(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")


@dataclass(frozen=True)
class MiningStressScenario:
    """Multipliers applied to one point-in-time rig and market snapshot."""

    name: str
    price_multiplier: float = 1.0
    network_hashrate_multiplier: float = 1.0
    uptime_multiplier: float = 1.0
    electricity_multiplier: float = 1.0
    cloud_cost_multiplier: float = 1.0
    temperature_add_c: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name must be non-empty")
        for name in (
            "price_multiplier",
            "network_hashrate_multiplier",
            "uptime_multiplier",
            "electricity_multiplier",
            "cloud_cost_multiplier",
        ):
            _positive_multiplier(name, getattr(self, name))
        if not math.isfinite(self.temperature_add_c):
            raise ValueError("temperature_add_c must be finite")


@dataclass(frozen=True)
class MiningScenarioEvaluation:
    scenario: MiningStressScenario
    evaluation: MiningEvaluation

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": asdict(self.scenario),
            "evaluation": self.evaluation.to_dict(),
        }


def default_scenarios() -> tuple[MiningStressScenario, ...]:
    """Return a fixed scenario set; values are policy inputs, not forecasts."""
    return (
        MiningStressScenario("base"),
        MiningStressScenario(
            "optimistic",
            price_multiplier=1.15,
            network_hashrate_multiplier=0.95,
            uptime_multiplier=1.03,
            electricity_multiplier=0.95,
        ),
        MiningStressScenario(
            "pessimistic",
            price_multiplier=0.75,
            network_hashrate_multiplier=1.20,
            uptime_multiplier=0.90,
            electricity_multiplier=1.20,
            cloud_cost_multiplier=1.15,
        ),
        MiningStressScenario("price_crash", price_multiplier=0.50),
        MiningStressScenario("difficulty_spike", network_hashrate_multiplier=1.50),
        MiningStressScenario("uptime_drop", uptime_multiplier=0.60),
        MiningStressScenario("tariff_spike", electricity_multiplier=1.75),
        MiningStressScenario(
            "ventilation_failure",
            uptime_multiplier=0.70,
            temperature_add_c=20.0,
        ),
        MiningStressScenario(
            "extreme",
            price_multiplier=0.40,
            network_hashrate_multiplier=1.75,
            uptime_multiplier=0.50,
            electricity_multiplier=2.0,
            cloud_cost_multiplier=1.50,
            temperature_add_c=25.0,
        ),
    )


def evaluate_scenario(
    rig: MiningRig,
    market: MiningMarketSnapshot,
    policy: MiningPolicy,
    scenario: MiningStressScenario,
) -> MiningScenarioEvaluation:
    """Evaluate one scenario without network, cloud, or process side effects."""
    scenario_temperature = (
        None
        if rig.temperature_c is None
        else rig.temperature_c + scenario.temperature_add_c
    )
    scenario_rig = replace(
        rig,
        uptime_rate=min(1.0, rig.uptime_rate * scenario.uptime_multiplier),
        infrastructure_hourly_cost_usd=(
            rig.infrastructure_hourly_cost_usd * scenario.cloud_cost_multiplier
        ),
        temperature_c=scenario_temperature,
    )
    scenario_market = replace(
        market,
        coin_price_usd=market.coin_price_usd * scenario.price_multiplier,
        network_hashrate_hs=(
            market.network_hashrate_hs * scenario.network_hashrate_multiplier
        ),
    )
    scenario_policy = replace(
        policy,
        electricity_usd_per_kwh=(
            policy.electricity_usd_per_kwh * scenario.electricity_multiplier
        ),
    )
    return MiningScenarioEvaluation(
        scenario=scenario,
        evaluation=evaluate_mining(scenario_rig, scenario_market, scenario_policy),
    )


def evaluate_all_scenarios(
    rigs: tuple[MiningRig, ...],
    markets: tuple[MiningMarketSnapshot, ...],
    policy: MiningPolicy,
    scenarios: tuple[MiningStressScenario, ...] | None = None,
) -> list[MiningScenarioEvaluation]:
    """Evaluate every compatible pair under a deterministic scenario matrix."""
    selected = scenarios or default_scenarios()
    results = [
        evaluate_scenario(rig, market, policy, scenario)
        for rig in rigs
        for market in markets
        if rig.algorithm.casefold() == market.algorithm.casefold()
        for scenario in selected
    ]
    if not results:
        raise ValueError("no compatible rig/market algorithm pairs")
    return results

