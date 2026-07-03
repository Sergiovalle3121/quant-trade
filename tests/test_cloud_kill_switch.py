import pytest

from quant_trade.cloud.config import CloudConfig
from quant_trade.cloud.exceptions import SafetyGateError
from quant_trade.cloud.kill_switch import (
    activate_kill_switch,
    assert_not_killed,
    clear_kill_switch,
    get_kill_switch_status,
)


def cfg(tmp_path):
    return CloudConfig(
        deployment_name="d",
        artifact_uri=str(tmp_path / "o"),
        state_uri=str(tmp_path / "s"),
        heartbeat_uri=str(tmp_path / "h.json"),
        kill_switch_uri=str(tmp_path / "k.json"),
    )


def test_activate_clear(tmp_path):
    c = cfg(tmp_path)
    activate_kill_switch(c, "test", "me")
    assert get_kill_switch_status(c).active
    clear_kill_switch(c, "reset", "me")
    assert not get_kill_switch_status(c).active


def test_env_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_TRADE_GLOBAL_KILL_SWITCH", "true")
    with pytest.raises(SafetyGateError):
        assert_not_killed(cfg(tmp_path))
