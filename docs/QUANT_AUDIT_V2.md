# Quant Platform Audit V2

Date: 2026-07-22. Scope: repository code under `src/quant_trade/`, tests, configs, docs, and sample artifacts. This audit is a research/backtesting assessment only and does not approve real-money trading.

## 1. Architecture map

- **CLI and orchestration**: `quant_trade.cli` wires backtests, research workflows, data, broker-paper utilities, cloud dry runs, ops, trials, and data lake commands.
- **Data layer**: `quant_trade.data` validates canonical OHLCV, panel data, provider requests, cache manifests, quality reports, CSV/yfinance/polygon/synthetic/ccxt adapters, and funding-rate attachment.
- **Data lake v2**: `quant_trade.datalake` manages local versioned datasets, contracts, snapshots, provider comparisons, quality reports, lineage, dashboard generation, and survivorship metadata.
- **Signal research**: `quant_trade.research.signals` contains long-only/short-capable allocation, trend, momentum, mean-reversion, volatility, breakout, carry, ensemble, and sizing signal models registered through `strategy_registry`.
- **Backtesting**: `quant_trade.backtest.engine` handles single-asset next-bar execution; `quant_trade.backtest.multi_asset` handles multi-asset target weights, next-open fills, cash, costs, funding accrual, positions, and metrics.
- **Metrics and validation**: `quant_trade.metrics` computes performance and statistical validation such as PSR/DSR support; `quant_trade.research.walk_forward*`, `robustness`, `selection`, `promotion`, and `ledger` implement selection evidence and overfit controls.
- **Risk and allocation**: `quant_trade.risk`, `quant_trade.allocation`, and `quant_trade.stress` define position/risk limits, portfolio governance, risk budgets, liquidity/cost shocks, regimes, scenarios, and dashboards.
- **Paper and broker-paper**: `quant_trade.paper` simulates local paper runs; `quant_trade.execution` contains simulated broker plus Alpaca paper-only planning/adapters with live endpoint safety checks.
- **Operations and trials**: `quant_trade.ops`, `quant_trade.cloud`, and `quant_trade.trials` cover readiness, alerts, kill switches, incidents, run validation, dry-run cloud jobs, evidence records, review packs, and conservative paper-only decisions.

## 2. End-to-end flow

1. **Datos**: providers or CSVs normalize rows to canonical UTC OHLCV; panels require `timestamp`, `symbol`, `open`, `high`, `low`, `close`, `volume` and reject duplicate timestamp/symbol bars.
2. **Features**: signal modules derive rolling statistics, momentum, trend, volatility, funding, breakout, and allocation features from historical bars.
3. **Señales**: strategy registry returns a `SignalModel` that emits target weights in long form.
4. **Posiciones objetivo**: target weights are checked against short/leverage/max-weight constraints before simulation.
5. **Órdenes**: rebalances are converted to quantity deltas against current portfolio value at execution prices.
6. **Fills**: backtests fill decisions on the next bar's open, never on the decision bar close.
7. **Costos**: conservative default cost model applies commission, slippage, and spread unless explicit zero-cost assumptions are provided.
8. **Contabilidad**: cash, positions, funding payments, equity, gross/net exposure, turnover, and trades are recorded per bar.
9. **Métricas**: total return, CAGR, volatility, Sharpe, Sortino, drawdown, Calmar, turnover, exposure, monthly stats, PSR/DSR-related moments, and benchmark-aware evidence are produced.
10. **Selección**: train/test, walk-forward, robustness, selection gates, trial ledger, and evidence scorecards reject weak or overfit candidates.
11. **Paper trading**: simulated paper uses local/cached data and emits orders, fills, account snapshots, events, reports, and state; broker-paper planning remains manual/paper-only and guarded by endpoint checks.

## 3. Risk and defect register

### Critical

- Real-money trading remains intentionally unsupported; adding live endpoints, live credentials, leverage, shorting in broker flows, or automatic order submission would violate repository safety boundaries.
- Strategy promotion depends on correct append-only trial ledger hygiene; deleting or selectively editing ledger evidence would understate multiple-testing risk.

### High

- Full-panel signal generation in multi-asset walk-forward relies on signal causality. Existing no-lookahead tests cover key strategies, but every new signal must receive truncation-invariance tests.
- Underestimated execution assumptions remain possible in illiquid assets: spread/slippage models are deterministic approximations rather than order-book simulations.
- Survivorship bias can enter if users manually provide current constituents without point-in-time membership data.
- Selection bias can enter if only favorable external datasets or symbols are committed as evidence.

