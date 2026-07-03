"""Typed models for offline transaction cost analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExecutionAssumption:
    model: str = "spread_adjusted_open"
    slippage_bps: float = 5.0
    spread_bps: float = 2.0
    max_participation_rate: float = 0.10
    impact_bps_per_10pct_adv: float = 4.0
    reject_when_over_capacity: bool = False

@dataclass(frozen=True)
class TcaPolicy:
    name: str = "conservative_offline_tca"
    real_money_ready: bool = False
    default_equity: float = 100000.0
    research_assumed_cost_bps: float = 10.0
    execution: ExecutionAssumption = ExecutionAssumption()

@dataclass(frozen=True)
class SlippageModel:
    name: str = "conservative_bps"
    base_bps: float = 5.0

@dataclass(frozen=True)
class ParticipationModel:
    max_participation_rate: float = 0.10

@dataclass(frozen=True)
class OrderExecutionAnalysis:
    order_id: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    arrival_price: float
    decision_price: float
    execution_price: float
    implementation_shortfall: float
    slippage_bps: float
    spread_cost_bps: float
    delay_cost_bps: float
    market_impact_proxy: float
    total_cost: float
    status: str
    fill_rate: float
    cost_vs_research_assumption: float
    def to_dict(self) -> dict[str, object]: return asdict(self)

@dataclass(frozen=True)
class FillQualityMetrics:
    order_count: int
    fill_rate: float
    partial_fill_rate: float
    rejected_rate: float
    average_slippage_bps: float
    total_cost: float
    cost_as_pct_of_equity: float
    turnover_adjusted_cost: float
    real_money_ready: bool = False
    def to_dict(self) -> dict[str, object]: return asdict(self)

@dataclass(frozen=True)
class ExecutionQualityReport:
    run_id: str
    metrics: FillQualityMetrics
    limitations: list[str]
    output_dir: str
    real_money_ready: bool = False
