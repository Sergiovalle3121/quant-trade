# Crypto validation gates (research only)

This document is the operational contract for the Bybit Spot low/mid-cap
study. It is not a profitability claim and it does not authorize external or
real-money action. The repository contains no Bybit order-submission adapter.

## Current verdict

**INSUFFICIENT_EVIDENCE / NO-GO for P&L generation.** The historical panel
identified by the hash-bound invalidation artifact is retained for
traceability and marked `INVALID_LOOKAHEAD` in
`data/experiments/crypto_lowcap_2026_08/INVALIDATION.json`.

The companion invalidation also makes the holdout seal and the H1-H4
pre-registrations tied to that digest unusable. The reserved holdout has not
been evaluated by this remediation. It must not be read until a replacement
`TRUSTED_CAUSAL` panel, new ExperimentSpec v2 seals, and a frozen candidate
exist.

The implementation branch is **draft-only scaffolding**. Its status remains
NO-GO: opening a draft PR records and reviews the controls, but does not make
the dataset valid, authorize a holdout reveal, promote a candidate, or support
a profitability claim. Merge remains blocked until the complete CI contract is
green and an independent reviewer approves the causal and economic bindings.

The four failures that dominate the decision are:

1. venue selection used the future length of each price history;
2. a global 20-bar filter used future survival to decide earlier membership;
3. target weights were executed at the same close that produced the signal;
4. absence/rank exit/gap was treated as a terminal delisting.

## Gate 0 - venue evidence

The only v1 policy is `configs/crypto/bybit_spot_demo.yaml`: Bybit, Demo,
Spot, dedicated subaccount, read + Spot permissions, IP allowlist, and no
withdrawal, transfer, margin, derivative, loan, live endpoint, credential
storage, or execution-adapter capability.

`quant_trade.ops.crypto_gates.evaluate_gate0` fails closed. A field that is
missing produces `INSUFFICIENT_EVIDENCE`; a contradictory value produces
`BLOCKED`. A PASS only removes this one research blocker. It never authorizes
an external action or money movement. The verdict persists the exact evidence
payload and hashes it separately as well as inside the full verdict digest, so
two PASS/BLOCKED results based on different observations cannot share a
binding.

Operator evidence still required outside this repository:

- Mexican KYC approval and contractual entity confirmation;
- Spot/API/subaccount availability and exact permission review;
- IP allowlist confirmation;
- account-specific fee capture for every symbol;
- minimum manual deposit and withdrawal round trip;
- one venue across dataset, cost model, and planned execution.

If any item fails, the fallback is a completely separate Binance experiment.
History from Binance must never be combined with Bybit fees/fills in one
ExperimentSpec.

## Gate 1 - causal panel

The panel builder must produce one Bybit series per stable identity
`CMC:<cmc_id>`. `ticker` and `venue_symbol` are time-varying metadata only.
Every row distinguishes:

- `eligible_to_open`: in the declared rank/capitalization band and past the
  causal warm-up;
- `tradable`: the fixed venue has an executable bar;
- `mark_price`: a valid valuation/exit mark;
- `data_status`: observed or explicitly degraded/missing state;
- `market_event`: rename, rank exit/reentry, gap, halt, announcement, or
  confirmed terminal event.

A rank exit blocks a new position but keeps later venue prices available for
valuation and exit. The 20-bar requirement is a running counter and enables
the instrument on its twentieth observed bar; it never deletes its first 19
rows. Every ticker binding, including an apparently unique one, must pass the
price-plausibility check.

Sensitive venue facts are governed by a separate `MarketEventLedger`, not
inferred from klines or missing panel rows. `HALT`, delisting announcement,
confirmed delisting/listing end, and any evidenced terminal recovery cite a
source and SHA-256 in that sparse ledger. Selection and holdout ledgers are
distinct manifest components. A protected run rejects a sensitive event copied
into `PanelRow.market_event` unless the active ledger contains the exact same
timestamp, stable instrument, venue, event, and recovery price. Derived panel
metadata such as gap, rename, and rank exit/reentry does not acquire terminal
semantics. An empty ledger is explicit evidence of no confirmed sensitive
event; it is never permission to reinterpret an absence.

