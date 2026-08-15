"""Hash, provenance, and causal-time tests for sparse crypto market events."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from quant_trade.data.crypto_market_events import (
    CryptoMarketEventError,
    MarketEventEvidence,
    MarketEventLedger,
    load_market_event_ledger,
    write_market_event_ledger,
)
from quant_trade.evidence.canonical_json import sha256_of_file


def _event(**overrides) -> MarketEventEvidence:
    values = {
        "instrument_id": "CMC:7",
        "venue": "bybit",
        "event": "DELISTING_ANNOUNCED",
        "effective_at_utc": "2020-01-02T12:00:00Z",
        "observed_at_utc": "2020-01-02T10:00:00Z",
        "source": "Bybit announcement 123",
        "source_sha256": "a" * 64,
    }
    values.update(overrides)
    return MarketEventEvidence(**values)


def test_market_event_ledger_round_trips_and_is_manifest_component_hashable(tmp_path) -> None:
    ledger = MarketEventLedger.from_events([_event()])
    path = write_market_event_ledger(tmp_path / "market_events.json", ledger)
    component_sha = sha256_of_file(path)

    loaded = load_market_event_ledger(path, expected_component_sha256=component_sha)

    assert loaded == ledger
    assert loaded.digest() == ledger.digest()
    assert loaded.to_frame().iloc[0]["instrument_id"] == "CMC:7"


def test_market_event_ledger_rejects_tampered_bytes_and_embedded_digest(tmp_path) -> None:
    path = write_market_event_ledger(
        tmp_path / "market_events.json", MarketEventLedger.from_events([_event()])
    )
    component_sha = sha256_of_file(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["events"][0]["source"] = "tampered announcement"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CryptoMarketEventError, match="component byte hash mismatch"):
        load_market_event_ledger(path, expected_component_sha256=component_sha)
    with pytest.raises(CryptoMarketEventError, match="embedded digest mismatch"):
        load_market_event_ledger(path)


def test_market_event_requires_causal_observation_and_explicit_provenance() -> None:
    with pytest.raises(CryptoMarketEventError, match="no later than"):
        _event(observed_at_utc="2020-01-03T00:00:00Z")
    with pytest.raises(CryptoMarketEventError, match="source_sha256"):
        _event(source_sha256="not-a-digest")
    with pytest.raises(CryptoMarketEventError, match="confirmed terminal"):
        replace(_event(), terminal_recovery_price=8.0)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("observed_at_utc", "2020-01-02T10:00:00"),
        ("effective_at_utc", "2020-01-02T12:00:00-06:00"),
    ],
)
def test_market_event_timestamps_must_carry_zero_utc_offset(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(CryptoMarketEventError, match="explicit UTC timestamp"):
        _event(**{field_name: value})


def test_market_event_source_must_be_nonempty() -> None:
    with pytest.raises(CryptoMarketEventError, match="source is required"):
        _event(source="  ")


def test_terminal_recovery_is_allowed_only_with_confirmed_evidence() -> None:
    event = _event(
        event="DELISTING_CONFIRMED",
        terminal_recovery_price=8.0,
    )
    assert event.terminal_recovery_price == 8.0
