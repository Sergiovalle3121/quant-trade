"""Run every estimator the repository already trusts over a client's upload.

``run_audit`` is pure: it takes parsed inputs, a seed and a clock, and
returns an ``AuditResult``. It never reads or writes files, never touches
the network, and produces the same JSON for the same inputs and seed. The
CLI and the web layer are thin wrappers that own I/O.

Nothing here is new statistics. PSR, DSR, the minimum track record and the
expected maximum Sharpe come from ``metrics/statistics.py``; the annualised
performance table from ``metrics/performance.py``; the stationary bootstrap
from ``research/bootstrap.py``; sub-period and rolling views from
``research/robustness.py``; the date split from ``research/splits.py``; the
benchmark comparison from ``research/benchmarks.py``; CSCV from
``research/overfitting.py``; the holdout seal from
``research/holdout_seal.py``. What is new is the composition, the evidence
tags, and the refusal to compute anything the upload cannot support.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit import account as account_lib
from quant_trade.audit import analytics, charts, redflags, verdict
from quant_trade.audit import costs as cost_lib
from quant_trade.audit import live as live_lib
from quant_trade.audit import stress as stress_lib
from quant_trade.audit import testdata as testdata_lib
from quant_trade.audit import timing as timing_lib
from quant_trade.audit.guard import find_claims, scan_client_text
from quant_trade.audit.prop_presets import DEFAULT_PRESET, get_preset
from quant_trade.audit.schema import (
    DECLARED,
    MEASURED,
    NOT_MEASURED,
    SCHEMA_VERSION,
    AuditInputs,
    AuditResult,
    IngestedSeries,
    declared,
    measured,
    not_measured,
    parse_equity_csv,
)
from quant_trade.audit.verdict import DEFAULT_THRESHOLDS, Thresholds
from quant_trade.metrics.performance import calculate_performance
from quant_trade.metrics.statistics import (
    expected_max_sharpe,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    psr_from_moments,
    return_moments,
    sharpe_per_period,
    sharpe_variance_across_trials,
)
from quant_trade.research.benchmarks import compare_to_benchmark
from quant_trade.research.bootstrap import bootstrap_confidence_intervals
from quant_trade.research.holdout_seal import HoldoutSeal, HoldoutSealError, dataset_digest
from quant_trade.research.overfitting import cscv_probability_of_backtest_overfitting
from quant_trade.research.robustness import rolling_metrics, subperiod_analysis
from quant_trade.research.splits import date_based_split

ENGINE_NAME = "quant_trade.audit"
DSR_SENSITIVITY_TRIALS = (1, 5, 20, 100)
TRIALS_TO_HALF_CAP = 1_000_000
CSCV_PARTITIONS = 8
BENCHMARK_MIN_OVERLAP = 0.90
HOLDOUT_MIN_OBSERVATIONS = 30
BOOTSTRAP_PERCENTILES = (5.0, 50.0, 95.0)
#: Upper bound on bootstrap cells (samples x returns). A 200,000-row intraday
#: curve at 1,000 samples is 200 million cells (about 38 s and 1.5 GB); above
#: the budget the samples are reduced to fit and both counts are recorded.
BOOTSTRAP_MAX_CELLS = 10_000_000
BOOTSTRAP_MIN_SAMPLES = 50
VARIANCE_POLICY = "max(observed across uploaded variants, sampling-variance floor)"
RISK_SAMPLES = 2000
CHALLENGE_SAMPLES = 5000
#: The challenge simulator walks daily closes; coarser data cannot feed it.
CHALLENGE_MIN_PERIODS_PER_YEAR = 200.0
SERIES_MAX_POINTS = 400
WITHHELD_TEXT = "[withheld: promotional wording]"


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("quant-trade")
    except Exception:  # pragma: no cover - metadata absent in odd installs
        return "0.0.0"


def _iso(value: Any) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def sharpe_sampling_variance(sharpe: float, skew: float, kurtosis: float, n: int) -> float:
    """Variance of the per-period Sharpe estimator (Bailey & López de Prado).

    Used as the floor for the cross-trial variance when the client uploads
    no variants: unskilled trials disagree at least by sampling error.
    """
    if n < 2:
        return 0.0
    term = 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe**2
    return max(term, 0.0) / (n - 1)


def _annualised_sharpe(returns: pd.Series, ppy: float) -> float:
    return redflags.annualised_sharpe(returns, ppy)


#: Shortest history whose compound annual return is reported.
MIN_CAGR_DAYS = 365


def _performance(frame: pd.DataFrame, trades: list[Any]) -> dict[str, Any]:
    metrics = calculate_performance(frame[["timestamp", "equity"]], trades)
    keys = (
        "total_return",
        "cagr",
        "volatility",
        "sharpe",
        "sortino",
        "max_drawdown",
        "win_rate",
        "trade_count",
    )
    out = {key: measured(metrics[key]) for key in keys}
    span_days = (frame["timestamp"].iloc[-1] - frame["timestamp"].iloc[0]).days
    if span_days < MIN_CAGR_DAYS:
        # Compounding five good weeks into a year prints a four-digit
        # "annual" return nobody earned; the total return says it plainly.
        out["cagr"] = not_measured("under a year of history; annualising it would exaggerate")
    if not trades:
        out["win_rate"] = not_measured("no trades uploaded")
        out["trade_count"] = not_measured("no trades uploaded")
    return out


def _significance(returns: pd.Series) -> tuple[dict[str, Any], dict[str, float] | None]:
    moments = return_moments(returns)
    n = int(moments["observations"])
    std = float(returns.std(ddof=1)) if n >= 2 else 0.0
    if n < 3 or std <= 0:
        reason = "fewer than three returns" if n < 3 else "zero variance"
        section = {
            "status": "NOT_MEASURED",
            "reason": reason,
            "observations": measured(n),
            "sharpe_per_period": not_measured(reason),
            "skewness": not_measured(reason),
            "kurtosis": not_measured(reason),
            "psr": not_measured(reason),
            "min_track_record_length": not_measured(reason),
            "observations_short_by": not_measured(reason),
        }
        return section, None
    psr = probabilistic_sharpe_ratio(returns)
    mintrl = minimum_track_record_length(returns)
    short_by = max(0.0, mintrl - n) if math.isfinite(mintrl) else None
    section = {
        "status": "MEASURED",
        "observations": measured(n),
        "sharpe_per_period": measured(moments["sharpe_per_period"]),
        "skewness": measured(moments["skewness"]),
        "kurtosis": measured(moments["kurtosis"]),
        "psr": measured(psr, "P[true Sharpe > 0] given length, skew and kurtosis"),
        "min_track_record_length": (
            measured(mintrl, "observations needed for PSR to reach 0.95")
            if math.isfinite(mintrl)
            else not_measured("observed Sharpe <= 0; no track record length reaches 0.95")
        ),
        "observations_short_by": (
            measured(short_by) if short_by is not None else not_measured("unreachable")
        ),
    }
    return section, {**moments, "psr": psr}


#: The trial count when the client declares none and no file shows one.
UNDECLARED_TRIALS = "not declared; computed with 1, the most favourable case"


def trial_count(inputs: AuditInputs) -> tuple[int, str, str]:
    """The trial count the deflated Sharpe uses, its evidence and its source.

    The larger of what the client declares and what the files prove: the
    columns of an uploaded variants matrix, the passes of an MT5
    optimisation export, or the variants a report holds. A declaration of 1
    next to 100 uploaded variants cannot deflate by 1.
    """
    best = (
        (inputs.declared.trials, DECLARED, "declared by the client")
        if inputs.declared.trials_declared
        else (1, NOT_MEASURED, UNDECLARED_TRIALS)
    )
    measured_counts = [
        (inputs.optimization_passes, "passes in the MT5 optimisation export"),
        (
            int(inputs.variants.shape[1]) if inputs.variants is not None else None,
            "columns of the uploaded variants matrix",
        ),
        (inputs.report_variants, "parameter variants in the uploaded report"),
    ]
    for count, source in measured_counts:
        if count is not None and count >= best[0]:
            best = (int(count), MEASURED, source)
    return best


def _multiplicity(
    moments: dict[str, float] | None,
    *,
    declared_trials: int,
    variants: np.ndarray | None,
    trials_used: int | None = None,
    trials_evidence: str = DECLARED,
    trials_source: str = "declared by the client",
) -> dict[str, Any]:
    trials = trials_used if trials_used is not None else declared_trials
    trials_record = {"value": trials, "evidence": trials_evidence, "note": trials_source}
    if moments is None:
        reason = "statistical significance not measured"
        return {
            "status": "NOT_MEASURED",
            "reason": reason,
            "trials_used": trials_record,
            "sharpe_variance_used": not_measured(reason),
            "variance_policy": VARIANCE_POLICY,
            "floor": not_measured(reason),
            "observed_across_variants": not_measured(reason),
            "dsr_at_declared": not_measured(reason),
            "dsr_at_trials_used": not_measured(reason),
            "sensitivity": [],
            "trials_to_half": not_measured(reason),
        }
    sr = float(moments["sharpe_per_period"])
    n = int(moments["observations"])
    skew = float(moments["skewness"])
    kurt = float(moments["kurtosis"])
    floor = sharpe_sampling_variance(sr, skew, kurt, n)
    if variants is not None:
        per_column = [
            sharpe_per_period(pd.Series(variants[:, j])) for j in range(variants.shape[1])
        ]
        observed = sharpe_variance_across_trials(per_column)
        observed_evidence = measured(observed, f"variance across {variants.shape[1]} variants")
    else:
        observed = 0.0
        observed_evidence = not_measured("no variants uploaded")
    used = max(observed, floor)

    def dsr(trials: int) -> float:
        return psr_from_moments(
            sr, n, skew, kurt, benchmark_sharpe=expected_max_sharpe(trials, used)
        )

    grid = sorted({*DSR_SENSITIVITY_TRIALS, declared_trials, trials})
    sensitivity = [
        {
            "n_trials": trials,
            "expected_max_sharpe_per_period": measured(expected_max_sharpe(trials, used)),
            "dsr": measured(dsr(trials)),
        }
        for trials in grid
    ]
    trials_to_half: int | None = None
    candidate = 1
    while candidate <= TRIALS_TO_HALF_CAP:
        if dsr(candidate) < 0.5:
            trials_to_half = candidate
            break
        candidate *= 2
    return {
        "status": "MEASURED",
        "trials_used": trials_record,
        "sharpe_variance_used": measured(used),
        "variance_policy": VARIANCE_POLICY,
        "floor": measured(floor, "sampling variance of the Sharpe estimator"),
        "observed_across_variants": observed_evidence,
        "dsr_at_declared": measured(
            dsr(declared_trials), f"PSR against E[max Sharpe] of {declared_trials} trial(s)"
        ),
        "dsr_at_trials_used": measured(
            dsr(trials), f"PSR against E[max Sharpe] of {trials} trial(s), {trials_source}"
        ),
        "sensitivity": sensitivity,
        "trials_to_half": (
            measured(trials_to_half, "smallest power-of-two trial count with DSR < 0.5")
            if trials_to_half is not None
            else not_measured(f"DSR stays >= 0.5 up to {TRIALS_TO_HALF_CAP:,} trials")
        ),
    }


def bootstrap_samples_used(requested: int, observations: int) -> int:
    """The samples the bootstrap draws: ``requested`` unless that would pass
    ``BOOTSTRAP_MAX_CELLS``, never fewer than ``BOOTSTRAP_MIN_SAMPLES``."""
    budget = BOOTSTRAP_MAX_CELLS // max(observations, 1)
    return int(min(requested, max(BOOTSTRAP_MIN_SAMPLES, budget)))


def _bootstrap(returns: pd.Series, *, samples: int, seed: int) -> dict[str, Any]:
    n = int(len(returns))
    requested = samples
    samples = bootstrap_samples_used(requested, n)
    if n < 10:
        reason = "fewer than ten returns"
        return {
            "status": "NOT_MEASURED",
            "reason": reason,
            "method": "stationary",
            "samples": samples,
            "block_size": None,
            "sharpe_per_period": not_measured(reason),
            "total_return": not_measured(reason),
        }
    block = float(max(2, min(20, n // 10)))
    table = bootstrap_confidence_intervals(
        returns,
        method="stationary",
        samples=samples,
        seed=seed,
        block_size=block,
        percentiles=BOOTSTRAP_PERCENTILES,
        nan_policy="drop",
    )

    def band(stat: str) -> dict[str, Any]:
        return {
            "point_estimate": measured(table.loc[stat, "point_estimate"]),
            "p5": measured(table.loc[stat, "p5"]),
            "p50": measured(table.loc[stat, "p50"]),
            "p95": measured(table.loc[stat, "p95"]),
        }

    return {
        "status": "MEASURED",
        "method": "stationary",
        "samples": samples,
        "samples_requested": requested,
        "block_size": block,
        "sharpe_per_period": band("sharpe"),
        "total_return": band("total_return"),
    }


def _subperiods(frame: pd.DataFrame) -> list[dict[str, Any]]:
    table = subperiod_analysis(frame[["timestamp", "equity"]])
    return [
        {
            "year": int(row["year"]),
            "return": measured(row["return"]),
            "max_drawdown": measured(row["max_drawdown"]),
        }
        for _, row in table.iterrows()
    ]


def _rolling(frame: pd.DataFrame, ppy: float) -> list[dict[str, Any]]:
    n = len(frame)
    candidates = sorted({max(2, round(ppy / 4)), max(2, round(ppy / 2)), max(2, round(ppy))})
    windows = tuple(w for w in candidates if w <= n // 2)
    if not windows:
        return []
    table = rolling_metrics(frame[["timestamp", "equity"]], windows, periods_per_year=ppy)
    out: list[dict[str, Any]] = []
    for w in windows:
        ret = table[f"rolling_{w}_return"].dropna()
        dd = table[f"rolling_{w}_drawdown"].dropna()
        out.append(
            {
                "window": w,
                "min_return": measured(ret.min()) if len(ret) else not_measured("too short"),
                "min_drawdown": measured(dd.min()) if len(dd) else not_measured("too short"),
                "share_negative": (
                    measured(float((ret < 0).mean())) if len(ret) else not_measured("too short")
                ),
            }
        )
    return out


def _side_stats(frame: pd.DataFrame, ppy: float) -> dict[str, Any]:
    returns = frame["equity"].astype(float).pct_change().dropna()
    return {
        "observations": measured(int(len(returns))),
        "sharpe_annualised": measured(_annualised_sharpe(returns, ppy)),
        "psr": measured(probabilistic_sharpe_ratio(returns)),
        "total_return": measured(float(frame["equity"].iloc[-1] / frame["equity"].iloc[0] - 1)),
    }


def _holdout(
    frame: pd.DataFrame, oos_start: datetime | None, ppy: float
) -> tuple[dict[str, Any], float | None, float | None, str | None]:
    if oos_start is None:
        reason = "no out-of-sample start declared"
        return {"status": "NOT_MEASURED", "reason": reason, "oos_start": None}, None, None, reason
    start = pd.Timestamp(oos_start)
    first, last = frame["timestamp"].iloc[0], frame["timestamp"].iloc[-1]
    base = {"oos_start": declared(_iso(start), "declared by the client; not verifiable")}
    if start <= first or start > last:
        reason = "declared out-of-sample start lies outside the uploaded series"
        return {"status": "NOT_MEASURED", "reason": reason, **base}, None, None, reason
    try:
        train, test = date_based_split(
            frame[["timestamp", "equity"]], first, start - pd.Timedelta(nanoseconds=1), start, last
        )
    except ValueError as exc:
        reason = f"split failed: {exc}"
        return {"status": "NOT_MEASURED", "reason": reason, **base}, None, None, reason
    if len(train) < HOLDOUT_MIN_OBSERVATIONS + 1 or len(test) < HOLDOUT_MIN_OBSERVATIONS + 1:
        reason = (
            f"a side has fewer than {HOLDOUT_MIN_OBSERVATIONS} returns "
            f"(in-sample {max(len(train) - 1, 0)}, out-of-sample {max(len(test) - 1, 0)})"
        )
        return {"status": "NOT_MEASURED", "reason": reason, **base}, None, None, reason
    in_sample = _side_stats(train, ppy)
    out_of_sample = _side_stats(test, ppy)
    is_sharpe = float(in_sample["sharpe_annualised"]["value"])
    oos_sharpe = float(out_of_sample["sharpe_annualised"]["value"])
    gap = is_sharpe - oos_sharpe
    section = {
        "status": "MEASURED",
        **base,
        "in_sample": in_sample,
        "out_of_sample": out_of_sample,
        "gap": measured(gap, "in-sample minus out-of-sample annualised Sharpe"),
    }
    return section, oos_sharpe, gap, None


def _benchmark(
    strategy: IngestedSeries, benchmark: IngestedSeries | None
) -> tuple[dict[str, Any], dict[str, float | None], str | None]:
    empty: dict[str, float | None] = {
        "excess_return": None,
        "drawdown_ratio": None,
        "information_ratio": None,
    }
    if benchmark is None:
        reason = "no benchmark uploaded"
        return {"status": "NOT_MEASURED", "reason": reason}, empty, reason
    s = strategy.frame[["timestamp", "equity"]]
    b = benchmark.frame[["timestamp", "equity"]]
    joined = s.merge(b, on="timestamp", suffixes=("_s", "_b"))
    overlap = len(joined) / max(len(s), 1)
    if overlap < BENCHMARK_MIN_OVERLAP or len(joined) < 3:
        reason = f"benchmark overlaps only {overlap:.0%} of the strategy timestamps"
        return (
            {
                "status": "NOT_MEASURED",
                "reason": reason,
                "overlap_share": measured(overlap),
            },
            empty,
            reason,
        )
    s_eq = joined[["timestamp", "equity_s"]].rename(columns={"equity_s": "equity"})
    b_eq = joined[["timestamp", "equity_b"]].rename(columns={"equity_b": "equity"})
    s_metrics = calculate_performance(s_eq, [])
    b_metrics = calculate_performance(b_eq, [])
    comparison = compare_to_benchmark(s_metrics, b_metrics, s_eq, b_eq)
    b_mdd = float(b_metrics["max_drawdown"])
    s_mdd = float(s_metrics["max_drawdown"])
    drawdown_ratio = (s_mdd / b_mdd) if b_mdd < 0 else None
    values: dict[str, float | None] = {
        "excess_return": float(comparison["excess_return"]),
        "drawdown_ratio": drawdown_ratio,
        "information_ratio": float(comparison["information_ratio"]),
    }
    section = {
        "status": "MEASURED",
        "overlap_share": measured(overlap),
        "strategy_total_return": measured(comparison["strategy_total_return"]),
        "benchmark_total_return": measured(comparison["benchmark_total_return"]),
        "excess_return": measured(comparison["excess_return"]),
        "strategy_sharpe": measured(comparison["strategy_sharpe"]),
        "benchmark_sharpe": measured(comparison["benchmark_sharpe"]),
        "tracking_error": measured(comparison["tracking_error"]),
        "information_ratio": measured(comparison["information_ratio"]),
        "strategy_max_drawdown": measured(s_mdd),
        "benchmark_max_drawdown": measured(b_mdd),
        "drawdown_ratio": (
            measured(drawdown_ratio, "strategy max drawdown over benchmark max drawdown")
            if drawdown_ratio is not None
            else not_measured("benchmark has no drawdown")
        ),
    }
    return section, values, None


def _cscv(variants: np.ndarray | None) -> tuple[dict[str, Any], float | None]:
    if variants is None:
        return {"status": "NOT_MEASURED", "reason": "no variants uploaded"}, None
    usable = (len(variants) // CSCV_PARTITIONS) * CSCV_PARTITIONS
    trimmed = variants[len(variants) - usable :]
    try:
        evidence = cscv_probability_of_backtest_overfitting(trimmed, partitions=CSCV_PARTITIONS)
    except ValueError as exc:
        return {"status": "NOT_MEASURED", "reason": str(exc)}, None
    return {
        "status": "MEASURED",
        "pbo": measured(
            evidence.pbo, "fraction of CSCV splits where the IS winner is below the OOS median"
        ),
        "partitions": evidence.partitions,
        "combinations": evidence.combinations,
        "parameter_variants": evidence.parameter_variants,
        "observations_used": evidence.observations,
        "observations_dropped": int(len(variants) - usable),
    }, float(evidence.pbo)


def _costs(
    inputs: AuditInputs,
) -> tuple[dict[str, Any], list[cost_lib.RecostRow] | None, float | None, bool, list[float] | None]:
    if inputs.trades is None:
        return {"status": "NOT_MEASURED", "reason": "no trades uploaded"}, None, None, False, None
    fees_reported = inputs.trades.reports_fees
    charged = inputs.trades.fees if fees_reported else None
    ref, assumed = cost_lib.reference_bps(
        inputs.declared.cost_bps_per_side, fees_reported=fees_reported
    )
    rows = cost_lib.recost_trades(
        inputs.trades.trades, inputs.trades.sides, ref, reported_costs=charged
    )
    be = cost_lib.break_even_bps(inputs.trades.trades, inputs.trades.sides, reported_costs=charged)
    gross = cost_lib.gross_pnls(inputs.trades.trades, inputs.trades.sides)
    section = {
        "status": "MEASURED",
        "reference_bps": declared(ref, cost_lib.reference_note(assumed, fees_reported)),
        "reported_costs_in_rows": fees_reported,
        "rows": [
            {
                "multiplier": row.multiplier,
                "cost_bps_per_side": row.cost_bps_per_side,
                "gross_pnl": measured(row.gross_pnl),
                "total_cost": measured(row.total_cost),
                "net_pnl": measured(row.net_pnl),
                "win_rate": measured(row.win_rate),
                "mean_net_pnl_per_trade": measured(row.mean_net_pnl_per_trade),
                "trades": row.trades,
            }
            for row in rows
        ],
        "break_even_bps": (
            measured(
                be,
                "extra cost per side, on top of the report's fees, at which the ledger nets to zero"
                if fees_reported
                else "cost per side at which the ledger nets to zero",
            )
            if be is not None
            else not_measured("no traded notional")
        ),
        "break_even_multiple": (
            measured(be / ref) if be is not None and ref > 0 else not_measured("undefined")
        ),
    }
    if inputs.reported_fees:
        section["reported_fees"] = {
            name: measured(value, "signed total the report itemises; negative is a cost")
            for name, value in sorted(inputs.reported_fees.items())
        }
    return section, rows, ref, assumed, gross


def _safe_text(text: str) -> str:
    """Client-controlled text (report metadata, names echoed in warnings) is
    kept out of the audit's own voice: wording the guard refuses is withheld."""
    return WITHHELD_TEXT if find_claims(text) else text