Acceptance is byte-level prefix invariance: building `[start, T]` and
`[start, T + future]`, then cutting the latter at `T`, must produce identical
ordered records. Adversarial fixtures cover venue disagreement, reused ticker,
rename, 1-19 day listing, rank exit/reentry, one-bar gap, halt, confirmed
delisting, and incompatible price.

The canonical panel component is also lossless with respect to every finite
floating-point value consumed by the evaluator. It preserves round-trip float
precision, canonicalizes timestamps to UTC and signed zero, rejects NaN and
infinity, and sorts complete normalized records deterministically. Thus even a
sub-tenth-decimal price change changes the component digest; two economically
different in-memory panels cannot share a seal because of JSON rounding.

Hashes for account fees, measured cost profiles, and venue-event notices are
not accepted as self-attestations. Their original bytes are distinct manifest
components below the sealed provenance root and are rehashed before any signal
or P&L is evaluated. Account-specific fees also bind venue, API endpoint,
dedicated account scope, venue symbol, and an explicit UTC capture time.
Selection may read only its active evidence sources; it never opens either
holdout panel or holdout event component.

The protected runner also verifies the code actually executing. In a checkout,
the sealed full commit must equal Git `HEAD` and the complete tree—including
untracked files and submodules—must be clean. Installed builds and unsigned
sidecar metadata fail closed; they will require an independently verifiable
build attestation in a future version. A declared `code_commit` without Git
proof fails before targets are constructed, and the portable runtime proof
(commit, tree object, mode and clean status—not a local absolute path) is
included in the content-addressed run artifact.

No market bytes are committed or redistributed. A replacement manifest must
record source/component hashes, code commit, UTC policy, date range, gaps,
schema, venue policy, row/symbol counts, and license/terms status. Loading a
manifest verifies its embedded digest and then re-hashes each component at its
sealed, relative provenance path. `TRUSTED_CAUSAL` additionally requires zero
unexplained gaps; missing bytes, paths, gap evidence, or terms evidence fail
closed.

## Gate 2 - causal execution and falsifiable experiments

`quant_trade.research.crypto_evaluator` enforces a mandatory next-bar delay.
A decision made with bar `t` can fill no earlier than `t+1 open`, plus the
sealed latency. Its `ExecutionResult` records requested, filled, and refused
quantity/notional, fee, impact, price, reason, status, and reconciliation
state. Buys require both `eligible_to_open` and `tradable`; sells require
`tradable` but do not require current universe eligibility.

Missing rows and non-terminal events carry the last valid mark. Only an
explicit terminal event removes a position. Without an evidenced executable
recovery price, confirmation writes the remaining position down to zero; a
later absence never turns a prior close into a retroactive fill.

The generic flat-cost research runner and both legacy promotion paths reject
all `crypto_*` strategies. This prevents an accidental bypass around the
single-venue cost model, event semantics, ExperimentSpec, and two benchmarks.

H1-H4 use a total pre-registered budget of 15 trials (4+4+4+3). H2 emits a
sparse forced exit when its screen transitions, H3 freezes exactly one cohort
for both treatment and control, and H4 uses elapsed venue age plus an explicit
left-censor flag. A final ExperimentSpec v2 must bind the dataset digest,
commit, venue/cost/execution policies, universe, selection and holdout ranges,
walk-forward rules, both benchmarks, controls, refutation, and trial budget.

The two required benchmarks are BTC/USDT buy-and-hold and the eligible
equal-weight basket. Both run through the same evaluator and sealed cost and
execution policy as the candidate.

## Gate 3 - promotion and shadow

Promotion is tri-state: `PASS`, `NO_GO`, or `INSUFFICIENT_EVIDENCE`. Missing
data can never become a pass. A complete candidate must satisfy all of:

- positive net excess over both benchmarks;
- PSR and DSR at least 0.95, PBO at most 0.10, at least four walk-forward
  windows, and no unregistered ledger trial;
- at least 30 independent closed, non-overlapping portfolio round trips;
- absolute OOS drawdown at most 25% and no worse than either benchmark;
- gross expected alpha at least twice p95 total cost;
- non-negative result at 2x costs and 50% fills;
- no asset or episode above 25% of positive P&L;
- capacity at least twice proposed canary capital.

