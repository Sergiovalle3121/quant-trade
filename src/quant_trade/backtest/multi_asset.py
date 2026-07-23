from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.backtest.costs import CONSERVATIVE_COST_MODEL, CostModel
from quant_trade.data.panel import pivot_close, pivot_open, validate_panel_schema
from quant_trade.metrics.performance import periods_per_year

TRADING_DAYS = 252


@dataclass(frozen=True)
class MultiAssetBacktestResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, Any]


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
) -> MultiAssetBacktestResult:
    # Omitted costs resolve to a conservative default; a frictionless run must
    # be requested explicitly by passing an all-zero CostModel.
    cost_model = cost_model if cost_model is not None else CONSERVATIVE_COST_MODEL
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be finite and > 0")
    if not math.isfinite(max_weight_per_asset) or max_weight_per_asset <= 0:
        raise ValueError("max_weight_per_asset must be finite and > 0")
    if not math.isfinite(rebalance_band) or rebalance_band < 0:
        raise ValueError("rebalance_band must be >= 0")
    validated = validate_panel_schema(data)
    opens = pivot_open(data)
    closes = pivot_close(data)
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
    eq_rows = []
    pos_rows = []
    tr_rows = []
    pending: dict[str, float] | None = None
    by_ts = {k: g for k, g in tw.groupby("timestamp")}
    for i, ts in enumerate(dates):
        if pending is not None:
            # Missing opens are not silently replaced with the execution bar's
            # close. The previous close may value an existing position, but an
            # order without an observable open is deferred by skipping it.
            prices = opens.loc[ts]
            valuation_prices = prices.combine_first(closes.iloc[i - 1])
            port_val = cash + sum(
                qty[s] * float(valuation_prices[s])
                for s in symbols
                if pd.notna(valuation_prices[s])
            )
            if not math.isfinite(port_val) or port_val <= 0:
                raise ValueError("portfolio equity must remain finite and positive")
            turnover = 0.0
            desired = {s: 0.0 for s in symbols}
            desired.update(pending)
            reducing_orders: list[tuple[str, float, float]] = []
            increasing_orders: list[tuple[str, float, float]] = []
            for s in sorted(desired):
                w = desired[s]
                price = prices.get(s, np.nan)
                if pd.isna(price) or not math.isfinite(float(price)) or price <= 0:
                    continue
                target_val = port_val * w
                cur = qty.get(s, 0.0) * float(price)
                delta = target_val - cur
                if abs(delta) < 1e-9:
                    continue
                # No-trade band: skip drifts smaller than the band in weight
                # points, but always allow full exits so risk-off targets are
                # never suppressed by the turnover control.
                if rebalance_band > 0 and port_val > 0 and w != 0:
                    drift = abs(delta) / port_val
                    if drift < rebalance_band:
                        continue
                target_quantity = target_val / float(price)
                reducing, increasing = _split_order(qty.get(s, 0.0), target_quantity)
                if abs(reducing) > 1e-12:
                    reducing_orders.append((s, reducing, float(price)))
                if abs(increasing) > 1e-12:
                    increasing_orders.append((s, increasing, float(price)))

            def execute_orders(
                orders: list[tuple[str, float, float]],
                scale: float,
                execution_ts: Any = ts,
                turnover_denominator: float = port_val,
            ) -> None:
                nonlocal cash, turnover
                # Proceeds are available before any buy/cover on the same bar.
                for symbol, requested, price in sorted(
                    orders, key=lambda item: (item[1] > 0, item[0])
                ):
                    executed = _scaled_quantity(requested, scale, fractional_shares)
                    if abs(executed) < 1e-12:
                        continue
                    notional = abs(executed * price)
                    cost = cost_model.trade_cost(notional)
                    next_cash = cash - executed * price - cost
                    if not allow_leverage and next_cash < -1e-8:
                        raise RuntimeError(
                            "internal sizing error: trade would create negative cash"
                        )
                    cash = max(0.0, next_cash) if not allow_leverage else next_cash
                    qty[symbol] += executed
                    turnover += notional / turnover_denominator
                    tr_rows.append(
                        {
                            "timestamp": execution_ts,
                            "symbol": symbol,
                            "side": "buy" if executed > 0 else "sell",
                            "quantity": abs(executed),
                            "price": price,
                            "notional": notional,
                            "cost": cost,
                        }
                    )

            reduction_sells = [order for order in reducing_orders if order[1] < 0]
            reduction_buys = [order for order in reducing_orders if order[1] > 0]
            execute_orders(reduction_sells, 1.0)
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
            execute_orders(reduction_buys, cover_scale)

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
                    raise ValueError("transaction costs would exhaust portfolio equity")
                increase_scale = 1.0
            else:
                increase_scale = _maximum_feasible_scale(
                    cash,
                    qty,
                    increasing_orders,
                    valuation_prices,
                    cost_model,
                    fractional_shares,
                    1.0,
                )
            execute_orders(increasing_orders, increase_scale)
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
                raise RuntimeError("internal sizing error: gross exposure exceeds equity")
            pending = None
        else:
            turnover = 0.0
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
            pending = {str(r.symbol): float(r.target_weight) for r in by_ts[ts].itertuples()}
    eq = pd.DataFrame(eq_rows)
    return MultiAssetBacktestResult(eq, pd.DataFrame(pos_rows), pd.DataFrame(tr_rows), _metrics(eq))

