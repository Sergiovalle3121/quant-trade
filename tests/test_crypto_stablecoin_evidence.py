"""Offline adversarial tests for receipt-bound CMC stablecoin evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from quant_trade.data.crypto_stablecoin_evidence import (
    MANIFEST_FILENAME,
    MAXIMUM_CUTOFF,
    StablecoinEvidenceError,
    StablecoinEvidenceState,
    TagsShape,
    build_stablecoin_observations,
    load_stablecoin_observations,
)
from quant_trade.data.universe import SCHEMA_VERSION, UNIVERSE_POLICY, parse_snapshot_page
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
)

_MISSING = object()


def _entry(
    cmc_id: int,
    snapshot: date,
    *,
    tags: object = _MISSING,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": cmc_id,
        "name": f"Coin {cmc_id}",
        "symbol": f"C{cmc_id}",
        "cmcRank": cmc_id,
        "circulatingSupply": 1_000_000,
        "lastUpdated": f"{snapshot.isoformat()}T12:00:00.000Z",
        "quotes": [
            {
                "name": 2781,
                "marketCap": 20_000_000,
                "volume24h": 1_000_000,
                "lastUpdated": f"{snapshot.isoformat()}T12:00:00.000Z",
            }
        ],
    }
    if tags is not _MISSING:
        entry["tags"] = tags
    return entry


def _raw(
    snapshot: date,
    entries: list[dict[str, Any]],
    *,
    response_at: str = "2026-08-11T07:04:08.743Z",
) -> bytes:
    return canonical_dumps(
        {
            "data": entries,
            "status": {
                # Response publication/capture is intentionally later than the
                # requested historical snapshot.  The artifact must expose it.
                "timestamp": response_at,
            },
        }
    ).encode("utf-8")


def _append_page(
    source: Path,
    snapshot: date,
    entries: list[dict[str, Any]],
    *,
    start: int = 1,
    raw_path_override: str | None = None,
    raw_sha_override: str | None = None,
    response_at: str = "2026-08-11T07:04:08.743Z",
    captured_at: str = "2026-08-11T07:04:10Z",
) -> None:
    raw = _raw(snapshot, entries, response_at=response_at)
    sha = sha256_of_bytes(raw)
    raw_path = source / "raw" / f"{sha}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    append_receipt(
        source / "receipts.jsonl",
        IngestionReceipt(
            provider_or_venue="coinmarketcap",
            endpoint=str(UNIVERSE_POLICY["endpoint"]),
            request_parameters={"date": snapshot.isoformat(), "start": start},
            http_status=200,
            captured_at_utc=captured_at,
            adapter_name="data.universe.cmc_snapshots",
            adapter_version=str(SCHEMA_VERSION),
            raw_path=raw_path_override or f"raw/{sha}.json",
            raw_sha256=raw_sha_override or sha,
            normalized_rows_sha256=normalized_rows_sha256(parse_snapshot_page(raw)),
            source_kind="fixture",
        ),
    )


def _artifact_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_exact_tags_produce_positive_or_unknown_but_never_negative(tmp_path: Path) -> None:
    source, artifact = tmp_path / "source", tmp_path / "artifact"
    snapshot = date(2023, 11, 28)
    _append_page(
        source,
        snapshot,
        [
            _entry(1, snapshot, tags=["defi", "algorithmic-stablecoin", "MiXeD"]),
            _entry(2, snapshot, tags=["defi"]),
            _entry(3, snapshot, tags=None),
            _entry(4, snapshot),
        ],
    )

    result = build_stablecoin_observations(source, artifact, cutoff_date=snapshot)
    loaded = load_stablecoin_observations(artifact)
    rows = list(loaded.iter_observations())

    assert result.positive_observations == 1
    assert result.source_entries == 4
    assert result.unknown == 3
    assert rows[0].tags == ("defi", "algorithmic-stablecoin", "MiXeD")
    assert rows[0].evidence_state is StablecoinEvidenceState.STABLECOIN_POSITIVE
    assert StablecoinEvidenceState.NON_STABLE not in {row.evidence_state for row in rows}
    assert rows[0].effective_at_utc == "2023-11-28T12:00:00Z"
    coverage = loaded.manifest["days"][0]["page_coverage"][0]
    assert coverage["source_response_at_utcs"] == ["2026-08-11T07:04:08.743000Z"]
    assert coverage["source_captured_at_utcs"] == ["2026-08-11T07:04:10Z"]
    assert coverage["unknown_by_tags_shape"] == {
        TagsShape.ABSENT.value: 1,
        TagsShape.LIST.value: 1,
        TagsShape.NULL.value: 1,
    }
    assert len(coverage["unknown_evidence_sha256"]) == 64
    assert loaded.manifest["blocker_cleared"] is False
    assert loaded.manifest["status"] == "INSUFFICIENT_EVIDENCE"
    assert loaded.manifest["profitability_evidence"] is False


def test_retry_with_different_platform_and_timestamps_but_same_projection_passes(
    tmp_path: Path,
) -> None:
    source, artifact = tmp_path / "source", tmp_path / "artifact"
    snapshot = date(2022, 2, 25)
    first = _entry(7, snapshot, tags=["stablecoin", "defi"])
    second = {**first, "platform": {"name": "Ethereum", "token_address": "0xabc"}}
    _append_page(source, snapshot, [first])
    _append_page(
        source,
        snapshot,
        [second],
        response_at="2026-08-12T08:00:00Z",
        captured_at="2026-08-12T08:00:01Z",
    )

    build_stablecoin_observations(source, artifact, cutoff_date=snapshot)
    loaded = load_stablecoin_observations(artifact)
    coverage = loaded.manifest["days"][0]["page_coverage"][0]

    assert len(list(loaded.iter_observations())) == 1
    assert coverage["corroborating_receipts"] == 2
    assert len(coverage["source_raw_sha256s"]) == 2
    assert len(coverage["source_receipt_sha256s"]) == 2
    assert coverage["source_response_at_utcs"] == [
        "2026-08-11T07:04:08.743000Z",
        "2026-08-12T08:00:00Z",
    ]


def test_retry_with_changed_tag_fails_as_ambiguous_projection(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = date(2022, 2, 25)
    _append_page(source, snapshot, [_entry(7, snapshot, tags=["stablecoin"])])
    _append_page(
        source,
        snapshot,
        [_entry(7, snapshot, tags=["defi"])],
        response_at="2026-08-12T08:00:00Z",
    )

    with pytest.raises(StablecoinEvidenceError, match="ambiguous.*projections"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=snapshot)


def test_same_identity_is_not_forward_or_backfilled_between_dates(tmp_path: Path) -> None:
    source, artifact = tmp_path / "source", tmp_path / "artifact"
    first, second = date(2023, 11, 27), date(2023, 11, 28)
    _append_page(source, first, [_entry(7, first, tags=["stablecoin"])])
    _append_page(source, second, [_entry(7, second, tags=[])])

    build_stablecoin_observations(source, artifact, cutoff_date=second)
    loaded = load_stablecoin_observations(artifact)
    rows = list(loaded.iter_observations())

    assert [row.evidence_state for row in rows] == [StablecoinEvidenceState.STABLECOIN_POSITIVE]
    assert loaded.manifest["days"][0]["unknown"] == 0
    assert loaded.manifest["days"][1]["unknown"] == 1
    assert loaded.manifest["days"][1]["positive_observations"] == 0


def test_post_cutoff_receipt_raw_is_never_opened_and_changes_no_artifact_byte(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    cutoff = date(2023, 11, 28)
    _append_page(source, cutoff, [_entry(1, cutoff, tags=["stablecoin"])])
    before = tmp_path / "before"
    build_stablecoin_observations(source, before, cutoff_date=cutoff)

    future = date(2023, 11, 29)
    _append_page(
        source,
        future,
        [_entry(2, future, tags=["future-stablecoin-tag"])],
        raw_path_override="raw/does-not-exist.json",
        raw_sha_override="a" * 64,
    )
    after = tmp_path / "after"
    build_stablecoin_observations(source, after, cutoff_date=cutoff)

    assert _artifact_bytes(before) == _artifact_bytes(after)


def test_builder_rejects_raw_byte_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = date(2023, 11, 28)
    _append_page(source, snapshot, [_entry(1, snapshot, tags=["stablecoin"])])
    raw_path = next((source / "raw").glob("*.json"))
    raw_path.write_bytes(raw_path.read_bytes() + b" ")

    with pytest.raises(StablecoinEvidenceError, match="raw payload hash mismatch"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=snapshot)


def test_builder_rejects_receipt_content_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = date(2023, 11, 28)
    _append_page(source, snapshot, [_entry(1, snapshot)])
    receipts = source / "receipts.jsonl"
    record = json.loads(receipts.read_text(encoding="utf-8"))
    record["http_status"] = 201
    receipts.write_text(canonical_dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(StablecoinEvidenceError, match="complete source receipt chain"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=snapshot)


def test_complete_chain_is_verified_even_when_tamper_is_after_cutoff(tmp_path: Path) -> None:
    source = tmp_path / "source"
    cutoff, future = date(2023, 11, 28), date(2023, 11, 29)
    _append_page(source, cutoff, [_entry(1, cutoff, tags=["stablecoin"])])
    _append_page(source, future, [_entry(2, future)])
    receipts = source / "receipts.jsonl"
    records = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines()]
    records[-1]["endpoint"] = "tampered-after-cutoff"
    receipts.write_text(
        "".join(canonical_dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    with pytest.raises(StablecoinEvidenceError, match="complete source receipt chain"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=cutoff)


def test_builder_rejects_raw_effective_date_that_disagrees_with_request(tmp_path: Path) -> None:
    source = tmp_path / "source"
    requested = date(2023, 11, 28)
    wrong = date(2023, 11, 27)
    _append_page(source, requested, [_entry(1, wrong, tags=["stablecoin"])])

    with pytest.raises(StablecoinEvidenceError, match="does not bind to receipt request"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=requested)


def test_missing_request_date_binding_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = date(2023, 11, 28)
    _append_page(source, snapshot, [_entry(1, snapshot)])
    receipts = source / "receipts.jsonl"
    record = json.loads(receipts.read_text(encoding="utf-8"))
    del record["request_parameters"]["date"]
    receipt_payload = {key: value for key, value in record.items() if key != "receipt_sha256"}
    record["receipt_sha256"] = sha256_of_bytes(canonical_dumps(receipt_payload).encode("utf-8"))
    receipts.write_text(canonical_dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(StablecoinEvidenceError, match="request date"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=snapshot)


def test_cutoff_cannot_cross_protected_holdout(tmp_path: Path) -> None:
    with pytest.raises(StablecoinEvidenceError, match="protected holdout"):
        build_stablecoin_observations(
            tmp_path / "not-opened",
            tmp_path / "artifact",
            cutoff_date=date(2023, 11, 29),
        )
    assert date(2023, 11, 28) == MAXIMUM_CUTOFF


def test_malformed_tags_are_rejected_instead_of_guessed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = date(2023, 11, 28)
    _append_page(source, snapshot, [_entry(1, snapshot, tags="stablecoin")])

    with pytest.raises(StablecoinEvidenceError, match="tags must be null or a list"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=snapshot)


def test_receipt_raw_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = date(2023, 11, 28)
    _append_page(source, snapshot, [_entry(1, snapshot, tags=["stablecoin"])])
    original = next((source / "raw").glob("*.json"))
    linked = source / "raw" / "linked.json"
    try:
        linked.symlink_to(original)
    except OSError:
        pytest.skip("host policy does not permit creating a test symlink")
    receipts = source / "receipts.jsonl"
    record = json.loads(receipts.read_text(encoding="utf-8"))
    record["raw_path"] = "raw/linked.json"
    receipt_payload = {key: value for key, value in record.items() if key != "receipt_sha256"}
    record["receipt_sha256"] = sha256_of_bytes(canonical_dumps(receipt_payload).encode("utf-8"))
    receipts.write_text(canonical_dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(StablecoinEvidenceError, match="symlink"):
        build_stablecoin_observations(source, tmp_path / "artifact", cutoff_date=snapshot)


def test_loader_rehashes_day_files_and_rejects_unmanifested_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    snapshot = date(2023, 11, 28)
    _append_page(source, snapshot, [_entry(1, snapshot)])
    tampered = tmp_path / "tampered"
    build_stablecoin_observations(source, tampered, cutoff_date=snapshot)
    day_file = next((tampered / "days").glob("*.jsonl"))
    day_file.write_bytes(day_file.read_bytes() + b" ")
    with pytest.raises(StablecoinEvidenceError, match="day file hash mismatch"):
        load_stablecoin_observations(tampered)

    clean = tmp_path / "clean"
    build_stablecoin_observations(source, clean, cutoff_date=snapshot)
    (clean / "days" / "unmanifested.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(StablecoinEvidenceError, match="unmanifested"):
        load_stablecoin_observations(clean)


def test_loader_rejects_manifest_tampering(tmp_path: Path) -> None:
    source, artifact = tmp_path / "source", tmp_path / "artifact"
    snapshot = date(2023, 11, 28)
    _append_page(source, snapshot, [_entry(1, snapshot)])
    build_stablecoin_observations(source, artifact, cutoff_date=snapshot)
    manifest = artifact / MANIFEST_FILENAME
    manifest.write_bytes(manifest.read_bytes() + b" ")

    with pytest.raises(StablecoinEvidenceError, match="manifest hash mismatch"):
        load_stablecoin_observations(artifact)
