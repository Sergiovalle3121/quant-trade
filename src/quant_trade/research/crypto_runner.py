"""The only production entry point for causal crypto P&L evaluation.

The lower-level evaluator remains importable for unit tests and simulation
primitives.  Productive research must enter through
``run_protected_crypto_evaluation``: it requires a trusted manifest, a passing
Gate-0 verdict, the exact immutable ExperimentSpec, and a persisted holdout
directory whose authorization and single reveal are independently reloaded.
The caller supplies the panel in memory, but the runner proves that its
canonical bytes are one of the manifest's phase components before evaluating.
"""

from __future__ import annotations

import hmac
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.costs.crypto_lowcap import (
    DEFAULT_TIER_PROFILES,
    CostInput,
    TierCostProfile,
)
from quant_trade.data.crypto_manifest import (
    CryptoDatasetManifest,
    provenance_paths,
    verify_component_bytes,
)
from quant_trade.data.crypto_market_events import EVIDENCED_MARKET_EVENTS, MarketEventLedger
from quant_trade.data.crypto_panel import (
    MARKET_EVENT_DELISTED,
    MARKET_EVENT_DELISTING_CONFIRMED,
    MARKET_EVENT_LISTING_ENDED_CONFIRMED,
    parse_market_events,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_file, sha256_of_text
from quant_trade.execution.bar_model import BarExecutionPolicy
from quant_trade.metrics.statistics import return_moments
from quant_trade.ops.crypto_gates import Gate0Verdict, require_gate0_passed
from quant_trade.research.crypto_economic_evidence import (
    CryptoEconomicEvidenceError,
    canonical_evidence_digest,
    derive_capacity,
    derive_execution_economics,
    derive_pnl_concentration,
    derive_stress_evidence,
)
from quant_trade.research.crypto_evaluator import (
    EvaluationResult,
    ExecutionLimits,
    btc_buy_and_hold_benchmark,
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
    independent_closed_round_trip_count,
)
from quant_trade.research.holdout_seal import (
    CryptoHoldoutAuthorization,
    HoldoutSeal,
    HoldoutSealError,
    assert_dataset_not_invalidated,
    load_crypto_holdout_authorization,
    load_seal,
    read_reveals,
)
from quant_trade.research.runtime_provenance import (
    RuntimeProvenanceError,
    verify_runtime_code_commit,
)
from quant_trade.research.signals.base import rebalance_mask
from quant_trade.research.strategy_registry import get_research_signal_model


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


def _is_panel_timestamp_column(column: str, values: pd.Series) -> bool:
    lowered = column.lower()
    return bool(
        pd.api.types.is_datetime64_any_dtype(values)
        or lowered == "timestamp"
        or lowered.endswith("_timestamp")
        or lowered.endswith("_at")
        or lowered.endswith("_at_utc")
    )


def _canonical_panel_value(value: Any, *, column: str, timestamp: bool) -> Any:
    """Normalize one panel scalar without reducing floating-point precision."""

    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if timestamp or isinstance(value, (pd.Timestamp, datetime, date)):
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(parsed) or not isinstance(parsed, pd.Timestamp):
            raise CryptoGovernanceError(f"panel column {column!r} contains an invalid timestamp")
        return parsed.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CryptoGovernanceError(
                f"panel column {column!r} contains NaN or an infinite value"
            )
        # JSON distinguishes -0.0 at the byte level although the evaluator
        # cannot.  Collapse both representations to the same canonical value.
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        return value
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        raise CryptoGovernanceError(f"panel column {column!r} contains a missing scalar")
    raise CryptoGovernanceError(
        f"panel column {column!r} contains unsupported value type {type(value).__name__}"
    )


def _canonical_panel_payload(panel: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(panel, pd.DataFrame) or panel.empty:
        raise CryptoGovernanceError("cannot digest an empty panel")
    frame = panel.copy()
    normalized_columns = [str(column) for column in frame.columns]
    if len(normalized_columns) != len(set(normalized_columns)):
        raise CryptoGovernanceError("panel columns collide after canonical string normalization")
    frame.columns = normalized_columns
    ordered_columns = sorted(frame.columns)
    frame = frame[ordered_columns]
    timestamp_columns = {
        column for column in ordered_columns if _is_panel_timestamp_column(column, frame[column])
    }
    records = [
        {
            column: _canonical_panel_value(
                value,
                column=column,
                timestamp=column in timestamp_columns,
            )
            for column, value in zip(ordered_columns, row, strict=True)
        }
        for row in frame.itertuples(index=False, name=None)
    ]
    sort_columns = [
        column for column in ("timestamp", "instrument_id", "symbol", "venue") if column in frame
    ]
    records.sort(
        key=lambda record: (
            canonical_dumps([record[column] for column in sort_columns]),
            canonical_dumps(record),
        )
    )
    return {"columns": ordered_columns, "records": records}


def canonical_panel_bytes(panel: pd.DataFrame) -> bytes:
    """Canonical component bytes required by ``canonical_panel_v1`` manifests."""

    return canonical_dumps(_canonical_panel_payload(panel)).encode("utf-8")


def canonical_panel_digest(panel: pd.DataFrame) -> str:
    """Hash the exact normalized records consumed by an evaluation phase."""

    return sha256_of_text(canonical_panel_bytes(panel).decode("utf-8"))


def canonical_market_event_ledger_bytes(ledger: MarketEventLedger) -> bytes:
    """Return the exact canonical bytes used for a market-event component."""

    if not isinstance(ledger, MarketEventLedger):
        raise CryptoGovernanceError("an explicit MarketEventLedger is required")
    return canonical_dumps(ledger.to_dict()).encode("utf-8")


def canonical_market_event_ledger_digest(ledger: MarketEventLedger) -> str:
    """Hash the complete event component, including its embedded content seal."""

    return sha256_of_text(canonical_market_event_ledger_bytes(ledger).decode("utf-8"))


@dataclass(frozen=True)
class SelectionContext:
    """Selection bytes plus the directory containing durable holdout evidence."""

    holdout_directory: str | Path
    panel: pd.DataFrame
    market_events: MarketEventLedger

    def __post_init__(self) -> None:
        if not isinstance(self.panel, pd.DataFrame) or self.panel.empty:
            raise CryptoGovernanceError("the explicit selection panel is required")
        if not isinstance(self.market_events, MarketEventLedger):
            raise CryptoGovernanceError("the explicit selection MarketEventLedger is required")
        if not str(self.holdout_directory).strip():
            raise CryptoGovernanceError("the persisted holdout directory is required")


@dataclass(frozen=True)
class RevealedHoldoutContext:
    """Holdout bytes plus the directory containing the persisted reveal log."""

    holdout_directory: str | Path
    panel: pd.DataFrame
    market_events: MarketEventLedger

    def __post_init__(self) -> None:
        if not isinstance(self.panel, pd.DataFrame) or self.panel.empty:
            raise CryptoGovernanceError("the explicit revealed holdout panel is required")
        if not isinstance(self.market_events, MarketEventLedger):
            raise CryptoGovernanceError("the explicit holdout MarketEventLedger is required")
        if not str(self.holdout_directory).strip():
            raise CryptoGovernanceError("the persisted holdout directory is required")


@dataclass(frozen=True)
class _PersistedHoldoutEvidence:
    seal: HoldoutSeal
    authorization: CryptoHoldoutAuthorization
    reveal_record: Mapping[str, Any] | None

    @property
    def reveal_digest(self) -> str | None:
        return canonical_digest(self.reveal_record) if self.reveal_record is not None else None


@dataclass(frozen=True)
class ProtectedCryptoRun:
    artifact: Mapping[str, Any]
    candidate_result: EvaluationResult
    control_result: EvaluationResult
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
            "phase": "HOLDOUT",
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
            "candidate_result_digest": artifact["candidate_result_digest"],
            "control_result_digest": artifact["control_result_digest"],
            "holdout_seal_digest": holdout["seal_digest"],
            "holdout_authorization_digest": holdout["authorization_digest"],
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
    control_result: EvaluationResult
    benchmark_results: Mapping[str, EvaluationResult]

    @property
    def promotable(self) -> bool:
        return False

    def ledger_record(self) -> dict[str, Any]:
        """Return one of the 15 selection-trial rows; never a holdout result."""

        artifact = self.artifact
        metrics = artifact["test_metrics"]
        policy = artifact["policy_bindings"]
        benchmark_digests = artifact["benchmark_artifact_digests"]
        return {
            "schema_version": SCHEMA_VERSION,
            "phase": "SELECTION",
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
            "candidate_result_digest": artifact["candidate_result_digest"],
            "control_result_digest": artifact["control_result_digest"],
            "holdout_seal_digest": artifact["holdout_seal_digest"],
            "holdout_authorization_digest": artifact["holdout_authorization_digest"],
            "execution_policy_digest": policy["execution_policy_digest"],
            "cost_policy_digest": policy["cost_policy_digest"],
            "benchmark_policy_digest": policy["benchmark_policy_digest"],
            "cohort_digest": policy["cohort_digest"],
            "metrics_digest": canonical_digest(metrics),
            "benchmark_artifacts_digest": canonical_digest(benchmark_digests),
            "test_range": list(artifact["selection_range"]),
            "test_sharpe_per_period": metrics["sharpe_per_period"],
        }


def _benchmark_spec(spec: ExperimentSpec, benchmark_id: str) -> Mapping[str, Any]:
    matches = [item for item in spec.benchmarks if str(item.get("benchmark_id")) == benchmark_id]
    if len(matches) != 1:
        raise CryptoGovernanceError(f"missing unique benchmark spec {benchmark_id!r}")
    return matches[0]


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


def _load_persisted_holdout(
    directory: str | Path,
    *,
    expect_revealed: bool,
) -> _PersistedHoldoutEvidence:
    try:
        seal = load_seal(directory)
        assert_dataset_not_invalidated(directory, seal.dataset_digest)
        authorization = load_crypto_holdout_authorization(directory)
        reveals = read_reveals(directory)
    except (HoldoutSealError, OSError, ValueError) as exc:
        raise CryptoGovernanceError(f"invalid persisted holdout evidence: {exc}") from exc
    expected_count = 1 if expect_revealed else 0
    if len(reveals) != expected_count:
        state = "exactly one reveal" if expect_revealed else "zero reveals"
        raise CryptoGovernanceError(f"persisted holdout evidence must contain {state}")
    reveal = reveals[0] if reveals else None
    return _PersistedHoldoutEvidence(seal, authorization, reveal)


def _validate_phase_panel_component(
    *,
    manifest: CryptoDatasetManifest,
    spec: ExperimentSpec,
    panel: pd.DataFrame,
    phase: str,
) -> None:
    phase_name = phase.lower()
    component_key = f"{phase_name}_panel_component"
    component_name = str(spec.split_policy.get(component_key, ""))
    expected_digest = str(getattr(spec, f"{phase_name}_panel_digest"))
    observed_digest = canonical_panel_digest(panel)
    manifest_digest = manifest.components.get(component_name)
    if manifest_digest is None:
        raise CryptoGovernanceError(
            f"manifest does not contain sealed {phase_name} panel component {component_name!r}"
        )
    if manifest_digest != observed_digest or expected_digest != observed_digest:
        raise CryptoGovernanceError(
            f"{phase_name} panel records are not the canonical bytes hashed by the manifest"
        )


def _validate_phase_market_events_component(
    *,
    manifest: CryptoDatasetManifest,
    spec: ExperimentSpec,
    ledger: MarketEventLedger,
    phase: str,
) -> str:
    phase_name = phase.lower()
    component_name = str(spec.split_policy.get(f"{phase_name}_market_events_component", ""))
    observed_digest = canonical_market_event_ledger_digest(ledger)
    manifest_digest = manifest.components.get(component_name)
    if manifest_digest is None:
        raise CryptoGovernanceError(
            f"manifest does not contain sealed {phase_name} market-event component "
            f"{component_name!r}"
        )
    if manifest_digest != observed_digest:
        raise CryptoGovernanceError(
            f"{phase_name} market-event records are not the canonical bytes hashed by the manifest"
        )

    start = pd.Timestamp(getattr(spec, f"{phase_name}_start"), tz="UTC")
    end = pd.Timestamp(getattr(spec, f"{phase_name}_end"), tz="UTC") + pd.Timedelta(days=1)
    for event in ledger.events:
        effective = pd.to_datetime(event.effective_at_utc, utc=True)
        if effective < start or effective >= end:
            raise CryptoGovernanceError(
                f"{phase_name} market-event ledger reaches outside its sealed phase range"
            )
    return observed_digest


def _bar_policy_from_spec(spec: ExperimentSpec) -> BarExecutionPolicy:
    delay = int(spec.execution_policy["decision_to_execution_bars"])
    expected_additional = delay - 1
    declared = int(spec.execution_policy.get("additional_latency_bars", expected_additional))
    if declared != expected_additional:
        raise CryptoGovernanceError(
            "sealed decision-to-execution delay contradicts additional latency"
        )
    values = dict(spec.execution_policy)
    values["additional_latency_bars"] = expected_additional
    return BarExecutionPolicy.from_mapping(values)


def _control_strategy_and_params(spec: ExperimentSpec) -> tuple[str, dict[str, Any]]:
    control = dict(spec.control)
    strategy = str(control.pop("strategy", spec.strategy))
    if strategy != spec.strategy:
        raise CryptoGovernanceError("the sealed control must use the candidate strategy model")
    comparison_variable = control.pop("comparison_variable", None)
    if not isinstance(comparison_variable, str) or not comparison_variable.strip():
        raise CryptoGovernanceError("control.comparison_variable is required")
    comparison_variable = comparison_variable.strip()
    nested = control.pop("strategy_params", None)
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise CryptoGovernanceError("control.strategy_params must be a mapping")
        if control:
            raise CryptoGovernanceError(
                "control cannot mix strategy_params with top-level parameter overrides"
            )
        params = {**dict(spec.strategy_params), **dict(nested)}
    else:
        params = {**dict(spec.strategy_params), **control}
    candidate_params = dict(spec.strategy_params)
    differing = {
        key
        for key in set(candidate_params) | set(params)
        if candidate_params.get(key) != params.get(key)
    }
    if differing != {comparison_variable}:
        raise CryptoGovernanceError(
            "the sealed control must change exactly control.comparison_variable; "
            f"observed differences: {sorted(differing)}"
        )
    return strategy, params


def _h3_exact_cohort_weights(
    panel: pd.DataFrame,
    *,
    cohort_members: Sequence[str],
    rebalance_frequency: str,
    rebalance_once: bool,
) -> pd.DataFrame:
    members = tuple(
        sorted({str(member).strip() for member in cohort_members if str(member).strip()})
    )
    available = set(panel["symbol"].astype(str))
    if not members or set(members) != set(cohort_members) or not set(members).issubset(available):
        raise CryptoGovernanceError("H3 requires the exact non-empty sealed cohort in the panel")
    timestamps = pd.DatetimeIndex(
        pd.to_datetime(panel["timestamp"], utc=True).sort_values().unique()
    )
    mask = rebalance_mask(timestamps, rebalance_frequency)
    decisions = list(mask[mask].index)
    if rebalance_once:
        decisions = decisions[:1]
    if not decisions:
        raise CryptoGovernanceError("H3 has no rebalance decision in the active phase")
    target_weight = 1.0 / len(members)
    return pd.DataFrame(
        [
            {
                "timestamp": timestamp,
                "symbol": member,
                "target_weight": target_weight,
                "order_intent": "TARGET_PORTFOLIO",
            }
            for timestamp in decisions
            for member in members
        ]
    )


def _validate_generated_weights(
    weights: pd.DataFrame,
    *,
    cohort_members: Sequence[str],
    label: str,
) -> pd.DataFrame:
    if not isinstance(weights, pd.DataFrame) or weights.empty:
        raise CryptoGovernanceError(f"the sealed {label} emitted no targets")
    required = {"timestamp", "symbol", "target_weight"}
    if not required.issubset(weights.columns):
        raise CryptoGovernanceError(f"the sealed {label} emitted malformed targets")
    timestamps = pd.to_datetime(weights["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise CryptoGovernanceError(f"the sealed {label} emitted invalid timestamps")
    positive = pd.to_numeric(weights["target_weight"], errors="coerce") > 0
    targeted = set(weights.loc[positive, "symbol"].astype(str))
    if not targeted.issubset(set(str(member) for member in cohort_members)):
        raise CryptoGovernanceError(f"sealed {label} targets escape the frozen cohort")
    return weights


def _generate_candidate_and_control_weights(
    panel: pd.DataFrame,
    spec: ExperimentSpec,
    cohort_members: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    control_strategy, control_params = _control_strategy_and_params(spec)
    if spec.hypothesis_id == "H3":
        if spec.strategy != "crypto_annual_equal_weight_rebalance":
            raise CryptoGovernanceError("H3 must use crypto_annual_equal_weight_rebalance")
        candidate_params = dict(spec.strategy_params)
        if (
            candidate_params.get("freeze_cohort", True) is not True
            or candidate_params.get("rebalance_once", False) is not False
        ):
            raise CryptoGovernanceError("H3 candidate must annually rebalance the frozen cohort")
        if (
            control_params.get("freeze_cohort", True) is not True
            or control_params.get("rebalance_once") is not True
        ):
            raise CryptoGovernanceError("H3 control must buy and hold the identical frozen cohort")
        frequency = str(candidate_params.get("rebalance_frequency", "annual"))
        candidate = _h3_exact_cohort_weights(
            panel,
            cohort_members=cohort_members,
            rebalance_frequency=frequency,
            rebalance_once=False,
        )
        control = _h3_exact_cohort_weights(
            panel,
            cohort_members=cohort_members,
            rebalance_frequency=frequency,
            rebalance_once=True,
        )
    else:
        model = get_research_signal_model(spec.strategy, allow_sealed_crypto=True)
        control_model = get_research_signal_model(control_strategy, allow_sealed_crypto=True)
        candidate = model.generate(panel, dict(spec.strategy_params))
        control = control_model.generate(panel, control_params)
    return (
        _validate_generated_weights(candidate, cohort_members=cohort_members, label="candidate"),
        _validate_generated_weights(control, cohort_members=cohort_members, label="control"),
    )


_TERMINAL_EVIDENCED_MARKET_EVENTS = frozenset(
    {
        MARKET_EVENT_DELISTING_CONFIRMED,
        MARKET_EVENT_LISTING_ENDED_CONFIRMED,
        MARKET_EVENT_DELISTED,
    }
)


def _utc_event_timestamp(value: Any, label: str) -> str:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed) or not isinstance(parsed, pd.Timestamp):
        raise CryptoGovernanceError(f"{label} must be a valid timestamp")
    return parsed.isoformat()


def _optional_recovery_price(value: Any, label: str) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        recovery = float(value)
    except (TypeError, ValueError) as exc:
        raise CryptoGovernanceError(f"{label} must be numeric when present") from exc
    if not math.isfinite(recovery) or recovery <= 0:
        raise CryptoGovernanceError(f"{label} must be finite and positive when present")
    return recovery


def _validate_panel_market_event_evidence(
    panel: pd.DataFrame,
    ledger: MarketEventLedger,
    *,
    expected_venue: str,
) -> None:
    """Require every sensitive event copied into the panel to exist in the ledger."""

    if "market_event" not in panel or "timestamp" not in panel:
        raise CryptoGovernanceError("phase panel requires timestamp and market_event columns")
    identity_column = "instrument_id" if "instrument_id" in panel else "symbol"
    if identity_column not in panel:
        raise CryptoGovernanceError("phase panel requires a stable instrument identity")
    expected_venue = expected_venue.strip().lower()
    ledger_index: dict[tuple[str, str, str], Any] = {}
    for event in ledger.events:
        if event.venue != expected_venue:
            raise CryptoGovernanceError(
                "market-event ledger venue does not match the sealed venue policy"
            )
        key = (
            _utc_event_timestamp(event.effective_at_utc, "ledger effective_at_utc"),
            event.instrument_id,
            event.event,
        )
        ledger_index[key] = event

    has_recovery_column = "terminal_recovery_price" in panel
    for row_number, (_, row) in enumerate(panel.iterrows()):
        try:
            tokens = parse_market_events(row["market_event"])
        except ValueError as exc:
            raise CryptoGovernanceError(
                f"panel row {row_number} contains an invalid market_event: {exc}"
            ) from exc
        sensitive = tokens & EVIDENCED_MARKET_EVENTS
        if not sensitive:
            continue
        timestamp = _utc_event_timestamp(row["timestamp"], f"panel row {row_number} timestamp")
        instrument_id = str(row[identity_column])
        if "venue" in panel and str(row["venue"]).strip().lower() != expected_venue:
            raise CryptoGovernanceError(
                f"panel row {row_number} sensitive event has the wrong venue"
            )
        panel_recovery = (
            _optional_recovery_price(
                row["terminal_recovery_price"],
                f"panel row {row_number} terminal_recovery_price",
            )
            if has_recovery_column
            else None
        )
        if panel_recovery is not None and not (sensitive & _TERMINAL_EVIDENCED_MARKET_EVENTS):
            raise CryptoGovernanceError(
                "a panel recovery price requires an exactly evidenced terminal market_event"
            )
        for event_name in sensitive:
            evidence = ledger_index.get((timestamp, instrument_id, event_name))
            if evidence is None:
                raise CryptoGovernanceError(
                    "sensitive panel market_event is not exactly backed by the active "
                    "MarketEventLedger"
                )
            if has_recovery_column and event_name in _TERMINAL_EVIDENCED_MARKET_EVENTS:
                ledger_recovery = _optional_recovery_price(
                    evidence.terminal_recovery_price,
                    "ledger terminal_recovery_price",
                )
                if panel_recovery != ledger_recovery:
                    raise CryptoGovernanceError(
                        "sensitive panel market_event recovery does not match the active "
                        "MarketEventLedger"
                    )


def _validate_common_context(
    *,
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
    gate0_verdict: Gate0Verdict,
    spec: ExperimentSpec,
    panel: pd.DataFrame,
    market_events: MarketEventLedger,
    cohort_members: Sequence[str],
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile],
    verify_all_components: bool,
) -> None:
    manifest.require_trusted("protected crypto P&L generation")
    if verify_all_components:
        verify_component_bytes(manifest, provenance_root)
    else:
        paths = provenance_paths(manifest, provenance_root)
        for policy_key in (
            "selection_panel_component",
            "selection_market_events_component",
        ):
            component_name = str(spec.split_policy[policy_key])
            selection_path = paths[component_name]
            if sha256_of_file(selection_path) != manifest.components[component_name]:
                raise CryptoGovernanceError(
                    f"selection component byte hash mismatch: {component_name}"
                )
    require_gate0_passed(gate0_verdict, "pnl_generation")
    if manifest.digest() != spec.dataset_digest or manifest.dataset_id != spec.dataset_id:
        raise CryptoGovernanceError("manifest identity/digest does not match ExperimentSpec")
    if manifest.venue.lower() != spec.venue.lower() or manifest.code_commit != spec.code_commit:
        raise CryptoGovernanceError("manifest venue/code commit does not match ExperimentSpec")
    if not gate0_verdict.passed or gate0_verdict.status != spec.gate0_status:
        raise CryptoGovernanceError("Gate 0 did not positively pass")
    if gate0_verdict.digest() != spec.gate0_verdict_digest:
        raise CryptoGovernanceError("Gate-0 verdict digest does not match ExperimentSpec")
    if gate0_verdict.evidence_digest() != spec.gate0_evidence_digest:
        raise CryptoGovernanceError("Gate-0 evidence digest does not match ExperimentSpec")
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
            for field_name in (
                "tick_size",
                "quantity_step",
                "min_notional_usd",
                "median_daily_notional_20d_usd",
                "executable_depth_usd",
            )
        ):
            raise CryptoGovernanceError(
                f"{symbol}: tick, quantity step, minimum notional, ADV20, and executable "
                "depth are all required"
            )
    for symbol, fee in taker_fees.items():
        if fee.evidence_class != "REAL_ACCOUNT_SPECIFIC":
            raise CryptoGovernanceError(
                f"{symbol}: account-specific fee bytes are required; assumptions are forbidden"
            )
        if fee.venue != spec.venue or fee.venue_symbol != symbol:
            raise CryptoGovernanceError(
                f"{symbol}: fee evidence venue/symbol metadata contradicts the active instrument"
            )
    if not profiles or any(
        profile.evidence_class not in {"REAL_PUBLIC_RETAIL", "REAL_ACCOUNT_SPECIFIC"}
        for profile in profiles
    ):
        raise CryptoGovernanceError(
            "every active cost profile requires measured source bytes; assumptions are forbidden"
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

    # A digest in a dataclass is only a claim until the original bytes are
    # found under the sealed provenance root and rehashed.  Evidence sources
    # are ordinary manifest components, kept distinct from phase panels and
    # ledgers.  Selection may read these active sources, but never a holdout
    # phase component.
    phase_component_names = {
        str(manifest.policy[field_name])
        for field_name in (
            "selection_panel_component",
            "holdout_panel_component",
            "selection_market_events_component",
            "holdout_market_events_component",
        )
    }
    evidence_digests: dict[str, str] = {
        **{f"fee:{symbol}": fee.raw_sha256 for symbol, fee in taker_fees.items()},
        **{
            f"cost_profile:{profile.tier}": profile.manifest_sha256
            for profile in profiles
            if profile.evidence_class in {"REAL_PUBLIC_RETAIL", "REAL_ACCOUNT_SPECIFIC"}
        },
        **{
            f"market_event:{index}": event.source_sha256
            for index, event in enumerate(market_events.events)
        },
    }
    component_paths = provenance_paths(manifest, provenance_root)
    for evidence_name, expected_digest in sorted(evidence_digests.items()):
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise CryptoGovernanceError(
                f"{evidence_name}: source digest must be a lower-case SHA-256"
            )
        matching_components = sorted(
            name
            for name, digest in manifest.components.items()
            if hmac.compare_digest(digest, expected_digest) and name not in phase_component_names
        )
        if not matching_components:
            raise CryptoGovernanceError(
                f"{evidence_name}: source bytes are not a distinct manifest component"
            )
        for component_name in matching_components:
            source_path = component_paths[component_name]
            if not source_path.is_file() or not hmac.compare_digest(
                sha256_of_file(source_path), expected_digest
            ):
                raise CryptoGovernanceError(
                    f"{evidence_name}: source byte hash mismatch: {component_name}"
                )

    # Validate the in-memory ledger independently from its on-disk component.
    # An empty ledger remains explicit and hash-bound rather than falling back
    # to panel absences as synthetic event evidence.
    if not isinstance(market_events, MarketEventLedger):
        raise CryptoGovernanceError("an explicit MarketEventLedger is required")
    _validate_panel_market_event_evidence(
        panel,
        market_events,
        expected_venue=spec.venue,
    )


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
) -> _PersistedHoldoutEvidence:
    _validate_common_context(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0_verdict,
        spec=spec,
        panel=context.panel,
        market_events=context.market_events,
        cohort_members=cohort_members,
        execution_limits=execution_limits,
        taker_fees=taker_fees,
        profiles=profiles,
        verify_all_components=True,
    )
    persisted = _load_persisted_holdout(context.holdout_directory, expect_revealed=True)
    seal = persisted.seal
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

    authorization = persisted.authorization
    if authorization.digest() != spec.holdout_authorization_digest:
        raise CryptoGovernanceError("holdout authorization digest contradicts ExperimentSpec")
    if (
        authorization.manifest_digest != manifest.digest()
        or authorization.gate0_verdict_digest != gate0_verdict.digest()
        or authorization.gate0_evidence_digest != gate0_verdict.evidence_digest()
    ):
        raise CryptoGovernanceError(
            "persisted holdout authorization does not bind the active manifest and Gate 0"
        )
    reveal = persisted.reveal_record
    if reveal is None:
        raise CryptoGovernanceError("the persisted holdout reveal is missing")
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
    _validate_phase_panel_component(
        manifest=manifest,
        spec=spec,
        panel=context.panel,
        phase="holdout",
    )
    _validate_phase_market_events_component(
        manifest=manifest,
        spec=spec,
        ledger=context.market_events,
        phase="holdout",
    )
    return persisted


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
) -> _PersistedHoldoutEvidence:
    _validate_common_context(
        manifest=manifest,
        provenance_root=provenance_root,
        gate0_verdict=gate0_verdict,
        spec=spec,
        panel=context.panel,
        market_events=context.market_events,
        cohort_members=cohort_members,
        execution_limits=execution_limits,
        taker_fees=taker_fees,
        profiles=profiles,
        verify_all_components=False,
    )
    persisted = _load_persisted_holdout(context.holdout_directory, expect_revealed=False)
    seal = persisted.seal
    if seal.seal() != spec.holdout_seal_digest:
        raise CryptoGovernanceError("selection context does not use the sealed holdout declaration")
    if seal.dataset_id != spec.dataset_id or seal.dataset_digest != spec.dataset_digest:
        raise CryptoGovernanceError("selection declaration does not bind the trusted manifest")
    if (
        seal.selection_start,
        seal.selection_end,
        seal.holdout_start,
        seal.holdout_end,
    ) != (
        spec.selection_start,
        spec.selection_end,
        spec.holdout_start,
        spec.holdout_end,
    ):
        raise CryptoGovernanceError("selection declaration ranges contradict ExperimentSpec")
    authorization = persisted.authorization
    if authorization.digest() != spec.holdout_authorization_digest:
        raise CryptoGovernanceError("holdout authorization digest contradicts ExperimentSpec")
    if (
        authorization.manifest_digest != manifest.digest()
        or authorization.gate0_verdict_digest != gate0_verdict.digest()
        or authorization.gate0_evidence_digest != gate0_verdict.evidence_digest()
    ):
        raise CryptoGovernanceError(
            "persisted holdout authorization does not bind the active manifest and Gate 0"
        )
    timestamps = pd.to_datetime(context.panel["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise CryptoGovernanceError("selection panel contains invalid timestamps")
    days = timestamps.dt.date.map(lambda value: value.isoformat())
    if (days < spec.selection_start).any() or (days > spec.selection_end).any():
        raise CryptoGovernanceError("selection panel reaches outside the sealed selection range")
    if days.min() != spec.selection_start or days.max() != spec.selection_end:
        raise CryptoGovernanceError("selection panel must cover the exact sealed selection range")
    _validate_phase_panel_component(
        manifest=manifest,
        spec=spec,
        panel=context.panel,
        phase="selection",
    )
    _validate_phase_market_events_component(
        manifest=manifest,
        spec=spec,
        ledger=context.market_events,
        phase="selection",
    )
    return persisted


@dataclass(frozen=True)
class _CommonRun:
    candidate_result: EvaluationResult
    control_result: EvaluationResult
    benchmark_results: Mapping[str, EvaluationResult]
    candidate_payload: Mapping[str, Any]
    control_payload: Mapping[str, Any]
    benchmark_payloads: Mapping[str, Mapping[str, Any]]
    benchmark_digests: Mapping[str, str]
    test_metrics: Mapping[str, Any]
    comparisons: Mapping[str, Any]
    stressed_result: EvaluationResult
    stressed_payload: Mapping[str, Any]
    gate3_derivations: Mapping[str, Mapping[str, Any]]
    gate3_inputs: Mapping[str, Any]
    runtime_provenance: Mapping[str, Any]


def _run_common(
    *,
    panel: pd.DataFrame,
    market_events: MarketEventLedger,
    spec: ExperimentSpec,
    cohort_members: Sequence[str],
    execution_limits: Mapping[str, ExecutionLimits],
    taker_fees: Mapping[str, CostInput],
    profiles: Sequence[TierCostProfile],
) -> _CommonRun:
    try:
        runtime_provenance = verify_runtime_code_commit(spec.code_commit).to_dict()
    except RuntimeProvenanceError as exc:
        raise CryptoGovernanceError(f"runtime code provenance rejected: {exc}") from exc
    candidate_weights, control_weights = _generate_candidate_and_control_weights(
        panel, spec, cohort_members
    )
    panel_timestamps = pd.to_datetime(panel["timestamp"], utc=True)
    for label, weights in (("candidate", candidate_weights), ("control", control_weights)):
        weight_timestamps = pd.to_datetime(weights["timestamp"], utc=True)
        if (weight_timestamps < panel_timestamps.min()).any() or (
            weight_timestamps > panel_timestamps.max()
        ).any():
            raise CryptoGovernanceError(f"{label} targets escape the active phase")

    btc_spec = _benchmark_spec(spec, "btc_buy_and_hold")
    basket_spec = _benchmark_spec(spec, "eligible_equal_weight")
    benchmark_weights = {
        "btc_buy_and_hold": btc_buy_and_hold_benchmark(
            panel,
            instrument_id=str(btc_spec["instrument_id"]),
            expected_venue=spec.venue,
            min_bound_bars=int(btc_spec.get("min_bound_bars", 20)),
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
        if weights.empty:
            raise CryptoGovernanceError(f"{benchmark_id} emitted no benchmark target")
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
    bar_policy = _bar_policy_from_spec(spec)
    limit_map = dict(execution_limits)
    fee_map = dict(taker_fees)

    def evaluate_weights(
        weights: pd.DataFrame,
        *,
        cost_multiplier: float = 1.0,
        fill_fraction_multiplier: float = 1.0,
    ) -> EvaluationResult:
        return evaluate(
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
            market_events=market_events,
            cost_multiplier=cost_multiplier,
            fill_fraction_multiplier=fill_fraction_multiplier,
        )

    candidate_result = evaluate_weights(candidate_weights)
    control_result = evaluate_weights(control_weights)
    benchmark_results = {
        benchmark_id: evaluate_weights(weights)
        for benchmark_id, weights in benchmark_weights.items()
    }
    stressed_result = evaluate_weights(
        candidate_weights,
        cost_multiplier=2.0,
        fill_fraction_multiplier=0.5,
    )
    candidate_payload = _result_payload(candidate_result)
    control_payload = _result_payload(control_result)
    benchmark_payloads = {
        benchmark_id: _result_payload(result) for benchmark_id, result in benchmark_results.items()
    }
    benchmark_digests = {
        benchmark_id: canonical_digest(payload)
        for benchmark_id, payload in benchmark_payloads.items()
    }
    stressed_payload = _result_payload(stressed_result)

    def unavailable(kind: str, exc: Exception) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "available": False,
            "kind": kind,
            "reason": str(exc),
        }
        payload["digest"] = canonical_evidence_digest(payload)
        return payload

    derivations: dict[str, Mapping[str, Any]] = {}
    producers = {
        "economics": lambda: derive_execution_economics(
            candidate_result,
            benchmark_results,
        ),
        "concentration": lambda: derive_pnl_concentration(candidate_result, panel),
        "capacity": lambda: derive_capacity(
            candidate_result,
            limit_map,
            float(spec.selection_criteria["canary_capital_usd"]),
        ),
        "stress": lambda: derive_stress_evidence(
            stressed_result,
            cost_multiplier=2.0,
            fill_fraction=0.5,
        ),
    }
    for kind, producer in producers.items():
        try:
            derivations[kind] = producer()
        except CryptoEconomicEvidenceError as exc:
            # A failed experiment remains in the immutable 15-trial ledger.
            # Missing economic evidence blocks promotion; it must not erase
            # the attempt or turn the research runner into an optimizer.
            derivations[kind] = unavailable(kind, exc)
    limits_payload = {
        instrument_id: asdict(limit) for instrument_id, limit in sorted(limit_map.items())
    }
    gate3_inputs: dict[str, Any] = {
        "panel": {
            "encoding": "canonical_panel_v1",
            "digest": canonical_panel_digest(panel),
            # Market-data bytes remain in the locally verified manifest component.
            # They are deliberately not copied into portable evaluation artifacts
            # until redistribution rights and a local promotion-time loader exist.
            "payload_omitted": "MARKET_DATA_LICENSE_UNRESOLVED",
        },
        "execution_limits": {
            "payload": limits_payload,
            "digest": execution_limits_digest(limit_map),
        },
    }
    returns = candidate_result.equity.pct_change().dropna()
    test_metrics = {
        **return_moments(returns),
        "max_drawdown": _max_drawdown(candidate_result.equity),
        "independent_trade_count": independent_closed_round_trip_count(
            [row.to_dict() for row in candidate_result.executions]
        ),
        "independent_trade_definition": spec.selection_criteria["independent_trade_definition"],
    }
    candidate_summary = candidate_result.summary()
    control_digest = canonical_digest(control_payload)
    control_summary = control_result.summary()
    comparisons: dict[str, Any] = {
        "sealed_control": {
            "artifact_digest": control_digest,
            "net_excess_return": (
                float(candidate_summary["total_return"]) - float(control_summary["total_return"])
            ),
            "control_max_drawdown": _max_drawdown(control_result.equity),
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
        }
    }
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
    return _CommonRun(
        candidate_result,
        control_result,
        benchmark_results,
        candidate_payload,
        control_payload,
        benchmark_payloads,
        benchmark_digests,
        test_metrics,
        comparisons,
        stressed_result,
        stressed_payload,
        derivations,
        gate3_inputs,
        runtime_provenance,
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
) -> ProtectedCryptoRun:
    """Run candidate, sealed control, and both benchmarks through one policy."""

    if not run_id.strip():
        raise CryptoGovernanceError("run_id is required")
    limits = dict(execution_limits)
    fees = dict(taker_fees)
    profile_tuple = tuple(profiles)
    persisted = _validate_holdout_context(
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
    common = _run_common(
        panel=panel,
        market_events=holdout.market_events,
        spec=spec,
        cohort_members=cohort_members,
        execution_limits=limits,
        taker_fees=fees,
        profiles=profile_tuple,
    )

    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "HOLDOUT",
        "promotable": True,
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
        "gate0_verdict_digest": gate0_verdict.digest(),
        "gate0_evidence_digest": gate0_verdict.evidence_digest(),
        "code_commit": spec.code_commit,
        "runtime_provenance": common.runtime_provenance,
        "venue": spec.venue,
        "market_events": holdout.market_events.to_dict(),
        "market_events_component_digest": canonical_market_event_ledger_digest(
            holdout.market_events
        ),
        "holdout": {
            "seal_digest": persisted.seal.seal(),
            "authorization_digest": persisted.authorization.digest(),
            "reveal_digest": persisted.reveal_digest,
            "reveal_count": 1,
            "reveal_record": _json_copy(persisted.reveal_record or {}),
            "test_range": [spec.holdout_start, spec.holdout_end],
        },
        "policy_bindings": {
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
            "benchmark_policy_digest": spec.benchmark_policy_digest,
            "cohort_digest": spec.cohort_digest,
        },
        "candidate_result_digest": canonical_digest(common.candidate_payload),
        "control_result_digest": canonical_digest(common.control_payload),
        "benchmark_artifact_digests": common.benchmark_digests,
        "test_metrics": common.test_metrics,
        "comparisons": common.comparisons,
        "economics": common.gate3_derivations["economics"],
        "stress": common.gate3_derivations["stress"],
        "concentration": common.gate3_derivations["concentration"],
        "capacity": common.gate3_derivations["capacity"],
        "gate3_inputs": common.gate3_inputs,
        "runs": {
            "candidate": common.candidate_payload,
            "control": common.control_payload,
            "benchmarks": common.benchmark_payloads,
            "stress_candidate": common.stressed_payload,
        },
    }
    artifact["artifact_digest"] = evaluation_artifact_digest(artifact)
    return ProtectedCryptoRun(
        artifact,
        common.candidate_result,
        common.control_result,
        common.benchmark_results,
    )


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
    persisted = _validate_selection_context(
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
    common = _run_common(
        panel=selection.panel,
        market_events=selection.market_events,
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
        "dataset_status": manifest.status,
        "gate0_status": gate0_verdict.status,
        "gate0_verdict_digest": gate0_verdict.digest(),
        "gate0_evidence_digest": gate0_verdict.evidence_digest(),
        "code_commit": spec.code_commit,
        "runtime_provenance": common.runtime_provenance,
        "venue": spec.venue,
        "selection_panel_digest": canonical_panel_digest(selection.panel),
        "market_events": selection.market_events.to_dict(),
        "market_events_component_digest": canonical_market_event_ledger_digest(
            selection.market_events
        ),
        "holdout_seal_digest": persisted.seal.seal(),
        "holdout_authorization_digest": persisted.authorization.digest(),
        "holdout_reveal_count": 0,
        "selection_range": [spec.selection_start, spec.selection_end],
        "policy_bindings": {
            "execution_policy_digest": spec.execution_policy_digest,
            "cost_policy_digest": spec.cost_policy_digest,
            "benchmark_policy_digest": spec.benchmark_policy_digest,
            "cohort_digest": spec.cohort_digest,
        },
        "candidate_result_digest": canonical_digest(common.candidate_payload),
        "control_result_digest": canonical_digest(common.control_payload),
        "benchmark_artifact_digests": common.benchmark_digests,
        "test_metrics": common.test_metrics,
        "comparisons": common.comparisons,
        "economics": common.gate3_derivations["economics"],
        "stress": common.gate3_derivations["stress"],
        "concentration": common.gate3_derivations["concentration"],
        "capacity": common.gate3_derivations["capacity"],
        "gate3_inputs": common.gate3_inputs,
        "runs": {
            "candidate": common.candidate_payload,
            "control": common.control_payload,
            "benchmarks": common.benchmark_payloads,
            "stress_candidate": common.stressed_payload,
        },
    }
    artifact["artifact_digest"] = evaluation_artifact_digest(artifact)
    return ProtectedCryptoSelectionRun(
        artifact,
        common.candidate_result,
        common.control_result,
        common.benchmark_results,
    )


__all__ = [
    "ProtectedCryptoRun",
    "ProtectedCryptoSelectionRun",
    "RevealedHoldoutContext",
    "SelectionContext",
    "canonical_market_event_ledger_bytes",
    "canonical_market_event_ledger_digest",
    "canonical_panel_bytes",
    "canonical_panel_digest",
    "cohort_members_digest",
    "cost_profiles_digest",
    "execution_limits_digest",
    "run_protected_crypto_evaluation",
    "run_protected_crypto_selection",
    "taker_fees_digest",
]
