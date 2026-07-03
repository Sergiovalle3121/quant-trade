from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median

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
    orders = _read_csv(run_dir / "orders.csv")
    fills = _read_csv(run_dir / "fills.csv")
    fills_by_order = {fill.get("order_id") or fill.get("client_order_id"): fill for fill in fills}
    slippages: list[float] = []
    fees = 0.0
    filled_notional = 0.0
    planned_notional = 0.0

    for order in orders:
        quantity = abs(_float(order.get("quantity") or order.get("qty")))
        planned_price = _float(
            order.get("expected_price") or order.get("limit_price") or order.get("price")
        )
        planned_notional += quantity * planned_price
        fill = fills_by_order.get(order.get("order_id") or order.get("client_order_id"))
        if fill is None:
            continue
        fill_price = _float(fill.get("fill_price") or fill.get("price")) or planned_price
        fill_quantity = abs(_float(fill.get("quantity") or fill.get("qty"))) or quantity
        filled_notional += fill_price * fill_quantity
        fees += _float(fill.get("commission") or fill.get("fees"))
        if planned_price:
            slippages.append((fill_price - planned_price) / planned_price * 10_000)

    rejected = sum(1 for order in orders if order.get("status", "").lower() == "rejected")
    active_order_count = max(0, len(orders) - rejected)
    warnings = (
        []
        if fills
        else ["Actual broker fills unavailable; analyzing simulated/no-fill artifacts only."]
    )
    return FillAnalysis(
        number_of_orders=len(orders),
        number_of_fills=len(fills),
        fill_rate=len(fills) / len(orders) if orders else 0.0,
        rejected_rate=rejected / len(orders) if orders else 0.0,
        average_slippage_bps=mean(slippages) if slippages else 0.0,
        median_slippage_bps=median(slippages) if slippages else 0.0,
        max_slippage_bps=max([abs(item) for item in slippages], default=0.0),
        total_estimated_slippage_cost=sum(slippages) if slippages else 0.0,
        total_commissions_or_fees=fees,
        planned_notional=planned_notional,
        filled_notional=filled_notional,
        missing_fill_count=max(0, active_order_count - len(fills)),
        warnings=warnings,
    )


def compare_planned_vs_filled(run_dir: Path) -> dict[str, object]:
    return asdict(analyze_fills(run_dir))


def generate_fill_report(analysis: FillAnalysis, out: Path) -> None:
    write_json(out / "fill_analysis.json", analysis)
    write_csv(out / "fill_analysis.csv", [asdict(analysis)])
    write_md(out / "fill_analysis.md", "Fill Analysis", {"analysis": analysis})
