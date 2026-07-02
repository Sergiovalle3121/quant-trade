from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_research_summary(
    path: Path,
    *,
    experiment_name: str,
    dataset_info: dict[str, Any],
    strategy: str,
    strategy_params: dict[str, Any],
    benchmark: dict[str, Any],
    train_metrics: dict[str, Any],
    test_metrics: dict[str, Any],
    comparison: dict[str, Any],
    robustness_files: list[str],
) -> None:
    red = []
    if test_metrics.get("sharpe", 0) < train_metrics.get("sharpe", 0) * 0.5:
        red.append("Test Sharpe is much lower than train Sharpe.")
    if comparison.get("excess_return", 0) < 0:
        red.append("Strategy loses to benchmark out-of-sample.")
    if test_metrics.get("max_drawdown", 0) < -0.25:
        red.append("Max drawdown may be too high.")
    if test_metrics.get("total_turnover", 0) > 12:
        red.append("Turnover is high; costs may dominate.")
    lines = [
        f"# {experiment_name}",
        "",
        "## Scope and safety warning",
        "Research/backtesting only. No live trading, broker connectivity, "
        "order routing, leverage, or profitability claims.",
        "",
        "## Dataset information",
        str(dataset_info),
        "",
        "## Strategy parameters",
        f"Strategy: `{strategy}`",
        str(strategy_params),
        "",
        "## Benchmark",
        str(benchmark),
        "",
        "## Train metrics",
        str(train_metrics),
        "",
        "## Test metrics",
        str(test_metrics),
        "",
        "## Benchmark comparison",
        str(comparison),
        "",
        "## Robustness diagnostics",
        ", ".join(robustness_files) or "Not requested.",
        "",
        "## Cost sensitivity",
        "See cost_sensitivity.csv when enabled.",
        "",
        "## Red flags",
        *(red or ["No automatic red flags triggered; human review is still required."]),
        "",
        "## Next actions",
        "Review OOS behavior, parameter stability, costs, turnover, and "
        "economic rationale before paper-trading readiness work.",
    ]
    path.write_text("\n".join(lines) + "\n")
