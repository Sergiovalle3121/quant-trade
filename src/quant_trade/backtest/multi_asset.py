from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.backtest.costs import CONSERVATIVE_COST_MODEL, CostModel
from quant_trade.data.panel import pivot_close, pivot_open, validate_panel_schema
from quant_trade.execution.bar_model import (
    BarExecutionPolicy,
    BarOrderState,
    ExecutionStatus,
    cancel_order,
    execute_market_order_on_bar,
)
from quant_trade.metrics.performance import periods_per_year

TRADING_DAYS = 252


@dataclass(frozen=True)
class MultiAssetBacktestResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, Any]
    order_events: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass(frozen=True)
class _TargetIntent:
    weights: dict[str, float]
    decided_bar_index: int
    eligible_bar_index: int
    decided_at: Any


def _split_order(current: float, target: float) -> tuple[float, float]:
    """Return (exposure-reducing quantity, exposure-increasing quantity)."""
    if current >= 0 and target >= 0:
        delta = target - current
        return (delta, 0.0) if delta < 0 else (0.0, delta)
    if current <= 0 and target <= 0:
        delta = target - current
        return (delta, 0.0) if delta > 0 else (0.0, delta)
    if current > 0 > target:
        return -current, target
    if current < 0 < target:
        return -current, target
    return 0.0, target


def _scaled_quantity(quantity: float, scale: float, fractional_shares: bool) -> float:
    scaled = quantity * scale
    return scaled if fractional_shares else float(math.trunc(scaled))


def _simulate_orders(
    cash: float,
    quantities: dict[str, float],
    orders: list[tuple[str, float, float]],
    scale: float,
    prices: pd.Series,
    cost_model: CostModel,
    fractional_shares: bool,
) -> tuple[float, dict[str, float], float, float]:
    simulated_cash = cash
    simulated_qty = quantities.copy()
    for symbol, quantity, price in orders:
        executed = _scaled_quantity(quantity, scale, fractional_shares)
        if abs(executed) < 1e-12:
            continue
        notional = abs(executed * price)
        simulated_cash -= executed * price + cost_model.trade_cost(notional)
        simulated_qty[symbol] += executed
    equity = simulated_cash + sum(
        simulated_qty[symbol] * float(prices[symbol])
        for symbol in simulated_qty
        if pd.notna(prices.get(symbol))
    )
    gross_value = sum(
        abs(simulated_qty[symbol] * float(prices[symbol]))
        for symbol in simulated_qty
        if pd.notna(prices.get(symbol))
    )
    return simulated_cash, simulated_qty, equity, gross_value


def _maximum_feasible_scale(
    cash: float,
    quantities: dict[str, float],
    orders: list[tuple[str, float, float]],
    prices: pd.Series,
    cost_model: CostModel,
    fractional_shares: bool,
    max_gross: float,
) -> float:
    if not orders:
        return 0.0

    def feasible(scale: float) -> bool:
        simulated_cash, _, equity, gross_value = _simulate_orders(
            cash,
            quantities,
            orders,
            scale,
            prices,
            cost_model,
            fractional_shares,
        )
        return (
            math.isfinite(simulated_cash)
            and simulated_cash >= -1e-9
            and math.isfinite(equity)
            and equity > 0
            and gross_value <= max_gross * equity + 1e-8
        )

    if feasible(1.0):
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        if feasible(mid):
            low = mid
        else:
            high = mid
    return low


