# The collector-integrity pattern

Extracted from `v9/mining_shadow.py` before the mining route was retired. The
module is gone; the problem it solved is not, and the next place it will
reappear is a data collector for low-cap crypto tokens — where gaps, stale
quotes and restarts are the norm rather than the exception.

## The problem

A collector is trivially forgeable. The thresholds that gate promotion of
collected evidence are typically "how long has this been running" and "how many
observations were made" — and both are one `for` loop away from being invented.
Replaying a thousand cached snapshots in one second produces a journal that
*looks* like a fortnight of observation. Nothing about the file betrays the
difference, unless the collector was built so that it does.

The retired implementation gated shadow-mode promotion on
`MIN_SHADOW_DAYS = 14.0` **and** `MIN_SHADOW_SNAPSHOTS = 2000`, deliberately
non-substitutable: a dense hour is not a fortnight, and a fortnight holding two
snapshots is not a sample. Every defence below existed to make those two
numbers mean what they claim.

## The four defences

### 1. Elapsed time comes from persisted wall-clock stamps, never from a counter

Each record carries `wall_clock` (the collector's clock at capture time) and
`clock_source`. Elapsed days are computed by re-reading the stamps across
restarts — the delta between consecutive persisted stamps, not an in-memory
accumulator. Replaying snapshots advances the snapshot count and *not* the
clock, and the journal records which clock produced each record
(`system` vs `injected_test`), so a session driven by an injected clock is
visibly a test session forever.

The V9 paper daemon used the same rule and went one step further: an injected
clock marked the session permanently unpromotable
(`clock_is_persisted = False`), and the canary gate checked it.

### 2. The journal is hash-chained

Every record carries `previous_sha256`, the digest of its predecessor
(canonical JSON, sha256). A deleted or edited record breaks the chain instead
of vanishing quietly, and `verify_chain()` re-walks the whole journal from the
genesis record on every resume. The checkpoint stores the last digest, so a
journal truncated after the checkpoint was written is also caught.

One writer at a time, enforced by a lease file — two writers would interleave
the journal and break the chain in ways indistinguishable from tampering, so
the lease makes concurrent writing fail loudly instead.

### 3. Gaps are first-class records, not smoothing targets

If the interval between consecutive stamps exceeds `GAP_THRESHOLD_SECONDS`
(1800s in the retired module), the collector was *down*, not slow. The interval
is written to the journal as an explicit `gap` record carrying its duration,
and — this is the part that matters — **`observed_days` excludes gap time**. A
collector that was down for six hours did not observe six hours. The
gap count and total gap seconds travel in the stats, so a window with heavy
downtime is visibly worse than a clean one even at equal span.

For low-cap tokens this defence does double duty: an illiquid venue that stops
printing trades produces exactly the same silence as a crashed collector, and
recording the gap honestly is what lets you tell "no data existed" from "we
were not looking" — which is the survivorship question in miniature.

### 4. The policy under test is frozen at start, by hash

Whatever the collected data is meant to evaluate (a bidding policy there; a
screening rule or cost model here) is hashed into the journal header at start.
Changing it mid-window resets the window, because otherwise the policy gets
quietly tuned against the very data that is supposed to test it. The checkpoint
re-verifies the stored `policy_sha256` on resume, so a swapped policy cannot
inherit an old window's accumulated days.

This is the collector-side twin of the experiment pre-registration mechanism
(`research/preregistration.py`): both freeze intent before evidence arrives,
and both make the freeze verifiable by hash rather than by promise.

## Freshness must be recomputed, never trusted

A closely related defect retired with the mining package (V4 defect E, recorded
in `tests/test_v4_defect_reproduction.py`): a snapshot carried both
`captured_at_utc` and a caller-supplied `staleness_seconds`, and the checker
believed the field instead of recomputing the age from the timestamp — so a
caller could declare stale data fresh. Any collector that reports its own
freshness reproduces this. The rule: staleness is always derived from a
persisted timestamp against the evaluation clock, never accepted as an input.

## Reference constants from the retired implementation

| Constant | Value | Meaning |
|---|---|---|
| `MIN_SHADOW_DAYS` | 14.0 | wall-clock floor, gap-excluded |
| `MIN_SHADOW_SNAPSHOTS` | 2000 | observation floor, non-substitutable |
| `GAP_THRESHOLD_SECONDS` | 1800 | beyond this, downtime, recorded as a gap |
| `HEARTBEAT_STALE_SECONDS` | 900 | older heartbeat = not running now |

The thresholds themselves were tuned for hourly-ish marketplace snapshots;
a token collector will need its own numbers. The *structure* — two
non-substitutable floors, gap-excluded elapsed time, chained journal, frozen
policy hash — transfers unchanged.

The retired source survives in git history: last present at tag-less commit
`5474c97` (`src/quant_trade/v9/mining_shadow.py`, 507 lines), for when an
implementation reference is wanted rather than this summary.
