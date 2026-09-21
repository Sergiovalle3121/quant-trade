"""The capital horizon: what a revealed verdict implies for a capital and a target.

"How do I get to a million" has a measurable answer once a holdout has been
read: resample the holdout's daily returns with the stationary bootstrap into
long paths, apply the capital and any monthly contribution, and count the years
until the target is first reached. The answer is a distribution, not a number,
and it inherits every limit of the verdict it is computed from: one window that
the seal itself says flatters long-only strategies, a Sharpe standard error
near 0.75, costs from one order-book cross-section, and capacity priced only up
to $10,000 per leg. The artifact states all five.

Without a revealed verdict there is nothing to resample. The command then says
NOT_MEASURED, and only with two explicit assumptions from the operator (annual
return and volatility) does it produce a projection, labelled ASSUMPTION and
never mixed with a measured row.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from quant_trade.costs.crypto_lowcap import DEFAULT_TIER_PROFILES
from quant_trade.costs.rebalance import max_calibrated_notional, max_fully_executable_notional
from quant_trade.evidence.canonical_json import atomic_write_json, load_json, sha256_of_file
from quant_trade.research.bootstrap import stationary_bootstrap_indices
from quant_trade.research.crypto_lowcap.campaign import (
    RECOVERIES,
    RESULTS_FILENAME,
    SELECTION_DIRNAME,
    STRESS_RECOVERY,
    TRIALS_DIRNAME,
    load_frozen,
)
from quant_trade.research.crypto_lowcap.config import CampaignConfigError, load_trials_config
from quant_trade.research.crypto_lowcap.reveal import HOLDOUT_DIRNAME, STATE_REVEALED, verdict_path

HORIZON_FILENAME = "HORIZON.json"
DAYS_PER_YEAR = 365
CHUNK_SAMPLES = 500
REACH_HORIZONS_YEARS = (5, 10, 20, 30)
NOT_MEASURED = "NOT_MEASURED"

DECLARED_LIMITS = (
    "one holdout window, which the seal declares flatters long-only strategies (2024-2025 "
    "upswing); the resampled future is drawn from that window and no other",
    "the holdout Sharpe carries a standard error of about 0.75; every path here inherits it",
    "costs come from one order-book cross-section (2026-08-05) priced at $1,000 per leg; "
    "capacity beyond $10,000 per leg is NOT_MEASURED",
    "delisting recovery 1.0 and 0.0 bracket an ASSUMPTION; rows are reported at both",
    "no realised money is involved; a path that reaches a target is a resample, not a forecast",
)


class HorizonError(RuntimeError):
    """Raised when the horizon cannot be computed honestly from what exists."""


def horizon_path(experiment_dir: str | Path) -> Path:
    return Path(experiment_dir) / HOLDOUT_DIRNAME / HORIZON_FILENAME


def daily_returns_from_equity(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size < 3:
        raise HorizonError("an equity series needs at least three points")
    if not np.isfinite(arr).all() or (arr <= 0).any():
        raise HorizonError("equity must be finite and positive")
    returns = arr[1:] / arr[:-1] - 1.0
    return returns


@dataclass
class PathStats:
    years_to_target: np.ndarray  # +inf when never reached inside the horizon
    min_wealth_before_target: np.ndarray
    terminal_wealth: np.ndarray


def _month_boundaries(length: int) -> np.ndarray:
    """True on the first simulated day of each new month (12 per 365 days)."""
    month = (np.arange(1, length + 1) * 12) // DAYS_PER_YEAR
    previous = np.concatenate([[0], month[:-1]])
    return month > previous


def _walk(
    daily: np.ndarray,
    *,
    capital: float,
    target: float,
    monthly_contribution: float,
) -> PathStats:
    """Run the wealth recursion over a ``(paths, days)`` return matrix."""
    paths, length = daily.shape
    boundary = _month_boundaries(length)
    wealth = np.full(paths, capital, dtype=float)
    first_day = np.full(paths, -1, dtype=np.int64)
    min_before = np.full(paths, capital, dtype=float)
    for t in range(length):
        wealth = wealth * (1.0 + daily[:, t])
        if boundary[t] and monthly_contribution:
            wealth = wealth + monthly_contribution
        pending = first_day < 0
        min_before = np.where(pending, np.minimum(min_before, wealth), min_before)
        hit = pending & (wealth >= target)
        first_day[hit] = t + 1
    years = np.where(first_day > 0, first_day / DAYS_PER_YEAR, np.inf)
    return PathStats(
        years_to_target=years, min_wealth_before_target=min_before, terminal_wealth=wealth
    )


def _concat(parts: list[PathStats]) -> PathStats:
    return PathStats(
        years_to_target=np.concatenate([p.years_to_target for p in parts]),
        min_wealth_before_target=np.concatenate([p.min_wealth_before_target for p in parts]),
        terminal_wealth=np.concatenate([p.terminal_wealth for p in parts]),
    )


def simulate_paths(
    returns: np.ndarray,
    *,
    years: int,
    samples: int,
    seed: int,
    expected_block_size: float,
    capital: float,
    target: float,
    monthly_contribution: float = 0.0,
) -> PathStats:
    """Stationary-bootstrap ``samples`` paths of ``years`` from observed returns."""
    if years < 1 or samples < 1:
        raise HorizonError("years and samples must be positive")
    n = int(returns.size)
    length = years * DAYS_PER_YEAR
    rng = np.random.default_rng(seed)
    parts: list[PathStats] = []
    remaining = samples
    while remaining > 0:
        k = min(CHUNK_SAMPLES, remaining)
        idx = stationary_bootstrap_indices(
            n, length=length, samples=k, expected_block_size=expected_block_size, rng=rng
        )
        parts.append(
            _walk(
                returns[idx],
                capital=capital,
                target=target,
                monthly_contribution=monthly_contribution,
            )
        )
        remaining -= k
    return _concat(parts)


def assumed_paths(
    *,
    annual_return: float,
    annual_volatility: float,
    years: int,
    samples: int,
    seed: int,
    capital: float,
    target: float,
    monthly_contribution: float = 0.0,
) -> PathStats:
    """Lognormal daily returns from two declared assumptions. ASSUMPTION class."""
    if annual_return <= -1.0 or annual_volatility < 0:
        raise HorizonError("assumed annual return must exceed -100% and volatility be >= 0")
    length = years * DAYS_PER_YEAR
    mu = (math.log1p(annual_return) - annual_volatility**2 / 2.0) / DAYS_PER_YEAR
    sigma = annual_volatility / math.sqrt(DAYS_PER_YEAR)
    rng = np.random.default_rng(seed)
    parts: list[PathStats] = []
    remaining = samples
    while remaining > 0:
        k = min(CHUNK_SAMPLES, remaining)
        daily = np.expm1(rng.normal(mu, sigma, size=(k, length)))
        parts.append(
            _walk(daily, capital=capital, target=target, monthly_contribution=monthly_contribution)
        )
        remaining -= k
    return _concat(parts)


def summarise(stats: PathStats, *, capital: float, years: int) -> dict[str, Any]:
    ytt = stats.years_to_target

    def _pct(q: float) -> float | None:
        # "lower" picks an observed element, so an infinite tail never enters
        # an interpolation and the percentile is a real path's year count.
        value = float(np.percentile(ytt, q, method="lower"))
        return None if not math.isfinite(value) else value

    return {
        "paths": int(ytt.size),
        "p_reached_within_horizon": float(np.mean(np.isfinite(ytt))),
        "years_to_target": {"p5": _pct(5), "p50": _pct(50), "p95": _pct(95)},
        "years_to_target_note": (
            "null means the target is not reached within the horizon at that percentile"
        ),
        "p_reach_by_years": {
            str(h): float(np.mean(ytt <= h)) for h in REACH_HORIZONS_YEARS if h <= years
        },
        "p_50pct_drawdown_before_target": float(
            np.mean(stats.min_wealth_before_target < 0.5 * capital)
        ),
        "median_terminal_wealth_usd": float(np.median(stats.terminal_wealth)),
    }


def constant_return_years(
    cagr: float, *, capital: float, target: float, monthly_contribution: float, years: int
) -> float | None:
    """Deterministic reference: months at a constant CAGR until the target."""
    if capital >= target:
        return 0.0
    monthly = (1.0 + cagr) ** (1.0 / 12.0) - 1.0 if cagr > -1.0 else -1.0
    wealth = capital
    for month in range(1, years * 12 + 1):
        wealth = wealth * (1.0 + monthly) + monthly_contribution
        if wealth >= target:
            return month / 12.0
    return None


def capacity(
    frozen_primary: dict[str, Any],
    *,
    capital: float,
    quantile: str,
    min_executable_fraction: float,
    campaign_legs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Whether ``capital`` even fits the measured cost model, per leg."""
    params = frozen_primary.get("strategy_params", {})
    top_n = params.get("top_n")
    by_tier = {
        profile.tier: {
            "max_calibrated_notional_usd": max_calibrated_notional(profile, quantile),
            "max_fully_executable_notional_usd": max_fully_executable_notional(
                profile, min_executable_fraction
            ),
        }
        for profile in DEFAULT_TIER_PROFILES
    }
    if not top_n:
        return {
            "status": NOT_MEASURED,
            "reason": "the frozen candidate declares no top_n, so a per-leg notional is undefined",
            "by_tier": by_tier,
            "campaign_legs_at_1k": campaign_legs,
        }
    leg = capital / float(top_n)
    tiers = [str(params["tier"])] if params.get("tier") in by_tier else list(by_tier)
    calibrated = min(by_tier[t]["max_calibrated_notional_usd"] for t in tiers)
    executable = min(by_tier[t]["max_fully_executable_notional_usd"] for t in tiers)
    if leg > calibrated:
        status = NOT_MEASURED
    elif leg > executable:
        status = "CAPPED"
    else:
        status = "WITHIN_CALIBRATION"
    return {
        "status": status,
        "top_n": int(top_n),
        "leg_notional_usd": leg,
        "tiers_considered": tiers,
        "max_calibrated_notional_usd": calibrated,
        "max_fully_executable_notional_usd": executable,
        "by_tier": by_tier,
        "campaign_legs_at_1k": campaign_legs,
        "note": (
            "the campaign priced $1,000 portfolios; a larger capital divides into larger legs, "
            "and the cost model refuses what the sampled books could not fill"
        ),
    }


