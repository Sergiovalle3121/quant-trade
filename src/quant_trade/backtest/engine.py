"""Simple deterministic long-only backtest engine."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from quant_trade.backtest.portfolio import Portfolio
from quant_trade.core.models import PortfolioSnapshot, Trade
from quant_trade.metrics.performance import calculate_performance
from quant_trade.risk.risk_manager import RiskManager
from quant_trade.strategies.base import Strategy


class BacktestResult(BaseModel):
    """Backtest output bundle."""

    trades: list[Trade]
    equity_curve: pd.DataFrame
    metrics: dict[str, float | int]

    model_config = {"arbitrary_types_allowed": True}


class BacktestEngine(BaseModel):
    """Long-only, cash-only simulator with next-bar execution approximation."""

    initial_cash: float = Field(default=10_000.0, gt=0)
    transaction_cost_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    risk_manager: RiskManager = Field(default_factory=RiskManager)

    def run(self, data: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        signals = strategy.generate_signals(data).set_index("timestamp")
        portfolio = Portfolio(cash=self.initial_cash)
        trades: list[Trade] = []
        snapshots: list[PortfolioSnapshot] = []

        for i in range(len(data)):
            row = data.iloc[i]
            timestamp = row["timestamp"]
            close_price = float(row["close"])
            signal = float(signals.loc[timestamp, "signal"]) if timestamp in signals.index else 0.0

            if i + 1 < len(data) and signal != 0:
                next_row = data.iloc[i + 1]
                execution_time = next_row["timestamp"]
                execution_price = self._execution_price(float(next_row["open"]), signal)
                if signal > 0 and portfolio.quantity == 0:
                    equity = portfolio.equity(close_price)
                    quantity = self.risk_manager.size_buy_quantity(
                        cash=portfolio.cash,
                        equity=equity,
                        price=execution_price,
                        current_position_value=portfolio.quantity * close_price,
                    )
                    cost = self._cost(quantity, execution_price)
                    if quantity > 0 and quantity * execution_price + cost <= portfolio.cash:
                        portfolio.buy(quantity, execution_price, cost)
                elif signal < 0 and portfolio.quantity > 0:
                    quantity = portfolio.quantity
                    cost = self._cost(quantity, execution_price)
                    sold_quantity, entry_price, _ = portfolio.sell_all(execution_price, cost)
                    pnl = (execution_price - entry_price) * sold_quantity - cost
                    trades.append(
                        Trade(
                            entry_time=timestamp,
                            exit_time=execution_time,
                            quantity=sold_quantity,
                            entry_price=entry_price,
                            exit_price=execution_price,
                            pnl=pnl,
                            return_pct=pnl / (entry_price * sold_quantity),
                        )
                    )

            if portfolio.quantity > 0 and self.risk_manager.is_stop_loss_triggered(
                entry_price=portfolio.average_price, current_price=close_price
            ):
                cost = self._cost(portfolio.quantity, close_price)
                sold_quantity, entry_price, _ = portfolio.sell_all(close_price, cost)
                pnl = (close_price - entry_price) * sold_quantity - cost
                trades.append(
                    Trade(
                        entry_time=timestamp,
                        exit_time=timestamp,
                        quantity=sold_quantity,
                        entry_price=entry_price,
                        exit_price=close_price,
                        pnl=pnl,
                        return_pct=pnl / (entry_price * sold_quantity),
                    )
                )

            equity = portfolio.equity(close_price)
            snapshots.append(
                PortfolioSnapshot(
                    timestamp=timestamp,
                    cash=portfolio.cash,
                    position_quantity=portfolio.quantity,
                    position_value=portfolio.quantity * close_price,
                    equity=equity,
                )
            )

        equity_curve = pd.DataFrame([snapshot.model_dump() for snapshot in snapshots])
        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            metrics=calculate_performance(equity_curve, trades),
        )

    def _execution_price(self, open_price: float, signal: float) -> float:
        slippage = self.slippage_bps / 10_000
        return open_price * (1 + slippage if signal > 0 else 1 - slippage)

    def _cost(self, quantity: float, price: float) -> float:
        return quantity * price * self.transaction_cost_bps / 10_000
