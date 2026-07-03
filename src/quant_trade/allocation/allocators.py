from __future__ import annotations

import pandas as pd

from .models import AllocationCandidate, AllocationPolicy, PortfolioAllocation, StrategyAllocation


def _bounded(weights: dict[str, float], policy: AllocationPolicy) -> dict[str, float]:
    investable = max(0.0, 1.0 - policy.min_cash_buffer_pct)
    if not weights:
        return {}
    clipped = {
        k: min(policy.max_strategy_weight, max(policy.min_strategy_weight, v))
        for k, v in weights.items()
    }
    total = sum(clipped.values())
    if total <= 0:
        return {k: 0.0 for k in clipped}
    scaled = {k: v / total * investable for k, v in clipped.items()}
    return {k: min(policy.max_strategy_weight, v) for k, v in scaled.items()}


def _build(
    run_id: str,
    weights: dict[str, float],
    policy: AllocationPolicy,
    warnings: dict[str, list[str]] | None = None,
) -> PortfolioAllocation:
    total_weight = sum(weights.values())
    allocs = [
        StrategyAllocation(k, v, v * policy.max_total_capital, warnings=(warnings or {}).get(k, []))
        for k, v in sorted(weights.items())
        if v > 0
    ]
    return PortfolioAllocation(
        run_id,
        policy.max_total_capital,
        max(0.0, 1.0 - total_weight),
        allocs,
        real_money_ready=False,
    )


def equal_weight_allocator(
    run_id: str,
    candidates: list[AllocationCandidate],
    returns: pd.DataFrame,
    policy: AllocationPolicy,
) -> PortfolioAllocation:
    raw = {c.strategy_id: 1.0 / len(candidates) for c in candidates} if candidates else {}
    return _build(run_id, _bounded(raw, policy), policy)


def inverse_volatility_allocator(
    run_id: str,
    candidates: list[AllocationCandidate],
    returns: pd.DataFrame,
    policy: AllocationPolicy,
) -> PortfolioAllocation:
    raw: dict[str, float] = {}
    warnings: dict[str, list[str]] = {}
    for c in candidates:
        vol = c.expected_volatility or (
            float(returns[c.strategy_id].std() * (252**0.5)) if c.strategy_id in returns else 0.0
        )
        if vol <= 0:
            vol = 1.0
            warnings[c.strategy_id] = ["missing or zero volatility; neutral score used"]
        raw[c.strategy_id] = 1.0 / vol
    s = sum(raw.values()) or 1.0
    return _build(run_id, _bounded({k: v / s for k, v in raw.items()}, policy), policy, warnings)


def drawdown_adjusted_allocator(
    run_id: str,
    candidates: list[AllocationCandidate],
    returns: pd.DataFrame,
    policy: AllocationPolicy,
) -> PortfolioAllocation:
    raw: dict[str, float] = {}
    for c in candidates:
        dd = abs(
            c.max_drawdown if c.max_drawdown is not None else _max_drawdown(returns[c.strategy_id])
        )
        raw[c.strategy_id] = max(0.0, policy.max_strategy_drawdown - dd)
    s = sum(raw.values()) or 1.0
    return _build(run_id, _bounded({k: v / s for k, v in raw.items()}, policy), policy)


def risk_budget_allocator(
    run_id: str,
    candidates: list[AllocationCandidate],
    returns: pd.DataFrame,
    policy: AllocationPolicy,
) -> PortfolioAllocation:
    inv = inverse_volatility_allocator(run_id, candidates, returns, policy)
    weights = {a.strategy_id: a.weight for a in inv.allocations}
    if policy.volatility_target and not returns.empty:
        port = returns[list(weights)].mul(pd.Series(weights)).sum(axis=1)
        vol = float(port.std() * (252**0.5))
        if vol > policy.volatility_target and vol > 0:
            weights = {k: v * policy.volatility_target / vol for k, v in weights.items()}
    return _build(run_id, _bounded(weights, policy), policy)


def conservative_blend_allocator(
    run_id: str,
    candidates: list[AllocationCandidate],
    returns: pd.DataFrame,
    policy: AllocationPolicy,
) -> PortfolioAllocation:
    eq = {
        a.strategy_id: a.weight
        for a in equal_weight_allocator(run_id, candidates, returns, policy).allocations
    }
    iv = {
        a.strategy_id: a.weight
        for a in inverse_volatility_allocator(run_id, candidates, returns, policy).allocations
    }
    dd = {
        a.strategy_id: a.weight
        for a in drawdown_adjusted_allocator(run_id, candidates, returns, policy).allocations
    }
    keys = set(eq) | set(iv) | set(dd)
    return _build(
        run_id,
        _bounded({k: (eq.get(k, 0) + iv.get(k, 0) + dd.get(k, 0)) / 3 for k in keys}, policy),
        policy,
    )


def _max_drawdown(r: pd.Series) -> float:
    equity = (1 + r.astype(float)).cumprod()
    return float((equity / equity.cummax() - 1).min())


ALLOCATORS = {
    "equal_weight": equal_weight_allocator,
    "inverse_volatility": inverse_volatility_allocator,
    "drawdown_adjusted": drawdown_adjusted_allocator,
    "risk_budget": risk_budget_allocator,
    "conservative_blend": conservative_blend_allocator,
}
