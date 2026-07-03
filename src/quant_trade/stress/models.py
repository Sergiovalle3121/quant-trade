"""Stress-testing domain models for simulation-only scenario analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ScenarioType = Literal[
    "price_shock",
    "volatility_spike",
    "correlation_spike",
    "liquidity_shock",
    "gap_risk",
    "drawdown_replay",
    "benchmark_crash",
    "rate_shock_proxy",
    "strategy_pause_scenario",
    "operational_failure_scenario",
]


@dataclass(frozen=True)
class ScenarioShock:
    kind: str
    value: float
    symbol: str | None = None


@dataclass(frozen=True)
class StressScenario:
    name: str
    scenario_type: ScenarioType
    shocks: dict[str, float] = field(default_factory=dict)
    severity: str = "medium"
    description: str = ""
    volatility_multiplier: float = 1.0
    correlation_direction: float = -1.0
    liquidity_cost_multiplier: float = 1.0
    slippage_bps_add: float = 0.0
    benchmark_symbol: str = "SPY"
    required_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class StressPolicy:
    name: str = "conservative"
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.12
    max_liquidity_cost_pct: float = 0.01
    max_slippage_bps: float = 25.0
    max_exposure: float = 1.0
    required_symbols: tuple[str, ...] = ()
    real_money_ready: bool = False


@dataclass(frozen=True)
class StressResult:
    scenario_name: str
    scenario_type: str
    stressed_total_return: float
    stressed_max_drawdown: float
    stressed_daily_loss: float
    stressed_liquidity_cost: float
    stressed_slippage_bps: float
    stressed_exposure: float
    breach_count: int
    scenario_pass: bool
    warnings: tuple[str, ...] = ()
    capital_at_risk_estimate: float = 0.0
    recovery_days_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True)
class StressDecision:
    status: Literal["pass", "fail"]
    reason: str
    real_money_ready: bool = False


@dataclass(frozen=True)
class StressPortfolioReport:
    run_id: str
    results: tuple[StressResult, ...]
    decision: StressDecision

    @property
    def worst_scenario(self) -> str:
        if not self.results:
            return "none"
        return min(self.results, key=lambda item: item.stressed_total_return).scenario_name
