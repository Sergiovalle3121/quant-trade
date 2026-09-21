"""Tests for the pre-flight doctor and the run-all orchestrator on the fixture."""

from __future__ import annotations

from pathlib import Path

import pytest
from crypto_lowcap_fixture import AT, build_experiment
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.research.crypto_lowcap.doctor import doctor_exit_code, run_doctor
from quant_trade.research.crypto_lowcap.orchestrate import (
    FAILED,
    OK,
    SKIPPED,
    OrchestrationError,
    plan_steps,
    run_all,
)
from quant_trade.research.crypto_lowcap.report import programme_state

runner = CliRunner()


def _listing(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def test_doctor_passes_on_the_fixture_and_never_writes(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    before = _listing(tmp_path)
    report = run_doctor(fx["experiment"], fx["inputs"], fx["trials"], at_utc=AT)
    assert report.overall == "PASS", [c.to_dict() for c in report.checks if c.status == "FAIL"]
    assert doctor_exit_code(report) == 0
    assert report.runtime_estimate["evidence_class"] == "ASSUMPTION"
    assert report.runtime_estimate["select"]["evaluations"] > 0
    assert report.panel["rows"] > 0
    assert report.programme_state == "NOT_RUN"
    assert _listing(tmp_path) == before


def test_doctor_names_the_verify_command_when_verification_is_missing(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    (fx["experiment"] / "panel_verification.json").unlink()
    report = run_doctor(fx["experiment"], fx["inputs"], fx["trials"], at_utc=AT)
    assert report.overall == "FAIL"
    failing = {c.name: c for c in report.checks if c.status == "FAIL"}
    assert "verification" in failing
    assert "verify-panel" in failing["verification"].fix
    assert report.to_dict()["missing_inputs"][0]["command"].startswith("quant-trade")


def test_doctor_detects_a_broken_journal_chain(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    journal = fx["inputs"].venue_dirs["bybit"] / "journal.jsonl"
    lines = journal.read_text(encoding="utf-8").splitlines()
    # Editing a record that has a successor breaks the successor's link.
    lines[0] = lines[0].replace('"policy_sha256":"b"', '"policy_sha256":"x"')
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = run_doctor(fx["experiment"], fx["inputs"], fx["trials"], at_utc=AT)
    failing = {c.name: c for c in report.checks if c.status == "FAIL"}
    assert "dataset:venue:bybit" in failing
    assert "chain" in failing["dataset:venue:bybit"].detail


def test_run_all_dry_run_lists_every_step_and_writes_nothing(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    before = _listing(tmp_path)
    result = run_all(
        fx["experiment"],
        fx["inputs"],
        fx["trials"],
        reason="x",
        output=tmp_path / "r.md",
        dry_run=True,
        at_utc=AT,
        code_sha="abc",
    )
    assert result["dry_run"] is True
    assert [s["name"] for s in result["steps"]] == ["verify-panel", "select", "reveal", "report"]
    # the fixture already verified the panel, so that step is not needed
    assert [s["needed"] for s in result["steps"]] == [False, True, True, True]
    assert _listing(tmp_path) == before


def test_run_all_refuses_a_reveal_without_a_reason(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    with pytest.raises(OrchestrationError, match="reason"):
        run_all(
            fx["experiment"],
            fx["inputs"],
            fx["trials"],
            reason="  ",
            output=tmp_path / "r.md",
            dry_run=False,
            at_utc=AT,
            code_sha="abc",
        )
    assert programme_state(fx["experiment"]) == "NOT_RUN"


def test_run_all_reaches_revealed_and_a_second_run_skips(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    output = tmp_path / "RESULTS.md"
    first = run_all(
        fx["experiment"],
        fx["inputs"],
        fx["trials"],
        reason="fixture",
        output=output,
        dry_run=False,
        at_utc=AT,
        code_sha="abc",
    )
    assert first["failed_step"] is None
    assert first["state_after"] == "REVEALED"
    assert {s["name"]: s["status"] for s in first["steps"]} == {
        "verify-panel": SKIPPED,
        "select": OK,
        "reveal": OK,
        "report": OK,
    }
    assert output.read_text(encoding="utf-8").startswith("# Low/mid-cap crypto campaign")
    second = run_all(
        fx["experiment"],
        fx["inputs"],
        fx["trials"],
        reason="",
        output=output,
        dry_run=False,
        at_utc=AT,
        code_sha="abc",
    )
    assert {s["name"]: s["status"] for s in second["steps"]} == {
        "verify-panel": SKIPPED,
        "select": SKIPPED,
        "reveal": SKIPPED,
        "report": OK,
    }


def test_run_all_stops_at_the_first_failure(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    fx["trials"].write_text("not: [a, mapping", encoding="utf-8")
    result = run_all(
        fx["experiment"],
        fx["inputs"],
        fx["trials"],
        reason="fixture",
        output=tmp_path / "r.md",
        dry_run=False,
        at_utc=AT,
        code_sha="abc",
    )
    assert result["failed_step"] == "select"
    assert {s["name"]: s["status"] for s in result["steps"]} == {
        "verify-panel": SKIPPED,
        "select": FAILED,
        "reveal": SKIPPED,
        "report": SKIPPED,
    }
    assert programme_state(fx["experiment"]) == "NOT_RUN"


def test_plan_steps_requires_verification_when_the_panel_changed(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    steps = plan_steps(fx["experiment"], fx["panel"])
    assert steps[0].needed is False
    (fx["experiment"] / "panel_verification.json").unlink()
    steps = plan_steps(fx["experiment"], fx["panel"])
    assert steps[0].needed is True


def test_cli_doctor_and_run_all(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    common = [
        "--experiment-dir",
        str(fx["experiment"]),
        "--trials",
        str(fx["trials"]),
        "--panel",
        str(fx["panel"]),
        "--universe-dir",
        str(fx["inputs"].universe_dir),
        "--deathlist-dir",
        str(fx["inputs"].deathlist_dir),
        "--venue-dir",
        f"bybit={fx['inputs'].venue_dirs['bybit']}",
    ]
    result = runner.invoke(app, ["crypto-lowcap", "doctor", *common, "--at-utc", AT])
    assert result.exit_code == 0, result.output
    assert '"overall": "PASS"' in result.output
    result = runner.invoke(app, ["crypto-lowcap", "run-all", *common, "--dry-run", "--reason", "x"])
    assert result.exit_code == 0, result.output
    assert "select" in result.output and "PENDING" in result.output
    help_text = runner.invoke(app, ["crypto-lowcap", "--help"]).output
    for command in (
        "doctor",
        "run-all",
        "horizon",
        "majors-overlap",
        "paper-plan",
        "paper-record",
        "paper-status",
    ):
        assert command in help_text
