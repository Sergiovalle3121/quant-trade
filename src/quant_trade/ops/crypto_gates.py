"""Fail-closed operational gates for the crypto research programme.

This module deliberately contains policy and evidence evaluation only.  It has
no HTTP client, endpoint, credential lookup, request signing, or order-routing
path.  A ``PASS`` means that the evidence supplied to one gate satisfies that
gate; it never authorises real-money trading or any external action.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

import yaml

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.ops.crypto_capital import CapitalFeasibility

Gate0Status = Literal["PASS", "BLOCKED", "INSUFFICIENT_EVIDENCE"]
ReadinessStatus = Literal["PASS", "NO_GO", "INSUFFICIENT_EVIDENCE"]

PROTECTED_RESEARCH_ACTIONS = frozenset({"pnl_generation", "holdout_seal", "candidate_promotion"})


class CryptoGateError(RuntimeError):
    """Raised when a protected action is attempted before its gate passes."""


@dataclass(frozen=True)
class VenuePolicy:
    """The only venue posture permitted by the first implementation.

    There is intentionally no URL or credential field.  The repository only
    evaluates operator-supplied attestations and remains unable to connect.
    """

    schema_version: int = 1
    venue: str = "bybit"
    environment: str = "demo"
    market: str = "spot"
    account_scope: str = "dedicated_subaccount"
    fee_source: str = "operator_capture_per_symbol"
    read_permission_required: bool = True
    spot_permission_required: bool = True
    ip_allowlist_required: bool = True
    withdrawals_enabled: bool = False
    transfers_enabled: bool = False
    margin_enabled: bool = False
    derivatives_enabled: bool = False
    loans_enabled: bool = False
    live_endpoint_enabled: bool = False
    credentials_in_repository: bool = False
    execution_adapter_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Gate0Evidence:
    """Human/operator evidence required before venue-specific research runs."""

    venue: str | None = None
    environment: str | None = None
    kyc_mexico_approved: bool | None = None
    contractual_entity_identified: bool | None = None
    spot_account_enabled: bool | None = None
    api_access_enabled: bool | None = None
    dedicated_subaccount_active: bool | None = None
    ip_allowlist_active: bool | None = None
    read_permission_enabled: bool | None = None
    spot_permission_enabled: bool | None = None
    withdrawal_permission_disabled: bool | None = None
    transfer_permission_disabled: bool | None = None
    margin_permission_disabled: bool | None = None
    derivatives_permission_disabled: bool | None = None
    loan_permission_disabled: bool | None = None
    fee_rate_captured_per_symbol: bool | None = None
    minimum_deposit_test_passed: bool | None = None
    minimum_withdrawal_test_passed: bool | None = None
    dataset_venue: str | None = None
    cost_venue: str | None = None
    planned_execution_venue: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Gate0Verdict:
    status: Gate0Status
    blocking_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    policy: VenuePolicy
    evidence: Gate0Evidence

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": "GATE_0",
            "schema_version": 1,
            "status": self.status,
            "passed": self.passed,
            "blocking_conditions": list(self.blocking_conditions),
            "missing_conditions": list(self.missing_conditions),
            "policy": self.policy.to_dict(),
            "evidence": self.evidence.to_dict(),
            "evidence_digest": self.evidence_digest(),
            "downstream_gates_still_required": True,
            "demo_order_submission_authorized": False,
            "external_action_authorized": False,
            "real_money_authorized": False,
        }

    def digest(self) -> str:
        """Bind a later ExperimentSpec to this exact fail-closed verdict."""
        return sha256_of_text(canonical_dumps(self.to_dict()))

    def evidence_digest(self) -> str:
        """Hash the exact observations, including missing and contradictory facts."""
        return sha256_of_text(canonical_dumps(self.evidence.to_dict()))


_GATE0_TRUE_FIELDS: dict[str, str] = {
    "kyc_mexico_approved": "Mexican KYC approval is not confirmed",
    "contractual_entity_identified": "the contractual entity is not identified",
    "spot_account_enabled": "Spot is not confirmed as enabled",
    "api_access_enabled": "API access is not confirmed as enabled",
    "dedicated_subaccount_active": "a dedicated subaccount is not confirmed",
    "ip_allowlist_active": "an IP allowlist is not confirmed",
    "read_permission_enabled": "read permission is not confirmed",
    "spot_permission_enabled": "Spot permission is not confirmed",
    "withdrawal_permission_disabled": "withdrawal permission is not confirmed disabled",
    "transfer_permission_disabled": "transfer permission is not confirmed disabled",
    "margin_permission_disabled": "margin permission is not confirmed disabled",
    "derivatives_permission_disabled": "derivatives permission is not confirmed disabled",
    "loan_permission_disabled": "loan permission is not confirmed disabled",
    "fee_rate_captured_per_symbol": "account fee rates were not captured per symbol",
    "minimum_deposit_test_passed": "the operator's minimum deposit test is not confirmed",
    "minimum_withdrawal_test_passed": "the operator's minimum withdrawal test is not confirmed",
}


def _venue_policy_blockers(policy: VenuePolicy) -> list[str]:
    blockers: list[str] = []
    expected_values: dict[str, Any] = {
        "schema_version": 1,
        "venue": "bybit",
        "environment": "demo",
        "market": "spot",
        "account_scope": "dedicated_subaccount",
        "fee_source": "operator_capture_per_symbol",
        "read_permission_required": True,
        "spot_permission_required": True,
        "ip_allowlist_required": True,
        "withdrawals_enabled": False,
        "transfers_enabled": False,
        "margin_enabled": False,
        "derivatives_enabled": False,
        "loans_enabled": False,
        "live_endpoint_enabled": False,
        "credentials_in_repository": False,
        "execution_adapter_enabled": False,
    }
    for name, expected in expected_values.items():
        observed = getattr(policy, name)
        if observed != expected or type(observed) is not type(expected):
            blockers.append(f"venue policy {name} must be {expected!r}, got {observed!r}")
    return blockers


def load_venue_policy(path: str | Path) -> VenuePolicy:
    """Load the declarative policy, rejecting unknown or credential-like keys."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("venue policy must be a YAML mapping")
    allowed = {item.name for item in fields(VenuePolicy)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"unknown venue policy keys: {sorted(unknown)}")
    return VenuePolicy(**raw)


