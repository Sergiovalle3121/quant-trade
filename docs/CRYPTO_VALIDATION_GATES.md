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

## Capital-feasibility evidence for Gate 4

`evaluate_capital_feasibility` is a pure, offline sizing check. It binds the
operator-supplied MXN/quote conversion, a separate quote/USD conversion,
account fee, ask, tick, quantity step, minimum notional, currencies, and
capture time to canonical hashes. It does not assume that USDT equals USD.
Missing or stale evidence returns `INSUFFICIENT_EVIDENCE`; contradictory
evidence or too few executable instruments returns `NO_GO`. No result
authorizes an order.

The hard 5% per-asset ceiling implies at least 20 distinct executable
instruments. For a MXN 1,000 sleeve, each instrument receives at most MXN 50.
That amount must cover the rounded minimum order and its fee. The legacy
`minimum_order_constraints_allow_diversification` boolean remains readable for
old artifacts but can no longer establish readiness: Gate 4 recomputes and
requires a byte-bound `CapitalFeasibility` result with status `PASS`.
That evidence must identify Bybit Demo Spot and the dedicated subaccount, use
unique venue symbols/base assets, and its converted USD sleeve must match the
proposed canary capital to within one cent. Evidence from Binance, a live
environment, derivatives, a shared account, or a different sleeve cannot be
reused to pass this gate.

This is intentionally a feasibility gate, not a recommendation to weaken the
5% ceiling when capital is too small. A failed minimum-order check means do not
trade; it does not permit concentrating the sleeve or changing strategy rules.

## Prospective Binance BTC/ETH campaign (sealed signal only)

`binance_btc_eth_tsmom_long_cash_v1` is a separate, single-trial prospective
falsification campaign. It is not an H1-H4 variant, a backtest result, a
profitable candidate, or a reason to reveal either existing holdout. Its
canonical declaration and SHA-256 seal live in
`configs/experiments/binance_btc_eth_tsmom_long_cash_v1.yaml`.

The declaration fixes Binance Spot, only `BTCUSDT` and `ETHUSDT`, independent
50% sleeves, and LONG/CASH exposure. At the last UTC daily close of each
calendar month, each symbol is LONG only when its close is above the last
observed daily close inside the calendar month exactly 12 months earlier. It
does not use a 365-row offset and does not fall back to month -13 when the
reference month is absent. A target is emitted only at initialization or a
LONG/CASH transition. A sleeve that remains LONG is not traded back to 50%, so
ordinary price drift does not create a rebalance.

Every intention decided from close `t` records the next daily open as its
earliest execution. It contains no execution price and cannot authorize a
same-bar fill or an order. `development_tsmom_targets` exposes the identical
pure signal core for pre-holdout falsification, but accepts only subranges
inside the sealed evidence interval 2018-08-31 through 2023-11-28; a start one
day earlier or an end one day later fails closed. `development_end=2026-08-31`
is the warm-up/final close for the first prospective decision, not a cap or
license for development evidence. `prospective_tsmom_targets` fixes its
decision range from that 2026-08-31 close through 2029-08-31. Neither function
reads a data file, evaluates returns, routes an order, or contacts Binance.

The economic comparison, if eventually authorized after the seal expires,
has exactly three frozen benchmarks: BTC buy-and-hold, ETH buy-and-hold, and a
50/50 BTC/ETH buy-and-hold basket. The cost floor is 10 bps venue fee plus 5
bps friction per side, with a mandatory 2x-cost stress. No leverage, short,
margin, or Earn exposure is permitted.

The signal, universe, costs, and benchmark set were sealed before the first
development diagnostic. The acceptance criteria had been stated in the task,
but were added to the machine-readable seal only after that diagnostic.
Accordingly, this development run is a falsification/diagnostic and never
confirmatory evidence. The final prospective seal fixes the criteria before
the future holdout starts: net total return must be positive and outperform all
three benchmarks overall, absolute drawdown must not exceed 25%, and a second
run at 2x costs and 50% fills must remain non-negative. Time robustness uses
exactly four contiguous, non-empty blocks and requires outperformance in at
least three; that block comparison applies to the two risk benchmarks fixed by
the original proposal (BTC buy-and-hold and 50/50 BTC/ETH buy-and-hold). ETH
buy-and-hold is the third overall benchmark, not a retroactively added block
requirement. The four blocks are partitioned as equal contiguous daily
observations over the aligned series
(`EQUAL_CONTIGUOUS_DAILY_OBSERVATIONS`), leaving no choice of calendar or
market-regime boundaries during the future holdout.

Any eventual promotion additionally requires positive net excess against each
benchmark, PSR and DSR of at least 0.95, and a one-sided 95% excess-return
confidence interval whose lower bound is above zero. With only one registered
trial, PBO is explicitly `NOT_IDENTIFIABLE_SINGLE_TRIAL`; if PBO remains a
mandatory criterion the verdict is `INSUFFICIENT_EVIDENCE`, never an inferred
pass. Drawdown must be at most 25% and no worse than every benchmark, the same
2x-cost/50%-fill stress must remain non-negative, both sleeves must contribute
positive P&L, neither may exceed 75% of positive P&L, and capacity must cover
at least twice proposed capital. Even complete economic success keeps
`real_money_authorized=false`.

The first 24 months end on 2028-08-31, but that date is a non-economic
administrative checkpoint, **not a reveal**. The additional 12 months through
2029-08-31 are committed ex ante. In particular, the implementation cannot
inspect 24-month returns and then choose whether to extend; inability to prove
sufficiency without seeing those returns defaults to continued sealing. No
economic reveal is allowed before 2029-09-01.

This strategy is deliberately absent from the legacy strategy registry and
all runners. Its spec states `live_execution_enabled=false`,
`real_money_authorized=false`, and `external_action_authorized=false`.
Producing a target therefore proves only deterministic signal behavior, not
edge, execution feasibility, readiness to deposit MXN 1,000, or any path to a
million pesos.

Its two 50% research sleeves also contradict Gate 4's live 5% per-asset
ceiling. That conflict is intentional and fail-closed: even a future economic
success would require a separately reviewed concentration policy before this
campaign could become canary-eligible. The prospective declaration itself
cannot weaken Gate 4.
