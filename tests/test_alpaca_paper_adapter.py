from __future__ import annotations

import pytest

from quant_trade.execution.alpaca_paper import AlpacaPaperBroker
from quant_trade.execution.broker import BrokerOrderRequest
from quant_trade.execution.config import BrokerConfig
from quant_trade.execution.exceptions import BrokerCredentialsError, BrokerSafetyError


def test_dry_run_never_needs_credentials_or_network(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    cfg = BrokerConfig(provider="alpaca_paper", mode="paper", audit_dir=str(tmp_path))
    broker = AlpacaPaperBroker(cfg)
    result = broker.submit_order(BrokerOrderRequest("SPY", "buy", 1, "market", "day", "c1"))
    assert result.status == "dry_run"


def test_missing_credentials_for_account(monkeypatch) -> None:
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    broker = AlpacaPaperBroker(BrokerConfig(provider="alpaca_paper", mode="paper"))
    with pytest.raises(BrokerCredentialsError):
        broker.get_account()


def test_submit_without_confirm_fails(tmp_path) -> None:
    broker = AlpacaPaperBroker(
        BrokerConfig(provider="alpaca_paper", mode="paper", audit_dir=str(tmp_path))
    )
    with pytest.raises(BrokerSafetyError):
        broker.submit_order(
            BrokerOrderRequest("SPY", "buy", 1, "market", "day", "c1", dry_run=False)
        )
