"""Conservative promotion V2: recompute evidence, never trust stored flags.

The V1 gate accepted a run's own ``robustness`` / ``psr`` flags at face value.
V2 reopens ``results.json`` and the trial ledger and *recomputes* the deflated
Sharpe from the persisted return moments and the ledger's effective trial
count, so a run cannot promote itself by writing a friendly flag. Every gate
fails closed: missing evidence is a rejection, not a pass.

The best possible outcome here is ``paper_candidate``. This module never emits a
real-money decision — ``real_money_authorized`` is always ``False``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quant_trade.metrics.statistics import expected_max_sharpe, psr_from_moments
from quant_trade.research.candidate import CandidateStrategy
from quant_trade.research.ledger import LedgerIntegrityReport, ledger_integrity_report


@dataclass(frozen=True)
class PromotionPolicyV2:
    """Thresholds for the conservative paper-candidate gate."""

    min_oos_sharpe: float = 0.5
    min_net_excess_return: float = 0.0
    min_probabilistic_sharpe: float = 0.95
    min_deflated_sharpe: float = 0.95
    min_observations: int = 60
    min_trade_count: int = 30
    max_drawdown: float = 0.20
    max_turnover: float = 3.0
    require_cost_sensitivity_pass: bool = True
    require_subperiod_pass: bool = True
    require_bootstrap_positive_lower_bound: bool = True
    min_quantity_fill_rate: float = 0.90
    max_incomplete_order_rate: float = 0.10
    require_execution_policy: bool = True
    require_dataset_binding: bool = True
    require_ledger_integrity: bool = True
    require_approval_notes: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> PromotionPolicyV2:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Gate:
    name: str
    passed: bool
    detail: str


@dataclass
class PromotionDecisionV2:
    candidate_id: str
    status: str  # "paper_candidate" | "rejected"
    gates: list[Gate]
    failed_gates: list[str]
    recomputed: dict[str, Any]
    real_money_authorized: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "gates": [asdict(g) for g in self.gates],
            "failed_gates": self.failed_gates,
            "recomputed": self.recomputed,
            "real_money_authorized": self.real_money_authorized,
            "notes": self.notes,
        }


def _num(payload: dict[str, Any], *keys: str) -> float | None:
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    if cur is None or isinstance(cur, bool):
        return None
    try:
        return float(cur)
    except (TypeError, ValueError):
        return None


def _dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _load_results(run_dir: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def evaluate_promotion_v2(
    run_dir: str | Path,
    policy: PromotionPolicyV2,
    *,
    ledger_dir: str | Path | None = None,
    candidate: CandidateStrategy | None = None,
    approval_notes: str | None = None,
) -> PromotionDecisionV2:
    """Recompute all evidence from artifacts and apply the conservative gate.

    ``approval_notes`` (if given) overrides the candidate's notes, so a caller
    can supply human sign-off without constructing a full candidate object.
    """
    run_dir = Path(run_dir)
    ledger_dir = Path(ledger_dir) if ledger_dir is not None else run_dir.parent
    candidate_id = candidate.candidate_id if candidate else run_dir.name
    gates: list[Gate] = []

    def add(name: str, passed: bool, detail: str) -> None:
        gates.append(Gate(name=name, passed=bool(passed), detail=detail))

    results = _load_results(run_dir)
    add("results_json_readable", results is not None, "results.json must be valid JSON")
    if results is None:
        return PromotionDecisionV2(
            candidate_id=candidate_id,
            status="rejected",
            gates=gates,
            failed_gates=[g.name for g in gates if not g.passed],
            recomputed={},
            notes=["no readable results.json; nothing can be recomputed"],
        )

    # --- pull raw evidence -------------------------------------------------
    sharpe_pp = _num(results, "test_metrics", "sharpe_per_period")
    observations = _num(results, "test_metrics", "observations")
    skew = _num(results, "test_metrics", "skewness")
    kurt = _num(results, "test_metrics", "kurtosis")
    oos_sharpe = _num(results, "test_metrics", "sharpe")
    drawdown_raw = _num(results, "test_metrics", "max_drawdown")
    turnover = _num(results, "test_metrics", "turnover")
    trade_count = _num(results, "test_metrics", "trade_count")
    excess = _num(results, "comparison_test", "excess_return")
    fill_rate = _num(results, "execution_test", "quantity_fill_rate")
    incomplete_rate = _num(results, "execution_test", "partial_or_expired_order_rate")
    robustness = _dict(results, "robustness")
    bootstrap = _dict(results, "bootstrap")
    execution_policy = _dict(results, "execution_policy")
    dataset_sha = None
    binding = results.get("dataset_binding")
    if isinstance(binding, dict):
        dataset_sha = binding.get("data_sha256")

    # --- recompute PSR / DSR from the ledger, not stored flags -------------
    integrity: LedgerIntegrityReport = ledger_integrity_report(ledger_dir)
    recomputed_psr: float | None = None
    recomputed_dsr: float | None = None
    dsr_threshold: float | None = None
    if None not in (sharpe_pp, observations, skew, kurt):
        n_obs = int(observations)  # type: ignore[arg-type]
        recomputed_psr = psr_from_moments(sharpe_pp, n_obs, skew, kurt, 0.0)  # type: ignore[arg-type]
        dsr_threshold = expected_max_sharpe(
            integrity.effective_trial_count, integrity.sharpe_variance
        )
        recomputed_dsr = psr_from_moments(
            sharpe_pp, n_obs, skew, kurt, benchmark_sharpe=dsr_threshold  # type: ignore[arg-type]
        )

    # --- gates (all fail closed) ------------------------------------------
    if policy.require_dataset_binding:
        add("dataset_binding_present", bool(dataset_sha), "dataset SHA must be recorded")
    if policy.require_ledger_integrity:
        add(
            "ledger_integrity",
            integrity.exists and integrity.is_intact,
            "trial ledger must exist and be free of corrupt lines",
        )
    if policy.require_execution_policy:
        add(
            "execution_policy_specified",
            bool(execution_policy.get("specified")),
            "a realistic execution policy must be specified (no unlimited fills)",
        )
    add(
        "min_observations",
        observations is not None and observations >= policy.min_observations,
        f"OOS observations must be >= {policy.min_observations}",
    )
    add(
        "min_trade_count",
        trade_count is not None and trade_count >= policy.min_trade_count,
        f"OOS trade count must be >= {policy.min_trade_count}",
    )
    add(
        "oos_sharpe",
        oos_sharpe is not None and oos_sharpe >= policy.min_oos_sharpe,
        f"OOS Sharpe must be >= {policy.min_oos_sharpe}",
    )
    add(
        "net_excess_return_positive",
        excess is not None and excess > policy.min_net_excess_return,
        f"net OOS excess return must exceed {policy.min_net_excess_return}",
    )
    add(
        "probabilistic_sharpe",
        recomputed_psr is not None and recomputed_psr >= policy.min_probabilistic_sharpe,
        f"recomputed PSR must be >= {policy.min_probabilistic_sharpe}",
    )
    add(
        "deflated_sharpe",
        recomputed_dsr is not None and recomputed_dsr >= policy.min_deflated_sharpe,
        f"recomputed DSR must be >= {policy.min_deflated_sharpe} "
        f"(after {integrity.effective_trial_count} effective trials)",
    )
    add(
        "drawdown_within_limit",
        drawdown_raw is not None and abs(drawdown_raw) <= policy.max_drawdown,
        f"OOS drawdown must not exceed {policy.max_drawdown:.0%}",
    )
    add(
        "turnover_within_limit",
        turnover is not None and turnover <= policy.max_turnover,
        f"OOS turnover must not exceed {policy.max_turnover}",
    )
    if policy.require_cost_sensitivity_pass:
        add(
            "cost_sensitivity_pass",
            robustness.get("cost_sensitivity_pass") is True,
            "cost sensitivity must be present and passing",
        )
    if policy.require_subperiod_pass:
        add(
            "subperiod_stability",
            robustness.get("subperiod_pass") is True,
            "subperiod/regime stability must be present and passing",
        )
    if policy.require_bootstrap_positive_lower_bound:
        add(
            "bootstrap_ci_positive",
            bool(bootstrap.get("available")) and bool(bootstrap.get("total_return_lower_positive")),
            "block-bootstrap CI must be available with a positive lower bound",
        )
    add(
        "fill_rate",
        fill_rate is not None and fill_rate >= policy.min_quantity_fill_rate,
        f"OOS fill rate must be >= {policy.min_quantity_fill_rate:.0%}",
    )
    add(
        "incomplete_order_rate",
        incomplete_rate is not None and incomplete_rate <= policy.max_incomplete_order_rate,
        f"OOS incomplete-order rate must be <= {policy.max_incomplete_order_rate:.0%}",
    )
    if policy.require_approval_notes:
        effective_notes = (
            approval_notes if approval_notes is not None
            else (candidate.approval_notes if candidate else "")
        )
        has_notes = bool(effective_notes.strip())
        add(
            "human_approval_notes",
            has_notes,
            "human approval notes are required before a paper candidate advances",
        )

    failed = [g.name for g in gates if not g.passed]
    status = "paper_candidate" if not failed else "rejected"
    notes = [
        "Best attainable outcome is paper_candidate; this gate never authorizes real money.",
    ]
    if integrity.notes:
        notes.extend(f"ledger: {n}" for n in integrity.notes)
    return PromotionDecisionV2(
        candidate_id=candidate_id,
        status=status,
        gates=gates,
        failed_gates=failed,
        recomputed={
            "recomputed_psr": recomputed_psr,
            "recomputed_dsr": recomputed_dsr,
            "dsr_threshold": dsr_threshold,
            "effective_trial_count": integrity.effective_trial_count,
            "ledger_intact": integrity.is_intact,
        },
        real_money_authorized=False,
        notes=notes,
    )


def save_promotion_decision(path: str | Path, decision: PromotionDecisionV2) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(decision.to_dict(), indent=2), encoding="utf-8")
