# Claude 8-Hour Autonomous Session — Worklog

Rigor upgrade for `Sergiovalle3121/quant-trade`: statistical integrity, cash-and-carry
research, mining economics, and paper parity — all research-only, no real money, no
hardware control.

- **Repository:** `Sergiovalle3121/quant-trade` (verified via `git remote -v`).
- **Base branch:** `main`
- **Initial `origin/main` SHA:** `3d66ac662b3db7a0f404dda47d83974003a4cd18`
- **Working branch:** `claude/quant-statistics-carry-mining-v3-03175j`
- **Session start (UTC):** 2026-07-24T05:24Z

## Non-negotiable safety posture (held for the whole session)

- `REAL_MONEY: NO-GO` — no real-money code paths, no live broker/exchange endpoints.
- `MINING_HARDWARE_CONTROL: DISABLED` — no ASIC/PDU/firmware/pool control; telemetry read-only.
- `AWS_RESOURCES_CREATED: FALSE` — no Terraform apply, no resource creation.
- Wallets watch-only; no private keys / seed phrases / transaction signing.
- No gate weakening to approve strategies; trial ledger never deleted or reset.
- Synthetic data never presented as realized profitability; holdout never used for tuning.
- All network integrations behind adapters with timeout / limited retry / staleness /
  attribution and offline mocks; **tests never make network calls or send orders.**

---

## Checkpoint log

### CP0 — Baseline & audit — 2026-07-24T05:35Z — SHA `3d66ac6` (branch tip = origin/main)

**Task finished:** Phase 0 baseline established and the confirmed defects reproduced.

**Environment note (important for reproducibility):** the bare `pytest` on `PATH`
resolves to a uv-managed tool interpreter without project dependencies. Use
`python -m pytest`. The editable install (`pip install -e ".[dev,data,crypto,cloud]"`)
aborted at the end because pip could not uninstall the Debian-managed
`cryptography 41.0.7` (missing RECORD); `typer` and the crypto/cloud extras were then
installed separately (`pip install typer`; `pip install --ignore-installed cryptography
ccxt boto3 curl_cffi yfinance`). Resolved versions include numpy 2.2.6, pandas 3.0.5.

**Baseline validation (executed on SHA `3d66ac6`):**

| Check | Command | Result |
| --- | --- | --- |
| Lint | `ruff check .` | All checks passed |
| Types | `mypy src` | Success: no issues found in 197 source files |
| Compile | `python -m compileall -q src tests` | OK |
| Tests | `python -m pytest -q` | **277 passed** in ~61s |

The "277 tests passed" description is therefore **verified on the current SHA**, not
taken on faith.

**Confirmed status of the system (verified in code, not from PR titles):**
- 0/5 base strategies approved; 0/3 benchmark-aware allocations approved; equal-weight
  remains unbeaten (see `docs/BENCHMARK_AWARE_VERDICT.md`, `docs/REAL_DATA_VERDICT.md`).
- Restricted-execution example is correctly `NO-GO`; S21 XP mining example is correctly
  `NO-GO`.

**Defects reproduced (evidence captured this session):**

1. **Block bootstrap ignores `block_size` (IID sampling).**
   `research/robustness.py::simple_bootstrap_or_block_bootstrap` never references
   `block_size` in its body; it calls `Series.sample(replace=True)` (IID). Proof:
   `block_size=2` and `block_size=50` produce byte-identical output
   (`a.equals(b) == True`). Autocorrelation structure is destroyed regardless of the
   nominal block size, so confidence intervals are anti-conservative for serially
   correlated returns.

2. **Chronological / walk-forward splits are row-based, not timestamp-based.**
   `research/splits.py` cuts at `int(len(df) * train_fraction)` and slices with
   `iloc`. On a long-form multi-asset panel this splits a single timestamp across
   train and test. Proof: an 8-row / 4-timestamp / 2-symbol panel with
   `train_fraction=0.4` puts `2020-01-02` (AAA) in *train* and `2020-01-02` (BBB) in
   *test* — the same bar leaks across the boundary. `embargo_bars` is likewise applied
   in rows, not timestamps, and nothing "purges" label-overlapping bars.

3. **Mining NPV/IRR uses a level daily cash flow.**
   `mining/profitability.py::_present_value` discounts a single constant
   `daily_cash_flow_usd` as a level annuity over `analysis_horizon_days` (default
   1095). `MiningPolicy.monthly_difficulty_growth_rate` (default 0.05) only feeds the
   single-point `stressed_*` figures — never the NPV/IRR projection. A 3-year NPV with
   non-zero difficulty growth is therefore materially overstated.

4. **Trial ledger is not an unambiguous record of each evaluated combination.**
   `research/ledger.py` is append-only, keys only on `test_sharpe_per_period`, and
   **silently drops corrupt lines** (`except json.JSONDecodeError: continue`). There is
   no `hypothesis_id` / `attempt_id` / `run_id`, no record of discarded grid candidates
   or failed evaluations, and no integrity report.

