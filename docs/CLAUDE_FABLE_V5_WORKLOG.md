# Claude Fable V5 Sprint Worklog — Profit Discovery

Objective: turn the platform into an opportunity-discovery engine — close the
remaining economic false positives, run reproducible campaigns on available
real data, and rank trading / rented-mining / cash honestly. No live orders,
no miners, no cloud resources, no spend.

Safety posture held: `REAL_MONEY: NO-GO` · `LIVE_ORDER_SUBMISSION: DISABLED` ·
`MINER_EXECUTION: DISABLED` · `MINING_HARDWARE_CONTROL: DISABLED` ·
`WALLET_SIGNING: DISABLED` · `AWS_RESOURCES_CREATED: FALSE` ·
`ALIBABA_RESOURCES_CREATED: FALSE` · `EXTERNAL_SPEND_AUTHORIZED: FALSE`

## CP0 — 2026-07-24T19:55Z — baseline + P0 red tests

- **Observed-state correction:** the prompt assumed PR #41 open; it was merged
  at the owner's order as `f3be7a8` before this sprint. Base rule 2 applies:
  branch `claude/profit-discovery-v5` from `origin/main` = `f3be7a8`.
- **Baseline (executed on `f3be7a8`):** ruff pass · mypy pass (235 files) ·
  compileall OK · diff-check OK · **pytest 538 passed**.
- **Network probe:** Bybit and OKX public funding endpoints return proxy 403
  (`CONNECT tunnel failed`) from this sandbox. Live backfill will be recorded
  as `NOT_RUN` with this verifiable error; adapters are built and tested
  offline per the sprint mandate.
- **P0 red tests** (`tests/test_v5_defect_reproduction.py`, xfail strict, 3):
  - **A** mixed symbols (BTC/ETH alternating) and mixed venues (binance/okx)
    in one store flow into ONE return series — cross-instrument "price moves"
    become fake basis P&L; campaign must fail closed on mixed identity.
  - **B** 90 five-minute polls of the same 8h funding rate accrue ~90× the
    funding a position could actually collect (one settlement).

Next: V5-1 instrument identity + poll/settlement event semantics.

## CP1 — 2026-07-24T20:00Z — V5-1: identity + event semantics green (`8bf566e`)

- `carry/instruments.py`: frozen `InstrumentIdentity` (venue|symbol|spot/perp
  instrument|contract|quote|settlement|interval), `require_single_identity`
  fails closed on any mixing; `check_clock_skew` (120 s max) fails closed.
- `carry/store.py`: event taxonomy `poll/backfill/funding_settlement/
  funding_prediction/open_interest`; polls are QUOTES and never settle;
  `extract_settlement_events` dedups by venue|symbol|funding_time;
  `verify_raw_payload` invalidates records on one flipped raw byte; appends
  serialised under an exclusive `flock` (4-thread test: no dupes/interleave).
- `carry/research.py`: provenance comes from the DATASET MANIFEST, never the
  first record — mixed provenance → `NOT_RUN_INSUFFICIENT_REAL_DATA`.
- Red tests A/B flipped green + 7 adversarial additions. Suite: **547 passed**.

## CP2 — 2026-07-24T20:09Z — V5-2: stateful ledger + applied gross cap

- `carry/ledger_engine.py` (new): explicit account simulation — cash, per-leg
  quantities, posted margin, per-fill fees, settlement-causal funding accrual
  in `(t[i-1], t[i]]`, collateral yield, carrying costs, mandatory terminal
  close, and the identity `final_equity − initial_capital == Σ components`
  checked to 1e-9 · capital. Entries are gated through the two-leg execution
  state machine: injected partial fills below `min_fill_rate` ABORT the entry
  and book the emergency-unwind cost as real money (never assume the hedge).
