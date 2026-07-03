# Transaction Cost Analysis

Phase 16 adds an offline transaction cost analysis lab for research and simulated paper artifacts only. It never connects to brokers, never places orders, and always records `real_money_ready=false`.

The lab computes implementation shortfall, slippage bps, spread cost proxies, fill rates, partial/rejected rates, total cost, cost as a percent of equity, turnover-adjusted cost, and research-vs-paper cost deltas.

## Limitations

When only OHLCV data is available, bid/ask spread, VWAP, queue position, order-book depth, and venue-specific liquidity are unknown. Results are conservative proxies and must not be treated as realistic fills or real-money readiness.
