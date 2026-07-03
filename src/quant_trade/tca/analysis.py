"""Offline execution quality and transaction cost analysis."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pandas as pd
import yaml

from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.tca.config import load_tca_policy
from quant_trade.tca.execution_models import execution_price_for_row
from quant_trade.tca.models import FillQualityMetrics, OrderExecutionAnalysis
from quant_trade.tca.partial_fills import simulate_partial_fills
from quant_trade.tca.slippage import calculate_implementation_shortfall, calculate_slippage_bps
from quant_trade.tca.spread import estimate_bid_ask_spread_proxy

LIMITATIONS = [
    "OHLCV-only execution analysis uses proxy prices and cannot validate queue position, "
    "venue liquidity, or realistic fills.",
    "This lab is research/backtesting-only and never indicates real-money readiness.",
]


def _fallback_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["SYNTH"] * 5,
            "open": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "volume": [1000, 900, 800, 700, 600],
        }
    )


def _synthetic_orders(frame: pd.DataFrame) -> list[dict[str, object]]:
    orders = []
    for i, (_, row) in enumerate(frame.head(5).iterrows(), start=1):
        orders.append(
            {
                "order_id": f"order_{i}",
                "symbol": str(row.get("symbol", "SYNTH")),
                "side": "buy",
                "quantity": 10.0,
            }
        )
    return orders


def analyze_orders(
    config_path: Path,
) -> tuple[list[OrderExecutionAnalysis], FillQualityMetrics, dict[str, object]]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    policy_path = Path(cfg.get("policy_path", "configs/tca/tca_policy_conservative.yaml"))
    policy = load_tca_policy(policy_path)
    data_value = str(cfg.get("data_path", ""))
    data_path = Path(data_value) if data_value else None
    if data_path is not None and data_path.is_file():
        frame = load_ohlcv_csv(data_path)
    else:
        frame = _fallback_frame()
    frame = frame.reset_index(drop=True)
    spreads = estimate_bid_ask_spread_proxy(frame, floor_bps=policy.execution.spread_bps)
    rows: list[OrderExecutionAnalysis] = []
    for idx, order in enumerate(_synthetic_orders(frame)):
        bar = frame.iloc[min(idx, len(frame) - 1)]
        side = str(order["side"])
        qty = float(cast(Any, order["quantity"]))
        partial = simulate_partial_fills(
            qty, float(cast(Any, bar["volume"])), policy.execution.max_participation_rate
        )
        arrival = float(cast(Any, bar["open"]))
        decision = float(cast(Any, bar["close"]))
        spread_bps = float(spreads.iloc[min(idx, len(spreads) - 1)])
        execution = execution_price_for_row(
            bar,
            policy.execution.model,
            side,
            spread_bps + policy.execution.slippage_bps,
        )
        slippage = calculate_slippage_bps(arrival, execution, side)
        shortfall = calculate_implementation_shortfall(
            decision, execution, partial.filled_quantity, side
        )
        traded_value = abs(partial.filled_quantity * execution)
        total_cost = shortfall + traded_value * spread_bps / 10000.0
        rows.append(
            OrderExecutionAnalysis(
                str(order["order_id"]),
                str(order["symbol"]),
                side,
                qty,
                partial.filled_quantity,
                arrival,
                decision,
                execution,
                shortfall,
                slippage,
                spread_bps,
                calculate_slippage_bps(decision, arrival, side),
                max(0.0, slippage - spread_bps),
                total_cost,
                partial.status,
                partial.fill_rate,
                slippage - policy.research_assumed_cost_bps,
            )
        )
    metrics = summarize(rows, policy.default_equity)
    metadata = {
        "policy": policy.name,
        "limitations": LIMITATIONS,
        "real_money_ready": False,
    }
    return rows, metrics, metadata


def summarize(rows: list[OrderExecutionAnalysis], equity: float) -> FillQualityMetrics:
    if not rows:
        return FillQualityMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False)
    total_cost = sum(r.total_cost for r in rows)
    turnover = sum(abs(r.filled_quantity * r.execution_price) for r in rows)
    return FillQualityMetrics(
        len(rows),
        sum(r.fill_rate for r in rows) / len(rows),
        sum(1 for r in rows if r.status == "partial") / len(rows),
        sum(1 for r in rows if r.status == "rejected") / len(rows),
        sum(r.slippage_bps for r in rows) / len(rows),
        total_cost,
        total_cost / equity * 100.0 if equity else 0.0,
        total_cost / turnover if turnover else 0.0,
        False,
    )


def compare_research_vs_paper_execution(
    rows: list[OrderExecutionAnalysis], research_assumed_cost_bps: float = 10.0
) -> dict[str, object]:
    actual = 0.0 if not rows else sum(r.slippage_bps + r.spread_cost_bps for r in rows) / len(rows)
    return {
        "research_assumed_cost_bps": research_assumed_cost_bps,
        "actual_cost_bps": actual,
        "cost_delta_bps": actual - research_assumed_cost_bps,
        "quality_reduced_by_costs": actual > research_assumed_cost_bps,
        "real_money_ready": False,
    }


def write_artifacts(config_path: Path) -> Path:
    rows, metrics, metadata = analyze_orders(config_path)
    run_id = uuid4().hex[:12]
    out = Path("outputs/tca") / run_id
    (out / "dashboard").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, out / "tca_config_used.yaml")
    fieldnames = list(rows[0].to_dict()) if rows else list(OrderExecutionAnalysis.__annotations__)
    with (out / "order_execution_analysis.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([r.to_dict() for r in rows])
    metrics_json = json.dumps(metrics.to_dict(), indent=2)
    (out / "fill_quality_metrics.json").write_text(metrics_json, encoding="utf-8")
    pd.DataFrame(
        [{"average_slippage_bps": metrics.average_slippage_bps, "total_cost": metrics.total_cost}]
    ).to_csv(out / "slippage_summary.csv", index=False)
    comparison = compare_research_vs_paper_execution(rows)
    (out / "cost_comparison.json").write_text(
        json.dumps(comparison, indent=2), encoding="utf-8"
    )
    summary = generate_tca_report(metrics, comparison, metadata)
    (out / "tca_summary.md").write_text(summary, encoding="utf-8")
    html = (
        "<html><body><h1>TCA Dashboard</h1><p>real_money_ready=false</p>"
        f"<p>Average slippage: {metrics.average_slippage_bps:.2f} bps</p></body></html>"
    )
    (out / "dashboard" / "index.html").write_text(html, encoding="utf-8")
    return out


def generate_tca_report(
    metrics: FillQualityMetrics, comparison: dict[str, object], metadata: dict[str, object]
) -> str:
    return f"""# Transaction Cost Analysis Summary

Paper-only research artifact. `real_money_ready=false`.

## Metrics
- Orders: {metrics.order_count}
- Fill rate: {metrics.fill_rate:.2%}
- Partial fill rate: {metrics.partial_fill_rate:.2%}
- Rejected rate: {metrics.rejected_rate:.2%}
- Average slippage bps: {metrics.average_slippage_bps:.2f}
- Total cost: {metrics.total_cost:.2f}

## Research comparison
- Cost delta bps: {comparison["cost_delta_bps"]:.2f}

## Limitations
- {cast(list[str], metadata["limitations"])[0]}
- {cast(list[str], metadata["limitations"])[1]}
"""