def _trade_stats(inputs: AuditInputs) -> dict[str, Any]:
    if inputs.trades is None:
        return {"status": "NOT_MEASURED", "reason": "no trades uploaded"}
    # A net credit (swap paid to the account) counts too, so the net result
    # matches the platform's; the stress tests keep only costs (stricter).
    fees = -sum(value for value in inputs.reported_fees.values())
    stats = analytics.trade_statistics(inputs.trades.trades, inputs.trades.sides, fees_total=fees)
    return {"status": "MEASURED", **stats}


def _stress(inputs: AuditInputs, frame: pd.DataFrame) -> dict[str, Any]:
    if inputs.trades is None:
        trades: dict[str, Any] = {"status": "NOT_MEASURED", "reason": "no trades uploaded"}
    else:
        fees = -sum(value for value in inputs.reported_fees.values())
        trades = stress_lib.trades_stress(inputs.trades.trades, fees_total=max(fees, 0.0))
    return {"returns": stress_lib.returns_stress(frame), "trades": trades}


def _risk(returns: pd.Series, ppy: float, *, samples: int, seed: int) -> dict[str, Any]:
    risk = analytics.drawdown_risk(returns, periods_per_year=ppy, samples=samples, seed=seed)
    status = "MEASURED" if risk.get("method") else "NOT_MEASURED"
    out: dict[str, Any] = {"status": status, "horizon_years": 1.0, **risk}
    if status == "NOT_MEASURED":
        out["reason"] = risk["max_drawdown"]["p50"]["note"]
    return out


