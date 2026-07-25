"""Ingestion receipts: provenance is verified from bytes, never self-declared."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.evidence.canonical_json import sha256_of_bytes
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
    resolve_provenance,
)


def _receipt(raw_file: Path, kind: str) -> IngestionReceipt:
    return IngestionReceipt(
        provider_or_venue="bybit",
        endpoint="https://api.bybit.com/v5/market/funding/history",
        request_parameters={"symbol": "BTCUSDT", "limit": 200},
        http_status=200,
        captured_at_utc="2026-07-24T23:00:00Z",
        adapter_name="evidence.json.identity",
        adapter_version="1",
        raw_path=raw_file.name,
        raw_sha256=sha256_of_bytes(raw_file.read_bytes()),
        normalized_rows_sha256=normalized_rows_sha256([json.loads(raw_file.read_bytes())]),
        source_kind=kind,
    )


def test_live_receipt_with_intact_bytes_resolves_real(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_bytes(b'{"page": 1}')
    receipts = tmp_path / "receipts.jsonl"
    append_receipt(receipts, _receipt(raw, "live"))
    records = [{"raw_sha256": sha256_of_bytes(raw.read_bytes())}]
    report = resolve_provenance(records, receipts)
    assert report.provenance == "real"
    assert report.records_real == 1


def test_fixture_receipt_is_test_only_forever(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_bytes(b'{"page": 1}')
    receipts = tmp_path / "receipts.jsonl"
    append_receipt(receipts, _receipt(raw, "fixture"))
    records = [{"raw_sha256": sha256_of_bytes(raw.read_bytes())}]
    report = resolve_provenance(records, receipts)
    assert report.provenance == "test_only"


def test_tampered_raw_invalidates_the_dataset(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_bytes(b'{"page": 1}')
    receipts = tmp_path / "receipts.jsonl"
    receipt = _receipt(raw, "live")
    append_receipt(receipts, receipt)
    raw.write_bytes(b'{"page": 1} ')  # one flipped byte after the receipt
    report = resolve_provenance([{"raw_sha256": receipt.raw_sha256}], receipts)
    assert report.provenance == "invalid"
    assert any("do not hash" in p for p in report.problems)


def test_records_without_receipts_are_unverified_legacy(tmp_path):
    report = resolve_provenance([{"raw_sha256": "deadbeef"}, {}], tmp_path / "receipts.jsonl")
    assert report.provenance == "unverified_legacy"
    assert report.records_unverified == 2


def test_mixed_receipt_and_legacy_records_resolve_mixed(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_bytes(b'{"page": 1}')
    receipts = tmp_path / "receipts.jsonl"
    append_receipt(receipts, _receipt(raw, "live"))
    records = [
        {"raw_sha256": sha256_of_bytes(raw.read_bytes())},
        {"raw_sha256": ""},  # no receipt
    ]
    report = resolve_provenance(records, receipts)
    assert report.provenance == "mixed"


def test_receipts_refuse_secrets_and_unknown_kinds(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_bytes(b"{}")
    with pytest.raises(ValueError, match="secrets"):
        IngestionReceipt(
            provider_or_venue="bybit",
            endpoint="x",
            request_parameters={"api_key": "abc"},
            http_status=200,
            captured_at_utc="2026-07-24T23:00:00Z",
            adapter_name="a",
            adapter_version="1",
            raw_path=str(raw),
            raw_sha256="ab",
            normalized_rows_sha256="cd",
            source_kind="live",
        )
    with pytest.raises(ValueError, match="source_kind"):
        _receipt(raw, "totally_real_trust_me")


def test_backfill_writes_a_receipt_and_research_sees_test_only(tmp_path):
    from quant_trade.carry.backfill import run_backfill
    from quant_trade.evidence.receipts import load_receipts

    store = tmp_path / "history.jsonl"
    result = run_backfill(
        "bybit", "BTC", store, fixture_path="tests/fixtures/bybit_funding_history.json"
    )
    assert result.status == "OK"
    receipts = load_receipts(tmp_path / "receipts.jsonl")
    assert len(receipts) == 1
    assert receipts[0]["source_kind"] == "fixture"  # never live, never real
    assert receipts[0]["raw_sha256"] == result.raw_sha256
    assert json.loads(Path(result.raw_path).read_bytes()) is not None
