# Real Alpha, Paper Launch and First-Canary Preparation — V8

Evaluation clock: `2026-07-28T08:00:00Z`
Base: `596c2accd5c535f3c537a4439a96b94e521e4018` (V7, PR #44)
Pre-registration freeze hash: `b21483449a7e1e1917f59458012fd236353d536d5ca19412af4627f86e659678`
Regeneration: `quant-trade v8 revenue-run --verify-determinism`

## Outcome

**`NO_EDGE_FOUND`**, with one important qualification that the artifacts state
everywhere and this report will not soften: the three pre-registered
hypotheses were **not measured**. They were not measured because the dataset
could not be acquired, and the reason is recorded byte for byte rather than
summarised.

That distinction is the whole point of the V8 artifact schema. A campaign that
lost money and a campaign that never ran are both "no candidate", and
conflating them is how a research programme convinces itself it has ruled
something out when it has not. Every V8 artifact therefore carries
`measured: true|false`, unmeasured rows are never ranked, and the leaderboard's
`winner` is `null` rather than a least-bad row.

| Question | Answer |
|---|---|
| Trading `PAPER_CANDIDATE` rows | 0 |
| Campaigns that actually ran | 0 of 3 (H1, H2, H3) |
| Reason | acquisition blocked by the environment's egress policy |
| Real settlements captured this sprint | 0 |
| Raw pages captured this sprint | 0 |
| Paper/shadow session | `NOT_STARTED_NO_CANDIDATE` |
| Allocation | 100% cash |
| Mining marketplace | `BLOCKED_NETWORK` |
| Canary | `BLOCKED`, 6 of 6 conditions unmet |
| Real money authorised | No |

## The acquisition blocker, exactly

Every outbound HTTPS connection to a venue domain is refused by the egress
policy of the environment this sprint ran in. The proxy answers `CONNECT` with
`403 Forbidden` before any TLS handshake, so this is a permission decision,
not a venue-side rate limit, geoblock, or outage.

Probed hosts — all **venue-published official domains**, no mirrors, no
proxies, no third-party redistributors:

| Venue | Host | Role | Outcome |
|---|---|---|---|
| Bybit | `api.bybit.com` | primary documented API domain | `BLOCKED_EGRESS_POLICY` |
| Bybit | `api.bytick.com` | venue-published alternative domain | `BLOCKED_EGRESS_POLICY` |
| Bybit | `api.bybit.nl` | venue-published Netherlands entity | `BLOCKED_EGRESS_POLICY` |
| OKX | `www.okx.com` | primary documented API domain | `BLOCKED_EGRESS_POLICY` |
| OKX | `aws.okx.com` | venue-published alternative domain | `BLOCKED_EGRESS_POLICY` |
| OKX | `my.okx.com` | venue-published regional domain | `BLOCKED_EGRESS_POLICY` |
| NiceHash | `api2.nicehash.com` | documented public marketplace API | `BLOCKED_EGRESS_POLICY` |

Verbatim error, identical for all seven:

```
URLError: <urlopen error Tunnel connection failed: 403 Forbidden>
```

Evidence: `artifacts/v8/NETWORK_REACHABILITY_PROBE.json`,
`data/v8_evidence/bybit_btc_usdt/attempts.jsonl` (28 attempts),
`data/v8_evidence/okx_btc_usdt/attempts.jsonl` (28 attempts). Each attempt log
records the exact URL, the attempt number within the retry policy, the host,
and the verbatim exception.

No workaround was attempted. Routing around an organisation's egress policy or
a venue's regional restriction is out of scope regardless of how convenient it
would have been, and a dataset obtained that way could not have been used
anyway.

## What was built, and why it is not just infrastructure

The mission's standard is that more generic infrastructure does not count as
progress. Each item below closes a specific gap V7 named as open, or removes a
specific way the pipeline could have lied.

### The OKX panel now exists (V7 open route #1)

V7 could fetch OKX funding history and nothing else, so H2 and H3 were
structurally impossible — not rejected, impossible. The backfill is now
venue-generalized and covers all five series a carry panel needs on both
venues: spot candles, perp candles, mark-price candles, index candles and
settled funding, plus instrument metadata and the venue's own server clock.

Two OKX-specific traps are handled explicitly rather than silently:

- **OKX candle bodies do not echo `instId`.** Identity cannot be asserted from
  the payload, so `identity_verifiable` is `False` for those series and the
  requested instrument rides in the ingestion receipt instead. Claiming an
  identity check that did not happen would have been worse than not checking.
- **`confirm` distinguishes closed from forming bars.** Unconfirmed bars are
  dropped: an in-progress close is a value that has not happened yet, and
  including it is look-ahead in its purest form.
- **`realizedRate` beats `fundingRate`.** OKX publishes both; only the settled
  value can enter realized P&L, and every row records which field supplied it
  so an audit can prove no announced rate leaked in.

### Resume and idempotency are mechanical, not aspirational

Each request is keyed by its canonical parameters and the key→bytes mapping is
persisted next to the content-addressed page archive. A re-run replays from
disk: in the test suite a second invocation over the same window issues **zero**
network calls and produces identical series. An interrupted run continues from
the first page that was never fetched rather than restarting.

### Funding-interval changes are distinguished from data loss

Perpetual funding intervals are not constant across a venue's history. Measured
naively against one assumed interval, a real 8h→4h change reads as 50% data
loss and a good dataset gets thrown away; measured too loosely, repeated
outages hide inside a phantom "cadence change" and missing data disappears from
the completeness count. `detect_interval_segments` requires a new spacing to
**persist** for three consecutive settlements before it opens a new segment;
otherwise the gap is counted as absent settlements at the current cadence.

### The evidence pack answers `REAL_LOCAL_UNCOMMITTED`

V7's real capture existed on one machine and nowhere else. A pack makes the
bytes the unit of exchange: a manifest with per-file SHA-256, a Merkle root
over `(path, sha256)`, and a **deterministic** `.tar.gz` — sorted entries,
zeroed mtimes/uids/modes, gzip without a timestamp — stored under its own hash.

Verification goes all the way back to raw. Every archived response is re-parsed
with the recorded parser version and must reproduce the receipt's
`normalized_rows_sha256`; then every series file is rebuilt from raw and
byte-compared against the packed one. A single flipped byte anywhere fails the
pack.

### Costs carry their evidence class

This is the constraint that ends up blocking everything else, and it is
intentional. Every friction records whether its number came from the venue
(`REAL`) or from documentation that could not be re-fetched
(`ASSUMPTION_UNVERIFIED`). A stack containing any unverified component is not
promotable, full stop.

The assumptions are also required to be *conservative* — chosen at or above the
venue's published retail rate — so they can only reject a strategy, never
promote one. A strategy that fails on assumed costs would also have failed on
real ones.

### The holdout can prove it was not used

"We kept a holdout" is unverifiable when the holdout is a slice everything can
see. `HoldoutGuard` makes the rows unreachable until the variant selection is
frozen, permits exactly one reveal, and records the access. Selecting after
revealing, or revealing twice, raises rather than quietly producing a
slightly-too-good number.

### Mining got the engine V7 lacked (V7 open route #2)

V7 could validate marketplace evidence but could not answer whether renting
hashrate makes money. The dynamic cash-flow engine applies one definition
literally: *value of coins actually received, minus every cost paid, minus
every dollar effectively committed*. Three consequences it refuses to skip:

- Below the pool's minimum payout the mined balance is **stranded and worth
  zero**, not "worth its market value".
- Escrowed and unused deposited funds are charged opportunity cost at the same
  cash rate the trading side benchmarks against.
- The result is **never annualized**. A three-day contract is reported over
  three days; `to_dict()` carries an explicit note saying so, because
  multiplying a short contract up to a yearly rate is the most common way
  rented-hashrate economics get overstated.

Uncertainty is a seeded Monte Carlo over delivery shortfall, pool luck,
difficulty drift and coin price, giving P05/P50/P95, loss probability and
CVaR95. PPLNS carries block variance; PPS does not, and the distribution
reflects the difference.

Without a verifiable delivery-and-payout history the status is capped at
`DISCOVERY_ONLY` no matter how good the arithmetic looks. Advertised hashrate
is a claim.

## Break-even: the one number the blocked dataset cannot take away

How much funding a carry must earn to cover its own frictions depends on the
cost stack and the holding period — not on what BTC did last year. So even
with acquisition blocked, the bar is exact.

Reference position: $100,000 notional, 30-day hold, 3× perp leverage, 8h
funding interval. Costs at the conservative retail stack.

| Hypothesis | Round-trip cost | Annual carry cost | Break-even per 8h settlement | Annualised |
|---|---|---|---|---|
| H1 (Bybit) | 45 bps (0.600% of notional) | 4.50%/yr | `0.00010776` | 11.80% |
| H2 (OKX) | 44 bps (0.590%) | 4.50%/yr | `0.00010665` | 11.68% |
| H3 (cross-venue) | 36 bps (0.660% incl. transfer) | 4.50%/yr | `0.00011443` | 12.53% |

Under the 2× and 3× cost scenarios those rates scale linearly: H1 needs
`0.00021553` at 2× and `0.00032329` at 3×.

The round trip is charged **per leg**, which is worth spelling out because
getting it wrong is easy and expensive in both directions. A carry round trip
is four fills — buy spot and sell perp on entry, sell spot and buy perp on
exit — of which two are spot and two are perp. The spot taker fee applies to
the spot fills only and the perp taker fee to the perp fills only; spread,
slippage, impact and latency apply to all four. H1 is therefore
`2 x 10 + 2 x 5.5 + 4 x 3.5 = 45 bps`, not `4 x 15.5 = 76 bps`. H3 has no spot
leg at all — both legs are perpetuals — so it pays `4 x 5.5 + 4 x 3.5 = 36 bps`
plus the cross-venue transfer.

Capital actually immobilised for the reference position is **$166,667** —
$100,000 of spot inventory, $33,333 of initial margin and $33,333 of
maintenance buffer, for a capital efficiency of 0.60. A model that ignores the
buffer invents leverage the position could not have survived.

Whether settled BTC funding clears `0.00010776` per 8h on average, over 730
days, after a conservative cost stack, is *precisely* the question the blocked
dataset would answer. This report does not assume it in either direction. What
can be said is that the bar is not trivially low: 11.8% annualised is
materially above a typical stablecoin lending rate, so a naive "funding is
usually positive, therefore carry works" intuition is not sufficient. It is
also the number a VIP fee tier moves most — the two taker fees are 31 of the
45 round-trip basis points, so a desk paying 3 bps spot / 2 bps perp would face
roughly `0.00008` per settlement instead.

## Statistical machinery: executed, not documented

The gates are the V7 gates, unchanged and re-stated in code so no config can
relax them: 730 days, 1,000 unique settlements, ≥5 walk-forward windows,
PSR ≥ 0.95, DSR ≥ 0.95, CSCV PBO ≤ 0.50, positive bootstrap P05, positive at 2×
costs, 3× reported, zero liquidations, reconciled ledger, majority-positive
walk-forward, beats cash, beats buy-and-hold, untouched holdout, real
provenance, promotable cost evidence.

Because none of this ran on real data, the suite proves it runs *at all* on a
731-day recorded dataset for both venues:

- 15 of 16 gates pass on a dataset engineered to be profitable; the sixteenth,
  `cost_evidence_promotable`, fails — which is the correct answer, since the
  fee schedule was never captured from the venue.
- `test_a_fully_passing_campaign_promotes` asserts that a campaign clearing
  every gate *does* reach `PAPER_CANDIDATE`. Without it, "every campaign was
  rejected" would be unfalsifiable — a pipeline that always says no is not
  rigorous, it is broken.
- Nine parametrised tests break one gate at a time and assert that exactly that
  gate fails.
- H3 runs the genuine two-venue dispersion account, not a single-venue carry
  wearing H3's name, and must beat the better of H1/H2 to survive.

## Paper and canary

No candidate exists, so no paper session was started. A session on an
unvalidated hypothesis produces an equity curve, a dashboard and a sense of
progress that are indistinguishable from the real thing and mean nothing.
`PAPER_STATUS.json` reads `NOT_STARTED_NO_CANDIDATE` with `wall_clock_seconds:
0.0` and the portfolio stays 100% cash.

The launch path is nonetheless real and tested: a manifest can only be built
from a `PAPER_CANDIDATE` campaign (every other status raises
`NoCandidateError`), the session persists WAL, checkpoints and a hash-chained
trading-event journal, it recovers across process restarts, and events apply
exactly once.

Wall-clock and replay time are separate fields and the report says they are
never summed. A test replays two years of history in ninety seconds and asserts
the status reports ninety seconds.

`CANARY_READINESS.json` is `BLOCKED` on all six conditions. Two are
machine-checkable (a sufficient supervised paper result; a clean
reconciliation). **Four are human decisions by construction** — the owner's
explicit budget, the exchange and jurisdiction, the loss limits, and a secure
credential-delivery mechanism — and a test asserts that perfect paper evidence
still leaves exactly those four blocking. No amount of further engineering can
unblock the canary alone, which is the intended shape of that boundary.

No credential, key, seed phrase or wallet is requested, printed, stored or read
from the environment anywhere in the V8 surface; a test enforces this by
scanning the source.

## What is still blocking real money

1. **Outbound HTTPS to the venues.** Nothing downstream can proceed without it.
   Either the egress policy permits `api.bybit.com` and `www.okx.com`, or an
   operator produces an evidence pack out-of-band and imports it through
   `quant-trade v8 evidence-verify --import-to`.
2. **Fee schedules captured from the venue.** The cost stack is
   `ASSUMPTION_UNVERIFIED`; that alone blocks promotion even on a perfect
   dataset.
3. **A measured campaign result.** H1–H3 have never produced an economic number
   on real data.
4. **A supervised paper run**, ≥72h wall-clock and ≥500 events, reconciling
   cleanly.
5. **The four human decisions** in `CANARY_READINESS.json`.

## Next pre-registered experiment

`V9-E1` — *complete the blocked acquisition, then re-run H1–H3 unchanged*.

Registering new hypotheses now would be starting a second search while the
first is still open. The parameters stay frozen at hash
`b21483449a7e1e1917f59458012fd236353d536d5ca19412af4627f86e659678`.

Falsifier: if 730 days of receipt-verified evidence on both venues yields no
hypothesis clearing the gates, cash-and-carry on these venues is abandoned as a
source of edge at this capital scale.

H6 and H7 are registered and remain **locked**. `additional_hypotheses_unlocked`
returns `False` with the reason "H1, H2, H3 did not run for want of evidence" —
they unlock only after the primaries have been *measured* and rejected, not
merely attempted.

## Reproducing this

```bash
quant-trade v8 probe-network
quant-trade v8 evidence-backfill --venue bybit --symbol BTC \
    --since 2024-07-28 --until 2026-07-27
quant-trade v8 evidence-backfill --venue okx --symbol BTC \
    --since 2024-07-28 --until 2026-07-27
quant-trade v8 evidence-validate --venue bybit
quant-trade v8 evidence-pack --redistribution UNRESOLVED
quant-trade v8 evidence-verify --pack <archive> --manifest <manifest>
quant-trade v8 campaign --hypothesis all
quant-trade v8 mining-scan
quant-trade v8 revenue-run --verify-determinism
```

`--verify-determinism` regenerates every artifact twice and compares hashes; it
exits non-zero on any difference. Two consecutive runs in this environment
produced identical hashes for all ten artifacts.

## Safety posture

No order was submitted, no funds moved, no deposit or withdrawal enabled, no
cloud resource created, no miner started, and no credential requested or
stored. AWS and Alibaba remain `BLOCKED` for hashing workloads. The V8 surface
contains no `place_order`, `deposit`, `withdraw`, `buy_hashrate` or
`start_miner` verb, and `tests/test_v8_safety.py` asserts their absence
structurally rather than trusting the absence of a call site.
