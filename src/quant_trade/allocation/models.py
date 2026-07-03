from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

AllocationDecisionStatus = Literal[
    "approve_simulated",
    "reduce_allocation",
    "pause_allocation",
    "reject_allocation",
    "require_human_review",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class AllocationCandidate:
    strategy_id: str
    strategy_name: str
    status: str
    evidence_paths: list[str]
    daily_returns_path: str
    metrics_path: str | None = None
    approved_for_paper: bool = False
    expected_volatility: float | None = None
    max_drawdown: float | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AllocationCandidate:
        return cls(**raw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AllocationPolicy:
    max_total_capital: float
    max_strategy_weight: float
    min_strategy_weight: float
    max_strategy_drawdown: float
    max_portfolio_drawdown: float
    max_pairwise_correlation: float
    max_cluster_exposure: float
    max_single_strategy_loss_contribution: float
    min_cash_buffer_pct: float
    volatility_target: float | None = None
    allow_leverage: bool = False
    allow_short: bool = False
    real_money_enabled: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AllocationPolicy:
        obj = cls(**raw)
        if obj.allow_leverage:
            raise ValueError("allow_leverage must be false for allocation simulation")
        if obj.allow_short:
            raise ValueError("allow_short must be false for allocation simulation")
        if obj.real_money_enabled:
            raise ValueError("real_money_enabled must be false")
        if obj.min_cash_buffer_pct < 0 or obj.min_cash_buffer_pct >= 1:
            raise ValueError("min_cash_buffer_pct must be in [0, 1)")
        if obj.min_strategy_weight < 0 or obj.max_strategy_weight <= 0:
            raise ValueError("strategy weight bounds must be positive")
        return obj

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyAllocation:
    strategy_id: str
    weight: float
    capital: float
    decision: str = "selected"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioAllocation:
    run_id: str
    total_capital: float
    cash_weight: float
    allocations: list[StrategyAllocation]
    warnings: list[str] = field(default_factory=list)
    real_money_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AllocationDecision:
    decision_id: str
    allocation_run_id: str
    strategy_id: str
    decision: AllocationDecisionStatus
    reason: str
    evidence_paths: list[str]
    human_notes: str = ""
    real_money_approved: bool = False
    created_at_utc: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["real_money_approved"] = False
        return d


@dataclass(frozen=True)
class PortfolioRiskReport:
    portfolio_volatility: float
    max_drawdown: float
    pairwise_correlation_max: float
    high_correlation_pairs: list[dict[str, Any]]
    drawdown_overlap_pairs: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AllocationSimulationResult:
    allocation: PortfolioAllocation
    metrics: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    risk_report: PortfolioRiskReport

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
