# Capital Allocation Simulation

Phase 10 adds a paper-only capital allocation layer. It allocates simulated capital across approved paper strategies using deterministic offline evidence and never routes orders or enables real-money trading.

Key limitations:
- `real_money_ready` remains false.
- No broker calls, API keys, live endpoints, leverage, shorting, or real orders are used.
- Allocation outputs are governance research artifacts, not profitability claims.

Artifacts are written under `outputs/allocation/<run_id>/` and include selected/rejected candidates, portfolio metrics, correlation matrix, risk budget report, decisions, summary, and dashboard HTML.
