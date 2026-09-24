"""Block 3: the selection-window campaign.

Runs every declared trial of every sealed hypothesis over the selection window
and nothing else, under the measured cost model, at both delisting extremes
and at 1x/2x/3x costs; walks forward by calendar year with an embargo; writes
each candidate trial to a hash-chained ledger against its pre-registration
seal; scores every trial under its primary gate and under the unmodified ETF
gate; and freezes at most one primary candidate for the single holdout reveal.

What it refuses, each for a reason that has bitten this repository before:

- a panel that has not been verified against the seal (the seal is bound to
  bytes, not dates);
- a date outside the selection window (``assert_within_selection`` on the
  frame actually evaluated);
- a run after the holdout was revealed (research after a reveal is in-sample
  work wearing an out-of-sample label);
- a trials file whose hash differs from the one locked on first run;
- a second run in the same experiment directory (it would count the declared
  budget twice, and the deflation arithmetic depends on that count).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.costs.crypto_lowcap import equivalent_total_window_turnover
from quant_trade.data.panel_digest import (
    PanelDigestError,
    PanelVerification,
    panel_content_sha256,
)
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.metrics.performance import calculate_performance, periods_per_year
from quant_trade.metrics.statistics import (
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    psr_from_moments,
    return_moments,
    sharpe_variance_across_trials,
)
from quant_trade.research.bootstrap import bootstrap_confidence_intervals
from quant_trade.research.candidate import SelectionCriteria
from quant_trade.research.crypto_evaluator import EvaluationResult, evaluate
from quant_trade.research.crypto_lowcap.config import (
    CommonSettings,
    TrialsConfig,
    assert_lock_matches,
    load_trials_config,
    lock_payload,
    read_lock,
    write_lock,
)
from quant_trade.research.holdout_seal import (
    HoldoutSeal,
    assert_not_revealed,
    assert_within_selection,
    load_seal,
)
from quant_trade.research.ledger import append_trial_record, build_trial_record, read_trials
from quant_trade.research.overfitting import (
    assess_walk_forward_overfitting,
    cscv_probability_of_backtest_overfitting,
)
from quant_trade.research.preregistration import (
    ExperimentPreregistration,
    assert_within_budget,
    load_preregistration,
)
from quant_trade.research.selection import _reasons
from quant_trade.research.signals.crypto_lowcap import REQUIRED_PANEL_COLUMNS
from quant_trade.research.strategy_registry import get_research_signal_model

SCHEMA_VERSION = 1
PANEL_VERIFICATION_FILENAME = "panel_verification.json"
FROZEN_FILENAME = "frozen_selection.json"
SELECTION_DIRNAME = "selection"
TRIALS_DIRNAME = "trials"
RESULTS_FILENAME = "SELECTION_RESULTS.json"
LEDGER_FILENAME = "trial_ledger.jsonl"

SOURCE_CANDIDATE = "crypto_lowcap_select:candidate"
SOURCE_CONTROL = "crypto_lowcap_select:control"
SOURCE_BENCHMARK = "crypto_lowcap_select:benchmark"
SOURCE_FOLD = "crypto_lowcap_select:fold"

#: Both declared delisting assumptions, as strings so they are JSON keys.
RECOVERIES: tuple[str, ...] = ("1.0", "0.0")
#: The stress case decides: ledger Sharpe, CSCV matrix and the freeze read it.
STRESS_RECOVERY = "0.0"

OHLCV_COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")

NOT_MEASURED = "NOT_MEASURED"


class CampaignError(RuntimeError):
    """Raised when the campaign cannot proceed honestly."""


# --- panel ------------------------------------------------------------------


def load_panel(path: str | Path) -> pd.DataFrame:
    """Read a built panel (csv, csv.gz or parquet) into the canonical long form."""
    target = Path(path)
    if not target.is_file():
        raise CampaignError(f"no panel at {target}")
    frame = pd.read_parquet(target) if target.suffix == ".parquet" else pd.read_csv(target)
    missing = [c for c in (*OHLCV_COLUMNS, *REQUIRED_PANEL_COLUMNS) if c not in frame.columns]
    if missing:
        raise CampaignError(f"{target} lacks panel columns {missing}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["symbol"] = frame["symbol"].astype(str)
    return frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def iso_days(frame: pd.DataFrame) -> list[str]:
    return sorted(set(frame["timestamp"].dt.strftime("%Y-%m-%d")))


def span_slice(panel: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    days = panel["timestamp"].dt.strftime("%Y-%m-%d")
    return panel[(days >= start) & (days <= end)].reset_index(drop=True)


def selection_slice(panel: pd.DataFrame, seal: HoldoutSeal) -> pd.DataFrame:
    """The only frame research may see. Raises if a holdout date slipped in."""
    sliced = span_slice(panel, seal.selection_start, seal.selection_end)
    assert_within_selection(seal, iso_days(sliced))
    return sliced


def record_panel_verification(
    experiment_dir: str | Path,
    verification: PanelVerification,
    *,
    panel_path: str | Path,
    at_utc: str,
) -> dict[str, Any]:
    """Persist a verification so ``select`` can bind to the verified bytes."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": verification.status,
        "expected_digest": verification.expected_digest,
        "actual_digest": verification.actual_digest,
        "recipe_by_component": dict(verification.recipe_by_component),
        "reasons": list(verification.reasons),
        "panel_path": str(panel_path),
        "panel_content_sha256": (
            panel_content_sha256(panel_path) if Path(panel_path).is_file() else ""
        ),
        "verified_at_utc": at_utc,
    }
    atomic_write_json(Path(experiment_dir) / PANEL_VERIFICATION_FILENAME, payload)
    return payload