def evaluate_gate0(policy: VenuePolicy, evidence: Gate0Evidence | None) -> Gate0Verdict:
    """Evaluate Gate 0; missing facts and unsafe facts both fail closed."""
    blockers = _venue_policy_blockers(policy)
    missing: list[str] = []
    observed = evidence or Gate0Evidence()

    for name, message in _GATE0_TRUE_FIELDS.items():
        value = getattr(observed, name)
        if value is None:
            missing.append(name)
        elif value is not True:
            blockers.append(message)

    exact_values = {
        "venue": policy.venue,
        "environment": policy.environment,
        "dataset_venue": policy.venue,
        "cost_venue": policy.venue,
        "planned_execution_venue": policy.venue,
    }
    for name, expected in exact_values.items():
        value = getattr(observed, name)
        if value is None or not str(value).strip():
            missing.append(name)
        elif str(value).strip().lower() != expected:
            blockers.append(f"{name} must be {expected!r}, got {value!r}")

    status: Gate0Status
    if blockers:
        status = "BLOCKED"
    elif missing:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "PASS"
    return Gate0Verdict(status, tuple(blockers), tuple(missing), policy, observed)


def require_gate0_passed(verdict: Gate0Verdict, action: str) -> None:
    """Block a protected research action unless Gate 0 positively passed.

    Passing this check is not an authorisation for external action.  It only
    removes Gate 0 as one blocker; all downstream gates still apply.
    """
    if action not in PROTECTED_RESEARCH_ACTIONS:
        raise CryptoGateError(f"Gate 0 cannot authorize unsupported action {action!r}")
    expected = evaluate_gate0(verdict.policy, verdict.evidence)
    if verdict != expected:
        raise CryptoGateError(
            f"Gate 0 blocks {action}: verdict is inconsistent with its policy and evidence"
        )
    if not verdict.passed:
        details = verdict.blocking_conditions or verdict.missing_conditions
        raise CryptoGateError(f"Gate 0 blocks {action}: {', '.join(details)}")


