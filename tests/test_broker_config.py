from pathlib import Path

from quant_trade.execution.config import load_broker_config


def test_load_broker_config() -> None:
    cfg = load_broker_config(Path("configs/broker/alpaca_paper.example.yaml"))
    assert cfg.provider == "alpaca_paper"
    assert cfg.dry_run_default is True
