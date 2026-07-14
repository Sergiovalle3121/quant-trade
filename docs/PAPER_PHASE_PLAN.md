# Paper Trading Phase Plan — Equal-Weight Quarterly, 24/7, Cloud

**Status: PLAN — awaiting human approval. Nothing in this document is deployed
or implemented until the repository owner approves it.**

## 0. Objective and non-objectives

The research program closed with two verdicts
([REAL_DATA_VERDICT.md](REAL_DATA_VERDICT.md),
[BENCHMARK_AWARE_VERDICT.md](BENCHMARK_AWARE_VERDICT.md)): 0/8 strategies pass
the conservative gate and equal-weight is undefeated. This phase pivots from
seeking alpha to **operating discipline**: run equal weight (SPY, QQQ, IWM,
TLT, GLD at 20%) with **quarterly** rebalancing, in **paper trading**, 24/7 in
the cloud.

- **Objective:** validate the operational plumbing end-to-end — signal →
  targets → orders → broker (paper) → fills → reconciliation → monitoring →
  weekly governance — under real market data, real time, real process
  failures.
- **Non-objectives:** finding edge (we know there is none and accept it);
  proving profitability; anything touching real money. `real_money_approved`
  stays structurally `false` (enforced by `trials/decisions.py:25-31` and
  every ops/readiness output).
- **Hard constraints:** paper-only, zero live endpoints (the code hard-blocks
  them: `execution/safety.py:28-35` allows only
  `https://paper-api.alpaca.markets`), new code limited to the four small
  wiring items in §4.

## 1. Architecture: two tracks, one system of record

The repo has two complementary paper engines. This phase runs both,
deliberately:

```
                        ┌──────────────────────── EC2 t3.small (Docker) ───────────────────────┐
                        │                                                                       │
  yfinance daily bars ──►  TRACK 1 · paper loop 24/7 (live/loop.py)                             │
                        │   strategy: equal_weight_quarterly (research registry, config-only)   │
                        │   sim fills @ next open · kill-switch fail-closed · circuit breakers  │
                        │   state/ + heartbeat → S3            ── system of record ──           │
                        │                                                                       │
                        │  TRACK 2 · Alpaca-paper rebalance job (host cron, rebalance days)     │
                        │   strategy-aware plan (W4) → submit-plan --confirm-paper-order        │
                        │   → next-day reconcile vs Alpaca account → audit JSONL                │
                        └───────────────┬──────────────────────────────┬────────────────────────┘
                                        │ artifacts (daily sync)        │ CloudWatch Logs (EMF)
                                        ▼                               ▼
                                 S3 bucket (versioned)        dead-man + job-failure alarms
                                        │                               │
                          trials/ops weekly cycle                 SNS → email
                          (review packs, decisions)
```

- **Track 1 (system of record):** the existing 24/7 `paper loop` runs
  `equal_weight_quarterly` continuously with simulated next-open fills. It
  already provides: kill-switch re-checked every cycle failing closed
  (`loop.py:180-192`), daily-loss/drawdown/max-orders circuit breakers,
  pending-target persistence across restarts (causality survives crashes),
  and a heartbeat every cycle. **Zero new code** — the loop resolves
  strategies from the research registry (`loop.py:374`), where
  `equal_weight_quarterly` is already registered.
- **Track 2 (real order lifecycle, per your stated preference for Alpaca
  paper):** on each rebalance day, a scheduled job generates a
  strategy-aware order plan (wiring item W4), submits it to the **real Alpaca
  paper API** through the existing hard-gated `broker submit-plan
  --confirm-paper-order --execute-paper` path, and reconciles the Alpaca
  account against the plan the next morning
  (`execution/reconciliation.py`). This exercises what the simulator cannot:
  real REST auth, order acknowledgement, fill lifecycle, partial
  fills/rejects, cancel paths, and reconciliation against an external source
  of truth.