def _metrics(eq: pd.DataFrame) -> dict[str, Any]:
    if eq.empty:
        return {}
    equity = eq["equity"].astype(float)
    ret = equity.pct_change().dropna()
    total = float(equity.iloc[-1] / equity.iloc[0] - 1) if equity.iloc[0] else 0.0
    ppy = periods_per_year(eq["timestamp"]) if "timestamp" in eq else float(TRADING_DAYS)
    years = max(len(equity) / ppy, 1 / ppy)
    vol = float(ret.std(ddof=0) * math.sqrt(ppy)) if len(ret) > 1 else 0.0
    downside = ret[ret < 0]
    dvol = float(downside.std(ddof=0) * math.sqrt(ppy)) if len(downside) > 1 else 0.0
    dd = equity / equity.cummax() - 1
    months = (
        eq.resample("ME", on="timestamp").last()["equity"].pct_change().dropna()
        if "timestamp" in eq
        else pd.Series(dtype=float)
    )
    return {
        "total_return": total,
        "cagr": float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)
        if len(equity) > 1
        else 0.0,
        "volatility": vol,
        "sharpe": float(ret.mean() * ppy / vol) if vol else 0.0,
        "sortino": float(ret.mean() * ppy / dvol) if dvol else 0.0,
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "calmar": float(((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) / abs(dd.min()))
        if len(dd) and dd.min() < 0
        else 0.0,
        "average_turnover": float(eq["turnover"].mean()),
        "total_turnover": float(eq["turnover"].sum()),
        "average_positions": float(eq["number_of_positions"].mean()),
        "max_positions": int(eq["number_of_positions"].max()),
        "exposure": float(eq["gross_exposure"].mean()),
        "hit_rate": float((ret > 0).mean()) if len(ret) else 0.0,
        "best_month": float(months.max()) if len(months) else 0.0,
        "worst_month": float(months.min()) if len(months) else 0.0,
        "monthly_win_rate": float((months > 0).mean()) if len(months) else 0.0,
    }


