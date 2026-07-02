from __future__ import annotations

from quant_trade.paper.models import PaperOrder


class SimulatedBroker:
    def __init__(self) -> None:
        self.orders: dict[str, PaperOrder] = {}

    def get_account(self) -> dict:
        return {"mode": "simulated"}

    def get_positions(self) -> list[dict]:
        return []

    def submit_order(self, order: PaperOrder) -> PaperOrder:
        if order.quantity <= 0:
            order.status = "rejected"
            order.reason = "quantity must be positive"
        self.orders[order.order_id] = order
        return order

    def cancel_order(self, order_id: str) -> None:
        if order_id in self.orders:
            self.orders[order_id].status = "cancelled"

    def get_order(self, order_id: str) -> PaperOrder | None:
        return self.orders.get(order_id)

    def list_orders(self) -> list[PaperOrder]:
        return list(self.orders.values())