def require_verified_panel(
    experiment_dir: str | Path, panel_path: str | Path, seal: HoldoutSeal
) -> dict[str, Any]:
    """Fail closed unless this exact panel passed verification against this seal."""
    path = Path(experiment_dir) / PANEL_VERIFICATION_FILENAME
    if not path.is_file():
        raise CampaignError(
            f"no {PANEL_VERIFICATION_FILENAME} in {experiment_dir}; run "
            "`quant-trade crypto-lowcap verify-panel` first"
        )
    payload = load_json(path)
    if payload.get("status") != "PASS":
        raise CampaignError("the recorded panel verification did not pass; nothing may run")
    if payload.get("expected_digest") != seal.dataset_digest:
        raise CampaignError("the panel verification was made against a different seal")
    try:
        actual = panel_content_sha256(panel_path)
    except PanelDigestError as exc:
        raise CampaignError(f"panel bytes differ from the verified panel: {exc}") from exc
    if payload.get("panel_content_sha256") != actual:
        raise CampaignError(
            "panel bytes differ from the verified panel; re-run verify-panel on this file"
        )
    return payload


# --- evaluation -------------------------------------------------------------


@dataclass
class Evaluated:
    result: EvaluationResult
    returns: pd.Series
    equity_frame: pd.DataFrame


def generate_weights(panel: pd.DataFrame, strategy: str, params: dict[str, Any]) -> pd.DataFrame:
    return get_research_signal_model(strategy).generate(panel, params)


def evaluate_span(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    start: str,
    end: str,
    *,
    common: CommonSettings,
    recovery: float,
    cost_multiplier: float = 1.0,
) -> Evaluated:
    sliced = span_slice(panel, start, end)
    if sliced.empty:
        raise CampaignError(f"no panel rows between {start} and {end}")
    result = evaluate(
        sliced,
        weights,
        initial_capital_usd=common.initial_capital_usd,
        delisting_recovery=recovery,
        quantile=common.quantile,
        min_executable_fraction=common.min_executable_fraction,
        cost_multiplier=cost_multiplier,
    )
    equity = result.equity
    frame = pd.DataFrame({"timestamp": equity.index, "equity": equity.to_numpy(dtype=float)})
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    return Evaluated(result=result, returns=returns, equity_frame=frame)


def performance(evaluated: Evaluated) -> dict[str, Any]:
    perf = calculate_performance(evaluated.equity_frame, [])
    moments = return_moments(evaluated.returns)
    summary = evaluated.result.summary()
    return {
        "sharpe": float(perf["sharpe"]),
        "total_return": float(perf["total_return"]),
        "cagr": float(perf["cagr"]),
        "volatility": float(perf["volatility"]),
        "max_drawdown": float(perf["max_drawdown"]),
        "psr": float(probabilistic_sharpe_ratio(evaluated.returns)),
        "sharpe_per_period": float(moments["sharpe_per_period"]),
        "observations": float(moments["observations"]),
        "skewness": float(moments["skewness"]),
        "kurtosis": float(moments["kurtosis"]),
        "annual_turnover": float(summary["annual_turnover"]),
        "turnover_raw": float(summary["total_turnover"]),
        "cost_drag_bps_per_year": float(summary["cost_drag_bps_per_year"]),
        "total_cost_usd": float(summary["total_cost_usd"]),
        "executed_legs": int(summary["executed_legs"]),
        "refused_legs": int(summary["refused_legs"]),
        "capped_legs": int(summary["capped_legs"]),
        "unpriceable_legs": int(summary["unpriceable_legs"]),
        "delisted_positions": int(summary["delisted_positions"]),
        "delisting_losses_usd": float(summary["delisting_losses_usd"]),
        "final_value_usd": float(summary["final_value_usd"]),
        "years": float(summary["years"]),
        "rebalances": int(summary["rebalances"]),
    }


def gate_turnover(metrics: dict[str, Any], turnover: dict[str, Any]) -> float:
    """The turnover the gate reads, on the basis the config declared."""
    if turnover["basis"] == "annual_x_holdout_years":
        return equivalent_total_window_turnover(
            metrics["annual_turnover"], float(turnover["holdout_years"])
        )
    return float(metrics["turnover_raw"])


def comparison(strategy: dict[str, Any], benchmark: dict[str, Any] | None) -> dict[str, Any]:
    if benchmark is None:
        return {"status": NOT_MEASURED}
    strategy_dd = abs(float(strategy["max_drawdown"]))
    benchmark_dd = abs(float(benchmark["max_drawdown"]))
    return {
        "status": "MEASURED",
        "excess_return": float(strategy["total_return"]) - float(benchmark["total_return"]),
        "strategy_total_return": float(strategy["total_return"]),
        "benchmark_total_return": float(benchmark["total_return"]),
        "strategy_sharpe": float(strategy["sharpe"]),
        "benchmark_sharpe": float(benchmark["sharpe"]),
        "strategy_max_drawdown": -strategy_dd,
        "benchmark_max_drawdown": -benchmark_dd,
        "drawdown_ratio": (strategy_dd / benchmark_dd) if benchmark_dd > 0 else None,
    }


def sharpe_standard_error(metrics: dict[str, Any], periods: float) -> float | None:
    """Lo (2002) standard error of an annualised Sharpe from per-period moments.

    Same denominator as ``psr_from_moments``, so the range this produces and
    the PSR the gate reads are two views of one estimate.
    """
    sr = float(metrics["sharpe_per_period"])
    n = float(metrics["observations"])
    if n < 3:
        return None
    variance = 1.0 - metrics["skewness"] * sr + ((metrics["kurtosis"] - 1.0) / 4.0) * sr**2
    if variance <= 0:
        return None
    return math.sqrt(variance / (n - 1.0)) * math.sqrt(periods)


