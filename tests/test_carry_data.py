"""Tests for the read-only carry data layer (offline; no network)."""

from __future__ import annotations

import pytest

from quant_trade.carry.data import (
    load_snapshots_from_json,
    load_snapshots_from_records,
    synthetic_funding_snapshots,
    validate_snapshot_record,
    write_snapshots_json,
)


def _valid_record(**overrides) -> dict:
    base = dict(
        symbol="BTC",
        exchange="venue",
        captured_at_utc="2024-01-01T00:00:00Z",
        spot_price=30000.0,
        perp_mark_price=30030.0,
        perp_index_price=30000.0,
        realized_funding_rate=0.0005,
    )
    base.update(overrides)
    return base


def test_validate_flags_missing_fields():
    errors = validate_snapshot_record({"symbol": "BTC"})
    assert any("spot_price" in e for e in errors)
    assert any("realized_funding_rate" in e for e in errors)


def test_validate_flags_non_finite():
    errors = validate_snapshot_record(_valid_record(spot_price=float("inf")))
    assert any("spot_price must be a finite number" in e for e in errors)


def test_valid_record_passes():
    assert validate_snapshot_record(_valid_record()) == []


def test_load_from_records_builds_snapshots():
    snaps = load_snapshots_from_records([_valid_record(), _valid_record(symbol="ETH")])
    assert len(snaps) == 2
    assert snaps[1].symbol == "ETH"


def test_load_from_records_fails_closed_on_bad_record():
    with pytest.raises(ValueError, match="invalid"):
        load_snapshots_from_records([{"symbol": "BTC"}])


def test_synthetic_snapshots_are_deterministic_and_labelled():
    a = synthetic_funding_snapshots(periods=50, seed=3)
    b = synthetic_funding_snapshots(periods=50, seed=3)
    assert len(a) == 50
    assert all(s.data_source == "synthetic" for s in a)
    assert a[10].realized_funding_rate == b[10].realized_funding_rate
    # different seed -> different path
    c = synthetic_funding_snapshots(periods=50, seed=4)
    assert a[10].realized_funding_rate != c[10].realized_funding_rate


def test_json_round_trip(tmp_path):
    snaps = synthetic_funding_snapshots(periods=20, seed=1)
    path = write_snapshots_json(tmp_path / "snaps.json", snaps)
    loaded = load_snapshots_from_json(path)
    assert len(loaded) == 20
    assert loaded[0].symbol == snaps[0].symbol
