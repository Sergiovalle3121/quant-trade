"""Artifact generation: determinism, honest states, and the end-to-end flows.

The determinism test is the load-bearing one. An artifact set that changes
between two runs on the same inputs cannot be reviewed, because a reader
cannot tell a real change from noise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.evidence.canonical_json import sha256_of_file
from quant_trade.v9.artifacts import (
    ARTIFACT_NAMES,
    EVALUATED_AT_UTC,
    RECORDED_PROBE_FILENAME,
    artifact_fingerprint,
    generate_v9_artifacts,
)
from quant_trade.v9.economic_status import (
    ECONOMIC_STATES,
    MINING_STATES,
    REALIZED_PROFIT_STATE,
    V9_PERMITTED_STATES,
)
from quant_trade.v9.preregistration import V8_ERRATA, freeze_hash, preregistration

BLOCKED_PROBE = {
    "artifact": "V8_NETWORK_REACHABILITY_PROBE",
    "attempted_at_utc": "2026-07-28T19:36:28Z",
    "any_reachable": False,
    "reachable_venues": [],
    "blocked_venues": ["bybit", "okx"],
    "policy": "Only venue-published official domains are attempted.",
    "probes": [
        {
            "venue": "bybit",
            "host": "api.bybit.com",
            "url": "https://api.bybit.com/v5/market/time",
            "outcome": "BLOCKED_EGRESS_POLICY",
            "error": "URLError: <urlopen error Tunnel connection failed: 403 Forbidden>",
        },
        {
            "venue": "okx",
            "host": "www.okx.com",
            "url": "https://www.okx.com/api/v5/public/time",
            "outcome": "BLOCKED_EGRESS_POLICY",
            "error": "URLError: <urlopen error Tunnel connection failed: 403 Forbidden>",
        },
    ],
}


@pytest.fixture()
def generated(tmp_path: Path):
    out = tmp_path / "artifacts"
    out.mkdir()
    (out / RECORDED_PROBE_FILENAME).write_text(json.dumps(BLOCKED_PROBE), encoding="utf-8")
    result = generate_v9_artifacts(
        tmp_path,
        evidence_root=tmp_path / "evidence",
        out_dir=out,
        source_commit_sha="deadbeef",
    )
    return out, result


def test_every_required_artifact_is_produced(generated) -> None:
    out, result = generated
    for name in ARTIFACT_NAMES:
        assert (out / name).exists(), f"{name} was not generated"
    assert set(result.hashes) == set(ARTIFACT_NAMES)


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    """Two runs on the same inputs, compared byte for byte."""
    out = tmp_path / "artifacts"
    out.mkdir()
    (out / RECORDED_PROBE_FILENAME).write_text(json.dumps(BLOCKED_PROBE), encoding="utf-8")
    first = generate_v9_artifacts(
        tmp_path,
        evidence_root=tmp_path / "evidence",
        out_dir=out,
        source_commit_sha="deadbeef",
    )
    second = generate_v9_artifacts(
        tmp_path,
        evidence_root=tmp_path / "evidence",
        out_dir=out,
        source_commit_sha="deadbeef",
    )
    assert first.hashes == second.hashes
    assert artifact_fingerprint(first.hashes) == artifact_fingerprint(second.hashes)
    for name in ARTIFACT_NAMES:
        assert sha256_of_file(out / name) == first.hashes[name]


def test_the_generator_never_reads_its_own_output(tmp_path: Path) -> None:
    """Deleting a produced artifact must not change the next regeneration."""
    out = tmp_path / "artifacts"
    out.mkdir()
    (out / RECORDED_PROBE_FILENAME).write_text(json.dumps(BLOCKED_PROBE), encoding="utf-8")
    first = generate_v9_artifacts(
        tmp_path, evidence_root=tmp_path / "e", out_dir=out, source_commit_sha="deadbeef"
    )
    for name in ARTIFACT_NAMES:
        (out / name).unlink()
    second = generate_v9_artifacts(
        tmp_path, evidence_root=tmp_path / "e", out_dir=out, source_commit_sha="deadbeef"
    )
    assert first.hashes == second.hashes


def test_a_blocked_run_is_not_measured_not_no_edge(generated) -> None:
    out, result = generated
    assert result.trading_state == "NOT_MEASURED"
    campaigns = json.loads((out / "OOS_CAMPAIGN_RESULTS.json").read_text())
    assert {c["hypothesis_id"] for c in campaigns["campaigns"]} == {"H1", "H2", "H3"}
    for campaign in campaigns["campaigns"]:
        assert campaign["state"] == "NOT_MEASURED"
        assert campaign["measured"] is False
    assert "NO_EDGE_FOUND" not in (out / "OOS_CAMPAIGN_RESULTS.json").read_text()


#: Keys whose value is a claim about where something stands right now.
STATE_KEYS = ("state", "trading_state", "mining_state")

#: The one key that may quote a superseded claim: the errata record what V8
#: said in order to correct it, and redacting that would hide the correction.
QUOTATION_KEYS = ("v8_claim",)


def walk_states(node: object, path: str = "") -> list[tuple[str, str]]:
    """Every (path, value) pair under a state key, recursively."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in STATE_KEYS and isinstance(value, str):
                found.append((child, value))
            found.extend(walk_states(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(walk_states(value, f"{path}[{index}]"))
    return found


def test_no_artifact_uses_a_forbidden_state(generated) -> None:
    out, _ = generated
    permitted = set(V9_PERMITTED_STATES) | set(MINING_STATES)
    assert permitted <= set(ECONOMIC_STATES) | set(MINING_STATES)
    for name in ARTIFACT_NAMES:
        payload = json.loads((out / name).read_text())
        for path, state in walk_states(payload):
            assert state != REALIZED_PROFIT_STATE, f"{name}:{path} claims realized profit"
            assert state != "NO_EDGE_FOUND", f"{name}:{path} claims a result it does not have"
            assert state in permitted, f"{name}:{path} carries illegal state {state!r}"


def test_the_superseded_claim_appears_only_as_a_quotation(generated) -> None:
    """The errata quote what V8 said; nothing else may use the token."""
    out, _ = generated
    for name in ARTIFACT_NAMES:
        text = (out / name).read_text()
        if "NO_EDGE_FOUND" not in text:
            continue
        payload = json.loads(text)
        quoted = [
            e
            for e in payload.get("preregistration", {}).get("v8_errata", [])
            if any(e.get(key) == "NO_EDGE_FOUND" for key in QUOTATION_KEYS)
        ]
        assert quoted, f"{name} uses the token outside an erratum quotation"
        # Once quoted, the correction must sit beside it.
        assert all(e["correction"].startswith("NOT_MEASURED") for e in quoted)
        assert text.count("NO_EDGE_FOUND") == len(quoted)


def test_the_claim_guard_is_clean(generated) -> None:
    out, _ = generated
    guard = json.loads((out / "PROFIT_CLAIM_GUARD.json").read_text())
    assert guard["clean"] is True, guard["findings"]
    assert guard["realized_profit_state_present"] is False


def test_the_guard_does_not_scan_its_own_output(generated) -> None:
    """Otherwise the guard's own list of banned words would flag itself."""
    out, _ = generated
    guard = json.loads((out / "PROFIT_CLAIM_GUARD.json").read_text())
    assert "PROFIT_CLAIM_GUARD.json" not in guard["scanned_sources"]
    assert guard["scanned_sources"]


# The mining-route artifact tests (blocked-evidence gate, synthetic cashflow
# labelling, the thousandfold unit audit) retired with the route itself. The
# defects they pinned remain recorded in the sealed V9 errata (E9/E10), whose
# hash has not moved. See docs/MINING_RETIREMENT.md.


def test_no_mining_artifact_is_generated_any_more(generated) -> None:
    out, _ = generated
    leftovers = [p.name for p in out.glob("MINING_*.json")]
    leftovers += [p.name for p in out.glob("UNIT_CONVERSION_AUDIT.json")]
    assert not leftovers, f"retired mining artifacts reappeared: {leftovers}"


def test_the_sealed_preregistration_still_carries_the_mining_declaration(generated) -> None:
    """Retiring the route must not rewrite the sealed declaration.

    mining_gates and the E9/E10 errata are part of what was registered on
    2026-07-28; the route's retirement is documented outside the sealed
    content, so freeze_hash() must not move.
    """
    out, _ = generated
    manifest = json.loads((out / "REGENERATION_MANIFEST.json").read_text())
    assert manifest["preregistration_hash"] == freeze_hash()
    prereg = manifest["preregistration"]
    assert "mining_gates" in prereg, "the sealed declaration was edited"
    errata_ids = {e["erratum_id"] for e in prereg["v8_errata"]}
    assert {"E9", "E10"} <= errata_ids


def test_the_capital_curve_brackets_its_own_floor(generated) -> None:
    """A curve whose lowest rung passes has not measured a minimum."""
    out, _ = generated
    curve = json.loads((out / "SMALL_CAPITAL_FEASIBILITY.json").read_text())
    statuses = [s["status"] for s in curve["scenarios"]]
    assert "INSUFFICIENT_EXECUTABLE_CAPITAL" in statuses
    assert "EXECUTABLE" in statuses
    floor = curve["minimum_executable_capital_usd"]
    assert floor is not None
    below = [s for s in curve["scenarios"] if s["starting_capital_usd"] < floor]
    assert below and all(s["status"] == "INSUFFICIENT_EXECUTABLE_CAPITAL" for s in below)
    assert all(s["binding_constraint"] for s in below)
    # And it is nowhere near V8's claimed figure.
    assert floor < 1_000.0


def test_the_capital_curve_reports_no_returns_without_a_series(generated) -> None:
    out, _ = generated
    curve = json.loads((out / "SMALL_CAPITAL_FEASIBILITY.json").read_text())
    assert curve["oos_distribution_available"] is False
    for scenario in curve["scenarios"]:
        assert scenario["expected_return_on_capital"] is None
        assert scenario["p05_return_on_capital"] is None
        assert scenario["probability_of_ruin"] is None


def test_the_canary_is_blocked_and_names_every_reason(generated) -> None:
    out, _ = generated
    canary = json.loads((out / "CANARY_READINESS_V9.json").read_text())
    assert canary["status"] != "READY_PENDING_HUMAN_AUTHORISATION"
    assert canary["unblocked"] is False
    assert canary["canary_authorized"] is False
    assert canary["real_money_authorized"] is False
    assert canary["blocking_conditions"]
    assert canary["all_problems"]


def test_paper_is_not_started_and_says_why(generated) -> None:
    out, _ = generated
    paper = json.loads((out / "PAPER_DAEMON_STATUS.json").read_text())
    assert paper["status"] == "NOT_STARTED_NO_CANDIDATE"
    assert paper["wall_clock_seconds"] == 0.0
    assert paper["orders_submitted_live"] == 0
    assert paper["live_order_submission"] == "DISABLED"
    assert len(paper["commands"]) == 6


def test_blockers_are_external_and_carry_verbatim_evidence(generated) -> None:
    out, _ = generated
    blockers = json.loads((out / "BLOCKERS.json").read_text())
    ids = {b["blocker_id"] for b in blockers["blockers"]}
    assert {"B-EGRESS", "B-COST-EVIDENCE", "B-POOL-EVIDENCE"} <= ids
    egress = next(b for b in blockers["blockers"] if b["blocker_id"] == "B-EGRESS")
    assert any("403" in e or "BLOCKED" in e for e in egress["evidence"])
    assert "proxies" in egress["workarounds_refused"]


def test_the_manifest_records_the_boundary(generated) -> None:
    out, _ = generated
    manifest = json.loads((out / "REGENERATION_MANIFEST.json").read_text())
    safety = manifest["safety"]
    assert safety["live_order_submission"] == "DISABLED"
    assert safety["aws_alibaba_hashing"] == "PROHIBITED"
    assert safety["orders_submitted"] == 0
    assert safety["hashrate_purchased"] == 0
    assert safety["funds_moved_usd"] == 0.0
    assert safety["cloud_resources_created"] == 0
    assert safety["secrets_stored"] == 0
    assert manifest["preregistration_hash"] == freeze_hash()
    assert manifest["evaluated_at_utc"] == EVALUATED_AT_UTC


def test_the_manifest_hashes_cover_every_artifact(generated) -> None:
    out, _ = generated
    manifest = json.loads((out / "REGENERATION_MANIFEST.json").read_text())
    recorded = manifest["artifact_sha256"]
    for name in ARTIFACT_NAMES:
        if name == "REGENERATION_MANIFEST.json":
            continue  # cannot contain its own hash
        assert recorded[name] == sha256_of_file(out / name)


# --- pre-registration --------------------------------------------------------


def test_no_v8_gate_was_relaxed() -> None:
    from quant_trade.v8.preregistration import PROMOTION_GATES as V8_GATES

    v9 = preregistration().promotion_gates
    for name, value in V8_GATES.items():
        assert name in v9, f"V9 dropped the V8 gate {name}"
        if isinstance(value, bool):
            assert v9[name] == value
        elif isinstance(value, int | float):
            if name.startswith("max_"):
                assert v9[name] <= value, f"{name} was loosened"
            else:
                assert v9[name] >= value, f"{name} was loosened"
    assert preregistration().to_dict()["gates_relaxed_from_v8"] == []


def test_v9_adds_gates_for_each_defect_it_found() -> None:
    v9 = preregistration().promotion_gates
    for added in (
        "require_positive_holdout",
        "require_per_window_oos_selection",
        "require_hash_chained_trial_ledger",
        "require_nonzero_cross_trial_sharpe_variance",
        "forbid_caller_supplied_pnl",
        "forbid_injected_wall_clock",
    ):
        assert v9[added] is True


def test_the_errata_are_specific_and_traceable() -> None:
    assert len(V8_ERRATA) >= 11
    ids = [e.erratum_id for e in V8_ERRATA]
    assert len(set(ids)) == len(ids)
    for erratum in V8_ERRATA:
        assert erratum.v9_module.startswith("quant_trade.v9.")
        assert erratum.defect and erratum.correction and erratum.magnitude
        importlib_name = erratum.v9_module
        __import__(importlib_name)


def test_the_freeze_hash_moves_when_a_gate_moves(monkeypatch) -> None:
    baseline = freeze_hash()
    from quant_trade.v9 import preregistration as module

    monkeypatch.setitem(module.PROMOTION_GATES, "min_deflated_sharpe", 0.10)
    assert freeze_hash() != baseline


# --- CLI ---------------------------------------------------------------------


def test_the_artifacts_command_regenerates(tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    out.mkdir()
    (out / RECORDED_PROBE_FILENAME).write_text(json.dumps(BLOCKED_PROBE), encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "v9",
            "artifacts",
            "--repo-root",
            str(tmp_path),
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--out-dir",
            str(out),
            "--source-commit-sha",
            "deadbeef",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["trading_state"] == "NOT_MEASURED"
    assert payload["mining_state"] == "BLOCKED_EVIDENCE"


def test_the_acquisition_command_hands_back_a_runbook(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["v9", "acquisition-status", "--evidence-root", str(tmp_path / "nothing")]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["state"] == "NOT_MEASURED"
    assert payload["measured"] is False
    assert payload["operator_commands"]
    assert payload["import_command"]


def test_the_claim_guard_command_scans_docs_and_artifacts(generated) -> None:
    out, _ = generated
    runner = CliRunner()
    result = runner.invoke(
        app, ["v9", "claim-guard", "--artifact-dir", str(out), "--docs-dir", "docs"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["clean"] is True, payload["findings"]
    assert any(s.endswith(".md") for s in payload["scanned_sources"])
