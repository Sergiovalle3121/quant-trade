# Carry Real-Data Pipeline

How real funding history is collected, audited, byte-bound, and consumed by the
cash-and-carry research campaign. Read-only end to end: no API keys, no order
methods, no daemons.

## 1. Collect (point-in-time)

```bash
quant-trade carry collect-once --config configs/carry/collector.example.yaml
```

One safe capture per invocation. Each observation records: spot bid/ask, perp
bid/ask/mark/index, the venue's published funding rate, next funding time (when
exposed), open interest (when public), the venue's own `exchange_timestamp_utc`
**separate from** the local `captured_at_utc`, the source name, and the SHA-256
of the preserved raw response. Adapters expose a single `observe` verb — a test
asserts no create/cancel/order/withdraw method exists.

Scheduling repeated captures (cron, systemd timer) is an explicit operator
choice. Nothing in this repo loops or daemonizes, and tests only run single
iterations against `tests/fixtures/carry_observations.json`.

## 2. Store (append-only, idempotent)

`data/carry/funding_history.jsonl` — one canonical-JSON record per line,
appended with flush+fsync. Re-running the collector never double-counts: the
dedup key is `(venue, symbol, exchange_timestamp_utc, source_event)`. Corrupt
lines are **quarantined with line numbers**, never silently dropped.

## 3. Audit

```bash
quant-trade carry dataset-audit --path data/carry/funding_history.jsonl
```

Reports records, venues/symbols/pairs, time range and span, funding events,
gaps beyond 1.5× the funding interval, duplicates, non-monotonic series,
invalid/naive timestamps, and quarantined lines. Exit code 1 when problems
exist — a dirty dataset does not feed research.

## 4. Bind and consume

A campaign consumes collected history via:

```yaml
data:
  source: jsonl_observations
  path: data/carry/funding_history.jsonl
```

Loading fails closed if any line is quarantined. The dataset manifest hashes
the JSONL file's **real bytes** (`evidence/manifest.py`), and that hash chains
into `results.json`, `dataset_manifest.json`, and the trial ledger — changing a
single byte of the dataset after the fact invalidates verification.

## Honesty rules

- One captured observation is one observation — never presented as "history".
- Bid/ask are preserved so spread costs can come from data, not assumptions.
- `data_source: "real"` is set by the bridge only for genuinely collected
  records; synthetic generators remain labelled synthetic and can never GO.
