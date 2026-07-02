from __future__ import annotations

import uuid

from quant_trade.backtest.costs import CostModel
from quant_trade.paper.models import PaperOrder, PaperRiskLimits, PaperSessionState


def target_weights_to_orders(
    account_state: PaperSessionState,
    target_weights: dict[str, float],
    current_prices: dict[str, float],
    risk_limits: PaperRiskLimits,
    cost_model: CostModel,
) -> list[PaperOrder]:
    equity = account_state.equity or account_state.cash
    capped = {
        s: min(max(float(w), 0.0), risk_limits.max_weight_per_asset)
        for s, w in target_weights.items()
    }
    gross = sum(capped.values())
    if gross > risk_limits.max_gross_exposure:
        capped = {s: w / gross * risk_limits.max_gross_exposure for s, w in capped.items()}
    orders = []
    turnover = 0.0
    symbols = set(capped) | set(account_state.positions)
    for sym in sorted(symbols):
        price = current_prices.get(sym)
        if not price:
            continue
        position = account_state.positions.get(sym)
        cur_qty = position.quantity if position is not None else 0.0
        cur_val = cur_qty * price
        desired = capped.get(sym, 0.0) * equity
        delta = desired - cur_val
        if abs(delta) < risk_limits.minimum_order_notional:
            continue
        if turnover + abs(delta) / max(equity, 1e-9) > risk_limits.max_turnover_per_rebalance:
            continue
        if (
            delta > 0
            and account_state.cash - delta - cost_model.trade_cost(abs(delta))
            < equity * risk_limits.min_cash_pct
        ):
            continue
        turnover += abs(delta) / max(equity, 1e-9)
        orders.append(
            PaperOrder(
                str(uuid.uuid4()),
                account_state.last_processed_timestamp,
                sym,
                "buy" if delta > 0 else "sell",
                abs(delta) / price,
                submitted_at=account_state.last_processed_timestamp,
            )
        )
    return sorted(orders, key=lambda o: 0 if o.side == "sell" else 1)
