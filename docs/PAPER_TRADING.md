# Simulated Paper Trading

Phase 5 is simulated paper trading only. It uses local cached historical OHLCV data, writes local state, orders, fills, events, and reports, and has no broker connectivity or real orders.

Forward replay iterates timestamps chronologically and passes only data available up to the current timestamp to signal models. This differs from normal backtesting by exercising session state, order generation, risk checks, audit logging, and kill-switch behavior.

Use `quant-trade paper init`, `run`, `status`, `pause`, `resume`, `kill-switch`, and `report` with configs under `configs/paper/`.

Do not move to real broker paper trading unless CI is green, a candidate has human approval, simulated paper passes, risk limits and kill switch are tested, monitoring reports are generated, data quality is verified, no secrets are committed, broker integration receives separate review, and real-money trading remains prohibited.
