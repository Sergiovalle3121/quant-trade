from __future__ import annotations

import pytest

from quant_trade.execution.broker import BrokerAccount, BrokerOrderRequest
from quant_trade.execution.config import BrokerConfig
from quant_trade.execution.exceptions import BrokerSafetyError
from quant_trade.execution.safety import (
    sanitize_raw_payload,
    validate_alpaca_paper_endpoint,
    validate_order_safety,
    validate_paper_mode,
)


def test_paper_endpoint_validation() -> None:
    assert (
        validate_alpaca_paper_endpoint("https://paper-api.alpaca.markets/")
        == "https://paper-api.alpaca.markets"
    )
    for url in ("", "https://api.alpaca.markets", "https://evil.example"):
        with pytest.raises(BrokerSafetyError):
            validate_alpaca_paper_endpoint(url)


def test_live_mode_rejected() -> None:
    with pytest.raises(BrokerSafetyError):
        validate_paper_mode(
            BrokerConfig(provider="alpaca_paper", mode="paper", allow_live_trading=True)
        )


def test_secrets_redacted() -> None:
    payload = sanitize_raw_payload(
        {"Authorization": "Bearer abcdef", "nested": {"secret_key": "123456"}}
    )
    assert "abcdef" not in str(payload)
    assert "123456" not in str(payload)


def test_order_safety_rejects_oversized_and_short_flags() -> None:
    account = BrokerAccount("alpaca_paper", "x****", "USD", 1000, 1000, 1000, "active", True)
    order = BrokerOrderRequest("SPY", "buy", 2000, "market", "day", "c1")
    with pytest.raises(BrokerSafetyError):
        validate_order_safety(order, BrokerConfig(max_notional_per_order=100), account)
    with pytest.raises(BrokerSafetyError):
        validate_order_safety(
            BrokerOrderRequest("SPY", "sell", 1, "market", "day", "c2", reason="short"),
            BrokerConfig(),
            account,
        )