def _challenge(inputs: AuditInputs, *, samples: int, seed: int) -> dict[str, Any]:
    key = inputs.declared.challenge or DEFAULT_PRESET
    rules = get_preset(key)
    selected_by = "client" if inputs.declared.challenge else "default"
    if inputs.periods_per_year < CHALLENGE_MIN_PERIODS_PER_YEAR:
        reason = "the simulator needs daily or finer data; the upload is coarser"
        return {
            "status": "NOT_MEASURED",
            "reason": reason,
            "preset": key,
            "selected_by": selected_by,
            "rules": rules.to_dict(),
            "assumptions": analytics.CHALLENGE_ASSUMPTIONS,
        }
    daily = analytics.daily_returns_from_equity(inputs.equity.frame)
    result = analytics.simulate_challenge(daily, rules, samples=samples, seed=seed)
    status = "MEASURED" if result.get("method") else "NOT_MEASURED"
    out: dict[str, Any] = {"status": status, "preset": key, "selected_by": selected_by, **result}
    if status == "NOT_MEASURED":
        out["reason"] = result["probability"]["pass"]["note"]
    return out


def _round(value: float) -> float:
    return float(f"{value:.10g}")


def _series(frame: pd.DataFrame, *, balance_only: bool) -> dict[str, Any]:
    """What the charts need, small enough to store: the curve downsampled
    with its extremes kept, and the month-end closes for the heatmap."""
    stamps = pd.to_datetime(frame["timestamp"], utc=True)
    equity = frame["equity"].astype(float).tolist()
    keep = charts.downsample(equity, SERIES_MAX_POINTS)
    month = stamps.dt.year.to_numpy() * 12 + stamps.dt.month.to_numpy()
    last_of_month = [
        i for i in range(len(month)) if i == len(month) - 1 or month[i + 1] != month[i]
    ]
    month_end = sorted({0, *last_of_month})
    note = (
        "balance rebuilt from closed trades; floating drawdown is not visible"
        if balance_only
        else "as uploaded"
    )
    return {
        "evidence": MEASURED,
        "note": note,
        "points_total": int(len(frame)),
        "timestamps": [_iso(stamps.iloc[i]) for i in keep],
        "equity": [_round(equity[i]) for i in keep],
        "month_end_timestamps": [_iso(stamps.iloc[i]) for i in month_end],
        "month_end_equity": [_round(equity[i]) for i in month_end],
    }