def _row(
    name: str,
    recovery: str | None,
    evidence_class: str,
    returns: np.ndarray | None,
    stats: PathStats,
    *,
    cagr: float | None,
    capital: float,
    target: float,
    monthly_contribution: float,
    years: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "recovery": recovery,
        "evidence_class": evidence_class,
        "n_days": None if returns is None else int(returns.size),
        "cagr_holdout": cagr,
        "constant_return_years_to_target": (
            None
            if cagr is None
            else constant_return_years(
                cagr,
                capital=capital,
                target=target,
                monthly_contribution=monthly_contribution,
                years=years,
            )
        ),
        **summarise(stats, capital=capital, years=years),
    }


def run_horizon(
    experiment_dir: str | Path,
    *,
    capital: float,
    target: float,
    monthly_contribution: float = 0.0,
    years: int = 30,
    samples: int = 2000,
    seed: int = 20260921,
    expected_block_size: float = 20.0,
    assume_annual_return: float | None = None,
    assume_annual_volatility: float | None = None,
    at_utc: str,
    code_sha: str,
) -> dict[str, Any]:
    if capital <= 0 or target <= 0:
        raise HorizonError("capital and target must be positive")
    if monthly_contribution < 0:
        raise HorizonError("monthly_contribution must be >= 0")
    if (assume_annual_return is None) != (assume_annual_volatility is None):
        raise HorizonError("assumed return and volatility must be given together, or neither")
    exp = Path(experiment_dir)
    vpath = verdict_path(exp)
    verdict = load_json(vpath) if vpath.is_file() else None
    inputs = {
        "capital_usd": capital,
        "target_usd": target,
        "monthly_contribution_usd": monthly_contribution,
        "years": years,
        "samples": samples,
        "seed": seed,
        "expected_block_size": expected_block_size,
        "verdict_path": str(vpath),
        "verdict_sha256": sha256_of_file(vpath) if vpath.is_file() else None,
        "holdout_window": None if verdict is None else verdict.get("holdout_window"),
    }
    payload: dict[str, Any] = {
        "artifact": "HORIZON",
        "schema_version": 1,
        "generated_at_utc": at_utc,
        "code_sha": code_sha,
        "inputs": inputs,
        "rows": [],
        "capacity": None,
        "declared_limits": list(DECLARED_LIMITS),
        "assumed": None,
    }
    revealed = verdict is not None and verdict.get("state") == STATE_REVEALED
    if revealed:
        if assume_annual_return is not None:
            raise HorizonError(
                "the holdout is revealed; a measured horizon is available and assumptions are "
                "refused so the two are never mixed"
            )
        assert verdict is not None
        payload["state"] = "MEASURED"
        primary = verdict["candidates"][0]
        for rec in RECOVERIES:
            block = primary["by_recovery"][rec]
            returns = daily_returns_from_equity(block["equity"]["values"])
            stats = simulate_paths(
                returns,
                years=years,
                samples=samples,
                seed=seed,
                expected_block_size=expected_block_size,
                capital=capital,
                target=target,
                monthly_contribution=monthly_contribution,
            )
            payload["rows"].append(
                _row(
                    f"primary:{primary['trial_id']}",
                    rec,
                    "MEASURED",
                    returns,
                    stats,
                    cagr=float(block["test_metrics"]["cagr"]),
                    capital=capital,
                    target=target,
                    monthly_contribution=monthly_contribution,
                    years=years,
                )
            )
        bench_equity = verdict.get("benchmark_equity")
        for name, by_rec in sorted((bench_equity or {}).items()):
            for rec in RECOVERIES:
                block = by_rec.get(rec)
                if not block:
                    payload["rows"].append(
                        {
                            "name": f"benchmark:{name}",
                            "recovery": rec,
                            "evidence_class": NOT_MEASURED,
                        }
                    )
                    continue
                returns = daily_returns_from_equity(block["values"])
                stats = simulate_paths(
                    returns,
                    years=years,
                    samples=samples,
                    seed=seed,
                    expected_block_size=expected_block_size,
                    capital=capital,
                    target=target,
                    monthly_contribution=monthly_contribution,
                )
                metrics = (verdict.get("benchmarks", {}).get(name, {}) or {}).get(rec) or {}
                payload["rows"].append(
                    _row(
                        f"benchmark:{name}",
                        rec,
                        "MEASURED",
                        returns,
                        stats,
                        cagr=None if metrics.get("cagr") is None else float(metrics["cagr"]),
                        capital=capital,
                        target=target,
                        monthly_contribution=monthly_contribution,
                        years=years,
                    )
                )
        if bench_equity is None:
            payload["rows"].append(
                {
                    "name": "benchmark:*",
                    "recovery": None,
                    "evidence_class": NOT_MEASURED,
                    "reason": (
                        "verdict schema 1 carries no benchmark equity and the holdout is read once"
                    ),
                }
            )
        payload["capacity"] = _capacity_from_experiment(exp, primary, capital=capital)
    else:
        reason = (
            "no holdout verdict exists"
            if verdict is None
            else (
                f"the holdout verdict is {verdict.get('state')}; there is no measured "
                "series to resample"
            )
        )
        payload["state"] = NOT_MEASURED
        payload["reason"] = reason
        if assume_annual_return is not None and assume_annual_volatility is not None:
            stats = assumed_paths(
                annual_return=assume_annual_return,
                annual_volatility=assume_annual_volatility,
                years=years,
                samples=samples,
                seed=seed,
                capital=capital,
                target=target,
                monthly_contribution=monthly_contribution,
            )
            payload["state"] = "ASSUMPTION"
            payload["assumed"] = {
                "annual_return": assume_annual_return,
                "annual_volatility": assume_annual_volatility,
                "model": "lognormal daily returns, no dependence, no costs, no capacity",
                "rows": [
                    _row(
                        "assumed",
                        None,
                        "ASSUMPTION",
                        None,
                        stats,
                        cagr=assume_annual_return,
                        capital=capital,
                        target=target,
                        monthly_contribution=monthly_contribution,
                        years=years,
                    )
                ],
            }
    atomic_write_json(horizon_path(exp), payload)
    return payload


