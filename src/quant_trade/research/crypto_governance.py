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
from quant_trade.research.ledger import ledger_integrity_report, read_ledger

SCHEMA_VERSION = 2
SPEC_FILENAME = "experiment_spec.json"
HYPOTHESIS_TRIAL_BUDGETS = MappingProxyType({"H1": 4, "H2": 4, "H3": 4, "H4": 3})
CAMPAIGN_TRIAL_BUDGET = 15
REQUIRED_BENCHMARKS = frozenset({"btc_buy_and_hold", "eligible_equal_weight"})
MIN_VERIFIED_DSR_TRIALS = CAMPAIGN_TRIAL_BUDGET


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
        if not _is_hex_digest(self.gate0_evidence_digest, minimum=64, maximum=64):
            raise CryptoGovernanceError(
                "gate0_evidence_digest must be a 64-character SHA-256 digest"
            )
        if not _is_hex_digest(self.holdout_seal_digest, minimum=64, maximum=64):
            raise CryptoGovernanceError("holdout_seal_digest must be a 64-character SHA-256 digest")
        for name in ("selection_panel_digest", "holdout_panel_digest"):
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

        delay = self.execution_policy.get("decision_to_execution_bars")
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or int(delay) < 1:
            raise CryptoGovernanceError("execution_policy must delay decisions by at least one bar")
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
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CryptoGovernanceError(f"selection_criteria.{name} is required")
            is_strict_enough = (
                float(value) >= boundary if direction == "at least" else float(value) <= boundary
            )
            if not is_strict_enough:
                raise CryptoGovernanceError(
                    f"selection_criteria.{name} must be {direction} {boundary}"
                )
        if criteria.get("require_nonnegative_double_cost_half_fill") is not True:
            raise CryptoGovernanceError(
                "selection_criteria.require_nonnegative_double_cost_half_fill must be true"
            )

        if len(self.benchmarks) != 2 or any(
            not isinstance(item, Mapping) for item in self.benchmarks
        ):
            raise CryptoGovernanceError("exactly two benchmark specifications are required")
        benchmark_ids = {_benchmark_id(item) for item in self.benchmarks}
        if benchmark_ids != REQUIRED_BENCHMARKS:
            raise CryptoGovernanceError(
                "benchmarks must be btc_buy_and_hold and eligible_equal_weight"
            )

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
        floors = (
            (self.min_psr >= 0.95, "min_psr must be >= 0.95"),
            (self.min_dsr >= 0.95, "min_dsr must be >= 0.95"),
            (self.max_pbo <= 0.10, "max_pbo must be <= 0.10"),
            (
                self.min_walk_forward_windows >= 4,
                "min_walk_forward_windows must be >= 4",
            ),
            (self.min_independent_trades >= 30, "min_independent_trades must be >= 30"),
            (self.max_oos_drawdown <= 0.25, "max_oos_drawdown must be <= 0.25"),
            (
                self.min_gross_alpha_cost_multiple >= 2.0,
                "min_gross_alpha_cost_multiple must be >= 2.0",
            ),
            (
                self.max_positive_pnl_share <= 0.25,
                "max_positive_pnl_share must be <= 0.25",
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
    trade_count = _finite_number(
        _path(
            evidence,
            ("test_metrics", "independent_trade_count"),
            ("test_metrics", "trade_count"),
        )
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
        "campaign_id",
        "experiment_id",
        "hypothesis_id",
        "experiment_spec_seal",
        "run_id",
        "status",
        "dataset_digest",
        "code_commit",
        "artifact_digest",
        "source",
        "execution_policy_digest",
        "cost_policy_digest",
        "benchmark_policy_digest",
        "cohort_digest",
        "metrics_digest",
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
        "execution_policy_digest",
        "cost_policy_digest",
        "benchmark_policy_digest",
        "cohort_digest",
        "metrics_digest",
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


def evaluate_crypto_promotion(
    evidence: Mapping[str, Any],
    spec: ExperimentSpec,
    *,
    ledger_path: str | Path | None = None,
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
    add_binding("campaign_binding", evidence.get("campaign_id"), spec.campaign_id)
    add_binding("experiment_binding", evidence.get("experiment_id"), spec.experiment_id)
    add_binding("dataset_id_binding", evidence.get("dataset_id"), spec.dataset_id)

    holdout = evidence.get("holdout")
    holdout = holdout if isinstance(holdout, Mapping) else {}
    expected_test_range = [spec.holdout_start, spec.holdout_end]
    add_binding("holdout_seal_binding", holdout.get("seal_digest"), spec.holdout_seal_digest)
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

    recomputed_candidate_metrics: dict[str, Any] | None = None
    if candidate_run is not None:
        equity_rows = candidate_run.get("equity")
        executions = candidate_run.get("executions")
        if isinstance(equity_rows, Sequence) and not isinstance(equity_rows, (str, bytes)):
            equity_values = [
                _finite_number(row.get("value_usd"))
                for row in equity_rows
                if isinstance(row, Mapping)
            ]
            if equity_values and all(value is not None and value > 0 for value in equity_values):
                series = pd.Series([value for value in equity_values if value is not None])
                returns = series.pct_change().dropna()
                recomputed_candidate_metrics = {
                    **return_moments(returns),
                    "max_drawdown": float((series / series.cummax() - 1.0).min()),
                    "independent_trade_count": sum(
                        1
                        for row in executions or []
                        if isinstance(row, Mapping)
                        and (_finite_number(row.get("filled_quantity")) or 0.0) > 0
                    ),
                }
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

    for benchmark_id in sorted(REQUIRED_BENCHMARKS):
        comparison = comparisons.get(benchmark_id)
        comparison = comparison if isinstance(comparison, Mapping) else None
        payload = benchmark_runs.get(benchmark_id)
        candidate_summary = candidate_run.get("summary") if candidate_run is not None else None
        benchmark_summary = payload.get("summary") if isinstance(payload, Mapping) else None
        candidate_total = (
            _finite_number(candidate_summary.get("total_return"))
            if isinstance(candidate_summary, Mapping)
            else None
        )
        benchmark_total = (
            _finite_number(benchmark_summary.get("total_return"))
            if isinstance(benchmark_summary, Mapping)
            else None
        )
        recomputed_excess = (
            candidate_total - benchmark_total
            if candidate_total is not None and benchmark_total is not None
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

    counts = Counter(str(row.get("hypothesis_id", "")) for row in campaign_records)
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

    spec_records = [
        row for row in campaign_records if str(row.get("experiment_spec_seal", "")) == spec_seal
    ]
    if len(spec_records) > spec.trial_budget:
        spec_budget_status = VerdictStatus.NO_GO
    elif len(spec_records) < spec.trial_budget:
        spec_budget_status = VerdictStatus.INSUFFICIENT_EVIDENCE
    else:
        spec_budget_status = VerdictStatus.PASS
    strict_checks.append(
        PromotionCheck(
            "experiment_trial_budget",
            spec_budget_status,
            "the exact spec must consume its complete sealed trial allocation",
            len(spec_records),
            spec.trial_budget,
        )
    )

    run_id = str(evidence.get("run_id", "")).strip()
    candidate_rows = [row for row in spec_records if str(row.get("run_id", "")) == run_id]
    test_metrics = evidence.get("test_metrics")
    test_metrics = test_metrics if isinstance(test_metrics, Mapping) else {}
    metrics_digest = canonical_digest(test_metrics)
    benchmark_results_digest = canonical_digest(benchmark_digests)
    expected_candidate = {
        "schema_version": SCHEMA_VERSION,
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
        "holdout_seal_digest": spec.holdout_seal_digest,
        "holdout_reveal_digest": recomputed_reveal_digest,
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

    base = _evaluate_unbound_economic_checks(
        evidence,
        spec,
        ledger_records=campaign_records,
        ledger_intact=ledger_verified,
        thresholds=thresholds,
    )
    checks = [
        *strict_checks,
        *(check for check in base.checks if check.name not in _REPLACED_UNBOUND_CHECKS),
    ]

    trial_sharpes = [
        value
        for row in campaign_records
        if row.get("status") == "evaluated" and (value := _record_sharpe(row)) is not None
    ]
    variance = sharpe_variance_across_trials(trial_sharpes)
    distribution_ready = (
        ledger_verified
        and not malformed
        and budget_status is VerdictStatus.PASS
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
            "holdout_reveal_digest": recomputed_reveal_digest,
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
    "HYPOTHESIS_TRIAL_BUDGETS",
    "MIN_VERIFIED_DSR_TRIALS",
    "PROMOTION_THRESHOLDS",
    "REQUIRED_BENCHMARKS",
    "CryptoGovernanceError",
    "CryptoPromotionThresholds",
    "ExperimentSpec",
    "PromotionCheck",
    "PromotionVerdict",
    "VerdictStatus",
    "canonical_digest",
    "evaluate_crypto_promotion",
    "evaluation_artifact_digest",
    "evaluate_promotion_verdict",
    "load_experiment_spec",
    "seal_experiment_spec",
    "verify_experiment_spec",
]
