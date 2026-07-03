# Architecture

Quant Trade separates concerns so research code remains testable and safe.

- **Data** loads and validates local OHLCV files. Data quality problems should fail early.
- **Strategy** converts market data into timestamped research signals without touching brokerage or account state.
- **Backtesting** simulates long-only fills, portfolio accounting, costs, and slippage deterministically.
- **Risk** caps trade and position size and prevents leverage in this first version.
- **Metrics** evaluates outcomes without changing simulation state.
- **Execution** is future-only. No broker connectivity exists in this foundation.
- **Monitoring** is future-only and should cover system health, data quality, orders, positions, and drawdowns before live use.

This boundary keeps later integrations replaceable: NautilusTrader, broker adapters, data vendors, and cloud services can be added behind explicit interfaces after human approval.

## Phase 5 transition layer

The transition layer contains research candidate selection, promotion checks, simulated paper engine, risk manager, append-only audit events, reports, and a simulated broker stub only. No live adapters exist.

## Phase 6 Broker Layer

The execution package contains broker-neutral models, safety validation, Alpaca Paper adapter, order mapping, reconciliation, and sanitized audit logging. No live-money broker path exists.

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

## Phase 12 evidence layer

The evidence layer (`quant_trade.evidence`) is an offline SQLite subsystem that indexes local artifacts, computes checksums, redacts/skips likely secrets, and produces conservative scorecards. It has no broker connectivity and no network dependency.
