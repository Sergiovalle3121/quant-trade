from quant_trade.readiness.loss_limits import calculate_loss_limits


def test_loss_limits_are_paper_only():
    r = calculate_loss_limits({"paper_capital": 10000})
    assert r["portfolio_max_daily_loss"] == 200
    assert r["real_money_ready"] is False
