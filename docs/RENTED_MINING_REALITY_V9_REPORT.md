# Rented hashrate: what V9 measured, and what it refuses to claim

**Mining state: `BLOCKED_EVIDENCE`. Hashrate purchased: 0. BTC moved: 0.**

The marketplace host is refused at CONNECT, so no quote was captured and the
shadow window never opened. Nothing here says renting hashrate is or is not
worthwhile — that question requires pool payout evidence this environment
cannot reach.

What V9 did do is rebuild the arithmetic, because V8's was wrong in ways large
enough to decide the answer by themselves.

## 1. The evidence ceiling

The rented-hashrate story has a specific failure mode. Marketplace prices are
easy to fetch, so an analysis looks well-evidenced while the half that decides
profitability — *did the hashrate arrive, and did the pool pay* — is assumed.

Prices are a quote. Payouts are the product.

So the ceiling comes from the weakest leg:

| state | means |
|---|---|
| `BLOCKED_EVIDENCE` | the marketplace could not be read at all — where we are |
| `SHADOW_MARKET_ONLY` | prices exist; no pool-side record of delivery or payment |
| `SHADOW_COLLECTING` | a pool adapter is attached, the window is too short to mean anything |
| `SHADOW_CANDIDATE` | enough real days and snapshots, quotes reconcile, pool evidence is real |

**Without a parsed pool payout record the route cannot exceed
`SHADOW_MARKET_ONLY`, however attractive the arithmetic looks.** A declared
"delivery was fine" boolean is recorded and never counted. A record whose
evidence class says `REAL_*` but which carries no source bytes is rejected at
construction. Records that exist but show no payout mean hashrate was accepted
and nothing was received — which is a finding, not a gap.

## 2. Three unit errors, each worth orders of magnitude

### The speed unit is not TH/s

NiceHash quotes SHA-256 in BTC per **PH/s** per day. Multiplying that price by
BTC/USD without dividing by the unit multiplier overstates the cost of
hashrate by exactly **1,000×**.

At a 0.001 BTC/unit/day quote and $60,000/BTC:

| | USD per TH/s per day |
|---|---|
| naive (unit skipped) | 60.00 |
| correct | 0.06 |

A 1,000× error in the cost of the only input turns any rental into an obvious
loss or an obvious win depending on which direction you get it wrong. So
`public/buy/info` is the authority for the unit, and a field missing from that
response is an error rather than a default — guessing a minimum order size or
a price floor produces a number that looks like evidence and is not.

### `limit` is not supply

`minSpeedLimit` and `maxSpeedLimit` bound the speed the *buyer requests*.
Reading them as available hashrate converts an order parameter into a market
depth figure that does not exist. The parsed spec carries the semantics in the
artifact so the mistake cannot be made downstream by inspection.

### A cheap bid is not a fill

Hashpower goes to the highest bidders. An order priced below the market clears
slowly or not at all, and modelling a purchase as "I paid X and received X
worth of hashrate" assumes away the only real risk of the strategy.
`estimate_delivery` derives an expected fill ratio from the bid's position in
the order book. It is a coarse model — the honest alternative to assuming a
bid always fills, not a precise forecast — and it is monotone in price, which
is the property that matters for ranking.

## 3. Sixteen cash-flow corrections

V8 priced a purchase as `units × price × days` in USD. That is the shape of a
mining calculator, not the shape of a marketplace order. A real order is funded
in BTC, spends its balance as hashrate is *delivered*, charges several fees at
different triggers, and refunds what it never spent.

| correction | V8 | V9 |
|---|---|---|
| spend vs delivery | charged the full order amount | spends in proportion to accepted hashrate |
| buyer fee base | applied to deposited funds | applied to BTC actually spent |
| order creation fee | absent | fixed per order — can swallow a small order whole |
| deposit fee | absent | charged on the way in |
| withdrawal fee | implicit per order | charged once per payout |
| refunds | unspent budget consumed | refunded, less any cancellation fee |
| cancellation | not modelled | refund of unspent balance minus fee |
| price / amount / limit | conflated | three independent order parameters |
| minimum order | in hashrate | in BTC, as the venue states it |
| maximum duration | unbounded | enforced |
| repricing | continuous delivery assumed | a bid below market delivers nothing until repriced |
| pool fee | double-counted in V8's decomposition | taken once from mined coins |
| payout minimum | ignored | a sub-minimum balance is mined and not spendable |
| accumulation | reset per order | balances accumulate across orders |
| currency | USD | BTC ledger, USD as a parallel view of the same rows |
| benchmark | zero | holding BTC *and* holding cash |

