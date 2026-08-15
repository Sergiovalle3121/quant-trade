# Quant Research Auditor MVP

`quant-trade audit` is a local, bring-your-own-data research audit. It gives a
potential customer a reproducible answer to a narrower question than “will this
strategy make money?”: are the supplied research claims bound to identifiable
bytes, causally plausible, cost-aware, benchmarked, and declared in a trial
ledger?

It does not connect to an exchange, fetch data, import or execute customer
Python, evaluate formulas, submit orders, or authorize real-money trading.
Every verdict includes `real_money_authorized=false`.

## Run the examples

After the root CLI registers `quant_trade.audit.cli.audit_app` as `audit`:

```powershell
quant-trade audit run --config configs/audit/clean.yaml --out-dir artifacts/audit-clean
quant-trade audit run --config configs/audit/contaminated.yaml --out-dir artifacts/audit-bad
```

The clean package demonstrates the input contract. The contaminated package
deliberately includes a future-return column, future/availability timestamps,
same-bar execution, an unapplied cost model, a mismatched manifest/results
hash, duplicate trial IDs, and benchmark underperformance. It must produce
`NO_GO`.

Each output directory receives:

- `audit.json`: canonical JSON with a semantic `bundle_digest`;
- `audit.html`: a standalone report whose dynamic text is HTML-escaped.

Existing output files are never overwritten. Choose a fresh directory for a
new run. The report contains no external scripts, images, fonts, or network
resources.

## Input contract

The YAML configuration itself is limited to 1 MB and declares a contained
`root_dir`. Every referenced path must resolve inside that root, including
through symlinks. Evidence files default to a 25 MB limit and cannot exceed the
hard 100 MB ceiling.

Datasets may be UTF-8 `.csv`, `.json`, or `.jsonl`. Manifests, results, and
trial ledgers are deliberately strict JSON only; JSONL ledgers are not accepted
in v1. JSON is parsed as data and is never executed. Timestamps must carry an
explicit timezone offset.

```yaml
root_dir: fixtures/clean
dataset_path: dataset.csv
results_path: results.json
manifest_path: dataset.manifest.json
trial_ledger_path: trial_ledger.json
evaluation_cutoff_utc: "2024-12-31T23:59:59Z"
timestamp_column: timestamp
required_columns: [timestamp, symbol, open, high, low, close, volume]
max_file_size_bytes: 1000000
```

The results object should declare:

- `dataset_sha256`, calculated from the dataset's exact bytes;
- `trial_ledger_sha256`, calculated from the ledger's exact bytes;
- `execution.signal_lag_bars` of at least one;
- applied fee/slippage or total costs;
- `strategy_net_return` and one or more net benchmark returns.

When provided, the dataset manifest is checked for byte hash, byte size, source,
capture time, and a usage-rights or provenance note. Missing optional evidence
does not pass silently: it yields `INSUFFICIENT_EVIDENCE`.

## Verdict semantics

- `PASS`: every declared MVP check passed. This means evidence completeness,
  not expected future profit and never live-trading approval.
- `NO_GO`: at least one blocking contradiction or causal/economic failure was
  detected.
- `INSUFFICIENT_EVIDENCE`: no blocking contradiction was detected, but at least
  one required decision input is missing.

`NO_GO` dominates missing evidence. A future version can add deeper statistical
checks (DSR, PSR, PBO, walk-forward independence, concentration and capacity),
but those claims are intentionally outside this MVP rather than represented as
already audited.
