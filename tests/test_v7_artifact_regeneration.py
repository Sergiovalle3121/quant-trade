"""End-to-end deterministic regeneration of the V7 economic artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from quant_trade.evidence.canonical_json import load_json, sha256_of_file
from quant_trade.v7_artifacts import ARTIFACT_NAMES, generate_v7_artifacts


def test_v7_artifacts_regenerate_byte_identically(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    kwargs = {
        "repo_root": Path("."),
        "source_commit_sha": "11" * 20,
    }
    generate_v7_artifacts(output_dir=first, **kwargs)
    generate_v7_artifacts(output_dir=second, **kwargs)
    assert {path.name for path in first.iterdir()} == set(ARTIFACT_NAMES)
    assert {path.name: sha256_of_file(path) for path in sorted(first.iterdir())} == {
        path.name: sha256_of_file(path) for path in sorted(second.iterdir())
    }


def test_v7_board_is_honestly_all_cash_and_non_promotable(tmp_path) -> None:
    generate_v7_artifacts(
        repo_root=Path("."),
        output_dir=tmp_path,
        source_commit_sha="22" * 20,
    )
    board = load_json(tmp_path / "UNIFIED_OPPORTUNITY_BOARD.json")
    allocation = load_json(tmp_path / "PAPER_ALLOCATION.json")
    provenance = load_json(tmp_path / "DATA_PROVENANCE_REPORT.json")
    shadow = load_json(tmp_path / "SHADOW_STATUS.json")

    assert board["champion"]["entry_id"] == "cash_usd"
    assert board["cash_evidence"]["evidence_class"] == "RECORDED_RESPONSE"
    assert board["cash_evidence_promotable"] is False
    assert allocation["allocations"][0]["fraction"] == 1.0
    assert shadow["status"] == "NOT_STARTED_NO_ELIGIBLE_NON_CASH_CANDIDATE"

    # The provenance report must declare how good its evidence is, and must not
    # assert a capture that the recorded attempts contradict. Asserting the old
    # literals (5 raw captures, 6 verified settlements) pinned the fabrication:
    # correcting the artifact would have turned the suite red.
    assert provenance["evidence_class"] == "NOT_MEASURED"
    assert provenance["real_raw_data_captured"] is None
    assert provenance["real_settlements_verified"] is None
    assert provenance["real_local_uncommitted_capture"] is None
    assert provenance["withdrawn_claims"]


def test_v7_provenance_state_agrees_with_the_recorded_backfill_attempts(tmp_path) -> None:
    """No claim of captured real data may outlive the attempts that recorded it."""
    generate_v7_artifacts(
        repo_root=Path("."),
        output_dir=tmp_path,
        source_commit_sha="33" * 20,
    )
    provenance = load_json(tmp_path / "DATA_PROVENANCE_REPORT.json")

    attempts = provenance["backfill_attempts"]
    assert attempts, "the report must read the recorded attempts, not assert around them"

    settled = 0
    for attempt in attempts:
        record = attempt["last_record"]
        if not record:
            continue
        settled += int(json.loads(record).get("settlements", 0) or 0)

    # Every recorded attempt today is NOT_RUN_NETWORK_BLOCKED with 0 settlements,
    # so the report is only honest while it measures nothing.
    if settled == 0:
        assert provenance["evidence_class"] == "NOT_MEASURED"
        assert provenance["real_settlements_verified"] is None
    else:
        assert provenance["real_settlements_verified"] == settled


def test_committed_v7_artifacts_match_the_documented_regeneration(tmp_path) -> None:
    committed = Path("artifacts/v7")
    reproducibility = load_json(committed / "PROMOTION_REPRODUCIBILITY.json")
    generate_v7_artifacts(
        repo_root=Path("."),
        output_dir=tmp_path,
        source_commit_sha=reproducibility["source_commit_sha"],
    )
    assert {name: sha256_of_file(committed / name) for name in ARTIFACT_NAMES} == {
        name: sha256_of_file(tmp_path / name) for name in ARTIFACT_NAMES
    }