@dataclass(frozen=True)
class ShadowPolicy:
    minimum_demo_order_cycles: int = 100
    minimum_shadow_calendar_days: int = 365
    minimum_complete_annual_rebalances: int = 1
    maximum_unresolved_reconciliation_discrepancies: int = 0
    maximum_duplicate_orders: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_HARD_SHADOW_POLICY = ShadowPolicy()


def _effective_shadow_policy(policy: ShadowPolicy) -> ShadowPolicy:
    """Clamp valid values to hard limits and replace invalid values fail-closed."""
    minimums: dict[str, int] = {}
    for name in (
        "minimum_demo_order_cycles",
        "minimum_shadow_calendar_days",
        "minimum_complete_annual_rebalances",
    ):
        value = getattr(policy, name)
        hard_floor = getattr(_HARD_SHADOW_POLICY, name)
        minimums[name] = (
            max(value, hard_floor)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else hard_floor
        )
    maximums: dict[str, int] = {}
    for name in (
        "maximum_unresolved_reconciliation_discrepancies",
        "maximum_duplicate_orders",
    ):
        value = getattr(policy, name)
        hard_ceiling = getattr(_HARD_SHADOW_POLICY, name)
        maximums[name] = (
            min(value, hard_ceiling)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else hard_ceiling
        )
    return ShadowPolicy(**minimums, **maximums)


@dataclass(frozen=True)
class ShadowEvidence:
    demo_completed_order_cycles: int | None = None
    shadow_calendar_days: int | None = None
    complete_annual_rebalances: int | None = None
    unresolved_reconciliation_discrepancies: int | None = None
    duplicate_orders: int | None = None
    submit_cancel_cycle_passed: bool | None = None
    idempotency_passed: bool | None = None
    reconnection_passed: bool | None = None
    rate_limit_handling_passed: bool | None = None
    restart_recovery_passed: bool | None = None
    reconciliation_passed: bool | None = None
    kill_switch_drills_passed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessVerdict:
    gate: str
    status: ReadinessStatus
    blocking_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    observed: dict[str, Any]
    policy: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "schema_version": 1,
            "status": self.status,
            "passed": self.passed,
            "blocking_conditions": list(self.blocking_conditions),
            "missing_conditions": list(self.missing_conditions),
            "observed": dict(self.observed),
            "policy": dict(self.policy),
            "automatic_transition_authorized": False,
            "external_action_authorized": False,
            "real_money_authorized": False,
        }


def _readiness_status(blockers: list[str], missing: list[str]) -> ReadinessStatus:
    if blockers:
        return "NO_GO"
    if missing:
        return "INSUFFICIENT_EVIDENCE"
    return "PASS"


def _int_evidence(
    name: str,
    value: Any,
    missing: list[str],
    blockers: list[str],
) -> int | None:
    if value is None:
        missing.append(name)
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        blockers.append(f"{name} must be a non-negative integer, got {value!r}")
        return None
    return value


def _positive_number(
    name: str,
    value: Any,
    missing: list[str],
    blockers: list[str],
    *,
    allow_zero: bool = False,
) -> float | None:
    if value is None:
        missing.append(name)
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        blockers.append(f"{name} must be a finite number, got {value!r}")
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "strictly positive"
        blockers.append(f"{name} must be finite and {qualifier}, got {value!r}")
        return None
    return number


