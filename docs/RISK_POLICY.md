# Risk Policy

- The platform does not support live trading yet.
- No leverage, shorting, margin, or derivatives are supported in the initial simulator.
- Position and trade size caps are mandatory for backtests.
- Future live systems need explicit max drawdown limits, exposure limits, order throttles, and a kill switch.
- Paper trading must demonstrate stable operations, reconciliation, monitoring, and risk controls before real capital.
- Backtests can lie because of lookahead bias, overfitting, survivorship bias, poor cost assumptions, and market regime changes.
- Future validation must include walk-forward analysis and out-of-sample testing.

## Strategy advancement checklist

A strategy cannot move to paper trading unless CI is green, it beats benchmark out-of-sample after realistic costs, max drawdown is acceptable, cost sensitivity is acceptable, performance is not dependent on one lucky period, reasonable parameter ranges work, economic rationale is clear, turnover is suitable, a human reviews it, and paper-trading risk limits are defined.

## Simulated paper risk guardrails

Phase 5 enforces local risk limits for gross exposure, max asset weight, turnover, cash, leverage, shorting, order counts, and total drawdown kill switches. Broker connectivity is intentionally absent.

## Broker Paper Guardrails

Phase 6 rejects live mode, live-like endpoints, shorting, leverage, unsupported assets, oversized orders, and ambiguous configuration. Paper order submission requires explicit confirmation flags.

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

## Campaign risk controls

Research campaign rankings are not trading approval. They require OOS metrics, benchmark comparison, cost sensitivity, and penalties for drawdown, turnover, and train/test gaps.
