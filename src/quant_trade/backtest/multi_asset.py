from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.data.panel import pivot_close, pivot_open, validate_panel_schema

TRADING_DAYS = 252


@dataclass(frozen=True)
class MultiAssetBacktestResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, Any]


def _metrics(eq: pd.DataFrame) -> dict[str, Any]:
    if eq.empty:
        return {}
    equity = eq["equity"].astype(float)
    ret = equity.pct_change().dropna()
    total = float(equity.iloc[-1] / equity.iloc[0] - 1) if equity.iloc[0] else 0.0
    years = max(len(equity) / TRADING_DAYS, 1 / TRADING_DAYS)
    vol = float(ret.std(ddof=0) * math.sqrt(TRADING_DAYS)) if len(ret) > 1 else 0.0
    downside = ret[ret < 0]
    dvol = float(downside.std(ddof=0) * math.sqrt(TRADING_DAYS)) if len(downside) > 1 else 0.0
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
        "sharpe": float(ret.mean() * TRADING_DAYS / vol) if vol else 0.0,
        "sortino": float(ret.mean() * TRADING_DAYS / dvol) if dvol else 0.0,
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
) -> MultiAssetBacktestResult:
    cost_model = cost_model or CostModel()
    validate_panel_schema(data)
    opens = pivot_open(data)
    closes = pivot_close(data)
    dates = list(closes.index)
    symbols = list(closes.columns)
    tw = (
        target_weights.copy()
        if not target_weights.empty
        else pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    )
    tw["timestamp"] = (
        pd.to_datetime(tw["timestamp"], utc=True, errors="coerce")
        if not tw.empty
        else pd.Series(dtype="datetime64[ns, UTC]")
    )
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
            prices = opens.loc[ts].combine_first(closes.loc[ts])
            port_val = cash + sum(
                qty[s] * float(closes.loc[ts, s]) for s in symbols if pd.notna(closes.loc[ts, s])
            )
            turnover = 0.0
            desired = {s: 0.0 for s in symbols}
            desired.update(pending)
            for s, w in desired.items():
                price = prices.get(s, np.nan)
                if pd.isna(price) or price <= 0:
                    continue
                target_val = port_val * w
                cur = qty.get(s, 0.0) * float(price)
                delta = target_val - cur
                if abs(delta) < 1e-9:
                    continue
                q = delta / float(price)
                q = math.trunc(q) if not fractional_shares else q
                notional = abs(q * float(price))
                cost = cost_model.trade_cost(notional)
                cash -= q * float(price) + cost
                qty[s] = qty.get(s, 0.0) + q
                turnover += notional / max(port_val, 1e-12)
                tr_rows.append(
                    {
                        "timestamp": ts,
                        "symbol": s,
                        "side": "buy" if q > 0 else "sell",
                        "quantity": abs(q),
                        "price": float(price),
                        "notional": notional,
                        "cost": cost,
                    }
                )
            pending = None
        else:
            turnover = 0.0
        equity = cash + sum(
            qty[s] * float(closes.loc[ts, s]) for s in symbols if pd.notna(closes.loc[ts, s])
        )
        gross = sum(
            abs(qty[s] * float(closes.loc[ts, s])) for s in symbols if pd.notna(closes.loc[ts, s])
        ) / max(equity, 1e-12)
        net = sum(
            qty[s] * float(closes.loc[ts, s]) for s in symbols if pd.notna(closes.loc[ts, s])
        ) / max(equity, 1e-12)
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