def evaluate_shadow(
    policy: ShadowPolicy,
    evidence: ShadowEvidence | None,
) -> ReadinessVerdict:
    """Evaluate Demo plus shadow evidence without performing either activity."""
    blockers: list[str] = []
    missing: list[str] = []
    observed = evidence or ShadowEvidence()

    policy_values = policy.to_dict()
    for name, value in policy_values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            blockers.append(f"shadow policy {name} must be a non-negative integer")
    hard_minimums = (
        "minimum_demo_order_cycles",
        "minimum_shadow_calendar_days",
        "minimum_complete_annual_rebalances",
    )
    for name in hard_minimums:
        value = getattr(policy, name)
        hard_floor = getattr(_HARD_SHADOW_POLICY, name)
        if isinstance(value, int) and not isinstance(value, bool) and value < hard_floor:
            blockers.append(f"shadow policy {name} cannot be relaxed below {hard_floor}")
    hard_maximums = (
        "maximum_unresolved_reconciliation_discrepancies",
        "maximum_duplicate_orders",
    )
    for name in hard_maximums:
        value = getattr(policy, name)
        hard_ceiling = getattr(_HARD_SHADOW_POLICY, name)
        if isinstance(value, int) and not isinstance(value, bool) and value > hard_ceiling:
            blockers.append(f"shadow policy {name} cannot be relaxed above {hard_ceiling}")

    effective_policy = _effective_shadow_policy(policy)

    minimums = {
        "demo_completed_order_cycles": effective_policy.minimum_demo_order_cycles,
        "shadow_calendar_days": effective_policy.minimum_shadow_calendar_days,
        "complete_annual_rebalances": effective_policy.minimum_complete_annual_rebalances,
    }
    for name, required in minimums.items():
        value = _int_evidence(name, getattr(observed, name), missing, blockers)
        if value is not None and value < required:
            blockers.append(f"{name} {value} is below required {required}")

    maximums = {
        "unresolved_reconciliation_discrepancies": (
            effective_policy.maximum_unresolved_reconciliation_discrepancies
        ),
        "duplicate_orders": effective_policy.maximum_duplicate_orders,
    }
    for name, maximum in maximums.items():
        value = _int_evidence(name, getattr(observed, name), missing, blockers)
        if value is not None and value > maximum:
            blockers.append(f"{name} {value} exceeds allowed {maximum}")

    required_checks = (
        "submit_cancel_cycle_passed",
        "idempotency_passed",
        "reconnection_passed",
        "rate_limit_handling_passed",
        "restart_recovery_passed",
        "reconciliation_passed",
        "kill_switch_drills_passed",
    )
    for name in required_checks:
        value = getattr(observed, name)
        if value is None:
            missing.append(name)
        elif value is not True:
            blockers.append(f"{name} is not positively verified")

    return ReadinessVerdict(
        gate="SHADOW",
        status=_readiness_status(blockers, missing),
        blocking_conditions=tuple(blockers),
        missing_conditions=tuple(missing),
        observed=observed.to_dict(),
        policy=policy_values,
    )


@dataclass(frozen=True)
class CanaryPolicy:
    maximum_declared_risk_capital_usd: float = 5_000.0
    maximum_initial_capital_fraction: float = 0.10
    maximum_initial_capital_usd: float = 500.0
    maximum_asset_fraction: float = 0.05
    maximum_order_adv_fraction: float = 0.01
    maximum_order_depth_fraction: float = 0.05
    daily_loss_kill_fraction: float = 0.01
    drawdown_pause_fraction: float = 0.05
    minimum_fills_before_scale: int = 100
    minimum_calendar_days_before_scale: int = 30
    maximum_slippage_ratio: float = 1.50
    maximum_median_cost_error_fraction: float = 0.20
    maximum_scale_increment_fraction: float = 0.25

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanaryEvidence:
    shadow_passed: bool | None = None
    own_capital_only: bool | None = None
    spot_only: bool | None = None
    leverage_disabled: bool | None = None
    shorts_disabled: bool | None = None
    human_approval_each_initial_rebalance: bool | None = None
    post_rebalance_reconciliation_required: bool | None = None
    venue_balance_operational_only: bool | None = None
    capital_feasibility: CapitalFeasibility | None = None
    # Retained for artifact compatibility only.  A caller-supplied boolean can
    # never establish feasibility; Gate 4 requires the recomputable object.
    minimum_order_constraints_allow_diversification: bool | None = None
    risk_capital_usd: float | None = None
    proposed_initial_capital_usd: float | None = None
    configured_maximum_asset_fraction: float | None = None
    configured_maximum_order_adv_fraction: float | None = None
    configured_maximum_order_depth_fraction: float | None = None
    configured_daily_loss_kill_fraction: float | None = None
    configured_drawdown_pause_fraction: float | None = None
    stale_data_pause_configured: bool | None = None
    unexpected_fee_pause_configured: bool | None = None
    abnormal_latency_pause_configured: bool | None = None
    slippage_outside_model_pause_configured: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.capital_feasibility is not None:
            payload["capital_feasibility"] = self.capital_feasibility.to_dict()
        return payload


