"""Simulation-only stress testing and scenario lab."""

from quant_trade.stress.config import load_stress_policy, load_stress_scenarios, load_suite_config
from quant_trade.stress.costs import apply_cost_shock
from quant_trade.stress.models import (
    StressPolicy,
    StressPortfolioReport,
    StressResult,
    StressScenario,
)
from quant_trade.stress.reports import generate_stress_report
from quant_trade.stress.scenarios import rank_scenarios_by_loss
from quant_trade.stress.shocks import apply_price_shock
from quant_trade.stress.simulator import (
    run_scenario_suite,
    stress_allocation_portfolio,
    stress_strategy_equity_curve,
)

__all__ = [
    "StressPolicy",
    "StressPortfolioReport",
    "StressResult",
    "StressScenario",
    "apply_cost_shock",
    "apply_price_shock",
    "generate_stress_report",
    "load_stress_policy",
    "load_stress_scenarios",
    "load_suite_config",
    "rank_scenarios_by_loss",
    "run_scenario_suite",
    "stress_allocation_portfolio",
    "stress_strategy_equity_curve",
]
