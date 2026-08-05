# Anti-bias plan for the low/mid-cap crypto dataset — the three poisons

Session A, Block 2. This is the detection-and-handling design the acquisition
(Block 5) and the quality validator (Block 3) implement. No strategy content.

Sources and their measured properties: `docs/CRYPTO_LOWCAP_DATA_SOURCES.md`.
Pattern being applied: `docs/COLLECTOR_INTEGRITY_PATTERN.md`.

Design rule used throughout: **detected data is flagged and kept, never
deleted.** A poisoned row that vanishes silently becomes unfalsifiable; a
poisoned row that stays with a flag is evidence about the source. Exclusion
happens at universe-construction time, visibly, by rule.

## Poison 1 — survivorship bias (the worst)

**How it manifests.** The universe is assembled from coins that exist *today*;
every coin that went to zero is absent, so any long strategy backtests
against a sample whose losers were removed by construction. Subtler forms:
histories truncated at death with no death marker (the coin just "stops",
and a naive join forward-fills its last price into eternity); resurrections
(delisted then relisted, leaving a hole that looks like missing data);
ticker reuse (a dead coin's symbol reassigned to an unrelated token, welding
two price histories together).

**How it is detected.**

- *Constructionally*: universe membership for date T is computed **only**
  from the point-in-time snapshot dated T (CMC data-api). Today's coin list
  is never an input. This is not a detector but the reason the detector class
  exists — everything below verifies the construction held.
- *Churn measurement*: per calendar year, count coins entering and leaving
  the top-N-by-rank universe. Low-cap crypto has double-digit annual
  mortality; a built universe showing near-zero exits is the alarm itself
  (it means dead coins leaked out of the panel).
- *Death cross-check, three independent angles*: (a) last snapshot date on
  which the coin appears; (b) CoinPaprika `is_active: false` (48,992 coins,
  free); (c) venue klines ending months before today (venue delist). A coin
  flagged dead by (b) but still present in recent snapshots — or alive today
  but absent from snapshots — is a source inconsistency to record, not to
  smooth over.
- *Ticker-reuse guard*: coin identity is the source's stable id (CMC numeric
  id / paprika slug), **never the ticker symbol**. A symbol that maps to two
  ids across time is recorded as a rename/reuse event (validator check,
  Block 3).

**What is done with detections.** Dead coins stay in the panel up to their
last real observation, carrying `death_date` and `death_source`. Membership
functions are pure functions of snapshot data at T. Resurrection holes remain
holes (gap records, below). Any experiment consuming the dataset binds to the
dataset version hash (existing `dataset_binding` mechanism), so a universe
rebuilt after a survivorship fix is a *different dataset* by hash, and old
results cannot silently claim the new data.

## Poison 2 — fake volume

**How it manifests.** Exchange-reported volume is inflated by wash trading,
zero-fee incentive schemes and outright fabrication; aggregator `volume24h`
sums all venues including the garbage ones. A coin can show millions in
daily volume and be untouchable beyond a few hundred dollars. In bar data:
volume wildly out of proportion to market cap (>100% of mcap turning over
daily), volume flat/identical across many days (quota-shaped), high reported
volume coexisting with zero price range, and aggregate volume many multiples
of the volume on any credible venue.

**How it is detected.**

- *Venue-ratio screen*: `aggregate_volume / credible_venue_volume` where the
  denominator is the coin's volume on vetted venues (Bybit, Binance —
  measured, receipted klines). Ratio thresholds are declared ASSUMPTION-class
  initially and tuned on measured distributions, not invented per-coin.
- *Turnover sanity*: daily volume / market cap. Sustained >1.0 in a low-cap
  is presumptively wash (ASSUMPTION threshold, declared).
- *Volume–range coherence*: days with high volume and zero high-low range;
  runs of identical volume values (exact-repeat counting, no distributional
  assumption needed).
- *What is honestly out of reach*: trade-level screens (Benford digits,
  round-size clustering, buy/sell alternation) need tick data we do not have
  free — recorded as NOT_MEASURED, not approximated at bar level.

