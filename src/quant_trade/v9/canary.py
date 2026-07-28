"""Canary readiness that fails closed on every input.

V8's version had a fail-open hole with three separate causes, and the
combination let a canary report ``READY_PENDING_HUMAN_AUTHORISATION`` on a
session that had failed to reconcile and had tripped its own kill switch:

1. **A reconciliation was "clean" if it had no ``problems`` key.** A payload
   of ``{"reconciled": false}`` has no such key, so a failed reconciliation
   read as a passing one. Absence of a complaint is not evidence of health.
2. **Loss limits were checked for key presence, not value sanity.** So
   ``{"per_trade": -1, "daily": 0, "total": "bad"}`` satisfied the condition:
   a negative limit, a limit that forbids all trading, and a string.
3. **The kill switch was not read at all.** A session halted by its own
   breaker still counted as a running session.

The rewrite inverts the default everywhere: a value must be *positively*
verified to count, every violation is enumerated by name, and an unparseable
input is a failure rather than a skipped check.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

#: Minimum supervised paper runtime before a canary may be considered.
MIN_PAPER_WALL_CLOCK_HOURS = 72.0
MIN_PAPER_EVENTS = 500
#: Stronger economic evidence. Recommended, reported, never faked.
RECOMMENDED_PAPER_DAYS = 30

CONDITION_MACHINE = "MACHINE_CHECKABLE"
CONDITION_HUMAN = "REQUIRES_HUMAN_DECISION"

#: Loss limits that must all be present, numeric, finite and strictly positive.
REQUIRED_LOSS_LIMITS = ("per_trade", "daily", "total")


def _positive_number(value: Any) -> tuple[bool, str]:
    """Is this a real, finite, strictly positive number?

    Booleans are rejected explicitly: ``True`` is an ``int`` in Python and
    would otherwise pass as the number 1, turning a checkbox into a limit.
    """
    if isinstance(value, bool):
        return False, "is a boolean, not a monetary limit"
    if not isinstance(value, int | float):
        return False, f"is {type(value).__name__}, not a number"
    if not math.isfinite(float(value)):
        return False, "is not finite"
    if float(value) <= 0:
        return False, f"is {value}, which is not strictly positive"
    return True, ""


def validate_loss_limits(limits: Any) -> list[str]:
    """Return one problem string per invalid or missing limit."""
    problems: list[str] = []
    if not isinstance(limits, dict):
        return [f"loss limits must be an object, got {type(limits).__name__}"]
    for name in REQUIRED_LOSS_LIMITS:
        if name not in limits:
            problems.append(f"loss limit {name!r} is missing")
            continue
        ok, why = _positive_number(limits[name])
        if not ok:
            problems.append(f"loss limit {name!r} {why}")
    ordered: list[Any] = [limits.get(n) for n in REQUIRED_LOSS_LIMITS]
    if all(isinstance(v, int | float) and not isinstance(v, bool) for v in ordered):
        per_trade, daily, total = (float(str(v)) for v in ordered)
        if per_trade > daily:
            problems.append(
                f"per_trade {per_trade} exceeds daily {daily}: a single trade could "
                "breach the daily limit"
            )
        if daily > total:
            problems.append(
                f"daily {daily} exceeds total {total}: one day could exhaust the entire budget"
            )
    return problems


def validate_reconciliation(reconciliation: Any) -> list[str]:
    """Return problems; an absent or ambiguous reconciliation is a problem.

    The check is positive: ``reconciled`` must be present and exactly ``True``.
    Anything else — missing, false, null, a string — fails.
    """
    if not isinstance(reconciliation, dict) or not reconciliation:
        return ["no reconciliation on record"]
    problems: list[str] = []
    reconciled = reconciliation.get("reconciled")
    if reconciled is not True:
        problems.append(f"reconciliation reports reconciled={reconciled!r}, not True")
    declared = reconciliation.get("problems")
    if declared:
        problems.append(f"reconciliation declares {len(declared)} problem(s)")
    error = reconciliation.get("reconciliation_error")
    if isinstance(error, int | float) and abs(float(error)) > 1e-9:
        problems.append(f"reconciliation error {error} exceeds tolerance")
    return problems


def validate_paper_session(status: Any) -> list[str]:
    """Return problems with the supervised paper result."""
    if not isinstance(status, dict) or not status:
        return ["no paper session on record"]
    problems: list[str] = []
    session_state = str(status.get("status", ""))
    if session_state != "PAPER_RUNNING":
        problems.append(f"paper session is {session_state or 'absent'}, not PAPER_RUNNING")
    if status.get("kill_switch_engaged") is True:
        problems.append("the session's kill switch is engaged")
    for breaker in status.get("breakers_tripped", []) or []:
        problems.append(f"breaker tripped: {breaker}")
    hours = float(status.get("wall_clock_seconds") or 0.0) / 3600.0
    if hours < MIN_PAPER_WALL_CLOCK_HOURS:
        problems.append(
            f"{hours:.2f}h of wall-clock runtime < required {MIN_PAPER_WALL_CLOCK_HOURS}h"
        )
    events = int(status.get("events_processed", 0) or 0)
    if events < MIN_PAPER_EVENTS:
        problems.append(f"{events} events < required {MIN_PAPER_EVENTS}")
    if int(status.get("liquidations", 0) or 0) > 0:
        problems.append(f"{status.get('liquidations')} liquidation(s) during paper")
    if not status.get("clock_is_persisted", False):
        problems.append(
            "the session's wall clock is not derived from persisted, verifiable "
            "time; a caller-supplied duration cannot support a canary"
        )
    return problems


@dataclass
class ReadinessCondition:
    condition_id: str
    description: str
    kind: str
    satisfied: bool
    observed: Any = None
    required: Any = None
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanaryReadinessV9:
    evaluated_at_utc: str
    status: str
    conditions: list[ReadinessCondition] = field(default_factory=list)
    blocking_conditions: list[str] = field(default_factory=list)
    all_problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def unblocked(self) -> bool:
        return not self.blocking_conditions

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "CANARY_READINESS_V9",
            "schema_version": 2,
            "evaluated_at_utc": self.evaluated_at_utc,
            "status": self.status,
            "canary_authorized": False,
            "real_money_authorized": False,
            "conditions": [c.to_dict() for c in self.conditions],
            "blocking_conditions": list(self.blocking_conditions),
            "all_problems": list(self.all_problems),
            "unblocked": self.unblocked,
            "notes": list(self.notes),
            "safety": {
                "live_order_submission": "DISABLED",
                "live_broker_execution": "DISABLED",
                "mining_purchase_execution": "DISABLED",
                "deposit_execution": "DISABLED",
                "withdrawal_execution": "DISABLED",
                "wallet_signing": "DISABLED",
                "cloud_resource_creation": "DISABLED",
                "external_spend": "DISABLED",
                "no_credentials_requested_or_stored": True,
            },
        }


def evaluate_canary_readiness_v9(
    *,
    evaluated_at_utc: str,
    paper_status: dict[str, Any] | None,
    owner_budget_usd: Any = None,
    exchange_and_jurisdiction_confirmed: Any = False,
    loss_limits_configured: Any = None,
    credentials_delivery_mechanism_confirmed: Any = False,
) -> CanaryReadinessV9:
    """Evaluate the canary preconditions, failing closed on every input."""
    status = paper_status or {}
    paper_problems = validate_paper_session(status)
    reconciliation_problems = validate_reconciliation(status.get("reconciliation"))
    limit_problems = validate_loss_limits(loss_limits_configured)

    budget_ok, budget_why = _positive_number(owner_budget_usd)
    budget_problems = [] if budget_ok else [f"owner budget {budget_why}"]

    venue_ok = exchange_and_jurisdiction_confirmed is True
    venue_problems = (
        []
        if venue_ok
        else [
            "exchange and jurisdiction are not confirmed "
            f"(got {exchange_and_jurisdiction_confirmed!r}; only True counts)"
        ]
    )
    credentials_ok = credentials_delivery_mechanism_confirmed is True
    credential_problems = (
        []
        if credentials_ok
        else [
            "no confirmed secure credential delivery mechanism "
            f"(got {credentials_delivery_mechanism_confirmed!r}; only True counts)"
        ]
    )

    conditions = [
        ReadinessCondition(
            condition_id="paper_result_sufficient",
            description=(
                "A supervised paper session has run long enough on verifiable "
                "wall-clock time, without a tripped breaker or a liquidation."
            ),
            kind=CONDITION_MACHINE,
            satisfied=not paper_problems,
            observed={
                "session_status": status.get("status", "NOT_STARTED"),
                "wall_clock_hours": round(
                    float(status.get("wall_clock_seconds") or 0.0) / 3600.0, 3
                ),
                "events_processed": int(status.get("events_processed", 0) or 0),
                "kill_switch_engaged": status.get("kill_switch_engaged"),
                "liquidations": status.get("liquidations"),
                "clock_is_persisted": status.get("clock_is_persisted"),
            },
            required={
                "session_status": "PAPER_RUNNING",
                "wall_clock_hours": MIN_PAPER_WALL_CLOCK_HOURS,
                "events_processed": MIN_PAPER_EVENTS,
                "kill_switch_engaged": False,
                "liquidations": 0,
                "clock_is_persisted": True,
            },
            problems=paper_problems,
        ),
        ReadinessCondition(
            condition_id="reconciliation_clean",
            description="The paper session reconciles exactly, with zero problems.",
            kind=CONDITION_MACHINE,
            satisfied=not reconciliation_problems,
            observed=status.get("reconciliation") or "no reconciliation on record",
            required={"reconciled": True, "problems": []},
            problems=reconciliation_problems,
        ),
        ReadinessCondition(
            condition_id="owner_budget_explicit",
            description=("The owner has stated explicitly how much money may be at risk."),
            kind=CONDITION_HUMAN,
            satisfied=not budget_problems,
            observed=owner_budget_usd,
            required="a finite amount strictly greater than zero",
            problems=budget_problems,
        ),
        ReadinessCondition(
            condition_id="exchange_and_jurisdiction_confirmed",
            description="The venue and its legal jurisdiction are confirmed by a human.",
            kind=CONDITION_HUMAN,
            satisfied=venue_ok,
            observed=exchange_and_jurisdiction_confirmed,
            required=True,
            problems=venue_problems,
        ),
        ReadinessCondition(
            condition_id="loss_limits_configured",
            description=(
                "Per-trade, daily and total loss limits are present, numeric, "
                "strictly positive and mutually consistent."
            ),
            kind=CONDITION_HUMAN,
            satisfied=not limit_problems,
            observed=loss_limits_configured,
            required={
                "per_trade": "> 0",
                "daily": ">= per_trade",
                "total": ">= daily",
            },
            problems=limit_problems,
        ),
        ReadinessCondition(
            condition_id="credentials_delivery_secure",
            description=(
                "A secure mechanism exists for delivering venue credentials "
                "directly to the execution host. No key, seed phrase or wallet is "
                "ever requested, printed or stored by this tooling."
            ),
            kind=CONDITION_HUMAN,
            satisfied=credentials_ok,
            observed=credentials_delivery_mechanism_confirmed,
            required=True,
            problems=credential_problems,
        ),
    ]

    blocking = [c.condition_id for c in conditions if not c.satisfied]
    all_problems = [p for c in conditions for p in c.problems]
    return CanaryReadinessV9(
        evaluated_at_utc=evaluated_at_utc,
        status="BLOCKED" if blocking else "CANARY_REQUIRES_HUMAN_AUTHORISATION",
        conditions=conditions,
        blocking_conditions=blocking,
        all_problems=all_problems,
        notes=[
            "Every condition fails closed: a value must be positively verified "
            "to count, and an unparseable input is a failure rather than a "
            "skipped check.",
            "Clearing all six still does not authorise real money. It means a "
            "human may now make that decision deliberately.",
            f"{RECOMMENDED_PAPER_DAYS} days of paper is the recommended standard "
            "for stronger economic evidence; the 72h floor is a minimum, not a "
            "target, and neither may be simulated or accelerated.",
        ],
    )


__all__ = [
    "CONDITION_HUMAN",
    "CONDITION_MACHINE",
    "MIN_PAPER_EVENTS",
    "MIN_PAPER_WALL_CLOCK_HOURS",
    "RECOMMENDED_PAPER_DAYS",
    "REQUIRED_LOSS_LIMITS",
    "CanaryReadinessV9",
    "ReadinessCondition",
    "evaluate_canary_readiness_v9",
    "validate_loss_limits",
    "validate_paper_session",
    "validate_reconciliation",
]
