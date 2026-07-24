# Statistical Integrity V2

This document describes the Phase-1 rigor upgrade: honest resampling, leak-free
splits, an auditable trial ledger, and a conservative promotion gate that
recomputes evidence instead of trusting stored flags. Everything here is
research-only and never authorizes real money.

## 1. Bootstrap confidence intervals (`quant_trade.research.bootstrap`)

The previous `simple_bootstrap_or_block_bootstrap` accepted a `block_size` and
then ignored it — it always did IID resampling, destroying serial dependence
and producing anti-conservative intervals for autocorrelated returns.

Replaced by three explicit, seeded APIs plus a CI wrapper:

| Function | Dependence handling | Use when |
| --- | --- | --- |
| `iid_bootstrap` | destroys autocorrelation | returns are ~independent |
| `moving_block_bootstrap` | fixed contiguous blocks (Kunsch), configurable circular `wrap` | serially correlated returns |
| `stationary_bootstrap` | geometric block lengths (Politis & Romano) | correlated, unknown block length |
| `bootstrap_confidence_intervals` | wraps any method into percentile bands | reporting/evidence |

Guarantees enforced by tests (`tests/test_bootstrap.py`):

- Explicit integer `seed` → byte-for-byte reproducibility; different seeds differ.
- `block_size` is actually applied (two block sizes give different draws);
  `block_size=1` reduces to IID.
- On a synthetic AR(1) series, block resamples retain lag-1 autocorrelation
  (~0.7) while IID collapses it (<0.15).
- Length preserved; NaN handling is explicit (`nan_policy="raise"` by default,
  `"drop"` opt-in); empty/short/inf inputs raise clear errors.
- **Per-period, never annualized** — no hardcoded `sqrt(252)`. Annualization is
  the caller's responsibility using the dataset's true frequency.

Statistics reported per resample: total return, mean, volatility, Sharpe, and
max drawdown. The multi-asset runner records a stationary-bootstrap CI for the
OOS returns in `results.json` under `bootstrap` (fail-closed: `available:false`
when the sample is too thin).

## 2. Purged, timestamp-based splits (`quant_trade.research.splits`)

The old splits cut at `int(len(df) * fraction)` on rows. On a long-form panel
two symbols sharing a timestamp could land on opposite sides of the cut, putting
the same bar in both train and test.

All splits now partition **unique timestamps**, so every symbol of a timestamp
moves together and train always ends before test. Single-asset behaviour is
unchanged (unique timestamps == rows).

- `chronological_train_test_split`, `walk_forward_splits` — backward-compatible
  signatures, now timestamp-based, `embargo_bars` counted in timestamps.
- `purged_chronological_split`, `purged_walk_forward_splits` — add López de
  Prado purging: `purge_bars` (the label/feature horizon) removes timestamps
  from the **end of train**; `embargo_bars` removes timestamps from the **start
  of test**. The returned `PurgedSplit` records exactly which timestamps were
  purged and embargoed and the effective train/test ranges.

Tests (`tests/test_purged_splits.py`) prove: no timestamp shared across
train/test on panels, symbols kept together at the boundary, exact purge/embargo
counts, label-horizon > embargo, irregular panels, and future-perturbation
causality (the train partition is invariant to changes in the test window).

## 3. Honest trial ledger (`quant_trade.research.ledger`)

Redesigned without deleting history. The v2 `TrialRecord` separates three
identities:

- **`hypothesis_id`** — deterministic over (strategy, params, dataset SHA, split
  policy, feature version). Re-tuning a knob is a *new* hypothesis, not a free
  re-roll.
- **`attempt_id`** — unique per execution.
- **`content_fingerprint`** — deterministic over (hypothesis, code SHA, dataset
  SHA, config SHA, seed). Identical fingerprints across attempts = a
  reproducible rerun; a different fingerprint means something material changed.

Each record also stores code/dataset/config SHA, seed, split policy, execution
policy hash, costs, and train/test ranges, and a `status` of `evaluated`,
`failed`, or `discarded`. Grid search now logs discarded (invalid) and failed
combinations too, so the search breadth is complete. Legacy flat rows remain
readable.

`ledger_integrity_report` never hides corruption: corrupt JSONL lines are
surfaced with line numbers and set `is_intact = False`. It counts hypotheses,
attempts, valid observations, failed and discarded trials, and reproducible
rerun groups.

### Deflated Sharpe: effective trial count

The deflated Sharpe needs the number of trials that were actually run. Policy:

- **One trial per recorded evaluation** with a usable per-period Sharpe
  (discarded rows excluded).
- **Assume independence** between trials (no correlation shrinkage). Correlated
  trials have a *smaller* effective count, which would *lower* the
  expected-max-Sharpe threshold; assuming independence keeps the threshold as
  high as the data supports — the conservative choice for an approval gate.
- When trial correlation cannot be estimated we use the full count rather than
  an unvalidated shrinkage estimator, and say so in the report notes.

## 4. Promotion V2 (`quant_trade.research.promotion_v2`)

`evaluate_promotion_v2` reopens `results.json` and the ledger and **recomputes**
PSR and DSR from the persisted return moments and the ledger's effective trial
count. Stored flags (e.g. a friendly `dsr` written into results) are ignored —
a test asserts a bogus stored flag cannot promote a weak run.

Config `configs/selection/conservative_v2.yaml` requires, all fail-closed:

- OOS Sharpe ≥ 0.5; strictly positive net excess return.
- Recomputed **PSR ≥ 0.95** and **DSR ≥ 0.95**.
- ≥ 60 OOS observations and ≥ 30 trades.
- Drawdown ≤ 20%, turnover ≤ 3.0.
- Cost-sensitivity pass and subperiod/regime stability.
- Block-bootstrap CI available with a positive lower bound.
- A realistic **execution policy specified** (unlimited-fill runs are not
  promotable), fill rate ≥ 90%, incomplete-order rate ≤ 10%.
- Dataset SHA recorded; ledger present and intact; human approval notes present.

The best attainable outcome is **`paper_candidate`**. The decision object always
carries `real_money_authorized = False`.

## Current verdict

The shipped synthetic and real-ETF strategies do not clear this gate: 0/5 base
strategies and 0/3 benchmark-aware allocations pass, equal-weight remains
unbeaten. That is the intended, honest result — the gate exists to keep
simulation optimism from being mistaken for demonstrated profitability.
