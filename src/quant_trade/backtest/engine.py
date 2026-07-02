from dataclasses import dataclass
import pandas as pd
from quant_trade.backtest.costs import CostModel


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, float | int | None]


def load_ohlcv(path: str) -> pd.DataFrame:
    data = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {sorted(missing)}")
    return data.sort_values("date").reset_index(drop=True)


def run_backtest(
    data: pd.DataFrame,
    signals: pd.Series,
    initial_cash: float = 10_000,
    cost_model: CostModel | None = None,
) -> BacktestResult:
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    cost_model = cost_model or CostModel()
    df = data.sort_values("date").reset_index(drop=True).copy()
    sig = signals.reset_index(drop=True).reindex(df.index).fillna(0).astype(int).clip(0, 1)
    cash = float(initial_cash)
    shares = 0.0
    position = 0
    entry_value = 0.0
    entry_date = None
    rows = []
    trades = []
    prev_equity = initial_cash
    for i, row in df.iterrows():
        price = float(row["close"])
        target = int(sig.iloc[i])
        date = row["date"]
        if target != position:
            if target == 1:
                cost_est = cost_model.trade_cost(cash)
                shares = max((cash - cost_est) / price, 0.0)
                notional = shares * price
                cost = cost_model.trade_cost(notional)
                cash -= notional + cost
                entry_value = notional
                entry_date = date
            else:
                notional = shares * price
                cost = cost_model.trade_cost(notional)
                cash += notional - cost
                pnl = notional - cost - entry_value
                trades.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": date,
                        "entry_value": entry_value,
                        "exit_value": notional,
                        "pnl": pnl,
                        "return": pnl / entry_value if entry_value else 0.0,
                        "holding_period": (date - entry_date).days if entry_date is not None else 0,
                    }
                )
                shares = 0.0
                entry_value = 0.0
                entry_date = None
            position = target
        equity = cash + shares * price
        rows.append(
            {
                "date": date,
                "cash": cash,
                "shares": shares,
                "position": position,
                "equity": equity,
                "return": equity / prev_equity - 1 if prev_equity else 0.0,
            }
        )
        prev_equity = equity
    if position == 1 and len(df):
        row = df.iloc[-1]
        price = float(row["close"])
        date = row["date"]
        notional = shares * price
        cost = cost_model.trade_cost(notional)
        cash += notional - cost
        pnl = notional - cost - entry_value
        trades.append(
            {
                "entry_date": entry_date,
                "exit_date": date,
                "entry_value": entry_value,
                "exit_value": notional,
                "pnl": pnl,
                "return": pnl / entry_value if entry_value else 0.0,
                "holding_period": (date - entry_date).days if entry_date is not None else 0,
            }
        )
        rows[-1].update(
            {
                "cash": cash,
                "shares": 0.0,
                "position": 0,
                "equity": cash,
                "return": cash / prev_equity - 1 if prev_equity else 0.0,
            }
        )
    equity_curve = pd.DataFrame(rows)
    trades_df = pd.DataFrame(trades)
    return BacktestResult(
        equity_curve, trades_df, calculate_metrics(equity_curve, trades_df, initial_cash)
    )


def calculate_metrics(
    equity: pd.DataFrame, trades: pd.DataFrame, initial_cash: float
) -> dict[str, float | int | None]:
    if equity.empty:
        return {
            "total_return": 0.0,
            "sharpe": None,
            "max_drawdown": 0.0,
            "calmar_ratio": None,
            "profit_factor": None,
            "average_trade_return": None,
            "best_trade": None,
            "worst_trade": None,
            "average_holding_period": None,
            "longest_drawdown_duration": 0,
            "turnover": 0.0,
        }
    final = float(equity["equity"].iloc[-1])
    total = final / initial_cash - 1
    rets = equity["equity"].pct_change().fillna(0)
    sharpe = None if rets.std() == 0 else float((rets.mean() / rets.std()) * (252**0.5))
    peak = equity["equity"].cummax()
    dd = equity["equity"] / peak - 1
    max_dd = float(dd.min())
    calmar = None if max_dd == 0 else float(total / abs(max_dd))
    in_dd = dd < 0
    longest = (
        int((in_dd.groupby((~in_dd).cumsum()).cumcount() + 1).where(in_dd, 0).max())
        if len(dd)
        else 0
    )
    if trades.empty:
        pf = avg = best = worst = avg_hold = None
        turnover = 0.0
    else:
        gains = trades.loc[trades["pnl"] > 0, "pnl"].sum()
        losses = -trades.loc[trades["pnl"] < 0, "pnl"].sum()
        pf = None if losses == 0 else float(gains / losses)
        avg = float(trades["return"].mean())
        best = float(trades["return"].max())
        worst = float(trades["return"].min())
        avg_hold = float(trades["holding_period"].mean())
        turnover = float(trades["entry_value"].abs().sum() / initial_cash)
    return {
        "total_return": float(total),
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "profit_factor": pf,
        "average_trade_return": avg,
        "best_trade": best,
        "worst_trade": worst,
        "average_holding_period": avg_hold,
        "longest_drawdown_duration": longest,
        "turnover": turnover,
        "trade_count": int(len(trades)),
    }
