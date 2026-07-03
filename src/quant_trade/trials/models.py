from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

TrialStatus = Literal["planned", "active", "paused", "completed", "rejected", "retired"]
ReviewFrequency = Literal["daily", "weekly", "monthly"]
DecisionStatus = Literal[
    "continue_trial",
    "pause_trial",
    "extend_trial",
    "reject_strategy",
    "retire_strategy",
    "complete_trial",
    "paper_ops_ready",
    "needs_human_review",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TrialConfig:
    trial_id: str
    display_name: str
    status: TrialStatus
    paper_session_id: str
    strategy_name: str
    strategy_params: dict[str, Any]
    universe: list[str]
    benchmark: str
    paper_config_path: str
    ops_config_path: str
    start_date: date
    planned_end_date: date
    trial_length_days: int
    review_frequency: ReviewFrequency
    timezone: str
    owner: str
    reviewer: str
    initial_paper_equity: float
    expected_rebalance_frequency: str
    expected_turnover_range: tuple[float, float]
    candidate_id: str | None = None
    research_run_dir: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TrialConfig:
        data = dict(raw)
        data["start_date"] = date.fromisoformat(str(data["start_date"]))
        data["planned_end_date"] = date.fromisoformat(str(data["planned_end_date"]))
        data["expected_turnover_range"] = tuple(data.get("expected_turnover_range", [0.0, 1.0]))
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["planned_end_date"] = self.planned_end_date.isoformat()
        d["expected_turnover_range"] = list(self.expected_turnover_range)
        return d


@dataclass
class TrialPolicy:
    min_observation_days: int = 20
    min_success_rate: float = 0.95
    max_total_drawdown_pct: float = 0.10
    max_daily_loss_pct: float = 0.03
    max_rejected_order_rate: float = 0.02
    max_slippage_bps: float = 10.0
    max_turnover_multiple_vs_research: float = 2.0
    max_tracking_error_vs_research: float = 0.08
    min_excess_return_vs_benchmark: float = -0.03
    max_underperformance_vs_research: float = 0.05
    max_open_critical_incidents: int = 0
    max_stale_heartbeats: int = 0
    require_weekly_reviews: bool = True
    require_monthly_reviews: bool = True
    require_reconciliation_pass: bool = True
    require_fill_analysis_pass: bool = True
    require_kill_switch_drill_pass: bool = True
    require_manual_review_notes: bool = True
    require_no_secrets_findings: bool = True
    allow_advancement_to_real_money: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TrialPolicy:
        obj = cls(**(raw or {}))
        if obj.allow_advancement_to_real_money:
            raise ValueError("allow_advancement_to_real_money must remain false")
        return obj

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyTrialRecord:
    trial_id: str
    date: date
    paper_session_id: str
    equity: float
    cash: float
    daily_return: float
    cumulative_return: float
    drawdown: float
    benchmark_return: float
    excess_return: float
    orders_count: int
    fills_count: int
    rejected_orders_count: int
    turnover: float
    gross_exposure: float
    max_position_weight: float
    slippage_bps: float
    risk_events_count: int
    open_incidents_count: int
    heartbeat_status: str
    reconciliation_status: str
    kill_switch_active: bool
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DailyTrialRecord:
        d = dict(raw)
        d["date"] = date.fromisoformat(str(d["date"]))
        d["kill_switch_active"] = str(d.get("kill_switch_active", False)).lower() in {
            "true",
            "1",
            "yes",
        }
        for k in [
            "equity",
            "cash",
            "daily_return",
            "cumulative_return",
            "drawdown",
            "benchmark_return",
            "excess_return",
            "turnover",
            "gross_exposure",
            "max_position_weight",
            "slippage_bps",
        ]:
            d[k] = float(d.get(k, 0) or 0)
        for k in [
            "orders_count",
            "fills_count",
            "rejected_orders_count",
            "risk_events_count",
            "open_incidents_count",
        ]:
            d[k] = int(float(d.get(k, 0) or 0))
        return cls(**d)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d
