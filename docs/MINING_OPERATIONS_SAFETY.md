# Mining operations safety boundary

This release is evaluation-only. It cannot launch, download, supervise, or
restart mining software; provision cloud compute; join a pool; control physical
hardware; or sign a wallet transaction.

## Invariants

- Every report sets `authorized_to_start_miner=false`.
- Every report sets `cloud_resources_created=false`.
- Tests use local files and deterministic values; they require no network,
  broker, exchange, pool, or AWS credentials.
- A `GO` means only that the supplied assumptions passed configured economic
  gates. It is not permission to start infrastructure.
- Missing temperature, excess temperature, excess cloud hourly cost, negative
  stressed profit, inadequate margin/profit, or non-positive required NPV
  produces `NO-GO`.
- Missing, placeholder, future-dated, or stale market evidence produces
  `NO-GO`; every snapshot is fingerprinted in the report.
- Wallet support, if added later, must be watch-only in the evaluator. Private
  keys, seed phrases, and signing belong outside this repository.

## Required controls before any future execution

Any execution phase remains `NO-GO` until it has all of the following under
separate review:

- documented ownership/authorization for every worker;
- immutable image provenance and vulnerability scanning;
- least-privilege IAM and no instance role capable of privilege expansion;
- independently enforced AWS budget, quota, and desired-capacity ceilings;
- fresh attributable market, network, tariff, FX, and cloud-price inputs;
- temperature/power telemetry with fail-closed freshness checks;
- idempotent start/stop commands and a tested kill switch that prevents
  replacement instances;
- secrets in a managed secret store and watch-only payout observability;
- reconciliation of pool payouts, exchange fees, taxes, and all cloud charges;
- an operator approval trail and incident runbook.

The present code deliberately stops before that control boundary.

