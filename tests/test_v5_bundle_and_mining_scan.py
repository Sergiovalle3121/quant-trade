"""Evidence bundle validator + mining rental scanner (V5-5, defect F)."""

from __future__ import annotations

import json

import pytest

from quant_trade.cloud_rental.bundle import EvidenceBundleValidator
from quant_trade.cloud_rental.models import (
    BenchmarkEvidence,
    CloudProvider,
    ComputeQuote,
    InstanceSpecification,
    ProviderPolicyEvidence,
    WorkloadPurpose,
)
from quant_trade.evidence.canonical_json import sha256_of_bytes
from quant_trade.opportunities.mining_scan import (
    load_scan_config,
    scan_mining_cells,
    write_mining_matrix,
)

NOW = "2026-07-24T21:00:00Z"


def _spec(**overrides):
    base = dict(
        provider=CloudProvider.AWS,
        sku="g5.xlarge",
        region="us-east-1",
        architecture="gpu",
        vcpus=4,
        memory_gb=16.0,
        accelerator_model="NVIDIA A10G",
        accelerator_count=1,
    )
    base.update(overrides)
    return InstanceSpecification(**base)


def _quote(**overrides):
    base = dict(
        provider=CloudProvider.AWS,
        sku="g5.xlarge",
        region="us-east-1",
        purchase_model="spot",
        price_per_hour=0.30,
        currency="USD",
        source_kind="fixture",
        source_name="offline_example",
        captured_at_utc="2026-07-24T00:00:00Z",
        max_age_hours=168.0,
    )
    base.update(overrides)
    return ComputeQuote(**base)


def _benchmark(artifact_sha: str, **overrides):
    base = dict(
        provider=CloudProvider.AWS,
        sku="g5.xlarge",
        accelerator_model="NVIDIA A10G",
        accelerator_count=1,
        algorithm="sha256",
        hashrate_hs=1.0e9,
        duration_seconds=3600.0,
        warmup_seconds=300.0,
        shares_accepted=1000,
        shares_rejected=10,
        captured_at_utc="2026-07-24T00:00:00Z",
        source="fixture:offline_bench",
        artifact_sha256=artifact_sha,
    )
    base.update(overrides)
    return BenchmarkEvidence(**base)


@pytest.fixture()
def artifact(tmp_path):
    path = tmp_path / "bench_artifact.json"
    payload = b'{"benchmark_log": "offline fixture artifact"}'
    path.write_bytes(payload)
    return path, sha256_of_bytes(payload)


def test_valid_fixture_bundle_is_test_only(artifact):
    path, sha = artifact
    result = EvidenceBundleValidator().validate(
        spec=_spec(),
        quote=_quote(),
        benchmark=_benchmark(sha),
        algorithm="sha256",
        benchmark_artifact_path=path,
    )
    assert result.status == "VALID_TEST_ONLY"
    assert result.test_only is True
    assert result.usable


def test_cross_sku_and_cross_region_bundles_are_rejected(artifact):
    path, sha = artifact
    v = EvidenceBundleValidator()
    cross_sku = v.validate(
        spec=_spec(),
        quote=_quote(),
        benchmark=_benchmark(sha, sku="p5.48xlarge", accelerator_model="NVIDIA H100"),
        algorithm="sha256",
        benchmark_artifact_path=path,
    )
    assert cross_sku.status == "REJECTED_IDENTITY_MISMATCH"
    assert any("cross-SKU" in p for p in cross_sku.problems)

    cross_region = v.validate(
        spec=_spec(),
        quote=_quote(region="eu-west-1"),
        benchmark=_benchmark(sha),
        algorithm="sha256",
        benchmark_artifact_path=path,
    )
    assert cross_region.status == "REJECTED_IDENTITY_MISMATCH"

    cross_provider = v.validate(
        spec=_spec(),
        quote=_quote(),
        benchmark=_benchmark(sha),
        policy_evidence=ProviderPolicyEvidence(
            provider=CloudProvider.ALIBABA,
            workload=WorkloadPurpose.HASHING_WORKER,
            policy_status="prohibited_default",
            source_url="https://example.invalid/terms",
            reviewed_at_utc=NOW,
            snapshot_sha256="ab" * 32,
            expires_at_utc="2027-01-01T00:00:00Z",
            human_reviewed=True,
        ),
        algorithm="sha256",
        benchmark_artifact_path=path,
    )
    assert cross_provider.status == "REJECTED_IDENTITY_MISMATCH"


