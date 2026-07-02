from __future__ import annotations

from quant_trade.paper.events import create_event
from quant_trade.paper.models import PaperEvent, PaperOrder, PaperRiskLimits, PaperSessionState


def _equity(state: PaperSessionState) -> float:
    return state.equity or state.cash


def validate_order(
    order: PaperOrder,
    state: PaperSessionState,
    risk_limits: PaperRiskLimits,
    prices: dict[str, float],
) -> tuple[bool, str]:
    price = prices.get(order.symbol, order.fill_price or 0.0)
    if order.quantity <= 0:
        return False, "quantity must be positive"
    if (
        order.side == "sell"
        and not risk_limits.allow_short
        and state.positions.get(order.symbol, None) is not None
        and order.quantity > state.positions[order.symbol].quantity + 1e-9
    ):
        return False, "short sales are disabled"
    if order.side == "sell" and not risk_limits.allow_short and order.symbol not in state.positions:
        return False, "short sales are disabled"
    notional = order.quantity * price
    eq = max(_equity(state), 1e-9)
    if order.side == "buy":
        if (
            not risk_limits.allow_leverage
            and notional > state.cash * (1 - risk_limits.min_cash_pct) + 1e-9
        ):
            return False, "leverage is disabled or min cash would be breached"
        if notional / eq > risk_limits.max_weight_per_asset + 1e-9:
            return False, "order would exceed max weight per asset"
    return True, "accepted"


def validate_portfolio_state(
    state: PaperSessionState, risk_limits: PaperRiskLimits
) -> tuple[bool, list[str]]:
    reasons = []
    eq = max(_equity(state), 1e-9)
    gross = sum(abs(p.quantity * p.last_price) for p in state.positions.values()) / eq
    if gross > risk_limits.max_gross_exposure + 1e-9:
        reasons.append("gross exposure limit breached")
    if state.cash / eq < risk_limits.min_cash_pct - 1e-9:
        reasons.append("minimum cash breached")
    if not risk_limits.allow_leverage and gross > 1.0 + 1e-9:
        reasons.append("leverage is disabled")
    return not reasons, reasons


def should_trigger_kill_switch(state: PaperSessionState, risk_limits: PaperRiskLimits) -> bool:
    return (
        risk_limits.kill_switch_enabled and state.max_drawdown >= risk_limits.max_total_drawdown_pct
    )


def generate_risk_events(
    timestamp: str, state: PaperSessionState, risk_limits: PaperRiskLimits
) -> list[PaperEvent]:
    ok, reasons = validate_portfolio_state(state, risk_limits)
    events = (
        [create_event(timestamp, "risk_warning", r, "warning") for r in reasons] if not ok else []
    )
    if should_trigger_kill_switch(state, risk_limits):
        events.append(
            create_event(
                timestamp, "kill_switch_triggered", "max drawdown kill switch triggered", "critical"
            )
        )
    return events
