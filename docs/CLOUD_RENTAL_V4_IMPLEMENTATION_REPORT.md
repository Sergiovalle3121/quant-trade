# Cloud Rental V4 — Implementation Report

Sprint objective: make the platform able to collect real evidence, compare
rented infrastructure (AWS / Alibaba Cloud — the owner buys no mining
hardware), and emit honest, reproducible economic decisions. Priority was
preventing false positives, not reaching a GO. No cloud resources were created,
no miners ran, no orders were sent, no money was spent.

## SHAs, base, and PRs

- **Initial `origin/main`:** `cf97401` (pre-consolidation).
- **Consolidation:** at the owner's explicit request, PR #40 (head `f35b3d2`,
  CI green, mergeable clean) was squash-merged into main as **`4afc7e4`**. A
  26-branch audit (merge-tree + byte-level tree comparison) proved **no open
  branch holds unintegrated work**; the obsolete #31 branch (would delete
  12,120 lines) stays excluded.
- **Base chosen:** `origin/main` = `4afc7e4` (PR #40 merged ⇒ per protocol the
  new branch starts from updated main, not stacked).
- **Branch:** `claude/cloud-rental-evidence-v4` → final SHA **`ad3cfb3`**.
- **Prior PR:** #40 (merged). **New PR:** **#41 (draft, open, never merged)** —
  <https://github.com/Sergiovalle3121/quant-trade/pull/41>.

### Commits (small, reviewable, red-tests-first)

1. `21a369f` test: reproduce v4 evidence and rental defects (A–E, G as strict xfail)
2. `27c35f3` fix: make evidence artifacts canonical JSON and byte-bound (A, B)
3. `7b9f8e0` feat: collect and audit point-in-time funding history
4. `8c73355` fix: include basis and collateral in carry economics (C, D)
5. `15afa80` feat: add policy-gated AWS and Alibaba rental evaluation (incl. F)
6. `88e2947` fix: recompute mining freshness and retire promotable v1 path (E)
7. `ad3cfb3` feat: require drill evidence for paper readiness (G)

Diff vs main: **43 files, +5,148/−115**.

## Validation (executed on `ad3cfb3`)

| Check | Result |
| --- | --- |
| `ruff check .` | All checks passed |
| `python -m mypy src` (2.3.0, matches CI) | Success, 235 files |
| `python -m compileall -q src tests` | OK |
| `python -m pytest -q` | **538 passed, 0 xfailed** |
| `git diff --check` | clean |

Baseline on `4afc7e4` was 461 passed; this sprint added 77 tests. Terraform/ROS
was not touched. Every defect-reproduction test that started red (xfail-strict)
now passes with the defect fixed — none was deleted or weakened.

## Defects reproduced and corrected (all seven)

- **A** — carry `results.json` was YAML behind a `.json` name while promotion
  read `json.loads`. Fixed: canonical, atomic, real JSON everywhere
  (`evidence/canonical_json.py`); explicit YAML→JSON migrator, no permissive
  fallback.
- **B** — dataset binding hashed the *config*, not the data. Fixed: manifests
  hash the dataset's REAL bytes (+size, rows, time range, symbols, venues,
  schema, provenance); re-verification fails on a single flipped byte; the
  ledger stores the byte SHA.
- **C** — 40 real-labelled snapshots (~13 days) reached GO with ZERO
  walk-forward windows. Fixed: sufficiency gate (≥90 funding events, ≥30 days,
  ≥2 walk-forward windows, real provenance) → `NOT_RUN_INSUFFICIENT_REAL_DATA`;
  economics gate (2×/3× cost stress, bootstrap lower bound, PSR≥0.95,
  margin-path, subperiods, walk-forward majority) → `REJECTED`/`PAPER_CANDIDATE`;
  plus `evaluate_carry_promotion`, an artifact-recomputing review the campaign
  cannot skip. "GO" no longer exists in the carry vocabulary.
- **D** — basis P&L was missing. Fixed: the return series books funding P&L,
  spot-leg and perp-leg mark-to-market (= basis convergence P&L), collateral
  yield, and all costs, per component; `carry/capital.py` adds trajectory
  margin paths (min maintenance distance, breach index, MAE), capital required,
  collateral identity invariants, and residual delta.
- **E** — mining freshness trusted a caller-supplied `staleness_seconds`.
  Fixed: age is recomputed from `captured_at_utc` against an injectable
  evaluation clock; naive timestamps rejected; future snapshots rejected; a
  lying `staleness_seconds=0` cannot rescue an old snapshot.
- **F** — a fictitious 100 TH/s cloud "worker". Fixed: a manual `hashrate_hs`
  is rejected for cloud SKUs; benchmarks are valid only for the exact
  provider+SKU+accelerator; no GPU→ASIC or cross-SKU extrapolation; SHA-256 on
  CPU/GPU without an exact-SKU measurement is `BLOCKED_INCOMPATIBLE_HARDWARE`.
- **G** — declarative readiness. Fixed: `broker_mode` explicit (no default),
  endpoint declared, and seven executed-drill artifacts required (timestamp,
  hash, expiry, failure injection where applicable). Booleans alone are
  `NOT_READY`. The parity drill executes the real engine.

## Real data captured, or its absence

**No real market data was captured in this sandbox** (no authenticated
exchange egress). What exists now that did not before: a point-in-time
collector (`carry collect-once`) with an append-only deduplicated JSONL store,
a dataset auditor (`carry dataset-audit`), byte-bound manifests, and a
`jsonl_observations` campaign source — so real funding history can be
accumulated across days/weeks with cron and consumed with full provenance. One
captured observation is one observation; nothing here claims history exists.

