"""Simulation-only stress suite engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.stress.costs import apply_cost_shock, estimate_liquidity_cost
from quant_trade.stress.models import StressPolicy, StressResult, StressScenario
from quant_trade.stress.scenarios import missing_required_symbols, rank_scenarios_by_loss
from quant_trade.stress.shocks import apply_scenario_shock


def _sample_data(symbols: list[str]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        for idx, close in enumerate((100.0, 101.0, 99.0, 102.0, 100.0)):
            rows.append(
                {
                    "date": f"2020-01-0{idx + 1}",
                    "symbol": symbol,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000,
                }
            )
    return pd.DataFrame(rows)


def load_stress_data(config: dict[str, Any]) -> pd.DataFrame:
    path = config.get("data_path")
    if path and Path(path).exists():
        return pd.read_csv(path)
    symbols = list(config.get("symbols", ["SPY", "TLT", "GLD"]))
    return _sample_data(symbols)


def _equity_from_prices(data: pd.DataFrame) -> pd.Series:
    if data.empty or "close" not in data.columns:
        return pd.Series(dtype="float64")
    if "date" in data.columns and "symbol" in data.columns:
        pivot = data.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
        returns = pivot.pct_change(fill_method=None).fillna(0.0).mean(axis=1)
    else:
        returns = data["close"].astype(float).pct_change().fillna(0.0)
    return (1.0 + returns).cumprod()


def stress_strategy_equity_curve(data: pd.DataFrame, scenario: StressScenario) -> pd.Series:
    return _equity_from_prices(apply_scenario_shock(data, scenario))


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def _daily_loss(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float(equity.pct_change().fillna(0.0).min())


def stress_allocation_portfolio(
    data: pd.DataFrame,
    scenario: StressScenario,
    policy: StressPolicy,
    cost_model: dict[str, float] | None = None,
) -> StressResult:
    warnings: list[str] = []
    missing = set(missing_required_symbols(data, scenario)) | set(
        symbol
        for symbol in policy.required_symbols
        if "symbol" in data.columns and symbol not in set(data["symbol"].astype(str))
    )
    if data.empty:
        warnings.append("missing data: input price data is empty")
    if missing:
        warnings.append("missing required symbols: " + ", ".join(sorted(missing)))
    equity = stress_strategy_equity_curve(data, scenario)
    total_return = 0.0 if equity.empty else float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    max_dd = _max_drawdown(equity)
    daily_loss = _daily_loss(equity)
    shocked_costs = apply_cost_shock(
        cost_model or {"slippage_bps": 2.0, "spread_bps": 1.0}, scenario
    )
    liquidity_cost = estimate_liquidity_cost(100_000.0, shocked_costs)
    slippage = float(shocked_costs.get("slippage_bps", 0.0))
    breaches = [
        daily_loss < -policy.max_daily_loss_pct,
        max_dd < -policy.max_drawdown_pct,
        liquidity_cost / 100_000.0 > policy.max_liquidity_cost_pct,
        slippage > policy.max_slippage_bps,
        bool(warnings),
    ]
    breach_count = sum(bool(item) for item in breaches)
    return StressResult(
        scenario.name,
        scenario.scenario_type,
        total_return,
        max_dd,
        daily_loss,
        liquidity_cost,
        slippage,
        min(policy.max_exposure, 1.0),
        breach_count,
        breach_count == 0,
        tuple(warnings),
        abs(min(total_return, daily_loss, max_dd, 0.0)) * 100_000.0,
        int(max(0.0, abs(max_dd)) * 252),
    )


def run_scenario_suite(
    data: pd.DataFrame,
    scenarios: tuple[StressScenario, ...],
    policy: StressPolicy,
    cost_model: dict[str, float] | None = None,
) -> list[StressResult]:
    return [
        stress_allocation_portfolio(data, scenario, policy, cost_model) for scenario in scenarios
    ]


__all__ = [
    "rank_scenarios_by_loss",
    "run_scenario_suite",
    "stress_allocation_portfolio",
    "stress_strategy_equity_curve",
    "load_stress_data",
]
