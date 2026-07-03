import pytest

from quant_trade.allocation.config import load_allocation_config
from quant_trade.allocation.models import AllocationPolicy


def test_policy_rejects_real_money_enabled():
    raw = dict(
        max_total_capital=1,
        max_strategy_weight=0.5,
        min_strategy_weight=0.1,
        max_strategy_drawdown=0.1,
        max_portfolio_drawdown=0.1,
        max_pairwise_correlation=0.8,
        max_cluster_exposure=0.5,
        max_single_strategy_loss_contribution=0.5,
        min_cash_buffer_pct=0.1,
        real_money_enabled=True,
    )
    with pytest.raises(ValueError):
        AllocationPolicy.from_dict(raw)


def test_load_conservative_config():
    cfg = load_allocation_config("configs/allocation/conservative_portfolio.yaml")
    assert cfg["policy"].real_money_enabled is False
