# CLOUD RUNBOOK

Phase 7 supports AWS cloud deployment for PAPER workflows only. No live trading, live endpoints, real-money execution, secrets, or broker auto-submit defaults are included.

- Build locally: `docker build -t quant-trade:paper .`.
- Run health: `quant-trade cloud run-job --config configs/cloud/local_dry_run.yaml --job health_check`.
- Default mode is dry-run/local storage.
- Store Alpaca Paper credentials in environment variables locally or AWS Secrets Manager in AWS; never commit values.
- EventBridge Scheduler can run ECS tasks; inspect CloudWatch Logs and S3 artifacts under the configured prefix.
- Activate the kill switch with `quant-trade cloud kill-switch activate --config configs/cloud/local_dry_run.yaml --reason "manual safety"`.
- Pause schedules in EventBridge, rollback to a prior image tag, rotate leaked secrets immediately, and review any wrong paper orders before re-enabling submission.
- Control costs with schedule frequency, log retention, Fargate CPU/memory, S3 lifecycle rules, and DynamoDB on-demand locks.


## Phase 8 operations safety

- Operations code must never call broker/network in tests.
- Never expose secrets in dashboard/alerts/incidents.
- New alert categories need tests.
- New readiness criteria need docs.
- Retention deletes require explicit confirmation.
- No command may imply real-money readiness.
