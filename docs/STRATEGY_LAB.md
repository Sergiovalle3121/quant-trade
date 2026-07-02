# Strategy Research Lab

Phase 4 is a research-only daily multi-asset backtesting lab. It starts with liquid equities and ETFs because daily bars, long-only weights, no leverage, and rebalance-based execution are easier to validate than high-frequency, derivatives, or market-making systems.

No live trading, broker connectivity, order routing, or profitability claims are included. Target weights express desired portfolio allocations by timestamp and symbol; cash is held when weights sum below 100%. Signals are executed at the next available open when possible, with conservative costs.

Run examples:

```bash
quant-trade research list-strategies
quant-trade research run --config configs/research/ts_momentum_synthetic.yaml
```

Synthetic sample data is committed at `examples/data/sample_multi_asset_ohlcv.csv` for offline CI and demos. Real provider data should be fetched with `quant-trade data fetch` before use.

Interpret train/test results conservatively. Benchmark comparison, cost sensitivity, turnover, max drawdown, and parameter stability matter more than a single high Sharpe. Very high backtest Sharpe is suspicious unless robust across costs, periods, and reasonable parameters.

## Advancement checklist

A strategy cannot move to paper trading unless CI is green, it beats benchmark out-of-sample after realistic costs, drawdown is acceptable, it survives cost sensitivity, returns are not dominated by one period, reasonable parameter ranges work, economic rationale is clear, turnover is appropriate, a human reviews it, and paper-trading risk limits are defined.
