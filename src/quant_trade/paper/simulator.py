from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.execution.bar_model import (
    BarExecutionPolicy,
    BarOrderState,
    ExecutionStatus,
    cancel_order,
    execute_market_order_on_bar,
)
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
from quant_trade.paper.state import load_state, save_state
from quant_trade.research.strategy_registry import get_research_signal_model


class PaperTradingSimulator:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = load_paper_config(config_path)
        self.cost_model = CostModel(**self.config.costs)
        execution_price = str((self.config.execution or {}).get("execution_price", "next_open"))
        if execution_price != "next_open":
            raise ValueError(
                "only execution.execution_price=next_open is supported; signals decided on "
                "bar t fill at bar t+1's open to match the backtest engine"
            )
        self.execution_policy = BarExecutionPolicy.from_mapping(self.config.execution)
        if (
            not bool((self.config.execution or {}).get("fractional_shares", True))
            and self.execution_policy.lot_size is None
        ):
            self.execution_policy = replace(self.execution_policy, lot_size=1.0)

    def run(self) -> Path:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = Path(self.config.output_dir) / self.config.paper_session_name / run_id
        out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.config_path, out / "config_used.yaml")
        data = load_ohlcv_csv(Path(self.config.data_path))
        data = data[data["symbol"].isin(self.config.universe.get("symbols", []))].sort_values(
            "timestamp"
        )
        state_path = (
            Path(self.config.state_dir) / self.config.paper_session_name / "latest_state.json"
        )
        resume = bool((self.config.execution or {}).get("resume_from_state", False))
        if resume and state_path.exists():
            state = load_state(state_path)
            if state.kill_switch_active or state.status == "paused":
                raise RuntimeError(
                    "persisted session is paused or kill-switched; an operator must clear "
                    "the flags explicitly before resuming"
                )
            if state.last_processed_timestamp:
                cutoff = pd.Timestamp(state.last_processed_timestamp)
                data = data[data["timestamp"] > cutoff]
            state.status = "running"
        else:
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
        # Targets decided on bar t are executed at bar t+1's open. Executing at
        # bar t's open would fill using close-derived information from the same
        # bar (look-ahead) and systematically flatter paper results.
        pending_target: dict[str, float] | None = None
        current_day = ""
        day_start_equity = state.equity
        orders_submitted_today = 0

        def _execution_state(order) -> BarOrderState:
            status = (
                ExecutionStatus.SUBMITTED
                if order.status == "pending"
                else ExecutionStatus(order.status)
            )
            direction = 1.0 if order.side == "buy" else -1.0
            return BarOrderState(
                order_id=order.order_id,
                symbol=order.symbol,
                signed_quantity=direction * order.quantity,
                submitted_bar_index=order.submitted_bar_index,
                eligible_bar_index=order.eligible_bar_index,
                remaining_quantity=direction * float(order.remaining_quantity or 0.0),
                cumulative_filled_quantity=order.filled_quantity,
                average_fill_price=order.fill_price,
                fill_count=order.fill_count,
                status=status,
                reason=order.reason,
                last_attempt_bar_index=order.last_attempt_bar_index,
            )

        def _sync_order(order, execution_order: BarOrderState) -> None:
            order.status = execution_order.status.value
            order.reason = execution_order.reason
            order.remaining_quantity = abs(float(execution_order.remaining_quantity or 0.0))
            order.filled_quantity = execution_order.cumulative_filled_quantity
            order.fill_price = execution_order.average_fill_price
            order.fill_count = execution_order.fill_count
            order.last_attempt_bar_index = execution_order.last_attempt_bar_index

        def _daily_loss_breached() -> bool:
            if day_start_equity <= 0:
                return False
            loss = 1 - state.equity / day_start_equity
            return loss > self.config.risk_limits.max_daily_loss_pct

        for ts, day in data.groupby("timestamp", sort=True):
            bar_index = state.processed_bar_count
            state.processed_bar_count += 1
            ts_str = str(ts)
            state.last_processed_timestamp = ts_str
            prices = {str(r.symbol): float(r.open) for r in day.itertuples()}
            volumes = {str(r.symbol): float(r.volume) for r in day.itertuples()}
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
            bar_day = ts_str[:10]
            if bar_day != current_day:
                current_day = bar_day
                day_start_equity = state.equity
                orders_submitted_today = 0
            if _daily_loss_breached() and not state.kill_switch_active:
                state.kill_switch_active = True
                state.status = "paused"
                events.append(
                    create_event(
                        ts_str,
                        "daily_loss_circuit_breaker",
                        "daily loss limit breached; trading halted",
                        "critical",
                    ).to_dict()
                )
            if should_trigger_kill_switch(state, self.config.risk_limits):
                state.kill_switch_active = True
                state.status = "paused"
            if state.status == "paused" or state.kill_switch_active:
                continue
            target, pending_target = pending_target, None
            if target is not None:
                if state.open_orders:
                    for old_order in state.open_orders:
                        execution_order = _execution_state(old_order)
                        cancel_order(execution_order, "superseded by a newer target")
                        _sync_order(old_order, execution_order)
                        orders.append(old_order.to_dict())
                        events.append(
                            create_event(
                                ts_str,
                                "order_cancelled",
                                old_order.reason,
                                "warning",
                                old_order.to_dict(),
                            ).to_dict()
                        )
                    state.open_orders = []
                new_orders = target_weights_to_orders(
                    state, target, prices, self.config.risk_limits, self.cost_model
                )
                if new_orders:
                    events.append(
                        create_event(ts_str, "rebalance_due", "rebalance orders created").to_dict()
                    )
                for order in new_orders:
                    if (
                        orders_submitted_today
                        >= self.config.risk_limits.max_orders_per_day
                    ):
                        order.status = "rejected"
                        order.reason = "max_orders_per_day reached"
                        orders.append(order.to_dict())
                        events.append(
                            create_event(
                                ts_str,
                                "order_rejected",
                                order.reason,
                                "warning",
                                order.to_dict(),
                            ).to_dict()
                        )
                        continue
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
                    order.status = "submitted"
                    order.submitted_bar_index = bar_index
                    order.eligible_bar_index = (
                        bar_index + self.execution_policy.additional_latency_bars
                    )
                    order.remaining_quantity = order.quantity
                    state.open_orders.append(order)
                    orders_submitted_today += 1
                    events.append(
                        create_event(
                            ts_str,
                            "order_submitted",
                            "order accepted by simulated execution model",
                            details=order.to_dict(),
                        ).to_dict()
                    )

            retained_orders = []
            for order in sorted(
                state.open_orders,
                key=lambda item: (item.side == "buy", item.symbol, item.order_id),
            ):
                execution_order = _execution_state(order)
                fill_decision = execute_market_order_on_bar(
                    execution_order,
                    bar_index=bar_index,
                    open_price=prices.get(order.symbol),
                    volume=volumes.get(order.symbol),
                    policy=self.execution_policy,
                )
                if fill_decision is not None:
                    notional = fill_decision.quantity * fill_decision.price
                    cost = self.cost_model.trade_cost(notional)
                    if (
                        order.side == "buy"
                        and not self.config.risk_limits.allow_leverage
                        and state.cash - notional - cost
                        < state.equity * self.config.risk_limits.min_cash_pct - 1e-9
                    ):
                        # Discard the tentative execution mutation. Preserve
                        # prior partial fills, but do not report this rejected
                        # proposal as filled quantity.
                        execution_order = _execution_state(order)
                        execution_order.status = ExecutionStatus.REJECTED
                        execution_order.reason = (
                            "fill would breach cash reserve after costs and impact"
                        )
                        fill_decision = None
                _sync_order(order, execution_order)
                if fill_decision is not None:
                    price = fill_decision.price
                    notional = fill_decision.quantity * price
                    cost = self.cost_model.trade_cost(notional)
                    order.filled_at = ts_str
                    order.cost += cost
                    if order.side == "buy":
                        state.cash -= notional + cost
                        pos = state.positions.get(
                            order.symbol,
                            PaperPosition(order.symbol, 0.0, price, price),
                        )
                        prior_value = pos.quantity * pos.average_cost
                        pos.quantity += fill_decision.quantity
                        pos.average_cost = (prior_value + notional) / pos.quantity
                        pos.last_price = price
                        state.positions[order.symbol] = pos
                    else:
                        pos = state.positions[order.symbol]
                        pos.quantity -= fill_decision.quantity
                        state.cash += notional - cost
                        state.realized_pnl += (
                            (price - pos.average_cost) * fill_decision.quantity - cost
                        )
                        if pos.quantity <= 1e-9:
                            del state.positions[order.symbol]
                    paper_fill = PaperFill(
                        f"{order.order_id}:{order.fill_count}",
                        order.order_id,
                        ts_str,
                        order.symbol,
                        order.side,
                        fill_decision.quantity,
                        price,
                        cost,
                        fill_decision.participation_rate,
                        fill_decision.price_impact_bps,
                    )
                    state.fills.append(paper_fill)
                    fills.append(paper_fill.to_dict())
                    event_type = (
                        "order_filled"
                        if order.status == "filled"
                        else "order_partially_filled"
                    )
                    events.append(
                        create_event(
                            ts_str,
                            event_type,
                            event_type.replace("_", " "),
                            details=order.to_dict(),
                        ).to_dict()
                    )
                if execution_order.is_terminal:
                    orders.append(order.to_dict())
                    if fill_decision is None and order.status in {"rejected", "expired"}:
                        events.append(
                            create_event(
                                ts_str,
                                f"order_{order.status}",
                                order.reason,
                                "warning",
                                order.to_dict(),
                            ).to_dict()
                        )
                else:
                    retained_orders.append(order)
            state.open_orders = retained_orders
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
            if _daily_loss_breached() and not state.kill_switch_active:
                state.kill_switch_active = True
                state.status = "paused"
                events.append(
                    create_event(
                        ts_str,
                        "daily_loss_circuit_breaker",
                        "daily loss limit breached after fills; trading halted",
                        "critical",
                    ).to_dict()
                )
                continue
            if should_trigger_kill_switch(state, self.config.risk_limits):
                state.kill_switch_active = True
                state.status = "paused"
                events.append(
                    create_event(
                        ts_str, "kill_switch_triggered", "kill switch active", "critical"
                    ).to_dict()
                )
                continue
            # Decide targets from history through this bar; they become
            # actionable at the next bar's open.
            hist = data[data["timestamp"] <= ts]
            signals = model.generate(hist, self.config.strategy_params)
            todays = signals[signals["timestamp"] == ts] if not signals.empty else signals
            if not todays.empty:
                pending_target = {
                    str(r.symbol): float(r.target_weight) for r in todays.itertuples()
                }
                events.append(
                    create_event(
                        ts_str,
                        "signal_generated",
                        "target weights generated",
                        details=pending_target,
                    ).to_dict()
                )
        state.status = "stopped" if not state.kill_switch_active else "paused"
        for order in state.open_orders:
            execution_order = _execution_state(order)
            cancel_order(execution_order, "session ended before order completed")
            _sync_order(order, execution_order)
            orders.append(order.to_dict())
            events.append(
                create_event(
                    state.last_processed_timestamp,
                    "order_cancelled",
                    order.reason,
                    "warning",
                    order.to_dict(),
                ).to_dict()
            )
        state.open_orders = []
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

