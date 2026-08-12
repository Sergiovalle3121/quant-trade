from __future__ import annotations

import json
from dataclasses import replace

import pytest

from quant_trade.data.crypto_manifest import (
    CausalValidationEvidence,
    CryptoDatasetManifest,
    CryptoManifestError,
    component_hashes,
    load_manifest,
    write_manifest,
)


def _validation(passed: bool = True) -> CausalValidationEvidence:
    return CausalValidationEvidence(
        prefix_invariance_passed=passed,
        fixed_venue_passed=passed,
        stable_identity_and_rename_passed=passed,
        unique_and_ambiguous_price_binding_passed=passed,
        causal_warmup_passed=passed,
        rank_exit_reentry_passed=passed,
        gap_and_halt_semantics_passed=passed,
        explicit_delisting_semantics_passed=passed,
    )


def _manifest(**overrides) -> CryptoDatasetManifest:
    payload = {
        "dataset_id": "crypto_bybit_causal_v2",
        "status": "TRUSTED_CAUSAL",
        "venue": "bybit",
        "market": "spot",
        "quote_asset": "USDT",
        "timezone": "UTC",
        "start_date": "2021-07-05",
        "end_date": "2023-11-28",
        "rows": 100,
        "instruments": 5,
        "schema_version": 2,
        "code_commit": "a" * 40,
        "policy": {"rank_ceiling": 1000, "market_cap_usd": [10e6, 1e9]},
        "components": {"panel/csv": "b" * 64, "journal/bybit": "c" * 64},
        "component_provenance": {
            "panel/csv": "panel.csv",
            "journal/bybit": "journal.jsonl",
        },
        "causal_validation": _validation(),
        "gap_summary": {"unexplained": 0},
        "terms_status": "UNRESOLVED_NO_REDISTRIBUTION",
    }
    payload.update(overrides)
    return CryptoDatasetManifest(**payload)


def test_trusted_manifest_is_hash_stable_and_allows_research_gate() -> None:
    manifest = _manifest()
    assert manifest.digest() == _manifest().digest()
    assert len(manifest.digest()) == 64
    manifest.require_trusted("pnl_generation")


def test_trust_claim_requires_every_adversarial_check() -> None:
    with pytest.raises(CryptoManifestError, match="every adversarial"):
        _manifest(causal_validation=_validation(False))
    unvalidated = _manifest(status="UNVALIDATED", causal_validation=_validation(False))
    with pytest.raises(CryptoManifestError, match="cannot be used"):
        unvalidated.require_trusted("holdout_seal")


def test_manifest_rejects_mixed_venue_and_redistribution_claim() -> None:
    with pytest.raises(CryptoManifestError, match="Bybit Spot"):
        _manifest(venue="binance")
    with pytest.raises(CryptoManifestError, match="redistribution"):
        _manifest(redistribution_allowed=True)


def test_manifest_requires_gap_and_terms_provenance() -> None:
    with pytest.raises(CryptoManifestError, match="gap_summary"):
        _manifest(gap_summary={})
    with pytest.raises(CryptoManifestError, match="terms_status"):
        _manifest(terms_status=" ")
    with pytest.raises(CryptoManifestError, match="zero unexplained gaps"):
        _manifest(gap_summary={"unexplained": 1})
    assert _manifest(status="UNVALIDATED", gap_summary={"unexplained": 1})
    with pytest.raises(CryptoManifestError, match="exactly every hashed component"):
        _manifest(component_provenance={"panel/csv": "panel.csv"})
    with pytest.raises(CryptoManifestError, match="beneath the provenance root"):
        _manifest(
            component_provenance={
                "panel/csv": "../panel.csv",
                "journal/bybit": "journal.jsonl",
            }
        )


def test_component_hashes_bind_exact_bytes(tmp_path) -> None:
    first = tmp_path / "panel"
    second = tmp_path / "journal"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    hashes = component_hashes({"panel": first, "journal": second})
    assert set(hashes) == {"journal", "panel"}
    assert hashes["panel"] != hashes["journal"]
    first.write_bytes(b"changed")
    assert component_hashes({"panel": first})["panel"] != hashes["panel"]


def test_manifest_write_is_non_overwriting_and_digest_bound(tmp_path) -> None:
    path = tmp_path / "dataset_manifest.json"
    manifest = _manifest()
    write_manifest(path, manifest)
    assert manifest.digest() in path.read_text(encoding="utf-8")
    with pytest.raises(CryptoManifestError, match="already exists"):
        write_manifest(path, replace(manifest, notes=("changed",)))


def _write_loadable_manifest(tmp_path):
    provenance = tmp_path / "provenance"
    provenance.mkdir()
    panel = provenance / "panel.csv"
    journal = provenance / "journal.jsonl"
    panel.write_bytes(b"causal panel bytes")
    journal.write_bytes(b"collector journal bytes")
    paths = {"panel/csv": panel, "journal/bybit": journal}
    manifest = _manifest(components=component_hashes(paths))
    manifest_path = tmp_path / "dataset_manifest.json"
    write_manifest(manifest_path, manifest)
    return manifest_path, provenance, panel, manifest


def test_loader_verifies_embedded_digest_and_component_bytes(tmp_path) -> None:
    path, provenance, panel, expected = _write_loadable_manifest(tmp_path)

    assert load_manifest(path, provenance_root=provenance) == expected
    panel.write_bytes(b"silently edited panel")
    with pytest.raises(CryptoManifestError, match="component byte hash mismatch"):
        load_manifest(path, provenance_root=provenance)


def test_loader_rejects_manifest_tampering_before_rehash(tmp_path) -> None:
    path, provenance, _panel, _manifest_value = _write_loadable_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CryptoManifestError, match="manifest digest mismatch"):
        load_manifest(path, provenance_root=provenance)


@pytest.mark.parametrize("required", ["gap_summary", "terms_status", "digest"])
def test_loader_fails_closed_when_required_evidence_is_missing(tmp_path, required) -> None:
    path, provenance, _panel, _manifest_value = _write_loadable_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload[required]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        CryptoManifestError,
        match="missing manifest fields|embedded manifest digest",
    ):
        load_manifest(path, provenance_root=provenance)
