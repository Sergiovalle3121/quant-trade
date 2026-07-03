from quant_trade.allocation.allocators import equal_weight_allocator
from quant_trade.allocation.config import load_policy, load_registry
from quant_trade.allocation.correlation import load_returns


def test_allocation_respects_max_strategy_weight_and_cash_buffer():
    policy = load_policy('configs/allocation/risk_budget_policy.yaml')
    candidates = load_registry('configs/allocation/allocation_registry.yaml')[:2]
    alloc = equal_weight_allocator('test', candidates, load_returns(candidates), policy)
    assert all(a.weight <= policy.max_strategy_weight for a in alloc.allocations)
    assert alloc.cash_weight >= policy.min_cash_buffer_pct
