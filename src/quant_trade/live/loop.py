"""Cycle-based live paper-trading loop (paper-only).

This is the 24/7 runtime shape the batch replay cannot provide: each cycle
fetches the latest bars from a market-data provider, executes the target
decided on the PREVIOUS bar at the NEWEST bar's open, then decides a new
target from all bars through now. The pending target is persisted with the
session state, so the next-open causality convention survives process
restarts, crashes, and redeploys.

Safety posture:
- paper-only: no broker connectivity lives here; fills are simulated at the
  newest bar's open with the configured cost model.
- the kill switch is re-checked at the START of every cycle and fails closed
  (storage errors mean HALT).
- the daily-loss circuit breaker and max-orders-per-day caps are enforced
  every cycle; a triggered breaker persists as a paused session that an
  operator must clear explicitly.
- a heartbeat is written every cycle (even no-op cycles) so a dead-man
  monitor can alarm on staleness.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from quant_trade.backtest.costs import CostModel
from quant_trade.cloud.exceptions import SafetyGateError, StorageError
from quant_trade.cloud.monitoring import emit_metric
from quant_trade.cloud.storage import backend_for_uri
from quant_trade.data.providers.base import MarketDataProvider, get_data_provider
from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.paper.models import PaperFill, PaperOrder, PaperRiskLimits, PaperSessionState
from quant_trade.paper.rebalancer import target_weights_to_orders
from quant_trade.paper.risk import validate_order
from quant_trade.paper.state import load_state, save_state
from quant_trade.research.strategy_registry import get_research_signal_model

_INTERVAL_TO_TIMEDELTA = {
    "1d": timedelta(days=1),
    "4h": timedelta(hours=4),
    "1h": timedelta(hours=1),
    "30m": timedelta(minutes=30),
    "15m": timedelta(minutes=15),
    "5m": timedelta(minutes=5),
    "1m": timedelta(minutes=1),
}


@dataclass
class LoopConfig:
    session_name: str
    strategy: str
    strategy_params: dict[str, Any]
    symbols: list[str]
    initial_cash: float
    costs: dict[str, float]
    risk_limits: PaperRiskLimits
    provider: str = "synthetic"
    interval: str = "1d"
    history_bars: int = 400
    state_dir: str = "state/paper_loop"
    kill_switch_uri: str | None = None
    heartbeat_uri: str | None = None
    # When true, every heartbeat also emits the heartbeat_age_seconds EMF
    # metric (namespace QuantTrade/CloudPaper, dimension job=heartbeat) that
    # the provisioned CloudWatch dead-man alarm watches: a dead loop stops
    # emitting and the alarm breaches on missing data. Requires the process
    # stdout to be shipped to CloudWatch Logs (the awslogs docker driver).
    emit_cloudwatch_metrics: bool = False

    @classmethod
    def from_yaml(cls, path: Path) -> LoopConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("mode") != "paper_loop":
            raise ValueError("loop config mode must be paper_loop")
        if raw.get("broker") is not None:
            raise ValueError("broker connectivity is not allowed in the paper loop")
        limits = PaperRiskLimits(**(raw.get("risk_limits") or {}))
        if limits.allow_leverage:
            raise ValueError("leverage is disabled in the paper loop")
        if not limits.kill_switch_enabled:
            raise ValueError("kill switch must be enabled")
        return cls(
            session_name=str(raw["session_name"]),
            strategy=str(raw["strategy"]),
            strategy_params=dict(raw.get("strategy_params", {})),
            symbols=[str(s).upper() for s in raw.get("universe", {}).get("symbols", [])],
            initial_cash=float(raw.get("initial_cash", 100_000.0)),
            costs=dict(raw.get("costs", {})),
            risk_limits=limits,
            provider=str(raw.get("provider", {}).get("name", "synthetic")),
            interval=str(raw.get("provider", {}).get("interval", "1d")),
            history_bars=int(raw.get("provider", {}).get("history_bars", 400)),
            state_dir=str(raw.get("state_dir", "state/paper_loop")),
            kill_switch_uri=raw.get("kill_switch_uri"),
            heartbeat_uri=raw.get("heartbeat_uri"),
            emit_cloudwatch_metrics=bool(raw.get("emit_cloudwatch_metrics", False)),
        )


@dataclass
class LoopState:
    session: PaperSessionState
    pending_target: dict[str, float] | None = None
    pending_decided_at: str = ""
    day_key: str = ""
    day_start_equity: float = 0.0
    orders_filled_today: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


class PaperLoopRunner:
    """Paper-only live loop. Inject ``provider`` and ``now_fn`` for tests."""

    def __init__(
        self,
        config: LoopConfig,
        provider: MarketDataProvider | None = None,
        now_fn: Any = None,
    ) -> None:
        self.config = config
        self.cost_model = CostModel(**config.costs)
        self._provider = provider or get_data_provider(config.provider)
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._state_root = Path(config.state_dir) / config.session_name

    # ---------------------------------------------------------------- state

    @property
    def session_state_path(self) -> Path:
        return self._state_root / "latest_state.json"

    @property
    def loop_state_path(self) -> Path:
        return self._state_root / "loop_state.json"

    def _load_state(self) -> LoopState:
        if self.session_state_path.exists():
            session = load_state(self.session_state_path)
        else:
            session = PaperSessionState(
                cash=self.config.initial_cash,
                equity=self.config.initial_cash,
                high_water_mark=self.config.initial_cash,
                status="running",
            )
        extra: dict[str, Any] = {}
        if self.loop_state_path.exists():
            extra = json.loads(self.loop_state_path.read_text(encoding="utf-8"))
        return LoopState(
            session=session,
            pending_target=extra.get("pending_target"),
            pending_decided_at=str(extra.get("pending_decided_at", "")),
            day_key=str(extra.get("day_key", "")),
            day_start_equity=float(extra.get("day_start_equity", session.equity)),
            orders_filled_today=int(extra.get("orders_filled_today", 0)),
        )

    def _save_state(self, state: LoopState) -> None:
        save_state(self.session_state_path, state.session)
        self.loop_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.loop_state_path.write_text(
            json.dumps(
                {
                    "pending_target": state.pending_target,
                    "pending_decided_at": state.pending_decided_at,
                    "day_key": state.day_key,
                    "day_start_equity": state.day_start_equity,
                    "orders_filled_today": state.orders_filled_today,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    # -------------------------------------------------------------- history

    def _append_jsonl(self, name: str, rows: list[dict[str, Any]]) -> None:
        """Append-only per-session history; consumed by `paper export-session`."""
        if not rows:
            return
        path = self._state_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    def _snapshot_row(self, state: LoopState, ts_str: str) -> dict[str, Any]:
        session = state.session
        gross = sum(abs(p.quantity * p.last_price) for p in session.positions.values())
        return {
            "timestamp": ts_str,
            "cash": session.cash,
            "equity": session.equity,
            "gross_exposure": (gross / session.equity) if session.equity else 0.0,
            "realized_pnl": session.realized_pnl,
            "unrealized_pnl": session.unrealized_pnl,
            "drawdown": session.max_drawdown,
        }

    def _persist_history(
        self, state: LoopState, executed: list[PaperOrder], ts_str: str
    ) -> None:
        self._append_jsonl("snapshots.jsonl", [self._snapshot_row(state, ts_str)])
        self._append_jsonl("orders.jsonl", [o.to_dict() for o in executed])
        self._append_jsonl("events.jsonl", state.events)
        state.events = []

    # --------------------------------------------------------------- safety

    def _kill_switch_active(self) -> tuple[bool, str]:
        """Fail closed: unreadable kill-switch storage means HALT."""
        uri = self.config.kill_switch_uri
        if not uri:
            return False, ""
        try:
            backend = backend_for_uri(uri)
            if not backend.exists(uri):
                return False, ""
            payload = backend.read_json(uri)
            return bool(payload.get("active", False)), str(payload.get("reason", ""))
        except (StorageError, OSError, json.JSONDecodeError) as exc:
            return True, f"kill-switch storage unreadable (failing closed): {exc}"

    def _write_heartbeat(self, state: LoopState, cycle_summary: dict[str, Any]) -> None:
        uri = self.config.heartbeat_uri or str(self._state_root / "heartbeat.json")
        payload = {
            "session_name": self.config.session_name,
            "last_update_utc": self._now_fn().isoformat(),
            "status": state.session.status,
            "kill_switch_active": state.session.kill_switch_active,
            "equity": state.session.equity,
            "last_processed_timestamp": state.session.last_processed_timestamp,
            "mode": "paper_loop",
            "summary": cycle_summary,
        }
        # A heartbeat write failure must not kill the loop; staleness is
        # exactly what the dead-man alarm exists to catch.
        import contextlib

        with contextlib.suppress(StorageError):
            backend_for_uri(uri).write_json(uri, payload)
        if self.config.emit_cloudwatch_metrics:
            # Value 0 = "alive right now"; the dead-man alarm fires on the
            # metric going missing, not on the value.
            emit_metric(
                "heartbeat_age_seconds",
                0.0,
                unit="Seconds",
                dimensions={"job": "heartbeat"},
                emf=True,
            )

    # ---------------------------------------------------------------- cycle

    def _fetch_panel(self) -> pd.DataFrame:
        now = self._now_fn()
        span = _INTERVAL_TO_TIMEDELTA[self.config.interval] * (self.config.history_bars + 5)
        request = HistoricalDataRequest(
            provider=self.config.provider,
            symbols=self.config.symbols,
            start=(now - span).date(),
            end=max((now + timedelta(days=1)).date(), (now - span).date() + timedelta(days=2)),
            interval=self.config.interval,
        )
        return self._provider.fetch_ohlcv(request)

    def _daily_loss_breached(self, state: LoopState) -> bool:
        if state.day_start_equity <= 0:
            return False
        loss = 1 - state.session.equity / state.day_start_equity
        return loss > self.config.risk_limits.max_daily_loss_pct

    def _halt(self, state: LoopState, reason: str, ts_str: str) -> None:
        state.session.kill_switch_active = True
        state.session.status = "paused"
        state.events.append(
            {"timestamp": ts_str, "event_type": "halted", "message": reason, "severity": "critical"}
        )

    def _execute_target(
        self, state: LoopState, target: dict[str, float], prices: dict[str, float], ts_str: str
    ) -> list[PaperOrder]:
        session = state.session
        orders = target_weights_to_orders(
            session, target, prices, self.config.risk_limits, self.cost_model
        )
        executed: list[PaperOrder] = []
        for order in orders:
            if state.orders_filled_today >= self.config.risk_limits.max_orders_per_day:
                order.status = "rejected"
                order.reason = "max_orders_per_day reached"
                executed.append(order)
                continue
            ok, reason = validate_order(order, session, self.config.risk_limits, prices)
            if not ok:
                order.status = "rejected"
                order.reason = reason
                executed.append(order)
                continue
            price = prices[order.symbol]
            notional = order.quantity * price
            cost = self.cost_model.trade_cost(notional)
            order.status = "filled"
            order.filled_at = ts_str
            order.fill_price = price
            order.cost = cost
            if order.side == "buy":
                session.cash -= notional + cost
                pos = session.positions.get(order.symbol)
                if pos is None:
                    from quant_trade.paper.models import PaperPosition

                    pos = PaperPosition(order.symbol, 0.0, price, price)
                prior_value = pos.quantity * pos.average_cost
                pos.quantity += order.quantity
                pos.average_cost = (prior_value + notional) / pos.quantity
                pos.last_price = price
                session.positions[order.symbol] = pos
            else:
                pos = session.positions[order.symbol]
                pos.quantity -= order.quantity
                session.cash += notional - cost
                session.realized_pnl += (price - pos.average_cost) * order.quantity - cost
                if pos.quantity <= 1e-9:
                    del session.positions[order.symbol]
            session.fills.append(
                PaperFill(
                    str(uuid.uuid4()),
                    order.order_id,
                    ts_str,
                    order.symbol,
                    order.side,
                    order.quantity,
                    price,
                    cost,
                )
            )
            state.orders_filled_today += 1
            executed.append(order)
        return executed

    def run_cycle(self) -> dict[str, Any]:
        """One idempotent cycle; safe to call again with no new bar."""
        state = self._load_state()
        summary: dict[str, Any] = {"action": "noop", "orders": 0}
        killed, reason = self._kill_switch_active()
        if killed:
            last_ts = state.session.last_processed_timestamp
            self._halt(state, f"kill switch active: {reason}", last_ts)
            self._save_state(state)
            self._persist_history(state, [], last_ts)
            self._write_heartbeat(state, {"action": "halted", "reason": reason})
            raise SafetyGateError(f"kill switch active: {reason}")
        if state.session.kill_switch_active or state.session.status == "paused":
            self._write_heartbeat(state, {"action": "paused"})
            return {"action": "paused", "orders": 0}

        panel = self._fetch_panel()
        panel = panel[panel["symbol"].isin(self.config.symbols)].sort_values("timestamp")
        if panel.empty:
            self._write_heartbeat(state, summary)
            return summary
        newest_ts = panel["timestamp"].max()
        newest_str = str(newest_ts)
        last_processed = state.session.last_processed_timestamp

        if last_processed and newest_str <= last_processed:
            # No new bar since the last cycle: heartbeat only.
            self._write_heartbeat(state, summary)
            return summary

        newest_bar = panel[panel["timestamp"] == newest_ts]
        prices = {str(r.symbol): float(r.open) for r in newest_bar.itertuples()}
        session = state.session
        for sym, pos in session.positions.items():
            if sym in prices:
                pos.last_price = prices[sym]
        session.equity = session.cash + sum(
            p.quantity * p.last_price for p in session.positions.values()
        )
        session.high_water_mark = max(session.high_water_mark, session.equity)
        session.max_drawdown = max(
            session.max_drawdown, 1 - session.equity / max(session.high_water_mark, 1e-9)
        )
        bar_day = newest_str[:10]
        if bar_day != state.day_key:
            state.day_key = bar_day
            state.day_start_equity = session.equity
            state.orders_filled_today = 0
        if self._daily_loss_breached(state):
            self._halt(state, "daily loss limit breached", newest_str)
            self._save_state(state)
            self._persist_history(state, [], newest_str)
            self._write_heartbeat(state, {"action": "halted", "reason": "daily_loss"})
            return {"action": "halted", "orders": 0}
        if session.max_drawdown >= self.config.risk_limits.max_total_drawdown_pct:
            self._halt(state, "total drawdown limit breached", newest_str)
            self._save_state(state)
            self._persist_history(state, [], newest_str)
            self._write_heartbeat(state, {"action": "halted", "reason": "max_drawdown"})
            return {"action": "halted", "orders": 0}

        executed: list[PaperOrder] = []
        # 1) execute the target decided on the previous bar at this bar's open
        if state.pending_target is not None and state.pending_decided_at < newest_str:
            executed = self._execute_target(state, state.pending_target, prices, newest_str)
            state.pending_target = None
            state.pending_decided_at = ""
            session.equity = session.cash + sum(
                p.quantity * p.last_price for p in session.positions.values()
            )
            if self._daily_loss_breached(state):
                self._halt(state, "daily loss limit breached after fills", newest_str)

        # 2) decide the next target from bars through the newest one
        if not session.kill_switch_active:
            model = get_research_signal_model(self.config.strategy)
            signals = model.generate(panel, self.config.strategy_params)
            todays = (
                signals[signals["timestamp"] == newest_ts] if not signals.empty else signals
            )
            if not todays.empty:
                state.pending_target = {
                    str(r.symbol): float(r.target_weight) for r in todays.itertuples()
                }
                state.pending_decided_at = newest_str

        session.last_processed_timestamp = newest_str
        session.unrealized_pnl = sum(
            (p.last_price - p.average_cost) * p.quantity for p in session.positions.values()
        )
        self._save_state(state)
        self._persist_history(state, executed, newest_str)
        summary = {
            "action": "traded" if executed else "marked",
            "orders": len(executed),
            "filled": sum(1 for o in executed if o.status == "filled"),
            "rejected": sum(1 for o in executed if o.status == "rejected"),
            "equity": session.equity,
            "bar": newest_str,
        }
        self._write_heartbeat(state, summary)
        return summary

    def run_forever(
        self, interval_seconds: float = 3600.0, max_cycles: int | None = None
    ) -> list[dict[str, Any]]:
        """Supervised loop; ``max_cycles`` bounds it for tests and dry runs."""
        results = []
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            results.append(self.run_cycle())
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                time.sleep(interval_seconds)
        return results


def bars_elapsed_today(now: datetime, interval: str) -> int:
    """Bars completed since UTC midnight; scheduling helper for cron setups."""
    delta = now - datetime.combine(date(now.year, now.month, now.day), datetime.min.time(), UTC)
    return int(delta / _INTERVAL_TO_TIMEDELTA[interval])
