"""Cash-and-carry research campaign: causal backtest + honest verdict.

Builds a causal net-funding return series from read-only snapshots (the position
at ``t`` uses only funding known at ``t``), computes bootstrap and purged
walk-forward evidence, records a trial-ledger entry, and emits a
GO / NO-GO / NOT-RUN verdict.

Hard rule: **synthetic data can never produce GO.** A synthetic campaign always
returns ``NOT-RUN — REAL DATA REQUIRED`` regardless of how good the paper numbers
look, so an optimistic simulation is never mistaken for demonstrated carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from quant_trade.carry.data import (
    load_snapshots_from_json,
    synthetic_funding_snapshots,
)
from quant_trade.carry.economics import _round_trip_friction, evaluate_carry
from quant_trade.carry.models import (
    CarryCostModel,
    CarryPolicy,
    CarryPosition,
    CarrySnapshot,
)
from quant_trade.metrics.statistics import return_moments
from quant_trade.research.bootstrap import bootstrap_confidence_intervals
from quant_trade.research.ledger import append_trial_record, build_trial_record, sha256_hex
from quant_trade.research.splits import purged_walk_forward_splits


@dataclass
class CarryCampaignResult:
    decision: str  # "GO" | "NO-GO" | "NOT-RUN"
    reasons: list[str]
    data_source: str
    net_return_series: pd.DataFrame
    metrics: dict[str, Any]
    bootstrap: dict[str, Any]
    walk_forward: list[dict[str, Any]]
    per_snapshot_go_fraction: float


def carry_campaign_returns(
    snapshots: list[CarrySnapshot],
    costs: CarryCostModel,
    *,
    entry_threshold: float,
    trailing_window: int,
) -> pd.DataFrame:
    """Causal per-interval net-carry returns.

    Position at ``t`` is decided from the trailing mean of realized funding up to
    ``t`` (never future funding); it earns the *next* interval's realized funding
    minus per-turn transaction cost and per-interval carry cost.
    """
    ordered = sorted(snapshots, key=lambda s: s.captured_at_utc)
    funding = [s.realized_funding_rate for s in ordered]
    round_trip = _round_trip_friction(ordered[0], costs) if ordered else 0.0
    turn_cost = round_trip / 2.0  # entering or exiting is half a round trip
    intervals_per_year = ordered[0].funding_intervals_per_year if ordered else 1.0
    annual_carry_cost = costs.spot_custody_cost_annual + costs.perp_margin_cost_annual
    per_interval_carry_cost = annual_carry_cost / intervals_per_year

    rows: list[dict[str, Any]] = []
    prev_position = 0.0
    for i in range(len(ordered)):
        if i < trailing_window:
            position = 0.0  # warm-up: no causal signal yet
        else:
            trailing_mean = sum(funding[i - trailing_window : i]) / trailing_window
            position = 1.0 if trailing_mean > entry_threshold else 0.0
        earned = prev_position * funding[i]
        turn = abs(position - prev_position) * turn_cost
        carry = position * per_interval_carry_cost
        rows.append(
            {
                "timestamp": pd.to_datetime(ordered[i].captured_at_utc, utc=True, errors="coerce"),
                "symbol": ordered[i].symbol,
                "funding": funding[i],
                "position": position,
                "net_return": earned - turn - carry,
            }
        )
        prev_position = position
    return pd.DataFrame(rows)


def _load_snapshots(config: dict[str, Any]) -> list[CarrySnapshot]:
    data_cfg = config.get("data", {})
    source = str(data_cfg.get("source", "synthetic"))
    if source == "synthetic":
        return synthetic_funding_snapshots(**data_cfg.get("synthetic", {}))
    if source == "json":
        return load_snapshots_from_json(data_cfg["path"])
    raise ValueError(f"unsupported carry data source {source!r}; use 'synthetic' or 'json'")


def run_carry_research(config: dict[str, Any]) -> CarryCampaignResult:
    """Run a pre-registered carry campaign and return the verdict + evidence."""
    snapshots = _load_snapshots(config)
    if not snapshots:
        raise ValueError("no snapshots to evaluate")
    data_source = snapshots[0].data_source
    costs = CarryCostModel(**config.get("costs", {}))
    policy = CarryPolicy(**config.get("policy", {}))
    position = CarryPosition(
        **config.get("position", {"notional_usd": 100_000, "holding_days": 30})
    )
    signal_cfg = config.get("signal", {})
    entry_threshold = float(signal_cfg.get("entry_threshold", 0.0001))
    trailing_window = int(signal_cfg.get("trailing_window", 6))

    returns = carry_campaign_returns(
        snapshots, costs, entry_threshold=entry_threshold, trailing_window=trailing_window
    )
    net = returns["net_return"].astype(float)
    active = net[returns["position"].shift(fill_value=0.0) > 0]
    moments = return_moments(net)
    total_return = float((1.0 + net).prod() - 1.0)

    # per-snapshot economic GO fraction (diagnostic, not the campaign verdict)
    go = [evaluate_carry(s, position, costs, policy).decision == "GO" for s in snapshots]
    go_fraction = float(sum(go) / len(go)) if go else 0.0

    # bootstrap CI on the net return series (fail-closed on thin samples)
    bootstrap: dict[str, Any]
    if len(net.dropna()) >= 2:
        ci = bootstrap_confidence_intervals(
            net.dropna(), method="stationary", samples=1000, seed=12345, block_size=10
        )
        bootstrap = {
            "available": True,
            "method": "stationary",
            "total_return": {
                "lower": float(ci.loc["total_return", "p2.5"]),
                "upper": float(ci.loc["total_return", "p97.5"]),
            },
            "total_return_lower_positive": bool(ci.loc["total_return", "p2.5"] > 0),
        }
    else:
        bootstrap = {"available": False, "reason": "insufficient observations"}

    # purged walk-forward over timestamps
    walk_forward: list[dict[str, Any]] = []
    wf_cfg = config.get("walk_forward", {"train_size": 30, "test_size": 15, "step_size": 15})
    try:
        splits = purged_walk_forward_splits(
            returns.dropna(subset=["timestamp"]),
            train_size=int(wf_cfg["train_size"]),
            test_size=int(wf_cfg["test_size"]),
            step_size=int(wf_cfg["step_size"]),
            purge_bars=int(wf_cfg.get("purge_bars", trailing_window)),
            embargo_bars=int(wf_cfg.get("embargo_bars", 1)),
        )
        for split in splits:
            test_ret = split.test["net_return"].astype(float)
            walk_forward.append(
                {
                    "test_start": str(split.test_range[0]) if split.test_range else None,
                    "test_end": str(split.test_range[1]) if split.test_range else None,
                    "test_total_return": float((1.0 + test_ret).prod() - 1.0),
                    "test_sharpe_per_period": return_moments(test_ret)["sharpe_per_period"],
                }
            )
    except ValueError:
        walk_forward = []

    metrics = {
        "total_return": total_return,
        "active_intervals": int(len(active)),
        **moments,
        "go_fraction": go_fraction,
    }

    # --- verdict -----------------------------------------------------------
    reasons: list[str] = []
    if data_source == "synthetic":
        decision = "NOT-RUN"
        reasons.append("synthetic data cannot demonstrate carry; real funding data required")
    else:
        gate_reasons: list[str] = []
        if total_return <= 0:
            gate_reasons.append("campaign net carry is not positive")
        if not bootstrap.get("total_return_lower_positive"):
            gate_reasons.append("bootstrap lower bound on total return is not positive")
        if go_fraction <= 0:
            gate_reasons.append("no snapshot passed the per-snapshot economic gate")
        decision = "GO" if not gate_reasons else "NO-GO"
        reasons = gate_reasons

    return CarryCampaignResult(
        decision=decision,
        reasons=reasons,
        data_source=data_source,
        net_return_series=returns,
        metrics=metrics,
        bootstrap=bootstrap,
        walk_forward=walk_forward,
        per_snapshot_go_fraction=go_fraction,
    )


def write_carry_artifacts(
    output_dir: str | Path, config: dict[str, Any], result: CarryCampaignResult
) -> Path:
    """Persist results.json-style artifacts and a trial-ledger entry."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results_payload = {
        "experiment_name": config.get("experiment_name", "cash_and_carry"),
        "strategy": "cash_and_carry_funding",
        "data_source": result.data_source,
        "decision": result.decision,
        "reasons": result.reasons,
        "test_metrics": result.metrics,
        "bootstrap": result.bootstrap,
        "walk_forward": result.walk_forward,
        "benchmark": {"type": "flat_cash", "annual_return": 0.0},
        "comparison_test": {"excess_return": result.metrics["total_return"]},
    }
    (out / "results.json").write_text(
        yaml.safe_dump(results_payload, sort_keys=False), encoding="utf-8"
    )
    result.net_return_series.to_csv(out / "net_returns.csv", index=False)
    append_trial_record(
        out,
        build_trial_record(
            source="cash_and_carry_research",
            strategy="cash_and_carry_funding",
            strategy_params=config.get("signal", {}),
            run_id=str(config.get("experiment_name", "carry")),
            status="evaluated" if result.decision != "NOT-RUN" else "discarded",
            dataset_sha=sha256_hex(config.get("data", {})),
            config_sha=sha256_hex(config),
            split_policy="purged_walk_forward",
            feature_version="carry_v1",
            test_sharpe_per_period=result.metrics.get("sharpe_per_period"),
            test_total_return=result.metrics.get("total_return"),
            error=None if result.decision != "NOT-RUN" else "synthetic data; NOT-RUN",
        ),
    )
    return out / "results.json"
