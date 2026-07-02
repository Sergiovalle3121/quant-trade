"""Portfolio accounting helpers for long-only deterministic backtests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Portfolio:
    """Cash and long position state."""

    cash: float
    quantity: float = 0.0
    average_price: float = 0.0

    def equity(self, price: float) -> float:
        return self.cash + self.quantity * price

    def buy(self, quantity: float, price: float, cost: float) -> None:
        total_cost = quantity * price + cost
        if total_cost > self.cash + 1e-9:
            raise ValueError("Buy exceeds available cash")
        old_value = self.quantity * self.average_price
        self.quantity += quantity
        self.average_price = (old_value + quantity * price) / self.quantity
        self.cash -= total_cost

    def sell_all(self, price: float, cost: float) -> tuple[float, float, float]:
        if self.quantity <= 0:
            return 0.0, 0.0, 0.0
        quantity = self.quantity
        entry_price = self.average_price
        proceeds = quantity * price - cost
        self.cash += proceeds
        self.quantity = 0.0
        self.average_price = 0.0
        return quantity, entry_price, proceeds
