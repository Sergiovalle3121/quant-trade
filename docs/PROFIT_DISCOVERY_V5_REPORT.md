# Profit Discovery V5 — Final Report

Sprint: 2026-07-24 · branch `claude/profit-discovery-v5` · PR #42

## Status block

```
BASE_SHA: f3be7a8
FINAL_SHA: db10d3e (code-complete; this report is the docs-only commit on top)
TESTS: 590 passed, 0 failed (python -m pytest) · ruff clean · mypy clean (245 files)
P0_FALSE_PROFITS_CLOSED: A (instrument identity), B (poll/settlement semantics),
  C (stateful ledger), D (causal aggregation + applied gross cap),
  E (reproducible promotion), F (evidence bundle validator)
LIVE_BACKFILL: NOT_RUN_NETWORK_BLOCKED (proxy 403; data/carry/backfill_attempts.jsonl)
TRADING_OPPORTUNITIES_ELIGIBLE: 0 (H1–H3 NOT_RUN_NO_DATASET)
MINING_OPPORTUNITIES_ELIGIBLE: 0 (all cells POLICY_BLOCKED)
CHAMPION: cash_usd
PAPER_ALLOCATION: 100% cash (paper only)
REAL_MONEY: NO-GO
LIVE_ORDER_SUBMISSION: DISABLED
MINER_EXECUTION: DISABLED
MINING_HARDWARE_CONTROL: DISABLED
WALLET_SIGNING: DISABLED
AWS_RESOURCES_CREATED: FALSE
ALIBABA_RESOURCES_CREATED: FALSE
EXTERNAL_SPEND_AUTHORIZED: FALSE
```

## What this sprint closed (P0 — fictitious profits)

Every fix landed red-test-first (`tests/test_v5_defect_reproduction.py`).

**A — Strict instrument identity.** `carry/instruments.py`: a campaign series
is one frozen identity (venue | symbol | spot/perp instrument | contract |
quote | settlement | funding interval). Mixed identities in one store fail
closed — cross-instrument price moves can no longer masquerade as basis P&L.
Provenance comes from the full-dataset manifest (mixed ⇒ never "real"), not
from the first record.

**B — Event semantics.** `carry/store.py`: polls/backfills are QUOTE
observations and never settle funding; `funding_settlement` events dedup by
venue|symbol|funding-time; predictions never enter realized P&L. 90 re-polls
of one 8-hour rate now accrue at most one settlement, not ninety.

**C — Stateful cash-and-carry ledger.** `carry/ledger_engine.py`: explicit
account simulation (cash, per-leg quantities, posted margin, per-fill fees,
collateral yield, carrying costs, mandatory terminal close) with a
reconciliation identity — `final_equity − initial_capital == Σ components` —
checked to 1e-9·capital. Entries gate through the two-leg execution state
machine: partial fills below the minimum fill rate abort and book the
emergency-unwind cost as real money.

**D — Causal aggregation + applied caps.** Funding accrues only from settled
events inside `(t[i-1], t[i]]`; multiple settlements per bar all count;
walk-forward windows keep position continuity (no cash reset). Clock-skew
fail-closed applies to polls (quote capture must be near-simultaneous);
backfilled settlements are historical by construction. `max_gross_exposure`
is now ENFORCED in `backtest/multi_asset.py` — order-time sizing cap plus
per-bar proportional drift trims (report-only behaviour drifted to 0.5485
gross under a 0.5 cap; enforced behaviour holds ≤ 0.5006) — and refuses to
combine with `allow_leverage` rather than being silently ignored.

**E — Reproducible promotion.** `carry/promote.py` + `quant-trade carry
promote`: clean-room rebuild from config + dataset, byte comparison of every
artifact (`results.json`, `dataset_manifest.json`, `net_returns.csv`),
fail-closed ladder (missing evidence → dataset tampered → rebuild failed →
not reproducible → artifact-recomputing review; max PAPER_CANDIDATE). The
committed drill (`configs/carry/cash_and_carry_demo_file.yaml`) reproduces
byte-for-byte and is still REJECTED because its dataset is honestly
synthetic — see `artifacts/v5/PROMOTION_REPRODUCIBILITY_REPORT.json`.

