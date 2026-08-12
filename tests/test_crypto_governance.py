"""Strict, holdout-bound tests for the crypto Gate-3 contract."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from quant_trade.metrics.statistics import return_moments
from quant_trade.research.crypto_governance import (
    HYPOTHESIS_TRIAL_BUDGETS,
    CryptoGovernanceError,
    CryptoPromotionThresholds,
    ExperimentSpec,
    VerdictStatus,
    canonical_digest,
    evaluate_crypto_promotion,
    evaluation_artifact_digest,
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
        "control": {"strategy": "crypto_capacity_illiquidity", "liquid_band": True},
        "refutation": "net excess is non-positive against either sealed benchmark",
        "dataset_id": "bybit-causal-panel-v2",
        "dataset_digest": "d" * 64,
        "dataset_status": "TRUSTED_CAUSAL",
        "gate0_status": "PASS",
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
        "cohort_digest": "c" * 64,
        "split_policy": {"type": "sealed_date_holdout", "embargo_bars": 1},
        "walk_forward_policy": {"min_windows": 4, "selection_only": True},
        "benchmarks": [
            {"benchmark_id": "btc_buy_and_hold", "instrument_id": "CMC:1"},
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
    candidate_run = {
        "summary": {"total_return": 0.20},
        "equity": [
            {"timestamp": f"day-{index}", "value_usd": value} for index, value in enumerate(values)
        ],
        "executions": [{"filled_quantity": 1.0} for _ in range(30)],
        "rebalances": [],
    }
    benchmark_runs = {
        "btc_buy_and_hold": {
            "summary": {"total_return": 0.10},
            "equity": [],
            "executions": [],
            "rebalances": [],
        },
        "eligible_equal_weight": {
            "summary": {"total_return": 0.05},
            "equity": [],
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
    }
    evidence = {
        "schema_version": 2,
        "campaign_id": spec.campaign_id,
        "experiment_id": spec.experiment_id,
        "hypothesis_id": spec.hypothesis_id,
        "experiment_spec_seal": spec.seal(),
        "dataset_id": spec.dataset_id,
        "dataset_digest": spec.dataset_digest,
        "dataset_status": spec.dataset_status,
        "gate0_status": spec.gate0_status,
        "gate0_evidence_digest": spec.gate0_evidence_digest,
        "code_commit": spec.code_commit,
        "venue": spec.venue,
        "run_id": "candidate-run",
        "holdout": {
            "seal_digest": spec.holdout_seal_digest,
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
        "test_metrics": test_metrics,
        "overfitting": {"pbo": 0.10, "windows": 4},
        "comparisons": {
            benchmark_id: {
                "artifact_digest": digest,
                "execution_policy_digest": spec.execution_policy_digest,
                "cost_policy_digest": spec.cost_policy_digest,
                "net_excess_return": 0.10 if benchmark_id == "btc_buy_and_hold" else 0.15,
                "benchmark_max_drawdown": -0.30 if benchmark_id == "btc_buy_and_hold" else -0.20,
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
        "runs": {"candidate": candidate_run, "benchmarks": benchmark_runs},
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
                        "holdout_seal_digest": spec.holdout_seal_digest,
                        "holdout_reveal_digest": evidence["holdout"].get("reveal_digest", "0" * 64),
                        "benchmark_artifacts_digest": canonical_digest(
                            evidence["benchmark_artifact_digests"]
                        ),
                    }
                )
                if legacy:
                    row["preregistration_seal"] = spec.seal()
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
    params = {"top_n": 20, "nested": {"window": 90}}
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
        {"benchmarks": [{"benchmark_id": "btc_buy_and_hold"}]},
        {"campaign_trial_budgets": {"H1": 4, "H2": 4, "H3": 4, "H4": 4}},
    ],
)
def test_experiment_spec_refuses_incomplete_or_weakened_contracts(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(CryptoGovernanceError):
        _spec(**overrides)


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


def test_complete_holdout_bound_evidence_and_verified_campaign_pass(tmp_path: Path) -> None:
    spec = _spec()
    evidence = _passing_evidence(spec)
    ledger = tmp_path / "crypto-ledger.jsonl"
    _write_ledger(ledger, _campaign_rows(spec, evidence))
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert verdict.status is VerdictStatus.PASS, verdict.to_dict()
    assert verdict.real_money_authorized is False
    assert verdict.recomputed["dsr_trial_count"] == 15


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
    assert verdict.status is VerdictStatus.NO_GO
    assert "exact_candidate_ledger_binding" in verdict.failed_checks

    evidence["comparisons"]["btc_buy_and_hold"]["net_excess_return"] = 999.0
    verdict = evaluate_crypto_promotion(evidence, spec, ledger_path=ledger)
    assert verdict.status is VerdictStatus.NO_GO
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