**Why not Alpaca-only?** Three reasons, disclosed honestly: (i) the entire
trials/ops governance pipeline consumes loop/simulator artifacts — making
Alpaca fills the equity source of truth would require rewriting that pipeline
(violates "minimal new code"); (ii) the cloud job runner **deliberately**
refuses auto-submission (`cloud/jobs.py:209-220` always raises) — the
repo's design keeps broker submission as an explicit, human-flagged CLI path,
and this plan respects that boundary by invoking that CLI path from a
scheduled job with its existing `--confirm-paper-order --execute-paper`
flags; (iii) if Alpaca is down, Track 1 keeps producing governance data —
plumbing validation continues. Simulated equity and Alpaca fills **will
diverge** (different fill prices); §6 defines reconciliation pass criteria on
**share quantities and order states**, with cash/equity drift recorded as
slippage data rather than gated at the library's cent-level tolerance.

## 2. (a) Where it runs — options and monthly cost

| # | Option | What it is | Est. cost/month | Assessment |
|---|--------|-----------|-----------------|------------|
| 1 | **EC2 via the repo's Terraform** (`infra/aws/`) | t3.small + Docker `--restart unless-stopped`, S3 (versioned, lifecycle 180d), DynamoDB locks (on-demand), CloudWatch Logs (30d), SNS+email, ECR, SSM-only access (no SSH) | **~$19–22** (instance $15.20 + EBS gp3 20GB $1.60 + logs/S3/ECR/alarms ~$2–5) | **Recommended.** Already provisioned, least-privilege IAM, review-first apply. |
| 1b | Same, downsized to **t3.micro** | `instance_type` is a variable; the workload is one loop cycle/hour + a weekly broker job — a micro is ample | **~$11–14** ($7.60 instance) | **Recommended variant.** Start micro; resize if memory-constrained (measure in week 1). |
| 2 | AWS Lightsail | $5–12 flat VPS | ~$5–12 | Not recommended: bypasses the Terraform IAM/S3/alarm provisioning; more manual glue, less auditability. |
| 3 | ECS Fargate + EventBridge | What some docs describe | ~$5–10 | Not recommended **because it does not exist**: the docs are aspirational; actual Terraform is EC2-only. Building it violates minimal-code. |

Notes: this Claude session's container is ephemeral and unsuitable for 24/7 —
the deployment target is your AWS account. There are **no cost guardrails in
the current Terraform** (no Budgets/billing alarms) — §5 adds a manual AWS
Budget alert (e.g. $30/month threshold) as a setup step, not code. Alpaca
paper accounts are free (you create one and store the two keys in Secrets
Manager under the name Terraform expects).

## 3. (b) Cadence — production quarterly, validation accelerated

The production rebalance is quarterly, but a 90-day phase would exercise the
full cycle exactly once — useless for plumbing validation. Two **parallel
sessions with disjoint configs, state dirs, session names, and trial IDs**,
so acceleration never contaminates production:

| | Session PROD | Session VAL |
|---|---|---|
| Config file | `configs/paper/loop_ew_quarterly_prod.yaml` | `configs/paper/loop_ew_weekly_validation.yaml` |
| Strategy | `equal_weight_quarterly` (default cadence: quarterly — **untouched**) | `equal_weight_quarterly` with `rebalance_frequency: weekly` (via wiring item W1) |
| Role | The real thing, from day 1 | Plumbing exerciser: ~12 full rebalance cycles in 90 days |
| Alpaca leg (Track 2) | On its quarterly rebalance (≥1 in the phase: 2026-10-01 falls inside a 90-day window starting mid-July) | Every weekly rebalance |
| State dir / session | `state/paper_loop/ew_quarterly_prod` | `state/paper_loop/ew_weekly_val` |
| Trial ID | `ew_quarterly_prod_90d` | `ew_weekly_val_90d` |

Both run the **same code path** (same signal function, same loop, same order
pipeline) — the only difference is the rebalance mask frequency parameter, so
every plumbing lesson from VAL transfers to PROD. Loop cycle interval: 3600s
(cycles are idempotent; ~23 no-op heartbeat cycles + 1 acting cycle per
trading day). Provider: `yfinance` daily bars, `history_bars: 400` (spans
quarter boundaries with margin).

