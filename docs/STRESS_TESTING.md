# Phase 11 Stress Testing

Phase 11 adds an offline, deterministic stress-testing suite for strategy equity curves, simulated paper sessions, trial evidence, and allocation research. It is simulation-only: it does not connect to brokers, place orders, fetch network data, or mark anything as real-money ready.

## Safety constraints

- `real_money_ready` is always false in stress outputs.
- Missing required symbols produce warnings and conservative scenario failures.
- Tests use local synthetic or fixture data only.
- Reports must not be interpreted as profitability claims or approval for live trading.

## Artifacts

`quant-trade stress run --config configs/stress/allocation_stress_test.yaml` writes:

- `stress_config_used.yaml`
- `scenario_results.csv`
- `stress_metrics.json`
- `worst_scenarios.csv`
- `breaches.csv`
- `stress_summary.md`
- `dashboard/index.html`

## Metrics

The report includes stressed return, max drawdown, daily loss, liquidity cost, slippage, exposure, breach counts, worst scenario, capital-at-risk estimate, recovery-days estimate, and scenario pass/fail.
