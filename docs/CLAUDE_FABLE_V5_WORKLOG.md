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
