"""Sealed crypto experiment specifications and fail-closed promotion gates.

This module is deliberately independent from the holdout reader.  Everything
here can be constructed and tested using selection-period or synthetic data;
none of the helpers opens, slices, or reveals market data.

Two contracts are provided:

``ExperimentSpec``
    The complete declaration made before an H1--H4 experiment is run.  Nested
    values are recursively frozen, all economically relevant fields enter a
    canonical SHA-256 seal, and the fixed 4+4+4+3 campaign budget is enforced.

``PromotionVerdict``
    A tri-state decision.  Missing evidence is
    ``INSUFFICIENT_EVIDENCE`` rather than a pass or an inferred zero; complete
    evidence that misses a threshold is ``NO_GO``; only complete evidence that
    clears every gate is ``PASS``.  A pass authorizes shadow/paper evaluation
    only and can never authorize real-money trading.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, fields
from datetime import date
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)
from quant_trade.metrics.statistics import (
    expected_max_sharpe,
    psr_from_moments,
    return_moments,
    sharpe_variance_across_trials,
)
from quant_trade.research.crypto_economic_evidence import (
    CryptoEconomicEvidenceError,
    canonical_evidence_digest,
    derive_capacity,
    derive_execution_economics,
    derive_overfitting_evidence,
    derive_pnl_concentration,
    derive_stress_evidence,
)
from quant_trade.research.crypto_evaluator import (
    EvaluationResult,
    ExecutionResult,
    RebalanceRecord,
)
from quant_trade.research.holdout_seal import (
    HoldoutSealError,
    assert_dataset_not_invalidated,
    load_crypto_holdout_authorization,
    load_seal,
    read_reveals,
)
from quant_trade.research.ledger import ledger_integrity_report, read_ledger

SCHEMA_VERSION = 2
SPEC_FILENAME = "experiment_spec.json"
HYPOTHESIS_TRIAL_BUDGETS = MappingProxyType({"H1": 4, "H2": 4, "H3": 4, "H4": 3})
CAMPAIGN_TRIAL_BUDGET = 15
REQUIRED_BENCHMARKS = frozenset({"btc_buy_and_hold", "eligible_equal_weight"})
MIN_VERIFIED_DSR_TRIALS = CAMPAIGN_TRIAL_BUDGET
HYPOTHESIS_STRATEGIES = MappingProxyType(
    {
        "H1": "crypto_capacity_illiquidity",
        "H2": "crypto_death_avoidance",
        "H3": "crypto_annual_equal_weight_rebalance",
        "H4": "crypto_survival_duration",
    }
)
INDEPENDENT_TRADE_DEFINITION = "closed_nonoverlapping_portfolio_round_trip_v1"
_TERMINAL_EXECUTION_STATUSES = frozenset({"TERMINAL_RECOVERY", "WRITTEN_DOWN"})


class CryptoGovernanceError(ValueError):
    """Raised when a spec or evidence artifact contradicts its contract."""


def _freeze(value: Any) -> Any:
    """Recursively make JSON-shaped values immutable."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise CryptoGovernanceError(
        f"experiment specs accept JSON-shaped values only, got {type(value).__name__}"
    )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CryptoGovernanceError(f"{name} is required")


def _parse_day(name: str, value: str) -> date:
    _required_text(name, value)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CryptoGovernanceError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc


def _is_hex_digest(value: str, *, minimum: int, maximum: int) -> bool:
    return minimum <= len(value) <= maximum and all(c in "0123456789abcdefABCDEF" for c in value)


def _benchmark_id(spec: Mapping[str, Any]) -> str:
    return str(spec.get("benchmark_id", spec.get("type", ""))).strip()


def _control_parameter(control: Mapping[str, Any], name: str) -> Any:
    nested = control.get("strategy_params")
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise CryptoGovernanceError("control.strategy_params must be a mapping")
        top_level_overrides = set(control).difference(
            {"strategy", "strategy_params", "comparison_variable"}
        )
        if top_level_overrides:
            raise CryptoGovernanceError(
                "control cannot mix strategy_params with top-level parameter overrides"
            )
        return nested.get(name)
    return control.get(name)


def _validate_hypothesis_strategy_contract(spec: ExperimentSpec) -> None:
    expected_strategy = HYPOTHESIS_STRATEGIES[spec.hypothesis_id]
    if spec.strategy != expected_strategy:
        raise CryptoGovernanceError(f"{spec.hypothesis_id} strategy must be {expected_strategy}")
    control_strategy = str(spec.control.get("strategy", spec.strategy))
    if control_strategy != expected_strategy:
        raise CryptoGovernanceError(f"{spec.hypothesis_id} control must use {expected_strategy}")
    if str(spec.strategy_params.get("rebalance_frequency", "")).lower() != "annual":
        raise CryptoGovernanceError(
            f"{spec.hypothesis_id} candidate must preserve the sealed annual frequency"
        )

    expected_variables = {
        "H1": "liquid_band",
        "H2": "screen_off",
        "H3": "rebalance_once",
        "H4": "min_age_days",
    }
    variable = expected_variables[spec.hypothesis_id]
    if spec.control.get("comparison_variable") != variable:
        raise CryptoGovernanceError(
            f"{spec.hypothesis_id} control.comparison_variable must be {variable}"
        )
    control_value = _control_parameter(spec.control, variable)

    if str(spec.strategy_params.get("rebalance_frequency", "")) != "annual":
        raise CryptoGovernanceError(
            f"{spec.hypothesis_id} candidate must use the sealed annual frequency"
        )

    if spec.hypothesis_id in {"H1", "H2", "H3"}:
        if spec.strategy_params.get(variable, False) is not False:
            raise CryptoGovernanceError(f"{spec.hypothesis_id} candidate {variable} must be false")
        if control_value is not True:
            raise CryptoGovernanceError(f"{spec.hypothesis_id} control {variable} must be true")
    if spec.hypothesis_id == "H3" and spec.strategy_params.get("freeze_cohort") is not True:
        raise CryptoGovernanceError("H3 candidate must freeze its cohort")
    if spec.hypothesis_id == "H4":
        candidate_age = spec.strategy_params.get("min_age_days")
        if (
            isinstance(candidate_age, bool)
            or not isinstance(candidate_age, (int, float))
            or not math.isfinite(float(candidate_age))
            or not float(candidate_age).is_integer()
            or int(candidate_age) <= 0
        ):
            raise CryptoGovernanceError("H4 candidate min_age_days must be an integer > 0")
        if spec.strategy_params.get("exclude_left_censored") is not True:
            raise CryptoGovernanceError("H4 must explicitly exclude left-censored histories")
        if isinstance(control_value, bool) or control_value != 0:
            raise CryptoGovernanceError("H4 control min_age_days must be zero")


def canonical_digest(value: Any) -> str:
    """Return a canonical SHA-256 digest for a JSON-shaped value.

    Mapping keys are normalized to strings by the same recursive conversion
    used by :class:`ExperimentSpec`, which also rejects NaN/Infinity and
    non-JSON objects before anything economically relevant is sealed.
    """

    return sha256_of_text(canonical_dumps(_thaw(_freeze(value))))


