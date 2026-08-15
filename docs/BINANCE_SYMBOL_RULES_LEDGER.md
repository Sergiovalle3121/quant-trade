# Binance Spot symbol-rules ledger (PIT v2)

Status: **local research evidence only**. This component does not fetch from
Binance, evaluate P&L, send orders, authenticate a venue response, or authorize
real money.

## Security boundary: integrity is not authenticity

Binance `GET /api/v3/exchangeInfo` returns current metadata, not historical
rules. Applying a snapshot captured today to an earlier backtest date is
look-ahead. V2 therefore treats each response as a point-in-time observation:

- `observed_at_utc` is the receipt capture time and is the earliest instant at
  which the bytes may be inspected;
- the payload's `serverTime` must not regress across receipts;
- capture must occur from 0 through 300 seconds after `serverTime`; that bound
  is sealed in the ledger bytes;
- lookup uses only the latest full snapshot observed at or before `as_of_utc`;
- the caller must provide a positive `max_age`;
- absence from a later snapshot blocks lookup, with no fallback and no inferred
  delisting;
- appending future evidence cannot change `prefix_bytes(T)` or lookup at `T`.

The local receipt chain, raw SHA-256, and normalized-row SHA-256 detect local
tampering. They do **not** prove that the bytes came from Binance: a user can
create new bytes and recompute every local hash. `source_kind=live` is retained
only as `receipt_declared_source_kind`, never as authentication.

Consequently V2 has no successful availability path:

- a fixture returns `TEST_ONLY_PROVENANCE`;
- a self-labelled live receipt with complete rules returns
  `UNATTESTED_SOURCE`;
- `AVAILABLE_REAL` is reserved for a future independent attestation protocol,
  and its public constructor currently rejects it unconditionally;
- unavailable and unattested lookups never expose a `rule` object;
- `real_money_authorized`, `pnl_evaluation_authorized`, and
  `network_access_authorized` are fixed `false` and cannot be constructor
  arguments.

Copying or constructing snapshots directly cannot upgrade this status. A
future schema must define an external attestation object, its trusted issuer,
signature validation, replay policy, and digest binding before enabling
`AVAILABLE_REAL`.

## Sealed receipt contract

The loader accepts only receipts with this identity:

| Field | Required value |
|---|---|
| `provider_or_venue` | `binance` |
| `endpoint` | `https://api.binance.com/api/v3/exchangeInfo` |
| `request_parameters` | `{}` (full snapshot) |
| `http_status` | integer `200` |
| `adapter_name` | `data.binance_spot_symbol_rules.exchange_info` |
| `adapter_version` | `2` |
| receipt `schema_version` | integer `1` |

The complete `receipts.jsonl` chain is checked before parsing. The raw path
must remain inside the receipt directory. Exact raw bytes must match
`raw_sha256`; deterministic V2 rows must match `normalized_rows_sha256`. If
`server_timestamp_utc` is present, it must equal the raw payload's
`serverTime`.

These controls authenticate internal consistency only. Acquisition is a
separate, presently unimplemented trust boundary.

## Exact filter schema

Every USDT row is preserved, including `isSpotTradingAllowed=false`. The row
records `exchange_status` separately; neither field is inferred from the
other. Each row requires unambiguous `PRICE_FILTER`, `LOT_SIZE`, and
`MARKET_LOT_SIZE`, plus at least one complete `MIN_NOTIONAL` or `NOTIONAL`.

V2 binds:

- `PRICE_FILTER.tickSize` and whether the exact value is enabled;
- `LOT_SIZE.minQty`, `maxQty`, and `stepSize`;
- `MARKET_LOT_SIZE.minQty`, `maxQty`, and `stepSize`, with a separate enabled
  boolean for each value;
- `MIN_NOTIONAL.minNotional`, `applyToMarket`, and `avgPriceMins` as one
  all-or-none group;
- `NOTIONAL.minNotional`, `maxNotional`, `applyMinToMarket`,
  `applyMaxToMarket`, and `avgPriceMins` as one all-or-none group.

Decimal values remain exact canonical strings. JSON floats are rejected. For
`MARKET_LOT_SIZE` (and `PRICE_FILTER.tickSize`) an exact zero is retained as
`"0"` with its enabled flag set to `false`; it is neither discarded nor
misreported as a positive constraint. `LOT_SIZE` quantities/step and notional
bounds must be positive. Boolean fields require real JSON booleans, and
`avgPriceMins` requires an integer of zero or greater (`true` is not accepted
as integer `1`).

If both notional filters are present, both remain separate. V2 does not merge
them into a synthetic minimum because their market-order flags and averaging
windows can differ.

