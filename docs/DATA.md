# Historical Data Layer

Phase 3 adds research-only historical OHLCV ingestion. It does not implement live trading, broker connectivity, order routing, or real-money execution.

## Canonical schema

Normalized data uses `timestamp` (timezone-aware UTC), `symbol`, `open`, `high`, `low`, `close`, `volume`, optional `adjusted_close`, `provider`, and `interval`. Backtests remain compatible with the core `timestamp/open/high/low/close/volume` columns.

## Providers

- `csv`: offline local files for reproducible research.
- `synthetic`: deterministic generated daily bars for tests and demos.
- `yfinance`: optional prototype data; install with `python -m pip install -e ".[data]"`.
- `polygon`: REST aggregate skeleton reading `POLYGON_API_KEY` from the environment; tests must mock HTTP.

YFinance data can be revised, incomplete, adjusted differently across time, and is not institutional-grade. Paid-provider adapters should be validated before research conclusions.

## Quality and bias warnings

Validation rejects empty datasets, missing columns, duplicate timestamps, invalid OHLC relationships, non-positive prices, and negative volume. Researchers must still account for adjusted versus unadjusted prices, survivorship bias, lookahead bias, corporate actions, timezone/session differences, and delisted symbols.

## Cache and manifests

Fetched datasets are written under `data/cache/<provider>/<symbols>/<interval>/` as CSV plus a `.manifest.json` containing request metadata, row counts, timestamps, columns, SHA-256, validation status, and quality warnings. Cache files are not overwritten unless `--force-refresh` is set. Do not commit downloaded data.

## CLI workflow

```bash
quant-trade data fetch --provider synthetic --symbol SPY --start 2020-01-01 --end 2020-12-31 --interval 1d
quant-trade data validate --path data/cache/synthetic/SPY/1d/SPY_2020-01-01_2020-12-31_adjusted.csv
quant-trade data info --path data/cache/synthetic/SPY/1d/SPY_2020-01-01_2020-12-31_adjusted.csv
quant-trade data list-cache
quant-trade backtest --strategy buy_and_hold --data data/cache/synthetic/SPY/1d/SPY_2020-01-01_2020-12-31_adjusted.csv --initial-cash 10000
```

Config-driven fetch:

```bash
quant-trade data fetch --config configs/data/synthetic_spy_daily.yaml
```

Set secrets only in your local environment, never in Git:

```bash
export POLYGON_API_KEY="..."
export DATA_CACHE_DIR=data/cache
```


## Versioned research data lake

Phase 15 adds `src/quant_trade/datalake/` for offline dataset registration, versioning, snapshots, contracts, quality checks, and lineage reports. Local data lake artifacts are generated under `data/lake/` and must not be committed except placeholder documentation files.
