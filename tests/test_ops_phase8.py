from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.ops.alerts import (
    ConsoleNotifier,
    JsonlNotifier,
    SlackWebhookNotifier,
    SnsNotifier,
    acknowledge_alert,
    load_alerts,
    make_alert,
)
from quant_trade.ops.archive import apply_retention_policy, archive_run_artifacts, verify_archive
from quant_trade.ops.config import OpsConfig, load_ops_config, validate_ops_config
from quant_trade.ops.dashboard import generate_dashboard
from quant_trade.ops.drills import run_all_drills
from quant_trade.ops.exceptions import OpsConfigError, OpsValidationError
from quant_trade.ops.fill_analysis import analyze_fills
from quant_trade.ops.incidents import (
    create_incident_from_alert,
    list_incidents,
    save_incident,
    update_incident,
)
from quant_trade.ops.inspect import inspect_run
from quant_trade.ops.readiness import ReadinessPolicy, evaluate_ops_readiness
from quant_trade.ops.reconciliation import reconcile_broker_artifacts
from quant_trade.ops.reliability import calculate_reliability_metrics
from quant_trade.ops.sessions import (
    find_latest_session_artifacts,
    get_session,
    load_session_registry,
    validate_session_config,
)
from quant_trade.ops.validation import validate_artifacts

FIX = Path("tests/fixtures/ops")
CFG = Path("configs/ops/local_ops_validation.yaml")


def test_sessions_load_and_discover() -> None:
    cfg = load_ops_config(CFG)
    registry = load_session_registry(cfg.session_registry_path)
    session = get_session(registry, "ts_momentum_synthetic_paper")

    validate_session_config(session)

    assert find_latest_session_artifacts(session, [FIX]) is not None
    with pytest.raises(OpsValidationError):
        get_session(registry, "missing")


def test_validation_pass_missing_and_mismatch() -> None:
    valid = validate_artifacts(FIX / "paper_run_valid/ts_momentum_synthetic_paper", "s")
    missing = validate_artifacts(
        FIX / "paper_run_missing_artifact/ts_momentum_synthetic_paper", "s"
    )
    mismatch = validate_artifacts(FIX / "paper_run_state_mismatch/ts_momentum_synthetic_paper", "s")

    assert valid.status == "pass"
    assert missing.status == "fail"
    assert mismatch.status == "fail"


def test_reliability_empty_and_threshold() -> None:
    empty = calculate_reliability_metrics([])
    populated = calculate_reliability_metrics([{"status": "pass"}, {"status": "fail"}])

    assert empty.total_runs == 0
    assert populated.success_rate == 0.5


def test_fill_analysis_and_reconciliation() -> None:
    run_dir = FIX / "paper_run_valid/ts_momentum_synthetic_paper"
    analysis = analyze_fills(run_dir)

    assert analysis.fill_rate == pytest.approx(1.0)
    assert analysis.average_slippage_bps == pytest.approx(25.0)
    assert reconcile_broker_artifacts(run_dir).status == "pass"


def test_alerts_incidents_dashboard_archive_inspect(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    alert = make_alert()
    alert.details = {"api_key": "secret"}

    JsonlNotifier(tmp_path / "alerts.jsonl").notify(alert)
    loaded_alert = load_alerts(tmp_path / "alerts.jsonl")[0]
    assert loaded_alert["details"]["api_key"] == "[REDACTED]"

    ConsoleNotifier().notify(alert)
    assert "secret" not in capsys.readouterr().out

    client = type("Client", (), {"publish": lambda self, **kwargs: kwargs})()
    SnsNotifier(client=client, topic_arn="arn").notify(alert)
    SlackWebhookNotifier(post=lambda *args, **kwargs: None).notify(alert)

    acknowledge_alert(alert.alert_id, "reviewed", tmp_path / "acks.jsonl")
    assert (tmp_path / "acks.jsonl").exists()

    incident = create_incident_from_alert(alert)
    save_incident(tmp_path, incident)
    assert list_incidents(tmp_path)[0].status == "open"
    update_incident(tmp_path, incident.incident_id, "resolved", "done")

    generate_dashboard(tmp_path / "dash", [], {"status": "pass", "api_token": "x"})
    assert (tmp_path / "dash/index.html").exists()
    assert "x" not in (tmp_path / "dash/dashboard.json").read_text(encoding="utf-8")

    # archive_run_artifacts writes artifacts_index.json into the run dir;
    # archive from a copy so the committed fixture is never mutated.
    run_copy = tmp_path / "paper_run_valid" / "ts_momentum_synthetic_paper"
    shutil.copytree(FIX / "paper_run_valid/ts_momentum_synthetic_paper", run_copy)
    archive = archive_run_artifacts(run_copy, tmp_path / "archive")
    assert verify_archive(archive)
    assert apply_retention_policy(tmp_path / "none", 1, 1)["candidates"] == []

    inspected = inspect_run(FIX / "paper_run_valid/ts_momentum_synthetic_paper")
    assert inspected["detected_artifact_type"] == "paper_run"


def test_drills_readiness_and_config_safety() -> None:
    cfg = load_ops_config(CFG)
    assert all(result.status == "pass" for result in run_all_drills(cfg))

    bad = OpsConfig(**{**cfg.__dict__, "allow_live_trading": True})
    with pytest.raises(OpsConfigError):
        validate_ops_config(bad)

    report = evaluate_ops_readiness(
        "s",
        [{"status": "pass"}],
        calculate_reliability_metrics([{"status": "pass"}]),
        [],
        [{"name": "kill_switch_drill", "status": "pass"}],
        ReadinessPolicy(),
    )
    assert report.real_money_ready is False


def test_cli_acceptance_commands() -> None:
    runner = CliRunner()
    commands = [
        ["ops", "list-sessions", "--config", str(CFG)],
        ["ops", "validate", "--config", str(CFG)],
        ["ops", "reliability", "--config", str(CFG)],
        ["ops", "dashboard", "generate", "--config", str(CFG)],
        ["ops", "drill", "all", "--config", str(CFG)],
        ["ops", "readiness", "--config", str(CFG), "--session", "ts_momentum_synthetic_paper"],
        ["ops", "run-cycle", "--config", str(CFG)],
        ["ops", "alert-test", "--config", str(CFG)],
        ["ops", "incidents", "list", "--config", str(CFG)],
        [
            "ops",
            "inspect-session",
            "--config",
            str(CFG),
            "--session",
            "ts_momentum_synthetic_paper",
        ],
    ]
    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
