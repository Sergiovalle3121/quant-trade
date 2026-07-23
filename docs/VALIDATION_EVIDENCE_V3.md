# Validation evidence V3

This phase strengthens rejection rules. It does not claim or guarantee that a
strategy or mining project will make money.

## Trading: train-winner OOS rank

Multi-asset walk-forward now evaluates every configured parameter variant on
each train window and its corresponding embargoed OOS window. Parameters are
still selected using train data only. The other OOS results are used solely to
measure how often that train-time winner retains its rank; they are never used
to replace the selected parameters.

For each window, the report records:

- the selected parameters and train score;
- the selected variant's OOS score;
- train-to-test score degradation;
- the selected variant's percentile rank among all variants OOS; and
- every variant evaluation in the append-only trial ledger.

`walk_forward_pbo` is the fraction of windows where the train winner ranks at
or below the OOS median. This is an empirical rolling walk-forward estimate,
not the combinatorially symmetric cross-validation PBO estimator. The artifact
therefore names its method explicitly: `rolling_train_winner_oos_rank`.

The result is `NO-GO` when there are fewer than two parameter variants, fewer
than the configured minimum windows, or PBO exceeds the configured maximum.
The default validation policy requires four windows and PBO no greater than
0.50. These are rejection thresholds, not optimization targets.

The command writes `overfitting_evidence.json`. A normal research run may bind
that artifact through `overfitting_evidence_path`; the dataset SHA-256 and
strategy must match or the run fails. Conservative selection requires the
bound evidence, and simulated-paper promotion can independently require it.

## Mining: point-in-time evidence

Mining profitability now treats market and network inputs as point-in-time
evidence. By default, a decision is `NO-GO` when:

- `source` is empty or contains a placeholder/manual marker;
- `captured_at_utc` is missing, invalid, or lacks a timezone;
- the snapshot is older than `max_market_snapshot_age_hours`; or
- the timestamp is in the future beyond `max_future_clock_skew_minutes`.

Each evaluation includes source, capture time, age, evaluation time, and a
SHA-256 fingerprint over the complete market snapshot. CLI commands accept
`--as-of-utc` so historical decisions and tests can use an explicit,
reproducible clock. Cloud jobs capture one evaluation time and reuse it across
all compatible rig/market pairs.

Fresh data can still be wrong, manipulated, or economically incomplete.
Fresher inputs do not override stress, NPV, thermal, cloud-cost, margin, or
profit gates. A mining `GO` remains evaluation-only:
`authorized_to_start_miner=false` and `cloud_resources_created=false`.

## Honest limitations

- OOS rank evidence reduces one form of parameter-selection overfitting; it
  does not eliminate regime risk, survivorship bias, data errors, or future
  execution slippage.
- Evaluating all variants OOS is itself research evidence that must remain in
  the ledger. Repeated redesign after viewing it increases the trial count and
  must not be hidden.
- Mining snapshot provenance is asserted by configuration, not cryptographically
  attested by an upstream provider. A future ingestion layer should sign or
  otherwise bind raw provider responses before autonomous operations.
- Neither subsystem is authorized for live capital or automatic infrastructure
  execution.