The official semantics are documented in the
[Binance Spot symbol filters](https://developers.binance.com/en/docs/products/spot/filters).

## Offline receipt construction

Acquisition is intentionally absent. An approved collector may write exact raw
bytes and then append an `IngestionReceipt`. It must bind the normalized digest
to the same pure parser:

```python
from quant_trade.data.binance_symbol_rules import (
    BINANCE_EXCHANGE_INFO_ENDPOINT,
    BINANCE_SYMBOL_RULES_ADAPTER,
    BINANCE_SYMBOL_RULES_ADAPTER_VERSION,
    normalize_binance_spot_symbol_rules,
)
from quant_trade.evidence.canonical_json import sha256_of_bytes
from quant_trade.evidence.receipts import IngestionReceipt, normalized_rows_sha256

raw: bytes = exchange_info_response_body
rows = normalize_binance_spot_symbol_rules(raw)
receipt = IngestionReceipt(
    provider_or_venue="binance",
    endpoint=BINANCE_EXCHANGE_INFO_ENDPOINT,
    request_parameters={},
    http_status=200,
    captured_at_utc="2026-08-13T12:00:05Z",
    adapter_name=BINANCE_SYMBOL_RULES_ADAPTER,
    adapter_version=BINANCE_SYMBOL_RULES_ADAPTER_VERSION,
    raw_path=f"raw/{sha256_of_bytes(raw)}.json",
    raw_sha256=sha256_of_bytes(raw),
    normalized_rows_sha256=normalized_rows_sha256(rows),
    source_kind="live",  # declaration only; lookup still returns UNATTESTED_SOURCE
)
```

The collector must write the raw body before appending its receipt, keep
credentials out of request parameters, and label fixtures honestly. Even a
correctly labelled collector does not cross V2's authenticity boundary.

## Causal inspection

```python
from datetime import timedelta

from quant_trade.data.binance_symbol_rules import (
    SymbolRuleAvailability,
    load_binance_spot_symbol_rules_ledger,
)

ledger = load_binance_spot_symbol_rules_ledger("evidence/symbol_rules/receipts.jsonl")
result = ledger.lookup(
    "ABCUSDT",
    as_of_utc="2026-08-20T00:00:00Z",
    max_age=timedelta(hours=24),
)
assert result.availability is SymbolRuleAvailability.UNATTESTED_SOURCE
assert result.rule is None
```

The exact filters remain inspectable in `ledger.snapshots`, but using those
rows for promotion requires the future external attestation layer.

## Identity and unit boundary

`exchangeInfo` authenticates no CoinMarketCap identity. Lookup binds only:

- the exact canonical `venue_symbol` requested;
- the canonical UTC `as_of_utc` returned;
- the latest snapshot observation time selected under that cutoff.

It deliberately does not accept or emit `InstrumentId`; echoing a caller's
`CMC:<id>` would not prove the CMC-to-Binance mapping. XSMOM must join a
separately evidenced PIT symbol-identity ledger and reject mismatches.

Likewise, every notional is denominated in the quote asset `USDT`. No field is
named USD, and V2 provides no USDT-to-USD conversion. Populating an evaluator's
`min_notional_usd` requires separately attested PIT conversion evidence or a
sealed par policy; direct mapping is blocked by this interface.

## What this still cannot prove

Complete captured filters do not establish executability. In particular V2
does not model:

- a Friday bid/ask or order book;
- applicable account fees;
- percent-price, asset/account, open-order, or position limits;
- side-aware rounding or order type selection;
- latency, rejection, partial fills, cancellation, or reconciliation;
- stablecoin classification, CMC identity, listing/delisting history, market
  cap, or price availability.

Until those independent inputs and external source attestation are joined
causally, the maximum campaign verdict remains `INSUFFICIENT_EVIDENCE`. This
ledger does not authorize opening a historical holdout.

## Regression requirements

`tests/test_binance_symbol_rules.py` covers:

- self-labelled live evidence remaining unattested;
- public-constructor attempts to fabricate `AVAILABLE_REAL`, expose a rule, or
  inject authorization;
- strict `serverTime` monotonicity and the sealed capture/server skew;
- preservation and blocking of Spot-disabled rows;
- exact zero/disabled `MARKET_LOT_SIZE` semantics;
- complete `MIN_NOTIONAL` and `NOTIONAL` flags, max bound, and averaging
  windows;
- prefix invariance, no backdating, freshness, and no old-rule fallback;
- raw-byte, normalized-row, server-time, and receipt-chain tampering;
- duplicate/missing filters, invalid types, duplicate symbols, and replayed
  bytes.

Use a new evidence directory/version whenever acquisition policy or adapter
schema changes. Never rewrite a sealed receipt chain.