def sharpe_range(evaluated: Evaluated, metrics: dict[str, Any]) -> dict[str, Any]:
    periods = periods_per_year(evaluated.equity_frame["timestamp"])
    se = sharpe_standard_error(metrics, periods)
    point = float(metrics["sharpe_per_period"]) * math.sqrt(periods)
    if se is None:
        return {"status": NOT_MEASURED, "sharpe_annualised": point}
    low1, high1 = point - se, point + se
    if low1 > 0:
        verdict = "RANGE_ABOVE_ZERO"
    elif high1 < 0:
        verdict = "RANGE_BELOW_ZERO"
    else:
        verdict = "RANGE_INCLUDES_ZERO"
    return {
        "status": "MEASURED",
        "sharpe_annualised": point,
        "sharpe_se": se,
        "range_1se": [low1, high1],
        "range_95": [point - 1.96 * se, point + 1.96 * se],
        "verdict_class": verdict,
    }


# --- walk-forward -----------------------------------------------------------


@dataclass(frozen=True)
class Fold:
    index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
        }


def fold_windows(seal: HoldoutSeal, test_years: list[int], embargo_days: int) -> list[Fold]:
    """Calendar-year test windows with an expanding, embargoed train span."""
    if embargo_days < 0:
        raise CampaignError("embargo_days must be >= 0")
    folds: list[Fold] = []
    for year in sorted(int(y) for y in test_years):
        test_start = max(f"{year}-01-01", seal.selection_start)
        test_end = min(f"{year}-12-31", seal.selection_end)
        if test_start > test_end:
            continue
        train_end = (date.fromisoformat(test_start) - timedelta(days=embargo_days + 1)).isoformat()
        if train_end <= seal.selection_start:
            raise CampaignError(f"test year {year} leaves no train span before the embargo")
        folds.append(Fold(len(folds) + 1, seal.selection_start, train_end, test_start, test_end))
    if not folds:
        raise CampaignError("walk_forward.test_years produced no fold inside the selection window")
    return folds


@dataclass
class WalkForwardOutcome:
    evidence: dict[str, Any]
    folds: list[dict[str, Any]]
    train_sharpes: dict[str, list[float]]


def walk_forward(
    panel: pd.DataFrame,
    weights_by_trial: dict[str, pd.DataFrame],
    folds: list[Fold],
    *,
    common: CommonSettings,
    recovery: float,
    criteria: SelectionCriteria,
) -> WalkForwardOutcome:
    """Per-fold train-winner OOS rank, the estimator the ETF study used."""
    ranks: list[float] = []
    degradations: list[float] = []
    rows: list[dict[str, Any]] = []
    train_sharpes: dict[str, list[float]] = {tid: [] for tid in weights_by_trial}
    for fold in folds:
        train = {
            tid: performance(
                evaluate_span(
                    panel, w, fold.train_start, fold.train_end, common=common, recovery=recovery
                )
            )["sharpe"]
            for tid, w in weights_by_trial.items()
        }
        test = {
            tid: performance(
                evaluate_span(
                    panel, w, fold.test_start, fold.test_end, common=common, recovery=recovery
                )
            )["sharpe"]
            for tid, w in weights_by_trial.items()
        }
        best = sorted(train, key=lambda tid: (-train[tid], tid))[0]
        rank = float(pd.Series(test, dtype=float).rank(method="average", pct=True).loc[best])
        ranks.append(rank)
        degradations.append(float(train[best] - test[best]))
        for tid in train:
            train_sharpes[tid].append(float(train[tid]))
        rows.append(
            {
                **fold.to_dict(),
                "selected_trial_id": best,
                "train_sharpe": {tid: float(v) for tid, v in train.items()},
                "test_sharpe": {tid: float(v) for tid, v in test.items()},
                "selected_oos_rank_percentile": rank,
                "train_test_degradation": float(train[best] - test[best]),
            }
        )
    evidence = assess_walk_forward_overfitting(
        ranks,
        degradations,
        parameter_variants=len(weights_by_trial),
        max_walk_forward_pbo=criteria.max_walk_forward_pbo,
        min_windows=criteria.min_walk_forward_windows,
    )
    return WalkForwardOutcome(evidence=evidence.to_dict(), folds=rows, train_sharpes=train_sharpes)


def cscv(
    returns_by_trial: dict[str, pd.Series], *, partitions: int, max_pbo: float
) -> dict[str, Any]:
    """Rank-based CSCV over the trials' aligned OOS daily returns."""
    if len(returns_by_trial) < 2:
        return {"status": NOT_MEASURED, "reason": "CSCV needs at least two variants"}
    matrix = pd.concat(returns_by_trial, axis=1).dropna()
    usable = len(matrix) - (len(matrix) % partitions)
    if usable < partitions:
        return {"status": NOT_MEASURED, "reason": "too few aligned observations for CSCV"}
    evidence = cscv_probability_of_backtest_overfitting(
        matrix.iloc[len(matrix) - usable :].to_numpy(dtype=float),
        partitions=partitions,
        max_pbo=max_pbo,
    )
    payload = evidence.to_dict()
    payload["status"] = "MEASURED"
    payload["trial_ids"] = list(matrix.columns)
    return payload


def bootstrap(returns: pd.Series, common: CommonSettings) -> dict[str, Any]:
    try:
        table = bootstrap_confidence_intervals(
            returns,
            method="stationary",
            samples=common.bootstrap_samples,
            seed=common.bootstrap_seed,
            block_size=common.bootstrap_block_size,
            percentiles=(5.0, 50.0, 95.0),
        )
    except ValueError as exc:
        return {"status": NOT_MEASURED, "reason": str(exc)}
    out: dict[str, Any] = {
        "status": "MEASURED",
        "method": "stationary",
        "samples": common.bootstrap_samples,
        "seed": common.bootstrap_seed,
        "expected_block_size": common.bootstrap_block_size,
    }
    for stat in ("total_return", "sharpe", "max_drawdown"):
        row = table.loc[stat]
        out[stat] = {
            "point_estimate": float(row["point_estimate"]),
            "p5": float(row["p5"]),
            "p50": float(row["p50"]),
            "p95": float(row["p95"]),
        }
    return out


