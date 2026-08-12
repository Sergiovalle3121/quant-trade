"""Tests for the durable holdout seal: binding to bytes, refusing rewrites,
refusing overlap, guarding research dates, and revealing exactly once."""

from __future__ import annotations

import json

import pytest

from quant_trade.data.crypto_manifest import CausalValidationEvidence, CryptoDatasetManifest
from quant_trade.ops.crypto_gates import Gate0Evidence, VenuePolicy, evaluate_gate0
from quant_trade.research.holdout_seal import (
    CRYPTO_AUTHORIZATION_FIELD,
    INVALIDATION_FILENAME,
    SEAL_FILENAME,
    HoldoutSeal,
    HoldoutSealError,
    assert_dataset_not_invalidated,
    assert_not_revealed,
    assert_within_selection,
    dataset_digest,
    invalidation_seal,
    load_crypto_holdout_authorization,
    load_invalidation,
    load_seal,
    read_reveals,
    record_reveal,
    seal_crypto_holdout,
    seal_holdout,
    verify_against_dataset,
)

COMPONENTS = {"2020-01-01": "a" * 64, "2020-01-02": "b" * 64}


def _seal(**overrides) -> HoldoutSeal:
    kwargs = dict(
        seal_id="etf_v1",
        dataset_id="etf_universe_v1",
        dataset_digest=dataset_digest(COMPONENTS),
        selection_start="2017-08-17",
        selection_end="2023-11-30",
        holdout_start="2023-12-01",
        holdout_end="2026-08-09",
        rationale="final 30% reserved; regime asymmetry declared",
        sealed_at_utc="2026-08-11T06:00:00Z",
    )
    kwargs.update(overrides)
    return HoldoutSeal(**kwargs)  # type: ignore[arg-type]


def _gate0(**overrides):
    values = {
        "venue": "bybit",
        "environment": "demo",
        "kyc_mexico_approved": True,
        "contractual_entity_identified": True,
        "spot_account_enabled": True,
        "api_access_enabled": True,
        "dedicated_subaccount_active": True,
        "ip_allowlist_active": True,
        "read_permission_enabled": True,
        "spot_permission_enabled": True,
        "withdrawal_permission_disabled": True,
        "transfer_permission_disabled": True,
        "margin_permission_disabled": True,
        "derivatives_permission_disabled": True,
        "loan_permission_disabled": True,
        "fee_rate_captured_per_symbol": True,
        "minimum_deposit_test_passed": True,
        "minimum_withdrawal_test_passed": True,
        "dataset_venue": "bybit",
        "cost_venue": "bybit",
        "planned_execution_venue": "bybit",
    }
    values.update(overrides)
    return evaluate_gate0(VenuePolicy(), Gate0Evidence(**values))


def _crypto_inputs(tmp_path):
    provenance = tmp_path / "provenance"
    provenance.mkdir()
    panel = provenance / "panel.csv"
    journal = provenance / "journal.jsonl"
    panel.write_bytes(b"causal panel")
    journal.write_bytes(b"collector journal")
    from quant_trade.data.crypto_manifest import component_hashes

    manifest = CryptoDatasetManifest(
        dataset_id="crypto_bybit_causal_v2",
        status="TRUSTED_CAUSAL",
        venue="bybit",
        market="spot",
        quote_asset="USDT",
        timezone="UTC",
        start_date="2017-08-17",
        end_date="2026-08-09",
        rows=100,
        instruments=5,
        schema_version=2,
        code_commit="a" * 40,
        policy={"rank_ceiling": 1000},
        components=component_hashes({"panel": panel, "journal": journal}),
        component_provenance={"panel": "panel.csv", "journal": "journal.jsonl"},
        causal_validation=CausalValidationEvidence(
            prefix_invariance_passed=True,
            fixed_venue_passed=True,
            stable_identity_and_rename_passed=True,
            unique_and_ambiguous_price_binding_passed=True,
            causal_warmup_passed=True,
            rank_exit_reentry_passed=True,
            gap_and_halt_semantics_passed=True,
            explicit_delisting_semantics_passed=True,
        ),
        gap_summary={"unexplained": 0},
        terms_status="UNRESOLVED_NO_REDISTRIBUTION",
    )
    seal = _seal(
        seal_id="crypto_bybit_causal_v2",
        dataset_id=manifest.dataset_id,
        dataset_digest=manifest.digest(),
    )
    return manifest, provenance, panel, seal, _gate0()


