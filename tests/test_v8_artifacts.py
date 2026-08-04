"""V8 artifact regeneration: determinism, honesty, and required content."""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_trade.evidence.canonical_json import atomic_write_json, load_json
from quant_trade.v8.artifacts import (
    ARTIFACT_NAMES,
    NETWORK_PROBE_FILENAME,
    OUTCOME_NO_EDGE,
    artifact_fingerprint,
    generate_v8_artifacts,
)
from quant_trade.v8.preregistration import PROMOTION_GATES, freeze_hash

BLOCKED_PROBE = {
    "artifact": "V8_NETWORK_REACHABILITY_PROBE",
    "attempted_at_utc": "2026-07-28T06:00:00Z",
    "probes": [
        {
            "venue": "bybit",
            "host": "api.bybit.com",
            "url": "https://api.bybit.com/v5/market/time",
            "role": "primary documented API domain",
            "outcome": "BLOCKED_EGRESS_POLICY",
            "error": "URLError: <urlopen error Tunnel connection failed: 403 Forbidden>",
        }
    ],
    "reachable_venues": [],
    "blocked_venues": ["bybit", "okx"],
    "any_reachable": False,
    "policy": "only venue-published official domains are attempted",
}


@pytest.fixture
def generated(tmp_path: Path):
    out = tmp_path / "artifacts"
    out.mkdir(parents=True)
    atomic_write_json(out / NETWORK_PROBE_FILENAME, BLOCKED_PROBE)
    result = generate_v8_artifacts(
        tmp_path,
        evidence_root=tmp_path / "evidence",
        out_dir=out,
        source_commit_sha="deadbeef",
    )
    return out, result


# --- determinism ------------------------------------------------------------------


