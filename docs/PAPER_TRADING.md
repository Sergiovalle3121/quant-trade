# Simulated Paper Trading

Phase 5 is simulated paper trading only. It uses local cached historical OHLCV data, writes local state, orders, fills, events, and reports, and has no broker connectivity or real orders.

Forward replay iterates timestamps chronologically and passes only data available up to the current timestamp to signal models. This differs from normal backtesting by exercising session state, order generation, risk checks, audit logging, and kill-switch behavior.

Use `quant-trade paper init`, `run`, `status`, `pause`, `resume`, `kill-switch`, and `report` with configs under `configs/paper/`.

Do not move to real broker paper trading unless CI is green, a candidate has human approval, simulated paper passes, risk limits and kill switch are tested, monitoring reports are generated, data quality is verified, no secrets are committed, broker integration receives separate review, and real-money trading remains prohibited.

## Phase 6 Alpaca Paper Warning

Alpaca Paper support is paper-only, manually confirmed, and hard-blocks live endpoints. Paper results are simulations and are not real-money results.

## Phase 7 cloud paper deployment note

Scheduled cloud workflows are paper-only and fail closed. Defaults are dry-run; paper submission requires explicit config, official Alpaca Paper endpoint credentials from env or AWS Secrets Manager, kill switch clear, and reviewed operations. No live trading endpoints or real-money execution are supported.


## Phase 8 operations safety

- Operations code must never call broker/network in tests.
- Never expose secrets in dashboard/alerts/incidents.
- New alert categories need tests.
- New readiness criteria need docs.
- Retention deletes require explicit confirmation.
- No command may imply real-money readiness.

## Phase 9 paper trial management

Paper trial management formalizes 30/60/90-day simulated strategy trials, weekly/monthly review packs, strategy decay checks, evidence requirements, and conservative decisions. Human notes are required before advancement within paper operations. Real-money approval remains explicitly out of scope and must remain false.
