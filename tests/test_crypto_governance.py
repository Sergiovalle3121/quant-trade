"""Strict, holdout-bound tests for the crypto Gate-3 contract."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from quant_trade.metrics.statistics import return_moments
from quant_trade.research.crypto_governance import (
    HYPOTHESIS_STRATEGIES,
    HYPOTHESIS_TRIAL_BUDGETS,
    INDEPENDENT_TRADE_DEFINITION,
    CryptoGovernanceError,
    CryptoPromotionThresholds,
    ExperimentSpec,
    VerdictStatus,
    campaign_spec_compatibility_errors,
    canonical_digest,
    evaluate_crypto_promotion,
    evaluation_artifact_digest,
    independent_closed_round_trip_count,
    load_experiment_spec,
    seal_experiment_spec,
)
from quant_trade.research.ledger import append_trial


def _criteria(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "min_psr": 0.95,
        "min_dsr": 0.95,
        "max_pbo": 0.10,
        "min_walk_forward_windows": 4,
        "min_independent_trades": 30,
        "max_oos_drawdown": 0.25,
        "min_gross_alpha_cost_multiple": 2.0,
        "max_positive_pnl_share": 0.25,
        "min_capacity_canary_multiple": 2.0,
        "require_nonnegative_double_cost_half_fill": True,
        "canary_capital_usd": 500.0,
        "independent_trade_definition": INDEPENDENT_TRADE_DEFINITION,
    }
    values.update(overrides)
    return values


def _spec(**overrides: object) -> ExperimentSpec:
    payload: dict[str, object] = {
        "campaign_id": "crypto-lowcap-2026-08",
        "experiment_id": "h1-capacity-v1",
        "hypothesis_id": "H1",
        "hypothesis": "a capacity-constrained illiquidity premium exists net of costs",
        "strategy": "crypto_capacity_illiquidity",
        "strategy_params": {"top_n": 20, "rebalance_frequency": "annual"},
        "control": {
            "strategy": "crypto_capacity_illiquidity",
            "comparison_variable": "liquid_band",
            "liquid_band": True,
        },
        "refutation": "net excess is non-positive against either sealed benchmark",
        "dataset_id": "bybit-causal-panel-v2",
        "dataset_digest": "d" * 64,
        "dataset_status": "TRUSTED_CAUSAL",
        "gate0_status": "PASS",
        "gate0_verdict_digest": "4" * 64,
        "gate0_evidence_digest": "e" * 64,
        "code_commit": "a" * 40,
        "venue": "bybit",
        "venue_policy": {
            "venue": "bybit",
            "venues": ["bybit"],
            "market": "spot",
            "environment": "demo",
            "fee_source": "operator_capture_per_symbol",
        },
        "universe_policy": {
            "market_cap_min_usd": 10_000_000,
            "market_cap_max_usd": 1_000_000_000,
            "quote": "USDT",
        },
        "selection_start": "2017-08-17",
        "selection_end": "2023-11-28",
        "holdout_start": "2023-11-29",
        "holdout_end": "2026-08-09",
        "selection_panel_digest": "6" * 64,
        "holdout_panel_digest": "7" * 64,
        "holdout_seal_digest": "f" * 64,
        "holdout_authorization_digest": "8" * 64,
        "cohort_digest": "c" * 64,
        "split_policy": {
            "type": "sealed_date_holdout",
            "embargo_bars": 1,
            "panel_component_encoding": "canonical_panel_v1",
            "selection_panel_component": "selection_panel",
            "holdout_panel_component": "holdout_panel",
            "selection_market_events_component": "selection_market_events",
            "holdout_market_events_component": "holdout_market_events",
        },
        "walk_forward_policy": {
            "min_windows": 4,
            "selection_only": True,
            "cscv_partitions": 4,
        },
        "benchmarks": [
            {
                "benchmark_id": "btc_buy_and_hold",
                "instrument_id": "CMC:1",
                "min_bound_bars": 20,
            },
            {
                "benchmark_id": "eligible_equal_weight",
                "top_n": 20,
                "rebalance_frequency": "annual",
            },
        ],
        "execution_policy": {
            "decision_to_execution_bars": 1,
            "execution_price": "open",
            "partial_fills": True,
            "execution_limits_digest": "1" * 64,
        },
        "cost_policy": {
            "quantile": "p75",
            "fee_source": "venue_policy",
            "taker_fees_digest": "2" * 64,
            "cost_profiles_digest": "3" * 64,
            "initial_capital_usd": 1_000.0,
            "min_executable_fraction": 1.0,
            "delisting_recovery": 0.0,
        },
        "selection_criteria": _criteria(),
        "trial_budget": 4,
        "campaign_trial_budgets": dict(HYPOTHESIS_TRIAL_BUDGETS),
        "registered_at_utc": "2026-08-11T00:00:00Z",
    }
    payload.update(overrides)
    return ExperimentSpec(**payload)  # type: ignore[arg-type]


def _hypothesis_spec(hypothesis_id: str, *, trial_index: int = 0) -> ExperimentSpec:
    strategy = HYPOTHESIS_STRATEGIES[hypothesis_id]
    common: dict[str, object] = {
        "experiment_id": f"{hypothesis_id.lower()}-trial-{trial_index}",
        "hypothesis_id": hypothesis_id,
        "hypothesis": f"sealed {hypothesis_id} causal hypothesis",
        "strategy": strategy,
        "trial_budget": HYPOTHESIS_TRIAL_BUDGETS[hypothesis_id],
    }
    if hypothesis_id == "H1":
        common.update(
            {
                "strategy_params": {"top_n": 20, "rebalance_frequency": "annual"},
                "control": {
                    "strategy": strategy,
                    "comparison_variable": "liquid_band",
                    "liquid_band": True,
                },
            }
        )
    elif hypothesis_id == "H2":
        common.update(
            {
                "strategy_params": {"top_n": 20, "rebalance_frequency": "annual"},
                "control": {
                    "strategy": strategy,
                    "comparison_variable": "screen_off",
                    "screen_off": True,
                },
            }
        )
    elif hypothesis_id == "H3":
        common.update(
            {
                "strategy_params": {
                    "top_n": 20,
                    "rebalance_frequency": "annual",
                    "freeze_cohort": True,
                    "rebalance_once": False,
                },
                "control": {
                    "strategy": strategy,
                    "comparison_variable": "rebalance_once",
                    "rebalance_once": True,
                },
            }
        )
    elif hypothesis_id == "H4":
        common.update(
            {
                "strategy_params": {
                    "top_n": 20,
                    "rebalance_frequency": "annual",
                    "min_age_days": 730,
                    "exclude_left_censored": True,
                },
                "control": {
                    "strategy": strategy,
                    "comparison_variable": "min_age_days",
                    "min_age_days": 0,
                },
            }
        )
    else:  # pragma: no cover - test helper guard
        raise AssertionError(f"unsupported hypothesis {hypothesis_id}")
    return _spec(**common)


def _execution(
    timestamp: pd.Timestamp | str,
    instrument_id: str,
    side: str,
    quantity: float,
    *,
    status: str = "FILLED",
) -> dict[str, object]:
    return {
        "execution_timestamp": pd.Timestamp(timestamp).isoformat(),
        "instrument_id": instrument_id,
        "side": side,
        "filled_quantity": quantity,
        "status": status,
    }


def _nonoverlapping_round_trips(count: int) -> list[dict[str, object]]:
    base = pd.Timestamp("2023-11-29", tz="UTC")
    executions: list[dict[str, object]] = []
    for index in range(count):
        entry = base + pd.Timedelta(days=3 * index)
        executions.extend(
            (
                _execution(entry, "CMC:7", "buy", 1.0),
                _execution(entry + pd.Timedelta(days=1), "CMC:7", "sell", 1.0),
            )
        )
    return executions


def _passing_evidence(spec: ExperimentSpec) -> dict:
    reveal = {
        "seal_id": "crypto-holdout-v1",
        "seal": spec.holdout_seal_digest,
        "reason": "single final evaluation",
        "at_utc": "2026-08-11T01:00:00Z",
        "frozen_selection": {"experiment_spec_seal": spec.seal()},
        "schema_version": 2,
    }
    values = [1_000.0]
    for index in range(500):
        values.append(values[-1] * (1.01 if index % 2 else 1.02))
    candidate_returns = pd.Series(values).pct_change().dropna()
    timestamps = pd.date_range("2023-11-29", periods=len(values), freq="D", tz="UTC")
    candidate_run: dict[str, Any] = {
        "summary": {"total_return": values[-1] / values[0] - 1.0},
        "equity": [
            {"timestamp": timestamps[index].isoformat(), "value_usd": value}
            for index, value in enumerate(values)
        ],
        "executions": _nonoverlapping_round_trips(30),
        "rebalances": [],
    }
    control_values = [1_000.0 * (1.005**index) for index in range(len(values))]
    control_run: dict[str, Any] = {
        "summary": {"total_return": control_values[-1] / control_values[0] - 1.0},
        "equity": [
            {"timestamp": timestamps[index].isoformat(), "value_usd": value}
            for index, value in enumerate(control_values)
        ],
        "executions": [],
        "rebalances": [],
    }
    benchmark_runs: dict[str, dict[str, Any]] = {
        "btc_buy_and_hold": {
            "summary": {"total_return": control_values[-1] / control_values[0] - 1.0},
            "equity": control_run["equity"],
            "executions": [],
            "rebalances": [],
        },
        "eligible_equal_weight": {
            "summary": {"total_return": control_values[-1] / control_values[0] - 1.0},
            "equity": control_run["equity"],
            "executions": [],
            "rebalances": [],
        },
    }
    benchmark_digests = {
        benchmark_id: canonical_digest(payload) for benchmark_id, payload in benchmark_runs.items()
    }
    test_metrics = {
        **return_moments(candidate_returns),
        "max_drawdown": 0.0,
        "independent_trade_count": 30,
        "independent_trade_definition": INDEPENDENT_TRADE_DEFINITION,
    }
    evidence: dict[str, Any] = {
        "schema_version": 2,
        "phase": "HOLDOUT",
        "promotable": True,
        "campaign_id": spec.campaign_id,
        "experiment_id": spec.experiment_id,
        "hypothesis_id": spec.hypothesis_id,
        "experiment_spec_seal": spec.seal(),
        "dataset_id": spec.dataset_id,
        "dataset_digest": spec.dataset_digest,
        "dataset_status": spec.dataset_status,
        "gate0_status": spec.gate0_status,
        "gate0_verdict_digest": spec.gate0_verdict_digest,
        "gate0_evidence_digest": spec.gate0_evidence_digest,
        "code_commit": spec.code_commit,
        "venue": spec.venue,
        "run_id": "candidate-run",
        "holdout": {
            "seal_digest": spec.holdout_seal_digest,
            "authorization_digest": spec.holdout_authorization_digest,
            "reveal_digest": canonical_digest(reveal),
            "reveal_count": 1,
            "reveal_record": reveal,
            "test_range": [spec.holdout_start, spec.holdout_end],
        },
        "policy_bindings": {
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
            "benchmark_policy_digest": spec.benchmark_policy_digest,
            "cohort_digest": spec.cohort_digest,
        },
        "benchmark_artifact_digests": benchmark_digests,
        "candidate_result_digest": canonical_digest(candidate_run),
        "control_result_digest": canonical_digest(control_run),
        "test_metrics": test_metrics,
        "overfitting": {"pbo": 0.10, "windows": 4},
        "comparisons": {
            benchmark_id: {
                "artifact_digest": digest,
                "execution_policy_digest": spec.execution_policy_digest,
                "cost_policy_digest": spec.cost_policy_digest,
                "net_excess_return": (
                    candidate_run["summary"]["total_return"]
                    - benchmark_runs[benchmark_id]["summary"]["total_return"]
                ),
                "benchmark_max_drawdown": 0.0,
            }
            for benchmark_id, digest in benchmark_digests.items()
        },
        "economics": {"gross_alpha_return": 0.04, "total_cost_p95_return": 0.02},
        "stress": {"double_cost_half_fill_total_return": 0.0},
        "concentration": {
            "max_asset_positive_pnl_share": 0.25,
            "max_episode_positive_pnl_share": 0.25,
        },
        "capacity": {"capacity_usd": 1_000.0, "canary_capital_usd": 500.0},
        "runs": {
            "candidate": candidate_run,
            "control": control_run,
            "benchmarks": benchmark_runs,
        },
    }
    evidence["comparisons"]["sealed_control"] = {
        "artifact_digest": canonical_digest(control_run),
        "execution_policy_digest": spec.execution_policy_digest,
        "cost_policy_digest": spec.cost_policy_digest,
        "net_excess_return": (
            candidate_run["summary"]["total_return"] - control_run["summary"]["total_return"]
        ),
        "control_max_drawdown": 0.0,
    }
    evidence["artifact_digest"] = evaluation_artifact_digest(evidence)
    return evidence


def _campaign_rows(
    spec: ExperimentSpec,
    evidence: dict,
    *,
    candidate_sharpe: float | None = None,
    incomplete_distribution: bool = False,
    legacy: bool = False,
) -> list[dict]:
    rows: list[dict] = []
    index = 0
    for hypothesis_id, budget in HYPOTHESIS_TRIAL_BUDGETS.items():
        for local_index in range(budget):
            is_candidate = hypothesis_id == spec.hypothesis_id and local_index == 0
            metrics = (
                evidence["test_metrics"]
                if is_candidate
                else {"sharpe_per_period": 0.01 * (index + 1)}
            )
            sharpe = (
                float(evidence["test_metrics"]["sharpe_per_period"])
                if is_candidate and candidate_sharpe is None
                else candidate_sharpe
                if is_candidate
                else float(metrics["sharpe_per_period"])
            )
            row = {
                "schema_version": 2,
                "phase": "HOLDOUT" if is_candidate else "SELECTION",
                "campaign_id": spec.campaign_id,
                "experiment_id": (
                    spec.experiment_id
                    if hypothesis_id == spec.hypothesis_id
                    else f"{hypothesis_id}-experiment"
                ),
                "hypothesis_id": hypothesis_id,
                "experiment_spec_seal": (
                    spec.seal()
                    if hypothesis_id == spec.hypothesis_id
                    else canonical_digest({"hypothesis": hypothesis_id})
                ),
                "run_id": "candidate-run" if is_candidate else f"trial-{index}",
                "status": "evaluated",
                "source": "protected_crypto_runner",
                "dataset_digest": spec.dataset_digest,
                "code_commit": spec.code_commit,
                "artifact_digest": (
                    evidence["artifact_digest"]
                    if is_candidate
                    else canonical_digest({"artifact": index})
                ),
                "candidate_result_digest": (
                    evidence["candidate_result_digest"]
                    if is_candidate
                    else canonical_digest({"candidate": index})
                ),
                "control_result_digest": (
                    evidence["control_result_digest"]
                    if is_candidate
                    else canonical_digest({"control": index})
                ),
                "holdout_seal_digest": spec.holdout_seal_digest,
                "holdout_authorization_digest": spec.holdout_authorization_digest,
                "execution_policy_digest": spec.execution_policy_digest,
                "cost_policy_digest": spec.cost_policy_digest,
                "benchmark_policy_digest": spec.benchmark_policy_digest,
                "cohort_digest": spec.cohort_digest,
                "metrics_digest": (
                    canonical_digest(evidence["test_metrics"])
                    if is_candidate
                    else canonical_digest(metrics)
                ),
                "test_range": [spec.holdout_start, spec.holdout_end],
                "test_sharpe_per_period": sharpe,
            }
            if is_candidate:
                row.update(
                    {
                        "holdout_reveal_digest": evidence["holdout"].get("reveal_digest", "0" * 64),
                        "benchmark_artifacts_digest": canonical_digest(
                            evidence["benchmark_artifact_digests"]
                        ),
                    }
                )
                if legacy:
                    row["preregistration_seal"] = spec.seal()
            else:
                row["benchmark_artifacts_digest"] = canonical_digest(
                    {"trial": index, "benchmarks": True}
                )
            if incomplete_distribution and index == 14:
                row["status"] = "failed"
                row["test_sharpe_per_period"] = None
            rows.append(row)
            index += 1
    return rows


def _write_ledger(path: Path, rows: list[dict]) -> None:
    for row in rows:
        append_trial(None, row, registry_path=path)


def test_experiment_spec_is_deeply_immutable_and_seals_every_policy() -> None:
    params: dict[str, Any] = {
        "top_n": 20,
        "rebalance_frequency": "annual",
        "nested": {"window": 90},
    }
    spec = _spec(strategy_params=params)
    seal = spec.seal()
    params["top_n"] = 999
    params["nested"]["window"] = 1
    assert spec.strategy_params["top_n"] == 20
    assert spec.seal() == seal
    assert len(spec.execution_policy_digest) == 64
    assert len(spec.cost_policy_digest) == 64
    assert len(spec.benchmark_policy_digest) == 64
    with pytest.raises(TypeError):
        spec.strategy_params["top_n"] = 3  # type: ignore[index]
    assert replace(spec, notes=("filing metadata",)).seal() == seal


@pytest.mark.parametrize("hypothesis_id", tuple(HYPOTHESIS_STRATEGIES))
def test_hypothesis_strategy_mapping_is_exact(hypothesis_id: str) -> None:
    spec = _hypothesis_spec(hypothesis_id)
    assert spec.strategy == HYPOTHESIS_STRATEGIES[hypothesis_id]
    assert spec.control["strategy"] == spec.strategy
    with pytest.raises(CryptoGovernanceError, match=f"{hypothesis_id} strategy must be"):
        replace(spec, strategy="renamed_or_post_hoc_strategy")
    frequent = dict(spec.strategy_params)
    frequent["rebalance_frequency"] = "daily"
    with pytest.raises(CryptoGovernanceError, match="sealed annual frequency"):
        replace(spec, strategy_params=frequent)


@pytest.mark.parametrize(
    ("hypothesis_id", "comparison_variable"),
    [("H1", "liquid_band"), ("H2", "screen_off"), ("H3", "rebalance_once")],
)
def test_boolean_hypothesis_controls_have_the_sealed_causal_shape(
    hypothesis_id: str,
    comparison_variable: str,
) -> None:
    spec = _hypothesis_spec(hypothesis_id)
    bad_control = dict(spec.control)
    bad_control[comparison_variable] = False
    with pytest.raises(CryptoGovernanceError, match=f"control {comparison_variable} must be true"):
        replace(spec, control=bad_control)

    wrong_variable = dict(spec.control)
    wrong_variable["comparison_variable"] = "post_hoc_variable"
    with pytest.raises(CryptoGovernanceError, match="control.comparison_variable"):
        replace(spec, control=wrong_variable)


def test_h3_freezes_the_cohort_and_h4_uses_causal_uncensored_age() -> None:
    h3 = _hypothesis_spec("H3")
    h3_params = dict(h3.strategy_params)
    h3_params["freeze_cohort"] = False
    with pytest.raises(CryptoGovernanceError, match="freeze its cohort"):
        replace(h3, strategy_params=h3_params)

    h4 = _hypothesis_spec("H4")
    h4_params = dict(h4.strategy_params)
    h4_params["exclude_left_censored"] = False
    with pytest.raises(CryptoGovernanceError, match="exclude left-censored"):
        replace(h4, strategy_params=h4_params)
    bad_control = dict(h4.control)
    bad_control["min_age_days"] = 365
    with pytest.raises(CryptoGovernanceError, match="control min_age_days must be zero"):
        replace(h4, control=bad_control)


def test_all_15_campaign_specs_share_one_environment_and_policy() -> None:
    campaign = [
        _hypothesis_spec(hypothesis_id, trial_index=trial_index)
        for hypothesis_id, budget in HYPOTHESIS_TRIAL_BUDGETS.items()
        for trial_index in range(budget)
    ]
    assert len(campaign) == 15
    reference = campaign[0]
    assert campaign_spec_compatibility_errors(reference, campaign) == ()

    victim = campaign[-1]
    universe_policy = dict(victim.universe_policy)
    universe_policy["market_cap_min_usd"] = 20_000_000
    split_policy = dict(victim.split_policy)
    split_policy["selection_panel_component"] = "selection_panel_v2"
    walk_forward_policy = dict(victim.walk_forward_policy)
    walk_forward_policy["min_windows"] = 5
    selection_criteria = dict(victim.selection_criteria)
    selection_criteria["min_dsr"] = 0.96
    venue_policy = dict(victim.venue_policy)
    venue_policy["environment"] = "demo_alternate"
    mismatches: list[tuple[str, ExperimentSpec]] = [
        ("gate0_verdict_digest", replace(victim, gate0_verdict_digest="5" * 64)),
        ("gate0_evidence_digest", replace(victim, gate0_evidence_digest="9" * 64)),
        ("universe_policy", replace(victim, universe_policy=universe_policy)),
        ("selection_panel_digest", replace(victim, selection_panel_digest="a" * 64)),
        ("holdout_panel_digest", replace(victim, holdout_panel_digest="b" * 64)),
        ("split_policy", replace(victim, split_policy=split_policy)),
        ("walk_forward_policy", replace(victim, walk_forward_policy=walk_forward_policy)),
        ("selection_criteria", replace(victim, selection_criteria=selection_criteria)),
        ("venue_policy", replace(victim, venue_policy=venue_policy)),
        ("cohort_digest", replace(victim, cohort_digest="0" * 64)),
    ]
    for field_name, mismatch in mismatches:
        altered = [*campaign[:-1], mismatch]
        errors = campaign_spec_compatibility_errors(reference, altered)
        assert any(f"shared {field_name} mismatch" in error for error in errors)


def test_independent_trade_count_does_not_count_filled_legs() -> None:
    base = pd.Timestamp("2024-01-01", tz="UTC")
    executions = [
        _execution(base + pd.Timedelta(minutes=index), "CMC:7", "buy", 1.0) for index in range(14)
    ]
    executions.append(_execution(base + pd.Timedelta(minutes=15), "CMC:7", "sell", 14.0))
    assert len(executions) == 15
    assert independent_closed_round_trip_count(executions) == 1


def test_promotion_rederives_trade_episodes_from_candidate_executions() -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    base = pd.Timestamp("2024-01-01", tz="UTC")
    executions = [
        _execution(base + pd.Timedelta(minutes=index), "CMC:7", "buy", 1.0) for index in range(14)
    ]
    executions.append(_execution(base + pd.Timedelta(minutes=15), "CMC:7", "sell", 14.0))
    evidence["runs"]["candidate"]["executions"] = executions
    evidence["runs"]["candidate"]["summary"]["independent_trade_count"] = 30
    evidence["candidate_result_digest"] = canonical_digest(evidence["runs"]["candidate"])
    evidence["artifact_digest"] = evaluation_artifact_digest(evidence)

    verdict = evaluate_crypto_promotion(evidence, spec)
    assert "candidate_metrics_derivation" in verdict.failed_checks
    assert independent_closed_round_trip_count(executions) == 1


def test_partial_fills_and_terminal_close_form_one_episode() -> None:
    base = pd.Timestamp("2024-01-01", tz="UTC")
    executions = [
        _execution(base, "CMC:7", "buy", 0.4, status="PARTIALLY_FILLED"),
        _execution(base + pd.Timedelta(hours=1), "CMC:7", "buy", 0.6),
        _execution(base + pd.Timedelta(hours=2), "CMC:7", "sell", 0.3),
        _execution(base + pd.Timedelta(hours=3), "CMC:7", "sell", 0.2),
        _execution(
            base + pd.Timedelta(hours=4),
            "CMC:7",
            "sell",
            0.0,
            status="WRITTEN_DOWN",
        ),
    ]
    assert independent_closed_round_trip_count(executions) == 1


def test_thirty_closed_nonoverlapping_round_trips_meet_the_boundary() -> None:
    executions = _nonoverlapping_round_trips(30)
    assert len(executions) == 60
    assert independent_closed_round_trip_count(executions) == 30
    assert _criteria()["min_independent_trades"] == 30


def _selection_artifact_with_equity(
    spec: ExperimentSpec,
    *,
    run_id: str,
    trial_index: int,
) -> dict[str, Any]:
    observations = 41
    timestamps = pd.date_range(
        "2017-08-17",
        "2023-11-28",
        periods=observations,
        tz="UTC",
    )
    sample = pd.Series(range(observations - 1), dtype=float)
    returns = pd.Series(np.sin(sample / 3.0), dtype=float) * 0.00001 + (trial_index + 1) * 0.00005
    values = [1_000.0]
    for value in returns:
        values.append(values[-1] * (1.0 + float(value)))
    candidate = {
        "summary": {"total_return": values[-1] / values[0] - 1.0},
        "equity": [
            {"timestamp": timestamp.isoformat(), "value_usd": value}
            for timestamp, value in zip(timestamps, values, strict=True)
        ],
        "executions": [],
        "rebalances": [],
    }
    derived = {
        **return_moments(pd.Series(values).pct_change().dropna()),
        "max_drawdown": 0.0,
        "independent_trade_count": 0,
        "independent_trade_definition": INDEPENDENT_TRADE_DEFINITION,
    }
    control = candidate
    benchmarks = {
        "btc_buy_and_hold": candidate,
        "eligible_equal_weight": candidate,
    }
    benchmark_digests = {
        benchmark_id: canonical_digest(payload) for benchmark_id, payload in benchmarks.items()
    }
    artifact: dict[str, Any] = {
        "phase": "SELECTION",
        "promotable": False,
        "campaign_id": spec.campaign_id,
        "experiment_id": spec.experiment_id,
        "hypothesis_id": spec.hypothesis_id,
        "experiment_spec_seal": spec.seal(),
        "run_id": run_id,
        "dataset_digest": spec.dataset_digest,
        "code_commit": spec.code_commit,
        "selection_panel_digest": spec.selection_panel_digest,
        "holdout_seal_digest": spec.holdout_seal_digest,
        "holdout_authorization_digest": spec.holdout_authorization_digest,
        "holdout_reveal_count": 0,
        "selection_range": [spec.selection_start, spec.selection_end],
        "policy_bindings": {
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
            "benchmark_policy_digest": spec.benchmark_policy_digest,
            "cohort_digest": spec.cohort_digest,
        },
        "candidate_result_digest": canonical_digest(candidate),
        "control_result_digest": canonical_digest(control),
        "benchmark_artifact_digests": benchmark_digests,
        "test_metrics": derived,
        "runs": {
            "candidate": candidate,
            "control": control,
            "benchmarks": benchmarks,
        },
    }
    artifact["artifact_digest"] = evaluation_artifact_digest(artifact)
    return artifact


def test_verified_overfitting_uses_bound_selection_return_paths() -> None:
    import quant_trade.research.crypto_governance as governance

    campaign = [
        _hypothesis_spec(hypothesis_id, trial_index=trial_index)
        for hypothesis_id, budget in HYPOTHESIS_TRIAL_BUDGETS.items()
        for trial_index in range(budget)
    ]
    records: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}
    for index, trial_spec in enumerate(campaign):
        run_id = f"selection-{index:02d}"
        artifact = _selection_artifact_with_equity(
            trial_spec,
            run_id=run_id,
            trial_index=index,
        )
        artifacts[run_id] = artifact
        records.append({"run_id": run_id})
    spec = replace(
        campaign[0],
        walk_forward_policy={
            "min_windows": 4,
            "selection_only": True,
            "cscv_partitions": 8,
        },
    )
    # The helper is exercised directly because the public verdict additionally
    # requires durable holdout and ledger I/O, which is orthogonal here.
    derived, check = governance._derive_verified_overfitting(
        spec=spec,
        selection_records=records,
        artifact_map=artifacts,
        artifacts_verified=True,
    )
    assert check.status is VerdictStatus.PASS
    assert derived is not None
    assert derived["pbo"] == 0.0
    assert derived["windows"] == 4

    artifacts.pop("selection-14")
    missing, missing_check = governance._derive_verified_overfitting(
        spec=spec,
        selection_records=records,
        artifact_map=artifacts,
        artifacts_verified=True,
    )
    assert missing is None
    assert missing_check.status is VerdictStatus.INSUFFICIENT_EVIDENCE

    artifacts["selection-14"] = _selection_artifact_with_equity(
        campaign[-1], run_id="selection-14", trial_index=14
    )
    artifacts["selection-14"]["runs"]["candidate"]["equity"][-1]["timestamp"] = (
        "2023-11-29T00:00:00+00:00"
    )
    future, future_check = governance._derive_verified_overfitting(
        spec=spec,
        selection_records=records,
        artifact_map=artifacts,
        artifacts_verified=True,
    )
    assert future is None
    assert future_check.status is VerdictStatus.INSUFFICIENT_EVIDENCE


def test_verified_overfitting_requires_passing_walk_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_trade.research.crypto_governance as governance

    spec = _spec()
    records = [{"run_id": f"selection-{index:02d}"} for index in range(15)]
    artifacts = {
        record["run_id"]: _selection_artifact_with_equity(
            spec,
            run_id=record["run_id"],
            trial_index=index,
        )
        for index, record in enumerate(records)
    }

    def failed_walk_forward(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "digest": "d" * 64,
            "pbo": 0.0,
            "windows": 4,
            "walk_forward": {
                "walk_forward_pbo": 0.25,
                "decision": "NO-GO",
            },
        }

    monkeypatch.setattr(governance, "derive_overfitting_evidence", failed_walk_forward)
    derived, check = governance._derive_verified_overfitting(
        spec=spec,
        selection_records=records,
        artifact_map=artifacts,
        artifacts_verified=True,
    )
    assert derived is not None
    assert check.status is VerdictStatus.NO_GO


def test_gate3_inputs_are_payload_bound_to_panel_and_execution_policy() -> None:
    import quant_trade.research.crypto_governance as governance

    panel_payload = {
        "columns": ["instrument_id", "mark_price", "timestamp"],
        "records": [
            {
                "instrument_id": "CMC:2",
                "mark_price": 10.0,
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
        ],
    }
    limits_payload = {
        "CMC:2": {
            "tick_size": 0.01,
            "quantity_step": 0.001,
            "min_notional_usd": 1.0,
            "median_daily_notional_20d_usd": 100_000.0,
            "executable_depth_usd": 10_000.0,
        }
    }
    panel_digest = canonical_digest(panel_payload)
    limits_digest = canonical_digest(limits_payload)
    execution_policy = dict(_spec().execution_policy)
    execution_policy["execution_limits_digest"] = limits_digest
    spec = _spec(
        holdout_panel_digest=panel_digest,
        execution_policy=execution_policy,
    )
    evidence = {
        "gate3_inputs": {
            "panel": {
                "encoding": "canonical_panel_v1",
                "payload": panel_payload,
                "digest": panel_digest,
            },
            "execution_limits": {
                "payload": limits_payload,
                "digest": limits_digest,
            },
        }
    }
    panel, panel_check = governance._verified_gate3_panel_input(evidence, spec)
    limits, limits_check = governance._verified_gate3_execution_limits_input(evidence, spec)
    assert panel is not None and len(panel) == 1
    assert limits == limits_payload
    assert panel_check.status is VerdictStatus.PASS
    assert limits_check.status is VerdictStatus.PASS

    tampered = json.loads(json.dumps(evidence))
    tampered["gate3_inputs"]["execution_limits"]["payload"]["CMC:2"][
        "median_daily_notional_20d_usd"
    ] = 999_999_999.0
    _, tampered_check = governance._verified_gate3_execution_limits_input(tampered, spec)
    assert tampered_check.status is VerdictStatus.NO_GO


def test_gate3_detail_digest_tamper_is_no_go_and_missing_is_insufficient() -> None:
    import quant_trade.research.crypto_governance as governance

    spec = _spec()
    evidence = _passing_evidence(spec)
    evidence["economics"] = {
        "gross_alpha_return": 999.0,
        "total_cost_p95_return": 0.00001,
        "digest": "0" * 64,
    }
    verified, checks = governance._derive_verified_gate3_blocks(
        evidence,
        spec,
    )
    assert "economics" not in verified
    by_name = {check.name: check for check in checks}
    assert by_name["verified_economics_derivation"].status is VerdictStatus.NO_GO
    assert by_name["verified_stress_derivation"].status is VerdictStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "overrides",
    [
        {"dataset_digest": "not-a-digest"},
        {"dataset_status": "UNVALIDATED"},
        {"gate0_status": "INSUFFICIENT_EVIDENCE"},
        {"holdout_seal_digest": "bad"},
        {"selection_panel_digest": "bad"},
        {"holdout_panel_digest": "bad"},
        {"cohort_digest": "bad"},
        {
            "execution_policy": {
                "decision_to_execution_bars": 1,
                "execution_price": "open",
                "partial_fills": True,
            }
        },
        {"cost_policy": {"quantile": "p75"}},
        {"selection_criteria": _criteria(min_dsr=0.94)},
        {"selection_criteria": _criteria(min_independent_trades=29)},
        {"selection_criteria": _criteria(require_nonnegative_double_cost_half_fill=False)},
        {"walk_forward_policy": {"min_windows": 4, "selection_only": True}},
        {"benchmarks": [{"benchmark_id": "btc_buy_and_hold"}]},
        {"campaign_trial_budgets": {"H1": 4, "H2": 4, "H3": 4, "H4": 4}},
    ],
)
def test_experiment_spec_refuses_incomplete_or_weakened_contracts(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(CryptoGovernanceError):
        _spec(**overrides)


def test_experiment_spec_requires_distinct_phase_market_event_components() -> None:
    missing = dict(_spec().split_policy)
    missing.pop("selection_market_events_component")
    with pytest.raises(CryptoGovernanceError, match="selection_market_events_component"):
        _spec(split_policy=missing)

    aliased = dict(_spec().split_policy)
    aliased["holdout_market_events_component"] = aliased["selection_market_events_component"]
    with pytest.raises(CryptoGovernanceError, match="must be distinct"):
        _spec(split_policy=aliased)


def test_experiment_spec_seal_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    spec = _spec()
    path, seal = seal_experiment_spec(tmp_path, spec)
    assert load_experiment_spec(tmp_path).seal() == seal
    with pytest.raises(CryptoGovernanceError, match="never rewritten"):
        seal_experiment_spec(tmp_path, spec)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["strategy_params"]["top_n"] = 19
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CryptoGovernanceError, match="seal mismatch"):
        load_experiment_spec(tmp_path)


def test_self_attested_holdout_and_campaign_cannot_pass(tmp_path: Path) -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence))
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert verdict.status is VerdictStatus.INSUFFICIENT_EVIDENCE, verdict.to_dict()
    assert verdict.real_money_authorized is False
    assert "annual_independent_cycle_feasibility" in verdict.missing_checks
    annual_check = next(
        check for check in verdict.checks if check.name == "annual_independent_cycle_feasibility"
    )
    assert annual_check.actual == 4
    assert annual_check.threshold == 30
    assert "persisted_holdout_evidence" in verdict.missing_checks
    assert "campaign_experiment_specs" in verdict.missing_checks
    assert "selection_trial_artifact_bindings" in verdict.missing_checks


def test_missing_holdout_binding_is_insufficient(tmp_path: Path) -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    del evidence["holdout"]["reveal_digest"]
    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence))
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert verdict.status is VerdictStatus.INSUFFICIENT_EVIDENCE
    assert "holdout_reveal_digest" in verdict.missing_checks


def test_tampered_artifact_and_candidate_metric_mismatch_are_no_go(tmp_path: Path) -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence, candidate_sharpe=0.01))
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert verdict.status is VerdictStatus.INSUFFICIENT_EVIDENCE
    assert "exact_candidate_ledger_binding" in verdict.failed_checks

    evidence["comparisons"]["btc_buy_and_hold"]["net_excess_return"] = 999.0
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert verdict.status is VerdictStatus.INSUFFICIENT_EVIDENCE
    assert "evaluation_artifact_integrity" in verdict.failed_checks


def test_legacy_seal_is_rejected_even_on_a_hash_chained_row(tmp_path: Path) -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence, legacy=True))
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert "strict_crypto_ledger_schema" in verdict.failed_checks


def test_dsr_is_insufficient_until_all_15_verified_sharpes_exist(tmp_path: Path) -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence, incomplete_distribution=True))
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert verdict.status is VerdictStatus.INSUFFICIENT_EVIDENCE
    assert "verified_dsr_distribution" in verdict.missing_checks
    assert "deflated_sharpe" in verdict.missing_checks


def test_thresholds_cannot_be_weakened_or_overridden_publicly(tmp_path: Path) -> None:
    with pytest.raises(CryptoGovernanceError):
        CryptoPromotionThresholds(min_dsr=0.0)
    spec = _spec()
    evidence = _passing_evidence(spec)
    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence))
    with pytest.raises(TypeError):
        evaluate_crypto_promotion(  # type: ignore[call-arg]
            evidence,
            spec,
            ledger_path=ledger,
            thresholds=CryptoPromotionThresholds(),
        )


def test_missing_or_unverified_ledger_is_fail_closed(tmp_path: Path) -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    missing = evaluate_crypto_promotion(evidence, spec)
    assert missing.status is VerdictStatus.INSUFFICIENT_EVIDENCE

    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence))
    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    corrupt = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert "ledger_integrity" in corrupt.failed_checks
