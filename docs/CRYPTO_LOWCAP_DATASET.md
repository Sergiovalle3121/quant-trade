# The low/mid-cap crypto dataset — what was acquired, and what it proves

Session B, Block 1. Acquisition and validation only: no strategy content, no
backtests, no returns computed.

Sources and their measured properties: `docs/CRYPTO_LOWCAP_DATA_SOURCES.md`.
Detection design being implemented: `docs/CRYPTO_LOWCAP_ANTIBIAS_PLAN.md`.
Cost model that constrains everything downstream: `docs/CRYPTO_LOWCAP_COST_MODEL.md`.

Everything below labelled MEASURED was produced by a live run from this
development environment on 2026-08-11 and is recomputed from bytes on disk by
`quant_trade.data.quality.universe`, never taken from a collector's own
self-report (the Defect E rule). The dataset itself is git-ignored; what is
committed is the code, the validation, and the numbers.

## What exists now

| Leg | Module | Extent | Status |
|---|---|---|---|
| Point-in-time universe | `data/universe.py` | 4,852 days, 2013-04-28 → 2026-08-09 | MEASURED |
| External death list | `data/deathlist.py` | 60,918 coins, one snapshot 2026-08-11 | MEASURED |
| Venue klines | `data/venue_klines.py` | Bybit + Binance spot, 2017-08-17 → 2026-08-09 | see below |

A correction to the session's starting assumption, recorded because it changes
how the numbers read: the universe collector had already been run once, on
2026-08-05, covering 2020-01-01 → 2022-02-24 (786 contiguous days). This run
extended that to the full range rather than starting from nothing. All 4,852
day records carry `clock_source: system`, so the whole panel is real-provenance;
none of it is fixture-derived.

## Universe acquisition (Block 1.1) — MEASURED

One CMC point-in-time snapshot per day over the deepest range the source
offers. The earliest snapshot the endpoint serves is 2013-04-28 and it returns
exact-date data at every probe tested back to 2013-05-01, so the range is
source-limited, not choice-limited.

```
days requested   4,852
days collected   4,852
gap records          0
UNOBSERVED days      0
coverage         1.000
elapsed          123 minutes
on disk          15 GB (git-ignored)
```

Zero gaps and zero unobserved days is the outcome to check, not to celebrate:
in a 24/7 market a hole is a signal, and the absence of holes is what makes the
churn measurement below trustworthy. Depth per snapshot grows with the market —
7 rows on 2013-04-28, 866 on 2017-06-14, 5,000 on 2021-09-08, 10,000 at the
deepest days in 2024-2026.

Policy sha256 `787d52a55f6a24947d7d34a6ee35490b562a00ff3891b8f0593f5d8859ee69db`,
sealed in the journal header and re-verified on every resume.

## Validation (Block 1.3) — MEASURED

`validate_universe` recomputes every claim from the journal and the day files.
Full report reproduced by the command at the end of this document.

### The survivorship alarm did not fire

The stop condition was zero exits from the top-N universe. Measured exits from
the top-500, by year:

| Year | Entered | Exited | | Year | Entered | Exited |
|---|---:|---:|---|---|---:|---:|
| 2016 | 153 | 153 | | 2021 | 239 | 239 |
| 2017 | 198 | 198 | | 2022 | 217 | 220 |
| 2018 | 311 | 311 | | 2023 | 112 | 109 |
| 2019 | 254 | 254 | | 2024 | 140 | 140 |
| 2020 | 199 | 199 | | 2025 | 174 | 174 |
| | | | | 2026 | 227 | 227 |

Entries and exits match almost exactly because the top-500 is a fixed-size set:
once it is full, every entry displaces someone. The years that differ (2022,
2023) are the ones where the set was not exactly full.

Of **34,278 distinct coins** ever observed, **25,774 (75%)** were last seen more
than 30 days before the panel ends. Restricted to the study window and the
tradable rank band, 5,360 of 6,360 coins (84%) are gone before the window
closes. This panel is not a survivors' panel.

### Journal chain and file integrity

4,853 records re-walked from genesis: chain intact. All 4,852 day files
re-hashed against the digests the journal claims for them: **0 mismatches, 0
missing files**.

### Death cross-check — MEASURED, not NOT_MEASURED

The external list is CoinPaprika's `is_active` roster, captured live
(raw sha256 `a94c1b4a40ae067065a3611747c4e4e7ef2ccc8b9468fe8c4bedba688ad188fc`):

```
coins in roster           60,918
inactive coins            48,817
active coins              12,101
distinct inactive tickers 33,027
distinct active tickers    9,835
tickers on BOTH lists      4,128
```

Coin counts and ticker counts are reported separately on purpose: thousands of
coins share a ticker, and reporting one as the other misstates the death list by
tens of thousands. Of 25,774 death candidates in the panel, **20,894 (81.1%)**
are corroborated by a matching inactive ticker.

The method is a declared heuristic and stays one: coin ids do not map across
sources, so the match is by symbol, and 4,128 tickers are carried by both a dead
and a live coin — for those, a symbol match cannot distinguish which died. The
81.1% is therefore a corroboration rate, not a death rate, and the residual 19%
is uncorroborated rather than disproved.

## Source defects found (and attributed)