@dataclass(frozen=True)
class ExperimentSpec:
    """Immutable, complete declaration for one H1--H4 experiment.

    ``notes`` are filing metadata and intentionally do not enter the seal.  All
    fields that could change an economic result do enter it.
    """

    campaign_id: str
    experiment_id: str
    hypothesis_id: str
    hypothesis: str
    strategy: str
    strategy_params: Mapping[str, Any]
    control: Mapping[str, Any]
    refutation: str
    dataset_id: str
    dataset_digest: str
    dataset_status: str
    gate0_status: str
    gate0_verdict_digest: str
    gate0_evidence_digest: str
    code_commit: str
    venue: str
    venue_policy: Mapping[str, Any]
    universe_policy: Mapping[str, Any]
    selection_start: str
    selection_end: str
    holdout_start: str
    holdout_end: str
    selection_panel_digest: str
    holdout_panel_digest: str
    holdout_seal_digest: str
    holdout_authorization_digest: str
    cohort_digest: str
    split_policy: Mapping[str, Any]
    walk_forward_policy: Mapping[str, Any]
    benchmarks: Sequence[Mapping[str, Any]]
    execution_policy: Mapping[str, Any]
    cost_policy: Mapping[str, Any]
    selection_criteria: Mapping[str, Any]
    trial_budget: int
    campaign_trial_budgets: Mapping[str, int]
    registered_at_utc: str
    schema_version: int = SCHEMA_VERSION
    notes: Sequence[str] = ()

    def __post_init__(self) -> None:
        mapping_fields = (
            "strategy_params",
            "control",
            "venue_policy",
            "universe_policy",
            "split_policy",
            "walk_forward_policy",
            "execution_policy",
            "cost_policy",
            "selection_criteria",
            "campaign_trial_budgets",
        )
        for name in mapping_fields:
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise CryptoGovernanceError(f"{name} must be a mapping")
            object.__setattr__(self, name, _freeze(value))
        if not isinstance(self.benchmarks, (list, tuple)):
            raise CryptoGovernanceError("benchmarks must be a sequence")
        object.__setattr__(self, "benchmarks", _freeze(self.benchmarks))
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))

        for name in (
            "campaign_id",
            "experiment_id",
            "hypothesis",
            "strategy",
            "refutation",
            "dataset_id",
            "dataset_status",
            "gate0_status",
            "venue",
            "registered_at_utc",
        ):
            _required_text(name, str(getattr(self, name)))
        if self.hypothesis_id not in HYPOTHESIS_TRIAL_BUDGETS:
            raise CryptoGovernanceError("hypothesis_id must be one of H1, H2, H3, or H4")
        if self.schema_version != SCHEMA_VERSION:
            raise CryptoGovernanceError(f"schema_version must be {SCHEMA_VERSION}")
        if not _is_hex_digest(self.dataset_digest, minimum=64, maximum=64):
            raise CryptoGovernanceError("dataset_digest must be a 64-character SHA-256 digest")
        if self.dataset_status != "TRUSTED_CAUSAL":
            raise CryptoGovernanceError(
                "dataset_status must be TRUSTED_CAUSAL before an experiment can be sealed"
            )
        if self.gate0_status != "PASS":
            raise CryptoGovernanceError(
                "gate0_status must be PASS before an experiment can be sealed"
            )
        for name in (
            "gate0_verdict_digest",
            "gate0_evidence_digest",
            "holdout_seal_digest",
            "holdout_authorization_digest",
            "selection_panel_digest",
            "holdout_panel_digest",
        ):
            if not _is_hex_digest(str(getattr(self, name)), minimum=64, maximum=64):
                raise CryptoGovernanceError(f"{name} must be a 64-character SHA-256 digest")
        if not _is_hex_digest(self.cohort_digest, minimum=64, maximum=64):
            raise CryptoGovernanceError("cohort_digest must be a 64-character SHA-256 digest")
        if not _is_hex_digest(self.code_commit, minimum=7, maximum=64):
            raise CryptoGovernanceError("code_commit must be a hexadecimal git commit id")

        selection_start = _parse_day("selection_start", self.selection_start)
        selection_end = _parse_day("selection_end", self.selection_end)
        holdout_start = _parse_day("holdout_start", self.holdout_start)
        holdout_end = _parse_day("holdout_end", self.holdout_end)
        if selection_end < selection_start:
            raise CryptoGovernanceError("selection_end must not precede selection_start")
        if holdout_end < holdout_start:
            raise CryptoGovernanceError("holdout_end must not precede holdout_start")
        if holdout_start <= selection_end:
            raise CryptoGovernanceError("holdout must begin after the selection window")

        required_nonempty = (
            "control",
            "venue_policy",
            "universe_policy",
            "split_policy",
            "walk_forward_policy",
            "execution_policy",
            "cost_policy",
            "selection_criteria",
        )
        for name in required_nonempty:
            if not getattr(self, name):
                raise CryptoGovernanceError(f"{name} must be declared before the run")
        comparison_variable = self.control.get("comparison_variable")
        if not isinstance(comparison_variable, str) or not comparison_variable.strip():
            raise CryptoGovernanceError("control.comparison_variable is required")
        _validate_hypothesis_strategy_contract(self)

        policy_venue = str(self.venue_policy.get("venue", "")).strip()
        if not policy_venue:
            raise CryptoGovernanceError("venue_policy must name its single venue")
        if policy_venue.lower() != self.venue.lower():
            raise CryptoGovernanceError("venue_policy venue must match the experiment venue")
        listed_venues = self.venue_policy.get("venues")
        if listed_venues is not None and tuple(listed_venues) != (self.venue,):
            raise CryptoGovernanceError("an experiment may use exactly one venue")
        if self.venue.lower() != "bybit":
            raise CryptoGovernanceError("the v1 experiment venue must be Bybit")
        if str(self.venue_policy.get("market", "")).lower() != "spot":
            raise CryptoGovernanceError("venue_policy.market must be spot")

        cap_min = self.universe_policy.get("market_cap_min_usd")
        cap_max = self.universe_policy.get("market_cap_max_usd")
        if (
            isinstance(cap_min, bool)
            or isinstance(cap_max, bool)
            or not isinstance(cap_min, (int, float))
            or not isinstance(cap_max, (int, float))
            or float(cap_min) < 10_000_000
            or float(cap_max) > 1_000_000_000
            or float(cap_min) >= float(cap_max)
        ):
            raise CryptoGovernanceError(
                "universe_policy must stay within the USD 10M-1B capitalization band"
            )
        if str(self.universe_policy.get("quote", "")).upper() != "USDT":
            raise CryptoGovernanceError("universe_policy.quote must be USDT")

        panel_encoding = str(self.split_policy.get("panel_component_encoding", ""))
        if panel_encoding != "canonical_panel_v1":
            raise CryptoGovernanceError(
                "split_policy.panel_component_encoding must be canonical_panel_v1"
            )
        phase_components = []
        for name in (
            "selection_panel_component",
            "holdout_panel_component",
            "selection_market_events_component",
            "holdout_market_events_component",
        ):
            component = self.split_policy.get(name)
            if not isinstance(component, str) or not component.strip():
                raise CryptoGovernanceError(f"split_policy.{name} is required")
            phase_components.append(component)
        if len(set(phase_components)) != len(phase_components):
            raise CryptoGovernanceError(
                "panel and market-event components must be distinct for each phase"
            )

        delay = self.execution_policy.get("decision_to_execution_bars")
        if (
            isinstance(delay, bool)
            or not isinstance(delay, (int, float))
            or not math.isfinite(float(delay))
            or not float(delay).is_integer()
            or int(delay) < 1
        ):
            raise CryptoGovernanceError("execution_policy must delay decisions by at least one bar")
        additional_latency = self.execution_policy.get("additional_latency_bars", int(delay) - 1)
        if (
            isinstance(additional_latency, bool)
            or not isinstance(additional_latency, (int, float))
            or not math.isfinite(float(additional_latency))
            or not float(additional_latency).is_integer()
            or int(additional_latency) != int(delay) - 1
        ):
            raise CryptoGovernanceError(
                "execution_policy.additional_latency_bars must equal decision_to_execution_bars - 1"
            )
        if str(self.execution_policy.get("execution_price", "")).lower() != "open":
            raise CryptoGovernanceError("execution_policy.execution_price must be open")
        if self.execution_policy.get("partial_fills") is not True:
            raise CryptoGovernanceError("execution_policy.partial_fills must be enabled")
        for name in ("execution_limits_digest",):
            digest = str(self.execution_policy.get(name, ""))
            if not _is_hex_digest(digest, minimum=64, maximum=64):
                raise CryptoGovernanceError(f"execution_policy.{name} must be a SHA-256 digest")
        if str(self.cost_policy.get("quantile", "")).lower() != "p75":
            raise CryptoGovernanceError("cost_policy.quantile must be p75")
        for name in ("taker_fees_digest", "cost_profiles_digest"):
            digest = str(self.cost_policy.get(name, ""))
            if not _is_hex_digest(digest, minimum=64, maximum=64):
                raise CryptoGovernanceError(f"cost_policy.{name} must be a SHA-256 digest")
        for name, default in (
            ("initial_capital_usd", None),
            ("min_executable_fraction", None),
            ("delisting_recovery", None),
        ):
            value = self.cost_policy.get(name, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CryptoGovernanceError(f"cost_policy.{name} must be numeric")
        if float(self.cost_policy["initial_capital_usd"]) <= 0:
            raise CryptoGovernanceError("cost_policy.initial_capital_usd must be positive")
        if not 0 < float(self.cost_policy["min_executable_fraction"]) <= 1:
            raise CryptoGovernanceError("cost_policy.min_executable_fraction must be in (0, 1]")
        if not 0 <= float(self.cost_policy["delisting_recovery"]) <= 1:
            raise CryptoGovernanceError("cost_policy.delisting_recovery must be in [0, 1]")

        criteria = self.selection_criteria
        fixed_criteria = {
            "min_psr": (0.95, "at least"),
            "min_dsr": (0.95, "at least"),
            "max_pbo": (0.10, "at most"),
            "min_walk_forward_windows": (4.0, "at least"),
            "min_independent_trades": (30.0, "at least"),
            "max_oos_drawdown": (0.25, "at most"),
            "min_gross_alpha_cost_multiple": (2.0, "at least"),
            "max_positive_pnl_share": (0.25, "at most"),
            "min_capacity_canary_multiple": (2.0, "at least"),
        }
        for name, (boundary, direction) in fixed_criteria.items():
            value = criteria.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise CryptoGovernanceError(f"selection_criteria.{name} is required")
            is_strict_enough = (
                float(value) >= boundary if direction == "at least" else float(value) <= boundary
            )
            if not is_strict_enough:
                raise CryptoGovernanceError(
                    f"selection_criteria.{name} must be {direction} {boundary}"
                )
        if not 0 <= float(criteria["max_pbo"]) <= 1:
            raise CryptoGovernanceError("selection_criteria.max_pbo must be in [0, 1]")
        if not 0 <= float(criteria["max_oos_drawdown"]) <= 1:
            raise CryptoGovernanceError("selection_criteria.max_oos_drawdown must be in [0, 1]")
        if not 0 <= float(criteria["max_positive_pnl_share"]) <= 1:
            raise CryptoGovernanceError(
                "selection_criteria.max_positive_pnl_share must be in [0, 1]"
            )
        if criteria.get("require_nonnegative_double_cost_half_fill") is not True:
            raise CryptoGovernanceError(
                "selection_criteria.require_nonnegative_double_cost_half_fill must be true"
            )
        if criteria.get("independent_trade_definition") != INDEPENDENT_TRADE_DEFINITION:
            raise CryptoGovernanceError(
                "selection_criteria.independent_trade_definition must seal the conservative "
                f"{INDEPENDENT_TRADE_DEFINITION} method"
            )
        canary = criteria.get("canary_capital_usd")
        if (
            isinstance(canary, bool)
            or not isinstance(canary, (int, float))
            or not math.isfinite(float(canary))
            or not 0 < float(canary) <= 500
        ):
            raise CryptoGovernanceError("selection_criteria.canary_capital_usd must be in (0, 500]")

        if len(self.benchmarks) != 2 or any(
            not isinstance(item, Mapping) for item in self.benchmarks
        ):
            raise CryptoGovernanceError("exactly two benchmark specifications are required")
        benchmark_ids = {_benchmark_id(item) for item in self.benchmarks}
        if benchmark_ids != REQUIRED_BENCHMARKS:
            raise CryptoGovernanceError(
                "benchmarks must be btc_buy_and_hold and eligible_equal_weight"
            )
        benchmark_map = {_benchmark_id(item): item for item in self.benchmarks}
        btc = benchmark_map["btc_buy_and_hold"]
        if str(btc.get("instrument_id", "")) != "CMC:1":
            raise CryptoGovernanceError("btc_buy_and_hold instrument_id must be CMC:1")
        min_bound_bars = btc.get("min_bound_bars", 20)
        if (
            isinstance(min_bound_bars, bool)
            or not isinstance(min_bound_bars, (int, float))
            or not float(min_bound_bars).is_integer()
            or int(min_bound_bars) < 1
        ):
            raise CryptoGovernanceError("btc_buy_and_hold.min_bound_bars must be an integer >= 1")
        basket = benchmark_map["eligible_equal_weight"]
        if str(basket.get("rebalance_frequency", "")).lower() != "annual":
            raise CryptoGovernanceError("eligible_equal_weight must rebalance annually")
        basket_top_n = basket.get("top_n")
        if (
            isinstance(basket_top_n, bool)
            or not isinstance(basket_top_n, (int, float))
            or not float(basket_top_n).is_integer()
            or int(basket_top_n) < 1
        ):
            raise CryptoGovernanceError("eligible_equal_weight.top_n must be an integer >= 1")

        budgets = {str(key): int(value) for key, value in self.campaign_trial_budgets.items()}
        if budgets != dict(HYPOTHESIS_TRIAL_BUDGETS):
            raise CryptoGovernanceError("campaign trial budgets must be H1=4, H2=4, H3=4, H4=3")
        if sum(budgets.values()) != CAMPAIGN_TRIAL_BUDGET:
            raise CryptoGovernanceError("the campaign trial budget must total 15")
        if self.trial_budget != HYPOTHESIS_TRIAL_BUDGETS[self.hypothesis_id]:
            raise CryptoGovernanceError(
                f"{self.hypothesis_id} trial_budget must be "
                f"{HYPOTHESIS_TRIAL_BUDGETS[self.hypothesis_id]}"
            )

        min_windows = self.walk_forward_policy.get("min_windows")
        if isinstance(min_windows, bool) or not isinstance(min_windows, (int, float)):
            raise CryptoGovernanceError("walk_forward_policy.min_windows is required")
        if int(min_windows) < 4:
            raise CryptoGovernanceError("walk_forward_policy must require at least 4 windows")
        if self.walk_forward_policy.get("selection_only") is not True:
            raise CryptoGovernanceError("walk_forward_policy must be selection-only")
        partitions = self.walk_forward_policy.get("cscv_partitions")
        if type(partitions) is not int or partitions < 4 or partitions > 16 or partitions % 2:
            raise CryptoGovernanceError(
                "walk_forward_policy.cscv_partitions is required and must be an even "
                "integer in [4, 16]"
            )

        # Force serialization now.  NaN/Infinity or a non-canonical nested value
        # must fail at construction, not much later when the experiment is run.
        try:
            canonical_dumps(self.sealed_content())
        except (TypeError, ValueError) as exc:
            raise CryptoGovernanceError("experiment spec is not finite canonical JSON") from exc

    @property
    def max_trials(self) -> int:
        """Compatibility spelling used by the older preregistration helpers."""
        return self.trial_budget

    def sealed_content(self) -> dict[str, Any]:
        return {
            field.name: _thaw(getattr(self, field.name))
            for field in fields(self)
            if field.name != "notes"
        }

    def seal(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    @property
    def execution_policy_digest(self) -> str:
        return canonical_digest(self.execution_policy)

    @property
    def cost_policy_digest(self) -> str:
        return canonical_digest(self.cost_policy)

    @property
    def benchmark_policy_digest(self) -> str:
        return canonical_digest(self.benchmarks)

    def to_dict(self) -> dict[str, Any]:
        payload = {field.name: _thaw(getattr(self, field.name)) for field in fields(self)}
        return {**payload, "seal": self.seal()}


def campaign_spec_compatibility_errors(
    reference: ExperimentSpec,
    campaign_specs: Sequence[ExperimentSpec],
) -> tuple[str, ...]:
    """Return cross-spec contradictions in immutable campaign-wide bindings.

    H1--H4 may vary only their hypothesis, strategy parameters, causal control,
    refutation and experiment identity. Dataset, venue, Gate-0, split, cohort,
    walk-forward and promotion policy are one common experiment environment.
    """

    scalar_fields = (
        "campaign_id",
        "dataset_id",
        "dataset_digest",
        "dataset_status",
        "gate0_status",
        "gate0_verdict_digest",
        "gate0_evidence_digest",
        "code_commit",
        "venue",
        "selection_start",
        "selection_end",
        "holdout_start",
        "holdout_end",
        "selection_panel_digest",
        "holdout_panel_digest",
        "holdout_seal_digest",
        "holdout_authorization_digest",
        "cohort_digest",
    )
    policy_fields = (
        "venue_policy",
        "universe_policy",
        "split_policy",
        "walk_forward_policy",
        "selection_criteria",
        "execution_policy",
        "cost_policy",
        "benchmarks",
    )
    errors: list[str] = []
    for index, trial_spec in enumerate(campaign_specs):
        if not isinstance(trial_spec, ExperimentSpec):
            errors.append(f"campaign_specs[{index}] is not an ExperimentSpec")
            continue
        seal = trial_spec.seal()
        for field_name in scalar_fields:
            if getattr(trial_spec, field_name) != getattr(reference, field_name):
                errors.append(f"{seal}: shared {field_name} mismatch")
        for field_name in policy_fields:
            if canonical_digest(getattr(trial_spec, field_name)) != canonical_digest(
                getattr(reference, field_name)
            ):
                errors.append(f"{seal}: shared {field_name} mismatch")
    return tuple(errors)


def seal_experiment_spec(directory: str | Path, spec: ExperimentSpec) -> tuple[Path, str]:
    """Persist a spec once; refusing overwrite makes the seal pre-commitment."""
    path = Path(directory) / SPEC_FILENAME
    if path.exists():
        raise CryptoGovernanceError(
            f"{path} already exists; a sealed experiment spec is never rewritten"
        )
    atomic_write_json(path, spec.to_dict())
    return path, spec.seal()


def load_experiment_spec(directory: str | Path) -> ExperimentSpec:
    path = Path(directory) / SPEC_FILENAME
    if not path.exists():
        raise CryptoGovernanceError(f"no sealed experiment spec at {path}")
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise CryptoGovernanceError("experiment spec must be a JSON object")
    claimed = str(payload.pop("seal", ""))
    known = {field.name for field in fields(ExperimentSpec)}
    unknown = set(payload).difference(known)
    if unknown:
        raise CryptoGovernanceError(f"unknown experiment spec fields: {sorted(unknown)}")
    try:
        spec = ExperimentSpec(**payload)
    except TypeError as exc:
        raise CryptoGovernanceError("experiment spec is incomplete") from exc
    actual = spec.seal()
    if not claimed or claimed != actual:
        raise CryptoGovernanceError(
            f"experiment spec seal mismatch: stored {claimed[:12]}..., "
            f"content hashes to {actual[:12]}..."
        )
    return spec


def verify_experiment_spec(spec: ExperimentSpec, seal: str) -> bool:
    return bool(seal) and spec.seal() == seal


@dataclass(frozen=True)
class CryptoPromotionThresholds:
    min_psr: float = 0.95
    min_dsr: float = 0.95
    max_pbo: float = 0.10
    min_walk_forward_windows: int = 4
    min_independent_trades: int = 30
    max_oos_drawdown: float = 0.25
    min_gross_alpha_cost_multiple: float = 2.0
    max_positive_pnl_share: float = 0.25
    min_capacity_canary_multiple: float = 2.0

    def __post_init__(self) -> None:
        numeric_values = (
            self.min_psr,
            self.min_dsr,
            self.max_pbo,
            self.min_walk_forward_windows,
            self.min_independent_trades,
            self.max_oos_drawdown,
            self.min_gross_alpha_cost_multiple,
            self.max_positive_pnl_share,
            self.min_capacity_canary_multiple,
        )
        if any(
            isinstance(value, bool) or not math.isfinite(float(value)) for value in numeric_values
        ):
            raise CryptoGovernanceError("promotion thresholds must be finite numeric values")
        floors = (
            (0.95 <= self.min_psr <= 1.0, "min_psr must be in [0.95, 1.0]"),
            (0.95 <= self.min_dsr <= 1.0, "min_dsr must be in [0.95, 1.0]"),
            (0.0 <= self.max_pbo <= 0.10, "max_pbo must be in [0.0, 0.10]"),
            (
                self.min_walk_forward_windows >= 4,
                "min_walk_forward_windows must be >= 4",
            ),
            (self.min_independent_trades >= 30, "min_independent_trades must be >= 30"),
            (
                0.0 <= self.max_oos_drawdown <= 0.25,
                "max_oos_drawdown must be in [0.0, 0.25]",
            ),
            (
                self.min_gross_alpha_cost_multiple >= 2.0,
                "min_gross_alpha_cost_multiple must be >= 2.0",
            ),
            (
                0.0 <= self.max_positive_pnl_share <= 0.25,
                "max_positive_pnl_share must be in [0.0, 0.25]",
            ),
            (
                self.min_capacity_canary_multiple >= 2.0,
                "min_capacity_canary_multiple must be >= 2.0",
            ),
        )
        for passed, message in floors:
            if not passed:
                raise CryptoGovernanceError(message)

    @classmethod
    def from_spec(cls, spec: ExperimentSpec) -> CryptoPromotionThresholds:
        criteria = spec.selection_criteria
        return cls(
            min_psr=float(criteria["min_psr"]),
            min_dsr=float(criteria["min_dsr"]),
            max_pbo=float(criteria["max_pbo"]),
            min_walk_forward_windows=int(criteria["min_walk_forward_windows"]),
            min_independent_trades=int(criteria["min_independent_trades"]),
            max_oos_drawdown=float(criteria["max_oos_drawdown"]),
            min_gross_alpha_cost_multiple=float(criteria["min_gross_alpha_cost_multiple"]),
            max_positive_pnl_share=float(criteria["max_positive_pnl_share"]),
            min_capacity_canary_multiple=float(criteria["min_capacity_canary_multiple"]),
        )


PROMOTION_THRESHOLDS = CryptoPromotionThresholds()


class VerdictStatus(StrEnum):
    PASS = "PASS"
    NO_GO = "NO_GO"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class PromotionCheck:
    name: str
    status: VerdictStatus
    detail: str
    actual: Any = None
    threshold: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "actual": self.actual,
            "threshold": self.threshold,
        }


@dataclass(frozen=True)
class PromotionVerdict:
    status: VerdictStatus
    experiment_id: str
    experiment_spec_seal: str
    checks: tuple[PromotionCheck, ...]
    recomputed: Mapping[str, Any]
    real_money_authorized: bool = False

    @property
    def missing_checks(self) -> tuple[str, ...]:
        return tuple(
            check.name
            for check in self.checks
            if check.status is VerdictStatus.INSUFFICIENT_EVIDENCE
        )

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks if check.status is VerdictStatus.NO_GO)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "experiment_id": self.experiment_id,
            "experiment_spec_seal": self.experiment_spec_seal,
            "checks": [check.to_dict() for check in self.checks],
            "missing_checks": list(self.missing_checks),
            "failed_checks": list(self.failed_checks),
            "recomputed": _thaw(self.recomputed),
            "real_money_authorized": False,
        }


