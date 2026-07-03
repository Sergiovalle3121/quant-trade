from __future__ import annotations

import numpy as np
import pandas as pd

from .correlation import drawdown_overlap_pairs, high_correlation_pairs, pairwise_correlation
from .models import PortfolioAllocation, PortfolioRiskReport


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    return float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0


def build_risk_report(
    allocation: PortfolioAllocation, returns: pd.DataFrame, max_pairwise_correlation: float
) -> PortfolioRiskReport:
    weights = {a.strategy_id: a.weight for a in allocation.allocations}
    warnings: list[str] = []
    if returns.empty or not weights:
        return PortfolioRiskReport(0.0, 0.0, 0.0, [], [], ["no returns available"])
    port = returns[list(weights)].mul(pd.Series(weights)).sum(axis=1)
    corr = pairwise_correlation(returns[list(weights)])
    high = high_correlation_pairs(corr, max_pairwise_correlation)
    if high:
        warnings.append("high correlation pairs exceed policy")
    return PortfolioRiskReport(
        float(port.std() * (252**0.5)),
        max_drawdown(port),
        float(corr.where(~np.eye(len(corr), dtype=bool)).abs().max().max() or 0.0),
        high,
        drawdown_overlap_pairs(returns[list(weights)]),
        warnings,
    )