def _seal(inputs: AuditInputs, *, audit_id: str, now: datetime, holdout_ok: bool) -> dict[str, Any]:
    digest = dataset_digest(inputs.digests)
    section: dict[str, Any] = {"dataset_digest": digest, "components": dict(inputs.digests)}
    oos = inputs.declared.oos_start
    if oos is None or not holdout_ok:
        section["status"] = "NOT_MEASURED"
        section["reason"] = (
            "no out-of-sample start declared" if oos is None else "holdout not evaluated"
        )
        section["holdout_seal"] = None
        return section
    frame = inputs.equity.frame
    start = pd.Timestamp(oos)
    try:
        seal = HoldoutSeal(
            seal_id=audit_id,
            dataset_id="client_upload",
            dataset_digest=digest,
            selection_start=_iso(frame["timestamp"].iloc[0]),
            selection_end=_iso(start - pd.Timedelta(seconds=1)),
            holdout_start=_iso(start),
            holdout_end=_iso(frame["timestamp"].iloc[-1]),
            rationale=(
                "out-of-sample start declared by the client; the auditor cannot verify the "
                "client did not look at it"
            ),
            sealed_at_utc=now.isoformat().replace("+00:00", "Z"),
        )
    except HoldoutSealError as exc:
        section["status"] = "NOT_MEASURED"
        section["reason"] = str(exc)
        section["holdout_seal"] = None
        return section
    section["status"] = "DECLARED"
    section["holdout_seal"] = seal.to_dict()
    return section


