"""Tests for the point-in-time funding collector, store, and dataset audit."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from quant_trade.carry.cli import carry_app
from quant_trade.carry.collector import (
    CcxtFundingAdapter,
    CollectorConfig,
    FixtureFundingAdapter,
    collect_once,
)
from quant_trade.carry.quality import audit_dataset, parse_utc
from quant_trade.carry.store import (
    FundingObservation,
    append_observations,
    observations_to_snapshot_records,
    read_store,
)

FIXTURE = "tests/fixtures/carry_observations.json"
runner = CliRunner()


def _obs(**overrides) -> FundingObservation:
    base = dict(
        venue="binance",
        symbol="BTC",
        captured_at_utc="2026-07-20T00:00:05Z",
        exchange_timestamp_utc="2026-07-20T00:00:00Z",
        spot_bid=64000.5,
        spot_ask=64001.5,
        perp_bid=64010.0,
        perp_ask=64011.0,
        perp_mark=64010.5,
        perp_index=64001.0,
        realized_funding_rate=0.0001,
        source_name="test",
    )
    base.update(overrides)
    return FundingObservation(**base)


# --- store ----------------------------------------------------------------


def test_append_is_idempotent_by_dedup_key(tmp_path):
    store = tmp_path / "history.jsonl"
    first = append_observations(store, [_obs()])
    assert first.appended == 1
    again = append_observations(store, [_obs()])
    assert again.appended == 0
    assert again.deduplicated == 1
    assert len(read_store(store).records) == 1


def test_distinct_timestamps_and_venues_are_kept(tmp_path):
    store = tmp_path / "history.jsonl"
    result = append_observations(
        store,
        [
            _obs(),
            _obs(exchange_timestamp_utc="2026-07-20T08:00:00Z"),
            _obs(venue="okx"),
        ],
    )
    assert result.appended == 3


def test_corrupt_lines_are_quarantined_not_dropped(tmp_path):
    store = tmp_path / "history.jsonl"
    append_observations(store, [_obs()])
    with store.open("a", encoding="utf-8") as fh:
        fh.write("{torn line\n")
    read = read_store(store)
    assert len(read.records) == 1
    assert len(read.quarantined) == 1


def test_observation_validation_rejects_crossed_books():
    with pytest.raises(ValueError, match="spot_bid"):
        _obs(spot_bid=99999.0, spot_ask=1.0)


def test_bridge_to_snapshot_records_marks_real_and_uses_mid(tmp_path):
    store = tmp_path / "history.jsonl"
    append_observations(store, [_obs()])
    records = observations_to_snapshot_records(read_store(store).records)
    assert records[0]["data_source"] == "real"
    assert records[0]["spot_price"] == pytest.approx((64000.5 + 64001.5) / 2)
    assert records[0]["exchange"] == "binance"


# --- collector ------------------------------------------------------------


def _config(tmp_path, pairs=(("binance", "BTC"), ("okx", "BTC"))) -> CollectorConfig:
    return CollectorConfig(
        pairs=tuple(pairs),
        output_path=str(tmp_path / "history.jsonl"),
        adapter="fake",
        fixture_path=FIXTURE,
    )


def test_collect_once_captures_and_dedups(tmp_path):
    cfg = _config(tmp_path)
    first = collect_once(cfg)
    assert first.captured == 2
    assert first.appended == 2
    second = collect_once(cfg)  # same fixture: everything dedups
    assert second.appended == 0
    assert second.deduplicated == 2


def test_collect_once_records_errors_per_pair(tmp_path):
    cfg = _config(tmp_path, pairs=(("binance", "BTC"), ("kraken", "DOGE")))
    summary = collect_once(cfg)
    assert summary.captured == 1  # binance ok
    assert any("kraken:DOGE" in e for e in summary.errors)


def test_adapters_expose_no_trading_verbs():
    forbidden = {
        "create_order", "cancel_order", "cancel_all_orders", "withdraw",
        "transfer", "create_instance", "run_instances", "submit_order",
    }
    for adapter_cls in (FixtureFundingAdapter, CcxtFundingAdapter):
        assert forbidden.isdisjoint(dir(adapter_cls)), adapter_cls.__name__


# --- quality audit --------------------------------------------------------


def _series(tmp_path, hours: list[int], venue: str = "binance") -> str:
    store = tmp_path / "history.jsonl"
    append_observations(
        store,
        [
            _obs(
                venue=venue,
                exchange_timestamp_utc=f"2026-07-{20 + h // 24:02d}T{h % 24:02d}:00:00Z",
            )
            for h in hours
        ],
    )
    return str(store)


def test_audit_clean_series(tmp_path):
    path = _series(tmp_path, [0, 8, 16, 24, 32])
    report = audit_dataset(path)
    assert report.is_clean, report.problems
    assert report.funding_events == 5
    assert report.gaps_detected == 0
    assert report.span_days == pytest.approx(32 / 24)


def test_audit_detects_gap(tmp_path):
    path = _series(tmp_path, [0, 8, 40])  # 32h hole in an 8h series
    report = audit_dataset(path)
    assert report.gaps_detected == 1
    assert not report.is_clean
    assert report.largest_gap_hours == pytest.approx(32.0)


def test_audit_detects_quarantine_and_duplicates(tmp_path):
    path = _series(tmp_path, [0, 8])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("not json at all\n")
        # a manually duplicated key bypassing append-dedup
        record = read_store(path).records[0]
        fh.write(json.dumps(record) + "\n")
    report = audit_dataset(path)
    assert report.quarantined_lines == 1
    assert report.duplicate_keys == 1
    assert not report.is_clean


def test_parse_utc_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_utc("2026-07-20T00:00:00")


# --- CLI ------------------------------------------------------------------


def test_collect_once_cli_offline(tmp_path):
    cfg = tmp_path / "collector.yaml"
    cfg.write_text(
        "adapter: fake\n"
        f"fixture_path: {FIXTURE}\n"
        "pairs:\n  - venue: binance\n    symbol: BTC\n"
        f"output_path: {tmp_path / 'store.jsonl'}\n",
        encoding="utf-8",
    )
    result = runner.invoke(carry_app, ["collect-once", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "captured=1" in result.output
    assert "read-only collector" in result.output


def test_dataset_audit_cli(tmp_path):
    path = _series(tmp_path, [0, 8, 16])
    out = tmp_path / "audit.json"
    result = runner.invoke(
        carry_app, ["dataset-audit", "--path", path, "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "CLEAN" in result.output
    payload = json.loads(out.read_text())
    assert payload["funding_events"] == 3
