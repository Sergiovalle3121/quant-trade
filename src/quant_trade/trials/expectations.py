from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import utc_now


@dataclass
class ExpectedPerformance:
    strategy_name: str
    benchmark: str
    research_run_dir: str
    train_metrics: dict[str, Any]
    test_metrics: dict[str, Any]
    benchmark_metrics: dict[str, Any]
    cost_sensitivity_metrics: dict[str, Any]
    subperiod_metrics: dict[str, Any]
    expected_daily_return_range: tuple[float, float]
    expected_monthly_return_range: tuple[float, float]
    expected_volatility_range: tuple[float, float]
    expected_drawdown_range: tuple[float, float]
    expected_turnover_range: tuple[float, float]
    expected_sharpe_range: tuple[float, float]
    expected_hit_rate_range: tuple[float, float] | None = None
    expected_slippage_bps_range: tuple[float, float] | None = None
    confidence_level: str = "low"
    limitations: list[str] = field(default_factory=list)
    generated_at_utc: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def derive_expectation_ranges(
    metrics: dict[str, Any], robustness_artifacts: dict[str, Any] | None = None
) -> ExpectedPerformance:
    daily = float(metrics.get("mean_daily_return", metrics.get("daily_return", 0.0005)))
    vol = float(metrics.get("volatility", 0.12))
    dd = float(metrics.get("max_drawdown", -0.08))
    sharpe = float(metrics.get("sharpe", 0.5))
    turnover = float(metrics.get("turnover", 0.1))
    return ExpectedPerformance(
        str(metrics.get("strategy_name", "unknown")),
        str(metrics.get("benchmark", "SPY")),
        str(metrics.get("research_run_dir", "")),
        {},
        metrics,
        {},
        robustness_artifacts or {},
        {},
        (daily - 0.002, daily + 0.002),
        (daily * 21 - 0.05, daily * 21 + 0.05),
        (max(0, vol * 0.5), vol * 1.75),
        (dd * 1.5, 0.0),
        (0.0, max(0.05, turnover * 2)),
        (sharpe - 1, sharpe + 1),
        (0.35, 0.65),
        (0.0, 8.0),
        "medium",
        ["Research expectations are uncertain ranges, not profitability promises."],
    )


def load_expectations_from_research_artifacts(
    research_run_dir: Path | str | None,
) -> ExpectedPerformance:
    if not research_run_dir:
        return derive_expectation_ranges({"strategy_name": "unknown", "benchmark": "SPY"})
    root = Path(research_run_dir)
    files = ["metrics.json", "summary.json", "research_metrics.json"]
    data = {}
    warnings = []
    for name in files:
        p = root / name
        if p.exists():
            data.update(json.loads(p.read_text(encoding="utf-8")))
    if not data:
        warnings.append("missing research metrics; confidence lowered")
    exp = derive_expectation_ranges(data or {"strategy_name": "unknown", "benchmark": "SPY"})
    exp.research_run_dir = str(root)
    exp.limitations.extend(warnings)
    exp.confidence_level = "low" if warnings else exp.confidence_level
    return exp


def compare_actual_to_expectations(
    actual_metrics: dict[str, Any], expected_performance: ExpectedPerformance
) -> dict[str, Any]:
    warnings = []
    breaches = []
    # total_return is cumulative over the whole trial; the expectation range
    # is a 21-bar (monthly) bound. Pro-rate the bound to the observed horizon
    # or a 90-day trial can never breach a monthly floor.
    observed_days = max(1.0, float(actual_metrics.get("days_observed", 21)))
    horizon_factor = observed_days / 21.0
    scaled_floor = expected_performance.expected_monthly_return_range[0] * max(
        1.0, horizon_factor
    )
    if float(actual_metrics.get("total_return", 0)) < scaled_floor:
        breaches.append("performance below expected range")
    if (
        float(actual_metrics.get("volatility", 0))
        > expected_performance.expected_volatility_range[1]
    ):
        warnings.append("volatility above expected range")
    if (
        float(actual_metrics.get("max_drawdown", 0))
        < expected_performance.expected_drawdown_range[0]
    ):
        breaches.append("drawdown worse than expected range")
    if (
        float(actual_metrics.get("average_daily_turnover", 0))
        > expected_performance.expected_turnover_range[1]
    ):
        warnings.append("turnover above expected range")
    return {
        "breaches": breaches,
        "warnings": warnings,
        "confidence_level": expected_performance.confidence_level,
        "real_money_ready": False,
    }
