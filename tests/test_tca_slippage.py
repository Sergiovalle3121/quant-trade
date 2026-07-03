import pytest

from quant_trade.tca.slippage import calculate_implementation_shortfall, calculate_slippage_bps


def test_slippage_bps_computed_with_approx():
    assert calculate_slippage_bps(100, 101, "buy") == pytest.approx(100)
    assert calculate_implementation_shortfall(100, 101, 2, "buy") == pytest.approx(2)
