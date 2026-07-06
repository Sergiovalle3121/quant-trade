from __future__ import annotations

import pandas as pd

from quant_trade.metrics.performance import periods_per_year

from .models import AllocationCandidate, AllocationPolicy, PortfolioAllocation, StrategyAllocation


def _bounded(weights: dict[str, float], policy: AllocationPolicy) -> dict[str, float]:
    """Clip weights to policy bounds and cap gross exposure at the investable
    fraction.

    Zero and negative raw weights stay at zero: an allocator that deliberately
    excluded a strategy (e.g. after a drawdown breach) must not have it
    resurrected by the minimum-weight floor. Totals below the investable
    fraction are preserved rather than scaled back up, so deliberate
    de-risking (volatility targeting) survives this pass.
    """
    investable = max(0.0, 1.0 - policy.min_cash_buffer_pct)
    if not weights:
        return {}
    clipped = {
        k: min(policy.max_strategy_weight, max(policy.min_strategy_weight, v)) if v > 0 else 0.0
        for k, v in weights.items()
    }
    total = sum(clipped.values())
    if total <= 0:
        return {k: 0.0 for k in clipped}
    if total > investable:
        scale = investable / total
        clipped = {k: v * scale for k, v in clipped.items()}
    return clipped


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
    if policy.volatility_target and not returns.empty and weights:
        available = [k for k in weights if k in returns.columns]
        if available:
            port = returns[available].mul(pd.Series({k: weights[k] for k in available})).sum(axis=1)
            ppy = periods_per_year(port.index)
            vol = float(port.std() * (ppy**0.5))
            if vol > policy.volatility_target and vol > 0:
                # Scale down after bounding; re-running _bounded here would
                # renormalize gross exposure back up and undo the targeting.
                scale = policy.volatility_target / vol
                weights = {k: v * scale for k, v in weights.items()}
    return _build(run_id, weights, policy)


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
