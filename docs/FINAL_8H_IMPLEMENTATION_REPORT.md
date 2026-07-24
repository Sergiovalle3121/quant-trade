# Final 8-Hour Implementation Report

Autonomous rigor upgrade for `Sergiovalle3121/quant-trade`. Research-only
throughout: no real money, no live broker/exchange endpoints, no mining hardware
control, no AWS resources, no key handling.

## Status summary

| Signal | Status |
| --- | --- |
| `STATISTICAL_INTEGRITY` | **PASS** |
| `TRADING_EDGE` | **NO-GO** (base strategies) / **NOT-RUN** (cash-and-carry — real data required) |
| `PAPER_READINESS` | **READY** (for a supervised paper trial only) |
| `REAL_MONEY` | **NO-GO** |
| `MINING_ECONOMICS` | **NO-GO** at the example inputs / **NEEDS-INPUT** in general |
| `MINING_TELEMETRY` | **READY** (read-only) |
| `MINING_HARDWARE_CONTROL` | **DISABLED** |
| `AWS_RESOURCES_CREATED` | **FALSE** |

## SHAs, branch, and pull requests

- **Initial `origin/main`:** `3d66ac662b3db7a0f404dda47d83974003a4cd18`
- **Final branch SHA:** `e4021de8b29c14f02515a82d6033baf065c21fc8`
  (branch `claude/quant-statistics-carry-mining-v3-03175j`)
- **`main` after the session:** `cf97401ec72cbb456cbc5acbf114045a6e034475`
- **PR #39** — statistical integrity + cash-and-carry (Phases 0–2): **MERGED**
  by the repo owner mid-session (squash `cf97401`). Final; not reused.
- **PR #40 (draft)** — mining economics V2 + telemetry + paper parity/readiness
  (Phases 3–4): <https://github.com/Sergiovalle3121/quant-trade/pull/40>
  — **draft, do not merge.**

### Commits created this session

Merged via PR #39 (now in `main`):
- `0ce43b8` open 8h worklog with baseline + reproduced defects
- `3267c70` real block/stationary bootstrap replacing the IID no-op
- `95cb0bb` timestamp-based purged splits (fix panel boundary leak)
- `651fb58` honest trial ledger with hypothesis/attempt identity
- `b5f00b7` conservative promotion V2 that recomputes evidence
- `0877375` fix promotion_v2 mypy 2.3 union-attr
- `c28d2e3` research-only cash-and-carry / funding toolkit

Follow-up on PR #40 (draft):
- `5fc860f` mining economics V2 (dynamic cash flow) + read-only telemetry
- `e4021de` execution parity report + paper-readiness V3

(The repo owner also merged PR #38 and concurrent integration commits into the
same line; those were preserved, never overwritten.)

## Files (follow-up branch vs `main`: 16 files, +2,181 lines)

New modules: `mining/{market,cashflow,tariffs,pool,telemetry}.py`,
`paper/{parity,readiness}.py`. New tests:
`test_mining_{market,cashflow,tariffs_pool,telemetry}.py`,
`test_paper_parity_readiness.py`. New docs: `MINING_ECONOMICS_V2.md`,
`MINING_TELEMETRY.md`, `PAPER_READINESS_V3.md`. Phases 0–2 files (bootstrap,
splits, ledger, promotion_v2, the `carry/` package, `STATISTICAL_INTEGRITY_V2`,
cash-and-carry docs/configs/fixtures) are in `main` via PR #39.

## Validation (executed on the final SHA)

| Check | Command | Result |
| --- | --- | --- |
| Lint | `ruff check .` | All checks passed |
| Types | `python -m mypy src` (mypy 2.3.0, matches CI) | Success, 214 files |
| Compile | `python -m compileall -q src tests` | OK |
| Tests | `python -m pytest -q` | **417 passed** |

Baseline was 277 passed on `3d66ac6`; the session added ~140 tests across the
merged and follow-up work (bootstrap, purged splits, ledger integrity, promotion
V2, cash-and-carry, mining market/cashflow/tariffs/pool/telemetry, paper
parity/readiness). **Environment note:** the bare `pytest` on PATH is a uv tool
without deps — use `python -m pytest`; CI's mypy is 2.3.0, so use
`python -m mypy src` locally.

## Defects corrected

1. **Block bootstrap ignored `block_size`** (IID sampling) → real
   `iid`/`moving_block`/`stationary` bootstraps, seeded, per-period, with
   autocorrelation-preservation tests. Old function is a deprecated shim.
2. **Row-based splits leaked across the train/test boundary on panels** →
   timestamp-based splits + `purged_chronological_split` /
   `purged_walk_forward_splits` with exact purge/embargo and causality tests.
3. **Trial ledger was ambiguous and dropped corrupt rows silently** →
   hypothesis/attempt/content-fingerprint identity, failed/discarded records,
   corruption surfaced, integrity report, conservative independent-trials DSR
   count. Grid search now logs discarded/failed combinations.
