from __future__ import annotations

import pytest

from quant_trade.execution.config import BrokerConfig
from quant_trade.execution.exceptions import BrokerSafetyError
from quant_trade.execution.order_mapper import paper_order_to_broker_order_request
from quant_trade.paper.models import PaperOrder


def test_maps_buy_and_sell() -> None:
    cfg = BrokerConfig(universe=["SPY"])
    for side in ("buy", "sell"):
        req = paper_order_to_broker_order_request(PaperOrder("1", "t", "SPY", side, 1.5), cfg)  # type: ignore[arg-type]
        assert req.side == side
        assert req.symbol == "SPY"


def test_rejects_bad_quantity_and_unknown_symbol() -> None:
    with pytest.raises(BrokerSafetyError):
        paper_order_to_broker_order_request(PaperOrder("1", "t", "SPY", "buy", 0), BrokerConfig())
    with pytest.raises(BrokerSafetyError):
        paper_order_to_broker_order_request(
            PaperOrder("1", "t", "XYZ", "buy", 1), BrokerConfig(universe=["SPY"])
        )
