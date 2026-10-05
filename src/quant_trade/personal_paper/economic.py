"""Review a frozen prospective SIMULATION; never authorize real execution.

The sealed MXN capital is the initial wealth, before the first observed close.
That partial initial interval affects net return and drawdown, including FX and
operating expenses, but is never annualized as a daily return. Bootstrap draws
only complete close-to-close intervals and holds the initial partial return
fixed. Each candidate bears the complete bot expense as a separate hypothetical
deployment; the passive control bears only FX and transfer costs.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.metrics import statistics
from quant_trade.metrics.statistics import (
    deflated_sharpe_ratio,
    sharpe_variance_across_trials,
)

CANDIDATES = ("inverse_volatility", "vol_targeted_equal_weight")
CONTROL = "equal_weight_quarterly"
COST_CATEGORIES = ("infrastructure", "data", "fx_transfer")
SEED = 20261005
BOOTSTRAP_SAMPLES = 10_000
BLOCK_SESSIONS = 20
MINIMUM_FULL_RETURN_OBSERVATIONS = 252


def economic_protocol() -> dict[str, Any]:
    """Versioned economic criteria and implementation, sealed before observing.

    It is intentionally separate from execution policy: changing review rules,
    resampling choices or statistics code requires a new registered experiment.
    """
    return {
        "schema_version": 2,
        "evidence_kind": "PROSPECTIVE_SIMULATION",
        "exchange": "XNYS",
        "calendar_policy": "all_exact_official_closes_after_seal_without_gaps",
        "initial_wealth": "sealed_capital_mxn_at_prospective_started_at",
        "initial_partial_interval": "net_return_and_drawdown_only; fixed_in_bootstrap",
        "minimum_closed_sessions": MINIMUM_FULL_RETURN_OBSERVATIONS + 1,
        "minimum_complete_close_to_close_returns": MINIMUM_FULL_RETURN_OBSERVATIONS,
        "annualization": {"periods_per_year": 252, "returns": "complete_close_to_close_only"},
        "candidates": list(CANDIDATES),
        "control": CONTROL,
        "cost_scenarios_reviewed": [1, 2],
        "cost_coverage": "seal_through_last_close; explicit_nonnegative_expenses_including_zero",
        "cost_allocation": "full_bot_expense_per_candidate; control_fx_transfer_only",
        "criteria": {
            "net_positive_1x": True,
            "net_positive_2x": True,
            "minimum_annualized_sharpe_gap": 0.10,
            "maximum_drawdown_fraction_of_control": 0.90,
            "positive_control_drawdown_required": True,
            "bootstrap_sharpe_gap_lower_bound_positive": True,
            "bootstrap_drawdown_advantage_lower_bound_positive": True,
            "minimum_deflated_sharpe_probability": 0.975,
            "complete_historical_trials_and_nondegenerate_moments_required": True,
        },
        "bootstrap": {
            "samples": BOOTSTRAP_SAMPLES,
            "block_sessions": BLOCK_SESSIONS,
            "seed": SEED,
            "method": "paired_circular_moving_blocks",
            "family_wise_alpha": 0.05,
            "candidate_count": len(CANDIDATES),
            "interval_quantiles": [0.025, 0.975],
            "initial_partial_interval": "fixed; excluded_from_sharpe_and_resampling",
        },
        "code_sha256": {
            "personal_paper/economic.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "metrics/statistics.py": hashlib.sha256(
                Path(statistics.__file__).read_bytes()
            ).hexdigest(),
        },
        "real_money_approved": False,
    }


def economic_protocol_hash() -> str:
    content = json.dumps(
        economic_protocol(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(content.encode()).hexdigest()


def _utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("timestamps must be present and timezone-aware")
    return stamp.tz_convert("UTC")


def _metrics(closes: np.ndarray, baseline: float) -> dict[str, float]:
    # The seal-to-first-close interval can be hours or days, never a daily sample.
    returns = closes[1:] / closes[:-1] - 1.0
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    path = np.concatenate(([baseline], closes))
    return {
        "net_return": float(closes[-1] / baseline - 1.0),
        "sharpe": float(returns.mean() / std * math.sqrt(252)) if std > 0 else 0.0,
        "max_drawdown": float((1.0 - path / np.maximum.accumulate(path)).max()),
        "initial_partial_return": float(closes[0] / baseline - 1.0),
    }


def _trial_history(path: Path) -> tuple[int, float | None, dict[str, Any]]:
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not records or any(not isinstance(row, dict) for row in records):
        raise ValueError("historical trial ledger must contain nonempty object records")
    sharpes: list[float] = []
    complete = True
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        value = row.get("test_sharpe_per_period")
        if value is None:
            complete = False
        elif isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError("historical trial ledger contains invalid Sharpe")
        else:
            sharpes.append(float(value))
        if "trials_in_window" in row:
            declared = row["trials_in_window"]
            if isinstance(declared, bool) or not isinstance(declared, int) or declared < 1:
                raise ValueError("historical trial count must be a positive integer")
            key = json.dumps(
                {
                    k: row.get(k)
                    for k in ("source", "experiment_name", "strategy", "window", "data_sha256")
                },
                sort_keys=True,
            )
            groups.setdefault(key, []).append(row)
    incomplete_groups = []
    for key, rows in sorted(groups.items()):
        counts = {row["trials_in_window"] for row in rows}
        configurations = {
            json.dumps(row.get("strategy_params", {}), sort_keys=True) for row in rows
        }
        expected = max(counts)
        if len(counts) != 1 or len(configurations) != expected:
            complete = False
            incomplete_groups.append(
                {
                    **json.loads(key),
                    "declared_trials": sorted(counts),
                    "recorded_unique_configurations": len(configurations),
                }
            )
    diagnostics = {
        "record_count": len(records),
        "window_group_count": len(groups),
        "incomplete_window_group_count": len(incomplete_groups),
        "incomplete_window_groups": incomplete_groups,
        "selection_history_complete": complete,
        "count_policy": "all_frozen_records_plus_two_prespecified_candidates",
    }
    # Missing alternatives cannot be assigned invented Sharpe values. The shared
    # routine's zero-variance fallback is uncorrected PSR, which is inadmissible.
    if not complete or len(sharpes) < 2:
        return len(records), None, diagnostics
    variance = sharpe_variance_across_trials(sharpes)
    return (
        len(records),
        variance if math.isfinite(variance) and variance > 0 else None,
        diagnostics,
    )


def _calendar_matches(dates: pd.DatetimeIndex, start: pd.Timestamp) -> bool:
    if len(dates) == 0:
        return True
    try:
        import exchange_calendars as xcals
    except ImportError:
        return False
    # The calendar factory requires start < end, even for a single new close.
    left = start - pd.Timedelta(days=1)
    right = dates[-1] + pd.Timedelta(days=1)
    try:
        calendar = xcals.get_calendar("XNYS", start=str(left.date()), end=str(right.date()))
    except ValueError:
        return False
    closes = pd.DatetimeIndex(pd.to_datetime(calendar.schedule["close"], utc=True))
    expected = closes[(closes > start) & (closes <= dates[-1])]
    return dates.equals(expected)


def _cost_paths(
    costs: pd.DataFrame,
    dates: pd.DatetimeIndex,
    *,
    prospective_started_at: pd.Timestamp,
) -> dict[str, np.ndarray]:
    required = {"start", "end", "category", "amount_mxn"}
    if not required.issubset(costs.columns):
        raise ValueError("costs require start,end,category,amount_mxn")
    prepared = costs.copy()
    prepared["start"] = prepared["start"].map(_utc)
    prepared["end"] = prepared["end"].map(_utc)
    prepared["amount_mxn"] = pd.to_numeric(prepared["amount_mxn"], errors="raise")
    if not np.isfinite(prepared["amount_mxn"]).all() or (prepared["amount_mxn"] < 0).any():
        raise ValueError("observed costs must be finite and nonnegative")
    if not set(prepared["category"]).issubset(COST_CATEGORIES):
        raise ValueError("unknown observed cost category")
    if (prepared.end <= prepared.start).any():
        raise ValueError("observed cost interval must have positive duration")
    # Half-open expense intervals cover the seal through the last close exactly.
    # The endpoint has zero duration: no extra day or future expense is required.
    start, end = prospective_started_at, dates[-1]
    paths: dict[str, np.ndarray] = {}
    for category in COST_CATEGORIES:
        rows = prepared[prepared.category == category].sort_values("start")
        cursor = start
        cumulative = np.zeros(len(dates), dtype=float)
        for row in rows.itertuples(index=False):
            left, right = row.start, row.end
            if right <= start or left >= end:
                continue
            clipped_left, clipped_right = max(left, start), min(right, end)
            if clipped_left > cursor:
                raise ValueError(f"missing observed cost coverage: {category}")
            if clipped_left < cursor:
                raise ValueError(f"overlapping observed cost coverage: {category}")
            cursor = clipped_right
            elapsed = np.asarray(
                [max(0.0, (min(date, right) - clipped_left).total_seconds()) for date in dates],
                dtype=float,
            )
            cumulative += float(row.amount_mxn) * elapsed / (right - left).total_seconds()
        if cursor < end:
            raise ValueError(f"missing observed cost coverage: {category}")
        paths[category] = cumulative
    return paths


def _bootstrap_pair(
    candidate: np.ndarray,
    control: np.ndarray,
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    initial_candidate_return: float = 0.0,
    initial_control_return: float = 0.0,
) -> dict[str, list[float]]:
    """Resample full daily pairs; hold the seal-to-first-close returns fixed.

    Bonferroni one-sided 97.5% lower limits control a 5% family-wise error
    across the two prespecified candidates. These are simulation diagnostics.
    """
    if samples < 100 or samples > BOOTSTRAP_SAMPLES:
        raise ValueError("bootstrap samples must be between 100 and 10000")
    if len(candidate) != len(control) or len(candidate) < 2:
        raise ValueError("paired bootstrap requires at least two matching daily returns")
    for values in (
        candidate,
        control,
        np.asarray([initial_candidate_return, initial_control_return]),
    ):
        if not np.isfinite(values).all() or (values <= -1).any():
            raise ValueError("bootstrap returns must be finite and greater than -1")
    rng = np.random.default_rng(SEED)
    count = len(candidate)
    gaps, advantages = [], []
    for offset in range(0, samples, 250):
        size = min(250, samples - offset)
        starts = rng.integers(0, count, size=(size, math.ceil(count / BLOCK_SESSIONS)))
        indexes = ((starts[:, :, None] + np.arange(BLOCK_SESSIONS)) % count).reshape(size, -1)
        indexes = indexes[:, :count]
        c, b = candidate[indexes], control[indexes]
        cstd, bstd = c.std(axis=1, ddof=1), b.std(axis=1, ddof=1)
        cs = np.divide(c.mean(axis=1), cstd, out=np.zeros(size), where=cstd > 0)
        bs = np.divide(b.mean(axis=1), bstd, out=np.zeros(size), where=bstd > 0)
        gaps.extend((cs - bs) * math.sqrt(252))
        ce = (1 + initial_candidate_return) * np.concatenate(
            (np.ones((size, 1)), np.cumprod(1 + c, axis=1)), axis=1
        )
        be = (1 + initial_control_return) * np.concatenate(
            (np.ones((size, 1)), np.cumprod(1 + b, axis=1)), axis=1
        )
        cp = np.maximum(np.maximum.accumulate(ce, axis=1), 1.0)
        bp = np.maximum(np.maximum.accumulate(be, axis=1), 1.0)
        cd, bd = (1 - ce / cp).max(axis=1), (1 - be / bp).max(axis=1)
        advantages.extend(0.9 * bd - cd)
    return {
        "sharpe_gap_interval": np.quantile(gaps, [0.025, 0.975]).tolist(),
        "drawdown_advantage_interval": np.quantile(advantages, [0.025, 0.975]).tolist(),
    }


def evaluate_economic(
    curves: pd.DataFrame,
    *,
    prospective_started_at: str,
    evidence_kind: str,
    ledger_path: Path,
    baseline_capital_mxn: float | None = None,
    calendar_verified: bool = False,
    frozen_economic_protocol_sha256: str | None = None,
    observed_costs: pd.DataFrame | None = None,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict[str, Any]:
    """Review verified state, sealed capital, calendar and economic protocol.

    Missing seals, 253 new closes, expense coverage or complete prior trials
    yields INCONCLUSIVE. A successful review is SIMULATION_CRITERIA_MET only.
    """
    required = {"timestamp", "portfolio", "cost_multiplier", "equity_mxn"}
    if not required.issubset(curves.columns):
        raise ValueError("curves require timestamp,portfolio,cost_multiplier,equity_mxn")
    frame = curves.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"].map(_utc), utc=True)
    start = _utc(prospective_started_at)
    frame = frame[frame.timestamp > start]
    for column in ("equity_mxn", "cost_multiplier"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"non-finite {column}")
    if (frame.equity_mxn <= 0).any():
        raise ValueError("equity must remain positive")
    if frame.duplicated(["timestamp", "portfolio", "cost_multiplier"]).any():
        raise ValueError("duplicate curve observation")
    daily = frame.assign(session=frame.timestamp.dt.tz_convert("America/New_York").dt.date)
    if daily.duplicated(["session", "portfolio", "cost_multiplier"]).any():
        raise ValueError("daily review admits only one observation per exchange session")
    baseline: float | None = None
    if baseline_capital_mxn is not None:
        if (
            isinstance(baseline_capital_mxn, bool)
            or not math.isfinite(float(baseline_capital_mxn))
            or float(baseline_capital_mxn) <= 0
        ):
            raise ValueError("sealed baseline capital must be finite and positive")
        baseline = float(baseline_capital_mxn)
    trials, variance, history = _trial_history(ledger_path)
    protocol = economic_protocol()
    protocol_sha = economic_protocol_hash()
    result: dict[str, Any] = {
        "status": "INCONCLUSIVE",
        "real_money_approved": False,
        "evidence_kind": evidence_kind,
        "historical_trials": trials,
        "historical_trial_evidence": history,
        "new_prespecified_candidates": len(CANDIDATES),
        "prospective_started_at": start.isoformat(),
        "baseline_capital_mxn": baseline,
        "calendar_verified": calendar_verified is True,
        "economic_protocol": protocol,
        "economic_protocol_sha256": protocol_sha,
        "frozen_economic_protocol_sha256": frozen_economic_protocol_sha256,
        "bootstrap": {**protocol["bootstrap"], "requested_samples": bootstrap_samples},
        "cost_allocation": protocol["cost_allocation"],
        "cost_coverage_start": start.isoformat(),
        "operating_cost_evidence": "DECLARED; caller supplies observed expense records",
        "candidates": {},
    }
    for name in CANDIDATES:
        reasons: list[str] = []
        if evidence_kind != "PROSPECTIVE_SIMULATION":
            reasons.append("independent_prospective_evidence_required")
        if baseline is None:
            reasons.append("sealed_initial_capital_required")
        if frozen_economic_protocol_sha256 != protocol_sha:
            reasons.append("frozen_economic_protocol_match_required")
        if bootstrap_samples != BOOTSTRAP_SAMPLES:
            reasons.append("frozen_bootstrap_sample_count_required")
        series: dict[tuple[str, int], pd.Series] = {}
        for portfolio, multiplier in ((name, 1), (name, 2), (CONTROL, 1)):
            rows = frame[(frame.portfolio == portfolio) & (frame.cost_multiplier == multiplier)]
            series[portfolio, multiplier] = (
                rows.sort_values("timestamp").set_index("timestamp").equity_mxn
            )
        dates = series[name, 1].index
        matching = all(dates.equals(values.index) for values in series.values())
        if not matching:
            reasons.append("identical_session_coverage_required")
        calendar_matches = _calendar_matches(dates, start)
        if calendar_verified is not True or not calendar_matches:
            reasons.append("verified_official_session_calendar_required")
        observations = len(dates)
        return_observations = max(0, observations - 1)
        if return_observations < MINIMUM_FULL_RETURN_OBSERVATIONS:
            reasons.append("at_least_252_complete_close_to_close_returns_required")
        if variance is None:
            reasons.append("complete_historical_trial_moments_required")
        if not history["selection_history_complete"]:
            reasons.append("complete_historical_selection_trials_required")
        costs = None
        cost_issue = None
        if observed_costs is not None and len(dates) > 0:
            try:
                costs = _cost_paths(observed_costs, dates, prospective_started_at=start)
            except ValueError as exc:
                cost_issue = str(exc)
        if costs is None:
            reasons.append("observed_operating_cost_coverage_required")
        review: dict[str, Any] = {
            "status": "INCONCLUSIVE",
            "observations": observations,
            "complete_close_to_close_return_observations": return_observations,
            "initial_partial_interval_counted_as_daily_return": False,
            "missing_evidence": reasons,
            "real_money_approved": False,
        }
        if len(dates):
            review["cost_coverage_end"] = dates[-1].isoformat()
        if cost_issue is not None:
            review["cost_coverage_error"] = cost_issue
        if costs is not None and baseline is not None and matching:
            expense = sum(costs.values(), np.zeros(len(dates)))
            c1 = series[name, 1].to_numpy(dtype=float) - expense
            c2 = series[name, 2].to_numpy(dtype=float) - expense
            benchmark = series[CONTROL, 1].to_numpy(dtype=float) - costs["fx_transfer"]
            review["operating_costs_mxn"] = {k: float(v[-1]) for k, v in costs.items()}
            if min(c1.min(), c2.min(), benchmark.min()) <= 0:
                review["status"] = "REJECTED"
                review["failed_criteria"] = ["expense_exceeds_simulated_equity"]
            else:
                a, stress, control = (
                    _metrics(c1, baseline),
                    _metrics(c2, baseline),
                    _metrics(benchmark, baseline),
                )
                review.update({"net_1x": a, "net_2x": stress, "control": control})
                cr, br = c1[1:] / c1[:-1] - 1, benchmark[1:] / benchmark[:-1] - 1
                if not np.isfinite(cr).all() or not np.isfinite(br).all():
                    raise ValueError("non-finite derived daily returns")
                if variance is not None and len(cr) >= 3:
                    review["dsr"] = deflated_sharpe_ratio(pd.Series(cr), trials + 2, variance)
                if not reasons:
                    intervals = _bootstrap_pair(
                        cr,
                        br,
                        samples=bootstrap_samples,
                        initial_candidate_return=a["initial_partial_return"],
                        initial_control_return=control["initial_partial_return"],
                    )
                    review.update(intervals)
                    checks = {
                        "net_positive_1x": a["net_return"] > 0,
                        "net_positive_2x": stress["net_return"] > 0,
                        "sharpe_gap_010": a["sharpe"] >= control["sharpe"] + 0.10,
                        "drawdown_reduction_10pct": (
                            control["max_drawdown"] > 0
                            and a["max_drawdown"] <= control["max_drawdown"] * 0.90
                        ),
                        "bootstrap_sharpe_gap_positive": intervals["sharpe_gap_interval"][0] > 0,
                        "bootstrap_drawdown_advantage_positive": (
                            intervals["drawdown_advantage_interval"][0] > 0
                        ),
                        "dsr_multiple_trials": review.get("dsr", 0) >= 0.975,
                    }
                    review["criteria"] = checks
                    review["status"] = (
                        "SIMULATION_CRITERIA_MET" if all(checks.values()) else "REJECTED"
                    )
        result["candidates"][name] = review
    statuses = [item["status"] for item in result["candidates"].values()]
    if "SIMULATION_CRITERIA_MET" in statuses:
        result["status"] = "SIMULATION_CRITERIA_MET"
    elif all(status == "REJECTED" for status in statuses):
        result["status"] = "REJECTED"
    return result