- `backtest/multi_asset.py`: `max_gross_exposure` is now ENFORCED, not
  reported — sizing cap at order time plus a per-bar drift trim (breaches are
  trimmed proportionally at the next executable price; overshoot bounded by
  one bar's drift). Combined with `allow_leverage` → refuses (fail closed).
  On the sample dataset the report-only behaviour drifted to 0.5485 gross
  under a 0.5 cap; enforced behaviour holds ≤ 0.5006.
- `research/multi_asset_runner.py`: portfolio `max_gross_exposure` from the
  config is passed into BOTH train and test engine calls.
- 10 new tests (`tests/test_v5_ledger_engine.py`): reconciliation to the
  cent, flat ledger charges nothing, partial-fill abort books unwind cost,
  settlement-only accrual, multi-settlement bars, walk-forward position
  continuity (no cash reset), cap binds, cap+leverage refuses, negative
  funding loses money, determinism. Suite: **557 passed** · ruff/mypy clean.

Next: V5-3 funding backfill CLI + pre-registered hypotheses + campaign.

## CP3 — 2026-07-24T20:30Z — V5-3: backfill CLI + pre-registration

- `carry/backfill.py` (new): Bybit/OKX PUBLIC funding-history backfill.
  Pure parsers separated from network fetch (fully offline-testable);
  response symbol must match the requested instrument or the parse fails
  closed ("refusing to relabel records"); raw bytes preserved
  content-addressed (`raw/<sha256>.json`) and every stored record is
  byte-bound via `raw_sha256`; every attempt (success/failure) appended to
  `backfill_attempts.jsonl` with the exact URL and verbatim error.
- `carry/store.py`: settlement/prediction events may honestly omit order-book
  prices (history endpoints carry none — inventing them would be fabricated
  evidence); quote events still REQUIRE the full price set.
- CLI `quant-trade carry backfill --venue bybit|okx` with `--fixture` replay
  (provenance marked `fixture`, source_name prefixed — TEST_ONLY forever).
- **Live attempts executed and recorded:** both venues →
  `NOT_RUN_NETWORK_BLOCKED`, error verbatim
  `URLError: <urlopen error Tunnel connection failed: 403 Forbidden>`,
  logged in `data/carry/backfill_attempts.jsonl` (committed as evidence).
- `docs/PROFIT_HYPOTHESES_V5.md`: H1–H5 pre-registered (fixed identities,
  signals, gates, falsifiers) BEFORE any campaign; synthetic campaign run
  confirms honest terminal `NOT_RUN_INSUFFICIENT_REAL_DATA`.
- 9 new tests (`tests/test_v5_backfill.py`). Suite: **566 passed** ·
  ruff/mypy clean.

Next: V5-4 reproducible promotion (`carry promote`, clean-room rebuild).

## CP4 — 2026-07-24T20:45Z — V5-4: reproducible promotion (fix E)

- Determinism proven first: two independent campaign runs produce
  byte-identical `results.json` (no wall-clock fields in artifacts).
- `carry/promote.py` (new): `reproduce_campaign` rebuilds the campaign from
  config + dataset in a clean room and byte-compares ALL evidence files
  (`results.json`, `dataset_manifest.json`, `net_returns.csv`). Ordered
  fail-closed verdicts: `REJECTED_MISSING_EVIDENCE` (no/unreadable claim) →
  `REJECTED_DATASET_TAMPERED` (dataset bytes no longer hash to the claimed
  manifest, checked BEFORE any rebuild) → `REJECTED_REBUILD_FAILED` →
  `REJECTED_NOT_REPRODUCIBLE` (any artifact differs) → only a byte-identical
  rebuild reaches the artifact-recomputing promotion review (max outcome
  PAPER_CANDIDATE). The rebuild's trial-ledger entry stays in the scratch
  dir — a reproduction is a verification, never a new trial.
- CLI `quant-trade carry promote --config … --claimed … [--report …]`;
  exit 0 only on full PAPER_CANDIDATE.
- 6 new tests (`tests/test_v5_promote.py`): byte-for-byte reproduction,
  tampered results → NOT_REPRODUCIBLE, tampered dataset → rejected before
  rebuild, missing claim, wrong config cannot reproduce, CLI roundtrip.
  Suite: **572 passed** · ruff/mypy clean.

Next: V5-5 evidence bundle validator + mining rental scanner.

## CP5 — 2026-07-24T21:10Z — V5-5: bundle validator + mining scanner (fix F)

- `cloud_rental/bundle.py` (new): `EvidenceBundleValidator` — exact
  quote↔spec↔benchmark↔policy identity (provider, SKU, region, accelerator
  model+count, algorithm, workload); byte-verifies `artifact_sha256` and
  `snapshot_sha256` against the actual files (unavailable bytes = missing
  evidence; wrong bytes = broken chain); fixture-sourced quotes/benchmarks →
  TEST_ONLY forever. Verdict precedence: identity > SHA > missing.
- `opportunities/` (new package) + `opportunities scan-mining` CLI:
  provider×region×SKU×algorithm×coin cells; per-cell precedence:
  incoherent bundle rejects outright → POLICY_BLOCKED (decisive, outranks a
  missing benchmark, never converted to economics) → MISSING_EVIDENCE →
  economics; fixture-fed candidates are renamed `TEST_ONLY_*` in the status
  itself. Every cell appears in the matrix — nothing silently dropped.
- `configs/opportunities/mining_scan_v5.yaml`: the REAL posture, honestly —
  no fabricated policy evidence. Scan executed →
  `artifacts/v5/MINING_RENTAL_MATRIX.json`: AWS
  `POLICY_BLOCKED:BLOCKED_PENDING_WRITTEN_APPROVAL` (Service Terms §1.25,
  ambiguity NOT resolved in favor of hashing), Alibaba × 2
  `POLICY_BLOCKED:BLOCKED_PROVIDER_POLICY`. Zero candidates — correct.
- 8 new tests (`tests/test_v5_bundle_and_mining_scan.py`): TEST_ONLY
  classification, cross-SKU/region/provider rejection, tampered artifact →
  SHA break, missing bytes → missing evidence, real-posture scan, policy
  block outranks missing benchmark, identity break precedes policy, CLI.
  Suite: **580 passed** · ruff/mypy clean.

Next: V5-6 trading scanner + unified opportunity board + paper allocator.

## CP6 — 2026-07-24T21:40Z — V5-6: trading scanner + board + allocator

- `opportunities/trading_scan.py`: executes ONLY hypotheses pre-registered in
  `docs/PROFIT_HYPOTHESES_V5.md`. Statuses: `NOT_RUN_NO_DATASET` (quotes the
  committed backfill-attempts log as evidence), `NOT_RUN_DATASET_REJECTED`
  (fail-closed validation error verbatim), or the campaign's own verdict.
  NOT_RUN rows stay on the leaderboard — absence of evidence is visible.
- Semantic fix surfaced by tests: clock-skew checking now applies to POLL
  events only — backfilled settlements/predictions legitimately carry a
  historical exchange timestamp far from capture time; polls still fail
  closed at 120 s.
- `opportunities/board.py`: unified board (trading + mining + cash). Strict
  eligibility (trading: real-data PAPER_CANDIDATE; mining: non-TEST_ONLY
  economic candidate; cash always on the board). Ineligible rows are tracked
  but never ranked. Champion/challenger scoreboard included. Paper allocator:
  zero to ineligible rows, equal-weight under a per-opportunity cap (25 %
  default) to eligible ones, cash absorbs the residual so the total is exact.
- CLI: `opportunities scan-trading | rank | allocate-paper`. Artifacts
  generated and committed: `TRADING_OPPORTUNITY_LEADERBOARD.json` (H1–H3 all
  `NOT_RUN_NO_DATASET` with proxy-403 evidence), `UNIFIED_OPPORTUNITY_BOARD
  .json` (champion: `cash_usd` — nothing beats cash on current evidence),
  `PAPER_CAPITAL_ALLOCATION.json` (100 % cash, paper only).
- 8 new tests (`tests/test_v5_opportunity_board.py`). Suite: **588 passed** ·
  ruff/mypy clean.

Next: V5-7 freeze, validation matrix, final report, PR update, merge.
