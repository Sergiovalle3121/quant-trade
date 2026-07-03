"""Data models for offline research campaigns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CampaignMode = Literal[
    "research_strategy_campaign",
    "grid_search_campaign",
    "walk_forward_campaign",
    "robustness_campaign",
    "stress_campaign",
    "ml_baseline_campaign",
    "paper_trial_review_campaign",
]


@dataclass(frozen=True)
class CampaignRunConfig:
    run_id: str
    campaign_id: str
    mode: str
    strategy: str
    parameters: dict[str, Any]
    cost_assumptions: dict[str, Any]
    universe: list[str]
    data_path: str
    split_policy: dict[str, Any]
    benchmark: str
    random_seed: int


@dataclass(frozen=True)
class CampaignResult:
    run_id: str
    strategy: str
    metrics: dict[str, float]
    artifacts_complete: bool = True
    rejection_reason: str = ""


@dataclass(frozen=True)
class RankedCandidate:
    run_id: str
    strategy: str
    composite_score: float
    oos_score: float
    robustness_score: float
    risk_score: float
    operational_score: float
    overfitting_penalty: float
    turnover_penalty: float
    drawdown_penalty: float
    rejected: bool = False
    rejection_reason: str = ""


@dataclass
class GuardrailPolicy:
    max_parameter_combinations: int = 100
    require_oos_metrics: bool = True
    require_benchmark_comparison: bool = True
    require_cost_sensitivity: bool = True
    min_trades: int = 5
    max_drawdown: float = 0.35
    max_train_test_gap: float = 0.25
    max_turnover: float = 8.0
    single_metric_ranking_allowed: bool = False


@dataclass
class CampaignConfig:
    campaign_id: str
    campaign_name: str
    mode: CampaignMode
    universe: list[str]
    data_path: str
    strategies: list[str]
    parameter_grids: dict[str, dict[str, list[Any]]] = field(default_factory=dict)
    cost_assumptions: list[dict[str, Any]] = field(default_factory=lambda: [{}])
    split_policy: dict[str, Any] = field(default_factory=dict)
    benchmark: str = "SPY"
    max_runs: int = 25
    output_dir: str = "outputs/campaigns"
    allow_parallel: bool = False
    random_seed: int = 42
    overfitting_guardrails: dict[str, Any] = field(default_factory=dict)
    ranking_policy: dict[str, Any] = field(default_factory=dict)
    real_money_enabled: bool = False