def _path(payload: Mapping[str, Any], *alternatives: tuple[str, ...]) -> Any:
    for keys in alternatives:
        current: Any = payload
        for key in keys:
            if not isinstance(current, Mapping) or key not in current:
                break
            current = current[key]
        else:
            return current
    return None


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _numbers_equal(actual: Any, expected: Any) -> bool:
    left = _finite_number(actual)
    right = _finite_number(expected)
    return (
        left is not None
        and right is not None
        and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-15)
    )


def _record_seal(record: Mapping[str, Any]) -> str:
    return str(record.get("experiment_spec_seal", record.get("preregistration_seal", ""))).strip()


def _record_sharpe(record: Mapping[str, Any]) -> float | None:
    return _finite_number(record.get("test_sharpe_per_period", record.get("sharpe_per_period")))


def _evaluate_unbound_economic_checks(
    evidence: Mapping[str, Any],
    spec: ExperimentSpec,
    *,
    ledger_records: Sequence[Mapping[str, Any]] | None = None,
    ledger_intact: bool | None = None,
    thresholds: CryptoPromotionThresholds = PROMOTION_THRESHOLDS,
) -> PromotionVerdict:
    """Legacy implementation retained only as an internal economic-check helper.

    The public evaluator below first verifies the sealed artifact, holdout and
    hash-chained ledger.  This helper is never exported because its historical
    list/boolean inputs are not an acceptable evidence boundary.
    """
    if not isinstance(evidence, Mapping):
        evidence = {}
    checks: list[PromotionCheck] = []
    recomputed: dict[str, Any] = {}

    def add_binding(name: str, actual: Any, expected: Any) -> None:
        if actual is None or (isinstance(actual, str) and not actual.strip()):
            checks.append(
                PromotionCheck(
                    name,
                    VerdictStatus.INSUFFICIENT_EVIDENCE,
                    f"{name} is missing",
                    actual,
                    expected,
                )
            )
        elif actual == expected or _numbers_equal(actual, expected):
            checks.append(
                PromotionCheck(name, VerdictStatus.PASS, "binding matches", actual, expected)
            )
        else:
            checks.append(
                PromotionCheck(
                    name,
                    VerdictStatus.NO_GO,
                    "binding contradicts the sealed spec",
                    actual,
                    expected,
                )
            )

    def add_numeric(
        name: str,
        actual: float | None,
        passed: bool | None,
        threshold: Any,
        detail: str,
    ) -> None:
        if actual is None or passed is None:
            status = VerdictStatus.INSUFFICIENT_EVIDENCE
            message = f"{name} is missing or non-finite"
        else:
            status = VerdictStatus.PASS if passed else VerdictStatus.NO_GO
            message = detail
        checks.append(PromotionCheck(name, status, message, actual, threshold))

    spec_seal = spec.seal()
    add_binding(
        "experiment_spec_binding",
        _path(evidence, ("experiment_spec_seal",), ("bindings", "experiment_spec_seal")),
        spec_seal,
    )
    add_binding(
        "dataset_binding",
        _path(
            evidence,
            ("dataset_digest",),
            ("dataset_binding", "dataset_digest"),
            ("dataset_binding", "data_sha256"),
        ),
        spec.dataset_digest,
    )
    add_binding(
        "dataset_status_binding",
        _path(evidence, ("dataset_status",), ("dataset_binding", "status")),
        spec.dataset_status,
    )
    add_binding(
        "gate0_status_binding",
        _path(evidence, ("gate0_status",), ("gate0", "status")),
        spec.gate0_status,
    )
    add_binding(
        "gate0_verdict_binding",
        _path(
            evidence,
            ("gate0_verdict_digest",),
            ("gate0", "verdict_digest"),
        ),
        spec.gate0_verdict_digest,
    )
    add_binding(
        "gate0_evidence_binding",
        _path(
            evidence,
            ("gate0_evidence_digest",),
            ("gate0", "evidence_digest"),
        ),
        spec.gate0_evidence_digest,
    )
    add_binding(
        "code_commit_binding",
        _path(evidence, ("code_commit",), ("bindings", "code_commit")),
        spec.code_commit,
    )
    add_binding("venue_binding", _path(evidence, ("venue",)), spec.venue)

    if ledger_records is None:
        embedded = _path(evidence, ("ledger", "records"), ("ledger_records",))
        if isinstance(embedded, Sequence) and not isinstance(embedded, (str, bytes)):
            ledger_records = [row for row in embedded if isinstance(row, Mapping)]
    if ledger_intact is None:
        embedded_integrity = _path(evidence, ("ledger", "intact"), ("ledger_intact",))
        ledger_intact = embedded_integrity if isinstance(embedded_integrity, bool) else None

    if ledger_intact is None:
        checks.append(
            PromotionCheck(
                "ledger_integrity",
                VerdictStatus.INSUFFICIENT_EVIDENCE,
                "ledger integrity evidence is missing",
            )
        )
    else:
        checks.append(
            PromotionCheck(
                "ledger_integrity",
                VerdictStatus.PASS if ledger_intact else VerdictStatus.NO_GO,
                "ledger is intact" if ledger_intact else "ledger is corrupt or unverified",
                ledger_intact,
                True,
            )
        )

    records = list(ledger_records) if ledger_records is not None else []
    if ledger_records is None:
        checks.append(
            PromotionCheck(
                "ledger_records_present",
                VerdictStatus.INSUFFICIENT_EVIDENCE,
                "trial ledger records are missing",
            )
        )
    elif not records:
        checks.append(
            PromotionCheck(
                "ledger_records_present",
                VerdictStatus.INSUFFICIENT_EVIDENCE,
                "trial ledger contains no records",
                0,
                ">= 1",
            )
        )
    else:
        checks.append(
            PromotionCheck(
                "ledger_records_present",
                VerdictStatus.PASS,
                "trial ledger is present",
                len(records),
                ">= 1",
            )
        )

    spec_records = [record for record in records if _record_seal(record) == spec_seal]
    run_id_raw = _path(evidence, ("run_id",), ("bindings", "run_id"))
    run_id = str(run_id_raw).strip() if run_id_raw is not None else ""
    if not run_id:
        checks.append(
            PromotionCheck(
                "candidate_run_binding",
                VerdictStatus.INSUFFICIENT_EVIDENCE,
                "run_id is missing",
            )
        )
    else:
        matching_run = [row for row in spec_records if str(row.get("run_id", "")) == run_id]
        contradictory = [
            row
            for row in records
            if str(row.get("run_id", "")) == run_id and _record_seal(row) != spec_seal
        ]
        if matching_run and not contradictory:
            status = VerdictStatus.PASS
            detail = "candidate run is bound to this exact experiment spec"
        elif contradictory:
            status = VerdictStatus.NO_GO
            detail = "candidate run is recorded under a different or empty spec seal"
        else:
            status = VerdictStatus.INSUFFICIENT_EVIDENCE
            detail = "candidate run is absent from the spec-bound ledger records"
        checks.append(PromotionCheck("candidate_run_binding", status, detail, run_id, spec_seal))

    experiment_rows = [
        row for row in records if str(row.get("experiment_id", "")) == spec.experiment_id
    ]
    wrong_experiment_seals = [row for row in experiment_rows if _record_seal(row) != spec_seal]
    if wrong_experiment_seals:
        checks.append(
            PromotionCheck(
                "all_experiment_trials_declared",
                VerdictStatus.NO_GO,
                "the experiment ledger contains trials outside this sealed spec",
                len(wrong_experiment_seals),
                0,
            )
        )
    elif spec_records:
        checks.append(
            PromotionCheck(
                "all_experiment_trials_declared",
                VerdictStatus.PASS,
                "all identifiable experiment trials carry the exact seal",
                0,
                0,
            )
        )
    else:
        checks.append(
            PromotionCheck(
                "all_experiment_trials_declared",
                VerdictStatus.INSUFFICIENT_EVIDENCE,
                "no trials are bound to this experiment spec",
            )
        )

    spent = len(spec_records)
    add_numeric(
        "trial_budget",
        float(spent) if ledger_records is not None else None,
        spent <= spec.trial_budget if ledger_records is not None else None,
        spec.trial_budget,
        "recorded trial count must not exceed the sealed budget",
    )

    sharpe = _finite_number(_path(evidence, ("test_metrics", "sharpe_per_period")))
    observations = _finite_number(_path(evidence, ("test_metrics", "observations")))
    skew = _finite_number(_path(evidence, ("test_metrics", "skewness")))
    kurtosis = _finite_number(_path(evidence, ("test_metrics", "kurtosis")))
    recomputed_psr: float | None = None
    recomputed_dsr: float | None = None
    dsr_threshold: float | None = None
    if (
        sharpe is not None
        and observations is not None
        and skew is not None
        and kurtosis is not None
    ):
        recomputed_psr = psr_from_moments(sharpe, int(observations), skew, kurtosis, 0.0)
        trial_sharpes = [value for row in records if (value := _record_sharpe(row)) is not None]
        variance = sharpe_variance_across_trials(trial_sharpes)
        # The declared 15-trial campaign budget enters DSR even before every
        # trial is spent.  Using only observed trials would reward stopping
        # early after a lucky result.
        dsr_trial_count = max(CAMPAIGN_TRIAL_BUDGET, len(records))
        dsr_threshold = expected_max_sharpe(dsr_trial_count, variance)
        recomputed_dsr = psr_from_moments(
            sharpe,
            int(observations),
            skew,
            kurtosis,
            dsr_threshold,
        )
        recomputed["ledger_trial_count"] = len(records)
        recomputed["dsr_trial_count"] = dsr_trial_count
        recomputed["trial_sharpe_variance"] = variance
    recomputed.update(
        {
            "psr": recomputed_psr,
            "dsr": recomputed_dsr,
            "dsr_threshold": dsr_threshold,
        }
    )
    add_numeric(
        "probabilistic_sharpe",
        recomputed_psr,
        recomputed_psr >= thresholds.min_psr if recomputed_psr is not None else None,
        thresholds.min_psr,
        "recomputed PSR must meet the threshold",
    )
    add_numeric(
        "deflated_sharpe",
        recomputed_dsr,
        recomputed_dsr >= thresholds.min_dsr if recomputed_dsr is not None else None,
        thresholds.min_dsr,
        "recomputed DSR must meet the threshold",
    )

    pbo = _finite_number(
        _path(evidence, ("overfitting", "pbo"), ("overfitting_evidence", "walk_forward_pbo"))
    )
    windows = _finite_number(
        _path(evidence, ("overfitting", "windows"), ("overfitting_evidence", "windows"))
    )
    add_numeric(
        "probability_of_backtest_overfitting",
        pbo,
        pbo <= thresholds.max_pbo if pbo is not None else None,
        thresholds.max_pbo,
        "PBO must not exceed the threshold",
    )
    add_numeric(
        "walk_forward_windows",
        windows,
        windows >= thresholds.min_walk_forward_windows if windows is not None else None,
        thresholds.min_walk_forward_windows,
        "at least four walk-forward windows are required",
    )
    trade_definition = spec.selection_criteria.get("independent_trade_definition")
    definition_valid = trade_definition == INDEPENDENT_TRADE_DEFINITION
    checks.append(
        PromotionCheck(
            "independent_trade_definition",
            (
                VerdictStatus.PASS
                if definition_valid
                else (
                    VerdictStatus.INSUFFICIENT_EVIDENCE
                    if trade_definition is None
                    else VerdictStatus.NO_GO
                )
            ),
            "independent trades must use sealed non-overlapping closed round trips",
            trade_definition,
            INDEPENDENT_TRADE_DEFINITION,
        )
    )
    trade_count = (
        _finite_number(
            _path(
                evidence,
                ("test_metrics", "independent_trade_count"),
                ("test_metrics", "trade_count"),
            )
        )
        if definition_valid
        else None
    )
    add_numeric(
        "independent_trade_count",
        trade_count,
        trade_count >= thresholds.min_independent_trades if trade_count is not None else None,
        thresholds.min_independent_trades,
        "at least 30 independent OOS trades are required",
    )

    comparisons = _path(evidence, ("comparisons",), ("benchmarks",))
    comparisons = comparisons if isinstance(comparisons, Mapping) else {}
    strategy_drawdown = _finite_number(_path(evidence, ("test_metrics", "max_drawdown")))
    strategy_drawdown_abs = abs(strategy_drawdown) if strategy_drawdown is not None else None
    add_numeric(
        "absolute_oos_drawdown",
        strategy_drawdown_abs,
        (
            strategy_drawdown_abs <= thresholds.max_oos_drawdown
            if strategy_drawdown_abs is not None
            else None
        ),
        thresholds.max_oos_drawdown,
        "absolute OOS drawdown must not exceed 25%",
    )
    for benchmark_id in sorted(REQUIRED_BENCHMARKS):
        comparison = comparisons.get(benchmark_id)
        comparison = comparison if isinstance(comparison, Mapping) else {}
        excess = _finite_number(
            comparison.get("net_excess_return", comparison.get("excess_return"))
        )
        add_numeric(
            f"net_excess_vs_{benchmark_id}",
            excess,
            excess > 0.0 if excess is not None else None,
            "> 0",
            "net OOS excess return must be positive",
        )
        benchmark_drawdown = _finite_number(comparison.get("benchmark_max_drawdown"))
        benchmark_drawdown_abs = abs(benchmark_drawdown) if benchmark_drawdown is not None else None
        relative_actual = (
            strategy_drawdown_abs / benchmark_drawdown_abs
            if strategy_drawdown_abs is not None
            and benchmark_drawdown_abs is not None
            and benchmark_drawdown_abs > 0
            else None
        )
        add_numeric(
            f"drawdown_not_worse_than_{benchmark_id}",
            relative_actual,
            relative_actual <= 1.0 if relative_actual is not None else None,
            "<= 1.0x",
            "strategy drawdown must be no worse than the benchmark",
        )

    control = comparisons.get("sealed_control")
    control = control if isinstance(control, Mapping) else {}
    control_excess = _finite_number(control.get("net_excess_return"))
    add_numeric(
        "net_excess_vs_sealed_control",
        control_excess,
        control_excess > 0.0 if control_excess is not None else None,
        "> 0",
        "the treatment must beat its sealed same-cohort control after identical costs",
    )

    gross_alpha = _finite_number(
        _path(
            evidence,
            ("economics", "gross_alpha_return"),
            ("gross_alpha_return",),
        )
    )
    cost_p95 = _finite_number(
        _path(
            evidence,
            ("economics", "total_cost_p95_return"),
            ("total_cost_p95_return",),
        )
    )
    alpha_cost_multiple = (
        gross_alpha / cost_p95
        if gross_alpha is not None and cost_p95 is not None and cost_p95 > 0
        else None
    )
    recomputed["gross_alpha_cost_multiple"] = alpha_cost_multiple
    add_numeric(
        "gross_alpha_vs_p95_cost",
        alpha_cost_multiple,
        (
            alpha_cost_multiple >= thresholds.min_gross_alpha_cost_multiple
            if alpha_cost_multiple is not None
            else None
        ),
        thresholds.min_gross_alpha_cost_multiple,
        "gross expected alpha must be at least twice total p95 cost",
    )

    stressed_return = _finite_number(
        _path(
            evidence,
            ("stress", "double_cost_half_fill_total_return"),
            ("stress", "double_cost_half_fills_total_return"),
        )
    )
    add_numeric(
        "double_cost_half_fill_stress",
        stressed_return,
        stressed_return >= 0.0 if stressed_return is not None else None,
        ">= 0",
        "return must remain non-negative with 2x costs and 50% fills",
    )

    for dimension, path_name in (
        ("asset", "max_asset_positive_pnl_share"),
        ("episode", "max_episode_positive_pnl_share"),
    ):
        share = _finite_number(_path(evidence, ("concentration", path_name), (path_name,)))
        add_numeric(
            f"max_{dimension}_positive_pnl_share",
            share,
            share <= thresholds.max_positive_pnl_share if share is not None else None,
            thresholds.max_positive_pnl_share,
            f"no {dimension} may contribute more than 25% of positive P&L",
        )

    capacity = _finite_number(_path(evidence, ("capacity", "capacity_usd"), ("capacity_usd",)))
    canary = _finite_number(
        _path(evidence, ("capacity", "canary_capital_usd"), ("canary_capital_usd",))
    )
    capacity_multiple = (
        capacity / canary if capacity is not None and canary is not None and canary > 0 else None
    )
    recomputed["capacity_canary_multiple"] = capacity_multiple
    add_numeric(
        "capacity_for_two_canaries",
        capacity_multiple,
        (
            capacity_multiple >= thresholds.min_capacity_canary_multiple
            if capacity_multiple is not None
            else None
        ),
        thresholds.min_capacity_canary_multiple,
        "measured capacity must cover at least twice the planned canary",
    )

    if any(check.status is VerdictStatus.INSUFFICIENT_EVIDENCE for check in checks):
        status = VerdictStatus.INSUFFICIENT_EVIDENCE
    elif any(check.status is VerdictStatus.NO_GO for check in checks):
        status = VerdictStatus.NO_GO
    else:
        status = VerdictStatus.PASS
    return PromotionVerdict(
        status=status,
        experiment_id=spec.experiment_id,
        experiment_spec_seal=spec_seal,
        checks=tuple(checks),
        recomputed=_freeze(recomputed),
        real_money_authorized=False,
    )


