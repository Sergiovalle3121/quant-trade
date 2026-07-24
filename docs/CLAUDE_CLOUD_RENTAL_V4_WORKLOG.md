# Claude V4 Sprint Worklog — Cloud Rental Evidence

Sprint objective: turn the platform into a system that can collect real
evidence, compare rented infrastructure (AWS / Alibaba Cloud), and emit honest,
reproducible economic decisions. Owner constraint: **no hardware purchases —
rented capacity only**. No cloud resources are created, no miners run, no
orders are sent, no money is spent.

## Safety posture (held the whole sprint)

`REAL_MONEY: NO-GO` · `LIVE_ORDER_SUBMISSION: DISABLED` ·
`MINER_EXECUTION: DISABLED` · `MINING_HARDWARE_CONTROL: DISABLED` ·
`WALLET_SIGNING: DISABLED` · `AWS_RESOURCES_CREATED: FALSE` ·
`ALIBABA_RESOURCES_CREATED: FALSE` · `EXTERNAL_SPEND_AUTHORIZED: FALSE`

## CP0 — Consolidation + baseline + defect reproduction — 2026-07-24T18:35Z

**Branch:** `claude/cloud-rental-evidence-v4` from `origin/main` = `4afc7e4`.

### Consolidation (user-directed merge of all progress)

- PR #40 (head `f35b3d2`, CI success runs 30075969605/30075967053,
  `mergeable_state: clean`) was marked ready and **squash-merged into main as
  `4afc7e4`** at the owner's explicit request ("mergea todo el avance").
- **Open-branch audit** (26 remote branches, merge-tree test + byte-level tree
  comparison):
  - 16 branches: merge adds nothing (`git merge-tree` result tree == main tree).
  - 8 branches (`agent/evidence-validation-v3`, `codex/{backtest-execution-
    convergence, execution-model-v2, mining-economics-v2, backtest-cash-
    invariants-v1, aws-profit-gates-v1, profitability-stack-v1,
    quant-platform-v2}`): trees **byte-identical** to their merged squashes
    (#38, #37, #36, #35, #34, #33, #32, #30). Nothing to integrate.
  - `codex/enhance-quant-trade-platform-for-algorithmic-trading` = the obsolete
    PR #31: merging it would delete 12,120 lines of later work. Excluded, as
    the owner previously directed.
- **Conclusion: no open branch contains unintegrated work. Everything is in
  `main` @ `4afc7e4`.**

### Baseline (executed on `4afc7e4`)

| Check | Result |
| --- | --- |
| `ruff check .` | All checks passed |
| `python -m mypy src` (2.3.0, matches CI) | Success, 219 files |
| `python -m compileall -q src tests` | OK |
| `python -m pytest -q` | **461 passed** |
| `git diff --check` | clean |

Note: the old PR #40 body said 417 and the previous worklog said 452 — both were
point-in-time snapshots during that session. The revalidated count on the merged
head is **461**. This sprint reports only revalidated numbers.

### Defects reproduced (tests in `tests/test_v4_defect_reproduction.py`, all
`xfail(strict=True)` until each block fixes its defect — 8 xfailed)

- **A — carry results.json is YAML.** `write_carry_artifacts` writes
  `results.json` via `yaml.safe_dump`; `promotion_v2` reads with `json.loads`.
  Red test: `json.loads(results.json)` fails today.
- **B — dataset binding hashes config, not bytes.** The carry ledger records
  `sha256_hex(config["data"])`. Red test: same path, different snapshot bytes →
  identical `dataset_sha`.
- **C — thin real history reaches GO.** Empirically: 40 real-labelled snapshots
  (~13 days of 8h funding, constant positive) → **GO with ZERO walk-forward
  windows** (n=2/6 were blocked only *incidentally* by the bootstrap because
  the entry-cost interval dominates a 6-obs p2.5). Nothing explicitly requires
  minimum funding events, minimum time range, non-empty walk-forward, DSR, or
  promotion V2. Red test encodes n=40 → must not be GO.
- **D — basis P&L missing.** `carry_campaign_returns` accounts funding minus
  costs only. Red test: a 1%→0 perp-premium convergence with zero funding must
  surface a `basis_pnl` column with non-zero P&L; today the column doesn't
  exist.
- **E — freshness is caller-supplied.** `require_fresh` trusts
  `staleness_seconds`. Red tests: a years-old snapshot with
  `staleness_seconds=0` must fail against an injected `evaluated_at_utc`; a
  future-dated snapshot must fail. Today the signature doesn't even accept an
  evaluation clock.
- **F — fictitious cloud hashrate.** `configs/mining/aws_profitability_example.yaml`
  declares a 100 TH/s "worker" with no instance binding or benchmark. The
  rejection gate belongs to the (not yet existing) `cloud_rental` package, so
  the red test for F lands with Block 4 (benchmark-evidence gate) rather than
  in the reproduction file.
- **G — declarative readiness.** `evaluate_paper_readiness` defaults
  `broker_mode` to `"paper"` (a config missing it passes) and accepts booleans
  with no executed-drill artifacts. Red tests: missing broker_mode ⇒ NOT_READY;
  booleans-without-drills ⇒ NOT_READY.

**Next:** Block 1 — evidence contract (canonical JSON, byte-bound dataset
manifests, lineage, atomic writes) fixing defects A and B.

## CP1 — Blocks 1–3 complete — 2026-07-24T19:20Z

**Branch/SHA:** `claude/cloud-rental-evidence-v4`; Block 1 `27c35f3`, Block 2
`7b9f8e0`, Block 3 in this commit. PR #41 draft open; CI green per push.