Three of these deserve expanding.

**Spend follows delivery.** The engine walks an order hour by hour, and spend,
buyer fee and mined coins all derive from the same delivered figure in the same
step. A 60% fill spends 60% of the money and mines 60% of the coins. Charging
the full amount and crediting partial hashrate — or the reverse — breaks the
only invariant that makes the result checkable.

**The ledger is BTC.** Spend and income are both BTC-denominated, so a rental
is mostly a bet on hashrate against difficulty, not on price. Converting each
leg to USD at a different moment invents a currency P&L the buyer never took.
USD is carried as a view of the same rows.

**Repricing is the risk.** If the market price rises above your bid you receive
nothing until you raise it, and raising it costs more per delivered hour than
you planned. The engine models both branches: an order that stays put records
its outbid hours, one that reprices records the new price and the higher spend.

## 4. A shadow window that cannot be forged

Two of the three promotion thresholds are "how long has this been running" and
"how many observations", and both are one loop away from being invented. So:

- **Elapsed days accumulate from persisted wall-clock stamps.** Replaying a
  thousand snapshots in one second advances the snapshot count and not the
  window. A test asserts exactly this.
- **The journal is hash-chained.** An edited record fails its own digest; a
  removed one breaks its successor's back-pointer. Both are named in the
  report rather than silently absorbed.
- **Downtime is a gap, not observation.** A collector down for six hours did
  not observe six hours; the interval is recorded with its duration and
  excluded from observed time, across restarts.
- **The bidding policy is frozen at start.** Its hash is in the header, and
  changing it restarts the window — otherwise the policy gets tuned against
  the data that is supposed to test it.
- **An injected clock is permanent.** A window collected under a test clock
  can be reported and can never support a promotion.

Thresholds: 14 real days and 2,000 snapshots. Both required; neither
substitutes for the other, because a dense hour is not a fortnight and a
fortnight of two snapshots is not a sample.

## 5. The canary manifest — every flag false

A first purchase would be a single order with no refill, and the manifest
fixes its shape in advance: a hard price ceiling, an explicit refusal to chase
the market up, a speed limit, a maximum duration, a named pool and worker, and
stop conditions including "cancel if the modelled margin over holding BTC
disappears".

**The budget is derived, not chosen.** It is the marketplace minimum order
amount plus the fixed order fee, the deposit fee, the withdrawal fee and the
buyer fee on spend — raised to the pool's payout minimum when that binds,
because renting less hashrate than would ever clear the payout minimum
produces coins that can never be withdrawn. Naming a round number like "$50 to
try it" ignores all six and usually lands below the point where anything can
be taken out.

Every authorisation flag is `false`: `purchase_authorized`,
`deposit_authorized`, `withdrawal_authorized`, `wallet_signing_authorized`,
`cloud_hashing_authorized`. `aws_alibaba_hashing` is `PROHIBITED`. The
manifest carries its own hash, so a manifest loosened later is a different
manifest.

## 6. The boundary, verified rather than asserted

No mining module exposes a buy, purchase, deposit, withdraw, sign or
instance-creation verb. None reads a credential, signs a request, opens a
network connection, or names a cloud hashing surface — the collector is
handed snapshots the caller fetched read-only. These are not claims in a
comment; a test suite imports every module and searches for each of them, and
one deliberately-planted sample proves the search can fail.

## 7. What would change the answer

Two inputs, in order:

1. **A captured `public/buy/info` and order book**, which would move the route
   from `BLOCKED_EVIDENCE` to `SHADOW_MARKET_ONLY` and let the shadow window
   open.
2. **A read-only pool adapter with real payout records**, which is the only
   thing that can lift the ceiling above `SHADOW_MARKET_ONLY` at all.

With both, 14 days of collection would produce a `SHADOW_CANDIDATE` or a
documented rejection. Without the second, no amount of collection will.
