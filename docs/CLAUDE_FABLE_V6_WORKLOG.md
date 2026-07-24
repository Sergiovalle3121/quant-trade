# Claude Fable V6 Sprint Worklog — Economic Integrity, Real Data & Shadow Portfolio

Objective: turn V5's defensive components into ONE integrated economic path —
authentic raw data, a single reconciled ledger, comparable opportunities in a
common unit, and a persistent shadow portfolio. No live orders, no miners, no
cloud resources, no spend.

Safety posture held: `REAL_MONEY: NO-GO` · `LIVE_ORDER_SUBMISSION: DISABLED` ·
`MINER_EXECUTION: DISABLED` · `MINING_HARDWARE_CONTROL: DISABLED` ·
`WALLET_SIGNING: DISABLED` · `AWS_RESOURCES_CREATED: FALSE` ·
`ALIBABA_RESOURCES_CREATED: FALSE` · `EXTERNAL_SPEND_AUTHORIZED: FALSE`

Merge policy this sprint: draft PR, NO auto-merge unless the owner orders it
explicitly during the session.

## CP0 — 2026-07-24T23:01Z — baseline + P0 red tests A–O

- **Git revalidated:** `main` = `1a9833a` (PR #42 squash-merged at
  2026-07-24T20:45Z, CI run 30124797791 green). Zero open PRs. Branch
  `claude/economic-integrity-real-data-v6` created from `origin/main`.
- **Baseline (on `1a9833a`):** ruff pass · mypy pass (245 files) ·
  compileall OK · diff-check OK · **pytest 590 passed**.
- **All 15 P0 defects (A–O) confirmed live at this head** and reproduced as
  21 xfail(strict) red tests in `tests/test_v6_defect_reproduction.py`; the
  full evidence table is `artifacts/v6/DEFECT_REPRODUCTION_MATRIX.json`.
  Highlights verified in source before writing each test:
  - A: `run_carry_research` never calls `run_carry_ledger`; artifacts carry
    no ledger and reconciliation is computed from one expression.
  - B: `funding_events = len(returns)` — 120 polls with 0 settlements pass
    the `min_funding_events` gate.
  - C: `_stressed_total` re-runs `carry_campaign_returns` WITHOUT
    `settlements=` (2×/3× re-fabricate poll funding) and never multiplies
    `taker_fee_bps`.
  - D: `observations_to_snapshot_records` hardcodes `data_source="real"`.
  - E: backfill writes `bybit:BTCUSDT`, ccxt collector `BTC/USDT:USDT` —
    the same economic pair cannot share a store.
  - G: `perp_mark=float(perp["last"])` in the ccxt adapter.
  - J: promotion recomputes PSR only — no DSR, no PBO.
  - K: the board ranks Sharpe/period vs USD/hour vs annual yield.
  - O: inline `hashprice_usd_per_th_day`, no raw SHA on quote/spec, KAS
    priced in a SHA-256 unit.

Next: V6-1 — single economic source of truth (ledger wired into research,
cost stress with settlements, independent reconciliation, ledger artifacts).

## CP1 — 2026-07-24T23:35Z — V6-1: single economic truth (defects A/B/C closed)

- **Ledger rewritten as a real balance sheet** (`carry/ledger_engine.py`):
  `cash` mutated flow-by-flow (spot purchase/sale, margin post/release,
  per-fill fees, conversion/withdrawal, cash-settled funding, per-bar
  variation margin, collateral yield, carrying costs, emergency unwinds) with
  a cash-flow JOURNAL; per-bar `equity = cash + spot·price + margin`.
  Reconciliation now compares two INDEPENDENT accounting paths — final
  balance-sheet equity vs initial + separately-accumulated category totals —
  not one expression against itself. `signal_rates` decouples signal from
  quoted rates (V6-5 hook). Perp exit fees priced on perp, not spot.
- **Research consumes the ledger as THE promotable path** (defect A):
  `run_carry_research` runs `run_carry_ledger` (unreconciled ledger refuses
  to produce evidence), aborted two-leg entries reject the campaign, and
  `carry_campaign_returns` is now marked DIAGNOSTIC — NON-PROMOTABLE.
  Artifacts gained `reconciliation.json`, `equity_curve.csv`,
  `funding_cashflows.jsonl`; results.json embeds the ledger summary;
  promotion byte-compares all six artifacts.
- **Settlement sufficiency** (defect B): metrics expose
  `unique_settlement_count`, `settlement_span_days`,
  `settlement_coverage_ratio`; the gate counts UNIQUE SETTLEMENTS (polls
  never count) — 120 polls with 0 settlements now fail sufficiency.
- **Cost stress** (defect C): 2×/3× rerun the SAME ledger with the same
  settlements/signals/fills; new `CarryCostModel.fee_multiplier` scales the
  venue `taker_fee_bps` inside `_round_trip_friction`, and
  `conversion_withdrawal_cost` is now actually charged at entry.
- 5 xfail markers removed (A×2, B, C×2); one V5 test recalibrated to
  perp-notional funding scale. Suite: **596 passed, 16 xfailed** ·
  ruff/mypy clean.

Next: V6-2 — authentic provenance chain (IngestionReceipt).