def test_regenerating_twice_produces_identical_hashes(tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    out.mkdir(parents=True)
    atomic_write_json(out / NETWORK_PROBE_FILENAME, BLOCKED_PROBE)
    first = generate_v8_artifacts(
        tmp_path,
        evidence_root=tmp_path / "evidence",
        out_dir=out,
        source_commit_sha="deadbeef",
    )
    second = generate_v8_artifacts(
        tmp_path,
        evidence_root=tmp_path / "evidence",
        out_dir=out,
        source_commit_sha="deadbeef",
    )
    assert first.hashes == second.hashes
    assert artifact_fingerprint(first.hashes) == artifact_fingerprint(second.hashes)


def test_every_required_artifact_is_written(generated) -> None:
    out, result = generated
    for name in ARTIFACT_NAMES:
        assert (out / name).exists(), name
        assert name in result.hashes


def test_the_manifest_records_every_artifact_hash(generated) -> None:
    out, result = generated
    manifest = load_json(out / "REGENERATION_MANIFEST.json")
    for name in ARTIFACT_NAMES:
        if name == "REGENERATION_MANIFEST.json":
            continue
        assert manifest["artifact_sha256"][name] == result.hashes[name]
    assert manifest["source_commit_sha"] == "deadbeef"
    assert manifest["preregistration_hash"] == freeze_hash()


# --- honesty ------------------------------------------------------------------------


def test_no_evidence_yields_no_edge_found_not_a_loss(generated) -> None:
    _out, result = generated
    assert result.outcome == OUTCOME_NO_EDGE
    for campaign in result.campaigns:
        assert not campaign.ran
        assert any(
            "acquisition failure, not an economic verdict" in reason
            for reason in campaign.blocking_reasons
        )


def test_unmeasured_rows_are_never_ranked(generated) -> None:
    out, _result = generated
    leaderboard = load_json(out / "TRADING_LEADERBOARD.json")
    assert leaderboard["winner"] is None
    for row in leaderboard["rows"]:
        assert row["measured"] is False
        assert row["rank"] is None


def test_the_diagnosis_quantifies_break_even_even_without_data(generated) -> None:
    out, _result = generated
    diagnosis = load_json(out / "NO_EDGE_DIAGNOSIS.json")
    assert len(diagnosis["candidates"]) == 3
    for candidate in diagnosis["candidates"]:
        assert candidate["measured"] is False
        assert candidate["net_return"] is None
        break_even = candidate["break_even"]
        assert break_even["required_funding_rate_per_8h_1x"] > 0
        assert break_even["required_funding_rate_per_8h_3x"] == pytest.approx(
            break_even["required_funding_rate_per_8h_1x"] * 3
        )
        assert candidate["minimum_capital_usd"] > 0
        assert candidate["what_would_have_to_change"]


def test_the_diagnosis_pre_registers_the_next_experiment(generated) -> None:
    out, _result = generated
    diagnosis = load_json(out / "NO_EDGE_DIAGNOSIS.json")
    experiment = diagnosis["next_preregistered_experiment"]
    assert experiment["experiment_id"] == "V9-E1"
    assert experiment["preconditions"]
    assert experiment["falsifier"]
    assert freeze_hash() in experiment["frozen_parameters"]


def test_the_evidence_index_records_the_acquisition_blocker(generated) -> None:
    out, _result = generated
    index = load_json(out / "EVIDENCE_INDEX.json")
    assert index["totals"]["raw_pages"] == 0
    assert index["totals"]["unique_settlements"] == 0
    assert index["acquisition_blocker"]["blocked_venues"] == ["bybit", "okx"]
    assert index["requirements"]["min_span_days"] == PROMOTION_GATES["min_span_days"]
    assert index["rebuild_command"]


def test_cash_holds_the_entire_allocation(generated) -> None:
    out, _result = generated
    board = load_json(out / "UNIFIED_OPPORTUNITY_BOARD.json")
    assert board["allocation"]["cash_weight"] == 1.0
    assert board["allocation"]["non_cash_weight"] == 0.0
    assert board["allocation"]["real_money_authorized"] is False
    assert all(row["allocation_weight"] == 0.0 for row in board["rows"] if row["kind"] != "CASH")


def test_paper_status_reports_nothing_running(generated) -> None:
    out, _result = generated
    paper = load_json(out / "PAPER_STATUS.json")
    assert paper["status"] == "NOT_STARTED_NO_CANDIDATE"
    assert paper["wall_clock_seconds"] == 0.0
    assert paper["simulated_span_days"] == 0.0
    assert "H1=NOT_RUN_NO_EVIDENCE" in paper["reason"]


def test_canary_is_blocked_and_authorises_nothing(generated) -> None:
    out, _result = generated
    canary = load_json(out / "CANARY_READINESS.json")
    assert canary["status"] == "BLOCKED"
    assert canary["canary_authorized"] is False
    assert canary["real_money_authorized"] is False
    assert len(canary["blocking_conditions"]) == 6


def test_no_mining_artifact_is_generated_any_more(generated) -> None:
    """The marketplace scan retired with the hashrate route."""
    out, _result = generated
    leftovers = [p.name for p in out.glob("MINING_*.json")]
    assert not leftovers, f"retired mining artifacts reappeared: {leftovers}"
    board = load_json(out / "UNIFIED_OPPORTUNITY_BOARD.json")
    kinds = {row["kind"] for row in board["rows"]}
    assert "MINING_MARKETPLACE" not in kinds


def test_the_regeneration_manifest_reports_zero_spend(generated) -> None:
    out, _result = generated
    manifest = load_json(out / "REGENERATION_MANIFEST.json")
    safety = manifest["safety"]
    assert safety["orders_submitted"] == 0
    assert safety["deposits"] == 0
    assert safety["withdrawals"] == 0
    assert safety["cloud_resources_created"] == 0
    assert safety["miners_started"] == 0
    assert safety["real_money_authorized"] is False


def test_the_preregistration_artifact_carries_the_frozen_gates(generated) -> None:
    out, _result = generated
    payload = load_json(out / "V8_PREREGISTRATION.json")
    assert payload["freeze_hash"] == freeze_hash()
    assert payload["gates"] == PROMOTION_GATES
    assert [h["hypothesis_id"] for h in payload["hypotheses"]] == [
        "H1",
        "H2",
        "H3",
        "H6",
        "H7",
    ]


def test_additional_hypotheses_are_reported_as_locked(generated) -> None:
    out, _result = generated
    campaigns = load_json(out / "REAL_TRADING_CAMPAIGNS.json")
    additional = campaigns["additional_hypotheses"]
    assert additional["unlocked"] is False
    assert additional["executed"] == []
    assert "did not run for want of evidence" in additional["reason"]