- **Block 1 (defects A, B fixed):** `evidence/canonical_json.py` (deterministic
  canonical JSON, NaN rejected, atomic writes) + `evidence/manifest.py`
  (byte-SHA-256 dataset manifests, re-verification fails closed on a one-byte
  change, explicit YAML→JSON migrator). `write_carry_artifacts` now emits real
  JSON and binds the ledger to dataset bytes. Defect tests A/B green.
- **Block 2:** point-in-time collector (`carry/store.py`, `quality.py`,
  `collector.py`): append-only JSONL with idempotent dedup, quarantined corrupt
  lines, gap/duplicate/monotonicity audit, fixture + lazy ccxt read-only
  adapters (no trading verbs — asserted), `collect-once` / `dataset-audit` CLI,
  `jsonl_observations` campaign source fail-closed on quarantine.
  Validation after Block 2: **488 passed, 6 xfailed**.
- **Block 3 (defects C, D fixed):** `carry_campaign_returns` now books the
  TOTAL economic return — funding P&L, spot-leg and perp-leg mark-to-market
  (basis convergence P&L), collateral yield, minus turn and carrying costs.
  `carry/capital.py` adds capital-required breakdown, trajectory margin path
  (min maintenance distance, breach index, MAE, variation margin), collateral
  identity invariants, residual delta. The campaign gate now separates
  **sufficiency** (real data, ≥90 funding events, ≥30 days span, ≥2 walk-forward
  windows → otherwise `NOT_RUN_INSUFFICIENT_REAL_DATA`) from **economics**
  (positive net, survives 2×/3× costs, bootstrap lower bound, PSR≥0.95, margin
  path unbreached, both subperiod halves positive, majority of walk-forward
  windows positive → `REJECTED` on any failure, else `PAPER_CANDIDATE`).
  `evaluate_carry_promotion` reopens artifacts (strict JSON, manifest
  re-verified byte-for-byte, ledger integrity, recomputed PSR, non-empty
  walk-forward) so the campaign cannot skip promotion review. The defect-C
  construction (40 snapshots, 0 windows) now lands in
  `NOT_RUN_INSUFFICIENT_REAL_DATA`.

**Validation (executed):** `ruff` pass · `python -m mypy src` pass (225 files) ·
`python -m pytest -q` → **501 passed, 4 xfailed** (E×2, G×2 pending Blocks 5–6).

**Next:** Block 4 — cloud_rental package (AWS/Alibaba policy gates, read-only
quotes, mandatory benchmarks, rental economics, feasibility matrix).

## CP2 — Blocks 4–7 complete (sprint delivered) — 2026-07-24T20:20Z

**Branch/SHA:** `claude/cloud-rental-evidence-v4` @ Block 4 `15afa80`, Block 5
`88e2947`, Block 6 `ad3cfb3`, report in this commit. PR #41 draft; CI green per
pushed head.

- **Block 4** (`cloud_rental/`, 23 tests): fail-closed policy gates with the
  official sources registered (AWS hashing → BLOCKED_PENDING_WRITTEN_APPROVAL;
  Free Tier/credits categorically blocked; Alibaba hashing →
  BLOCKED_PROVIDER_POLICY by default; ambiguous → BLOCKED_POLICY_UNKNOWN;
  control plane evaluable and distinct). Mandatory exact-SKU benchmark
  evidence (defect F: manual hashrate rejected; no cross-SKU/GPU→ASIC
  extrapolation; CPU/GPU sha256 → BLOCKED_INCOMPATIBLE_HARDWARE). Quote
  source-family separation (Spot ≠ Price List ≠ DescribePrice), recomputed
  freshness (future/expired fail). Rental economics in cancelable hourly flows
  (multi-year horizons refused), 1×/2×/3× margins, budget ceiling. Read-only
  price adapters with no creation verbs (asserted). CLI quote/evaluate/compare;
  4 example configs; `docs/CLOUD_RENTAL_FEASIBILITY.md` with the 4-row matrix.
- **Block 5** (defect E): freshness recomputed from `captured_at_utc` vs an
  injectable clock; future snapshots rejected; V1 constant-flow marked
  `legacy_non_promotable`; new `mining rental-evaluate` with hashprice
  divergence fail-closed and deployment-model separation.
- **Block 6** (defect G): drill-evidence readiness (7 executed drills with
  hash/timestamp/expiry/failure-injection; broker_mode explicit; booleans
  alone NOT_READY; real executable parity drill; `paper readiness-evidence`
  CLI).
- **Block 7:** final matrix run, `docs/CLOUD_RENTAL_V4_IMPLEMENTATION_REPORT.md`
  with the exact status lines, PR #41 body updated with revalidated numbers.

**Final validation (executed on `ad3cfb3`):** ruff pass · mypy pass (235
files) · compileall OK · **pytest 538 passed, 0 xfailed** · `git diff --check`
clean. All seven defects (A–G) reproduced red first, fixed, and green.

**Verdicts:** both providers CANDIDATE for control plane; AWS hashing BLOCKED
(written approval required); Alibaba hashing BLOCKED (provider policy); real
funding history NOT-RUN (collector ready); carry NOT-RUN; paper NOT_READY
(drills must actually run). Safety: REAL_MONEY NO-GO; LIVE_ORDER_SUBMISSION,
MINER_EXECUTION, MINING_HARDWARE_CONTROL, WALLET_SIGNING all DISABLED;
AWS/ALIBABA_RESOURCES_CREATED FALSE; EXTERNAL_SPEND_AUTHORIZED FALSE.
