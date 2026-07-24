# Pre-registered Profit Hypotheses — V5 (Profit Discovery)

Registered: 2026-07-24T20:20Z, BEFORE any V5 campaign was executed.
Registered at commit: `5102dd2` (branch `claude/profit-discovery-v5`).

Rules of this registry (binding for the whole sprint):

1. Hypotheses, datasets, thresholds, and decision gates are FIXED here first.
   Campaigns run afterwards. A failed hypothesis is recorded as failed — it is
   never re-parameterised into a success and every attempt lands in the trial
   ledger under the same hypothesis id (multiplicity is counted, not hidden).
2. The holdout is never used for tuning. Gates are never lowered mid-sprint.
3. `PAPER_CANDIDATE` is the best possible outcome. Nothing in this sprint can
   authorize real money, live orders, miners, cloud resources, or spend.
4. Synthetic or fixture data can never produce a promotable result — campaigns
   on such data terminate at `NOT_RUN_INSUFFICIENT_REAL_DATA` / `TEST_ONLY`.

## Shared promotion gates (fixed, identical for every trading hypothesis)

- PSR ≥ 0.95 and DSR ≥ 0.95 (trial-count-adjusted, conservative counting)
- Stationary-bootstrap lower confidence bound on mean net return > 0
- PBO check run and reported; majority of OOS walk-forward windows positive
- Still positive at 2× modelled costs; zero liquidations in the ledger
- Settlement-causal accrual only (no poll multiplication); reconciled ledger
- Promotion must be byte-reproducible from config + dataset manifest (V5-4)
- Insufficient real history → `RESEARCH_CANDIDATE` or
  `NOT_RUN_INSUFFICIENT_HISTORY`, never a lowered bar

## H1 — BTC cash-and-carry funding capture (Bybit linear USDT perp)

- **Claim:** persistently positive settled funding on `bybit:BTCUSDT` makes a
  fully hedged long-spot/short-perp position profitable net of entry/exit
  friction, carrying costs, and margin drag, at 1× perp leverage.
- **Instrument identity (fixed):**
  `bybit|BTC|spot:BTCUSDT|perp:bybit:BTCUSDT|linear_perpetual|USDT|USDT|8h`.
- **Dataset:** settled funding via `quant-trade carry backfill --venue bybit`
  (public endpoint, settlements only) + point-in-time quote polls from the
  collector. Minimum history to run at all: 30 settlement events (~10 days).
- **Signal (fixed):** trailing mean of the last 3 settled rates > 0.00003 per
  interval (≈ 3.3%/yr gross at 8h intervals) enters; exit on signal loss.
- **Economics (fixed):** `configs/carry/` cost model; entry/exit friction per
  leg; `min_fill_rate = 0.9`; abort books the emergency-unwind cost.
- **Decision:** shared gates above → at best `PAPER_CANDIDATE`.
- **Falsifier:** bootstrap lower bound ≤ 0, or 2×-cost net ≤ 0, or the ledger
  fails reconciliation.

## H2 — BTC cash-and-carry funding capture (OKX linear USDT swap)

- Same claim, signal, economics, and gates as H1 on
  `okx|BTC|spot:BTC-USDT|perp:okx:BTC-USDT-SWAP|linear_perpetual|USDT|USDT|8h`,
  using `realizedRate` (settled) from the OKX public history endpoint.
- H1 and H2 are separate hypotheses in the trial ledger; running both counts
  as two trials for multiplicity adjustment.

## H3 — Cross-venue funding dispersion (Bybit vs OKX)

- **Claim:** the settled-funding spread between H1 and H2 instruments is wide
  and persistent enough that always holding the higher-funding venue (fully
  hedged on that single venue; NEVER a mixed-identity series) beats holding
  either venue alone, net of the extra switching friction.
- **Constraint:** the allocator switches between complete single-identity
  campaigns; return series from different identities are never concatenated.
  Each venue's leg is evaluated by its own ledger; switching cost = full
  exit + entry friction on both legs.
- **Decision:** shared gates, evaluated on the switched sequence, plus: must
  beat max(H1, H2) net return over the same window. Otherwise REJECTED.

## H4 — Rented-hashrate spread (provider × SKU × algorithm × coin)

- **Claim:** for some (provider, region, SKU, model, algorithm, coin) cell,
  renting hashrate and selling rewards yields NPV > 0 under pre-registered
  haircuts (reward variance, pool fees, stale shares, price path scenarios).
- **Method:** V5 mining scanner over the existing rental catalog + benchmark
  store; exact-SKU benchmark evidence required; cancelable-hourly economics.
- **Policy gates (fixed):** AWS hashing → `POLICY_BLOCKED` (Service Terms
  §1.25); Alibaba hashing → `BLOCKED_PROVIDER_POLICY`; unknown policy →
  `BLOCKED_POLICY_UNKNOWN`. Conditional economics may be computed while
  blocked but can never rank above the block. Missing benchmark/quote →
  `MISSING_EVIDENCE`, never a guess.
- **Decision:** cells rank in the opportunity board only with complete
  evidence bundles; blocked cells are reported as blocked. No provider
  resources are created and no miner runs in any case.

## H5 — Cash benchmark

- **Claim (null):** cash at the configured risk-free/collateral yield beats
  every candidate above after honest costs. Every board ranking includes cash;
  any candidate that cannot beat cash is `ECONOMIC_NO_GO`.

## Registered datasets

| Dataset | Source | Provenance rule |
|---|---|---|
| `data/carry/funding_history.jsonl` | collector polls + backfill settlements | mixed provenance → NOT_RUN |
| `tests/fixtures/bybit_funding_history.json` | canned raw bytes | TEST_ONLY, never promotable |
| `tests/fixtures/okx_funding_history.json` | canned raw bytes | TEST_ONLY, never promotable |
| Live Bybit/OKX endpoints | public, unauthenticated | blocked network → NOT_RUN with verbatim error |

## Environment fact recorded at registration

Outbound HTTPS to `api.bybit.com` and `www.okx.com` from this sandbox fails
with proxy `403 Forbidden` (CONNECT tunnel). Unless the network policy
changes mid-sprint, H1–H3 campaigns on LIVE data are expected to conclude
`NOT_RUN` with that verifiable error in `backfill_attempts.jsonl`; the full
pipeline is exercised offline on fixtures marked TEST_ONLY.
