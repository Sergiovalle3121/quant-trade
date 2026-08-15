# CMC stablecoin tag evidence (v1)

`quant_trade.data.crypto_stablecoin_evidence` builds the canonical
`stablecoin_observations_v1` artifact from the archived raw CoinMarketCap
historical-snapshot pages and their ingestion receipts. It is offline,
deterministic, byte-hashed and hard-stopped at **2023-11-28**; it never opens a
raw page whose receipt requests a later date.

Each row retains stable `cmc_id`, requested `snapshot_date`, the entry's
`effective_at_utc`, CMC `source_response_at_utc`, local `captured_at_utc`, exact
tag list (including its original order and spelling), raw SHA-256 and receipt
SHA-256. The complete receipt chain, selected raw bytes and the
collector-normalized row digest are all reverified. The loader then rehashes
the manifest and every daily file and rejects extra, missing or non-canonical
bytes.

Repeated captures for the same snapshot page are not resolved by choosing the
first response. Every receipt, raw payload and normalized-row binding is
verified, then the extractor compares a canonical projection containing page
identity plus each entry's `cmc_id`, `lastUpdated`, tags shape and exact tags.
Retries are accepted only when that projection digest is identical. The
artifact records all corroborating raw/receipt hashes and response/capture
timestamps in sorted lists, so irrelevant response metadata and retry order do
not change the semantic observation bytes. A changed tag remains an ambiguous
source conflict and fails closed.

The automatic state is deliberately asymmetric:

- any tag containing `stablecoin` (case-insensitive) is
  `STABLECOIN_POSITIVE`;
- absent tags, null tags, an empty list, or a list without that substring is
  `UNKNOWN`;
- automatic extraction never emits `NON_STABLE`.

No state is forward-filled or backfilled across dates. Post-cutoff receipts
are ignored after parsing only their requested date, and their raw paths are
not resolved. Consequently, appending a future receipt or future tag cannot
change any artifact byte through the cutoff. Receipt metadata for the complete
ledger is still chain-verified; a manipulated future receipt invalidates the
source ledger without opening its raw page.

The artifact is compact: daily JSONL files contain only positive observations.
UNKNOWN rows are represented by per-page and per-day coverage counts split by
`ABSENT`, `NULL` and `LIST`, plus a digest over each compacted decision and its
exact tags. Raw and receipt hashes remain attached to every page. This proves,
for example, how many explicit nulls became UNKNOWN without materializing
millions of repetitive UNKNOWN rows.

## What this does not prove

The CMC source-response and local capture timestamps may be years after the
requested historical snapshot. The entry timestamp is not a tag-specific
publication timestamp. Therefore v1 records positive source evidence but
**does not prove when a tag first became public**, does not clear the
historical stablecoin classification blocker, and must not be joined into the
causal eligibility panel. Its manifest stays `INSUFFICIENT_EVIDENCE`,
`blocker_cleared=false` and `profitability_evidence=false`.

There is intentionally no manual `NON_STABLE` ledger in v1. Such a ledger
would need a typed `public_known_at`, evidence URL and content hash for every
assertion; absence from a list is not evidence of non-stable status or of
classification completeness.

## Offline usage

```python
from datetime import date

from quant_trade.data.crypto_stablecoin_evidence import (
    build_stablecoin_observations,
    load_stablecoin_observations,
)

build_stablecoin_observations(
    "data/cache/crypto_universe/v1",
    "data/derived/stablecoin_observations_v1_2023-11-28",
    cutoff_date=date(2023, 11, 28),
)
artifact = load_stablecoin_observations(
    "data/derived/stablecoin_observations_v1_2023-11-28"
)
for observation in artifact.iter_observations():  # positive rows only in v1
    pass
```

The destination must be new. Generated evidence stays uncommitted alongside
the market-data cache.