# --- deflation and gates ----------------------------------------------------


def deflated_sharpes(
    metrics: dict[str, Any],
    *,
    n_declared: int,
    n_spent: int,
    own_sharpes: list[float],
    floor: float,
    etf_sharpes: list[float] | None,
) -> dict[str, Any]:
    """The three declared DSR variants from one set of per-period moments."""
    sr = float(metrics["sharpe_per_period"])
    n = int(metrics["observations"])
    skew = float(metrics["skewness"])
    kurt = float(metrics["kurtosis"])

    def _dsr(trials: int, variance: float) -> float:
        return psr_from_moments(
            sr, n, skew, kurt, benchmark_sharpe=expected_max_sharpe(trials, variance)
        )

    observed = sharpe_variance_across_trials(own_sharpes)
    used = max(observed, floor)
    out: dict[str, Any] = {
        "declared": {
            "n_trials": n_declared,
            "sharpe_variance": used,
            "variance_policy": "max(observed across sealed trials, floor)",
            "value": _dsr(n_declared, used),
        },
        "observed": {
            "n_trials": n_spent,
            "sharpe_variance": observed,
            "value": _dsr(n_spent, observed),
        },
        "inputs": {
            "sharpe_per_period": sr,
            "observations": n,
            "skewness": skew,
            "kurtosis": kurt,
            "sharpe_variance_floor": floor,
        },
    }
    if etf_sharpes is None:
        out["combined"] = {"status": NOT_MEASURED, "reason": "ETF ledger not available"}
    else:
        pooled = sharpe_variance_across_trials([*own_sharpes, *etf_sharpes])
        trials = n_declared + len(etf_sharpes)
        out["combined"] = {
            "n_trials": trials,
            "sharpe_variance": pooled,
            "value": _dsr(trials, pooled),
        }
    return out


def score(
    result: dict[str, Any], criteria: SelectionCriteria, n_trials: int, variance: float
) -> dict[str, Any]:
    reasons = _reasons(result, criteria, (n_trials, variance))
    return {"pass": not reasons, "reasons": reasons}


def load_gates(config: TrialsConfig) -> tuple[dict[str, SelectionCriteria], dict[str, str]]:
    criteria: dict[str, SelectionCriteria] = {}
    shas: dict[str, str] = {}
    for name, path in config.gate_paths().items():
        target = Path(path)
        if not target.is_file():
            raise CampaignError(f"gate {name!r} points at a missing file {target}")
        criteria[name] = SelectionCriteria.from_yaml(target)
        shas[name] = sha256_of_file(target)
    return criteria, shas


def etf_ledger_sharpes(config: TrialsConfig) -> list[float] | None:
    path = config.deflated_sharpe.get("etf_ledger")
    if not path or not Path(path).is_file():
        return None
    records = read_trials(None, registry_path=path)
    return [
        float(r["test_sharpe_per_period"])
        for r in records
        if r.get("test_sharpe_per_period") is not None
    ]


# --- benchmarks -------------------------------------------------------------


def btc_weights(panel: pd.DataFrame, symbol: str, start: str) -> pd.DataFrame | None:
    """Buy-and-hold of one symbol from its first bar at or after ``start``."""
    rows = panel[
        (panel["symbol"] == symbol) & (panel["timestamp"].dt.strftime("%Y-%m-%d") >= start)
    ]
    if rows.empty:
        return None
    first = rows["timestamp"].min()
    return pd.DataFrame([{"timestamp": first, "symbol": symbol, "target_weight": 1.0}])


def benchmark_weights(
    panel: pd.DataFrame, config: TrialsConfig, start: str
) -> dict[str, pd.DataFrame | None]:
    out: dict[str, pd.DataFrame | None] = {}
    for name, spec in config.benchmarks.items():
        if "symbol" in spec:
            out[name] = btc_weights(panel, str(spec["symbol"]), start)
        else:
            params = {**config.common.signal_params(), **dict(spec.get("params", {}))}
            out[name] = generate_weights(panel, str(spec["strategy"]), params)
    return out


# --- freeze -----------------------------------------------------------------


def frozen_sha256(payload: dict[str, Any]) -> str:
    return sha256_of_text(canonical_dumps({k: v for k, v in payload.items() if k != "sha256"}))


def freeze(
    trial_rows: list[dict[str, Any]],
    *,
    primary_gate_key: str,
    panel_digest: str,
    results_sha256: str,
    at_utc: str,
) -> dict[str, Any]:
    """At most one primary candidate, plus at most one secondary per other hypothesis."""

    def passes(row: dict[str, Any]) -> bool:
        return all(row["gates"][rec][primary_gate_key]["pass"] for rec in RECOVERIES)

    def key(row: dict[str, Any]) -> tuple[float, float, str]:
        return (
            -float(row["dsr"][STRESS_RECOVERY]["declared"]["value"]),
            float(row["by_recovery"][STRESS_RECOVERY]["test_metrics"]["turnover"]),
            row["trial_id"],
        )

    passing = sorted((r for r in trial_rows if passes(r)), key=key)
    if not passing:
        return {
            "schema_version": SCHEMA_VERSION,
            "frozen_at_utc": at_utc,
            "panel_digest": panel_digest,
            "selection_results_sha256": results_sha256,
            "primary": None,
            "secondaries": [],
            "no_candidate_reason": (
                "no trial passed its primary gate at both delisting assumptions; nothing is "
                "frozen and the holdout stays sealed"
            ),
        }
    primary = passing[0]
    secondaries: list[dict[str, Any]] = []
    seen = {primary["experiment_id"]}
    for row in passing[1:]:
        if row["experiment_id"] in seen:
            continue
        seen.add(row["experiment_id"])
        secondaries.append(_frozen_entry(row))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "frozen_at_utc": at_utc,
        "panel_digest": panel_digest,
        "selection_results_sha256": results_sha256,
        "criterion": (
            "passes the primary gate at delisting_recovery 1.0 AND 0.0; highest declared DSR "
            "at recovery 0.0; ties broken by lower turnover, then trial id"
        ),
        "primary": _frozen_entry(primary),
        "secondaries": secondaries,
        "no_candidate_reason": None,
    }
    payload["sha256"] = frozen_sha256(payload)
    return payload


