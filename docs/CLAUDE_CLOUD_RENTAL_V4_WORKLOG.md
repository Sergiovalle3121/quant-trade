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
