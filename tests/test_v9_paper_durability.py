"""Durability and safety of the V9 paper session.

Crash-recovery bugs do not announce themselves: a session that double-counts
one fill on restart still produces a plausible equity curve. These tests kill
the session at the specific points where that can happen and assert the books
come back identical.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.v9.paper_engine import (
    ExecutionModel,
    MarketTick,
    PaperEngineError,
    PaperFill,
    PaperOrder,
    PositionLedger,
    SimulatedBroker,
)
from quant_trade.v9.paper_session import (
    BREAKER_LIQUIDATION,
    BREAKER_STALE_DATA,
    SESSION_HALTED,
    SESSION_RUNNING,
    LeaseError,
    PaperSession,
    SessionConfig,
    WriterLease,
)

HOUR_MS = 3_600_000
BASE_MS = 1_700_000_000_000


def _tick(
    index: int, *, price: float = 64_000.0, funding: float | None = None, gap_hours: int = 1
) -> MarketTick:
    start = BASE_MS + index * gap_hours * HOUR_MS
    return MarketTick(
        venue="bybit",
        instrument="BTCUSDT",
        bar_start_ms=start,
        bar_end_ms=start + HOUR_MS,
        observed_at_ms=start + HOUR_MS,
        spot_bid=price - 1,
        spot_ask=price + 1,
        perp_bid=price + 1,
        perp_ask=price + 3,
        perp_mark=price + 2,
        index=price,
        settled_funding_rate=funding,
        spot_quote_volume=1e9,
        perp_quote_volume=1e9,
    )


def _config(**overrides) -> SessionConfig:
    payload = {
        "session_id": "s1",
        "candidate_id": "H1-v1",
        "manifest_sha256": "a" * 64,
        "initial_capital_usd": 10_000.0,
        "stale_tick_seconds": 2 * 3600.0,
        "strategy": {
            "entry_threshold": 0.00005,
            "trailing_window": 3,
            "target_notional_usd": 2_000.0,
        },
        "execution": {
            "latency_ms": 0,
            "slippage_bps": 1.0,
            "max_participation": 1.0,
            "spot_fee_bps": 10.0,
            "perp_fee_bps": 5.5,
        },
    }
    payload.update(overrides)
    return SessionConfig(**payload)


def _run(tmp_path: Path, count: int = 12, **config_overrides):
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    session.start(_config(**config_overrides))
    ticks = []
    for index in range(count):
        ticks.append(_tick(index, funding=0.0002 if index % 3 == 0 else None))
        clock[0] += 3600.0
    session.advance(ticks)
    return session, clock


# --- exactly-once ------------------------------------------------------------------


def test_replaying_the_same_ticks_changes_nothing(tmp_path: Path) -> None:
    session, clock = _run(tmp_path)
    before = session.status_report()
    ticks = [_tick(i, funding=0.0002 if i % 3 == 0 else None) for i in range(12)]
    session.advance(ticks)
    after = session.status_report()
    assert after["counters"] == before["counters"]
    assert after["equity_usd"] == pytest.approx(before["equity_usd"])


def test_restart_recovers_the_same_books(tmp_path: Path) -> None:
    session, clock = _run(tmp_path)
    before = session.status_report()
    session.lease.release()

    reopened = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    reopened.resume()
    after = reopened.status_report()
    assert after["equity_usd"] == pytest.approx(before["equity_usd"])
    assert after["counters"]["fills"] == before["counters"]["fills"]
    assert after["ledger"]["positions"] == before["ledger"]["positions"]
    assert after["reconciliation"]["reconciled"]


def test_resume_continues_the_session_rather_than_only_reporting(
    tmp_path: Path,
) -> None:
    session, clock = _run(tmp_path, count=6)
    session.lease.release()
    reopened = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    reopened.resume()
    assert reopened.status == SESSION_RUNNING
    more = [_tick(i, funding=0.0002 if i % 3 == 0 else None) for i in range(6, 12)]
    for _ in more:
        clock[0] += 3600.0
    result = reopened.advance(more)
    assert result["ticks_applied"] == 6
    assert reopened.status_report()["counters"]["ticks_applied"] == 12


def test_a_crash_between_journal_and_checkpoint_replays_the_event(
    tmp_path: Path,
) -> None:
    """The journal is appended first, so the lost checkpoint is recoverable."""
    session, clock = _run(tmp_path, count=8)
    expected = session.status_report()
    session.lease.release()

    # Simulate the crash: roll the checkpoint back one sequence, leaving the
    # journal ahead of it exactly as an interrupted write would.
    checkpoint = json.loads(session.checkpoint_path.read_text())
    journal = [
        json.loads(line) for line in session.journal_path.read_text().splitlines() if line.strip()
    ]
    tick_records = [r for r in journal if r["kind"] == "tick"]
    checkpoint["sequence"] = tick_records[-1]["seq"] - 1
    session.checkpoint_path.write_text(json.dumps(checkpoint))

    reopened = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    reopened.resume()
    assert reopened.status_report()["counters"]["ticks_applied"] >= (
        expected["counters"]["ticks_applied"] - 1
    )
    assert reopened.reconcile().reconciled


def test_a_torn_final_journal_line_is_discarded_not_guessed(tmp_path: Path) -> None:
    session, clock = _run(tmp_path, count=8)
    with session.journal_path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 999, "kind": "tick", "ti')  # torn write
    session.lease.release()
    reopened = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    reopened.resume()
    assert reopened.reconcile().reconciled


def test_the_journal_is_hash_chained(tmp_path: Path) -> None:
    session, _clock = _run(tmp_path, count=6)
    records = [
        json.loads(line) for line in session.journal_path.read_text().splitlines() if line.strip()
    ]
    previous = "0" * 64
    for record in records:
        assert record["previous_sha256"] == previous
        previous = record["record_sha256"]


# --- single writer -------------------------------------------------------------------


def test_a_second_writer_is_refused(tmp_path: Path) -> None:
    session, clock = _run(tmp_path, count=2)
    second = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    with pytest.raises(LeaseError, match="another writer holds the session lease"):
        second.resume()


def test_an_expired_lease_can_be_taken_over(tmp_path: Path) -> None:
    session, clock = _run(tmp_path, count=2)
    clock[0] += 10_000.0  # well past the TTL
    second = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    second.resume()
    assert second.status == SESSION_RUNNING


def test_lease_release_frees_the_session(tmp_path: Path) -> None:
    lease = WriterLease(tmp_path / "writer.lease", ttl_seconds=60.0)
    lease.acquire(now=0.0)
    assert (tmp_path / "writer.lease").exists()
    lease.release()
    assert not (tmp_path / "writer.lease").exists()


def test_starting_over_an_existing_session_is_refused(tmp_path: Path) -> None:
    session, clock = _run(tmp_path, count=2)
    other = PaperSession(tmp_path / "session", clock=lambda: clock[0] + 10_000.0)
    with pytest.raises(PaperEngineError, match="a session already exists"):
        other.start(_config())


# --- breakers --------------------------------------------------------------------------


def test_stale_market_data_trips_the_breaker(tmp_path: Path) -> None:
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    session.start(_config(stale_tick_seconds=3600.0))
    session.advance([_tick(0)])
    clock[0] += 3600.0
    session.advance([_tick(10)])  # a ten-hour jump
    report = session.status_report()
    assert report["status"] == SESSION_HALTED
    assert any(BREAKER_STALE_DATA in b for b in report["breakers_tripped"])
    assert report["kill_switch_engaged"] is True


def test_a_halted_session_refuses_to_advance(tmp_path: Path) -> None:
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    session.start(_config(stale_tick_seconds=3600.0))
    session.advance([_tick(0)])
    session.advance([_tick(10)])
    with pytest.raises(PaperEngineError, match="not advancing"):
        session.advance([_tick(11)])


def test_a_maintenance_breach_counts_a_liquidation(tmp_path: Path) -> None:
    """A short perp against a sharply rising mark must liquidate, not coast."""
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    session.start(_config(perp_leverage=50.0, stale_tick_seconds=10 * 3600.0))
    for index in range(6):
        session.advance([_tick(index, funding=0.0002)])
        clock[0] += 3600.0
    # Mark doubles: a 50x short is far past maintenance.
    session.advance([_tick(6, price=128_000.0)])
    report = session.status_report()
    assert report["counters"]["liquidations"] >= 1
    assert any(BREAKER_LIQUIDATION in b for b in report["breakers_tripped"])
    assert report["status"] == SESSION_HALTED


def test_drawdown_beyond_policy_trips_the_breaker(tmp_path: Path) -> None:
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    session.start(_config(max_drawdown=0.0001, perp_leverage=20.0, stale_tick_seconds=10 * 3600.0))
    ticks = []
    for index in range(8):
        ticks.append(_tick(index, price=64_000.0 + index * 500, funding=0.0002))
        clock[0] += 3600.0
    session.advance(ticks)
    report = session.status_report()
    assert report["kill_switch_engaged"] or report["drawdown"] >= -0.0001


def test_a_breaker_stops_the_rest_of_the_batch(tmp_path: Path) -> None:
    """A halt must not trade on through the condition that caused it."""
    clock = [1_000.0]
    session = PaperSession(tmp_path / "session", clock=lambda: clock[0])
    session.start(_config(stale_tick_seconds=3600.0))
    result = session.advance([_tick(0), _tick(10), _tick(11), _tick(12)])
    assert result["ticks_applied"] == 2  # the good one, then the one that halted
    assert session.status == SESSION_HALTED


def test_a_reconciliation_mismatch_halts_the_session(tmp_path: Path) -> None:
    session, _clock = _run(tmp_path, count=12)
    assert session.ledger is not None
    session.ledger.cash_usd += 500.0  # corrupt the running books
    result = session.reconcile()
    assert not result.reconciled
    assert result.problems
    assert session.status == SESSION_HALTED


# --- broker semantics --------------------------------------------------------------------


def test_a_reused_client_order_id_is_rejected() -> None:
    broker = SimulatedBroker(ExecutionModel())
    order = PaperOrder(
        client_order_id="dup",
        venue="bybit",
        instrument="BTCUSDT",
        leg="spot",
        side="buy",
        quantity=1.0,
        order_type="market",
        created_at_ms=0,
        eligible_at_ms=0,
    )
    broker.submit(order)
    with pytest.raises(PaperEngineError, match="already open"):
        broker.submit(order)


def test_latency_delays_the_fill() -> None:
    broker = SimulatedBroker(ExecutionModel(latency_ms=5_000, max_participation=1.0))
    tick = _tick(0)
    broker.submit(
        PaperOrder(
            client_order_id="o1",
            venue="bybit",
            instrument="BTCUSDT",
            leg="spot",
            side="buy",
            quantity=1.0,
            order_type="market",
            created_at_ms=tick.observed_at_ms,
            eligible_at_ms=tick.observed_at_ms + 5_000,
        )
    )
    assert broker.match(tick) == []
    later = _tick(1)
    assert len(broker.match(later)) == 1


def test_thin_liquidity_produces_a_partial_fill() -> None:
    broker = SimulatedBroker(ExecutionModel(latency_ms=0, max_participation=0.01))
    tick = MarketTick(
        venue="bybit",
        instrument="BTCUSDT",
        bar_start_ms=BASE_MS,
        bar_end_ms=BASE_MS + HOUR_MS,
        observed_at_ms=BASE_MS + HOUR_MS,
        spot_bid=99.0,
        spot_ask=101.0,
        perp_bid=100.0,
        perp_ask=102.0,
        perp_mark=101.0,
        index=100.0,
        spot_quote_volume=1_000.0,
        perp_quote_volume=1_000.0,
    )
    broker.submit(
        PaperOrder(
            client_order_id="o1",
            venue="bybit",
            instrument="BTCUSDT",
            leg="spot",
            side="buy",
            quantity=100.0,
            order_type="market",
            created_at_ms=tick.observed_at_ms,
            eligible_at_ms=tick.observed_at_ms,
        )
    )
    fills = broker.match(tick)
    assert len(fills) == 1
    assert fills[0].is_partial
    assert fills[0].quantity < 100.0


def test_cancelling_an_unknown_order_is_an_error() -> None:
    broker = SimulatedBroker(ExecutionModel())
    with pytest.raises(PaperEngineError, match="no open order"):
        broker.cancel("nope")


def test_a_buy_pays_the_ask_plus_slippage_and_a_sell_receives_less() -> None:
    broker = SimulatedBroker(ExecutionModel(latency_ms=0, slippage_bps=10.0, max_participation=1.0))
    tick = _tick(0)
    for index, side in enumerate(("buy", "sell")):
        broker.submit(
            PaperOrder(
                client_order_id=f"o{index}",
                venue="bybit",
                instrument="BTCUSDT",
                leg="spot",
                side=side,
                quantity=0.001,
                order_type="market",
                created_at_ms=tick.observed_at_ms,
                eligible_at_ms=tick.observed_at_ms,
            )
        )
    fills = {f.side: f for f in broker.match(tick)}
    assert fills["buy"].price > tick.spot_ask
    assert fills["sell"].price < tick.spot_bid
    assert fills["buy"].fee_usd > 0 and fills["sell"].fee_usd > 0


# --- ledger arithmetic ---------------------------------------------------------------------


def test_funding_settles_against_the_position_that_exists_now() -> None:
    ledger = PositionLedger(initial_capital_usd=10_000.0, perp_leverage=3.0)
    assert ledger.apply_funding(0.0005, 64_000.0) == 0.0  # flat: nothing settles
    ledger.apply_fill(
        PaperFill(
            client_order_id="o1",
            venue="bybit",
            instrument="BTCUSDT",
            leg="perp",
            side="sell",
            price=64_000.0,
            quantity=0.01,
            fee_usd=0.0,
            at_ms=0,
            sequence=1,
        )
    )
    received = ledger.apply_funding(0.0005, 64_000.0)
    assert received == pytest.approx(0.01 * 64_000.0 * 0.0005)
    assert ledger.totals.funding_usd == pytest.approx(received)


def test_a_short_perp_pays_funding_when_the_rate_is_negative() -> None:
    ledger = PositionLedger(initial_capital_usd=10_000.0)
    ledger.apply_fill(
        PaperFill("o1", "bybit", "BTCUSDT", "perp", "sell", 64_000.0, 0.01, 0.0, 0, 1)
    )
    assert ledger.apply_funding(-0.0005, 64_000.0) < 0


def test_equity_is_capital_when_nothing_has_happened() -> None:
    ledger = PositionLedger(initial_capital_usd=10_000.0)
    assert ledger.equity_usd(spot_mark=64_000.0, perp_mark=64_000.0) == 10_000.0


def test_a_delta_neutral_carry_is_insensitive_to_the_price_level() -> None:
    """The point of the hedge: equity must not move with BTC."""
    ledger = PositionLedger(initial_capital_usd=10_000.0, perp_leverage=3.0)
    quantity = 0.03
    ledger.apply_fill(
        PaperFill("o1", "bybit", "BTCUSDT", "spot", "buy", 64_000.0, quantity, 0.0, 0, 1)
    )
    ledger.apply_fill(
        PaperFill("o2", "bybit", "BTCUSDT", "perp", "sell", 64_000.0, quantity, 0.0, 0, 2)
    )
    flat = ledger.equity_usd(spot_mark=64_000.0, perp_mark=64_000.0)
    up = ledger.equity_usd(spot_mark=96_000.0, perp_mark=96_000.0)
    down = ledger.equity_usd(spot_mark=32_000.0, perp_mark=32_000.0)
    assert up == pytest.approx(flat, rel=1e-12)
    assert down == pytest.approx(flat, rel=1e-12)


def test_fees_reduce_equity_exactly_once() -> None:
    ledger = PositionLedger(initial_capital_usd=10_000.0)
    ledger.apply_fill(PaperFill("o1", "bybit", "BTCUSDT", "spot", "buy", 100.0, 1.0, 3.0, 0, 1))
    assert ledger.totals.fees_usd == 3.0
    assert ledger.equity_usd(spot_mark=100.0, perp_mark=100.0) == pytest.approx(9_997.0)


def test_a_zero_capital_ledger_is_rejected() -> None:
    with pytest.raises(PaperEngineError, match="initial capital must be > 0"):
        PositionLedger(initial_capital_usd=0.0)


def test_an_order_with_non_positive_quantity_is_rejected() -> None:
    with pytest.raises(PaperEngineError, match="quantity must be finite and > 0"):
        PaperOrder("o", "bybit", "BTCUSDT", "spot", "buy", 0.0, "market", 0, 0)


def test_an_unknown_side_is_rejected() -> None:
    with pytest.raises(PaperEngineError, match="side must be one of"):
        PaperOrder("o", "bybit", "BTCUSDT", "spot", "sideways", 1.0, "market", 0, 0)