def test_digest_changes_when_any_member_changes() -> None:
    base = dataset_digest(COMPONENTS)
    assert dataset_digest({**COMPONENTS, "2020-01-02": "c" * 64}) != base
    assert dataset_digest({**COMPONENTS, "2020-01-03": "d" * 64}) != base
    assert dataset_digest({"2020-01-01": "a" * 64}) != base
    assert dataset_digest(dict(reversed(list(COMPONENTS.items())))) == base


def test_empty_dataset_cannot_be_sealed() -> None:
    with pytest.raises(HoldoutSealError, match="constrains nothing"):
        dataset_digest({})


def test_overlapping_sections_are_not_a_holdout() -> None:
    with pytest.raises(HoldoutSealError, match="overlapping"):
        _seal(holdout_start="2023-11-30")


def test_rationale_is_required() -> None:
    with pytest.raises(HoldoutSealError, match="rationale"):
        _seal(rationale="   ")


def test_seal_is_stable_and_excludes_metadata() -> None:
    assert _seal().seal() == _seal().seal()
    assert _seal(notes=["anything"]).seal() == _seal().seal()
    assert _seal(rationale="different").seal() != _seal().seal()


def test_a_sealed_holdout_is_never_rewritten(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    with pytest.raises(HoldoutSealError, match="never rewritten"):
        seal_holdout(tmp_path, _seal(holdout_start="2024-01-01"))


def test_editing_the_file_breaks_the_seal(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    path = tmp_path / SEAL_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["holdout_start"] = "2025-01-01"  # move the boundary after the fact
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HoldoutSealError, match="edited after sealing"):
        load_seal(tmp_path)


def test_a_changed_dataset_fails_closed(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    loaded = load_seal(tmp_path)
    verify_against_dataset(loaded, COMPONENTS)  # unchanged: fine
    with pytest.raises(HoldoutSealError, match="changed after sealing"):
        verify_against_dataset(loaded, {**COMPONENTS, "2020-01-03": "e" * 64})


def test_research_dates_reaching_into_the_holdout_raise() -> None:
    seal = _seal()
    assert_within_selection(seal, ["2017-08-17", "2020-06-01", "2023-11-30"])
    with pytest.raises(HoldoutSealError, match="outside the selection window"):
        assert_within_selection(seal, ["2023-11-30", "2023-12-01"])


def test_reveal_happens_once_and_names_what_it_judges(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    assert_not_revealed(tmp_path)
    record = record_reveal(
        tmp_path,
        reason="final evaluation of the single selected candidate",
        at_utc="2026-08-11T07:00:00Z",
        frozen_selection={"strategy": "xs_momentum", "trial_id": "t7"},
    )
    assert record["frozen_selection"]["trial_id"] == "t7"
    assert len(read_reveals(tmp_path)) == 1
    with pytest.raises(HoldoutSealError, match="already revealed"):
        assert_not_revealed(tmp_path)
    with pytest.raises(HoldoutSealError, match="already revealed"):
        record_reveal(
            tmp_path,
            reason="just one more look",
            at_utc="2026-08-11T08:00:00Z",
            frozen_selection={"strategy": "other"},
        )


def test_a_reveal_that_cannot_say_what_it_tests_is_refused(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    with pytest.raises(HoldoutSealError, match="already-frozen selection"):
        record_reveal(
            tmp_path,
            reason="curiosity",
            at_utc="2026-08-11T07:00:00Z",
            frozen_selection={},
        )
    assert read_reveals(tmp_path) == []  # a refused reveal leaves no trace of use


def test_reveal_requires_a_seal_to_exist(tmp_path) -> None:
    with pytest.raises(HoldoutSealError, match="no sealed holdout"):
        record_reveal(
            tmp_path,
            reason="x",
            at_utc="2026-08-11T07:00:00Z",
            frozen_selection={"strategy": "y"},
        )


def test_invalidated_dataset_keeps_history_but_cannot_be_revealed(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    invalidation = {
        "status": "INVALID_LOOKAHEAD",
        "dataset_digest": _seal().dataset_digest,
        "reasons": ["future venue selection", "future minimum-bar filter"],
    }
    invalidation["seal"] = invalidation_seal(invalidation)
    (tmp_path / INVALIDATION_FILENAME).write_text(
        json.dumps(invalidation),
        encoding="utf-8",
    )
    assert load_seal(tmp_path).seal_id == "etf_v1"
    with pytest.raises(HoldoutSealError, match="not usable or revealable"):
        record_reveal(
            tmp_path,
            reason="must fail",
            at_utc="2026-08-11T07:00:00Z",
            frozen_selection={"strategy": "crypto_h1"},
        )


def test_invalidated_digest_cannot_be_sealed_again(tmp_path) -> None:
    invalidation = {
        "status": "INVALID_LOOKAHEAD",
        "dataset_digest": _seal().dataset_digest,
        "reasons": ["causal audit failed"],
    }
    invalidation["seal"] = invalidation_seal(invalidation)
    (tmp_path / INVALIDATION_FILENAME).write_text(
        json.dumps(invalidation),
        encoding="utf-8",
    )
    with pytest.raises(HoldoutSealError, match="INVALID_LOOKAHEAD"):
        seal_holdout(tmp_path, _seal())


def test_legacy_crypto_holdout_entry_is_blocked(tmp_path) -> None:
    with pytest.raises(HoldoutSealError, match="legacy seal_holdout is blocked for crypto"):
        seal_holdout(
            tmp_path,
            _seal(seal_id="crypto_old", dataset_id="crypto_old"),
        )


def test_protected_crypto_holdout_binds_manifest_gate0_and_component_bytes(tmp_path) -> None:
    manifest, provenance, _panel, seal, gate0 = _crypto_inputs(tmp_path)

    seal_crypto_holdout(
        tmp_path,
        seal,
        manifest=manifest,
        provenance_root=provenance,
        manifest_digest=manifest.digest(),
        gate0_verdict=gate0,
        gate0_verdict_digest=gate0.digest(),
        gate0_evidence_digest=gate0.evidence_digest(),
    )
    authorization = load_crypto_holdout_authorization(tmp_path)
    assert authorization.manifest_status == "TRUSTED_CAUSAL"
    assert authorization.manifest_digest == manifest.digest()
    assert authorization.gate0_status == "PASS"
    assert authorization.gate0_verdict_digest == gate0.digest()
    payload = json.loads((tmp_path / SEAL_FILENAME).read_text(encoding="utf-8"))
    assert CRYPTO_AUTHORIZATION_FIELD in payload


def test_protected_crypto_holdout_rejects_untrusted_or_mismatched_bindings(tmp_path) -> None:
    manifest, provenance, _panel, seal, gate0 = _crypto_inputs(tmp_path)
    blocked_gate0 = _gate0(ip_allowlist_active=False)

    with pytest.raises(HoldoutSealError, match="Gate 0 blocks"):
        seal_crypto_holdout(
            tmp_path,
            seal,
            manifest=manifest,
            provenance_root=provenance,
            manifest_digest=manifest.digest(),
            gate0_verdict=blocked_gate0,
            gate0_verdict_digest=blocked_gate0.digest(),
            gate0_evidence_digest=blocked_gate0.evidence_digest(),
        )
    with pytest.raises(HoldoutSealError, match="provided manifest_digest"):
        seal_crypto_holdout(
            tmp_path,
            seal,
            manifest=manifest,
            provenance_root=provenance,
            manifest_digest="f" * 64,
            gate0_verdict=gate0,
            gate0_verdict_digest=gate0.digest(),
            gate0_evidence_digest=gate0.evidence_digest(),
        )
    with pytest.raises(HoldoutSealError, match="Gate 0 evidence digest"):
        seal_crypto_holdout(
            tmp_path,
            seal,
            manifest=manifest,
            provenance_root=provenance,
            manifest_digest=manifest.digest(),
            gate0_verdict=gate0,
            gate0_verdict_digest=gate0.digest(),
            gate0_evidence_digest="f" * 64,
        )


def test_protected_crypto_holdout_rehashes_components_at_sealing(tmp_path) -> None:
    manifest, provenance, panel, seal, gate0 = _crypto_inputs(tmp_path)
    panel.write_bytes(b"changed after manifest")

    with pytest.raises(HoldoutSealError, match="component bytes"):
        seal_crypto_holdout(
            tmp_path,
            seal,
            manifest=manifest,
            provenance_root=provenance,
            manifest_digest=manifest.digest(),
            gate0_verdict=gate0,
            gate0_verdict_digest=gate0.digest(),
            gate0_evidence_digest=gate0.evidence_digest(),
        )


def test_tampered_crypto_authorization_cannot_be_loaded_or_revealed(tmp_path) -> None:
    manifest, provenance, _panel, seal, gate0 = _crypto_inputs(tmp_path)
    seal_crypto_holdout(
        tmp_path,
        seal,
        manifest=manifest,
        provenance_root=provenance,
        manifest_digest=manifest.digest(),
        gate0_verdict=gate0,
        gate0_verdict_digest=gate0.digest(),
        gate0_evidence_digest=gate0.evidence_digest(),
    )
    path = tmp_path / SEAL_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[CRYPTO_AUTHORIZATION_FIELD]["gate0_evidence_digest"] = "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HoldoutSealError, match="authorization digest mismatch"):
        load_crypto_holdout_authorization(tmp_path)
    with pytest.raises(HoldoutSealError, match="authorization digest mismatch"):
        record_reveal(
            tmp_path,
            reason="final evaluation",
            at_utc="2026-08-12T08:00:00Z",
            frozen_selection={"strategy": "h1"},
        )


def test_invalidation_blocks_primary_and_superseded_dataset_digests(tmp_path) -> None:
    primary = "a" * 64
    superseded = "b" * 64
    invalidation = {
        "status": "INVALID_LOOKAHEAD",
        "dataset_digest": primary,
        "superseded_dataset_digests": [superseded],
        "reasons": ["causal audit failed"],
    }
    invalidation["seal"] = invalidation_seal(invalidation)
    (tmp_path / INVALIDATION_FILENAME).write_text(json.dumps(invalidation), encoding="utf-8")

    for digest in (primary, superseded):
        with pytest.raises(HoldoutSealError, match="not usable or revealable"):
            assert_dataset_not_invalidated(tmp_path, digest)


def test_invalidation_verifies_named_historical_holdout_artifact(tmp_path) -> None:
    seal_holdout(tmp_path, _seal())
    invalidation = {
        "status": "INVALID_LOOKAHEAD",
        "dataset_digest": _seal().dataset_digest,
        "invalidated_artifacts": {
            "holdout_seal": _seal().seal(),
            "experiment_preregistrations": [],
        },
        "reasons": ["causal audit failed"],
    }
    invalidation["seal"] = invalidation_seal(invalidation)
    invalidation_path = tmp_path / INVALIDATION_FILENAME
    invalidation_path.write_text(json.dumps(invalidation), encoding="utf-8")
    assert load_invalidation(tmp_path) is not None

    invalidation["invalidated_artifacts"]["holdout_seal"] = "f" * 64
    invalidation["seal"] = invalidation_seal(invalidation)
    invalidation_path.write_text(json.dumps(invalidation), encoding="utf-8")
    with pytest.raises(HoldoutSealError, match="does not match"):
        load_invalidation(tmp_path)


def test_invalidation_rejects_a_missing_named_preregistration_artifact(tmp_path) -> None:
    invalidation = {
        "status": "INVALID_LOOKAHEAD",
        "dataset_digest": "a" * 64,
        "invalidated_artifacts": {
            "experiment_preregistrations": ["crypto_h1_missing"],
        },
        "reasons": ["causal audit failed"],
    }
    invalidation["seal"] = invalidation_seal(invalidation)
    (tmp_path / INVALIDATION_FILENAME).write_text(json.dumps(invalidation), encoding="utf-8")

    with pytest.raises(HoldoutSealError, match="missing or corrupt"):
        load_invalidation(tmp_path)
