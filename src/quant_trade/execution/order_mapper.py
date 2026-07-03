from __future__ import annotations

from quant_trade.execution.broker import BrokerOrderRequest
from quant_trade.execution.config import BrokerConfig
from quant_trade.execution.exceptions import BrokerSafetyError
from quant_trade.paper.models import PaperOrder


def paper_order_to_broker_order_request(
    paper_order: PaperOrder, config: BrokerConfig
) -> BrokerOrderRequest:
    if paper_order.order_type != "market":
        raise BrokerSafetyError("only market orders can be mapped initially")
    if paper_order.side not in {"buy", "sell"}:
        raise BrokerSafetyError("invalid paper order side")
    if paper_order.quantity <= 0:
        raise BrokerSafetyError("paper order quantity must be positive")
    symbol = paper_order.symbol.upper().strip()
    if config.universe and symbol not in {s.upper() for s in config.universe}:
        raise BrokerSafetyError(f"symbol {symbol} is outside configured universe")
    return BrokerOrderRequest(
        symbol=symbol,
        side=paper_order.side,
        quantity=float(paper_order.quantity),
        order_type="market",
        time_in_force="day",
        client_order_id=f"qt-{paper_order.order_id}"[:48],
        dry_run=config.dry_run_default,
        strategy_id=None,
        reason=paper_order.reason or "mapped from simulated paper order",
    )
