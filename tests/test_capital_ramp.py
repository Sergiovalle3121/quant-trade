from quant_trade.readiness.capital_ramp import simulate_capital_ramp


def test_capital_ramp_calculates_dollar_drawdown():
    rows = simulate_capital_ramp({"capital_levels": [10000], "max_drawdown_pct": 0.1})
    assert rows[0].drawdown_dollars == 1000
    assert rows[0].real_money_ready is False
