# Pre-registered Profit Hypotheses — V8

Registered `2026-07-28T06:30:00Z` at commit
`596c2accd5c535f3c537a4439a96b94e521e4018`, **before** any V8 campaign ran.
The machine-readable source of truth is
`src/quant_trade/v8/preregistration.py`; this document explains it.

Freeze hash: `b21483449a7e1e1917f59458012fd236353d536d5ca19412af4627f86e659678`

The hash covers the hypotheses, their variants, the gates and the splits. It is
written into every campaign artifact. If any registered parameter changes after
results are seen, the hash changes with it and the artifacts no longer agree —
which is the only mechanism that makes "we pre-registered this" checkable
rather than assertable.

All V5/V6/V7 binding rules remain in force: no holdout tuning, no lowered
gates, every trial counted, `PAPER_CANDIDATE` is the maximum status any
research run may confer, and fixture or recorded provenance is never
promotable.

## Primary hypotheses

### H1 — Bybit BTC spot/perp cash-and-carry

Long `BTCUSDT` spot, short `BTCUSDT` linear perpetual, held delta-neutral,
earning settled funding.

- **Signal:** trailing mean of the *settled* funding series, held constant
  between settlements. Announced and predicted rates carry no entry authority.
- **Periodicity:** 1h bars; funding accrues only at settlement instants.
- **Variants (4):** `entry_threshold ∈ {0.00005, 0.0001}` × `trailing_window ∈
  {3, 6}`. The same four as V6/V7 — no grid expansion.
- **Costs:** conservative Bybit stack; 1×/2×/3× reported.
- **Benchmarks:** cash, buy-and-hold BTC.

### H2 — OKX BTC spot/swap carry on settled `realizedRate`

The same structure on `BTC-USDT` / `BTC-USDT-SWAP`, driven strictly by OKX's
settled `realizedRate`. `fundingRate` is used only where OKX published no
realized value, and every such row is counted and reported.

### H3 — Bybit/OKX funding dispersion, full venue-switching cost

Long the lower-funding perpetual, short the higher-funding perpetual, collecting
the settled spread. Requires **both** venue panels. Prices four fills plus a
capital transfer on every direction change, and the unhedged window while
capital moves.

H3 must beat `max(H1, H2, cash)`. Two-venue operation is materially more complex
and more fragile than one-venue operation; if it does not beat the better single
venue, it is not worth running regardless of its standalone return. The relative
gate is applied after all three campaigns complete and can only **demote** H3,
never promote it.

## Additional hypotheses — registered, locked

H6 and H7 are registered here so that, if they are ever run, they were not
chosen after seeing H1–H3's results. They unlock only when H1–H3 have been
**measured and rejected** — a campaign that never ran has not tested anything,
and moving on would be starting a second search while the first is open.

- **H6:** low-turnover BTC/ETH time-series momentum with 10% annual volatility
  targeting. Variants: `lookback_days ∈ {90, 180}`.
- **H7:** low-turnover BTC/ETH/cash relative rotation, unlevered. Variants:
  `lookback_days ∈ {60, 120}`.

Combined cap: **8 variants**. Both are spot-only; H7 forbids leverage outright.

## Data splits

Chronological, never random: 50% train, 30% walk-forward, 20% holdout, holdout
most recent. Walk-forward is purged and embargoed (`train=720`, `test=240`,
`step=240`, `purge=6`, `embargo=1`).

The holdout is enforced by `HoldoutGuard`, not by convention: the rows are
unreachable until the variant selection is frozen, may be revealed exactly once,
and the access is recorded in the artifact. Selecting after revealing, or
revealing twice, raises.

## Promotion gates

Unchanged from V7. Duplicated in code rather than read from configuration so no
runtime input can relax them.

| Gate | Threshold |
|---|---|
| Span | ≥ 730 days |
| Unique settled funding events | ≥ 1,000 (polls never count) |
| Walk-forward windows | ≥ 5, majority positive |
| Probabilistic Sharpe | ≥ 0.95 |
| Deflated Sharpe | ≥ 0.95, over the global trial count |
| CSCV PBO (rank-based) | ≤ 0.50 |
| Bootstrap P05 of total return | > 0 |
| Net return at 2× costs | > 0 |
| Net return at 3× costs | reported |
| Liquidations / margin breaches | zero |
| Ledger reconciliation | exact |
| Benchmarks | beats cash **and** buy-and-hold |
| Holdout | frozen selection, revealed exactly once |
| Provenance | receipt-verified live capture |
| Cost evidence | `REAL` — captured from the venue, not assumed |

The last row is the one that blocks everything else today. Fee schedules could
not be captured, so the cost stack is `ASSUMPTION_UNVERIFIED` and no campaign
can promote regardless of its returns.

## Falsifiers

Per hypothesis, declared in advance:

- net marked-equity return ≤ 0 over the campaign;
- net return ≤ 0 at 2× costs;
- bootstrap P05 ≤ 0;
- a majority of walk-forward windows negative;
- any liquidation or maintenance-margin breach along the path;
- does not beat cash; does not beat buy-and-hold;
- (H3 only) does not beat `max(H1, H2)`, or either venue panel is missing.

## Cost treatment

Every friction carries an evidence class. Unverified inputs are chosen at or
above the venue's published *retail* rate, so they overstate cost — an
overstated cost can reject a strategy that would have worked, but cannot promote
one that would not.

Charged **per leg** across the round trip's four fills (buy spot + sell perp on
entry, sell spot + buy perp on exit): the spot taker fee on the two spot fills,
the perp taker fee on the two perp fills, and half-spread, slippage, market
impact and latency/partial-fill adverse selection on all four. H3 is perp/perp
and pays no spot fee at all. Priced continuously: collateral opportunity cost,
perp maintenance drag. Priced once: conversion/withdrawal, emergency-unwind
reserve, and (H3) cross-venue transfer.

Break-even at 1× costs, 30-day hold, 8h settlements:

| Hypothesis | Round trip | Break-even per settlement | Annualised |
|---|---|---|---|
| H1 | 45 bps | `0.00010776` | 11.80% |
| H2 | 44 bps | `0.00010665` | 11.68% |
| H3 | 36 bps + transfer | `0.00011443` | 12.53% |

## Environment fact recorded at registration

Outbound HTTPS to every venue-published domain — `api.bybit.com`,
`api.bytick.com`, `api.bybit.nl`, `www.okx.com`, `aws.okx.com`, `my.okx.com` —
is refused by this environment's egress policy with `CONNECT ... 403 Forbidden`,
recorded verbatim in `artifacts/v8/NETWORK_REACHABILITY_PROBE.json` and
`data/v8_evidence/*/attempts.jsonl`. No proxy, mirror or third-party
redistributor was used to route around it.

Until that changes, every campaign terminates at `NOT_RUN_NO_EVIDENCE`, which
is an acquisition failure and not an economic verdict on any hypothesis here.
