"""The only production entry point for causal crypto P&L evaluation.

The lower-level evaluator remains importable for unit tests and simulation
primitives.  Productive research must enter through
``run_protected_crypto_evaluation``: it requires a trusted manifest, a passing
Gate-0 verdict, the exact immutable ExperimentSpec, and an explicitly supplied
holdout context whose reveal is already recorded.  This module never opens a
panel, holdout seal, reveal log, manifest, or credential from disk.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.costs.crypto_lowcap import (
    DEFAULT_TIER_PROFILES,
    CostInput,
    TierCostProfile,
)
from quant_trade.data.crypto_manifest import CryptoDatasetManifest, verify_component_bytes
from quant_trade.execution.bar_model import BarExecutionPolicy
from quant_trade.metrics.statistics import return_moments
from quant_trade.ops.crypto_gates import Gate0Verdict, require_gate0_passed
from quant_trade.research.crypto_evaluator import (
    EvaluationResult,
    ExecutionLimits,
    equal_weight_benchmark,
    evaluate,
)
from quant_trade.research.crypto_governance import (
    REQUIRED_BENCHMARKS,
    SCHEMA_VERSION,
    CryptoGovernanceError,
    ExperimentSpec,
    canonical_digest,
    evaluation_artifact_digest,
)
from quant_trade.research.holdout_seal import HoldoutSeal
from quant_trade.research.strategy_registry import get_research_signal_model

_SUPPLEMENTAL_KEYS = frozenset({"overfitting", "economics", "stress", "concentration", "capacity"})


def execution_limits_digest(limits: Mapping[str, ExecutionLimits]) -> str:
    return canonical_digest(
        {str(symbol): asdict(value) for symbol, value in sorted(limits.items())}
    )


def taker_fees_digest(fees: Mapping[str, CostInput]) -> str:
    return canonical_digest(
        {str(symbol): value.to_dict() for symbol, value in sorted(fees.items())}
    )


def cost_profiles_digest(profiles: Sequence[TierCostProfile]) -> str:
    def finite_payload(profile: TierCostProfile) -> dict[str, Any]:
        payload = profile.to_dict()
        for name in ("market_cap_min_usd", "market_cap_max_usd"):
            value = float(payload[name])
            payload[name] = value if math.isfinite(value) else "INF"
        return payload

    return canonical_digest([finite_payload(profile) for profile in profiles])


def cohort_members_digest(members: Sequence[str]) -> str:
    normalized = sorted({str(member).strip() for member in members if str(member).strip()})
    if not normalized:
        raise CryptoGovernanceError("the frozen cohort must contain at least one instrument")
    return canonical_digest(normalized)


def canonical_panel_digest(panel: pd.DataFrame) -> str:
    """Hash the exact normalized records consumed by an evaluation phase."""

    if not isinstance(panel, pd.DataFrame) or panel.empty:
        raise CryptoGovernanceError("cannot digest an empty panel")
    frame = panel.copy()
    frame.columns = [str(column) for column in frame.columns]
    ordered_columns = sorted(frame.columns)
    frame = frame[ordered_columns]
    for column in ordered_columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = pd.to_datetime(frame[column], utc=True).map(
                lambda value: value.isoformat()
            )
    sort_columns = [column for column in ("timestamp", "symbol", "venue") if column in frame]
    if sort_columns:
        frame = frame.sort_values(sort_columns, kind="mergesort")
    frame = frame.reset_index(drop=True)
    records = json.loads(frame.to_json(orient="records", date_format="iso", date_unit="ns"))
    return canonical_digest({"columns": ordered_columns, "records": records})


@dataclass(frozen=True)
class SelectionContext:
    """Selection bytes plus proof that the holdout has never been revealed."""

    seal: HoldoutSeal
    reveal_count: int
    panel: pd.DataFrame

    def __post_init__(self) -> None:
        if self.reveal_count != 0:
            raise CryptoGovernanceError("selection is blocked after any holdout reveal")
        if not isinstance(self.panel, pd.DataFrame) or self.panel.empty:
            raise CryptoGovernanceError("the explicit selection panel is required")


@dataclass(frozen=True)
class RevealedHoldoutContext:
    """Already-revealed holdout bytes and their independently loaded evidence."""

    seal: HoldoutSeal
    reveal_record: Mapping[str, Any]
    reveal_count: int
    panel: pd.DataFrame

    def __post_init__(self) -> None:
        if self.reveal_count != 1:
            raise CryptoGovernanceError("exactly one recorded holdout reveal is required")
        if not isinstance(self.reveal_record, Mapping) or not self.reveal_record:
            raise CryptoGovernanceError("the recorded holdout reveal is required")
        if not isinstance(self.panel, pd.DataFrame) or self.panel.empty:
            raise CryptoGovernanceError("the explicit revealed holdout panel is required")

    @property
    def reveal_digest(self) -> str:
        return canonical_digest(self.reveal_record)


@dataclass(frozen=True)
class ProtectedCryptoRun:
    artifact: Mapping[str, Any]
    candidate_result: EvaluationResult
    benchmark_results: Mapping[str, EvaluationResult]

    @property
    def artifact_digest(self) -> str:
        return str(self.artifact["artifact_digest"])

    def ledger_record(self) -> dict[str, Any]:
        """Return the strict v2 row to append with ``ledger.append_trial``."""

        artifact = self.artifact
        holdout = artifact["holdout"]
        metrics = artifact["test_metrics"]
        policy = artifact["policy_bindings"]
        benchmark_digests = artifact["benchmark_artifact_digests"]
        return {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": artifact["campaign_id"],
            "experiment_id": artifact["experiment_id"],
            "hypothesis_id": artifact["hypothesis_id"],
            "experiment_spec_seal": artifact["experiment_spec_seal"],
            "run_id": artifact["run_id"],
            "attempt_id": artifact["run_id"],
            "status": "evaluated",
            "source": "protected_crypto_runner",
            "strategy": artifact["strategy"],
            "dataset_digest": artifact["dataset_digest"],
            "code_commit": artifact["code_commit"],
            "artifact_digest": artifact["artifact_digest"],
            "holdout_seal_digest": holdout["seal_digest"],
            "holdout_reveal_digest": holdout["reveal_digest"],
            "execution_policy_digest": policy["execution_policy_digest"],
            "cost_policy_digest": policy["cost_policy_digest"],
            "benchmark_policy_digest": policy["benchmark_policy_digest"],
            "cohort_digest": policy["cohort_digest"],
            "metrics_digest": canonical_digest(metrics),
            "benchmark_artifacts_digest": canonical_digest(benchmark_digests),
            "test_range": list(holdout["test_range"]),
            "test_sharpe_per_period": metrics["sharpe_per_period"],
        }


@dataclass(frozen=True)
class ProtectedCryptoSelectionRun:
    artifact: Mapping[str, Any]
    candidate_result: EvaluationResult
    benchmark_results: Mapping[str, EvaluationResult]

    @property
    def promotable(self) -> bool:
        return False


def _benchmark_spec(spec: ExperimentSpec, benchmark_id: str) -> Mapping[str, Any]:
    matches = [item for item in spec.benchmarks if str(item.get("benchmark_id")) == benchmark_id]
    if len(matches) != 1:
        raise CryptoGovernanceError(f"missing unique benchmark spec {benchmark_id!r}")
    return matches[0]


def _btc_benchmark_weights(panel: pd.DataFrame, instrument_id: str) -> pd.DataFrame:
    """BTC is an external benchmark and need not belong to the low-cap universe."""

    rows = panel[panel["symbol"].astype(str) == instrument_id].sort_values("timestamp")
    tradable = rows[rows["tradable"].astype(bool)]
    if tradable.empty:
        raise CryptoGovernanceError("the sealed BTC benchmark is not tradable in this phase")
    return pd.DataFrame(
        [
            {
                "timestamp": tradable.iloc[0]["timestamp"],
                "symbol": instrument_id,
                "target_weight": 1.0,
                "order_intent": "TARGET_PORTFOLIO",
            }
        ]
    )


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    drawdowns = equity / equity.cummax() - 1.0
    return float(drawdowns.min())


def _result_payload(result: EvaluationResult) -> dict[str, Any]:
    return {
        "summary": result.summary(),
        "equity": [
            {"timestamp": timestamp.isoformat(), "value_usd": float(value)}
            for timestamp, value in result.equity.items()
        ],
        "rebalances": [record.to_dict() for record in result.rebalances],
        "executions": [record.to_dict() for record in result.executions],
    }


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _generate_candidate_weights(
    panel: pd.DataFrame,
    spec: ExperimentSpec,
    cohort_members: Sequence[str],
) -> pd.DataFrame:
    model = get_research_signal_model(spec.strategy)
    weights = model.generate(panel, dict(spec.strategy_params))
    if not isinstance(weights, pd.DataFrame) or weights.empty:
        raise CryptoGovernanceError("the sealed strategy emitted no candidate targets")
    required = {"timestamp", "symbol", "target_weight"}
    if not required.issubset(weights.columns):
        raise CryptoGovernanceError("the sealed strategy emitted malformed targets")
    timestamps = pd.to_datetime(weights["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise CryptoGovernanceError("the sealed strategy emitted invalid timestamps")
    targeted = set(weights.loc[weights["target_weight"] > 0, "symbol"].astype(str))
    if not targeted.issubset(set(str(member) for member in cohort_members)):
        raise CryptoGovernanceError("sealed strategy targets escape the frozen cohort")
    return weights


def _validate_common_context(
    *,
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
    gate0_verdict: Gate0Verdict,
    spec: ExperimentSpec,
    panel: pd.DataFrame,
    cohort_members: Sequence[str],
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile],
) -> None:
    manifest.require_trusted("protected crypto P&L generation")
    verify_component_bytes(manifest, provenance_root)
    require_gate0_passed(gate0_verdict, "pnl_generation")
    if manifest.digest() != spec.dataset_digest or manifest.dataset_id != spec.dataset_id:
        raise CryptoGovernanceError("manifest identity/digest does not match ExperimentSpec")
    if manifest.venue.lower() != spec.venue.lower() or manifest.code_commit != spec.code_commit:
        raise CryptoGovernanceError("manifest venue/code commit does not match ExperimentSpec")
    if not gate0_verdict.passed or gate0_verdict.status != spec.gate0_status:
        raise CryptoGovernanceError("Gate 0 did not positively pass")
    if gate0_verdict.digest() != spec.gate0_evidence_digest:
        raise CryptoGovernanceError("Gate-0 verdict digest does not match ExperimentSpec")
    if gate0_verdict.policy.venue.lower() != spec.venue.lower():
        raise CryptoGovernanceError("Gate-0 venue does not match ExperimentSpec")
    if str(spec.venue_policy.get("market", "")).lower() != gate0_verdict.policy.market:
        raise CryptoGovernanceError("Gate-0 market does not match the sealed venue policy")
    if str(spec.venue_policy.get("environment", "")).lower() != gate0_verdict.policy.environment:
        raise CryptoGovernanceError("Gate-0 environment does not match the sealed venue policy")

    expected_symbols = set(panel.loc[panel["tradable"].astype(bool), "symbol"].astype(str))
    if not expected_symbols:
        raise CryptoGovernanceError("the phase panel has no tradable symbols")
    if set(execution_limits) != expected_symbols:
        raise CryptoGovernanceError(
            "execution limits must cover every tradable symbol in the phase panel"
        )
    if set(taker_fees) != expected_symbols:
        raise CryptoGovernanceError(
            "account fee evidence must cover every tradable symbol in the phase panel"
        )
    for symbol, limit in execution_limits.items():
        if any(
            getattr(limit, field_name) is None
            for field_name in ("tick_size", "quantity_step", "min_notional_usd")
        ):
            raise CryptoGovernanceError(
                f"{symbol}: tick, quantity step, and minimum notional are all required"
            )
    for symbol, fee in taker_fees.items():
        if fee.evidence_class != "REAL_ACCOUNT_SPECIFIC" or not fee.raw_sha256:
            raise CryptoGovernanceError(
                f"{symbol}: account-specific fee bytes are required; assumptions are forbidden"
            )

    if (
        execution_limits_digest(execution_limits)
        != spec.execution_policy["execution_limits_digest"]
    ):
        raise CryptoGovernanceError("execution-limit bytes contradict the sealed policy")
    if taker_fees_digest(taker_fees) != spec.cost_policy["taker_fees_digest"]:
        raise CryptoGovernanceError("fee evidence contradicts the sealed cost policy")
    if cost_profiles_digest(profiles) != spec.cost_policy["cost_profiles_digest"]:
        raise CryptoGovernanceError("cost profiles contradict the sealed cost policy")
    if cohort_members_digest(cohort_members) != spec.cohort_digest:
        raise CryptoGovernanceError("frozen cohort digest does not match ExperimentSpec")


def _validate_holdout_context(
    *,
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
    gate0_verdict: Gate0Verdict,
    spec: ExperimentSpec,
    context: RevealedHoldoutContext,
    cohort_members: Sequence[str],
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile],
) -> None:
    _validate_common_context(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0_verdict,
        spec=spec,
        panel=context.panel,
        cohort_members=cohort_members,
        execution_limits=execution_limits,
        taker_fees=taker_fees,
        profiles=profiles,
    )
    seal = context.seal
    if seal.seal() != spec.holdout_seal_digest:
        raise CryptoGovernanceError("holdout declaration digest does not match ExperimentSpec")
    if seal.dataset_id != spec.dataset_id or seal.dataset_digest != spec.dataset_digest:
        raise CryptoGovernanceError("holdout declaration does not bind the trusted manifest")
    expected_ranges = (
        spec.selection_start,
        spec.selection_end,
        spec.holdout_start,
        spec.holdout_end,
    )
    observed_ranges = (
        seal.selection_start,
        seal.selection_end,
        seal.holdout_start,
        seal.holdout_end,
    )
    if observed_ranges != expected_ranges:
        raise CryptoGovernanceError("holdout ranges contradict ExperimentSpec")

    reveal = context.reveal_record
    if reveal.get("seal") != seal.seal():
        raise CryptoGovernanceError("reveal record does not bind the sealed holdout")
    if not str(reveal.get("reason", "")).strip() or not str(reveal.get("at_utc", "")).strip():
        raise CryptoGovernanceError("reveal reason and timestamp are required")
    frozen = reveal.get("frozen_selection")
    if not isinstance(frozen, Mapping) or frozen.get("experiment_spec_seal") != spec.seal():
        raise CryptoGovernanceError("reveal was not aimed at this frozen ExperimentSpec")

    timestamps = pd.to_datetime(context.panel["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise CryptoGovernanceError("revealed panel contains invalid timestamps")
    first = timestamps.min().date().isoformat()
    last = timestamps.max().date().isoformat()
    if [first, last] != [spec.holdout_start, spec.holdout_end]:
        raise CryptoGovernanceError("revealed panel must cover the exact sealed holdout range")
    if canonical_panel_digest(context.panel) != spec.holdout_panel_digest:
        raise CryptoGovernanceError("holdout panel bytes contradict ExperimentSpec")


def _validate_selection_context(
    *,
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
    gate0_verdict: Gate0Verdict,
    spec: ExperimentSpec,
    context: SelectionContext,
    cohort_members: Sequence[str],
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile],
) -> None:
    _validate_common_context(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0_verdict,
        spec=spec,
        panel=context.panel,
        cohort_members=cohort_members,
        execution_limits=execution_limits,
        taker_fees=taker_fees,
        profiles=profiles,
    )
    seal = context.seal
    if seal.seal() != spec.holdout_seal_digest:
        raise CryptoGovernanceError("selection context does not use the sealed holdout declaration")
    if seal.dataset_id != spec.dataset_id or seal.dataset_digest != spec.dataset_digest:
        raise CryptoGovernanceError("selection declaration does not bind the trusted manifest")
    timestamps = pd.to_datetime(context.panel["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise CryptoGovernanceError("selection panel contains invalid timestamps")
    days = timestamps.dt.date.map(lambda value: value.isoformat())
    if (days < spec.selection_start).any() or (days > spec.selection_end).any():
        raise CryptoGovernanceError("selection panel reaches outside the sealed selection range")
    if days.min() != spec.selection_start or days.max() != spec.selection_end:
        raise CryptoGovernanceError("selection panel must cover the exact sealed selection range")
    if canonical_panel_digest(context.panel) != spec.selection_panel_digest:
        raise CryptoGovernanceError("selection panel bytes contradict ExperimentSpec")


def _run_common(
    *,
    panel: pd.DataFrame,
    spec: ExperimentSpec,
    cohort_members: Sequence[str],
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile],
) -> tuple[
    pd.DataFrame,
    EvaluationResult,
    dict[str, EvaluationResult],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, Any],
    dict[str, Any],
]:
    candidate_weights = _generate_candidate_weights(panel, spec, cohort_members)
    panel_timestamps = pd.to_datetime(panel["timestamp"], utc=True)
    weight_timestamps = pd.to_datetime(candidate_weights["timestamp"], utc=True)
    if (weight_timestamps < panel_timestamps.min()).any() or (
        weight_timestamps > panel_timestamps.max()
    ).any():
        raise CryptoGovernanceError("candidate targets escape the active phase")

    btc_spec = _benchmark_spec(spec, "btc_buy_and_hold")
    basket_spec = _benchmark_spec(spec, "eligible_equal_weight")
    benchmark_weights = {
        "btc_buy_and_hold": _btc_benchmark_weights(
            panel, str(btc_spec.get("instrument_id", "CMC:1"))
        ),
        "eligible_equal_weight": equal_weight_benchmark(
            panel,
            rebalance_frequency=str(basket_spec.get("rebalance_frequency", "annual")),
            top_n=int(basket_spec.get("top_n", 20)),
        ),
    }
    if set(benchmark_weights) != REQUIRED_BENCHMARKS:
        raise CryptoGovernanceError("the sealed benchmark pair is incomplete")
    for benchmark_id, weights in benchmark_weights.items():
        timestamps = pd.to_datetime(weights["timestamp"], utc=True, errors="coerce")
        if timestamps.isna().any() or (
            (timestamps < panel_timestamps.min()).any()
            or (timestamps > panel_timestamps.max()).any()
        ):
            raise CryptoGovernanceError(f"{benchmark_id} targets escape the active phase")

    initial_capital = float(spec.cost_policy["initial_capital_usd"])
    recovery = float(spec.cost_policy["delisting_recovery"])
    quantile = str(spec.cost_policy["quantile"])
    profile_tuple = tuple(profiles)
    executable_fraction = float(spec.cost_policy["min_executable_fraction"])
    bar_policy = BarExecutionPolicy.from_mapping(spec.execution_policy)
    limit_map = dict(execution_limits)
    fee_map = dict(taker_fees)
    candidate_result = evaluate(
        panel,
        candidate_weights,
        initial_capital_usd=initial_capital,
        delisting_recovery=recovery,
        quantile=quantile,
        profiles=profile_tuple,
        min_executable_fraction=executable_fraction,
        execution_policy=bar_policy,
        execution_limits=limit_map,
        taker_fees=fee_map,
        expected_venue=spec.venue,
    )
    benchmark_results = {
        benchmark_id: evaluate(
            panel,
            weights,
            initial_capital_usd=initial_capital,
            delisting_recovery=recovery,
            quantile=quantile,
            profiles=profile_tuple,
            min_executable_fraction=executable_fraction,
            execution_policy=bar_policy,
            execution_limits=limit_map,
            taker_fees=fee_map,
            expected_venue=spec.venue,
        )
        for benchmark_id, weights in benchmark_weights.items()
    }
    candidate_payload = _result_payload(candidate_result)
    benchmark_payloads = {
        benchmark_id: _result_payload(result) for benchmark_id, result in benchmark_results.items()
    }
    benchmark_digests = {
        benchmark_id: canonical_digest(payload)
        for benchmark_id, payload in benchmark_payloads.items()
    }
    returns = candidate_result.equity.pct_change().dropna()
    test_metrics = {
        **return_moments(returns),
        "max_drawdown": _max_drawdown(candidate_result.equity),
        "independent_trade_count": sum(
            1 for row in candidate_result.executions if row.filled_quantity > 0
        ),
    }
    candidate_summary = candidate_result.summary()
    comparisons: dict[str, Any] = {}
    for benchmark_id, result in benchmark_results.items():
        summary = result.summary()
        comparisons[benchmark_id] = {
            "artifact_digest": benchmark_digests[benchmark_id],
            "net_excess_return": (
                float(candidate_summary["total_return"]) - float(summary["total_return"])
            ),
            "benchmark_max_drawdown": _max_drawdown(result.equity),
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
        }
    return (
        candidate_weights,
        candidate_result,
        benchmark_results,
        candidate_payload,
        benchmark_payloads,
        benchmark_digests,
        test_metrics,
        comparisons,
    )


def run_protected_crypto_evaluation(
    *,
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
    gate0_verdict: Gate0Verdict,
    spec: ExperimentSpec,
    holdout: RevealedHoldoutContext,
    cohort_members: Sequence[str],
    run_id: str,
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile] = DEFAULT_TIER_PROFILES,
    supplemental_evidence: Mapping[str, Any] | None = None,
) -> ProtectedCryptoRun:
    """Run candidate and both sealed benchmarks through one evaluator policy."""

    if not run_id.strip():
        raise CryptoGovernanceError("run_id is required")
    limits = dict(execution_limits)
    fees = dict(taker_fees)
    profile_tuple = tuple(profiles)
    _validate_holdout_context(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0_verdict,
        spec=spec,
        context=holdout,
        cohort_members=cohort_members,
        execution_limits=limits,
        taker_fees=fees,
        profiles=profile_tuple,
    )

    panel = holdout.panel
    (
        _,
        candidate_result,
        benchmark_results,
        candidate_payload,
        benchmark_payloads,
        benchmark_digests,
        test_metrics,
        comparisons,
    ) = _run_common(
        panel=panel,
        spec=spec,
        cohort_members=cohort_members,
        execution_limits=limits,
        taker_fees=fees,
        profiles=profile_tuple,
    )

    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": spec.campaign_id,
        "experiment_id": spec.experiment_id,
        "hypothesis_id": spec.hypothesis_id,
        "experiment_spec_seal": spec.seal(),
        "strategy": spec.strategy,
        "run_id": run_id,
        "dataset_id": spec.dataset_id,
        "dataset_digest": spec.dataset_digest,
        "dataset_status": manifest.status,
        "gate0_status": gate0_verdict.status,
        "gate0_evidence_digest": gate0_verdict.digest(),
        "code_commit": spec.code_commit,
        "venue": spec.venue,
        "holdout": {
            "seal_digest": holdout.seal.seal(),
            "reveal_digest": holdout.reveal_digest,
            "reveal_count": holdout.reveal_count,
            "reveal_record": _json_copy(holdout.reveal_record),
            "test_range": [spec.holdout_start, spec.holdout_end],
        },
        "policy_bindings": {
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
            "benchmark_policy_digest": spec.benchmark_policy_digest,
            "cohort_digest": spec.cohort_digest,
        },
        "candidate_result_digest": canonical_digest(candidate_payload),
        "benchmark_artifact_digests": benchmark_digests,
        "test_metrics": test_metrics,
        "comparisons": comparisons,
        "runs": {"candidate": candidate_payload, "benchmarks": benchmark_payloads},
    }
    supplemental = dict(supplemental_evidence or {})
    unknown = set(supplemental).difference(_SUPPLEMENTAL_KEYS)
    if unknown:
        raise CryptoGovernanceError(
            f"supplemental evidence cannot override protected fields: {sorted(unknown)}"
        )
    artifact.update(supplemental)
    artifact["artifact_digest"] = evaluation_artifact_digest(artifact)
    return ProtectedCryptoRun(artifact, candidate_result, benchmark_results)


def run_protected_crypto_selection(
    *,
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
    gate0_verdict: Gate0Verdict,
    spec: ExperimentSpec,
    selection: SelectionContext,
    cohort_members: Sequence[str],
    run_id: str,
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile] = DEFAULT_TIER_PROFILES,
) -> ProtectedCryptoSelectionRun:
    """Evaluate selection data only; the artifact can never be promoted."""

    if not run_id.strip():
        raise CryptoGovernanceError("run_id is required")
    limits = dict(execution_limits)
    fees = dict(taker_fees)
    profile_tuple = tuple(profiles)
    _validate_selection_context(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0_verdict,
        spec=spec,
        context=selection,
        cohort_members=cohort_members,
        execution_limits=limits,
        taker_fees=fees,
        profiles=profile_tuple,
    )
    (
        _,
        candidate_result,
        benchmark_results,
        candidate_payload,
        benchmark_payloads,
        benchmark_digests,
        test_metrics,
        comparisons,
    ) = _run_common(
        panel=selection.panel,
        spec=spec,
        cohort_members=cohort_members,
        execution_limits=limits,
        taker_fees=fees,
        profiles=profile_tuple,
    )
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "SELECTION",
        "promotable": False,
        "campaign_id": spec.campaign_id,
        "experiment_id": spec.experiment_id,
        "hypothesis_id": spec.hypothesis_id,
        "experiment_spec_seal": spec.seal(),
        "strategy": spec.strategy,
        "run_id": run_id,
        "dataset_id": spec.dataset_id,
        "dataset_digest": spec.dataset_digest,
        "selection_panel_digest": canonical_panel_digest(selection.panel),
        "holdout_reveal_count": 0,
        "selection_range": [spec.selection_start, spec.selection_end],
        "policy_bindings": {
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
            "benchmark_policy_digest": spec.benchmark_policy_digest,
            "cohort_digest": spec.cohort_digest,
        },
        "candidate_result_digest": canonical_digest(candidate_payload),
        "benchmark_artifact_digests": benchmark_digests,
        "test_metrics": test_metrics,
        "comparisons": comparisons,
        "runs": {"candidate": candidate_payload, "benchmarks": benchmark_payloads},
    }
    artifact["artifact_digest"] = evaluation_artifact_digest(artifact)
    return ProtectedCryptoSelectionRun(artifact, candidate_result, benchmark_results)


__all__ = [
    "ProtectedCryptoRun",
    "ProtectedCryptoSelectionRun",
    "RevealedHoldoutContext",
    "SelectionContext",
    "canonical_panel_digest",
    "cohort_members_digest",
    "cost_profiles_digest",
    "execution_limits_digest",
    "run_protected_crypto_evaluation",
    "run_protected_crypto_selection",
    "taker_fees_digest",
]
