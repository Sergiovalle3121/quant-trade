from quant_trade.allocation.config import load_registry
from quant_trade.allocation.correlation import (
    high_correlation_pairs,
    load_returns,
    pairwise_correlation,
)


def test_high_correlation_is_flagged():
    candidates = [
        c
        for c in load_registry("configs/allocation/allocation_registry.yaml")
        if c.strategy_id != "missing_evidence"
    ]
    clone = candidates[0].__class__(
        "clone_paper",
        "clone",
        "approved_paper",
        ["tests/fixtures/allocation/clone_evidence.md"],
        "tests/fixtures/allocation/clone_returns.csv",
        approved_for_paper=True,
    )
    returns = load_returns([candidates[0], clone])
    assert high_correlation_pairs(pairwise_correlation(returns), 0.85)
