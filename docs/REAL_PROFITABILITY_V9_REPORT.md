# V9 real-profitability report

**Trading state: `NOT_MEASURED`. Money spent: $0. Real orders: 0.**

That is the headline and it is not a euphemism. Outbound HTTPS to every
venue-published domain is refused at CONNECT by this environment's egress
policy, so no campaign has been run against market data. `NOT_MEASURED` is not
a negative result: nothing about H1, H2 or H3 has been tested, and a claim
that no edge exists would assert a finding that was never obtained.

What follows is therefore in two parts: what was blocked, and what turned out
to be computable anyway.

## 1. The blocker, verbatim

Eight hosts, all published by the venues themselves, all refused:

| host | outcome |
|---|---|
| `api.bybit.com` | `BLOCKED_EGRESS_POLICY` |
| `api.bytick.com` | `BLOCKED_EGRESS_POLICY` |
| `api.bybit.nl` | `BLOCKED_EGRESS_POLICY` |
| `www.okx.com` | `BLOCKED_EGRESS_POLICY` |
| `aws.okx.com` | `BLOCKED_EGRESS_POLICY` |
| `my.okx.com` | `BLOCKED_EGRESS_POLICY` |
| `api2.nicehash.com` | CONNECT tunnel failed, 403 |
| pool hosts | CONNECT tunnel failed, 403 |

The error in every case is
`URLError: <urlopen error Tunnel connection failed: 403 Forbidden>`, and the
proxy's own status endpoint records each as
`gateway answered 403 to CONNECT (policy denial or upstream failure)`.

No proxy, VPN exit, mirror or third-party redistributor was used. Routing
around an organisational restriction is out of scope, and it would invalidate
the provenance in any case: data from an unofficial mirror cannot support a
claim about what a venue's API returned.

The handoff is in `artifacts/v9/DATA_AND_COST_EVIDENCE_INDEX.json`: the exact
commands to run on a host with egress, and an import path that verifies the
returned pack byte-for-byte before extracting. That is the difference between
a status update and a next step.

## 2. What is computable without price history

Three things, because they are properties of venue *rules* rather than of
market history. They survive a blocked sprint intact, and they are the honest
output of it.

### 2.1 The executable capital floor

V8 reported a "$166,667 minimum capital". That number was the capital a $100k
reference position happened to immobilise, not a floor.

The V9 curve walks a ladder that deliberately starts below the expected
answer, because a curve whose lowest rung passes reports its own starting
point as the minimum and measures nothing:

| capital | status | binding constraint | notional | round trip | break-even funding /8h |
|---|---|---|---|---|---|
| $25 | `INSUFFICIENT_EXECUTABLE_CAPITAL` | lot_step | — | — | — |
| $50 | `INSUFFICIENT_EXECUTABLE_CAPITAL` | lot_step | — | — | — |
| $75 | `EXECUTABLE` | none | $60 | $0.40 | 0.0000741 |
| $100 | `EXECUTABLE` | none | $60 | $0.40 | 0.0000741 |
| $250 | `EXECUTABLE` | none | $180 | $0.79 | 0.0000489 |
| $1,000 | `EXECUTABLE` | none | $840 | $3.70 | 0.0000489 |
| $10,000 | `EXECUTABLE` | none | $8,640 | $38.02 | 0.0000489 |

Two findings:

**The floor is $75, not $166,667** — three orders of magnitude out. And what
binds below it is not capital but the 0.001 BTC lot step: at a $60,000
reference price, no smaller position exists to place.

**The fee floor costs 52% at the bottom rung.** At $75–$100 the largest
placeable position is 0.001 BTC, whose four fills each fall under a $0.10
per-fill floor. Break-even funding is 0.0000741 per 8h against 0.0000489
everywhere above — a penalty that is completely invisible in a bps-only cost
model, and that applies to precisely the balances a first-time operator would
use.

Both rest on `ASSUMPTION`-class venue rules and an assumed $60,000 reference
price. The artifact records both classes in its own fields. The return columns
are absent, because there is no out-of-sample series to resample; reporting
P05/P50/P95 here would be reporting a resampling of nothing.

### 2.2 The multiplicity correction

The deflated Sharpe is computable as a function, and computing it is how V8's
E4 was found: with `sharpe_variance=0` and one trial, the deflation term
vanishes and DSR equals PSR. Holding a candidate Sharpe fixed, the corrected
figure falls 0.9996 → 0.7527 → 0.1867 → 0.0110 across 1, 5, 20 and 100 trials.

