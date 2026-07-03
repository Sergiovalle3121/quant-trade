import pytest

from quant_trade.cloud.config import CloudConfig
from quant_trade.cloud.exceptions import SafetyGateError
from quant_trade.cloud.jobs import validate_broker_submit_gates


def base(tmp_path, **kw):
    d = dict(
        deployment_name="d",
        artifact_uri=str(tmp_path / "o"),
        state_uri=str(tmp_path / "s"),
        heartbeat_uri=str(tmp_path / "h.json"),
        kill_switch_uri=str(tmp_path / "k.json"),
        mode="alpaca_paper_submit",
        allow_paper_order_submission=True,
        broker_provider="alpaca_paper",
    )
    d.update(kw)
    return CloudConfig(**d)


def test_missing_secrets_block(tmp_path):
    with pytest.raises(SafetyGateError):
        validate_broker_submit_gates(base(tmp_path))


def test_kill_switch_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_TRADE_GLOBAL_KILL_SWITCH", "true")
    with pytest.raises(SafetyGateError):
        validate_broker_submit_gates(base(tmp_path))