@dataclass(frozen=True)
class CanaryScaleEvidence:
    observed_fills: int | None = None
    observed_calendar_days: int | None = None
    p95_realized_to_simulated_slippage_ratio: float | None = None
    median_cost_error_fraction: float | None = None
    unresolved_reconciliation_discrepancies: int | None = None
    duplicate_orders: int | None = None
    proposed_scale_increment_fraction: float | None = None
    daily_loss_kill_triggered: bool | None = None
    drawdown_pause_triggered: bool | None = None
    stale_data_detected: bool | None = None
    unexpected_fee_detected: bool | None = None
    abnormal_latency_detected: bool | None = None
    slippage_outside_model_detected: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_HARD_CANARY_POLICY = CanaryPolicy()


def _canary_policy_blockers(policy: CanaryPolicy) -> list[str]:
    blockers: list[str] = []
    fractions = (
        "maximum_initial_capital_fraction",
        "maximum_asset_fraction",
        "maximum_order_adv_fraction",
        "maximum_order_depth_fraction",
        "daily_loss_kill_fraction",
        "drawdown_pause_fraction",
        "maximum_median_cost_error_fraction",
        "maximum_scale_increment_fraction",
    )
    for name in fractions:
        value = getattr(policy, name)
        if not isinstance(value, int | float) or isinstance(value, bool):
            blockers.append(f"canary policy {name} must be numeric")
        elif not math.isfinite(float(value)) or not 0 < float(value) <= 1:
            blockers.append(f"canary policy {name} must be in (0, 1]")
    positive_values = (
        "maximum_declared_risk_capital_usd",
        "maximum_initial_capital_usd",
        "maximum_slippage_ratio",
    )
    for name in positive_values:
        value = getattr(policy, name)
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            blockers.append(f"canary policy {name} must be finite and positive")
    for name in ("minimum_fills_before_scale", "minimum_calendar_days_before_scale"):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            blockers.append(f"canary policy {name} must be a positive integer")

    hard_maximums = (
        "maximum_declared_risk_capital_usd",
        "maximum_initial_capital_fraction",
        "maximum_initial_capital_usd",
        "maximum_asset_fraction",
        "maximum_order_adv_fraction",
        "maximum_order_depth_fraction",
        "daily_loss_kill_fraction",
        "drawdown_pause_fraction",
        "maximum_slippage_ratio",
        "maximum_median_cost_error_fraction",
        "maximum_scale_increment_fraction",
    )
    for name in hard_maximums:
        value = getattr(policy, name)
        hard_ceiling = getattr(_HARD_CANARY_POLICY, name)
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > hard_ceiling
        ):
            blockers.append(f"canary policy {name} cannot be relaxed above {hard_ceiling}")
    hard_minimums = ("minimum_fills_before_scale", "minimum_calendar_days_before_scale")
    for name in hard_minimums:
        value = getattr(policy, name)
        hard_floor = getattr(_HARD_CANARY_POLICY, name)
        if isinstance(value, int) and not isinstance(value, bool) and value < hard_floor:
            blockers.append(f"canary policy {name} cannot be relaxed below {hard_floor}")
    return blockers


