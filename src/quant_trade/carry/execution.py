"""Simulated two-leg execution state machine (no real orders, ever).

Establishing a cash-and-carry position means filling two legs — buy spot, short
perp — while never sitting on more delta than you can tolerate. This module
simulates that coordination deterministically so research can reason about
partial fills, unhedged-risk windows, timeouts, and emergency unwinds without
touching a venue. No function here submits, cancels, or routes a real order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class TwoLegState(StrEnum):
    PLANNED = "PLANNED"
    LEG_1_PARTIAL = "LEG_1_PARTIAL"
    LEG_2_PARTIAL = "LEG_2_PARTIAL"
    HEDGED = "HEDGED"
    UNHEDGED_RISK = "UNHEDGED_RISK"
    UNWINDING = "UNWINDING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class TwoLegPlan:
    symbol: str
    exchange: str
    spot_target_qty: float
    perp_target_qty: float
    spot_price: float
    perp_price: float
    max_unhedged_notional: float
    timeout_steps: int
    max_retries: int = 3
    unwind_cost_bps: float = 10.0
    fill_epsilon: float = 1e-9

    def __post_init__(self) -> None:
        for name in ("spot_target_qty", "perp_target_qty", "spot_price", "perp_price"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.max_unhedged_notional < 0:
            raise ValueError("max_unhedged_notional must be >= 0")
        if self.timeout_steps <= 0:
            raise ValueError("timeout_steps must be > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")


@dataclass
class FillStep:
    """One coordination step: requested fills and per-leg venue availability."""

    spot_fill: float = 0.0
    perp_fill: float = 0.0
    spot_available: bool = True
    perp_available: bool = True


@dataclass
class TwoLegResult:
    state: TwoLegState
    spot_filled: float
    perp_filled: float
    delta_notional: float
    max_unhedged_notional_seen: float
    unwind_cost_usd: float
    retries_used: int
    reconciled: bool
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


def _delta_notional(spot_filled: float, perp_filled: float, plan: TwoLegPlan) -> float:
    return spot_filled * plan.spot_price - perp_filled * plan.perp_price


def simulate_two_leg(plan: TwoLegPlan, steps: list[FillStep]) -> TwoLegResult:
    """Drive the state machine deterministically over ``steps``.

    Invariants: fills never exceed targets (no phantom fills); an unhedged
    notional above ``max_unhedged_notional`` flags UNHEDGED_RISK; failure to
    hedge within ``timeout_steps`` (or exhausting retries with one leg only)
    triggers a simulated emergency unwind that returns the book to flat.
    """
    spot_filled = 0.0
    perp_filled = 0.0
    retries_used = 0
    max_unhedged_seen = 0.0
    events: list[dict[str, Any]] = []
    state = TwoLegState.PLANNED
    events.append({"step": -1, "state": state.value, "detail": "plan accepted"})

    eps = plan.fill_epsilon

    def leg_complete() -> tuple[bool, bool]:
        return (
            spot_filled >= plan.spot_target_qty - eps,
            perp_filled >= plan.perp_target_qty - eps,
        )

    for i, step in enumerate(steps):
        if state in (TwoLegState.HEDGED, TwoLegState.CLOSED, TwoLegState.REJECTED):
            break
        # apply fills, clamped to remaining target (never overfill)
        if step.spot_available and step.spot_fill > 0:
            room = max(0.0, plan.spot_target_qty - spot_filled)
            spot_filled += min(step.spot_fill, room)
        elif step.spot_fill > 0 and not step.spot_available:
            retries_used += 1
        if step.perp_available and step.perp_fill > 0:
            room = max(0.0, plan.perp_target_qty - perp_filled)
            perp_filled += min(step.perp_fill, room)
        elif step.perp_fill > 0 and not step.perp_available:
            retries_used += 1

        delta = _delta_notional(spot_filled, perp_filled, plan)
        max_unhedged_seen = max(max_unhedged_seen, abs(delta))
        spot_done, perp_done = leg_complete()

        if spot_done and perp_done:
            state = TwoLegState.HEDGED
        elif abs(delta) > plan.max_unhedged_notional:
            state = TwoLegState.UNHEDGED_RISK
        elif spot_filled > eps and not perp_done:
            state = TwoLegState.LEG_1_PARTIAL
        elif perp_filled > eps and not spot_done:
            state = TwoLegState.LEG_2_PARTIAL
        events.append(
            {
                "step": i,
                "state": state.value,
                "spot_filled": spot_filled,
                "perp_filled": perp_filled,
                "delta_notional": delta,
                "retries_used": retries_used,
            }
        )
        if retries_used > plan.max_retries and state != TwoLegState.HEDGED:
            events.append({"step": i, "state": state.value, "detail": "retry budget exhausted"})
            break
        if i + 1 >= plan.timeout_steps and state != TwoLegState.HEDGED:
            events.append({"step": i, "state": state.value, "detail": "timeout reached"})
            break

    delta = _delta_notional(spot_filled, perp_filled, plan)
    unwind_cost = 0.0

    if state == TwoLegState.HEDGED:
        reconciled = abs(delta) <= max(plan.max_unhedged_notional, eps)
        events.append({"step": "final", "state": state.value, "detail": "hedge established"})
        return TwoLegResult(
            state=state,
            spot_filled=spot_filled,
            perp_filled=perp_filled,
            delta_notional=delta,
            max_unhedged_notional_seen=max_unhedged_seen,
            unwind_cost_usd=0.0,
            retries_used=retries_used,
            reconciled=reconciled,
            events=events,
        )

    # Not hedged: fail closed. Nothing filled -> REJECTED; otherwise emergency
    # unwind the filled legs back to flat and book the unwind cost.
    if spot_filled <= eps and perp_filled <= eps:
        state = TwoLegState.REJECTED
        events.append({"step": "final", "state": state.value, "detail": "no fills; rejected"})
        return TwoLegResult(
            state=state,
            spot_filled=0.0,
            perp_filled=0.0,
            delta_notional=0.0,
            max_unhedged_notional_seen=max_unhedged_seen,
            unwind_cost_usd=0.0,
            retries_used=retries_used,
            reconciled=True,
            events=events,
        )

    state = TwoLegState.UNWINDING
    events.append({"step": "final", "state": state.value, "detail": "emergency unwind"})
    unwound_notional = spot_filled * plan.spot_price + perp_filled * plan.perp_price
    unwind_cost = unwound_notional * plan.unwind_cost_bps / 1e4
    state = TwoLegState.CLOSED
    events.append(
        {
            "step": "final",
            "state": state.value,
            "detail": "unwound to flat",
            "unwind_cost": unwind_cost,
        }
    )
    return TwoLegResult(
        state=state,
        spot_filled=0.0,  # unwound
        perp_filled=0.0,  # unwound
        delta_notional=0.0,
        max_unhedged_notional_seen=max_unhedged_seen,
        unwind_cost_usd=unwind_cost,
        retries_used=retries_used,
        reconciled=True,
        events=events,
    )
