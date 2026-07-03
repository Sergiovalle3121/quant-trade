from quant_trade.readiness.risk_of_ruin import estimate_risk_of_ruin


def test_risk_of_ruin_deterministic_with_seed():
    cfg = {"seed": 1, "paths": 50, "horizon_days": 10, "daily_returns": [0.01, -0.02, 0.0]}
    assert estimate_risk_of_ruin(cfg) == estimate_risk_of_ruin(cfg)
