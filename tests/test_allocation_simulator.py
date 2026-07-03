from quant_trade.allocation.allocators import equal_weight_allocator
from quant_trade.allocation.config import load_policy, load_registry
from quant_trade.allocation.correlation import load_returns
from quant_trade.allocation.simulator import simulate_allocation


def test_portfolio_metrics_calculate_correctly():
    policy = load_policy("configs/allocation/risk_budget_policy.yaml")
    candidates = load_registry("configs/allocation/allocation_registry.yaml")[:2]
    returns = load_returns(candidates)
    alloc = equal_weight_allocator("test", candidates, returns, policy)
    result = simulate_allocation(alloc, returns, policy.max_pairwise_correlation)
    assert "total_return" in result.metrics
    assert result.metrics["real_money_ready"] is False
    assert len(result.equity_curve) == len(returns)
