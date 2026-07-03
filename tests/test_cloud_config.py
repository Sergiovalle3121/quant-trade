from pathlib import Path

import pytest

from quant_trade.cloud.config import CloudConfig, load_cloud_config


def test_local_config_loads():
    cfg = load_cloud_config(Path("configs/cloud/local_dry_run.yaml"))
    assert cfg.mode == "dry_run"
    assert cfg.allow_live_trading is False


def test_live_trading_rejected():
    with pytest.raises(ValueError):
        CloudConfig(
            deployment_name="x",
            artifact_uri="o",
            state_uri="s",
            heartbeat_uri="h",
            kill_switch_uri="k",
            allow_live_trading=True,
        )


def test_submit_requires_gate():
    with pytest.raises(ValueError):
        CloudConfig(
            deployment_name="x",
            artifact_uri="o",
            state_uri="s",
            heartbeat_uri="h",
            kill_switch_uri="k",
            mode="alpaca_paper_submit",
            broker_provider="alpaca_paper",
        )