**F — Evidence bundle validator.** `cloud_rental/bundle.py`: exact
quote↔spec↔benchmark↔policy identity (cross-SKU/provider/region/accelerator/
algorithm mismatches reject), SHAs byte-verified against files on disk,
fixture-sourced bundles TEST_ONLY forever.

## Discovery infrastructure (P1)

- **Funding backfill** (`quant-trade carry backfill`): Bybit/OKX public
  endpoints, pure parsers separated from fetch, response-symbol identity
  fail-closed, raw bytes preserved content-addressed, every attempt logged
  verbatim. Live attempts from this sandbox: `NOT_RUN_NETWORK_BLOCKED`
  (`URLError: Tunnel connection failed: 403 Forbidden`) — recorded in
  `data/carry/backfill_attempts.jsonl`.
- **Pre-registration** (`docs/PROFIT_HYPOTHESES_V5.md`): H1–H5 registered
  with fixed identities, signals, gates, and falsifiers BEFORE any campaign.
- **Scanners + board + allocator** (`quant-trade opportunities …`):
  `scan-trading` (pre-registered hypotheses only; NOT_RUN rows stay visible),
  `scan-mining` (per-cell precedence: incoherent bundle → POLICY_BLOCKED →
  MISSING_EVIDENCE → economics; blocks are never out-ranked), `rank` (unified
  board vs cash), `allocate-paper` (paper capital only; ineligible rows get
  zero; cash absorbs the residual exactly).

## Current honest verdict

| Artifact | Result |
|---|---|
| `artifacts/v5/TRADING_OPPORTUNITY_LEADERBOARD.json` | H1–H3 `NOT_RUN_NO_DATASET` (backfill blocked by proxy 403) |
| `artifacts/v5/MINING_RENTAL_MATRIX.json` | AWS `POLICY_BLOCKED:BLOCKED_PENDING_WRITTEN_APPROVAL` (Service Terms §1.25); Alibaba ×2 `POLICY_BLOCKED:BLOCKED_PROVIDER_POLICY` |
| `artifacts/v5/UNIFIED_OPPORTUNITY_BOARD.json` | Champion: `cash_usd`; 0 challengers eligible |
| `artifacts/v5/PAPER_CAPITAL_ALLOCATION.json` | 100 % cash, paper only |
| `artifacts/v5/PROMOTION_REPRODUCIBILITY_REPORT.json` | reproduced byte-for-byte: true · status REJECTED (data not real) |

**No profitable opportunity was found, and none was invented.** On current
evidence, cash beats every candidate: trading hypotheses cannot run without
real settled-funding history (network blocked, verifiably), and every
rented-mining cell is policy-blocked (the AWS terms-vs-blog ambiguity was
NOT resolved in favor of hashing). The platform now discovers, validates,
reproduces, and ranks opportunities honestly the moment real evidence
arrives: collect quotes with `carry collect-once`, backfill settlements with
`carry backfill` from an unblocked network, and the pre-registered H1/H2
campaigns, the board, and the paper allocator run unchanged.

## What did NOT happen (safety)

No live orders (paper or real), no API keys read or written, no miner
downloaded or executed, no cloud instance created or priced-for-purchase, no
wallet touched, no spend authorized, no threshold lowered, no holdout used
for tuning, no synthetic data presented as real profitability.

## Next steps (for the owner)

1. Run `quant-trade carry backfill --venue bybit|okx` from a network that can
   reach the public endpoints (or import history and verify SHAs); polls via
   `carry collect-once` on a schedule.
2. Once ≥ 30 settlements exist per venue, `opportunities scan-trading` runs
   H1/H2 exactly as registered; promotion requires `carry promote` to
   reproduce byte-for-byte.
3. Mining stays blocked unless AWS written approval materializes; the matrix
   recomputes with `opportunities scan-mining` when policy evidence changes.
