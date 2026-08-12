from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from quant_trade.costs.crypto_lowcap import DEFAULT_TIER_PROFILES, CostInput
from quant_trade.data.crypto_manifest import (
    CausalValidationEvidence,
    CryptoDatasetManifest,
    CryptoManifestError,
    component_hashes,
)
from quant_trade.ops.crypto_gates import (
    CryptoGateError,
    Gate0Evidence,
    VenuePolicy,
    evaluate_gate0,
)
from quant_trade.research.crypto_evaluator import ExecutionLimits
from quant_trade.research.crypto_governance import (
    HYPOTHESIS_TRIAL_BUDGETS,
    CryptoGovernanceError,
    ExperimentSpec,
    evaluation_artifact_digest,
)
from quant_trade.research.crypto_runner import (
    RevealedHoldoutContext,
    SelectionContext,
    canonical_panel_digest,
    cohort_members_digest,
    cost_profiles_digest,
    execution_limits_digest,
    run_protected_crypto_evaluation,
    run_protected_crypto_selection,
    taker_fees_digest,
)
from quant_trade.research.holdout_seal import HoldoutSeal


def _panel(start: str = "2024-01-01") -> pd.DataFrame:
    rows = []
    for day_index, day in enumerate(pd.date_range(start, periods=4, tz="UTC")):
        for symbol, base, cap, rank in (
            ("CMC:1", 40_000.0, 2_000_000_000.0, 1),
            ("CMC:2", 10.0, 100_000_000.0, 50),
        ):
            price = base * (1.0 + 0.02 * day_index)
            rows.append(
                {
                    "timestamp": day,
                    "symbol": symbol,
                    "venue": "bybit",
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "mark_price": price,
                    "volume": 1_000_000.0,
                    "venue_turnover_usd": 10_000_000.0,
                    "market_cap_usd": cap,
                    "cmc_rank": rank,
                    "eligible_to_open": symbol != "CMC:1",
                    "tradable": True,
                    "data_status": "VALID",
                    "market_event": "NONE",
                }
            )
    return pd.DataFrame(rows)


def _gate0_evidence() -> Gate0Evidence:
    return Gate0Evidence(
        venue="bybit",
        environment="demo",
        kyc_mexico_approved=True,
        contractual_entity_identified=True,
        spot_account_enabled=True,
        api_access_enabled=True,
        dedicated_subaccount_active=True,
        ip_allowlist_active=True,
        read_permission_enabled=True,
        spot_permission_enabled=True,
        withdrawal_permission_disabled=True,
        transfer_permission_disabled=True,
        margin_permission_disabled=True,
        derivatives_permission_disabled=True,
        loan_permission_disabled=True,
        fee_rate_captured_per_symbol=True,
        minimum_deposit_test_passed=True,
        minimum_withdrawal_test_passed=True,
        dataset_venue="bybit",
        cost_venue="bybit",
        planned_execution_venue="bybit",
    )


def _manifest(provenance_root: Path) -> CryptoDatasetManifest:
    provenance_root.mkdir(parents=True)
    panel_component = provenance_root / "panel"
    panel_component.write_bytes(b"synthetic causal panel component")
    return CryptoDatasetManifest(
        dataset_id="bybit-causal-panel-v2",
        status="TRUSTED_CAUSAL",
        venue="bybit",
        market="spot",
        quote_asset="USDT",
        timezone="UTC",
        start_date="2017-08-17",
        end_date="2024-01-04",
        rows=8,
        instruments=2,
        schema_version=2,
        code_commit="a" * 40,
        policy={"single_venue": True},
        components=component_hashes({"panel": panel_component}),
        component_provenance={"panel": "panel"},
        causal_validation=CausalValidationEvidence(
            prefix_invariance_passed=True,
            fixed_venue_passed=True,
            stable_identity_and_rename_passed=True,
            unique_and_ambiguous_price_binding_passed=True,
            causal_warmup_passed=True,
            rank_exit_reentry_passed=True,
            gap_and_halt_semantics_passed=True,
            explicit_delisting_semantics_passed=True,
        ),
        gap_summary={"unexplained": 0},
        terms_status="research-only",
    )


