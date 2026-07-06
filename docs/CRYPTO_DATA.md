# Crypto market data (research-only)

The `ccxt-<exchange>` provider family fetches spot and linear-perpetual OHLCV
plus perpetual funding-rate history from any ccxt-supported exchange using
**public market-data endpoints only**. No API keys, no account access, no
order routing. This layer exists to let the research lab run on real crypto
history; it does not enable live trading.

## Install

```bash
python -m pip install -e ".[crypto]"
```

## Symbology

Symbols use a path-safe dashed form that maps to ccxt unified symbols:

| Request symbol   | ccxt market      | Meaning            |
| ---------------- | ---------------- | ------------------ |
| `BTC-USD`        | `BTC/USD`        | spot               |
| `ETH-USDT`       | `ETH/USDT`       | spot               |
| `BTC-USDT-PERP`  | `BTC/USDT:USDT`  | linear perpetual   |

## Backfill OHLCV

```bash
# Daily majors from Kraken (copy the .example config first)
quant-trade data fetch --config configs/data/ccxt_crypto_majors_daily.yaml

# Or ad hoc:
quant-trade data fetch --provider ccxt-kraken --symbol BTC-USD --symbol ETH-USD \
  --start 2020-01-01 --end 2025-12-31 --interval 1d

# 4h bars for medium-frequency research
quant-trade data fetch --provider ccxt-kraken --symbol BTC-USD --interval 4h \
  --start 2022-01-01 --end 2025-12-31
```

Fetches paginate with a `since` cursor until the requested end (exchange page
caps are handled), retry transient network errors with bounded backoff, and
respect ccxt's built-in exchange rate limits. If any requested symbol fails or
returns no bars, the whole fetch fails loudly — a partial panel is never
written to the cache.

Every fetch runs the data-quality report with a **24/7 calendar**: missing
bars beyond tolerance and extreme return spikes (robust MAD outliers — the
fat-finger signature) are printed as warnings and recorded in the cache
manifest. Inspect warnings before using a dataset for research.

## Funding rates (perpetuals)

Funding is the dominant carry term for perp strategies and a required input
for the future funding-aware cost model:

```bash
quant-trade data fetch-funding --provider ccxt-binance \
  --symbol BTC-USDT-PERP --symbol ETH-USDT-PERP \
  --start 2023-01-01 --end 2025-12-31
```

Writes `timestamp, symbol, funding_rate, provider` rows under
`data/cache/ccxt-<exchange>/funding/`.

## Research on crypto data

Copy `configs/research/ts_momentum_crypto_daily.example.yaml`, point
`data_path` at your cached CSV, and run:

```bash
quant-trade research run --config configs/research/ts_momentum_crypto_daily.yaml
```

Notes:

- Metrics annualize using the observed bar density (`periods_per_year`), so
  crypto daily data annualizes at ~365 bars/year automatically.
- The example configs use a conservative retail taker cost profile
  (10 bps fee + 5 bps slippage + 3 bps half-spread per side). Do not lower
  these without measured fills from paper sessions.
- Every research run records the dataset file's sha256 in
  `config_used.yaml` (`dataset_binding`) so results are auditable against
  the exact bytes consumed.

## Boundaries

- Downloaded market data lives under `data/cache/` and is git-ignored.
  Never commit datasets.
- Public endpoints only. Adding authenticated endpoints, keys, or any order
  routing requires explicit human approval per repository policy.
- Some execution environments (CI, restricted sandboxes) block exchange
  hosts; backfills must run from a network that allows them. CI tests use an
  injected fake exchange and never touch the network.
