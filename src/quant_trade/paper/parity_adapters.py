"""Build parity ExecutionRecords from real engine outputs.

Turns a multi-asset backtest result (and, by the same shape, a paper run's
trade/position frames) into the normalised :class:`ExecutionRecord` the parity
report consumes — so parity runs on real runs, not just hand-built fixtures.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.paper.parity import ExecutionRecord


def _signed(row: pd.Series) -> float:
    qty = float(row.get("quantity", 0.0))
    return -qty if str(row.get("side", "buy")).lower() == "sell" else qty


def execution_record_from_frames(
    *,
    source: str,
    trades: pd.DataFrame,
    positions: pd.DataFrame,
    equity_curve: pd.DataFrame,
    order_events: pd.DataFrame | None = None,
    target_weights: dict[str, float] | None = None,
) -> ExecutionRecord:
    """Normalise standard engine frames into an ExecutionRecord.

    Works for any engine emitting the canonical columns: trades
    (symbol/side/quantity/price/cost/price_impact_bps), positions
    (timestamp/symbol/quantity), and equity_curve (timestamp/equity/cash).
    """
    fills: list[dict[str, Any]] = []
    order_quantities: dict[str, float] = {}
    for _, row in trades.iterrows():
        signed = _signed(row)
        symbol = str(row["symbol"])
        fills.append(
            {
                "symbol": symbol,
                "quantity": signed,
                "price": float(row.get("price", 0.0)),
                "timestamp": str(row.get("timestamp", "")),
                "fee": float(row.get("cost", 0.0)),
                "slippage_bps": float(row.get("price_impact_bps", 0.0)),
            }
        )
        order_quantities[symbol] = order_quantities.get(symbol, 0.0) + signed

    final_positions: dict[str, float] = {}
    if not positions.empty:
        last_ts = positions["timestamp"].max()
        for _, row in positions[positions["timestamp"] == last_ts].iterrows():
            final_positions[str(row["symbol"])] = float(row["quantity"])

    final_cash = 0.0
    final_equity = 0.0
    if not equity_curve.empty:
        last = equity_curve.iloc[-1]
        final_cash = float(last.get("cash", 0.0))
        final_equity = float(last.get("equity", 0.0))

    partial_fills = 0
    cancellations = 0
    if order_events is not None and not order_events.empty and "status" in order_events.columns:
        terminal = order_events.groupby("order_id", sort=False, as_index=False).tail(1)
        partial_fills = int((terminal["status"] == "partially_filled").sum())
        cancellations = int(terminal["status"].isin(["cancelled", "expired"]).sum())

    return ExecutionRecord(
        source=source,
        target_weights=dict(target_weights or {}),
        order_quantities=order_quantities,
        fills=fills,
        cancellations=cancellations,
        partial_fills=partial_fills,
        final_positions=final_positions,
        final_cash=final_cash,
        final_equity=final_equity,
    )


def execution_record_from_backtest(
    result: Any, *, source: str = "backtest", target_weights: dict[str, float] | None = None
) -> ExecutionRecord:
    """Adapter for a MultiAssetBacktestResult (duck-typed on its frames)."""
    return execution_record_from_frames(
        source=source,
        trades=result.trades,
        positions=result.positions,
        equity_curve=result.equity_curve,
        order_events=getattr(result, "order_events", None),
        target_weights=target_weights,
    )
