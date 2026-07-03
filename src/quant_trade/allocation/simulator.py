from __future__ import annotations

import pandas as pd

from .models import AllocationSimulationResult, PortfolioAllocation
from .risk_budget import build_risk_report, max_drawdown


def simulate_allocation(
    allocation: PortfolioAllocation, returns: pd.DataFrame, max_pairwise_correlation: float
) -> AllocationSimulationResult:
    weights = {a.strategy_id: a.weight for a in allocation.allocations}
    if not weights or returns.empty:
        metrics = {
            "total_return": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "contribution_to_return_by_strategy": {},
            "contribution_to_drawdown_by_strategy": {},
            "portfolio_turnover": 0.0,
            "cash_drag": allocation.cash_weight * 0.0,
            "real_money_ready": False,
        }
        return AllocationSimulationResult(
            allocation,
            metrics,
            [],
            build_risk_report(allocation, returns, max_pairwise_correlation),
        )
    aligned = returns[list(weights)].fillna(0.0)
    contrib = aligned.mul(pd.Series(weights))
    port = contrib.sum(axis=1)
    equity = (1 + port).cumprod()
    total = float(equity.iloc[-1] - 1)
    vol = float(port.std() * (252**0.5))
    downside = port[port < 0].std() * (252**0.5)
    dd = max_drawdown(port)
    metrics = {
        "total_return": total,
        "volatility": vol,
        "sharpe": float(port.mean() / port.std() * (252**0.5)) if port.std() else 0.0,
        "sortino": float(port.mean() / downside * (252**0.5)) if downside else 0.0,
        "max_drawdown": dd,
        "calmar": float(total / abs(dd)) if dd else 0.0,
        "contribution_to_return_by_strategy": {k: float(v.sum()) for k, v in contrib.items()},
        "contribution_to_drawdown_by_strategy": {
            k: float(contrib.loc[equity.idxmin(), k]) for k in contrib.columns
        },
        "portfolio_turnover": float(sum(abs(a.weight) for a in allocation.allocations)),
        "cash_drag": float(allocation.cash_weight * max(total, 0.0)),
        "real_money_ready": False,
    }
    curve = [
        {
            "date": str(idx.date()),
            "portfolio_return": float(port.loc[idx]),
            "equity": float(equity.loc[idx]),
        }
        for idx in equity.index
    ]
    return AllocationSimulationResult(
        allocation, metrics, curve, build_risk_report(allocation, returns, max_pairwise_correlation)
    )