def _effective_canary_policy(policy: CanaryPolicy) -> CanaryPolicy:
    """Return a valid policy honoring stricter values and immutable hard limits."""
    hard_maximums = (
        "maximum_declared_risk_capital_usd",
        "maximum_initial_capital_fraction",
        "maximum_initial_capital_usd",
        "maximum_asset_fraction",
        "maximum_order_adv_fraction",
        "maximum_order_depth_fraction",
        "daily_loss_kill_fraction",
        "drawdown_pause_fraction",
        "maximum_slippage_ratio",
        "maximum_median_cost_error_fraction",
        "maximum_scale_increment_fraction",
    )
    values: dict[str, float | int] = {}
    for name in hard_maximums:
        value = getattr(policy, name)
        hard_ceiling = getattr(_HARD_CANARY_POLICY, name)
        values[name] = (
            min(float(value), hard_ceiling)
            if isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
            else hard_ceiling
        )
    for name in ("minimum_fills_before_scale", "minimum_calendar_days_before_scale"):
        value = getattr(policy, name)
        hard_floor = getattr(_HARD_CANARY_POLICY, name)
        values[name] = (
            max(value, hard_floor)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
            else hard_floor
        )
    return CanaryPolicy(
        maximum_declared_risk_capital_usd=float(values["maximum_declared_risk_capital_usd"]),
        maximum_initial_capital_fraction=float(values["maximum_initial_capital_fraction"]),
        maximum_initial_capital_usd=float(values["maximum_initial_capital_usd"]),
        maximum_asset_fraction=float(values["maximum_asset_fraction"]),
        maximum_order_adv_fraction=float(values["maximum_order_adv_fraction"]),
        maximum_order_depth_fraction=float(values["maximum_order_depth_fraction"]),
        daily_loss_kill_fraction=float(values["daily_loss_kill_fraction"]),
        drawdown_pause_fraction=float(values["drawdown_pause_fraction"]),
        minimum_fills_before_scale=int(values["minimum_fills_before_scale"]),
        minimum_calendar_days_before_scale=int(values["minimum_calendar_days_before_scale"]),
        maximum_slippage_ratio=float(values["maximum_slippage_ratio"]),
        maximum_median_cost_error_fraction=float(values["maximum_median_cost_error_fraction"]),
        maximum_scale_increment_fraction=float(values["maximum_scale_increment_fraction"]),
    )


def canary_capital_limit(policy: CanaryPolicy, risk_capital_usd: float) -> float:
    """Return ``min(10% of risk capital, USD 500)`` without moving funds."""
    if (
        isinstance(risk_capital_usd, bool)
        or not isinstance(risk_capital_usd, int | float)
        or not math.isfinite(float(risk_capital_usd))
        or float(risk_capital_usd) <= 0
    ):
        raise ValueError("risk_capital_usd must be finite and positive")
    return min(
        float(risk_capital_usd)
        * min(
            policy.maximum_initial_capital_fraction,
            _HARD_CANARY_POLICY.maximum_initial_capital_fraction,
        ),
        min(policy.maximum_initial_capital_usd, _HARD_CANARY_POLICY.maximum_initial_capital_usd),
    )


def canary_order_limit(
    policy: CanaryPolicy,
    median_daily_notional_usd: float,
    executable_depth_usd: float,
) -> float:
    """Calculate the policy ceiling; this function cannot construct an order."""
    values = {
        "median_daily_notional_usd": median_daily_notional_usd,
        "executable_depth_usd": executable_depth_usd,
    }
    for name, value in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(f"{name} must be finite and non-negative")
    return min(
        float(median_daily_notional_usd)
        * min(policy.maximum_order_adv_fraction, _HARD_CANARY_POLICY.maximum_order_adv_fraction),
        float(executable_depth_usd)
        * min(
            policy.maximum_order_depth_fraction,
            _HARD_CANARY_POLICY.maximum_order_depth_fraction,
        ),
    )


