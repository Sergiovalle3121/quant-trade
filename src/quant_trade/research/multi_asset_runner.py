from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from quant_trade.backtest.costs import CONSERVATIVE_COST_MODEL, CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.manifest import file_sha256
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.execution.bar_model import BarExecutionPolicy
from quant_trade.metrics.statistics import probabilistic_sharpe_ratio, return_moments
from quant_trade.reporting.artifacts import create_run_dir, write_csv, write_json, write_yaml
from quant_trade.reporting.research_report import generate_research_summary
from quant_trade.research.benchmarks import compare_to_benchmark, run_benchmark
from quant_trade.research.ledger import append_trial_record, build_trial_record, sha256_hex
from quant_trade.research.robustness import (
    bootstrap_summary,
    cost_sensitivity,
    rolling_metrics,
    subperiod_analysis,
)
from quant_trade.research.strategy_registry import get_research_signal_model


def load_multi_asset_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    cfg = yaml.safe_load(p.read_text()) or {}
    cfg.setdefault("experiment_name", p.stem)
    return cfg


def _cost(cfg: dict[str, Any]) -> CostModel:
    costs = cfg.get("costs")
    if costs is None:
        # A config without a costs block gets conservative defaults; zero
        # costs must be requested explicitly.
        return CONSERVATIVE_COST_MODEL
    return CostModel(**{k: float(v) for k, v in costs.items()})


def _execution_policy(cfg: dict[str, Any]) -> BarExecutionPolicy:
    return BarExecutionPolicy.from_mapping(cfg.get("execution"))


