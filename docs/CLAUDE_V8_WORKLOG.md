# V8 Worklog — Real Alpha, Paper Launch, First Canary

Base: `596c2accd5c535f3c537a4439a96b94e521e4018` (V7, PR #44).
Branch: `claude/v8-alpha-paper-launch-vigt10`.
Pre-registration frozen at `b21483449a7e1e1917f59458012fd236353d536d5ca19412af4627f86e659678`
**before** any campaign ran.

## Checkpoint 1 — orientation and the first hard fact (0:00–0:35)

`git fetch origin` put `main` exactly at the expected V7 commit; no unmerged
work from other agents, worktree clean.

Read `AGENTS.md`, the V7 report and the modules V7 named as open routes. The
V7 report is unusually candid about its own gaps, which made the priority list
short: OKX has funding history only (so H2/H3 are structurally impossible, not
merely untested), the real capture is `REAL_LOCAL_UNCOMMITTED`, and the
marketplace route has no cash-flow engine.

Then, before writing anything, the thing that determines the whole sprint:

```
curl https://api.bybit.com/v5/market/time   → CONNECT tunnel failed, 403
curl https://www.okx.com/api/v5/public/time → CONNECT tunnel failed, 403
curl https://api2.nicehash.com/...          → CONNECT tunnel failed, 403
```

Also probed the venue-published alternatives (`api.bytick.com`, `api.bybit.nl`,
`aws.okx.com`, `my.okx.com`) — all identical. Every host the *venues themselves*
publish is refused by the environment's egress policy at CONNECT, before TLS.

Decision taken here and held for the rest of the sprint: no proxy, no mirror,
no third-party redistributor. The block is the finding, and the finding gets
recorded with the same rigour a successful capture would get. Wrote
`v8/network_probe.py` so the failure is a structured, classified artifact
rather than a sentence in a report.

## Checkpoint 2 — evidence acquisition, built to work when unblocked (0:35–2:10)

Built `v8/venues.py`, `v8/backfill.py`, `v8/validation.py`,
`v8/panel_builder.py` and a synthetic recorded-response harness.

Design decisions worth recording:

- **OKX candle bodies do not echo `instId`.** The honest move was to set
  `identity_verifiable=False` for those series and carry the requested
  instrument in the receipt, rather than pretend a check happened. Asserting an
  identity check you did not perform is worse than not performing it.
- **`confirm` handling.** OKX marks forming bars; they are dropped. An
  unconfirmed close is a future value.
- **Resume is the same mechanism as idempotency.** Requests are keyed by
  canonical parameters, the key→bytes map is persisted, and a re-run replays
  from disk. The test asserting a second run makes *zero* network calls is the
  one that convinced me the design was right.
- **Interval-change detection took two attempts.** The first version anchored
  on the smallest observed gap, so an 8h→4h change made every 8h gap look like
  "4h with one missing". Rewrote it to require a new spacing to *persist* for
  three settlements before opening a segment. A real change and a run of
  outages look identical in a single gap; only persistence separates them.

Smoke-ran both venues end to end against recorded responses: 730 days, 17,545
hourly bars per series, 2,193 settlements, panels clean, validation clean,
resume touching no network.

## Checkpoint 3 — evidence packs and the redistribution question (2:10–2:40)

`v8/evidence_pack.py`. The interesting constraint was determinism: a `.tar.gz`
records mtimes, uids and a gzip timestamp by default, so two builds of the same
bytes differ. Zeroed all of it and asserted it in a test that inspects the tar
members directly.

Verification goes back to raw: re-parse every archived page with the recorded
parser version, check it reproduces the receipt's `normalized_rows_sha256`, then
rebuild every series file from raw and byte-compare.

On redistribution: I could not check Bybit's or OKX's terms (no network), so
the honest stance is `UNRESOLVED`, which means raw bytes are *not* committed.
Added the `.gitignore` rules with a comment explaining that this is not a
reproducibility fig leaf — the attempt logs and receipts stay, and the pack
tooling exists precisely so an operator who does hold the rights can move the
bytes and have a third party verify them.

## Checkpoint 4 — pre-registration, costs, and the campaign engine (2:40–4:45)

`v8/preregistration.py` froze H1/H2/H3 (primary) and H6/H7 (additional, capped
at 8 variants, locked until the primaries are *measured*). Gates duplicated in
code rather than read from config, so nothing can relax them at runtime.

`v8/costs.py` carries the decision I think matters most in this sprint: **every
cost input records its evidence class, and an unverified one blocks promotion**.
Fee schedules could not be captured, so the stack is `ASSUMPTION_UNVERIFIED` and
deliberately pessimistic. That combination means the assumptions can reject a
strategy but never promote one.

The by-product is the number that survives the blocked network: break-even
funding is a property of the cost stack and holding period, not of price
history. H1 needs `0.00010776` per 8h settlement — 11.80% annualised — purely
to cover frictions.

`v8/holdout.py`: made the holdout mechanically unreachable until selection is
frozen, revealable once, with the access recorded.

`v8/campaigns.py`: four endings, sixteen gates evaluated from measured values,
full decomposition from the reconciled ledger, 1×/2×/3× stress, stationary
bootstrap, rank-based CSCV over the registered variants, purged walk-forward,
cash and buy-and-hold benchmarks, capacity from the 5th-percentile bar rather
than the median.

Three problems surfaced while wiring it:

1. V7's receipt-rebuild registry did not know the V8 adapters, and its panel
   verifier rejected metadata receipts. Extended both — the fix is small and
   correct: contract metadata and server-clock captures are provenance, not
   panel inputs.
2. CSCV requires observations divisible by its partition count. Trimmed the
   *oldest* observations, not the newest: dropping recent data would bias the
   estimate toward the easiest period.
3. The first version recomputed variant ledgers for CSCV. Reused the selection
   pass's series instead — faster, and it guarantees PBO measures the search
   that actually happened.

Ran the full three-campaign integration on a 731-day recorded dataset for both
venues. 15 of 16 gates pass; `cost_evidence_promotable` fails. That is the
correct outcome and I left it failing rather than weakening it.

## Checkpoint 5 — paper, canary, mining (4:45–6:15)

`v8/paper_launch.py` refuses to build a manifest from anything but a
`PAPER_CANDIDATE`. Wall-clock and replay are separate fields; the test that
replays two years in ninety seconds and asserts the report says ninety seconds
is the one that encodes the mission's "no afirmes que lleva días corriendo".

The shadow WAL only carries cash-accrual fields, so rather than widen V7's
contract I gave the paper layer its own hash-chained trading-event journal
alongside it.

`v8/canary.py`: six conditions, four of which no engineering can satisfy. The
test asserting that perfect paper evidence still leaves exactly those four
blocking is the point of the module.

`v8/hashrate_cashflow.py` + `v8/hashrate_market.py`. The bug worth recording:
my first decomposition listed the pool fee as a USD cost *and* netted it out of
the coin figure, double-counting it. Restructured so the lines sum exactly to
the reported profit, and added a test asserting that identity. Also confirmed
the engine can return a profitable verdict on genuinely cheap hashrate —
otherwise "not profitable" would be a constant, not a finding.

Kept mining to roughly the mandated 20% of effort.

## Checkpoint 6 — artifacts, CLI, determinism (6:15–7:15)

`v8/artifacts.py` generates all ten artifacts from a fixed clock and seeded
statistics. Two subtleties:

- The network probe and marketplace scan are *recorded inputs*, not live calls
  — a live probe is by definition not reproducible.
- The generator must not read its own output back. My first version loaded
  `MINING_MARKETPLACE_SCAN.json` from the output directory, which would have
  made the second regeneration depend on the first — exactly the property the
  determinism test checks. Moved it to a separate `.recorded.json` input.

Ran the real CLI against the real (blocked) network so the committed evidence
is genuine: 56 recorded attempts across both venues, each with the verbatim
`403`. Then `revenue-run --verify-determinism`: two regenerations, ten
artifacts, identical hashes.

Also discovered that `ruff format` over the whole tree touches ~50 pre-existing
files — the repo maintains a curated format-check list. Reverted the unrelated
reformatting and added `.github/v8-python-files.txt` plus a CI step, so V8 files
are format-checked without churning V7's.

## Checkpoint 7 — a real defect found while CI ran (7:15–7:40)

Re-derived the round trip by hand rather than trusting the code, and the code
was wrong. `round_trip_fraction` multiplied the *sum* of all per-fill
frictions by four, which charges the spot taker fee on the perp fills and the
perp taker fee on the spot fills: 76 bps where the truth is 45. The same
mistake had leaked into the V7 ledger projection, where `_taker_fee_bps`
summed the two fees and handed the total to a model that applies one rate to
every fill.

The error was conservative in sign, which is why nothing failed — but a
break-even 70% too high can abandon a strategy that would have worked, and
that is exactly as bad as the optimistic direction. Added a `leg` field to
`CostComponent` ("spot" | "perp" | "both"), made the round trip charge leg
fees on two fills and shared frictions on four, and made the V7 projection
pass the *blended* rate.

H3 gained a `spot_leg=False` stack in the same change: it is perp/perp, so a
spot taker fee prices a leg the strategy does not have.

Headline effect: H1 break-even falls from 15.57% to 11.80% annualised. Four
new tests pin the leg semantics, including one that asserts the conservative
stack is 45 bps and not 76.

## Checkpoint 8 — regression, docs, PR (7:40–8:00)

Full suite, lint, types, `git diff --check`, double regeneration, PR, CI.

## Honest assessment

What V8 delivers: the OKX gap is closed, the acquisition pipeline is resumable
and idempotent and proven end to end on 730-day recorded datasets, evidence is
now portable and verifiable back to raw bytes, the campaign engine runs all
three hypotheses including a genuine two-venue H3, the mining route has the
cash-flow engine it lacked, and every artifact distinguishes "not measured"
from "measured and rejected".

What V8 does not deliver: a single real settlement. The economic question is
exactly as open as it was at V7, and I want to be blunt that no amount of the
above substitutes for it. The one durable economic contribution from a blocked
sprint is the break-even bar — 11.80% annualised for H1 at 1× costs — which at
least tells the next attempt what it is looking for, and is high enough that
"funding is usually positive" is not an answer.
