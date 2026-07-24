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

## CP2 — 2026-07-25T00:05Z — V6-2: authentic provenance chain (defect D closed)

- `evidence/receipts.py` (new): `IngestionReceipt` (venue, endpoint, params
  WITHOUT secrets — validated, http status, capture time, adapter, raw_path,
  raw_sha256, normalized_rows_sha256, source_kind). `resolve_provenance`
  works ONLY from byte-verified receipts: `live` → real; `fixture/recorded/
  manual/synthetic/unknown` → test_only forever; no receipt →
  `unverified_legacy`; tampered raw → dataset `invalid`; mixtures → `mixed`.
  Self-labels inside records are ignored — reproducibility ≠ authenticity.
- `carry/backfill.py` writes a receipt per capture (source_kind honest:
  fixture replay is `fixture`, live is `live`).
- `carry/research.py`: jsonl provenance resolved from receipts (broken raw
  evidence refuses to run); JSON files self-labelled "real" downgrade to
  `unverified_legacy` with an explicit manifest note.
- `carry/store.py`: the snapshot bridge takes provenance from the CALLER —
  the `"real"` literal is gone. `CarrySnapshot` accepts the new provenance
  labels (`DATA_SOURCES`).
- 2 more xfail markers removed (D×2); 3 legacy tests updated to the honest
  posture. 7 new receipt tests. Suite: **605 passed, 14 xfailed** ·
  ruff/mypy clean.

Next: V6-3 — canonical instrument catalog + collector mark/index fixes.

## CP3 — 2026-07-25T00:25Z — V6-3: canonical identity + honest collector (E/G)

- `carry/instruments.py`: `parse_symbol` normalizes EVERY spelling — venue
  native (`BTCUSDT`, `BTC-USDT-SWAP`), ccxt unified (`BTC/USDT:USDT`),
  canonical ids (idempotent round-trip) and bare bases — to (base, quote);
  `canonical_instrument_id`/`canonical_spot_id` yield ONE id per economic
  pair per venue. `InstrumentIdentity.from_record` normalizes stored ids
  through the same path, so backfill and collector records of the same pair
  can never split into per-adapter identities. Seed metadata table
  (funding interval, native symbols, contract terms) fails closed on
  unknown pairs.
- `carry/collector.py` (V6-G): mark ONLY from the funding payload's
  `markPrice` (missing mark fails closed — the last trade is never
  substituted); index ONLY from `indexPrice`; `perp_last` preserved as
  last; bid/ask required, no `or last` fallbacks; funding interval from
  instrument metadata; ccxt clients cached per venue with an explicit
  `close()`; canonical instrument ids stamped on every observation.
- `carry/backfill.py` stamps canonical spot/perp ids.
- 2 more xfail markers removed (E, G); 2 V5 asserts updated to canonical
  ids. Suite: **607 passed, 12 xfailed** · ruff/mypy clean.

Next: V6-4 — HistoricalCarryPanel (paginated klines+funding backfill).

## CP4 — 2026-07-25T00:55Z — V6-4: HistoricalCarryPanel executable (defect F)

- `carry/panel.py` (new): pure Bybit kline parsers (spot/perp/mark/index,
  identity fail-closed, positive-price validation); `build_carry_panel`
  joins the four series point-in-time — rows exist ONLY where every series
  has a bar (gaps detected, NEVER forward-filled), settlements attached to
  their exact instants, spread labelled `proxy_ohlcv_close` (never called
  observed); audit with coverage/gaps; `panel_to_research_inputs` emits the
  settlement-driven signal series (last SETTLED rate held between events).
- `carry/panel_backfill.py` (new): paginated end-cursor backfill with
  repeated-page detection, content-addressed raw pages + one ingestion
  receipt per page, bounded retries, idempotent re-runs, NOT_RUN attempts
  log. Live attempt executed: `NOT_RUN_NETWORK_BLOCKED` (proxy 403),
  recorded in `data/carry/panel/bybit_btc/backfill_attempts.jsonl`.
- `research.py`: new `source: panel` — provenance resolved from page
  receipts (`resolve_dir_provenance`), settlements + settlement-driven
  `signal_rates` flow into the ledger AND the cost stress.
- CLI: `carry backfill-panel` (with `--fixture-dir` replay) and
  `carry panel-audit`.
- E2E proven on recorded pages: raw → receipts → panel → ledger →
  research → artifacts → promotion (byte-for-byte reproduced, honestly
  REJECTED because fixtures are TEST_ONLY). Defect F xfail removed.
- 8 new tests. Suite: **616 passed, 11 xfailed** · ruff/mypy clean.

Next: V6-5 — H1/H2 settlement signals everywhere + real H3 + DSR/PBO gates.

