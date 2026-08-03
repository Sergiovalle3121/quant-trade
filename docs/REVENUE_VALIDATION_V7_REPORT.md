# Revenue Validation & Controlled Monetization V7

Evaluation clock: `2026-07-25T06:00:00Z`
Base: `98daabe6585bfa80d7706a61c8742d5da8ac9ea3`
Regeneration: `make v7-artifacts SOURCE_COMMIT_SHA=<code-commit-sha>`

## Economic verdict

V7 found no promotable non-cash opportunity. This is the fail-closed result,
not a missing winner:

- receipt-verified `REAL` raw pages captured locally: **5**;
- verified real funding settlements captured locally: **6**;
- trading `PAPER_CANDIDATE` rows: **0**;
- real cloud quotes / exact-SKU benchmarks / market snapshots: **0 / 0 / 0**;
- eligible mining candidates: **0**;
- paper allocation: **100% cash**;
- shadow: **not started**, because an all-cash session would add no economic
  evidence.

The 4% cash input is a byte-verified `RECORDED_RESPONSE`, not `REAL` evidence.
It exercises ranking deterministically but cannot promote a non-cash row.

No public Bybit capture has completed. An earlier revision of this report
described a clean 41-row panel for `2026-07-20T00:00:00Z` through
`2026-07-21T16:00:00Z` and quoted a panel SHA-256 for it; that digest
corresponded to no bytes, here or anywhere, and the claim is withdrawn rather
than reissued. The only machine record of the attempt is
`data/carry/panel/bybit_btc/backfill_attempts.jsonl`, which reports
`status: NOT_RUN_NETWORK_BLOCKED` with 0 pages fetched, 0 panel rows and 0
settlements, against `URLError: Tunnel connection failed: 403 Forbidden`.
Raw market cache is intentionally not committed, and the repository campaign
reports H1/H2 as `NOT_RUN_NO_DATASET`.

## Implemented controls

### P0-A — provenance and historical panels

- Receipts use relative contained paths, reject traversal, form a hash chain,
  and recompute both raw and normalized hashes.
- Panel verification opens every raw page, reparses it in a clean rebuild, and
  byte-compares the rebuilt panel, audit and manifest.
- Range edges, interval, identity, timestamps, gaps, conflicting duplicates and
  missing settlements fail closed.
- Bybit funding history paginates to the requested lower bound with content
  deduplication.
- `REAL`, `RECORDED_REAL`, `RECORDED_RESPONSE`, `PAPER`, `SIMULATION` and
  `FIXTURE` are explicit; fixture evidence cannot promote.

### P0-B — one trading economic truth

- The authoritative return series is the marked-equity change from the ledger.
- Entry/exit fees, funding, spot/perp marks, borrow, conversion, slippage,
  transfers and terminal close flow through that series.
- The product-of-returns identity reconciles to final versus initial equity.
- Sizing reserves margin, both-side fees, conversion and a cash buffer.
- Signals advance on unique settlements and hold between events; duplicate or
  out-of-order inputs are rejected.

### P0-C — statistical validation and trials

- PBO is genuine rank-based CSCV over preregistered variants.
- The gate also requires stationary/block bootstrap P05, walk-forward, PSR and
  DSR.
- Conservative defaults require 730 days, 1,000 unique settlements, five
  walk-forward folds, PSR/DSR ≥ 0.95, CSCV PBO < 0.50, positive bootstrap P05,
  positive 2× costs and mandatory 3× reporting.
- Trial history is global, append-only and hash-chained; changing the output
  directory cannot reset it.
- H3 remains technically blocked until both real panels exist and it runs the
  same full statistical campaign.

### P0-D/E/F — rented mining

- Rental types are explicit: `COMPUTE_RENTAL`, `HASHPOWER_MARKETPLACE` and
  `MANAGED_ASIC_LEASE`.
- AWS hashing is `BLOCKED_PROVIDER_TERMS`; Alibaba hashing is
  `BLOCKED_PROVIDER_POLICY`. Control-plane permission is separate.
- The versioned Decimal unit registry uses TH/s for SHA-256, GH/s for
  KHeavyHash and MH/s for Etchash; no universal `/1e12` remains.
- The scanner opens and hashes quote, specification, policy, market and
  benchmark bytes, reconstructs benchmark claims from raw logs, and checks
  algorithm/coin/network identity.
- Compute-rental economics model billing minimum/granularity, availability,
  interruption, boot/restart, rejects and 1×/2×/3× risk scenarios with
  P05/P50/P95, loss probability and CVaR95.
- A provider-neutral marketplace evidence importer validates orderbook,
  jurisdiction, KYC, terms, liquidity and delivery records. Without delivery
  history it cannot exceed `DISCOVERY_ONLY`; it exposes no purchase or deposit
  operation.

### P0-G — board, allocation, shadow and paper safety

- Mining uses evidenced-horizon return on committed capital and is never
  multiplied by 8,766.
- Manual/unverified cash inputs cannot promote a candidate.
- Allocation is weighted by excess return, risk, liquidity and capacity; cash
  absorbs the residual.
- Shadow WAL/checkpoint state is atomic, fsynced, hash-chained, exactly-once and
  crash recoverable; frozen allocation and reconciliation are reverified.
- Paper market orders require a fresh positive reference mark. Broker order IDs
  are idempotent and conflicting reuse is rejected.

## Determinism and safety

`tests/test_v7_artifact_regeneration.py` generates all 11 JSON outputs twice
and compares every file hash. `PROMOTION_REPRODUCIBILITY.json` binds the
generated content to the base, source code commit and exact command.

No live order, wallet action, deposit, miner, cloud resource or external spend
is reachable from the regeneration path.

## Explicitly blocked or incomplete routes

The following work is not silently represented as complete:

1. A complete OKX kline/mark/index/funding panel backfill equivalent to Bybit
   is not implemented; H2/H3 remain `NOT_RUN_NO_DATASET`.
2. The hashpower marketplace importer exists, but a dynamic marketplace
   cash-flow engine covering payout, cancellation/refund and locked funds is
   not implemented; the route is capped at `DISCOVERY_ONLY`.
3. Exact compute benchmark metadata still needs real image/driver/runtime,
   binary/flags, stale-share, dev-fee and interruption-history evidence.
4. A short Bybit capture succeeded locally, but repository policy excludes raw
   market cache. Promotion remains blocked until an approved evidence store
   preserves the raw bytes/receipts and the full preregistered range is
   acquired.

These blocks leave all affected routes at zero allocation.