_STRICT_CRYPTO_LEDGER_FIELDS = frozenset(
    {
        "schema_version",
        "phase",
        "campaign_id",
        "experiment_id",
        "hypothesis_id",
        "experiment_spec_seal",
        "run_id",
        "status",
        "dataset_digest",
        "code_commit",
        "artifact_digest",
        "candidate_result_digest",
        "control_result_digest",
        "source",
        "holdout_seal_digest",
        "holdout_authorization_digest",
        "execution_policy_digest",
        "cost_policy_digest",
        "benchmark_policy_digest",
        "cohort_digest",
        "metrics_digest",
        "benchmark_artifacts_digest",
        "test_range",
        "test_sharpe_per_period",
        "sequence",
        "previous_hash",
        "entry_hash",
    }
)
_LEDGER_DIGEST_FIELDS = frozenset(
    {
        "experiment_spec_seal",
        "dataset_digest",
        "artifact_digest",
        "candidate_result_digest",
        "control_result_digest",
        "holdout_seal_digest",
        "holdout_authorization_digest",
        "execution_policy_digest",
        "cost_policy_digest",
        "benchmark_policy_digest",
        "cohort_digest",
        "metrics_digest",
        "benchmark_artifacts_digest",
        "entry_hash",
    }
)
_REPLACED_UNBOUND_CHECKS = frozenset(
    {
        "ledger_integrity",
        "ledger_records_present",
        "candidate_run_binding",
        "all_experiment_trials_declared",
        "trial_budget",
        "deflated_sharpe",
    }
)


def evaluation_artifact_digest(evidence: Mapping[str, Any]) -> str:
    """Hash a final evaluation artifact without its self-referential digest field."""

    payload = {str(key): value for key, value in evidence.items() if key != "artifact_digest"}
    return canonical_digest(payload)


def _strict_crypto_ledger_errors(record: Mapping[str, Any]) -> tuple[str, ...]:
    missing = sorted(_STRICT_CRYPTO_LEDGER_FIELDS.difference(record))
    errors = [f"missing {name}" for name in missing]
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if record.get("source") != "protected_crypto_runner":
        errors.append("source must be protected_crypto_runner")
    phase = record.get("phase")
    if phase not in {"SELECTION", "HOLDOUT"}:
        errors.append("phase must be SELECTION or HOLDOUT")
    if phase == "HOLDOUT":
        reveal_digest = str(record.get("holdout_reveal_digest", ""))
        if not _is_hex_digest(reveal_digest, minimum=64, maximum=64):
            errors.append("HOLDOUT rows require holdout_reveal_digest")
    elif str(record.get("holdout_reveal_digest", "")).strip():
        errors.append("SELECTION rows cannot carry a holdout reveal digest")
    if str(record.get("preregistration_seal", "")).strip():
        errors.append("legacy preregistration_seal is forbidden for crypto Gate 3")
    for name in _LEDGER_DIGEST_FIELDS:
        value = str(record.get(name, ""))
        if not _is_hex_digest(value, minimum=64, maximum=64):
            errors.append(f"{name} must be a SHA-256 digest")
    if record.get("hypothesis_id") not in HYPOTHESIS_TRIAL_BUDGETS:
        errors.append("hypothesis_id must be H1, H2, H3, or H4")
    if record.get("status") not in {"evaluated", "failed", "discarded"}:
        errors.append("status must be evaluated, failed, or discarded")
    test_range = record.get("test_range")
    if not isinstance(test_range, list) or len(test_range) != 2:
        errors.append("test_range must be a two-element JSON list")
    return tuple(errors)


def _status_from_checks(checks: Sequence[PromotionCheck]) -> VerdictStatus:
    if any(check.status is VerdictStatus.INSUFFICIENT_EVIDENCE for check in checks):
        return VerdictStatus.INSUFFICIENT_EVIDENCE
    if any(check.status is VerdictStatus.NO_GO for check in checks):
        return VerdictStatus.NO_GO
    return VerdictStatus.PASS


def independent_closed_round_trip_count(
    executions: Sequence[Mapping[str, Any]],
) -> int:
    """Count the maximum set of non-overlapping closed portfolio episodes.

    An instrument episode opens only when filled buys move its reconstructed
    position from zero to positive and closes only when filled sells return it
    to zero. ``TERMINAL_RECOVERY`` and ``WRITTEN_DOWN`` close the remaining
    position even when venue-filled quantity is zero. Partial executions stay
    inside one episode and never manufacture additional observations.

    Episodes across instruments can overlap. Sorting by close time and greedily
    accepting only intervals that begin strictly after the prior accepted close
    yields the maximum number of temporally non-overlapping portfolio episodes.
    """

    if isinstance(executions, (str, bytes)) or not isinstance(executions, Sequence):
        raise CryptoGovernanceError("executions must be a sequence of mappings")
    normalized: list[tuple[pd.Timestamp, int, Mapping[str, Any]]] = []
    for index, execution in enumerate(executions):
        if not isinstance(execution, Mapping):
            raise CryptoGovernanceError("every execution must be a mapping")
        quantity = _finite_number(execution.get("filled_quantity"))
        if quantity is not None and quantity < 0:
            raise CryptoGovernanceError("filled_quantity cannot be negative")
        status = str(execution.get("status", "")).upper()
        active = (quantity is not None and quantity > 0) or (status in _TERMINAL_EXECUTION_STATUSES)
        if not active:
            continue
        timestamp = pd.to_datetime(execution.get("execution_timestamp"), utc=True, errors="coerce")
        if pd.isna(timestamp):
            raise CryptoGovernanceError(
                "filled and terminal executions require execution_timestamp"
            )
        normalized.append((pd.Timestamp(timestamp), index, execution))
    normalized.sort(key=lambda item: (item[0], item[1]))

    positions: dict[str, float] = {}
    opened_at: dict[str, pd.Timestamp] = {}
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    tolerance = 1e-9
    for timestamp, _index, execution in normalized:
        instrument = str(execution.get("instrument_id", "")).strip()
        side = str(execution.get("side", "")).lower()
        quantity = _finite_number(execution.get("filled_quantity")) or 0.0
        status = str(execution.get("status", "")).upper()
        if not instrument or side not in {"buy", "sell"}:
            raise CryptoGovernanceError(
                "economically active executions require instrument_id and buy/sell side"
            )
        prior = positions.get(instrument, 0.0)
        if side == "buy":
            if quantity <= 0:
                raise CryptoGovernanceError("active buy executions require positive fill")
            if prior <= tolerance:
                opened_at[instrument] = timestamp
            positions[instrument] = prior + quantity
            continue

        if status in _TERMINAL_EXECUTION_STATUSES:
            updated = 0.0
        else:
            if quantity <= 0:
                raise CryptoGovernanceError("active sell executions require positive fill")
            if quantity > prior + tolerance:
                raise CryptoGovernanceError("execution history sells more than the open position")
            updated = max(0.0, prior - quantity)
        if prior > tolerance and updated <= tolerance:
            start = opened_at.pop(instrument, None)
            if start is None or timestamp < start:
                raise CryptoGovernanceError("closed execution episode has no causal entry")
            intervals.append((start, timestamp))
            positions.pop(instrument, None)
        else:
            positions[instrument] = updated

    accepted = 0
    last_close: pd.Timestamp | None = None
    for start, close in sorted(intervals, key=lambda item: (item[1], item[0])):
        if last_close is None or start > last_close:
            accepted += 1
            last_close = close
    return accepted


def _annual_completed_cycle_upper_bound(spec: ExperimentSpec) -> int:
    """Upper-bound non-overlapping entry-to-exit cycles under annual entry waves.

    Every accepted portfolio interval must begin strictly after the preceding
    close. Annual strategies can create at most one new independent interval
    per calendar-year entry wave, even when H2 forces several overlapping exits.
    """

    start = _parse_day("holdout_start", spec.holdout_start)
    end = _parse_day("holdout_end", spec.holdout_end)
    return max(0, end.year - start.year + 1)


