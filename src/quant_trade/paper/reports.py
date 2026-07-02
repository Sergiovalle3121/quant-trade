from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_trade.paper.models import PaperSessionState, PaperTradingConfig


def paper_metrics(
    state: PaperSessionState,
    orders: list[dict],
    fills: list[dict],
    snapshots: list[dict],
    risk_events: list[dict],
) -> dict[str, float | int | bool]:
    initial = snapshots[0]["equity"] if snapshots else state.high_water_mark
    total_costs = sum(float(f.get("cost", 0.0)) for f in fills)
    return {
        "total_return": (state.equity / initial - 1) if initial else 0.0,
        "max_drawdown": state.max_drawdown,
        "realized_pnl": state.realized_pnl,
        "unrealized_pnl": state.unrealized_pnl,
        "total_costs": total_costs,
        "number_of_orders": len(orders),
        "number_of_fills": len(fills),
        "rejected_orders": sum(1 for o in orders if o.get("status") == "rejected"),
        "average_daily_turnover": 0.0,
        "max_gross_exposure": max((s.get("gross_exposure", 0.0) for s in snapshots), default=0.0),
        "max_single_position_weight": 0.0,
        "days_active": len(snapshots),
        "kill_switch_triggered": state.kill_switch_active,
    }


def write_report(
    out: Path,
    config: PaperTradingConfig,
    state: PaperSessionState,
    orders: list[dict],
    fills: list[dict],
    snapshots: list[dict],
    risk_events: list[dict],
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    metrics = paper_metrics(state, orders, fills, snapshots, risk_events)
    (out / "paper_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    initial_equity = snapshots[0]["equity"] if snapshots else config.initial_cash
    summary = (
        "# Simulated paper trading summary\n\n"
        "**Safety warning:** simulated only; no broker integration and no real orders.\n\n"
        f"Session: {config.paper_session_name}\n\n"
        f"Strategy: {config.strategy}\n\n"
        f"Universe: {', '.join(config.universe.get('symbols', []))}\n\n"
        f"Initial equity: {initial_equity:.2f}\n\n"
        f"Final equity: {state.equity:.2f}\n\n"
        f"Total return: {metrics['total_return']:.2%}\n\n"
        f"Max drawdown: {metrics['max_drawdown']:.2%}\n\n"
        f"Orders: {len(orders)}\n\n"
        f"Fills: {len(fills)}\n\n"
        f"Costs paid: {metrics['total_costs']:.2f}\n\n"
        f"Kill switch active: {state.kill_switch_active}\n\n"
        "Next recommended action: review audit logs and risk events before any further "
        "paper-broker planning.\n"
    )
    (out / "paper_summary.md").write_text(summary, encoding="utf-8")
    return metrics


def write_csvs(
    out: Path,
    snapshots: list[dict],
    orders: list[dict],
    fills: list[dict],
    positions: list[dict],
    events: list[dict],
    risk_events: list[dict],
) -> None:
    for name, rows in {
        "account_snapshots.csv": snapshots,
        "orders.csv": orders,
        "fills.csv": fills,
        "positions.csv": positions,
        "events.csv": events,
        "risk_events.csv": risk_events,
    }.items():
        pd.DataFrame(rows).to_csv(out / name, index=False)
