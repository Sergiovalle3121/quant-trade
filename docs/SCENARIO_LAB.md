# Scenario Lab

The Scenario Lab defines adverse market, liquidity, and operational scenarios for deterministic research stress testing.

Implemented scenario families:

1. `price_shock`
2. `volatility_spike`
3. `correlation_spike`
4. `liquidity_shock`
5. `gap_risk`
6. `drawdown_replay`
7. `benchmark_crash`
8. `rate_shock_proxy`
9. `strategy_pause_scenario`
10. `operational_failure_scenario`

Use `quant-trade stress list-scenarios --config configs/stress/equity_etf_scenarios.yaml` to inspect the configured suite. Scenario outputs are risk diagnostics only and do not approve real-money trading.
