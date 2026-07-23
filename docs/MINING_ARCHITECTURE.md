# Mining subsystem architecture

The mining package is an isolated, offline decision-support subsystem. It does
not share order, broker, wallet, or execution interfaces with the trading
system.

## Data flow

1. A versioned YAML file supplies rig, facility, market/network, and policy
   assumptions.
2. `config.py` parses those values into validated immutable dataclasses.
3. `profitability.py` computes one deterministic economic evaluation per
   compatible rig/algorithm pair.
4. `scenarios.py` applies a fixed matrix of explicit multipliers and evaluates
   each transformed snapshot.
5. `cli.py` writes JSON reports locally and may publish only the evaluation
   report through the existing S3 storage adapter.
6. The cloud `mining_evaluation` job writes an immutable artifact and
   observability metrics while keeping miner authorization false.

The dependency direction stops at reports:

```text
YAML -> validated models -> economics/scenarios -> JSON/S3 artifact
                                                  |
                                                  +-> no miner process
                                                  +-> no wallet signing
                                                  +-> no AWS provisioning
```

## Trust boundaries

- Market values are caller-supplied point-in-time observations. The package
  makes no external requests and cannot silently substitute current prices.
- `source` and `captured_at_utc` are provenance fields, not proof that a value
  is fresh. Operational automation must reject stale/unattributable snapshots
  before a future eligibility step is considered.
- USD/MXN conversion is informational and configurable. It is never fetched or
  used to hide an uneconomic USD result.
- Cloud publication uses normal AWS credential resolution; credentials must
  never appear in YAML, reports, logs, or source control.

## Separation from a future control plane

A future control plane would require its own reviewed package, IAM boundary,
budget alarms, operator authorization, idempotency, and independent kill
switch. This repository currently provides no interface that can start a
miner. `authorized_to_start_miner` and `cloud_resources_created` remain
hard-coded safety facts set to `false` in every report.

