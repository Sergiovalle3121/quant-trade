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

### Offline research audit

The local BYOD auditor checks byte bindings, basic look-ahead signatures,
timestamp causality, next-bar execution, costs, benchmarks, and the trial
ledger without executing customer code or using the network:

```bash
quant-trade audit init --package-dir ./my-research --evaluation-cutoff-utc "2024-12-31T23:59:59Z"
quant-trade audit run --config configs/audit/clean.yaml --out-dir artifacts/audit-clean
quant-trade audit verify --bundle artifacts/audit-clean/audit.json
```

`init` builds the package skeleton with both SHA-256 digests already computed,
so a clerical slip cannot masquerade as unbound results; `verify` recomputes a
delivered bundle's digest from its own bytes, needing no access to the original
inputs. `run` exits 0/1/2 for PASS/INSUFFICIENT_EVIDENCE/NO_GO and takes
`--redact` to keep local paths out of a delivered report. Row ordering is checked
per instrument, so a panel exported as `(symbol, timestamp)` is causal rather
than a false `NO_GO`. Every check carries `finding_class`: `DEFECT` for an error
in the method, `RESULT` for a correctly measured outcome such as not beating a
benchmark — the verdict is unchanged, the report just stops conflating the two.

It emits deterministic JSON/HTML and always leaves
`real_money_authorized=false`. Sample outputs are committed under
`artifacts/audit-sample/`. See `docs/QUANT_RESEARCH_AUDITOR.md`, the bounded
customer-validation process in `docs/AUDIT_PILOT_PLAYBOOK.md`, and the pilot
packaging in `docs/CLAUDE_REVENUE_PILOT.md`.

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
- Cost models are configurable but still simplified relative to real venues. Omitting the
  `costs` block resolves to conservative defaults (5 bps commission, 5 bps slippage, 2 bps
  spread); a frictionless backtest requires explicitly setting every cost field to zero.
- Causality is enforced by regression tests (`tests/test_no_lookahead.py`): decisions on bar t
  fill at bar t+1's open in both the backtest engines and the paper simulator, and golden-file
  tests (`tests/test_golden_regression.py`) fail CI on silent P&L drift.
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

The data layer normalizes OHLCV bars to a canonical UTC schema, validates quality (including bar-gap and return-spike detection), writes a local CSV cache, and stores JSON manifests. Do not commit downloaded data, API keys, secrets, or `.env` files. This project remains research/backtesting only and includes no live trading or broker execution.

## Crypto market data (research-only)

The `ccxt-<exchange>` providers fetch spot/perpetual OHLCV and funding-rate history from public exchange endpoints (no keys, no order routing):

```bash
python -m pip install -e ".[crypto]"
quant-trade data fetch --provider ccxt-kraken --symbol BTC-USD --symbol ETH-USD --start 2020-01-01 --end 2025-12-31 --interval 1d
quant-trade data fetch-funding --provider ccxt-binance --symbol BTC-USDT-PERP --start 2023-01-01 --end 2025-12-31
```

See `docs/CRYPTO_DATA.md` for symbology, pagination/rate-limit behavior, quality checks, and crypto research configs. Every research run records the dataset's sha256 (`dataset_binding`) for reproducibility.

The low/mid-cap Bybit study is currently blocked from P&L generation: its
first constructed panel was invalidated after a causal audit. See
`docs/CRYPTO_VALIDATION_GATES.md` for the fail-closed rebuild, experiment,
promotion, shadow, and canary contract. Legacy research/promotion commands
reject `crypto_*` strategies so the venue-specific evaluator cannot be
bypassed.

The replacement H2 acquisition path is Binance-only and selection-only. It
hashes every permitted historical CMC day, hard-caps requests at 2023-11-28,
and supports exact resumable batches. Its current real-data manifest is
`INSUFFICIENT_EVIDENCE` because the normalized daily rows lack a causal
stablecoin classification; no P&L may be generated from that symbol plan.
See `docs/BINANCE_H2_DATA_ACQUISITION.md`.

The separately sealed BTC weekly-momentum translation was also falsified on
development data. It returned 255.73% but trailed BTC buy-and-hold's 776.15%,
beat BTC in 0/4 contiguous blocks, and suffered an 80.84% maximum drawdown.
It is retired as `NO_GO`; no lookback, threshold, weekday, or exposure variant
may be introduced after observing that result. See
`docs/BINANCE_BTC_WEEKLY_MOMENTUM_DEVELOPMENT_VERDICT.md`.

A distinct one-trial cross-sectional momentum declaration now ranks 30-day
returns only inside a point-in-time top-100 liquidity cohort and produces a
paired top-20 liquidity control. Its development evaluator is deliberately
fail-closed: real bundles stop after their manifest, before any market JSONL
is opened, while an explicitly synthetic mode only exercises Friday fills,
the paired control, benchmarks, filters and 2x-cost/50%-fill stress. It can
return only `NO_GO` or `INSUFFICIENT_EVIDENCE`, never `PASS`. Local hashes and
a receipt labelled `live` do not authenticate Binance symbol rules; schema v2
therefore exposes no executable rule. Exchange filters also remain quoted in
USDT and require point-in-time FX, fees and external source attestation before
economic evaluation. See `docs/BINANCE_LIQUID_XSMOM_CAMPAIGN.md` and
`docs/BINANCE_LIQUID_XSMOM_DEVELOPMENT_EVALUATOR.md`.

