from pathlib import Path

from quant_trade.trials.config import load_trial_policy
from quant_trade.trials.decisions import recommend_decision
from quant_trade.trials.drift import analyze_drift
from quant_trade.trials.expectations import load_expectations_from_research_artifacts
from quant_trade.trials.performance import calculate_trial_performance
from quant_trade.trials.registry import get_trial, load_trial_registry
from quant_trade.trials.review import generate_review_pack
from quant_trade.trials.schedule import calculate_trial_day, generate_review_calendar
from quant_trade.trials.tracker import collect_daily_records


def test_trial_registry_and_collection() -> None:
    registry = load_trial_registry(Path("tests/fixtures/trials/trial_registry_sample.yaml"))
    trial = get_trial(registry, "ts_momentum_90d")
    records = collect_daily_records(trial, [Path("tests/fixtures/trials")])
    assert records
    assert records[0].trial_id == "ts_momentum_90d"


def test_expectations_drift_and_decision_are_paper_only() -> None:
    registry = load_trial_registry(Path("tests/fixtures/trials/trial_registry_sample.yaml"))
    trial = get_trial(registry, "ts_momentum_90d")
    records = collect_daily_records(trial, [Path("tests/fixtures/trials")])
    metrics = calculate_trial_performance(records)
    expectations = load_expectations_from_research_artifacts(trial.research_run_dir)
    drift = analyze_drift(trial, metrics, expectations)
    policy = load_trial_policy(Path("tests/fixtures/trials/trial_policy_sample.yaml"))
    decision = recommend_decision(
        {
            "trial_id": trial.trial_id,
            "performance_summary": metrics,
            "drift_report": drift.to_dict(),
        },
        policy,
    )
    assert decision.real_money_approved is False
    assert drift.status in {"no_drift", "warning", "severe"}


def test_review_pack_and_calendar_outputs() -> None:
    registry = load_trial_registry(Path("tests/fixtures/trials/trial_registry_sample.yaml"))
    trial = get_trial(registry, "ts_momentum_90d")
    review_dir = generate_review_pack(
        trial, "weekly_review", artifact_roots=[Path("tests/fixtures/trials")]
    )
    calendar_path = generate_review_calendar(trial)
    assert (review_dir / "review_pack.md").exists()
    assert "PAPER-ONLY" in (review_dir / "review_pack.md").read_text(encoding="utf-8")
    assert calendar_path.exists()
    assert calculate_trial_day(trial.start_date, trial.start_date) == 1