The stress result is a second full evaluator run, not arithmetic applied to
the baseline return and not a caller-supplied scalar. It uses the same sealed
targets, panel, event ledger, venue limits and account fees with an exact
`cost_multiplier=2.0` and `fill_fraction_multiplier=0.5`. The fill reduction is
applied before venue quantity rounding; doubled costs are charged inside the
cash accounting. The complete stressed executions and equity curve are
content-addressed before the non-negative-return gate is evaluated.

The sealed independent-trade definition is
`closed_nonoverlapping_portfolio_round_trip_v1`. An instrument episode opens
when filled buys move its reconstructed position from zero to positive and
closes only when fills return it to zero, or an evidenced terminal settlement
closes it. Partial fills, repeated legs, and buy/sell sides inside one episode
do not create extra observations. Because instrument episodes can overlap, the
count uses the maximum set of temporally non-overlapping closed intervals. Open
positions and overlapping exposure therefore cannot manufacture the required
30 independent observations.

The current draft deliberately cannot emit a promotion `PASS`: concentration
must be reconstructed from independently reloaded, hash-verified holdout panel
marks, not marks copied into the result artifact. That consumer boundary is
still pending. In addition, an annual strategy may not generate 30 genuinely
independent closed portfolio episodes inside the present holdout. These are
`INSUFFICIENT_EVIDENCE` conditions, not thresholds the implementation may
relax. They must be resolved (or Bybit declared statistically insufficient)
before this draft can be considered merge-ready.

If H1-H4 exhaust their sealed budgets without a PASS, the outcome is NO-GO;
no post-hoc variants are permitted.

Operational validation then requires at least 100 complete Demo order cycles
and at least 365 real shadow calendar days including one annual rebalance.
Submit/cancel, idempotency, reconnect, rate limits, restart, reconciliation,
and kill-switch drills must all pass, with zero unresolved discrepancies and
zero duplicates. These periods cannot be accelerated in a backtest.
Those thresholds are hard floors: a caller-supplied `ShadowPolicy` cannot
shorten the observation period, reduce cycles/rebalances, or permit any
duplicate or unresolved discrepancy.

## Gate 4 - canary policy (calculation only)

The implemented canary module evaluates evidence and calculates limits; it
cannot submit an order. It encodes:

- initial capital `min(10% of declared risk capital, USD 500)`;
- at most 5% of the sleeve per asset;
- each order at most `min(1% of 20-day median notional, 5% of executable depth)`;
- daily kill at 1% and review pause at 5% drawdown;
- no leverage or shorts, own Spot capital only;
- before scaling: at least 100 real fills and 30 calendar days, p95 slippage
  no more than 1.5x simulated, median cost error no more than 20%, and clean
  reconciliation;
- scale increments no greater than 25%.

Canary ceilings and scale prerequisites are also immutable hard safety bounds;
passing a more permissive policy cannot enlarge the calculated limits. Scaling
evidence must explicitly state that daily-loss/drawdown triggers, stale data,
unexpected fees, abnormal latency, and out-of-model slippage were not observed.
Any observed trigger produces `NO_GO` and requires pause/review; an omitted
field produces `INSUFFICIENT_EVIDENCE`.

Every readiness payload includes `real_money_authorized=false` and
`external_action_authorized=false`. Human and legal approval would still be a
separate future decision after every technical gate passes.

## Reproducibility and CI

CI installs the full project extras under `requirements.lock.txt` constraints,
runs Ruff plus explicit format checks, mypy, artifact regeneration, pytest on
Python 3.11/3.12, branch coverage across the critical crypto gate/manifest/
holdout/governance modules, an audit of the same locked dependency set, and a
pinned Gitleaks scan with full Git history checked out. Dependabot checks
Python and GitHub Actions weekly. Repository administration must still protect
`main` and require all checks plus one independent approving review; workflow
files cannot enable branch protection themselves.

Green CI proves that the implementation satisfies its tested contract. It
does not prove an economic edge, capacity, legal availability, or future
profitability.
