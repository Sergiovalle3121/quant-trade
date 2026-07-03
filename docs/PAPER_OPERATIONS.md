# Phase 8 Paper Operations

Paper trading / dry-run only. No live trading exists in this workflow, and real-money readiness is always false.

Run a local cycle with `quant-trade ops run-cycle --config configs/ops/local_ops_validation.yaml`. The cycle validates artifacts, computes reliability, analyzes fills, reconciles ledgers, writes alerts/reports, generates a static dashboard, and evaluates paper-operations readiness without broker, AWS, or network calls.

Daily checklist:
1. Check dashboard.
2. Check heartbeats.
3. Check active alerts.
4. Check open incidents.
5. Check rejected orders.
6. Check drawdown.
7. Check fills/slippage.
8. Check reconciliation.
9. Check data freshness.
10. Confirm kill switch status.

Paper fills are not proof of profitability. They can be optimistic, stale, partially missing, or operationally inconsistent. Critical alerts require stopping promotion work, preserving artifacts, opening or updating an incident, running reconciliation, and documenting manual review notes.
