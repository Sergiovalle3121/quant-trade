# Quant Research Auditor MVP

`quant-trade audit` is a local, bring-your-own-data research audit. It gives a
potential customer a reproducible answer to a narrower question than “will this
strategy make money?”: are the supplied research claims bound to identifiable
bytes, causally plausible, cost-aware, benchmarked, and declared in a trial
ledger?

It does not connect to an exchange, fetch data, import or execute customer
Python, evaluate formulas, submit orders, or authorize real-money trading.
Every verdict includes `real_money_authorized=false`.

## Build a package from your own results

`audit init` writes the four package files next to a dataset you already have,
with both SHA-256 digests already computed:

```powershell
quant-trade audit init --package-dir .\my-research --evaluation-cutoff-utc "2024-12-31T23:59:59Z"
```

Hashing your own bytes by hand and pasting the digest into two files is the step
most likely to be got wrong, and a wrong digest is indistinguishable from results
that were never bound to the data — so a clerical slip reads as a defect. `init`
does that part for you. Everything only you can know is left as an explicit
`FILL_ME`, which the auditor refuses, so an unedited template can never pass.
Existing files are never overwritten.

## Run the examples

After the root CLI registers `quant_trade.audit.cli.audit_app` as `audit`:

```powershell
quant-trade audit run --config configs/audit/clean.yaml --out-dir artifacts/audit-clean
quant-trade audit run --config configs/audit/contaminated.yaml --out-dir artifacts/audit-bad
```

Sample outputs from both are committed under `artifacts/audit-sample/`, so a
report can be read without running anything.

`--redact` replaces absolute paths with file names, so a delivered report does
not disclose either party's directory layout. The bundle stays verifiable from
its own bytes; only the digest differs from an unredacted run of the same inputs.

The command exits `0` on `PASS`, `1` on `INSUFFICIENT_EVIDENCE`, and `2` on
`NO_GO`, so a pipeline can gate on the verdict instead of parsing the report.

## Verify a delivered report

```powershell
quant-trade audit verify --bundle .\artifacts\audit-clean\audit.json
```

Recomputes `bundle_digest` from the file's own bytes. It needs no access to the
original inputs and no trust in whoever sent the file: a content address nobody
else can check is decoration. Exits `2` on a mismatch.

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

`root_dir` must also resolve **inside the directory holding the config**: a
config may narrow its trust root but never widen it. Put the config in or above
your package directory, as `audit init` does.

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
symbol_column: symbol
required_columns: [timestamp, symbol, open, high, low, close, volume]
max_file_size_bytes: 1000000
```

Row ordering is checked **within each instrument**, named by `symbol_column`. A
panel exported as `(symbol, timestamp)` — the shape almost every real research
package has — is causal and passes; a timestamp moving backwards inside one
instrument still fails. When `symbol_column` names no column present in every
row, the whole file must be globally ascending instead.

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

### Defect versus result

Every check also carries a `finding_class`:

- `DEFECT` — an error in **how** the result was produced: look-ahead columns,
  unbound bytes, same-bar execution, undeclared costs, a broken trial ledger.
- `RESULT` — a correctly measured property of the result **itself**. Today only
  `NET_BENCHMARK_RESULT` is in this class: not beating your benchmark is an
  outcome, not a flaw in your method.

This changes no verdict — a blocking check blocks either way — and exists so a
customer is not told their research is broken when what actually happened is
that their strategy lost to buy-and-hold. Whether `RESULT` findings *should*
block is a product decision that has not been made; it is recorded here rather
than silently resolved.

### What "audit" does and does not mean here

Costs, benchmarks, `strategy_net_return`, and `signal_lag_bars` are declared by
the customer in `results.json`; none of them is recomputed from the dataset. The
honest claim is that a package is **internally consistent and byte-bound**, not
that its numbers were independently reproduced. Say this to a customer before
they infer the stronger claim from the word "audit".