The next economically distinct candidate, AANV30 on-chain value, remains a
data-feasibility backlog rather than a strategy. Its offline gate requires 30
exact daily active-address observations, point-in-time market cap, stable
chain/contract/CMC identity, reproducible method bytes, commercial-use terms
and at least 100 completely covered assets. Passing that gate would authorize
only a future preregistration—not a signal, P&L, holdout access or trading.
Current project evidence is therefore `INSUFFICIENT_EVIDENCE`. See
`docs/AANV30_DATA_FEASIBILITY.md`.

A second data-only backlog tracks the published `world order flow` family.
The paper input is CryptoCompare/CCData buyer- and seller-initiated volume,
aggregated across exchanges in 11 fiat currencies on its own 30-observation
calendar. A Binance USDT kline is explicitly rejected as a substitute. The
public CCData terms, exact historical signed-volume contract and point-in-time
vintages are not yet authenticated for commercial use, so schema v1 can never
advance beyond `INSUFFICIENT_EVIDENCE` and authorizes no model or backtest. See
`docs/WORLD_ORDER_FLOW_DATA_FEASIBILITY.md`.

BTC cash-and-carry is tracked as a separate, derivatives-based research path,
not as an exception to the Spot-only canary policy. With a US$200 research
budget, the conservative capital envelope reserves US$40 and can match about
US$80 of spot with US$80 of isolated 1x perpetual exposure. That is only
technical sizing, not expected profit: schema v1 remains
`INSUFFICIENT` until a trusted external attestation root and parsers bind the
venue, account, funding, basis, fees, liquidation, FX, legal, tax and
counterparty evidence bytes. It contains no P&L or derivatives execution path.
See `docs/BTC_CASH_AND_CARRY_FEASIBILITY.md`.

For Alpaca, the repository now contains a separate SPY turn-of-the-month
research campaign, a GET-only evidence collector and an isolated US$200 Paper
sleeve. The collector downloads only the exact preregistered event windows,
enforces bounded pagination and content-addressed receipts, and never calls
account, order, position or transfer endpoints. The development evaluator is
deliberately limited to `INSUFFICIENT_EVIDENCE` until an external authority
attests the calendar, SIP market data, corporate actions and fee vintages. The
Paper sleeve prevents duplicate plans, stale-state resets and campaign forks,
but it is simulation infrastructure—not evidence of profitability and not a
live-money adapter. See `docs/ALPACA_SPY_TOM_READONLY_COLLECTOR.md`,
`docs/SPY_TURN_OF_MONTH_CAMPAIGN.md`,
`docs/SPY_TURN_OF_MONTH_DEVELOPMENT_EVALUATOR.md` and
`docs/ALPACA_USD200_PAPER_SLEEVE.md`.

Small-capital arithmetic is kept separate from strategy evidence. The
fail-closed planner distinguishes total risk capital from a canary and flags
the 1,000x-in-one-month shortcut as `NO_GO`; it never authorizes a deposit or
profit claim. See `docs/WEALTH_BUILDING_PLAN.md`.

Two further arithmetic gates run before any data is opened, so a target or a
strategy family that could never have worked does not consume a trial:

```bash
quant-trade wealth target-feasibility --start 100 --target 1000000 --days 30
```

`quant_trade.ops.growth_feasibility` adds the stochastic layer the planner
lacks. Under a declared lognormal model, raising volatility does not
monotonically raise the chance of a large multiple: the variance drag caps it at
a finite optimum, and at that optimum the median outcome is exactly the starting
capital divided by the target multiple. Reaching 10,000x in 30 days therefore
tops out at about 1 in 112,915 with no edge, and would need a net Sharpe of 9.23
for even a 5% chance — no volatility, leverage, or sizing changes that.
`quant_trade.ops.family_screen` applies the same discipline to a strategy
family, naming the binding constraint (`min_notional`, `cost_drag`,
`fixed_data_cost`, `data_license`, `no_point_in_time_data`). Both are pure
functions, emit `ASSUMPTION`-classed output, and authorize nothing. The applied
results, the venue matrix, and the family matrix are in
`docs/CLAUDE_ALPHA_SEARCH_REPORT.md`; the audit-pilot counterpart is
`docs/CLAUDE_REVENUE_PILOT.md`.

Net-money measurement is also separate from alpha. The offline MXN tax-lot
ledger reconciles FIFO inventory, event-time FX, fees, observed slippage,
realized/unrealized P&L and minimum funding. Tax fields remain empty unless the
operator supplies an explicit sensitivity scenario; they are not legal or tax
advice. See `docs/AFTER_TAX_TCA_MXN.md`.

## Alpha components and statistical validation

The research lab includes a volatility-targeted multi-horizon momentum signal (`multi_horizon_tsmom`), Donchian breakout with ATR exits (`donchian_breakout`), and perpetual funding carry (`funding_carry`, requires funding data joined via `attach_funding_rates`). The multi-asset engine supports shorts (explicit `allow_short`), per-bar funding accrual, and no-trade rebalance bands (`portfolio.rebalance_band`).

Every backtest evaluation appends to an append-only trial ledger (`outputs/trial_ledger.jsonl`); research runs emit `results.json` with PSR and return moments, and the selection layer gates on trade count, probabilistic Sharpe, and the ledger-driven deflated Sharpe ratio. Train/test splits support an embargo (`split.embargo_bars`). See `docs/STATISTICAL_VALIDATION.md`.

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


## Phase 15: Data Lake v2 + Dataset Versioning

The project now includes a research-only versioned data lake (`quant-trade datalake ...`) for local CSV registration, immutable versions, snapshots, contracts, quality reports, provider comparison utilities, lineage artifacts, and a static dashboard. Generated market data artifacts remain ignored by git and are not approved for live trading. See `docs/DATA_LAKE.md`, `docs/DATASET_VERSIONING.md`, and `docs/DATA_CONTRACTS.md`.
