# Alpaca SPY TOM read-only collector

Status: **IMPLEMENTED AND TESTED OFFLINE — NOT RUN — NO AUTHENTIC BUNDLE**

`alpaca_spy_tom_collector.py` creates the exact local bundle consumed by the
sealed SPY turn-of-month development evaluator. It is a data-acquisition tool,
not a broker adapter. Importing it performs no network activity, and collection
requires an explicit `ReadOnlyTransport` instance.

The collector can issue only HTTPS `GET` requests to this fixed allowlist:

- `https://paper-api.alpaca.markets/v2/calendar`;
- `https://data.alpaca.markets/v2/stocks/SPY/quotes`;
- `https://data.alpaca.markets/v2/stocks/SPY/trades`;
- `https://paper-api.alpaca.markets/v2/corporate_actions/announcements`.

It has no generic HTTP method, trading endpoint, account endpoint, position
query, order route, transfer route, live-trading hostname, shorting, or
leverage path. Tests use a fake transport and make no requests.

Official references:

- [historical SPY quotes](https://docs.alpaca.markets/us/v1.1/reference/stockquotesingle-1);
- [historical SPY trades](https://docs.alpaca.markets/us/reference/stocktradesingle-1);
- [US market calendar](https://docs.alpaca.markets/us/reference/legacycalendar);
- [market-data plans and SIP limitations](https://docs.alpaca.markets/us/docs/about-market-data-api);
- [deprecated announcement contract](https://docs.alpaca.markets/us/v1.1/reference/get-v2-corporate_actions-announcements-1);
- [current corporate-actions API and vintage warning](https://docs.alpaca.markets/us/reference/corporateactions-1).

## Fail-before-network preflight

Before the transport can be called, collection requires:

1. paper-scoped `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_SECRET_KEY` in the
   process environment; generic `APCA_*`, `ALPACA_API_KEY` and live/base-URL
   variables are rejected even if paper variables are also present;
2. an explicit `ALPACA_MARKET_DATA_PLAN=BASIC` or
   `ALPACA_MARKET_DATA_PLAN=ALGO_TRADER_PLUS` declaration;
3. aware start, hard-cutoff and as-of timestamps with the cutoff not after
   as-of;
4. a start no earlier than Alpaca's documented 2016 historical-data boundary;
5. a Basic-plan cutoff at least 15 minutes old;
6. an independently frozen canonical fee schedule and its expected SHA-256;
7. a new output path. Existing output is always refused.

The plan environment variable is a local declaration, not proof of an Alpaca
entitlement. A provider `403` fails as
`ALPACA_SIP_ACCESS_FORBIDDEN_VERIFY_PLAN`; the collector never queries an
account or subscription endpoint to infer it.

Credentials are passed only as request headers. They are excluded from the
configuration digest, state, request ledger, receipts, manifest and errors.
Successful responses that echo either credential are rejected before they are
written.

## The 120-pair feasibility gate

The first and only request before market ticks is the Alpaca calendar. The
collector then computes the maximum attestable pair count using the sealed
rule itself:

- primary entry: penultimate session of the anchor month;
- primary exit: third session of the following month;
- control entry and exit: eighth and twelfth sessions of the following month;
- if any of those four sessions closes before 15:58 New York time, the entire
  adjacent-month pair is excluded.

If fewer than 120 pairs remain, collection stops before any quote, trade or
corporate-action request with the machine-readable reason:

```text
MAXIMUM_ATTESTABLE_PAIRS_BELOW_120
```

This is important at the data boundary. From January 2016 through January 2026
there are only 120 adjacent calendar-month pairs before early-close
exclusions; one excluded event month makes that range insufficient. A later
cutoff can increase the ceiling, but the collector accepts only the count from
the captured calendar. It never lowers the 120-pair threshold or modifies the
strategy seal.

## Pagination, cutoff and recovery

The collector never downloads a continuous decade of SPY ticks. It derives the
four sessions used by every eligible adjacent-month pair, deduplicates those
dates, and requests only `15:56:00` through `15:58:00` New York time for each
date. Every page repeats that exact event-window `start`/`end`, `feed=sip`,
`sort=asc` and `limit=10000`. Only Alpaca's opaque `page_token` can change.
Missing, repeated, cyclic or empty-page tokens fail closed. Every returned
observation is independently checked to be inside its event window and
monotonically ordered across all windows.

Hard, sealed resource ceilings stop a malformed or hostile pagination stream:
600 event windows, 16 pages per window, 5,000 recorded successful requests,
6,000 HTTP attempts per invocation, 64 MiB per identity-encoded response, 2 GiB
each for retained response and normalized-row bytes, and a default one-hour
invocation deadline. Local reads are also bounded before allocation: 64 MiB
for collector state, 4 MiB for fee evidence, 128 MiB per normalized page and
64 MiB for the aggregate calendar/corporate-action inputs. The real transport uses `stream=True`, rejects an
oversized `Content-Length`, sends `Accept-Encoding: identity`, rejects any
non-identity `Content-Encoding`, and counts streamed chunks before retaining
them; it never materializes `response.content` first.

The deprecated announcement endpoint is queried in inclusive windows whose
date difference never exceeds its documented 90-day maximum. The final window
cannot extend beyond the local date of the hard cutoff.

Before the next request, each successful response and its next cursor are:

1. saved with its SHA-256 as its filename;
2. linked to the preceding response receipt hash;
3. recorded together in one canonical atomic checkpoint without credentials.

On restart, all response bytes, normalized pages and every hash-chain link are
verified before pagination resumes. A completed page is not downloaded again.
A crash before the atomic state replacement may leave an unreferenced
content-addressed file, but it cannot persist a receipt without its cursor or
vice versa; a retry verifies and safely reuses identical orphan bytes.
Every request-chain entry also commits the role cursor after that response;
offline verification reconstructs `complete`, token, window index, sequence
and last timestamp from the chain. Editing a standalone completion flag is
therefore rejected. Content-addressed outputs are written to fsynced temporary
files and linked into place atomically, so a killed writer cannot turn a
partial file into valid evidence.
Materialization re-hashes and checks the size of every source chunk from the
same open file handle whose bytes are copied; changing a chunk after the
earlier resume audit cannot create an apparently valid aggregate artifact.
`429` and `5xx` responses use bounded retry/backoff; an excessive retry delay
stops safely so a later invocation can resume. Calls are paced to the declared
plan's documented request-rate ceiling.

Publishing is an atomic rename from `.NAME.partial` to `NAME`. Neither final
artifacts nor content-addressed pages are overwritten. The bundle retains the
`.collector` response ledger for offline verification with
`verify_alpaca_spy_tom_collection_ledger()`.

A crash-released operating-system file lock serializes the complete collection
for one output name. A second process fails closed instead of forking the
cursor. The lock inode must be a single-link regular file; symlinks and
hardlinks are rejected without writing through them. The manifest capture
timestamp is persisted in collector state before
materialization, so a crash immediately before the final rename resumes with
byte-identical manifest content rather than a new clock value.
If that fully captured state is resumed after `as_of`, the collector permits
only this local verify-and-publish path. Any incomplete role or missing
persisted capture timestamp still fails the clock boundary, and no transport
method can be called.

## Canonical output

The published directory contains:

```text
manifest.json
raw/calendar.jsonl
raw/quotes.jsonl
raw/trades.jsonl
raw/corporate_actions.jsonl
raw/fees.jsonl
raw/receipts.jsonl
.collector/state.json
.collector/responses/...
.collector/rows/...
```

`manifest.json` has no trailing newline because the evaluator requires exact
canonical JSON bytes. Every JSONL record is canonical and newline terminated.
The five evaluator receipts bind the normalized artifact hash and use the last
collector-chain hash for that role as `receipt_id`. Their
`request_parameters` describe the aggregate artifact scope expected by the
evaluator; the exact sparse window, page token and limit of every HTTP request
remain in `.collector/state.json`.

The collector/evaluator bundle contract is
`alpaca_spy_sip_development_bundle_v2`. Quote and trade receipts explicitly
declare `EXACT_EVENT_WINDOWS_1556_1558_ET`, the number of unique event windows,
and the SHA-256 of the canonical ordered `{start,end}` window list. They never
claim that 480 sparse GETs were one continuous historical request.

Even the sparse event windows can produce a sizable SIP cache. Normalized quote
and trade chunks are streamed into their final artifacts instead of joined in
RAM. Never put a generated bundle, response page, `.partial` directory or
credential file in Git.

## Required fee evidence

Alpaca does not expose a historical fee-schedule API matching the evaluator.
Consequently, the collector does not invent fees and does not read account
activities. The caller must provide a separately captured, canonical JSONL
schedule and an independently recorded SHA-256. Rows have the exact form:

```json
{"commission_bps_per_side":0.0,"effective_end":"2026-01-30","effective_start":"2016-01-04","regulatory_sell_bps":0.2,"regulatory_sell_fixed_cents":0,"source_url":"https://alpaca.markets/disclosures/fees"}
```

Intervals must be contiguous, the regulatory sell rate must meet the
evaluator's positive floor, and source URLs must use an official Alpaca HTTPS
host. This structural check is not proof that a manually captured historical
schedule is correct.

## Corporate-action blocker

The evaluator v1 requires the receipt endpoint string
`/v2/corporate_actions/announcements`. Alpaca now marks that endpoint deprecated
in favor of `https://data.alpaca.markets/v1/corporate-actions`. The old
announcement model provides declaration dates and revision IDs but no signed
ingestion timestamp. The collector groups announcements by
`corporate_action_id`, selects the last declaration no later than the ex-date,
and preserves every original response in the hash chain.

This is only a reproducible transformation of Alpaca's response. It is not a
cryptographic vintage attestation. Alpaca's current documentation also warns
that corporate-action creation time is not guaranteed. Therefore the evaluator
must continue reporting
`external_data_authority_verified=false` and can return only
`INSUFFICIENT_EVIDENCE`.

Migrating to the current API requires a new evaluator schema and seal; this
collector intentionally does not silently mislabel the current endpoint as the
deprecated one.

## Explicit invocation

No CLI or scheduled task is registered. A human must prepare fee evidence,
set credentials locally, select a cutoff, and explicitly construct the network
transport:

```python
from datetime import UTC, datetime
from pathlib import Path

from quant_trade.data.alpaca_spy_tom_collector import (
    AlpacaSpyTomCollectorConfig,
    RequestsReadOnlyTransport,
    collect_alpaca_spy_tom_bundle,
)

result = collect_alpaca_spy_tom_bundle(
    AlpacaSpyTomCollectorConfig(
        output_root=Path("outside-the-repository/alpaca-spy-tom-bundle"),
        start=datetime(2016, 1, 4, 14, 30, tzinfo=UTC),
        hard_cutoff=datetime(2026, 7, 31, 20, 0, tzinfo=UTC),
        as_of=datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
        fee_schedule_path=Path("outside-the-repository/fees.jsonl"),
        expected_fee_schedule_sha256="<independently recorded lowercase SHA-256>",
    ),
    RequestsReadOnlyTransport(),
)
```

This example is illustrative and is not a recommendation to purchase a data
plan or run collection. No authentic collection was performed while developing
or testing this module.