**What is done with detections.** Every coin-date carries two liquidity
fields: `reported_volume` (as-reported, kept for audit) and
`credible_volume` (vetted-venue volume only; absent venue = 0, i.e. a coin
with no vetted-venue listing has *no demonstrated liquidity*, whatever the
aggregator claims). Screens set `wash_suspect` flags with the failing rule
named. Flagged coins remain in the dataset, visible; the tradable-universe
constructor excludes on `credible_volume` and flags, and the exclusion list
per date is part of the dataset artifact (auditable, versioned).

## Poison 3 — phantom prices

**How it manifests.** A close is printed where no real buyer existed: stale
prints carried forward for days (constant close, zero volume), bid-ask
bounce in an empty book (spike up, full reversal next bar, no volume),
aggregator prices computed from one dead venue, prints far from any vetted
venue's simultaneous close. A backtest "sells" into these prices; live, the
order book would have absorbed the order at a fraction of the mark.

**How it is detected** (validator checks, Block 3):

- zero-volume bars whose close nonetheless moves (`price moved with no
  volume` — phantom by definition at bar granularity);
- constant-price runs: N consecutive identical closes (dead-but-listed
  token; threshold declared, exact-match so no distribution assumed);
- low-volume spike-reversal: |return| large on bottom-decile volume followed
  by ≥80% retracement next bar (parameters ASSUMPTION-class, declared);
- cross-source disagreement: snapshot price vs vetted-venue close on the
  same date diverging beyond a declared band — the venue close wins, the
  divergence is recorded;
- split/redenomination guard: a −90%+ overnight "return" with volume and
  supply jumping proportionally is a redenomination, not a crash (checked
  against circulating-supply series from snapshots).

**What is done with detections.** Bars get a quality grade per coin-date:
`clean`, `degraded` (survives with caveats), `phantom` (present, flagged,
never a valid execution or valuation price). Phantom bars are excluded from
return computation for screening; a coin whose tail is all-phantom has its
effective death date pulled back to its last clean bar. Grades and reasons
live in the dataset artifact so the exclusion is reproducible byte-for-byte.

## Applying the collector-integrity pattern (Block 2.4)

The acquisition collector (Block 5) inherits all four defences from
`docs/COLLECTOR_INTEGRITY_PATTERN.md`, plus the Defect E rule:

1. **Persisted wall-clock**: every fetched page records `wall_clock` and
   `clock_source` at capture. Elapsed acquisition time is recomputed from
   persisted stamps; replaying archived pages advances counts, never the
   clock. Fixture-driven runs are marked test-only forever (the
   `panel_backfill` convention: fixtures can never become real).
2. **Hash-chained journal**: one journal per acquisition run; every record
   carries `previous_sha256` over canonical JSON; `verify_chain()` re-walks
   from genesis on resume; single writer enforced by a lease file. Raw pages
   are content-addressed (existing `evidence/receipts.py`), so the journal
   chains *references to bytes that cannot drift*.
3. **Gaps are first-class**: a snapshot date that could not be fetched is a
   `gap` record carrying the verbatim error (`NOT_RUN_NETWORK_BLOCKED`,
   HTTP status, parse rejection). Coverage metrics exclude gap time. A
   missing date is never interpolated — in a 24/7 market a hole is a signal
   (venue outage, source outage, or our outage — the record says which we
   can prove). This is also how "no data existed" stays distinguishable from
   "we were not looking", which is the survivorship question in miniature.
4. **Frozen policy hash**: the universe-construction rule (rank band,
   liquidity screens, flag thresholds) is a declared document hashed into
   the acquisition journal header at start — the collector-side twin of
   `research/preregistration.py`. Changing any threshold mid-acquisition
   resets the window and produces a new dataset version.

**Defect E, restated for datasets**: freshness and coverage are always
*recomputed* from persisted timestamps and journal contents by the validator;
the collector's own summary numbers are display hints, never inputs to any
gate. A collector that reports its own freshness is falsifiable by
construction — so nothing downstream believes it.

## Thresholds

Every numeric threshold above ships as ASSUMPTION-class evidence with a
declared value in versioned config, following the
`v9/cost_evidence.py` vocabulary (`ASSUMPTION` → `REAL_PUBLIC_RETAIL`).
A threshold graduates only when tuned against measured distributions from
the acquired data, and the tuning itself is recorded. No unlabelled numbers.
