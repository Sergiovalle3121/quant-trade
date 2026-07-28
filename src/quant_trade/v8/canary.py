"""Canary readiness: the checklist between paper and the first real dollar.

The canary is deliberately hard to reach. Six preconditions must all hold, and
four of them cannot be satisfied by code at all — they require a human to
decide something and say so. That asymmetry is the point: an agent can produce
evidence, but it cannot authorise spending someone else's money, choose a
jurisdiction, or hand itself credentials.

The artifact this module produces is therefore always ``BLOCKED`` unless every
condition is independently satisfied, and the two conditions that *are*
machine-checkable (a sufficient paper result, a clean reconciliation) are
computed from the session rather than asserted.

Nothing here reads, prints, stores or requests an API key, a seed phrase, or a
wallet. The credential condition is satisfied by a human confirming that a
secure delivery mechanism exists — never by a secret passing through this
process.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Minimum supervised paper runtime before a canary may even be considered.
MIN_PAPER_WALL_CLOCK_HOURS = 72.0
MIN_PAPER_EVENTS = 500

CONDITION_MACHINE = "MACHINE_CHECKABLE"
CONDITION_HUMAN = "REQUIRES_HUMAN_DECISION"


@dataclass
class ReadinessCondition:
    condition_id: str
    description: str
    kind: str
    satisfied: bool
    observed: Any = None
    required: Any = None
    blocker: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanaryReadiness:
    evaluated_at_utc: str
    status: str  # "BLOCKED" | "READY_PENDING_HUMAN_AUTHORISATION"
    conditions: list[ReadinessCondition] = field(default_factory=list)
    blocking_conditions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def unblocked(self) -> bool:
        return not self.blocking_conditions

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "CANARY_READINESS",
            "schema_version": 1,
            "evaluated_at_utc": self.evaluated_at_utc,
            "status": self.status,
            "canary_authorized": False,
            "real_money_authorized": False,
            "conditions": [c.to_dict() for c in self.conditions],
            "blocking_conditions": list(self.blocking_conditions),
            "unblocked": self.unblocked,
            "notes": list(self.notes),
            "safety": {
                "no_orders_submitted": True,
                "no_deposits": True,
                "no_withdrawals": True,
                "no_credentials_requested_or_stored": True,
            },
        }


def evaluate_canary_readiness(
    *,
    evaluated_at_utc: str,
    paper_status: dict[str, Any] | None,
    owner_budget_usd: float | None = None,
    exchange_and_jurisdiction_confirmed: bool = False,
    loss_limits_configured: dict[str, Any] | None = None,
    credentials_delivery_mechanism_confirmed: bool = False,
) -> CanaryReadiness:
    """Evaluate the six canary preconditions and report what still blocks.

    ``paper_status`` is the :class:`PaperSessionReport` payload. Passing
    ``None`` means no session exists, which fails the first two conditions
    outright rather than defaulting them to true.
    """
    status = paper_status or {}
    wall_clock_hours = float(status.get("wall_clock_seconds", 0.0) or 0.0) / 3600.0
    events = int(status.get("events_processed", 0) or 0)
    running = str(status.get("status", "")) == "RUNNING"
    paper_sufficient = (
        running and wall_clock_hours >= MIN_PAPER_WALL_CLOCK_HOURS and events >= MIN_PAPER_EVENTS
    )
    reconciliation = status.get("reconciliation") or {}
    reconciliation_clean = bool(reconciliation) and not reconciliation.get("problems")

    conditions = [
        ReadinessCondition(
            condition_id="paper_result_sufficient",
            description=(
                "A supervised paper session has run long enough, on wall-clock "
                "time, to be evidence rather than a smoke test."
            ),
            kind=CONDITION_MACHINE,
            satisfied=paper_sufficient,
            observed={
                "session_status": status.get("status", "NOT_STARTED"),
                "wall_clock_hours": round(wall_clock_hours, 3),
                "events_processed": events,
            },
            required={
                "session_status": "RUNNING",
                "wall_clock_hours": MIN_PAPER_WALL_CLOCK_HOURS,
                "events_processed": MIN_PAPER_EVENTS,
            },
            blocker=(
                ""
                if paper_sufficient
                else "no paper session has produced a sufficient supervised result"
            ),
        ),
        ReadinessCondition(
            condition_id="reconciliation_clean",
            description="The paper session reconciles with no errors.",
            kind=CONDITION_MACHINE,
            satisfied=reconciliation_clean,
            observed=reconciliation or "no reconciliation on record",
            required="a reconciliation with zero problems",
            blocker="" if reconciliation_clean else "no clean reconciliation on record",
        ),
        ReadinessCondition(
            condition_id="owner_budget_explicit",
            description=(
                "The owner has stated, explicitly, how much money may be at "
                "risk. An agent cannot infer or assume this."
            ),
            kind=CONDITION_HUMAN,
            satisfied=owner_budget_usd is not None and owner_budget_usd > 0,
            observed=owner_budget_usd,
            required="a positive amount stated by the owner",
            blocker=(
                ""
                if owner_budget_usd is not None and owner_budget_usd > 0
                else "no explicit owner budget"
            ),
        ),
        ReadinessCondition(
            condition_id="exchange_and_jurisdiction_confirmed",
            description=(
                "The venue and the legal jurisdiction it will be traded from "
                "are confirmed by a human."
            ),
            kind=CONDITION_HUMAN,
            satisfied=exchange_and_jurisdiction_confirmed,
            observed=exchange_and_jurisdiction_confirmed,
            required=True,
            blocker=(
                ""
                if exchange_and_jurisdiction_confirmed
                else "exchange and jurisdiction not confirmed"
            ),
        ),
        ReadinessCondition(
            condition_id="loss_limits_configured",
            description="Per-trade, daily and total loss limits are configured.",
            kind=CONDITION_HUMAN,
            satisfied=bool(loss_limits_configured)
            and {"per_trade", "daily", "total"} <= set(loss_limits_configured or {}),
            observed=loss_limits_configured,
            required=["per_trade", "daily", "total"],
            blocker=(
                ""
                if loss_limits_configured
                and {"per_trade", "daily", "total"} <= set(loss_limits_configured)
                else "loss limits are not fully configured"
            ),
        ),
        ReadinessCondition(
            condition_id="credentials_delivery_secure",
            description=(
                "A secure mechanism exists for delivering venue credentials "
                "directly to the execution host. No key, seed phrase or wallet "
                "is ever requested, printed or stored by this tooling."
            ),
            kind=CONDITION_HUMAN,
            satisfied=credentials_delivery_mechanism_confirmed,
            observed=credentials_delivery_mechanism_confirmed,
            required=True,
            blocker=(
                ""
                if credentials_delivery_mechanism_confirmed
                else "no confirmed secure credential delivery mechanism"
            ),
        ),
    ]
    blocking = [c.condition_id for c in conditions if not c.satisfied]
    return CanaryReadiness(
        evaluated_at_utc=evaluated_at_utc,
        status="BLOCKED" if blocking else "READY_PENDING_HUMAN_AUTHORISATION",
        conditions=conditions,
        blocking_conditions=blocking,
        notes=[
            "Clearing every condition still does not authorise real money: it "
            "only means a human may now make that decision deliberately.",
            "Four of the six conditions are human decisions by construction and "
            "cannot be satisfied by any amount of further engineering.",
        ],
    )


__all__ = [
    "CONDITION_HUMAN",
    "CONDITION_MACHINE",
    "MIN_PAPER_EVENTS",
    "MIN_PAPER_WALL_CLOCK_HOURS",
    "CanaryReadiness",
    "ReadinessCondition",
    "evaluate_canary_readiness",
]
