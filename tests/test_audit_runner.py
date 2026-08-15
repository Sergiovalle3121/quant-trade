from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from quant_trade.audit import (
    AuditBundle,
    AuditStatus,
    load_audit_input,
    run_audit,
    write_audit_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAN_CONFIG = REPO_ROOT / "configs" / "audit" / "clean.yaml"
CONTAMINATED_CONFIG = REPO_ROOT / "configs" / "audit" / "contaminated.yaml"


def _package(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "package"
    shutil.copytree(REPO_ROOT / "configs" / "audit" / "fixtures" / "clean", package)
    config = tmp_path / "audit.yaml"
    config.write_text(
        "\n".join(
            [
                "root_dir: package",
                "dataset_path: dataset.csv",
                "results_path: results.json",
                "manifest_path: dataset.manifest.json",
                "trial_ledger_path: trial_ledger.json",
                'evaluation_cutoff_utc: "2024-12-31T23:59:59Z"',
                "timestamp_column: timestamp",
                "required_columns: [timestamp, symbol, open, high, low, close, volume]",
                "max_file_size_bytes: 1000000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config, package


def _mutate_json(path: Path, **updates: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _status(bundle: AuditBundle, code: str) -> AuditStatus:
    return next(check.status for check in bundle.checks if check.code == code)


def test_clean_fixture_passes_without_authorizing_money() -> None:
    bundle = run_audit(load_audit_input(CLEAN_CONFIG))
    assert bundle.verdict.status is AuditStatus.PASS
    assert bundle.verdict.real_money_authorized is False
    assert bundle.job.network_accessed is False
    assert bundle.job.customer_code_executed is False


def test_contaminated_fixture_is_no_go_for_multiple_independent_reasons() -> None:
    bundle = run_audit(load_audit_input(CONTAMINATED_CONFIG))
    assert bundle.verdict.status is AuditStatus.NO_GO
    assert _status(bundle, "LOOKAHEAD_COLUMNS") is AuditStatus.NO_GO
    assert _status(bundle, "TIMESTAMP_CAUSALITY") is AuditStatus.NO_GO
    assert _status(bundle, "NEXT_BAR_EXECUTION") is AuditStatus.NO_GO
    assert _status(bundle, "RESULT_DATASET_BINDING") is AuditStatus.NO_GO


def test_repeated_run_has_identical_job_and_bundle_digest() -> None:
    audit_input = load_audit_input(CLEAN_CONFIG)
    first = run_audit(audit_input)
    second = run_audit(audit_input)
    assert first.job.job_id == second.job.job_id
    assert first.to_dict() == second.to_dict()
    assert len(first.bundle_digest) == 64


def test_bundle_writes_identical_bytes_to_fresh_directories(tmp_path: Path) -> None:
    bundle = run_audit(load_audit_input(CLEAN_CONFIG))
    first_json, first_html = write_audit_bundle(bundle, tmp_path / "one")
    second_json, second_html = write_audit_bundle(bundle, tmp_path / "two")
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_html.read_bytes() == second_html.read_bytes()
    assert json.loads(first_json.read_text(encoding="utf-8"))["bundle_digest"] == (
        bundle.bundle_digest
    )


def test_writer_refuses_to_overwrite_either_artifact(tmp_path: Path) -> None:
    bundle = run_audit(load_audit_input(CLEAN_CONFIG))
    output = tmp_path / "out"
    write_audit_bundle(bundle, output)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_audit_bundle(bundle, output)


def test_html_escapes_customer_controlled_benchmark_name(tmp_path: Path) -> None:
    config, package = _package(tmp_path)
    results_path = package / "results.json"
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    payload["benchmarks"][0]["name"] = '<img src=x onerror="alert(1)">'
    results_path.write_text(json.dumps(payload), encoding="utf-8")
    bundle = run_audit(load_audit_input(config))
    _, html_path = write_audit_bundle(bundle, tmp_path / "report")
    html = html_path.read_text(encoding="utf-8")
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html
    assert "<script" not in html.lower()


def test_missing_manifest_is_insufficient_not_pass(tmp_path: Path) -> None:
    config, _ = _package(tmp_path)
    text = config.read_text(encoding="utf-8").replace("manifest_path: dataset.manifest.json\n", "")
    config.write_text(text, encoding="utf-8")
    bundle = run_audit(load_audit_input(config))
    assert bundle.verdict.status is AuditStatus.INSUFFICIENT_EVIDENCE
    assert _status(bundle, "MANIFEST_PROVENANCE") is AuditStatus.INSUFFICIENT_EVIDENCE


def test_config_cannot_widen_root_outside_its_directory(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    config = child / "audit.yaml"
    config.write_text(
        "root_dir: ..\ndataset_path: data.csv\nresults_path: results.json\n"
        'evaluation_cutoff_utc: "2024-01-01T00:00:00Z"\nrequired_columns: [timestamp]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="contained by the config directory"):
        load_audit_input(config)


def test_dataset_rejects_executable_extension(tmp_path: Path) -> None:
    config, package = _package(tmp_path)
    (package / "dataset.py").write_text("raise RuntimeError('never run')", encoding="utf-8")
    config.write_text(
        config.read_text(encoding="utf-8").replace("dataset.csv", "dataset.py"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="format is not allowed"):
        load_audit_input(config)


def test_boolean_file_limit_is_rejected(tmp_path: Path) -> None:
    config, _ = _package(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "max_file_size_bytes: 1000000", "max_file_size_bytes: true"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be an integer"):
        load_audit_input(config)


def test_naive_cutoff_is_rejected(tmp_path: Path) -> None:
    config, _ = _package(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8").replace("2024-12-31T23:59:59Z", "2024-12-31T23:59:59"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="explicit UTC offset"):
        load_audit_input(config)


def test_boolean_signal_lag_is_not_treated_as_one(tmp_path: Path) -> None:
    config, package = _package(tmp_path)
    _mutate_json(package / "results.json", execution={"signal_lag_bars": True})
    bundle = run_audit(load_audit_input(config))
    assert _status(bundle, "NEXT_BAR_EXECUTION") is AuditStatus.NO_GO


def test_boolean_cost_is_not_treated_as_numeric(tmp_path: Path) -> None:
    config, package = _package(tmp_path)
    _mutate_json(
        package / "results.json",
        costs={"applied": True, "fee_bps": True, "slippage_bps": 5.0},
    )
    bundle = run_audit(load_audit_input(config))
    assert _status(bundle, "COSTS_DECLARED") is AuditStatus.NO_GO


def test_boolean_strategy_return_is_not_treated_as_numeric(tmp_path: Path) -> None:
    config, package = _package(tmp_path)
    _mutate_json(package / "results.json", strategy_net_return=True)
    bundle = run_audit(load_audit_input(config))
    assert _status(bundle, "NET_BENCHMARK_RESULT") is AuditStatus.INSUFFICIENT_EVIDENCE


def test_boolean_benchmark_return_is_not_treated_as_numeric(tmp_path: Path) -> None:
    config, package = _package(tmp_path)
    _mutate_json(package / "results.json", benchmarks={"cash": True, "btc": 0.05})
    bundle = run_audit(load_audit_input(config))
    assert _status(bundle, "BENCHMARKS_DECLARED") is AuditStatus.NO_GO


def test_boolean_manifest_size_is_rejected_as_mismatch(tmp_path: Path) -> None:
    config, package = _package(tmp_path)
    _mutate_json(package / "dataset.manifest.json", size_bytes=True)
    bundle = run_audit(load_audit_input(config))
    assert _status(bundle, "MANIFEST_PROVENANCE") is AuditStatus.NO_GO


@pytest.mark.parametrize(
    "captured_at_utc",
    ["2024-01-04T00:00:00", "2025-01-01T00:00:00Z"],
)
def test_manifest_capture_time_must_be_zoned_and_before_cutoff(
    tmp_path: Path, captured_at_utc: str
) -> None:
    config, package = _package(tmp_path)
    _mutate_json(package / "dataset.manifest.json", captured_at_utc=captured_at_utc)
    bundle = run_audit(load_audit_input(config))
    assert _status(bundle, "MANIFEST_PROVENANCE") is AuditStatus.NO_GO


def test_runtime_rechecks_containment_for_programmatic_input(tmp_path: Path) -> None:
    audit_input = load_audit_input(CLEAN_CONFIG)
    escaped = replace(audit_input, dataset_path=str(tmp_path / "outside.csv"))
    (tmp_path / "outside.csv").write_text("timestamp,close\n", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes the declared root"):
        run_audit(escaped)


def test_programmatic_boolean_file_limit_is_rejected() -> None:
    audit_input = replace(load_audit_input(CLEAN_CONFIG), max_file_size_bytes=True)
    with pytest.raises(ValueError, match="invalid max_file_size_bytes"):
        run_audit(audit_input)
