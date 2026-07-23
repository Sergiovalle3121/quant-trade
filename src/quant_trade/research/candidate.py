from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

CandidateStatus = Literal[
    "research_only",
    "candidate",
    "rejected",
    "paper_ready",
    "paper_active",
    "paper_paused",
    "retired",
]


@dataclass
class CandidateStrategy:
    candidate_id: str
    name: str
    strategy_name: str
    strategy_params: dict[str, Any]
    universe: list[str]
    benchmark: str
    data_start: str
    data_end: str
    research_run_dir: str
    selected_at_utc: str
    selected_by: str
    status: CandidateStatus = "candidate"
    approval_notes: str = ""
    risk_notes: str = ""
    known_limitations: str = ""
    required_capital: float = 0.0
    expected_rebalance_frequency: str = "unknown"
    max_weight_per_asset: float = 1.0
    max_gross_exposure: float = 1.0
    estimated_turnover: float = 0.0
    expected_cost_sensitivity: str = "unknown"
    tags: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateStrategy:
        return cls(**payload)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SelectionCriteria:
    min_test_sharpe: float = 0.5
    min_excess_return: float = 0.0
    max_test_drawdown: float = 0.2
    max_turnover: float = 3.0
    require_beats_benchmark: bool = True
    require_cost_sensitivity_pass: bool = True
    require_subperiod_pass: bool = False
    require_no_red_flags: bool = False
    min_test_months: int = 12
    max_train_test_sharpe_gap: float = 1.0
    allowed_strategies: list[str] | None = None
    allowed_symbols: list[str] | None = None
    # Statistical gates (0 / False = disabled for backward compatibility;
    # the shipped conservative configs enable them).
    min_trade_count: int = 0
    min_probabilistic_sharpe: float = 0.0
    require_deflated_sharpe: bool = False
    min_deflated_sharpe: float = 0.5
    require_walk_forward_overfitting_evidence: bool = False
    max_walk_forward_pbo: float = 0.50
    min_walk_forward_windows: int = 4

    @classmethod
    def from_yaml(cls, path: Path) -> SelectionCriteria:
        return cls(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
