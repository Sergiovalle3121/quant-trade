import pytest

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