def _capacity_from_experiment(
    exp: Path, primary: dict[str, Any], *, capital: float
) -> dict[str, Any]:
    frozen = load_frozen(exp) or {}
    frozen_primary = frozen.get("primary") or {
        "strategy_params": primary.get("strategy_params", {})
    }
    quantile, fraction = "p75", 1.0
    results_path = exp / SELECTION_DIRNAME / RESULTS_FILENAME
    if results_path.is_file():
        try:
            common = load_trials_config(load_json(results_path)["trials_config"]["path"]).common
            quantile, fraction = common.quantile, common.min_executable_fraction
        except (CampaignConfigError, KeyError, OSError):
            pass
    legs: dict[str, Any] | None = None
    trial_file = (
        exp / SELECTION_DIRNAME / TRIALS_DIRNAME / f"{primary['trial_id'].replace(':', '__')}.json"
    )
    if trial_file.is_file():
        metrics = load_json(trial_file)["by_recovery"][STRESS_RECOVERY]["test_metrics"]
        legs = {
            k: metrics.get(k)
            for k in ("executed_legs", "refused_legs", "capped_legs", "unpriceable_legs")
        }
    return capacity(
        frozen_primary,
        capital=capital,
        quantile=quantile,
        min_executable_fraction=fraction,
        campaign_legs=legs,
    )


__all__ = [
    "DECLARED_LIMITS",
    "HORIZON_FILENAME",
    "HorizonError",
    "PathStats",
    "assumed_paths",
    "capacity",
    "constant_return_years",
    "daily_returns_from_equity",
    "horizon_path",
    "run_horizon",
    "simulate_paths",
    "summarise",
]