def test_tampered_benchmark_artifact_breaks_the_sha_chain(artifact):
    path, sha = artifact
    path.write_bytes(path.read_bytes() + b"\n")  # one extra byte
    result = EvidenceBundleValidator().validate(
        spec=_spec(),
        quote=_quote(),
        benchmark=_benchmark(sha),
        algorithm="sha256",
        benchmark_artifact_path=path,
    )
    assert result.status == "REJECTED_SHA_MISMATCH"
    assert any("do NOT hash" in p for p in result.problems)


def test_missing_artifact_bytes_are_missing_evidence(artifact):
    _, sha = artifact
    result = EvidenceBundleValidator().validate(
        spec=_spec(),
        quote=_quote(),
        benchmark=_benchmark(sha),
        algorithm="sha256",
        benchmark_artifact_path=None,
    )
    assert result.status == "REJECTED_MISSING_EVIDENCE"
    no_benchmark = EvidenceBundleValidator().validate(
        spec=_spec(), quote=_quote(), benchmark=None, algorithm="sha256"
    )
    assert no_benchmark.status == "REJECTED_MISSING_EVIDENCE"


# --- scanner --------------------------------------------------------------


def test_v5_scan_config_reflects_the_real_blocked_posture(tmp_path):
    cells = load_scan_config("configs/opportunities/mining_scan_v5.yaml")
    result = scan_mining_cells(cells, evaluated_at_utc=NOW)
    assert len(result.cells) == 3
    by_provider = {c.provider: c for c in result.cells}
    # AWS: Service Terms §1.25 — no written approval exists, hashing blocked
    assert (
        by_provider["aws"].status
        == "POLICY_BLOCKED:BLOCKED_PENDING_WRITTEN_APPROVAL"
    )
    assert "1.25" in " ".join(by_provider["aws"].reasons)
    # Alibaba: mining is a security-violation example — provider policy block
    assert by_provider["alibaba"].status == "POLICY_BLOCKED:BLOCKED_PROVIDER_POLICY"
    # nothing ranked as a real opportunity; safety posture embedded
    assert all(not c.status.startswith("ECONOMIC_CANDIDATE") for c in result.cells)
    assert result.safety["miner_execution"] is False
    assert result.safety["external_spend_authorized"] is False

    out = tmp_path / "MINING_RENTAL_MATRIX.json"
    write_mining_matrix(out, result)
    payload = json.loads(out.read_text())
    assert payload["artifact"] == "MINING_RENTAL_MATRIX"
    assert payload["counts_by_status"]
    assert payload["safety"]["hardware_control_enabled"] is False


def test_scan_policy_block_outranks_missing_benchmark():
    cells = load_scan_config("configs/opportunities/mining_scan_v5.yaml")
    result = scan_mining_cells(cells, evaluated_at_utc=NOW)
    # every cell lacks a benchmark AND is policy-blocked: the block must win
    for cell in result.cells:
        assert cell.status.startswith("POLICY_BLOCKED:"), cell.status


def test_scan_identity_break_rejects_before_policy(tmp_path):
    cells = load_scan_config("configs/opportunities/mining_scan_v5.yaml")
    broken = dict(cells[0])
    # quote says us-east-1 but the spec claims eu-west-1: incoherent evidence
    broken["spec"] = dict(broken["spec"], region="eu-west-1")
    result = scan_mining_cells([broken], evaluated_at_utc=NOW)
    assert result.cells[0].status == "REJECTED_IDENTITY_MISMATCH"


def test_cli_scan_mining_writes_matrix(tmp_path):
    from typer.testing import CliRunner

    from quant_trade.cli import app

    out = tmp_path / "MINING_RENTAL_MATRIX.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "opportunities",
            "scan-mining",
            "--config",
            "configs/opportunities/mining_scan_v5.yaml",
            "--output",
            str(out),
            "--evaluated-at-utc",
            NOW,
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "POLICY_BLOCKED" in result.output
    assert "no miners were run" in result.output