def run_multi_asset_backtest(
    data: pd.DataFrame,
    target_weights: pd.DataFrame,
    initial_cash: float = 100000.0,
    cost_model: CostModel | None = None,
    max_weight_per_asset: float = 1.0,
    allow_leverage: bool = False,
    allow_short: bool = False,
    fractional_shares: bool = True,
    rebalance_band: float = 0.0,
    execution_policy: BarExecutionPolicy | None = None,
    max_gross_exposure: float | None = None,
) -> MultiAssetBacktestResult:
    # Omitted costs resolve to a conservative default; a frictionless run must
    # be requested explicitly by passing an all-zero CostModel.
    cost_model = cost_model if cost_model is not None else CONSERVATIVE_COST_MODEL
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be finite and > 0")
    if not math.isfinite(max_weight_per_asset) or max_weight_per_asset <= 0:
        raise ValueError("max_weight_per_asset must be finite and > 0")
    if max_gross_exposure is not None:
        if not math.isfinite(max_gross_exposure) or max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be finite and > 0")
        if allow_leverage:
            raise ValueError(
                "max_gross_exposure enforcement together with allow_leverage is "
                "not implemented; refusing a cap that would be silently ignored"
            )
    # The gross cap actually applied when sizing exposure-increasing orders.
    applied_max_gross = 1.0 if max_gross_exposure is None else max_gross_exposure
    if not math.isfinite(rebalance_band) or rebalance_band < 0:
        raise ValueError("rebalance_band must be >= 0")
    policy = execution_policy or BarExecutionPolicy()
    if not fractional_shares and policy.lot_size is None:
        policy = replace(policy, lot_size=1.0)
    if (
        not fractional_shares
        and policy.lot_size is not None
        and (policy.lot_size < 1 or not float(policy.lot_size).is_integer())
    ):
        raise ValueError("non-fractional execution requires an integer lot_size >= 1")
    validated = validate_panel_schema(data)
    opens = pivot_open(data)
    closes = pivot_close(data)
    volumes = (
        validated.pivot(index="timestamp", columns="symbol", values="volume")
        .sort_index()
        .reindex(index=closes.index, columns=closes.columns)
    )
    # Perp funding accrual: longs pay positive funding, shorts receive it.
    funding = None
    if "funding_rate" in data.columns:
        funding = (
            validated.assign(
                funding_rate=pd.to_numeric(data["funding_rate"], errors="coerce").to_numpy()
            )
            .pivot(index="timestamp", columns="symbol", values="funding_rate")
            .sort_index()
        )
    dates = list(closes.index)
    symbols = list(closes.columns)
    required_weight_columns = {"timestamp", "symbol", "target_weight"}
    if target_weights.empty:
        tw = pd.DataFrame(columns=sorted(required_weight_columns))
        tw["timestamp"] = pd.Series(dtype="datetime64[ns, UTC]")
    else:
        missing_columns = required_weight_columns.difference(target_weights.columns)
        if missing_columns:
            raise ValueError(
                f"target_weights missing required columns: {sorted(missing_columns)}"
            )
        tw = target_weights.loc[:, ["timestamp", "symbol", "target_weight"]].copy()
        tw["timestamp"] = pd.to_datetime(tw["timestamp"], utc=True, errors="coerce")
        tw["symbol"] = tw["symbol"].astype("string").str.strip()
        tw["target_weight"] = pd.to_numeric(tw["target_weight"], errors="coerce")
        if tw[["timestamp", "symbol", "target_weight"]].isna().any().any():
            raise ValueError("target_weights contains missing or invalid values")
        if tw["symbol"].eq("").any():
            raise ValueError("target_weights contains an empty symbol")
        if tw.duplicated(["timestamp", "symbol"]).any():
            raise ValueError("target_weights contains duplicate timestamp/symbol rows")
        unknown_symbols = sorted(set(tw["symbol"]).difference(symbols))
        if unknown_symbols:
            raise ValueError(f"target_weights contains unknown symbols: {unknown_symbols}")
    if not tw.empty:
        if (tw["target_weight"] < 0).any() and not allow_short:
            raise ValueError("negative target weights require allow_short=True")
        if (tw["target_weight"].abs() > max_weight_per_asset + 1e-12).any():
            raise ValueError("target weight exceeds max_weight_per_asset")
        gross = tw.groupby("timestamp")["target_weight"].apply(lambda s: float(s.abs().sum()))
        if (gross > 1.0 + 1e-12).any() and not allow_leverage:
            raise ValueError("target weights imply leverage")
    cash = float(initial_cash)
    qty = {s: 0.0 for s in symbols}
    eq_rows: list[dict[str, Any]] = []
    pos_rows: list[dict[str, Any]] = []
    tr_rows: list[dict[str, Any]] = []
    order_event_rows: list[dict[str, Any]] = []
    open_orders: list[BarOrderState] = []
    pending_targets: list[_TargetIntent] = []
    order_sequence = 0
    by_ts = {k: g for k, g in tw.groupby("timestamp")}

    def record_order_event(
        timestamp: Any,
        event_type: str,
        order: BarOrderState,
        fill: Any = None,
    ) -> None:
        order_event_rows.append(
            {
                "timestamp": timestamp,
                "event_type": event_type,
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side,
                "requested_quantity": abs(order.signed_quantity),
                "filled_quantity": order.cumulative_filled_quantity,
                "remaining_quantity": abs(float(order.remaining_quantity or 0.0)),
                "status": order.status.value,
                "reason": order.reason,
                "fill_id": fill.fill_id if fill is not None else "",
                "fill_quantity": fill.quantity if fill is not None else 0.0,
                "fill_price": fill.price if fill is not None else 0.0,
                "participation_rate": (
                    fill.participation_rate if fill is not None else 0.0
                ),
                "price_impact_bps": (
                    fill.price_impact_bps if fill is not None else 0.0
                ),
            }
        )

    for i, ts in enumerate(dates):
        turnover = 0.0
        prices = opens.loc[ts]
        bar_volumes = volumes.loc[ts]
        previous_close = closes.iloc[max(0, i - 1)]
        valuation_prices = prices.combine_first(previous_close)
        port_val = cash + sum(
            qty[s] * float(valuation_prices[s])
            for s in symbols
            if pd.notna(valuation_prices[s])
        )
        if not math.isfinite(port_val) or port_val <= 0:
            raise ValueError("portfolio equity must remain finite and positive")

        def attempt_orders(
            orders: list[BarOrderState],
            current_prices: pd.Series = prices,
            current_volumes: pd.Series = bar_volumes,
            bar_index: int = i,
            turnover_denominator: float = port_val,
            timestamp: Any = ts,
        ) -> list[BarOrderState]:
            nonlocal cash, turnover
            retained: list[BarOrderState] = []
            for order in sorted(
                orders, key=lambda item: (item.signed_quantity > 0, item.symbol)
            ):
                candidate = replace(order)
                raw_price = current_prices.get(order.symbol, np.nan)
                raw_volume = current_volumes.get(order.symbol, np.nan)
                fill = execute_market_order_on_bar(
                    candidate,
                    bar_index=bar_index,
                    open_price=(
                        float(raw_price)
                        if pd.notna(raw_price) and math.isfinite(float(raw_price))
                        else None
                    ),
                    volume=(
                        float(raw_volume)
                        if pd.notna(raw_volume) and math.isfinite(float(raw_volume))
                        else None
                    ),
                    policy=policy,
                )
                if fill is not None:
                    signed_fill = fill.quantity if order.side == "buy" else -fill.quantity
                    notional = abs(signed_fill * fill.price)
                    cost = cost_model.trade_cost(notional)
                    next_cash = cash - signed_fill * fill.price - cost
                    if not allow_leverage and next_cash < -1e-8:
                        candidate = replace(order)
                        candidate.status = ExecutionStatus.REJECTED
                        candidate.reason = (
                            "fill would create negative cash after costs and impact"
                        )
                        fill = None
                    else:
                        cash = (
                            max(0.0, next_cash)
                            if not allow_leverage
                            else next_cash
                        )
                        qty[order.symbol] += signed_fill
                        turnover += notional / turnover_denominator
                        tr_rows.append(
                            {
                                "timestamp": timestamp,
                                "order_id": order.order_id,
                                "fill_id": fill.fill_id,
                                "symbol": order.symbol,
                                "side": order.side,
                                "quantity": fill.quantity,
                                "price": fill.price,
                                "notional": notional,
                                "cost": cost,
                                "participation_rate": fill.participation_rate,
                                "price_impact_bps": fill.price_impact_bps,
                                "order_status": candidate.status.value,
                            }
                        )
                record_order_event(
                    timestamp, candidate.status.value, candidate, fill
                )
                if not candidate.is_terminal:
                    retained.append(candidate)
            return retained

        # Existing partial orders receive their next attempt before a newly
        # eligible target cancels and replaces any remaining quantity.
        if open_orders:
            open_orders = attempt_orders(open_orders)

        eligible_targets = [
            intent for intent in pending_targets if intent.eligible_bar_index <= i
        ]
        pending_targets = [
            intent for intent in pending_targets if intent.eligible_bar_index > i
        ]
        if eligible_targets:
            intent = eligible_targets[-1]
            for stale_order in open_orders:
                cancel_order(stale_order, "superseded by a newer target")
                record_order_event(ts, "cancelled", stale_order)
            open_orders = []

            desired = {s: 0.0 for s in symbols}
            desired.update(intent.weights)
            reducing_orders: list[tuple[str, float, float]] = []
            increasing_orders: list[tuple[str, float, float]] = []
            for s in sorted(desired):
                weight = desired[s]
                execution_price = prices.get(s, np.nan)
                sizing_price = (
                    execution_price
                    if pd.notna(execution_price)
                    and math.isfinite(float(execution_price))
                    and execution_price > 0
                    else valuation_prices.get(s, np.nan)
                )
                if (
                    pd.isna(sizing_price)
                    or not math.isfinite(float(sizing_price))
                    or sizing_price <= 0
                ):
                    continue
                price = float(sizing_price)
                target_val = port_val * weight
                current_value = qty.get(s, 0.0) * price
                delta = target_val - current_value
                if abs(delta) < 1e-9:
                    continue
                if rebalance_band > 0 and weight != 0:
                    drift = abs(delta) / port_val
                    if drift < rebalance_band:
                        continue
                target_quantity = target_val / price
                reducing, increasing = _split_order(
                    qty.get(s, 0.0), target_quantity
                )
                if abs(reducing) > 1e-12:
                    reducing_orders.append((s, reducing, price))
                if abs(increasing) > 1e-12:
                    increasing_orders.append((s, increasing, price))

            def submit_orders(
                requests: list[tuple[str, float, float]],
                scale: float,
                target_intent: _TargetIntent = intent,
                timestamp: Any = ts,
            ) -> list[BarOrderState]:
                nonlocal order_sequence
                submitted: list[BarOrderState] = []
                for symbol, requested, _ in requests:
                    quantity = _scaled_quantity(
                        requested, scale, fractional_shares
                    )
                    if abs(quantity) < 1e-12:
                        continue
                    order_sequence += 1
                    order = BarOrderState(
                        order_id=f"bt-{order_sequence:08d}",
                        symbol=symbol,
                        signed_quantity=quantity,
                        submitted_bar_index=target_intent.decided_bar_index,
                        eligible_bar_index=target_intent.eligible_bar_index,
                    )
                    record_order_event(timestamp, "submitted", order)
                    submitted.append(order)
                return submitted

            reduction_sells = [
                order for order in reducing_orders if order[1] < 0
            ]
            reduction_buys = [
                order for order in reducing_orders if order[1] > 0
            ]
            open_orders.extend(attempt_orders(submit_orders(reduction_sells, 1.0)))
            cover_scale = (
                1.0
                if allow_leverage
                else _maximum_feasible_scale(
                    cash,
                    qty,
                    reduction_buys,
                    valuation_prices,
                    cost_model,
                    fractional_shares,
                    float("inf"),
                )
            )
            open_orders.extend(
                attempt_orders(submit_orders(reduction_buys, cover_scale))
            )

            if allow_leverage:
                _, _, projected_equity, _ = _simulate_orders(
                    cash,
                    qty,
                    increasing_orders,
                    1.0,
                    valuation_prices,
                    cost_model,
                    fractional_shares,
                )
                if not math.isfinite(projected_equity) or projected_equity <= 0:
                    raise ValueError(
                        "transaction costs would exhaust portfolio equity"
                    )
                increase_scale = 1.0
            else:
                increase_scale = _maximum_feasible_scale(
                    cash,
                    qty,
                    increasing_orders,
                    valuation_prices,
                    cost_model,
                    fractional_shares,
                    applied_max_gross,
                )
            open_orders.extend(
                attempt_orders(submit_orders(increasing_orders, increase_scale))
            )

            if not allow_leverage and cash < -1e-9:
                raise RuntimeError("internal sizing error: negative cash")
            execution_equity = cash + sum(
                qty[symbol] * float(valuation_prices[symbol])
                for symbol in symbols
                if pd.notna(valuation_prices[symbol])
            )
            execution_gross = sum(
                abs(qty[symbol] * float(valuation_prices[symbol]))
                for symbol in symbols
                if pd.notna(valuation_prices[symbol])
            )
            if not math.isfinite(execution_equity) or execution_equity <= 0:
                raise ValueError("fills would leave non-positive or invalid equity")
            if (
                not allow_leverage
                and execution_gross > execution_equity + 1e-8
            ):
                raise RuntimeError(
                    "internal sizing error: gross exposure exceeds equity"
                )
        if max_gross_exposure is not None and not allow_leverage:
            # A gross cap is a standing risk limit, not a rebalance-time
            # suggestion: when drift pushes exposure above the cap between
            # rebalances, trim every position proportionally at the next
            # executable price (this bar's open). Residual overshoot is
            # bounded by one bar's intra-bar drift.
            trim_equity = cash + sum(
                qty[s] * float(valuation_prices[s])
                for s in symbols
                if pd.notna(valuation_prices[s])
            )
            trim_gross = sum(
                abs(qty[s] * float(valuation_prices[s]))
                for s in symbols
                if pd.notna(valuation_prices[s])
            )
            if (
                math.isfinite(trim_equity)
                and trim_equity > 0
                and trim_gross > applied_max_gross * trim_equity * (1.0 + 1e-6)
            ):
                shrink = (applied_max_gross * trim_equity) / trim_gross
                trim_orders: list[BarOrderState] = []
                for s in sorted(symbols):
                    price = valuation_prices.get(s, np.nan)
                    if pd.isna(price) or float(price) <= 0 or abs(qty[s]) < 1e-12:
                        continue
                    delta_qty = _scaled_quantity(
                        qty[s] * (shrink - 1.0), 1.0, fractional_shares
                    )
                    if abs(delta_qty) < 1e-12:
                        continue
                    order_sequence += 1
                    trim = BarOrderState(
                        order_id=f"bt-{order_sequence:08d}",
                        symbol=s,
                        signed_quantity=delta_qty,
                        submitted_bar_index=i,
                        eligible_bar_index=i,
                    )
                    record_order_event(ts, "submitted", trim)
                    trim_orders.append(trim)
                open_orders.extend(attempt_orders(trim_orders))
        if funding is not None and ts in funding.index:
            for s in symbols:
                rate = funding.loc[ts, s] if s in funding.columns else np.nan
                price = closes.loc[ts, s]
                if pd.isna(rate) or rate == 0 or pd.isna(price) or abs(qty[s]) < 1e-12:
                    continue
                cash -= qty[s] * float(price) * float(rate)
        equity = cash + sum(
            qty[s] * float(closes.loc[ts, s]) for s in symbols if pd.notna(closes.loc[ts, s])
        )
        gross = sum(
            abs(qty[s] * float(closes.loc[ts, s])) for s in symbols if pd.notna(closes.loc[ts, s])
        ) / max(equity, 1e-12)
        net = sum(
            qty[s] * float(closes.loc[ts, s]) for s in symbols if pd.notna(closes.loc[ts, s])
        ) / max(equity, 1e-12)
        if (
            not math.isfinite(equity)
            or equity <= 0
            or not math.isfinite(gross)
            or not math.isfinite(net)
        ):
            raise ValueError("portfolio accounting produced non-finite or non-positive values")
        eq_rows.append(
            {
                "timestamp": ts,
                "equity": equity,
                "cash": cash,
                "gross_exposure": gross,
                "net_exposure": net,
                "turnover": turnover,
                "number_of_positions": sum(abs(v) > 1e-12 for v in qty.values()),
            }
        )
        for s in symbols:
            price = closes.loc[ts, s]
            if pd.notna(price) and abs(qty[s]) > 1e-12:
                pos_rows.append(
                    {
                        "timestamp": ts,
                        "symbol": s,
                        "quantity": qty[s],
                        "market_value": qty[s] * float(price),
                        "weight": qty[s] * float(price) / max(equity, 1e-12),
                    }
                )
        if ts in by_ts and i < len(dates) - 1:
            target = {
                str(row.symbol): float(row.target_weight)
                for row in by_ts[ts].itertuples()
            }
            eligible_index = i + 1 + policy.additional_latency_bars
            if eligible_index < len(dates):
                pending_targets.append(
                    _TargetIntent(target, i, eligible_index, ts)
                )
    for order in open_orders:
        cancel_order(order, "backtest ended before order completed")
        record_order_event(dates[-1], "cancelled", order)
    eq = pd.DataFrame(eq_rows)
    return MultiAssetBacktestResult(
        eq,
        pd.DataFrame(pos_rows),
        pd.DataFrame(tr_rows),
        _metrics(eq),
        pd.DataFrame(order_event_rows),
    )


