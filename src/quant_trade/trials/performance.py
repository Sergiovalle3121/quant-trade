from __future__ import annotations

import math
import statistics
from typing import Any

from .models import DailyTrialRecord


def _std(xs: list[float]) -> float:
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def _num(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def calculate_trial_performance(daily_records: list[DailyTrialRecord]) -> dict[str, Any]:
    if not daily_records:
        return {"days_observed": 0, "warnings": ["no daily records"], "real_money_ready": False}
    rs = [r.daily_return for r in daily_records]
    br = [r.benchmark_return for r in daily_records]
    total = daily_records[-1].cumulative_return
    # Compound the benchmark like the strategy leg; mixing an arithmetic sum
    # with a compounded return biases excess return with the sign of the
    # benchmark's variance drag.
    bench = math.prod(1 + b for b in br) - 1
    vol = _std(rs) * math.sqrt(252)
    downside = [min(0, x) for x in rs]
    orders = sum(r.orders_count for r in daily_records)
    rejects = sum(r.rejected_orders_count for r in daily_records)
    fills = sum(r.fills_count for r in daily_records)
    failures = sum(
        1
        for r in daily_records
        if r.heartbeat_status != "ok" or r.reconciliation_status != "pass" or r.kill_switch_active
    )
    return {
        "days_observed": len(daily_records),
        "calendar_days_elapsed": (daily_records[-1].date - daily_records[0].date).days + 1,
        "trial_progress_pct": 0.0,
        "total_return": total,
        "benchmark_return": bench,
        "excess_return": total - bench,
        "annualized_return_estimate": ((1 + total) ** (252 / max(1, len(rs))) - 1),
        "volatility": vol,
        "sharpe_estimate": (statistics.mean(rs) * 252 / vol if vol else 0.0),
        "sortino_estimate": (
            statistics.mean(rs) * 252 / (_std(downside) * math.sqrt(252)) if _std(downside) else 0.0
        ),
        "max_drawdown": min(r.drawdown for r in daily_records),
        "current_drawdown": daily_records[-1].drawdown,
        "average_daily_turnover": statistics.mean([r.turnover for r in daily_records]),
        "total_turnover": sum(r.turnover for r in daily_records),
        "average_slippage_bps": statistics.mean([r.slippage_bps for r in daily_records]),
        "rejected_order_rate": rejects / max(1, orders),
        "fill_rate": fills / max(1, orders),
        "operational_success_rate": 1 - failures / max(1, len(daily_records)),
        "stale_heartbeat_count": sum(1 for r in daily_records if r.heartbeat_status != "ok"),
        "reconciliation_fail_count": sum(
            1 for r in daily_records if r.reconciliation_status != "pass"
        ),
        "incident_count": sum(r.open_incidents_count for r in daily_records),
        "critical_incident_count": sum(1 for r in daily_records if r.open_incidents_count > 0),
        "days_since_last_rebalance": 0,
        "best_day": max(rs),
        "worst_day": min(rs),
        "positive_day_rate": sum(1 for r in rs if r > 0) / len(rs),
        "benchmark_correlation": _correlation(rs, br),
        "tracking_error": _std([a - b for a, b in zip(rs, br, strict=False)]) * math.sqrt(252),
        "information_ratio": _information_ratio(rs, br),
        "psr": _trial_psr(rs),
        "minimum_track_record_days": _min_track_record(rs),
        "warnings": [],
        "real_money_ready": False,
    }


def _correlation(rs: list[float], br: list[float]) -> float:
    if len(rs) < 3 or _std(rs) == 0 or _std(br) == 0:
        return 0.0
    return float(statistics.correlation(rs, br))


def _information_ratio(rs: list[float], br: list[float]) -> float:
    diffs = [a - b for a, b in zip(rs, br, strict=False)]
    te = _std(diffs)
    if te == 0 or not diffs:
        return 0.0
    return float(statistics.mean(diffs) * 252 / (te * math.sqrt(252)))


def _trial_psr(rs: list[float]) -> float:
    """P[true Sharpe > 0] for the trial's realized daily returns."""
    import pandas as pd

    from quant_trade.metrics.statistics import probabilistic_sharpe_ratio

    return probabilistic_sharpe_ratio(pd.Series(rs))


def _min_track_record(rs: list[float]) -> float:
    """Days of track record needed before the Sharpe is credibly above zero."""
    import pandas as pd

    from quant_trade.metrics.statistics import minimum_track_record_length

    value = minimum_track_record_length(pd.Series(rs))
    return float(value) if math.isfinite(value) else -1.0


def compare_trial_to_benchmark(daily_records: list[DailyTrialRecord]) -> dict[str, float]:
    p = calculate_trial_performance(daily_records)
    return {
        "benchmark_return": _num(p.get("benchmark_return", 0.0)),
        "excess_return": _num(p.get("excess_return", 0.0)),
        "tracking_error": _num(p.get("tracking_error", 0.0)),
    }


def calculate_operational_metrics(daily_records: list[DailyTrialRecord]) -> dict[str, float | int]:
    p = calculate_trial_performance(daily_records)
    keys = [
        "operational_success_rate",
        "stale_heartbeat_count",
        "reconciliation_fail_count",
        "incident_count",
        "critical_incident_count",
        "rejected_order_rate",
        "fill_rate",
    ]
    return {k: p[k] for k in keys if isinstance(p[k], int | float)}


def generate_performance_summary(daily_records: list[DailyTrialRecord]) -> dict[str, object]:
    return calculate_trial_performance(daily_records)
