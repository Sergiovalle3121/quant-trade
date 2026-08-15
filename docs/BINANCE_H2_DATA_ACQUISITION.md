# Binance H2 selection-only data acquisition

## Scope and verdict

This pipeline prepares data for falsifying the H2 `death_avoidance`
hypothesis. It is research-only. It does not generate orders, authorize real
money, reveal the reserved holdout, or establish profitability.

The acquisition policy is frozen to:

- venue: Binance Spot, USDT quote;
- selection interval: 2017-08-17 through 2023-11-28, inclusive;
- causal universe source: normalized daily CoinMarketCap snapshots;
- open-universe band: rank at most 1,000 and market capitalization from
  USD 10 million through USD 1 billion;
- stable identity: `CMC:<cmc_id>`; ticker and Binance symbol are metadata;
- output: a selection symbol plan and venue klines, never a combined-venue
  dataset.

Current normalized CMC day rows generally do not contain a historical
`is_stablecoin` field. Therefore plans built from those rows report
`status=INSUFFICIENT_EVIDENCE` with blocker
`HISTORICAL_STABLECOIN_CLASSIFICATION_MISSING`. Symbols on affected rows are
not guessed from a current list and are not represented as causally screened.
Acquisition may be staged, but H2 research must not treat that plan as a
research-ready universe until the blocker is resolved with historical,
point-in-time evidence.

The local artifact audited on 2026-08-13 makes the size of that blocker
explicit: all 2,295 selection dates are present, but all 10,924,565 causal rows
lack `is_stablecoin`. The plan therefore remains `INSUFFICIENT_EVIDENCE` even
though it lists 2,919 CMC identities and 2,844 candidate venue symbols. The
separate CMC-tag artifact finds 89,841 positive observations but leaves
11,581,874 observations `UNKNOWN`; its later response/capture timestamps do
not prove when those classifications became public.

## Research-readiness guard

`evaluate_binance_h2_selection_research_readiness(plan_dir)` is the explicit
fail-closed boundary between staged acquisition and a causal panel build. It
does not trust the manifest status label alone. After re-verifying the plan
and symbol bytes, it requires:

- the exact ordered 2,295-day source sequence from 2017-08-17 through
  2023-11-28, with no missing date;
- proof that neither holdout nor later sources were opened;
- an explicit historical stablecoin boolean on every causal row;
- zero manifest blockers and a non-empty eligible identity/symbol set; and
- no embedded profitability claim.

`require_binance_h2_selection_research_ready(plan_dir)` raises
`CryptoSelectionError` unless every condition holds. Passing it permits only
the next offline causal-panel construction step. Its verdict always exports
`holdout_access_authorized=false`, `pnl_generation_authorized=false` and
`real_money_authorized=false`; Gate 0, a trusted single-venue manifest, sealed
cost/execution evidence and a new ExperimentSpec remain separate blockers.

The next evidence artifact cannot be another current stablecoin list or a
negative inference from missing tags. It must be a typed point-in-time ledger
whose every assertion binds at least `CMC:<cmc_id>`, classification state,
`public_known_at`, effective interval, source bytes and SHA-256. It also needs
a documented completeness rule capable of supporting `NON_STABLE`; a
positive-only tag ledger cannot establish that all remaining rows are safe.

After that ledger is available, rebuild the selection plan from fresh
normalized bytes and run this guard. Only then should the repository add a
separate Binance v2 manifest/Gate-0 policy. The current protected experiment
manifest and Gate-0 implementation are still Bybit-only, so a successful
selection guard by itself cannot be routed into the existing P&L runner.

## Discovery contract

`build_binance_h2_selection_plan(universe_dir, plan_dir)` opens only paths of
the exact form `days/YYYY-MM-DD.jsonl` for dates inside the frozen selection
interval. It does not glob the directory. A file for 2023-11-29 or later can
therefore exist beside selection files without being opened or influencing a
single output byte.

Rows are streamed. Each opened source's relative path, byte count, row count,
and SHA-256 is recorded. An identity enters the candidate set only on a row
whose contemporaneous rank, capitalization and explicit stablecoin flag pass.
After entry, a later ticker for the same `cmc_id` is retained even after a
rank exit, because an existing position may need a mark or exit. A ticker seen
only before first eligibility is never backfilled. Reused tickers keep every
stable CMC identity in the manifest rather than silently welding them.

The plan directory must be new or empty. It receives:

- `symbols_selection.txt`: sorted, unique Binance venue symbols;
- `selection_manifest.json`: canonical JSON, embedded digest, source hashes,
  stable identity/ticker mappings, ambiguity evidence, exclusions and
  machine-readable blockers.

`load_binance_h2_selection_plan` re-hashes the manifest payload and the exact
symbol bytes before collection.

## Venue collection contract

`collect_binance_h2_selection_klines(plan_dir, venue_dir, ...)` refuses a
venue other than Binance and any start/end date other than the frozen
selection interval before invoking a fetcher. Binance requests include both
`startTime` and `endTime`; raw responses are therefore bounded at the HTTP
request, not merely trimmed after download.

Before the first request, the wrapper writes canonical
`selection_collection_binding.json`. It binds the plan digest, symbol bytes,
Binance policy bytes and exact window. Long collections can use
`max_symbols_per_run` and resume. Resume is allowed only when:

1. the intent binding is byte-for-byte identical;
2. the hash-chained journal is valid;
3. the journal header's venue, window, policy object and policy digest exactly
   match the binding; and
4. the directory contains only the declared collector layout.

A binding-only directory left before the collector journal begins is safe to
resume. Raw, series or receipt artifacts without a valid matching journal are
orphaned cache evidence and are refused. Unbound non-empty directories and
mixed Bybit/Binance caches are also refused.

The underlying collector journals unknown symbols instead of silently
dropping them, archives every raw page under its content hash, emits ingestion
receipts, and normalizes only rows inside the requested window.

## Offline acceptance tests

`tests/test_crypto_selection.py` covers exact range boundaries, a future day
file, source hashes, missing/explicit historical stablecoin fields, rename,
ticker reuse, invalid exchange tickers, canonical byte tampering, output
isolation, pre-request intent, Binance `endTime`, batched exact resume,
orphaned/unbound cache refusal, refusal of incomplete selection coverage and a
complete offline research-readiness case. `tests/test_venue_klines.py`
independently pins the request-side end boundary. All network behavior in
tests uses local fixture responses.

No market-data cache, generated manifest, raw response or selection result is
committed by this implementation.