Circuit-breaker settings for both sessions (loop halts, operator clears):
`max_daily_loss_pct: 0.06`, `max_total_drawdown_pct: 0.30`,
`max_orders_per_day: 20`. Rationale: a fully-invested 5-ETF portfolio
routinely moves 3–6% in a bad day (2020-03-16: −10.9% SPY); tighter breakers
would halt the session on market beta rather than plumbing faults. Note the
**trial policy** (`configs/trials/trial_policy_conservative.yaml`) still
flags drawdown < −10% as blocking → the weekly decision will recommend
`pause_trial` during a genuine bear move. We accept that: handling a
policy-driven pause/resume is itself plumbing worth validating, and we do
not touch the policy.

## 4. Minimal new code (the complete list — nothing else gets written)

| # | Item | Size (est.) | Why it is indispensable |
|---|------|-------------|--------------------------|
| W1 | `rebalance_mask` gains `"quarterly"`; `equal_weight_quarterly` gains `rebalance_frequency` param (default `"quarterly"` — production semantics unchanged, existing tests keep passing) | ~15 lines + tests | Enables the accelerated VAL session on the identical code path. Without it, weekly-cadence EW needs a different strategy function → validation wouldn't validate production. |
| W2 | Paper loop `_write_heartbeat` additionally emits the `heartbeat_age_seconds` EMF metric (namespace `QuantTrade/CloudPaper`, dimension `job=heartbeat`) | ~15 lines + test | **The provisioned dead-man alarm currently has no data source**: `cloudwatch.tf:5-21` alarms on a metric nothing emits (the loop only writes the heartbeat *file*). With W2, loop death → metric goes missing → `treat_missing_data=breaching` fires → SNS → email. Zero-infra fix to a real gap. |
| W3 | `quant-trade paper export-session`: materialize the standard artifact set (`account_snapshots.csv`, `orders.csv`, `fills.csv`, `positions.csv`, `events.csv`, `paper_metrics.json`, …) from a 24/7 loop session's persisted state, reusing `paper/reports.py` writers | ~70 lines + tests | The loop persists state JSON only; the entire trials/ops pipeline (`trials export-daily-records`, `ops run-cycle`, reconciliation, dashboards) consumes the CSV artifact format. This is the bridge that lets governance see the 24/7 sessions. |
| W4 | `quant-trade broker rebalance-plan`: strategy-aware order plan — load loop session state + fresh panel → `get_research_signal_model(...)` targets → existing `target_weights_to_orders(...)` → existing `order_mapper` → standard plan dir consumed by the **existing** `submit-plan`/`reconcile` | ~120 lines + tests | Today `broker plan` fabricates a placeholder order (`cli.py:681-689`) and never runs a strategy. W4 is the only missing link between the registry signal and the real Alpaca paper order lifecycle — everything downstream (safety gates, submission, audit, reconciliation) already exists. |

Total: ~220 lines of glue + tests, all reusing existing components. **Not
touched:** engines, cost models, risk validators, safety gates, selection
gates, trial policy, Terraform resources (only `terraform.tfvars` values),
anything live-trading-adjacent.

## 5. (c) Monitoring and alerting — how you find out

Signal-to-notification matrix (what reaches your inbox vs. what waits for the
weekly review):

| Failure | Detection | Notification path | Latency |
|---|---|---|---|
| Loop process/host dies | Dead-man alarm: `heartbeat_age_seconds` EMF missing/stale (W2) | CloudWatch alarm → SNS → **email** | ≤ 15 min |
| Container crash | Docker `--restart unless-stopped` auto-recovers; restart visible in logs; if crash-looping → heartbeat stale → dead-man alarm | email (via dead-man) | ≤ 15 min |
| Loop halts itself (kill switch, daily-loss, drawdown breaker) | Heartbeat keeps writing with `status: paused` + `action: halted`; cron watcher greps heartbeat JSON status → `aws sns publish` on transition (runbook script, host-side, no repo code) | email | ≤ 1 h |
| Track-2 job fails (plan/submit/reconcile non-zero exit) | Cron wrapper publishes to the SNS alerts topic on non-zero exit (host IAM already allows `sns:Publish`) | email | immediate |
| Order rejected by Alpaca | Present in `submit-plan` outputs + `broker_events.jsonl` audit; non-zero-exit path above for hard failures; soft rejects surface in daily ops cycle + weekly review | email (hard) / weekly pack (soft) | immediate / ≤ 7 d |
| Reconciliation mismatch | Daily `broker reconcile` after rebalance days; wrapper alerts if quantity mismatch or orphan orders (§6 tolerances); `ops incidents create` opens the incident record | email + incident | next morning |
| Data staleness / quality | Loop no-ops on stale panels (no new bar → heartbeat only); yfinance gaps surface as missed acting cycles in weekly reliability report | weekly pack | ≤ 7 d |
| AWS cost runaway | AWS Budget alert at $30/month (manual setup step — the Terraform has none) | email | daily granularity |

