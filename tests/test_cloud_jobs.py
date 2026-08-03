import pytest
import yaml

from quant_trade.cloud.exceptions import SafetyGateError
from quant_trade.cloud.jobs import run_job


def test_health_job_runs(tmp_path):
    summary = run_job("configs/cloud/local_dry_run.yaml", "health_check")
    assert summary.status == "success"


def test_broker_submit_fails_default():
    with pytest.raises(SafetyGateError):
        run_job("configs/cloud/local_dry_run.yaml", "broker_submit_paper")


def test_broker_plan_no_network():
    assert run_job("configs/cloud/local_dry_run.yaml", "broker_plan").status == "success"


def test_an_unknown_job_name_is_refused(tmp_path):
    """The dispatcher must reject what it cannot run, not succeed silently.

    This replaces the two mining_evaluation tests. They covered the shared
    dispatcher through a mining example, so deleting them outright would have
    dropped coverage of a path that stays: heartbeat, kill-switch and artifact
    plumbing all run around this branch.
    """
    cloud_config = tmp_path / "cloud.yaml"
    payload = {
        "environment": "local",
        "deployment_name": "dispatch-test",
        "job_name": "no_such_job",
        "mode": "dry_run",
        "allow_live_trading": False,
        "real_money_enabled": False,
        "artifact_uri": str(tmp_path / "artifacts"),
        "state_uri": str(tmp_path / "state"),
        "heartbeat_uri": str(tmp_path / "state" / "heartbeat.json"),
        "kill_switch_uri": str(tmp_path / "state" / "kill_switch.json"),
    }
    cloud_config.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(SafetyGateError, match="unknown cloud job"):
        run_job(cloud_config)

    assert (tmp_path / "state" / "heartbeat.json").exists(), (
        "the heartbeat must be written even when the job itself fails"
    )