def _frozen_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trial_id": row["trial_id"],
        "experiment_id": row["experiment_id"],
        "preregistration_seal": row["preregistration_seal"],
        "strategy": row["strategy"],
        "strategy_params": dict(row["strategy_params"]),
        "control_strategy": row["control_strategy"],
        "control_params": dict(row["control_params"]),
        "gate": row["primary_gate"],
        "refutation_checks": list(row["refutation_checks"]),
        "declared_dsr_at_recovery_0": float(row["dsr"][STRESS_RECOVERY]["declared"]["value"]),
    }


def load_frozen(experiment_dir: str | Path) -> dict[str, Any] | None:
    path = Path(experiment_dir) / FROZEN_FILENAME
    if not path.is_file():
        return None
    payload = load_json(path)
    if payload.get("primary") is None:
        return payload
    if payload.get("sha256") != frozen_sha256(payload):
        raise CampaignError(f"{path} was edited after it was frozen; its sha256 no longer matches")
    return payload


# --- the campaign -----------------------------------------------------------


def _trial_id(experiment_id: str, index: int) -> str:
    return f"{experiment_id}:t{index}"


def run_select(
    experiment_dir: str | Path,
    trials_path: str | Path,
    panel_path: str | Path,
    *,
    evaluated_at_utc: str,
    code_sha: str,
) -> dict[str, Any]:
    exp = Path(experiment_dir)
    seal = load_seal(exp)
    assert_not_revealed(exp)
    results_path = exp / SELECTION_DIRNAME / RESULTS_FILENAME
    if results_path.exists():
        raise CampaignError(
            f"{results_path} already exists. A selection runs once per experiment: running it "
            "again would spend the declared trial budget twice. Reseal a new experiment instead."
        )
    config = load_trials_config(trials_path)
    criteria, gate_shas = load_gates(config)
    verification = require_verified_panel(exp, panel_path, seal)
    panel_digest = seal.dataset_digest
    content_sha = str(verification["panel_content_sha256"])

    lock = read_lock(exp)
    if lock is None:
        lock = lock_payload(
            seal_id=seal.seal_id,
            panel_digest=panel_digest,
            panel_content_sha256=content_sha,
            digest_recipe=dict(verification["recipe_by_component"]),
            trials_config_path=config.path,
            trials_config_sha256=config.sha256,
            gate_shas=gate_shas,
            code_sha=code_sha,
            at_utc=evaluated_at_utc,
        )
        write_lock(exp, lock)
    else:
        assert_lock_matches(
            lock,
            panel_digest=panel_digest,
            panel_content_sha256=content_sha,
            trials_config_sha256=config.sha256,
            gate_shas=gate_shas,
        )

    ledger = exp / LEDGER_FILENAME
    preregs: dict[str, ExperimentPreregistration] = {}
    existing = read_trials(None, registry_path=ledger)
    for spec in config.hypotheses:
        prereg = load_preregistration(exp / spec.experiment_id)
        if prereg.universe[0].split("@", 1)[-1] != panel_digest:
            raise CampaignError(
                f"{spec.experiment_id} was registered against a different panel digest"
            )
        if len(spec.variants) > prereg.max_trials:
            raise CampaignError(
                f"{spec.experiment_id} declares {len(spec.variants)} variants but its "
                f"pre-registration allows {prereg.max_trials}"
            )
        assert_within_budget(prereg, existing)
        preregs[spec.experiment_id] = prereg

    common = config.common
    panel = selection_slice(load_panel(panel_path), seal)
    folds = fold_windows(
        seal, list(config.walk_forward["test_years"]), int(config.walk_forward["embargo_days"])
    )
    oos_start = str(config.walk_forward.get("oos_start", folds[0].test_start))
    oos_end = seal.selection_end
    months = (date.fromisoformat(oos_end) - date.fromisoformat(oos_start)).days / 30.0
    floor = float(config.deflated_sharpe["sharpe_variance_floor"])
    n_declared = int(config.deflated_sharpe.get("n_trials_declared", config.declared_trials))
    etf_sharpes = etf_ledger_sharpes(config)
    primary_bench = str(config.deflated_sharpe.get("primary_benchmark", "ew_universe_buy_and_hold"))

    # Benchmarks once, at 1x, both recoveries.
    bench_weights = benchmark_weights(panel, config, oos_start)
    bench_metrics: dict[str, dict[str, dict[str, Any] | None]] = {}
    bench_equity: dict[str, dict[str, list[float]]] = {}
    for name, weights in bench_weights.items():
        bench_metrics[name] = {}
        bench_equity[name] = {}
        for rec in RECOVERIES:
            if weights is None:
                bench_metrics[name][rec] = None
                continue
            ev = evaluate_span(
                panel, weights, oos_start, oos_end, common=common, recovery=float(rec)
            )
            bench_metrics[name][rec] = performance(ev)
            bench_equity[name][rec] = [float(v) for v in ev.equity_frame["equity"]]
            _ledger_append(
                ledger,
                SOURCE_BENCHMARK,
                name,
                {},
                run_id=evaluated_at_utc,
                panel_digest=panel_digest,
                config_sha=config.sha256,
                code_sha=code_sha,
                common=common,
                scheme=str(config.walk_forward["scheme"]),
                seal="",
                metrics=bench_metrics[name][rec],
                test_range=[oos_start, oos_end],
            )

    trial_rows: list[dict[str, Any]] = []
    trials_dir = exp / SELECTION_DIRNAME / TRIALS_DIRNAME
    trials_dir.mkdir(parents=True, exist_ok=True)
    sealed_sharpes: list[float] = []
    cscv_inputs: dict[str, pd.Series] = {}
    fold_rows_by_hypothesis: dict[str, dict[str, list[dict[str, Any]]]] = {}
    per_trial: dict[str, dict[str, Any]] = {}

    for spec in config.hypotheses:
        prereg = preregs[spec.experiment_id]
        gate_key = f"primary:{spec.experiment_id}"
        weights_by_trial: dict[str, pd.DataFrame] = {}
        params_by_trial: dict[str, dict[str, Any]] = {}
        for i, variant in enumerate(spec.variants, start=1):
            tid = _trial_id(spec.experiment_id, i)
            params = {**common.signal_params(), **variant}
            params_by_trial[tid] = params
            weights_by_trial[tid] = generate_weights(panel, spec.strategy, params)
        control_strategy = spec.control_strategy or spec.strategy
        control_weights: dict[str, pd.DataFrame] = {}
        control_params_by_trial: dict[str, dict[str, Any]] = {}
        shared_control: pd.DataFrame | None = None
        shared_params: dict[str, Any] | None = None
        for tid, params in params_by_trial.items():
            cparams = (
                {**params, **spec.control}
                if spec.control_strategy is None
                else {
                    **common.signal_params(),
                    **spec.control,
                }
            )
            control_params_by_trial[tid] = cparams
            if spec.control_shared:
                if shared_control is None:
                    shared_params = cparams
                    shared_control = generate_weights(panel, control_strategy, cparams)
                control_weights[tid] = shared_control
                control_params_by_trial[tid] = dict(shared_params or cparams)
            else:
                control_weights[tid] = generate_weights(panel, control_strategy, cparams)

        wf_by_recovery = {
            rec: walk_forward(
                panel,
                weights_by_trial,
                folds,
                common=common,
                recovery=float(rec),
                criteria=criteria[gate_key],
            )
            for rec in RECOVERIES
        }
        fold_rows_by_hypothesis[spec.experiment_id] = {
            rec: wf_by_recovery[rec].folds for rec in RECOVERIES
        }

        for tid, params in params_by_trial.items():
            by_recovery: dict[str, Any] = {}
            equity_oos: dict[str, Any] = {}
            for rec in RECOVERIES:
                evals = {
                    mult: evaluate_span(
                        panel,
                        weights_by_trial[tid],
                        oos_start,
                        oos_end,
                        common=common,
                        recovery=float(rec),
                        cost_multiplier=mult,
                    )
                    for mult in common.cost_multipliers
                }
                base = evals[1.0]
                metrics = performance(base)
                control_ev = evaluate_span(
                    panel,
                    control_weights[tid],
                    oos_start,
                    oos_end,
                    common=common,
                    recovery=float(rec),
                )
                control_metrics = performance(control_ev)
                _ledger_append(
                    ledger,
                    SOURCE_CONTROL,
                    control_strategy,
                    control_params_by_trial[tid],
                    run_id=evaluated_at_utc,
                    panel_digest=panel_digest,
                    config_sha=config.sha256,
                    code_sha=code_sha,
                    common=common,
                    scheme=str(config.walk_forward["scheme"]),
                    seal="",
                    metrics=control_metrics,
                    test_range=[oos_start, oos_end],
                )
                highest = max(common.cost_multipliers)
                sensitivity = {
                    f"{mult:g}x": {
                        "total_return": performance(ev)["total_return"],
                        "cost_drag_bps_per_year": performance(ev)["cost_drag_bps_per_year"],
                    }
                    for mult, ev in evals.items()
                }
                cost_pass = float(sensitivity[f"{highest:g}x"]["total_return"]) > 0.0
                test_metrics = {
                    **metrics,
                    "turnover": gate_turnover(metrics, config.turnover),
                    "trade_count": metrics["executed_legs"],
                }
                wf = wf_by_recovery[rec]
                train_sharpe = (
                    float(np.mean(wf.train_sharpes[tid])) if wf.train_sharpes[tid] else 0.0
                )
                result = {
                    "strategy": spec.strategy,
                    "strategy_params": params,
                    "experiment_name": tid,
                    "universe": [],
                    "test_metrics": test_metrics,
                    "train_metrics": {"sharpe": train_sharpe},
                    "comparison_test": comparison(
                        metrics, bench_metrics.get(primary_bench, {}).get(rec)
                    ),
                    "test_range": [oos_start, oos_end],
                    "test_months": months,
                    "robustness": {"cost_sensitivity_pass": cost_pass},
                    "overfitting_evidence": {
                        **wf.evidence,
                        "strategy": spec.strategy,
                        "dataset_binding": {"data_sha256": panel_digest},
                    },
                    "dataset_binding": {"data_sha256": panel_digest},
                }
                by_recovery[rec] = {
                    "test_metrics": test_metrics,
                    "train_metrics": {"sharpe": train_sharpe},
                    "comparison_test": result["comparison_test"],
                    "comparisons": {
                        name: comparison(metrics, bench_metrics[name].get(rec))
                        for name in bench_metrics
                    },
                    "control": {
                        "strategy": control_strategy,
                        "params": control_params_by_trial[tid],
                        "metrics": control_metrics,
                    },
                    "beats_control": bool(
                        metrics["total_return"] > control_metrics["total_return"]
                    ),
                    "cost_sensitivity": sensitivity,
                    "robustness": {"cost_sensitivity_pass": cost_pass},
                    "bootstrap": bootstrap(base.returns, common),
                    "sharpe_range": sharpe_range(base, metrics),
                    "overfitting_evidence": result["overfitting_evidence"],
                    "_result": result,
                }
                equity_oos[rec] = [float(v) for v in base.equity_frame["equity"]]
                if rec == STRESS_RECOVERY:
                    equity_oos["dates"] = [
                        t.strftime("%Y-%m-%d") for t in base.equity_frame["timestamp"]
                    ]
                    cscv_inputs[tid] = base.returns
            stress = by_recovery[STRESS_RECOVERY]["test_metrics"]
            sealed_sharpes.append(float(stress["sharpe_per_period"]))
            _ledger_append(
                ledger,
                SOURCE_CANDIDATE,
                spec.strategy,
                params,
                run_id=evaluated_at_utc,
                panel_digest=panel_digest,
                config_sha=config.sha256,
                code_sha=code_sha,
                common=common,
                scheme=str(config.walk_forward["scheme"]),
                seal=prereg.seal(),
                metrics=stress,
                test_range=[oos_start, oos_end],
                extra_costs={"recovery_1.0": by_recovery["1.0"]["test_metrics"]},
            )
            per_trial[tid] = {
                "trial_id": tid,
                "experiment_id": spec.experiment_id,
                "preregistration_seal": prereg.seal(),
                "strategy": spec.strategy,
                "strategy_params": params,
                "control_strategy": control_strategy,
                "control_params": control_params_by_trial[tid],
                "primary_gate": gate_key,
                "refutation_checks": list(spec.refutation_checks),
                "by_recovery": by_recovery,
                "equity_oos": equity_oos,
            }

    # Deflation needs every sealed Sharpe, so it runs after all trials.
    n_spent = len(sealed_sharpes)
    variance_used = max(sharpe_variance_across_trials(sealed_sharpes), floor)
    cscv_by_hypothesis = {
        spec.experiment_id: cscv(
            {tid: s for tid, s in cscv_inputs.items() if tid.startswith(spec.experiment_id + ":")},
            partitions=common.cscv_partitions,
            max_pbo=criteria[f"primary:{spec.experiment_id}"].max_walk_forward_pbo,
        )
        for spec in config.hypotheses
    }
    cscv_pooled = cscv(cscv_inputs, partitions=common.cscv_partitions, max_pbo=0.5)

    for tid, row in per_trial.items():
        gate_key = row["primary_gate"]
        row["dsr"] = {}
        row["gates"] = {}
        for rec in RECOVERIES:
            block = row["by_recovery"][rec]
            result = block.pop("_result")
            row["dsr"][rec] = deflated_sharpes(
                block["test_metrics"],
                n_declared=n_declared,
                n_spent=n_spent,
                own_sharpes=sealed_sharpes,
                floor=floor,
                etf_sharpes=etf_sharpes,
            )
            row["gates"][rec] = {
                name: score(result, crit, n_declared, variance_used)
                for name, crit in criteria.items()
                if name == gate_key or not name.startswith("primary:")
            }
        row["cscv"] = cscv_by_hypothesis[row["experiment_id"]]
        row["folds"] = fold_rows_by_hypothesis[row["experiment_id"]]
        row["evidence_class"] = "MEASURED"
        row["schema_version"] = SCHEMA_VERSION
        atomic_write_json(trials_dir / f"{tid.replace(':', '__')}.json", row)
        trial_rows.append(row)

    summary_rows = [_summary_row(row) for row in trial_rows]
    results = {
        "artifact": "SELECTION_RESULTS",
        "schema_version": SCHEMA_VERSION,
        "evaluated_at_utc": evaluated_at_utc,
        "code_sha": code_sha,
        "evidence_class": "MEASURED",
        "seal": {"seal_id": seal.seal_id, "seal": seal.seal(), "panel_digest": panel_digest},
        "trials_config": {"path": config.path, "sha256": config.sha256},
        "gate_shas": gate_shas,
        "selection_window": [seal.selection_start, seal.selection_end],
        "oos_window": [oos_start, oos_end],
        "walk_forward": {**config.walk_forward, "folds": [f.to_dict() for f in folds]},
        "turnover_basis": config.turnover,
        "benchmarks": {
            name: {rec: bench_metrics[name][rec] for rec in RECOVERIES} for name in bench_metrics
        },
        "benchmark_equity": {
            name: {rec: bench_equity[name].get(rec) for rec in RECOVERIES} for name in bench_equity
        },
        "budgets": [
            {
                "experiment_id": spec.experiment_id,
                "seal": preregs[spec.experiment_id].seal(),
                "max_trials": preregs[spec.experiment_id].max_trials,
                "trials_spent": len(spec.variants),
            }
            for spec in config.hypotheses
        ],
        "deflated_sharpe": {
            "n_trials_declared": n_declared,
            "n_trials_spent": n_spent,
            "sharpe_variance_observed": sharpe_variance_across_trials(sealed_sharpes),
            "sharpe_variance_floor": floor,
            "sharpe_variance_used": variance_used,
            "etf_ledger_trials": None if etf_sharpes is None else len(etf_sharpes),
        },
        "cscv_by_hypothesis": cscv_by_hypothesis,
        "cscv_pooled": cscv_pooled,
        "trials": summary_rows,
        "ledger": {"path": str(ledger), "sealed_records": n_spent},
        "declared_limits": [
            "the holdout is sealed and unread; nothing here is out-of-sample evidence",
            "annual rebalancing yields few executed legs; min_trade_count is reported as a "
            "structural limit where it binds",
            "delisting_recovery 1.0 and 0.0 bracket an ASSUMPTION; neither is the truth",
            "costs rest on one order-book cross-section (2026-08-05); historical spreads are "
            "NOT_MEASURED",
        ],
    }
    # Written exactly once: the frozen selection binds to this file's sha256,
    # so nothing may be appended to it afterwards, not even the freeze summary.
    atomic_write_json(results_path, results)
    results_sha = sha256_of_file(results_path)
    frozen = _freeze_with_primary(trial_rows, panel_digest, results_sha, evaluated_at_utc)
    atomic_write_json(exp / FROZEN_FILENAME, frozen)
    return {
        **results,
        "frozen": {
            "primary_trial_id": None
            if frozen["primary"] is None
            else frozen["primary"]["trial_id"],
            "secondary_trial_ids": [s["trial_id"] for s in frozen["secondaries"]],
            "no_candidate_reason": frozen["no_candidate_reason"],
        },
    }