def _derived_result_metrics(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    equity_rows = payload.get("equity")
    executions = payload.get("executions")
    if (
        not isinstance(equity_rows, Sequence)
        or isinstance(equity_rows, (str, bytes))
        or len(equity_rows) < 2
        or not isinstance(executions, Sequence)
        or isinstance(executions, (str, bytes))
    ):
        return None
    timestamps: list[pd.Timestamp] = []
    values: list[float] = []
    for row in equity_rows:
        if not isinstance(row, Mapping):
            return None
        timestamp = pd.to_datetime(row.get("timestamp"), utc=True, errors="coerce")
        value = _finite_number(row.get("value_usd"))
        if pd.isna(timestamp) or value is None or value <= 0:
            return None
        timestamps.append(pd.Timestamp(timestamp))
        values.append(value)
    if any(right <= left for left, right in zip(timestamps, timestamps[1:], strict=False)):
        return None
    series = pd.Series(values, index=pd.DatetimeIndex(timestamps), dtype=float)
    returns = series.pct_change().dropna()
    try:
        independent_trades = independent_closed_round_trip_count(executions)
    except CryptoGovernanceError:
        return None
    return {
        **return_moments(returns),
        "max_drawdown": float((series / series.cummax() - 1.0).min()),
        "independent_trade_count": independent_trades,
        "independent_trade_definition": INDEPENDENT_TRADE_DEFINITION,
        "total_return": float(series.iloc[-1] / series.iloc[0] - 1.0),
    }


def _selection_return_series(
    artifact: Mapping[str, Any],
    *,
    trial_id: str,
    selection_start: str,
    selection_end: str,
) -> pd.Series:
    runs = artifact.get("runs")
    runs = runs if isinstance(runs, Mapping) else {}
    candidate = runs.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    equity_rows = candidate.get("equity")
    if (
        not isinstance(equity_rows, Sequence)
        or isinstance(equity_rows, (str, bytes))
        or len(equity_rows) < 3
    ):
        raise CryptoGovernanceError(f"selection trial {trial_id} has no usable equity path")
    timestamps: list[pd.Timestamp] = []
    values: list[float] = []
    for row in equity_rows:
        if not isinstance(row, Mapping):
            raise CryptoGovernanceError(f"selection trial {trial_id} equity row is malformed")
        timestamp = pd.to_datetime(row.get("timestamp"), utc=True, errors="coerce")
        value = _finite_number(row.get("value_usd"))
        if pd.isna(timestamp) or value is None or value <= 0:
            raise CryptoGovernanceError(
                f"selection trial {trial_id} equity contains invalid timestamp/value"
            )
        timestamps.append(pd.Timestamp(timestamp))
        values.append(value)
    index = pd.DatetimeIndex(timestamps)
    if not index.is_monotonic_increasing or not index.is_unique:
        raise CryptoGovernanceError(
            f"selection trial {trial_id} equity must be chronological and unique"
        )
    observed_start = index.min().date().isoformat()
    observed_end = index.max().date().isoformat()
    if observed_start != selection_start or observed_end != selection_end:
        raise CryptoGovernanceError(
            f"selection trial {trial_id} equity must cover exactly "
            f"[{selection_start}, {selection_end}]"
        )
    returns = pd.Series(values, index=index, dtype=float).pct_change().dropna()
    returns.attrs["data_scope"] = "selection"
    return returns


def _derive_verified_overfitting(
    *,
    spec: ExperimentSpec,
    selection_records: Sequence[Mapping[str, Any]],
    artifact_map: Mapping[str, Mapping[str, Any]],
    artifacts_verified: bool,
) -> tuple[Mapping[str, Any] | None, PromotionCheck]:
    partitions = spec.walk_forward_policy.get("cscv_partitions")
    if partitions is None:
        return None, PromotionCheck(
            "verified_overfitting_derivation",
            VerdictStatus.INSUFFICIENT_EVIDENCE,
            "CSCV partitions must be sealed before selection trials run",
            None,
            "walk_forward_policy.cscv_partitions",
        )
    if not artifacts_verified:
        return None, PromotionCheck(
            "verified_overfitting_derivation",
            VerdictStatus.INSUFFICIENT_EVIDENCE,
            "PBO requires all 15 selection artifacts to pass byte bindings first",
            None,
            CAMPAIGN_TRIAL_BUDGET,
        )
    trial_returns: dict[str, pd.Series] = {}
    try:
        for record in selection_records:
            run_id = str(record.get("run_id", "")).strip()
            if not run_id or run_id in trial_returns:
                raise CryptoGovernanceError("selection run identifiers must be unique")
            artifact = artifact_map.get(run_id)
            if artifact is None:
                raise CryptoGovernanceError(f"selection artifact {run_id} is missing")
            trial_returns[run_id] = _selection_return_series(
                artifact,
                trial_id=run_id,
                selection_start=spec.selection_start,
                selection_end=spec.selection_end,
            )
        if len(trial_returns) != CAMPAIGN_TRIAL_BUDGET:
            raise CryptoGovernanceError("exactly 15 selection return paths are required")
        derived = derive_overfitting_evidence(
            trial_returns,
            partitions=int(partitions),
            min_windows=int(spec.walk_forward_policy["min_windows"]),
        )
    except (CryptoGovernanceError, CryptoEconomicEvidenceError, TypeError, ValueError) as exc:
        return None, PromotionCheck(
            "verified_overfitting_derivation",
            VerdictStatus.INSUFFICIENT_EVIDENCE,
            f"selection return paths cannot support sealed PBO/walk-forward: {exc}",
            None,
            {"trials": CAMPAIGN_TRIAL_BUDGET, "partitions": partitions},
        )
    walk_forward = derived.get("walk_forward")
    walk_forward = walk_forward if isinstance(walk_forward, Mapping) else {}
    walk_forward_pbo = _finite_number(walk_forward.get("walk_forward_pbo"))
    max_pbo = float(spec.selection_criteria["max_pbo"])
    walk_forward_passed = (
        walk_forward.get("decision") == "PASS"
        and walk_forward_pbo is not None
        and walk_forward_pbo <= max_pbo
    )
    return derived, PromotionCheck(
        "verified_overfitting_derivation",
        VerdictStatus.PASS if walk_forward_passed else VerdictStatus.NO_GO,
        (
            "PBO and passing walk-forward evidence were recomputed from 15 bound paths"
            if walk_forward_passed
            else "sealed walk-forward evidence fails its PBO/decision threshold"
        ),
        {
            "digest": derived["digest"],
            "pbo": derived["pbo"],
            "windows": derived["windows"],
            "walk_forward_pbo": walk_forward_pbo,
            "walk_forward_decision": walk_forward.get("decision"),
        },
        {
            "trials": CAMPAIGN_TRIAL_BUDGET,
            "partitions": partitions,
            "walk_forward_pbo": f"<= {max_pbo}",
            "walk_forward_decision": "PASS",
        },
    )


def _result_from_artifact_payload(
    payload: Mapping[str, Any] | None,
    *,
    label: str,
) -> EvaluationResult:
    if payload is None:
        raise CryptoGovernanceError(f"{label} result payload is missing")
    summary = payload.get("summary")
    equity_rows = payload.get("equity")
    execution_rows = payload.get("executions")
    rebalance_rows = payload.get("rebalances")
    if not isinstance(summary, Mapping):
        raise CryptoGovernanceError(f"{label}.summary is missing")
    if (
        not isinstance(equity_rows, Sequence)
        or isinstance(equity_rows, (str, bytes))
        or len(equity_rows) < 2
    ):
        raise CryptoGovernanceError(f"{label}.equity is incomplete")
    if not isinstance(execution_rows, Sequence) or isinstance(execution_rows, (str, bytes)):
        raise CryptoGovernanceError(f"{label}.executions is missing")
    if not isinstance(rebalance_rows, Sequence) or isinstance(rebalance_rows, (str, bytes)):
        raise CryptoGovernanceError(f"{label}.rebalances is missing")

    timestamps: list[pd.Timestamp] = []
    values: list[float] = []
    for row in equity_rows:
        if not isinstance(row, Mapping):
            raise CryptoGovernanceError(f"{label}.equity contains a malformed row")
        timestamp = pd.to_datetime(row.get("timestamp"), utc=True, errors="coerce")
        value = _finite_number(row.get("value_usd"))
        if pd.isna(timestamp) or value is None or value < 0:
            raise CryptoGovernanceError(f"{label}.equity contains invalid data")
        timestamps.append(pd.Timestamp(timestamp))
        values.append(value)
    try:
        executions = [
            ExecutionResult(**dict(row)) for row in execution_rows if isinstance(row, Mapping)
        ]
        rebalances = [
            RebalanceRecord(**dict(row)) for row in rebalance_rows if isinstance(row, Mapping)
        ]
    except TypeError as exc:
        raise CryptoGovernanceError(f"{label} accounting row is incomplete: {exc}") from exc
    if len(executions) != len(execution_rows) or len(rebalances) != len(rebalance_rows):
        raise CryptoGovernanceError(f"{label} accounting rows must be mappings")

    required_summary = (
        "initial_capital_usd",
        "total_turnover",
        "total_cost_usd",
        "delisting_losses_usd",
        "delisted_positions",
        "delisting_recovery",
        "cost_multiplier",
        "fill_fraction_multiplier",
    )
    if any(name not in summary for name in required_summary):
        raise CryptoGovernanceError(f"{label}.summary lacks simulator accounting fields")
    try:
        result = EvaluationResult(
            equity=pd.Series(values, index=pd.DatetimeIndex(timestamps), dtype=float),
            rebalances=rebalances,
            executions=executions,
            total_turnover=float(summary["total_turnover"]),
            total_cost_usd=float(summary["total_cost_usd"]),
            delisting_losses_usd=float(summary["delisting_losses_usd"]),
            delisted_positions=int(summary["delisted_positions"]),
            delisting_recovery=float(summary["delisting_recovery"]),
            initial_capital_usd=float(summary["initial_capital_usd"]),
            cost_multiplier=float(summary["cost_multiplier"]),
            fill_fraction_multiplier=float(summary["fill_fraction_multiplier"]),
        )
    except (TypeError, ValueError) as exc:
        raise CryptoGovernanceError(f"{label}.summary accounting is invalid") from exc
    if canonical_digest(result.summary()) != canonical_digest(summary):
        raise CryptoGovernanceError(f"{label}.summary is not derivable from its result rows")
    return result


def _canonical_evidence_block_error(block: Mapping[str, Any]) -> str | None:
    claimed = block.get("digest")
    if not isinstance(claimed, str) or not claimed:
        return "digest is missing"
    payload = {str(key): value for key, value in block.items() if key != "digest"}
    try:
        actual = canonical_evidence_digest(payload)
    except CryptoEconomicEvidenceError as exc:
        return str(exc)
    return None if claimed == actual else "digest contradicts canonical block bytes"


def _verified_gate3_panel_input(
    evidence: Mapping[str, Any], spec: ExperimentSpec
) -> tuple[pd.DataFrame | None, PromotionCheck]:
    gate3_inputs = evidence.get("gate3_inputs")
    gate3_inputs = gate3_inputs if isinstance(gate3_inputs, Mapping) else {}
    raw = gate3_inputs.get("panel")
    if not isinstance(raw, Mapping) or not isinstance(raw.get("payload"), Mapping):
        return None, PromotionCheck(
            "verified_gate3_panel_input",
            VerdictStatus.INSUFFICIENT_EVIDENCE,
            "gate3_inputs.panel.payload is missing",
        )
    payload = raw["payload"]
    columns = payload.get("columns")
    records = payload.get("records")
    shaped = (
        raw.get("encoding") == "canonical_panel_v1"
        and isinstance(columns, Sequence)
        and not isinstance(columns, (str, bytes))
        and isinstance(records, Sequence)
        and not isinstance(records, (str, bytes))
        and bool(columns)
        and bool(records)
        and all(isinstance(name, str) and name for name in columns)
        and len(set(columns)) == len(columns)
        and all(isinstance(row, Mapping) and set(row) == set(columns) for row in records)
    )
    if not shaped:
        return None, PromotionCheck(
            "verified_gate3_panel_input",
            VerdictStatus.NO_GO,
            "gate3 panel input is present but not canonical_panel_v1 shaped",
        )
    observed_digest = canonical_digest(payload)
    if raw.get("digest") != observed_digest or observed_digest != spec.holdout_panel_digest:
        return None, PromotionCheck(
            "verified_gate3_panel_input",
            VerdictStatus.NO_GO,
            "gate3 panel bytes contradict their digest or sealed holdout component",
            raw.get("digest"),
            spec.holdout_panel_digest,
        )
    frame = pd.DataFrame([dict(row) for row in records], columns=list(columns))
    return frame, PromotionCheck(
        "verified_gate3_panel_input",
        VerdictStatus.PASS,
        "gate3 panel payload hashes to the sealed holdout panel component",
        observed_digest,
        spec.holdout_panel_digest,
    )


def _verified_gate3_execution_limits_input(
    evidence: Mapping[str, Any], spec: ExperimentSpec
) -> tuple[Mapping[str, Any] | None, PromotionCheck]:
    gate3_inputs = evidence.get("gate3_inputs")
    gate3_inputs = gate3_inputs if isinstance(gate3_inputs, Mapping) else {}
    raw = gate3_inputs.get("execution_limits")
    if not isinstance(raw, Mapping) or not isinstance(raw.get("payload"), Mapping):
        return None, PromotionCheck(
            "verified_gate3_execution_limits_input",
            VerdictStatus.INSUFFICIENT_EVIDENCE,
            "gate3_inputs.execution_limits.payload is missing",
        )
    payload = raw["payload"]
    if not payload:
        return None, PromotionCheck(
            "verified_gate3_execution_limits_input",
            VerdictStatus.INSUFFICIENT_EVIDENCE,
            "gate3 execution-limit payload is empty",
        )
    observed_digest = canonical_digest(payload)
    expected_digest = str(spec.execution_policy["execution_limits_digest"])
    if raw.get("digest") != observed_digest or observed_digest != expected_digest:
        return None, PromotionCheck(
            "verified_gate3_execution_limits_input",
            VerdictStatus.NO_GO,
            "execution-limit payload contradicts its digest or sealed policy",
            raw.get("digest"),
            expected_digest,
        )
    return payload, PromotionCheck(
        "verified_gate3_execution_limits_input",
        VerdictStatus.PASS,
        "execution-limit payload hashes to the sealed execution policy",
        observed_digest,
        expected_digest,
    )


def _derive_verified_gate3_blocks(
    evidence: Mapping[str, Any],
    spec: ExperimentSpec,
) -> tuple[dict[str, Mapping[str, Any]], tuple[PromotionCheck, ...]]:
    runs = evidence.get("runs")
    runs = runs if isinstance(runs, Mapping) else {}
    candidate_payload = runs.get("candidate")
    candidate_payload = candidate_payload if isinstance(candidate_payload, Mapping) else None
    benchmark_payloads = runs.get("benchmarks")
    benchmark_payloads = benchmark_payloads if isinstance(benchmark_payloads, Mapping) else {}
    stress_payload = runs.get("stress_candidate")
    stress_payload = stress_payload if isinstance(stress_payload, Mapping) else None
    panel_input, panel_input_check = _verified_gate3_panel_input(evidence, spec)
    limits_input, limits_input_check = _verified_gate3_execution_limits_input(evidence, spec)

    verified: dict[str, Mapping[str, Any]] = {}
    checks: list[PromotionCheck] = [panel_input_check, limits_input_check]
    for name in ("economics", "stress", "concentration", "capacity"):
        raw = evidence.get(name)
        if not isinstance(raw, Mapping):
            checks.append(
                PromotionCheck(
                    f"verified_{name}_derivation",
                    VerdictStatus.INSUFFICIENT_EVIDENCE,
                    f"sealed {name} detail block is missing",
                )
            )
            continue
        digest_error = _canonical_evidence_block_error(raw)
        if digest_error is not None:
            checks.append(
                PromotionCheck(
                    f"verified_{name}_derivation",
                    (
                        VerdictStatus.INSUFFICIENT_EVIDENCE
                        if digest_error == "digest is missing"
                        else VerdictStatus.NO_GO
                    ),
                    f"{name} {digest_error}",
                )
            )
            continue
        if raw.get("available") is False:
            checks.append(
                PromotionCheck(
                    f"verified_{name}_derivation",
                    VerdictStatus.INSUFFICIENT_EVIDENCE,
                    f"runner could not derive {name}: {raw.get('reason', 'unspecified')}",
                    raw.get("digest"),
                    "complete derivation",
                )
            )
            continue
        try:
            candidate = _result_from_artifact_payload(candidate_payload, label="candidate")
            if name == "economics":
                if set(benchmark_payloads) != REQUIRED_BENCHMARKS:
                    raise CryptoGovernanceError("economics requires the exact benchmark pair")
                benchmarks = {
                    benchmark_id: _result_from_artifact_payload(
                        (
                            benchmark_payloads[benchmark_id]
                            if isinstance(benchmark_payloads[benchmark_id], Mapping)
                            else None
                        ),
                        label=f"benchmarks[{benchmark_id}]",
                    )
                    for benchmark_id in sorted(REQUIRED_BENCHMARKS)
                }
                expected = derive_execution_economics(candidate, benchmarks)
            elif name == "stress":
                stressed = _result_from_artifact_payload(
                    stress_payload,
                    label="stress_candidate",
                )
                expected = derive_stress_evidence(
                    stressed,
                    cost_multiplier=2.0,
                    fill_fraction=0.5,
                )
            elif name == "concentration":
                if panel_input is None:
                    raise CryptoGovernanceError("sealed gate3 panel input is unavailable")
                expected = derive_pnl_concentration(candidate, panel_input)
            else:
                if limits_input is None:
                    raise CryptoGovernanceError("sealed gate3 execution-limit input is unavailable")
                expected = derive_capacity(
                    candidate,
                    limits_input,
                    float(spec.selection_criteria["canary_capital_usd"]),
                )
        except (CryptoGovernanceError, CryptoEconomicEvidenceError, TypeError, ValueError) as exc:
            checks.append(
                PromotionCheck(
                    f"verified_{name}_derivation",
                    VerdictStatus.INSUFFICIENT_EVIDENCE,
                    f"{name} cannot be independently reconstructed: {exc}",
                    raw.get("digest"),
                    "complete runner accounting detail",
                )
            )
            continue
        if canonical_digest(raw) != canonical_digest(expected):
            checks.append(
                PromotionCheck(
                    f"verified_{name}_derivation",
                    VerdictStatus.NO_GO,
                    f"{name} identities contradict the bound run/detail",
                    raw.get("digest"),
                    expected.get("digest"),
                )
            )
            continue
        verified[name] = expected
        checks.append(
            PromotionCheck(
                f"verified_{name}_derivation",
                VerdictStatus.PASS,
                f"{name} was independently reconstructed from bound run/detail",
                expected.get("digest"),
                expected.get("digest"),
            )
        )
    return verified, tuple(checks)


def _selection_trial_binding_errors(
    record: Mapping[str, Any],
    trial_spec: ExperimentSpec,
    artifact: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    errors: list[str] = []
    if artifact is None:
        return ("selection artifact is missing",)
    artifact_digest: str | None = None
    with suppress(CryptoGovernanceError, TypeError, ValueError):
        artifact_digest = evaluation_artifact_digest(artifact)
    expected_fields = {
        "phase": "SELECTION",
        "promotable": False,
        "campaign_id": trial_spec.campaign_id,
        "experiment_id": trial_spec.experiment_id,
        "hypothesis_id": trial_spec.hypothesis_id,
        "experiment_spec_seal": trial_spec.seal(),
        "run_id": record.get("run_id"),
        "dataset_digest": trial_spec.dataset_digest,
        "code_commit": trial_spec.code_commit,
        "selection_panel_digest": trial_spec.selection_panel_digest,
        "holdout_seal_digest": trial_spec.holdout_seal_digest,
        "holdout_authorization_digest": trial_spec.holdout_authorization_digest,
        "holdout_reveal_count": 0,
        "selection_range": [trial_spec.selection_start, trial_spec.selection_end],
        "artifact_digest": artifact_digest,
    }
    for name, expected in expected_fields.items():
        if artifact.get(name) != expected:
            errors.append(f"artifact {name} contradicts its ExperimentSpec")
    runtime_provenance = artifact.get("runtime_provenance")
    runtime_provenance = runtime_provenance if isinstance(runtime_provenance, Mapping) else {}
    if (
        runtime_provenance.get("code_commit") != trial_spec.code_commit
        or runtime_provenance.get("clean") is not True
        or runtime_provenance.get("source_mode") != "git-checkout"
        or len(str(runtime_provenance.get("source_tree_digest", ""))) not in {40, 64}
        or not _is_hex_digest(
            str(runtime_provenance.get("source_tree_digest", "")), minimum=40, maximum=64
        )
    ):
        errors.append("runtime provenance does not bind a clean ExperimentSpec commit")
    if record.get("artifact_digest") != artifact_digest:
        errors.append("ledger artifact_digest does not bind the selection artifact")

    policy = artifact.get("policy_bindings")
    policy = policy if isinstance(policy, Mapping) else {}
    expected_policy = {
        "execution_policy_digest": trial_spec.execution_policy_digest,
        "cost_policy_digest": trial_spec.cost_policy_digest,
        "benchmark_policy_digest": trial_spec.benchmark_policy_digest,
        "cohort_digest": trial_spec.cohort_digest,
    }
    for name, expected in expected_policy.items():
        if policy.get(name) != expected or record.get(name) != expected:
            errors.append(f"{name} is not bound across spec, artifact and ledger")

    runs = artifact.get("runs")
    runs = runs if isinstance(runs, Mapping) else {}
    candidate = runs.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else None
    control = runs.get("control")
    control = control if isinstance(control, Mapping) else None
    candidate_digest = canonical_digest(candidate) if candidate is not None else None
    control_digest = canonical_digest(control) if control is not None else None
    if (
        artifact.get("candidate_result_digest") != candidate_digest
        or record.get("candidate_result_digest") != candidate_digest
    ):
        errors.append("candidate result is not byte-bound")
    if (
        artifact.get("control_result_digest") != control_digest
        or record.get("control_result_digest") != control_digest
    ):
        errors.append("control result is not byte-bound")

    benchmark_runs = runs.get("benchmarks")
    benchmark_runs = benchmark_runs if isinstance(benchmark_runs, Mapping) else {}
    benchmark_digests = artifact.get("benchmark_artifact_digests")
    benchmark_digests = benchmark_digests if isinstance(benchmark_digests, Mapping) else {}
    if set(benchmark_runs) != REQUIRED_BENCHMARKS or set(benchmark_digests) != REQUIRED_BENCHMARKS:
        errors.append("selection artifact does not contain the exact benchmark pair")
    else:
        for benchmark_id in REQUIRED_BENCHMARKS:
            payload = benchmark_runs.get(benchmark_id)
            digest = canonical_digest(payload) if isinstance(payload, Mapping) else None
            if benchmark_digests.get(benchmark_id) != digest:
                errors.append(f"{benchmark_id} result is not byte-bound")
    if record.get("benchmark_artifacts_digest") != canonical_digest(benchmark_digests):
        errors.append("benchmark artifact set is not bound to the ledger")

    metrics = artifact.get("test_metrics")
    metrics = metrics if isinstance(metrics, Mapping) else None
    derived = _derived_result_metrics(candidate)
    derived_metrics = (
        {key: value for key, value in derived.items() if key != "total_return"}
        if derived is not None
        else None
    )
    if (
        metrics is None
        or derived_metrics is None
        or canonical_digest(metrics) != canonical_digest(derived_metrics)
    ):
        errors.append("selection metrics are not derivable from candidate equity")
    elif record.get("metrics_digest") != canonical_digest(metrics) or record.get(
        "test_sharpe_per_period"
    ) != metrics.get("sharpe_per_period"):
        errors.append("selection metrics are not exactly bound to the ledger")
    return tuple(errors)


def evaluate_crypto_promotion(
    evidence: Mapping[str, Any],
    spec: ExperimentSpec,
    *,
    ledger_path: str | Path | None = None,
    holdout_directory: str | Path | None = None,
    campaign_specs: Sequence[ExperimentSpec] | None = None,
    campaign_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> PromotionVerdict:
    """Verify the sealed Gate-3 artifact against a strict hash-chained ledger.

    The public boundary intentionally accepts neither caller-supplied ledger
    rows, a caller-supplied integrity boolean, nor caller-supplied thresholds.
    Thresholds are derived from the immutable spec and may be stricter, never
    weaker, than the programme floors.
    """

    if not isinstance(evidence, Mapping):
        evidence = {}
    thresholds = CryptoPromotionThresholds.from_spec(spec)
    strict_checks: list[PromotionCheck] = []

    def add_binding(name: str, actual: Any, expected: Any) -> None:
        if actual is None or (isinstance(actual, str) and not actual.strip()):
            status = VerdictStatus.INSUFFICIENT_EVIDENCE
            detail = f"{name} is missing"
        elif actual == expected or _numbers_equal(actual, expected):
            status = VerdictStatus.PASS
            detail = "binding matches"
        else:
            status = VerdictStatus.NO_GO
            detail = "binding contradicts the sealed artifact or spec"
        strict_checks.append(PromotionCheck(name, status, detail, actual, expected))

    spec_seal = spec.seal()
    add_binding("artifact_phase", evidence.get("phase"), "HOLDOUT")
    add_binding("artifact_promotable", evidence.get("promotable"), True)
    add_binding("campaign_binding", evidence.get("campaign_id"), spec.campaign_id)
    add_binding("experiment_binding", evidence.get("experiment_id"), spec.experiment_id)
    add_binding("dataset_id_binding", evidence.get("dataset_id"), spec.dataset_id)
    runtime_provenance = evidence.get("runtime_provenance")
    runtime_provenance = runtime_provenance if isinstance(runtime_provenance, Mapping) else {}
    add_binding(
        "runtime_code_commit_binding",
        runtime_provenance.get("code_commit"),
        spec.code_commit,
    )
    add_binding("runtime_clean_binding", runtime_provenance.get("clean"), True)
    add_binding(
        "runtime_source_mode_binding",
        runtime_provenance.get("source_mode"),
        "git-checkout",
    )
    runtime_tree_digest = str(runtime_provenance.get("source_tree_digest", ""))
    runtime_tree_valid = len(runtime_tree_digest) in {40, 64} and _is_hex_digest(
        runtime_tree_digest, minimum=40, maximum=64
    )
    strict_checks.append(
        PromotionCheck(
            "runtime_source_tree_binding",
            VerdictStatus.PASS if runtime_tree_valid else VerdictStatus.INSUFFICIENT_EVIDENCE,
            (
                "runtime tree object is content-addressed"
                if runtime_tree_valid
                else "runtime source_tree_digest is missing or malformed"
            ),
            runtime_tree_digest or None,
            "full 40- or 64-character Git tree object id",
        )
    )
    annual_cycle_bound = _annual_completed_cycle_upper_bound(spec)
    required_cycles = int(spec.selection_criteria["min_independent_trades"])
    strict_checks.append(
        PromotionCheck(
            "annual_independent_cycle_feasibility",
            (
                VerdictStatus.PASS
                if annual_cycle_bound >= required_cycles
                else VerdictStatus.INSUFFICIENT_EVIDENCE
            ),
            (
                "the sealed holdout can support the required annual independent cycles"
                if annual_cycle_bound >= required_cycles
                else "annual frequency and holdout length cannot establish 30 independent "
                "non-overlapping round trips; the preregistered requirements conflict"
            ),
            annual_cycle_bound,
            required_cycles,
        )
    )

    holdout = evidence.get("holdout")
    holdout = holdout if isinstance(holdout, Mapping) else {}
    expected_test_range = [spec.holdout_start, spec.holdout_end]
    add_binding("holdout_seal_binding", holdout.get("seal_digest"), spec.holdout_seal_digest)
    add_binding(
        "holdout_authorization_binding",
        holdout.get("authorization_digest"),
        spec.holdout_authorization_digest,
    )
    add_binding("holdout_test_range", holdout.get("test_range"), expected_test_range)
    add_binding("holdout_reveal_count", holdout.get("reveal_count"), 1)

    reveal_record = holdout.get("reveal_record")
    reveal_record = reveal_record if isinstance(reveal_record, Mapping) else None
    claimed_reveal_digest = holdout.get("reveal_digest")
    recomputed_reveal_digest: str | None = None
    if reveal_record is not None:
        try:
            recomputed_reveal_digest = canonical_digest(reveal_record)
        except (CryptoGovernanceError, TypeError, ValueError):
            recomputed_reveal_digest = None
    add_binding("holdout_reveal_digest", claimed_reveal_digest, recomputed_reveal_digest)
    add_binding(
        "holdout_reveal_seal",
        reveal_record.get("seal") if reveal_record is not None else None,
        spec.holdout_seal_digest,
    )
    frozen_selection = reveal_record.get("frozen_selection") if reveal_record is not None else None
    frozen_selection = frozen_selection if isinstance(frozen_selection, Mapping) else {}
    add_binding(
        "holdout_frozen_selection",
        frozen_selection.get("experiment_spec_seal"),
        spec_seal,
    )

    persisted_reveal_digest: str | None = None
    if holdout_directory is None:
        strict_checks.append(
            PromotionCheck(
                "persisted_holdout_evidence",
                VerdictStatus.INSUFFICIENT_EVIDENCE,
                "the persisted holdout directory is required",
            )
        )
    else:
        try:
            persisted_seal = load_seal(holdout_directory)
            assert_dataset_not_invalidated(holdout_directory, persisted_seal.dataset_digest)
            persisted_authorization = load_crypto_holdout_authorization(holdout_directory)
            persisted_reveals = read_reveals(holdout_directory)
        except (HoldoutSealError, OSError, ValueError) as exc:
            strict_checks.append(
                PromotionCheck(
                    "persisted_holdout_evidence",
                    VerdictStatus.NO_GO,
                    f"persisted holdout evidence is invalid: {exc}",
                )
            )
        else:
            persisted_ok = len(persisted_reveals) == 1
            strict_checks.append(
                PromotionCheck(
                    "persisted_holdout_evidence",
                    VerdictStatus.PASS if persisted_ok else VerdictStatus.NO_GO,
                    "exactly one durable reveal must exist",
                    len(persisted_reveals),
                    1,
                )
            )
            add_binding(
                "persisted_holdout_seal",
                persisted_seal.seal(),
                spec.holdout_seal_digest,
            )
            add_binding(
                "persisted_holdout_dataset",
                [persisted_seal.dataset_id, persisted_seal.dataset_digest],
                [spec.dataset_id, spec.dataset_digest],
            )
            add_binding(
                "persisted_holdout_authorization",
                persisted_authorization.digest(),
                spec.holdout_authorization_digest,
            )
            add_binding(
                "persisted_gate0_verdict",
                persisted_authorization.gate0_verdict_digest,
                spec.gate0_verdict_digest,
            )
            add_binding(
                "persisted_gate0_evidence",
                persisted_authorization.gate0_evidence_digest,
                spec.gate0_evidence_digest,
            )
            if persisted_reveals:
                persisted_record = persisted_reveals[0]
                persisted_reveal_digest = canonical_digest(persisted_record)
                add_binding(
                    "artifact_reveal_matches_persisted_log",
                    recomputed_reveal_digest,
                    persisted_reveal_digest,
                )
                add_binding(
                    "artifact_reveal_record_matches_persisted_log",
                    canonical_digest(reveal_record) if reveal_record is not None else None,
                    persisted_reveal_digest,
                )
    verified_reveal_digest = persisted_reveal_digest

    policy_bindings = evidence.get("policy_bindings")
    policy_bindings = policy_bindings if isinstance(policy_bindings, Mapping) else {}
    add_binding(
        "execution_policy_binding",
        policy_bindings.get("execution_policy_digest"),
        spec.execution_policy_digest,
    )
    add_binding(
        "cost_policy_binding",
        policy_bindings.get("cost_policy_digest"),
        spec.cost_policy_digest,
    )
    add_binding(
        "benchmark_policy_binding",
        policy_bindings.get("benchmark_policy_digest"),
        spec.benchmark_policy_digest,
    )
    add_binding("cohort_binding", policy_bindings.get("cohort_digest"), spec.cohort_digest)

    benchmark_digests = evidence.get("benchmark_artifact_digests")
    benchmark_digests = benchmark_digests if isinstance(benchmark_digests, Mapping) else {}
    observed_benchmark_ids = set(str(key) for key in benchmark_digests)
    if not benchmark_digests:
        benchmark_status = VerdictStatus.INSUFFICIENT_EVIDENCE
        benchmark_detail = "benchmark artifact digests are missing"
    elif observed_benchmark_ids != REQUIRED_BENCHMARKS:
        benchmark_status = VerdictStatus.NO_GO
        benchmark_detail = "benchmark artifact digests must contain exactly the sealed pair"
    elif all(
        _is_hex_digest(str(value), minimum=64, maximum=64) for value in benchmark_digests.values()
    ):
        benchmark_status = VerdictStatus.PASS
        benchmark_detail = "both benchmark artifacts are byte-bound"
    else:
        benchmark_status = VerdictStatus.NO_GO
        benchmark_detail = "a benchmark artifact digest is malformed"
    strict_checks.append(
        PromotionCheck(
            "benchmark_artifact_digest_set",
            benchmark_status,
            benchmark_detail,
            sorted(observed_benchmark_ids),
            sorted(REQUIRED_BENCHMARKS),
        )
    )

    comparisons = evidence.get("comparisons")
    comparisons = comparisons if isinstance(comparisons, Mapping) else {}
    runs = evidence.get("runs")
    runs = runs if isinstance(runs, Mapping) else {}
    candidate_run = runs.get("candidate")
    candidate_run = candidate_run if isinstance(candidate_run, Mapping) else None
    candidate_result_digest = evidence.get("candidate_result_digest")
    recomputed_candidate_result_digest = (
        canonical_digest(candidate_run) if candidate_run is not None else None
    )
    add_binding(
        "candidate_result_artifact_binding",
        candidate_result_digest,
        recomputed_candidate_result_digest,
    )
    benchmark_runs = runs.get("benchmarks")
    benchmark_runs = benchmark_runs if isinstance(benchmark_runs, Mapping) else {}
    for benchmark_id in sorted(REQUIRED_BENCHMARKS):
        payload = benchmark_runs.get(benchmark_id)
        recomputed_digest = canonical_digest(payload) if isinstance(payload, Mapping) else None
        add_binding(
            f"{benchmark_id}_result_artifact_binding",
            benchmark_digests.get(benchmark_id),
            recomputed_digest,
        )

    derived_candidate = _derived_result_metrics(candidate_run)
    recomputed_candidate_metrics = (
        {key: value for key, value in derived_candidate.items() if key != "total_return"}
        if derived_candidate is not None
        else None
    )
    candidate_metrics = evidence.get("test_metrics")
    candidate_metrics = candidate_metrics if isinstance(candidate_metrics, Mapping) else None
    add_binding(
        "candidate_metrics_derivation",
        canonical_digest(candidate_metrics) if candidate_metrics is not None else None,
        (
            canonical_digest(recomputed_candidate_metrics)
            if recomputed_candidate_metrics is not None
            else None
        ),
    )
    candidate_summary = candidate_run.get("summary") if candidate_run is not None else None
    add_binding(
        "candidate_summary_total_return_derivation",
        (
            _finite_number(candidate_summary.get("total_return"))
            if isinstance(candidate_summary, Mapping)
            else None
        ),
        derived_candidate.get("total_return") if derived_candidate is not None else None,
    )

    control_run = runs.get("control")
    control_run = control_run if isinstance(control_run, Mapping) else None
    control_result_digest = evidence.get("control_result_digest")
    recomputed_control_result_digest = (
        canonical_digest(control_run) if control_run is not None else None
    )
    add_binding(
        "control_result_artifact_binding",
        control_result_digest,
        recomputed_control_result_digest,
    )
    derived_control = _derived_result_metrics(control_run)
    control_summary = control_run.get("summary") if control_run is not None else None
    add_binding(
        "control_summary_total_return_derivation",
        (
            _finite_number(control_summary.get("total_return"))
            if isinstance(control_summary, Mapping)
            else None
        ),
        derived_control.get("total_return") if derived_control is not None else None,
    )
    control_comparison = comparisons.get("sealed_control")
    control_comparison = control_comparison if isinstance(control_comparison, Mapping) else None
    add_binding(
        "sealed_control_artifact_binding",
        control_comparison.get("artifact_digest") if control_comparison is not None else None,
        recomputed_control_result_digest,
    )
    control_excess = (
        derived_candidate["total_return"] - derived_control["total_return"]
        if derived_candidate is not None and derived_control is not None
        else None
    )
    add_binding(
        "sealed_control_excess_derivation",
        (
            _finite_number(control_comparison.get("net_excess_return"))
            if control_comparison is not None
            else None
        ),
        control_excess,
    )
    add_binding(
        "sealed_control_drawdown_derivation",
        (
            _finite_number(control_comparison.get("control_max_drawdown"))
            if control_comparison is not None
            else None
        ),
        derived_control.get("max_drawdown") if derived_control is not None else None,
    )

    for benchmark_id in sorted(REQUIRED_BENCHMARKS):
        comparison = comparisons.get(benchmark_id)
        comparison = comparison if isinstance(comparison, Mapping) else None
        payload = benchmark_runs.get(benchmark_id)
        benchmark_summary = payload.get("summary") if isinstance(payload, Mapping) else None
        derived_benchmark = _derived_result_metrics(
            payload if isinstance(payload, Mapping) else None
        )
        add_binding(
            f"{benchmark_id}_summary_total_return_derivation",
            (
                _finite_number(benchmark_summary.get("total_return"))
                if isinstance(benchmark_summary, Mapping)
                else None
            ),
            derived_benchmark.get("total_return") if derived_benchmark is not None else None,
        )
        recomputed_excess = (
            derived_candidate["total_return"] - derived_benchmark["total_return"]
            if derived_candidate is not None and derived_benchmark is not None
            else None
        )
        add_binding(
            f"{benchmark_id}_excess_derivation",
            (
                _finite_number(comparison.get("net_excess_return"))
                if comparison is not None
                else None
            ),
            recomputed_excess,
        )
        add_binding(
            f"{benchmark_id}_drawdown_derivation",
            (
                _finite_number(comparison.get("benchmark_max_drawdown"))
                if comparison is not None
                else None
            ),
            derived_benchmark.get("max_drawdown") if derived_benchmark is not None else None,
        )

    comparisons = evidence.get("comparisons")
    comparisons = comparisons if isinstance(comparisons, Mapping) else {}
    for benchmark_id in sorted(REQUIRED_BENCHMARKS):
        comparison = comparisons.get(benchmark_id)
        comparison = comparison if isinstance(comparison, Mapping) else {}
        add_binding(
            f"{benchmark_id}_artifact_binding",
            comparison.get("artifact_digest"),
            benchmark_digests.get(benchmark_id),
        )
        add_binding(
            f"{benchmark_id}_execution_policy_binding",
            comparison.get("execution_policy_digest"),
            spec.execution_policy_digest,
        )
        add_binding(
            f"{benchmark_id}_cost_policy_binding",
            comparison.get("cost_policy_digest"),
            spec.cost_policy_digest,
        )

    claimed_artifact_digest = evidence.get("artifact_digest")
    recomputed_artifact_digest: str | None = None
    with suppress(CryptoGovernanceError, TypeError, ValueError):
        recomputed_artifact_digest = evaluation_artifact_digest(evidence)
    add_binding(
        "evaluation_artifact_integrity",
        claimed_artifact_digest,
        recomputed_artifact_digest,
    )

    ledger_records: list[Mapping[str, Any]] = []
    campaign_records: list[Mapping[str, Any]] = []
    ledger_verified = False
    if ledger_path is None:
        strict_checks.append(
            PromotionCheck(
                "ledger_integrity",
                VerdictStatus.INSUFFICIENT_EVIDENCE,
                "a hash-chained ledger path is required",
            )
        )
    else:
        path = Path(ledger_path)
        read = read_ledger(None, registry_path=path)
        report = ledger_integrity_report(None, registry_path=path)
        ledger_records = list(read.records)
        if not report.exists or not ledger_records:
            ledger_status = VerdictStatus.INSUFFICIENT_EVIDENCE
            ledger_detail = "the ledger is missing or empty"
        elif (
            report.is_intact
            and report.hash_chained_records == report.valid_records
            and report.legacy_records == 0
        ):
            ledger_status = VerdictStatus.PASS
            ledger_detail = "the complete v2 ledger is hash-chained and intact"
            ledger_verified = True
        else:
            ledger_status = VerdictStatus.NO_GO
            ledger_detail = "the ledger is corrupt, unchained, or contains legacy rows"
        strict_checks.append(
            PromotionCheck(
                "ledger_integrity",
                ledger_status,
                ledger_detail,
                report.to_dict(),
                "intact, fully hash-chained, zero legacy rows",
            )
        )

    orphan_related = [
        row
        for row in ledger_records
        if (
            str(row.get("experiment_id", "")) == spec.experiment_id
            or str(row.get("experiment_spec_seal", "")) == spec_seal
        )
        and str(row.get("campaign_id", "")) != spec.campaign_id
    ]
    strict_checks.append(
        PromotionCheck(
            "no_orphan_experiment_trials",
            VerdictStatus.NO_GO if orphan_related else VerdictStatus.PASS,
            (
                "related trials omit or contradict campaign_id"
                if orphan_related
                else "no related trial escapes the campaign filter"
            ),
            len(orphan_related),
            0,
        )
    )

    campaign_records = [
        row for row in ledger_records if str(row.get("campaign_id", "")) == spec.campaign_id
    ]
    malformed = [
        (index, _strict_crypto_ledger_errors(row))
        for index, row in enumerate(campaign_records)
        if _strict_crypto_ledger_errors(row)
    ]
    if not campaign_records:
        strict_status = VerdictStatus.INSUFFICIENT_EVIDENCE
        strict_detail = "no rows are bound to the sealed campaign"
    elif malformed:
        strict_status = VerdictStatus.NO_GO
        strict_detail = "campaign contains malformed or legacy ledger rows"
    else:
        strict_status = VerdictStatus.PASS
        strict_detail = "every campaign row satisfies the strict crypto v2 schema"
    strict_checks.append(
        PromotionCheck(
            "strict_crypto_ledger_schema",
            strict_status,
            strict_detail,
            malformed,
            "zero malformed rows",
        )
    )

    selection_records = [row for row in campaign_records if row.get("phase") == "SELECTION"]
    holdout_records = [row for row in campaign_records if row.get("phase") == "HOLDOUT"]
    counts = Counter(str(row.get("hypothesis_id", "")) for row in selection_records)
    expected_counts = dict(HYPOTHESIS_TRIAL_BUDGETS)
    if any(counts[key] > expected_counts[key] for key in expected_counts):
        budget_status = VerdictStatus.NO_GO
        budget_detail = "a hypothesis exceeded its immutable trial budget"
    elif any(counts[key] < expected_counts[key] for key in expected_counts):
        budget_status = VerdictStatus.INSUFFICIENT_EVIDENCE
        budget_detail = "the complete 4+4+4+3 campaign is not yet recorded"
    elif set(counts).difference(expected_counts):
        budget_status = VerdictStatus.NO_GO
        budget_detail = "the campaign contains an undeclared hypothesis"
    else:
        budget_status = VerdictStatus.PASS
        budget_detail = "the campaign contains exactly the sealed 15 trials"
    strict_checks.append(
        PromotionCheck(
            "campaign_trial_budget",
            budget_status,
            budget_detail,
            dict(counts),
            expected_counts,
        )
    )

    supplied_specs = list(campaign_specs or ())
    specs_by_seal: dict[str, ExperimentSpec] = {}
    campaign_spec_errors = list(campaign_spec_compatibility_errors(spec, supplied_specs))
    for trial_spec in supplied_specs:
        if not isinstance(trial_spec, ExperimentSpec):
            continue
        seal = trial_spec.seal()
        if seal in specs_by_seal:
            campaign_spec_errors.append(f"duplicate campaign spec seal {seal}")
        specs_by_seal[seal] = trial_spec
    spec_counts = Counter(item.hypothesis_id for item in specs_by_seal.values())
    selection_seals = [str(row.get("experiment_spec_seal", "")) for row in selection_records]
    if campaign_specs is None:
        campaign_specs_status = VerdictStatus.INSUFFICIENT_EVIDENCE
        campaign_specs_detail = "all 15 sealed ExperimentSpecs are required"
    elif (
        campaign_spec_errors
        or len(specs_by_seal) != CAMPAIGN_TRIAL_BUDGET
        or dict(spec_counts) != dict(HYPOTHESIS_TRIAL_BUDGETS)
        or set(selection_seals) != set(specs_by_seal)
        or len(selection_seals) != len(set(selection_seals))
        or spec_seal not in specs_by_seal
    ):
        campaign_specs_status = VerdictStatus.NO_GO
        campaign_specs_detail = (
            "selection trials must map one-to-one to 15 unique, policy-compatible specs"
        )
    else:
        campaign_specs_status = VerdictStatus.PASS
        campaign_specs_detail = "all 15 selection trials have unique sealed specifications"
    strict_checks.append(
        PromotionCheck(
            "campaign_experiment_specs",
            campaign_specs_status,
            campaign_specs_detail,
            {
                "specs": len(specs_by_seal),
                "hypotheses": dict(spec_counts),
                "errors": campaign_spec_errors,
            },
            {"specs": CAMPAIGN_TRIAL_BUDGET, "hypotheses": dict(HYPOTHESIS_TRIAL_BUDGETS)},
        )
    )

    artifact_map = dict(campaign_artifacts or {})
    selection_binding_errors: list[tuple[str, tuple[str, ...]]] = []
    for record in selection_records:
        run_id_value = str(record.get("run_id", ""))
        candidate_trial_spec = specs_by_seal.get(str(record.get("experiment_spec_seal", "")))
        if candidate_trial_spec is None:
            selection_binding_errors.append((run_id_value, ("unknown ExperimentSpec seal",)))
            continue
        errors = _selection_trial_binding_errors(
            record,
            candidate_trial_spec,
            artifact_map.get(run_id_value),
        )
        if errors:
            selection_binding_errors.append((run_id_value, errors))
    expected_artifact_ids = {str(row.get("run_id", "")) for row in selection_records}
    extra_artifacts = set(artifact_map).difference(expected_artifact_ids)
    if campaign_artifacts is None:
        artifact_status = VerdictStatus.INSUFFICIENT_EVIDENCE
        artifact_detail = "the 15 complete selection artifacts are required"
    elif selection_binding_errors or extra_artifacts:
        artifact_status = VerdictStatus.NO_GO
        artifact_detail = "a selection ledger row is not exactly derivable from its artifact"
    else:
        artifact_status = VerdictStatus.PASS
        artifact_detail = "all selection rows bind complete runner artifacts"
    strict_checks.append(
        PromotionCheck(
            "selection_trial_artifact_bindings",
            artifact_status,
            artifact_detail,
            {"errors": selection_binding_errors, "extra_artifacts": sorted(extra_artifacts)},
            "exact one-to-one artifact bindings",
        )
    )

    overfitting, overfitting_check = _derive_verified_overfitting(
        spec=spec,
        selection_records=selection_records,
        artifact_map=artifact_map,
        artifacts_verified=artifact_status is VerdictStatus.PASS,
    )
    strict_checks.append(overfitting_check)

    spec_records = [
        row for row in holdout_records if str(row.get("experiment_spec_seal", "")) == spec_seal
    ]

    run_id = str(evidence.get("run_id", "")).strip()
    candidate_rows = [row for row in spec_records if str(row.get("run_id", "")) == run_id]
    test_metrics = evidence.get("test_metrics")
    test_metrics = test_metrics if isinstance(test_metrics, Mapping) else {}
    metrics_digest = canonical_digest(test_metrics)
    benchmark_results_digest = canonical_digest(benchmark_digests)
    expected_candidate = {
        "schema_version": SCHEMA_VERSION,
        "phase": "HOLDOUT",
        "campaign_id": spec.campaign_id,
        "experiment_id": spec.experiment_id,
        "hypothesis_id": spec.hypothesis_id,
        "experiment_spec_seal": spec_seal,
        "run_id": run_id,
        "status": "evaluated",
        "source": "protected_crypto_runner",
        "dataset_digest": spec.dataset_digest,
        "code_commit": spec.code_commit,
        "artifact_digest": recomputed_artifact_digest,
        "candidate_result_digest": recomputed_candidate_result_digest,
        "control_result_digest": recomputed_control_result_digest,
        "holdout_seal_digest": spec.holdout_seal_digest,
        "holdout_authorization_digest": spec.holdout_authorization_digest,
        "holdout_reveal_digest": verified_reveal_digest,
        "execution_policy_digest": spec.execution_policy_digest,
        "cost_policy_digest": spec.cost_policy_digest,
        "benchmark_policy_digest": spec.benchmark_policy_digest,
        "cohort_digest": spec.cohort_digest,
        "metrics_digest": metrics_digest,
        "benchmark_artifacts_digest": benchmark_results_digest,
        "test_range": expected_test_range,
        "test_sharpe_per_period": _finite_number(test_metrics.get("sharpe_per_period")),
    }
    if not run_id:
        candidate_status = VerdictStatus.INSUFFICIENT_EVIDENCE
        candidate_detail = "run_id is missing"
        candidate_actual: Any = None
    elif len(holdout_records) > 1:
        candidate_status = VerdictStatus.NO_GO
        candidate_detail = "the campaign contains more than one holdout evaluation"
        candidate_actual = len(holdout_records)
    elif len(candidate_rows) == 0:
        candidate_status = VerdictStatus.INSUFFICIENT_EVIDENCE
        candidate_detail = "candidate run is absent from the exact spec ledger"
        candidate_actual = None
    elif len(candidate_rows) > 1:
        candidate_status = VerdictStatus.NO_GO
        candidate_detail = "candidate run_id is duplicated"
        candidate_actual = len(candidate_rows)
    else:
        candidate = candidate_rows[0]
        contradictions = {
            key: {"actual": candidate.get(key), "expected": expected}
            for key, expected in expected_candidate.items()
            if candidate.get(key) != expected
        }
        candidate_status = VerdictStatus.NO_GO if contradictions else VerdictStatus.PASS
        candidate_detail = (
            "candidate ledger row contradicts its sealed artifact"
            if contradictions
            else "candidate row exactly binds artifact, holdout, policies and metrics"
        )
        candidate_actual = contradictions
    strict_checks.append(
        PromotionCheck(
            "exact_candidate_ledger_binding",
            candidate_status,
            candidate_detail,
            candidate_actual,
            "exact field-for-field match",
        )
    )

    verified_gate3, gate3_checks = _derive_verified_gate3_blocks(evidence, spec)
    strict_checks.extend(gate3_checks)
    economic_evidence = dict(evidence)
    for name in ("overfitting", "economics", "stress", "concentration", "capacity"):
        economic_evidence.pop(name, None)
    if overfitting is not None:
        economic_evidence["overfitting"] = {
            "pbo": overfitting["pbo"],
            "windows": overfitting["windows"],
        }
    economics = verified_gate3.get("economics")
    if economics is not None:
        economic_evidence["economics"] = {
            "gross_alpha_return": economics["gross_alpha_return"],
            "total_cost_p95_return": economics["total_cost_p95_return"],
        }
    stress = verified_gate3.get("stress")
    if stress is not None:
        economic_evidence["stress"] = {
            "double_cost_half_fill_total_return": stress["double_cost_half_fill_total_return"]
        }
    concentration = verified_gate3.get("concentration")
    if concentration is not None:
        economic_evidence["concentration"] = {
            "max_asset_positive_pnl_share": concentration["max_asset_positive_pnl_share"],
            "max_episode_positive_pnl_share": concentration["max_episode_positive_pnl_share"],
        }
    capacity = verified_gate3.get("capacity")
    if capacity is not None:
        economic_evidence["capacity"] = {
            "capacity_usd": capacity["capacity_usd"],
            "canary_capital_usd": capacity["canary_capital_usd"],
        }
    base = _evaluate_unbound_economic_checks(
        economic_evidence,
        spec,
        ledger_records=selection_records,
        ledger_intact=ledger_verified,
        thresholds=thresholds,
    )
    checks = [
        *strict_checks,
        *(check for check in base.checks if check.name not in _REPLACED_UNBOUND_CHECKS),
    ]

    trial_sharpes = [
        value
        for row in selection_records
        if row.get("status") == "evaluated" and (value := _record_sharpe(row)) is not None
    ]
    variance = sharpe_variance_across_trials(trial_sharpes)
    distribution_ready = (
        ledger_verified
        and not malformed
        and budget_status is VerdictStatus.PASS
        and campaign_specs_status is VerdictStatus.PASS
        and artifact_status is VerdictStatus.PASS
        and len(trial_sharpes) == MIN_VERIFIED_DSR_TRIALS
        and variance > 0
    )
    checks.append(
        PromotionCheck(
            "verified_dsr_distribution",
            VerdictStatus.PASS if distribution_ready else VerdictStatus.INSUFFICIENT_EVIDENCE,
            (
                "all 15 hash-bound campaign Sharpes define a non-degenerate distribution"
                if distribution_ready
                else "DSR requires all 15 evaluated campaign Sharpes and positive variance"
            ),
            {"observations": len(trial_sharpes), "variance": variance},
            {"observations": MIN_VERIFIED_DSR_TRIALS, "variance": "> 0"},
        )
    )

    sharpe = _finite_number(test_metrics.get("sharpe_per_period"))
    observations = _finite_number(test_metrics.get("observations"))
    skew = _finite_number(test_metrics.get("skewness"))
    kurtosis = _finite_number(test_metrics.get("kurtosis"))
    moments_valid = (
        sharpe is not None
        and observations is not None
        and observations.is_integer()
        and observations >= 3
        and skew is not None
        and kurtosis is not None
        and kurtosis > 0
    )
    recomputed_dsr: float | None = None
    dsr_threshold: float | None = None
    if (
        distribution_ready
        and moments_valid
        and sharpe is not None
        and observations is not None
        and skew is not None
        and kurtosis is not None
    ):
        dsr_threshold = expected_max_sharpe(MIN_VERIFIED_DSR_TRIALS, variance)
        recomputed_dsr = psr_from_moments(
            sharpe,
            int(observations),
            skew,
            kurtosis,
            dsr_threshold,
        )
    checks.append(
        PromotionCheck(
            "deflated_sharpe",
            (
                VerdictStatus.INSUFFICIENT_EVIDENCE
                if recomputed_dsr is None
                else (
                    VerdictStatus.PASS
                    if recomputed_dsr >= thresholds.min_dsr
                    else VerdictStatus.NO_GO
                )
            ),
            "DSR is recomputed only from the complete verified campaign distribution",
            recomputed_dsr,
            thresholds.min_dsr,
        )
    )

    recomputed = dict(_thaw(base.recomputed))
    recomputed.update(
        {
            "dsr": recomputed_dsr,
            "dsr_threshold": dsr_threshold,
            "dsr_trial_count": len(trial_sharpes),
            "trial_sharpe_variance": variance,
            "artifact_digest": recomputed_artifact_digest,
            "holdout_reveal_digest": verified_reveal_digest,
        }
    )
    return PromotionVerdict(
        status=_status_from_checks(checks),
        experiment_id=spec.experiment_id,
        experiment_spec_seal=spec_seal,
        checks=tuple(checks),
        recomputed=_freeze(recomputed),
        real_money_authorized=False,
    )


# A short spelling for callers; both names keep the crypto-only scope explicit.
evaluate_promotion_verdict = evaluate_crypto_promotion


__all__ = [
    "CAMPAIGN_TRIAL_BUDGET",
    "HYPOTHESIS_STRATEGIES",
    "HYPOTHESIS_TRIAL_BUDGETS",
    "INDEPENDENT_TRADE_DEFINITION",
    "MIN_VERIFIED_DSR_TRIALS",
    "PROMOTION_THRESHOLDS",
    "REQUIRED_BENCHMARKS",
    "CryptoGovernanceError",
    "CryptoPromotionThresholds",
    "ExperimentSpec",
    "PromotionCheck",
    "PromotionVerdict",
    "VerdictStatus",
    "campaign_spec_compatibility_errors",
    "canonical_digest",
    "evaluate_crypto_promotion",
    "evaluation_artifact_digest",
    "independent_closed_round_trip_count",
    "evaluate_promotion_verdict",
    "load_experiment_spec",
    "seal_experiment_spec",
    "verify_experiment_spec",
]