def evaluate_canary_readiness(
    policy: CanaryPolicy,
    evidence: CanaryEvidence | None,
) -> ReadinessVerdict:
    """Evaluate readiness for human review, never authorisation or execution."""
    blockers = _canary_policy_blockers(policy)
    effective_policy = _effective_canary_policy(policy)
    missing: list[str] = []
    observed = evidence or CanaryEvidence()

    required_checks = (
        "shadow_passed",
        "own_capital_only",
        "spot_only",
        "leverage_disabled",
        "shorts_disabled",
        "human_approval_each_initial_rebalance",
        "post_rebalance_reconciliation_required",
        "venue_balance_operational_only",
        "stale_data_pause_configured",
        "unexpected_fee_pause_configured",
        "abnormal_latency_pause_configured",
        "slippage_outside_model_pause_configured",
    )
    for name in required_checks:
        value = getattr(observed, name)
        if value is None:
            missing.append(name)
        elif value is not True:
            blockers.append(f"{name} is not positively verified")

    # The legacy diversification flag remains readable in old artifacts but
    # is never proof: it is an unauthenticated assertion by the caller.  The
    # byte-bound feasibility object is recalculated here before it can pass.
    legacy_diversification = observed.minimum_order_constraints_allow_diversification
    if legacy_diversification is not None and legacy_diversification is not True:
        blockers.append("minimum_order_constraints_allow_diversification is contradicted")
    capital_feasibility = observed.capital_feasibility
    verified_capital_feasibility: CapitalFeasibility | None = None
    if capital_feasibility is None:
        missing.append("capital_feasibility")
    elif not isinstance(capital_feasibility, CapitalFeasibility):
        blockers.append("capital_feasibility must be a CapitalFeasibility result")
    elif not capital_feasibility.is_verified():
        blockers.append("capital_feasibility does not match a fresh recomputation")
    elif capital_feasibility.status == "INSUFFICIENT_EVIDENCE":
        missing.append("capital_feasibility.PASS")
    elif not capital_feasibility.passed:
        blockers.append("capital_feasibility is NO_GO")
    elif capital_feasibility.maximum_asset_fraction > effective_policy.maximum_asset_fraction:
        blockers.append(
            "capital_feasibility uses a larger asset fraction than the effective canary policy"
        )
    else:
        expected_context = {
            "venue": "bybit",
            "market": "spot",
            "environment": "demo",
            "account_scope": "dedicated_subaccount",
        }
        context_mismatch = False
        for field_name, expected in expected_context.items():
            if getattr(capital_feasibility.request, field_name) != expected:
                blockers.append(
                    f"capital_feasibility {field_name} does not match Bybit canary policy"
                )
                context_mismatch = True
        if not context_mismatch:
            verified_capital_feasibility = capital_feasibility

    risk_capital = _positive_number(
        "risk_capital_usd", observed.risk_capital_usd, missing, blockers
    )
    proposed = _positive_number(
        "proposed_initial_capital_usd",
        observed.proposed_initial_capital_usd,
        missing,
        blockers,
    )
    if verified_capital_feasibility is not None and proposed is not None:
        converted_sleeve = verified_capital_feasibility.sleeve_amount_usd
        if converted_sleeve is None:
            missing.append("capital_feasibility.sleeve_amount_usd")
        elif not math.isclose(proposed, converted_sleeve, rel_tol=0.0, abs_tol=0.01):
            blockers.append(
                "proposed_initial_capital_usd does not match capital_feasibility "
                "converted sleeve amount"
            )
    if risk_capital is not None:
        if risk_capital >= effective_policy.maximum_declared_risk_capital_usd:
            blockers.append(
                "risk_capital_usd must remain below "
                f"{effective_policy.maximum_declared_risk_capital_usd:.2f}"
            )
        if proposed is not None and proposed > canary_capital_limit(effective_policy, risk_capital):
            blockers.append("proposed_initial_capital_usd exceeds the canary capital limit")

    configured_limits = {
        "configured_maximum_asset_fraction": effective_policy.maximum_asset_fraction,
        "configured_maximum_order_adv_fraction": effective_policy.maximum_order_adv_fraction,
        "configured_maximum_order_depth_fraction": effective_policy.maximum_order_depth_fraction,
        "configured_daily_loss_kill_fraction": effective_policy.daily_loss_kill_fraction,
        "configured_drawdown_pause_fraction": effective_policy.drawdown_pause_fraction,
    }
    for name, maximum in configured_limits.items():
        value = _positive_number(name, getattr(observed, name), missing, blockers)
        if value is not None and value > maximum:
            blockers.append(f"{name} {value} exceeds policy maximum {maximum}")

    return ReadinessVerdict(
        gate="CANARY_REVIEW",
        status=_readiness_status(blockers, missing),
        blocking_conditions=tuple(blockers),
        missing_conditions=tuple(missing),
        observed=observed.to_dict(),
        policy=policy.to_dict(),
    )


