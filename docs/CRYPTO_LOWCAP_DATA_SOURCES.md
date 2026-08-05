# Low/mid-cap crypto data sources — the point-in-time requirement

Session A, Block 1. Research only: no strategy design, no backtests.

The universe for any historical study must be **point-in-time**: which coins
existed, at what market cap, rank and volume, **on each past date** — not
today's coin list projected backwards. A universe built from today's listings
contains only survivors, and a backtest on survivors wins by construction
(see `docs/CRYPTO_LOWCAP_ANTIBIAS_PLAN.md`, Block 2).

Everything labelled MEASURED below was probed from this development
environment on 2026-08-04/05 with unauthenticated GET requests. Pricing is
quoted from vendor pages on the same date and is not a measurement.

## Connectivity from this environment (MEASURED)

The v7 session recorded Bybit returning `403 Forbidden`. That does **not**
reproduce here — the 403 was that environment's egress policy, not a Bybit
property. From this environment:

| Endpoint | HTTP |
|---|---|
| `api.bybit.com/v5/market/time` | 200 |
| `api.binance.com/api/v3/ping` | 200 |
| `api.coingecko.com/api/v3/ping` | 200 |
| `api.coinpaprika.com/v1/global` | 200 |
| `api.kraken.com`, `okx.com`, `kucoin.com`, `gate.io`, `mexc.com` public time/ping | 200 |
| `min-api.cryptocompare.com` (keyless) | 401 |

Network access is environment-dependent; any collector must record
`NOT_RUN_NETWORK_BLOCKED` with the verbatim error when blocked (the
`carry/panel_backfill.py` convention), never fabricate or silently skip.

## Candidate sources

### CoinMarketCap web data-api (undocumented) — MEASURED

`https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical?date=YYYY-MM-DD`
is the endpoint behind CMC's public "Historical Snapshots" pages. Measured
properties:

- **True point-in-time**: returns the listing as of the requested date with
  rank, price, market cap, circulating supply, volume24h per coin. Coins that
  later died appear in old snapshots (this is the survivorship fix).
- **Daily cadence, full depth of history**: earliest snapshot 2013-04-28;
  mid-week dates return exact-date data at least back to 2017-06-14; snapshots
  exist up to yesterday.
- **Depth per snapshot**: <2,001 coins in 2014 and 2017; <6,001 in 2021;
  <10,001 in 2024 and 2026. `limit=5000` returns 5,000 rows in one page, so a
  full day is 1–2 requests.
- **Free, no key.** ~50 probe requests drew no throttling; sustained-rate
  behaviour NOT_MEASURED (acquisition must rate-limit itself and treat 429/403
  as a first-class outcome).

Risks, stated plainly: the endpoint is **undocumented**. Schema drift, terms
of use, or a silent block can end it at any time. Mitigations: archive every
raw page content-addressed with ingestion receipts (existing
`evidence/receipts.py` machinery), fail loudly on schema mismatch, and keep a
documented paid fallback (below).

### Exchange-native klines — MEASURED

- **Bybit v5** (already integrated via `carry/panel_backfill.py`): reachable
  from here. `instruments-info` lists only 557 spot symbols with status
  `Trading` — the current list cannot enumerate dead symbols. But klines for
  **delisted** symbols survive: `SRMUSDT` (Serum, dead post-FTX) returns 2022
  spot klines. Given a symbol name from an external universe list, history is
  retrievable even for dead coins.
- **Binance REST**: klines for delisted symbols also survive (`BCCUSDT`,
  delisted 2018, returns data).
- **data.binance.vision** (public S3 dumps): monthly/daily kline zips retained
  for delisted symbols (`BCCUSDT-1d-2018-08.zip` → 200), and the S3 listing
  API enumerates every symbol prefix ever dumped (>1,000 on the first page,
  truncated), delisted included. This is the breadth backbone for actual
  tradable prices/volumes on a real venue.

