# SPY turn-of-month development evaluator

Status: **IMPLEMENTED OFFLINE — REAL BUNDLE MISSING — INSUFFICIENT EVIDENCE**

`prospective_spy_tom_development.py` evaluates the single sealed
`SPY_TOM_Dm1_P3_v1` rule. It is a development-only falsifier, not a strategy
optimizer or promotion gate. It has no network client, API-key field, broker,
registry hook, order route, deposit path, or caller-provided performance
metric. Schema v1 can return only `INSUFFICIENT_EVIDENCE`: it has no external
trust root with which to authenticate an Alpaca response, so even an adverse
diagnostic cannot yet be called an authoritative campaign `NO_GO`.

The strategy spec seal consumed by this evaluator is:

```text
5d2c57f22a4437b3064a596b3dd804c7e1e683b3228d4a5d6901e73f1053c540
```

## Required local evidence bundle

The caller supplies a directory and an expected SHA-256 for `manifest.json`.
The evaluator verifies the digest but **cannot prove that it was independently
recorded**; a caller can fabricate a mutually consistent bundle and digest.
The manifest must itself be canonical JSON with
schema `alpaca_spy_sip_development_bundle_v2` and bind all of these exact
properties:

- provider `ALPACA`, feed `SIP`, symbol `SPY`, calendar `XNYS`;
- an aware request start, exact hard end/cutoff, and capture timestamp;
- `development_only=true`;
- relative paths and SHA-256 hashes for canonical `calendar`, `quotes`,
  `trades`, `corporate_actions`, `fees`, and `receipts` artifacts.

The evaluator checks the external manifest digest and canonical bytes, then
reads and rehashes **all six artifacts before parsing any of them**. Absolute,
escaping, duplicate, missing, or hash-mismatched paths fail closed. An updated
manifest supplied together with an unrecorded new digest is a different
dataset, not proof that old evidence remained unchanged.

Five canonical source-receipt records internally bind the raw calendar,
quotes, trades, corporate actions, and fee schedule. Receipts freeze the
provider/source kind, endpoint, SIP/SPY scope, request start/end, HTTP status,
capture time, raw path, and raw hash. These JSON records are evidence claims,
not verified Alpaca signatures. The fee receipt claims an official-document
capture; its normalized rows carry non-overlapping effective intervals and
source URLs. No fee is read from an account or accepted as a free caller
number.

No authentic bundle, expected manifest digest, or receipts are currently
present in the repository. Synthetic test fixtures exercise the contract but
are not market evidence.

Every report therefore fixes `external_data_authority_verified=false` and
`metrics_diagnostic_only=true`. A future schema would need an out-of-bundle
allowlisted trust root and provider-verifiable signature or equivalent
attestation before changing either field.

## Calendar and execution evidence

Every calendar row contains an aware Alpaca/XNYS open and close. Its dates and
hours must exactly equal the separately supplied `ExplicitExchangeCalendar`.
This binds holidays, DST, and 13:00 early closes. The prospective generator
excludes an entire primary/control pair if any required session closes before
15:58 ET; it cannot retain an entry while silently losing the exit.

For each remaining event, the exact permitted quote/trade interval is
inclusive 15:56:00–15:58:00 ET:

- at least one valid SIP quote and one SPY trade must exist inside the window;
- entries use the **highest ask** observed in the window;
- exits use the **lowest bid** observed in the window;
- midpoint, trade price, close, previous quote, next quote, and nearby session
  substitution are prohibited;
- primary D−1→P3 and control D8→D12 must both have all four matched events for
  the same adjacent-month pair.

Prices, sizes, dividends, split ratios, fees, years, and timezone-normalized
timestamps have explicit finite bounds. Extreme Decimal exponents, huge JSON
integers, unhashable schema shapes, and UTC underflow/overflow become
`INSUFFICIENT_EVIDENCE`; they cannot escape the public evaluator or reach the
economic calculation.

Each normalized episode starts with US$200. Total entry debit cannot exceed
US$195, preserving at least US$5 before the exit. Fractional long SPY is the
only position; there is no leverage or short sale.

## Fees, total return, and stress

The content-addressed fee schedule must cover every calendar date without
gaps or overlaps. Each interval explicitly declares commission, sell-side
regulatory bps, fixed regulatory cents, effective dates, and its official
source URL. Regulatory bps below the sealed positive floor are rejected.

Normal evaluation already pays the observed worst bid/ask and adds a sealed
1 bp adverse impact per side. Stress uses 5 bps per side and doubles every
declared commission/regulatory fee. Both scenarios recalculate quantity so
entry notional plus entry commission stays within US$195.

Price-only SPY accounting is forbidden. A content-addressed corporate-action
ledger and full-window receipt must cover cash dividends and splits. Each
record binds its announcement/revision vintage, which must precede the
effective session open. While a leg is held:

- a split changes quantity at the effective session open;
- a cash dividend is credited per then-current share at the ex-date open.

Missing dividend evidence, split-query coverage, vintage, receipt, or hash
produces `INSUFFICIENT_EVIDENCE` before performance is calculated.

## Recomputed report

At least 120 complete paired months are required. With fewer, the report has
no scenario metrics. For sufficient structurally valid development evidence,
the evaluator derives internally:

- primary and control mean monthly net returns;
- compounded total returns and maximum drawdowns;
- paired primary-minus-control excess;
- a deterministic year-cluster bootstrap with seed `20260814` and 2,000
  repetitions;
- fee totals and a SHA-256 of every conservative fill selection.

No return, fill, drawdown, confidence interval, verdict, or fee number can be
provided in the manifest. Unknown manifest fields—including caller metrics—are
rejected. The final report is canonical and exposes `report_sha256()`.

Adverse comparisons are labelled diagnostic but still return
`INSUFFICIENT_EVIDENCE`; they cannot authoritatively falsify the campaign while
the bundle is self-attested. A favourable historical comparison also returns
`INSUFFICIENT_EVIDENCE`, because every historical observation is development
data and `PASS` is structurally impossible. Paper profit cannot authorize
promotion, live execution, real money, or a bank transfer.

## API

```python
evaluate_spy_tom_development(
    bundle_root: str | Path,
    spec: SpyTomSpec,
    calendar: ExplicitExchangeCalendar,
    *,
    expected_manifest_sha256: str,
    development_cutoff: datetime,
    as_of: datetime,
) -> SpyTomDevelopmentVerdict
```

All evidence inputs are local and explicit. A missing bundle is a normal
blocked state, not permission to download data or weaken the contract.