5. **DSR trial count is fed by ledger rows only.** `ledger_stats` counts rows and the
   cross-trial Sharpe variance; `trials_in_window` and grid breadth are not guaranteed
   to reach the multiple-testing correction, and `min_deflated_sharpe` defaults to
   `0.5` (weak evidence).

6. **Realistic execution can be silently disabled.** Research configs that omit an
   execution policy fall back to unlimited fills, so "promotable" evidence can be
   generated without the realistic model. (To be closed in Phase 4 by making the policy
   mandatory for promotion and stamping a policy hash into results.)

**Tests executed:** full suite (`python -m pytest -q`) → 277 passed; targeted
reproduction script for defects 1–3 (scratchpad, evidence above).

**Risks / blockers:** No real market data for cash-and-carry or mining in this
sandbox (network egress is proxied and unauthenticated for exchanges) — those research
tracks will ship contracts + synthetic fixtures + real-data import commands and be
marked `NOT RUN — REAL DATA REQUIRED`. pandas 3.0.5 / numpy 2.2.6 are newer than the
lockfile; watched for API drift.

**Next task:** Phase 1.1 — real bootstrap APIs (`iid_bootstrap`,
`moving_block_bootstrap`, `stationary_bootstrap`, `bootstrap_confidence_intervals`)
with a deprecated compatibility shim, plus the full statistical test matrix.

### CP1 — Statistical integrity (Phase 1.1–1.4 complete) — 2026-07-24T06:35Z

**Tasks finished:** the entire statistical-integrity track.

- **1.1 Bootstrap** (`research/bootstrap.py`, commit `3267c70`): explicit seeded
  `iid_bootstrap`, `moving_block_bootstrap` (contiguous blocks, configurable
  wrap), `stationary_bootstrap` (geometric lengths), and
  `bootstrap_confidence_intervals`. Per-period, never annualized. Old function
  is a deprecated shim delegating to the real moving-block bootstrap.
  `robustness.bootstrap_summary` records a fail-closed CI in `results.json`.
- **1.2 Purged splits** (`research/splits.py`, commit `95cb0bb`): timestamp-based
  (fixes the panel boundary leak) + `purged_chronological_split` /
  `purged_walk_forward_splits` with exact purge/embargo and a `PurgedSplit`
  audit trail. Single-asset behaviour unchanged.
- **1.3 Honest ledger** (`research/ledger.py`, commit `651fb58`): hypothesis /
  attempt / content-fingerprint identity, records failed and discarded trials,
  surfaces corrupt lines (never silent), integrity report with the conservative
  independent-trials DSR count. Runner + grid search emit structured records.
- **1.4 Promotion V2** (`research/promotion_v2.py`, this commit):
  `configs/selection/conservative_v2.yaml` requiring DSR≥0.95, PSR≥0.95, positive
  net excess, block-bootstrap CI, mandatory execution policy, fill/incomplete
  gates, subperiod stability, dataset binding, ledger integrity, and human
  approval notes. Evidence is **recomputed** from artifacts; a bogus stored DSR
  flag cannot promote a weak run. Best outcome is `paper_candidate`;
  `real_money_authorized` is always False. The runner now stamps the execution
  policy + hash into `results.json` (also serves Phase 4).

**Tests executed:**
- `ruff check .` → All checks passed
- `mypy src` → Success: no issues found in 199 source files
- `python -m pytest -q` → **333 passed** (277 baseline + 56 new: 21 bootstrap,
  15 purged-split, 10 ledger-integrity, 13 promotion-v2, minus overlap).

**Results:** `STATISTICAL_INTEGRITY: PASS`. The rigor upgrade did not
manufacture an edge — 0/5 base strategies still clear the V2 gate; equal-weight
remains unbeaten. That is the intended honest outcome.

**Risks / blockers:** none for this track. pandas 3.0.5 / numpy 2.2.6 caused no
API drift. Docs added: `docs/STATISTICAL_INTEGRITY_V2.md`.

**Next task:** Phase 2 — cash-and-carry / funding market-neutral research module
(two-leg model, full cost stack, causal funding, execution state machine, risk
gates, pre-registration), research-only. Synthetic data can never yield GO;
absent real data stays NOT-RUN.

### CP2 — Cash-and-carry research-only (Phase 2 complete) — 2026-07-24T07:05Z

**Task finished:** the entire cash-and-carry / funding track, research-only.

New package `src/quant_trade/carry/`:
- `models.py` — `CarrySnapshot` (causal schema: realized funding known at `t`;
  `predicted_funding_rate` kept separate and never merged), `CarryCostModel`,
  `CarryPosition`, `CarryPolicy`, `CarryEvaluation`.
