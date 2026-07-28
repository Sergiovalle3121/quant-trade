"""Fault injection: every way the pipeline can be interrupted or lied to.

Each test drives a specific failure into a component that has to survive it —
transport faults into the backfill, corruption and crashes into the paper
session and the shadow collector — and asserts that the survivor is either
correct or honestly broken. A component that quietly loses an event, silently
resumes at the wrong place, or promotes recorded bytes to live provenance
would pass a happy-path test and fail here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.v8.backfill import (
    STATUS_OK,
    BackfillRequest,
    RetryPolicy,
    evidence_dir_for,
    run_backfill,
)
from quant_trade.v9.mining_shadow import BiddingPolicy, MarketSnapshot, ShadowCollector
from quant_trade.v9.paper_engine import CLOCK_INJECTED_TEST, MarketTick, PaperEngineError
from quant_trade.v9.paper_session import PaperSession, SessionConfig
from tests.v8_venue_fakes import FakeVenue

# --- fixtures ----------------------------------------------------------------

SINCE_MS = 1_750_000_000_000
UNTIL_MS = SINCE_MS + 48 * 3_600_000


def fake_venue(*faults: str) -> FakeVenue:
    """A deterministic Bybit stand-in, optionally injecting transport faults."""
    return FakeVenue(
        venue="bybit",
        symbol="BTC",
        start_ms=SINCE_MS,
        end_ms=UNTIL_MS,
        interval_minutes=60,
        faults=list(faults),
    )


def request() -> BackfillRequest:
    return BackfillRequest(
        venue="bybit",
        symbol="BTC",
        since_ms=SINCE_MS,
        until_ms=UNTIL_MS,
        interval_minutes=60,
    )


def backfill(tmp_path: Path, fetcher, **kwargs):
    return run_backfill(
        request(),
        tmp_path,
        fetcher=fetcher,
        retry=RetryPolicy(max_attempts=3, base_delay_seconds=0.001),
        sleeper=lambda _: None,
        clock=lambda: 0.0,
        source_kind="recorded_test_response",
        captured_at_utc="2026-07-28T00:00:00Z",
        **kwargs,
    )


def attempts_for(tmp_path: Path) -> list[dict]:
    path = evidence_dir_for(tmp_path, "bybit", "BTC") / "attempts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- transport faults --------------------------------------------------------


def test_a_429_is_retried_and_recorded_verbatim(tmp_path: Path) -> None:
    venue = fake_venue("429")
    result = backfill(tmp_path, venue.fetch)
    records = attempts_for(tmp_path)
    assert any(r.get("http_status") == 429 for r in records)
    assert result.status == STATUS_OK, "the run did not recover from a single 429"
    assert result.provenance == "test_only"


@pytest.mark.parametrize("fault", ["429", "500"])
def test_a_retryable_status_is_retried_and_the_run_still_completes(
    tmp_path: Path, fault: str
) -> None:
    venue = fake_venue(fault)
    result = backfill(tmp_path, venue.fetch)
    records = attempts_for(tmp_path)
    assert any(r.get("http_status") == int(fault) for r in records)
    assert result.status == STATUS_OK


def test_a_transport_failure_is_recorded_with_its_exception_text(tmp_path: Path) -> None:
    venue = fake_venue("transport")
    result = backfill(tmp_path, venue.fetch)
    records = attempts_for(tmp_path)
    assert any("simulated transport failure" in str(r.get("error", "")) for r in records)
    assert result.status == STATUS_OK


def test_repeated_faults_beyond_the_retry_budget_fail_loudly(tmp_path: Path) -> None:
    """Exhausting the budget must not look like success with missing data."""
    venue = fake_venue(*(["transport"] * 12))
    result = backfill(tmp_path, venue.fetch)
    assert result.status != STATUS_OK
    assert result.errors
    assert any("simulated transport failure" in e for e in result.errors)


def test_retry_backoff_is_deterministic() -> None:
    """A replayed run must produce the same attempt log, so no jitter."""
    policy = RetryPolicy(max_attempts=4, base_delay_seconds=2.0)
    assert [policy.delay_for(i) for i in range(1, 5)] == [2.0, 4.0, 8.0, 16.0]
    assert policy.delay_for(10) == policy.max_delay_seconds


def test_schema_drift_is_rejected_rather_than_coerced(tmp_path: Path) -> None:
    """A response that no longer means what it did must not be guessed at."""
    venue = fake_venue()

    def drifted(url: str) -> tuple[int, bytes, dict[str, str]]:
        status, body, headers = venue.fetch(url)
        if "/v5/market/kline" in url:
            payload = json.loads(body.decode("utf-8"))
            # The venue starts returning objects where it returned arrays.
            payload["result"]["list"] = [
                {"start": row[0], "close": row[4]} for row in payload["result"]["list"]
            ]
            return status, json.dumps(payload).encode(), headers
        return status, body, headers

    result = backfill(tmp_path, drifted)
    assert result.status != STATUS_OK, "drifted rows were accepted"
    assert result.errors


def test_a_missing_required_field_is_rejected(tmp_path: Path) -> None:
    venue = fake_venue()

    def truncated(url: str) -> tuple[int, bytes, dict[str, str]]:
        status, body, headers = venue.fetch(url)
        if "/v5/market/time" in url:
            return status, json.dumps({"retCode": 0, "result": {}}).encode(), headers
        return status, body, headers

    result = backfill(tmp_path, truncated)
    assert any("server_time" in e for e in result.errors)


def test_recorded_bytes_can_never_claim_live_provenance(tmp_path: Path) -> None:
    result = backfill(tmp_path, fake_venue().fetch)
    assert result.provenance == "test_only"
    assert result.status == STATUS_OK
    directory = evidence_dir_for(tmp_path, "bybit", "BTC")
    receipts = [
        json.loads(line)
        for line in (directory / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert receipts, "no receipt was written to check"
    for receipt in receipts:
        assert receipt["source_kind"] == "recorded_test_response"
        assert receipt["source_kind"] != "live"


def test_a_resumed_backfill_touches_no_network_and_adds_no_receipts(tmp_path: Path) -> None:
    """The archive answers every request the second time around."""
    first = backfill(tmp_path, fake_venue().fetch)
    assert first.status == STATUS_OK
    directory = evidence_dir_for(tmp_path, "bybit", "BTC")
    before = sorted(p.name for p in directory.glob("**/*") if p.is_file())

    def refuse(url: str) -> tuple[int, bytes, dict[str, str]]:
        raise AssertionError(f"resume must not touch the network, but fetched {url}")

    second = backfill(tmp_path, refuse)
    after = sorted(p.name for p in directory.glob("**/*") if p.is_file())
    assert second.status == STATUS_OK
    assert after == before, "a resumed backfill wrote new files"


# --- paper session durability ------------------------------------------------


def session_config(**overrides) -> SessionConfig:
    base = {
        "session_id": "fault-1",
        "candidate_id": "H1-v1",
        "manifest_sha256": "a" * 64,
        "initial_capital_usd": 10_000.0,
        "strategy": {
            "entry_threshold": 0.0001,
            "trailing_window": 3,
            "target_notional_usd": 5_000.0,
        },
        "execution": {
            "latency_ms": 250,
            "slippage_bps": 1.0,
            "max_participation": 0.05,
            "spot_fee_bps": 10.0,
            "perp_fee_bps": 5.5,
        },
    }
    base.update(overrides)
    return SessionConfig(**base)  # type: ignore[arg-type]


def tick(index: int, *, funding: float | None = None) -> MarketTick:
    start = 1_750_000_000_000 + index * 3_600_000
    return MarketTick(
        venue="bybit",
        instrument="BTCUSDT",
        bar_start_ms=start,
        bar_end_ms=start + 3_600_000,
        observed_at_ms=start + 3_600_000,
        spot_bid=59_990.0,
        spot_ask=60_010.0,
        perp_bid=60_040.0,
        perp_ask=60_060.0,
        perp_mark=60_050.0,
        index=60_000.0,
        settled_funding_rate=funding,
        spot_quote_volume=5_000_000.0,
        perp_quote_volume=5_000_000.0,
    )


class Clock:
    def __init__(self, start: float = 1_750_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 60.0
        return self.now


def test_a_crash_between_journal_and_checkpoint_replays_to_the_same_state(
    tmp_path: Path,
) -> None:
    """Journal first, checkpoint second: the crash window must be recoverable."""
    session = PaperSession(tmp_path, clock=Clock())
    session.start(session_config())
    session.advance([tick(i, funding=0.0002) for i in range(6)])
    good = session.status_report()
    session.stop()

    # Simulate the crash: the checkpoint is stale by one tick, the journal is not.
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    journal_lines = (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(journal_lines) > 3
    stale = dict(checkpoint)
    stale["sequence"] = max(1, int(checkpoint.get("sequence", 1)) - 1)
    (tmp_path / "checkpoint.json").write_text(json.dumps(stale), encoding="utf-8")

    revived = PaperSession(tmp_path, clock=Clock())
    revived.resume()
    replayed = revived.status_report()
    assert replayed["counters"]["ticks_applied"] == good["counters"]["ticks_applied"]
    assert replayed["equity_usd"] == pytest.approx(good["equity_usd"], rel=1e-12)


def test_a_torn_final_journal_line_is_survivable(tmp_path: Path) -> None:
    session = PaperSession(tmp_path, clock=Clock())
    session.start(session_config())
    session.advance([tick(i, funding=0.0002) for i in range(4)])
    applied = session.status_report()["counters"]["ticks_applied"]
    session.stop()

    with (tmp_path / "journal.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 999, "kind": "ti')

    revived = PaperSession(tmp_path, clock=Clock())
    revived.resume()
    assert revived.status_report()["counters"]["ticks_applied"] == applied


def test_a_restart_is_exactly_once(tmp_path: Path) -> None:
    """Re-feeding the same ticks after a restart must not double-count them."""
    session = PaperSession(tmp_path, clock=Clock())
    session.start(session_config(stale_tick_seconds=7_200.0))
    ticks = [tick(i, funding=0.0002) for i in range(5)]
    applied = session.advance(ticks)
    assert applied["ticks_applied"] == 5, "the batch did not complete"
    first = session.status_report()
    session.stop()

    revived = PaperSession(tmp_path, clock=Clock())
    revived.resume()
    result = revived.advance(ticks)
    assert result["ticks_applied"] == 0
    second = revived.status_report()
    assert second["counters"]["ticks_applied"] == first["counters"]["ticks_applied"]
    assert second["equity_usd"] == pytest.approx(first["equity_usd"], rel=1e-12)


def test_a_halted_session_stays_halted_across_a_restart(tmp_path: Path) -> None:
    """A restart is not a way to clear a tripped kill switch."""
    session = PaperSession(tmp_path, clock=Clock())
    session.start(session_config(stale_tick_seconds=900.0))
    session.advance([tick(i, funding=0.0002) for i in range(5)])
    assert session.breakers, "no breaker tripped; the test is not exercising the halt"
    halted_at = session.counters.ticks_applied
    session.stop()

    revived = PaperSession(tmp_path, clock=Clock())
    revived.resume()
    report = revived.status_report()
    assert report["status"] == "PAPER_HALTED"
    assert report["kill_switch_engaged"] is True
    assert report["breakers_tripped"] == session.breakers
    with pytest.raises(PaperEngineError, match="not advancing"):
        revived.advance([tick(9, funding=0.0002)])
    assert revived.counters.ticks_applied == halted_at


def test_a_halt_survives_an_edited_status_field(tmp_path: Path) -> None:
    """The recorded breakers rebuild the halt even if the status is tampered with."""
    session = PaperSession(tmp_path, clock=Clock())
    session.start(session_config(stale_tick_seconds=900.0))
    session.advance([tick(i, funding=0.0002) for i in range(5)])
    assert session.breakers
    session.stop()

    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    checkpoint["status"] = "PAPER_RUNNING"
    (tmp_path / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")

    revived = PaperSession(tmp_path, clock=Clock())
    revived.resume()
    assert revived.status == "PAPER_HALTED"


def test_a_gap_in_the_tick_stream_trips_the_stale_data_breaker(tmp_path: Path) -> None:
    session = PaperSession(tmp_path, clock=Clock())
    session.start(session_config(stale_tick_seconds=7_200.0))
    session.advance([tick(0, funding=0.0002)])
    far = tick(0)
    jumped = MarketTick(
        **{
            **{f: getattr(far, f) for f in MarketTick.__dataclass_fields__},
            "bar_start_ms": far.bar_start_ms + 86_400_000,
            "bar_end_ms": far.bar_end_ms + 86_400_000,
            "observed_at_ms": far.observed_at_ms + 86_400_000,
        }
    )
    session.advance([jumped])
    report = session.status_report()
    assert report["breakers_tripped"], "a day-long gap did not trip anything"
    assert report["status"] != "RUNNING"


def test_a_second_writer_is_refused(tmp_path: Path) -> None:
    from quant_trade.v9.paper_engine import LeaseError

    first = PaperSession(tmp_path, clock=Clock())
    first.start(session_config())
    second = PaperSession(tmp_path, clock=Clock())
    with pytest.raises((LeaseError, PaperEngineError)):
        second.start(session_config(session_id="fault-2"))


def test_an_injected_clock_marks_the_session_forever(tmp_path: Path) -> None:
    session = PaperSession(tmp_path, clock=Clock())
    session.start(session_config())
    session.advance([tick(0, funding=0.0002)])
    assert session.status_report()["clock_source"] == CLOCK_INJECTED_TEST
    assert session.status_report()["clock_is_persisted"] is False
    session.stop()

    # The mark survives a restart under a different clock.
    revived = PaperSession(tmp_path, clock=Clock())
    revived.resume()
    assert revived.status_report()["clock_source"] == CLOCK_INJECTED_TEST


# --- shadow collector durability ---------------------------------------------


def shadow_policy() -> BiddingPolicy:
    return BiddingPolicy(
        name="p50-frozen",
        bid_percentile=0.5,
        max_price_btc=0.005,
        speed_limit=1.0,
        amount_btc=0.01,
        duration_hours=24.0,
    )


def shadow_snapshot(index: int) -> MarketSnapshot:
    return MarketSnapshot(
        captured_at_ms=1_750_000_000_000 + index * 600_000,
        algorithm="SHA256",
        market="EU",
        best_price_btc=0.001,
        orderbook_depth=5,
        raw_sha256="0" * 64,
        evidence_class="RECORDED_TEST",
        source_url="https://api2.nicehash.com/main/api/v2/hashpower/orderBook",
    )


class StepClock:
    def __init__(self, start: float = 1_750_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_a_crash_mid_capture_leaves_a_verifiable_chain(tmp_path: Path) -> None:
    clock = StepClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(shadow_policy())
    for i in range(4):
        clock.advance(600.0)
        collector.capture(shadow_snapshot(i))
    collector.release()

    # A crash truncates the tail of the last write.
    text = collector.journal_path.read_text(encoding="utf-8")
    collector.journal_path.write_text(text[: len(text) - 25], encoding="utf-8")

    revived = ShadowCollector(tmp_path, clock=clock)
    revived.resume()
    ok, problems = revived.verify_chain()
    # The surviving prefix is intact; the truncated record simply is not there.
    assert ok, problems
    assert revived.stats.snapshots == 3


def test_a_checkpoint_that_disagrees_with_the_journal_loses(tmp_path: Path) -> None:
    """The journal is the authority; a stale or edited checkpoint cannot win."""
    clock = StepClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(shadow_policy())
    for i in range(5):
        clock.advance(600.0)
        collector.capture(shadow_snapshot(i))
    collector.release()

    checkpoint = json.loads(collector.checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["stats"]["snapshots"] = 9_999
    checkpoint["stats"]["observed_seconds"] = 86_400.0 * 30
    collector.checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    revived = ShadowCollector(tmp_path, clock=clock)
    revived.resume()
    assert revived.stats.snapshots == 5
    assert revived.stats.observed_seconds == pytest.approx(4 * 600.0)


def test_a_restarted_collector_keeps_its_window(tmp_path: Path) -> None:
    clock = StepClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(shadow_policy())
    for i in range(6):
        clock.advance(600.0)
        collector.capture(shadow_snapshot(i))
    observed = collector.stats.observed_seconds
    collector.release()

    revived = ShadowCollector(tmp_path, clock=clock)
    revived.start(shadow_policy())
    clock.advance(600.0)
    revived.capture(shadow_snapshot(6))
    assert revived.stats.snapshots == 7
    assert revived.stats.observed_seconds > observed


def test_downtime_across_a_restart_is_recorded_as_a_gap(tmp_path: Path) -> None:
    clock = StepClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(shadow_policy())
    clock.advance(600.0)
    collector.capture(shadow_snapshot(0))
    collector.release()

    clock.advance(6 * 3600.0)  # the collector was down for six hours
    revived = ShadowCollector(tmp_path, clock=clock)
    revived.start(shadow_policy())
    revived.capture(shadow_snapshot(1))
    assert revived.stats.gaps == 1
    assert revived.stats.gap_seconds == pytest.approx(6 * 3600.0)
    assert revived.stats.observed_seconds == pytest.approx(0.0)