Exchange klines answer "what did this coin trade at on this venue" — the
right price source, because a strategy can only trade venue prices. They do
not provide market cap or a cross-venue universe; that comes from the
snapshot source.

### CoinGecko — MEASURED (free tier) / quoted (paid)

- Free/keyless: `coins/list` returns 18,127 **active** coins; historical range
  queries beyond 365 days are rejected (`error_code 10012`, measured).
  Inactive-coin listing requires a paid plan.
- Analyst plan: **$129/month** (quoted 2026-08), full daily history to 2013,
  hourly from 2018, inactive coins included. This is the sanctioned,
  documented equivalent of the CMC data-api route.

### CoinPaprika — MEASURED (free tier) / quoted (paid)

- Free `/v1/coins`: 60,806 coins of which **48,992 are inactive**
  (`is_active: false`) — the largest free death-list found, and a strong
  cross-check for delisting/death dates.
- Free historical tickers are capped at the last 365 days and free OHLCV at
  the last 24 h (both measured as explicit plan errors). Deep history is paid
  (Pro tiers roughly $99+/month, quoted).

### Others

- **CoinMarketCap official API**: the documented `listings/historical`
  endpoint sits behind expensive tiers (Standard ~$3,588/yr-equivalent
  pricing; historical windows still capped per tier). Not viable at this
  capital size.
- **CoinAPI**: from $79/month, credit-metered; full-universe daily history
  would burn credits fast. NOT_PROBED (needs key).
- **CryptoCompare**: 401 without key; free key tier exists. Not evaluated
  further this session.
- **Kaiko / Coin Metrics / Amberdata**: institutional pricing, out of scope.
  NOT_PROBED.

## Assessment of `carry/panel_backfill.py` as a base (Block 1.2)

Reusable as-is: `fetch_public_bytes`, content-addressed raw archiving +
`IngestionReceipt` per page, `NOT_RUN_NETWORK_BLOCKED` semantics, repeated-page
fail-safe, fixture/live separation (`fixtures can never become real`).

Not sufficient as the universe collector: it is carry-specific (four kline
series + funding for one symbol), hardcodes `<BASE>USDT` symbology and Bybit
endpoints, and has no notion of a universe snapshot. The universe collector is
a **new module that reuses the same evidence machinery**, not an extension of
the carry backfill. Bybit klines remain the venue-price backbone where Bybit
lists (or listed) the coin.

## Recommendation (Block 1.3)

**Principal — two free sources composed:**

1. **Universe + market cap + rank, point-in-time**: CMC web data-api daily
   snapshots (2013→today), every raw page archived content-addressed with
   receipts, schema-validated, fail-loud.
2. **Venue prices/volume**: exchange-native klines — Bybit v5 (existing
   integration) plus `data.binance.vision` for breadth and delisted symbols.
   A strategy trades venue prices, so venue klines are the price truth;
   snapshot prices are only for universe construction and cross-checks.

Cross-check: CoinPaprika free coin list (48,992 inactive) to corroborate
death/delisting against universe disappearance.

**Backup (paid, requires explicit human approval per AGENTS.md):** CoinGecko
Analyst at **$129/month** — documented, includes inactive coins and full
history; the drop-in replacement if the undocumented CMC route breaks or its
terms become a problem. No paid integration is added in this session.

**Why this order**: the composition is free, point-in-time by construction,
covers dead coins from three independent angles (snapshots show them alive;
paprika flags them dead; venue klines price them to the end), and every byte
is archived and receipted so a later source failure cannot silently corrupt
history already acquired. The single-vendor paid alternative is simpler but
$1,548/year against a small capital base, and still needs the venue-price leg
for tradability.

## Acquisition sizing (informs Block 5)

~4,850 daily snapshots × 1–2 pages ≈ **7,500 requests** for the full
2013→today universe; at a self-imposed ~1 req/s that is 2–3 hours, resumable
and idempotent by content address. Venue klines are fetched per symbol
appearing in the universe, lazily.