### Medium

- Timezone handling is mostly UTC-normalized, but externally supplied CSVs with ambiguous local timestamps can still encode incorrect session timing before ingestion.
- Multi-asset metrics infer annualization from timestamps; mixed-frequency panels or sparse assets may need explicit policy documentation.
- Funding accrual is simplified per bar and may not match exchange-specific posting timestamps.
- Benchmark and robustness artifacts are useful diagnostics but do not replace independent out-of-sample trials.

### Low

- Sample datasets are tiny and suitable for regression tests only, not for statistical claims.
- Documentation is extensive but phase-specific; users need a single audit map to understand boundaries, which this document now provides.

## 4. Bias and accounting failure modes reviewed

- **Look-ahead/data leakage**: next-open execution and tests reduce direct leakage; danger remains in newly added global normalizers, universe filters, or labels computed with future bars.
- **Survivorship bias**: fixed ETF examples are acceptable baselines but do not prove robustness across delisted or historically unavailable symbols.
- **Selection bias/data snooping**: grid search and walk-forward log trial breadth, but users must preserve all trials and avoid cherry-picking run directories.
- **Timezone errors**: ingestion converts to UTC; users must still ensure source timestamps represent the intended market session.
- **Double accounting**: cash, costs, notional, funding, and market value are separated in the multi-asset engine; regression tests protect against silent P&L drift.
- **Impossible fills**: current fills use next open with configurable costs, but do not model partial fills, queue position, market impact, limit-order non-execution, halts, or borrow availability.
- **Costs underestimated**: conservative defaults help, yet crisis spreads and volume participation constraints require stress tests.
- **Misleading metrics**: Sharpe alone is insufficient; use drawdown, turnover, PSR/DSR, positive-window rate, benchmark comparison, and trial review evidence.
- **Overfitting**: promotion must require walk-forward, Monte Carlo/robustness, multiple-testing correction, conservative gates, and honest NO-GO decisions.

## 5. Existing reusable capabilities

- Canonical OHLCV validation, manifests, quality reports, and data lake contracts.
- Deterministic single- and multi-asset backtest engines with next-bar causality tests.
- Strategy registry with baseline allocation, trend, momentum, mean-reversion, volatility, breakout, carry, and ensemble signals.
- Walk-forward, grid search, robustness diagnostics, benchmark-aware verdicts, candidate selection, PSR/DSR evidence, and append-only trial ledger.
- Risk budgets, portfolio governance, stress scenarios, operations readiness, incident handling, kill switch, and paper-only trial management.
- Simulated paper and broker-paper safety adapters with offline tests and live endpoint rejection.

## 6. Backtest vs simulated paper vs broker paper

- **Backtest**: historical research simulator; deterministic, next-open fills, configurable costs, no external broker state.
- **Simulated paper**: local autonomous loop over local/cached data; creates paper orders/fills/account state but never contacts a broker.
- **Broker paper**: paper-only adapter/planning workflow for a broker sandbox; network calls are mocked in tests, live endpoints are blocked, and manual safeguards remain required.

## 7. Current blockers to safe real-money operation

- No explicit human approval for live trading exists in this task or repository state.
- Live broker endpoints, live keys, shorting, leverage, and real order routing are prohibited by project policy.
- Execution simulation lacks production-grade microstructure, venue limits, partial fills, borrow/locate checks, and exchange outage handling.
- Statistical evidence can still be invalidated by poor input data, unpreserved trial history, or biased universe construction.
- Operational readiness is paper-only; no command or artifact should be interpreted as real-money readiness.

## 8. Implemented V2 hardening

- Added stricter multi-asset target-weight validation: required columns, numeric finite weights, non-empty symbols, duplicate timestamp/symbol rejection, and unknown-symbol rejection before any rebalance is simulated.
- Added regression tests for malformed target weights so bad signal outputs fail closed instead of being silently ignored or double-counted.

## 9. Baseline/check results

- `python -m pip install -e ".[dev]"` could not complete because the environment's package-index tunnel returned HTTP 403 for build dependencies.
- `ruff check .` passed.
- `mypy src` passed.
- `python -m compileall -q src tests` passed.
- `pytest -q` passed with 223 tests and warnings limited to existing pandas future warnings.