def _freeze_with_primary(
    trial_rows: list[dict[str, Any]], panel_digest: str, results_sha: str, at_utc: str
) -> dict[str, Any]:
    """Freeze where each row's own primary gate decides its pass."""
    normalised = []
    for row in trial_rows:
        clone = dict(row)
        clone["gates"] = {
            rec: {**row["gates"][rec], "__primary__": row["gates"][rec][row["primary_gate"]]}
            for rec in RECOVERIES
        }
        normalised.append(clone)
    return freeze(
        normalised,
        primary_gate_key="__primary__",
        panel_digest=panel_digest,
        results_sha256=results_sha,
        at_utc=at_utc,
    )


def _summary_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "trial_id": row["trial_id"],
        "experiment_id": row["experiment_id"],
        "strategy": row["strategy"],
        "strategy_params": row["strategy_params"],
        "primary_gate": row["primary_gate"],
    }
    for rec in RECOVERIES:
        block = row["by_recovery"][rec]
        m = block["test_metrics"]
        out[f"recovery_{rec}"] = {
            "sharpe": m["sharpe"],
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "excess_vs_primary_benchmark": block["comparison_test"].get("excess_return"),
            "drawdown_ratio": block["comparison_test"].get("drawdown_ratio"),
            "turnover_gate_basis": m["turnover"],
            "annual_turnover": m["annual_turnover"],
            "cost_drag_bps_per_year": m["cost_drag_bps_per_year"],
            "executed_legs": m["executed_legs"],
            "psr": m["psr"],
            "dsr_declared": row["dsr"][rec]["declared"]["value"],
            "dsr_observed": row["dsr"][rec]["observed"]["value"],
            "walk_forward_pbo": block["overfitting_evidence"]["walk_forward_pbo"],
            "bootstrap_total_return_p5": block["bootstrap"].get("total_return", {}).get("p5"),
            "beats_control": block["beats_control"],
            "cost_sensitivity_pass": block["robustness"]["cost_sensitivity_pass"],
            "gates": {name: g["pass"] for name, g in row["gates"][rec].items()},
            "gate_reasons": {name: g["reasons"] for name, g in row["gates"][rec].items()},
        }
    return out


