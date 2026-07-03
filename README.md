# quant-trade

Research-first quantitative trading backtesting platform foundation.

> **Safety warning:** this repository is for research and backtesting only. It does not contain live trading, broker connectivity, paid data-provider integrations, order routing, real-money execution, API keys, tokens, or secrets. Backtest results are diagnostics, not profitability claims.

## Install

### pip

```bash
python -m pip install -e ".[dev]"
```

### uv

```bash
uv pip install -e ".[dev]"
```

If your environment uses a corporate proxy or restricted network, dependency installation may fail before tests can run. Verify `pip`/`uv` proxy configuration and that your package index allows `numpy`, `pandas`, `pydantic`, `typer`, `rich`, `PyYAML`, and the development tools.

## Developer commands

```bash
make install
make lint
make test
```

CI runs the equivalent of:

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy src
python -m compileall -q src tests
pytest -q
```

## Sample backtests

```bash
quant-trade backtest --strategy sma_crossover --data examples/data/sample_ohlcv.csv --initial-cash 10000
quant-trade backtest --strategy buy_and_hold --data examples/data/sample_ohlcv.csv --initial-cash 10000
```

Supported strategy registry names are:

- `sma_crossover`
- `mean_reversion`
- `buy_and_hold`

## Research workflows

The canonical time column throughout loaders, splits, and reports is `timestamp`.

### Single experiment

```bash
quant-trade run-experiment --config configs/sma_crossover_sample.yaml
```

Writes metrics, trades, equity curve, config, and a summary under a non-overwriting directory such as `outputs/sma_crossover_sample` or `outputs/sma_crossover_sample_001`.

### Grid search

```bash
quant-trade grid-search --config configs/sma_grid_search_sample.yaml
```

Writes ranked grid results, selected best parameters, skipped invalid parameter combinations, and a summary under `outputs/`.

### Walk-forward validation

```bash
quant-trade walk-forward --config configs/sma_walk_forward_sample.yaml
```

Writes walk-forward window results and aggregate metrics under `outputs/`.

## Model-risk and research limitations

- Strategies are educational baselines for framework validation.
- The engine is deterministic and long-only with simplified next-bar execution assumptions.
- Cost models are configurable but still simplified relative to real venues.
- Grid search and walk-forward outputs are research diagnostics; they are not live-trading signals.
- Do not add broker APIs, live execution, paid feeds, keys, tokens, or credentials without explicit human approval.

## Phase 3 historical data workflow

Install optional prototype data providers when needed:

```bash
python -m pip install -e ".[dev,data]"
```

Research-only data ingestion examples:

```bash
quant-trade data fetch --provider synthetic --symbol SPY --start 2020-01-01 --end 2020-12-31 --interval 1d
quant-trade data fetch --provider yfinance --symbol SPY --start 2015-01-01 --end 2024-12-31 --interval 1d
quant-trade data validate --path data/cache/synthetic/SPY/1d/SPY_2020-01-01_2020-12-31_adjusted.csv
quant-trade data info --path data/cache/synthetic/SPY/1d/SPY_2020-01-01_2020-12-31_adjusted.csv
quant-trade data list-cache
quant-trade backtest --strategy buy_and_hold --data data/cache/synthetic/SPY/1d/SPY_2020-01-01_2020-12-31_adjusted.csv --initial-cash 10000
```

The data layer normalizes OHLCV bars to a canonical UTC schema, validates quality, writes a local CSV cache, and stores JSON manifests. Do not commit downloaded data, API keys, secrets, or `.env` files. This project remains research/backtesting only and includes no live trading or broker execution.

## Phase 4 Strategy Research Lab

The repository now includes a research-only multi-asset daily strategy lab. It supports canonical long-form OHLCV panels, baseline long-only signal models, next-open rebalance backtesting, benchmark comparisons, robustness diagnostics, and offline synthetic examples.

```bash
quant-trade research list-strategies
quant-trade research run --config configs/research/equal_weight_synthetic.yaml
```

See `docs/STRATEGY_LAB.md` for assumptions, safety limits, and the strategy advancement checklist.

## Phase 5: Strategy selection and simulated paper readiness

This repository now includes conservative candidate selection and a local-only simulated paper-trading workflow. No live broker integration, order routing, secrets, or real-money trading is implemented. See `docs/STRATEGY_SELECTION.md` and `docs/PAPER_TRADING.md`.

## Phase 6 Safe Broker Paper Integration

`quant-trade broker` adds offline broker checks, dry-run planning, manual Alpaca Paper submission, account/position/order inspection, cancel-all with confirmation, and reconciliation. Live endpoints and live-money trading are not implemented and are rejected.

## Phase 7 cloud paper deployment

Cloud commands are paper-only and default to dry-run behavior. Example: `quant-trade cloud run-job --config configs/cloud/local_dry_run.yaml --job health_check`. AWS templates under `infra/aws/` are review-before-apply and never enable live trading.


## Phase 8 operations safety

- Operations code must never call broker/network in tests.
- Never expose secrets in dashboard/alerts/incidents.
- New alert categories need tests.
- New readiness criteria need docs.
- Retention deletes require explicit confirmation.
- No command may imply real-money readiness.

## Phase 9: Paper trading trials

The `quant-trade trials` command group manages paper-only 30/60/90-day strategy trials, daily records, drift checks, review packs, evidence indexes, conservative decisions, dashboards, archives, and review cycles. These workflows are offline/dry-run by default and never approve real-money trading.


## Phase 13 Safe ML Alpha Lab

The repository includes a research-only supervised ML alpha lab with deterministic synthetic-data examples, past-only features, forward labels, chronological validation, leakage reports, and static dashboards. Run `quant-trade ml run --config configs/ml/ml_baseline_synthetic.yaml`. It does not support live trading, broker orders, auto-deployment, reinforcement learning, deep learning, or real-money readiness; ML artifacts always set `real_money_ready=false`. See `docs/ML_ALPHA_LAB.md` and `docs/ML_LEAKAGE_PREVENTION.md`.
