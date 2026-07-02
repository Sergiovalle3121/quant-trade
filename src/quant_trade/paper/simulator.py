from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from quant_trade.backtest.costs import CostModel
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.paper.config import load_paper_config
from quant_trade.paper.events import create_event
from quant_trade.paper.models import (
    PaperFill,
    PaperPortfolioSnapshot,
    PaperPosition,
    PaperSessionState,
)
from quant_trade.paper.rebalancer import target_weights_to_orders
from quant_trade.paper.reports import write_csvs, write_report
from quant_trade.paper.risk import generate_risk_events, should_trigger_kill_switch, validate_order
from quant_trade.paper.state import save_state
from quant_trade.research.strategy_registry import get_research_signal_model


class PaperTradingSimulator:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = load_paper_config(config_path)
        self.cost_model = CostModel(**self.config.costs)

    def run(self) -> Path:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = Path(self.config.output_dir) / self.config.paper_session_name / run_id
        out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.config_path, out / "config_used.yaml")
        data = load_ohlcv_csv(Path(self.config.data_path))
        data = data[data["symbol"].isin(self.config.universe.get("symbols", []))].sort_values(
            "timestamp"
        )
        state = PaperSessionState(
            cash=self.config.initial_cash,
            equity=self.config.initial_cash,
            high_water_mark=self.config.initial_cash,
            status="running",
        )
        snapshots = []
        orders = []
        fills = []
        positions = []
        events = [
            create_event(
                str(data["timestamp"].min()), "session_started", "simulated session started"
            ).to_dict()
        ]
        risk_events = []
        model = get_research_signal_model(self.config.strategy)
        for ts, day in data.groupby("timestamp", sort=True):
            ts_str = str(ts)
            state.last_processed_timestamp = ts_str
            prices = {str(r.symbol): float(r.open) for r in day.itertuples()}
            for sym, pos in state.positions.items():
                if sym in prices:
                    pos.last_price = prices[sym]
            state.equity = state.cash + sum(
                p.quantity * p.last_price for p in state.positions.values()
            )
            state.high_water_mark = max(state.high_water_mark, state.equity)
            state.max_drawdown = max(
                state.max_drawdown, 1 - state.equity / max(state.high_water_mark, 1e-9)
            )
            if should_trigger_kill_switch(state, self.config.risk_limits):
                state.kill_switch_active = True
                state.status = "paused"
            if state.status == "paused" or state.kill_switch_active:
                continue
            hist = data[data["timestamp"] <= ts]
            signals = model.generate(hist, self.config.strategy_params)
            todays = signals[signals["timestamp"] == ts] if not signals.empty else signals
            if not todays.empty:
                target = {str(r.symbol): float(r.target_weight) for r in todays.itertuples()}
                events.append(
                    create_event(
                        ts_str, "signal_generated", "target weights generated", details=target
                    ).to_dict()
                )
                new_orders = target_weights_to_orders(
                    state, target, prices, self.config.risk_limits, self.cost_model
                )
                if new_orders:
                    events.append(
                        create_event(ts_str, "rebalance_due", "rebalance orders created").to_dict()
                    )
                for order in new_orders:
                    ok, reason = validate_order(order, state, self.config.risk_limits, prices)
                    if not ok:
                        order.status = "rejected"
                        order.reason = reason
                        orders.append(order.to_dict())
                        events.append(
                            create_event(
                                ts_str, "order_rejected", reason, "warning", order.to_dict()
                            ).to_dict()
                        )
                        continue
                    price = prices[order.symbol]
                    notional = order.quantity * price
                    cost = self.cost_model.trade_cost(notional)
                    order.status = "filled"
                    order.filled_at = ts_str
                    order.fill_price = price
                    order.cost = cost
                    if order.side == "buy":
                        state.cash -= notional + cost
                        pos = state.positions.get(
                            order.symbol, PaperPosition(order.symbol, 0.0, price, price)
                        )
                        pos.quantity += order.quantity
                        pos.average_cost = price
                        pos.last_price = price
                        state.positions[order.symbol] = pos
                    else:
                        pos = state.positions[order.symbol]
                        pos.quantity -= order.quantity
                        state.cash += notional - cost
                        state.realized_pnl += (price - pos.average_cost) * order.quantity - cost
                        if pos.quantity <= 1e-9:
                            del state.positions[order.symbol]
                    fill = PaperFill(
                        str(uuid.uuid4()),
                        order.order_id,
                        ts_str,
                        order.symbol,
                        order.side,
                        order.quantity,
                        price,
                        cost,
                    )
                    state.fills.append(fill)
                    fills.append(fill.to_dict())
                    orders.append(order.to_dict())
                    events.append(
                        create_event(
                            ts_str, "order_filled", "order filled", details=order.to_dict()
                        ).to_dict()
                    )
            state.equity = state.cash + sum(
                p.quantity * p.last_price for p in state.positions.values()
            )
            state.unrealized_pnl = sum(
                (p.last_price - p.average_cost) * p.quantity for p in state.positions.values()
            )
            gross = sum(abs(p.quantity * p.last_price) for p in state.positions.values()) / max(
                state.equity, 1e-9
            )
            state.high_water_mark = max(state.high_water_mark, state.equity)
            state.max_drawdown = max(
                state.max_drawdown, 1 - state.equity / max(state.high_water_mark, 1e-9)
            )
            snapshots.append(
                PaperPortfolioSnapshot(
                    ts_str,
                    state.cash,
                    state.equity,
                    gross,
                    state.realized_pnl,
                    state.unrealized_pnl,
                    state.max_drawdown,
                ).to_dict()
            )
            for ev in generate_risk_events(ts_str, state, self.config.risk_limits):
                risk_events.append(ev.to_dict())
                events.append(ev.to_dict())
            if should_trigger_kill_switch(state, self.config.risk_limits):
                state.kill_switch_active = True
                state.status = "paused"
                events.append(
                    create_event(
                        ts_str, "kill_switch_triggered", "kill switch active", "critical"
                    ).to_dict()
                )
        state.status = "stopped" if not state.kill_switch_active else "paused"
        events.append(
            create_event(
                state.last_processed_timestamp, "session_completed", "simulated session completed"
            ).to_dict()
        )
        positions = [{"symbol": s, **p.__dict__} for s, p in state.positions.items()]
        write_csvs(out, snapshots, orders, fills, positions, events, risk_events)
        write_report(out, self.config, state, orders, fills, snapshots, risk_events)
        (out / "final_state.json").write_text(
            json.dumps(state.to_dict(), indent=2), encoding="utf-8"
        )
        save_state(
            Path(self.config.state_dir) / self.config.paper_session_name / "latest_state.json",
            state,
        )
        return out