def _ledger_append(
    ledger: Path,
    source: str,
    strategy: str,
    params: dict[str, Any],
    *,
    run_id: str,
    panel_digest: str,
    config_sha: str,
    code_sha: str,
    common: CommonSettings,
    scheme: str,
    seal: str,
    metrics: dict[str, Any] | None,
    test_range: list[str],
    extra_costs: dict[str, Any] | None = None,
) -> None:
    costs = {"quantile": common.quantile, "order_notional_usd": common.order_notional_usd}
    if extra_costs:
        costs.update(extra_costs)
    record = build_trial_record(
        source=source,
        strategy=strategy,
        strategy_params=params,
        run_id=run_id,
        dataset_sha=panel_digest,
        config_sha=config_sha,
        code_sha=code_sha,
        seed=common.bootstrap_seed,
        split_policy=scheme,
        preregistration_seal=seal,
        costs=costs,
        test_range=test_range,
        test_sharpe_per_period=None if metrics is None else float(metrics["sharpe_per_period"]),
        test_sharpe=None if metrics is None else float(metrics["sharpe"]),
        test_total_return=None if metrics is None else float(metrics["total_return"]),
        trade_count=None if metrics is None else int(metrics["executed_legs"]),
    )
    append_trial_record(None, record, registry_path=ledger)


__all__ = [
    "FROZEN_FILENAME",
    "LEDGER_FILENAME",
    "PANEL_VERIFICATION_FILENAME",
    "RECOVERIES",
    "RESULTS_FILENAME",
    "SELECTION_DIRNAME",
    "STRESS_RECOVERY",
    "CampaignError",
    "Evaluated",
    "Fold",
    "benchmark_weights",
    "bootstrap",
    "comparison",
    "cscv",
    "deflated_sharpes",
    "evaluate_span",
    "fold_windows",
    "freeze",
    "frozen_sha256",
    "gate_turnover",
    "generate_weights",
    "iso_days",
    "load_frozen",
    "load_gates",
    "load_panel",
    "performance",
    "record_panel_verification",
    "require_verified_panel",
    "run_select",
    "score",
    "selection_slice",
    "sharpe_range",
    "sharpe_standard_error",
    "span_slice",
    "walk_forward",
]