def _execution_summary(order_events: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    if order_events.empty:
        return {
            "orders_submitted": 0,
            "quantity_fill_rate": 0.0,
            "partial_or_expired_orders": 0,
            "partial_or_expired_order_rate": 0.0,
            "average_participation_rate": 0.0,
            "average_price_impact_bps": 0.0,
        }
    submitted = order_events[order_events["event_type"] == "submitted"]
    terminal = order_events.groupby("order_id", sort=False, as_index=False).tail(1)
    requested = float(submitted["requested_quantity"].sum())
    filled = float(trades["quantity"].sum()) if not trades.empty else 0.0
    return {
        "orders_submitted": int(len(submitted)),
        "quantity_fill_rate": filled / requested if requested > 0 else 0.0,
        "partial_or_expired_orders": int(
            terminal["status"].isin(["partially_filled", "expired", "cancelled"]).sum()
        ),
        "partial_or_expired_order_rate": float(
            terminal["status"].isin(["partially_filled", "expired", "cancelled"]).mean()
        ),
        "average_participation_rate": (
            float(trades["participation_rate"].mean()) if not trades.empty else 0.0
        ),
        "average_price_impact_bps": (
            float(trades["price_impact_bps"].mean()) if not trades.empty else 0.0
        ),
    }


def _load_overfitting_evidence(
    config: dict[str, Any],
    dataset_binding: dict[str, Any],
    strategy: str,
) -> dict[str, Any] | None:
    raw_path = config.get("overfitting_evidence_path")
    if raw_path is None:
        return None
    path = Path(str(raw_path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid overfitting evidence file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("overfitting evidence must be a JSON object")
    evidence_binding = payload.get("dataset_binding")
    if (
        not isinstance(evidence_binding, dict)
        or evidence_binding.get("data_sha256") != dataset_binding["data_sha256"]
    ):
        raise ValueError("overfitting evidence dataset hash does not match the research dataset")
    if payload.get("strategy") != strategy:
        raise ValueError("overfitting evidence strategy does not match the research strategy")
    return payload


def _split(
    data: pd.DataFrame, frac: float, embargo_bars: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split with an optional embargo.

    ``embargo_bars`` drops that many bars at the start of the test window so
    signals whose lookbacks straddle the boundary cannot leak train-period
    information into the out-of-sample evidence.
    """
    dates = sorted(data["timestamp"].unique())
    cut = max(1, min(len(dates) - 1, int(len(dates) * frac)))
    test_start = cut + max(0, int(embargo_bars))
    if test_start >= len(dates):
        raise ValueError("embargo_bars leaves no test data")
    return data[data.timestamp.isin(dates[:cut])].copy(), data[
        data.timestamp.isin(dates[test_start:])
    ].copy()


def run_multi_asset_research_experiment(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("mode") != "multi_asset_research":
        raise ValueError("config mode must be multi_asset_research")
    data_path = Path(config["data_path"])
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} not found. Run quant-trade data fetch ... first.")
    data = load_canonical_dataset(data_path)
    # Bind the run to the exact bytes it consumed so results are reproducible
    # and auditable against dataset versions.
    dataset_binding = {
        "data_path": str(data_path),
        "data_sha256": file_sha256(data_path),
        "rows": int(len(data)),
    }
    split_cfg = config.get("split", {})
    train, test = _split(
        data,
        float(split_cfg.get("train_fraction", 0.7)),
        int(split_cfg.get("embargo_bars", 0)),
    )
    strategy = str(config["strategy"])
    params = dict(config.get("strategy_params", {}))
    overfitting_evidence = _load_overfitting_evidence(config, dataset_binding, strategy)
    initial = float(config.get("initial_cash", 100000))
    cost = _cost(config)
    model = get_research_signal_model(strategy)
    # Registered signals are causal (weights at t depend only on bars <= t,
    # enforced by the truncation-invariance tests), so generating on the full
    # panel and slicing is leak-free AND restores the whole test window as
    # evidence. Generating from the test slice alone burned the entire signal
    # lookback inside the test window (a 126-bar lookback left a 96-bar test
    # window with ~0 live bars).
    w_all = model.generate(data, params)
    train_ts = set(train["timestamp"].unique())
    test_ts = set(test["timestamp"].unique())
    w_train = w_all[w_all["timestamp"].isin(train_ts)].copy()
    w_test = w_all[w_all["timestamp"].isin(test_ts)].copy()
    port = config.get("portfolio", {})
    max_weight = float(port.get("max_weight_per_asset", params.get("max_weight_per_asset", 1.0)))
    allow_leverage = bool(port.get("allow_leverage", False))
    allow_short = bool(port.get("allow_short", params.get("allow_short", False)))
    rebalance_band = float(port.get("rebalance_band", 0.0))
    execution_policy = _execution_policy(config)
    # The configured gross cap is APPLIED to the engine, not merely reported
    # (with leverage the engine fails closed rather than silently ignoring it).
    max_gross_cfg = port.get("max_gross_exposure")
    max_gross_arg = (
        float(max_gross_cfg) if max_gross_cfg is not None and not allow_leverage else None
    )
    r_train = run_multi_asset_backtest(
        train,
        w_train,
        initial,
        cost,
        max_weight_per_asset=max_weight,
        allow_leverage=allow_leverage,
        allow_short=allow_short,
        rebalance_band=rebalance_band,
        execution_policy=execution_policy,
        max_gross_exposure=max_gross_arg,
    )
    r_test = run_multi_asset_backtest(
        test,
        w_test,
        initial,
        cost,
        max_weight_per_asset=max_weight,
        allow_leverage=allow_leverage,
        allow_short=allow_short,
        rebalance_band=rebalance_band,
        execution_policy=execution_policy,
        max_gross_exposure=max_gross_arg,
    )
    bcfg = dict(config.get("benchmark", {"type": "equal_weight_universe"}))
    b_train = run_benchmark(
        train,
        bcfg,
        initial,
        cost,
        execution_policy=execution_policy,
    )
    b_test = run_benchmark(
        test,
        bcfg,
        initial,
        cost,
        execution_policy=execution_policy,
    )
    c_train = compare_to_benchmark(
        r_train.metrics, b_train.metrics, r_train.equity_curve, b_train.equity_curve
    )
    c_test = compare_to_benchmark(
        r_test.metrics, b_test.metrics, r_test.equity_curve, b_test.equity_curve
    )
    run_id = time.strftime("%Y%m%d_%H%M%S")
    out = create_run_dir(
        config.get("output_dir", "outputs"), f"{config['experiment_name']}_{run_id}"
    )
    write_yaml(out / "config_used.yaml", {**config, "dataset_binding": dataset_binding})
    write_json(out / "metrics_train.json", r_train.metrics)
    write_json(out / "metrics_test.json", r_test.metrics)
    write_json(out / "benchmark_train.json", b_train.metrics)
    write_json(out / "benchmark_test.json", b_test.metrics)
    write_json(out / "comparison_train.json", c_train)
    write_json(out / "comparison_test.json", c_test)
    write_csv(out / "equity_curve_train.csv", r_train.equity_curve)
    write_csv(out / "equity_curve_test.csv", r_test.equity_curve)
    write_csv(out / "positions_test.csv", r_test.positions)
    write_csv(out / "trades_test.csv", r_test.trades)
    write_csv(out / "order_events_train.csv", r_train.order_events)
    write_csv(out / "order_events_test.csv", r_test.order_events)
    write_csv(out / "target_weights_test.csv", w_test)
    rob = config.get("robustness", {})
    files = []
    robustness_flags: dict[str, Any] = {}
    if rob.get("run_cost_sensitivity", False):
        cs = cost_sensitivity(
            test,
            strategy,
            params,
            initial,
            execution_policy=execution_policy,
        )
        write_csv(out / "cost_sensitivity.csv", cs)
        files.append("cost_sensitivity.csv")
        high = cs[cs["cost_level"] == "high"] if "cost_level" in cs.columns else cs.iloc[0:0]
        # Pass = still profitable at the highest cost assumption.
        robustness_flags["cost_sensitivity_pass"] = bool(
            not high.empty and float(high.iloc[0].get("total_return", 0.0)) > 0.0
        )
    if rob.get("run_subperiod_analysis", False):
        sp = subperiod_analysis(r_test.equity_curve)
        write_csv(out / "subperiod_analysis.csv", sp)
        files.append("subperiod_analysis.csv")
        # Pass = at least half the calendar years are positive.
        robustness_flags["subperiod_pass"] = bool(
            not sp.empty and float((sp["return"] > 0).mean()) >= 0.5
        )
    if rob.get("run_rolling_metrics", False):
        rm = rolling_metrics(r_test.equity_curve)
        write_csv(out / "rolling_metrics.csv", rm)
        files.append("rolling_metrics.csv")
    test_returns = r_test.equity_curve["equity"].astype(float).pct_change().dropna()
    moments = return_moments(test_returns)
    psr = probabilistic_sharpe_ratio(test_returns)
    # Block-bootstrap confidence interval on the OOS returns. Serial dependence
    # is preserved (stationary bootstrap), so the band is honest for
    # autocorrelated equity curves. Recorded as promotable evidence.
    bcfg_boot = rob.get("bootstrap", {}) if isinstance(rob.get("bootstrap", {}), dict) else {}
    bootstrap_ci = bootstrap_summary(
        test_returns,
        method=str(bcfg_boot.get("method", "stationary")),
        samples=int(bcfg_boot.get("samples", 2000)),
        block_size=int(bcfg_boot.get("block_size", 20)),
        seed=int(bcfg_boot.get("seed", 12345)),
    )
    execution_test = _execution_summary(r_test.order_events, r_test.trades)
    # Stamp the exact execution policy (and its hash) that produced BOTH the
    # strategy and benchmark numbers into results.json. A run whose config omits
    # an execution policy is marked specified=False so promotion can refuse to
    # treat unlimited-fill evidence as promotable (Phase 4 parity requirement).
    execution_policy_specified = config.get("execution") is not None
    execution_policy_hash = sha256_hex(config.get("execution") or {})
    execution_policy_block = {
        "specified": bool(execution_policy_specified),
        "hash": execution_policy_hash,
        "params": asdict(execution_policy),
        "applied_to_benchmark": True,
    }
    results_payload = {
        "experiment_name": config["experiment_name"],
        "strategy": strategy,
        "strategy_params": params,
        "symbols": sorted(data.symbol.unique()),
        "initial_cash": initial,
        "benchmark": str(bcfg.get("type", "equal_weight_universe")),
        "max_gross_exposure": float(port.get("max_gross_exposure", 1.0)),
        "train_metrics": r_train.metrics,
        "test_metrics": {
            **r_test.metrics,
            "turnover": float(r_test.metrics.get("total_turnover", 0.0)),
            "trade_count": int(len(r_test.trades)),
            "psr": psr,
            **moments,
        },
        "comparison_test": c_test,
        "train_range": [str(train.timestamp.min()), str(train.timestamp.max())],
        "test_range": [str(test.timestamp.min()), str(test.timestamp.max())],
        "robustness": robustness_flags,
        "bootstrap": bootstrap_ci,
        "dataset_binding": dataset_binding,
        "execution_test": execution_test,
        "execution_policy": execution_policy_block,
        "overfitting_evidence": overfitting_evidence,
    }
    write_json(out / "results.json", results_payload)
    split_policy = (
        f"chronological_timestamp:train_fraction={split_cfg.get('train_fraction', 0.7)},"
        f"embargo_bars={split_cfg.get('embargo_bars', 0)}"
    )
    append_trial_record(
        config.get("output_dir", "outputs"),
        build_trial_record(
            source="multi_asset_research",
            strategy=strategy,
            strategy_params=params,
            run_id=run_id,
            status="evaluated",
            dataset_sha=str(dataset_binding["data_sha256"]),
            config_sha=sha256_hex(config),
            seed=int(bcfg_boot.get("seed", 12345)),
            split_policy=split_policy,
            feature_version=str(config.get("feature_version", "v1")),
            execution_policy_hash=execution_policy_hash,
            costs=config.get("costs") or {"preset": "conservative_default"},
            train_range=[str(train.timestamp.min()), str(train.timestamp.max())],
            test_range=[str(test.timestamp.min()), str(test.timestamp.max())],
            test_sharpe_per_period=moments["sharpe_per_period"],
            test_sharpe=float(r_test.metrics.get("sharpe", 0.0)),
            test_total_return=float(r_test.metrics.get("total_return", 0.0)),
            trade_count=int(len(r_test.trades)),
        ),
    )
    generate_research_summary(
        out / "summary.md",
        experiment_name=config["experiment_name"],
        dataset_info={
            "symbols": sorted(data.symbol.unique()),
            "rows": len(data),
            "start": str(data.timestamp.min()),
            "end": str(data.timestamp.max()),
            "data_sha256": dataset_binding["data_sha256"],
        },
        strategy=strategy,
        strategy_params=params,
        benchmark=bcfg,
        train_metrics=r_train.metrics,
        test_metrics=r_test.metrics,
        comparison=c_test,
        robustness_files=files,
    )
    return {
        "output_dir": str(out),
        "train_metrics": r_train.metrics,
        "test_metrics": r_test.metrics,
        "comparison_test": c_test,
        "symbols": sorted(data.symbol.unique()),
        "train_range": [str(train.timestamp.min()), str(train.timestamp.max())],
        "test_range": [str(test.timestamp.min()), str(test.timestamp.max())],
        "dataset_binding": dataset_binding,
        "execution_test": execution_test,
        "overfitting_evidence": overfitting_evidence,
    }
