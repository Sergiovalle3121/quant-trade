from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from quant_trade.carry.panel import load_panel, verify_panel_bundle
from quant_trade.carry.panel_backfill import run_panel_backfill
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    load_receipts,
    normalized_rows_sha256,
    resolve_dir_provenance,
)

SINCE, UNTIL = 1784505600000, 1784649600000
FIXTURES = {
    "spot": "tests/fixtures/bybit_kline_spot.json",
    "perp": "tests/fixtures/bybit_kline_perp.json",
    "mark": "tests/fixtures/bybit_kline_mark.json",
    "index": "tests/fixtures/bybit_kline_index.json",
    "funding": "tests/fixtures/bybit_funding_history.json",
}


def _identity_receipt(raw: Path, *, kind: str = "live") -> IngestionReceipt:
    payload = json.loads(raw.read_bytes())
    return IngestionReceipt(
        provider_or_venue="local",
        endpoint="file",
        request_parameters={},
        http_status=200,
        captured_at_utc="2026-07-24T23:00:00Z",
        adapter_name="evidence.json.identity",
        adapter_version="1",
        raw_path=raw.name,
        raw_sha256=sha256_of_bytes(raw.read_bytes()),
        normalized_rows_sha256=normalized_rows_sha256([payload]),
        source_kind=kind,
    )


def _panel(tmp_path: Path) -> Path:
    out = tmp_path / "panel"
    result = run_panel_backfill(
        "bybit",
        "BTC",
        out,
        since_ms=SINCE,
        until_ms=UNTIL,
        fixture_pages=FIXTURES,
    )
    assert result.status == "OK"
    return out


def test_wrong_normalized_hash_fails_closed_with_intact_raw(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_text('{"page":1}', encoding="utf-8")
    receipt = replace(_identity_receipt(raw), normalized_rows_sha256="0" * 64)
    append_receipt(tmp_path / "receipts.jsonl", receipt)
    report = resolve_dir_provenance(tmp_path / "receipts.jsonl")
    assert report.provenance == "invalid"
    assert any("normalized rows" in problem for problem in report.problems)


def test_receipt_path_traversal_is_rejected(tmp_path):
    receipt_dir = tmp_path / "bundle"
    receipt_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"page":1}', encoding="utf-8")
    receipt = replace(_identity_receipt(outside), raw_path="../outside.json")
    append_receipt(receipt_dir / "receipts.jsonl", receipt)
    report = resolve_dir_provenance(receipt_dir / "receipts.jsonl")
    assert report.provenance == "invalid"
    assert any("traversal" in problem for problem in report.problems)


def test_fixture_relabel_breaks_receipt_hash_chain(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_text('{"page":1}', encoding="utf-8")
    receipts = tmp_path / "receipts.jsonl"
    append_receipt(receipts, _identity_receipt(raw, kind="fixture"))
    record = load_receipts(receipts)[0]
    record["source_kind"] = "live"
    receipts.write_text(canonical_dumps(record) + "\n", encoding="utf-8")
    report = resolve_dir_provenance(receipts)
    assert report.provenance == "invalid"
    assert any("receipt content hash mismatch" in problem for problem in report.problems)


def test_panel_paths_are_relative_and_clean_room_rebuild_is_exact(tmp_path):
    panel = _panel(tmp_path)
    receipts = load_receipts(panel / "receipts.jsonl")
    assert receipts
    assert all(not Path(record["raw_path"]).is_absolute() for record in receipts)
    assert all(str(record["raw_path"]).startswith("raw/") for record in receipts)
    rows, audit = verify_panel_bundle(panel)
    assert audit.is_clean
    assert rows == load_panel(panel)


@pytest.mark.parametrize("target", ["panel.jsonl", "panel_manifest.json"])
def test_panel_or_manifest_single_byte_tamper_fails_closed(tmp_path, target):
    panel = _panel(tmp_path)
    path = panel / target
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="panel"):
        load_panel(panel)


def test_incomplete_requested_range_blocks_panel(tmp_path):
    fixtures = dict(FIXTURES)
    payload = json.loads(Path(fixtures["perp"]).read_text(encoding="utf-8"))
    payload["result"]["list"] = payload["result"]["list"][1:]
    truncated = tmp_path / "perp_truncated.json"
    truncated.write_text(json.dumps(payload), encoding="utf-8")
    fixtures["perp"] = truncated
    result = run_panel_backfill(
        "bybit",
        "BTC",
        tmp_path / "panel",
        since_ms=SINCE,
        until_ms=UNTIL,
        fixture_pages=fixtures,
    )
    assert result.status == "OK"
    assert result.audit["is_clean"] is False
    with pytest.raises(ValueError, match="audit"):
        load_panel(tmp_path / "panel")