def evaluate_canary_scale(
    policy: CanaryPolicy,
    evidence: CanaryScaleEvidence | None,
) -> ReadinessVerdict:
    """Evaluate scale evidence; even a pass cannot scale anything automatically."""
    blockers = _canary_policy_blockers(policy)
    effective_policy = _effective_canary_policy(policy)
    missing: list[str] = []
    observed = evidence or CanaryScaleEvidence()

    fills = _int_evidence("observed_fills", observed.observed_fills, missing, blockers)
    if fills is not None and fills < effective_policy.minimum_fills_before_scale:
        blockers.append(
            "observed_fills "
            f"{fills} is below required {effective_policy.minimum_fills_before_scale}"
        )
    days = _int_evidence(
        "observed_calendar_days", observed.observed_calendar_days, missing, blockers
    )
    if days is not None and days < effective_policy.minimum_calendar_days_before_scale:
        blockers.append(
            "observed_calendar_days "
            f"{days} is below required {effective_policy.minimum_calendar_days_before_scale}"
        )

    slippage = _positive_number(
        "p95_realized_to_simulated_slippage_ratio",
        observed.p95_realized_to_simulated_slippage_ratio,
        missing,
        blockers,
        allow_zero=True,
    )
    if slippage is not None and slippage > effective_policy.maximum_slippage_ratio:
        blockers.append(
            "p95_realized_to_simulated_slippage_ratio "
            f"{slippage} exceeds {effective_policy.maximum_slippage_ratio}"
        )
    cost_error = _positive_number(
        "median_cost_error_fraction",
        observed.median_cost_error_fraction,
        missing,
        blockers,
        allow_zero=True,
    )
    if cost_error is not None and cost_error > effective_policy.maximum_median_cost_error_fraction:
        blockers.append(
            f"median_cost_error_fraction {cost_error} exceeds "
            f"{effective_policy.maximum_median_cost_error_fraction}"
        )

    for name in ("unresolved_reconciliation_discrepancies", "duplicate_orders"):
        value = _int_evidence(name, getattr(observed, name), missing, blockers)
        if value is not None and value != 0:
            blockers.append(f"{name} must be zero, got {value}")

    scale_increment = _positive_number(
        "proposed_scale_increment_fraction",
        observed.proposed_scale_increment_fraction,
        missing,
        blockers,
    )
    if (
        scale_increment is not None
        and scale_increment > effective_policy.maximum_scale_increment_fraction
    ):
        blockers.append(
            f"proposed_scale_increment_fraction {scale_increment} exceeds "
            f"{effective_policy.maximum_scale_increment_fraction}"
        )

    pause_events = (
        "daily_loss_kill_triggered",
        "drawdown_pause_triggered",
        "stale_data_detected",
        "unexpected_fee_detected",
        "abnormal_latency_detected",
        "slippage_outside_model_detected",
    )
    for name in pause_events:
        value = getattr(observed, name)
        if value is None:
            missing.append(name)
        elif value is not False:
            blockers.append(f"{name} requires a pause and review")

    return ReadinessVerdict(
        gate="CANARY_SCALE",
        status=_readiness_status(blockers, missing),
        blocking_conditions=tuple(blockers),
        missing_conditions=tuple(missing),
        observed=observed.to_dict(),
        policy=policy.to_dict(),
    )


__all__ = [
    "CanaryEvidence",
    "CanaryPolicy",
    "CanaryScaleEvidence",
    "CryptoGateError",
    "Gate0Evidence",
    "Gate0Verdict",
    "PROTECTED_RESEARCH_ACTIONS",
    "ReadinessVerdict",
    "ShadowEvidence",
    "ShadowPolicy",
    "VenuePolicy",
    "canary_capital_limit",
    "canary_order_limit",
    "evaluate_canary_readiness",
    "evaluate_canary_scale",
    "evaluate_gate0",
    "evaluate_shadow",
    "load_venue_policy",
    "require_gate0_passed",
]