## AWS / Alibaba matrix (offline example configs; quotes are fixtures)

| Provider | Purpose | Policy | Benchmark | Economics | Decision |
| --- | --- | --- | --- | --- | --- |
| AWS | control_plane | ordinary compute | n/a | ~$0.03/h fixture within $50/mo ceiling | **PAPER_CONTROL_PLANE_CANDIDATE** |
| AWS | hashing_worker | no written §1.25 approval artifact | not reached | not reached | **BLOCKED_PENDING_WRITTEN_APPROVAL** |
| Alibaba | control_plane | ordinary compute | n/a | ~$0.04/h fixture within $50/mo ceiling | **PAPER_CONTROL_PLANE_CANDIDATE** |
| Alibaba | hashing_worker | mining = security-violation lock example | not reached | not reached | **BLOCKED_PROVIDER_POLICY** |

Both providers can host the *software* (collector, research, dashboards, paper
runtime) within budget; **neither is currently eligible for hashing** — the
block is legal/operational and is reported as such, never as an economic NO-GO.
Even if policy were satisfied: no measured benchmark of any cloud SKU exists
(→ `BLOCKED_MISSING_BENCHMARK`), and a measured ~20 GH/s GPU benchmark against
a $10/h SKU yields fractions of a cent of hourly revenue (`ECONOMIC_NO_GO`,
tested). Free Tier/credits are categorically blocked. Spot and on-demand price
sources are structurally separated. No multi-year NPV is applied to rentals.

**Benchmarks:** none exist (none were invented). **Quotes:** fixtures only,
labelled as such; the read-only Price List / Spot-history / DescribePrice
adapters are implemented but were not exercised (no credentials, no network).
**Policy snapshots:** source URLs registered with capture instructions; no
snapshot was fabricated, so the hashing rows fail closed exactly as designed.

## Cash-and-carry status

Synthetic campaign: `NOT_RUN_INSUFFICIENT_REAL_DATA` (synthetic provenance).
No real campaign ran (no real funding history yet). The economics now include
basis P&L, collateral yield, capital efficiency and return on immobilized
capital, trajectory liquidation distance and MAE, and 2×/3× cost stress — with
`PAPER_CANDIDATE` as the best possible outcome, gated again by the
artifact-recomputing promotion review.

## Mining status

The V1 constant-flow path is stamped `legacy_non_promotable` (reports + CLI
warning); the dynamic engine (`mining project`) is the only promotable path.
Freshness is recomputed against an explicit clock. `mining rental-evaluate`
composes fresh market snapshots + hashprice-divergence fail-closed gate +
cloud_rental policy/benchmark/economics for generic cloud compute; owned
hardware stays in `mining project`; hosted-ASIC rental is a documented
extension contract only (deliberately unimplemented — no marketplace calls).

## Paper status

Readiness requires executed-drill evidence (see defect G above). The
`readiness-evidence` CLI validates artifacts and can execute the parity drill
for real. With no drill artifacts on file for a production config, the honest
current answer is **NOT_READY** — becoming READY requires actually running the
drills (kill the process, trip the switch, reconcile) and recording them.

## External blockers

1. No authenticated exchange egress → real funding capture must run outside
   this sandbox (any host with public HTTPS; cron + `carry collect-once`).
2. No AWS/Alibaba credentials → real quotes not captured (adapters ready).
3. AWS hashing requires a written Trust & Safety approval; Alibaba hashing
   requires a written contractual exception — both are human/legal actions.
4. Benchmarks require actually renting an instance (spend approval) — out of
   scope by design this sprint.
5. Paper drills (kill-switch, recovery, orphan) need a live supervised session
   to execute honestly — operator action, recorded via `record_drill`.

## Next five actions

1. Deploy the collector on a control-plane host (either provider qualifies) and
   run `carry collect-once` on a cron for ≥30 days; audit weekly with
   `carry dataset-audit`.
2. Capture policy snapshots of the AWS/Alibaba terms (hash + date + human
   review) and file them as `ProviderPolicyEvidence`; decide whether to request
   AWS written approval — without it, hashing stays blocked.
3. Capture real quotes with the read-only adapters (Price List, Spot history,
   DescribePrice) and re-run `cloud-rental compare` with fresh data.
4. When funding history crosses the sufficiency gate, run
   `carry research-v2` on the collected JSONL and submit the artifacts to
   `evaluate_carry_promotion`.
5. Execute the paper drills in a supervised session, record them with
   `record_drill`, and re-run `paper readiness-evidence`.

## Status lines

```
STATISTICAL_INTEGRITY: PASS
EVIDENCE_CHAIN: PASS
REAL_FUNDING_HISTORY: NOT-RUN
CASH_AND_CARRY_EDGE: NOT-RUN
AWS_CONTROL_PLANE: CANDIDATE
AWS_HASHING_WORKER: BLOCKED
ALIBABA_CONTROL_PLANE: CANDIDATE
ALIBABA_HASHING_WORKER: BLOCKED
PAPER_READINESS: NOT_READY
REAL_MONEY: NO-GO
LIVE_ORDER_SUBMISSION: DISABLED
MINER_EXECUTION: DISABLED
MINING_HARDWARE_CONTROL: DISABLED
WALLET_SIGNING: DISABLED
AWS_RESOURCES_CREATED: FALSE
ALIBABA_RESOURCES_CREATED: FALSE
EXTERNAL_SPEND_AUTHORIZED: FALSE
```
