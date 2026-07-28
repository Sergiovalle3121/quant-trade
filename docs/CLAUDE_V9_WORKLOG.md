# V9 worklog — profitability evidence, autonomous paper, rented-hashrate shadow

Baseline: PR #45 merged at `3818c2d127a17ae26e86b3c75087d04f88681048`, 894 tests.
Branch: `claude/v9-profitability-evidence`.

Every entry records what was built, what it changes about a previously reported
number, and what is still not measured. The economic state of the trading route
at the time of writing is **`NOT_MEASURED`** — no campaign has been run against
real venue data, because outbound HTTPS to every venue-published domain is
refused by the environment's egress policy. That is a data-acquisition status,
not a result.

---

## Phase 0 — the three confirmed V8 defects (`1192e29`)

Each defect was reproduced as a failing test first, then fixed.

**A. The canary gate failed open.** `CANARY_READINESS` returned
`READY_PENDING_HUMAN_AUTHORISATION` while carrying `reconciled=false`,
`kill_switch_engaged=true`, and a loss-limit block of
`{per_trade: -1, daily: 0, total: "bad"}`. Three separate holes: a missing
value was treated as satisfied, `bool` passed an `isinstance(x, (int, float))`
check, and the limits were never compared to each other. Now
`validate_loss_limits` requires all three present, numeric, positive and
ordered `per_trade <= daily <= total`; `validate_reconciliation` requires
`reconciled is True` rather than truthiness; an engaged kill switch is
disqualifying rather than informational.

**B. Paper accepted a fill with no order.** `record_fill` would book a
`paper_fill` whose `client_order_id` matched nothing, and the caller supplied
the resulting equity. Both are now impossible: a fill must resolve to a live
order, and equity is derived from the position ledger.

**C. `revenue-run` mislabelled a candidate.** With H1 evaluating to a
candidate, the run still emitted `PAPER_STATUS=NOT_STARTED_NO_CANDIDATE`. It
now emits `CANDIDATE_READY_PAPER_NOT_STARTED`, which is the difference between
"nothing qualified" and "something qualified and we have not started".

Also landed here: `economic_status.py`, which makes the permitted vocabulary
executable. `NO_EDGE_FOUND` is not in it.

---

## A2/A3 — real out-of-sample and real multiplicity (`9964977`)

**Walk-forward now selects out of sample.** The V8 implementation chose its
variant on the full sample and then reported performance on windows drawn from
that same sample. `run_walk_forward` now ends each window's selection data at
`test_start - purge - embargo` and evaluates only on the test block, so the
concatenated OOS series is genuinely unseen at selection time.

**The holdout is sealed, not consulted.** `HoldoutSeal` freezes a hash of the
holdout specification before any evaluation and reveals once. `evaluate_holdout`
makes the holdout decisive: a negative holdout rejects, and full-sample
performance can never rescue it.

**DSR is computed, not substituted.** V8 reported PSR under a DSR label with
`sharpe_variance=0`, which makes the deflation term vanish — the correction was
present in name only. `deflated_sharpe` now takes the real cross-trial Sharpe
variance and the trial count from a mandatory hash-chained ledger.
`require_promotable_ledger` refuses `trial_registry=None`, an empty ledger, a
broken chain, and zero variance across heterogeneous trials.

Measured effect of the fix, holding the candidate Sharpe fixed: DSR 0.9996 at
1 trial, 0.7527 at 5, 0.1867 at 20, 0.0110 at 100. The V8 number was the
1-trial figure regardless of how many trials had been run.

---

## A4/A5 — margin, liquidation, and a two-venue H3 book (`93bd65b`)

**Liquidation is checked intrabar.** A short is checked against the bar's
high and a long against its low, because a position that is liquidated at
11:14 does not get to see the 11:59 close. Tiered maintenance margin follows
the venue's risk-limit table rather than a flat rate. `liquidations == 0` is a
hard gate on any promotion.

**H3 returns come from equity.** The V8 dispersion campaign summed per-leg
percentage moves, which silently assumed both legs were the same size and that
capital was free. `run_dispersion` now keeps a per-venue book — cash, margin
posted, positions, in-transit capital — and derives each bar's return as
`equity_t / equity_{t-1} - 1`, with a flow reconciliation that must balance.
Capacity is `min(Bybit, OKX)` and names the binding venue: a spread you can
only half-execute is not a spread you can execute.

---

## A1 — costs become evidence (`792547f`, `c37dd0e`)

`CostEvidenceBundle` replaces the V8 fee constants. Every schedule carries the
sha256 of the response it was parsed from, an effective-from and an expiry, and
one of four classes ranked `REAL_ACCOUNT_SPECIFIC > REAL_PUBLIC_RETAIL >
RECORDED_TEST > ASSUMPTION`. A schedule claiming a REAL class without raw bytes
is rejected at construction.

Two failure modes have explicit guards: a bundle cannot hold a schedule for a
venue it does not describe, and `BundleSet.require` detects two venues sharing
one bundle — the exact way a Bybit fee gets quietly applied to OKX.

`operator_capture_instructions` tells an operator how to capture their own fee
schedule. It contains no signing code, no environment lookup and an explicit
never-send list; the repository never asks for, receives, or stores a key.

---

## A6/A7/A8 — time, acquisition, and small capital (`f44f9f5`)

**Three timestamps travel with every bar.** `bar_start_ms` and `bar_end_ms`
bound what the bar describes; `observed_at_ms` is the first moment it could
have been read. `StampedBar` refuses to exist if `observed_at_ms < bar_end_ms`.
Bars ending within a safety lag of the venue's own clock are discarded, because
venues publish the forming candle on the same endpoint as closed ones.
Funding is valued at the mark observable *at the settlement instant*, not the
next close.