This is worth stating plainly: **the correction is large enough to reverse a
promotion decision on its own**, and V8 reported the 1-trial value regardless
of how many trials had been run. `require_promotable_ledger` now refuses a
null ledger, an empty ledger, a broken hash chain, and a zero cross-trial
variance across heterogeneous trials.

### 2.3 The cost stack

Break-even funding is a property of the cost stack, not of the funding series,
so it is computable while everything downstream of it is not. The V8 round-trip
defect — summing all per-fill frictions and multiplying by four, which charges
the spot fee on perp fills — moved H1's break-even from 15.57% to 11.80%
annualised when fixed. That correction landed in V8; V9 inherits it and adds
per-leg attribution and a per-fill fee floor.

## 3. What was built but not exercised on real data

Working, tested, and waiting for evidence:

- **Walk-forward with genuine per-window selection**, purge and embargo, and a
  sealed holdout that reveals once and is decisive.
- **A hash-chained global trial ledger** whose identity is
  `(hypothesis, variant, code_sha, config_sha, dataset_sha, seed)`, so a
  re-run with any difference counts as a new draw.
- **Intrabar liquidation** against the adverse extreme with tiered maintenance
  margin, and `liquidations == 0` as a hard gate.
- **A two-venue H3 book** with per-venue fees, margin, in-transit capital and
  a flow reconciliation that must balance every bar.
- **An autonomous paper engine** with real orders, fills, a write-ahead
  journal, a single-writer lease, exactly-once replay, and a clock that
  accumulates from persisted stamps rather than being passed in.

A verified end-to-end promotion path exists and is tested: a campaign with real
cost evidence, positive holdout, sufficient DSR, zero liquidations and a
reconciled ledger *does* promote. That matters, because a pipeline in which
nothing can ever pass is not a strict pipeline — it is a broken one.

## 4. A defect found in V9's own code

The fault-injection suite found one, and it is the same shape as the V8 canary
defect: **a halted paper session came back RUNNING after a restart.** `stop()`
overwrote `PAPER_HALTED` with `PAPER_STOPPED`, and `resume()` mapped
`PAPER_STOPPED` back to `PAPER_RUNNING`, so restarting cleared a tripped
kill switch. Since "no breaker fired" is the canary gate's central
precondition, a restart could have manufactured canary readiness.

`HALTED` is now terminal, and the recorded breakers rebuild the halt on resume
even if the status field is edited. Two regression tests cover it.

## 5. Paper and canary status

Paper: `NOT_STARTED_NO_CANDIDATE`. No campaign reached `BACKTEST_CANDIDATE`,
because no campaign was measured. A session started now would produce an
equity curve that means nothing, so none was started — and the 72 real hours a
promotable session needs cannot be simulated forward.

Canary: blocked, on every condition. No paper result, no reconciliation, no
loss limits, no confirmed venue or jurisdiction, no credential delivery
mechanism. `canary_authorized: false`, `real_money_authorized: false`.

## 6. Counters

| | |
|---|---|
| real orders submitted | 0 |
| hashrate purchased | 0 |
| funds moved | $0.00 |
| deposits | 0 |
| withdrawals | 0 |
| transactions signed | 0 |
| cloud resources created | 0 |
| secrets requested | 0 |
| secrets stored | 0 |

`LIVE_ORDER_SUBMISSION`, `LIVE_BROKER_EXECUTION`, `MINING_PURCHASE_EXECUTION`,
`DEPOSIT_EXECUTION`, `WITHDRAWAL_EXECUTION`, `WALLET_SIGNING`,
`CLOUD_RESOURCE_CREATION` and `EXTERNAL_SPEND` are all `DISABLED`;
`AWS_ALIBABA_HASHING` is `PROHIBITED`. These are not runtime switches — there
is no branch they could enable. `quant_trade.v9.safety` states them as data
and a test suite verifies them against the package by importing every V9
module and searching for the names, credential handling, endpoints and cloud
surfaces a transacting path would need. Nineteen modules scanned, nothing
found, and one deliberate exclusion — the scanner itself, which necessarily
contains every string it searches for.

## 7. What would change the answer

One thing: market data. Run the acquisition runbook on a host with egress and
import the pack. Everything downstream is built, tested, and blocked on that
single input.
