# V9 pre-registration and V8 errata

Registered at commit `3818c2d127a17ae26e86b3c75087d04f88681048` — the merge
that closed V8 — before any V9 measurement was attempted. The machine-readable
form is `quant_trade.v9.preregistration`; its hash travels in every V9
artifact, so a gate that moves after results are seen moves the hash with it.

## 1. What is fixed before testing

**Splits.** Chronological, 50% train / 30% walk-forward / 20% holdout, holdout
most recent. Each walk-forward window selects on data ending at
`test_start − purge − embargo` and is scored on its test block only. The
holdout is sealed by hash before any evaluation and revealed exactly once.

**Costs.** Charged at 1×, 2× and 3×, attributed per leg. A two-leg round trip
is four fills, a single-leg round trip is two, and the fee floor applies per
fill. Every component — spot taker, perp taker, spread, slippage, borrow,
transfer — is named in `COST_TREATMENT` so a campaign cannot quietly drop one.

**Gates.** The seventeen V8 gates, unchanged, plus ten added. None relaxed;
a test enumerates every V8 gate and fails if a V9 threshold is looser.

The ten additions, each closing a hole a V8 artifact went through:

| gate | closes |
|---|---|
| `require_positive_holdout` | a negative holdout being outvoted by the full sample |
| `require_per_window_oos_selection` | selection reading data the window then scores |
| `require_hash_chained_trial_ledger` | multiplicity counted from nothing |
| `require_nonzero_cross_trial_sharpe_variance` | a deflation term that evaluates to zero |
| `require_per_venue_cost_bundles` | one venue's fees applied to another |
| `require_equity_derived_returns` | returns summed from per-leg percentage moves |
| `require_observed_at_timestamps` | a close used before it existed |
| `require_executable_at_capital` | a position size no balance can place |
| `forbid_caller_supplied_pnl` | paper P&L passed in as an argument |
| `forbid_injected_wall_clock` | elapsed time asserted rather than accumulated |

**Falsifiers.** Written per hypothesis before testing, in `FALSIFIERS`. H1 is
wrong if realised funding net of the full cost stack is below break-even in
most walk-forward windows, if the holdout is negative, if any window
liquidates, or if the edge does not survive 2× costs. H2 and H3 have their
own. The mining route has four, of which the first is decisive: no pool payout
record showing coins received for accepted hashrate.

**Mining thresholds.** 14 real days and 2,000 snapshots, fixed here so a
window cannot be declared long enough after the fact.

## 2. Errata against V8

Eleven corrections. Each has a regression test; none is a matter of taste. The
machine-readable list is `V8_ERRATA`, and every entry names the V9 module that
closes it.

### E1 — the canary gate failed open
`CANARY_READINESS.json` returned `READY_PENDING_HUMAN_AUTHORISATION` while
carrying `reconciled=false`, an engaged kill switch, and loss limits of
`{per_trade: -1, daily: 0, total: "bad"}`. Three independent holes: a missing
value counted as satisfied, `bool` passed an `isinstance(x, (int, float))`
check, and the limits were never compared to each other. Every limit must now
be present, numeric, positive and ordered `per_trade ≤ daily ≤ total`;
reconciliation must be exactly `True`; an engaged kill switch disqualifies.

### E2 — paper P&L was an input
A `paper_fill` could be booked with no matching `paper_order`, and the caller
supplied the resulting return. A fill must now resolve to a live order, and
equity is derived from the position ledger.

### E3 — a candidate was reported as absent
`revenue-run` emitted `PAPER_STATUS=NOT_STARTED_NO_CANDIDATE` while H1 was a
candidate. Now `CANDIDATE_READY_PAPER_NOT_STARTED` — the difference between
"nothing qualified" and "we have not started".

### E4 — the deflated Sharpe was the probabilistic Sharpe
Computed with `sharpe_variance=0` and a trial count of one, which makes the
deflation term vanish. The correction was present in name only.

Holding the candidate Sharpe fixed, the corrected figure by trial count:

| trials | DSR |
|---|---|
| 1 | 0.9996 |
| 5 | 0.7527 |
| 20 | 0.1867 |
| 100 | 0.0110 |

V8 always reported the first row.

### E5 — the out-of-sample series was in-sample
Variant selection ran on the full sample; performance was then reported on
windows drawn from that same sample.

### E6 — H3 returns assumed both legs were the same size and capital was free
Summing per-leg percentage moves does both. H3 now keeps a per-venue book —
cash, margin posted, position, capital in transit — derives each bar's return
as `equity_t / equity_{t−1} − 1`, reconciles flows every bar, and takes
capacity as `min(Bybit, OKX)`.

### E7 — cost inputs were unfalsifiable
Fee literals with no provenance, no expiry and no venue binding. Now every
schedule carries the sha256 of the bytes it was parsed from, an effective
window, and an evidence class; a `REAL_*` class without bytes is rejected, and
two venues sharing one bundle is detected.

### E8 — "$166,667 minimum capital" was not a minimum
It was the capital a $100k reference position happened to immobilise. The
feasibility curve brackets the real floor by starting below it: under the
modelled venue rules at a $60,000 reference price, **$25 and $50 fail on the
0.001 BTC lot step and $75 clears** — three orders of magnitude below the V8
figure, and bounded by lot granularity rather than by capital.

The fee floor is the second finding. At $75–$100 the largest placeable
position is 0.001 BTC ($60 notional), which puts all four fills under a $0.10
per-fill floor: break-even funding is 0.0000741 per 8h against 0.0000489 at
every larger rung — a 52% penalty invisible in a bps-only cost model.

Both figures rest on `ASSUMPTION`-class venue rules and an assumed reference
price. They are properties of the rules, not of market history.

### E9 — hashrate was mispriced by a factor of 1,000
SHA-256 is quoted in BTC per PH/s per day. Converting to USD per TH/s without
the unit multiplier overstates the cost by exactly 1,000×. V8 also read
min/max speed *limit* as available supply — it is the buyer's requested speed
— and assumed a bid always fills.

### E10 — the mining cash flow had the wrong currency and the wrong fees
Spend did not follow delivery, the buyer fee was applied to deposited rather
than spent funds, the fixed order fee and deposit fee were absent, unspent
budget was consumed rather than refunded, balances reset per order, and the
whole ledger was USD. Sixteen corrections, listed in `B4_CORRECTIONS`, one
test each.

### E11 — `NO_EDGE_FOUND` asserted a result that was never obtained
No campaign was ever measured: egress to every venue was refused. The honest
state is `NOT_MEASURED`, with an operator runbook and a verifying import path.
The token is no longer a legal state; it appears in the artifacts only as the
quoted V8 claim inside this erratum.

## 3. Defect found during V9 itself

One more, found while writing the fault-injection suite rather than inherited
from V8, recorded here because it has the same character as E1:

**A halted paper session came back RUNNING after a restart.** `stop()`
overwrote `PAPER_HALTED` with `PAPER_STOPPED`, and `resume()` mapped
`PAPER_STOPPED` back to `PAPER_RUNNING`. A restart therefore cleared a tripped
kill switch — and the canary gate's most important precondition is that no
breaker fired. `HALTED` is now terminal, and the recorded breakers rebuild the
halt on resume even if the status field is edited.

## 4. What the pre-registration does not do

It does not make the sprint's result more favourable. At the time of writing
every hypothesis is `NOT_MEASURED`, and the pre-registration's function is to
make that statement checkable rather than convenient.