## CP5 — 2026-07-25T01:30Z — V6-5: settlement signals, real H3, DSR/PBO, caps

- **H closed:** the jsonl path now derives its signal from SETTLEMENTS (last
  settled rate held between events; zero settlements ⇒ zero signal ⇒ polls
  carry no entry authority) — same semantics as the panel path; the signal
  series feeds the ledger AND the cost stress identically.
- **I closed:** `carry/cross_venue.py` — real perp-perp dispersion: long the
  lower-funding perp, short the higher, settled-spread trailing signal,
  per-venue marks (never concatenated) with divergence booked as P&L,
  per-switch fees + transfer costs, terminal close, independent cash-vs-
  totals reconciliation. Scanner kind `cross_venue_dispersion` (H3 config
  updated): requires BOTH panels, runs the engine, fixture panels stay
  TEST_ONLY; real panels reach at most RESEARCH_CANDIDATE pending gates.
- **J closed:** `evaluate_carry_promotion` now EXECUTES DSR (from the
  persisted return series + conservative trial counting from the trial
  ledger) and a PBO estimate (walk-forward negative-window fraction, ≥4
  windows required, pre-registered 0.50 limit), plus a reconciled-ledger
  requirement; the review exposes a `statistics` section.
- **M closed:** explicit leveraged-cap policy — `max_gross_exposure` is
  enforced WITH leverage (cash constraint relaxed, cap never silenced) in
  the engine, runner, and now `walk_forward_multi` windows.
- 5 xfail markers removed (H, I, J, M×2); V4/V5 tests updated to the new
  completeness bar. 6 new cross-venue tests. Suite: **627 passed, 6
  xfailed** · ruff/mypy clean.

Next: V6-6 — common-unit economic board + strict lineage (K/L).

## CP6 — 2026-07-25T02:00Z — V6-6: common-unit board + verified lineage (K/L)

- **K closed:** every ranked score is now ANNUALIZED NET RETURN ON CAPITAL —
  trading rows annualize `total_return` over `span_days` (the scanner now
  exports both), mining cells need `margin_per_hour ÷ all-in cost per hour`
  (labelled linear hourly extrapolation), cash is its annual yield. A row
  that cannot express the common unit is tracked with the exact reason and
  NEVER ranked — Sharpe-vs-USD/h-vs-yield rankings are impossible.
- **L closed:** the board requires lineage for BOTH inputs (artifact kind,
  path, evaluated_at, rows hash embedded at scan time), recomputes the rows
  hash from what it actually receives, and refuses hand-edited artifacts,
  missing lineage, wrong artifact kinds, or mismatched evaluation clocks.
  Scan artifacts (leaderboard + matrix) embed `rows_sha256` as the tamper
  anchor; `lineage_for_rows` is the one legitimate construction path.
- Board artifact renamed `UNIFIED_ECONOMIC_BOARD` (schema 2); allocation
  carries the lineage through. CLI `rank` builds lineage from the
  artifacts' EMBEDDED hashes.
- 2 xfail markers removed (K, L); V5 board tests updated to lineage +
  common-unit inputs. Suite: **629 passed, 4 xfailed** · ruff/mypy clean.

Next: V6-7 — persistent shadow portfolio + honest readiness (N).

## CP7 — 2026-07-25T02:35Z — V6-7: persistent shadow + honest readiness (N)

- `opportunities/shadow.py` (new): persistent shadow sessions — the paper
  allocation is FROZEN at start (hash-bound; overwrite refused; non-paper
  allocations rejected), event-driven advance with idempotent resume (seq
  journal), append-only snapshots, daily reconciliation that REBUILDS
  equity from the flow journal, and EVALUATED kill switches (stale data,
  drawdown, exposure, reconciliation) that HALT the session — a halted or
  stopped session refuses to advance. Scoreboard vs the cash benchmark.
  CLI: `opportunities shadow-start/advance/status/reconcile/stop`.
- **N closed** (`paper/readiness.py`): `record_drill` now REQUIRES a raw
  evidence log; `evidence_sha256` hashes THOSE bytes and readiness
  re-verifies them at evaluation time (missing/tampered logs are named
  problems). The parity drill binds its raw comparison dump and no longer
  compares a record against the same object — the second side is rebuilt
  through the independent frame-normalization path; the broker-paper leg
  stays NOT_READY_MISSING_BROKER_EVIDENCE honestly.
- 1 xfail marker removed (N); readiness tests moved to the raw-log
  contract. 8 new shadow tests. Suite: **638 passed, 3 xfailed** ·
  ruff/mypy clean.

Next: V6-8 — mining real-evidence chain (O).