**A blocked acquisition is `NOT_MEASURED`.** `evaluate_acquisition` reports
what evidence exists per venue and, when it does not, emits the exact commands
an operator runs on a host with egress plus a verifying import path. "We could
not download it" with a runbook is a next step; without one it is a status.

**Small capital, honestly.** V8's "$166,667 minimum capital" was not a minimum
— it was the capital a $100k reference position happened to immobilise. The
feasibility curve now walks $25 → $10,000 and, for each rung, either finds the
largest position that clears lot step, minimum notional, margin and fee floors,
or returns `INSUFFICIENT_EXECUTABLE_CAPITAL` and names the binding constraint.
Returns are on total immobilised capital, not on notional, and outcomes are
P05/P50/P95 with a ruin probability from a block bootstrap of the OOS series.

The ladder deliberately starts below the expected floor: a curve whose lowest
rung is executable reports its own starting point as the minimum, which
measures nothing. Bracketed, the answer under the modelled venue rules at a
$60,000 reference price is **$75**, not $166,667 — three orders of magnitude
out. Below $75 the binding constraint is the 0.001 BTC lot step, not capital.

The fee floor is the other number worth recording. At $75–$100 the largest
placeable position is 0.001 BTC ($60 notional), which puts all four fills under
a $0.10 per-fill floor: break-even funding is 0.0000741 per 8h against
0.0000489 at every larger rung — a 52% penalty arising purely from the floor
and invisible in any bps-only cost model.

Both figures rest on `ASSUMPTION`-class venue rules and an assumed reference
price, and the artifact says so in its own fields. They are properties of the
rules, not of market history, which is why they survive a blocked sprint.

---

## B — rented hashrate

### B2 — `buy/info` is the unit authority

`mining_units.py`. Three unit errors, each worth orders of magnitude:

* **The speed unit is not TH/s.** SHA-256 is quoted in PH/s. Multiplying the
  BTC price by BTC/USD without dividing by the unit multiplier misprices
  hashrate by exactly 1,000×. `price_usd_per_canonical_unit_day` applies the
  conversion and a test pins the factor.
* **`limit` is not supply.** It is the maximum speed the buyer requests.
  Reading it as market depth invents a quantity that does not exist.
* **A cheap bid is not a fill.** `estimate_delivery` derives an expected fill
  ratio from the bid's position in the order book — a coarse model, and the
  honest alternative to assuming a bid always fills.

`parse_buy_info` requires every marketplace term and refuses to default any of
them: a guessed minimum order size produces a number that looks like evidence.

### B4 — the sixteen cash-flow corrections

`mining_cashflow.py`, with `B4_CORRECTIONS` listing each and a test per item.
The engine walks an order hour by hour so that spend, buyer fee and mined coins
all derive from the same delivered figure in the same step. The corrections
that move the number most:

| correction | what V8 did | what it does now |
|---|---|---|
| spend vs delivery | charged the full order amount | spends in proportion to accepted hashrate |
| buyer fee base | applied to deposited funds | applied to BTC actually spent |
| order creation fee | absent | fixed per order — can swallow a small order whole |
| withdrawal fee | implicit per order | charged once per payout |
| refunds | unspent budget consumed | refunded, less any cancellation fee |
| repricing | assumed continuous delivery | a bid below market delivers nothing until repriced |
| payout minimum | ignored | a sub-minimum balance is mined and not spendable |
| accumulation | reset per order | balances accumulate across orders |
| currency | USD throughout | BTC ledger with USD as a parallel view |
| benchmark | zero | holding BTC *and* holding cash |

The BTC-first ledger matters on its own: spend and income are both BTC, so a
rental is a bet on hashrate against difficulty. Converting each leg at a
different moment manufactures a currency P&L the buyer never took.

### B3/B5/B6 — evidence ceiling, shadow window, refusals

`mining_evidence.py` sets the claim ceiling from the weakest leg. Without
parsed pool payout records — showing that speed was delivered *and* paid for —
the route cannot exceed `SHADOW_MARKET_ONLY`, however attractive the
arithmetic. A declared delivery boolean is recorded and never counted. A
`REAL_*` class record without its source bytes is rejected. Stale evidence and
a quote that disagrees with the priced economics both block.

`mining_shadow.py` is the persistent collector. Its two promotion thresholds
(14 real days, 2,000 snapshots) are each one loop away from being forged, so:
elapsed days accumulate from persisted wall-clock stamps and a replay advances
the count without advancing the window; the journal is hash-chained so an
edited or deleted record is detectable; downtime is recorded as a gap and
excluded from observed time; the bidding policy is frozen at start and changing
it restarts the window. An injected test clock marks the window unpromotable
forever.

`mining_canary_manifest` writes the boundary down as data:
`purchase_authorized`, `deposit_authorized`, `withdrawal_authorized`,
`wallet_signing_authorized` and `cloud_hashing_authorized` are all false,
`aws_alibaba_hashing` is `PROHIBITED`, and `orders_placed` is 0. Tests assert
that no mining module exposes a transacting verb, reads credentials, signs
anything, opens a network connection, or names a cloud hashing provider.

---

## What is still not measured

* No campaign has run against real venue data. Every venue-published domain is
  refused by the environment's egress policy; the verbatim errors are the
  evidence. Trading state: `NOT_MEASURED`.
* No pool payout evidence exists, so the mining route is capped at
  `SHADOW_MARKET_ONLY`.
* No paper session has run for a duration that could support a promotion.
* Nothing has been purchased, deposited, withdrawn, or signed.
