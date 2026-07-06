"""Simple deterministic long-only backtest engine."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from quant_trade.backtest.costs import CostModel
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
    cost_model: CostModel | None = None

    def run(self, data: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        signals = strategy.generate_signals(data).set_index("timestamp")
        portfolio = Portfolio(cash=self.initial_cash)
        trades: list[Trade] = []
        snapshots: list[PortfolioSnapshot] = []
        pending_signal = 0.0
        entry_time = None

        for i in range(len(data)):
            row = data.iloc[i]
            timestamp = row["timestamp"]
            open_price = float(row["open"])
            close_price = float(row["close"])
            raw_low = row.get("low")
            low_price = float(raw_low) if pd.notna(raw_low) else min(open_price, close_price)

            # Execute the order decided on the previous bar at this bar's open.
            if pending_signal > 0 and portfolio.quantity == 0:
                execution_price = self._execution_price(open_price, pending_signal)
                equity = portfolio.equity(execution_price)
                quantity = self.risk_manager.size_buy_quantity(
                    cash=portfolio.cash,
                    equity=equity,
                    price=execution_price,
                    current_position_value=portfolio.quantity * execution_price,
                )
                cost = self._cost(quantity, execution_price)
                if quantity > 0 and quantity * execution_price + cost <= portfolio.cash:
                    portfolio.buy(quantity, execution_price, cost)
                    entry_time = timestamp
            elif pending_signal < 0 and portfolio.quantity > 0:
                execution_price = self._execution_price(open_price, pending_signal)
                cost = self._cost(portfolio.quantity, execution_price)
                sold_quantity, entry_price, _ = portfolio.sell_all(execution_price, cost)
                pnl = (execution_price - entry_price) * sold_quantity - cost
                trades.append(
                    Trade(
                        entry_time=entry_time if entry_time is not None else timestamp,
                        exit_time=timestamp,
                        quantity=sold_quantity,
                        entry_price=entry_price,
                        exit_price=execution_price,
                        pnl=pnl,
                        return_pct=pnl / (entry_price * sold_quantity),
                    )
                )
                entry_time = None
            pending_signal = 0.0

            # Stop-loss on the intrabar low: fill at the stop level (or this
            # bar's open when it gapped through) with sell-side slippage.
            if portfolio.quantity > 0 and self.risk_manager.is_stop_loss_triggered(
                entry_price=portfolio.average_price, current_price=low_price
            ):
                stop_pct = self.risk_manager.stop_loss_pct or 0.0
                stop_level = portfolio.average_price * (1 - stop_pct)
                fill_price = self._execution_price(min(stop_level, open_price), -1.0)
                cost = self._cost(portfolio.quantity, fill_price)
                sold_quantity, entry_price, _ = portfolio.sell_all(fill_price, cost)
                pnl = (fill_price - entry_price) * sold_quantity - cost
                trades.append(
                    Trade(
                        entry_time=entry_time if entry_time is not None else timestamp,
                        exit_time=timestamp,
                        quantity=sold_quantity,
                        entry_price=entry_price,
                        exit_price=fill_price,
                        pnl=pnl,
                        return_pct=pnl / (entry_price * sold_quantity),
                    )
                )
                entry_time = None

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

            # Read this bar's signal only after the bar is fully processed;
            # it becomes actionable at the next bar's open.
            signal = float(signals.loc[timestamp, "signal"]) if timestamp in signals.index else 0.0
            if signal != 0 and i + 1 < len(data):
                pending_signal = signal

        equity_curve = pd.DataFrame([snapshot.model_dump() for snapshot in snapshots])
        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            metrics=calculate_performance(equity_curve, trades),
        )

    def _execution_price(self, open_price: float, signal: float) -> float:
        # Slippage is always applied as an adverse fill-price adjustment. When
        # a CostModel is provided its slippage_bps drives the adjustment (and
        # is then excluded from the cash cost so it is never charged twice).
        if self.cost_model is not None:
            slippage = self.cost_model.slippage_bps / 10_000
        else:
            slippage = self.slippage_bps / 10_000
        return open_price * (1 + slippage if signal > 0 else 1 - slippage)

    def _cost(self, quantity: float, price: float) -> float:
        notional = quantity * price
        if self.cost_model is not None:
            return self.cost_model.trade_cost(notional, include_slippage=False)
        return notional * self.transaction_cost_bps / 10_000