def run_audit(
    inputs: AuditInputs,
    *,
    seed: int = 12345,
    bootstrap_samples: int = 1000,
    now: datetime | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    audit_id: str | None = None,
    risk_samples: int = RISK_SAMPLES,
    challenge_samples: int = CHALLENGE_SAMPLES,
) -> AuditResult:
    """Audit one upload. Pure, deterministic for a fixed ``seed``/``now``/``audit_id``."""
    clock = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    identifier = audit_id or uuid.uuid4().hex
    frame = inputs.equity.frame
    returns = inputs.equity.returns
    ppy = inputs.periods_per_year
    trades = inputs.trades.trades if inputs.trades is not None else []
    trials_used, trials_evidence, trials_source = trial_count(inputs)

    performance = _performance(frame, trades)
    significance, moments = _significance(returns)
    multiplicity = _multiplicity(
        moments,
        declared_trials=inputs.declared.trials,
        variants=inputs.variants,
        trials_used=trials_used,
        trials_evidence=trials_evidence,
        trials_source=trials_source,
    )
    bootstrap = _bootstrap(returns, samples=bootstrap_samples, seed=seed)
    subperiods = _subperiods(frame)
    rolling = _rolling(frame, ppy)
    holdout, oos_sharpe, gap, holdout_reason = _holdout(frame, inputs.declared.oos_start, ppy)
    benchmark, benchmark_values, benchmark_reason = _benchmark(inputs.equity, inputs.benchmark)
    cscv, pbo = _cscv(inputs.variants)
    costs, rows, reference, assumed, gross = _costs(inputs)
    measured_trials = trials_used if trials_evidence == MEASURED else 0
    flags = redflags.scan(
        inputs.equity,
        periods_per_year=ppy,
        declared=inputs.declared,
        trades=inputs.trades,
        recomputed_pnl=gross,
        variants_columns=measured_trials,
    )
    if inputs.trades is not None:
        flags.extend(
            redflags.scan_trade_patterns(
                inputs.trades,
                symbols=inputs.trade_symbols,
                balance_only=inputs.balance_only,
            )
        )
        if not inputs.balance_only:
            flags.extend(redflags.scan_trades_against_equity(inputs.trades, frame))
    account, account_flags = account_lib.account_review(
        source_format=inputs.source_format,
        cash_flows=inputs.cash_flows,
        trades=inputs.trades,
        frame=frame,
        metadata=inputs.report_metadata,
    )
    if account["status"] == "MEASURED":
        flags.extend(account_flags)
        account["source"] = "report"
    elif inputs.live_equity_csv is not None and inputs.live_format in account_lib.ACCOUNT_FORMATS:
        # A backtest with the account history in the live field: the review
        # describes that account, and its flags stay out of the backtest's class.
        account, account_flags = account_lib.account_review(
            source_format=inputs.live_format,
            cash_flows=inputs.live_cash_flows,
            trades=inputs.live_trades,
            frame=parse_equity_csv(inputs.live_equity_csv, what="report").frame,
            metadata=inputs.live_metadata,
        )
        account["source"] = "live"
    account["flags"] = [flag.to_dict() for flag in account_flags]
    test_data, test_data_flags = testdata_lib.review_test_data(
        source_format=inputs.source_format,
        metadata=inputs.report_metadata,
        trades=inputs.trades,
    )
    flags.extend(test_data_flags)
    seal = _seal(inputs, audit_id=identifier, now=clock, holdout_ok=holdout_reason is None)
    trade_stats = _trade_stats(inputs)
    stress_tests = _stress(inputs, frame)
    timing = (
        timing_lib.timing_breakdown(inputs.trades.trades)
        if inputs.trades is not None
        else {"status": "NOT_MEASURED", "reason": "no trades uploaded"}
    )
    live = (
        live_lib.compare_live(
            inputs.trades,
            inputs.live_trades,
            backtest_symbols=inputs.trade_symbols,
            live_symbols=inputs.live_symbols,
            seed=seed,
        )
        if inputs.live_trades is not None
        else None
    )
    risk = _risk(returns, ppy, samples=risk_samples, seed=seed)
    challenge = _challenge(inputs, samples=challenge_samples, seed=seed)

    psr = float(moments["psr"]) if moments is not None else None
    p5 = (
        float(bootstrap["sharpe_per_period"]["p5"]["value"])
        if bootstrap["status"] == "MEASURED"
        else None
    )
    statistical = verdict.assess_statistical(
        psr=psr,
        bootstrap_p5_sharpe=p5,
        observations=int(len(returns)),
        thresholds=thresholds,
        not_measured_reason=significance.get("reason"),
    )
    dsr_used = (
        float(multiplicity["dsr_at_trials_used"]["value"])
        if multiplicity["status"] == "MEASURED"
        else None
    )
    dimensions = [
        statistical,
        verdict.assess_multiplicity(
            dsr=dsr_used,
            trials=trials_used,
            trials_evidence=trials_evidence,
            pbo=pbo,
            statistical_status=statistical.status,
            thresholds=thresholds,
        ),
        verdict.assess_costs(
            rows=rows,
            reference_bps=reference,
            reference_is_assumption=assumed,
            fees_reported=inputs.trades is not None and inputs.trades.reports_fees,
            thresholds=thresholds,
        ),
        verdict.assess_out_of_sample(
            oos_sharpe=oos_sharpe,
            gap=gap,
            not_measured_reason=holdout_reason,
            thresholds=thresholds,
        ),
        verdict.assess_data_quality(flags),
        verdict.assess_benchmark(
            applicable=inputs.declared.benchmark_applicable,
            excess_return=benchmark_values["excess_return"],
            drawdown_ratio=benchmark_values["drawdown_ratio"],
            information_ratio=benchmark_values["information_ratio"],
            not_measured_reason=benchmark_reason,
            thresholds=thresholds,
        ),
    ]
    final = verdict.build_verdict(
        dimensions,
        locale=inputs.declared.locale,
        trials=trials_used,
        trials_evidence=trials_evidence,
        thresholds=thresholds,
    )
    mintrl = significance.get("min_track_record_length", {})
    mintrl_value = mintrl.get("value") if mintrl.get("evidence") == MEASURED else None
    questions = analytics.vendor_questions(
        [flag.code for flag in flags],
        has_trades=inputs.trades is not None,
        trials_measured=trials_evidence == MEASURED,
        has_out_of_sample=holdout["status"] == "MEASURED",
        has_costs=inputs.declared.cost_bps_per_side > 0 or bool(inputs.reported_fees),
        balance_only=inputs.balance_only,
        min_track_record_months=(
            float(mintrl_value) / ppy * 12.0 if mintrl_value is not None and ppy > 0 else None
        ),
    )
    oos = inputs.declared.oos_start
    report_metadata = {
        key: _safe_text(value) for key, value in sorted(inputs.report_metadata.items())
    }
    return AuditResult(
        audit_id=identifier,
        schema_version=SCHEMA_VERSION,
        generated_at_utc=clock.isoformat().replace("+00:00", "Z"),
        engine={
            "name": ENGINE_NAME,
            "package_version": _package_version(),
            "seed": seed,
            "bootstrap_samples": bootstrap_samples,
            "risk_samples": risk_samples,
            "challenge_samples": challenge_samples,
        },
        inputs={
            "digests": dict(inputs.digests),
            "dataset_digest": seal["dataset_digest"],
            "source": inputs.equity.source,
            "source_format": inputs.source_format,
            "balance_only": inputs.balance_only,
            "observations": measured(int(len(returns))),
            "first_timestamp": _iso(frame["timestamp"].iloc[0]),
            "last_timestamp": _iso(frame["timestamp"].iloc[-1]),
            "periods_per_year": measured(ppy, "inferred from the timestamps"),
            "frequency_label": inputs.frequency_label,
            "parse_warnings": [_safe_text(w) for w in inputs.warnings],
            "initial_balance": (
                declared(inputs.initial_balance, "starting balance of the imported report")
                if inputs.initial_balance is not None
                else not_measured("no report imported")
            ),
            "report_metadata": report_metadata,
            "optimization": (
                {
                    "passes": measured(inputs.optimization_passes, "rows of the export"),
                    "parameters": [_safe_text(p) for p in inputs.optimization_parameters],
                }
                if inputs.optimization_passes is not None
                else None
            ),
        },
        declared={
            "trials": (
                declared(inputs.declared.trials)
                if inputs.declared.trials_declared
                else not_measured(UNDECLARED_TRIALS)
            ),
            "cost_bps_per_side": declared(inputs.declared.cost_bps_per_side),
            "oos_start": declared(_iso(oos)) if oos is not None else not_measured("not declared"),
            "benchmark_applicable": declared(inputs.declared.benchmark_applicable),
            "initial_balance": (
                declared(inputs.declared.initial_balance)
                if inputs.declared.initial_balance is not None
                else not_measured("not declared")
            ),
            "challenge": inputs.declared.challenge,
            "locale": inputs.declared.locale,
            "description": inputs.declared.description,
        },
        performance=performance,
        significance=significance,
        multiplicity=multiplicity,
        bootstrap=bootstrap,
        subperiods=subperiods,
        rolling=rolling,
        holdout=holdout,
        costs=costs,
        benchmark=benchmark,
        cscv=cscv,
        red_flags=[flag.to_dict() for flag in flags],
        client_text_findings=scan_client_text(inputs.declared.description),
        seal=seal,
        verdict=final,
        series=_series(frame, balance_only=inputs.balance_only),
        trade_stats=trade_stats,
        stress=stress_tests,
        timing=timing,
        live=live,
        risk=risk,
        challenge=challenge,
        account=account,
        test_data=test_data,
        vendor_questions=questions,
    )


__all__ = ["ENGINE_NAME", "run_audit", "sharpe_sampling_variance", "trial_count"]
