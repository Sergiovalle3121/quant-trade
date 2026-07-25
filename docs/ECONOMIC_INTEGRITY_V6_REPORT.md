# Economic Integrity V6 — Final Report

Sprint: 2026-07-24/25 · branch `claude/economic-integrity-real-data-v6` · PR #43

```text
BASE_SHA: 1a9833a
FINAL_SHA: (head of PR #43; code-complete at 1232918 + this docs/artifacts commit)
BRANCH: claude/economic-integrity-real-data-v6
PR: #43 (draft — NO auto-merge this sprint unless the owner orders it)
CI_RUN: per-commit on the PR (green through the last push)
COMMITS: 9 (V6-0 … V6-9)
FILES_CHANGED: ~60
TESTS: 642 passed, 0 failed, 0 xfailed (python -m pytest)
RUFF: clean
MYPY: clean (251 source files)
COMPILEALL: clean

P0_A_LEDGER_WIRED: YES — run_carry_ledger is the only promotable P&L path;
  independent balance-sheet vs category-totals reconciliation; artifacts +
  promotion carry and byte-compare the ledger evidence
P0_B_SETTLEMENT_COUNT_FIXED: YES — sufficiency counts unique settlements
P0_C_COST_STRESS_FIXED: YES — same ledger/settlements/signals at 1x/2x/3x;
  fee_multiplier scales the venue taker fee; conversion cost charged
P0_D_PROVENANCE_FIXED: YES — byte-verified ingestion receipts; self-labels
  ignored; legacy JSON = unverified_legacy; fixtures TEST_ONLY forever
P0_E_CANONICAL_IDS_FIXED: YES — one canonical id per pair across adapters
P0_F_HISTORICAL_PANEL_EXECUTABLE: YES — panel source runs research
  end-to-end (proven on recorded pages; live build network-blocked)
P0_G_REAL_MARK_USED: YES — mark only from markPrice; last stays perp_last
P0_H_SIGNAL_USES_SETTLEMENTS: YES — settlement-held signal series in jsonl
  and panel paths; polls have zero entry authority
P0_I_H3_REAL: YES — perp-perp cross-venue engine with per-venue marks,
  transfer costs and reconciliation; H3 re-registered accordingly
P0_J_DSR_PBO_GATED: YES — promotion executes DSR (conservative trial
  counting) and a walk-forward PBO estimate with a 0.50 limit
P0_K_COMMON_UNIT_BOARD: YES — one unit (annualized net return on capital)
P0_L_BOARD_LINEAGE: YES — lineage + rows-hash verification; edited
  artifacts refuse to rank
P0_M_MULTI_ASSET_BOUNDARIES: YES — leveraged-cap policy enforced in engine,
  runner and walk-forward windows
P0_N_REAL_SHADOW_PARITY: YES — raw-log-bound drill evidence re-verified at
  evaluation; frame-replay parity; persistent shadow with kill switches
P0_O_MINING_EVIDENCE_CHAIN: YES (contracts) — sourced/byte-bound market
  snapshots, dimensional units, quote/spec raw binding, benchmark importer.
  DOCUMENTED GAP: live AWS/Alibaba capture CLIs not yet wired to adapters.

REAL_RAW_DATA_CAPTURED: 0 (network blocked; verbatim 403 evidence committed)
REAL_SETTLEMENTS: 0 verified (6 TEST_ONLY via recorded responses)
REAL_PANEL_ROWS: 0 (41 TEST_ONLY rows via recorded responses)
TRADING_CANDIDATES_EVALUATED: 3 (H1, H2, H3 — all NOT_RUN_NO_DATASET)
TRADING_PAPER_CANDIDATES: 0
BEST_TRADING_NET_ROC: n/a (no real data)
BEST_TRADING_LOWER_BOUND: n/a
BEST_TRADING_CAPACITY: n/a

REAL_CLOUD_QUOTES: 0
REAL_EXACT_SKU_BENCHMARKS: 0
MINING_CELLS_EVALUATED: 3 (all POLICY_BLOCKED; economics uncomputable —
  no sourced market snapshot exists, and inline numbers are rejected)
MINING_PAPER_CANDIDATES: 0
AWS_HASHING_POLICY: BLOCKED_PENDING_WRITTEN_APPROVAL (Service Terms §1.25;
  the terms-vs-blog ambiguity is NOT resolved in favor of hashing)
ALIBABA_HASHING_POLICY: BLOCKED_PROVIDER_POLICY (security-lock example)

BOARD_CHAMPION: cash_usd (annualized net ROC 0.04 baseline; 0 challengers eligible)
PAPER_ALLOCATION: 100% cash (paper only)
SHADOW_SESSION_STATUS: RUNNING (session shadow-…, frozen all-cash allocation,
  0 events processed, kill switches all ok)
SHADOW_RECONCILED: TRUE

REAL_MONEY: NO-GO
LIVE_ORDER_SUBMISSION: DISABLED
MINER_EXECUTION: DISABLED
AWS_RESOURCES_CREATED: FALSE
ALIBABA_RESOURCES_CREATED: FALSE
EXTERNAL_SPEND_AUTHORIZED: FALSE
```

