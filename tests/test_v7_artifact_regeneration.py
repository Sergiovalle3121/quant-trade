"""End-to-end deterministic regeneration of the V7 economic artifacts."""

from __future__ import annotations

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
    assert provenance["real_raw_data_captured"] == 5
    assert provenance["real_settlements_verified"] == 6
    assert provenance["real_local_uncommitted_capture"]["promotion_eligible"] is False
    assert shadow["status"] == "NOT_STARTED_NO_ELIGIBLE_NON_CASH_CANDIDATE"


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
