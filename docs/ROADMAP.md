# Roadmap

## Phase 0: Foundation
Project structure, CLI, tests, sample data, docs, deterministic educational backtests.

## Phase 1: Research-quality backtesting
Improve event modeling, corporate actions, benchmark comparisons, walk-forward analysis, and experiment tracking.

## Phase 2: Data provider integration
Add approved vendor interfaces, local caching, schema validation, and data lineage. No secrets in source control.

## Phase 3: Paper trading
Add simulated or broker-provided paper trading only after risk gates and monitoring are ready.

## Phase 4: Broker execution
Integrate brokers only with explicit human approval, kill switches, reconciliation, and order controls.

## Phase 5: Cloud deployment
Package jobs and services for reproducible cloud/server environments.

## Phase 6: Monitoring and risk controls
Add alerts, drawdown limits, position checks, data health checks, and emergency shutdown procedures.

## Phase 7: Strategy portfolio and capital allocation
Research multi-strategy capital allocation, correlation management, and portfolio-level constraints.

## Phase 4 complete: Strategy Research Lab

Adds multi-asset daily research workflows, benchmark comparisons, robustness diagnostics, and synthetic offline demos. Phase 5 should focus on strategy selection and paper-trading readiness, not real-money trading.

## Phase 5

Implemented strategy selection, promotion checks, simulated paper replay, risk guardrails, local state, audit logs, and monitoring reports. Phase 6 should prepare real paper broker integration separately while still prohibiting real-money trading.
