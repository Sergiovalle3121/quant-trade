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
