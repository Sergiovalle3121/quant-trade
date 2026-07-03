from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .exceptions import TrialNotFoundError, TrialValidationError
from .models import TrialConfig, utc_now

ALLOWED_STRATEGIES = {
    "ts_momentum",
    "ma_trend",
    "equal_weight",
    "sma_crossover",
    "buy_and_hold",
    "mean_reversion",
}


def validate_trial(trial: TrialConfig) -> None:
    if trial.status not in {"planned", "active", "paused", "completed", "rejected", "retired"}:
        raise TrialValidationError("unknown trial status")
    if trial.strategy_name not in ALLOWED_STRATEGIES:
        raise TrialValidationError(f"unknown strategy: {trial.strategy_name}")
    if trial.trial_length_days not in {30, 60, 90}:
        raise TrialValidationError("trial_length_days must be 30, 60, or 90")
    if trial.start_date >= trial.planned_end_date:
        raise TrialValidationError("start_date must be before planned_end_date")
    if not trial.paper_session_id:
        raise TrialValidationError("paper_session_id is required")
    if not trial.paper_config_path or not trial.ops_config_path:
        raise TrialValidationError("paper_config_path and ops_config_path are required")


def load_trial_registry(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    trials = [TrialConfig.from_dict(x) for x in raw.get("trials", [])]
    for t in trials:
        validate_trial(t)
    reg = {"path": str(p), "policy_path": raw.get("policy_path"), "trials": trials}
    out = Path("outputs/trials/registry")
    out.mkdir(parents=True, exist_ok=True)
    (out / "trial_registry_snapshot.json").write_text(
        json.dumps([t.to_dict() for t in trials], indent=2), encoding="utf-8"
    )
    (out / "trial_registry_summary.md").write_text(
        "\n".join(["# Trial Registry", "", *[f"- {t.trial_id}: {t.status}" for t in trials]]),
        encoding="utf-8",
    )
    return reg


def list_trials(registry: dict[str, Any]) -> list[TrialConfig]:
    return list(registry.get("trials", []))


def get_trial(registry: dict[str, Any], trial_id: str) -> TrialConfig:
    for t in list_trials(registry):
        if t.trial_id == trial_id:
            return t
    raise TrialNotFoundError(f"unknown trial: {trial_id}")


def find_trials_by_status(registry: dict[str, Any], status: str) -> list[TrialConfig]:
    return [t for t in list_trials(registry) if t.status == status]


def find_trials_by_session(registry: dict[str, Any], session_id: str) -> list[TrialConfig]:
    return [t for t in list_trials(registry) if t.paper_session_id == session_id]


def update_trial_status(
    trial_id: str,
    status: str,
    notes: str,
    registry_path: Path | str = "configs/trials/trial_registry.yaml",
) -> Path:
    reg = load_trial_registry(registry_path)
    t = get_trial(reg, trial_id)
    t.status = status  # type: ignore[assignment]
    validate_trial(t)
    out = Path("outputs/trials") / trial_id / "trial_events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "event": "status_update",
                    "trial_id": trial_id,
                    "status": status,
                    "notes": notes,
                    "created_at_utc": utc_now(),
                }
            )
            + "\n"
        )
    return out


def create_trial_from_candidate(
    candidate_file: Path | str, candidate_id: str, policy: object | None = None
) -> TrialConfig:
    items = json.loads(Path(candidate_file).read_text(encoding="utf-8"))
    raw = next((x for x in items if x.get("candidate_id") == candidate_id), None)
    if raw is None:
        raise TrialNotFoundError("candidate_id not found")
    from datetime import date, timedelta

    start = date.today()
    length = 90
    return TrialConfig(
        trial_id=f"{candidate_id}_90d",
        display_name=f"{raw.get('name', candidate_id)} 90D Trial",
        status="planned",
        candidate_id=candidate_id,
        paper_session_id=f"{raw.get('name', candidate_id)}_paper",
        strategy_name=raw.get("strategy_name", "ts_momentum"),
        strategy_params=raw.get("strategy_params", {}),
        universe=raw.get("universe", ["SPY"]),
        benchmark=raw.get("benchmark", "SPY"),
        paper_config_path="configs/paper/sample.yaml",
        ops_config_path="configs/ops/sample.yaml",
        research_run_dir=raw.get("research_run_dir"),
        start_date=start,
        planned_end_date=start + timedelta(days=length),
        trial_length_days=length,
        review_frequency="weekly",
        timezone="UTC",
        owner="research",
        reviewer="human",
        initial_paper_equity=100000.0,
        expected_rebalance_frequency="monthly",
        expected_turnover_range=(0.0, 0.5),
        tags=["candidate"],
        notes="Created from candidate; paper-only.",
    )
