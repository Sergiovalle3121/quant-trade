import pytest

from quant_trade.execution.ibkr_stub import IBKRStub


def test_ibkr_stub_raises() -> None:
    with pytest.raises(NotImplementedError, match="IBKR integration is not implemented"):
        IBKRStub()
