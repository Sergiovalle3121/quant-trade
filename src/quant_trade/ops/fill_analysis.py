from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median, quantiles

from .reports import write_csv, write_json, write_md


@dataclass
class FillAnalysis:
    number_of_orders: int = 0
    number_of_fills: int = 0
    fill_rate: float = 0.0
    rejected_rate: float = 0.0
    partial_fill_count: int = 0
    average_slippage_bps: float = 0.0
    median_slippage_bps: float = 0.0
    p75_slippage_bps: float = 0.0
    max_slippage_bps: float = 0.0
    total_estimated_slippage_cost: float = 0.0
    total_commissions_or_fees: float = 0.0
    planned_notional: float = 0.0
    filled_notional: float = 0.0
    missing_fill_count: int = 0
    late_fill_count: int = 0
    unexpected_symbol_count: int = 0
    warnings: list[str] | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _float(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def analyze_fills(run_dir: Path) -> FillAnalysis:
    """Measure realized execution quality against planned prices.

    Slippage is ADVERSE-POSITIVE and side-signed: paying up on a buy and
    selling down on a sell are both positive slippage. Netting buys against
    sells (the old behavior) understated true transaction costs. Costs are
    aggregated in quote currency, and partial fills are counted by grouping
    every fill of an order instead of keeping only the last one.
    """
    orders = _read_csv(run_dir / "orders.csv")
    fills = _read_csv(run_dir / "fills.csv")
    fills_by_order: dict[str | None, list[dict[str, str]]] = defaultdict(list)
    for fill in fills:
        fills_by_order[fill.get("order_id") or fill.get("client_order_id")].append(fill)
    slippages: list[float] = []
    slippage_cost = 0.0
    fees = 0.0
    filled_notional = 0.0
    planned_notional = 0.0
    partial_fill_count = 0

    for order in orders:
        quantity = abs(_float(order.get("quantity") or order.get("qty")))
        side_sign = -1.0 if str(order.get("side", "buy")).lower() == "sell" else 1.0
        planned_price = _float(
            order.get("expected_price") or order.get("limit_price") or order.get("price")
        )
        planned_notional += quantity * planned_price
        order_fills = fills_by_order.get(
            order.get("order_id") or order.get("client_order_id"), []
        )
        if not order_fills:
            continue
        order_filled_qty = 0.0
        for fill in order_fills:
            fill_price = _float(fill.get("fill_price") or fill.get("price")) or planned_price
            fill_quantity = abs(_float(fill.get("quantity") or fill.get("qty"))) or quantity
            order_filled_qty += fill_quantity
            notional = fill_price * fill_quantity
            filled_notional += notional
            fees += _float(fill.get("commission") or fill.get("fees") or fill.get("cost"))
            if planned_price:
                adverse_bps = side_sign * (fill_price - planned_price) / planned_price * 10_000
                slippages.append(adverse_bps)
                slippage_cost += adverse_bps / 10_000 * notional
        if 0 < order_filled_qty < quantity - 1e-9:
            partial_fill_count += 1

    rejected = sum(1 for order in orders if order.get("status", "").lower() == "rejected")
    active_order_count = max(0, len(orders) - rejected)
    filled_orders = sum(1 for oid in fills_by_order if fills_by_order[oid])
    warnings = (
        []
        if fills
        else ["Actual broker fills unavailable; analyzing simulated/no-fill artifacts only."]
    )
    return FillAnalysis(
        number_of_orders=len(orders),
        number_of_fills=len(fills),
        fill_rate=filled_orders / len(orders) if orders else 0.0,
        rejected_rate=rejected / len(orders) if orders else 0.0,
        partial_fill_count=partial_fill_count,
        average_slippage_bps=mean(slippages) if slippages else 0.0,
        median_slippage_bps=median(slippages) if slippages else 0.0,
        p75_slippage_bps=(
            quantiles(slippages, n=4)[2] if len(slippages) >= 4 else max(slippages, default=0.0)
        ),
        max_slippage_bps=max([abs(item) for item in slippages], default=0.0),
        total_estimated_slippage_cost=slippage_cost,
        total_commissions_or_fees=fees,
        planned_notional=planned_notional,
        filled_notional=filled_notional,
        missing_fill_count=max(0, active_order_count - filled_orders),
        warnings=warnings,
    )


def calibrate_cost_model(analysis: FillAnalysis) -> dict[str, float | str]:
    """Suggest CostModel parameters from measured execution quality.

    Uses the 75th percentile of adverse slippage (conservative: worse than
    typical, better than worst-case) and the realized fee rate. This closes
    the loop the platform's cost realism depends on: research costs should
    trend toward measured fills, never toward optimism.
    """
    if analysis.filled_notional <= 0:
        return {
            "status": "insufficient_data",
            "detail": "no filled notional; run a session with real fills first",
        }
    fee_rate = analysis.total_commissions_or_fees / analysis.filled_notional
    suggested_slippage = max(0.0, analysis.p75_slippage_bps)
    return {
        "status": "ok",
        "suggested_percentage_commission": round(fee_rate, 6),
        "suggested_slippage_bps": round(suggested_slippage, 2),
        "observed_average_slippage_bps": round(analysis.average_slippage_bps, 2),
        "observed_p75_slippage_bps": round(analysis.p75_slippage_bps, 2),
        "observed_fill_rate": round(analysis.fill_rate, 4),
        "sample_orders": float(analysis.number_of_orders),
    }


def compare_planned_vs_filled(run_dir: Path) -> dict[str, object]:
    return asdict(analyze_fills(run_dir))


def generate_fill_report(analysis: FillAnalysis, out: Path) -> None:
    write_json(out / "fill_analysis.json", analysis)
    write_csv(out / "fill_analysis.csv", [asdict(analysis)])
    write_md(out / "fill_analysis.md", "Fill Analysis", {"analysis": analysis})
