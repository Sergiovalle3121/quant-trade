# Strategy Research Plan

Future research tracks:

- Trend following with robust cost and regime analysis.
- Mean reversion with stationarity checks and risk controls.
- Statistical arbitrage only after reliable multi-asset data handling exists.
- Cross-sectional momentum with survivorship-bias-aware universes.
- Volatility targeting and portfolio-level risk budgeting.
- Machine learning models only after strong baseline strategies and clean evaluation pipelines.
- Reinforcement learning is deferred until data, simulation, and evaluation are robust enough to avoid misleading results.

## Phase 4 research lab

Use the multi-asset research CLI for daily liquid ETF/equity studies. Treat all included strategies as transparent baselines for research, not production alpha. Always compare with benchmarks and inspect robustness artifacts before considering Phase 5 paper-trading readiness.

## Next evidence phase: bounded alpha search

The next phase is a bounded, preregistered search rather than an exhaustive
parameter sweep. Trying every possible rule until one backtest is profitable
would make the reported maximum a multiple-testing artifact. Each campaign
must therefore freeze, before evaluation:

1. an economic mechanism and falsifiable null hypothesis;
2. the point-in-time universe, dataset hash, benchmark and holdout seal;
3. a small parameter family and its complete trial-ledger identity;
4. execution assumptions, capacity limits and 1x/2x/3x cost scenarios; and
5. minimum OOS observations, PSR/DSR/PBO, drawdown and stability gates.

Candidate families remain trend, cross-sectional momentum, defensive
allocation and funding carry. They advance independently only when net excess
return survives walk-forward selection, a sealed holdout, block-bootstrap
uncertainty and the global trial-count correction. A failed family is recorded
and retired; its thresholds are not relaxed after seeing results. Passing can
authorize only a simulated paper trial, never real money.

The repository currently has no verified dataset capable of completing the
venue carry campaigns. Until an evidence pack is imported on a permitted host,
the correct state is `NOT_MEASURED`, not an assumed profit or loss.
