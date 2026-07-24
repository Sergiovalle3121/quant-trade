"""Cash-and-carry economics: the full cost stack and fail-closed risk gates.

This is a *research* calculator. It answers "would this two-leg funding trade
clear a conservative bar, on paper?" — never "send orders". Expected carry uses
only causal (already-published) funding and is discounted for mean reversion;
every friction is subtracted before a GO is even possible.
"""

from __future__ import annotations

import math

from quant_trade.carry.models import (
    CarryCostModel,
    CarryEvaluation,
    CarryPolicy,
    CarryPosition,
    CarrySnapshot,
)

_DAYS_PER_YEAR = 365.0


def _normal_survival(z: float) -> float:
    """P(Z > z) for a standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _round_trip_friction(snapshot: CarrySnapshot, costs: CarryCostModel) -> float:
    """One-time friction as a fraction of notional for the four fills."""
    per_fill_bps = (
        snapshot.taker_fee_bps
        + costs.half_spread_bps
        + costs.slippage_bps
        + costs.market_impact_bps
    )
    return 4.0 * per_fill_bps / 1e4


def evaluate_carry(
    snapshot: CarrySnapshot,
    position: CarryPosition,
    costs: CarryCostModel,
    policy: CarryPolicy,
) -> CarryEvaluation:
    """Evaluate one snapshot/position pair. No network, no orders."""
    intervals_per_year = snapshot.funding_intervals_per_year
    gross_annual_carry = snapshot.annualized_realized_funding

    # Expected carry is conservative: shrink a positive carry for mean reversion,
    # never assume an adverse (negative) carry reverts in our favour.
    if gross_annual_carry > 0:
        expected_annual_carry = gross_annual_carry * (1.0 - policy.funding_reversion_haircut)
    else:
        expected_annual_carry = gross_annual_carry

    # --- cost stack (all annualized) --------------------------------------
    one_time = _round_trip_friction(snapshot, costs) + costs.conversion_withdrawal_cost
    annual_transaction_cost = one_time / position.holding_days * _DAYS_PER_YEAR
    borrow_cost = snapshot.borrow_rate_annual if snapshot.borrow_available else 0.0
    annual_carry_cost = (
        costs.spot_custody_cost_annual + costs.perp_margin_cost_annual + borrow_cost
    )
    total_annual_cost = annual_transaction_cost + annual_carry_cost

    net_annual_carry = expected_annual_carry - total_annual_cost
    net_2x = expected_annual_carry - 2.0 * total_annual_cost
    net_3x = expected_annual_carry - 3.0 * total_annual_cost

    # --- break-evens -------------------------------------------------------
    numerator = expected_annual_carry - annual_carry_cost
    break_even_holding_days = (
        one_time * _DAYS_PER_YEAR / numerator if numerator > 0 else None
    )
    denom = (1.0 - policy.funding_reversion_haircut) * intervals_per_year
    break_even_funding_rate = total_annual_cost / denom if denom > 0 else None

    # --- liquidation proxy (short perp leg) --------------------------------
    liquidation_distance = max(
        0.0, 1.0 / position.perp_leverage - snapshot.maintenance_margin_rate
    )
    horizon_vol = position.daily_volatility * math.sqrt(position.holding_days)
    if horizon_vol <= 0:
        liquidation_probability = 0.0 if liquidation_distance > 0 else 1.0
    else:
        liquidation_probability = _normal_survival(liquidation_distance / horizon_vol)

    # --- gates (fail closed) ----------------------------------------------
    reasons: list[str] = []
    notes: list[str] = []
    if snapshot.staleness_seconds > policy.max_staleness_seconds:
        reasons.append("snapshot is stale")
    if gross_annual_carry <= 0:
        reasons.append("funding sign is unfavourable (position would pay funding)")
    if abs(snapshot.basis) > policy.max_abs_basis:
        reasons.append("basis exceeds the policy maximum")
    if net_annual_carry < policy.min_net_annual_carry:
        reasons.append("net annualized carry below policy minimum")
    if net_2x < policy.min_carry_after_2x_costs:
        reasons.append("carry does not survive 2x cost stress")
    if net_3x < policy.min_carry_after_3x_costs:
        reasons.append("carry does not survive 3x cost stress")
    if liquidation_distance < policy.min_liquidation_distance:
        reasons.append("liquidation distance below policy minimum")
    if liquidation_probability > policy.max_liquidation_probability:
        reasons.append("liquidation probability proxy above policy maximum")
    if snapshot.borrow_rate_annual > 0 and not snapshot.borrow_available:
        reasons.append("borrow required but unavailable")

    if snapshot.predicted_funding_rate is not None:
        notes.append(
            "predicted_funding_rate is present but is NOT used for the decision; "
            "only realized funding known at capture time is."
        )

    return CarryEvaluation(
        symbol=snapshot.symbol,
        exchange=snapshot.exchange,
        decision="GO" if not reasons else "NO-GO",
        reasons=tuple(reasons),
        data_source=snapshot.data_source,
        gross_annual_carry=gross_annual_carry,
        expected_annual_carry=expected_annual_carry,
        annual_transaction_cost=annual_transaction_cost,
        annual_carry_cost=annual_carry_cost,
        net_annual_carry=net_annual_carry,
        net_annual_carry_2x_costs=net_2x,
        net_annual_carry_3x_costs=net_3x,
        basis=snapshot.basis,
        liquidation_distance=liquidation_distance,
        liquidation_probability_proxy=liquidation_probability,
        break_even_holding_days=break_even_holding_days,
        break_even_funding_rate=break_even_funding_rate,
        delta_after_hedge=0.0,  # model assumes matched notional; execution handles residual
        field_notes=tuple(notes),
    )