Local `ops` alerts (`outputs/alerts/alerts.jsonl`) remain log-only by design;
the paths above are the ones that page a human. Setup includes **confirming
the SNS email subscription** (unconfirmed = alarms notify nobody) and firing
`ops alert-test` + a forced dead-man test (stop the container for >1h) during
week 1 so we never trust an untested alarm.

## 6. (d) Measurable "plumbing validated" criteria

All criteria are measured from committed/synced artifacts, not memory:

1. **≥ 12 successful E2E rebalances** on VAL (weekly) + **≥ 1 production
   quarterly rebalance** on PROD (2026-10-01): signal → plan → Alpaca
   submission → terminal order states → reconciliation pass.
2. **Order lifecycle integrity:** 100% of submitted orders reach a terminal
   state (filled / canceled / rejected-with-recorded-reason) within the
   rebalance day; **zero orphan orders** (open at Alpaca with no local plan
   record) across the phase.
3. **Reconciliation:** after every rebalance, per-symbol **share quantities
   match the plan exactly** (tolerance 1e-6) and `missing/extra_positions`
   are empty. Cash/equity differences vs the simulated track are **recorded
   as slippage data** (expected: real fills ≠ simulated next-open fills) and
   must stay < 0.5% of equity per rebalance; anything larger → incident.
   **Zero unreconciled positions at every weekly review.**
4. **Uptime:** heartbeat present for ≥ 99% of expected cycles over the phase;
   zero heartbeat gaps > 3h without a corresponding incident record
   explaining them; the dead-man alarm fired **only** during the deliberate
   test and injected failures.
5. **≥ 3 injected failures handled cleanly** (scheduled, announced in the
   weekly report beforehand):
   - **Week 2 — kill-switch drill:** `ops drill all` (the 5 existing drills)
     plus a *live* S3 kill-switch activation while the loop runs → loop
     halts fail-closed → clear → resume. (Also satisfies the trial policy's
     `require_kill_switch_drill`.)
   - **Week 5 — process kill:** `docker kill` mid-cycle → auto-restart →
     verify state and `pending_target` survive and the next fill respects
     next-open causality (no double-execution, no skipped target).
   - **Week 8 — credential failure:** temporarily rotate/revoke the Alpaca
     paper key before a VAL rebalance → submission fails → alert received →
     key restored → rebalance completes on retry; audit trail complete.
   Each injected failure must produce: an alert that reached email, an
   incident opened and resolved with notes, and no state corruption.
6. **Governance cadence:** 13/13 weekly review packs generated
   (`trials run-review-cycle`), each with a recorded human decision;
   `real_money_approved=false` in every record (automatic).
7. **CI green** for the phase's code (W1–W4) before deployment; no CI
   regression during the phase.

The phase **fails** (verdict: plumbing NOT validated) if: any orphan order
survives a week, reconciliation mismatches recur without root cause, the
dead-man alarm produces false silence (process dead, no email), or state
corruption is observed after any restart.

## 7. (e) Duration and weekly ops report

**Duration: 90 days** (the trials registry only accepts 30/60/90;
90 guarantees ≥ 1 real quarter boundary from any reasonable start and 12–13
weekly cycles). Trials: `ew_quarterly_prod_90d` and `ew_weekly_val_90d`,
`review_frequency: weekly`, registered in `configs/trials/trial_registry.yaml`
with `research_run_dir` pointing at the committed equal-weight evidence
(`docs/real_data_evidence/runs/equal_weight_quarterly_etf_real_daily`) so
expectation ranges derive from real research artifacts.

