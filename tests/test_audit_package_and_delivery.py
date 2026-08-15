"""Tests for the parts a customer touches: package init, delivery, verification.

The runner's own checks are covered in ``test_audit_runner.py``.  What is
covered here is everything that stands between a stranger's own backtest and a
report they can act on, plus the two failure modes that would burn a paid pilot:
a false ``NO_GO`` on a normally-sorted panel, and a deliverable that leaks local
filesystem layout.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_trade.audit.models import AuditStatus, FindingClass, recompute_bundle_digest
from quant_trade.audit.package import PACKAGE_FILENAMES, PLACEHOLDER, initialize_package
from quant_trade.audit.runner import load_audit_input, run_audit, write_audit_bundle
from quant_trade.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAN_FIXTURE = REPO_ROOT / "configs" / "audit" / "fixtures" / "clean"
CLEAN_CONFIG = REPO_ROOT / "configs" / "audit" / "clean.yaml"
CONTAMINATED_CONFIG = REPO_ROOT / "configs" / "audit" / "contaminated.yaml"

runner = CliRunner()

_PANEL_HEADER = "timestamp,symbol,open,high,low,close,volume\n"
_AAA = "2024-01-02T00:00:00Z,AAA,1,2,1,2,10\n2024-01-03T00:00:00Z,AAA,2,3,2,3,10\n"
_BBB = "2024-01-02T00:00:00Z,BBB,5,6,5,6,20\n2024-01-03T00:00:00Z,BBB,6,7,6,7,20\n"


def _write_panel(tmp_path: Path, body: str, *, symbol_column: str = "symbol") -> Path:
    package = tmp_path / "package"
    package.mkdir()
    (package / "dataset.csv").write_text(_PANEL_HEADER + body, encoding="utf-8")
    shutil.copy(CLEAN_FIXTURE / "results.json", package / "results.json")
    config = tmp_path / "audit.yaml"
    config.write_text(
        "\n".join(
            [
                "root_dir: package",
                "dataset_path: dataset.csv",
                "results_path: results.json",
                'evaluation_cutoff_utc: "2024-12-31T23:59:59Z"',
                "timestamp_column: timestamp",
                f"symbol_column: {symbol_column}",
                "required_columns: [timestamp, symbol]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config


def _check(bundle: object, code: str) -> object:
    return next(check for check in bundle.checks if check.code == code)  # type: ignore[attr-defined]


def test_a_panel_sorted_by_symbol_then_time_is_causal_not_a_defect(tmp_path: Path) -> None:
    """The export shape every real customer has must not read as look-ahead."""
    config = _write_panel(tmp_path, _AAA + _BBB)
    bundle = run_audit(load_audit_input(config))
    causality = _check(bundle, "TIMESTAMP_CAUSALITY")
    assert causality.status is AuditStatus.PASS  # type: ignore[attr-defined]
    assert "series=2" in causality.evidence  # type: ignore[attr-defined]


def test_time_going_backwards_within_one_symbol_is_still_no_go(tmp_path: Path) -> None:
    reversed_aaa = "2024-01-03T00:00:00Z,AAA,2,3,2,3,10\n2024-01-02T00:00:00Z,AAA,1,2,1,2,10\n"
    config = _write_panel(tmp_path, reversed_aaa + _BBB)
    causality = _check(run_audit(load_audit_input(config)), "TIMESTAMP_CAUSALITY")
    assert causality.status is AuditStatus.NO_GO  # type: ignore[attr-defined]
    assert "symbol=AAA" in causality.evidence  # type: ignore[attr-defined]


def test_without_a_symbol_column_the_whole_file_must_be_ordered(tmp_path: Path) -> None:
    config = _write_panel(tmp_path, _AAA + _BBB, symbol_column="not_a_column")
    causality = _check(run_audit(load_audit_input(config)), "TIMESTAMP_CAUSALITY")
    assert causality.status is AuditStatus.NO_GO  # type: ignore[attr-defined]
    assert "whole dataset" in causality.evidence  # type: ignore[attr-defined]


def test_losing_to_the_benchmark_is_labelled_a_result_not_a_defect() -> None:
    bundle = run_audit(load_audit_input(CONTAMINATED_CONFIG))
    benchmark = _check(bundle, "NET_BENCHMARK_RESULT")
    assert benchmark.status is AuditStatus.NO_GO  # type: ignore[attr-defined]
    assert benchmark.finding_class is FindingClass.RESULT  # type: ignore[attr-defined]
    # The label is a communication fix, not a relaxation: it still blocks.
    assert bundle.verdict.status is AuditStatus.NO_GO


def test_method_failures_stay_labelled_defects() -> None:
    bundle = run_audit(load_audit_input(CONTAMINATED_CONFIG))
    for code in ("LOOKAHEAD_COLUMNS", "TIMESTAMP_CAUSALITY", "NEXT_BAR_EXECUTION"):
        assert _check(bundle, code).finding_class is FindingClass.DEFECT  # type: ignore[attr-defined]


def test_redaction_removes_local_paths_but_keeps_the_bundle_verifiable(tmp_path: Path) -> None:
    bundle = run_audit(load_audit_input(CLEAN_CONFIG), redact=True)
    payload = bundle.to_dict()
    assert payload["audit_input"]["root_dir"] == "<redacted>"
    assert payload["audit_input"]["dataset_path"] == "dataset.csv"
    serialized = json.dumps(payload)
    assert str(REPO_ROOT) not in serialized
    assert recompute_bundle_digest(payload) == payload["bundle_digest"]


def test_redaction_changes_the_digest_so_the_two_reports_are_distinguishable() -> None:
    audit_input = load_audit_input(CLEAN_CONFIG)
    assert run_audit(audit_input).bundle_digest != run_audit(audit_input, redact=True).bundle_digest


def test_an_edited_bundle_fails_verification(tmp_path: Path) -> None:
    bundle = run_audit(load_audit_input(CLEAN_CONFIG))
    payload = bundle.to_dict()
    assert recompute_bundle_digest(payload) == payload["bundle_digest"]
    payload["verdict"]["status"] = "PASS_BUT_EDITED"
    assert recompute_bundle_digest(payload) != payload["bundle_digest"]


@pytest.mark.parametrize("payload", [{}, {"a": 1}, [], "text", None])
def test_verification_rejects_anything_that_is_not_a_bundle(payload: object) -> None:
    with pytest.raises(ValueError):
        recompute_bundle_digest(payload)  # type: ignore[arg-type]


def test_init_computes_both_digests_and_leaves_only_unknowable_fields_blank(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    dataset = package / "dataset.csv"
    dataset.write_text(_PANEL_HEADER + _AAA, encoding="utf-8")

    created, placeholders = initialize_package(
        package, dataset_name="dataset.csv", evaluation_cutoff_utc="2024-12-31T23:59:59Z"
    )
    assert {path.name for path in created} == set(PACKAGE_FILENAMES.values())
    assert placeholders

    results = json.loads((package / "results.json").read_text(encoding="utf-8"))
    manifest = json.loads((package / "dataset.manifest.json").read_text(encoding="utf-8"))
    ledger_bytes = (package / "trial_ledger.json").read_bytes()

    import hashlib

    assert results["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert manifest["byte_sha256"] == results["dataset_sha256"]
    assert results["trial_ledger_sha256"] == hashlib.sha256(ledger_bytes).hexdigest()
    assert manifest["size_bytes"] == dataset.stat().st_size


def test_an_unfilled_template_can_never_pass(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "dataset.csv").write_text(_PANEL_HEADER + _AAA + _BBB, encoding="utf-8")
    initialize_package(
        package, dataset_name="dataset.csv", evaluation_cutoff_utc="2024-12-31T23:59:59Z"
    )
    config = package / PACKAGE_FILENAMES["config"]
    assert PLACEHOLDER in config.parent.joinpath("results.json").read_text(encoding="utf-8")
    bundle = run_audit(load_audit_input(config))
    assert bundle.verdict.status is not AuditStatus.PASS


def test_init_refuses_to_overwrite_an_existing_package(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "dataset.csv").write_text(_PANEL_HEADER + _AAA, encoding="utf-8")
    kwargs = {"dataset_name": "dataset.csv", "evaluation_cutoff_utc": "2024-12-31T23:59:59Z"}
    initialize_package(package, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(FileExistsError):
        initialize_package(package, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "dataset_name",
    ["../escape.csv", "sub/dataset.csv", "missing.csv", "dataset.py"],
)
def test_init_rejects_a_dataset_outside_the_package_or_of_a_disallowed_type(
    tmp_path: Path, dataset_name: str
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "dataset.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "escape.csv").write_text(_PANEL_HEADER, encoding="utf-8")
    with pytest.raises((ValueError, FileExistsError)):
        initialize_package(
            package, dataset_name=dataset_name, evaluation_cutoff_utc="2024-12-31T23:59:59Z"
        )


def test_cli_init_then_run_is_a_complete_path_for_a_stranger(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "dataset.csv").write_text(_PANEL_HEADER + _AAA + _BBB, encoding="utf-8")

    created = runner.invoke(
        app,
        [
            "audit",
            "init",
            "--package-dir",
            str(package),
            "--evaluation-cutoff-utc",
            "2024-12-31T23:59:59Z",
        ],
    )
    assert created.exit_code == 0
    payload = json.loads(created.stdout)
    assert len(payload["created"]) == len(PACKAGE_FILENAMES)
    assert payload["fields_you_must_still_fill"]
    assert "audit run --config" in payload["next_command"]

    # The generated config is directly runnable, and an unfilled one cannot pass.
    result = runner.invoke(
        app,
        [
            "audit",
            "run",
            "--config",
            str(package / PACKAGE_FILENAMES["config"]),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert json.loads(result.stdout)["verdict"] != "PASS"


def test_cli_init_reports_a_bad_package_as_a_parameter_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    failed = runner.invoke(
        app,
        [
            "audit",
            "init",
            "--package-dir",
            str(empty),
            "--evaluation-cutoff-utc",
            "2024-12-31T23:59:59Z",
        ],
    )
    assert failed.exit_code != 0


def test_cli_verify_rejects_a_file_that_is_not_a_bundle(tmp_path: Path) -> None:
    stray = tmp_path / "notes.json"
    stray.write_text('{"hello": "world"}', encoding="utf-8")
    assert runner.invoke(app, ["audit", "verify", "--bundle", str(stray)]).exit_code != 0


def test_cli_exit_codes_let_a_pipeline_gate_on_the_verdict(tmp_path: Path) -> None:
    clean = runner.invoke(
        app, ["audit", "run", "--config", str(CLEAN_CONFIG), "--out-dir", str(tmp_path / "clean")]
    )
    assert clean.exit_code == 0
    assert json.loads(clean.stdout)["verdict"] == "PASS"

    bad = runner.invoke(
        app,
        [
            "audit",
            "run",
            "--config",
            str(CONTAMINATED_CONFIG),
            "--out-dir",
            str(tmp_path / "bad"),
        ],
    )
    assert bad.exit_code == 2
    assert json.loads(bad.stdout)["verdict"] == "NO_GO"


def test_cli_verify_round_trips_a_delivered_bundle(tmp_path: Path) -> None:
    bundle = run_audit(load_audit_input(CLEAN_CONFIG), redact=True)
    json_path, _ = write_audit_bundle(bundle, tmp_path / "delivery")
    ok = runner.invoke(app, ["audit", "verify", "--bundle", str(json_path)])
    assert ok.exit_code == 0
    assert json.loads(ok.stdout)["matches"] is True

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["verdict"]["pass_count"] = 999
    json_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tampered = runner.invoke(app, ["audit", "verify", "--bundle", str(json_path)])
    assert tampered.exit_code == 2
    assert json.loads(tampered.stdout)["matches"] is False