## What was reproduced and closed

All 15 defects (A–O) were confirmed live at `1a9833a`, reproduced as 21
strict red tests FIRST, then fixed; every marker was removed only when its
fix landed (`tests/test_v6_defect_reproduction.py`,
`artifacts/v6/DEFECT_REPRODUCTION_MATRIX.json`). The suite grew 590 → 642
with zero xfails remaining.

## What is now integrated (CLI → research → artifacts → promotion → board → shadow)

- **One economic truth.** `run_carry_research` executes the balance-sheet
  ledger (cash mutated flow-by-flow with a journal; reconciliation compares
  two independent accounting paths); unreconciled books refuse to produce
  evidence; aborted two-leg entries reject the campaign; cost stress reruns
  the SAME ledger. Artifacts: `reconciliation.json`, `equity_curve.csv`,
  `funding_cashflows.jsonl` — all byte-compared by `carry promote`.
- **Authentic provenance.** Ingestion receipts at capture; provenance
  resolves only from verified receipts; the demo drill reproduces
  byte-for-byte and is still REJECTED (synthetic + DSR 0.937 + PBO 0.60 —
  the gates demonstrably fire).
- **Executable history.** `carry backfill-panel` / `panel-audit` build a
  point-in-time panel (klines + mark + index + settlements, no forward
  fill), consumed by `source: panel` with settlement-driven signals. Proven
  E2E on recorded pages; the live build records its 403 verbatim.
- **Comparable opportunities.** One unit on the board, verified lineage,
  cash always present; the paper allocator feeds the persistent shadow
  session (frozen allocation, idempotent replay, rebuilt-from-flows
  reconciliation, evaluated kill switches).

## Honest verdict

**No real profitability evidence exists, and none was fabricated.** Cash
remains the champion. Every trading hypothesis is NOT_RUN for lack of
receipt-verified real data (network-blocked, verifiably); every mining cell
is policy-blocked with economics uncomputable by design (no sourced market
snapshot). The entire discovery→validation→allocation→shadow path now runs
end-to-end the moment real evidence arrives.

## Exact blockers and next actions

1. **Real data:** run `quant-trade carry backfill-panel --venue bybit
   --symbol BTC --since-ms … --until-ms …` from an unblocked network (or
   import raw pages + receipts). ≥ 90 settlements per venue unlocks H1/H2.
2. **H3:** build both venue panels; the cross-venue engine and its gates are
   ready.
3. **Mining:** nothing proceeds without (a) written AWS approval or a
   permitted provider, and (b) sourced market snapshots + exact-SKU
   benchmarks with raw logs. The contracts that will verify them are live.
4. **Remaining engineering gap (documented):** wire the read-only
   AWS/Alibaba capture adapters to `cloud-rental capture-*` CLIs with
   recorded-response contract tests; extend the shadow simulator to carry
   candidate legs when one is ever promoted.

## What did NOT happen

No live orders, no API keys, no miner downloaded or executed, no cloud
resource created, no spend, no threshold lowered, no holdout touched, no
synthetic data presented as real.