**Timeline:**
- **Week 0 (setup):** W1–W4 code + tests + PR; `terraform apply` (reviewed);
  ECR push; SNS confirm; Alpaca paper keys → Secrets Manager; AWS Budget
  alert; `ops drill all` locally; compose dry-run.
- **Weeks 1–2 (shakedown):** both loops running, Track 1 only; alarm tests
  (deliberate dead-man trip); first VAL rebalances simulated-only; injected
  failure #1.
- **Weeks 3–12 (full dual-track):** Alpaca submissions on every VAL weekly
  rebalance; PROD quarterly rebalance (~Oct 1) via the same path; injected
  failures #2–#3; weekly review cycle throughout.
- **Week 13 (close):** `trials review final` + `trials decision record` +
  `trials archive` for both trials; write `docs/PAPER_PHASE_VERDICT.md`
  scoring every criterion in §6 pass/fail with artifact links.

**Weekly ops report** — generated by the existing machinery
(`trials run-review-cycle` → `review_pack.md` per trial + `ops run-cycle` →
`cycle_summary.md`), synced to S3, and the combined summary committed to the
repo under `docs/paper_phase_reports/week_NN.md` (text-only, secret-redaction
is built into the report writers). Fixed format:

```
# Paper Phase — Week NN (dates)
1. Status:        uptime %, cycles (acting/noop), heartbeat gaps, alarms fired
2. Rebalances:    planned/executed per session; orders submitted/filled/rejected (+reasons)
3. Reconciliation: pass/fail per rebalance; qty diffs; cash drift (slippage data)
4. Incidents:     opened/resolved (incl. injected failures with outcome)
5. Portfolio:     equity, drawdown, tracking vs daily-EW benchmark (informational, not a gate)
6. Drift/policy:  trial drift status; policy decision recommendation vs human decision
7. Next week:     scheduled drills/rebalances/actions
```

## 8. Safety guardrails (unchanged, restated)

Paper-only enforced in code at every layer: loop config forbids `broker` keys;
broker config allows only the official Alpaca paper endpoint (re-validated on
every HTTP call); cloud config hard-fails on `allow_live_trading`;
`real_money_approved` forced false in every decision/readiness record; kill
switch (S3 object or env var) fails closed on unreadable storage; EC2 host has
no inbound access (SSM only) and least-privilege IAM. None of this is modified
by this plan.

## 9. Known risks and open decisions

- **Simulated-vs-Alpaca divergence** is expected and bounded (§6.3); if cash
  drift systematically exceeds 0.5%/rebalance, that is a *finding about our
  cost model*, recorded, not silently tolerated.
- **Trial policy pauses on market beta:** a −10% portfolio drawdown triggers a
  blocking `pause_trial` recommendation by design. We treat handling that
  pause as plumbing validation, not as a reason to loosen the policy.
- **yfinance as the data leg** is free but unwarranted; repeated failures show
  up as missed acting cycles (weekly reliability). If it proves flaky, the
  fallback is the csv provider fed by a scheduled fetch — config change, no
  new code.
- **Single instance, no redundancy:** host loss = outage until manual
  redeploy (Docker restart covers container death and reboots only). Accepted
  for a $12–20/month paper phase; the dead-man alarm bounds detection time.
- **Open decision for the owner:** t3.small vs t3.micro at start (§2); and
  whether weekly reports get committed to the repo (proposed) or live only in
  S3.

## 10. Pre-registered verdict template

At day 90, `docs/PAPER_PHASE_VERDICT.md` scores §6.1–6.7 pass/fail from
artifacts. **Plumbing validated** = all seven pass. Anything else = the
specific failures, root causes, and whether a 30-day extension (registry
supports it via `extend_trial`) or a redesign is warranted. The verdict never
contains a real-money recommendation — that concept stays out of scope by
construction.

---
*Research/backtesting/paper-trading only. This plan authorizes no live
trading, no real money, and no new endpoints. Approval of this plan means
approval to implement §4 and execute §7's timeline, nothing more.*
