Exit code: 0
Wall time: 0.9 seconds
Output:
# Cloud-first crypto-mining economics

This module evaluates whether an explicitly authorized mining worker has a
positive expected **net** profit. It does not download a miner, launch EC2,
join a pool, handle wallets, or start a process. Every report keeps
`authorized_to_start_miner=false`.

## What is included

- owned-hardware and AWS hourly-cost economics;
- pool fee, electricity, operating cost, and hardware depreciation;
- price haircut and network-difficulty growth stress;
- temperature telemetry and maximum cloud-hourly-cost gates;
- break-even electricity, hardware ROI, and payback diagnostics;
- local JSON output and optional S3 publication through the existing AWS
  storage adapter;
- deterministic tests with no network or AWS credentials.

AWS electricity must not be counted twice. For an EC2 worker set
`electricity_included: true`, record the current effective instance price in
`infrastructure_hourly_cost_usd`, and include EBS/data/monitoring charges in
`daily_operating_cost_usd`. Prices are region, instance, operating-system, and
purchase-model dependent; the repository deliberately does not hardcode them.

## Run an evaluation

```bash
quant-trade mining evaluate \
  --config configs/mining/aws_profitability_example.yaml \
  --output outputs/mining/profitability_report.json
```

Publish the same report to AWS:

```bash
quant-trade mining evaluate \
  --config configs/mining/aws_profitability_example.yaml \
  --artifact-uri s3://YOUR-BUCKET/mining/profitability_report.json
```

The S3 path uses the existing `quant_trade.cloud.storage` adapter and therefore
requires the `cloud` optional dependency and normal AWS credential resolution.
Do not commit credentials.

## Intended AWS cascade

1. GitHub Actions runs Ruff, mypy, compileall, and pytest.
2. A reviewed image is pushed to ECR.
3. A lightweight scheduled evaluator runs before any compute worker.
4. Inputs and reports are versioned in S3; CloudWatch receives decision/cost
   metrics; DynamoDB prevents overlapping runs.
5. Only a current `GO` may make a separate, explicitly approved worker eligible
   to start. A `NO-GO`, stale snapshot, missing temperature, budget breach, or
   kill switch keeps desired capacity at zero.
6. AWS Budgets/SNS and CloudWatch alarms provide independent cost and shutdown
   controls. If Auto Scaling is used, stopping one instance is insufficient
   because the group may replace it; the shutdown path must also set desired
   capacity to zero or deny new launches.

## Model risk

Expected blocks are probabilistic. Pool payout rules, rejected shares,
staleness, latency, Spot interruption, taxes, exchange fees, withdrawal costs,
hardware failure, EBS, public IPv4, and data-transfer charges can reduce
profitability. A `GO` is an eligibility result from supplied assumptions, not a
profit guarantee. Refresh snapshots and AWS prices before every run and prefer
a conservative `NO-GO` whenever inputs are stale or unverifiable.

The software must only run on infrastructure owned or explicitly authorized by
the operator. It contains no stealth, persistence, propagation, credential
collection, or resource-hijacking behavior.