Both are the source's, and the archived raw pages are what make that provable
rather than assertable.

**11,445 duplicate (day, coin) pairs, confined to 4 days** — 2020-07-13,
2020-07-16, 2020-08-05, 2020-08-14. Reading the archived page for 2020-07-13:

```
page 1 (start=1, limit=5000):  5,000 entries, 2,714 distinct ids
page 2 (start=5001):             428 entries,   428 distinct ids
2020-07-12, the day before:    2,708 entries, 2,708 distinct ids
```

CMC padded a page to the 5,000 limit by repeating entries. Because the page
came back exactly full, the collector correctly treated it as a full page and
requested the next one. The duplicated rows are byte-identical, so
deduplicating by `(date, cmc_id)` downstream is a no-op on content and chooses
nothing. 4 days of 4,852 (0.08%), all inside the study window.

**10 rows with negative market cap**, positive volume alongside: KYL
(2021-03-12), LUA (2021-03-15/16/17), ZNZ (2021-05-30/31, 2021-06-01), GMEE
(2022-12-23/24/25). A negative capitalisation is a source error, presumably a
corrupted circulating-supply figure. Flagged and excluded at
universe-construction time, visibly and by rule, per the anti-bias plan's
"detected data is flagged and kept, never deleted".

**6,208 ticker reuse events** across the full history; 624 within the study
window, plus 145 coins that changed their own ticker. This is the identity weld
the anti-bias plan warned about, and it is large enough to matter: coin identity
is `cmc_id` throughout, and the universe→venue bridge (venues know only
tickers) records the ambiguity instead of resolving it silently.

## Venue klines (Block 1.2)

Prices come from venues because a strategy can only trade venue prices;
snapshot prices are a cross-check and never an execution price. Two venues,
because they disagree and the disagreement is data — measured, one coin, two
venues:

```
SRMUSDT on Binance: 2020-08-11 → 2022-11-28
SRMUSDT on Bybit:   2021-10-22 → 2024-11-22
```

Serum died once, and a single-venue panel would have recorded the death two
years early or two years late depending which venue it asked. Earliest bar
available at all: Binance 2017-08-17, Bybit 2021-07-05 — which is why the study
window starts in 2017 and why Bybit alone would have bounded it to 5.1 years.

Each venue is a separate dataset directory under its own frozen policy hash; a
journal opened for one venue refuses to continue under another. Composing them
stays a declared downstream decision, because the measured cost model was
calibrated on Bybit books only and applying it to Binance fills is an
ASSUMPTION, recorded as one.

Symbols asked about: every ticker whose coin reached `cmc_rank <= 1000` on any
snapshot date in the window — 5,740 tickers from 6,360 coins. Declared filter:
42 tickers that cannot be an exchange symbol at all (`$MONG` and similar) are
not requested, because the request would not be well-formed. The remaining
5,698 are all asked, and every answer is journaled including "the venue never
listed this" — the outcome that removes a coin from the tradable universe, and
therefore the one that most needs bytes behind it. Both venues distinguish it
from silence (Bybit `retCode 10001` over HTTP 200, Binance HTTP 400 `-1121`),
and the collector archives and receipts the answering page *before* it
interprets it, so an exclusion cites evidence like everything else.

Run results are appended to this document when the collection completes.

## What is NOT measured

Declared rather than glossed:

- **Historical spread and depth.** The cost model rests on one live
  cross-section of 57 order books (2026-08-05). That today's cost structure
  resembles 2018's is an ASSUMPTION and is not testable with free data.
- **Trade-level wash-trading screens.** Benford digits, round-size clustering
  and buy/sell alternation need tick data that is not free. Bar-level proxies
  are implemented; the trade-level ones are absent, not approximated.
- **Death dates as facts.** The panel gives last-appearance dates and an
  external activity flag. Neither is a death certificate, and 19% of death
  candidates are uncorroborated.
- **The 4,128 ambiguous tickers.** For these, symbol-level death matching
  cannot say which of the two coins died.
- **Sustained-rate behaviour of the CMC endpoint.** 4,852 days drew no
  throttling at ~1 request/second. Nothing was learned about harder rates
  because nothing harder was attempted.

## Reproduction

```bash
python - <<'PY'
from datetime import date
from quant_trade.data.universe import collect_universe
from quant_trade.data.deathlist import collect_death_list, load_inactive_symbols
from quant_trade.data.quality.universe import validate_universe

collect_universe("data/cache/crypto_universe/v1",
                 start_date=date(2013, 4, 28), end_date=date(2026, 8, 9),
                 sleep_seconds=0.4)
collect_death_list("data/cache/crypto_universe/deathlist")
report = validate_universe(
    "data/cache/crypto_universe/v1",
    requested_start=date(2013, 4, 28), requested_end=date(2026, 8, 9),
    inactive_symbols=load_inactive_symbols("data/cache/crypto_universe/deathlist"))
print(report.to_dict())
PY
```

Acquisition is resumable and idempotent: days already journaled are skipped,
days journaled only as gaps are retried, and a changed policy hash refuses to
continue into an existing directory. A blocked network records
`NOT_RUN_NETWORK_BLOCKED` with the verbatim error and fabricates nothing. Tests
are fixture-driven and never touch the network.
