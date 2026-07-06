# Statistical validation of research results

Backtest point estimates are not evidence: search enough parameters and
something always looks spectacular in-sample. This layer quantifies how much
of an observed Sharpe survives track-record length, non-normal returns, and —
critically — the number of things that were tried.

## Components

### Trial ledger (`outputs/trial_ledger.jsonl`)

Every backtest evaluation appends one line: each `research run`, every
grid-search parameter combination, every walk-forward window. The ledger is
append-only and records the per-period test Sharpe of each trial. Deleting or
omitting it disables the deflated-Sharpe gate (selection then rejects
candidates when `require_deflated_sharpe` is on), so the honest default is to
let it grow.

### Probabilistic Sharpe Ratio (PSR)

`quant_trade.metrics.statistics.probabilistic_sharpe_ratio` — the probability
that the true Sharpe exceeds a benchmark given the observed track record,
adjusted for skewness and kurtosis (Bailey & López de Prado). Every research
run stores its test PSR and the return moments needed to recompute it in
`results.json`.

### Deflated Sharpe Ratio (DSR)

`deflated_sharpe_ratio` — PSR measured against the Sharpe you would expect
from the *best of N unskilled trials*, where N and the cross-trial variance
come from the trial ledger. This is the multiple-testing correction: a 1.2
Sharpe found after 5 trials is evidence; the same Sharpe found after 500
trials is noise.

### Minimum track record length

`minimum_track_record_length` — how many observations are needed before a
Sharpe estimate is statistically distinguishable from a benchmark at a given
confidence. Useful for sizing paper-trial durations.

## Selection gates

`SelectionCriteria` gained four fields (all disabled by default for
compatibility; `configs/selection/conservative_daily.yaml` enables them):

| Field                      | Meaning                                            |
| -------------------------- | -------------------------------------------------- |
| `min_trade_count`          | Reject runs with too few test trades (default cfg: 30) |
| `min_probabilistic_sharpe` | Reject runs whose test PSR is below the bar (0.90) |
| `require_deflated_sharpe`  | Compute DSR from the trial ledger and gate on it   |
| `min_deflated_sharpe`      | DSR threshold (0.5 = better than a coin flip after deflation) |

## Embargo

`split.embargo_bars` drops N bars at the train/test boundary (chronological
and walk-forward splits) so rolling lookbacks cannot leak train information
into out-of-sample evidence. Set it to the longest signal lookback — the
flagship crypto config uses 252.

## Honest usage

- Do not reset the ledger between search sessions on the same dataset.
- Robustness flags in `results.json` are computed, not asserted:
  `cost_sensitivity_pass` = still profitable at the highest cost level;
  `subperiod_pass` = at least half of calendar years positive.
- None of this proves future profitability; it bounds how much of the past
  was luck.
