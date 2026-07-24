"""Tests for the V4 evidence contract: canonical JSON + byte-bound manifests."""

from __future__ import annotations

import json

import pytest

from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.evidence.manifest import (
    build_dataset_manifest,
    build_inline_manifest,
    migrate_yaml_results_to_json,
    verify_dataset_manifest,
)

# --- canonical JSON -------------------------------------------------------


def test_canonical_dumps_is_deterministic_and_key_order_independent():
    a = canonical_dumps({"b": 1, "a": [1, 2], "c": {"y": 2, "x": 1}})
    b = canonical_dumps({"c": {"x": 1, "y": 2}, "a": [1, 2], "b": 1})
    assert a == b
    assert sha256_of_text(a) == sha256_of_text(b)


def test_canonical_dumps_rejects_nan_and_infinity():
    with pytest.raises(ValueError):
        canonical_dumps({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_dumps({"x": float("inf")})


def test_atomic_write_json_produces_real_json(tmp_path):
    path = atomic_write_json(tmp_path / "artifact.json", {"k": [1, 2, 3]})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"k": [1, 2, 3]}
    # no stray temp files left behind
    assert list(tmp_path.glob("*.tmp")) == []


def test_load_json_is_strict(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("key: value\n", encoding="utf-8")  # YAML, not JSON
    with pytest.raises(json.JSONDecodeError):
        load_json(bad)


# --- dataset manifests ----------------------------------------------------


def _dataset(tmp_path, seed: int, name: str = "snaps.json"):
    path = tmp_path / name
    write_snapshots_json(path, synthetic_funding_snapshots(periods=25, seed=seed))
    return path


def test_manifest_binds_real_bytes(tmp_path):
    path = _dataset(tmp_path, seed=1)
    manifest = build_dataset_manifest(path)
    assert manifest.byte_sha256 == sha256_of_file(path)
    assert manifest.rows == 25
    assert manifest.symbols == ("BTC",)
    assert manifest.data_source == "synthetic"
    assert manifest.time_range_start <= manifest.time_range_end


def test_same_path_different_bytes_different_sha(tmp_path):
    path = _dataset(tmp_path, seed=1)
    sha_a = build_dataset_manifest(path).byte_sha256
    _dataset(tmp_path, seed=2)  # overwrite same path
    sha_b = build_dataset_manifest(path).byte_sha256
    assert sha_a != sha_b


def test_verify_detects_single_byte_change(tmp_path):
    path = _dataset(tmp_path, seed=1)
    manifest = build_dataset_manifest(path)
    assert verify_dataset_manifest(manifest).ok
    # flip one byte after the manifest was produced
    raw = bytearray(path.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    path.write_bytes(bytes(raw))
    verdict = verify_dataset_manifest(manifest)
    assert not verdict.ok
    assert any("bytes changed" in p for p in verdict.problems)


def test_verify_fails_closed_on_missing_file(tmp_path):
    path = _dataset(tmp_path, seed=1)
    manifest = build_dataset_manifest(path)
    path.unlink()
    verdict = verify_dataset_manifest(manifest)
    assert not verdict.ok
    assert any("missing" in p for p in verdict.problems)


def test_inline_manifest_distinguishes_generated_datasets():
    recs_a = [s.to_dict() for s in synthetic_funding_snapshots(periods=10, seed=1)]
    recs_b = [s.to_dict() for s in synthetic_funding_snapshots(periods=10, seed=2)]
    m_a = build_inline_manifest(recs_a, data_source="synthetic", source_name="gen")
    m_b = build_inline_manifest(recs_b, data_source="synthetic", source_name="gen")
    assert m_a.byte_sha256 != m_b.byte_sha256
    # inline manifests can never be re-verified against a file: fail closed
    assert not verify_dataset_manifest(m_a).ok


def test_manifest_hash_is_stable():
    recs = [s.to_dict() for s in synthetic_funding_snapshots(periods=5, seed=3)]
    m1 = build_inline_manifest(recs, data_source="synthetic", source_name="gen")
    m2 = build_inline_manifest(recs, data_source="synthetic", source_name="gen")
    assert m1.manifest_hash == m2.manifest_hash


# --- migrator -------------------------------------------------------------


def test_migrator_converts_yaml_results_and_refuses_json(tmp_path):
    import yaml

    legacy = tmp_path / "results.json"
    legacy.write_text(yaml.safe_dump({"decision": "NOT-RUN", "x": 1}), encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(legacy.read_text())
    migrate_yaml_results_to_json(legacy)
    assert json.loads(legacy.read_text()) == {"decision": "NOT-RUN", "x": 1}
    # already-JSON files are refused (explicit migration, not permissive fallback)
    with pytest.raises(ValueError, match="already valid JSON"):
        migrate_yaml_results_to_json(legacy)
