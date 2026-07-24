"""Deterministic stress scenarios for cash-and-carry research.

Each scenario mutates a snapshot (and, where relevant, the cost model) and
re-evaluates, so a campaign's GO can be checked against exchange outages,
depegs, withdrawal freezes, funding sign flips, and extreme spreads. These are
policy inputs, not forecasts, and nothing here trades.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from quant_trade.carry.economics import evaluate_carry
from quant_trade.carry.models import (
    CarryCostModel,
    CarryEvaluation,
    CarryPolicy,
    CarryPosition,
    CarrySnapshot,
)


@dataclass(frozen=True)
class CarryScenario:
    """Multiplicative/additive shocks applied to one snapshot + cost model."""

    name: str
    funding_multiplier: float = 1.0
    basis_add: float = 0.0
    staleness_add_seconds: float = 0.0
    taker_fee_add_bps: float = 0.0
    spread_multiplier: float = 1.0
    borrow_available_override: bool | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name must be non-empty")
        if self.spread_multiplier < 0:
            raise ValueError("spread_multiplier must be >= 0")


@dataclass
class CarryScenarioEvaluation:
    scenario: str
    description: str
    decision: str
    reasons: tuple[str, ...]
    net_annual_carry: float
    basis: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_carry_scenarios() -> tuple[CarryScenario, ...]:
    """A fixed research scenario set (inputs, not predictions)."""
    return (
        CarryScenario("base", description="unshocked snapshot"),
        CarryScenario(
            "funding_sign_flip",
            funding_multiplier=-1.0,
            description="funding turns negative; the position would pay funding",
        ),
        CarryScenario(
            "depeg",
            basis_add=0.05,
            description="quote asset de-pegs; basis gaps well beyond the limit",
        ),
        CarryScenario(
            "withdrawal_freeze",
            borrow_available_override=False,
            staleness_add_seconds=0.0,
            description="venue halts withdrawals; borrow/unwind unavailable",
        ),
        CarryScenario(
            "exchange_outage",
            staleness_add_seconds=100_000.0,
            description="venue/API outage; the snapshot goes stale",
        ),
        CarryScenario(
            "extreme_spread",
            taker_fee_add_bps=20.0,
            spread_multiplier=8.0,
            description="liquidity evaporates; spreads and fees spike",
        ),
    )


def evaluate_carry_scenario(
    snapshot: CarrySnapshot,
    position: CarryPosition,
    costs: CarryCostModel,
    policy: CarryPolicy,
    scenario: CarryScenario,
) -> CarryScenarioEvaluation:
    """Apply a scenario's shocks and re-evaluate the carry (no orders)."""
    borrow_available = (
        snapshot.borrow_available
        if scenario.borrow_available_override is None
        else scenario.borrow_available_override
    )
    # basis_add shifts the perp mark relative to spot.
    shocked_perp = snapshot.perp_mark_price + scenario.basis_add * snapshot.spot_price
    shocked_snapshot = replace(
        snapshot,
        realized_funding_rate=snapshot.realized_funding_rate * scenario.funding_multiplier,
        perp_mark_price=max(1e-9, shocked_perp),
        staleness_seconds=snapshot.staleness_seconds + scenario.staleness_add_seconds,
        borrow_available=borrow_available,
        taker_fee_bps=snapshot.taker_fee_bps + scenario.taker_fee_add_bps,
    )
    shocked_costs = replace(
        costs,
        half_spread_bps=costs.half_spread_bps * scenario.spread_multiplier,
        slippage_bps=costs.slippage_bps * scenario.spread_multiplier,
    )
    result: CarryEvaluation = evaluate_carry(shocked_snapshot, position, shocked_costs, policy)
    return CarryScenarioEvaluation(
        scenario=scenario.name,
        description=scenario.description,
        decision=result.decision,
        reasons=result.reasons,
        net_annual_carry=result.net_annual_carry,
        basis=result.basis,
    )


def evaluate_carry_scenarios(
    snapshot: CarrySnapshot,
    position: CarryPosition,
    costs: CarryCostModel,
    policy: CarryPolicy,
    scenarios: tuple[CarryScenario, ...] | None = None,
) -> list[CarryScenarioEvaluation]:
    """Evaluate the full scenario matrix for one snapshot."""
    selected = scenarios or default_carry_scenarios()
    return [
        evaluate_carry_scenario(snapshot, position, costs, policy, scenario)
        for scenario in selected
    ]
