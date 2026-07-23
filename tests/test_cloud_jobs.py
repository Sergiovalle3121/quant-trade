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


def test_mining_evaluation_job_writes_offline_cloud_artifact(tmp_path, monkeypatch):
    from quant_trade.cloud import jobs

    cloud_config = tmp_path / "cloud.yaml"
    payload = {
        "environment": "local",
        "deployment_name": "mining-test",
        "job_name": "mining_evaluation",
        "mode": "dry_run",
        "allow_live_trading": False,
        "real_money_enabled": False,
        "mining_config_path": "configs/mining/aws_profitability_example.yaml",
        "artifact_uri": str(tmp_path / "artifacts"),
        "state_uri": str(tmp_path / "state"),
        "heartbeat_uri": str(tmp_path / "state" / "heartbeat.json"),
        "kill_switch_uri": str(tmp_path / "state" / "kill_switch.json"),
    }
    cloud_config.write_text(yaml.safe_dump(payload), encoding="utf-8")
    monkeypatch.setattr(jobs, "new_run_id", lambda: "fixed-run")

    summary = run_job(cloud_config)

    assert summary.status == "success"
    report_path = (
        tmp_path
        / "artifacts"
        / "cloud"
        / "mining-test"
        / "mining_evaluation"
        / "fixed-run"
        / "mining_profitability_report.json"
    )
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert report["authorized_to_start_miner"] is False
    assert report["cloud_resources_created"] is False


def test_mining_evaluation_requires_config():
    with pytest.raises(SafetyGateError, match="mining_config_path"):
        run_job("configs/cloud/local_dry_run.yaml", "mining_evaluation")