def _criteria() -> dict[str, object]:
    return {
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


def _setup(
    tmp_path: Path,
) -> tuple[
    CryptoDatasetManifest,
    Path,
    object,
    ExperimentSpec,
    RevealedHoldoutContext,
    dict[str, ExecutionLimits],
    dict[str, CostInput],
]:
    provenance_root = tmp_path / "provenance"
    manifest = _manifest(provenance_root)
    gate0 = evaluate_gate0(VenuePolicy(), _gate0_evidence())
    cohort = ["CMC:2"]
    limits = {
        symbol: ExecutionLimits(tick_size=0.01, quantity_step=0.001, min_notional_usd=1.0)
        for symbol in ("CMC:1", "CMC:2")
    }
    fees = {
        symbol: CostInput(
            name=f"{symbol}_account_taker_fee",
            value_bps=10.0,
            evidence_class="REAL_ACCOUNT_SPECIFIC",
            source="Bybit /v5/account/fee-rate",
            raw_sha256=("1" if symbol == "CMC:1" else "2") * 64,
        )
        for symbol in ("CMC:1", "CMC:2")
    }
    holdout_panel = _panel()
    selection_panel = _panel("2023-12-28")
    seal = HoldoutSeal(
        seal_id="crypto-holdout-v1",
        dataset_id=manifest.dataset_id,
        dataset_digest=manifest.digest(),
        selection_start="2023-12-28",
        selection_end="2023-12-31",
        holdout_start="2024-01-01",
        holdout_end="2024-01-04",
        rationale="one final untouched evaluation",
        sealed_at_utc="2023-12-31T00:00:00Z",
        sealed_at_commit="a" * 40,
    )
    spec = ExperimentSpec(
        campaign_id="crypto-lowcap-2026-08",
        experiment_id="h1-capacity-v1",
        hypothesis_id="H1",
        hypothesis="capacity premium",
        strategy="crypto_capacity_illiquidity",
        strategy_params={
            "top_n": 1,
            "rebalance_frequency": "daily",
            "liquidity_window": 2,
        },
        control={"liquid_band": True},
        refutation="non-positive net excess",
        dataset_id=manifest.dataset_id,
        dataset_digest=manifest.digest(),
        dataset_status="TRUSTED_CAUSAL",
        gate0_status="PASS",
        gate0_evidence_digest=gate0.digest(),
        code_commit=manifest.code_commit,
        venue="bybit",
        venue_policy={
            "venue": "bybit",
            "venues": ["bybit"],
            "market": "spot",
            "environment": "demo",
            "fee_source": "operator_capture_per_symbol",
        },
        universe_policy={
            "market_cap_min_usd": 10_000_000,
            "market_cap_max_usd": 1_000_000_000,
            "quote": "USDT",
        },
        selection_start=seal.selection_start,
        selection_end=seal.selection_end,
        holdout_start=seal.holdout_start,
        holdout_end=seal.holdout_end,
        selection_panel_digest=canonical_panel_digest(selection_panel),
        holdout_panel_digest=canonical_panel_digest(holdout_panel),
        holdout_seal_digest=seal.seal(),
        cohort_digest=cohort_members_digest(cohort),
        split_policy={"type": "sealed_date_holdout", "embargo_bars": 1},
        walk_forward_policy={"min_windows": 4, "selection_only": True},
        benchmarks=[
            {"benchmark_id": "btc_buy_and_hold", "instrument_id": "CMC:1"},
            {
                "benchmark_id": "eligible_equal_weight",
                "top_n": 1,
                "rebalance_frequency": "annual",
            },
        ],
        execution_policy={
            "decision_to_execution_bars": 1,
            "execution_price": "open",
            "partial_fills": True,
            "execution_limits_digest": execution_limits_digest(limits),
        },
        cost_policy={
            "quantile": "p75",
            "fee_source": "operator_capture_per_symbol",
            "taker_fees_digest": taker_fees_digest(fees),
            "cost_profiles_digest": cost_profiles_digest(DEFAULT_TIER_PROFILES),
            "initial_capital_usd": 1_000.0,
            "min_executable_fraction": 1.0,
            "delisting_recovery": 0.0,
        },
        selection_criteria=_criteria(),
        trial_budget=4,
        campaign_trial_budgets=dict(HYPOTHESIS_TRIAL_BUDGETS),
        registered_at_utc="2023-12-31T00:00:00Z",
    )
    reveal = {
        "seal_id": seal.seal_id,
        "seal": seal.seal(),
        "reason": "single final evaluation",
        "at_utc": "2024-01-05T00:00:00Z",
        "frozen_selection": {"experiment_spec_seal": spec.seal()},
        "schema_version": 2,
    }
    context = RevealedHoldoutContext(seal, reveal, 1, holdout_panel)
    return manifest, provenance_root, gate0, spec, context, limits, fees


def test_protected_runner_executes_candidate_and_both_benchmarks_with_bindings(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    run = run_protected_crypto_evaluation(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        holdout=context,
        cohort_members=["CMC:2"],
        run_id="candidate-run",
        execution_limits=limits,
        taker_fees=fees,
    )
    assert set(run.benchmark_results) == {"btc_buy_and_hold", "eligible_equal_weight"}
    assert run.artifact_digest == evaluation_artifact_digest(run.artifact)
    assert run.artifact["holdout"]["test_range"] == ["2024-01-01", "2024-01-04"]
    assert run.artifact["policy_bindings"]["execution_policy_digest"] == (
        spec.execution_policy_digest
    )
    row = run.ledger_record()
    assert row["artifact_digest"] == run.artifact_digest
    assert row["test_sharpe_per_period"] == run.artifact["test_metrics"]["sharpe_per_period"]
    assert "preregistration_seal" not in row


def test_runner_rejects_untrusted_or_mismatched_manifest_and_gate0(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    with pytest.raises(CryptoGovernanceError, match="manifest identity/digest"):
        run_protected_crypto_evaluation(
            manifest=replace(manifest, notes=("changes digest",)),
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rehashes_manifest_components_before_any_evaluation(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    (provenance_root / "panel").write_bytes(b"tampered after the manifest was sealed")
    with pytest.raises(CryptoManifestError, match="component byte hash mismatch"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_a_fabricated_pass_verdict(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    fabricated = replace(gate0, evidence=Gate0Evidence())
    forged_spec = replace(spec, gate0_evidence_digest=fabricated.digest())
    reveal = dict(context.reveal_record)
    reveal["frozen_selection"] = {"experiment_spec_seal": forged_spec.seal()}
    forged_context = RevealedHoldoutContext(context.seal, reveal, 1, context.panel)
    with pytest.raises(CryptoGateError, match="Gate 0"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=fabricated,
            spec=forged_spec,
            holdout=forged_context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )
    blocked = evaluate_gate0(VenuePolicy(), None)
    with pytest.raises(CryptoGateError, match="Gate 0"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=blocked,
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_requires_one_explicit_reveal_and_exact_holdout_range(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    with pytest.raises(CryptoGovernanceError, match="exactly one"):
        RevealedHoldoutContext(context.seal, context.reveal_record, 0, context.panel)
    short = RevealedHoldoutContext(
        context.seal,
        context.reveal_record,
        1,
        context.panel[context.panel["timestamp"] < pd.Timestamp("2024-01-04", tz="UTC")],
    )
    with pytest.raises(CryptoGovernanceError, match="exact sealed holdout range"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=short,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
        )


def test_runner_rejects_unsealed_execution_inputs_and_protected_overrides(
    tmp_path: Path,
) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    with pytest.raises(CryptoGovernanceError, match="cover every tradable symbol"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits={"CMC:2": ExecutionLimits(min_notional_usd=5.0)},
            taker_fees=fees,
        )
    with pytest.raises(CryptoGovernanceError, match="cannot override protected fields"):
        run_protected_crypto_evaluation(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            holdout=context,
            cohort_members=["CMC:2"],
            run_id="candidate-run",
            execution_limits=limits,
            taker_fees=fees,
            supplemental_evidence={"dataset_digest": "x"},
        )


def test_selection_runner_never_reads_holdout_and_is_not_promotable(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    selection_panel = _panel("2023-12-28")
    selection = SelectionContext(context.seal, 0, selection_panel)
    run = run_protected_crypto_selection(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0,  # type: ignore[arg-type]
        spec=spec,
        selection=selection,
        cohort_members=["CMC:2"],
        run_id="selection-run",
        execution_limits=limits,
        taker_fees=fees,
    )
    assert run.promotable is False
    assert run.artifact["phase"] == "SELECTION"
    assert run.artifact["promotable"] is False
    assert run.artifact["holdout_reveal_count"] == 0
    assert "holdout" not in run.artifact


def test_selection_runner_rejects_any_reveal_or_future_row(tmp_path: Path) -> None:
    manifest, provenance_root, gate0, spec, context, limits, fees = _setup(tmp_path)
    with pytest.raises(CryptoGovernanceError, match="blocked after any"):
        SelectionContext(context.seal, 1, _panel("2023-12-28"))
    future = pd.concat([_panel("2023-12-28"), _panel("2024-01-01")], ignore_index=True)
    with pytest.raises(CryptoGovernanceError, match="outside the sealed selection"):
        run_protected_crypto_selection(
            manifest=manifest,
            provenance_root=provenance_root,
            gate0_verdict=gate0,  # type: ignore[arg-type]
            spec=spec,
            selection=SelectionContext(context.seal, 0, future),
            cohort_members=["CMC:2"],
            run_id="selection-run",
            execution_limits=limits,
            taker_fees=fees,
        )
