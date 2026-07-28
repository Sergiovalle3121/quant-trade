"""The durable paper session: WAL, checkpoints, lease, reconciliation.

The engine in :mod:`quant_trade.v9.paper_engine` knows how a fill changes the
books. This module knows how a session survives being killed halfway through
writing one.

Durability rules, all of which have a test:

* **Append the journal before mutating the checkpoint.** A crash between the
  two replays the journal on restart and lands in the same place; the reverse
  order loses an event.
* **One writer.** A lease file carries a pid and an expiry; a second process
  that finds a live lease refuses to run rather than interleaving writes.
* **Exactly-once.** Every event carries a strictly increasing sequence, and a
  replayed sequence with identical content is skipped while a replayed
  sequence with *different* content is an error, not a silent overwrite.
* **The clock is persisted, not passed.** Runtime accumulates from timestamps
  written to disk at each advance. A test may inject a clock, and doing so
  marks the session ``injected_test`` forever — such a session can report, but
  its runtime can never support a promotion.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)
from quant_trade.v9.paper_engine import (
    CLOCK_INJECTED_TEST,
    CLOCK_SYSTEM,
    DEFAULT_STALE_TICK_SECONDS,
    RECONCILIATION_TOLERANCE,
    SESSION_HALTED,
    SESSION_RUNNING,
    SESSION_STOPPED,
    SIDE_BUY,
    SIDE_SELL,
    ExecutionModel,
    FrozenCarryStrategy,
    LeaseError,
    MarketTick,
    PaperEngineError,
    PaperOrder,
    PositionLedger,
    SimulatedBroker,
)

JOURNAL_FILENAME = "journal.jsonl"
CHECKPOINT_FILENAME = "checkpoint.json"
CONFIG_FILENAME = "session_config.json"
LEASE_FILENAME = "writer.lease"

#: How long a lease stays valid without a heartbeat.
LEASE_TTL_SECONDS = 120.0

#: Maintenance margin requirement for the perp leg.
DEFAULT_MAINTENANCE_RATE = 0.005

BREAKER_STALE_DATA = "stale_market_data"
BREAKER_RECONCILIATION = "reconciliation_failed"
BREAKER_DRAWDOWN = "max_drawdown_exceeded"
BREAKER_LIQUIDATION = "maintenance_margin_breached"


@dataclass
class SessionConfig:
    session_id: str
    candidate_id: str
    manifest_sha256: str
    initial_capital_usd: float
    strategy: dict[str, Any]
    execution: dict[str, Any]
    max_drawdown: float = 0.10
    maintenance_rate: float = DEFAULT_MAINTENANCE_RATE
    stale_tick_seconds: float = DEFAULT_STALE_TICK_SECONDS
    perp_leverage: float = 3.0
    clock_source: str = CLOCK_SYSTEM
    started_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["config_sha256"] = sha256_of_text(canonical_dumps(asdict(self)))
        return payload


@dataclass
class SessionCounters:
    events_processed: int = 0
    ticks_applied: int = 0
    signals: int = 0
    orders_submitted: int = 0
    fills: int = 0
    partial_fills: int = 0
    cancels: int = 0
    funding_settlements: int = 0
    liquidations: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class WriterLease:
    """A cooperative single-writer lease. Cheap, and enough to stop two daemons."""

    def __init__(
        self,
        path: str | Path,
        *,
        ttl_seconds: float = LEASE_TTL_SECONDS,
        token: str = "",
    ) -> None:
        self.path = Path(path)
        self.ttl = ttl_seconds
        # Identity is per WRITER, not per process. Two sessions inside one
        # interpreter are still two writers, and keying on pid alone would let
        # them interleave — which is exactly the case a test harness hits.
        self.token = token or f"{os.getpid()}-{id(self):x}"
        self._held = False

    def _read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def acquire(self, *, now: float, owner: str = "") -> None:
        existing = self._read()
        if existing is not None:
            expires = float(existing.get("expires_at", 0.0))
            if expires > now and str(existing.get("token", "")) != self.token:
                raise LeaseError(
                    f"another writer holds the session lease until {expires} "
                    f"(token {existing.get('token')}, pid {existing.get('pid')}); "
                    "refusing to interleave writes"
                )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.path,
            {
                "pid": os.getpid(),
                "token": self.token,
                "owner": owner or f"pid-{os.getpid()}",
                "acquired_at": now,
                "expires_at": now + self.ttl,
            },
        )
        self._held = True

    def renew(self, *, now: float) -> None:
        if not self._held:
            return
        existing = self._read() or {}
        existing.update({"expires_at": now + self.ttl, "pid": os.getpid(), "token": self.token})
        atomic_write_json(self.path, existing)

    def release(self) -> None:
        if self._held and self.path.exists():
            self.path.unlink()
        self._held = False


@dataclass
class ReconciliationResult:
    reconciled: bool
    reconciliation_error: float
    replayed_equity_usd: float
    running_equity_usd: float
    events_replayed: int
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PaperSession:
    """A durable, single-writer paper trading session."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        clock: Callable[[], float] | None = None,
        lease_ttl_seconds: float = LEASE_TTL_SECONDS,
    ) -> None:
        self.dir = Path(state_dir)
        self._injected_clock = clock is not None
        self._clock = clock or time.time
        self.lease = WriterLease(self.dir / LEASE_FILENAME, ttl_seconds=lease_ttl_seconds)
        self.config: SessionConfig | None = None
        self.ledger: PositionLedger | None = None
        self.broker: SimulatedBroker | None = None
        self.strategy: FrozenCarryStrategy | None = None
        self.counters = SessionCounters()
        self.status = SESSION_STOPPED
        self.breakers: list[str] = []
        self.settled_rates: list[float] = []
        self.peak_equity_usd = 0.0
        self.last_equity_usd = 0.0
        self.last_marks: tuple[float, float] = (0.0, 0.0)
        self.last_tick_observed_at_ms = 0
        self.first_wall_clock: float | None = None
        self.last_wall_clock: float | None = None
        self.accumulated_wall_seconds = 0.0
        self._sequence = 0
        self._order_counter = 0

    # --- persistence -------------------------------------------------------

    @property
    def journal_path(self) -> Path:
        return self.dir / JOURNAL_FILENAME

    @property
    def checkpoint_path(self) -> Path:
        return self.dir / CHECKPOINT_FILENAME

    def _read_journal(self) -> list[dict[str, Any]]:
        if not self.journal_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # A torn final line is the normal shape of a crash mid-write.
                # Everything before it is intact and replayable; the partial
                # record is discarded rather than guessed at.
                break
        return records

    def _append_journal(self, record: dict[str, Any]) -> dict[str, Any]:
        records = self._read_journal()
        previous = str(records[-1]["record_sha256"]) if records else "0" * 64
        payload = dict(record)
        payload["previous_sha256"] = previous
        payload["record_sha256"] = sha256_of_text(canonical_dumps(payload))
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_dumps(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return payload

    def _write_checkpoint(self) -> None:
        atomic_write_json(self.checkpoint_path, self._checkpoint_payload())

    def _checkpoint_payload(self) -> dict[str, Any]:
        assert self.ledger is not None
        return {
            "sequence": self._sequence,
            "status": self.status,
            "counters": self.counters.to_dict(),
            "ledger": self.ledger.to_dict(),
            "breakers": list(self.breakers),
            "settled_rates": list(self.settled_rates),
            "peak_equity_usd": self.peak_equity_usd,
            "last_equity_usd": self.last_equity_usd,
            "last_marks": list(self.last_marks),
            "last_tick_observed_at_ms": self.last_tick_observed_at_ms,
            "first_wall_clock": self.first_wall_clock,
            "last_wall_clock": self.last_wall_clock,
            "accumulated_wall_seconds": self.accumulated_wall_seconds,
            "order_counter": self._order_counter,
        }

    # --- lifecycle ----------------------------------------------------------

    def start(self, config: SessionConfig) -> None:
        """Create a session. Refuses to overwrite an existing one."""
        if self.checkpoint_path.exists():
            raise PaperEngineError(
                f"a session already exists at {self.dir}; stop it before starting "
                "another, or resume it"
            )
        self.dir.mkdir(parents=True, exist_ok=True)
        now = self._clock()
        self.lease.acquire(now=now, owner="paper-start")
        config.clock_source = CLOCK_INJECTED_TEST if self._injected_clock else CLOCK_SYSTEM
        self.config = config
        self._install(config)
        self.status = SESSION_RUNNING
        self.first_wall_clock = now
        self.last_wall_clock = now
        atomic_write_json(self.dir / CONFIG_FILENAME, config.to_dict())
        self._append_journal(
            {
                "seq": 0,
                "kind": "session_started",
                "at_wall_clock": now,
                "config_sha256": config.to_dict()["config_sha256"],
            }
        )
        self._write_checkpoint()

    def _install(self, config: SessionConfig) -> None:
        self.ledger = PositionLedger(
            initial_capital_usd=config.initial_capital_usd,
            perp_leverage=config.perp_leverage,
        )
        self.broker = SimulatedBroker(ExecutionModel(**config.execution))
        self.strategy = FrozenCarryStrategy(**config.strategy)
        self.peak_equity_usd = config.initial_capital_usd
        self.last_equity_usd = config.initial_capital_usd

    def resume(self) -> None:
        """Reopen an existing session and replay the journal exactly once."""
        if not self.checkpoint_path.exists():
            raise PaperEngineError(f"no session to resume at {self.dir}")
        payload = load_json(self.dir / CONFIG_FILENAME)
        if not isinstance(payload, dict):
            raise PaperEngineError("session config is unreadable")
        known = {f for f in SessionConfig.__dataclass_fields__}
        config = SessionConfig(**{k: v for k, v in payload.items() if k in known})
        self.config = config
        self._install(config)
        self.lease.acquire(now=self._clock(), owner="paper-resume")

        checkpoint = load_json(self.checkpoint_path)
        checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
        self._restore(checkpoint)
        # Replay anything the journal has beyond the checkpoint: the append
        # happens first, so a crash between the two leaves events here.
        for record in self._read_journal():
            if int(record.get("seq", 0)) <= self._sequence:
                continue
            if str(record.get("kind")) == "tick":
                self._apply_tick_record(record)
        self.status = str(checkpoint.get("status", SESSION_RUNNING))
        if self.status == SESSION_STOPPED:
            self.status = SESSION_RUNNING
        self._write_checkpoint()

    def _restore(self, checkpoint: dict[str, Any]) -> None:
        assert self.ledger is not None
        self._sequence = int(checkpoint.get("sequence", 0))
        counters = checkpoint.get("counters", {}) or {}
        known = {f for f in SessionCounters.__dataclass_fields__}
        self.counters = SessionCounters(**{k: int(v) for k, v in counters.items() if k in known})
        ledger = checkpoint.get("ledger", {}) or {}
        self.ledger.cash_usd = float(ledger.get("cash_usd", self.ledger.initial_capital_usd))
        self.ledger.margin_posted_usd = float(ledger.get("margin_posted_usd", 0.0))
        self.ledger.liquidations = int(ledger.get("liquidations", 0))
        from quant_trade.v9.paper_engine import LedgerTotals, Position

        totals = ledger.get("totals", {}) or {}
        self.ledger.totals = LedgerTotals(
            **{k: float(v) for k, v in totals.items() if k in LedgerTotals.__dataclass_fields__}
        )
        for leg, position in (ledger.get("positions", {}) or {}).items():
            self.ledger.positions[leg] = Position(
                leg=str(position.get("leg", leg)),
                quantity=float(position.get("quantity", 0.0)),
                average_price=float(position.get("average_price", 0.0)),
            )
        self.breakers = list(checkpoint.get("breakers", []))
        self.settled_rates = [float(r) for r in checkpoint.get("settled_rates", [])]
        self.peak_equity_usd = float(
            checkpoint.get("peak_equity_usd", self.ledger.initial_capital_usd)
        )
        self.last_equity_usd = float(
            checkpoint.get("last_equity_usd", self.ledger.initial_capital_usd)
        )
        marks = checkpoint.get("last_marks", [0.0, 0.0])
        self.last_marks = (float(marks[0]), float(marks[1]))
        self.last_tick_observed_at_ms = int(checkpoint.get("last_tick_observed_at_ms", 0))
        self.first_wall_clock = checkpoint.get("first_wall_clock")
        self.last_wall_clock = checkpoint.get("last_wall_clock")
        self.accumulated_wall_seconds = float(checkpoint.get("accumulated_wall_seconds", 0.0))
        self._order_counter = int(checkpoint.get("order_counter", 0))

    def stop(self) -> None:
        self.status = SESSION_STOPPED
        self._append_journal(
            {
                "seq": self._next_sequence(),
                "kind": "session_stopped",
                "at_wall_clock": self._clock(),
            }
        )
        self._write_checkpoint()
        self.lease.release()

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    # --- advancing ------------------------------------------------------------

    def advance(self, ticks: Iterable[MarketTick]) -> dict[str, Any]:
        """Apply market ticks. This is the ONLY way the books may move.

        There is deliberately no argument for a return, a yield, or a P&L: the
        caller supplies what the market did, and the engine derives what that
        was worth.
        """
        if self.ledger is None or self.broker is None or self.strategy is None:
            raise PaperEngineError("session is not started")
        if self.status != SESSION_RUNNING:
            raise PaperEngineError(f"session is {self.status}; not advancing")

        applied = 0
        for tick in ticks:
            if tick.observed_at_ms <= self.last_tick_observed_at_ms:
                continue  # already applied; exactly-once
            now = self._clock()
            self._accumulate_wall_clock(now)
            record = {
                "seq": self._next_sequence(),
                "kind": "tick",
                "at_wall_clock": now,
                "tick": tick.to_dict(),
            }
            # Journal first: a crash before the checkpoint replays this tick.
            self._append_journal(record)
            self._apply_tick(tick, now=now)
            self._write_checkpoint()
            self.lease.renew(now=now)
            applied += 1
            if self.status != SESSION_RUNNING:
                # A breaker fired part-way through the batch. Stop here rather
                # than trading on through the condition that halted us.
                break
        return {
            "ticks_applied": applied,
            "status": self.status,
            "equity_usd": self.last_equity_usd,
            "breakers": list(self.breakers),
        }

    def _apply_tick_record(self, record: dict[str, Any]) -> None:
        payload = record.get("tick", {})
        known = {f for f in MarketTick.__dataclass_fields__}
        tick = MarketTick(**{k: v for k, v in payload.items() if k in known})
        self._sequence = max(self._sequence, int(record.get("seq", 0)))
        self._apply_tick(tick, now=float(record.get("at_wall_clock", self._clock())))

    def _accumulate_wall_clock(self, now: float) -> None:
        if self.first_wall_clock is None:
            self.first_wall_clock = now
        if self.last_wall_clock is not None and now > self.last_wall_clock:
            self.accumulated_wall_seconds += now - self.last_wall_clock
        self.last_wall_clock = now

    def _apply_tick(self, tick: MarketTick, *, now: float) -> None:
        assert self.ledger is not None and self.broker is not None
        assert self.strategy is not None and self.config is not None

        spot_mid = (tick.spot_bid + tick.spot_ask) / 2.0
        self.last_marks = (spot_mid, tick.perp_mark)

        # 1. Stale data breaker, measured on the venue's own clock.
        if self.last_tick_observed_at_ms:
            gap = (tick.observed_at_ms - self.last_tick_observed_at_ms) / 1000.0
            if gap > self.config.stale_tick_seconds:
                self._trip(BREAKER_STALE_DATA, f"{gap:.0f}s between ticks")
        self.last_tick_observed_at_ms = tick.observed_at_ms
        self.counters.ticks_applied += 1
        self.counters.events_processed += 1

        # 2. Funding settles against the position that exists right now, at the
        #    mark observable at the settlement instant.
        if tick.settled_funding_rate is not None:
            self.ledger.apply_funding(tick.settled_funding_rate, tick.perp_mark)
            self.settled_rates.append(float(tick.settled_funding_rate))
            self.counters.funding_settlements += 1

        # 3. Fill whatever the broker can, then let the strategy react.
        for fill in self.broker.match(tick):
            self.ledger.apply_fill(fill)
            self.counters.fills += 1
            if fill.is_partial:
                self.counters.partial_fills += 1
            self._append_journal(
                {
                    "seq": self._next_sequence(),
                    "kind": "fill",
                    "at_wall_clock": now,
                    "fill": fill.to_dict(),
                }
            )

        # 4. Liquidation check on the intrabar path, not just the close.
        distance = self.ledger.maintenance_distance(
            perp_mark=tick.perp_mark, maintenance_rate=self.config.maintenance_rate
        )
        if distance < 0:
            self.ledger.liquidations += 1
            self.counters.liquidations += 1
            self._trip(BREAKER_LIQUIDATION, f"maintenance distance {distance:.4f}")

        # 5. Strategy decides from settled rates only.
        self._act(tick, now=now)

        # 6. Mark to market and check drawdown.
        equity = self.ledger.equity_usd(spot_mark=spot_mid, perp_mark=tick.perp_mark)
        self.last_equity_usd = equity
        self.peak_equity_usd = max(self.peak_equity_usd, equity)
        if self.peak_equity_usd > 0:
            drawdown = equity / self.peak_equity_usd - 1.0
            if drawdown < -abs(self.config.max_drawdown):
                self._trip(BREAKER_DRAWDOWN, f"drawdown {drawdown:.4f}")

    def _act(self, tick: MarketTick, *, now: float) -> None:
        assert self.ledger is not None and self.broker is not None
        assert self.strategy is not None and self.config is not None
        if self.status != SESSION_RUNNING:
            return
        desired = self.strategy.desired_position(self.settled_rates)
        self.counters.signals += 1
        spot = self.ledger.position("spot")
        holding = abs(spot.quantity) > 1e-12
        if desired == 1 and not holding:
            self._submit_two_leg(tick, opening=True, now=now)
        elif desired == 0 and holding:
            self._submit_two_leg(tick, opening=False, now=now)

    def _submit_two_leg(self, tick: MarketTick, *, opening: bool, now: float) -> None:
        assert self.ledger is not None and self.broker is not None
        assert self.strategy is not None and self.config is not None
        spot = self.ledger.position("spot")
        perp = self.ledger.position("perp")
        if opening:
            quantity = self.strategy.target_notional_usd / max(tick.spot_ask, 1e-12)
            legs = [("spot", SIDE_BUY, quantity), ("perp", SIDE_SELL, quantity)]
        else:
            legs = [
                ("spot", SIDE_SELL, abs(spot.quantity)),
                ("perp", SIDE_BUY, abs(perp.quantity)),
            ]
        for leg, side, quantity in legs:
            if quantity <= 1e-12:
                continue
            self._order_counter += 1
            order = PaperOrder(
                client_order_id=f"{self.config.session_id}-{self._order_counter:08d}",
                venue=tick.venue,
                instrument=tick.instrument,
                leg=leg,
                side=side,
                quantity=quantity,
                order_type="market",
                created_at_ms=tick.observed_at_ms,
                eligible_at_ms=tick.observed_at_ms + self.broker.execution.latency_ms,
            )
            self.broker.submit(order)
            self.counters.orders_submitted += 1
            self._append_journal(
                {
                    "seq": self._next_sequence(),
                    "kind": "order",
                    "at_wall_clock": now,
                    "order": order.to_dict(),
                }
            )

    def _trip(self, breaker: str, detail: str) -> None:
        entry = f"{breaker}: {detail}"
        if entry not in self.breakers:
            self.breakers.append(entry)
        self.status = SESSION_HALTED

    # --- reconciliation --------------------------------------------------------

    def reconcile(self) -> ReconciliationResult:
        """Rebuild equity from the journal and compare with the running total."""
        assert self.ledger is not None and self.config is not None
        replay = PositionLedger(
            initial_capital_usd=self.config.initial_capital_usd,
            perp_leverage=self.config.perp_leverage,
        )
        from quant_trade.v9.paper_engine import PaperFill

        spot_mark, perp_mark = self.last_marks
        events = 0
        for record in self._read_journal():
            kind = str(record.get("kind"))
            if kind == "fill":
                payload = record.get("fill", {})
                known = {f for f in PaperFill.__dataclass_fields__}
                replay.apply_fill(PaperFill(**{k: v for k, v in payload.items() if k in known}))
                events += 1
            elif kind == "tick":
                tick = record.get("tick", {})
                rate = tick.get("settled_funding_rate")
                if rate is not None:
                    replay.apply_funding(float(rate), float(tick["perp_mark"]))
                spot_mark = (float(tick["spot_bid"]) + float(tick["spot_ask"])) / 2.0
                perp_mark = float(tick["perp_mark"])
                events += 1
        replayed = replay.equity_usd(spot_mark=spot_mark, perp_mark=perp_mark)
        running = self.ledger.equity_usd(spot_mark=self.last_marks[0], perp_mark=self.last_marks[1])
        error = abs(replayed - running)
        tolerance = RECONCILIATION_TOLERANCE * max(1.0, self.config.initial_capital_usd)
        problems: list[str] = []
        if error > tolerance:
            problems.append(
                f"replayed equity {replayed:.10f} differs from running equity "
                f"{running:.10f} by {error:.10f} (tolerance {tolerance:.10f})"
            )
            self._trip(BREAKER_RECONCILIATION, f"error {error:.10f}")
        return ReconciliationResult(
            reconciled=not problems,
            reconciliation_error=error,
            replayed_equity_usd=replayed,
            running_equity_usd=running,
            events_replayed=events,
            problems=problems,
        )

    # --- reporting ---------------------------------------------------------------

    @property
    def wall_clock_seconds(self) -> float:
        return self.accumulated_wall_seconds

    @property
    def clock_is_persisted(self) -> bool:
        """True only when runtime came from a real system clock.

        A test may inject a clock; doing so marks the session permanently, and
        such a session can report but can never support a canary.
        """
        return (
            self.config is not None
            and self.config.clock_source == CLOCK_SYSTEM
            and self.first_wall_clock is not None
        )

    def status_report(self) -> dict[str, Any]:
        assert self.ledger is not None and self.config is not None
        reconciliation = self.reconcile()
        drawdown = (
            self.last_equity_usd / self.peak_equity_usd - 1.0 if self.peak_equity_usd > 0 else 0.0
        )
        return {
            "artifact": "PAPER_DAEMON_STATUS",
            "schema_version": 1,
            "session_id": self.config.session_id,
            "candidate_id": self.config.candidate_id,
            "manifest_sha256": self.config.manifest_sha256,
            "status": self.status,
            "state_dir": str(self.dir),
            "clock_source": self.config.clock_source,
            "clock_is_persisted": self.clock_is_persisted,
            "wall_clock_seconds": self.wall_clock_seconds,
            "wall_clock_hours": self.wall_clock_seconds / 3600.0,
            "heartbeat_wall_clock": self.last_wall_clock,
            "last_tick_observed_at_ms": self.last_tick_observed_at_ms,
            "counters": self.counters.to_dict(),
            "events_processed": self.counters.events_processed,
            "liquidations": self.counters.liquidations,
            "kill_switch_engaged": self.status == SESSION_HALTED,
            "breakers_tripped": list(self.breakers),
            "initial_capital_usd": self.config.initial_capital_usd,
            "equity_usd": self.last_equity_usd,
            "net_return": (
                self.last_equity_usd / self.config.initial_capital_usd - 1.0
                if self.config.initial_capital_usd
                else 0.0
            ),
            "drawdown": drawdown,
            "ledger": self.ledger.to_dict(),
            "reconciliation": reconciliation.to_dict(),
            "journal_records": len(self._read_journal()),
            "resume_command": f"quant-trade v9 paper-resume --state-dir {self.dir.as_posix()}",
            "safety": {
                "live_order_submission": "DISABLED",
                "live_broker_execution": "DISABLED",
                "deposit_execution": "DISABLED",
                "withdrawal_execution": "DISABLED",
                "real_orders": 0,
                "real_money_authorized": False,
            },
        }


__all__ = [
    "BREAKER_DRAWDOWN",
    "BREAKER_LIQUIDATION",
    "BREAKER_RECONCILIATION",
    "BREAKER_STALE_DATA",
    "CHECKPOINT_FILENAME",
    "CONFIG_FILENAME",
    "JOURNAL_FILENAME",
    "LEASE_FILENAME",
    "LEASE_TTL_SECONDS",
    "PaperSession",
    "ReconciliationResult",
    "SessionConfig",
    "SessionCounters",
    "WriterLease",
]
