from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from quant_trade.execution.broker import (
    BrokerAccount,
    BrokerClock,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)
from quant_trade.paper.models import PaperOrder


class SimulatedBroker:
    def __init__(self) -> None:
        self.orders: dict[str, Any] = {}

    def get_account(self) -> BrokerAccount:
        return BrokerAccount(
            "simulated", "sim****", "USD", 100000.0, 100000.0, 100000.0, "active", True
        )

    def get_positions(self) -> list[BrokerPosition]:
        return []

    def get_open_orders(self) -> list[BrokerOrder]:
        return [
            o for o in self.orders.values() if isinstance(o, BrokerOrder) and o.status == "open"
        ]

    def submit_order(self, order: BrokerOrderRequest | PaperOrder) -> BrokerOrder | PaperOrder:
        if isinstance(order, PaperOrder):
            if order.quantity <= 0:
                order.status = "rejected"
                order.reason = "quantity must be positive"
            self.orders[order.order_id] = order
            return order
        status = "dry_run" if order.dry_run else "accepted"
        result = BrokerOrder(
            str(uuid.uuid4()),
            order.client_order_id,
            order.symbol,
            order.side,
            order.quantity,
            0.0,
            order.order_type,
            status,
            datetime.now(UTC).isoformat(),
            True,
        )
        self.orders[result.broker_order_id] = result
        return result

    def cancel_order(self, order_id: str) -> None:
        if order_id in self.orders:
            self.orders[order_id].status = "cancelled"

    def cancel_all_orders(self) -> None:
        for order_id in list(self.orders):
            self.cancel_order(order_id)

    def get_order(self, order_id: str) -> BrokerOrder | PaperOrder | None:
        return self.orders.get(order_id)

    def list_orders(self) -> list[Any]:
        return list(self.orders.values())

    def get_clock(self) -> BrokerClock:
        now = datetime.now(UTC).isoformat()
        return BrokerClock(now, False, now, now)

    def health_check(self) -> BrokerHealth:
        return BrokerHealth("simulated", True, True, "simulated broker ready")