4. **`min_deflated_sharpe: 0.5` was weak; promotion trusted stored flags** →
   `conservative_v2.yaml` at DSR≥0.95 / PSR≥0.95, and `promotion_v2` recomputes
   evidence from artifacts (a bogus stored DSR cannot promote a weak run).
5. **Mining NPV used a constant daily cash flow** despite non-zero difficulty
   growth → `mining/cashflow.py` projects each day (difficulty, halvings, price,
   degradation, energy inflation, CAPEX, tax) and reports the V1 overstatement.
6. **Realistic execution could be silently optional** → the runner stamps the
   execution policy + hash into `results.json`; the V2 gate makes a missing
   policy NOT PROMOTABLE with no unlimited-fill fallback.
7. **Mining lacked attributable/stale-safe snapshots, transaction-fee/hashprice
   separation, tariffs, pool models, and telemetry** → all added, read-only.

## Real data used, or its absence

**No real market data was available in this sandbox** (outbound exchange access
is proxied/unauthenticated). Every cash-and-carry and mining number below is
either synthetic (clearly labelled) or a documented example. Read-only import
paths, contracts, validators, and exact commands are in place for real data.

## Trading results — synthetic vs real (kept strictly separate)

- **Base strategies / allocations:** 0/5 base strategies and 0/3
  benchmark-aware allocations clear the V2 gate; equal-weight remains unbeaten.
  `TRADING_EDGE: NO-GO`.
- **Cash-and-carry (synthetic):** −1.28% net return, −0.17 Sharpe, 0.000 GO
  fraction, 9 purged walk-forward windows — machinery exercise only. **Synthetic
  can never produce GO by construction.**
- **Cash-and-carry (real):** `NOT-RUN — REAL DATA REQUIRED`. No real funding/
  basis history was available.

## Mining results and assumptions

Example S21-like rig (200 TH/s, 3.5 kW, $0.06/kWh, BTC $60k, 3% monthly
difficulty growth, one mid-horizon halving, 3-year horizon):

- **Dynamic NPV −$5,029** vs V1 constant-flow NPV −$1,068 → **$3,961
  overstatement removed.** Production cost ≈ $65,745/coin > $60k price; IRR
  undefined; no discounted payback → **NO-GO**.

Assumptions are inputs, not forecasts: difficulty growth, halving schedule,
price drift/scenarios, degradation, energy inflation, tariff, and pool scheme
are all explicit and configurable. A real GO requires a real attributable fresh
market snapshot, a real per-site tariff (e.g. a CFE bill), and a real pool
contract. `MINING_HARDWARE_CONTROL: DISABLED`;
`AUTHORIZED_TO_START_MINER=false`, `HARDWARE_CONTROL_ENABLED=false`,
`WALLET_SIGNING_ENABLED=false` (asserted by tests).

## Technical decisions (conservative defaults, documented)

- Bootstrap is per-period; no hardcoded `sqrt(252)` annualization.
- DSR assumes independent trials (no correlation shrinkage) — conservative,
  since it keeps the expected-max-Sharpe threshold as high as the data supports.
- Purge removes the label horizon from train-tail; embargo removes test-head;
  both in timestamp units.
- Synthetic provenance forces `NOT-RUN`; a synthetic campaign can never GO.
- Expected carry shrinks positive funding for reversion and never assumes an
  adverse carry reverts favourably.
- Mining break-evens are reported at day-0 conditions (documented simplification)
  while NPV/IRR use the full varying series.

## Findings not corrected (left for follow-up)

- V1 `mining/profitability.py` still exposes the single-point `_present_value`;
  V2 `cashflow.py` supersedes it but the CLI has not been repointed.
- `robustness.rolling_metrics` still annualizes with `252`; acceptable for a
  daily diagnostic but should take a frequency argument.
- No Monte-Carlo price bands in the mining projection (deliberately omitted — no
  justified stochastic model without real data).
- Parity report compares recorded records; wiring it to run both engines
  end-to-end is not automated.

## External blockers

- No authenticated exchange/market-data egress → cash-and-carry and mining real
  campaigns are `NOT-RUN` / `NEEDS-INPUT`.
- The environment's editable install aborts on the Debian-managed `cryptography`
  package; documented workaround in the worklog (CI is unaffected).

## Next five actions

1. Import a real, versioned funding/spot/perp snapshot set and run the
   pre-registered cash-and-carry matrix (`configs/carry/cash_and_carry_real_template.yaml`).
2. Capture a real attributable mining market snapshot + a real CFE tariff + pool
   contract, and re-run `project_mining_cashflow`.
3. Repoint the mining CLI/report from the V1 constant-flow NPV to
   `mining/cashflow.py`, and add a regression test asserting no constant-flow path.
4. Run a supervised paper trial against Alpaca **Paper** using the readiness
   runbook; feed the real fills into the parity report.
5. Merge PR #40 after review, then keep the conservative gates as the single
   source of truth for any promotion decision.

## Definition of done

Every slice started is complete, tested, documented, and committed; progress is
on GitHub; PR #40 remains a draft; the full suite is green; no profitability was
invented; and it is explicit what evidence is still needed before trading or
mining could be judged economically viable.
