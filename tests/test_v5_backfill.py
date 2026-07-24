"""Funding-history backfill: pure parsers, identity discipline, NOT_RUN evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.carry.backfill import (
    build_backfill_url,
    parse_bybit_funding_history,
    parse_okx_funding_history,
    run_backfill,
)
from quant_trade.carry.store import (
    FundingObservation,
    extract_settlement_events,
    read_store,
    verify_raw_payload,
)

BYBIT_FIXTURE = Path("tests/fixtures/bybit_funding_history.json")
OKX_FIXTURE = Path("tests/fixtures/okx_funding_history.json")
CAPTURED = "2026-07-24T20:00:00Z"


def test_bybit_parser_yields_settlements_with_bound_raw_bytes():
    raw = BYBIT_FIXTURE.read_bytes()
    events = parse_bybit_funding_history(raw, symbol="BTC", captured_at_utc=CAPTURED)
    assert len(events) == 6
    assert {e.source_event for e in events} == {"funding_settlement"}
    assert {e.venue for e in events} == {"bybit"}
    assert events[0].exchange_timestamp_utc == "2026-07-21T16:00:00Z"
    assert events[0].realized_funding_rate == pytest.approx(0.00013)
    assert events[0].funding_interval_hours == pytest.approx(8.0)
    assert events[0].perpetual_instrument_id == "bybit:BTCUSDT"
    # every record is byte-bound to the exact raw response
    for e in events:
        assert verify_raw_payload(e.to_dict(), raw)
        assert not verify_raw_payload(e.to_dict(), raw + b" ")


def test_bybit_parser_rejects_error_responses_and_foreign_symbols():
    error = json.dumps({"retCode": 10001, "retMsg": "params error"}).encode()
    with pytest.raises(ValueError, match="retCode=10001"):
        parse_bybit_funding_history(error, symbol="BTC", captured_at_utc=CAPTURED)
    # response carrying a different instrument must fail closed, never relabel
    raw = BYBIT_FIXTURE.read_bytes()
    with pytest.raises(ValueError, match="identity mismatch"):
        parse_bybit_funding_history(raw, symbol="ETH", captured_at_utc=CAPTURED)


def test_okx_parser_prefers_realized_rate_and_checks_identity():
    raw = OKX_FIXTURE.read_bytes()
    events = parse_okx_funding_history(raw, symbol="BTC", captured_at_utc=CAPTURED)
    assert len(events) == 3
    # settled (realized) rate wins over the announced rate when present
    assert events[0].realized_funding_rate == pytest.approx(0.00018)
    # empty realizedRate falls back to fundingRate
    assert events[2].realized_funding_rate == pytest.approx(0.00010)
    assert events[0].perpetual_instrument_id == "okx:BTC-USDT-SWAP"
    with pytest.raises(ValueError, match="identity mismatch"):
        parse_okx_funding_history(raw, symbol="SOL", captured_at_utc=CAPTURED)
    bad = json.dumps({"code": "50011", "msg": "rate limit"}).encode()
    with pytest.raises(ValueError, match="code='50011'"):
        parse_okx_funding_history(bad, symbol="BTC", captured_at_utc=CAPTURED)


def test_run_backfill_fixture_is_idempotent_and_marked(tmp_path):
    store = tmp_path / "funding.jsonl"
    first = run_backfill("bybit", "BTC", store, fixture_path=BYBIT_FIXTURE)
    assert first.status == "OK"
    assert first.provenance == "fixture"
    assert first.appended == 6
    second = run_backfill("bybit", "BTC", store, fixture_path=BYBIT_FIXTURE)
    assert second.appended == 0
    assert second.deduplicated == 6  # re-runs can never double-count

    records = read_store(store).records
    assert all(r["source_name"].startswith("fixture:") for r in records)
    settlements = extract_settlement_events(records)
    assert len(settlements) == 6
    stamps = [s["exchange_timestamp_utc"] for s in settlements]
    assert stamps == sorted(stamps)

    # the raw payload is preserved content-addressed and still verifies
    raw_file = Path(first.raw_path)
    assert raw_file.exists()
    assert raw_file.name == f"{first.raw_sha256}.json"
    assert verify_raw_payload(records[0], raw_file.read_bytes())


def test_run_backfill_network_failure_records_verifiable_not_run(tmp_path):
    store = tmp_path / "funding.jsonl"

    def blocked(url: str) -> bytes:
        raise OSError("Tunnel connection failed: 403 Forbidden")

    result = run_backfill("okx", "BTC", store, fetcher=blocked)
    assert result.status == "NOT_RUN_NETWORK_BLOCKED"
    assert "403 Forbidden" in result.error
    assert not store.exists()  # nothing fabricated into the store

    # the attempt is logged verbatim — the evidence a reviewer can check
    log_lines = Path(result.attempts_log).read_text().splitlines()
    logged = json.loads(log_lines[-1])
    assert logged["status"] == "NOT_RUN_NETWORK_BLOCKED"
    assert "403 Forbidden" in logged["error"]
    assert logged["url"] == build_backfill_url("okx", "BTC", 200)


def test_run_backfill_rejects_garbage_bytes(tmp_path):
    store = tmp_path / "funding.jsonl"
    bad_fixture = tmp_path / "garbage.json"
    bad_fixture.write_bytes(b"<html>proxy error</html>")
    result = run_backfill("bybit", "BTC", store, fixture_path=bad_fixture)
    assert result.status == "NOT_RUN_PARSE_REJECTED"
    assert not store.exists()


def test_settlement_events_may_omit_prices_but_quotes_may_not():
    settlement = FundingObservation(
        venue="bybit",
        symbol="BTC",
        captured_at_utc=CAPTURED,
        exchange_timestamp_utc="2026-07-21T16:00:00Z",
        realized_funding_rate=0.0001,
        source_event="funding_settlement",
    )
    assert settlement.spot_bid is None  # honest: history endpoints carry no book
    with pytest.raises(ValueError, match="required for quote events"):
        FundingObservation(
            venue="bybit",
            symbol="BTC",
            captured_at_utc=CAPTURED,
            exchange_timestamp_utc="2026-07-21T16:00:00Z",
            realized_funding_rate=0.0001,
            source_event="poll",
        )


def test_cli_backfill_fixture_roundtrip(tmp_path):
    from typer.testing import CliRunner

    from quant_trade.cli import app

    store = tmp_path / "funding.jsonl"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "carry",
            "backfill",
            "--venue",
            "okx",
            "--symbol",
            "BTC",
            "--output",
            str(store),
            "--fixture",
            str(OKX_FIXTURE),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "OK" in result.output
    assert "provenance: fixture" in result.output
    assert len(extract_settlement_events(read_store(store).records)) == 3


def test_cli_backfill_live_blocked_exits_nonzero(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import quant_trade.carry.backfill as backfill_mod
    from quant_trade.cli import app

    def blocked(url: str, *, timeout_seconds: float = 10.0) -> bytes:
        raise OSError("Tunnel connection failed: 403 Forbidden")

    monkeypatch.setattr(backfill_mod, "fetch_public_bytes", blocked)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "carry",
            "backfill",
            "--venue",
            "bybit",
            "--output",
            str(tmp_path / "funding.jsonl"),
        ],
    )
    assert result.exit_code == 1
    assert "NOT_RUN_NETWORK_BLOCKED" in result.output
    assert "403 Forbidden" in result.output
