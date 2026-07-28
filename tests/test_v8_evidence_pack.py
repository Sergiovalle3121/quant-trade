"""V8 evidence packs: determinism, corruption detection, import gating."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest
from v8_venue_fakes import FakeVenue, no_sleep

from quant_trade.evidence.canonical_json import load_json
from quant_trade.v8.backfill import BackfillRequest, run_backfill
from quant_trade.v8.evidence_pack import (
    MANIFEST_NAME,
    REDISTRIBUTION_STANCES,
    PackEntry,
    build_evidence_pack,
    import_evidence_pack,
    merkle_root,
    verify_evidence_pack,
)

HOUR = 3_600_000
START = 1_700_000_000_000 - (1_700_000_000_000 % HOUR)


def _evidence(tmp_path: Path, venue: str = "bybit", days: int = 5) -> str:
    until = START + days * 24 * HOUR
    fake = FakeVenue(venue=venue, start_ms=START, end_ms=until)
    request = BackfillRequest(venue=venue, symbol="BTC", since_ms=START, until_ms=until)
    result = run_backfill(
        request,
        tmp_path / "evidence",
        fetcher=fake.fetch,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        source_kind="recorded_test_response",
        captured_at_utc="2026-07-28T00:00:00Z",
    )
    return result.evidence_dir


def _pack(tmp_path: Path, sources: dict[str, str], out_name: str = "pack", **kwargs):
    out = tmp_path / out_name
    manifest = build_evidence_pack(
        sources,
        out,
        pack_id=kwargs.pop("pack_id", "test"),
        created_at_utc="2026-07-28T00:00:00Z",
        rebuild_command="quant-trade evidence backfill ...",
        **kwargs,
    )
    return manifest, out / manifest.archive_name, out / MANIFEST_NAME


# --- determinism ----------------------------------------------------------------


def test_pack_bytes_are_reproducible(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    first, _, _ = _pack(tmp_path, {"bybit_btc": source}, "a")
    second, _, _ = _pack(tmp_path, {"bybit_btc": source}, "b")
    assert first.archive_sha256 == second.archive_sha256
    assert first.merkle_root == second.merkle_root
    assert first.total_bytes == second.total_bytes


def test_archive_name_is_content_addressed(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    manifest, archive, _ = _pack(tmp_path, {"bybit_btc": source})
    assert manifest.archive_sha256[:16] in archive.name
    assert archive.name.endswith(".tar.gz")


def test_archive_carries_no_timestamps_or_ownership(tmp_path: Path) -> None:
    """Reproducibility dies if the tar records mtimes or the build user."""
    source = _evidence(tmp_path)
    _manifest, archive, _ = _pack(tmp_path, {"bybit_btc": source})
    with gzip.open(archive, "rb") as handle:
        raw = handle.read()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        members = tar.getmembers()
    assert members
    assert all(m.mtime == 0 and m.uid == 0 and m.gid == 0 for m in members)
    assert all(m.uname == "" and m.gname == "" for m in members)
    assert [m.name for m in members] == sorted(m.name for m in members)


def test_merkle_root_is_order_independent() -> None:
    entries = [
        PackEntry(path="b", sha256="2" * 64, bytes=1),
        PackEntry(path="a", sha256="1" * 64, bytes=1),
    ]
    assert merkle_root(entries) == merkle_root(list(reversed(entries)))


# --- verification ----------------------------------------------------------------


def test_pack_verifies_byte_for_byte_back_to_raw(tmp_path: Path) -> None:
    sources = {
        "bybit_btc": _evidence(tmp_path / "b", "bybit"),
        "okx_btc": _evidence(tmp_path / "o", "okx"),
    }
    manifest, archive, manifest_path = _pack(tmp_path, sources)
    report = verify_evidence_pack(archive, manifest_path)
    assert report.is_verified, report.problems
    assert report.files_matched == report.files_checked == len(manifest.entries)
    assert report.archive_sha256_matches
    assert report.merkle_root_matches
    assert report.receipt_chains_verified == 2
    assert report.pages_reparsed > 0
    assert report.series_rebuilt >= 10  # 5 series x 2 venues
    assert report.series_byte_mismatches == []


def test_a_flipped_byte_in_the_archive_is_caught(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    _manifest, archive, manifest_path = _pack(tmp_path, {"bybit_btc": source})
    payload = bytearray(archive.read_bytes())
    payload[-5] ^= 0xFF
    archive.write_bytes(bytes(payload))
    report = verify_evidence_pack(archive, manifest_path)
    assert not report.is_verified
    assert report.status == "CORRUPT"


def test_an_edited_manifest_entry_is_caught(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    _manifest, archive, manifest_path = _pack(tmp_path, {"bybit_btc": source})
    manifest = load_json(manifest_path)
    manifest["entries"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_evidence_pack(archive, manifest_path)
    assert not report.is_verified
    assert not report.merkle_root_matches


def test_a_missing_pack_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    report = verify_evidence_pack(tmp_path / "nope.tar.gz", tmp_path / "nope.json")
    assert report.status == "MISSING"
    assert not report.is_verified


def test_verification_rejects_a_reparse_that_no_longer_matches(tmp_path: Path) -> None:
    """If a raw page no longer produces the receipt's normalized rows, the
    evidence is not reproducible and the pack must fail."""
    source = Path(_evidence(tmp_path))
    receipts = source / "receipts.jsonl"
    lines = receipts.read_text().splitlines()
    doctored = []
    patched = False
    for line in lines:
        record = json.loads(line)
        if not patched and record.get("request_parameters", {}).get("kind") == "spot":
            record["normalized_rows_sha256"] = "0" * 64
            patched = True
        doctored.append(json.dumps(record, separators=(",", ":"), sort_keys=True))
    receipts.write_text("\n".join(doctored) + "\n", encoding="utf-8")
    _manifest, archive, manifest_path = _pack(tmp_path, {"bybit_btc": str(source)})
    report = verify_evidence_pack(archive, manifest_path)
    assert not report.is_verified
    assert any("normalized rows differ" in p for p in report.pages_reparse_mismatches)


# --- import gating ----------------------------------------------------------------


def test_import_extracts_only_a_verified_pack(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    _manifest, archive, manifest_path = _pack(tmp_path, {"bybit_btc": source})
    destination = tmp_path / "imported"
    report = import_evidence_pack(archive, manifest_path, destination)
    assert report.is_verified
    assert (destination / "bybit_btc" / "receipts.jsonl").exists()
    assert sorted(p.name for p in (destination / "bybit_btc" / "series").glob("*.jsonl"))


def test_import_of_a_corrupt_pack_writes_nothing(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    _manifest, archive, manifest_path = _pack(tmp_path, {"bybit_btc": source})
    payload = bytearray(archive.read_bytes())
    payload[-5] ^= 0xFF
    archive.write_bytes(bytes(payload))
    destination = tmp_path / "imported"
    report = import_evidence_pack(archive, manifest_path, destination)
    assert not report.is_verified
    assert not destination.exists()


# --- policy ------------------------------------------------------------------------


def test_redistribution_stance_defaults_to_unresolved_and_blocks_committing(
    tmp_path: Path,
) -> None:
    source = _evidence(tmp_path)
    manifest, _, _ = _pack(tmp_path, {"bybit_btc": source})
    assert manifest.redistribution["stance"] == "UNRESOLVED"
    assert manifest.redistribution["committable_to_git"] is False


def test_permitted_stance_is_explicit_and_documented(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    manifest, _, _ = _pack(
        tmp_path,
        {"bybit_btc": source},
        redistribution_stance="PERMITTED_DOCUMENTED",
        redistribution_reason="operator supplied written permission",
        redistribution_source_terms="https://example.invalid/terms",
    )
    assert manifest.redistribution["committable_to_git"] is True
    assert manifest.redistribution["source_terms"]


def test_unknown_redistribution_stance_is_rejected(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    with pytest.raises(ValueError, match="redistribution_stance"):
        _pack(tmp_path, {"bybit_btc": source}, redistribution_stance="probably fine")
    assert "UNRESOLVED" in REDISTRIBUTION_STANCES


def test_manifest_records_size_and_rebuild_command(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    manifest, _, manifest_path = _pack(tmp_path, {"bybit_btc": source})
    payload = load_json(manifest_path)
    assert payload["rebuild_command"].startswith("quant-trade evidence backfill")
    assert payload["total_bytes"] > 0
    assert payload["archive_bytes"] > 0
    assert payload["file_count"] == len(manifest.entries)
    assert payload["sources"][0]["files"] > 0


def test_pack_never_carries_credentials(tmp_path: Path) -> None:
    source = _evidence(tmp_path)
    manifest, archive, _ = _pack(tmp_path, {"bybit_btc": source})
    with gzip.open(archive, "rb") as handle:
        raw = handle.read()
    lowered = raw.lower()
    for secret in (b"api_key", b"apikey", b"secret", b"passphrase", b"private_key"):
        assert secret not in lowered
    assert all("/.env" not in e.path for e in manifest.entries)
