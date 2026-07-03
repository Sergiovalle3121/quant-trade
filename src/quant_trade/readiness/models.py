from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FinalStatus = Literal[
    "not_ready",
    "needs_more_paper_data",
    "needs_risk_review",
    "needs_security_review",
    "paper_capital_ramp_ready",
    "rejected",
]

SAFETY_FLAGS = {
    "real_money_ready": False,
    "real_money_approved": False,
    "live_trading_enabled": False,
}


@dataclass
class ReadinessDossier:
    run_id: str
    executive_summary: str
    safety_status: dict[str, Any]
    strategy_inventory: list[dict[str, Any]] = field(default_factory=list)
    evidence_database_summary: dict[str, Any] = field(default_factory=dict)
    research_results: dict[str, Any] = field(default_factory=dict)
    oos_walk_forward_results: dict[str, Any] = field(default_factory=dict)
    paper_trial_results: dict[str, Any] = field(default_factory=dict)
    ops_reliability: dict[str, Any] = field(default_factory=dict)
    security_controls: dict[str, Any] = field(default_factory=dict)
    stress_tests: dict[str, Any] = field(default_factory=dict)
    tca_execution_quality: dict[str, Any] = field(default_factory=dict)
    allocation_simulation: dict[str, Any] = field(default_factory=dict)
    incident_history: list[dict[str, Any]] = field(default_factory=list)
    approval_history: list[dict[str, Any]] = field(default_factory=list)
    open_risks: list[dict[str, Any]] = field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    human_review_notes: str = ""
    final_status: FinalStatus = "not_ready"
    real_money_ready: bool = False
    real_money_approved: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(SAFETY_FLAGS)
        return data


@dataclass
class CapitalRampResult:
    paper_capital: float
    max_position_size: float
    expected_turnover: float
    expected_cost: float
    liquidity_capacity_warning: str
    drawdown_dollars: float
    daily_loss_dollars: float
    risk_budget_usage: float
    concentration_risk: str
    stress_loss_dollars: float
    recommended_paper_only_limit: float
    real_money_ready: bool = False


@dataclass
class RiskOfRuinResult:
    probability_drawdown_breach: float
    probability_daily_loss_breach: float
    expected_worst_drawdown: float
    worst_drawdown_ci: tuple[float, float]
    warnings: list[str]
    real_money_ready: bool = False


@dataclass
class ChecklistResult:
    passed: bool
    checks: dict[str, bool]
    blocking_issues: list[str]
    real_money_ready: bool = False