- `economics.py` — `evaluate_carry` with the full cost stack (fees, half-spread,
  slippage, impact on all four fills; custody/margin/borrow annual; conversion
  amortized), a reversion-haircut expected carry, break-evens, a liquidation
  proxy, and fail-closed risk gates.
- `execution.py` — deterministic two-leg state machine (PLANNED, LEG_1/2_PARTIAL,
  HEDGED, UNHEDGED_RISK, UNWINDING, CLOSED, REJECTED) with max unhedged notional,
  timeout, bounded retries, simulated emergency unwind, no phantom fills, and
  notional/delta reconciliation. **No real orders.**
- `data.py` + `real_adapter.py` — read-only adapter protocol, JSON fixtures,
  schema validator (fails closed), deterministic synthetic generator, and a
  lazy-imported public-endpoint ccxt adapter (no keys, never trades).
- `research.py` — causal campaign backtest, block bootstrap, purged walk-forward,
  ledger entry, and a GO / NO-GO / **NOT-RUN** verdict.

**Verdict enforcement:** synthetic data ⇒ NOT-RUN, always (a test asserts it).
The synthetic campaign shows −1.28% net return, −0.17 Sharpe, 0.000 GO fraction,
9 walk-forward windows — no invented profitability.

**Tests executed:** `ruff check .` pass; `python -m mypy src` (2.3.0, matching CI)
pass on 206 files; `python -m pytest -q` → **361 passed** (+28 carry tests).

Docs: `docs/CASH_AND_CARRY_PREREGISTRATION.md`, `docs/CASH_AND_CARRY_RESULTS.md`.
Configs: `configs/carry/cash_and_carry_synthetic.yaml`,
`configs/carry/cash_and_carry_real_template.yaml`. Fixture:
`examples/data/carry/synthetic_funding_snapshots.json`.

**Result:** `TRADING_EDGE (cash-and-carry): NOT-RUN — REAL DATA REQUIRED`.

**Next task:** Phase 3 — mining economics V2 (attributable stale-safe snapshots,
hashprice + bottom-up, dynamic per-period cash flow with difficulty growth /
halvings, electricity tariffs, pool models) and read-only telemetry/inventory/
ledger. Hardware control stays disabled.

### CP3 — Mining economics V2 + telemetry (Phase 3 complete) — 2026-07-24T07:40Z

**Task finished:** the mining economics V2 + read-only telemetry track.

New modules under `src/quant_trade/mining/`:
- `market.py` — attributable `MiningMarketData`; two revenue methods
  (`direct_hashprice`, `bottom_up_hashprice`) with `compare_hashprice`
  divergence alerts; fail-closed staleness; read-only adapter + fake + validator.
- `cashflow.py` — `project_mining_cashflow`: **fixes the constant-cash-flow NPV
  defect**. Per-day difficulty growth, scheduled halvings (subsidy halves, tx
  fees don't), price drift/scenarios, uptime/hashrate degradation, energy
  inflation, repair CAPEX, tax. Reports cash vs accounting profit, NPV, IRR,
  discounted payback, production cost, break-evens, and the V1
  `constant_flow_npv` overstatement.
- `tariffs.py` — flat/TOU/demand-charge/PUE/curtailment/hosting tariffs; CFE
  receipt template (never a hardcoded universal rate).
- `pool.py` — PPS/FPPS/PPS+/PPLNS payout economics with fees, stale/reject,
  variance flag, and counterparty-risk score.
- `telemetry.py` — read-only inventory/telemetry/alerts/watch-only
  reconciliation/operating ledger. `AUTHORIZED_TO_START_MINER`,
  `HARDWARE_CONTROL_ENABLED`, `WALLET_SIGNING_ENABLED` hard-wired `False` (tested);
  adapter protocol has no control verbs (tested).

**Defect-fix evidence (S21-like rig, 3% monthly difficulty growth, mid-horizon
halving, 3-year):** dynamic NPV −$5,029 vs V1 constant-flow NPV −$1,068 — a
**$3,961 overstatement removed**. Production cost $65,745/coin vs $60k price →
honest NO-GO; no profitability invented.

**Tests executed:** `ruff check .` pass; `python -m mypy src` (2.3.0) pass on 211
files; `python -m pytest -q` → **399 passed** (+38 mining tests).

Docs: `docs/MINING_ECONOMICS_V2.md`, `docs/MINING_TELEMETRY.md`.

**Result:** `MINING_ECONOMICS: NO-GO / NEEDS-INPUT` (real snapshot + tariff +
pool required for a GO); `MINING_TELEMETRY: READY` (read-only);
`MINING_HARDWARE_CONTROL: DISABLED`.

**Note:** PR #39 was manually marked ready-for-review by the repo owner; left as
they set it (no auto-merge configured), CI kept green.

**Next task:** Phase 4 — realistic execution mandatory for promotable evidence
(largely done in Phase 1.4), parity report (backtest vs sim paper vs broker
paper), paper-readiness V3.
