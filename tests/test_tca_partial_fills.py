from quant_trade.tca.partial_fills import simulate_partial_fills


def test_partial_fills_limited_by_volume():
    result = simulate_partial_fills(200, available_volume=1000, max_participation_rate=0.1)
    assert result.filled_quantity == 100
    assert result.status == "partial"
