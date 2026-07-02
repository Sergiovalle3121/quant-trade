"""Basic first-version risk controls for long-only research backtests."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskManager(BaseModel):
    """Position sizing guardrails: no leverage, no margin, cash-limited orders."""

    max_position_pct: float = Field(default=0.25, gt=0, le=1)
    max_trade_pct: float = Field(default=0.10, gt=0, le=1)
    stop_loss_pct: float | None = Field(default=None, gt=0, le=1)

    def size_buy_quantity(
        self, *, cash: float, equity: float, price: float, current_position_value: float
    ) -> float:
        """Return affordable quantity capped by trade and total-position limits."""
        if cash <= 0 or equity <= 0 or price <= 0:
            return 0.0
        max_position_value = equity * self.max_position_pct
        remaining_position_capacity = max(0.0, max_position_value - current_position_value)
        max_trade_value = equity * self.max_trade_pct
        order_value = min(cash, max_trade_value, remaining_position_capacity)
        return max(0.0, order_value / price)

    def is_stop_loss_triggered(self, *, entry_price: float, current_price: float) -> bool:
        """Check optional stop loss for an open long position."""
        return self.stop_loss_pct is not None and current_price <= entry_price * (
            1 - self.stop_loss_pct
        )
